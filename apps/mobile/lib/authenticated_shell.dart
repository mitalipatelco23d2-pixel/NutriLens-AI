import 'package:flutter/material.dart';

import 'account_profile_screen.dart';
import 'account_security_screen.dart';
import 'config/app_config.dart';
import 'account_data_screen.dart';
import 'hydration_screen.dart';
import 'health_connect_screen.dart';
import 'custom_recipes_screen.dart';
import 'weight_screen.dart';
import 'reminder_settings_screen.dart';
import 'scanner_screen.dart';
import 'services/assistant_voice_service.dart';
import 'services/account_data.dart';
import 'services/auth_service.dart';
import 'services/product_api.dart';
import 'services/scan_api.dart';
import 'services/intelligence_api.dart';
import 'services/local_reminders.dart';
import 'services/client_inference.dart';
import 'services/hydration_controller.dart';
import 'services/health_connect.dart';
import 'services/custom_recipe_controller.dart';
import 'services/recipe_action_controller.dart';
import 'services/weight_models.dart';

class AuthenticatedShell extends StatefulWidget {
  const AuthenticatedShell({
    required this.config,
    required this.session,
    required this.products,
    required this.scanGateway,
    this.intelligenceGateway,
    this.clientEvidenceGateway,
    this.localReminders,
    this.healthConnect,
    super.key,
  });

  final AppConfig config;
  final SessionController session;
  final ProductGateway products;
  final ScanGateway scanGateway;
  final IntelligenceGateway? intelligenceGateway;
  final ClientEvidenceGateway? clientEvidenceGateway;
  final LocalReminderCoordinator? localReminders;
  final HealthConnectCoordinator? healthConnect;

  @override
  State<AuthenticatedShell> createState() => _AuthenticatedShellState();
}

class _AuthenticatedShellState extends State<AuthenticatedShell>
    with WidgetsBindingObserver {
  var _selected = 0;
  late final HydrationController _hydration;
  late final CustomRecipeController _customRecipes;
  late final RecipeActionController _recipeActions;
  int _recipeDataRevision = 0;

  @override
  void initState() {
    super.initState();
    _hydration = HydrationController(
      gateway: widget.products,
      ownerId: widget.session.user!.id,
      currentOwnerId: () => widget.session.user?.id,
    );
    _customRecipes = CustomRecipeController(
      gateway: widget.products,
      ownerId: widget.session.user!.id,
      currentOwnerId: () => widget.session.user?.id,
    );
    _recipeActions = RecipeActionController(
      gateway: widget.products,
      ownerId: widget.session.user!.id,
      currentOwnerId: () => widget.session.user?.id,
    );
    widget.session.addListener(_sessionChanged);
    WidgetsBinding.instance.addObserver(this);
    _hydration.initialize();
  }

  void _sessionChanged() {
    if (widget.session.user?.id != _hydration.ownerId) _hydration.invalidate();
    if (widget.session.user?.id != _customRecipes.ownerId) {
      _customRecipes.invalidate();
      _recipeActions.invalidate();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _hydration.refresh();
  }

  Future<void> _openHydration() async {
    if (!_hydration.active) return;
    _hydration.refresh();
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => HydrationScreen(
          controller: _hydration,
          localReminders: widget.localReminders,
          ownerId: widget.session.user?.id ?? '',
        ),
      ),
    );
    if (mounted) _hydration.refresh();
  }

  Future<void> _openCustomRecipes() async {
    if (!_customRecipes.active) return;
    _customRecipes.refresh();
    _recipeActions.initialize();
    await Navigator.push(
      context,
      MaterialPageRoute<void>(
        builder: (_) => CustomRecipesScreen(
          controller: _customRecipes,
          actions: _recipeActions,
        ),
      ),
    );
    if (mounted) setState(() => _recipeDataRevision++);
  }

  @override
  void dispose() {
    widget.session.removeListener(_sessionChanged);
    WidgetsBinding.instance.removeObserver(this);
    _hydration.invalidate();
    _hydration.dispose();
    _customRecipes.invalidate();
    _customRecipes.dispose();
    _recipeActions.invalidate();
    _recipeActions.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.session.user;
    if (user == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return Scaffold(
      appBar: AppBar(
        title: const Text('NutriLens X'),
        actions: [
          Semantics(
            label: 'Account profile',
            button: true,
            child: IconButton(
              icon: const Icon(Icons.account_circle_outlined),
              onPressed: () => setState(() => _selected = 4),
            ),
          ),
        ],
      ),
      body: IndexedStack(
        index: _selected,
        children: [
          _Dashboard(
            key: ValueKey('tab-today-$_recipeDataRevision'),
            user: user,
            products: widget.products,
            hydration: _hydration,
            onWater: _openHydration,
            onAskNutri: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => AssistantScreen(products: widget.products),
              ),
            ),
          ),
          ScannerScreen(
            key: const ValueKey('tab-scan'),
            scanGateway: widget.scanGateway,
            intelligenceGateway: widget.intelligenceGateway,
            productGateway: widget.products,
            clientEvidenceGateway: widget.clientEvidenceGateway,
            localReminders: widget.localReminders,
            ownerId: user.id,
            onAskNutri: (scanId) => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) =>
                    AssistantScreen(products: widget.products, scanId: scanId),
              ),
            ),
          ),
          DiaryScreen(
            key: ValueKey('diary-$_recipeDataRevision'),
            products: widget.products,
            onDiaryChanged: () => setState(() => _recipeDataRevision++),
          ),
          PantryScreen(
            key: ValueKey('pantry-$_recipeDataRevision'),
            products: widget.products,
            ownerId: user.id,
            localReminders: widget.localReminders,
          ),
          AccountHub(
            key: const ValueKey('tab-more'),
            session: widget.session,
            products: widget.products,
            onWater: _openHydration,
            onRecipes: _openCustomRecipes,
            localReminders: widget.localReminders,
            healthConnect: widget.healthConnect,
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selected,
        onDestinationSelected: (value) {
          setState(() => _selected = value);
          if (value == 0) _hydration.refresh();
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            label: 'Today',
          ),
          NavigationDestination(
            icon: Icon(Icons.document_scanner_outlined),
            label: 'Scan',
          ),
          NavigationDestination(
            icon: Icon(Icons.menu_book_outlined),
            label: 'Diary',
          ),
          NavigationDestination(
            icon: Icon(Icons.kitchen_outlined),
            label: 'Pantry',
          ),
          NavigationDestination(
            icon: Icon(Icons.grid_view_outlined),
            label: 'More',
          ),
        ],
      ),
    );
  }
}

class _Dashboard extends StatefulWidget {
  const _Dashboard({
    super.key,
    required this.user,
    required this.products,
    required this.onAskNutri,
    required this.hydration,
    required this.onWater,
  });

  final AuthenticatedUser user;
  final ProductGateway products;
  final VoidCallback onAskNutri;
  final HydrationController hydration;
  final VoidCallback onWater;

  @override
  State<_Dashboard> createState() => _DashboardState();
}

class _DashboardState extends State<_Dashboard> {
  int _refreshCounter = 0;

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async {
        if (mounted) {
          setState(() => _refreshCounter++);
        }
        await widget.hydration.refresh();
      },
      child: FutureBuilder<AnalyticsSummary>(
        key: ValueKey('analytics-$_refreshCounter'),
        future: widget.products.analytics(),
        builder: (context, snapshot) {
          final summary = snapshot.data;
          return ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                'Hello, ${widget.user.name}',
                style: Theme.of(context).textTheme.headlineMedium,
              ),
              const SizedBox(height: 6),
              Text('${widget.user.plan} plan · wellness guidance, not medical advice'),
              const SizedBox(height: 16),
              FilledButton.tonalIcon(
                onPressed: widget.onAskNutri,
                icon: const Icon(Icons.chat_bubble_outline),
                label: const Text('Ask Nutri'),
              ),
              const SizedBox(height: 20),
              HydrationSummaryCard(controller: widget.hydration, onOpen: widget.onWater),
              FutureBuilder<WeightSummary>(
                key: ValueKey('weight-$_refreshCounter'),
                future: widget.products.weightSummary(limit: 2),
                builder: (context, weightSnapshot) {
                  final weight = weightSnapshot.data;
                  return Card(
                    child: ListTile(
                      leading: const Icon(Icons.monitor_weight_outlined),
                      title: const Text('Weight tracking'),
                      subtitle: Text(
                        weightSnapshot.hasError
                            ? 'Unavailable · open to retry'
                            : weight == null
                            ? 'Loading optional self-reported history…'
                            : weight.state == 'DISABLED'
                            ? 'Off · optional and consent-based'
                            : weight.latestWeightKg == null
                            ? 'On · no records yet'
                            : '${weight.latestWeightKg!.toStringAsFixed(2)} kg'
                                  '${weight.changeFromFirstKg == null ? '' : ' · ${weight.changeFromFirstKg! > 0 ? '+' : ''}${weight.changeFromFirstKg!.toStringAsFixed(2)} kg across returned records'}',
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => WeightScreen(gateway: widget.products),
                        ),
                      ),
                    ),
                  );
                },
              ),
              if (snapshot.connectionState == ConnectionState.waiting)
                const LinearProgressIndicator()
              else if (snapshot.hasError)
                _ErrorCard(message: snapshot.error.toString())
              else ...[
                _MetricCard(
                  label: 'Diary entries',
                  value: '${summary!.diaryEntries}',
                ),
                _MetricCard(
                  label: 'Daily energy',
                  value:
                      '${nutrientEvidence(summary.dailyAverages.calories, decimals: 0)} kcal',
                ),
                _MetricCard(
                  label: 'Daily protein',
                  value:
                      '${nutrientEvidence(summary.dailyAverages.proteinG)} g',
                ),
                _MetricCard(
                  label: 'Daily calcium',
                  value:
                      '${nutrientEvidence(summary.dailyAverages.calciumMg, decimals: 0)} mg',
                ),
                FutureBuilder<ProfileSnapshot>(
                  key: ValueKey('dash-profile-$_refreshCounter'),
                  future: widget.products.profile(),
                  builder: (context, profSnapshot) {
                    final prof = profSnapshot.data;
                    final conditions = prof?.healthConditions ?? const [];
                    final style = prof?.dietaryStyle ?? 'No specific diet';
                    final conditionNotes = <String>[];
                    if (conditions.contains('Diabetes')) {
                      conditionNotes.add('Monitoring carbohydrate and sugar content');
                    }
                    if (conditions.contains('Hypertension') || conditions.contains('Heart health')) {
                      conditionNotes.add('Watching sodium and saturated fat intake');
                    }
                    if (conditions.contains('Kidney')) {
                      conditionNotes.add('Tracking protein and electrolyte balance');
                    }
                    if (conditions.contains('High cholesterol')) {
                      conditionNotes.add('Prioritizing fiber and healthy fats');
                    }
                    if (conditions.contains('PCOS')) {
                      conditionNotes.add('Focusing on low-glycemic, balanced meals');
                    }
                    if (style != 'No specific diet') {
                      conditionNotes.add('Adhering to $style dietary style');
                    }

                    return Card(
                      key: const Key('daily-guidance-card'),
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                const Icon(Icons.shield_outlined, size: 20),
                                const SizedBox(width: 8),
                                Text(
                                  'Daily guidance summary',
                                  style: Theme.of(context).textTheme.titleMedium,
                                ),
                              ],
                            ),
                            const SizedBox(height: 6),
                            if (conditions.isNotEmpty || style != 'No specific diet') ...[
                              Text(
                                'Personalized for your profile: ${style != 'No specific diet' ? style : ''}${style != 'No specific diet' && conditions.isNotEmpty ? ' · ' : ''}${conditions.join(', ')}',
                                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
                              ),
                              const SizedBox(height: 4),
                              for (final note in conditionNotes)
                                Padding(
                                  padding: const EdgeInsets.symmetric(vertical: 2),
                                  child: Text('• $note', style: const TextStyle(fontSize: 13)),
                                ),
                            ] else
                              const Text(
                                'No specific health conditions or dietary style recorded. Configure in Settings > Health profile for personalized evidence guidance.',
                                style: TextStyle(fontSize: 13),
                              ),
                            const SizedBox(height: 6),
                            const Text(
                              'Wellness decision support only. Not medical treatment, diagnosis or cure.',
                              style: TextStyle(fontSize: 11, fontStyle: FontStyle.italic),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
                const Text(
                  'Missing nutrient evidence stays Unknown, not zero. Averages describe only the logged food; they are not a complete intake estimate.',
                ),
                for (final insight in summary.insights)
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.lightbulb_outline),
                      title: Text(insight),
                    ),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class DiaryScreen extends StatefulWidget {
  const DiaryScreen({required this.products, this.onDiaryChanged, super.key});
  final ProductGateway products;
  final VoidCallback? onDiaryChanged;

  @override
  State<DiaryScreen> createState() => _DiaryScreenState();
}

class _DiaryScreenState extends State<DiaryScreen> {
  late Future<List<DiaryEntry>> _entries;
  final Set<String> _selectedForComparison = {};
  MealComparison? _comparison;
  bool _comparing = false;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() => _entries = widget.products.diary();

  Future<void> _add() async {
    final name = TextEditingController();
    final calories = TextEditingController();
    final calcium = TextEditingController();
    final iron = TextEditingController();
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add diary entry'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: name,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Food or meal'),
            ),
            TextField(
              controller: calories,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Calories (optional)',
              ),
            ),
            TextField(
              controller: calcium,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Calcium mg (optional)',
              ),
            ),
            TextField(
              controller: iron,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Iron mg (optional)',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Add'),
          ),
        ],
      ),
    );
    final value = name.text.trim();
    if (accepted != true || value.isEmpty) return;
    try {
      await widget.products.addDiary(
        name: value,
        nutrients: Nutrients(
          calories: double.tryParse(calories.text) ?? 0,
          calciumMg: double.tryParse(calcium.text) ?? 0,
          ironMg: double.tryParse(iron.text) ?? 0,
        ),
      );
      if (mounted) {
        setState(_reload);
        widget.onDiaryChanged?.call();
      }
    } on Object catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not add diary entry: $error')),
        );
      }
    }
  }

  Future<void> _compare() async {
    if (_selectedForComparison.length < 2) return;
    setState(() => _comparing = true);
    try {
      final comparison = await widget.products.compareDiary(
        _selectedForComparison.toList(growable: false),
      );
      if (mounted) setState(() => _comparison = comparison);
    } finally {
      if (mounted) setState(() => _comparing = false);
    }
  }

  @override
  Widget build(BuildContext context) => _AsyncList<DiaryEntry>(
    title: 'Food diary',
    future: _entries,
    emptyMessage: 'No diary entries yet.',
    onAdd: _add,
    footer: [
      const SizedBox(height: 18),
      FilledButton.icon(
        onPressed: _selectedForComparison.length < 2 || _comparing
            ? null
            : _compare,
        icon: const Icon(Icons.compare_arrows),
        label: Text(
          _comparing
              ? 'Comparing…'
              : 'Compare ${_selectedForComparison.length} meals',
        ),
      ),
      if (_comparison != null) ...[
        const SizedBox(height: 12),
        Text(
          'Recorded meal comparison',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const Text('Logged serving values; no healthier-meal ranking.'),
        for (final candidate in _comparison!.candidates)
          Card(
            child: ListTile(
              title: Text(candidate.name),
              subtitle: Text(
                '${candidate.servingDescription} · '
                '${nutrientEvidence(candidate.loggedServing.proteinG)} g protein · '
                '${nutrientEvidence(candidate.loggedServing.sodiumMg, decimals: 0)} mg sodium\n'
                'Per 100 g: ${nutrientEvidence(candidate.per100g.calories, decimals: 0)} kcal',
              ),
              trailing: Text(
                '${nutrientEvidence(candidate.loggedServing.calories, decimals: 0)} kcal',
              ),
            ),
          ),
        Text(_comparison!.limitation),
      ],
    ],
    itemBuilder: (itemContext, entry) => Dismissible(
      key: ValueKey(entry.id),
      direction: DismissDirection.endToStart,
      background: Container(
        color: Theme.of(itemContext).colorScheme.errorContainer,
      ),
      onDismissed: (_) {
        widget.products.deleteDiary(entry.id);
        setState(() {
          _selectedForComparison.remove(entry.id);
          _comparison = null;
          _reload();
        });
        widget.onDiaryChanged?.call();
      },
      child: ListTile(
        onTap: () => _editDiary(entry),
        leading: Checkbox(
          value: _selectedForComparison.contains(entry.id),
          onChanged:
              !_selectedForComparison.contains(entry.id) &&
                  _selectedForComparison.length >= 5
              ? null
              : (selected) => setState(() {
                  if (selected ?? false) {
                    _selectedForComparison.add(entry.id);
                  } else {
                    _selectedForComparison.remove(entry.id);
                  }
                  _comparison = null;
                }),
        ),
        title: Text(entry.name),
        subtitle: Text(
          '${entry.servingDescription} · ${nutrientEvidence(entry.nutrients.calories, decimals: 0)} kcal',
        ),
        trailing: IconButton(
          icon: const Icon(Icons.edit_outlined),
          onPressed: () => _editDiary(entry),
        ),
      ),
    ),
  );

  Future<void> _editDiary(DiaryEntry entry) async {
    final name = TextEditingController(text: entry.name);
    final calories = TextEditingController(
      text: entry.nutrients.calories != null ? '${entry.nutrients.calories}' : '',
    );
    final calcium = TextEditingController(
      text: entry.nutrients.calciumMg != null ? '${entry.nutrients.calciumMg}' : '',
    );
    final iron = TextEditingController(
      text: entry.nutrients.ironMg != null ? '${entry.nutrients.ironMg}' : '',
    );
    final servingGrams = TextEditingController(
      text: entry.servingGrams != null ? '${entry.servingGrams}' : '',
    );

    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Edit diary entry'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: name,
                decoration: const InputDecoration(labelText: 'Food or meal'),
              ),
              TextField(
                controller: servingGrams,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Serving mass (grams)'),
              ),
              TextField(
                controller: calories,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Calories'),
              ),
              TextField(
                controller: calcium,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Calcium (mg)'),
              ),
              TextField(
                controller: iron,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Iron (mg)'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Save'),
          ),
        ],
      ),
    );

    if (accepted != true || name.text.trim().isEmpty) return;
    try {
      final newServing = double.tryParse(servingGrams.text);
      final oldServing = entry.servingGrams;
      final scaleFactor = (oldServing != null && oldServing > 0 && newServing != null && newServing > 0)
          ? newServing / oldServing
          : 1.0;

      final calInput = double.tryParse(calories.text);
      final calcInput = double.tryParse(calcium.text);
      final ironInput = double.tryParse(iron.text);

      // If user kept the original values but changed serving mass, scale proportionally
      final finalCal = (calInput != null && oldServing != null && newServing != null && oldServing != newServing && calInput == entry.nutrients.calories)
          ? calInput * scaleFactor
          : calInput;
      final finalCalc = (calcInput != null && oldServing != null && newServing != null && oldServing != newServing && calcInput == entry.nutrients.calciumMg)
          ? calcInput * scaleFactor
          : calcInput;
      final finalIron = (ironInput != null && oldServing != null && newServing != null && oldServing != newServing && ironInput == entry.nutrients.ironMg)
          ? ironInput * scaleFactor
          : ironInput;

      final bodyMap = <String, dynamic>{
        'name': name.text.trim(),
        'nutrients': <String, dynamic>{},
      };
      if (newServing != null) {
        bodyMap['serving_grams'] = newServing;
      }
      if (entry.scanId != null) {
        bodyMap['scan_id'] = entry.scanId;
      }
      final nutrientsMap = bodyMap['nutrients'] as Map<String, dynamic>;
      if (finalCal != null) nutrientsMap['calories'] = finalCal;
      if (finalCalc != null) nutrientsMap['calcium_mg'] = finalCalc;
      if (finalIron != null) nutrientsMap['iron_mg'] = finalIron;

      // Also scale other observed nutrients if serving mass scaled
      if (scaleFactor != 1.0) {
        if (entry.nutrients.proteinG != null) {
          nutrientsMap['protein_g'] = entry.nutrients.proteinG! * scaleFactor;
        }
        if (entry.nutrients.carbsG != null) {
          nutrientsMap['carbs_g'] = entry.nutrients.carbsG! * scaleFactor;
        }
        if (entry.nutrients.fatG != null) {
          nutrientsMap['fat_g'] = entry.nutrients.fatG! * scaleFactor;
        }
        if (entry.nutrients.sugarG != null) {
          nutrientsMap['sugar_g'] = entry.nutrients.sugarG! * scaleFactor;
        }
        if (entry.nutrients.sodiumMg != null) {
          nutrientsMap['sodium_mg'] = entry.nutrients.sodiumMg! * scaleFactor;
        }
        if (entry.nutrients.fiberG != null) {
          nutrientsMap['fiber_g'] = entry.nutrients.fiberG! * scaleFactor;
        }
      } else {
        if (entry.nutrients.proteinG != null) nutrientsMap['protein_g'] = entry.nutrients.proteinG;
        if (entry.nutrients.carbsG != null) nutrientsMap['carbs_g'] = entry.nutrients.carbsG;
        if (entry.nutrients.fatG != null) nutrientsMap['fat_g'] = entry.nutrients.fatG;
        if (entry.nutrients.sugarG != null) nutrientsMap['sugar_g'] = entry.nutrients.sugarG;
        if (entry.nutrients.sodiumMg != null) nutrientsMap['sodium_mg'] = entry.nutrients.sodiumMg;
        if (entry.nutrients.fiberG != null) nutrientsMap['fiber_g'] = entry.nutrients.fiberG;
      }

      await widget.products.client.patch(
        '/api/v1/diary/${Uri.encodeComponent(entry.id)}',
        body: bodyMap,
      );
      if (mounted) {
        setState(_reload);
        widget.onDiaryChanged?.call();
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not update diary entry: $error')),
        );
      }
    }
  }
}

class PantryScreen extends StatefulWidget {
  const PantryScreen({
    required this.products,
    this.ownerId,
    this.localReminders,
    super.key,
  });
  final ProductGateway products;
  final String? ownerId;
  final LocalReminderCoordinator? localReminders;

  @override
  State<PantryScreen> createState() => _PantryScreenState();
}

class _PantryScreenState extends State<PantryScreen> {
  late Future<List<PantryItem>> _items;
  late Future<List<RecipeRecommendation>> _recipes;
  late Future<UseSoonRecipeResponse> _useSoon;
  late Future<List<ShoppingListItem>> _shopping;
  String _recipeMode = 'COOK_WITH_WHAT_I_HAVE';
  final Set<String> _selectedIngredients = <String>{};

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    _items = widget.products.pantry();
    _recipes = widget.products.recipes(
      mode: _recipeMode,
      selectedIngredients: _recipeMode == 'USE_SELECTED_INGREDIENTS'
          ? _selectedIngredients.toList(growable: false)
          : null,
    );
    _useSoon = widget.products.useSoonRecipes();
    _shopping = widget.products.shoppingList();
  }

  Future<void> _add() async {
    final name = TextEditingController();
    final quantity = TextEditingController(text: '1');
    final threshold = TextEditingController();
    String selectedUnit = 'g';
    String selectedRole = 'INGREDIENT';
    const unitOptions = ['g', 'kg', 'ml', 'l', 'cup', 'tbsp', 'tsp', 'item', 'packet', 'slice'];
    const roleOptions = ['INGREDIENT', 'LEFTOVER'];

    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setModalState) => AlertDialog(
          title: const Text('Add pantry item'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Item name'),
                ),
                TextField(
                  controller: quantity,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(labelText: 'Current quantity'),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: selectedUnit,
                  decoration: const InputDecoration(labelText: 'Unit'),
                  items: unitOptions.map((u) => DropdownMenuItem(value: u, child: Text(u))).toList(),
                  onChanged: (val) => setModalState(() => selectedUnit = val ?? 'g'),
                ),
                TextField(
                  controller: threshold,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Low-stock threshold (optional)',
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: selectedRole,
                  decoration: const InputDecoration(
                    labelText: 'Role',
                    helperText: 'INGREDIENT or LEFTOVER',
                  ),
                  items: roleOptions.map((r) => DropdownMenuItem(value: r, child: Text(r))).toList(),
                  onChanged: (val) => setModalState(() => selectedRole = val ?? 'INGREDIENT'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Add'),
            ),
          ],
        ),
      ),
    );
    final parsedQuantity = double.tryParse(quantity.text);
    final parsedThreshold = threshold.text.trim().isEmpty
        ? null
        : double.tryParse(threshold.text);
    if (accepted != true ||
        name.text.trim().isEmpty ||
        parsedQuantity == null ||
        parsedQuantity <= 0 ||
        (threshold.text.trim().isNotEmpty &&
            (parsedThreshold == null || parsedThreshold <= 0))) {
      return;
    }
    try {
      await widget.products.addPantry(
        name: name.text.trim(),
        quantity: parsedQuantity,
        unit: selectedUnit,
        lowStockThreshold: parsedThreshold,
        itemRole: selectedRole,
      );
      if (parsedThreshold != null && parsedQuantity <= parsedThreshold) {
        await _notifyLowStock(
          itemName: name.text.trim(),
          quantity: parsedQuantity,
          unit: selectedUnit,
        );
      }
      if (mounted) setState(_reload);
    } on Object catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not add pantry item: $error')),
        );
      }
    }
  }

  Future<void> _deletePantryWithConfirmation(PantryItem item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete ${item.name}?'),
        content: Text('Are you sure you want to remove ${item.name} from your smart pantry?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      try {
        await widget.products.deletePantry(item.id);
        if (mounted) {
          setState(_reload);
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Removed ${item.name} from pantry')),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not delete pantry item: $e')),
          );
        }
      }
    }
  }

  Future<void> _editPantry(PantryItem item) async {
    final quantity = TextEditingController(text: item.quantity.toString());
    final threshold = TextEditingController(
      text: item.lowStockThreshold?.toString() ?? '',
    );
    String selectedRole = item.itemRole;
    if (!['INGREDIENT', 'LEFTOVER'].contains(selectedRole)) {
      selectedRole = 'INGREDIENT';
    }
    const roleOptions = ['INGREDIENT', 'LEFTOVER'];

    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setModalState) => AlertDialog(
          title: Text('Update ${item.name}'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: quantity,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(labelText: 'Quantity (${item.unit})'),
                ),
                TextField(
                  controller: threshold,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: InputDecoration(
                    labelText: 'Low-stock threshold (${item.unit})',
                    helperText: 'Leave blank to disable the alert.',
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: selectedRole,
                  decoration: const InputDecoration(
                    labelText: 'Role',
                    helperText: 'INGREDIENT or LEFTOVER',
                  ),
                  items: roleOptions.map((r) => DropdownMenuItem(value: r, child: Text(r))).toList(),
                  onChanged: (val) => setModalState(() => selectedRole = val ?? 'INGREDIENT'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    final parsedQuantity = double.tryParse(quantity.text);
    final parsedThreshold = threshold.text.trim().isEmpty
        ? null
        : double.tryParse(threshold.text);
    if (accepted == true &&
        parsedQuantity != null &&
        parsedQuantity > 0 &&
        (threshold.text.trim().isEmpty ||
            (parsedThreshold != null && parsedThreshold > 0))) {
      try {
        await widget.products.updatePantry(
          item.id,
          quantity: parsedQuantity,
          lowStockThreshold: parsedThreshold,
          itemRole: selectedRole,
        );
        final wasLowStock =
            item.lowStockThreshold != null &&
            item.quantity <= item.lowStockThreshold!;
        final isLowStock =
            parsedThreshold != null && parsedQuantity <= parsedThreshold;
        if (isLowStock && !wasLowStock) {
          await _notifyLowStock(
            itemName: item.name,
            quantity: parsedQuantity,
            unit: item.unit,
          );
        }
        if (mounted) setState(_reload);
      } on Object catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not update ${item.name}: $error')),
          );
        }
      }
    }
  }

  Future<void> _notifyLowStock({
    required String itemName,
    required double quantity,
    required String unit,
  }) async {
    final reminders = widget.localReminders;
    final ownerId = widget.ownerId;
    if (reminders == null || ownerId == null) return;
    try {
      await reminders.notifyLowStock(
        ownerId,
        itemName: itemName,
        quantity: quantity,
        unit: unit,
      );
    } on Object {
      // Pantry persistence is authoritative; a local notification is best effort.
    }
  }

  Future<void> _addShoppingItem() async {
    final name = TextEditingController();
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add shopping item'),
        content: TextField(
          controller: name,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Item name'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Add'),
          ),
        ],
      ),
    );
    if (accepted == true && name.text.trim().isNotEmpty) {
      try {
        await widget.products.addShoppingListItem(name.text.trim());
        if (mounted) setState(_reload);
      } on Object catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not add shopping item: $error')),
          );
        }
      }
    }
  }

  Future<void> _editShoppingItem(ShoppingListItem item) async {
    final name = TextEditingController(text: item.name);
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Edit shopping item'),
        content: TextField(
          controller: name,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Item name'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (accepted == true && name.text.trim().isNotEmpty) {
      try {
        await widget.products.updateShoppingListItem(item.id, name: name.text.trim());
        if (mounted) setState(_reload);
      } on Object catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not update shopping item: $error')),
          );
        }
      }
    }
  }

  Future<void> _clearCompletedShoppingList() async {
    final items = await _shopping;
    final checked = items.where((i) => i.checked).toList();
    if (checked.isEmpty) return;
    for (final item in checked) {
      await widget.products.deleteShoppingListItem(item.id);
    }
    if (mounted) setState(_reload);
  }

  Future<void> _generateShoppingList() async {
    final result = await widget.products.generateShoppingListFromLowStock();
    if (!mounted) return;
    setState(_reload);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          '${result.generatedCount} item(s) added. ${result.limitation}',
        ),
      ),
    );
  }

  Future<void> _compareNutrition() async {
    final names = [
      TextEditingController(text: 'Recipe one'),
      TextEditingController(text: 'Recipe two'),
    ];
    final servings = [
      TextEditingController(text: '1'),
      TextEditingController(text: '1'),
    ];
    final calories = [TextEditingController(), TextEditingController()];
    final protein = [TextEditingController(), TextEditingController()];
    final fiber = [TextEditingController(), TextEditingController()];
    final sodium = [TextEditingController(), TextEditingController()];
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Compare recipe nutrition'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Enter totals for each whole recipe and the number of servings yielded.',
              ),
              for (var index = 0; index < 2; index++) ...[
                const SizedBox(height: 14),
                Text('Recipe ${index + 1}'),
                TextField(
                  controller: names[index],
                  decoration: const InputDecoration(labelText: 'Name'),
                ),
                TextField(
                  controller: servings[index],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Servings yielded',
                  ),
                ),
                TextField(
                  controller: calories[index],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Whole recipe energy (kcal)',
                  ),
                ),
                TextField(
                  controller: protein[index],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Whole recipe protein (g)',
                  ),
                ),
                TextField(
                  controller: fiber[index],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Whole recipe fiber (g)',
                  ),
                ),
                TextField(
                  controller: sodium[index],
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  decoration: const InputDecoration(
                    labelText: 'Whole recipe sodium (mg)',
                  ),
                ),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Compare per serving'),
          ),
        ],
      ),
    );
    if (accepted == true) {
      final candidates = [
        for (var index = 0; index < 2; index++)
          RecipeNutritionInput(
            name: names[index].text.trim(),
            servings: double.tryParse(servings[index].text) ?? 0,
            nutrients: Nutrients(
              calories: double.tryParse(calories[index].text) ?? 0,
              proteinG: double.tryParse(protein[index].text) ?? 0,
              fiberG: double.tryParse(fiber[index].text) ?? 0,
              sodiumMg: double.tryParse(sodium[index].text) ?? 0,
            ),
          ),
      ];
      try {
        final comparison = await widget.products.compareRecipeNutrition(
          candidates,
        );
        if (mounted) {
          await showDialog<void>(
            context: context,
            builder: (context) => AlertDialog(
              title: const Text('Per-serving comparison'),
              content: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final candidate in comparison.candidates)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(candidate.name),
                        subtitle: Text(
                          '${nutrientEvidence(candidate.perServing.calories)} kcal · '
                          '${nutrientEvidence(candidate.perServing.proteinG)} g protein · '
                          '${nutrientEvidence(candidate.perServing.fiberG)} g fiber · '
                          '${nutrientEvidence(candidate.perServing.sodiumMg)} mg sodium',
                        ),
                      ),
                    Text(comparison.limitation),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Close'),
                ),
              ],
            ),
          );
        }
      } on Object catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not compare recipes: $error')),
          );
        }
      }
    }
    for (final controller in [
      ...names,
      ...servings,
      ...calories,
      ...protein,
      ...fiber,
      ...sodium,
    ]) {
      controller.dispose();
    }
  }

  Future<void> _showRecipePlanDialog(RecipeRecommendation recipe) async {
    var servings = recipe.servings > 0 ? recipe.servings : 1.0;
    final totalCount = recipe.totalIngredientsCount ??
        (recipe.completeIngredients.isNotEmpty
            ? recipe.completeIngredients.length
            : recipe.requiredIngredients.length);
    final availableCount = (recipe.coverage * totalCount).round();

    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (statefulContext, setDialogState) => AlertDialog(
          title: Text(recipe.title),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: recipe.coverage >= 0.8
                        ? Colors.green.withValues(alpha: 0.12)
                        : Colors.orange.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Coverage: ${(recipe.coverage * 100).round()}%',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: recipe.coverage >= 0.8 ? Colors.green.shade900 : Colors.orange.shade900,
                        ),
                      ),
                      Text(
                        'You have $availableCount/$totalCount ingredients (${(recipe.coverage * 100).round()}% match)',
                        style: TextStyle(
                          fontSize: 12,
                          color: recipe.coverage >= 0.8 ? Colors.green.shade800 : Colors.orange.shade800,
                        ),
                      ),
                    ],
                  ),
                ),
                if (recipe.nutrientsPerServing != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    'Per serving: ${nutrientEvidence(recipe.nutrientsPerServing!.calories)} kcal · '
                    '${nutrientEvidence(recipe.nutrientsPerServing!.proteinG)}g protein · '
                    '${nutrientEvidence(recipe.nutrientsPerServing!.carbsG)}g carbs · '
                    '${nutrientEvidence(recipe.nutrientsPerServing!.fatG)}g fat',
                    style: const TextStyle(fontSize: 11, color: Colors.blueGrey, fontWeight: FontWeight.w600),
                  ),
                ],
                if (recipe.completeIngredients.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const Text('Complete ingredients:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
                  const SizedBox(height: 4),
                  for (final ing in recipe.completeIngredients)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Text(
                        '• ${ing.name} (${nutrientEvidence(ing.quantity * (recipe.servings > 0 ? servings / recipe.servings : 1.0))} ${ing.unit}) · [${ing.category}]',
                        style: const TextStyle(fontSize: 12),
                      ),
                    ),
                ] else if (recipe.requiredIngredients.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text('Required: ${recipe.requiredIngredients.join(', ')}'),
                ],
                if (recipe.missingRequired.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text('Missing: ${recipe.missingRequired.join(', ')}'),
                ],
                if (recipe.steps.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const Text('Instructions:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
                  const SizedBox(height: 4),
                  for (var i = 0; i < recipe.steps.length; i++)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 2),
                      child: Text('${i + 1}. ${recipe.steps[i]}', style: const TextStyle(fontSize: 12)),
                    ),
                ],
                if (recipe.deficits.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  const Text('Ingredient deficits:', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
                  const SizedBox(height: 4),
                  Builder(
                    builder: (context) {
                      final scale = recipe.servings > 0 ? servings / recipe.servings : 1.0;
                      return Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: recipe.deficits.map((d) {
                          final scaledReq = d.requiredAmount != null ? d.requiredAmount! * scale : null;
                          final avail = d.availableAmount;
                          final unit = d.unit.isNotEmpty ? ' ${d.unit}' : '';
                          final scaledDeficit = (scaledReq != null && avail != null)
                              ? (scaledReq > avail ? scaledReq - avail : 0.0)
                              : (d.deficitAmount != null ? d.deficitAmount! * scale : null);
                          final desc = d.status == 'UNIT_UNCERTAIN'
                              ? 'needs ${nutrientEvidence(scaledReq)}$unit (unit conversion uncertain)'
                              : 'needs ${nutrientEvidence(scaledReq)}$unit, has ${nutrientEvidence(avail)}$unit (deficit ${nutrientEvidence(scaledDeficit)}$unit)';
                          return Padding(
                            padding: const EdgeInsets.symmetric(vertical: 2),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Text('• ${d.name}: $desc', style: const TextStyle(fontSize: 12)),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.add_shopping_cart, size: 18),
                                  tooltip: 'Add ${d.name} to shopping list',
                                  visualDensity: VisualDensity.compact,
                                  onPressed: () async {
                                    final messenger = ScaffoldMessenger.of(context);
                                    try {
                                      final itemLabel = d.unit.isNotEmpty && scaledDeficit != null && scaledDeficit > 0
                                          ? '${d.name} (${scaledDeficit.toStringAsFixed(1)} ${d.unit})'
                                          : d.name;
                                      await widget.products.addShoppingListItem(
                                        itemLabel,
                                        quantity: scaledDeficit,
                                        unit: d.unit.isNotEmpty ? d.unit : null,
                                        recipeId: recipe.id,
                                      );
                                      if (mounted) {
                                        setState(() {
                                          _shopping = widget.products.shoppingList();
                                        });
                                        messenger.showSnackBar(
                                          SnackBar(content: Text('Added ${d.name} to shopping list.')),
                                        );
                                      }
                                    } catch (e) {
                                      if (mounted) {
                                        messenger.showSnackBar(
                                          SnackBar(content: Text('Could not add ${d.name}: $e')),
                                        );
                                      }
                                    }
                                  },
                                ),
                              ],
                            ),
                          );
                        }).toList(),
                      );
                    },
                  ),
                ],
                const SizedBox(height: 12),
                const Text('Servings to plan:'),
                Row(
                  children: [
                    IconButton(
                      icon: const Icon(Icons.remove),
                      onPressed: servings > 1
                          ? () => setDialogState(() => servings -= 1)
                          : null,
                    ),
                    Text('${servings.toInt()}'),
                    IconButton(
                      icon: const Icon(Icons.add),
                      onPressed: () => setDialogState(() => servings += 1),
                    ),
                  ],
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(statefulContext).pop(),
              child: const Text('Cancel'),
            ),
            FilledButton.tonalIcon(
              icon: const Icon(Icons.restaurant_menu),
              label: const Text('Cook & Add to Diary'),
              onPressed: () async {
                Navigator.of(statefulContext).pop();
                // Prompt user for consumed servings (default to 1 or planned servings)
                double consumedServings = 1.0;
                final confirmed = await showDialog<bool>(
                  context: context,
                  builder: (ctx) => StatefulBuilder(
                    builder: (consumeCtx, setConsumeState) => AlertDialog(
                      title: const Text('Log Recipe to Diary'),
                      content: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('You planned/cooked ${servings.toInt()} serving${servings > 1 ? 's' : ''} of ${recipe.title}.'),
                          const SizedBox(height: 12),
                          const Text('How many servings did you eat?'),
                          Row(
                            children: [
                              IconButton(
                                icon: const Icon(Icons.remove),
                                onPressed: consumedServings > 0.5
                                    ? () => setConsumeState(() => consumedServings -= 0.5)
                                    : null,
                              ),
                              Text('$consumedServings serving${consumedServings > 1 ? 's' : ''}'),
                              IconButton(
                                icon: const Icon(Icons.add),
                                onPressed: () => setConsumeState(() => consumedServings += 0.5),
                              ),
                            ],
                          ),
                          if (recipe.nutrientsPerServing != null) ...[
                            const SizedBox(height: 8),
                            Text(
                              'Nutrition consumed: '
                              '${nutrientEvidence(recipe.nutrientsPerServing!.calories != null ? recipe.nutrientsPerServing!.calories! * consumedServings : null)} kcal · '
                              '${nutrientEvidence(recipe.nutrientsPerServing!.proteinG != null ? recipe.nutrientsPerServing!.proteinG! * consumedServings : null)}g protein · '
                              '${nutrientEvidence(recipe.nutrientsPerServing!.carbsG != null ? recipe.nutrientsPerServing!.carbsG! * consumedServings : null)}g carbs · '
                              '${nutrientEvidence(recipe.nutrientsPerServing!.fatG != null ? recipe.nutrientsPerServing!.fatG! * consumedServings : null)}g fat',
                              style: const TextStyle(fontSize: 11, color: Colors.blueGrey, fontWeight: FontWeight.w600),
                            ),
                          ],
                        ],
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.of(consumeCtx).pop(false),
                          child: const Text('Cancel'),
                        ),
                        FilledButton(
                          onPressed: () => Navigator.of(consumeCtx).pop(true),
                          child: const Text('Log to Diary'),
                        ),
                      ],
                    ),
                  ),
                );

                if (confirmed != true) return;

                try {
                  await widget.products.logTemplateRecipeToDiary(
                    recipe.id,
                    servings: consumedServings,
                  );
                  if (mounted) {
                    setState(_reload);
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Added ${recipe.title} to your food diary!')),
                    );
                  }
                } catch (error) {
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Could not add recipe to diary: $error')),
                    );
                  }
                }
              },
            ),
            FilledButton.icon(
              icon: const Icon(Icons.playlist_add),
              label: const Text('Plan to shopping list'),
              onPressed: () async {
                Navigator.of(statefulContext).pop();
                try {
                  await widget.products.planTemplateRecipe(
                    recipe.id,
                    servings: servings,
                  );
                  if (mounted) {
                    setState(() {
                      _shopping = widget.products.shoppingList();
                    });
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(
                          'Added missing ingredients for ${recipe.title} to shopping list.',
                        ),
                      ),
                    );
                  }
                } on Object catch (error) {
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Could not plan recipe: $error')),
                    );
                  }
                }
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => _AsyncList<PantryItem>(
    title: 'Smart pantry',
    future: _items,
    emptyMessage: 'Your pantry is empty.',
    onAdd: _add,
    footer: [
      const SizedBox(height: 18),
      FilledButton.icon(
        onPressed: _compareNutrition,
        icon: const Icon(Icons.compare_arrows),
        label: const Text('Compare recipe nutrition'),
      ),
      const SizedBox(height: 18),
      Text(
        'Recipe recommendations',
        style: Theme.of(context).textTheme.titleLarge,
      ),
      const SizedBox(height: 8),
      Wrap(
        spacing: 8,
        runSpacing: 4,
        children: [
          ChoiceChip(
            label: const Text('All pantry'),
            selected: _recipeMode == 'COOK_WITH_WHAT_I_HAVE',
            onSelected: (selected) {
              if (selected) {
                setState(() {
                  _recipeMode = 'COOK_WITH_WHAT_I_HAVE';
                  _recipes = widget.products.recipes(mode: _recipeMode);
                });
              }
            },
          ),
          ChoiceChip(
            label: const Text('Selected ingredients'),
            selected: _recipeMode == 'USE_SELECTED_INGREDIENTS',
            onSelected: (selected) {
              if (selected) {
                setState(() {
                  _recipeMode = 'USE_SELECTED_INGREDIENTS';
                  _recipes = widget.products.recipes(
                    mode: _recipeMode,
                    selectedIngredients: _selectedIngredients.toList(growable: false),
                  );
                });
              }
            },
          ),
          ChoiceChip(
            label: const Text('Expiring soon'),
            selected: _recipeMode == 'USE_EXPIRING_SOON',
            onSelected: (selected) {
              if (selected) {
                setState(() {
                  _recipeMode = 'USE_EXPIRING_SOON';
                  _recipes = widget.products.recipes(mode: _recipeMode);
                });
              }
            },
          ),
          ChoiceChip(
            label: const Text('Leftovers'),
            selected: _recipeMode == 'USE_LEFTOVERS',
            onSelected: (selected) {
              if (selected) {
                setState(() {
                  _recipeMode = 'USE_LEFTOVERS';
                  _recipes = widget.products.recipes(mode: _recipeMode);
                });
              }
            },
          ),
          ChoiceChip(
            label: const Text('Meal plan'),
            selected: _recipeMode == 'PLAN_A_RECIPE',
            onSelected: (selected) {
              if (selected) {
                setState(() {
                  _recipeMode = 'PLAN_A_RECIPE';
                  _recipes = widget.products.recipes(mode: _recipeMode);
                });
              }
            },
          ),
        ],
      ),
      if (_recipeMode == 'USE_SELECTED_INGREDIENTS') ...[
        const SizedBox(height: 8),
        FutureBuilder<List<PantryItem>>(
          future: _items,
          builder: (context, snapshot) {
            final items = snapshot.data ?? const [];
            if (items.isEmpty) return const SizedBox.shrink();
            return Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                for (final item in items)
                  FilterChip(
                    label: Text(item.name),
                    selected: _selectedIngredients.contains(item.name),
                    onSelected: (selected) {
                      setState(() {
                        if (selected) {
                          _selectedIngredients.add(item.name);
                        } else {
                          _selectedIngredients.remove(item.name);
                        }
                        _recipes = widget.products.recipes(
                          mode: _recipeMode,
                          selectedIngredients:
                              _selectedIngredients.toList(growable: false),
                        );
                      });
                    },
                  ),
              ],
            );
          },
        ),
      ],
      const SizedBox(height: 8),
      const Text('Tap a recipe to plan servings and add deficits to shopping list.'),
      FutureBuilder<List<RecipeRecommendation>>(
        future: _recipes,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return _ErrorCard(message: snapshot.error.toString());
          }
          if (!snapshot.hasData) return const LinearProgressIndicator();
          final recipes = snapshot.data!;
          if (recipes.isEmpty) {
            return const Card(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: Text('No recipe recommendations available for current pantry ingredients. Add items to your smart pantry to see what you can cook.'),
              ),
            );
          }
          return Column(
            children: [
              for (final recipe in recipes) ...[
                Card(
                  child: ListTile(
                    onTap: () => _showRecipePlanDialog(recipe),
                    title: Text(recipe.title),
                    subtitle: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'You have ${(recipe.requiredIngredients.length - recipe.missingRequired.length).clamp(0, recipe.requiredIngredients.length)}/${recipe.requiredIngredients.length} ingredients',
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          recipe.substitutions.isEmpty
                              ? recipe.missingRequired.isEmpty
                                    ? 'All required ingredients available · '
                                          '${recipe.preparationComplexity.band.toLowerCase()} structure '
                                          '(${recipe.preparationComplexity.writtenSteps} written steps)'
                                    : 'Missing: ${recipe.missingRequired.join(', ')} · '
                                          '${recipe.preparationComplexity.band.toLowerCase()} structure'
                              : recipe.substitutions
                                    .map(
                                      (item) =>
                                          '${item.availableAlternative} can fill the ${item.function} role for ${item.missingIngredient}. ${item.limitation}',
                                    )
                                    .join(' '),
                        ),
                      ],
                    ),
                    trailing: Text('${(recipe.coverage * 100).round()}%'),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  child: Text(recipe.preparationComplexity.limitation),
                ),
              ],
            ],
          );
        },
      ),
      const SizedBox(height: 18),
      Text(
        'Use-soon template matches',
        style: Theme.of(context).textTheme.titleLarge,
      ),
      FutureBuilder<UseSoonRecipeResponse>(
        future: _useSoon,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return _ErrorCard(message: snapshot.error.toString());
          }
          if (!snapshot.hasData) return const LinearProgressIndicator();
          final result = snapshot.data!;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (result.suggestions.isEmpty)
                const ListTile(
                  title: Text('No user-marked leftovers or use-soon matches.'),
                ),
              for (final suggestion in result.suggestions)
                Card(
                  child: ListTile(
                    leading: const Icon(Icons.energy_savings_leaf_outlined),
                    title: Text(suggestion.recipe.title),
                    subtitle: Text(
                      'Uses attention items: ${suggestion.attentionItems.map((item) => item.name).join(', ')}',
                    ),
                  ),
                ),
              Text(result.limitation),
            ],
          );
        },
      ),
      const SizedBox(height: 18),
      Row(
        children: [
          Expanded(
            child: Text(
              'Shopping list',
              style: Theme.of(context).textTheme.titleLarge,
            ),
          ),
          IconButton(
            tooltip: 'Add shopping item',
            onPressed: _addShoppingItem,
            icon: const Icon(Icons.add),
          ),
        ],
      ),
      const Text('Private checklist synced to your account.'),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          OutlinedButton.icon(
            onPressed: _generateShoppingList,
            icon: const Icon(Icons.low_priority),
            label: const Text('Add user-defined low-stock items'),
          ),
          OutlinedButton.icon(
            onPressed: _clearCompletedShoppingList,
            icon: const Icon(Icons.clear_all),
            label: const Text('Clear completed'),
          ),
          if (const bool.fromEnvironment('INSTAMART_INTEGRATION_ENABLED', defaultValue: false))
            OutlinedButton.icon(
              onPressed: () async {
                try {
                  final res = await widget.products.client.get('/api/v1/instamart/status');
                  if (!context.mounted) return;
                  final statusMap = res as Map<String, dynamic>;
                  final isReady = statusMap['status'] == 'READY';
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text(
                        isReady
                            ? 'Swiggy Instamart connected: ready to sync cart.'
                            : 'Swiggy Instamart: ${statusMap['message'] ?? 'Owner authorization required.'}',
                      ),
                    ),
                  );
                } catch (_) {
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text(
                        'Swiggy Instamart ordering is blocked: backend connection or owner OAuth authorization required.',
                      ),
                    ),
                  );
                }
              },
              icon: const Icon(Icons.shopping_bag_outlined),
              label: const Text('Order on Swiggy Instamart'),
            ),
        ],
      ),
      FutureBuilder<List<ShoppingListItem>>(
        future: _shopping,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return _ErrorCard(message: snapshot.error.toString());
          }
          if (!snapshot.hasData) return const LinearProgressIndicator();
          if (snapshot.data!.isEmpty) {
            return const ListTile(title: Text('No shopping items yet.'));
          }
          return Column(
            children: [
              for (final item in snapshot.data!)
                CheckboxListTile(
                  value: item.checked,
                  title: Text(item.name),
                  subtitle: item.source == 'LOW_STOCK'
                      ? const Text('From your low-stock threshold')
                      : (item.source == 'CUSTOM_RECIPE' || item.source == 'RECIPE_PLAN')
                      ? Text(
                          'From your planned recipe · ${nutrientEvidence(item.quantity)} ${item.unit ?? 'unit Unknown'}',
                        )
                      : item.source == 'USER_ADDED'
                      ? const Text('Added by you')
                      : null,
                  secondary: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      IconButton(
                        tooltip: 'Edit ${item.name}',
                        onPressed: () => _editShoppingItem(item),
                        icon: const Icon(Icons.edit_outlined),
                      ),
                      IconButton(
                        tooltip: 'Remove ${item.name}',
                        onPressed: () async {
                          await widget.products.deleteShoppingListItem(item.id);
                          if (mounted) setState(_reload);
                        },
                        icon: const Icon(Icons.delete_outline),
                      ),
                    ],
                  ),
                  onChanged: (checked) async {
                    await widget.products.updateShoppingListItem(
                      item.id,
                      checked: checked ?? false,
                    );
                    if (mounted) setState(_reload);
                  },
                ),
            ],
          );
        },
      ),
    ],
    itemBuilder: (itemContext, item) => Dismissible(
      key: ValueKey(item.id),
      direction: DismissDirection.endToStart,
      background: Container(
        color: Theme.of(itemContext).colorScheme.errorContainer,
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 16),
        child: Icon(Icons.delete, color: Theme.of(itemContext).colorScheme.onErrorContainer),
      ),
      confirmDismiss: (direction) async {
        return await showDialog<bool>(
          context: context,
          builder: (dialogCtx) => AlertDialog(
            title: Text('Delete ${item.name}?'),
            content: Text('Are you sure you want to remove ${item.name} from your pantry?'),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogCtx, false),
                child: const Text('Cancel'),
              ),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: Theme.of(context).colorScheme.error,
                  foregroundColor: Theme.of(context).colorScheme.onError,
                ),
                onPressed: () => Navigator.pop(dialogCtx, true),
                child: const Text('Delete'),
              ),
            ],
          ),
        );
      },
      onDismissed: (_) => widget.products.deletePantry(item.id),
      child: ListTile(
        title: Text(item.name),
        subtitle: Text(
          '${item.quantity.toStringAsFixed(item.quantity % 1 == 0 ? 0 : 1)} ${item.unit}'
          '${item.expiresOn == null ? '' : ' · expires ${item.expiresOn}'}'
          '${item.lowStockThreshold == null ? '' : ' · alert at ≤ ${item.lowStockThreshold} ${item.unit}'}'
          '${item.itemRole == 'LEFTOVER' ? ' · user-marked leftover' : ''}',
        ),
        trailing: IconButton(
          icon: const Icon(Icons.delete_outline),
          tooltip: 'Delete ${item.name}',
          onPressed: () => _deletePantryWithConfirmation(item),
        ),
        onTap: () => _editPantry(item),
      ),
    ),
  );
}

class AccountHub extends StatelessWidget {
  const AccountHub({
    required this.session,
    required this.products,
    required this.onWater,
    required this.onRecipes,
    this.localReminders,
    this.healthConnect,
    super.key,
  });
  final SessionController session;
  final ProductGateway products;
  final VoidCallback onWater;
  final VoidCallback onRecipes;
  final LocalReminderCoordinator? localReminders;
  final HealthConnectCoordinator? healthConnect;

  @override
  Widget build(BuildContext context) {
    final user = session.user;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('Settings', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 12),
        const _SettingsSectionLabel('Profile'),
        Card(
          child: ListTile(
            leading: const Icon(Icons.person_outline),
            title: Text(user?.name ?? 'Signed out'),
            subtitle: Text(user?.email ?? ''),
          ),
        ),
      ListTile(
        key: const Key('account-profile-link'),
        leading: const Icon(Icons.badge_outlined),
        title: const Text('Profile'),
        subtitle: const Text('Name, DOB, optional phone, region, and units'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => AccountProfileSettingsScreen(
              email: session.user?.email ?? '',
              products: products,
              onNameChanged: session.refreshUser,
            ),
          ),
        ),
      ),
      ListTile(
        leading: const Icon(Icons.groups_outlined),
        title: const Text('Household profiles'),
        subtitle: const Text('Separate, consented wellness contexts'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => HouseholdProfilesScreen(products: products),
          ),
        ),
      ),
      const _SettingsSectionLabel('Goals & personalization'),
      ListTile(
        leading: const Icon(Icons.tune),
        title: const Text('Health profile'),
        subtitle: const Text('Goals, dietary preferences, and consent'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => ProfileScreen(products: products)),
        ),
      ),
      ListTile(
        leading: const Icon(Icons.insights_outlined),
        title: const Text('Analytics'),
        subtitle: const Text('Logged nutrition totals and averages'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => AnalyticsScreen(products: products),
          ),
        ),
      ),
      const _SettingsSectionLabel('Your nutrition'),
      ListTile(
        leading: const Icon(Icons.water_drop_outlined),
        title: const Text('Water'),
        subtitle: const Text(
          'Log water, choose a target, and view daily history',
        ),
        onTap: onWater,
      ),
      ListTile(
        leading: const Icon(Icons.restaurant_menu),
        title: const Text('My recipes'),
        subtitle: const Text(
          'Save ingredients, servings and optional nutrition evidence',
        ),
        onTap: onRecipes,
      ),
      ListTile(
        leading: const Icon(Icons.chat_bubble_outline),
        title: const Text('Ask Nutri'),
        subtitle: const Text('Ask about a label, ingredient, or nutrient'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => AssistantScreen(products: products),
          ),
        ),
      ),
      ListTile(
        leading: const Icon(Icons.favorite_outline),
        title: const Text('Saved foods'),
        subtitle: const Text('Owner-scoped scans saved to your account'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => FavoritesScreen(products: products),
          ),
        ),
      ),
      ListTile(
        leading: const Icon(Icons.history),
        title: const Text('Scan history'),
        subtitle: const Text('Private summaries from your account'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => ScanHistoryScreen(products: products),
          ),
        ),
      ),
      ListTile(
        leading: const Icon(Icons.search),
        title: const Text('Search'),
        subtitle: const Text('Your scans and governed food knowledge'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => SearchScreen(products: products)),
        ),
      ),
      const _SettingsSectionLabel('Account & security'),
      ListTile(
        key: const Key('account-security-link'),
        leading: const Icon(Icons.security_outlined),
        title: const Text('Sign-in & security'),
        subtitle: const Text(
          'Google, email/password, phone state, and active sessions',
        ),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) =>
                AccountSecurityScreen(session: session, products: products),
          ),
        ),
      ),
      const _SettingsSectionLabel('Connected apps & health'),
      if (healthConnect != null)
        ListTile(
          key: const Key('health-connect-link'),
          leading: const Icon(Icons.health_and_safety_outlined),
          title: const Text('Health Connect'),
          subtitle: const Text(
            'Optional local hydration and weight preview on Android',
          ),
          onTap: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => HealthConnectScreen(
                ownerId: session.user!.id,
                healthConnect: healthConnect!,
              ),
            ),
          ),
        )
      else
        const ListTile(
          leading: Icon(Icons.health_and_safety_outlined),
          title: Text('Health Connect'),
          subtitle: Text('Not available on this platform'),
        ),
      const _SettingsSectionLabel('Reminders & notifications'),
      ListTile(
        leading: const Icon(Icons.notifications_outlined),
        title: const Text('Notifications'),
        subtitle: const Text('Pantry expiry and account updates'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => NotificationScreen(products: products),
          ),
        ),
      ),
      if (localReminders != null)
        ListTile(
          key: const Key('local-reminders-link'),
          leading: const Icon(Icons.schedule_outlined),
          title: const Text('Local reminders'),
          subtitle: const Text(
            'Hydration, meals, summaries, weight, scans, and low stock',
          ),
          onTap: () => Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => ReminderSettingsScreen(
                ownerId: session.user!.id,
                reminders: localReminders!,
              ),
            ),
          ),
        ),
      const _SettingsSectionLabel('Units & app preferences'),
      ListTile(
        leading: const Icon(Icons.straighten_outlined),
        title: const Text('Units'),
        subtitle: const Text('Metric or imperial in your private profile'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => AccountProfileSettingsScreen(
              email: session.user!.email,
              products: products,
              onNameChanged: session.refreshUser,
            ),
          ),
        ),
      ),
      const _SettingsSectionLabel('Subscription & usage'),
      ListTile(
        leading: const Icon(Icons.credit_card_outlined),
        title: const Text('Plan & billing'),
        subtitle: const Text('Razorpay Test Mode subscription state'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => BillingScreen(products: products)),
        ),
      ),
      const _SettingsSectionLabel('Privacy & data'),
      ListTile(
        key: const Key('account-data-link'),
        leading: const Icon(Icons.manage_accounts_outlined),
        title: const Text('Your data'),
        subtitle: const Text('Export data or permanently delete your account'),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => AccountDataScreen(
              accountData: AccountDataCoordinator(gateway: products),
              afterAccountDeleted: () async {
                try {
                  await healthConnect?.disconnect(session.user!.id);
                } on Object {
                  // System permission cleanup must not strand a deleted account.
                }
                await session.signOut();
              },
            ),
          ),
        ),
      ),
      const _SettingsSectionLabel('About'),
      ListTile(
        leading: const Icon(Icons.info_outline),
        title: const Text('NutriLens X'),
        subtitle: const Text('NutriLens X · general wellness'),
        onTap: () => showAboutDialog(
          context: context,
          applicationName: 'NutriLens X',
          applicationVersion: '1.0',
          applicationLegalese: '© 2026 NutriLens X',
          children: const [
            SizedBox(height: 12),
            SelectableText('Support: https://nutrilensx.tech/contact'),
            SelectableText('Terms: https://nutrilensx.tech/terms'),
            SelectableText('Privacy: https://nutrilensx.tech/privacy'),
          ],
        ),
      ),
      ListTile(
        leading: const Icon(Icons.description_outlined),
        title: const Text('Open-source licenses'),
        onTap: () => showLicensePage(
          context: context,
          applicationName: 'NutriLens X',
          applicationVersion: '1.0',
          applicationLegalese: '© 2026 NutriLens X',
        ),
      ),
      const SizedBox(height: 16),
      OutlinedButton.icon(
        onPressed: session.signOut,
        icon: const Icon(Icons.logout),
        label: const Text('Sign out'),
      ),
    ],
  );
}
}

class _SettingsSectionLabel extends StatelessWidget {
  const _SettingsSectionLabel(this.label);

  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 22, 16, 6),
    child: Text(
      label.toUpperCase(),
      style: Theme.of(context).textTheme.labelLarge?.copyWith(
        color: Theme.of(context).colorScheme.primary,
      ),
    ),
  );
}

class NotificationScreen extends StatefulWidget {
  const NotificationScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  State<NotificationScreen> createState() => _NotificationScreenState();
}

class FavoritesScreen extends StatefulWidget {
  const FavoritesScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  State<FavoritesScreen> createState() => _FavoritesScreenState();
}

class ScanHistoryScreen extends StatelessWidget {
  const ScanHistoryScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Scan history')),
    body: FutureBuilder<List<ScanHistoryItem>>(
      future: products.scanHistory(),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return _ErrorCard(message: snapshot.error.toString());
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.data!.isEmpty) {
          return const Center(child: Text('No saved scans yet.'));
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text(
              'Compact owner-scoped summaries. Original image bytes are not retained.',
            ),
            const SizedBox(height: 12),
            for (final item in snapshot.data!)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.document_scanner_outlined),
                  title: Text(item.productName ?? 'Unidentified food scan'),
                  subtitle: Text(
                    '${item.brand ?? 'Brand not resolved'} · '
                    '${item.inputKind.replaceAll('_', ' ').toLowerCase()}\n'
                    '${MaterialLocalizations.of(context).formatCompactDate(item.createdAt)} · '
                    '${item.confidence == null ? 'unknown confidence' : '${(item.confidence! * 100).round()}% confidence'}',
                  ),
                  trailing: Text(item.status.toLowerCase()),
                ),
              ),
          ],
        );
      },
    ),
  );
}

class _FavoritesScreenState extends State<FavoritesScreen> {
  late Future<List<FavoriteFood>> _favorites = widget.products.favorites();
  final _selected = <String>{};
  var _comparing = false;

  Future<void> _remove(FavoriteFood item) async {
    await widget.products.removeFavorite(item.scanId);
    if (mounted) {
      setState(() {
        _selected.remove(item.scanId);
        _favorites = widget.products.favorites();
      });
    }
  }

  void _toggleSelect(String scanId) {
    setState(() {
      if (_selected.contains(scanId)) {
        _selected.remove(scanId);
      } else if (_selected.length < 2) {
        _selected.add(scanId);
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Select up to 2 foods to compare.')),
        );
      }
    });
  }

  Future<void> _compareSelected() async {
    if (_selected.length != 2) return;
    setState(() => _comparing = true);
    try {
      final comparison = await widget.products.compareScans(_selected.toList());
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        useSafeArea: true,
        builder: (ctx) => _FoodComparisonModal(comparison: comparison),
      );
    } on Object catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not compare foods: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _comparing = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Saved foods'),
      actions: [
        if (_selected.length == 2)
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: FilledButton.tonalIcon(
              key: const Key('compare-saved-foods'),
              onPressed: _comparing ? null : _compareSelected,
              icon: const Icon(Icons.compare_arrows),
              label: Text(_comparing ? 'Comparing…' : 'Compare 2 foods'),
            ),
          ),
      ],
    ),
    body: FutureBuilder<List<FavoriteFood>>(
      future: _favorites,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return _ErrorCard(message: snapshot.error.toString());
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.data!.isEmpty) {
          return const Center(child: Text('No saved foods yet.'));
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final item in snapshot.data!)
              Card(
                color: _selected.contains(item.scanId)
                    ? Theme.of(context).colorScheme.primaryContainer.withValues(alpha: 0.4)
                    : null,
                child: ListTile(
                  leading: Checkbox(
                    value: _selected.contains(item.scanId),
                    onChanged: (_) => _toggleSelect(item.scanId),
                  ),
                  onTap: () => _toggleSelect(item.scanId),
                  title: Text(item.productName ?? 'Unidentified food scan'),
                  subtitle: Text(
                    '${item.brand ?? 'Brand not resolved'} · saved ${MaterialLocalizations.of(context).formatCompactDate(item.savedAt)}',
                  ),
                  trailing: IconButton(
                    tooltip: 'Remove saved food',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () => _remove(item),
                  ),
                ),
              ),
          ],
        );
      },
    ),
  );
}

class _FoodComparisonModal extends StatefulWidget {
  const _FoodComparisonModal({required this.comparison});
  final ScanComparisonResponse comparison;

  @override
  State<_FoodComparisonModal> createState() => _FoodComparisonModalState();
}

class _FoodComparisonModalState extends State<_FoodComparisonModal> {
  var _perServing = false;

  String _format(double? val, String unit) => val != null ? '$val $unit' : '—';

  @override
  Widget build(BuildContext context) {
    final c1 = widget.comparison.candidates[0];
    final c2 = widget.comparison.candidates.length > 1
        ? widget.comparison.candidates[1]
        : null;

    final n1 = _perServing ? c1.nutrientsPerServing : c1.nutrientsPer100;
    final n2 = c2 == null
        ? null
        : (_perServing ? c2.nutrientsPerServing : c2.nutrientsPer100);

    return DraggableScrollableSheet(
      initialChildSize: 0.85,
      maxChildSize: 0.95,
      minChildSize: 0.5,
      expand: false,
      builder: (context, scrollController) => ListView(
        controller: scrollController,
        padding: const EdgeInsets.all(20),
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Compare foods', style: Theme.of(context).textTheme.titleLarge),
              IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('Per 100g / 100ml')),
              ButtonSegment(value: true, label: Text('Per serving')),
            ],
            selected: {_perServing},
            onSelectionChanged: (set) => setState(() => _perServing = set.first),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              const Expanded(flex: 3, child: Text('Nutrient', style: TextStyle(fontWeight: FontWeight.bold))),
              Expanded(
                flex: 4,
                child: Text(
                  c1.productName,
                  style: const TextStyle(fontWeight: FontWeight.bold),
                  textAlign: TextAlign.center,
                ),
              ),
              if (c2 != null)
                Expanded(
                  flex: 4,
                  child: Text(
                    c2.productName,
                    style: const TextStyle(fontWeight: FontWeight.bold),
                    textAlign: TextAlign.center,
                  ),
                ),
            ],
          ),
          const Divider(),
          _row('Energy', _format(n1.energyKcal, 'kcal'), _format(n2?.energyKcal, 'kcal')),
          _row('Protein', _format(n1.proteinG, 'g'), _format(n2?.proteinG, 'g')),
          _row('Carbohydrate', _format(n1.carbohydrateG, 'g'), _format(n2?.carbohydrateG, 'g')),
          _row('Total Sugars', _format(n1.sugarG, 'g'), _format(n2?.sugarG, 'g')),
          _row('Added Sugars', _format(n1.addedSugarG, 'g'), _format(n2?.addedSugarG, 'g')),
          _row('Total Fat', _format(n1.fatG, 'g'), _format(n2?.fatG, 'g')),
          _row('Dietary Fiber', _format(n1.fiberG, 'g'), _format(n2?.fiberG, 'g')),
          _row('Sodium', _format(n1.sodiumMg, 'mg'), _format(n2?.sodiumMg, 'mg')),
          const Divider(),
          _row('Serving size', c1.servingSize ?? 'Not reported', c2?.servingSize ?? 'Not reported'),
          _row(
            'Allergens',
            c1.allergens.isEmpty ? 'None declared' : c1.allergens.join(', '),
            c2 == null || c2.allergens.isEmpty ? 'None declared' : c2.allergens.join(', '),
          ),
          const SizedBox(height: 16),
          Card(
            color: Theme.of(context).colorScheme.surfaceContainerHighest,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                widget.comparison.disclaimer,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _row(String label, String v1, String v2) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 6),
    child: Row(
      children: [
        Expanded(flex: 3, child: Text(label, style: const TextStyle(fontSize: 13))),
        Expanded(flex: 4, child: Text(v1, textAlign: TextAlign.center, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500))),
        Expanded(flex: 4, child: Text(v2, textAlign: TextAlign.center, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500))),
      ],
    ),
  );
}

class SearchScreen extends StatefulWidget {
  const SearchScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _query = TextEditingController();
  SearchResults? _results;
  String? _error;
  var _loading = false;

  Future<void> _search() async {
    if (_query.text.trim().length < 2) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await widget.products.search(_query.text.trim());
      if (mounted) setState(() => _results = results);
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Search')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        TextField(
          controller: _query,
          decoration: const InputDecoration(
            labelText: 'Product, brand, ingredient, or additive',
            border: OutlineInputBorder(),
          ),
          textInputAction: TextInputAction.search,
          onSubmitted: (_) => _search(),
        ),
        const SizedBox(height: 10),
        FilledButton.icon(
          onPressed: _loading ? null : _search,
          icon: const Icon(Icons.search),
          label: const Text('Search'),
        ),
        if (_loading) const LinearProgressIndicator(),
        if (_error != null) _ErrorCard(message: _error!),
        if (_results != null) ...[
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(_results!.limitation),
          ),
          if (_results!.items.isEmpty) const Text('No matching records found.'),
          for (final item in _results!.items)
            Card(
              child: ListTile(
                leading: Icon(
                  item.kind == 'SCAN'
                      ? Icons.document_scanner_outlined
                      : Icons.menu_book_outlined,
                ),
                title: Text(item.title),
                subtitle: Text(
                  '${item.subtitle} · ${(item.score * 100).round()}% lexical match',
                ),
              ),
            ),
        ],
      ],
    ),
  );
}

class _NotificationScreenState extends State<NotificationScreen> {
  late Future<List<AccountNotification>> _notifications = widget.products
      .notifications();

  Future<void> _markAll() async {
    await widget.products.markAllNotificationsRead();
    if (mounted) {
      setState(() => _notifications = widget.products.notifications());
    }
  }

  Future<void> _markOne(AccountNotification notification) async {
    if (notification.readAt != null) return;
    await widget.products.markNotificationRead(notification.id);
    if (mounted) {
      setState(() => _notifications = widget.products.notifications());
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Notifications'),
      actions: [
        TextButton(onPressed: _markAll, child: const Text('Mark all read')),
      ],
    ),
    body: FutureBuilder<List<AccountNotification>>(
      future: _notifications,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return _ErrorCard(message: snapshot.error.toString());
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.data!.isEmpty) {
          return const Center(child: Text('No active notifications.'));
        }
        return ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final notification in snapshot.data!)
              Card(
                child: ListTile(
                  leading: Icon(
                    notification.readAt == null
                        ? Icons.notifications_active_outlined
                        : Icons.notifications_none,
                  ),
                  title: Text(notification.title),
                  subtitle: Text(notification.body),
                  trailing: notification.readAt == null
                      ? const Icon(Icons.circle, size: 10)
                      : null,
                  onTap: () => _markOne(notification),
                ),
              ),
          ],
        );
      },
    ),
  );
}

class HouseholdProfilesScreen extends StatefulWidget {
  const HouseholdProfilesScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  State<HouseholdProfilesScreen> createState() =>
      _HouseholdProfilesScreenState();
}

class _HouseholdProfilesScreenState extends State<HouseholdProfilesScreen> {
  late Future<List<HouseholdProfile>> _profiles = widget.products
      .householdProfiles();

  void _refresh() {
    setState(() => _profiles = widget.products.householdProfiles());
  }

  Future<void> _edit([HouseholdProfile? existing]) async {
    final name = TextEditingController(text: existing?.displayName ?? '');
    final relationship = TextEditingController(
      text: existing?.relationship ?? '',
    );
    final allergens = TextEditingController(
      text: existing?.profile.allergens.join(', ') ?? '',
    );
    var goal = existing?.profile.goal ?? 'balanced';
    final customGoal = TextEditingController(
      text: existing?.profile.customGoal ?? '',
    );
    var consent = existing?.profile.consentPersonalization ?? false;
    final shouldSave = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: Text(
            existing == null ? 'Add household profile' : 'Edit profile',
          ),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  maxLength: 100,
                  decoration: const InputDecoration(labelText: 'Display name'),
                ),
                TextField(
                  controller: relationship,
                  maxLength: 50,
                  decoration: const InputDecoration(
                    labelText: 'Relationship (optional)',
                  ),
                ),
                DropdownButtonFormField<String>(
                  initialValue: goal,
                  decoration: const InputDecoration(labelText: 'Wellness goal'),
                  items: wellnessGoalLabels.entries
                      .map(
                        (entry) => DropdownMenuItem(
                          value: entry.key,
                          child: Text(entry.value),
                        ),
                      )
                      .toList(),
                  onChanged: (value) {
                    if (value != null) setDialogState(() => goal = value);
                  },
                ),
                if (goal == 'custom')
                  TextField(
                    controller: customGoal,
                    maxLength: 120,
                    decoration: const InputDecoration(
                      labelText: 'Describe the custom goal',
                      helperText:
                          'Personal intention only; not medical advice.',
                    ),
                    onChanged: (_) => setDialogState(() {}),
                  ),
                TextField(
                  controller: allergens,
                  decoration: const InputDecoration(
                    labelText: 'Allergens (comma separated)',
                  ),
                ),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Personalization consent'),
                  subtitle: const Text(
                    'Stored for this member; never applied automatically.',
                  ),
                  value: consent,
                  onChanged: (value) => setDialogState(() => consent = value),
                ),
                const Text(
                  'General wellness only. NutriLens does not infer age, life stage, diagnosis, or clinical suitability.',
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () {
                final customGoalValid =
                    goal != 'custom' || customGoal.text.trim().isNotEmpty;
                if (name.text.trim().isNotEmpty && customGoalValid) {
                  Navigator.pop(context, true);
                }
              },
              child: Text(existing == null ? 'Add' : 'Update'),
            ),
          ],
        ),
      ),
    );
    if (shouldSave == true) {
      try {
        await widget.products.saveHouseholdProfile(
          id: existing?.id,
          displayName: name.text.trim(),
          relationship: relationship.text.trim().isEmpty
              ? null
              : relationship.text.trim(),
          profile: ProfileSnapshot(
            goal: goal,
            customGoal: goal == 'custom' ? customGoal.text.trim() : null,
            allergens: allergens.text
                .split(',')
                .map((value) => value.trim())
                .where((value) => value.isNotEmpty)
                .toList(growable: false),
            dietaryPreferences:
                existing?.profile.dietaryPreferences ?? const [],
            consentPersonalization: consent,
            dailyTargets: existing?.profile.dailyTargets ?? const {},
          ),
        );
        _refresh();
      } on Object catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not save profile: $error')),
          );
        }
      }
    }
    name.dispose();
    relationship.dispose();
    allergens.dispose();
  }

  Future<void> _delete(HouseholdProfile profile) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete ${profile.displayName}?'),
        content: const Text(
          'This removes the household profile from your account.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await widget.products.deleteHouseholdProfile(profile.id);
      _refresh();
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Household profiles')),
    floatingActionButton: FloatingActionButton.extended(
      onPressed: _edit,
      icon: const Icon(Icons.person_add_alt_1),
      label: const Text('Add profile'),
    ),
    body: FutureBuilder<List<HouseholdProfile>>(
      future: _profiles,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(
            child: Text('Could not load profiles: ${snapshot.error}'),
          );
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final profiles = snapshot.data!;
        if (profiles.isEmpty) {
          return const Center(
            child: Padding(
              padding: EdgeInsets.all(28),
              child: Text(
                'No household profiles yet. Add a separate, consented wellness context for a household member.',
                textAlign: TextAlign.center,
              ),
            ),
          );
        }
        return ListView.builder(
          padding: const EdgeInsets.all(16),
          itemCount: profiles.length,
          itemBuilder: (context, index) {
            final profile = profiles[index];
            return Card(
              child: ListTile(
                leading: const Icon(Icons.person_outline),
                title: Text(profile.displayName),
                subtitle: Text(
                  [
                    if (profile.relationship?.isNotEmpty == true)
                      profile.relationship!,
                    wellnessGoalLabel(profile.profile.goal),
                    if (profile.profile.customGoal?.isNotEmpty == true)
                      profile.profile.customGoal!,
                    profile.profile.consentPersonalization
                        ? 'consented'
                        : 'personalization off',
                  ].join(' · '),
                ),
                onTap: () => _edit(profile),
                trailing: IconButton(
                  tooltip: 'Delete ${profile.displayName}',
                  icon: const Icon(Icons.delete_outline),
                  onPressed: () => _delete(profile),
                ),
              ),
            );
          },
        );
      },
    ),
  );
}

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  late Future<ProfileSnapshot> _profile = widget.products.profile();
  late Future<BmiContext> _bmi = widget.products.bmiContext();

  Future<void> _editGoal(ProfileSnapshot profile) async {
    var selectedGoal = profile.goal;
    final customGoal = TextEditingController(text: profile.customGoal ?? '');
    final selection = await showDialog<(String, String?)>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Wellness goal'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: selectedGoal,
                  decoration: const InputDecoration(labelText: 'Your intent'),
                  items: wellnessGoalLabels.entries
                      .map(
                        (entry) => DropdownMenuItem(
                          value: entry.key,
                          child: Text(entry.value),
                        ),
                      )
                      .toList(),
                  onChanged: (value) {
                    if (value != null) {
                      setDialogState(() => selectedGoal = value);
                    }
                  },
                ),
                if (selectedGoal == 'custom') ...[
                  const SizedBox(height: 12),
                  TextField(
                    key: const Key('health-profile-custom-goal'),
                    controller: customGoal,
                    maxLength: 120,
                    decoration: const InputDecoration(
                      labelText: 'Describe your goal',
                    ),
                    onChanged: (_) => setDialogState(() {}),
                  ),
                ],
                const SizedBox(height: 12),
                const Text(
                  'This records your intent. NutriLens does not prescribe a weight-change pace, calorie deficit or medical treatment.',
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            FilledButton(
              key: const Key('save-wellness-goal'),
              onPressed:
                  selectedGoal == 'custom' && customGoal.text.trim().isEmpty
                  ? null
                  : () => Navigator.pop(context, (
                      selectedGoal,
                      selectedGoal == 'custom' ? customGoal.text.trim() : null,
                    )),
              child: const Text('Save goal'),
            ),
          ],
        ),
      ),
    );
    customGoal.dispose();
    if (selection == null) return;
    final saved = await widget.products.saveProfile(
      ProfileSnapshot(
        goal: selection.$1,
        customGoal: selection.$2,
        allergens: profile.allergens,
        dietaryPreferences: profile.dietaryPreferences,
        dietaryStyle: profile.dietaryStyle,
        customDietaryStyle: profile.customDietaryStyle,
        healthConditions: profile.healthConditions,
        intolerances: profile.intolerances,
        foodExclusions: profile.foodExclusions,
        consentPersonalization: profile.consentPersonalization,
        dailyTargets: profile.dailyTargets,
        bodyContext: profile.bodyContext,
      ),
    );
    if (mounted) setState(() => _profile = Future.value(saved));
  }

  Future<void> _editTargets(ProfileSnapshot profile) async {
    const fields = {
      'calories': 'Energy (kcal)',
      'protein_g': 'Protein (g)',
      'fiber_g': 'Fiber (g)',
      'sodium_mg': 'Sodium (mg)',
      'calcium_mg': 'Calcium (mg)',
      'iron_mg': 'Iron (mg)',
    };
    final controllers = {
      for (final field in fields.keys)
        field: TextEditingController(
          text: profile.dailyTargets[field]?.toString() ?? '',
        ),
    };
    final targets = await showDialog<Map<String, double>>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Your daily references'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final entry in fields.entries)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: TextField(
                    controller: controllers[entry.key],
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: InputDecoration(labelText: entry.value),
                  ),
                ),
              const Text(
                'These are references you enter, not clinical targets selected by NutriLens.',
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final parsed = <String, double>{};
              for (final entry in controllers.entries) {
                final value = double.tryParse(entry.value.text.trim());
                if (value != null && value > 0) parsed[entry.key] = value;
              }
              Navigator.pop(context, parsed);
            },
            child: const Text('Save references'),
          ),
        ],
      ),
    );
    for (final controller in controllers.values) {
      controller.dispose();
    }
    if (targets == null) return;
    final saved = await widget.products.saveProfile(
      ProfileSnapshot(
        goal: profile.goal,
        customGoal: profile.customGoal,
        allergens: profile.allergens,
        dietaryPreferences: profile.dietaryPreferences,
        dietaryStyle: profile.dietaryStyle,
        customDietaryStyle: profile.customDietaryStyle,
        healthConditions: profile.healthConditions,
        intolerances: profile.intolerances,
        foodExclusions: profile.foodExclusions,
        consentPersonalization: profile.consentPersonalization,
        dailyTargets: targets,
        bodyContext: profile.bodyContext,
      ),
    );
    if (mounted) setState(() => _profile = Future.value(saved));
  }

  Future<void> _editBodyContext(ProfileSnapshot profile) async {
    final height = TextEditingController(
      text: profile.bodyContext.heightCm?.toString() ?? '',
    );
    final weight = TextEditingController(
      text: profile.bodyContext.weightKg?.toString() ?? '',
    );
    var consent =
        profile.bodyContext.adultAttestation &&
        profile.bodyContext.consentBmiContext;
    final bodyContext = await showDialog<SelfReportedBodyContext>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) {
          final parsedHeight = double.tryParse(height.text.trim());
          final parsedWeight = double.tryParse(weight.text.trim());
          final valid =
              !consent ||
              (parsedHeight != null &&
                  parsedHeight >= 100 &&
                  parsedHeight <= 250 &&
                  parsedWeight != null &&
                  parsedWeight >= 20 &&
                  parsedWeight <= 500);
          return AlertDialog(
            title: const Text('Optional adult BMI context'),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: consent,
                    title: const Text('Adult attestation and consent'),
                    subtitle: const Text(
                      'I confirm I am an adult and consent to storing these measurements for BMI context.',
                    ),
                    onChanged: (value) =>
                        setDialogState(() => consent = value ?? false),
                  ),
                  TextField(
                    controller: height,
                    enabled: consent,
                    onChanged: (_) => setDialogState(() {}),
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(labelText: 'Height (cm)'),
                  ),
                  TextField(
                    controller: weight,
                    enabled: consent,
                    onChanged: (_) => setDialogState(() {}),
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    decoration: const InputDecoration(labelText: 'Weight (kg)'),
                  ),
                  const SizedBox(height: 12),
                  const Text(
                    'NutriLens calculates weight ÷ height² only. It does not assign a category, ideal weight, diagnosis or target.',
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('Cancel'),
              ),
              FilledButton(
                onPressed: valid
                    ? () => Navigator.pop(
                        context,
                        consent
                            ? SelfReportedBodyContext(
                                adultAttestation: true,
                                consentBmiContext: true,
                                heightCm: parsedHeight,
                                weightKg: parsedWeight,
                              )
                            : const SelfReportedBodyContext(),
                      )
                    : null,
                child: Text(consent ? 'Save and calculate' : 'Disable context'),
              ),
            ],
          );
        },
      ),
    );
    height.dispose();
    weight.dispose();
    if (bodyContext == null) return;
    final saved = await widget.products.saveProfile(
      ProfileSnapshot(
        goal: profile.goal,
        customGoal: profile.customGoal,
        allergens: profile.allergens,
        dietaryPreferences: profile.dietaryPreferences,
        dietaryStyle: profile.dietaryStyle,
        customDietaryStyle: profile.customDietaryStyle,
        healthConditions: profile.healthConditions,
        intolerances: profile.intolerances,
        foodExclusions: profile.foodExclusions,
        consentPersonalization: profile.consentPersonalization,
        dailyTargets: profile.dailyTargets,
        bodyContext: bodyContext,
      ),
    );
    if (mounted) {
      setState(() {
        _profile = Future.value(saved);
        _bmi = widget.products.bmiContext();
      });
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Health profile')),
    body: FutureBuilder<ProfileSnapshot>(
      future: _profile,
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final profile = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.flag_outlined),
              title: const Text('Wellness goal'),
              subtitle: Text(
                profile.customGoal?.isNotEmpty == true
                    ? '${wellnessGoalLabel(profile.goal)} · ${profile.customGoal}'
                    : wellnessGoalLabel(profile.goal),
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _editGoal(profile),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.restaurant),
              title: const Text('Dietary style'),
              subtitle: Text(
                profile.dietaryStyle == 'Custom' && profile.customDietaryStyle?.isNotEmpty == true
                    ? 'Custom · ${profile.customDietaryStyle}'
                    : profile.dietaryStyle,
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _editDietaryStyle(profile),
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.medical_services_outlined),
              title: const Text('Health conditions'),
              subtitle: Text(
                profile.healthConditions.isEmpty
                    ? 'None specified'
                    : profile.healthConditions.join(', '),
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _editHealthConditions(profile),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Personalized guidance'),
              subtitle: const Text(
                'Use my saved profile to contextualize observed evidence.',
              ),
              value: profile.consentPersonalization,
              onChanged: (value) async {
                final saved = await widget.products.saveProfile(
                  ProfileSnapshot(
                    goal: profile.goal,
                    customGoal: profile.customGoal,
                    allergens: profile.allergens,
                    dietaryPreferences: profile.dietaryPreferences,
                    dietaryStyle: profile.dietaryStyle,
                    customDietaryStyle: profile.customDietaryStyle,
                    healthConditions: profile.healthConditions,
                    intolerances: profile.intolerances,
                    foodExclusions: profile.foodExclusions,
                    consentPersonalization: value,
                    dailyTargets: profile.dailyTargets,
                    bodyContext: profile.bodyContext,
                  ),
                );
                if (mounted) setState(() => _profile = Future.value(saved));
              },
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.track_changes),
              title: const Text('Daily references'),
              subtitle: Text(
                profile.dailyTargets.isEmpty
                    ? 'Not configured'
                    : '${profile.dailyTargets.length} references configured',
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _editTargets(profile),
            ),
            FutureBuilder<BmiContext>(
              future: _bmi,
              builder: (context, snapshot) {
                final bmi = snapshot.data;
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.straighten),
                  title: const Text('Adult BMI context'),
                  subtitle: Text(
                    bmi?.state == 'AVAILABLE'
                        ? 'Calculated BMI: ${bmi!.bmi?.toStringAsFixed(2)}. ${bmi.limitation}'
                        : 'Not configured. Requires adult attestation and separate consent.',
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _editBodyContext(profile),
                );
              },
            ),
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.monitor_weight_outlined),
              title: const Text('Optional weight tracking'),
              subtitle: const Text(
                'Self-reported account history with explicit enablement.',
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => WeightScreen(gateway: widget.products),
                ),
              ),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                foregroundColor: Theme.of(context).colorScheme.error,
              ),
              icon: const Icon(Icons.delete_sweep_outlined),
              label: const Text('Clear health profile data'),
              onPressed: () => _clearHealthProfileData(),
            ),
            const SizedBox(height: 8),
            const Text(
              'NutriLens provides wellness decision support only, not diagnosis or treatment.',
            ),
          ],
        );
      },
    ),
  );

  Future<void> _editDietaryStyle(ProfileSnapshot profile) async {
    const styles = [
      'Vegetarian',
      'Non-vegetarian',
      'Vegan',
      'Eggetarian',
      'Pescatarian',
      'Jain',
      'Keto',
      'No specific diet',
      'Custom',
    ];
    var selected = profile.dietaryStyle;
    final customCtrl = TextEditingController(text: profile.customDietaryStyle ?? '');

    final result = await showDialog<(String, String?)>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setModalState) => AlertDialog(
          title: const Text('Dietary style'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: styles.contains(selected) ? selected : 'No specific diet',
                  decoration: const InputDecoration(labelText: 'Select style'),
                  items: styles.map((s) => DropdownMenuItem(value: s, child: Text(s))).toList(),
                  onChanged: (val) {
                    if (val != null) setModalState(() => selected = val);
                  },
                ),
                if (selected == 'Custom') ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: customCtrl,
                    decoration: const InputDecoration(labelText: 'Specify custom dietary style'),
                  ),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(
                context,
                (selected, selected == 'Custom' ? customCtrl.text.trim() : null),
              ),
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (result == null) return;
    final saved = await widget.products.saveProfile(
      ProfileSnapshot(
        goal: profile.goal,
        customGoal: profile.customGoal,
        allergens: profile.allergens,
        dietaryPreferences: profile.dietaryPreferences,
        dietaryStyle: result.$1,
        customDietaryStyle: result.$2,
        healthConditions: profile.healthConditions,
        intolerances: profile.intolerances,
        foodExclusions: profile.foodExclusions,
        consentPersonalization: profile.consentPersonalization,
        dailyTargets: profile.dailyTargets,
        bodyContext: profile.bodyContext,
      ),
    );
    if (mounted) setState(() => _profile = Future.value(saved));
  }

  Future<void> _editHealthConditions(ProfileSnapshot profile) async {
    const conditionOptions = [
      'Diabetes',
      'Hypertension',
      'High cholesterol',
      'Heart health',
      'Kidney',
      'Liver',
      'PCOS',
      'Thyroid',
      'Asthma',
      'Cancer/oncology',
      'Food allergies',
      'Lactose intolerance',
      'Gluten intolerance',
      'Other',
      'None',
      'Prefer not to say',
    ];
    final selected = Set<String>.from(profile.healthConditions);

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setModalState) => AlertDialog(
          title: const Text('Health conditions'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Select any conditions that apply. This helps provide sensitive, relevant guidance.',
                  style: TextStyle(fontSize: 13),
                ),
                const SizedBox(height: 10),
                for (final cond in conditionOptions)
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(cond),
                    value: selected.contains(cond),
                    onChanged: (val) {
                      setModalState(() {
                        if (val == true) {
                          if (cond == 'None' || cond == 'Prefer not to say') {
                            selected.clear();
                          } else {
                            selected.remove('None');
                            selected.remove('Prefer not to say');
                          }
                          selected.add(cond);
                        } else {
                          selected.remove(cond);
                        }
                      });
                    },
                  ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true) return;
    final saved = await widget.products.saveProfile(
      ProfileSnapshot(
        goal: profile.goal,
        customGoal: profile.customGoal,
        allergens: profile.allergens,
        dietaryPreferences: profile.dietaryPreferences,
        dietaryStyle: profile.dietaryStyle,
        customDietaryStyle: profile.customDietaryStyle,
        healthConditions: selected.toList(),
        intolerances: profile.intolerances,
        foodExclusions: profile.foodExclusions,
        consentPersonalization: profile.consentPersonalization,
        dailyTargets: profile.dailyTargets,
        bodyContext: profile.bodyContext,
      ),
    );
    if (mounted) setState(() => _profile = Future.value(saved));
  }

  Future<void> _clearHealthProfileData() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear health profile?'),
        content: const Text(
          'This will delete your saved health conditions, dietary style, and wellness goals. This action cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(context).colorScheme.error,
              foregroundColor: Theme.of(context).colorScheme.onError,
            ),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Clear all data'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      try {
        await widget.products.client.delete('/api/v1/profile');
        if (mounted) {
          setState(() {
            _profile = widget.products.profile();
            _bmi = widget.products.bmiContext();
          });
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Health profile data cleared.')),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Could not clear health profile: $e')),
          );
        }
      }
    }
  }
}

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  var _days = 7;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Nutrition analytics')),
    body: FutureBuilder<AnalyticsSummary>(
      future: widget.products.analytics(days: _days),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return _ErrorCard(message: snapshot.error.toString());
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final data = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            SegmentedButton<int>(
              segments: const [
                ButtonSegment(value: 7, label: Text('7 days')),
                ButtonSegment(value: 30, label: Text('30 days')),
                ButtonSegment(value: 90, label: Text('90 days')),
              ],
              selected: {_days},
              onSelectionChanged: (selected) =>
                  setState(() => _days = selected.single),
            ),
            const SizedBox(height: 12),
            _MetricCard(
              label: 'Entries (${data.periodDays} days)',
              value: '${data.diaryEntries}',
            ),
            _MetricCard(
              label: 'Total energy',
              value:
                  '${nutrientEvidence(data.totals.calories, decimals: 0)} kcal',
            ),
            _MetricCard(
              label: 'Average protein',
              value: '${nutrientEvidence(data.dailyAverages.proteinG)} g/day',
            ),
            _MetricCard(
              label: 'Average sodium',
              value:
                  '${nutrientEvidence(data.dailyAverages.sodiumMg, decimals: 0)} mg/day',
            ),
            _MetricCard(
              label: 'Average calcium',
              value:
                  '${nutrientEvidence(data.dailyAverages.calciumMg, decimals: 0)} mg/day',
            ),
            _MetricCard(
              label: 'Average iron',
              value: '${nutrientEvidence(data.dailyAverages.ironMg)} mg/day',
            ),
            const Text(
              'Unknown means one or more logged entries lack nutrient evidence. It is not zero intake. These totals and averages describe only your recorded food.',
            ),
            const SizedBox(height: 8),
            Text(
              'Your references',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (data.goalTrackingState == 'AVAILABLE')
              for (final item in data.goalProgress)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(item.progressDescription),
                        const SizedBox(height: 8),
                        if (item.percentOfTarget != null)
                          LinearProgressIndicator(
                            value: (item.percentOfTarget! / 100)
                                .clamp(0.0, 1.0)
                                .toDouble(),
                          ),
                      ],
                    ),
                  ),
                )
            else
              ListTile(
                leading: const Icon(Icons.track_changes),
                title: Text(
                  data.goalTrackingState == 'DISABLED_NO_CONSENT'
                      ? 'Enable personalization consent to track your references.'
                      : 'Add daily references in your profile to track them here.',
                ),
              ),
            Text(data.goalTrackingLimitation),
            for (final insight in data.insights)
              ListTile(
                leading: const Icon(Icons.info_outline),
                title: Text(insight),
              ),
            const Divider(height: 32),
            Text(
              'Adjacent period evidence',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            FutureBuilder<AnalyticsComparison>(
              future: widget.products.analyticsComparison(days: _days),
              builder: (context, comparisonSnapshot) {
                if (comparisonSnapshot.hasError) {
                  return _ErrorCard(
                    message: comparisonSnapshot.error.toString(),
                  );
                }
                if (!comparisonSnapshot.hasData) {
                  return const LinearProgressIndicator();
                }
                final comparison = comparisonSnapshot.data!;
                if (comparison.state != 'AVAILABLE') {
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Add diary entries in both adjacent ${comparison.periodDays}-day windows to compare them.',
                      ),
                      Text(comparison.limitation),
                    ],
                  );
                }
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (final story in comparison.stories)
                      Card(
                        child: ListTile(
                          leading: const Icon(Icons.compare_arrows),
                          title: Text(story.title),
                          subtitle: Text(
                            '${story.evidence}\n${story.supportingRecords} supporting records',
                          ),
                        ),
                      ),
                    Text(comparison.limitation),
                  ],
                );
              },
            ),
            const Divider(height: 32),
            Text(
              'Source records',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            FutureBuilder<AnalyticsDrilldown>(
              future: widget.products.analyticsDrilldown(days: _days),
              builder: (context, drilldownSnapshot) {
                if (drilldownSnapshot.hasError) {
                  return _ErrorCard(
                    message: drilldownSnapshot.error.toString(),
                  );
                }
                if (!drilldownSnapshot.hasData) {
                  return const LinearProgressIndicator();
                }
                final drilldown = drilldownSnapshot.data!;
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(drilldown.limitation),
                    if (drilldown.entries.isEmpty)
                      const ListTile(title: Text('No entries in this window.')),
                    for (final entry in drilldown.entries)
                      ExpansionTile(
                        title: Text(entry.name),
                        subtitle: Text(
                          '${entry.servingDescription} · '
                          '${nutrientEvidence(entry.nutrients.calories, decimals: 0)} kcal',
                        ),
                        childrenPadding: const EdgeInsets.fromLTRB(
                          16,
                          0,
                          16,
                          12,
                        ),
                        children: [
                          Text(
                            '${nutrientEvidence(entry.nutrients.proteinG)} g protein · '
                            '${nutrientEvidence(entry.nutrients.fiberG)} g fiber · '
                            '${nutrientEvidence(entry.nutrients.sodiumMg, decimals: 0)} mg sodium',
                          ),
                          if (entry.eatenAt.isNotEmpty) Text(entry.eatenAt),
                        ],
                      ),
                  ],
                );
              },
            ),
            const Divider(height: 32),
            Text(
              'Descriptive patterns',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            FutureBuilder<DietaryPatterns>(
              future: widget.products.dietaryPatterns(days: _days),
              builder: (context, patternSnapshot) {
                if (patternSnapshot.hasError) {
                  return _ErrorCard(message: patternSnapshot.error.toString());
                }
                if (!patternSnapshot.hasData) {
                  return const LinearProgressIndicator();
                }
                final patterns = patternSnapshot.data!;
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(patterns.limitation),
                    Text(
                      '${patterns.observedDays}/${patterns.periodDays} logged days',
                    ),
                    if (patterns.state == 'INSUFFICIENT_HISTORY')
                      ListTile(
                        leading: const Icon(Icons.hourglass_empty),
                        title: Text(
                          'Log entries on at least ${patterns.minimumObservedDays} distinct days.',
                        ),
                      ),
                    for (final observation in patterns.observations)
                      Card(
                        child: ListTile(
                          title: Text(observation.label),
                          subtitle: Text(observation.evidence),
                          trailing: Text('${observation.supportingRecords}'),
                        ),
                      ),
                  ],
                );
              },
            ),
          ],
        );
      },
    ),
  );
}

class AssistantScreen extends StatefulWidget {
  const AssistantScreen({
    required this.products,
    this.voice,
    this.scanId,
    this.initialQuestion,
    super.key,
  });
  final ProductGateway products;
  final AssistantVoiceGateway? voice;
  final String? scanId;
  final String? initialQuestion;

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  final _message = TextEditingController();
  late final AssistantVoiceGateway _voice =
      widget.voice ?? PlatformAssistantVoice();
  final List<_AssistantTurn> _turns = [];
  bool _loading = false;
  bool _voiceInitialized = false;
  bool _voiceAvailable = false;
  bool _listening = false;
  bool _readAloud = false;
  String? _error;
  String? _lastQuestion;
  String _voiceStatus =
      'Voice input is optional. Tap the microphone to enable it.';

  @override
  void initState() {
    super.initState();
    _message.text = widget.initialQuestion ?? '';
  }

  Future<void> _initializeVoice() async {
    if (_voiceInitialized) return;
    final available = await _voice.initialize(
      onStatus: (status) {
        if (!mounted) return;
        setState(() {
          _listening = status == 'listening';
          if (status == 'done' || status == 'notListening') {
            _voiceStatus = 'Voice transcript ready. Review it before sending.';
          }
        });
      },
      onError: (error) {
        if (!mounted) return;
        setState(() {
          _listening = false;
          _voiceStatus = error.contains('permission')
              ? 'Microphone permission was not granted. You can keep typing.'
              : 'Voice input stopped before a question was captured.';
        });
      },
    );
    if (mounted) {
      setState(() {
        _voiceInitialized = true;
        _voiceAvailable = available;
        _voiceStatus = available
            ? 'Voice is ready. Audio stays with the device speech service.'
            : 'Voice input is unavailable on this device. You can keep typing.';
      });
    }
  }

  Future<void> _toggleListening() async {
    if (_listening) {
      await _voice.stopListening();
      if (mounted) setState(() => _listening = false);
      return;
    }
    if (!_voiceInitialized) {
      await _initializeVoice();
      if (!_voiceAvailable) return;
    }
    await _voice.stopSpeaking();
    setState(() {
      _listening = true;
      _voiceStatus =
          'Listening. Only the transcript is sent after you tap Ask assistant.';
    });
    await _voice.startListening((transcript) {
      if (mounted) setState(() => _message.text = transcript);
    });
  }

  Future<void> _send([String? suggestedQuestion]) async {
    final question = (suggestedQuestion ?? _message.text).trim();
    if (question.isEmpty || _loading) return;
    setState(() {
      _loading = true;
      _error = null;
      _lastQuestion = question;
      _message.clear();
    });
    try {
      final reply = await widget.products.askAssistant(
        question,
        scanId: widget.scanId,
      );
      if (_readAloud) await _voice.speak(reply.answer);
      if (!mounted) return;
      setState(() => _turns.add(_AssistantTurn(question, reply)));
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error =
            'Ask Nutri could not answer right now. Your scan and question are safe; try again.';
        _message.text = question;
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  void dispose() {
    _message.dispose();
    _voice.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Ask Nutri'),
      actions: [
        IconButton(
          tooltip: _readAloud ? 'Turn read aloud off' : 'Read answers aloud',
          isSelected: _readAloud,
          onPressed: () async {
            await _voice.stopSpeaking();
            if (mounted) setState(() => _readAloud = !_readAloud);
          },
          icon: const Icon(Icons.volume_up_outlined),
          selectedIcon: const Icon(Icons.volume_up),
        ),
      ],
    ),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text(
          widget.scanId == null
              ? 'Ask about food labels, ingredients, or nutrients. Answers use governed evidence and are not medical advice.'
              : 'Ask about this scan. NutriLens will keep the answer tied to evidence from the label.',
        ),
        if (widget.scanId != null) ...[
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.document_scanner_outlined),
              title: const Text('Using the current scan'),
              subtitle: Text('Scan ${widget.scanId}'),
            ),
          ),
        ],
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: _suggestions
              .map(
                (question) => ActionChip(
                  label: Text(question),
                  onPressed: _loading ? null : () => _send(question),
                ),
              )
              .toList(growable: false),
        ),
        for (final turn in _turns) ...[
          const SizedBox(height: 16),
          Align(
            alignment: Alignment.centerRight,
            child: Card(
              color: Theme.of(context).colorScheme.primaryContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text(turn.question),
              ),
            ),
          ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(turn.reply.answer),
                  if (turn.reply.evidence.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Text(
                      'Evidence',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    for (final evidence in turn.reply.evidence)
                      Text('• $evidence'),
                  ],
                  if (turn.reply.citations.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Text(
                      'Sources',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    for (final citation in turn.reply.citations)
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('${citation.authority} · ${citation.title}'),
                            if (citation.url.isNotEmpty)
                              SelectableText(
                                citation.url,
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                          ],
                        ),
                      ),
                  ],
                  const SizedBox(height: 12),
                  Text(
                    '${turn.reply.remainingToday} questions remaining today',
                  ),
                  Text(
                    turn.reply.disclaimer,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: 16),
        TextField(
          controller: _message,
          minLines: 2,
          maxLines: 5,
          decoration: const InputDecoration(
            border: OutlineInputBorder(),
            labelText: 'Your question',
          ),
          onSubmitted: (_) => _send(),
        ),
        const SizedBox(height: 8),
        Text(_voiceStatus, style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(height: 12),
        Row(
          children: [
            IconButton.filledTonal(
              tooltip: _listening ? 'Stop listening' : 'Dictate question',
              onPressed: !_loading && (_voiceAvailable || !_voiceInitialized)
                  ? _toggleListening
                  : null,
              icon: Icon(_listening ? Icons.mic : Icons.mic_none),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton.icon(
                onPressed: _loading ? null : () => _send(),
                icon: const Icon(Icons.send),
                label: const Text('Ask Nutri'),
              ),
            ),
          ],
        ),
        if (_loading) const LinearProgressIndicator(),
        if (_error != null)
          Card(
            child: ListTile(
              leading: const Icon(Icons.error_outline),
              title: Text(_error!),
              trailing: TextButton(
                onPressed: _loading || _lastQuestion == null
                    ? null
                    : () => _send(_lastQuestion),
                child: const Text('Retry'),
              ),
            ),
          ),
      ],
    ),
  );

  List<String> get _suggestions => widget.scanId == null
      ? const [
          'What can NutriLens explain?',
          'How should I read a nutrition label?',
          'What does per serving mean?',
        ]
      : const [
          'Explain this scan',
          'What should I watch?',
          'Does it contain an allergen?',
          'How much protein is one serving?',
        ];
}

class _AssistantTurn {
  const _AssistantTurn(this.question, this.reply);
  final String question;
  final AssistantReply reply;
}

class BillingScreen extends StatelessWidget {
  const BillingScreen({required this.products, super.key});
  final ProductGateway products;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Plan & billing')),
    body: FutureBuilder<BillingAccount>(
      future: products.billing(),
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return _ErrorCard(message: snapshot.error.toString());
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final account = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            _MetricCard(label: 'Current plan', value: account.plan),
            _MetricCard(
              label: 'Subscription status',
              value: account.subscriptionStatus,
            ),
            if (account.subscriptionId != null)
              SelectableText('Subscription: ${account.subscriptionId}'),
            const SizedBox(height: 16),
            const Text(
              'Purchases and lifecycle changes use Razorpay Test Mode. Payment details are entered only in Razorpay Checkout.',
            ),
          ],
        );
      },
    ),
  );
}

class _AsyncList<T> extends StatelessWidget {
  const _AsyncList({
    required this.title,
    required this.future,
    required this.emptyMessage,
    required this.onAdd,
    required this.itemBuilder,
    this.footer = const [],
  });
  final String title;
  final Future<List<T>> future;
  final String emptyMessage;
  final VoidCallback onAdd;
  final Widget Function(BuildContext context, T item) itemBuilder;
  final List<Widget> footer;

  @override
  Widget build(BuildContext context) => FutureBuilder<List<T>>(
    future: future,
    builder: (context, snapshot) => ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          key: const ValueKey('async-list-header-row'),
          children: [
            Expanded(
              child: Text(
                title,
                style: Theme.of(context).textTheme.headlineMedium,
              ),
            ),
            FilledButton.icon(
              onPressed: onAdd,
              icon: const Icon(Icons.add),
              label: const Text('Add'),
            ),
          ],
        ),
        const SizedBox(key: ValueKey('async-list-spacer'), height: 12),
        if (snapshot.hasError)
          _ErrorCard(key: const ValueKey('async-list-error'), message: snapshot.error.toString())
        else if (!snapshot.hasData)
          const LinearProgressIndicator(key: ValueKey('async-list-loading'))
        else if (snapshot.data!.isEmpty)
          Padding(
            key: const ValueKey('async-list-empty'),
            padding: const EdgeInsets.symmetric(vertical: 36),
            child: Center(child: Text(emptyMessage)),
          )
        else
          for (final item in snapshot.data!) itemBuilder(context, item),
        ...footer,
      ],
    ),
  );
}

class _MetricCard extends StatelessWidget {
  const _MetricCard({required this.label, required this.value});
  final String label;
  final String value;
  @override
  Widget build(BuildContext context) => Card(
    child: ListTile(
      title: Text(label),
      trailing: Text(value, style: Theme.of(context).textTheme.titleMedium),
    ),
  );
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({super.key, required this.message});
  final String message;
  @override
  Widget build(BuildContext context) => Card(
    color: Theme.of(context).colorScheme.errorContainer,
    child: Padding(padding: const EdgeInsets.all(16), child: Text(message)),
  );
}
