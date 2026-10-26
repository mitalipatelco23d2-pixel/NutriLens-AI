import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'api_client.dart';
import 'custom_recipe_models.dart';
import 'recipe_action_models.dart';

abstract interface class PendingRecipeActionStore {
  Future<PendingRecipeAction?> read(String ownerId);
  Future<void> write(String ownerId, PendingRecipeAction pending);
  Future<void> clear(String ownerId);
}

class SecurePendingRecipeActionStore implements PendingRecipeActionStore {
  const SecurePendingRecipeActionStore();
  static const _storage = FlutterSecureStorage();
  String _key(String owner) => 'nutrilens_recipe_action_pending_v1_$owner';
  @override
  Future<PendingRecipeAction?> read(String ownerId) async {
    final raw = await _storage.read(key: _key(ownerId));
    return raw == null
        ? null
        : PendingRecipeAction.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  @override
  Future<void> write(String ownerId, PendingRecipeAction pending) =>
      _storage.write(key: _key(ownerId), value: jsonEncode(pending.toJson()));
  @override
  Future<void> clear(String ownerId) => _storage.delete(key: _key(ownerId));
}

/// Writes are explicit. Recovery never replays a meal or shopping request itself.
class RecipeActionController extends ChangeNotifier {
  RecipeActionController({
    required this.gateway,
    required this.ownerId,
    required this.currentOwnerId,
    this.store = const SecurePendingRecipeActionStore(),
  });
  final RecipeActionGateway gateway;
  final String ownerId;
  final String? Function() currentOwnerId;
  final PendingRecipeActionStore store;
  PendingRecipeAction? pending;
  String? error;
  String? notice;
  bool busy = false;
  bool _ready = false;
  bool _valid = true;
  bool _disposed = false;
  bool get active => _valid && !_disposed && currentOwnerId() == ownerId;
  bool get canStart => active && _ready && !busy && pending == null;
  void _emit() {
    if (!_disposed) notifyListeners();
  }

  void invalidate() {
    _valid = false;
    pending = null;
    error = null;
    notice = null;
    _emit();
  }

  Future<void> initialize() async {
    if (!active || _ready || busy) return;
    busy = true;
    error = null;
    _emit();
    try {
      final saved = await store.read(ownerId);
      if (active) {
        pending = saved;
        _ready = true;
      }
    } on Object {
      if (active) {
        error =
            'Could not recover recipe actions. Retry recovery before logging food.';
      }
    } finally {
      busy = false;
      _emit();
    }
  }

  Future<void> logConsumed(CustomRecipe recipe, double servings) async {
    if (!canStart || !_validServings(servings)) return;
    pending = PendingRecipeAction(
      recipeId: recipe.id,
      recipeName: recipe.draft.name,
      kind: RecipeActionKind.diary,
      body: {
        'id': _uuid(),
        'expected_version': recipe.version,
        'servings': servings,
        'eaten_at': DateTime.now().toUtc().toIso8601String(),
      },
    );
    await retry();
  }

  Future<RecipePantryCheck?> checkPantry(
    CustomRecipe recipe,
    double servings,
  ) async {
    if (!canStart || !_validServings(servings)) return null;
    busy = true;
    error = null;
    notice = null;
    _emit();
    try {
      final result = await gateway.checkCustomRecipePantry(
        recipe.id,
        expectedVersion: recipe.version,
        servings: servings,
      );
      return active ? result : null;
    } on Object catch (failure) {
      if (active) error = _failure(failure);
      return null;
    } finally {
      busy = false;
      _emit();
    }
  }

  Future<void> addMissing(
    CustomRecipe recipe,
    RecipePantryCheck check,
    Set<String> keys,
  ) async {
    if (!canStart ||
        keys.isEmpty ||
        check.recipeId != recipe.id ||
        check.recipeVersion != recipe.version) {
      return;
    }
    final allowed = check.ingredients
        .where((item) => item.canAdd)
        .map((item) => item.key)
        .toSet();
    if (!allowed.containsAll(keys)) return;
    pending = PendingRecipeAction(
      recipeId: recipe.id,
      recipeName: recipe.draft.name,
      kind: RecipeActionKind.shopping,
      body: {
        'id': _uuid(),
        'expected_version': recipe.version,
        'servings': check.servings,
        'check_token': check.checkToken,
        'ingredient_keys': keys.toList()..sort(),
      },
    );
    await retry();
  }

  Future<void> retry() async {
    final original = pending;
    if (!active || busy || original == null) return;
    busy = true;
    error = null;
    notice = null;
    _emit();
    try {
      await store.write(ownerId, original);
      if (!active) return;
      String success;
      if (original.kind == RecipeActionKind.diary) {
        await gateway.logCustomRecipe(original);
        success =
            'Consumed servings saved to your diary. Pantry stock was not changed.';
      } else {
        final result = await gateway.addCustomRecipeShopping(original);
        success =
            '${result.generatedCount} shopping items added. ${result.limitation}';
      }
      if (!active) return;
      await store.clear(ownerId);
      if (active) {
        pending = null;
        notice = success;
      }
    } on Object catch (failure) {
      if (active) {
        // Only definitive rejected requests may be cleared. Unknown outcomes retain
        // the original UUID, timestamp, serving count and ingredient selection.
        if (failure is ApiException &&
            [409, 422].contains(failure.statusCode)) {
          try {
            await store.clear(ownerId);
            if (active) pending = null;
          } on Object {
            /* Keep the identity until secure cleanup succeeds. */
          }
        }
        if (active) error = _failure(failure);
      }
    } finally {
      busy = false;
      _emit();
    }
  }

  String _failure(Object failure) =>
      failure is ApiException && failure.statusCode == 409
      ? 'This recipe or action changed. Refresh recipes and review the latest version before trying again.'
      : failure.toString();

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}

bool _validServings(double value) =>
    value.isFinite && value >= .001 && value <= 1000;
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
