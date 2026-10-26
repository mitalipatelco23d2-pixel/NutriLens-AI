import 'package:flutter/material.dart';

import 'services/health_connect.dart';

class HealthConnectScreen extends StatefulWidget {
  const HealthConnectScreen({
    required this.ownerId,
    required this.healthConnect,
    super.key,
  });

  final String ownerId;
  final HealthConnectCoordinator healthConnect;

  @override
  State<HealthConnectScreen> createState() => _HealthConnectScreenState();
}

class _HealthConnectScreenState extends State<HealthConnectScreen> {
  HealthConnectAvailability? _availability;
  HealthConnectSnapshot? _snapshot;
  bool _syncEnabled = false;
  bool _busy = true;
  String? _notice;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final state = await widget.healthConnect.load(widget.ownerId);
      if (!mounted) return;
      setState(() {
        _availability = state.availability;
        _syncEnabled = state.syncEnabled;
        _busy = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _notice = 'Health Connect availability could not be checked: $error';
        _busy = false;
      });
    }
  }

  Future<void> _setEnabled(bool enabled) async {
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      await widget.healthConnect.setSyncEnabled(widget.ownerId, enabled);
      if (!mounted) return;
      setState(() {
        _syncEnabled = enabled;
        _snapshot = enabled ? _snapshot : null;
        _notice = enabled
            ? 'Sync is enabled. Tap Connect to choose Health Connect access.'
            : 'Sync is paused. NutriLens will not read Health Connect data.';
      });
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Could not save setting: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _connect() async {
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      final access = await widget.healthConnect.connect(widget.ownerId);
      if (!mounted) return;
      setState(
        () => _notice = access.all
            ? 'Hydration and weight read access granted. Tap Sync now to build a local preview.'
            : access.any
            ? '${access.water ? 'Hydration' : 'Weight'} read access granted. The other data type will remain unavailable.'
            : 'Access was not granted. No health data was read.',
      );
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Connection failed: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sync() async {
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      final snapshot = await widget.healthConnect.sync(widget.ownerId);
      if (!mounted) return;
      setState(() {
        _snapshot = snapshot;
        _notice = 'Local preview refreshed. Nothing was uploaded.';
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _notice = error is StateError
            ? error.message.toString()
            : 'Health data could not be read: $error';
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _disconnect() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Disconnect Health Connect?'),
        content: const Text(
          'This revokes NutriLens read access and pauses sync. It does not delete data stored by Health Connect.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('confirm-health-connect-disconnect'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      await widget.healthConnect.disconnect(widget.ownerId);
      if (!mounted) return;
      setState(() {
        _syncEnabled = false;
        _snapshot = null;
        _notice = 'Health Connect access revoked and sync paused.';
      });
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Could not disconnect: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _install() async {
    setState(() => _busy = true);
    try {
      await widget.healthConnect.openInstallFlow();
      if (mounted) {
        setState(
          () => _notice =
              'Finish installing or updating Health Connect, then return and refresh.',
        );
      }
    } on Object catch (error) {
      if (mounted) {
        setState(() => _notice = 'Could not open install flow: $error');
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Health Connect')),
    body: _busy && _availability == null
        ? const Center(child: CircularProgressIndicator())
        : ListView(
            padding: const EdgeInsets.all(20),
            children: [
              const Text(
                'Optional Android preview for hydration and weight. NutriLens requests read-only access, reads at most the last 30 days, and keeps this preview on this device.',
              ),
              const SizedBox(height: 12),
              Card(
                child: ListTile(
                  leading: const Icon(Icons.health_and_safety_outlined),
                  title: Text(_availabilityLabel(_availability)),
                  subtitle: const Text(
                    'No background, history, write, activity, or location permission is requested.',
                  ),
                ),
              ),
              if (_availability == HealthConnectAvailability.installRequired)
                FilledButton.icon(
                  key: const Key('install-health-connect'),
                  onPressed: _busy ? null : _install,
                  icon: const Icon(Icons.system_update_alt),
                  label: const Text('Install or update Health Connect'),
                ),
              SwitchListTile(
                key: const Key('health-connect-sync-toggle'),
                value: _syncEnabled,
                onChanged:
                    _busy ||
                        _availability != HealthConnectAvailability.available
                    ? null
                    : _setEnabled,
                title: const Text('Allow manual sync'),
                subtitle: const Text(
                  'Off by default. Turning this on does not open a permission prompt.',
                ),
              ),
              if (_availability == HealthConnectAvailability.available &&
                  _syncEnabled) ...[
                const SizedBox(height: 8),
                Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    FilledButton.icon(
                      key: const Key('connect-health-connect'),
                      onPressed: _busy ? null : _connect,
                      icon: const Icon(Icons.link),
                      label: const Text('Connect'),
                    ),
                    OutlinedButton.icon(
                      key: const Key('sync-health-connect'),
                      onPressed: _busy ? null : _sync,
                      icon: const Icon(Icons.sync),
                      label: const Text('Sync now'),
                    ),
                    TextButton.icon(
                      key: const Key('disconnect-health-connect'),
                      onPressed: _busy ? null : _disconnect,
                      icon: const Icon(Icons.link_off),
                      label: const Text('Disconnect'),
                    ),
                  ],
                ),
              ],
              if (_busy) const LinearProgressIndicator(),
              if (_notice != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Text(_notice!),
                ),
              if (_snapshot case final snapshot?) ...[
                const SizedBox(height: 8),
                Text(
                  'Local preview',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                Card(
                  child: ListTile(
                    leading: const Icon(Icons.water_drop_outlined),
                    title: Text(
                      !snapshot.access.water
                          ? 'Today’s water: access not granted'
                          : snapshot.waterTodayLiters == null
                          ? 'Today’s water: no record found'
                          : 'Today’s water: ${snapshot.waterTodayLiters!.toStringAsFixed(2)} L',
                    ),
                    subtitle: Text(
                      '${snapshot.waterRecordCount} hydration record(s) in the 30-day window',
                    ),
                  ),
                ),
                Card(
                  child: ListTile(
                    leading: const Icon(Icons.monitor_weight_outlined),
                    title: Text(
                      !snapshot.access.weight
                          ? 'Latest weight: access not granted'
                          : snapshot.latestWeightKg == null
                          ? 'Latest weight: no record found'
                          : 'Latest weight: ${snapshot.latestWeightKg!.toStringAsFixed(1)} kg',
                    ),
                    subtitle: Text(
                      snapshot.latestWeightAt == null
                          ? '${snapshot.weightRecordCount} weight record(s) in the 30-day window'
                          : '${snapshot.weightRecordCount} weight record(s) · ${_date(snapshot.latestWeightAt!)}',
                    ),
                  ),
                ),
                Text(
                  snapshot.sourceNames.isEmpty
                      ? 'Source: not reported by Health Connect'
                      : 'Sources: ${snapshot.sourceNames.join(', ')}',
                ),
                const SizedBox(height: 6),
                const Text(
                  'This preview is not a diagnosis and is not merged into your NutriLens account or diary.',
                ),
              ],
            ],
          ),
  );
}

String _availabilityLabel(HealthConnectAvailability? value) => switch (value) {
  HealthConnectAvailability.available => 'Health Connect is available',
  HealthConnectAvailability.installRequired =>
    'Health Connect needs installation or an update',
  HealthConnectAvailability.unavailable =>
    'Health Connect is unavailable on this device',
  HealthConnectAvailability.unsupported =>
    'This preview is currently available on Android only',
  null => 'Checking Health Connect availability',
};

String _date(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';
