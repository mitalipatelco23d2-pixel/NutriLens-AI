import 'package:flutter/material.dart';

import 'services/account_data.dart';

class AccountDataScreen extends StatefulWidget {
  const AccountDataScreen({
    required this.accountData,
    required this.afterAccountDeleted,
    super.key,
  });

  final AccountDataCoordinator accountData;
  final Future<void> Function() afterAccountDeleted;

  @override
  State<AccountDataScreen> createState() => _AccountDataScreenState();
}

class _AccountDataScreenState extends State<AccountDataScreen> {
  bool _busy = false;
  String? _notice;

  Future<void> _export(BuildContext buttonContext) async {
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      final box = buttonContext.findRenderObject() as RenderBox?;
      final origin = box == null || !box.hasSize
          ? null
          : box.localToGlobal(Offset.zero) & box.size;
      final result = await widget.accountData.export(
        sharePositionOrigin: origin,
      );
      if (!mounted) return;
      setState(
        () => _notice = switch (result.disposition) {
          AccountExportDisposition.success =>
            '${result.filename} was handed to the selected app.',
          AccountExportDisposition.dismissed =>
            'The share sheet was closed. No destination was confirmed.',
          AccountExportDisposition.unavailable =>
            'No secure share destination is available on this device.',
        },
      );
    } on Object catch (error) {
      if (mounted) setState(() => _notice = 'Export failed: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _confirmDelete() async {
    final accepted = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const _DeleteAccountDialog(),
    );
    if (accepted != true || _busy) return;
    setState(() {
      _busy = true;
      _notice = null;
    });
    var deleted = false;
    try {
      await widget.accountData.deleteAccount();
      deleted = true;
      await widget.afterAccountDeleted();
    } on Object catch (error) {
      if (mounted) {
        setState(
          () => _notice = deleted
              ? 'The account was deleted, but local sign-out cleanup needs attention. Close and reopen the app.'
              : 'Account deletion failed: $error',
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Your data')),
    body: ListView(
      padding: const EdgeInsets.all(20),
      children: [
        const Text(
          'Export a JSON copy of your stored account data or permanently delete your account. Raw scan images are not retained.',
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Export', style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 6),
                const Text(
                  'The authenticated export is prepared only after you tap. Android’s share sheet lets you choose where the JSON goes.',
                ),
                const SizedBox(height: 12),
                Builder(
                  builder: (buttonContext) => FilledButton.icon(
                    key: const Key('export-account-data'),
                    onPressed: _busy ? null : () => _export(buttonContext),
                    icon: const Icon(Icons.ios_share_outlined),
                    label: const Text('Export my data'),
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 12),
        Card(
          color: Theme.of(context).colorScheme.errorContainer,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Delete account',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 6),
                const Text(
                  'Deletion is permanent. You must type DELETE before the server request can be sent.',
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  key: const Key('delete-account'),
                  onPressed: _busy ? null : _confirmDelete,
                  icon: const Icon(Icons.delete_forever_outlined),
                  label: const Text('Delete account'),
                ),
              ],
            ),
          ),
        ),
        if (_busy) const LinearProgressIndicator(),
        if (_notice != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(_notice!),
          ),
      ],
    ),
  );
}

class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog();

  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  final _confirmation = TextEditingController();

  @override
  void dispose() {
    _confirmation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Permanently delete account?'),
    content: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'This permanently removes your NutriLens account and stored application data. This cannot be undone. Export first if you need a copy.',
          ),
          const SizedBox(height: 16),
          TextField(
            key: const Key('delete-account-confirmation'),
            controller: _confirmation,
            autofocus: true,
            autocorrect: false,
            enableSuggestions: false,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              labelText: 'Type DELETE to continue',
            ),
            onChanged: (_) => setState(() {}),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context, false),
        child: const Text('Keep account'),
      ),
      FilledButton(
        key: const Key('confirm-delete-account'),
        onPressed: _confirmation.text == 'DELETE'
            ? () => Navigator.pop(context, true)
            : null,
        child: const Text('Delete permanently'),
      ),
    ],
  );
}
