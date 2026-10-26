enum RecipeActionKind { diary, shopping }

/// The exact request identity and body are durable before any write is sent.
class PendingRecipeAction {
  PendingRecipeAction({
    required this.recipeId,
    required this.recipeName,
    required this.kind,
    required Map<String, dynamic> body,
  }) : body = Map.unmodifiable({
         for (final entry in body.entries)
           entry.key: entry.value is List
               ? List<dynamic>.unmodifiable(entry.value as List<dynamic>)
               : entry.value,
       });

  factory PendingRecipeAction.fromJson(Map<String, dynamic> json) =>
      PendingRecipeAction(
        recipeId: json['recipe_id'] as String,
        recipeName: json['recipe_name'] as String,
        kind: RecipeActionKind.values.byName(json['kind'] as String),
        body: json['body'] as Map<String, dynamic>,
      );

  final String recipeId;
  final String recipeName;
  final RecipeActionKind kind;
  final Map<String, dynamic> body;

  Map<String, dynamic> toJson() => {
    'recipe_id': recipeId,
    'recipe_name': recipeName,
    'kind': kind.name,
    'body': body,
  };
}

class RecipePantryIngredient {
  const RecipePantryIngredient({
    required this.key,
    required this.name,
    required this.unit,
    required this.requiredQuantity,
    required this.availableQuantity,
    required this.missingQuantity,
    required this.status,
  });

  factory RecipePantryIngredient.fromJson(Map<String, dynamic> json) =>
      RecipePantryIngredient(
        key: json['key'] as String,
        name: json['name'] as String,
        unit: json['unit'] as String,
        requiredQuantity: (json['required_quantity'] as num).toDouble(),
        availableQuantity: (json['available_quantity'] as num?)?.toDouble(),
        missingQuantity: (json['missing_quantity'] as num?)?.toDouble(),
        status: json['status'] as String,
      );

  final String key;
  final String name;
  final String unit;
  final double requiredQuantity;
  final double? availableQuantity;
  final double? missingQuantity;
  final String status;
  bool get canAdd => status == 'MISSING' && (missingQuantity ?? 0) > 0;
}

class RecipePantryCheck {
  const RecipePantryCheck({
    required this.recipeId,
    required this.recipeVersion,
    required this.servings,
    required this.ingredients,
    required this.limitation,
    required this.checkToken,
  });

  factory RecipePantryCheck.fromJson(Map<String, dynamic> json) =>
      RecipePantryCheck(
        recipeId: json['recipe_id'] as String,
        recipeVersion: json['recipe_version'] as int,
        servings: (json['servings'] as num).toDouble(),
        ingredients: (json['ingredients'] as List<dynamic>)
            .map(
              (item) =>
                  RecipePantryIngredient.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
        limitation: json['limitation'] as String? ?? '',
        checkToken: json['check_token'] as String,
      );

  final String recipeId;
  final int recipeVersion;
  final double servings;
  final List<RecipePantryIngredient> ingredients;
  final String limitation;
  final String checkToken;
}

class RecipeShoppingResult {
  const RecipeShoppingResult({
    required this.generatedCount,
    required this.limitation,
  });
  factory RecipeShoppingResult.fromJson(Map<String, dynamic> json) =>
      RecipeShoppingResult(
        generatedCount: json['generated_count'] as int,
        limitation: json['limitation'] as String? ?? '',
      );
  final int generatedCount;
  final String limitation;
}

abstract interface class RecipeActionGateway {
  Future<void> logCustomRecipe(PendingRecipeAction pending);
  Future<RecipePantryCheck> checkCustomRecipePantry(
    String recipeId, {
    required int expectedVersion,
    required double servings,
  });
  Future<RecipeShoppingResult> addCustomRecipeShopping(
    PendingRecipeAction pending,
  );
}
