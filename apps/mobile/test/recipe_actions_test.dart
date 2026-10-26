import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/authenticated_shell.dart';
import 'package:nutrilens_x/recipe_actions_screen.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/custom_recipe_models.dart';
import 'package:nutrilens_x/services/product_api.dart';
import 'package:nutrilens_x/services/recipe_action_controller.dart';
import 'package:nutrilens_x/services/recipe_action_models.dart';

const _recipeId = '0a8798d9-e980-429a-9157-99af85c6b945';
final _checkToken = List.filled(64, 'a').join();

CustomRecipe _recipe() => CustomRecipe(
  id: _recipeId,
  draft: CustomRecipeDraft(
    name: 'Lentil bowl',
    servings: 4,
    ingredients: [
      CustomRecipeIngredient(
        name: 'Lentils',
        quantity: 200,
        unit: 'g',
        nutrients: RecipeNutrients({'calories': 300, 'sugar_g': 0}),
      ),
    ],
  ),
  version: 2,
  createdAt: DateTime.utc(2026, 9, 5),
  updatedAt: DateTime.utc(2026, 9, 5),
  totalNutrients: RecipeNutrients({'calories': 300, 'sugar_g': 0}),
  perServing: RecipeNutrients({'calories': 75, 'sugar_g': 0}),
);

Map<String, dynamic> _checkJson({double servings = 1}) => {
  'recipe_id': _recipeId,
  'recipe_version': 2,
  'servings': servings,
  'check_token': _checkToken,
  'limitation':
      'Only matching names and units are compared. No conversions are inferred.',
  'ingredients': [
    {
      'key': 'missing',
      'name': 'Lentils',
      'unit': 'g',
      'required_quantity': 50,
      'available_quantity': 20,
      'missing_quantity': 30,
      'status': 'MISSING',
      'pantry_item_ids': ['p1'],
    },
    {
      'key': 'available',
      'name': 'Rice',
      'unit': 'g',
      'required_quantity': 40,
      'available_quantity': 100,
      'missing_quantity': 0,
      'status': 'AVAILABLE',
      'pantry_item_ids': ['p2'],
    },
    {
      'key': 'mismatch',
      'name': 'Onion',
      'unit': 'item',
      'required_quantity': 1,
      'available_quantity': null,
      'missing_quantity': null,
      'status': 'UNIT_MISMATCH',
      'pantry_item_ids': ['p3'],
    },
  ],
};

class _Store implements PendingRecipeActionStore {
  final values = <String, PendingRecipeAction>{};
  bool failWrite = false;
  Completer<void>? beforeWrite;
  @override
  Future<PendingRecipeAction?> read(String ownerId) async => values[ownerId];
  @override
  Future<void> write(String ownerId, PendingRecipeAction pending) async {
    if (beforeWrite != null) await beforeWrite!.future;
    if (failWrite) throw StateError('Secure storage unavailable');
    values[ownerId] = PendingRecipeAction.fromJson(
      jsonDecode(jsonEncode(pending.toJson())) as Map<String, dynamic>,
    );
  }

  @override
  Future<void> clear(String ownerId) async {
    values.remove(ownerId);
  }
}

class _Gateway implements RecipeActionGateway {
  final submissions = <PendingRecipeAction>[];
  final committed = <String>{};
  int checks = 0;
  bool loseReply = false;
  ApiException? rejection;
  Completer<void>? beforeResponse;
  void Function(PendingRecipeAction)? onSubmit;
  Future<void> _submit(PendingRecipeAction pending) async {
    submissions.add(pending);
    onSubmit?.call(pending);
    if (rejection != null) throw rejection!;
    committed.add(pending.body['id'] as String);
    if (beforeResponse != null) await beforeResponse!.future;
    if (loseReply) {
      loseReply = false;
      throw TimeoutException('Reply lost');
    }
  }

  @override
  Future<void> logCustomRecipe(PendingRecipeAction pending) => _submit(pending);
  @override
  Future<RecipePantryCheck> checkCustomRecipePantry(
    String recipeId, {
    required int expectedVersion,
    required double servings,
  }) async {
    checks++;
    return RecipePantryCheck.fromJson(_checkJson(servings: servings));
  }

  @override
  Future<RecipeShoppingResult> addCustomRecipeShopping(
    PendingRecipeAction pending,
  ) async {
    await _submit(pending);
    return const RecipeShoppingResult(
      generatedCount: 1,
      limitation: 'No stock changed.',
    );
  }
}

RecipeActionController _controller(
  _Gateway gateway,
  _Store store, {
  String owner = 'owner-a',
  String? Function()? currentOwner,
}) => RecipeActionController(
  gateway: gateway,
  ownerId: owner,
  currentOwnerId: currentOwner ?? () => owner,
  store: store,
);

void main() {
  test(
    'HTTP action contract uses authenticated exact bodies and checked snapshot token',
    () async {
      final requests = <http.Request>[];
      final api = ProductApi(
        ApiClient(
          baseUrl: 'https://api.example',
          accessToken: () => 'test-token',
          client: MockClient((request) async {
            requests.add(request);
            expect(request.method, 'POST');
            expect(request.headers['Authorization'], 'Bearer test-token');
            if (request.url.path.endsWith('/pantry-check')) {
              return http.Response(jsonEncode(_checkJson(servings: 1.5)), 200);
            }
            if (request.url.path.endsWith('/shopping-list')) {
              return http.Response(
                '{"generated_count":1,"items":[],"limitation":"No stock changed."}',
                201,
              );
            }
            return http.Response('{"id":"record-id"}', 201);
          }),
        ),
      );
      final check = await api.checkCustomRecipePantry(
        _recipeId,
        expectedVersion: 2,
        servings: 1.5,
      );
      expect(
        requests.last.url.path,
        '/api/v1/recipes/custom/$_recipeId/pantry-check',
      );
      expect(jsonDecode(requests.last.body), {
        'expected_version': 2,
        'servings': 1.5,
      });
      expect(check.ingredients.last.missingQuantity, isNull);
      final diary = PendingRecipeAction(
        recipeId: _recipeId,
        recipeName: 'Lentil bowl',
        kind: RecipeActionKind.diary,
        body: {
          'id': '990d3f06-5c7f-40ba-8832-32d40b4c19a4',
          'expected_version': 2,
          'servings': 1.5,
          'eaten_at': '2026-09-05T10:00:00Z',
        },
      );
      await api.logCustomRecipe(diary);
      expect(requests.last.url.path, '/api/v1/recipes/custom/$_recipeId/diary');
      expect(jsonDecode(requests.last.body), diary.body);
      final shopping = PendingRecipeAction(
        recipeId: _recipeId,
        recipeName: 'Lentil bowl',
        kind: RecipeActionKind.shopping,
        body: {
          'id': 'd0cc3e39-96f6-4d45-9e76-b50b8ff0f46d',
          'expected_version': 2,
          'servings': check.servings,
          'ingredient_keys': ['missing'],
          'check_token': check.checkToken,
        },
      );
      expect((await api.addCustomRecipeShopping(shopping)).generatedCount, 1);
      expect(
        requests.last.url.path,
        '/api/v1/recipes/custom/$_recipeId/shopping-list',
      );
      expect(jsonDecode(requests.last.body), shopping.body);
    },
  );

  test(
    'lost diary response survives restart and exact retry does not duplicate',
    () async {
      final store = _Store();
      final gateway = _Gateway()..loseReply = true;
      final first = _controller(gateway, store);
      await first.initialize();
      gateway.onSubmit = (pending) =>
          expect(store.values['owner-a']!.body, pending.body);
      await first.logConsumed(_recipe(), 1.5);
      final original = jsonEncode(first.pending!.toJson());
      expect(first.canStart, isFalse);
      expect(gateway.committed, hasLength(1));
      first.dispose();
      final resumed = _controller(gateway, store);
      await resumed.initialize();
      expect(
        gateway.submissions,
        hasLength(1),
        reason: 'Recovery cannot automatically log food',
      );
      expect(jsonEncode(resumed.pending!.toJson()), original);
      await resumed.retry();
      expect(gateway.committed, hasLength(1));
      expect(jsonEncode(gateway.submissions.last.toJson()), original);
      expect(resumed.pending, isNull);
      expect(store.values, isEmpty);
      resumed.dispose();
    },
  );

  test(
    'storage failure sends no untracked write and double tap has one identity',
    () async {
      final store = _Store()..failWrite = true;
      final gateway = _Gateway();
      final controller = _controller(gateway, store);
      await controller.initialize();
      await controller.logConsumed(_recipe(), 1);
      expect(gateway.submissions, isEmpty);
      expect(controller.pending, isNotNull);
      store.failWrite = false;
      gateway.beforeResponse = Completer<void>();
      final retry = controller.retry();
      await Future<void>.delayed(Duration.zero);
      await controller.retry();
      await controller.logConsumed(_recipe(), 2);
      expect(gateway.submissions, hasLength(1));
      expect(gateway.submissions.single.body['servings'], 1);
      gateway.beforeResponse!.complete();
      await retry;
      controller.dispose();
    },
  );

  test(
    '401 403 and 404 preserve ambiguous action until same identity succeeds',
    () async {
      final store = _Store();
      final gateway = _Gateway()..loseReply = true;
      final controller = _controller(gateway, store);
      await controller.initialize();
      await controller.logConsumed(_recipe(), .5);
      final identity = controller.pending!.body['id'];
      for (final status in [401, 403, 404]) {
        gateway.rejection = ApiException(
          'Authentication or record unavailable',
          statusCode: status,
        );
        await controller.retry();
        expect(controller.pending!.body['id'], identity);
        expect(store.values['owner-a']!.body['id'], identity);
        expect(controller.canStart, isFalse);
      }
      gateway.rejection = null;
      await controller.retry();
      expect(gateway.committed, {identity});
      expect(controller.pending, isNull);
      controller.dispose();
    },
  );

  test(
    'definitive conflict clears pending but asks for latest recipe review',
    () async {
      final controller = _controller(
        _Gateway()..rejection = const ApiException('Changed', statusCode: 409),
        _Store(),
      );
      await controller.initialize();
      await controller.logConsumed(_recipe(), 1);
      expect(controller.pending, isNull);
      expect(controller.error, contains('Refresh recipes'));
      controller.dispose();
    },
  );

  test(
    'owner change before send prevents write and late response does not clear recovery',
    () async {
      var owner = 'owner-a';
      final store = _Store()..beforeWrite = Completer<void>();
      final gateway = _Gateway();
      final controller = _controller(gateway, store, currentOwner: () => owner);
      await controller.initialize();
      final writing = controller.logConsumed(_recipe(), 1);
      owner = 'owner-b';
      controller.invalidate();
      store.beforeWrite!.complete();
      await writing;
      expect(gateway.submissions, isEmpty);
      expect(controller.pending, isNull);
      expect(store.values['owner-a'], isNotNull);
      final other = _controller(gateway, store, owner: 'owner-b');
      await other.initialize();
      expect(other.pending, isNull);
      owner = 'owner-a';
      final resumed = _controller(gateway, store, currentOwner: () => owner);
      await resumed.initialize();
      gateway.beforeResponse = Completer<void>();
      final response = resumed.retry();
      await Future<void>.delayed(Duration.zero);
      owner = 'owner-b';
      resumed.invalidate();
      gateway.beforeResponse!.complete();
      await response;
      expect(store.values['owner-a'], isNotNull);
      expect(resumed.notice, isNull);
      controller.dispose();
      other.dispose();
      resumed.dispose();
    },
  );

  test(
    'pantry check is read-only, selection bounded, shopping retry keeps snapshot',
    () async {
      final store = _Store();
      final gateway = _Gateway();
      final controller = _controller(gateway, store);
      await controller.initialize();
      final check = (await controller.checkPantry(_recipe(), 2))!;
      expect(gateway.submissions, isEmpty);
      await controller.addMissing(_recipe(), check, {});
      await controller.addMissing(_recipe(), check, {'mismatch'});
      await controller.addMissing(_recipe(), check, {'available'});
      await controller.addMissing(_recipe(), check, {'invented'});
      expect(gateway.submissions, isEmpty);
      gateway.loseReply = true;
      await controller.addMissing(_recipe(), check, {'missing'});
      final original = controller.pending!.body;
      expect(original['check_token'], _checkToken);
      expect(original['ingredient_keys'], ['missing']);
      expect(original['servings'], 2);
      await controller.retry();
      expect(gateway.submissions.last.body, original);
      expect(gateway.committed, hasLength(1));
      controller.dispose();
    },
  );

  test('null nutrition, grams and goal percentages never become zero', () {
    final entry = DiaryEntry.fromJson({
      'id': 'd1',
      'name': 'Lentil bowl',
      'eaten_at': '2026-09-05T09:00:00Z',
      'source': 'CUSTOM_RECIPE',
      'recipe_id': _recipeId,
      'recipe_version': 2,
      'recipe_servings': 1.5,
      'serving_grams': null,
      'nutrients': {'calories': 112.5, 'sugar_g': 0, 'protein_g': null},
    });
    expect(entry.servingGrams, isNull);
    expect(entry.recipeServings, 1.5);
    expect(entry.servingDescription, '1.5 recipe servings · mass Unknown');
    expect(entry.nutrients.sugarG, 0);
    expect(entry.nutrients.proteinG, isNull);
    expect(entry.nutrients.fiberG, isNull);
    expect(entry.nutrients.toJson()['protein_g'], isNull);
    expect(nutrientEvidence(null), 'Unknown');
    expect(nutrientEvidence(0), '0.0');
    final manualUnknownMass = DiaryEntry.fromJson({
      'id': 'd2',
      'name': 'Unknown mass',
      'eaten_at': '2026-09-05T09:00:00Z',
      'serving_grams': null,
      'nutrients': <String, dynamic>{},
    });
    expect(manualUnknownMass.servingDescription, 'Serving mass unknown');
    final goal = GoalProgress.fromJson({
      'daily_average': null,
      'user_target': 60,
      'percent_of_target': null,
    });
    expect(goal.dailyAverage, isNull);
    expect(goal.percentOfTarget, isNull);
    expect(
      goal.progressDescription,
      ': progress unknown because logged evidence is incomplete.',
    );
    final comparison = MealComparisonCandidate.fromJson({
      'serving_grams': null,
      'logged_serving': {'calories': 10},
      'per_100g': {},
    });
    expect(comparison.servingGrams, isNull);
    expect(comparison.servingDescription, 'Serving mass unknown');
    expect(comparison.per100g.calories, isNull);
    final shopping = ShoppingListItem.fromJson({
      'id': 's1',
      'name': 'Lentils',
      'source': 'CUSTOM_RECIPE',
      'quantity': 30,
      'unit': 'g',
      'recipe_id': _recipeId,
    });
    expect(shopping.quantity, 30);
    expect(shopping.unit, 'g');
    expect(shopping.recipeId, _recipeId);
  });

  testWidgets(
    'logging requires actual-consumption confirmation and validates servings',
    (tester) async {
      final gateway = _Gateway();
      final controller = _controller(gateway, _Store());
      await controller.initialize();
      await tester.pumpWidget(
        MaterialApp(
          home: RecipeActionsScreen(recipe: _recipe(), controller: controller),
        ),
      );
      await tester.enterText(find.byType(TextFormField), '0');
      await tester.tap(find.text('Log consumed servings'));
      await tester.pumpAndSettle();
      expect(find.text('Enter servings from 0.001 to 1000.'), findsOneWidget);
      expect(gateway.submissions, isEmpty);
      await tester.enterText(find.byType(TextFormField), '1.5');
      await tester.tap(find.text('Log consumed servings'));
      await tester.pumpAndSettle();
      expect(gateway.submissions, isEmpty);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(gateway.submissions, isEmpty);
      await tester.tap(find.text('Log consumed servings'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm consumed'));
      await tester.pumpAndSettle();
      expect(gateway.submissions, hasLength(1));
      expect(gateway.submissions.single.body['servings'], 1.5);
      expect(
        find.textContaining('Pantry stock was not changed.'),
        findsOneWidget,
      );
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
    },
  );

  testWidgets(
    'checking pantry never auto-adds and unknown unit cannot be selected',
    (tester) async {
      tester.view.physicalSize = const Size(1000, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final gateway = _Gateway();
      final controller = _controller(gateway, _Store());
      await controller.initialize();
      await tester.pumpWidget(
        MaterialApp(
          home: RecipeActionsScreen(recipe: _recipe(), controller: controller),
        ),
      );
      await tester.tap(find.text('Check pantry ingredients'));
      await tester.pumpAndSettle();
      expect(gateway.checks, 1);
      expect(gateway.submissions, isEmpty);
      final items = tester
          .widgetList<CheckboxListTile>(find.byType(CheckboxListTile))
          .toList();
      expect(items.every((item) => !item.value!), isTrue);
      expect(items[1].onChanged, isNull);
      expect(items[2].onChanged, isNull);
      expect(find.textContaining('missing amount is Unknown'), findsOneWidget);
      await tester.tap(find.text('Lentils'));
      await tester.pumpAndSettle();
      expect(gateway.submissions, isEmpty);
      await tester.tap(find.text('Add 1 selected missing ingredients'));
      await tester.pumpAndSettle();
      expect(gateway.submissions.single.body['ingredient_keys'], ['missing']);
      expect(gateway.submissions.single.body['check_token'], _checkToken);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
    },
  );

  testWidgets(
    'diary shows recipe servings and unknown mass without fabricated grams',
    (tester) async {
      final api = ProductApi(
        ApiClient(
          baseUrl: 'https://api.example',
          client: MockClient(
            (request) async => http.Response(
              jsonEncode([
                {
                  'id': 'd1',
                  'name': 'Recipe unknown evidence',
                  'eaten_at': '2026-09-05T09:00:00Z',
                  'source': 'CUSTOM_RECIPE',
                  'recipe_id': _recipeId,
                  'recipe_version': 2,
                  'recipe_servings': 2,
                  'serving_grams': null,
                  'nutrients': {'calories': null},
                },
              ]),
              200,
            ),
          ),
        ),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: DiaryScreen(products: api)),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.text('2 recipe servings · mass Unknown · Unknown kcal'),
        findsOneWidget,
      );
      expect(find.textContaining('100 g'), findsNothing);
    },
  );
}
