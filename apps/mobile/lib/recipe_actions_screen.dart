import 'package:flutter/material.dart';

import 'services/custom_recipe_models.dart';
import 'services/recipe_action_controller.dart';
import 'services/recipe_action_models.dart';

class RecipeActionStatus extends StatelessWidget {
  const RecipeActionStatus({required this.controller, super.key});
  final RecipeActionController controller;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) {
      if (!controller.active) return const SizedBox.shrink();
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (controller.busy) const LinearProgressIndicator(),
          if (controller.error != null) ...[
            Semantics(liveRegion: true, child: Text(controller.error!)),
            if (controller.pending == null && !controller.canStart)
              TextButton(
                onPressed: controller.busy ? null : controller.initialize,
                child: const Text('Retry action recovery'),
              ),
          ],
          if (controller.notice != null)
            Semantics(liveRegion: true, child: Text(controller.notice!)),
          if (controller.pending != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Unconfirmed ${controller.pending!.kind == RecipeActionKind.diary ? 'diary entry' : 'shopping addition'}: ${controller.pending!.recipeName}',
                    ),
                    const Text(
                      'The original request is kept securely. Retry uses the same identity, servings and selection; do not submit it again as a new action.',
                    ),
                    TextButton(
                      onPressed: controller.busy ? null : controller.retry,
                      child: const Text('Retry original action'),
                    ),
                  ],
                ),
              ),
            ),
        ],
      );
    },
  );
}

class RecipeActionsScreen extends StatefulWidget {
  const RecipeActionsScreen({
    required this.recipe,
    required this.controller,
    super.key,
  });
  final CustomRecipe recipe;
  final RecipeActionController controller;
  @override
  State<RecipeActionsScreen> createState() => _RecipeActionsScreenState();
}

class _RecipeActionsScreenState extends State<RecipeActionsScreen> {
  final _form = GlobalKey<FormState>();
  final _servings = TextEditingController(text: '1');
  RecipePantryCheck? _check;
  final _selected = <String>{};
  bool _confirming = false;

  double? _validatedServings() {
    if (!_form.currentState!.validate()) return null;
    return double.parse(_servings.text.trim());
  }

  Future<void> _log() async {
    if (!widget.controller.canStart || _confirming) return;
    final servings = _validatedServings();
    if (servings == null) return;
    setState(() => _confirming = true);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Log food you actually consumed?'),
        content: Text(
          'Add ${recipeNumber(servings)} servings of ${widget.recipe.draft.name} to your diary now. Unknown nutrients stay Unknown. Pantry stock will not change.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Confirm consumed'),
          ),
        ],
      ),
    );
    if (!mounted) return;
    setState(() => _confirming = false);
    if (confirmed == true && widget.controller.canStart) {
      await widget.controller.logConsumed(widget.recipe, servings);
    }
  }

  Future<void> _checkPantry() async {
    final servings = _validatedServings();
    if (servings == null || !widget.controller.canStart) return;
    setState(() {
      _check = null;
      _selected.clear();
    });
    final result = await widget.controller.checkPantry(widget.recipe, servings);
    if (!mounted || !widget.controller.active) return;
    setState(() => _check = result);
  }

  Future<void> _addSelected() async {
    final check = _check;
    if (check == null || !widget.controller.canStart || _selected.isEmpty) {
      return;
    }
    await widget.controller.addMissing(widget.recipe, check, Set.of(_selected));
    if (!mounted || !widget.controller.active) return;
    setState(() {
      _check = null;
      _selected.clear();
    });
  }

  @override
  void dispose() {
    _servings.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Use saved recipe')),
    body: ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        if (!widget.controller.active) {
          return const Center(
            child: Text('Your account changed. Close this recipe action.'),
          );
        }
        final enabled = widget.controller.canStart && !_confirming;
        return Form(
          key: _form,
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                widget.recipe.draft.name,
                style: Theme.of(context).textTheme.titleLarge,
              ),
              Text(
                'Saved version ${widget.recipe.version} · ${recipeNumber(widget.recipe.draft.servings)} servings in the full recipe',
              ),
              const SizedBox(height: 12),
              const Text(
                'Saving or checking a recipe does not mean you ate it. Only explicitly confirmed consumption is logged. Nutrition comes from your saved ingredient evidence, not inferred weights.',
              ),
              TextFormField(
                controller: _servings,
                enabled: enabled,
                keyboardType: const TextInputType.numberWithOptions(
                  decimal: true,
                ),
                decoration: const InputDecoration(
                  labelText: 'Recipe servings to use',
                ),
                validator: (raw) {
                  final value = double.tryParse(raw?.trim() ?? '');
                  return value == null ||
                          !value.isFinite ||
                          value < .001 ||
                          value > 1000
                      ? 'Enter servings from 0.001 to 1000.'
                      : null;
                },
                onChanged: (_) => setState(() {
                  _check = null;
                  _selected.clear();
                }),
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    onPressed: enabled ? _log : null,
                    icon: const Icon(Icons.restaurant),
                    label: const Text('Log consumed servings'),
                  ),
                  OutlinedButton.icon(
                    onPressed: enabled ? _checkPantry : null,
                    icon: const Icon(Icons.kitchen_outlined),
                    label: const Text('Check pantry ingredients'),
                  ),
                ],
              ),
              RecipeActionStatus(controller: widget.controller),
              if (_check != null) ...[
                const SizedBox(height: 16),
                Text(
                  'Pantry check for ${recipeNumber(_check!.servings)} servings',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(_check!.limitation),
                const Text(
                  'Select only the missing ingredients you want added. No stock is deducted and no shopping purchase is made.',
                ),
                for (final item in _check!.ingredients)
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(item.name),
                    subtitle: Text(
                      'Needed ${recipeNumber(item.requiredQuantity)} ${item.unit} · Available ${_amount(item.availableQuantity)} ${item.unit}\n${item.status == 'UNIT_MISMATCH'
                          ? 'Unit mismatch: missing amount is Unknown; review pantry units first.'
                          : item.status == 'AVAILABLE'
                          ? 'Available'
                          : 'Missing ${_amount(item.missingQuantity)} ${item.unit}'}',
                    ),
                    value: _selected.contains(item.key),
                    onChanged: enabled && item.canAdd
                        ? (value) => setState(() {
                            if (value == true) {
                              _selected.add(item.key);
                            } else {
                              _selected.remove(item.key);
                            }
                          })
                        : null,
                  ),
                FilledButton.tonal(
                  onPressed: enabled && _selected.isNotEmpty
                      ? _addSelected
                      : null,
                  child: Text(
                    'Add ${_selected.length} selected missing ingredients',
                  ),
                ),
              ],
            ],
          ),
        );
      },
    ),
  );

  String _amount(double? value) =>
      value == null ? 'Unknown' : recipeNumber(value);
}
