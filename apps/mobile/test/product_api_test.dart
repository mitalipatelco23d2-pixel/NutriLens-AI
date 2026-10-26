import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/intelligence_api.dart';
import 'package:nutrilens_x/services/product_api.dart';
import 'package:nutrilens_x/services/weight_models.dart';

void main() {
  test('profile snapshot preserves bounded custom goal intent', () {
    final profile = ProfileSnapshot.fromJson({
      'goal': 'custom',
      'custom_goal': 'Cook at home more often',
      'allergens': <String>[],
      'dietary_preferences': <String>[],
      'consent_personalization': true,
    });

    expect(profile.customGoal, 'Cook at home more often');
    expect(profile.toJson()['custom_goal'], 'Cook at home more often');
    expect(wellnessGoalLabel('lose-weight-gradually'), 'Lose weight gradually');
  });

  test('weight contracts preserve unknowns and owner-entered records', () {
    final summary = WeightSummary.fromJson({
      'state': 'ACTIVE',
      'target_weight_kg': 68.5,
      'latest_weight_kg': 69.25,
      'change_from_first_kg': -0.75,
      'difference_from_target_kg': 0.75,
      'entries': [
        {
          'id': 'entry-1',
          'weight_kg': 69.25,
          'recorded_at': '2026-09-23T08:00:00Z',
          'source': 'USER_ENTERED',
        },
      ],
      'method': 'SELF_REPORTED_WEIGHT_DIFFERENCE_V1',
      'limitation': 'Descriptive only.',
    });

    expect(summary.latestWeightKg, 69.25);
    expect(summary.entries.single.toJson()['weight_kg'], 69.25);
    expect(summary.differenceFromTargetKg, 0.75);
  });

  test('loads diary, analytics, assistant, and billing contracts', () async {
    String? assistantBody;
    String? accountProfileBody;
    String? revokedSessionPath;
    final client = MockClient((request) async {
      if (request.url.path == '/api/v1/assistant/messages') {
        assistantBody = request.body;
      }
      if (request.url.path == '/api/v1/account/profile' &&
          request.method == 'PUT') {
        accountProfileBody = request.body;
      }
      if (request.method == 'DELETE' &&
          request.url.path.startsWith('/api/v1/auth/sessions/')) {
        revokedSessionPath = request.url.path;
      }
      return switch (request.url.path) {
        '/api/v1/diary' => http.Response(_diary, 200),
        '/api/v1/diary/compare' => http.Response(_mealComparison, 200),
        '/api/v1/analytics/summary' => http.Response(_analytics, 200),
        '/api/v1/analytics/compare' => http.Response(_analyticsComparison, 200),
        '/api/v1/analytics/drilldown' => http.Response(_drilldown, 200),
        '/api/v1/analytics/patterns' => http.Response(_patterns, 200),
        '/api/v1/assistant/messages' => http.Response(_assistant, 200),
        '/api/v1/payments/account' => http.Response(_billing, 200),
        '/api/v1/notifications' => http.Response(_notifications, 200),
        '/api/v1/notifications/n1/read' => http.Response(
          _readNotification,
          200,
        ),
        '/api/v1/notifications/read-all' => http.Response('{"updated":1}', 200),
        '/api/v1/profile' => http.Response(_profile, 200),
        '/api/v1/account/profile' => http.Response(
          _accountProfile,
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        ),
        '/api/v1/auth/sessions' => http.Response(_accountSessions, 200),
        '/api/v1/auth/sessions/session-other' => http.Response('', 204),
        '/api/v1/profile/bmi-context' => http.Response(_bmiContext, 200),
        '/api/v1/weight' => http.Response(_weightSummary, 200),
        '/api/v1/weight/settings' =>
          request.method == 'DELETE'
              ? http.Response('', 204)
              : http.Response(_weightSettings, 200),
        '/api/v1/weight/entries' => http.Response(_weightEntry, 201),
        '/api/v1/weight/entries/weight-1' =>
          request.method == 'DELETE'
              ? http.Response('', 204)
              : http.Response(_weightEntry, 200),
        '/api/v1/profile/household' => http.Response(
          request.method == 'GET' ? _householdProfiles : _householdProfile,
          request.method == 'POST' ? 201 : 200,
        ),
        '/api/v1/profile/household/hp-1' =>
          request.method == 'DELETE'
              ? http.Response('', 204)
              : http.Response(_updatedHouseholdProfile, 200),
        '/api/v1/favorites' => http.Response(_favorites, 200),
        '/api/v1/scan/history' => http.Response(_scanHistory, 200),
        '/api/v1/favorites/scan-1' =>
          request.method == 'DELETE'
              ? http.Response('', 204)
              : http.Response(_favorite, 200),
        '/api/v1/search' => http.Response(_search, 200),
        '/api/v1/account/export' => http.Response(_accountExport, 200),
        '/api/v1/account' => http.Response('', 204),
        '/api/v1/recipes/recommendations' => http.Response(_recipes, 200),
        '/api/v1/recipes/use-soon' => http.Response(_useSoonRecipes, 200),
        '/api/v1/recipes/compare' => http.Response(_recipeComparison, 200),
        '/api/v1/pantry' => http.Response(
          request.method == 'GET' ? _pantry : _updatedPantry,
          request.method == 'POST' ? 201 : 200,
        ),
        '/api/v1/pantry/p1' =>
          request.method == 'DELETE'
              ? http.Response('', 204)
              : http.Response(_updatedPantry, 200),
        '/api/v1/shopping-list' => http.Response(
          request.method == 'GET' ? _shoppingList : _shoppingItem,
          request.method == 'POST' ? 201 : 200,
        ),
        '/api/v1/shopping-list/s1' =>
          request.method == 'DELETE'
              ? http.Response('', 204)
              : http.Response(_checkedShoppingItem, 200),
        '/api/v1/shopping-list/from-low-stock' => http.Response(
          _shoppingGeneration,
          200,
        ),
        _ => http.Response('{"detail":"not found"}', 404),
      };
    });
    final api = ProductApi(
      ApiClient(baseUrl: 'https://api.example', client: client),
    );

    expect((await api.diary()).single.name, 'Oats');
    final comparison = await api.compareDiary(['d1', 'd2']);
    expect(comparison.candidates.first.per100g.calories, 200);
    expect(comparison.limitation, contains('no meal is ranked'));
    final analytics = await api.analytics();
    expect(analytics.dailyAverages.proteinG, 7);
    expect(analytics.dailyAverages.calciumMg, 120);
    expect(analytics.goalTrackingState, 'AVAILABLE');
    expect(analytics.goalProgress.single.percentOfTarget, 50);
    final analyticsComparison = await api.analyticsComparison(days: 7);
    expect(analyticsComparison.state, 'AVAILABLE');
    expect(analyticsComparison.current.loggedDays, 2);
    expect(analyticsComparison.stories.last.evidence, contains('higher'));
    expect(
      analyticsComparison.limitation,
      contains('does not assess improvement'),
    );
    final drilldown = await api.analyticsDrilldown(days: 7);
    expect(drilldown.entries.single.name, 'Oats');
    expect(drilldown.periodDays, 7);
    final patterns = await api.dietaryPatterns(days: 7);
    expect(patterns.state, 'AVAILABLE');
    expect(patterns.observations.single.kind, 'LOGGING_COVERAGE');
    final profile = await api.profile();
    expect(profile.dailyTargets['calcium_mg'], 240);
    expect(profile.bodyContext.heightCm, 175);
    expect((await api.saveProfile(profile)).dailyTargets.length, 1);
    final weight = await api.weightSummary();
    expect(weight.latestWeightKg, 69.25);
    expect((await api.enableWeightTracking(68.5)).state, 'ACTIVE');
    final weightEntry = weight.entries.single;
    expect((await api.addWeight(weightEntry)).weightKg, 69.25);
    expect((await api.updateWeight(weightEntry)).source, 'USER_ENTERED');
    await api.deleteWeight(weightEntry.id);
    await api.disableWeightTracking();
    final accountProfile = await api.accountProfile();
    expect(accountProfile.fullName, 'Yash Owner');
    expect(accountProfile.maskedPhoneNumber, '+••••••••3210');
    expect(accountProfile.phoneState, 'UNVERIFIED');
    expect(accountProfile.onboardingComplete, isTrue);
    await api.saveAccountProfile(
      fullName: 'Yash Owner',
      dateOfBirth: DateTime(1990, 1, 2),
      phoneUpdate: 'SET',
      phoneNumber: '+919876543210',
      countryRegion: 'IN',
      unitSystem: 'METRIC',
      researchInsightsConsent: false,
      completeOnboarding: true,
    );
    final accountPayload =
        jsonDecode(accountProfileBody!) as Map<String, dynamic>;
    expect(accountPayload['date_of_birth'], '1990-01-02');
    expect(accountPayload['phone_number'], '+919876543210');
    expect(accountPayload['phone_update'], 'SET');
    final sessions = await api.accountSessions();
    expect(sessions.length, 2);
    expect(sessions.first.current, isTrue);
    expect(sessions.last.id, 'session-other');
    await api.revokeAccountSession('session-other');
    expect(revokedSessionPath, '/api/v1/auth/sessions/session-other');
    final bmi = await api.bmiContext();
    expect(bmi.state, 'AVAILABLE');
    expect(bmi.bmi, 22.86);
    expect(bmi.limitation, contains('does not assign a category'));
    final household = await api.householdProfiles();
    expect(household.single.displayName, 'Sam');
    expect(household.single.profile.consentPersonalization, isFalse);
    final added = await api.saveHouseholdProfile(
      displayName: 'Sam',
      relationship: 'Partner',
      profile: profile,
    );
    expect(added.relationship, 'Partner');
    final updated = await api.saveHouseholdProfile(
      id: 'hp-1',
      displayName: 'Samira',
      profile: profile,
    );
    expect(updated.displayName, 'Samira');
    await api.deleteHouseholdProfile('hp-1');
    expect((await api.favorites()).single.productName, 'Owner oats');
    expect((await api.scanHistory()).single.productName, 'Owner oats');
    expect((await api.saveFavorite('scan-1')).scanId, 'scan-1');
    await api.removeFavorite('scan-1');
    expect((await api.search('oat')).items.single.kind, 'SCAN');
    final recipes = await api.recipes();
    expect(
      recipes.single.substitutions.single.availableAlternative,
      'white beans',
    );
    expect(recipes.single.preparationComplexity.band, 'BASIC');
    final useSoon = await api.useSoonRecipes();
    expect(useSoon.suggestions.single.attentionItems.single.name, 'Chickpea');
    expect(useSoon.limitation, contains('never use expired'));
    final recipeComparison = await api.compareRecipeNutrition([
      const RecipeNutritionInput(
        name: 'Bean stew',
        servings: 4,
        nutrients: Nutrients(calories: 1200, proteinG: 60),
      ),
      const RecipeNutritionInput(
        name: 'Soup',
        servings: 2,
        nutrients: Nutrients(calories: 500, proteinG: 20),
      ),
    ]);
    expect(recipeComparison.candidates.first.perServing.calories, 300);
    expect(recipeComparison.candidates.first.recipeTotal.proteinG, 60);
    expect(recipeComparison.limitation, contains('no recipe is ranked'));
    final pantry = await api.pantry();
    expect(pantry.single.lowStockThreshold, 2);
    expect(pantry.single.itemRole, 'LEFTOVER');
    expect(
      (await api.addPantry(
        name: 'Rice',
        quantity: 1,
        unit: 'kg',
        lowStockThreshold: 2,
      )).lowStockThreshold,
      2,
    );
    expect((await api.updatePantry('p1', quantity: 3)).quantity, 3);
    await api.deletePantry('p1');
    expect((await api.shoppingList()).single.source, 'LOW_STOCK');
    expect((await api.addShoppingListItem('Rice')).name, 'Rice');
    expect(
      (await api.updateShoppingListItem('s1', checked: true)).checked,
      isTrue,
    );
    expect((await api.generateShoppingListFromLowStock()).generatedCount, 1);
    await api.deleteShoppingListItem('s1');
    final assistant = await api.askAssistant('What is this?', scanId: 'scan-1');
    expect(assistant.remainingToday, 4);
    expect(assistant.citations.single.authority, 'ICMR');
    expect(assistant.generationMode, 'DETERMINISTIC');
    expect(jsonDecode(assistantBody!)['scan_id'], 'scan-1');
    expect((await api.billing()).subscriptionStatus, 'ACTIVE');
    expect((await api.notifications()).single.readAt, isNull);
    expect((await api.markNotificationRead('n1')).readAt, isNotNull);
    await api.markAllNotificationsRead();
    expect((await api.exportAccount())['account'], isA<Map<String, dynamic>>());
    await api.deleteAccount();
  });

  test('parses governed R4 evidence and personalized findings', () async {
    final client = MockClient((request) async {
      if (request.url.path.contains('ingredient-intelligence')) {
        return http.Response(_intelligence, 200);
      }
      if (request.url.path.endsWith('/counterfactuals')) {
        return http.Response(_counterfactuals, 200);
      }
      return http.Response(_recommendations, 200);
    });
    final api = IntelligenceApi(
      ApiClient(baseUrl: 'https://api.example', client: client),
    );

    final intelligence = await api.ingredients('scan-1');
    final recommendations = await api.recommendations('scan-1');
    final counterfactuals = await api.counterfactuals('scan-1');
    expect(intelligence.ingredients, ['Oats']);
    expect(intelligence.allergens, ['Milk']);
    expect(intelligence.novaGroup, 'Processed foods');
    expect(recommendations.findings.single, contains('Profile match'));
    expect(counterfactuals.state, 'AVAILABLE');
    expect(counterfactuals.factors.single, contains('from 1 to 0'));
    expect(counterfactuals.limitation, contains('do not predict'));
  });
}

const _counterfactuals = '''
{"scan_id":"scan-1","state":"AVAILABLE","factors":[{"factor_id":"hidden-sugars","label":"Recognized sugar-source signals","observed_evidence":["sugar"],"hypothesis":"If this evidence were absent...","result_change":"The displayed count would change from 1 to 0. No other result is inferred.","method":"SINGLE_OBSERVED_SIGNAL_CATEGORY_ABLATION_V1"}],"limitation":"These hypothetical removals do not predict health outcomes."}
''';

const _accountExport = '''
{"exported_at":"2026-09-07T00:00:00Z","account":{"id":"owner"},"diary":[]}
''';

const _diary = '''
[{"id":"d1","name":"Oats","serving_grams":100,"nutrients":{"calories":200,"protein_g":7}}]
''';

const _analytics = '''
{"period_days":30,"diary_entries":1,"totals":{"calories":200,"protein_g":7,"calcium_mg":120},"daily_averages":{"calories":200,"protein_g":7,"calcium_mg":120},"insights":["One entry logged."],"goal_tracking_state":"AVAILABLE","goal_progress":[{"nutrient":"calcium_mg","label":"Calcium","unit":"mg","daily_average":120,"user_target":240,"percent_of_target":50}],"goal_tracking_limitation":"User-entered reference only."}
''';

const _analyticsComparison = '''
{"state":"AVAILABLE","period_days":7,"current":{"first_date":"2026-08-21","last_date":"2026-08-27","logged_days":2,"diary_entries":2,"daily_averages":{"calories":200}},"previous":{"first_date":"2026-08-14","last_date":"2026-08-20","logged_days":1,"diary_entries":1,"daily_averages":{"calories":100}},"changes":[{"nutrient":"calories","label":"Energy","unit":"kcal/day","direction":"HIGHER","absolute_change":100,"percent_change":100}],"stories":[{"kind":"PERIOD_COVERAGE","title":"Logged-day coverage","evidence":"Current window has 2 logged days.","supporting_records":3},{"kind":"RECORDED_AVERAGE_CHANGE","title":"Energy recorded average","evidence":"The logged daily energy average was 100 kcal/day higher than in the adjacent previous window.","supporting_records":3}],"method":"OWNER_DIARY_EQUAL_WINDOW_DESCRIPTIVE_COMPARISON_V1","limitation":"It does not assess improvement, health or causation."}
''';

const _mealComparison = '''
{"candidates":[{"entry_id":"d1","name":"Oats","serving_grams":100,"logged_serving":{"calories":200,"protein_g":7},"per_100g":{"calories":200,"protein_g":7}},{"entry_id":"d2","name":"Lunch","serving_grams":200,"logged_serving":{"calories":400,"protein_g":20},"per_100g":{"calories":200,"protein_g":10}}],"compared_nutrients":["calories","protein_g"],"method":"DIRECT_LOGGED_NUTRIENT_COMPARISON_V1","limitation":"Recorded values only; no meal is ranked as healthier."}
''';

const _drilldown = '''
{"period_days":7,"selected_date":null,"entries":[{"id":"d1","name":"Oats","eaten_at":"2026-08-27T08:00:00Z","serving_grams":100,"nutrients":{"calories":200,"protein_g":7}}],"method":"OWNER_SCOPED_DIARY_RECORD_DRILLDOWN_V1","limitation":"Underlying user-recorded diary entries."}
''';

const _patterns = '''
{"period_days":7,"state":"AVAILABLE","observed_days":7,"minimum_observed_days":7,"observations":[{"kind":"LOGGING_COVERAGE","label":"Logged-day coverage","evidence":"Entries were recorded on 7 of 7 days.","supporting_records":7}],"method":"DESCRIPTIVE_OWNER_DIARY_PATTERN_ANALYSIS_V1","limitation":"Does not classify a diet or assess adequacy."}
''';

const _profile = '''
{"goal":"balanced","allergens":[],"dietary_preferences":[],"consent_personalization":true,"daily_targets":{"calcium_mg":240,"iron_mg":null},"body_context":{"adult_attestation":true,"consent_bmi_context":true,"height_cm":175,"weight_kg":70}}
''';

const _accountProfile = '''
{"full_name":"Yash Owner","date_of_birth":"1990-01-02","masked_phone_number":"+••••••••3210","phone_state":"UNVERIFIED","phone_verification_availability":"BLOCKED_EXTERNAL_COST","country_region":"IN","unit_system":"METRIC","research_insights_consent":false,"onboarding_complete":true}
''';

const _accountSessions = '''
[{"id":"session-current","current":true,"created_at":"2026-09-07T08:00:00Z","last_seen_at":"2026-09-07T09:00:00Z","expires_at":"2026-09-07T10:00:00Z"},{"id":"session-other","current":false,"created_at":"2026-09-06T08:00:00Z","last_seen_at":"2026-09-06T09:00:00Z","expires_at":"2026-09-07T10:00:00Z"}]
''';

const _bmiContext = '''
{"state":"AVAILABLE","bmi":22.86,"height_cm":175,"weight_kg":70,"method":"SELF_REPORTED_ADULT_BMI_FORMULA_V1","reference_url":"https://www.who.int/news-room/fact-sheets/detail/obesity-and-overweight","limitation":"BMI is a weight-for-height surrogate; NutriLens does not assign a category."}
''';

const _weightSummary = '''
{"state":"ACTIVE","target_weight_kg":68.5,"latest_weight_kg":69.25,"change_from_first_kg":-0.75,"difference_from_target_kg":0.75,"entries":[{"id":"weight-1","weight_kg":69.25,"recorded_at":"2026-09-23T08:00:00Z","source":"USER_ENTERED"}],"method":"SELF_REPORTED_WEIGHT_DIFFERENCE_V1","limitation":"Descriptive self-reported records only."}
''';

const _weightSettings = '''
{"state":"ACTIVE","target_weight_kg":68.5}
''';

const _weightEntry = '''
{"id":"weight-1","weight_kg":69.25,"recorded_at":"2026-09-23T08:00:00Z","source":"USER_ENTERED"}
''';

const _householdProfiles = '''
[{"id":"hp-1","display_name":"Sam","relationship":"Partner","profile":{"goal":"low-sodium","allergens":["peanut"],"dietary_preferences":[],"consent_personalization":false,"daily_targets":{}},"created_at":"2026-08-27T08:00:00Z","updated_at":"2026-08-27T08:00:00Z"}]
''';

const _householdProfile = '''
{"id":"hp-1","display_name":"Sam","relationship":"Partner","profile":{"goal":"balanced","allergens":[],"dietary_preferences":[],"consent_personalization":true,"daily_targets":{"calcium_mg":240}},"created_at":"2026-08-27T08:00:00Z","updated_at":"2026-08-27T08:00:00Z"}
''';

const _updatedHouseholdProfile = '''
{"id":"hp-1","display_name":"Samira","relationship":null,"profile":{"goal":"balanced","allergens":[],"dietary_preferences":[],"consent_personalization":true,"daily_targets":{"calcium_mg":240}},"created_at":"2026-08-27T08:00:00Z","updated_at":"2026-08-27T09:00:00Z"}
''';

const _favorites = '''
[{"scan_id":"scan-1","product_name":"Owner oats","brand":"Example","saved_at":"2026-08-26T08:00:00Z"}]
''';

const _favorite = '''
{"scan_id":"scan-1","product_name":"Owner oats","brand":"Example","saved_at":"2026-08-26T08:00:00Z"}
''';

const _scanHistory = '''
[{"scan_id":"scan-1","created_at":"2026-08-27T08:00:00Z","input_kind":"PRODUCT","status":"COMPLETED","product_name":"Owner oats","brand":"Example","confidence":0.87}]
''';

const _search = '''
{"query":"oat","items":[{"kind":"SCAN","id":"scan-1","title":"Owner oats","subtitle":"Example","score":1.0}],"limitation":"Owner scans and governed records only."}
''';

const _recipes = '''
[{"recipe_id":"salad","title":"Bean salad","coverage":0.5,"missing_required":["chickpea"],"available_substitutions":[{"missing_ingredient":"chickpea","available_alternative":"white beans","function":"cooked legume base","limitation":"Texture differs."}],"source_version":"0.2.0","preparation_complexity":{"band":"BASIC","written_steps":2,"required_ingredients":2,"limitation":"Structural estimate only."}}]
''';

const _recipeComparison = '''
{"candidates":[{"name":"Bean stew","servings":4,"nutrients":{"calories":1200,"protein_g":60},"source_label":"User-entered recipe totals","per_serving":{"calories":300,"protein_g":15}},{"name":"Soup","servings":2,"nutrients":{"calories":500,"protein_g":20},"source_label":"User-entered recipe totals","per_serving":{"calories":250,"protein_g":10}}],"compared_nutrients":["calories","protein_g"],"method":"DIRECT_USER_SUPPLIED_RECIPE_NUTRIENT_COMPARISON_V1","limitation":"Results depend on supplied totals; no recipe is ranked as healthier."}
''';

const _pantry = '''
[{"id":"p1","name":"Rice","quantity":1,"unit":"kg","expires_on":null,"low_stock_threshold":2,"item_role":"LEFTOVER"}]
''';

const _updatedPantry = '''
{"id":"p1","name":"Rice","quantity":3,"unit":"kg","expires_on":null,"low_stock_threshold":2,"item_role":"INGREDIENT"}
''';

const _shoppingList = '''
[{"id":"s1","name":"Rice","checked":false,"source":"LOW_STOCK","pantry_item_id":"p1","created_at":"2026-08-27T08:00:00Z"}]
''';

const _shoppingItem = '''
{"id":"s1","name":"Rice","checked":false,"source":"MANUAL","pantry_item_id":null,"created_at":"2026-08-27T08:00:00Z"}
''';

const _checkedShoppingItem = '''
{"id":"s1","name":"Rice","checked":true,"source":"LOW_STOCK","pantry_item_id":"p1","created_at":"2026-08-27T08:00:00Z"}
''';

const _shoppingGeneration = '''
{"generated_count":1,"items":[{"id":"s1","name":"Rice","checked":false,"source":"LOW_STOCK","pantry_item_id":"p1","created_at":"2026-08-27T08:00:00Z"}],"method":"USER_DEFINED_LOW_STOCK_TO_SHOPPING_LIST_V1","limitation":"Verify amount before shopping."}
''';

const _useSoonRecipes = '''
{"suggestions":[{"recipe":{"recipe_id":"salad","title":"Bean salad","coverage":0.5,"missing_required":[],"available_substitutions":[],"source_version":"0.2.0","preparation_complexity":{"band":"BASIC","written_steps":2,"required_ingredients":2,"limitation":"Structural estimate only."}},"attention_items":[{"pantry_item_id":"p1","name":"Chickpea","reasons":["USER_MARKED_LEFTOVER"]}]}],"method":"USER_MARKED_LEFTOVER_AND_EXPIRY_TEMPLATE_MATCH_V1","limitation":"Check condition first; never use expired or spoiled food."}
''';

const _assistant = '''
{"answer":"Evidence-based answer.","evidence":["Label text"],"citations":[{"evidence_id":"icmr-1","title":"Dietary guidance","authority":"ICMR","url":"https://example.org/icmr"}],"remaining_today":4,"generation_mode":"DETERMINISTIC","method":"GOVERNED_RETRIEVAL","disclaimer":"Wellness guidance only."}
''';

const _billing = '''
{"plan":"PRO","subscription_status":"ACTIVE","subscription":{"provider_subscription_id":"sub_1"},"payments":[],"mode":"test"}
''';

const _notifications = '''
[{"id":"n1","kind":"PANTRY_EXPIRY","title":"Use spinach soon","body":"Verify the package date.","created_at":"2026-08-25T10:00:00Z","read_at":null}]
''';

const _readNotification = '''
{"id":"n1","kind":"PANTRY_EXPIRY","title":"Use spinach soon","body":"Verify the package date.","created_at":"2026-08-25T10:00:00Z","read_at":"2026-08-25T10:10:00Z"}
''';

const _intelligence = '''
{
  "ingredient_matches":[{"ingredient":{"normalized_text":"oats"},"taxonomy":{"canonical_name":"Oats"}}],
  "additives":[],
  "allergens":[{"ingredient":{"normalized_text":"milk"},"allergen":{"canonical_name":"Milk"}}],
  "nova":{"group_number":3,"canonical_name":"Processed foods"},
  "warnings":[]
}
''';

const _recommendations = '''
{"findings":[{"level":"INFO","title":"Profile match","explanation":"Matches your preferences."}],"disclaimer":"Wellness guidance only."}
''';
