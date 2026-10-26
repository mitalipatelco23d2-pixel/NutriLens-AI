import 'dart:math';

import 'package:flutter/material.dart';

import 'services/weight_models.dart';

class WeightScreen extends StatefulWidget {
  const WeightScreen({required this.gateway, super.key});

  final WeightGateway gateway;

  @override
  State<WeightScreen> createState() => _WeightScreenState();
}

class _WeightScreenState extends State<WeightScreen> {
  late Future<WeightSummary> _summary = widget.gateway.weightSummary();
  var _busy = false;
  String? _notice;

  void _reload() {
    setState(() {
      _summary = widget.gateway.weightSummary();
      _notice = null;
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      await action();
      if (mounted) _reload();
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Could not save: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _enable() async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Enable optional weight tracking?'),
        content: const Text(
          'Weight records will be stored in your NutriLens account and included in your account export. This is descriptive tracking only—not an ideal-weight, calorie or medical recommendation.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('confirm-enable-weight'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Enable'),
          ),
        ],
      ),
    );
    if (accepted == true) {
      await _run(() async => widget.gateway.enableWeightTracking(null));
    }
  }

  Future<(bool, double?)> _valueDialog({
    required String title,
    required String action,
    double? initial,
    required bool allowEmpty,
  }) async {
    final result = await showDialog<(bool, double?)>(
      context: context,
      builder: (context) => _WeightValueDialog(
        title: title,
        action: action,
        initial: initial,
        allowEmpty: allowEmpty,
      ),
    );
    return result ?? (false, null);
  }

  Future<void> _setTarget(WeightSummary summary) async {
    final result = await _valueDialog(
      title: 'Optional target weight',
      action: 'Save',
      initial: summary.targetWeightKg,
      allowEmpty: true,
    );
    if (result.$1) {
      await _run(() async => widget.gateway.enableWeightTracking(result.$2));
    }
  }

  Future<void> _add() async {
    final result = await _valueDialog(
      title: 'Add self-reported weight',
      action: 'Add',
      allowEmpty: false,
    );
    if (result.$1 && result.$2 != null) {
      await _run(
        () async => widget.gateway.addWeight(
          WeightEntry(
            id: _uuid(),
            weightKg: result.$2!,
            recordedAt: DateTime.now().toUtc(),
          ),
        ),
      );
    }
  }

  Future<void> _edit(WeightEntry entry) async {
    final result = await _valueDialog(
      title: 'Edit self-reported weight',
      action: 'Save',
      initial: entry.weightKg,
      allowEmpty: false,
    );
    if (result.$1 && result.$2 != null) {
      await _run(
        () async => widget.gateway.updateWeight(
          WeightEntry(
            id: entry.id,
            weightKg: result.$2!,
            recordedAt: entry.recordedAt,
          ),
        ),
      );
    }
  }

  Future<void> _delete(WeightEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Delete this weight record?'),
        content: Text(
          '${_formatKg(entry.weightKg)} will be removed from your account.',
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
      await _run(() => widget.gateway.deleteWeight(entry.id));
    }
  }

  Future<void> _disable() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Disable and erase weight tracking?'),
        content: const Text(
          'This permanently deletes your NutriLens weight target, history and retry records. Local Health Connect data is not changed.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('confirm-disable-weight'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Disable and erase'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _run(widget.gateway.disableWeightTracking);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Optional weight tracking')),
    body: FutureBuilder<WeightSummary>(
      future: _summary,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(
            child: FilledButton(
              onPressed: _reload,
              child: const Text('Retry weight history'),
            ),
          );
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final summary = snapshot.data!;
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            if (_notice != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(_notice!, key: const Key('weight-notice')),
              ),
            if (summary.state == 'DISABLED') ...[
              const Icon(Icons.monitor_weight_outlined, size: 52),
              const SizedBox(height: 12),
              const Text(
                'Weight tracking is off',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w700),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(summary.limitation, textAlign: TextAlign.center),
              const SizedBox(height: 20),
              FilledButton(
                key: const Key('enable-weight'),
                onPressed: _busy ? null : _enable,
                child: const Text('Enable optional tracking'),
              ),
            ] else ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('Latest self-reported weight'),
                      Text(
                        summary.latestWeightKg == null
                            ? 'No records yet'
                            : _formatKg(summary.latestWeightKg!),
                        style: const TextStyle(
                          fontSize: 26,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      if (summary.changeFromFirstKg != null)
                        Text(
                          'Change across returned records: ${_signedKg(summary.changeFromFirstKg!)}',
                        ),
                      if (summary.differenceFromTargetKg != null)
                        Text(
                          'Latest minus your target: ${_signedKg(summary.differenceFromTargetKg!)}',
                        ),
                    ],
                  ),
                ),
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.flag_outlined),
                title: const Text('Optional target'),
                subtitle: Text(
                  summary.targetWeightKg == null
                      ? 'Not set'
                      : _formatKg(summary.targetWeightKg!),
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: _busy ? null : () => _setTarget(summary),
              ),
              FilledButton.icon(
                key: const Key('add-weight'),
                onPressed: _busy ? null : _add,
                icon: const Icon(Icons.add),
                label: const Text('Add weight record'),
              ),
              const SizedBox(height: 12),
              if (summary.entries.isEmpty)
                const Text('No weight records yet.')
              else
                for (final entry in summary.entries)
                  ListTile(
                    title: Text(_formatKg(entry.weightKg)),
                    subtitle: Text(
                      MaterialLocalizations.of(
                        context,
                      ).formatMediumDate(entry.recordedAt.toLocal()),
                    ),
                    onTap: _busy ? null : () => _edit(entry),
                    trailing: IconButton(
                      tooltip: 'Delete weight record',
                      onPressed: _busy ? null : () => _delete(entry),
                      icon: const Icon(Icons.delete_outline),
                    ),
                  ),
              const SizedBox(height: 12),
              Text(summary.limitation),
              const SizedBox(height: 20),
              OutlinedButton(
                key: const Key('disable-weight'),
                onPressed: _busy ? null : _disable,
                child: const Text('Disable and erase weight data'),
              ),
            ],
          ],
        );
      },
    ),
  );
}

String _formatKg(double value) {
  final formatted = value
      .toStringAsFixed(2)
      .replaceFirst(RegExp(r'0+$'), '')
      .replaceFirst(RegExp(r'\.$'), '');
  return '$formatted kg';
}

String _signedKg(double value) => '${value > 0 ? '+' : ''}${_formatKg(value)}';

class _WeightValueDialog extends StatefulWidget {
  const _WeightValueDialog({
    required this.title,
    required this.action,
    required this.initial,
    required this.allowEmpty,
  });

  final String title;
  final String action;
  final double? initial;
  final bool allowEmpty;

  @override
  State<_WeightValueDialog> createState() => _WeightValueDialogState();
}

class _WeightValueDialogState extends State<_WeightValueDialog> {
  late final TextEditingController _controller = TextEditingController(
    text:
        widget.initial
            ?.toStringAsFixed(2)
            .replaceFirst(RegExp(r'\.?0+$'), '') ??
        '',
  );

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final text = _controller.text.trim();
    final parsed = double.tryParse(text);
    final valid =
        (widget.allowEmpty && text.isEmpty) ||
        (parsed != null && parsed >= 20 && parsed <= 500);
    return AlertDialog(
      title: Text(widget.title),
      content: TextField(
        key: const Key('weight-value'),
        controller: _controller,
        autofocus: true,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(
          labelText: 'Weight (kg)',
          helperText: widget.allowEmpty
              ? 'Leave blank to remove the optional target.'
              : 'Enter a value from 20 to 500 kg.',
        ),
        onChanged: (_) => setState(() {}),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: Key('confirm-${widget.action.toLowerCase()}-weight'),
          onPressed: valid
              ? () =>
                    Navigator.pop(context, (true, text.isEmpty ? null : parsed))
              : null,
          child: Text(widget.action),
        ),
      ],
    );
  }
}

String _uuid() {
  final random = Random.secure();
  final bytes = List<int>.generate(16, (_) => random.nextInt(256));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  final hex = bytes
      .map((value) => value.toRadixString(16).padLeft(2, '0'))
      .join();
  return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
      '${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
}
