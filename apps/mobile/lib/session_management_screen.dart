import 'package:flutter/material.dart';

import 'services/product_api.dart';

class SessionManagementScreen extends StatefulWidget {
  const SessionManagementScreen({required this.products, super.key});

  final ProductGateway products;

  @override
  State<SessionManagementScreen> createState() =>
      _SessionManagementScreenState();
}

class _SessionManagementScreenState extends State<SessionManagementScreen> {
  late Future<List<AccountSession>> _sessions = widget.products
      .accountSessions();
  String? _revokingId;
  String? _notice;

  Future<void> _refresh() async {
    final future = widget.products.accountSessions();
    setState(() => _sessions = future);
    await future;
  }

  Future<void> _revoke(AccountSession session) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Sign out this session?'),
        content: Text(
          'This revokes session …${_shortId(session.id)}. That device must sign in again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('confirm-revoke-session'),
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Sign out'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _revokingId = session.id;
      _notice = null;
    });
    try {
      await widget.products.revokeAccountSession(session.id);
      if (mounted) {
        setState(() {
          _revokingId = null;
          _notice = 'Session signed out.';
          _sessions = widget.products.accountSessions();
        });
      }
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _revokingId = null;
          _notice = 'Could not revoke session: $error';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Active sessions')),
    body: RefreshIndicator(
      onRefresh: _refresh,
      child: FutureBuilder<List<AccountSession>>(
        future: _sessions,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return ListView(
              padding: const EdgeInsets.all(24),
              children: [
                Text(
                  'Could not load active sessions: ${snapshot.error}',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 12),
                FilledButton(onPressed: _refresh, child: const Text('Retry')),
              ],
            );
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              const Text(
                'NutriLens stores session times, not device names or location. Revoke any other session you do not recognize.',
              ),
              if (_notice != null) ...[
                const SizedBox(height: 8),
                Text(_notice!),
              ],
              const SizedBox(height: 12),
              if (snapshot.data!.isEmpty)
                const Card(
                  child: ListTile(title: Text('No active sessions found.')),
                ),
              for (final session in snapshot.data!)
                Card(
                  child: ListTile(
                    leading: Icon(
                      session.current
                          ? Icons.smartphone_outlined
                          : Icons.devices_outlined,
                    ),
                    title: Text(
                      session.current
                          ? 'This session'
                          : 'Session …${_shortId(session.id)}',
                    ),
                    subtitle: Text(
                      'Created ${_formatTime(session.createdAt)}\n'
                      'Last active ${_formatTime(session.lastSeenAt)} · '
                      'expires ${_formatTime(session.expiresAt)}',
                    ),
                    isThreeLine: true,
                    trailing: session.current
                        ? const Chip(label: Text('Current'))
                        : IconButton(
                            key: Key('revoke-session-${session.id}'),
                            tooltip: 'Sign out this session',
                            onPressed: _revokingId == null
                                ? () => _revoke(session)
                                : null,
                            icon: _revokingId == session.id
                                ? const SizedBox.square(
                                    dimension: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.logout),
                          ),
                  ),
                ),
            ],
          );
        },
      ),
    ),
  );
}

String _shortId(String value) =>
    value.length <= 8 ? value : value.substring(value.length - 8);

String _formatTime(DateTime value) {
  final local = value.toLocal();
  return '${local.year.toString().padLeft(4, '0')}-'
      '${local.month.toString().padLeft(2, '0')}-'
      '${local.day.toString().padLeft(2, '0')} '
      '${local.hour.toString().padLeft(2, '0')}:'
      '${local.minute.toString().padLeft(2, '0')}';
}
