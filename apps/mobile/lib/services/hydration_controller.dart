import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api_client.dart';
import 'hydration_models.dart';

abstract interface class PendingHydrationStore {
  Future<HydrationEntry?> read(String ownerId);
  Future<void> write(String ownerId, HydrationEntry entry);
  Future<void> clear(String ownerId);
}

class SecurePendingHydrationStore implements PendingHydrationStore {
  const SecurePendingHydrationStore();
  static const _storage = FlutterSecureStorage();
  String _key(String ownerId) => 'nutrilens_hydration_pending_v1_$ownerId';

  @override
  Future<HydrationEntry?> read(String ownerId) async {
    final raw = await _storage.read(key: _key(ownerId));
    if (raw == null) return null;
    return HydrationEntry.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  @override
  Future<void> write(String ownerId, HydrationEntry entry) =>
      _storage.write(key: _key(ownerId), value: jsonEncode(entry.toJson()));

  @override
  Future<void> clear(String ownerId) => _storage.delete(key: _key(ownerId));
}

/// One instance per signed-in owner, shared by Today and the water screen.
/// A pending add is stored before transport; every retry reuses its identity.
class HydrationController extends ChangeNotifier {
  HydrationController({
    required this.gateway,
    required this.ownerId,
    required this.currentOwnerId,
    this.store = const SecurePendingHydrationStore(),
    DateTime Function()? now,
  }) : now = now ?? DateTime.now {
    selectedDay = this.now();
  }

  final HydrationGateway gateway;
  final String ownerId;
  final String? Function() currentOwnerId;
  final PendingHydrationStore store;
  final DateTime Function() now;
  late DateTime selectedDay;
  HydrationSummary? summary;
  HydrationSummary? todaySummary;
  HydrationEntry? pendingAdd;
  String? error;
  bool loading = false;
  bool saving = false;
  bool _initialized = false;
  bool _valid = true;
  bool _disposed = false;
  int _revision = 0;

  bool get active => _valid && !_disposed && currentOwnerId() == ownerId;
  bool get canMutate =>
      active && _initialized && !loading && !saving && pendingAdd == null;

  void _emit() {
    if (!_disposed) notifyListeners();
  }

  void invalidate() {
    _valid = false;
    _revision++;
    summary = null;
    todaySummary = null;
    pendingAdd = null;
    error = null;
    _emit();
  }

  Future<void> initialize() async {
    if (!active || _initialized || loading) return;
    loading = true;
    _emit();
    try {
      final pending = await store.read(ownerId);
      if (!active) return;
      pendingAdd = pending;
      _initialized = true;
    } on Object {
      if (active) error = 'Could not recover pending water entries. Try again.';
    } finally {
      loading = false;
      _emit();
    }
    if (_initialized && active) await refresh();
  }

  Future<void> refresh() async {
    if (!active || saving) return;
    if (!_initialized) return initialize();
    final revision = ++_revision;
    final day = selectedDay;
    loading = true;
    error = null;
    _emit();
    try {
      final value = await gateway.hydration(day: day);
      if (!active || revision != _revision) return;
      summary = value;
      if (hydrationDay(day) == hydrationDay(now())) {
        todaySummary = value;
      } else {
        final today = await gateway.hydration(day: now());
        if (!active || revision != _revision) return;
        todaySummary = today;
      }
    } on Object catch (failure) {
      if (active && revision == _revision) error = failure.toString();
    } finally {
      if (active && revision == _revision) {
        loading = false;
        _emit();
      }
    }
  }

  Future<void> selectDay(DateTime day) async {
    if (!active || saving) return;
    selectedDay = day;
    summary = null;
    await refresh();
  }

  Future<void> add(int amountMl) async {
    if (!canMutate || amountMl < 1 || amountMl > 5000) return;
    final instant = now();
    final consumed = hydrationDay(selectedDay) == hydrationDay(instant)
        ? instant
        : DateTime(
            selectedDay.year,
            selectedDay.month,
            selectedDay.day,
            instant.hour,
            instant.minute,
            instant.second,
          );
    pendingAdd = HydrationEntry(
      id: _uuidV4(),
      amountMl: amountMl,
      consumedAt: consumed.toUtc(),
    );
    await retryAdd();
  }

  Future<void> retryAdd() async {
    final entry = pendingAdd;
    if (!active || saving || entry == null) return;
    saving = true;
    _revision++;
    error = null;
    _emit();
    String? rejection;
    try {
      await store.write(ownerId, entry);
      if (!active) return;
      await gateway.addHydration(entry);
      if (!active) return;
      await store.clear(ownerId);
      if (active) pendingAdd = null;
    } on Object catch (failure) {
      // A conflict means the original identity was changed or deleted. Never
      // replace it with a fresh identity to work around the server's tombstone.
      // Network, 429 and 5xx responses keep the same pending payload.
      if (active &&
          failure is ApiException &&
          (failure.statusCode == 422 || failure.statusCode == 409)) {
        rejection = failure.statusCode == 409
            ? 'This addition was changed or deleted. Refresh your water log.'
            : failure.toString();
        try {
          await store.clear(ownerId);
          if (active) pendingAdd = null;
        } on Object {
          // Preserve the pending identity if its durable cleanup failed.
        }
      }
      if (active) error = rejection ?? failure.toString();
    } finally {
      saving = false;
      _emit();
    }
    if (active && pendingAdd == null) {
      await refresh();
      if (active && rejection != null) {
        error = rejection;
        _emit();
      }
    }
  }

  Future<void> saveTarget(int? targetMl) async {
    if (targetMl != null && (targetMl < 100 || targetMl > 10000)) return;
    await _change(() => gateway.saveHydrationTarget(targetMl));
  }

  Future<void> edit(HydrationEntry entry, int amountMl) async {
    if (amountMl < 1 || amountMl > 5000) return;
    await _change(
      () => gateway.updateHydration(
        HydrationEntry(
          id: entry.id,
          amountMl: amountMl,
          consumedAt: entry.consumedAt,
        ),
      ),
    );
  }

  Future<void> delete(String id) => _change(() async {
    try {
      await gateway.deleteHydration(id);
    } on ApiException catch (failure) {
      // A repeated delete may follow a committed operation with a lost reply.
      if (failure.statusCode != 404) rethrow;
    }
    return null;
  });

  Future<void> _change(Future<Object?> Function() action) async {
    if (!canMutate) return;
    saving = true;
    error = null;
    _revision++;
    _emit();
    try {
      await action();
    } on Object catch (failure) {
      if (active) error = failure.toString();
    } finally {
      saving = false;
      _emit();
    }
    if (active && error == null) await refresh();
  }

  @override
  void dispose() {
    _disposed = true;
    _revision++;
    super.dispose();
  }
}

String _uuidV4() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes
      .map((byte) => byte.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}
