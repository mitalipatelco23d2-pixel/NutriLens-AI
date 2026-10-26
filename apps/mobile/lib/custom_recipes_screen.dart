import 'package:flutter/material.dart';

import 'services/custom_recipe_controller.dart';
import 'services/custom_recipe_models.dart';
import 'services/recipe_action_controller.dart';
import 'recipe_actions_screen.dart';

class CustomRecipesScreen extends StatelessWidget {
  const CustomRecipesScreen({
    required this.controller,
    this.actions,
    super.key,
  });
  final CustomRecipeController controller;
  final RecipeActionController? actions;

  bool get canMutate =>
      controller.canMutate && (actions == null || actions!.canStart);

  Future<void> _use(BuildContext context, CustomRecipe recipe) async {
    if (!canMutate || actions == null) return;
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) =>
            RecipeActionsScreen(recipe: recipe, controller: actions!),
      ),
    );
  }

  Future<void> _edit(BuildContext context, [CustomRecipe? recipe]) async {
    if (!canMutate) return;
    final draft = await Navigator.push<CustomRecipeDraft>(
      context,
      MaterialPageRoute(
        builder: (_) => _RecipeEditor(controller: controller, recipe: recipe),
      ),
    );
    if (draft == null || !canMutate) return;
    if (recipe == null) {
      await controller.create(draft);
    } else {
      await controller.update(recipe, draft);
    }
  }

  Future<void> _delete(BuildContext context, CustomRecipe recipe) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete saved recipe?'),
        content: Text('Delete “${recipe.draft.name}”? This cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Delete recipe'),
          ),
        ],
      ),
    );
    if (confirmed == true && canMutate) {
      await controller.delete(recipe);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('My recipes')),
    body: ListenableBuilder(
      listenable: Listenable.merge([controller, ?actions]),
      builder: (context, _) {
        if (!controller.active) {
          return const Center(child: Text('Sign in to view your recipes.'));
        }
        return RefreshIndicator(
          onRefresh: controller.refresh,
          child: ListView(
            padding: const EdgeInsets.all(20),
            physics: const AlwaysScrollableScrollPhysics(),
            children: [
              const Text(
                'Save your own ingredients, quantities and recipe notes. Recipes are private to your account.',
              ),
              const SizedBox(height: 12),
              const Text(
                'Nutrition is calculated only from the values you enter. Missing evidence stays Unknown; it is not treated as zero. These values are not verified nutrition advice.',
              ),
              const SizedBox(height: 16),
              Wrap(
                spacing: 12,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    onPressed: canMutate ? () => _edit(context) : null,
                    icon: const Icon(Icons.add),
                    label: const Text('Create recipe'),
                  ),
                  OutlinedButton.icon(
                    onPressed: controller.loading || controller.saving
                        ? null
                        : controller.refresh,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Refresh recipes'),
                  ),
                ],
              ),
              if (controller.loading || controller.saving) ...[
                const SizedBox(height: 12),
                const LinearProgressIndicator(),
                Text(
                  controller.saving
                      ? 'Saving recipe…'
                      : 'Loading saved recipes…',
                ),
              ],
              if (controller.error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Semantics(
                    liveRegion: true,
                    child: Text(
                      controller.error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                ),
              if (controller.notice != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Semantics(
                    liveRegion: true,
                    child: Text(controller.notice!),
                  ),
                ),
              if (actions != null) RecipeActionStatus(controller: actions!),
              if (controller.pendingCreate != null)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Unconfirmed save: ${controller.pendingCreate!.draft.name}',
                        ),
                        const Text(
                          'Your original recipe is kept securely on this device. Retry checks the same save identity and cannot create a duplicate.',
                        ),
                        const SizedBox(height: 8),
                        FilledButton.tonal(
                          onPressed: controller.saving || controller.loading
                              ? null
                              : controller.retryCreate,
                          child: const Text('Retry original save'),
                        ),
                      ],
                    ),
                  ),
                ),
              if (!controller.loading && controller.recipes.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 28),
                  child: Text(
                    'No saved recipes yet. Create a recipe to start.',
                  ),
                ),
              ...controller.recipes.map(
                (recipe) => _RecipeCard(
                  recipe: recipe,
                  onEdit: canMutate ? () => _edit(context, recipe) : null,
                  onDelete: canMutate ? () => _delete(context, recipe) : null,
                  onUse: actions != null && canMutate
                      ? () => _use(context, recipe)
                      : null,
                ),
              ),
              if (controller.hasMore)
                OutlinedButton(
                  onPressed: controller.loading || controller.saving
                      ? null
                      : controller.loadMore,
                  child: const Text('Load more recipes'),
                ),
            ],
          ),
        );
      },
    ),
  );
}

class _RecipeCard extends StatelessWidget {
  const _RecipeCard({
    required this.recipe,
    required this.onEdit,
    required this.onDelete,
    required this.onUse,
  });
  final CustomRecipe recipe;
  final VoidCallback? onEdit;
  final VoidCallback? onDelete;
  final VoidCallback? onUse;

  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(top: 16),
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            recipe.draft.name,
            style: Theme.of(context).textTheme.titleLarge,
          ),
          Text(
            '${recipeNumber(recipe.draft.servings)} servings · User-entered recipe · Version ${recipe.version}',
          ),
          const SizedBox(height: 12),
          ...recipe.draft.ingredients.map(
            (ingredient) => Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                '${ingredient.name} — ${recipeNumber(ingredient.quantity)} ${ingredient.unit}\nEvidence: ${ingredient.sourceLabel}',
              ),
            ),
          ),
          if (recipe.draft.notes.isNotEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Text(recipe.draft.notes),
            ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('Nutrition totals and per serving'),
            children: [
              const Text(
                'A nutrient is Unknown if any ingredient is missing that value. No quantity-to-weight conversion is inferred.',
              ),
              ...recipeNutrientLabels.entries.map(
                (entry) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 5),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text(
                      '${entry.value}: total ${_evidence(recipe.totalNutrients.values[entry.key])} · per serving ${_evidence(recipe.perServing.values[entry.key])}',
                    ),
                  ),
                ),
              ),
            ],
          ),
          Wrap(
            spacing: 8,
            children: [
              TextButton.icon(
                onPressed: onUse,
                icon: const Icon(Icons.restaurant_outlined),
                label: const Text('Use recipe'),
              ),
              TextButton.icon(
                onPressed: onEdit,
                icon: const Icon(Icons.edit_outlined),
                label: const Text('Edit recipe'),
              ),
              TextButton.icon(
                onPressed: onDelete,
                icon: const Icon(Icons.delete_outline),
                label: const Text('Delete recipe'),
              ),
            ],
          ),
        ],
      ),
    ),
  );

  String _evidence(double? value) =>
      value == null ? 'Unknown' : recipeNumber(value);
}

class _RecipeEditor extends StatefulWidget {
  const _RecipeEditor({required this.controller, this.recipe});
  final CustomRecipeController controller;
  final CustomRecipe? recipe;
  @override
  State<_RecipeEditor> createState() => _RecipeEditorState();
}

class _RecipeEditorState extends State<_RecipeEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _name;
  late final TextEditingController _servings;
  late final TextEditingController _notes;
  late final List<_IngredientFields> _ingredients;

  @override
  void initState() {
    super.initState();
    final draft = widget.recipe?.draft;
    _name = TextEditingController(text: draft?.name ?? '');
    _servings = TextEditingController(text: draft?.servings.toString() ?? '1');
    _notes = TextEditingController(text: draft?.notes ?? '');
    _ingredients = draft == null
        ? [_IngredientFields()]
        : draft.ingredients.map(_IngredientFields.new).toList();
  }

  @override
  void dispose() {
    _name.dispose();
    _servings.dispose();
    _notes.dispose();
    for (final ingredient in _ingredients) {
      ingredient.dispose();
    }
    super.dispose();
  }

  void _save() {
    if (!widget.controller.canMutate || !_form.currentState!.validate()) return;
    Navigator.pop(
      context,
      CustomRecipeDraft(
        name: _name.text.trim(),
        servings: double.parse(_servings.text.trim()),
        notes: _notes.text.trim(),
        ingredients: _ingredients.map((fields) => fields.value).toList(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(widget.recipe == null ? 'Create recipe' : 'Edit recipe'),
    ),
    body: ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        if (!widget.controller.active) {
          return const Center(
            child: Text('Your account changed. Close this recipe editor.'),
          );
        }
        return Form(
          key: _form,
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextFormField(
                  controller: _name,
                  maxLength: 200,
                  decoration: const InputDecoration(labelText: 'Recipe name'),
                  validator: (value) => _required(value, 200),
                ),
                TextFormField(
                  controller: _servings,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Recipe servings',
                  ),
                  validator: (value) => _positive(value, 1000),
                ),
                const SizedBox(height: 16),
                const Text(
                  'Ingredient nutrition must be the TOTAL for the listed ingredient quantity, not per 100 g/ml. Leave unknown values blank. Changing a quantity does not automatically scale the nutrition you entered.',
                ),
                const SizedBox(height: 12),
                for (var index = 0; index < _ingredients.length; index++)
                  _ingredient(index),
                OutlinedButton.icon(
                  onPressed: _ingredients.length >= 100
                      ? null
                      : () => setState(
                          () => _ingredients.add(_IngredientFields()),
                        ),
                  icon: const Icon(Icons.add),
                  label: const Text('Add ingredient'),
                ),
                TextFormField(
                  controller: _notes,
                  maxLength: 4000,
                  minLines: 3,
                  maxLines: 8,
                  decoration: const InputDecoration(
                    labelText: 'Recipe notes (optional)',
                  ),
                  validator: (value) => (value?.length ?? 0) > 4000
                      ? 'Use at most 4000 characters.'
                      : null,
                ),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: widget.controller.canMutate ? _save : null,
                  child: const Text('Save recipe'),
                ),
                const SizedBox(height: 24),
              ],
            ),
          ),
        );
      },
    ),
  );

  Widget _ingredient(int index) {
    final fields = _ingredients[index];
    return Card(
      key: ObjectKey(fields),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Ingredient ${index + 1}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                IconButton(
                  tooltip: 'Remove ingredient ${index + 1}',
                  onPressed: _ingredients.length <= 1
                      ? null
                      : () {
                          setState(() => _ingredients.remove(fields));
                          WidgetsBinding.instance.addPostFrameCallback(
                            (_) => fields.dispose(),
                          );
                        },
                  icon: const Icon(Icons.remove_circle_outline),
                ),
              ],
            ),
            TextFormField(
              controller: fields.name,
              maxLength: 200,
              decoration: const InputDecoration(labelText: 'Ingredient name'),
              validator: (value) => _required(value, 200),
            ),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: TextFormField(
                    controller: fields.quantity,
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(labelText: 'Quantity'),
                    validator: (value) => _positive(value, 100000),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextFormField(
                    controller: fields.unit,
                    maxLength: 30,
                    decoration: const InputDecoration(
                      labelText: 'Unit (g, ml, cup…)',
                    ),
                    validator: (value) => _required(value, 30),
                  ),
                ),
              ],
            ),
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              maintainState: true,
              title: const Text('Optional nutrition evidence'),
              subtitle: const Text('Totals for this ingredient quantity'),
              children: [
                for (final nutrient in recipeNutrientLabels.entries)
                  TextFormField(
                    controller: fields.nutrients[nutrient.key],
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: InputDecoration(
                      labelText: nutrient.value,
                      hintText: 'Unknown',
                      helperText: 'Blank = unknown; 0 = known zero',
                    ),
                    validator: _nutrient,
                  ),
                TextFormField(
                  controller: fields.source,
                  maxLength: 200,
                  decoration: const InputDecoration(
                    labelText: 'Nutrition source label',
                  ),
                  validator: (value) => _required(value, 200),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _IngredientFields {
  _IngredientFields([CustomRecipeIngredient? ingredient])
    : name = TextEditingController(text: ingredient?.name ?? ''),
      quantity = TextEditingController(
        text: ingredient?.quantity.toString() ?? '',
      ),
      unit = TextEditingController(text: ingredient?.unit ?? ''),
      source = TextEditingController(
        text: ingredient?.sourceLabel ?? 'User-entered ingredient values',
      ),
      nutrients = {
        for (final key in recipeNutrientLabels.keys)
          key: TextEditingController(
            text: ingredient?.nutrients.values[key]?.toString() ?? '',
          ),
      };

  final TextEditingController name;
  final TextEditingController quantity;
  final TextEditingController unit;
  final TextEditingController source;
  final Map<String, TextEditingController> nutrients;

  CustomRecipeIngredient get value => CustomRecipeIngredient(
    name: name.text.trim(),
    quantity: double.parse(quantity.text.trim()),
    unit: unit.text.trim(),
    sourceLabel: source.text.trim(),
    nutrients: RecipeNutrients({
      for (final entry in nutrients.entries)
        entry.key: entry.value.text.trim().isEmpty
            ? null
            : double.parse(entry.value.text.trim()),
    }),
  );

  void dispose() {
    name.dispose();
    quantity.dispose();
    unit.dispose();
    source.dispose();
    for (final field in nutrients.values) {
      field.dispose();
    }
  }
}

String? _required(String? value, int maxLength) {
  final text = value?.trim() ?? '';
  return text.isEmpty || text.length > maxLength
      ? 'Enter 1 to $maxLength characters.'
      : null;
}

String? _positive(String? value, int maximum) {
  final number = double.tryParse(value?.trim() ?? '');
  return number == null ||
          !number.isFinite ||
          number < 0.001 ||
          number > maximum
      ? 'Enter a number from 0.001 to $maximum.'
      : null;
}

String? _nutrient(String? value) {
  if (value == null || value.trim().isEmpty) return null;
  final number = double.tryParse(value.trim());
  return number == null || !number.isFinite || number < 0 || number > 1000000
      ? 'Enter 0 to 1000000, or leave unknown values blank.'
      : null;
}
