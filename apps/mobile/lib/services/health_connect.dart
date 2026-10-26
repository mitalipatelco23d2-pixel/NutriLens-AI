import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:health/health.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum HealthConnectAvailability {
  available,
  installRequired,
  unavailable,
  unsupported,
}

enum HealthConnectRecordKind { water, weight }

class HealthConnectRecord {
  const HealthConnectRecord({
    required this.kind,
    required this.value,
    required this.recordedAt,
    required this.sourceName,
  });

  final HealthConnectRecordKind kind;
  final double value;
  final DateTime recordedAt;
  final String sourceName;
}

class HealthConnectReadAccess {
  const HealthConnectReadAccess({required this.water, required this.weight});

  static const none = HealthConnectReadAccess(water: false, weight: false);

  final bool water;
  final bool weight;

  bool get any => water || weight;
  bool get all => water && weight;

  Set<HealthConnectRecordKind> get permittedKinds => {
    if (water) HealthConnectRecordKind.water,
    if (weight) HealthConnectRecordKind.weight,
  };
}

abstract interface class HealthConnectGateway {
  Future<HealthConnectAvailability> availability();
  Future<HealthConnectReadAccess> readAccess();
  Future<HealthConnectReadAccess> requestReadAccess();
  Future<List<HealthConnectRecord>> read({
    required DateTime start,
    required DateTime end,
    required Set<HealthConnectRecordKind> kinds,
  });
  Future<void> revokeAccess();
  Future<void> openInstallFlow();
}

class PlatformHealthConnectGateway implements HealthConnectGateway {
  PlatformHealthConnectGateway({Health? health}) : _health = health ?? Health();

  static const _types = [HealthDataType.WATER, HealthDataType.WEIGHT];
  static const _permissions = [HealthDataAccess.READ, HealthDataAccess.READ];

  final Health _health;
  Future<void>? _configuration;

  bool get _supported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  Future<void> _configure() => _configuration ??= _health.configure();

  @override
  Future<HealthConnectAvailability> availability() async {
    if (!_supported) return HealthConnectAvailability.unsupported;
    await _configure();
    final status = await _health.getHealthConnectSdkStatus();
    return switch (status) {
      HealthConnectSdkStatus.sdkAvailable =>
        HealthConnectAvailability.available,
      HealthConnectSdkStatus.sdkUnavailableProviderUpdateRequired =>
        HealthConnectAvailability.installRequired,
      HealthConnectSdkStatus.sdkUnavailable ||
      null => HealthConnectAvailability.unavailable,
    };
  }

  @override
  Future<HealthConnectReadAccess> readAccess() async {
    if (await availability() != HealthConnectAvailability.available) {
      return HealthConnectReadAccess.none;
    }
    final results = await Future.wait([
      _health.hasPermissions(
        const [HealthDataType.WATER],
        permissions: const [HealthDataAccess.READ],
      ),
      _health.hasPermissions(
        const [HealthDataType.WEIGHT],
        permissions: const [HealthDataAccess.READ],
      ),
    ]);
    return HealthConnectReadAccess(
      water: results[0] == true,
      weight: results[1] == true,
    );
  }

  @override
  Future<HealthConnectReadAccess> requestReadAccess() async {
    if (await availability() != HealthConnectAvailability.available) {
      return HealthConnectReadAccess.none;
    }
    await _health.requestAuthorization(_types, permissions: _permissions);
    return readAccess();
  }

  @override
  Future<List<HealthConnectRecord>> read({
    required DateTime start,
    required DateTime end,
    required Set<HealthConnectRecordKind> kinds,
  }) async {
    if (await availability() != HealthConnectAvailability.available) {
      return const [];
    }
    final types = [
      if (kinds.contains(HealthConnectRecordKind.water)) HealthDataType.WATER,
      if (kinds.contains(HealthConnectRecordKind.weight)) HealthDataType.WEIGHT,
    ];
    if (types.isEmpty) return const [];
    final points = await _health.getHealthDataFromTypes(
      types: types,
      startTime: start,
      endTime: end,
    );
    final records = <HealthConnectRecord>[];
    for (final point in points) {
      final value = point.value;
      if (value is! NumericHealthValue) continue;
      final numeric = value.numericValue.toDouble();
      if (!numeric.isFinite || numeric < 0) continue;
      final kind = switch (point.type) {
        HealthDataType.WATER => HealthConnectRecordKind.water,
        HealthDataType.WEIGHT => HealthConnectRecordKind.weight,
        _ => null,
      };
      if (kind == null) continue;
      records.add(
        HealthConnectRecord(
          kind: kind,
          value: numeric,
          recordedAt: point.dateFrom.toLocal(),
          sourceName: _boundedLabel(point.sourceName),
        ),
      );
    }
    return records;
  }

  @override
  Future<void> revokeAccess() async {
    if (_supported) await _health.revokePermissions();
  }

  @override
  Future<void> openInstallFlow() async {
    if (_supported) await _health.installHealthConnect();
  }
}

abstract interface class HealthConnectPreferenceStore {
  Future<bool> loadSyncEnabled(String ownerId);
  Future<void> saveSyncEnabled(String ownerId, bool enabled);
}

class SharedPreferencesHealthConnectStore
    implements HealthConnectPreferenceStore {
  SharedPreferencesHealthConnectStore({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();

  final SharedPreferencesAsync _preferences;

  String _key(String ownerId) =>
      'nutrilens.health-connect.v1.${base64Url.encode(utf8.encode(ownerId))}';

  @override
  Future<bool> loadSyncEnabled(String ownerId) async =>
      await _preferences.getBool(_key(ownerId)) ?? false;

  @override
  Future<void> saveSyncEnabled(String ownerId, bool enabled) =>
      _preferences.setBool(_key(ownerId), enabled);
}

class HealthConnectInitialState {
  const HealthConnectInitialState({
    required this.availability,
    required this.syncEnabled,
  });

  final HealthConnectAvailability availability;
  final bool syncEnabled;
}

class HealthConnectSnapshot {
  const HealthConnectSnapshot({
    required this.fetchedAt,
    required this.waterRecordCount,
    required this.weightRecordCount,
    required this.sourceNames,
    required this.access,
    this.waterTodayLiters,
    this.latestWeightKg,
    this.latestWeightAt,
  });

  final DateTime fetchedAt;
  final double? waterTodayLiters;
  final double? latestWeightKg;
  final DateTime? latestWeightAt;
  final int waterRecordCount;
  final int weightRecordCount;
  final List<String> sourceNames;
  final HealthConnectReadAccess access;
}

class HealthConnectCoordinator {
  HealthConnectCoordinator({
    HealthConnectGateway? gateway,
    HealthConnectPreferenceStore? store,
    DateTime Function()? now,
  }) : _gateway = gateway ?? PlatformHealthConnectGateway(),
       _store = store ?? SharedPreferencesHealthConnectStore(),
       _now = now ?? DateTime.now;

  final HealthConnectGateway _gateway;
  final HealthConnectPreferenceStore _store;
  final DateTime Function() _now;

  Future<HealthConnectInitialState> load(String ownerId) async =>
      HealthConnectInitialState(
        availability: await _gateway.availability(),
        syncEnabled: await _store.loadSyncEnabled(ownerId),
      );

  Future<void> setSyncEnabled(String ownerId, bool enabled) =>
      _store.saveSyncEnabled(ownerId, enabled);

  Future<HealthConnectReadAccess> connect(String ownerId) async {
    if (!await _store.loadSyncEnabled(ownerId)) {
      return HealthConnectReadAccess.none;
    }
    return _gateway.requestReadAccess();
  }

  Future<HealthConnectSnapshot> sync(String ownerId) async {
    if (!await _store.loadSyncEnabled(ownerId)) {
      throw StateError('Health Connect sync is paused.');
    }
    final access = await _gateway.readAccess();
    if (!access.any) {
      throw StateError('Health Connect read permission is not granted.');
    }
    final now = _now();
    final start = now.subtract(const Duration(days: 30));
    final records = await _gateway.read(
      start: start,
      end: now,
      kinds: access.permittedKinds,
    );
    final today = DateTime(now.year, now.month, now.day);
    var waterCount = 0;
    var weightCount = 0;
    var waterTotal = 0.0;
    var hasWaterToday = false;
    HealthConnectRecord? latestWeight;
    final sources = <String>{};
    for (final record in records) {
      if (record.recordedAt.isBefore(start) || record.recordedAt.isAfter(now)) {
        continue;
      }
      if (record.sourceName.isNotEmpty) sources.add(record.sourceName);
      switch (record.kind) {
        case HealthConnectRecordKind.water:
          waterCount++;
          if (!record.recordedAt.isBefore(today)) {
            waterTotal += record.value;
            hasWaterToday = true;
          }
        case HealthConnectRecordKind.weight:
          weightCount++;
          if (latestWeight == null ||
              record.recordedAt.isAfter(latestWeight.recordedAt)) {
            latestWeight = record;
          }
      }
    }
    final sourceNames = sources.toList(growable: false)..sort();
    return HealthConnectSnapshot(
      fetchedAt: now,
      waterTodayLiters: hasWaterToday ? waterTotal : null,
      latestWeightKg: latestWeight?.value,
      latestWeightAt: latestWeight?.recordedAt,
      waterRecordCount: waterCount,
      weightRecordCount: weightCount,
      sourceNames: sourceNames.take(5).toList(growable: false),
      access: access,
    );
  }

  Future<void> disconnect(String ownerId) async {
    try {
      await _gateway.revokeAccess();
    } finally {
      await _store.saveSyncEnabled(ownerId, false);
    }
  }

  Future<void> openInstallFlow() => _gateway.openInstallFlow();
}

String _boundedLabel(String value) {
  final normalized = value.trim().replaceAll(RegExp(r'\s+'), ' ');
  return normalized.length <= 80 ? normalized : normalized.substring(0, 80);
}
