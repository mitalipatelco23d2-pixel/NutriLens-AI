import 'dart:math';

import 'package:flutter/material.dart';

import 'reminder_settings_screen.dart';
import 'services/hydration_controller.dart';
import 'services/hydration_models.dart';
import 'services/local_reminders.dart';

class HydrationSummaryCard extends StatelessWidget {
  const HydrationSummaryCard({
    required this.controller,
    required this.onOpen,
    super.key,
  });
  final HydrationController controller;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) {
      final value = controller.todaySummary;
      final current = value?.day == hydrationDay(controller.now());
      return Card(
        child: ListTile(
          leading: const Icon(Icons.water_drop_outlined),
          title: const Text('Water today'),
          subtitle: Text(
            !controller.active
                ? 'Sign in to view your water log.'
                : controller.error != null
                ? 'Unable to refresh. Open water to retry.'
                : !current
                ? 'Loading your water log…'
                : '${formatWater(value!.totalMl)} logged · '
                      '${value.targetMl == null ? 'No target set' : '${formatWater(value.remainingMl ?? 0)} remaining'}',
          ),
          trailing: const Icon(Icons.chevron_right),
          onTap: controller.active ? onOpen : null,
        ),
      );
    },
  );
}

class HydrationScreen extends StatefulWidget {
  const HydrationScreen({
    required this.controller,
    this.localReminders,
    this.ownerId,
    super.key,
  });
  final HydrationController controller;
  final LocalReminderCoordinator? localReminders;
  final String? ownerId;

  @override
  State<HydrationScreen> createState() => _HydrationScreenState();
}

class _HydrationScreenState extends State<HydrationScreen> {
  String _period = 'WEEK';
  Future<HydrationAnalytics>? _analytics;

  @override
  void initState() {
    super.initState();
    _loadAnalytics();
  }

  void _loadAnalytics() {
    if (widget.controller.active) {
      setState(() {
        _analytics = widget.controller.gateway.hydrationAnalytics(
          period: _period,
          day: widget.controller.selectedDay,
        );
      });
    }
  }

  Future<void> _chooseDay(BuildContext context) async {
    final day = await showDatePicker(
      context: context,
      initialDate: widget.controller.selectedDay,
      firstDate: DateTime(2000),
      lastDate: widget.controller.now(),
    );
    if (day != null && widget.controller.active) {
      await widget.controller.selectDay(day);
      _loadAnalytics();
    }
  }

  Future<void> _amount(BuildContext context, {HydrationEntry? entry}) async {
    final amount = await showDialog<int>(
      context: context,
      builder: (_) => _WaterAmountDialog(entry: entry),
    );
    if (amount == null || !widget.controller.active) return;
    if (entry == null) {
      await widget.controller.add(amount);
    } else {
      await widget.controller.edit(entry, amount);
    }
    _loadAnalytics();
  }

  Future<void> _target(BuildContext context) async {
    final result = await showDialog<_TargetChoice>(
      context: context,
      builder: (_) => _WaterTargetDialog(target: widget.controller.summary?.targetMl),
    );
    if (result != null && widget.controller.active) {
      await widget.controller.saveTarget(result.amountMl);
      _loadAnalytics();
    }
  }

  Future<void> _delete(BuildContext context, HydrationEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete water entry?'),
        content: Text('Remove ${formatWater(entry.amountMl)} from your log?'),
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
    if (confirmed == true && widget.controller.active) {
      await widget.controller.delete(entry.id);
      _loadAnalytics();
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Water'),
      actions: [
        if (widget.localReminders != null && widget.ownerId != null)
          IconButton(
            icon: const Icon(Icons.alarm_outlined),
            tooltip: 'Hydration reminders',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute<void>(
                builder: (_) => ReminderSettingsScreen(
                  ownerId: widget.ownerId!,
                  reminders: widget.localReminders!,
                ),
              ),
            ),
          ),
      ],
    ),
    body: ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        if (!widget.controller.active) {
          return const Center(
            child: Text('Sign in again to view your water log.'),
          );
        }
        final value = widget.controller.summary;
        final pending = widget.controller.pendingAdd;
        return RefreshIndicator(
          onRefresh: () async {
            await widget.controller.refresh();
            _loadAnalytics();
          },
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(20),
            children: [
              OutlinedButton.icon(
                onPressed: widget.controller.saving ? null : () => _chooseDay(context),
                icon: const Icon(Icons.calendar_today_outlined),
                label: Text(
                  MaterialLocalizations.of(
                    context,
                  ).formatMediumDate(widget.controller.selectedDay),
                ),
              ),
              if (widget.controller.loading || widget.controller.saving)
                const LinearProgressIndicator(),
              if (widget.controller.error != null)
                Card(
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(widget.controller.error!),
                        TextButton(
                          onPressed: widget.controller.saving || widget.controller.loading
                              ? null
                              : () {
                                  widget.controller.refresh();
                                  _loadAnalytics();
                                },
                          child: const Text('Refresh water log'),
                        ),
                      ],
                    ),
                  ),
                ),
              if (pending != null)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${formatWater(pending.amountMl)} is awaiting confirmation.',
                        ),
                        const Text(
                          'Retry this entry before adding more water. The same entry will be used to avoid duplicates.',
                        ),
                        FilledButton(
                          onPressed: widget.controller.saving || widget.controller.loading
                              ? null
                              : widget.controller.retryAdd,
                          child: const Text('Retry saved entry'),
                        ),
                      ],
                    ),
                  ),
                ),
              if (value != null) ...[
                const SizedBox(height: 16),
                Text(
                  '${formatWater(value.totalMl)} logged',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                if (value.targetMl == null)
                  const Text(
                    'No daily target set. Choose a target that works for you.',
                  )
                else ...[
                  Text(
                    '${formatWater(value.remainingMl ?? 0)} remaining · ${formatWater(value.targetMl!)} daily target',
                  ),
                  const SizedBox(height: 8),
                  LinearProgressIndicator(
                    value: (value.totalMl / value.targetMl!).clamp(0, 1),
                  ),
                ],
                TextButton.icon(
                  onPressed: widget.controller.canMutate
                      ? () => _target(context)
                      : null,
                  icon: const Icon(Icons.flag_outlined),
                  label: Text(
                    value.targetMl == null
                        ? 'Set daily target'
                        : 'Change daily target',
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  'Log water',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const Text('Amounts are recorded for the selected day.'),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final amount in [250, 500])
                      FilledButton(
                        onPressed: widget.controller.canMutate
                            ? () => widget.controller.add(amount)
                            : null,
                        child: Text('+ $amount ml'),
                      ),
                    OutlinedButton(
                      onPressed: widget.controller.canMutate
                          ? () => _amount(context)
                          : null,
                      child: const Text('Custom amount'),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                Text(
                  'Water history',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                if (value.entries.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 24),
                    child: Text('No water logged for this day.'),
                  ),
                for (final entry in value.entries)
                  Card(
                    child: ListTile(
                      title: Text(formatWater(entry.amountMl)),
                      subtitle: Text(
                        '${MaterialLocalizations.of(context).formatTimeOfDay(TimeOfDay.fromDateTime(entry.consumedAt.toLocal()))} · Entered by you',
                      ),
                      trailing: PopupMenuButton<String>(
                        tooltip: 'Water entry options',
                        enabled: widget.controller.canMutate,
                        onSelected: (action) => action == 'edit'
                            ? _amount(context, entry: entry)
                            : _delete(context, entry),
                        itemBuilder: (_) => const [
                          PopupMenuItem(value: 'edit', child: Text('Edit')),
                          PopupMenuItem(value: 'delete', child: Text('Delete')),
                        ],
                      ),
                    ),
                  ),
                const SizedBox(height: 24),
                Text(
                  'Hydration analytics',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                SegmentedButton<String>(
                  segments: const [
                    ButtonSegment(value: 'DAY', label: Text('Day')),
                    ButtonSegment(value: 'WEEK', label: Text('Week')),
                    ButtonSegment(value: 'MONTH', label: Text('Month')),
                    ButtonSegment(value: 'YEAR', label: Text('Year')),
                  ],
                  selected: {_period},
                  onSelectionChanged: (newSelection) {
                    setState(() {
                      _period = newSelection.first;
                      _loadAnalytics();
                    });
                  },
                ),
                const SizedBox(height: 12),
                if (_analytics != null)
                  FutureBuilder<HydrationAnalytics>(
                    future: _analytics,
                    builder: (context, snapshot) {
                      if (snapshot.connectionState == ConnectionState.waiting) {
                        return const Padding(
                          padding: EdgeInsets.symmetric(vertical: 12),
                          child: Center(child: CircularProgressIndicator()),
                        );
                      }
                      if (snapshot.hasError) {
                        return Text('Could not load analytics: ${snapshot.error}');
                      }
                      final data = snapshot.data;
                      if (data == null) return const SizedBox.shrink();
                      final maxVal = data.buckets.fold<int>(
                        0,
                        (prev, b) => b.totalMl > prev ? b.totalMl : prev,
                      );
                      final chartMax = max(maxVal, data.targetMl ?? 1000);
                      return Card(
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Wrap(
                                spacing: 16,
                                runSpacing: 8,
                                children: [
                                  Text(
                                    'Total: ${formatWater(data.totalMl)}',
                                    style: const TextStyle(fontWeight: FontWeight.bold),
                                  ),
                                  Text('Avg: ${formatWater(data.dailyAverageMl)}/day'),
                                  if (data.targetMl != null)
                                    Text(
                                      'Target met: ${data.daysTargetMet}/${data.totalDays} days (${data.attainmentRatePct.toStringAsFixed(0)}%)',
                                    ),
                                ],
                              ),
                              const SizedBox(height: 16),
                              SizedBox(
                                height: 110,
                                child: LayoutBuilder(
                                  builder: (context, constraints) {
                                    final bucketWidth = max(
                                      20.0,
                                      (constraints.maxWidth - (data.buckets.length * 4)) /
                                          max(1, data.buckets.length),
                                    );
                                    return SingleChildScrollView(
                                      scrollDirection: Axis.horizontal,
                                      child: Row(
                                        crossAxisAlignment: CrossAxisAlignment.end,
                                        children: [
                                          for (final bucket in data.buckets)
                                            Padding(
                                              padding: const EdgeInsets.symmetric(horizontal: 2),
                                              child: Column(
                                                mainAxisAlignment: MainAxisAlignment.end,
                                                children: [
                                                  if (bucket.totalMl > 0)
                                                    Text(
                                                      bucket.totalMl >= 1000
                                                          ? '${(bucket.totalMl / 1000).toStringAsFixed(1)}L'
                                                          : '${bucket.totalMl}',
                                                      style: const TextStyle(fontSize: 9),
                                                    ),
                                                  const SizedBox(height: 2),
                                                  Container(
                                                    width: bucketWidth,
                                                    height: chartMax > 0
                                                        ? ((bucket.totalMl / chartMax) * 70)
                                                            .clamp(4.0, 70.0)
                                                        : 4.0,
                                                    decoration: BoxDecoration(
                                                      color: bucket.targetAttained
                                                          ? Theme.of(context).colorScheme.primary
                                                          : Theme.of(context)
                                                              .colorScheme
                                                              .secondary
                                                              .withValues(alpha: bucket.totalMl > 0 ? 0.7 : 0.2),
                                                      borderRadius: BorderRadius.circular(4),
                                                    ),
                                                  ),
                                                  const SizedBox(height: 4),
                                                  Text(bucket.label, style: const TextStyle(fontSize: 10)),
                                                ],
                                              ),
                                            ),
                                        ],
                                      ),
                                    );
                                  },
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
              ],
            ],
          ),
        );
      },
    ),
  );
}

class _WaterAmountDialog extends StatefulWidget {
  const _WaterAmountDialog({this.entry});
  final HydrationEntry? entry;
  @override
  State<_WaterAmountDialog> createState() => _WaterAmountDialogState();
}

class _WaterAmountDialogState extends State<_WaterAmountDialog> {
  late final _amount = TextEditingController(
    text: widget.entry?.amountMl.toString() ?? '',
  );
  final _form = GlobalKey<FormState>();
  @override
  void dispose() {
    _amount.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.entry == null ? 'Log water' : 'Edit water entry'),
    content: Form(
      key: _form,
      child: TextFormField(
        controller: _amount,
        autofocus: true,
        keyboardType: TextInputType.number,
        decoration: const InputDecoration(labelText: 'Water amount (ml)'),
        validator: (value) => _validateAmount(value, 1, 5000),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      FilledButton(
        onPressed: () {
          if (_form.currentState!.validate()) {
            Navigator.pop(context, int.parse(_amount.text.trim()));
          }
        },
        child: const Text('Save'),
      ),
    ],
  );
}

class _TargetChoice {
  const _TargetChoice(this.amountMl);
  final int? amountMl;
}

class _WaterTargetDialog extends StatefulWidget {
  const _WaterTargetDialog({required this.target});
  final int? target;
  @override
  State<_WaterTargetDialog> createState() => _WaterTargetDialogState();
}

class _WaterTargetDialogState extends State<_WaterTargetDialog> {
  late final _target = TextEditingController(
    text: widget.target?.toString() ?? '',
  );
  final _form = GlobalKey<FormState>();
  @override
  void dispose() {
    _target.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Your daily water target'),
    content: Form(
      key: _form,
      child: TextFormField(
        controller: _target,
        autofocus: true,
        keyboardType: TextInputType.number,
        decoration: const InputDecoration(labelText: 'Daily target (ml)'),
        validator: (value) => _validateAmount(value, 100, 10000),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Cancel'),
      ),
      if (widget.target != null)
        TextButton(
          onPressed: () => Navigator.pop(context, const _TargetChoice(null)),
          child: const Text('Clear target'),
        ),
      FilledButton(
        onPressed: () {
          if (_form.currentState!.validate()) {
            Navigator.pop(
              context,
              _TargetChoice(int.parse(_target.text.trim())),
            );
          }
        },
        child: const Text('Save target'),
      ),
    ],
  );
}

String? _validateAmount(String? raw, int minimum, int maximum) {
  final value = int.tryParse(raw?.trim() ?? '');
  return value == null || value < minimum || value > maximum
      ? 'Enter a whole amount from $minimum to $maximum ml.'
      : null;
}
