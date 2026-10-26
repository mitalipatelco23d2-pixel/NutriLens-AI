import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/custom_recipes_screen.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/custom_recipe_controller.dart';
import 'package:nutrilens_x/services/custom_recipe_models.dart';
import 'package:nutrilens_x/services/product_api.dart';

CustomRecipeDraft _draft({String name = 'Lentil bowl', double servings = 2}) =>
    CustomRecipeDraft(
      name: name,
      servings: servings,
      ingredients: [
        CustomRecipeIngredient(
          name: 'Lentils',
          quantity: 250,
          unit: 'g',
          nutrients: RecipeNutrients({'calories': 200, 'sugar_g': 0}),
        ),
      ],
      notes: 'Cook until tender.',
    );

Map<String, dynamic> _json(
  String id,
  CustomRecipeDraft draft, {
  int version = 1,
}) => {
  'id': id,
  ...draft.toJson(),
  'version': version,
  'created_at': '2026-09-03T09:00:00Z',
  'updated_at': '2026-09-03T09:00:00Z',
  'source': 'USER_ENTERED',
  'total_nutrients': {
    for (final key in recipeNutrientLabels.keys)
      key:
          draft.ingredients.every(
            (ingredient) => ingredient.nutrients.values[key] != null,
          )
          ? draft.ingredients.fold<double>(
              0,
              (sum, ingredient) => sum + ingredient.nutrients.values[key]!,
            )
          : null,
  },
  'per_serving': {
    for (final key in recipeNutrientLabels.keys)
      key:
          draft.ingredients.every(
            (ingredient) => ingredient.nutrients.values[key] != null,
          )
          ? draft.ingredients.fold<double>(
                  0,
                  (sum, ingredient) => sum + ingredient.nutrients.values[key]!,
                ) /
                draft.servings
          : null,
  },
};

class _Store implements PendingCustomRecipeStore {
  final values = <String, PendingCustomRecipe>{};
  bool failWrite = false;
  @override
  Future<PendingCustomRecipe?> read(String ownerId) async => values[ownerId];
  @override
  Future<void> write(String ownerId, PendingCustomRecipe pending) async {
    if (failWrite) throw StateError('Storage unavailable');
    values[ownerId] = pending;
  }

  @override
  Future<void> clear(String ownerId) async {
    values.remove(ownerId);
  }
}

class _Gateway implements CustomRecipeGateway {
  final values = <String, CustomRecipe>{};
  final submitted = <PendingCustomRecipe>[];
  final offsets = <int>[];
  bool loseNextReply = false;
  bool failRead = false;
  ApiException? rejectCreate;
  Completer<List<CustomRecipe>>? delayedRead;
  int updates = 0;
  int deletes = 0;

  @override
  Future<List<CustomRecipe>> customRecipes({
    int offset = 0,
    int limit = 200,
  }) async {
    offsets.add(offset);
    if (delayedRead != null) return delayedRead!.future;
    if (failRead) {
      throw const ApiException('Recipes unavailable', statusCode: 503);
    }
    return values.values.skip(offset).take(limit).toList();
  }

  @override
  Future<CustomRecipe> customRecipe(String id) async => values[id]!;
  @override
  Future<CustomRecipe> createCustomRecipe(PendingCustomRecipe pending) async {
    submitted.add(pending);
    if (rejectCreate != null) throw rejectCreate!;
    values.putIfAbsent(
      pending.id,
      () => CustomRecipe.fromJson(_json(pending.id, pending.draft)),
    );
    if (loseNextReply) {
      loseNextReply = false;
      throw TimeoutException('Reply was lost');
    }
    return values[pending.id]!;
  }

  @override
  Future<CustomRecipe> updateCustomRecipe(
    String id,
    CustomRecipeDraft draft, {
    required int expectedVersion,
  }) async {
    updates++;
    if (values[id]!.version != expectedVersion) {
      throw const ApiException('Stale version', statusCode: 409);
    }
    return values[id] = CustomRecipe.fromJson(
      _json(id, draft, version: expectedVersion + 1),
    );
  }

  @override
  Future<void> deleteCustomRecipe(
    String id, {
    required int expectedVersion,
  }) async {
    deletes++;
    final current = values[id];
    if (current == null) throw const ApiException('Not found', statusCode: 404);
    if (current.version != expectedVersion) {
      throw const ApiException('Stale version', statusCode: 409);
    }
    values.remove(id);
  }
}

CustomRecipeController _controller(_Gateway gateway, {_Store? store}) =>
    CustomRecipeController(
      gateway: gateway,
      ownerId: 'owner-a',
      currentOwnerId: () => 'owner-a',
      store: store ?? _Store(),
    );

void main() {
  test(
    'HTTP contract authenticates and sends original IDs, versions and null evidence',
    () async {
      final requests = <http.Request>[];
      const id = '1c3af280-eed6-4aee-a0ff-e695dc6a25d5';
      final draft = _draft();
      final api = ProductApi(
        ApiClient(
          baseUrl: 'https://api.example',
          accessToken: () => 'test-token',
          client: MockClient((request) async {
            requests.add(request);
            expect(request.headers['Authorization'], 'Bearer test-token');
            if (request.method == 'DELETE') return http.Response('', 204);
            if (request.method == 'GET' &&
                request.url.path.endsWith('/custom')) {
              return http.Response(jsonEncode([_json(id, draft)]), 200);
            }
            return http.Response(
              jsonEncode(_json(id, draft)),
              request.method == 'POST' ? 201 : 200,
            );
          }),
        ),
      );
      final recipes = await api.customRecipes(offset: 200, limit: 50);
      expect(requests.last.url.queryParameters, {
        'offset': '200',
        'limit': '50',
      });
      expect(recipes.single.totalNutrients.values['protein_g'], isNull);
      expect(recipes.single.totalNutrients.values['sugar_g'], 0);
      await api.customRecipe(id);
      expect(requests.last.url.path, '/api/v1/recipes/custom/$id');
      await api.createCustomRecipe(PendingCustomRecipe(id: id, draft: draft));
      final created = jsonDecode(requests.last.body) as Map<String, dynamic>;
      expect(created['id'], id);
      expect(created.containsKey('source'), isFalse);
      expect(created['ingredients'][0]['quantity'], 250);
      expect(created['ingredients'][0]['nutrients']['calories'], 200);
      expect(created['ingredients'][0]['nutrients']['protein_g'], isNull);
      await api.updateCustomRecipe(id, draft, expectedVersion: 3);
      expect(requests.last.method, 'PUT');
      expect(jsonDecode(requests.last.body)['expected_version'], 3);
      expect(
        (jsonDecode(requests.last.body) as Map).containsKey('id'),
        isFalse,
      );
      await api.deleteCustomRecipe(id, expectedVersion: 4);
      expect(requests.last.method, 'DELETE');
      expect(requests.last.url.queryParameters, {'expected_version': '4'});
    },
  );

  test(
    'missing nutrient evidence stays null, explicit zero and entered quantities survive roundtrip',
    () {
      final nutrients = RecipeNutrients.fromJson({
        'calories': 12.5,
        'sugar_g': 0,
      });
      expect(nutrients.values['protein_g'], isNull);
      expect(nutrients.values['sugar_g'], 0);
      expect(nutrients.toJson().length, 7);
      final draft = _draft();
      final restored = CustomRecipeDraft.fromJson(draft.toJson());
      expect(restored.ingredients.single.quantity, 250);
      expect(restored.ingredients.single.nutrients.values['calories'], 200);
      expect(restored.toJson(), draft.toJson());
    },
  );

  test(
    'lost reply restores original creation and never auto-replays or duplicates on restart',
    () async {
      final gateway = _Gateway()..loseNextReply = true;
      final store = _Store();
      final first = _controller(gateway, store: store);
      await first.initialize();
      await first.create(_draft());
      expect(first.pendingCreate, isNotNull);
      expect(first.canMutate, isFalse);
      await first.create(_draft(name: 'Must not create'));
      expect(gateway.submitted.length, 1);
      first.dispose();
      final restored = _controller(gateway, store: store);
      await restored.initialize();
      expect(gateway.submitted.length, 1);
      expect(
        restored.pendingCreate!.id,
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
      await restored.retryCreate();
      expect(gateway.submitted.length, 2);
      expect(gateway.submitted.first.toJson(), gateway.submitted.last.toJson());
      expect(gateway.values.length, 1);
      expect(restored.pendingCreate, isNull);
      expect(store.values, isEmpty);
      restored.dispose();
    },
  );

  test(
    'durable storage failure blocks transport until same identity can be saved',
    () async {
      final gateway = _Gateway();
      final store = _Store()..failWrite = true;
      final controller = _controller(gateway, store: store);
      await controller.initialize();
      await controller.create(_draft());
      expect(gateway.submitted, isEmpty);
      final id = controller.pendingCreate!.id;
      store.failWrite = false;
      await controller.retryCreate();
      expect(gateway.submitted.single.id, id);
      controller.dispose();
    },
  );

  test('create, update and delete refresh canonical saved list', () async {
    final controller = _controller(_Gateway());
    await controller.initialize();
    await controller.create(_draft());
    expect(controller.recipes.single.perServing.values['calories'], 100);
    expect(controller.recipes.single.perServing.values['protein_g'], isNull);
    await controller.update(
      controller.recipes.single,
      _draft(name: 'Updated bowl', servings: 4),
    );
    expect(controller.recipes.single.draft.name, 'Updated bowl');
    expect(controller.recipes.single.version, 2);
    expect(controller.recipes.single.perServing.values['calories'], 50);
    await controller.delete(controller.recipes.single);
    expect(controller.recipes, isEmpty);
    controller.dispose();
  });

  test(
    'confirmed save with failed list refresh does not keep a retryable creation',
    () async {
      final gateway = _Gateway();
      final controller = _controller(gateway);
      await controller.initialize();
      gateway.failRead = true;
      await controller.create(_draft());
      expect(controller.pendingCreate, isNull);
      expect(controller.error, 'Recipes unavailable');
      expect(controller.notice, contains('Recipe saved'));
      expect(controller.notice, contains('do not create it again'));
      gateway.failRead = false;
      await controller.refresh();
      expect(controller.recipes, hasLength(1));
      expect(gateway.submitted, hasLength(1));
      controller.dispose();
    },
  );

  test(
    'stale edit and delete reload without overwriting another device',
    () async {
      final gateway = _Gateway();
      final controller = _controller(gateway);
      await controller.initialize();
      await controller.create(_draft());
      final stale = controller.recipes.single;
      gateway.values[stale.id] = CustomRecipe.fromJson(
        _json(stale.id, _draft(name: 'Other device'), version: 2),
      );
      await controller.update(stale, _draft(name: 'Do not overwrite'));
      expect(gateway.updates, 1);
      expect(controller.recipes.single.draft.name, 'Other device');
      expect(controller.error, contains('your changes were not applied'));
      await controller.delete(stale);
      expect(gateway.deletes, 1);
      expect(controller.recipes.single.version, 2);
      expect(controller.error, contains('another device'));
      controller.dispose();
    },
  );

  test(
    'owner change cannot display delayed records or replay another owner creation',
    () async {
      var owner = 'owner-a';
      final gateway = _Gateway()..loseNextReply = true;
      final store = _Store();
      final controller = CustomRecipeController(
        gateway: gateway,
        ownerId: owner,
        currentOwnerId: () => owner,
        store: store,
      );
      await controller.initialize();
      await controller.create(_draft());
      gateway.delayedRead = Completer<List<CustomRecipe>>();
      final refresh = controller.refresh();
      owner = 'owner-b';
      controller.invalidate();
      await controller.retryCreate();
      gateway.delayedRead!.complete(gateway.values.values.toList());
      await refresh;
      expect(controller.recipes, isEmpty);
      expect(controller.pendingCreate, isNull);
      expect(gateway.submitted.length, 1);
      expect(await store.read('owner-b'), isNull);
      expect(await store.read('owner-a'), isNotNull);
      controller.dispose();
    },
  );

  test(
    'conflicted or invalid create clears pending without inventing replacement identity',
    () async {
      for (final code in [409, 422]) {
        final gateway = _Gateway()
          ..rejectCreate = ApiException('Rejected', statusCode: code);
        final store = _Store();
        final controller = _controller(gateway, store: store);
        await controller.initialize();
        await controller.create(_draft());
        expect(controller.pendingCreate, isNull);
        expect(store.values, isEmpty);
        expect(gateway.submitted.length, 1);
        expect(controller.error, isNotNull);
        controller.dispose();
      }
    },
  );

  test(
    'pagination exposes remaining recipes and refresh resets first page',
    () async {
      final gateway = _Gateway();
      for (var i = 0; i < 201; i++) {
        gateway.values['$i'] = CustomRecipe.fromJson(
          _json('$i', _draft(name: 'Recipe $i')),
        );
      }
      final controller = _controller(gateway);
      await controller.initialize();
      expect(controller.recipes.length, 200);
      expect(controller.hasMore, isTrue);
      await controller.loadMore();
      expect(gateway.offsets, [0, 200]);
      expect(controller.recipes.length, 201);
      expect(controller.hasMore, isFalse);
      await controller.refresh();
      expect(controller.recipes.length, 200);
      controller.dispose();
    },
  );

  testWidgets('recipe screen recovers a read error through refresh', (
    tester,
  ) async {
    final gateway = _Gateway()..failRead = true;
    final controller = _controller(gateway);
    await controller.initialize();
    await tester.pumpWidget(
      MaterialApp(home: CustomRecipesScreen(controller: controller)),
    );
    expect(find.text('Recipes unavailable'), findsOneWidget);
    gateway.failRead = false;
    await tester.tap(find.text('Refresh recipes'));
    await tester.pumpAndSettle();
    expect(
      find.text('No saved recipes yet. Create a recipe to start.'),
      findsOneWidget,
    );
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets(
    'recipe editor validates and saves missing nutrition as unknown',
    (tester) async {
      final controller = _controller(_Gateway());
      await controller.initialize();
      await tester.pumpWidget(
        MaterialApp(home: CustomRecipesScreen(controller: controller)),
      );
      await tester.tap(find.text('Create recipe'));
      await tester.pumpAndSettle();
      Finder field(String label) => find.byWidgetPredicate(
        (widget) =>
            widget is TextField && widget.decoration?.labelText == label,
      );
      await tester.enterText(field('Recipe name'), 'Simple soup');
      await tester.enterText(field('Recipe servings'), '0');
      await tester.enterText(field('Ingredient name'), 'Carrot');
      await tester.enterText(field('Quantity'), '200');
      await tester.enterText(field('Unit (g, ml, cup…)'), 'g');
      await tester.ensureVisible(find.text('Save recipe'));
      await tester.tap(find.text('Save recipe'));
      await tester.pumpAndSettle();
      expect(find.text('Enter a number from 0.001 to 1000.'), findsOneWidget);
      await tester.ensureVisible(field('Recipe servings'));
      await tester.enterText(field('Recipe servings'), '2');
      await tester.ensureVisible(find.text('Save recipe'));
      await tester.tap(find.text('Save recipe'));
      await tester.pumpAndSettle();
      expect(controller.recipes.single.draft.name, 'Simple soup');
      expect(
        controller.recipes.single.totalNutrients.values.values.every(
          (value) => value == null,
        ),
        isTrue,
      );
      await tester.ensureVisible(find.text('Nutrition totals and per serving'));
      await tester.tap(find.text('Nutrition totals and per serving'));
      await tester.pumpAndSettle();
      expect(
        find.text('Energy (kcal): total Unknown · per serving Unknown'),
        findsOneWidget,
      );
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets('saved recipe deletion requires confirmation', (tester) async {
    final controller = _controller(_Gateway());
    await controller.initialize();
    await controller.create(_draft());
    await tester.pumpWidget(
      MaterialApp(home: CustomRecipesScreen(controller: controller)),
    );
    await tester.ensureVisible(find.text('Delete recipe'));
    await tester.tap(find.text('Delete recipe'));
    await tester.pumpAndSettle();
    expect(find.text('Delete saved recipe?'), findsOneWidget);
    expect(controller.recipes, hasLength(1));
    await tester.tap(find.widgetWithText(FilledButton, 'Delete recipe'));
    await tester.pumpAndSettle();
    expect(controller.recipes, isEmpty);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
}
