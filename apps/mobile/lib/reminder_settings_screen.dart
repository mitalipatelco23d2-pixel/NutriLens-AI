import 'package:flutter/material.dart';

import 'services/local_reminders.dart';

class ReminderSettingsScreen extends StatefulWidget {
  const ReminderSettingsScreen({
    required this.ownerId,
    required this.reminders,
    super.key,
  });

  final String ownerId;
  final LocalReminderCoordinator reminders;

  @override
  State<ReminderSettingsScreen> createState() => _ReminderSettingsScreenState();
}

class _ReminderSettingsScreenState extends State<ReminderSettingsScreen> {
  LocalReminderPreferences? _preferences;
  ReminderPermission _permission = ReminderPermission.unavailable;
  bool _loading = true;
  bool _saving = false;
  String? _notice;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final state = await widget.reminders.load(widget.ownerId);
      if (!mounted) return;
      setState(() {
        _preferences = state.preferences;
        _permission = state.permission;
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _notice = 'Reminders could not be loaded: $error';
        _loading = false;
      });
    }
  }

  Future<void> _requestPermission() async {
    setState(() {
      _saving = true;
      _notice = null;
    });
    try {
      final permission = await widget.reminders.requestPermissionAndSync(
        widget.ownerId,
      );
      if (!mounted) return;
      setState(() {
        _permission = permission;
        _notice = permission == ReminderPermission.granted
            ? 'Notification permission granted.'
            : 'Permission was not granted. Reminders stay off at system level.';
      });
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Permission check failed: $error');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _save() async {
    final preferences = _preferences;
    if (preferences == null || _saving) return;
    if (preferences.hydrationEnabled &&
        preferences.hydrationStartMinutes > preferences.hydrationEndMinutes) {
      setState(
        () => _notice =
            'Hydration end time must be after the start time on the same day.',
      );
      return;
    }
    setState(() {
      _saving = true;
      _notice = null;
    });
    try {
      await widget.reminders.save(widget.ownerId, preferences);
      if (!mounted) return;
      setState(
        () => _notice = _permission == ReminderPermission.granted
            ? '${preferences.schedules().length} scheduled reminder(s) saved.'
            : 'Preferences saved. Allow notifications to activate reminders.',
      );
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Could not save reminders: $error');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _showTest() async {
    setState(() {
      _saving = true;
      _notice = null;
    });
    try {
      await widget.reminders.showTest(widget.ownerId);
      if (mounted) setState(() => _notice = 'Test reminder sent.');
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Test reminder failed: $error');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<int?> _pickMinutes(int current) async {
    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: current ~/ 60, minute: current % 60),
    );
    return picked == null ? null : picked.hour * 60 + picked.minute;
  }

  void _update(LocalReminderPreferences preferences) {
    setState(() {
      _preferences = preferences;
      _notice = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final preferences = _preferences;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Local reminders'),
        actions: [
          TextButton(
            key: const Key('save-reminders'),
            onPressed: preferences == null || _saving ? null : _save,
            child: const Text('Save'),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : preferences == null
          ? _ReminderNotice(
              text:
                  _notice ?? 'Local reminders are unavailable on this device.',
            )
          : ListView(
              padding: const EdgeInsets.all(20),
              children: [
                const Text(
                  'Reminders stay on this device. NutriLens never asks for notification permission until you tap Allow.',
                ),
                const SizedBox(height: 12),
                Card(
                  child: ListTile(
                    leading: Icon(
                      _permission == ReminderPermission.granted
                          ? Icons.notifications_active_outlined
                          : Icons.notifications_off_outlined,
                    ),
                    title: Text(_permissionLabel(_permission)),
                    subtitle: const Text(
                      'Inexact delivery respects battery controls and does not request exact-alarm access.',
                    ),
                    trailing: _permission == ReminderPermission.granted
                        ? null
                        : FilledButton(
                            key: const Key('request-reminder-permission'),
                            onPressed: _saving ? null : _requestPermission,
                            child: const Text('Allow'),
                          ),
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  'Scheduled check-ins',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                SwitchListTile(
                  key: const Key('hydration-reminder-toggle'),
                  title: const Text('Hydration'),
                  subtitle: Text(
                    'Every ${preferences.hydrationIntervalMinutes ~/ 60} hour(s), ${_formatMinutes(context, preferences.hydrationStartMinutes)}–${_formatMinutes(context, preferences.hydrationEndMinutes)}',
                  ),
                  value: preferences.hydrationEnabled,
                  onChanged: (value) =>
                      _update(preferences.copyWith(hydrationEnabled: value)),
                ),
                if (preferences.hydrationEnabled) ...[
                  _TimeTile(
                    label: 'Hydration starts',
                    minutes: preferences.hydrationStartMinutes,
                    onTap: () async {
                      final value = await _pickMinutes(
                        preferences.hydrationStartMinutes,
                      );
                      if (value != null) {
                        _update(
                          preferences.copyWith(hydrationStartMinutes: value),
                        );
                      }
                    },
                  ),
                  _TimeTile(
                    label: 'Hydration ends',
                    minutes: preferences.hydrationEndMinutes,
                    onTap: () async {
                      final value = await _pickMinutes(
                        preferences.hydrationEndMinutes,
                      );
                      if (value != null) {
                        _update(
                          preferences.copyWith(hydrationEndMinutes: value),
                        );
                      }
                    },
                  ),
                  ListTile(
                    title: const Text('Hydration interval'),
                    trailing: DropdownButton<int>(
                      value: preferences.hydrationIntervalMinutes,
                      items: const [60, 120, 180]
                          .map(
                            (minutes) => DropdownMenuItem(
                              value: minutes,
                              child: Text('${minutes ~/ 60} hour(s)'),
                            ),
                          )
                          .toList(growable: false),
                      onChanged: (value) {
                        if (value != null) {
                          _update(
                            preferences.copyWith(
                              hydrationIntervalMinutes: value,
                            ),
                          );
                        }
                      },
                    ),
                  ),
                ],
                SwitchListTile(
                  key: const Key('meal-reminder-toggle'),
                  title: const Text('Meals'),
                  subtitle: const Text(
                    'Breakfast, lunch, and dinner check-ins',
                  ),
                  value: preferences.mealsEnabled,
                  onChanged: (value) =>
                      _update(preferences.copyWith(mealsEnabled: value)),
                ),
                if (preferences.mealsEnabled)
                  for (final entry
                      in <
                        (String, int, LocalReminderPreferences Function(int))
                      >[
                        (
                          'Breakfast',
                          preferences.breakfastMinutes,
                          (value) =>
                              preferences.copyWith(breakfastMinutes: value),
                        ),
                        (
                          'Lunch',
                          preferences.lunchMinutes,
                          (value) => preferences.copyWith(lunchMinutes: value),
                        ),
                        (
                          'Dinner',
                          preferences.dinnerMinutes,
                          (value) => preferences.copyWith(dinnerMinutes: value),
                        ),
                      ])
                    _TimeTile(
                      label: entry.$1,
                      minutes: entry.$2,
                      onTap: () async {
                        final value = await _pickMinutes(entry.$2);
                        if (value != null) _update(entry.$3(value));
                      },
                    ),
                SwitchListTile(
                  key: const Key('summary-reminder-toggle'),
                  title: const Text('Daily summary'),
                  value: preferences.dailySummaryEnabled,
                  onChanged: (value) =>
                      _update(preferences.copyWith(dailySummaryEnabled: value)),
                ),
                if (preferences.dailySummaryEnabled)
                  _TimeTile(
                    label: 'Summary time',
                    minutes: preferences.dailySummaryMinutes,
                    onTap: () async {
                      final value = await _pickMinutes(
                        preferences.dailySummaryMinutes,
                      );
                      if (value != null) {
                        _update(
                          preferences.copyWith(dailySummaryMinutes: value),
                        );
                      }
                    },
                  ),
                SwitchListTile(
                  key: const Key('weight-reminder-toggle'),
                  title: const Text('Weekly weight check-in'),
                  subtitle: const Text(
                    'Optional; disable if it does not support your wellbeing',
                  ),
                  value: preferences.weightEnabled,
                  onChanged: (value) =>
                      _update(preferences.copyWith(weightEnabled: value)),
                ),
                if (preferences.weightEnabled) ...[
                  ListTile(
                    title: const Text('Weekday'),
                    trailing: DropdownButton<int>(
                      value: preferences.weightWeekday,
                      items: [
                        for (
                          var day = DateTime.monday;
                          day <= DateTime.sunday;
                          day++
                        )
                          DropdownMenuItem(
                            value: day,
                            child: Text(_weekdayLabel(day)),
                          ),
                      ],
                      onChanged: (value) {
                        if (value != null) {
                          _update(preferences.copyWith(weightWeekday: value));
                        }
                      },
                    ),
                  ),
                  _TimeTile(
                    label: 'Weight reminder time',
                    minutes: preferences.weightMinutes,
                    onTap: () async {
                      final value = await _pickMinutes(
                        preferences.weightMinutes,
                      );
                      if (value != null) {
                        _update(preferences.copyWith(weightMinutes: value));
                      }
                    },
                  ),
                ],
                const Divider(height: 32),
                Text(
                  'Event reminders',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                SwitchListTile(
                  key: const Key('scan-completion-reminder-toggle'),
                  title: const Text('Scan completed'),
                  subtitle: const Text(
                    'Notify when this device receives a completed scan',
                  ),
                  value: preferences.scanCompletionEnabled,
                  onChanged: (value) => _update(
                    preferences.copyWith(scanCompletionEnabled: value),
                  ),
                ),
                SwitchListTile(
                  key: const Key('low-stock-reminder-toggle'),
                  title: const Text('User-defined low stock'),
                  subtitle: const Text(
                    'Notify only when quantity reaches your threshold',
                  ),
                  value: preferences.lowStockEnabled,
                  onChanged: (value) =>
                      _update(preferences.copyWith(lowStockEnabled: value)),
                ),
                const Divider(height: 32),
                Text(
                  'Quiet hours',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const Text(
                  'Scheduled times inside quiet hours are suppressed.',
                ),
                _TimeTile(
                  label: 'Quiet hours start',
                  minutes: preferences.quietStartMinutes,
                  onTap: () async {
                    final value = await _pickMinutes(
                      preferences.quietStartMinutes,
                    );
                    if (value != null) {
                      _update(preferences.copyWith(quietStartMinutes: value));
                    }
                  },
                ),
                _TimeTile(
                  label: 'Quiet hours end',
                  minutes: preferences.quietEndMinutes,
                  onTap: () async {
                    final value = await _pickMinutes(
                      preferences.quietEndMinutes,
                    );
                    if (value != null) {
                      _update(preferences.copyWith(quietEndMinutes: value));
                    }
                  },
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  key: const Key('test-reminder'),
                  onPressed:
                      _saving || _permission != ReminderPermission.granted
                      ? null
                      : _showTest,
                  icon: const Icon(Icons.notifications_active_outlined),
                  label: const Text('Send test reminder'),
                ),
                if (_saving) const LinearProgressIndicator(),
                if (_notice != null) ...[
                  const SizedBox(height: 12),
                  _ReminderNotice(text: _notice!),
                ],
              ],
            ),
    );
  }
}

class _TimeTile extends StatelessWidget {
  const _TimeTile({
    required this.label,
    required this.minutes,
    required this.onTap,
  });

  final String label;
  final int minutes;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => ListTile(
    title: Text(label),
    trailing: TextButton(
      onPressed: onTap,
      child: Text(_formatMinutes(context, minutes)),
    ),
  );
}

class _ReminderNotice extends StatelessWidget {
  const _ReminderNotice({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) => Semantics(
    liveRegion: true,
    child: Card(
      child: Padding(padding: const EdgeInsets.all(14), child: Text(text)),
    ),
  );
}

String _formatMinutes(BuildContext context, int minutes) =>
    TimeOfDay(hour: minutes ~/ 60, minute: minutes % 60).format(context);

String _permissionLabel(ReminderPermission permission) => switch (permission) {
  ReminderPermission.granted => 'Notifications allowed',
  ReminderPermission.denied => 'Notification permission required',
  ReminderPermission.unavailable => 'Notifications unavailable',
};

String _weekdayLabel(int weekday) => switch (weekday) {
  DateTime.monday => 'Monday',
  DateTime.tuesday => 'Tuesday',
  DateTime.wednesday => 'Wednesday',
  DateTime.thursday => 'Thursday',
  DateTime.friday => 'Friday',
  DateTime.saturday => 'Saturday',
  DateTime.sunday => 'Sunday',
  _ => 'Monday',
};
