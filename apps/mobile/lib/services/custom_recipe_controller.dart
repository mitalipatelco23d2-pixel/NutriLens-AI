import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api_client.dart';
import 'custom_recipe_models.dart';

abstract interface class PendingCustomRecipeStore {
  Future<PendingCustomRecipe?> read(String ownerId);
  Future<void> write(String ownerId, PendingCustomRecipe pending);
  Future<void> clear(String ownerId);
}

class SecurePendingCustomRecipeStore implements PendingCustomRecipeStore {
  const SecurePendingCustomRecipeStore();
  static const _storage = FlutterSecureStorage();
  String _key(String ownerId) => 'nutrilens_custom_recipe_pending_v1_$ownerId';

  @override
  Future<PendingCustomRecipe?> read(String ownerId) async {
    final raw = await _storage.read(key: _key(ownerId));
    return raw == null
        ? null
        : PendingCustomRecipe.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  @override
  Future<void> write(String ownerId, PendingCustomRecipe pending) =>
      _storage.write(key: _key(ownerId), value: jsonEncode(pending.toJson()));

  @override
  Future<void> clear(String ownerId) => _storage.delete(key: _key(ownerId));
}

/// Owner-bound state. No POST is automatically replayed during initialization.
class CustomRecipeController extends ChangeNotifier {
  CustomRecipeController({
    required this.gateway,
    required this.ownerId,
    required this.currentOwnerId,
    this.store = const SecurePendingCustomRecipeStore(),
  });

  final CustomRecipeGateway gateway;
  final String ownerId;
  final String? Function() currentOwnerId;
  final PendingCustomRecipeStore store;
  List<CustomRecipe> recipes = const [];
  PendingCustomRecipe? pendingCreate;
  String? error;
  String? notice;
  bool loading = false;
  bool saving = false;
  bool hasMore = false;
  bool _initialized = false;
  bool _valid = true;
  bool _disposed = false;
  int _revision = 0;

  bool get active => _valid && !_disposed && currentOwnerId() == ownerId;
  bool get canMutate =>
      active && _initialized && !loading && !saving && pendingCreate == null;

  void _emit() {
    if (!_disposed) notifyListeners();
  }

  void invalidate() {
    _valid = false;
    _revision++;
    recipes = const [];
    hasMore = false;
    pendingCreate = null;
    error = null;
    notice = null;
    _emit();
  }

  Future<void> initialize() async {
    if (!active || _initialized || loading) return;
    loading = true;
    error = null;
    _emit();
    try {
      final recovered = await store.read(ownerId);
      if (!active) return;
      pendingCreate = recovered;
      _initialized = true;
    } on Object {
      if (active) {
        error = 'Could not recover pending recipes. Refresh to try again.';
      }
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
    loading = true;
    error = null;
    _emit();
    try {
      final saved = await gateway.customRecipes();
      if (active && revision == _revision) {
        recipes = saved;
        hasMore = saved.length == 200;
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

  Future<void> loadMore() async {
    if (!active || loading || saving || !hasMore) return;
    final revision = ++_revision;
    loading = true;
    error = null;
    _emit();
    try {
      final page = await gateway.customRecipes(offset: recipes.length);
      if (active && revision == _revision) {
        recipes = {
          for (final recipe in [...recipes, ...page]) recipe.id: recipe,
        }.values.toList();
        hasMore = page.length == 200;
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

  Future<void> create(CustomRecipeDraft draft) async {
    if (!canMutate) return;
    pendingCreate = PendingCustomRecipe(id: _uuid(), draft: draft);
    await retryCreate();
  }

  Future<void> retryCreate() async {
    final pending = pendingCreate;
    if (!active || saving || pending == null) return;
    saving = true;
    _revision++;
    error = null;
    notice = null;
    _emit();
    String? rejection;
    try {
      // If secure storage fails, never send an untracked creation request.
      await store.write(ownerId, pending);
      if (!active) return;
      await gateway.createCustomRecipe(pending);
      if (!active) return;
      await store.clear(ownerId);
      if (active) pendingCreate = null;
    } on Object catch (failure) {
      if (active &&
          failure is ApiException &&
          (failure.statusCode == 409 || failure.statusCode == 422)) {
        rejection = failure.statusCode == 409
            ? 'That recipe was changed or deleted. Refresh the saved list; no replacement was created.'
            : failure.toString();
        try {
          await store.clear(ownerId);
          if (active) pendingCreate = null;
        } on Object {
          // Keep identity until durable cleanup can succeed.
        }
      }
      if (active) error = rejection ?? failure.toString();
    } finally {
      saving = false;
      _emit();
    }
    if (active && pendingCreate == null) {
      await refresh();
      if (active && rejection != null) {
        error = error == null ? rejection : '$rejection\n$error';
        _emit();
      }
      if (active && rejection == null) {
        notice =
            'Recipe saved. If the list has not refreshed, use Refresh recipes; do not create it again.';
        _emit();
      }
    }
  }

  Future<void> update(CustomRecipe recipe, CustomRecipeDraft draft) => _change(
    () => gateway.updateCustomRecipe(
      recipe.id,
      draft,
      expectedVersion: recipe.version,
    ),
    'Recipe updated. Use Refresh recipes if the list has not refreshed.',
  );

  Future<void> delete(CustomRecipe recipe) => _change(() async {
    try {
      await gateway.deleteCustomRecipe(
        recipe.id,
        expectedVersion: recipe.version,
      );
    } on ApiException catch (failure) {
      // A previous successful delete may have lost its response.
      if (failure.statusCode != 404) rethrow;
    }
    return null;
  }, 'Recipe deleted. Use Refresh recipes if the list has not refreshed.');

  Future<void> _change(
    Future<Object?> Function() action,
    String successNotice,
  ) async {
    if (!canMutate) return;
    saving = true;
    _revision++;
    error = null;
    notice = null;
    _emit();
    String? failureMessage;
    var reload = false;
    try {
      await action();
      if (active) notice = successNotice;
      reload = true;
    } on Object catch (failure) {
      failureMessage = failure is ApiException && failure.statusCode == 409
          ? 'This recipe changed on another device. Refresh and review the latest version before editing again; your changes were not applied.'
          : failure.toString();
      // A failed/unknown response may still have committed. Read canonical state,
      // never reissue a PUT with a newer version or silently overwrite it.
      reload = true;
    } finally {
      saving = false;
      _emit();
    }
    if (active && reload) {
      await refresh();
      if (active && failureMessage != null) {
        error = error == null
            ? failureMessage
            : '$failureMessage\nReload failed: $error';
        _emit();
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _revision++;
    super.dispose();
  }
}

String _uuid() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes
      .map((byte) => byte.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}
