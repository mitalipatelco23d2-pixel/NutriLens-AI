const recipeNutrientLabels = <String, String>{
  'calories': 'Energy (kcal)',
  'protein_g': 'Protein (g)',
  'carbs_g': 'Carbohydrate (g)',
  'fat_g': 'Fat (g)',
  'sugar_g': 'Sugar (g)',
  'sodium_mg': 'Sodium (mg)',
  'fiber_g': 'Fiber (g)',
};

/// Absent recipe evidence is unknown, never zero.
class RecipeNutrients {
  RecipeNutrients([Map<String, double?> values = const {}])
    : values = Map.unmodifiable({
        for (final key in recipeNutrientLabels.keys) key: values[key],
      });

  factory RecipeNutrients.fromJson(Map<String, dynamic> json) =>
      RecipeNutrients({
        for (final key in recipeNutrientLabels.keys)
          key: (json[key] as num?)?.toDouble(),
      });

  final Map<String, double?> values;
  Map<String, dynamic> toJson() => {...values};
}

class CustomRecipeIngredient {
  const CustomRecipeIngredient({
    required this.name,
    required this.quantity,
    required this.unit,
    required this.nutrients,
    this.sourceLabel = 'User-entered ingredient values',
  });

  factory CustomRecipeIngredient.fromJson(Map<String, dynamic> json) =>
      CustomRecipeIngredient(
        name: json['name'] as String,
        quantity: (json['quantity'] as num).toDouble(),
        unit: json['unit'] as String,
        nutrients: RecipeNutrients.fromJson(
          json['nutrients'] as Map<String, dynamic>? ?? const {},
        ),
        sourceLabel:
            json['source_label'] as String? ?? 'User-entered ingredient values',
      );

  final String name;
  final double quantity;
  final String unit;
  // Total for this exact listed quantity; never values per 100 g/ml.
  final RecipeNutrients nutrients;
  final String sourceLabel;

  Map<String, dynamic> toJson() => {
    'name': name,
    'quantity': quantity,
    'unit': unit,
    'nutrients': nutrients.toJson(),
    'source_label': sourceLabel,
  };
}

class CustomRecipeDraft {
  CustomRecipeDraft({
    required this.name,
    required this.servings,
    required List<CustomRecipeIngredient> ingredients,
    this.notes = '',
  }) : ingredients = List.unmodifiable(ingredients);

  factory CustomRecipeDraft.fromJson(Map<String, dynamic> json) =>
      CustomRecipeDraft(
        name: json['name'] as String,
        servings: (json['servings'] as num).toDouble(),
        ingredients: (json['ingredients'] as List<dynamic>)
            .map(
              (item) =>
                  CustomRecipeIngredient.fromJson(item as Map<String, dynamic>),
            )
            .toList(),
        notes: json['notes'] as String? ?? '',
      );

  final String name;
  final double servings;
  final List<CustomRecipeIngredient> ingredients;
  final String notes;

  Map<String, dynamic> toJson() => {
    'name': name,
    'servings': servings,
    'ingredients': ingredients
        .map((ingredient) => ingredient.toJson())
        .toList(),
    'notes': notes,
  };
}

class PendingCustomRecipe {
  const PendingCustomRecipe({required this.id, required this.draft});
  factory PendingCustomRecipe.fromJson(Map<String, dynamic> json) =>
      PendingCustomRecipe(
        id: json['id'] as String,
        draft: CustomRecipeDraft.fromJson(json),
      );
  final String id;
  final CustomRecipeDraft draft;
  Map<String, dynamic> toJson() => {'id': id, ...draft.toJson()};
}

class CustomRecipe {
  const CustomRecipe({
    required this.id,
    required this.draft,
    required this.version,
    required this.createdAt,
    required this.updatedAt,
    required this.totalNutrients,
    required this.perServing,
    this.source = 'USER_ENTERED',
  });

  factory CustomRecipe.fromJson(Map<String, dynamic> json) => CustomRecipe(
    id: json['id'] as String,
    draft: CustomRecipeDraft.fromJson(json),
    version: json['version'] as int,
    createdAt: DateTime.parse(json['created_at'] as String),
    updatedAt: DateTime.parse(json['updated_at'] as String),
    totalNutrients: RecipeNutrients.fromJson(
      json['total_nutrients'] as Map<String, dynamic>,
    ),
    perServing: RecipeNutrients.fromJson(
      json['per_serving'] as Map<String, dynamic>,
    ),
    source: json['source'] as String? ?? 'USER_ENTERED',
  );

  final String id;
  final CustomRecipeDraft draft;
  final int version;
  final DateTime createdAt;
  final DateTime updatedAt;
  final RecipeNutrients totalNutrients;
  final RecipeNutrients perServing;
  final String source;
}

abstract interface class CustomRecipeGateway {
  Future<List<CustomRecipe>> customRecipes({int offset = 0, int limit = 200});
  Future<CustomRecipe> customRecipe(String id);
  Future<CustomRecipe> createCustomRecipe(PendingCustomRecipe pending);
  Future<CustomRecipe> updateCustomRecipe(
    String id,
    CustomRecipeDraft draft, {
    required int expectedVersion,
  });
  Future<void> deleteCustomRecipe(String id, {required int expectedVersion});
}

String recipeNumber(double value) => value
    .toStringAsFixed(3)
    .replaceFirst(RegExp(r'0+$'), '')
    .replaceFirst(RegExp(r'\.$'), '');
