import 'dart:async';

import 'package:firebase_auth/firebase_auth.dart' as fb_auth;
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'services/auth_service.dart';
import 'services/product_api.dart';
import 'session_management_screen.dart';

class AccountSecurityScreen extends StatefulWidget {
  const AccountSecurityScreen({
    required this.session,
    required this.products,
    this.collegeDemoMode =
        const bool.fromEnvironment('COLLEGE_DEMO_MODE', defaultValue: false),
    super.key,
  });

  final SessionController session;
  final ProductGateway products;
  final bool collegeDemoMode;

  @override
  State<AccountSecurityScreen> createState() => _AccountSecurityScreenState();
}

class _AccountSecurityScreenState extends State<AccountSecurityScreen> {
  late Future<_SecuritySnapshot> _snapshot = _load();
  var _busy = false;
  String? _notice;

  Future<_SecuritySnapshot> _load() async => _SecuritySnapshot(
    identities: await widget.products.authIdentities(),
    profile: await widget.products.accountProfile(),
  );

  void _reload() {
    setState(() => _snapshot = _load());
  }

  Future<void> _run(Future<String> Function() action) async {
    setState(() {
      _busy = true;
      _notice = null;
    });
    try {
      final message = await action();
      if (mounted) {
        setState(() {
          _notice = message;
          _snapshot = _load();
        });
      }
    } on Object catch (error) {
      if (mounted) setState(() => _notice = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<String?> _passwordDialog({required bool changing}) async {
    return showDialog<String>(
      context: context,
      builder: (_) => _PasswordDialog(changing: changing),
    );
  }

  Future<void> _addPassword() async {
    final password = await _passwordDialog(changing: false);
    if (password == null || password.isEmpty) return;
    await _run(() => widget.products.addEmailPassword(password));
  }

  Future<void> _changePassword() async {
    final value = await _passwordDialog(changing: true);
    if (value == null) return;
    final separator = value.indexOf('\n');
    if (separator < 0) return;
    await _run(() async {
      await widget.session.changePassword(
        currentPassword: value.substring(0, separator),
        newPassword: value.substring(separator + 1),
      );
      return 'Password changed. Other sessions were signed out.';
    });
  }

  Future<void> _connectGoogle() async {
    await _run(() async {
      final credential = await widget.session.acquireGoogleCredential();
      await widget.products.connectGoogleIdentity(credential);
      return 'Google sign-in connected.';
    });
  }

  Future<void> _disconnectGoogle() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Disconnect Google?'),
        content: const Text(
          'You will keep access through your verified email/password login.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            key: const Key('confirm-google-disconnect'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _run(() async {
      await widget.products.disconnectGoogleIdentity();
      return 'Google sign-in disconnected.';
    });
  }

  Future<void> _verifyPhone(String maskedPhone) async {
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (_) => _PhoneVerificationDialog(maskedPhone: maskedPhone),
    );
    if (result == null) return;
    final phone = result['phone']!;
    final token = result['token']!;
    await _run(() async {
      await widget.products.connectPhoneIdentity(
        phone: phone,
        firebaseIdToken: token,
      );
      return 'Phone number verified and linked.';
    });
  }


  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Account & security')),
    body: FutureBuilder<_SecuritySnapshot>(
      future: _snapshot,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'Could not load account security: ${snapshot.error}',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _reload, child: const Text('Retry')),
                ],
              ),
            ),
          );
        }
        if (!snapshot.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        final identity = snapshot.data!.identities;
        final profile = snapshot.data!.profile;
        return ListView(
          padding: const EdgeInsets.all(20),
          children: [
            ListTile(
              leading: const Icon(Icons.g_mobiledata),
              title: const Text('Google sign-in'),
              subtitle: Text(
                identity.googleConnected
                    ? identity.emailVerified
                          ? 'Connected'
                          : 'Connected · add and verify email/password before disconnecting'
                    : 'Not connected',
              ),
              trailing: identity.googleConnected
                  ? TextButton(
                      key: const Key('disconnect-google'),
                      onPressed: _busy || !identity.emailVerified
                          ? null
                          : _disconnectGoogle,
                      child: const Text('Disconnect'),
                    )
                  : TextButton(
                      key: const Key('connect-google'),
                      onPressed: _busy ? null : _connectGoogle,
                      child: const Text('Connect'),
                    ),
            ),
            ListTile(
              leading: const Icon(Icons.password_outlined),
              title: const Text('Email & password'),
              subtitle: Text(
                identity.emailVerified
                    ? 'Verified login available'
                    : identity.emailPasswordConnected
                    ? 'Verification pending'
                    : 'Not configured',
              ),
              trailing: identity.emailVerified
                  ? TextButton(
                      onPressed: _busy ? null : _changePassword,
                      child: const Text('Change'),
                    )
                  : TextButton(
                      key: const Key('add-password-login'),
                      onPressed: _busy ? null : _addPassword,
                      child: Text(
                        identity.emailPasswordConnected
                            ? 'Resend / replace'
                            : 'Add',
                      ),
                    ),
            ),
            ListTile(
              leading: const Icon(Icons.mark_email_read_outlined),
              title: const Text('Reset password'),
              subtitle: Text(
                'Send a reset link to ${widget.session.user!.email}',
              ),
              trailing: TextButton(
                onPressed: _busy
                    ? null
                    : () => _run(() async {
                        return widget.session.requestPasswordReset(
                          widget.session.user!.email,
                        );
                      }),
                child: const Text('Send'),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.phone_outlined),
              title: const Text('Phone'),
              subtitle: Text(
                profile.maskedPhoneNumber == null
                    ? (widget.collegeDemoMode
                        ? 'Phone number (optional)'
                        : 'Optional · not added')
                    : (widget.collegeDemoMode
                        ? '${profile.maskedPhoneNumber} · optional'
                        : '${profile.maskedPhoneNumber} · ${profile.phoneState.toLowerCase()}'),
              ),
              trailing: widget.collegeDemoMode
                  ? null
                  : (profile.phoneState == 'VERIFIED'
                      ? TextButton(
                          key: const Key('update-phone-action'),
                          onPressed: _busy
                              ? null
                              : () => _verifyPhone(profile.maskedPhoneNumber ?? ''),
                          child: const Text('Update'),
                        )
                      : TextButton(
                          key: const Key('verify-phone-action'),
                          onPressed: _busy
                              ? null
                              : () => _verifyPhone(profile.maskedPhoneNumber ?? ''),
                          child: Text(profile.maskedPhoneNumber == null ? 'Link' : 'Verify'),
                        )),
            ),
            ListTile(
              key: const Key('security-active-sessions'),
              leading: const Icon(Icons.devices_outlined),
              title: const Text('Active sessions'),
              subtitle: const Text(
                'Review and revoke other signed-in sessions',
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) =>
                      SessionManagementScreen(products: widget.products),
                ),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.verified_user_outlined),
              title: const Text('Legal acceptance'),
              subtitle: Text(
                identity.termsAccepted && identity.privacyAccepted
                    ? 'Terms and Privacy Policy accepted'
                    : 'Complete account setup to accept current terms',
              ),
            ),
            if (_notice != null)
              Padding(
                padding: const EdgeInsets.all(12),
                child: Text(
                  _notice!,
                  style: TextStyle(
                    color: _notice!.toLowerCase().contains('error')
                        ? Theme.of(context).colorScheme.error
                        : null,
                  ),
                ),
              ),
          ],
        );
      },
    ),
  );
}

class _SecuritySnapshot {
  const _SecuritySnapshot({required this.identities, required this.profile});

  final AuthIdentityState identities;
  final AccountProfile profile;
}

class _PasswordDialog extends StatefulWidget {
  const _PasswordDialog({required this.changing});

  final bool changing;

  @override
  State<_PasswordDialog> createState() => _PasswordDialogState();
}

class _PasswordDialogState extends State<_PasswordDialog> {
  final _current = TextEditingController();
  final _next = TextEditingController();

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(
      widget.changing ? 'Change password' : 'Add email/password login',
    ),
    content: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (widget.changing) ...[
            TextField(
              key: const Key('current-password'),
              controller: _current,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Current password'),
            ),
            const SizedBox(height: 12),
          ],
          TextField(
            key: const Key('new-password'),
            controller: _next,
            obscureText: true,
            decoration: const InputDecoration(
              labelText: 'New password',
              helperText:
                  '12+ characters with upper/lowercase, number and symbol',
            ),
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
        key: const Key('confirm-password-action'),
        onPressed: () => Navigator.pop(
          context,
          widget.changing ? '${_current.text}\n${_next.text}' : _next.text,
        ),
        child: Text(widget.changing ? 'Change password' : 'Send verification'),
      ),
    ],
  );
}

class _PhoneVerificationDialog extends StatefulWidget {
  const _PhoneVerificationDialog({required this.maskedPhone});

  final String maskedPhone;

  @override
  State<_PhoneVerificationDialog> createState() =>
      _PhoneVerificationDialogState();
}

class _PhoneVerificationDialogState extends State<_PhoneVerificationDialog> {
  final _phoneController = TextEditingController();
  final _smsCodeController = TextEditingController();
  final _manualTokenController = TextEditingController();

  String? _verificationId;
  int? _resendToken;
  bool _sendingCode = false;
  bool _verifyingCode = false;
  String? _statusMessage;
  String? _errorMessage;
  int _activeRequestId = 0;
  bool _isCancelled = false;
  Timer? _watchdogTimer;

  @override
  void dispose() {
    _isCancelled = true;
    _watchdogTimer?.cancel();
    _phoneController.dispose();
    _smsCodeController.dispose();
    _manualTokenController.dispose();
    super.dispose();
  }

  bool get _isFirebaseAvailable {
    try {
      return Firebase.apps.isNotEmpty;
    } on Object {
      return false;
    }
  }

  Future<void> _sendCode() async {
    final phone = _phoneController.text.trim();
    if (!RegExp(r'^\+[1-9]\d{7,14}$').hasMatch(phone)) {
      setState(() => _errorMessage = 'Use E.164 format with country code (e.g. +919876543210).');
      return;
    }

    if (!_isFirebaseAvailable) {
      setState(() {
        _statusMessage = 'Firebase not initialized on this platform. Enter test proof token below.';
        _errorMessage = null;
      });
      return;
    }

    final requestId = ++_activeRequestId;
    _watchdogTimer?.cancel();

    setState(() {
      _sendingCode = true;
      _errorMessage = null;
      _statusMessage = 'Contacting Firebase verification service…';
    });

    // Reconciled UI watchdog (60s > 30s SDK timeout): ensures cancellation safety and prevents indefinite hang
    _watchdogTimer = Timer(const Duration(seconds: 60), () {
      if (!mounted || _isCancelled || _activeRequestId != requestId) return;
      if (_sendingCode && _verificationId == null) {
        debugPrint('PHONE_VERIFY_TIMEOUT');
        setState(() {
          _sendingCode = false;
          _errorMessage = 'Verification request timed out. Please try again.';
        });
      }
    });

    try {
      debugPrint('PHONE_VERIFY_REQUESTED');
      await fb_auth.FirebaseAuth.instance.verifyPhoneNumber(
        phoneNumber: phone,
        timeout: const Duration(seconds: 30),
        forceResendingToken: _resendToken,
        verificationCompleted: (fb_auth.PhoneAuthCredential credential) async {
          debugPrint('PHONE_AUTO_VERIFIED');
          _watchdogTimer?.cancel();
          if (!mounted || _isCancelled || _activeRequestId != requestId) return;
          await _signInWithCredential(phone, credential, requestId);
        },
        verificationFailed: (fb_auth.FirebaseAuthException e) {
          debugPrint('PHONE_VERIFY_FAILED');
          _watchdogTimer?.cancel();
          if (!mounted || _isCancelled || _activeRequestId != requestId) return;
          setState(() {
            _sendingCode = false;
            _errorMessage = e.message ?? 'Phone verification failed (${e.code}).';
          });
        },
        codeSent: (String verificationId, int? resendToken) {
          debugPrint('PHONE_CODE_SENT');
          _watchdogTimer?.cancel();
          if (!mounted || _isCancelled || _activeRequestId != requestId) return;
          setState(() {
            _verificationId = verificationId;
            _resendToken = resendToken;
            _sendingCode = false;
            _statusMessage = 'Enter the 6-digit verification code:';
          });
        },
        codeAutoRetrievalTimeout: (String verificationId) {
          debugPrint('PHONE_VERIFY_TIMEOUT');
          _watchdogTimer?.cancel();
          if (!mounted || _isCancelled || _activeRequestId != requestId) return;
          setState(() {
            _verificationId = verificationId;
            _sendingCode = false;
            _statusMessage = 'Enter the 6-digit verification code:';
          });
        },
      );
    } on Object {
      debugPrint('PHONE_VERIFY_FAILED');
      _watchdogTimer?.cancel();
      if (!mounted || _isCancelled || _activeRequestId != requestId) return;
      setState(() {
        _sendingCode = false;
        _errorMessage = 'Phone verification failed. Please try again.';
      });
    }
  }

  Future<void> _verifySmsCode() async {
    final phone = _phoneController.text.trim();
    final smsCode = _smsCodeController.text.trim();
    if (_verificationId == null || smsCode.length < 6) return;

    final credential = fb_auth.PhoneAuthProvider.credential(
      verificationId: _verificationId!,
      smsCode: smsCode,
    );
    await _signInWithCredential(phone, credential, _activeRequestId);
  }

  Future<void> _signInWithCredential(
    String phone,
    fb_auth.PhoneAuthCredential credential,
    int requestId,
  ) async {
    if (!mounted || _isCancelled || _activeRequestId != requestId) return;
    setState(() {
      _verifyingCode = true;
      _errorMessage = null;
    });
    try {
      final userCredential =
          await fb_auth.FirebaseAuth.instance.signInWithCredential(credential);
      final idToken = await userCredential.user?.getIdToken();
      if (idToken == null || idToken.isEmpty) {
        throw Exception('Firebase did not issue an ID token.');
      }
      if (mounted && !_isCancelled && _activeRequestId == requestId) {
        Navigator.pop(context, {'phone': phone, 'token': idToken});
      }
    } on fb_auth.FirebaseAuthException catch (e) {
      if (mounted && !_isCancelled && _activeRequestId == requestId) {
        setState(() {
          _verifyingCode = false;
          _errorMessage = e.message ?? 'Verification failed (${e.code}).';
        });
      }
    } on Object {
      if (mounted && !_isCancelled && _activeRequestId == requestId) {
        setState(() {
          _verifyingCode = false;
          _errorMessage = 'Verification failed. Please try again.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Verify phone number'),
    content: SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Confirm your full E.164 phone number (${widget.maskedPhone}).',
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('verify-phone-number-input'),
            controller: _phoneController,
            keyboardType: TextInputType.phone,
            decoration: const InputDecoration(
              labelText: 'Phone number (E.164)',
              hintText: '+919876543210',
            ),
          ),
          const SizedBox(height: 12),
          if (_verificationId == null) ...[
            SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                key: const Key('send-phone-code-btn'),
                onPressed: _sendingCode ? null : _sendCode,
                child: Text(_sendingCode ? 'Sending code…' : 'Send verification code'),
              ),
            ),
          ],
          if (_verificationId != null) ...[
            TextField(
              key: const Key('verify-sms-code-input'),
              controller: _smsCodeController,
              keyboardType: TextInputType.number,
              maxLength: 6,
              decoration: const InputDecoration(
                labelText: 'SMS Code',
                hintText: '6-digit code',
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                key: const Key('submit-sms-code-btn'),
                onPressed: _verifyingCode ? null : _verifySmsCode,
                child: Text(_verifyingCode ? 'Verifying…' : 'Confirm SMS code'),
              ),
            ),
          ],
          if (!_isFirebaseAvailable) ...[
            const SizedBox(height: 16),
            const Divider(),
            const Text(
              'Or enter verification proof token directly (testing / QA):',
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
            const SizedBox(height: 8),
            TextField(
              key: const Key('verify-phone-token-input'),
              controller: _manualTokenController,
              decoration: const InputDecoration(
                labelText: 'Direct token proof',
                hintText: 'Enter test proof token or Firebase ID token',
              ),
            ),
          ],
          if (_statusMessage != null) ...[
            const SizedBox(height: 8),
            Text(
              _statusMessage!,
              style: TextStyle(color: Theme.of(context).colorScheme.primary, fontSize: 13),
            ),
          ],
          if (_errorMessage != null) ...[
            const SizedBox(height: 8),
            Text(
              _errorMessage!,
              style: TextStyle(color: Theme.of(context).colorScheme.error, fontSize: 13),
            ),
          ],
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () {
          _isCancelled = true;
          _watchdogTimer?.cancel();
          debugPrint('PHONE_VERIFY_CANCELLED');
          Navigator.pop(context);
        },
        child: const Text('Cancel'),
      ),
      if (!_isFirebaseAvailable)
        FilledButton(
          key: const Key('submit-phone-verification-btn'),
          onPressed: () {
            final phone = _phoneController.text.trim();
            final manualToken = _manualTokenController.text.trim();
            if (phone.isEmpty || manualToken.isEmpty) return;
            Navigator.pop(context, {'phone': phone, 'token': manualToken});
          },
          child: const Text('Verify & link'),
        ),
    ],
  );
}

