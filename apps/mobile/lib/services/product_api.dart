import 'api_client.dart';
import 'hydration_models.dart';
import 'custom_recipe_models.dart';
import 'recipe_action_models.dart';
import 'weight_models.dart';

const wellnessGoalLabels = <String, String>{
  'balanced': 'Balanced eating',
  'maintain-weight': 'Maintain weight',
  'lose-weight-gradually': 'Lose weight gradually',
  'gain-weight-gradually': 'Gain weight gradually',
  'improve-nutrition': 'Improve nutrition',
  'high-protein': 'Higher protein preference',
  'low-sugar': 'Lower sugar preference',
  'low-sodium': 'Lower sodium preference',
  'custom': 'Custom goal',
};

String wellnessGoalLabel(String goal) => wellnessGoalLabels[goal] ?? goal;

class Nutrients {
  const Nutrients({
    this.calories,
    this.proteinG,
    this.carbsG,
    this.fatG,
    this.sugarG,
    this.sodiumMg,
    this.fiberG,
    this.vitaminAMcg,
    this.vitaminCMg,
    this.vitaminDMcg,
    this.calciumMg,
    this.ironMg,
    this.potassiumMg,
    this.zincMg,
  });

  factory Nutrients.fromJson(Map<String, dynamic> json) => Nutrients(
    calories: _nullableNumber(json['calories']),
    proteinG: _nullableNumber(json['protein_g']),
    carbsG: _nullableNumber(json['carbs_g']),
    fatG: _nullableNumber(json['fat_g']),
    sugarG: _nullableNumber(json['sugar_g']),
    sodiumMg: _nullableNumber(json['sodium_mg']),
    fiberG: _nullableNumber(json['fiber_g']),
    vitaminAMcg: _nullableNumber(json['vitamin_a_mcg']),
    vitaminCMg: _nullableNumber(json['vitamin_c_mg']),
    vitaminDMcg: _nullableNumber(json['vitamin_d_mcg']),
    calciumMg: _nullableNumber(json['calcium_mg']),
    ironMg: _nullableNumber(json['iron_mg']),
    potassiumMg: _nullableNumber(json['potassium_mg']),
    zincMg: _nullableNumber(json['zinc_mg']),
  );

  final double? calories;
  final double? proteinG;
  final double? carbsG;
  final double? fatG;
  final double? sugarG;
  final double? sodiumMg;
  final double? fiberG;
  final double? vitaminAMcg;
  final double? vitaminCMg;
  final double? vitaminDMcg;
  final double? calciumMg;
  final double? ironMg;
  final double? potassiumMg;
  final double? zincMg;

  Map<String, dynamic> toJson() => {
    'calories': calories,
    'protein_g': proteinG,
    'carbs_g': carbsG,
    'fat_g': fatG,
    'sugar_g': sugarG,
    'sodium_mg': sodiumMg,
    'fiber_g': fiberG,
    'vitamin_a_mcg': vitaminAMcg,
    'vitamin_c_mg': vitaminCMg,
    'vitamin_d_mcg': vitaminDMcg,
    'calcium_mg': calciumMg,
    'iron_mg': ironMg,
    'potassium_mg': potassiumMg,
    'zinc_mg': zincMg,
  };
}

double _number(Object? value) => (value as num?)?.toDouble() ?? 0;
double? _nullableNumber(Object? value) => (value as num?)?.toDouble();
Map<String, dynamic> _stringKeyedMap(Object? value) {
  if (value is Map<String, dynamic>) {
    return value;
  }
  if (value is Map<Object?, Object?> &&
      value.keys.every((key) => key is String)) {
    return Map<String, dynamic>.from(value);
  }
  return const <String, dynamic>{};
}

String nutrientEvidence(double? value, {int decimals = 1}) =>
    value == null ? 'Unknown' : value.toStringAsFixed(decimals);

class DiaryEntry {
  const DiaryEntry({
    required this.id,
    required this.name,
    required this.eatenAt,
    required this.servingGrams,
    required this.nutrients,
    this.recipeId,
    this.recipeVersion,
    this.recipeServings,
    this.source,
    this.scanId,
  });

  factory DiaryEntry.fromJson(Map<String, dynamic> json) => DiaryEntry(
    id: json['id'] as String,
    name: json['name'] as String,
    eatenAt: json['eaten_at']?.toString() ?? '',
    servingGrams: _nullableNumber(json['serving_grams']),
    scanId: json['scan_id'] as String?,
    recipeId: json['recipe_id'] as String?,
    recipeVersion: json['recipe_version'] as int?,
    recipeServings: _nullableNumber(json['recipe_servings']),
    source: json['source'] as String?,
    nutrients: Nutrients.fromJson(_stringKeyedMap(json['nutrients'])),
  );

  final String id;
  final String name;
  final String eatenAt;
  final double? servingGrams;
  final Nutrients nutrients;
  final String? scanId;
  final String? recipeId;
  final int? recipeVersion;
  final double? recipeServings;
  final String? source;

  String get servingDescription => recipeServings != null
      ? '${recipeNumber(recipeServings!)} recipe servings · mass ${servingGrams == null ? 'Unknown' : '${recipeNumber(servingGrams!)} g'}'
      : servingGrams == null
      ? 'Serving mass unknown'
      : '${recipeNumber(servingGrams!)} g';
}

class MealComparisonCandidate {
  const MealComparisonCandidate({
    required this.entryId,
    required this.name,
    required this.servingGrams,
    required this.loggedServing,
    required this.per100g,
  });

  factory MealComparisonCandidate.fromJson(Map<String, dynamic> json) =>
      MealComparisonCandidate(
        entryId: json['entry_id']?.toString() ?? '',
        name: json['name']?.toString() ?? 'Diary entry',
        servingGrams: _nullableNumber(json['serving_grams']),
        loggedServing: Nutrients.fromJson(
          _stringKeyedMap(json['logged_serving']),
        ),
        per100g: Nutrients.fromJson(_stringKeyedMap(json['per_100g'])),
      );

  final String entryId;
  final String name;
  final double? servingGrams;
  final Nutrients loggedServing;
  final Nutrients per100g;

  String get servingDescription => servingGrams == null
      ? 'Serving mass unknown'
      : '${recipeNumber(servingGrams!)} g logged';
}

class MealComparison {
  const MealComparison({required this.candidates, required this.limitation});

  factory MealComparison.fromJson(Map<String, dynamic> json) => MealComparison(
    candidates: (json['candidates'] as List<dynamic>? ?? const [])
        .map(
          (item) =>
              MealComparisonCandidate.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false),
    limitation: json['limitation']?.toString() ?? '',
  );

  final List<MealComparisonCandidate> candidates;
  final String limitation;
}

class PantryItem {
  const PantryItem({
    required this.id,
    required this.name,
    required this.quantity,
    required this.unit,
    this.expiresOn,
    this.lowStockThreshold,
    this.itemRole = 'INGREDIENT',
  });

  factory PantryItem.fromJson(Map<String, dynamic> json) => PantryItem(
    id: json['id'] as String,
    name: json['name'] as String,
    quantity: _number(json['quantity']),
    unit: json['unit']?.toString() ?? 'item',
    expiresOn: json['expires_on']?.toString(),
    lowStockThreshold: json['low_stock_threshold'] == null
        ? null
        : _number(json['low_stock_threshold']),
    itemRole: json['item_role']?.toString() ?? 'INGREDIENT',
  );

  final String id;
  final String name;
  final double quantity;
  final String unit;
  final String? expiresOn;
  final double? lowStockThreshold;
  final String itemRole;
}

class ShoppingListItem {
  const ShoppingListItem({
    required this.id,
    required this.name,
    required this.checked,
    required this.source,
    this.quantity,
    this.unit,
    this.recipeId,
  });

  factory ShoppingListItem.fromJson(Map<String, dynamic> json) {
    final rawSource = json['source']?.toString().toUpperCase() ?? 'USER_ADDED';
    final normalizedSource = switch (rawSource) {
      'MANUAL' => 'USER_ADDED',
      'USER_ADDED' => 'USER_ADDED',
      'LOW_STOCK' => 'LOW_STOCK',
      'RECIPE_PLAN' => 'RECIPE_PLAN',
      'CUSTOM_RECIPE' => 'RECIPE_PLAN',
      _ => rawSource,
    };
    return ShoppingListItem(
      id: json['id'] as String,
      name: json['name'] as String,
      checked: json['checked'] as bool? ?? false,
      source: normalizedSource,
      quantity: _nullableNumber(json['quantity']),
      unit: json['unit'] as String?,
      recipeId: json['recipe_id'] as String?,
    );
  }

  final String id;
  final String name;
  final bool checked;
  final String source;
  final double? quantity;
  final String? unit;
  final String? recipeId;
}

class ShoppingListGeneration {
  const ShoppingListGeneration({
    required this.generatedCount,
    required this.items,
    required this.limitation,
  });

  factory ShoppingListGeneration.fromJson(Map<String, dynamic> json) =>
      ShoppingListGeneration(
        generatedCount: (json['generated_count'] as num?)?.toInt() ?? 0,
        items: (json['items'] as List<dynamic>? ?? const [])
            .map(
              (item) => ShoppingListItem.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
        limitation: json['limitation']?.toString() ?? '',
      );

  final int generatedCount;
  final List<ShoppingListItem> items;
  final String limitation;
}

class RecipeSubstitution {
  const RecipeSubstitution({
    required this.missingIngredient,
    required this.availableAlternative,
    required this.function,
    required this.limitation,
  });

  factory RecipeSubstitution.fromJson(Map<String, dynamic> json) =>
      RecipeSubstitution(
        missingIngredient: json['missing_ingredient']?.toString() ?? '',
        availableAlternative: json['available_alternative']?.toString() ?? '',
        function: json['function']?.toString() ?? '',
        limitation: json['limitation']?.toString() ?? '',
      );

  final String missingIngredient;
  final String availableAlternative;
  final String function;
  final String limitation;
}

class IngredientDeficit {
  const IngredientDeficit({
    required this.name,
    this.requiredAmount,
    this.availableAmount,
    this.deficitAmount,
    this.unit = '',
    this.status = 'AVAILABLE',
  });

  factory IngredientDeficit.fromJson(Map<String, dynamic> json) =>
      IngredientDeficit(
        name: json['ingredient']?.toString() ??
            json['ingredient_name']?.toString() ??
            json['name']?.toString() ??
            '',
        requiredAmount: _nullableNumber(
          json['required_quantity'] ?? json['required_amount'],
        ),
        availableAmount: _nullableNumber(
          json['available_quantity'] ?? json['available_amount'],
        ),
        deficitAmount: _nullableNumber(
          json['missing_quantity'] ??
              json['missing_amount'] ??
              json['deficit_amount'],
        ),
        unit: json['unit']?.toString() ?? '',
        status: json['status']?.toString() ?? 'AVAILABLE',
      );

  final String name;
  final double? requiredAmount;
  final double? availableAmount;
  final double? deficitAmount;
  final String unit;
  final String status;
}

class CompleteRecipeIngredient {
  const CompleteRecipeIngredient({
    required this.name,
    required this.category,
    required this.quantity,
    required this.unit,
    this.isStaple = false,
  });

  factory CompleteRecipeIngredient.fromJson(Map<String, dynamic> json) =>
      CompleteRecipeIngredient(
        name: json['name']?.toString() ?? '',
        category: json['category']?.toString() ?? 'Other',
        quantity: _number(json['quantity']),
        unit: json['unit']?.toString() ?? '',
        isStaple: json['is_staple'] as bool? ?? false,
      );

  final String name;
  final String category;
  final double quantity;
  final String unit;
  final bool isStaple;
}

class RecipeRecommendation {
  const RecipeRecommendation({
    required this.id,
    required this.title,
    required this.coverage,
    required this.missingRequired,
    required this.substitutions,
    required this.sourceVersion,
    required this.preparationComplexity,
    this.requiredIngredients = const [],
    this.deficits = const [],
    this.steps = const [],
    this.servings = 1.0,
    this.nutrientsPerServing,
    this.totalIngredientsCount,
    this.completeIngredients = const [],
    this.nutritionProvenance,
  });

  factory RecipeRecommendation.fromJson(Map<String, dynamic> json) =>
      RecipeRecommendation(
        id: json['recipe_id'] as String,
        title: json['title']?.toString() ?? 'Recipe template',
        coverage: _number(json['coverage']),
        missingRequired: _strings(json['missing_required']),
        substitutions:
            (json['available_substitutions'] as List<dynamic>? ?? const [])
                .map(
                  (item) =>
                      RecipeSubstitution.fromJson(item as Map<String, dynamic>),
                )
                .toList(growable: false),
        sourceVersion: json['source_version']?.toString() ?? '',
        preparationComplexity: PreparationComplexity.fromJson(
          json['preparation_complexity'] as Map<String, dynamic>? ?? const {},
        ),
        requiredIngredients: _strings(json['required_ingredients']),
        deficits: (json['deficits'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(IngredientDeficit.fromJson)
            .toList(growable: false),
        steps: _strings(json['steps']),
        servings: _nullableNumber(json['servings']) ?? 1.0,
        nutrientsPerServing: json['nutrients_per_serving'] is Map<String, dynamic>
            ? Nutrients.fromJson(json['nutrients_per_serving'] as Map<String, dynamic>)
            : null,
        totalIngredientsCount: (json['total_ingredients_count'] as num?)?.toInt(),
        completeIngredients: (json['complete_ingredients'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(CompleteRecipeIngredient.fromJson)
            .toList(growable: false),
        nutritionProvenance: json['nutrition_provenance']?.toString(),
      );

  final String id;
  final String title;
  final double coverage;
  final List<String> missingRequired;
  final List<RecipeSubstitution> substitutions;
  final String sourceVersion;
  final PreparationComplexity preparationComplexity;
  final List<String> requiredIngredients;
  final List<IngredientDeficit> deficits;
  final List<String> steps;
  final double servings;
  final Nutrients? nutrientsPerServing;
  final int? totalIngredientsCount;
  final List<CompleteRecipeIngredient> completeIngredients;
  final String? nutritionProvenance;
}

class PreparationComplexity {
  const PreparationComplexity({
    required this.band,
    required this.writtenSteps,
    required this.requiredIngredients,
    required this.limitation,
  });

  factory PreparationComplexity.fromJson(Map<String, dynamic> json) =>
      PreparationComplexity(
        band: json['band']?.toString() ?? 'UNKNOWN',
        writtenSteps: (json['written_steps'] as num?)?.toInt() ?? 0,
        requiredIngredients:
            (json['required_ingredients'] as num?)?.toInt() ?? 0,
        limitation: json['limitation']?.toString() ?? '',
      );

  final String band;
  final int writtenSteps;
  final int requiredIngredients;
  final String limitation;
}

class PantryAttentionItem {
  const PantryAttentionItem({required this.name, required this.reasons});

  factory PantryAttentionItem.fromJson(Map<String, dynamic> json) =>
      PantryAttentionItem(
        name: json['name']?.toString() ?? '',
        reasons: (json['reasons'] as List<dynamic>? ?? const [])
            .map((reason) => reason.toString())
            .toList(growable: false),
      );

  final String name;
  final List<String> reasons;
}

class UseSoonSuggestion {
  const UseSoonSuggestion({required this.recipe, required this.attentionItems});

  factory UseSoonSuggestion.fromJson(Map<String, dynamic> json) =>
      UseSoonSuggestion(
        recipe: RecipeRecommendation.fromJson(
          json['recipe'] as Map<String, dynamic>,
        ),
        attentionItems: (json['attention_items'] as List<dynamic>? ?? const [])
            .map(
              (item) =>
                  PantryAttentionItem.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
      );

  final RecipeRecommendation recipe;
  final List<PantryAttentionItem> attentionItems;
}

class UseSoonRecipeResponse {
  const UseSoonRecipeResponse({
    required this.suggestions,
    required this.limitation,
  });

  factory UseSoonRecipeResponse.fromJson(Map<String, dynamic> json) =>
      UseSoonRecipeResponse(
        suggestions: (json['suggestions'] as List<dynamic>? ?? const [])
            .map(
              (item) =>
                  UseSoonSuggestion.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
        limitation: json['limitation']?.toString() ?? '',
      );

  final List<UseSoonSuggestion> suggestions;
  final String limitation;
}

class RecipeNutritionInput {
  const RecipeNutritionInput({
    required this.name,
    required this.servings,
    required this.nutrients,
    this.sourceLabel = 'User-entered recipe totals',
  });

  final String name;
  final double servings;
  final Nutrients nutrients;
  final String? sourceLabel;

  Map<String, dynamic> toJson() => {
    'name': name,
    'servings': servings,
    'nutrients': nutrients.toJson(),
    'source_label': sourceLabel,
  };
}

class RecipeNutritionCandidate {
  const RecipeNutritionCandidate({
    required this.name,
    required this.servings,
    required this.recipeTotal,
    required this.perServing,
  });

  factory RecipeNutritionCandidate.fromJson(Map<String, dynamic> json) =>
      RecipeNutritionCandidate(
        name: json['name']?.toString() ?? 'Recipe',
        servings: _number(json['servings']),
        recipeTotal: Nutrients.fromJson(
          json['nutrients'] as Map<String, dynamic>? ?? const {},
        ),
        perServing: Nutrients.fromJson(
          json['per_serving'] as Map<String, dynamic>? ?? const {},
        ),
      );

  final String name;
  final double servings;
  final Nutrients recipeTotal;
  final Nutrients perServing;
}

class RecipeNutritionComparison {
  const RecipeNutritionComparison({
    required this.candidates,
    required this.limitation,
  });

  factory RecipeNutritionComparison.fromJson(Map<String, dynamic> json) =>
      RecipeNutritionComparison(
        candidates: (json['candidates'] as List<dynamic>? ?? const [])
            .map(
              (item) => RecipeNutritionCandidate.fromJson(
                item as Map<String, dynamic>,
              ),
            )
            .toList(growable: false),
        limitation: json['limitation']?.toString() ?? '',
      );

  final List<RecipeNutritionCandidate> candidates;
  final String limitation;
}

class AnalyticsSummary {
  const AnalyticsSummary({
    required this.periodDays,
    required this.diaryEntries,
    required this.totals,
    required this.dailyAverages,
    required this.insights,
    required this.goalTrackingState,
    required this.goalProgress,
    required this.goalTrackingLimitation,
  });

  factory AnalyticsSummary.fromJson(Map<String, dynamic> json) =>
      AnalyticsSummary(
        periodDays: (json['period_days'] as num?)?.toInt() ?? 0,
        diaryEntries: (json['diary_entries'] as num?)?.toInt() ?? 0,
        totals: Nutrients.fromJson(
          json['totals'] as Map<String, dynamic>? ?? const {},
        ),
        dailyAverages: Nutrients.fromJson(
          json['daily_averages'] as Map<String, dynamic>? ?? const {},
        ),
        insights: (json['insights'] as List<dynamic>? ?? const [])
            .map((item) => item.toString())
            .toList(growable: false),
        goalTrackingState:
            json['goal_tracking_state']?.toString() ?? 'NOT_CONFIGURED',
        goalProgress: (json['goal_progress'] as List<dynamic>? ?? const [])
            .map((item) => GoalProgress.fromJson(item as Map<String, dynamic>))
            .toList(growable: false),
        goalTrackingLimitation:
            json['goal_tracking_limitation']?.toString() ??
            'NutriLens does not infer clinical nutrition targets.',
      );

  final int periodDays;
  final int diaryEntries;
  final Nutrients totals;
  final Nutrients dailyAverages;
  final List<String> insights;
  final String goalTrackingState;
  final List<GoalProgress> goalProgress;
  final String goalTrackingLimitation;
}

class AnalyticsPeriodEvidence {
  const AnalyticsPeriodEvidence({
    required this.loggedDays,
    required this.diaryEntries,
  });

  factory AnalyticsPeriodEvidence.fromJson(Map<String, dynamic> json) =>
      AnalyticsPeriodEvidence(
        loggedDays: (json['logged_days'] as num?)?.toInt() ?? 0,
        diaryEntries: (json['diary_entries'] as num?)?.toInt() ?? 0,
      );

  final int loggedDays;
  final int diaryEntries;
}

class AnalyticsStory {
  const AnalyticsStory({
    required this.title,
    required this.evidence,
    required this.supportingRecords,
  });

  factory AnalyticsStory.fromJson(Map<String, dynamic> json) => AnalyticsStory(
    title: json['title']?.toString() ?? '',
    evidence: json['evidence']?.toString() ?? '',
    supportingRecords: (json['supporting_records'] as num?)?.toInt() ?? 0,
  );

  final String title;
  final String evidence;
  final int supportingRecords;
}

class AnalyticsComparison {
  const AnalyticsComparison({
    required this.state,
    required this.periodDays,
    required this.current,
    required this.previous,
    required this.stories,
    required this.limitation,
  });

  factory AnalyticsComparison.fromJson(Map<String, dynamic> json) =>
      AnalyticsComparison(
        state: json['state']?.toString() ?? 'INSUFFICIENT_HISTORY',
        periodDays: (json['period_days'] as num?)?.toInt() ?? 0,
        current: AnalyticsPeriodEvidence.fromJson(
          json['current'] as Map<String, dynamic>,
        ),
        previous: AnalyticsPeriodEvidence.fromJson(
          json['previous'] as Map<String, dynamic>,
        ),
        stories: (json['stories'] as List<dynamic>? ?? const [])
            .map(
              (item) => AnalyticsStory.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
        limitation: json['limitation']?.toString() ?? '',
      );

  final String state;
  final int periodDays;
  final AnalyticsPeriodEvidence current;
  final AnalyticsPeriodEvidence previous;
  final List<AnalyticsStory> stories;
  final String limitation;
}

class FoodNutrientValues {
  const FoodNutrientValues({
    this.energyKcal,
    this.proteinG,
    this.carbohydrateG,
    this.sugarG,
    this.addedSugarG,
    this.fatG,
    this.fiberG,
    this.sodiumMg,
  });

  factory FoodNutrientValues.fromJson(Map<String, dynamic> json) => FoodNutrientValues(
    energyKcal: (json['energy_kcal'] as num?)?.toDouble(),
    proteinG: (json['protein_g'] as num?)?.toDouble(),
    carbohydrateG: (json['carbohydrate_g'] as num?)?.toDouble(),
    sugarG: (json['sugar_g'] as num?)?.toDouble(),
    addedSugarG: (json['added_sugar_g'] as num?)?.toDouble(),
    fatG: (json['fat_g'] as num?)?.toDouble(),
    fiberG: (json['fiber_g'] as num?)?.toDouble(),
    sodiumMg: (json['sodium_mg'] as num?)?.toDouble(),
  );

  final double? energyKcal;
  final double? proteinG;
  final double? carbohydrateG;
  final double? sugarG;
  final double? addedSugarG;
  final double? fatG;
  final double? fiberG;
  final double? sodiumMg;
}

class ScanComparisonCandidate {
  const ScanComparisonCandidate({
    required this.scanId,
    required this.productName,
    required this.rank,
    required this.signalBurden,
    required this.signalCounts,
    required this.evidence,
    required this.limitations,
    this.brandName,
    this.servingSize,
    this.basis,
    required this.nutrientsPer100,
    required this.nutrientsPerServing,
    required this.allergens,
  });

  factory ScanComparisonCandidate.fromJson(Map<String, dynamic> json) => ScanComparisonCandidate(
    scanId: json['scan_id'] as String,
    productName: json['product_name'] as String,
    rank: (json['rank'] as num?)?.toInt() ?? 1,
    signalBurden: (json['signal_burden'] as num?)?.toInt() ?? 0,
    signalCounts: (json['signal_counts'] as Map<String, dynamic>? ?? {})
        .map((k, v) => MapEntry(k, (v as num).toInt())),
    evidence: List<String>.from(json['evidence'] as List? ?? []),
    limitations: List<String>.from(json['limitations'] as List? ?? []),
    brandName: json['brand_name'] as String?,
    servingSize: json['serving_size'] as String?,
    basis: json['basis'] as String?,
    nutrientsPer100: FoodNutrientValues.fromJson(
      Map<String, dynamic>.from(json['nutrients_per_100'] as Map? ?? {}),
    ),
    nutrientsPerServing: FoodNutrientValues.fromJson(
      Map<String, dynamic>.from(json['nutrients_per_serving'] as Map? ?? {}),
    ),
    allergens: List<String>.from(json['allergens'] as List? ?? []),
  );

  final String scanId;
  final String productName;
  final int rank;
  final int signalBurden;
  final Map<String, int> signalCounts;
  final List<String> evidence;
  final List<String> limitations;
  final String? brandName;
  final String? servingSize;
  final String? basis;
  final FoodNutrientValues nutrientsPer100;
  final FoodNutrientValues nutrientsPerServing;
  final List<String> allergens;
}

class ScanComparisonResponse {
  const ScanComparisonResponse({
    required this.candidates,
    this.recommendedScanId,
    required this.profileUsed,
    required this.comparedNutrients,
    required this.method,
    required this.disclaimer,
  });

  factory ScanComparisonResponse.fromJson(Map<String, dynamic> json) => ScanComparisonResponse(
    candidates: (json['candidates'] as List<dynamic>? ?? [])
        .map((c) => ScanComparisonCandidate.fromJson(c as Map<String, dynamic>))
        .toList(growable: false),
    recommendedScanId: json['recommended_scan_id'] as String?,
    profileUsed: json['profile_used'] == true,
    comparedNutrients: List<String>.from(json['compared_nutrients'] as List? ?? []),
    method: json['method']?.toString() ?? '',
    disclaimer: json['disclaimer']?.toString() ?? '',
  );

  final List<ScanComparisonCandidate> candidates;
  final String? recommendedScanId;
  final bool profileUsed;
  final List<String> comparedNutrients;
  final String method;
  final String disclaimer;
}

class AnalyticsDrilldown {
  const AnalyticsDrilldown({
    required this.periodDays,
    required this.entries,
    required this.limitation,
  });

  factory AnalyticsDrilldown.fromJson(Map<String, dynamic> json) =>
      AnalyticsDrilldown(
        periodDays: (json['period_days'] as num?)?.toInt() ?? 0,
        entries: (json['entries'] as List<dynamic>? ?? const [])
            .map((item) => DiaryEntry.fromJson(item as Map<String, dynamic>))
            .toList(growable: false),
        limitation: json['limitation']?.toString() ?? '',
      );

  final int periodDays;
  final List<DiaryEntry> entries;
  final String limitation;
}

class DietaryPatternObservation {
  const DietaryPatternObservation({
    required this.kind,
    required this.label,
    required this.evidence,
    required this.supportingRecords,
  });

  factory DietaryPatternObservation.fromJson(Map<String, dynamic> json) =>
      DietaryPatternObservation(
        kind: json['kind']?.toString() ?? '',
        label: json['label']?.toString() ?? '',
        evidence: json['evidence']?.toString() ?? '',
        supportingRecords: (json['supporting_records'] as num?)?.toInt() ?? 0,
      );

  final String kind;
  final String label;
  final String evidence;
  final int supportingRecords;
}

class DietaryPatterns {
  const DietaryPatterns({
    required this.periodDays,
    required this.state,
    required this.observedDays,
    required this.minimumObservedDays,
    required this.observations,
    required this.limitation,
  });

  factory DietaryPatterns.fromJson(
    Map<String, dynamic> json,
  ) => DietaryPatterns(
    periodDays: (json['period_days'] as num?)?.toInt() ?? 0,
    state: json['state']?.toString() ?? 'INSUFFICIENT_HISTORY',
    observedDays: (json['observed_days'] as num?)?.toInt() ?? 0,
    minimumObservedDays: (json['minimum_observed_days'] as num?)?.toInt() ?? 7,
    observations: (json['observations'] as List<dynamic>? ?? const [])
        .map(
          (item) =>
              DietaryPatternObservation.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false),
    limitation: json['limitation']?.toString() ?? '',
  );

  final int periodDays;
  final String state;
  final int observedDays;
  final int minimumObservedDays;
  final List<DietaryPatternObservation> observations;
  final String limitation;
}

class GoalProgress {
  const GoalProgress({
    required this.nutrient,
    required this.label,
    required this.unit,
    required this.dailyAverage,
    required this.userTarget,
    required this.percentOfTarget,
  });

  factory GoalProgress.fromJson(Map<String, dynamic> json) => GoalProgress(
    nutrient: json['nutrient']?.toString() ?? '',
    label: json['label']?.toString() ?? '',
    unit: json['unit']?.toString() ?? '',
    dailyAverage: _nullableNumber(json['daily_average']),
    userTarget: _number(json['user_target']),
    percentOfTarget: _nullableNumber(json['percent_of_target']),
  );

  final String nutrient;
  final String label;
  final String unit;
  final double? dailyAverage;
  final double userTarget;
  final double? percentOfTarget;

  String get progressDescription => percentOfTarget == null
      ? '$label: progress unknown because logged evidence is incomplete.'
      : '$label: ${nutrientEvidence(dailyAverage)} of $userTarget $unit '
            '(${nutrientEvidence(percentOfTarget, decimals: 0)}%)';
}

class SelfReportedBodyContext {
  const SelfReportedBodyContext({
    this.adultAttestation = false,
    this.consentBmiContext = false,
    this.heightCm,
    this.weightKg,
  });

  factory SelfReportedBodyContext.fromJson(Map<String, dynamic> json) =>
      SelfReportedBodyContext(
        adultAttestation: json['adult_attestation'] == true,
        consentBmiContext: json['consent_bmi_context'] == true,
        heightCm: (json['height_cm'] as num?)?.toDouble(),
        weightKg: (json['weight_kg'] as num?)?.toDouble(),
      );

  final bool adultAttestation;
  final bool consentBmiContext;
  final double? heightCm;
  final double? weightKg;

  Map<String, dynamic> toJson() => {
    'adult_attestation': adultAttestation,
    'consent_bmi_context': consentBmiContext,
    'height_cm': heightCm,
    'weight_kg': weightKg,
  };
}

class BmiContext {
  const BmiContext({
    required this.state,
    required this.limitation,
    required this.referenceUrl,
    this.bmi,
  });

  factory BmiContext.fromJson(Map<String, dynamic> json) => BmiContext(
    state: json['state']?.toString() ?? 'NOT_CONFIGURED',
    bmi: (json['bmi'] as num?)?.toDouble(),
    limitation: json['limitation']?.toString() ?? '',
    referenceUrl: json['reference_url']?.toString() ?? '',
  );

  final String state;
  final double? bmi;
  final String limitation;
  final String referenceUrl;
}

class ProfileSnapshot {
  const ProfileSnapshot({
    required this.goal,
    required this.allergens,
    required this.dietaryPreferences,
    required this.consentPersonalization,
    this.customGoal,
    this.dietaryStyle = 'No specific diet',
    this.customDietaryStyle,
    this.healthConditions = const [],
    this.intolerances = const [],
    this.foodExclusions = const [],
    this.dailyTargets = const {},
    this.bodyContext = const SelfReportedBodyContext(),
  });

  factory ProfileSnapshot.fromJson(Map<String, dynamic> json) =>
      ProfileSnapshot(
        goal: json['goal']?.toString() ?? 'balanced',
        customGoal: json['custom_goal']?.toString(),
        allergens: _strings(json['allergens']),
        dietaryPreferences: _strings(json['dietary_preferences']),
        dietaryStyle: json['dietary_style']?.toString() ?? 'No specific diet',
        customDietaryStyle: json['custom_dietary_style']?.toString(),
        healthConditions: _strings(json['health_conditions']),
        intolerances: _strings(json['intolerances']),
        foodExclusions: _strings(json['food_exclusions']),
        consentPersonalization: json['consent_personalization'] == true,
        dailyTargets: Map.fromEntries(
          (json['daily_targets'] as Map<String, dynamic>? ?? const {}).entries
              .where((entry) => entry.value is num)
              .map(
                (entry) => MapEntry(entry.key, (entry.value as num).toDouble()),
              ),
        ),
        bodyContext: SelfReportedBodyContext.fromJson(
          json['body_context'] as Map<String, dynamic>? ?? const {},
        ),
      );

  final String goal;
  final String? customGoal;
  final List<String> allergens;
  final List<String> dietaryPreferences;
  final String dietaryStyle;
  final String? customDietaryStyle;
  final List<String> healthConditions;
  final List<String> intolerances;
  final List<String> foodExclusions;
  final bool consentPersonalization;
  final Map<String, double> dailyTargets;
  final SelfReportedBodyContext bodyContext;

  Map<String, dynamic> toJson() => {
    'goal': goal,
    'custom_goal': goal == 'custom' ? customGoal?.trim() : null,
    'allergens': allergens,
    'dietary_preferences': dietaryPreferences,
    'dietary_style': dietaryStyle,
    'custom_dietary_style': dietaryStyle == 'Custom' ? customDietaryStyle?.trim() : null,
    'health_conditions': healthConditions,
    'intolerances': intolerances,
    'food_exclusions': foodExclusions,
    'consent_personalization': consentPersonalization,
    'daily_targets': dailyTargets,
    'body_context': bodyContext.toJson(),
  };
}

class AccountProfile {
  const AccountProfile({
    required this.fullName,
    required this.phoneState,
    required this.phoneVerificationAvailability,
    required this.unitSystem,
    required this.researchInsightsConsent,
    required this.onboardingComplete,
    required this.ageEligibility,
    required this.minimumAccountAge,
    required this.legalAcceptanceComplete,
    this.dateOfBirth,
    this.maskedPhoneNumber,
    this.countryRegion,
  });

  factory AccountProfile.fromJson(Map<String, dynamic> json) => AccountProfile(
    fullName: json['full_name']?.toString() ?? '',
    dateOfBirth: DateTime.tryParse(json['date_of_birth']?.toString() ?? ''),
    maskedPhoneNumber: json['masked_phone_number']?.toString(),
    phoneState: json['phone_state']?.toString() ?? 'NOT_ADDED',
    phoneVerificationAvailability:
        json['phone_verification_availability']?.toString() ??
        'BLOCKED_EXTERNAL_COST',
    countryRegion: json['country_region']?.toString(),
    unitSystem: json['unit_system']?.toString() ?? 'METRIC',
    researchInsightsConsent: json['research_insights_consent'] == true,
    onboardingComplete: json['onboarding_complete'] == true,
    ageEligibility: json['age_eligibility']?.toString() ?? 'UNKNOWN',
    minimumAccountAge: (json['minimum_account_age'] as num?)?.toInt() ?? 18,
    legalAcceptanceComplete: json['legal_acceptance_complete'] == true,
  );

  final String fullName;
  final DateTime? dateOfBirth;
  final String? maskedPhoneNumber;
  final String phoneState;
  final String phoneVerificationAvailability;
  final String? countryRegion;
  final String unitSystem;
  final bool researchInsightsConsent;
  final bool onboardingComplete;
  final String ageEligibility;
  final int minimumAccountAge;
  final bool legalAcceptanceComplete;
}

class AccountSession {
  const AccountSession({
    required this.id,
    required this.current,
    required this.createdAt,
    required this.lastSeenAt,
    required this.expiresAt,
  });

  factory AccountSession.fromJson(Map<String, dynamic> json) => AccountSession(
    id: json['id']?.toString() ?? '',
    current: json['current'] == true,
    createdAt: DateTime.parse(json['created_at'].toString()).toLocal(),
    lastSeenAt: DateTime.parse(json['last_seen_at'].toString()).toLocal(),
    expiresAt: DateTime.parse(json['expires_at'].toString()).toLocal(),
  );

  final String id;
  final bool current;
  final DateTime createdAt;
  final DateTime lastSeenAt;
  final DateTime expiresAt;
}

class AuthIdentityState {
  const AuthIdentityState({
    required this.googleConnected,
    required this.emailPasswordConnected,
    required this.emailVerified,
    this.phoneVerified = false,
    required this.termsAccepted,
    required this.privacyAccepted,
  });

  factory AuthIdentityState.fromJson(Map<String, dynamic> json) =>
      AuthIdentityState(
        googleConnected: json['google_connected'] == true,
        emailPasswordConnected: json['email_password_connected'] == true,
        emailVerified: json['email_verified'] == true,
        phoneVerified: json['phone_verified'] == true,
        termsAccepted: json['terms_accepted'] == true,
        privacyAccepted: json['privacy_accepted'] == true,
      );

  final bool googleConnected;
  final bool emailPasswordConnected;
  final bool emailVerified;
  final bool phoneVerified;
  final bool termsAccepted;
  final bool privacyAccepted;
}

class HouseholdProfile {
  const HouseholdProfile({
    required this.id,
    required this.displayName,
    required this.profile,
    required this.createdAt,
    required this.updatedAt,
    this.relationship,
  });

  factory HouseholdProfile.fromJson(Map<String, dynamic> json) =>
      HouseholdProfile(
        id: json['id']?.toString() ?? '',
        displayName: json['display_name']?.toString() ?? 'Household member',
        relationship: json['relationship']?.toString(),
        profile: ProfileSnapshot.fromJson(
          json['profile'] as Map<String, dynamic>? ?? const {},
        ),
        createdAt: DateTime.parse(json['created_at'] as String),
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  final String id;
  final String displayName;
  final String? relationship;
  final ProfileSnapshot profile;
  final DateTime createdAt;
  final DateTime updatedAt;
}

List<String> _strings(Object? value) => (value as List<dynamic>? ?? const [])
    .map((item) => item.toString())
    .toList(growable: false);

class AssistantReply {
  const AssistantReply({
    required this.answer,
    required this.evidence,
    required this.citations,
    required this.remainingToday,
    required this.generationMode,
    required this.method,
    required this.disclaimer,
  });

  factory AssistantReply.fromJson(Map<String, dynamic> json) => AssistantReply(
    answer: json['answer']?.toString() ?? '',
    evidence: _strings(json['evidence']),
    citations: (json['citations'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(AssistantCitation.fromJson)
        .toList(growable: false),
    remainingToday: (json['remaining_today'] as num?)?.toInt() ?? 0,
    generationMode: json['generation_mode']?.toString() ?? 'UNKNOWN',
    method: json['method']?.toString() ?? 'GOVERNED_RETRIEVAL',
    disclaimer: json['disclaimer']?.toString() ?? 'General wellness guidance.',
  );

  final String answer;
  final List<String> evidence;
  final List<AssistantCitation> citations;
  final int remainingToday;
  final String generationMode;
  final String method;
  final String disclaimer;
}

class AssistantCitation {
  const AssistantCitation({
    required this.evidenceId,
    required this.title,
    required this.authority,
    required this.url,
  });

  factory AssistantCitation.fromJson(Map<String, dynamic> json) =>
      AssistantCitation(
        evidenceId: json['evidence_id']?.toString() ?? '',
        title: json['title']?.toString() ?? 'Reference',
        authority: json['authority']?.toString() ?? 'Source',
        url: json['url']?.toString() ?? '',
      );

  final String evidenceId;
  final String title;
  final String authority;
  final String url;
}

class BillingAccount {
  const BillingAccount({
    required this.plan,
    required this.subscriptionStatus,
    required this.subscriptionId,
  });

  factory BillingAccount.fromJson(Map<String, dynamic> json) => BillingAccount(
    plan: json['plan']?.toString() ?? 'FREE',
    subscriptionStatus: json['subscription_status']?.toString() ?? 'FREE',
    subscriptionId:
        (json['subscription']
                as Map<String, dynamic>?)?['provider_subscription_id']
            ?.toString(),
  );

  final String plan;
  final String subscriptionStatus;
  final String? subscriptionId;
}

class AccountNotification {
  const AccountNotification({
    required this.id,
    required this.kind,
    required this.title,
    required this.body,
    required this.createdAt,
    this.readAt,
  });

  factory AccountNotification.fromJson(Map<String, dynamic> json) =>
      AccountNotification(
        id: json['id'] as String,
        kind: json['kind']?.toString() ?? 'ACCOUNT',
        title: json['title']?.toString() ?? 'Notification',
        body: json['body']?.toString() ?? '',
        createdAt: DateTime.parse(json['created_at'] as String),
        readAt: json['read_at'] == null
            ? null
            : DateTime.parse(json['read_at'] as String),
      );

  final String id;
  final String kind;
  final String title;
  final String body;
  final DateTime createdAt;
  final DateTime? readAt;
}

class FavoriteFood {
  const FavoriteFood({
    required this.scanId,
    required this.productName,
    required this.brand,
    required this.savedAt,
  });

  factory FavoriteFood.fromJson(Map<String, dynamic> json) => FavoriteFood(
    scanId: json['scan_id'] as String,
    productName: json['product_name']?.toString(),
    brand: json['brand']?.toString(),
    savedAt: DateTime.parse(json['saved_at'] as String),
  );

  final String scanId;
  final String? productName;
  final String? brand;
  final DateTime savedAt;
}

class ScanHistoryItem {
  const ScanHistoryItem({
    required this.scanId,
    required this.createdAt,
    required this.inputKind,
    required this.status,
    required this.productName,
    required this.brand,
    required this.confidence,
  });

  factory ScanHistoryItem.fromJson(Map<String, dynamic> json) =>
      ScanHistoryItem(
        scanId: json['scan_id']?.toString() ?? '',
        createdAt: DateTime.parse(json['created_at'] as String).toLocal(),
        inputKind: json['input_kind']?.toString() ?? 'UNKNOWN',
        status: json['status']?.toString() ?? 'UNKNOWN',
        productName: json['product_name']?.toString(),
        brand: json['brand']?.toString(),
        confidence: (json['confidence'] as num?)?.toDouble(),
      );

  final String scanId;
  final DateTime createdAt;
  final String inputKind;
  final String status;
  final String? productName;
  final String? brand;
  final double? confidence;
}

class SearchResultItem {
  const SearchResultItem({
    required this.kind,
    required this.id,
    required this.title,
    required this.subtitle,
    required this.score,
  });

  factory SearchResultItem.fromJson(Map<String, dynamic> json) =>
      SearchResultItem(
        kind: json['kind']?.toString() ?? 'UNKNOWN',
        id: json['id']?.toString() ?? '',
        title: json['title']?.toString() ?? 'Unknown record',
        subtitle: json['subtitle']?.toString() ?? '',
        score: _number(json['score']),
      );

  final String kind;
  final String id;
  final String title;
  final String subtitle;
  final double score;
}

class SearchResults {
  const SearchResults({required this.items, required this.limitation});

  factory SearchResults.fromJson(Map<String, dynamic> json) => SearchResults(
    items: (json['items'] as List<dynamic>? ?? const [])
        .map((item) => SearchResultItem.fromJson(item as Map<String, dynamic>))
        .toList(growable: false),
    limitation: json['limitation']?.toString() ?? '',
  );

  final List<SearchResultItem> items;
  final String limitation;
}

abstract interface class ProductGateway
    implements
        HydrationGateway,
        WeightGateway,
        CustomRecipeGateway,
        RecipeActionGateway {
  Future<AccountProfile> accountProfile();
  Future<AccountProfile> saveAccountProfile({
    required String fullName,
    required DateTime? dateOfBirth,
    required String phoneUpdate,
    String? phoneNumber,
    String? countryRegion,
    required String unitSystem,
    required bool researchInsightsConsent,
    required bool completeOnboarding,
    bool acceptedTerms = false,
    bool acceptedPrivacy = false,
  });
  Future<List<AccountSession>> accountSessions();
  Future<void> revokeAccountSession(String id);
  Future<AuthIdentityState> authIdentities();
  Future<AuthIdentityState> connectGoogleIdentity(String credential);
  Future<AuthIdentityState> disconnectGoogleIdentity();
  Future<AuthIdentityState> connectPhoneIdentity({
    required String phone,
    required String firebaseIdToken,
  });
  Future<String> addEmailPassword(String password);
  Future<ProfileSnapshot> profile();
  Future<ProfileSnapshot> saveProfile(ProfileSnapshot profile);
  Future<BmiContext> bmiContext();
  Future<List<HouseholdProfile>> householdProfiles();
  Future<HouseholdProfile> saveHouseholdProfile({
    String? id,
    required String displayName,
    String? relationship,
    required ProfileSnapshot profile,
  });
  Future<void> deleteHouseholdProfile(String id);
  Future<List<DiaryEntry>> diary();
  Future<DiaryEntry> addDiary({
    required String name,
    required Nutrients nutrients,
    double? servingGrams,
    String? scanId,
    String? source,
    String? recipeId,
    int? recipeVersion,
    double? recipeServings,
  });
  Future<void> deleteDiary(String id);
  Future<MealComparison> compareDiary(List<String> entryIds);
  Future<List<PantryItem>> pantry();
  Future<PantryItem> addPantry({
    required String name,
    required double quantity,
    required String unit,
    double? lowStockThreshold,
    String itemRole = 'INGREDIENT',
  });
  Future<PantryItem> updatePantry(
    String id, {
    required double quantity,
    double? lowStockThreshold,
    String itemRole = 'INGREDIENT',
  });
  Future<void> deletePantry(String id);
  Future<List<ShoppingListItem>> shoppingList();
  Future<ShoppingListItem> addShoppingListItem(
    String name, {
    double? quantity,
    String? unit,
    String? recipeId,
  });
  Future<ShoppingListItem> updateShoppingListItem(
    String id, {
    String? name,
    bool? checked,
  });
  Future<void> deleteShoppingListItem(String id);
  Future<ShoppingListGeneration> generateShoppingListFromLowStock();
  Future<List<RecipeRecommendation>> recipes({
    String mode = 'COOK_WITH_WHAT_I_HAVE',
    List<String>? selectedIngredients,
    double? servings,
  });
  Future<void> planTemplateRecipe(String templateId, {double servings = 1.0});
  Future<void> logTemplateRecipeToDiary(String templateId, {double servings = 1.0});
  Future<UseSoonRecipeResponse> useSoonRecipes();
  Future<RecipeNutritionComparison> compareRecipeNutrition(
    List<RecipeNutritionInput> candidates,
  );
  Future<AnalyticsSummary> analytics({int days = 30});
  Future<AnalyticsComparison> analyticsComparison({int days = 7});
  Future<AnalyticsDrilldown> analyticsDrilldown({int days = 30});
  Future<DietaryPatterns> dietaryPatterns({int days = 90});
  Future<AssistantReply> askAssistant(String message, {String? scanId});
  Future<BillingAccount> billing();
  Future<List<AccountNotification>> notifications();
  Future<AccountNotification> markNotificationRead(String id);
  Future<void> markAllNotificationsRead();
  Future<List<FavoriteFood>> favorites();
  Future<FavoriteFood> saveFavorite(String scanId);
  Future<void> removeFavorite(String scanId);
  Future<ScanComparisonResponse> compareScans(List<String> scanIds);
  Future<List<ScanHistoryItem>> scanHistory({int limit = 50});
  Future<SearchResults> search(String query);
  Future<Map<String, dynamic>> exportAccount();
  Future<void> deleteAccount();
  ApiClient get client;
}

class ProductApi implements ProductGateway {
  ProductApi(this.client);

  @override
  final ApiClient client;

  @override
  Future<Map<String, dynamic>> exportAccount() async =>
      Map<String, dynamic>.from(
        await client.get('/api/v1/account/export') as Map<String, dynamic>,
      );

  @override
  Future<void> deleteAccount() async {
    await client.delete('/api/v1/account', body: {'confirmation': 'DELETE'});
  }

  @override
  Future<void> logCustomRecipe(PendingRecipeAction pending) async {
    await client.post(
      '/api/v1/recipes/custom/${Uri.encodeComponent(pending.recipeId)}/diary',
      body: pending.body,
    );
  }

  @override
  Future<RecipePantryCheck> checkCustomRecipePantry(
    String recipeId, {
    required int expectedVersion,
    required double servings,
  }) async => RecipePantryCheck.fromJson(
    await client.post(
          '/api/v1/recipes/custom/${Uri.encodeComponent(recipeId)}/pantry-check',
          body: {'expected_version': expectedVersion, 'servings': servings},
        )
        as Map<String, dynamic>,
  );

  @override
  Future<RecipeShoppingResult> addCustomRecipeShopping(
    PendingRecipeAction pending,
  ) async => RecipeShoppingResult.fromJson(
    await client.post(
          '/api/v1/recipes/custom/${Uri.encodeComponent(pending.recipeId)}/shopping-list',
          body: pending.body,
        )
        as Map<String, dynamic>,
  );

  @override
  Future<List<CustomRecipe>> customRecipes({
    int offset = 0,
    int limit = 200,
  }) async =>
      (await client.get(
                '/api/v1/recipes/custom',
                query: {'offset': '$offset', 'limit': '$limit'},
              )
              as List<dynamic>)
          .map((item) => CustomRecipe.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);

  @override
  Future<CustomRecipe> customRecipe(String id) async => CustomRecipe.fromJson(
    await client.get('/api/v1/recipes/custom/${Uri.encodeComponent(id)}')
        as Map<String, dynamic>,
  );

  @override
  Future<CustomRecipe> createCustomRecipe(PendingCustomRecipe pending) async =>
      CustomRecipe.fromJson(
        await client.post('/api/v1/recipes/custom', body: pending.toJson())
            as Map<String, dynamic>,
      );

  @override
  Future<CustomRecipe> updateCustomRecipe(
    String id,
    CustomRecipeDraft draft, {
    required int expectedVersion,
  }) async => CustomRecipe.fromJson(
    await client.put(
          '/api/v1/recipes/custom/${Uri.encodeComponent(id)}',
          body: {...draft.toJson(), 'expected_version': expectedVersion},
        )
        as Map<String, dynamic>,
  );

  @override
  Future<void> deleteCustomRecipe(
    String id, {
    required int expectedVersion,
  }) async => client.request(
    'DELETE',
    '/api/v1/recipes/custom/${Uri.encodeComponent(id)}',
    query: {'expected_version': '$expectedVersion'},
  );

  @override
  Future<HydrationSummary> hydration({
    required DateTime day,
  }) async => HydrationSummary.fromJson(
    await client.get(
          '/api/v1/hydration',
          query: {
            'day': hydrationDay(day),
            'timezone_offset_minutes':
                '${DateTime(day.year, day.month, day.day).timeZoneOffset.inMinutes}',
            'next_day_timezone_offset_minutes':
                '${DateTime(day.year, day.month, day.day + 1).timeZoneOffset.inMinutes}',
          },
        )
        as Map<String, dynamic>,
  );

  @override
  Future<int?> saveHydrationTarget(int? targetMl) async {
    final result =
        await client.put(
              '/api/v1/hydration/target',
              body: {'target_ml': targetMl},
            )
            as Map<String, dynamic>;
    return result['target_ml'] as int?;
  }

  @override
  Future<HydrationEntry> addHydration(HydrationEntry entry) async =>
      HydrationEntry.fromJson(
        await client.post('/api/v1/hydration/entries', body: entry.toJson())
            as Map<String, dynamic>,
      );

  @override
  Future<HydrationEntry> updateHydration(HydrationEntry entry) async =>
      HydrationEntry.fromJson(
        await client.put(
              '/api/v1/hydration/entries/${Uri.encodeComponent(entry.id)}',
              body: {
                'amount_ml': entry.amountMl,
                'consumed_at': entry.consumedAt.toUtc().toIso8601String(),
              },
            )
            as Map<String, dynamic>,
      );

  @override
  Future<void> deleteHydration(String id) async =>
      client.delete('/api/v1/hydration/entries/${Uri.encodeComponent(id)}');

  @override
  Future<HydrationAnalytics> hydrationAnalytics({
    String period = 'WEEK',
    DateTime? day,
    DateTime? startDate,
    DateTime? endDate,
  }) async {
    final query = <String, String>{
      'period': period,
      'timezone_offset_minutes': '${DateTime.now().timeZoneOffset.inMinutes}',
    };
    if (day != null) query['day'] = hydrationDay(day);
    if (startDate != null) query['start_date'] = hydrationDay(startDate);
    if (endDate != null) query['end_date'] = hydrationDay(endDate);
    final result = await client.get('/api/v1/hydration/analytics', query: query)
        as Map<String, dynamic>;
    return HydrationAnalytics.fromJson(result);
  }

  @override
  Future<WeightSummary> weightSummary({int limit = 180}) async =>
      WeightSummary.fromJson(
        await client.get('/api/v1/weight', query: {'limit': '$limit'})
            as Map<String, dynamic>,
      );

  @override
  Future<WeightSettings> enableWeightTracking(double? targetWeightKg) async =>
      WeightSettings.fromJson(
        await client.put(
              '/api/v1/weight/settings',
              body: {'target_weight_kg': targetWeightKg},
            )
            as Map<String, dynamic>,
      );

  @override
  Future<void> disableWeightTracking() async =>
      client.delete('/api/v1/weight/settings');

  @override
  Future<WeightEntry> addWeight(WeightEntry entry) async =>
      WeightEntry.fromJson(
        await client.post('/api/v1/weight/entries', body: entry.toJson())
            as Map<String, dynamic>,
      );

  @override
  Future<WeightEntry> updateWeight(WeightEntry entry) async =>
      WeightEntry.fromJson(
        await client.put(
              '/api/v1/weight/entries/${Uri.encodeComponent(entry.id)}',
              body: {
                'weight_kg': entry.weightKg,
                'recorded_at': entry.recordedAt.toUtc().toIso8601String(),
              },
            )
            as Map<String, dynamic>,
      );

  @override
  Future<void> deleteWeight(String id) async =>
      client.delete('/api/v1/weight/entries/${Uri.encodeComponent(id)}');

  @override
  Future<AccountProfile> accountProfile() async => AccountProfile.fromJson(
    await client.get('/api/v1/account/profile') as Map<String, dynamic>,
  );

  @override
  Future<AccountProfile> saveAccountProfile({
    required String fullName,
    required DateTime? dateOfBirth,
    required String phoneUpdate,
    String? phoneNumber,
    String? countryRegion,
    required String unitSystem,
    required bool researchInsightsConsent,
    required bool completeOnboarding,
    bool acceptedTerms = false,
    bool acceptedPrivacy = false,
  }) async {
    final body = <String, dynamic>{
      'full_name': fullName,
      'date_of_birth': dateOfBirth == null
          ? null
          : '${dateOfBirth.year.toString().padLeft(4, '0')}-'
                '${dateOfBirth.month.toString().padLeft(2, '0')}-'
                '${dateOfBirth.day.toString().padLeft(2, '0')}',
      'phone_update': phoneUpdate,
      'country_region': countryRegion,
      'unit_system': unitSystem,
      'research_insights_consent': researchInsightsConsent,
      'complete_onboarding': completeOnboarding,
      'accepted_terms': acceptedTerms,
      'accepted_privacy': acceptedPrivacy,
    };
    if (phoneUpdate == 'SET') body['phone_number'] = phoneNumber;
    return AccountProfile.fromJson(
      await client.put('/api/v1/account/profile', body: body)
          as Map<String, dynamic>,
    );
  }

  @override
  Future<List<AccountSession>> accountSessions() async =>
      (await client.get('/api/v1/auth/sessions') as List<dynamic>)
          .map((item) => AccountSession.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);

  @override
  Future<void> revokeAccountSession(String id) async =>
      client.delete('/api/v1/auth/sessions/${Uri.encodeComponent(id)}');

  @override
  Future<AuthIdentityState> authIdentities() async =>
      AuthIdentityState.fromJson(
        await client.get('/api/v1/auth/identities') as Map<String, dynamic>,
      );

  @override
  Future<AuthIdentityState> connectGoogleIdentity(String credential) async =>
      AuthIdentityState.fromJson(
        await client.post(
              '/api/v1/auth/identities/google/connect',
              body: {'credential': credential},
            )
            as Map<String, dynamic>,
      );

  @override
  Future<AuthIdentityState> disconnectGoogleIdentity() async =>
      AuthIdentityState.fromJson(
        await client.delete('/api/v1/auth/identities/google')
            as Map<String, dynamic>,
      );

  @override
  Future<AuthIdentityState> connectPhoneIdentity({
    required String phone,
    required String firebaseIdToken,
  }) async =>
      AuthIdentityState.fromJson(
        await client.post(
              '/api/v1/auth/phone/link',
              body: {'phone': phone, 'firebase_id_token': firebaseIdToken},
            )
            as Map<String, dynamic>,
      );

  @override
  Future<String> addEmailPassword(String password) async {
    final result = await client.post(
      '/api/v1/auth/identities/email/password',
      body: {'password': password},
    );
    return (result as Map<String, dynamic>)['message']?.toString() ??
        'Check your inbox to verify the email/password login.';
  }

  @override
  Future<ProfileSnapshot> profile() async => ProfileSnapshot.fromJson(
    await client.get('/api/v1/profile') as Map<String, dynamic>,
  );

  @override
  Future<ProfileSnapshot> saveProfile(ProfileSnapshot profile) async {
    final payload = await client.put('/api/v1/profile', body: profile.toJson());
    return ProfileSnapshot.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<BmiContext> bmiContext() async => BmiContext.fromJson(
    await client.get('/api/v1/profile/bmi-context') as Map<String, dynamic>,
  );

  @override
  Future<List<HouseholdProfile>> householdProfiles() async =>
      (await client.get('/api/v1/profile/household') as List<dynamic>)
          .map(
            (item) => HouseholdProfile.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false);

  @override
  Future<HouseholdProfile> saveHouseholdProfile({
    String? id,
    required String displayName,
    String? relationship,
    required ProfileSnapshot profile,
  }) async {
    final body = {
      'display_name': displayName,
      'relationship': relationship,
      'profile': profile.toJson(),
    };
    final payload = id == null
        ? await client.post('/api/v1/profile/household', body: body)
        : await client.put('/api/v1/profile/household/$id', body: body);
    return HouseholdProfile.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<void> deleteHouseholdProfile(String id) async =>
      client.delete('/api/v1/profile/household/$id');

  @override
  Future<List<DiaryEntry>> diary() async =>
      (await client.get('/api/v1/diary') as List<dynamic>)
          .map((item) => DiaryEntry.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);

  @override
  Future<DiaryEntry> addDiary({
    required String name,
    required Nutrients nutrients,
    double? servingGrams,
    String? scanId,
    String? source,
    String? recipeId,
    int? recipeVersion,
    double? recipeServings,
  }) async {
    final body = <String, dynamic>{
      'name': name,
      'nutrients': nutrients.toJson(),
    };
    if (servingGrams != null) body['serving_grams'] = servingGrams;
    if (scanId != null) body['scan_id'] = scanId;
    if (source != null) body['source'] = source;
    if (recipeId != null) body['recipe_id'] = recipeId;
    if (recipeVersion != null) body['recipe_version'] = recipeVersion;
    if (recipeServings != null) body['recipe_servings'] = recipeServings;

    final payload = await client.post('/api/v1/diary', body: body);
    return DiaryEntry.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<void> deleteDiary(String id) async =>
      client.delete('/api/v1/diary/$id');

  @override
  Future<MealComparison> compareDiary(List<String> entryIds) async =>
      MealComparison.fromJson(
        await client.post(
              '/api/v1/diary/compare',
              body: {'entry_ids': entryIds},
            )
            as Map<String, dynamic>,
      );

  @override
  Future<List<PantryItem>> pantry() async =>
      (await client.get('/api/v1/pantry') as List<dynamic>)
          .map((item) => PantryItem.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);

  @override
  Future<PantryItem> addPantry({
    required String name,
    required double quantity,
    required String unit,
    double? lowStockThreshold,
    String itemRole = 'INGREDIENT',
  }) async {
    final payload = await client.post(
      '/api/v1/pantry',
      body: {
        'name': name,
        'quantity': quantity,
        'unit': unit,
        'low_stock_threshold': lowStockThreshold,
        'item_role': itemRole,
      },
    );
    return PantryItem.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<PantryItem> updatePantry(
    String id, {
    required double quantity,
    double? lowStockThreshold,
    String itemRole = 'INGREDIENT',
  }) async => PantryItem.fromJson(
    await client.patch(
          '/api/v1/pantry/$id',
          body: {
            'quantity': quantity,
            'low_stock_threshold': lowStockThreshold,
            'item_role': itemRole,
          },
        )
        as Map<String, dynamic>,
  );

  @override
  Future<void> deletePantry(String id) async =>
      client.delete('/api/v1/pantry/$id');

  @override
  Future<List<ShoppingListItem>> shoppingList() async =>
      (await client.get('/api/v1/shopping-list') as List<dynamic>)
          .map(
            (item) => ShoppingListItem.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false);

  @override
  Future<ShoppingListItem> addShoppingListItem(
    String name, {
    double? quantity,
    String? unit,
    String? recipeId,
  }) async {
    final body = <String, dynamic>{'name': name};
    if (quantity != null) body['quantity'] = quantity;
    if (unit != null) body['unit'] = unit;
    if (recipeId != null) body['recipe_id'] = recipeId;
    final payload = await client.post('/api/v1/shopping-list', body: body);
    return ShoppingListItem.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<ShoppingListItem> updateShoppingListItem(
    String id, {
    String? name,
    bool? checked,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (checked != null) body['checked'] = checked;
    return ShoppingListItem.fromJson(
      await client.patch('/api/v1/shopping-list/$id', body: body)
          as Map<String, dynamic>,
    );
  }

  @override
  Future<void> deleteShoppingListItem(String id) async =>
      client.delete('/api/v1/shopping-list/$id');

  @override
  Future<ShoppingListGeneration> generateShoppingListFromLowStock() async =>
      ShoppingListGeneration.fromJson(
        await client.post('/api/v1/shopping-list/from-low-stock')
            as Map<String, dynamic>,
      );

  @override
  Future<List<RecipeRecommendation>> recipes({
    String mode = 'COOK_WITH_WHAT_I_HAVE',
    List<String>? selectedIngredients,
    double? servings,
  }) async {
    final queryParams = <String, String>{};
    if (mode != 'COOK_WITH_WHAT_I_HAVE') {
      queryParams['mode'] = mode;
    }
    if (selectedIngredients != null && selectedIngredients.isNotEmpty) {
      queryParams['selected_ingredients'] = selectedIngredients.join(',');
    }
    if (servings != null && servings > 0) {
      queryParams['servings'] = servings.toString();
    }
    final queryString = queryParams.isEmpty
        ? ''
        : '?${queryParams.entries.map((e) => '${Uri.encodeQueryComponent(e.key)}=${Uri.encodeQueryComponent(e.value)}').join('&')}';
    return (await client.get('/api/v1/recipes/recommendations$queryString')
            as List<dynamic>)
        .map(
          (item) =>
              RecipeRecommendation.fromJson(item as Map<String, dynamic>),
        )
        .toList(growable: false);
  }

  @override
  Future<void> planTemplateRecipe(
    String templateId, {
    double servings = 1.0,
  }) async {
    await client.post(
      '/api/v1/recipes/templates/$templateId/plan-to-shopping',
      body: {'servings': servings},
    );
  }

  @override
  Future<void> logTemplateRecipeToDiary(
    String templateId, {
    double servings = 1.0,
  }) async {
    await client.post(
      '/api/v1/recipes/templates/$templateId/log-to-diary',
      body: {'servings': servings},
    );
  }

  @override
  Future<UseSoonRecipeResponse> useSoonRecipes() async =>
      UseSoonRecipeResponse.fromJson(
        await client.get('/api/v1/recipes/use-soon') as Map<String, dynamic>,
      );

  @override
  Future<RecipeNutritionComparison> compareRecipeNutrition(
    List<RecipeNutritionInput> candidates,
  ) async => RecipeNutritionComparison.fromJson(
    await client.post(
          '/api/v1/recipes/compare',
          body: {
            'candidates': candidates
                .map((candidate) => candidate.toJson())
                .toList(growable: false),
          },
        )
        as Map<String, dynamic>,
  );

  @override
  Future<AnalyticsSummary> analytics({int days = 30}) async =>
      AnalyticsSummary.fromJson(
        await client.get('/api/v1/analytics/summary', query: {'days': '$days'})
            as Map<String, dynamic>,
      );

  @override
  Future<AnalyticsComparison> analyticsComparison({int days = 7}) async =>
      AnalyticsComparison.fromJson(
        await client.get('/api/v1/analytics/compare', query: {'days': '$days'})
            as Map<String, dynamic>,
      );

  @override
  Future<AnalyticsDrilldown> analyticsDrilldown({int days = 30}) async =>
      AnalyticsDrilldown.fromJson(
        await client.get(
              '/api/v1/analytics/drilldown',
              query: {'days': '$days'},
            )
            as Map<String, dynamic>,
      );

  @override
  Future<DietaryPatterns> dietaryPatterns({int days = 90}) async =>
      DietaryPatterns.fromJson(
        await client.get('/api/v1/analytics/patterns', query: {'days': '$days'})
            as Map<String, dynamic>,
      );

  @override
  Future<AssistantReply> askAssistant(String message, {String? scanId}) async {
    final payload = await client.post(
      '/api/v1/assistant/messages',
      body: {'message': message, 'scan_id': ?scanId},
    );
    return AssistantReply.fromJson(payload as Map<String, dynamic>);
  }

  @override
  Future<BillingAccount> billing() async => BillingAccount.fromJson(
    await client.get('/api/v1/payments/account') as Map<String, dynamic>,
  );

  @override
  Future<List<AccountNotification>> notifications() async =>
      (await client.get('/api/v1/notifications') as List<dynamic>)
          .map(
            (item) =>
                AccountNotification.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false);

  @override
  Future<AccountNotification> markNotificationRead(String id) async =>
      AccountNotification.fromJson(
        await client.patch('/api/v1/notifications/$id/read')
            as Map<String, dynamic>,
      );

  @override
  Future<void> markAllNotificationsRead() async {
    await client.post('/api/v1/notifications/read-all');
  }

  @override
  Future<List<FavoriteFood>> favorites() async =>
      (await client.get('/api/v1/favorites') as List<dynamic>)
          .map((item) => FavoriteFood.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);

  @override
  Future<FavoriteFood> saveFavorite(String scanId) async =>
      FavoriteFood.fromJson(
        await client.put('/api/v1/favorites/$scanId') as Map<String, dynamic>,
      );

  @override
  Future<void> removeFavorite(String scanId) async =>
      client.delete('/api/v1/favorites/$scanId');

  @override
  Future<ScanComparisonResponse> compareScans(List<String> scanIds) async =>
      ScanComparisonResponse.fromJson(
        await client.post(
              '/api/v1/recommendations/compare',
              body: {'scan_ids': scanIds},
            )
            as Map<String, dynamic>,
      );

  @override
  Future<List<ScanHistoryItem>> scanHistory({int limit = 50}) async =>
      (await client.get('/api/v1/scan/history', query: {'limit': '$limit'})
              as List<dynamic>)
          .map((item) => ScanHistoryItem.fromJson(item as Map<String, dynamic>))
          .toList(growable: false);

  @override
  Future<SearchResults> search(String query) async => SearchResults.fromJson(
    await client.get('/api/v1/search', query: {'q': query})
        as Map<String, dynamic>,
  );
}
