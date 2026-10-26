import 'dart:async';

import 'package:flutter/material.dart';

import 'account_profile_screen.dart';
import 'authenticated_shell.dart';
import 'config/app_config.dart';
import 'scanner_screen.dart';
import 'services/api_client.dart';
import 'services/auth_service.dart';
import 'services/health_api.dart';
import 'services/health_connect.dart';
import 'services/intelligence_api.dart';
import 'services/local_reminders.dart';
import 'services/product_api.dart';
import 'services/scan_api.dart';
import 'package:firebase_core/firebase_core.dart';
import 'services/client_inference.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    await Firebase.initializeApp();
  } catch (_) {
    // Allows execution in unit tests or platforms without native Firebase setup
  }
  final config = AppConfig.fromEnvironment();
  const scanCache = SecureScanResultCache();
  final localReminders = LocalReminderCoordinator();
  final healthConnect = HealthConnectCoordinator();
  final session = SessionController(
    baseUrl: config.apiBaseUrl,
    credentials: GoogleCredentialGateway(
      clientId: config.effectiveGoogleClientId,
      serverClientId: config.effectiveGoogleServerClientId,
    ),
    store: const SecureSessionStore(),
    onSignedOut: () async {
      await scanCache.clear();
      try {
        await localReminders.signOut();
      } on Object {
        // A local notification cleanup failure must never block account sign-out.
      }
    },
  );
  final authorizedClient = ApiClient(
    baseUrl: config.apiBaseUrl,
    accessToken: () => session.accessToken,
    onUnauthorized: session.handleSessionExpired,
  );
  runApp(
    NutriLensApp(
      config: config,
      healthGateway: HealthApi(baseUrl: config.apiBaseUrl),
      scanGateway: ScanApi(
        baseUrl: config.apiBaseUrl,
        accessToken: () => session.accessToken,
        userId: () => session.user?.id,
        cache: scanCache,
        onUnauthorized: session.handleSessionExpired,
      ),
      sessionController: session,
      productGateway: ProductApi(authorizedClient),
      intelligenceGateway: IntelligenceApi(authorizedClient),
      clientEvidenceGateway: ClientEvidenceApi(authorizedClient),
      localReminders: localReminders,
      healthConnect: healthConnect,
    ),
  );
}

class NutriLensApp extends StatelessWidget {
  const NutriLensApp({
    required this.config,
    required this.healthGateway,
    required this.scanGateway,
    this.sessionController,
    this.productGateway,
    this.intelligenceGateway,
    this.clientEvidenceGateway,
    this.localReminders,
    this.healthConnect,
    super.key,
  });

  final AppConfig config;
  final HealthGateway healthGateway;
  final ScanGateway scanGateway;
  final SessionController? sessionController;
  final ProductGateway? productGateway;
  final IntelligenceGateway? intelligenceGateway;
  final ClientEvidenceGateway? clientEvidenceGateway;
  final LocalReminderCoordinator? localReminders;
  final HealthConnectCoordinator? healthConnect;

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF08785C);
    return MaterialApp(
      title: 'NutriLens X',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        scaffoldBackgroundColor: const Color(0xFFF5F8F4),
        useMaterial3: true,
      ),
      home: sessionController == null || productGateway == null
          ? FoundationShell(
              config: config,
              healthGateway: healthGateway,
              scanGateway: scanGateway,
            )
          : _SessionRoot(
              config: config,
              session: sessionController!,
              products: productGateway!,
              scanGateway: scanGateway,
              intelligenceGateway: intelligenceGateway,
              clientEvidenceGateway: clientEvidenceGateway,
              localReminders: localReminders,
              healthConnect: healthConnect,
            ),
    );
  }
}

class _SessionRoot extends StatefulWidget {
  const _SessionRoot({
    required this.config,
    required this.session,
    required this.products,
    required this.scanGateway,
    this.intelligenceGateway,
    this.clientEvidenceGateway,
    this.localReminders,
    this.healthConnect,
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
  State<_SessionRoot> createState() => _SessionRootState();
}

class _SessionRootState extends State<_SessionRoot> {
  String? _profileOwnerId;
  Future<AccountProfile>? _accountProfile;

  @override
  void initState() {
    super.initState();
    widget.session.addListener(_changed);
    widget.session.restore();
  }

  @override
  void dispose() {
    widget.session.removeListener(_changed);
    super.dispose();
  }

  void _changed() {
    if (!widget.session.isAuthenticated) {
      final nav = Navigator.maybeOf(context);
      if (nav != null && nav.canPop()) {
        nav.popUntil((route) => route.isFirst);
      }
    }
    if (widget.session.user?.id != _profileOwnerId) {
      _profileOwnerId = null;
      _accountProfile = null;
    }
    if (mounted) setState(() {});
  }

  void _retryAccountProfile() {
    setState(() {
      _profileOwnerId = widget.session.user!.id;
      _accountProfile = widget.products.accountProfile();
    });
  }

  @override
  Widget build(BuildContext context) {
    if (widget.session.restoring) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!widget.session.isAuthenticated) {
      return _SignInScreen(
        environment: widget.config.displayEnvironment,
        session: widget.session,
        collegeDemoMode: widget.config.collegeDemoMode,
      );
    }
    final user = widget.session.user!;
    if (_profileOwnerId != user.id || _accountProfile == null) {
      _profileOwnerId = user.id;
      _accountProfile = widget.products.accountProfile();
    }
    return FutureBuilder<AccountProfile>(
      future: _accountProfile,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          return Scaffold(
            body: SafeArea(
              child: Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        'Could not load your private profile: ${snapshot.error}',
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 12),
                      FilledButton(
                        onPressed: _retryAccountProfile,
                        child: const Text('Retry'),
                      ),
                      TextButton(
                        onPressed: widget.session.signOut,
                        child: const Text('Sign out'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          );
        }
        if (!snapshot.hasData) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        if (!snapshot.data!.onboardingComplete) {
          return AccountProfileEditor(
            key: ValueKey('onboarding-${user.id}'),
            initial: snapshot.data!,
            email: user.email,
            hasGoogleIdentity: user.hasGoogleIdentity,
            products: widget.products,
            onboarding: true,
            onSignOut: widget.session.signOut,
            onSaved: (saved) async {
              await widget.session.refreshUser();
              if (mounted) {
                setState(() => _accountProfile = Future.value(saved));
              }
            },
          );
        }
        return AuthenticatedShell(
          key: ValueKey(user.id),
          config: widget.config,
          session: widget.session,
          products: widget.products,
          scanGateway: widget.scanGateway,
          intelligenceGateway: widget.intelligenceGateway,
          clientEvidenceGateway: widget.clientEvidenceGateway,
          localReminders: widget.localReminders,
          healthConnect: widget.healthConnect,
        );
      },
    );
  }
}

class _SignInScreen extends StatefulWidget {
  const _SignInScreen({
    required this.environment,
    required this.session,
    this.collegeDemoMode = false,
  });

  final String environment;
  final SessionController session;
  final bool collegeDemoMode;

  @override
  State<_SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<_SignInScreen> {
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _otp = TextEditingController();
  var _createAccount = false;
  var _submitting = false;
  var _submittingGoogle = false;
  var _submittingEmail = false;
  var _submittingDemo = false;
  var _acceptedTerms = false;
  String? _pendingVerificationEmail;
  var _resendCooldown = 0;
  Timer? _cooldownTimer;
  String? _notice;

  bool get _isBusy =>
      _submitting ||
      _submittingGoogle ||
      _submittingEmail ||
      _submittingDemo ||
      widget.session.loading;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    _otp.dispose();
    _cooldownTimer?.cancel();
    super.dispose();
  }

  void _startCooldownTimer() {
    _cooldownTimer?.cancel();
    _resendCooldown = 60;
    _cooldownTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) {
        timer.cancel();
        return;
      }
      setState(() {
        if (_resendCooldown > 0) {
          _resendCooldown--;
        } else {
          timer.cancel();
        }
      });
    });
  }

  void _changeEmail() {
    _cooldownTimer?.cancel();
    setState(() {
      _pendingVerificationEmail = null;
      _otp.clear();
      _notice = null;
    });
  }

  Future<void> _verifyOtp() async {
    final email = _pendingVerificationEmail;
    final code = _otp.text.trim();
    if (email == null || code.length != 6) return;
    if (_submitting || widget.session.loading) return;
    widget.session.clearError();
    setState(() {
      _submitting = true;
      _notice = null;
    });
    try {
      await widget.session.verifyEmailOtp(email: email, otp: code);
    } on Object catch (error) {
      if (mounted) setState(() => _notice = error.toString());
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _resendOtp() async {
    final email = _pendingVerificationEmail;
    if (email == null ||
        _resendCooldown > 0 ||
        _submitting ||
        widget.session.loading) {
      return;
    }
    setState(() {
      _submitting = true;
      _notice = null;
    });
    try {
      final msg = await widget.session.requestEmailOtp(email);
      if (mounted) {
        setState(() => _notice = msg);
        _startCooldownTimer();
      }
    } on Object catch (error) {
      if (mounted) setState(() => _notice = error.toString());
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _submitEmail() async {
    if (_isBusy) return;
    if (_createAccount && !_acceptedTerms) {
      setState(
        () => _notice =
            'Accept the Terms and Privacy Policy to create an account.',
      );
      return;
    }
    widget.session.clearError();
    setState(() {
      _submittingEmail = true;
      _notice = null;
    });
    try {
      if (_createAccount) {
        final message = await widget.session.signUpWithEmail(
          name: _name.text,
          email: _email.text,
          password: _password.text,
          acceptedTerms: _acceptedTerms,
          acceptedPrivacy: _acceptedTerms,
        );
        if (mounted) {
          setState(() {
            _pendingVerificationEmail = _email.text.trim();
            _notice = message;
          });
          _startCooldownTimer();
        }
      } else {
        await widget.session.signInWithEmail(
          email: _email.text,
          password: _password.text,
        );
      }
    } on Object catch (error) {
      if (mounted) setState(() => _notice = error.toString());
    } finally {
      if (mounted) setState(() => _submittingEmail = false);
    }
  }

  Future<void> _forgotPassword() async {
    if (_submitting || widget.session.loading) return;
    if (_email.text.trim().isEmpty) {
      setState(() => _notice = 'Enter your email address first.');
      return;
    }
    widget.session.clearError();
    setState(() {
      _submitting = true;
      _notice = null;
    });
    try {
      final message = await widget.session.requestPasswordReset(_email.text);
      if (mounted) setState(() => _notice = message);
    } on Object catch (error) {
      if (mounted) setState(() => _notice = error.toString());
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Widget _buildOtpVerification(BuildContext context, String email) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.mark_email_read_outlined,
                    size: 72,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                  const SizedBox(height: 18),
                  Text(
                    'Verify your email',
                    style: Theme.of(context).textTheme.headlineMedium,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 10),
                  Text(
                    'We sent a 6-digit verification code to\n$email',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  TextField(
                    key: const Key('otp-input'),
                    controller: _otp,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      fontSize: 24,
                      letterSpacing: 8,
                      fontWeight: FontWeight.bold,
                    ),
                    decoration: const InputDecoration(
                      border: OutlineInputBorder(),
                      labelText: 'Verification code',
                      counterText: '',
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      key: const Key('verify-otp-button'),
                      onPressed: _submitting || _otp.text.trim().length != 6
                          ? null
                          : _verifyOtp,
                      child: Text(_submitting ? 'Verifying…' : 'Verify code'),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      TextButton(
                        key: const Key('resend-otp-button'),
                        onPressed:
                            _resendCooldown > 0 || _submitting ? null : _resendOtp,
                        child: Text(
                          _resendCooldown > 0
                              ? 'Resend code in ${_resendCooldown}s'
                              : 'Resend code',
                        ),
                      ),
                    ],
                  ),
                  TextButton.icon(
                    key: const Key('change-email-button'),
                    onPressed: _submitting ? null : _changeEmail,
                    icon: const Icon(Icons.arrow_back, size: 18),
                    label: const Text('Back / Change email'),
                  ),
                  if (_notice != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text(
                        _notice!,
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.primary,
                        ),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_pendingVerificationEmail != null) {
      return _buildOtpVerification(context, _pendingVerificationEmail!);
    }
    return Scaffold(
    body: SafeArea(
      child: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(28),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 480),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.eco_outlined,
                  size: 72,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 18),
                Text(
                  'Understand what you’re really eating.',
                  style: Theme.of(context).textTheme.headlineMedium,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 10),
                const Text(
                  'Sign in to keep scans, diary, pantry, analytics, and subscription access synchronized.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 24),
                if (widget.session.error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      widget.session.error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                      textAlign: TextAlign.center,
                    ),
                  ),
                if (widget.collegeDemoMode) ...[
                  FilledButton.icon(
                    key: const Key('demo-sign-in'),
                    style: FilledButton.styleFrom(
                      backgroundColor: Theme.of(context).colorScheme.tertiary,
                      foregroundColor: Theme.of(context).colorScheme.onTertiary,
                    ),
                    onPressed: _isBusy
                        ? null
                        : () async {
                            setState(() {
                              _submittingDemo = true;
                              _notice = null;
                            });
                            widget.session.clearError();
                            try {
                              await widget.session.signInWithDemoUser();
                            } finally {
                              if (mounted) {
                                setState(() => _submittingDemo = false);
                              }
                            }
                          },
                    icon: _submittingDemo
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.school_outlined),
                    label: Text(
                      _submittingDemo
                          ? 'Starting demo session…'
                          : 'Continue as Demo User',
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                FilledButton.icon(
                  key: const Key('google-sign-in'),
                  onPressed: _isBusy
                      ? null
                      : () async {
                          setState(() {
                            _submittingGoogle = true;
                            _notice = null;
                          });
                          widget.session.clearError();
                          try {
                            await widget.session.signIn();
                          } finally {
                            if (mounted) {
                              setState(() => _submittingGoogle = false);
                            }
                          }
                        },
                  icon: _submittingGoogle
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.login),
                  label: Text(
                    _submittingGoogle
                        ? 'Signing in with Google…'
                        : 'Continue with Google',
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 18),
                  child: Row(
                    children: [
                      Expanded(child: Divider()),
                      Padding(
                        padding: EdgeInsets.symmetric(horizontal: 12),
                        child: Text('OR'),
                      ),
                      Expanded(child: Divider()),
                    ],
                  ),
                ),
                if (_createAccount) ...[
                  TextField(
                    controller: _name,
                    autofillHints: const [AutofillHints.name],
                    decoration: const InputDecoration(
                      border: OutlineInputBorder(),
                      labelText: 'Name',
                    ),
                  ),
                  const SizedBox(height: 12),
                ],
                TextField(
                  controller: _email,
                  keyboardType: TextInputType.emailAddress,
                  autofillHints: const [AutofillHints.email],
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    labelText: 'Email address',
                  ),
                ),
                if (_createAccount)
                  CheckboxListTile(
                    key: const Key('signup-terms'),
                    contentPadding: EdgeInsets.zero,
                    title: const Text(
                      'I agree to the Terms and Privacy Policy',
                    ),
                    value: _acceptedTerms,
                    onChanged: _isBusy
                        ? null
                        : (value) =>
                              setState(() => _acceptedTerms = value ?? false),
                  ),
                const SizedBox(height: 12),
                TextField(
                  controller: _password,
                  obscureText: true,
                  autofillHints: [
                    _createAccount
                        ? AutofillHints.newPassword
                        : AutofillHints.password,
                  ],
                  decoration: const InputDecoration(
                    border: OutlineInputBorder(),
                    labelText: 'Password',
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    key: const Key('submit-email-button'),
                    onPressed: _isBusy ? null : _submitEmail,
                    child: _submittingEmail
                        ? Row(
                            mainAxisAlignment: MainAxisAlignment.center,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              ),
                              const SizedBox(width: 8),
                              Text(
                                _createAccount
                                    ? 'Creating account…'
                                    : 'Signing in…',
                              ),
                            ],
                          )
                        : Text(
                            _createAccount ? 'Create account' : 'Sign in',
                          ),
                  ),
                ),
                if (!_createAccount)
                  TextButton(
                    key: const Key('forgot-password-button'),
                    onPressed: _isBusy ? null : _forgotPassword,
                    child: const Text('Forgot password?'),
                  ),
                TextButton(
                  key: const Key('toggle-auth-mode-button'),
                  onPressed: _isBusy
                      ? null
                      : () => setState(() {
                          _createAccount = !_createAccount;
                          _notice = null;
                          widget.session.clearError();
                        }),
                  child: Text(
                    _createAccount
                        ? 'Already have an account? Sign in'
                        : 'New here? Create account',
                  ),
                ),
                if (_notice != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Text(_notice!, textAlign: TextAlign.center),
                  ),
                const SizedBox(height: 16),
                Text(
                  'Wellness guidance only',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
  }
}

class FoundationShell extends StatefulWidget {
  const FoundationShell({
    required this.config,
    required this.healthGateway,
    required this.scanGateway,
    super.key,
  });

  final AppConfig config;
  final HealthGateway healthGateway;
  final ScanGateway scanGateway;

  @override
  State<FoundationShell> createState() => _FoundationShellState();
}

class _FoundationShellState extends State<FoundationShell> {
  var _selectedIndex = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('NutriLens X'), centerTitle: false),
      body: IndexedStack(
        index: _selectedIndex,
        children: [
          _FoundationOverview(environment: widget.config.displayEnvironment),
          ScannerScreen(scanGateway: widget.scanGateway),
          const _InsightsScreen(),
          const _PantryScreen(),
          HealthScreen(
            environment: widget.config.displayEnvironment,
            healthGateway: widget.healthGateway,
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (index) =>
            setState(() => _selectedIndex = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: 'Overview',
          ),
          NavigationDestination(
            icon: Icon(Icons.document_scanner_outlined),
            selectedIcon: Icon(Icons.document_scanner),
            label: 'Scan food',
          ),
          NavigationDestination(
            icon: Icon(Icons.insights_outlined),
            selectedIcon: Icon(Icons.insights),
            label: 'Insights',
          ),
          NavigationDestination(
            icon: Icon(Icons.kitchen_outlined),
            selectedIcon: Icon(Icons.kitchen),
            label: 'Pantry',
          ),
          NavigationDestination(
            icon: Icon(Icons.monitor_heart_outlined),
            selectedIcon: Icon(Icons.monitor_heart),
            label: 'System health',
          ),
        ],
      ),
    );
  }
}

class _FoundationOverview extends StatelessWidget {
  const _FoundationOverview({required this.environment});

  final String environment;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.eco_outlined,
              size: 64,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 16),
            Text(
              'Understand what you’re really eating.',
              style: Theme.of(context).textTheme.headlineSmall,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text('Environment: $environment'),
            const SizedBox(height: 8),
            const Text(
              'Scan a label for structured food evidence, then review nutrition and ingredient signals without medical overclaim.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 20),
            const Wrap(
              spacing: 8,
              runSpacing: 8,
              alignment: WrapAlignment.center,
              children: [
                Chip(label: Text('Explainable results')),
                Chip(label: Text('Raw images not retained')),
                Chip(label: Text('Wellness guidance only')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _InsightsScreen extends StatelessWidget {
  const _InsightsScreen();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          'Nutrition insights',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 8),
        const Text(
          'Authenticated diary trends will appear here after mobile sign-in is configured.',
        ),
        const SizedBox(height: 18),
        for (final item in const [
          (
            'Daily energy',
            'Add diary entries to calculate a trend.',
            Icons.bolt_outlined,
          ),
          ('Protein', 'No logged evidence yet.', Icons.fitness_center_outlined),
          ('Sodium', 'No logged evidence yet.', Icons.water_drop_outlined),
        ])
          Card(
            child: ListTile(
              leading: Icon(item.$3),
              title: Text(item.$1),
              subtitle: Text(item.$2),
            ),
          ),
      ],
    );
  }
}

class _PantryScreen extends StatelessWidget {
  const _PantryScreen();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text('Smart pantry', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 8),
        const Text(
          'Pantry inventory sync requires mobile Google sign-in. The web account remains the durable source of truth.',
        ),
        const SizedBox(height: 18),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(22),
            child: Column(
              children: [
                Icon(
                  Icons.inventory_2_outlined,
                  size: 52,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 12),
                const Text('No synced pantry items'),
                const SizedBox(height: 6),
                const Text(
                  'Use the web dashboard until authenticated mobile sync is enabled.',
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class HealthScreen extends StatefulWidget {
  const HealthScreen({
    required this.environment,
    required this.healthGateway,
    super.key,
  });

  final String environment;
  final HealthGateway healthGateway;

  @override
  State<HealthScreen> createState() => _HealthScreenState();
}

class _HealthScreenState extends State<HealthScreen> {
  HealthSnapshot? _snapshot;
  String? _error;
  var _loading = true;

  @override
  void initState() {
    super.initState();
    _loadHealth();
  }

  Future<void> _loadHealth() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final snapshot = await widget.healthGateway.fetchHealth();
      if (!mounted) return;
      setState(() => _snapshot = snapshot);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _snapshot = null;
        _error = error.toString();
      });
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final snapshot = _snapshot;
    final connected = snapshot?.isHealthy ?? false;
    final statusLabel = _loading
        ? 'Checking'
        : _error != null
        ? 'Unavailable'
        : connected
        ? 'Connected'
        : 'Degraded';

    return ListView(
      padding: const EdgeInsets.all(24),
      children: [
        Text(
          'System health',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Backend: $statusLabel', key: const Key('backend-status')),
                const SizedBox(height: 8),
                Text('Environment: ${widget.environment}'),
                if (_loading) ...[
                  const SizedBox(height: 16),
                  const LinearProgressIndicator(),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 16),
                  Text(
                    'Could not reach the backend. Check the API URL and try again.',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        if (snapshot != null) ...[
          const SizedBox(height: 16),
          ...snapshot.services.entries.map(
            (entry) => ListTile(
              leading: Icon(
                entry.value == 'healthy' ? Icons.check_circle : Icons.warning,
                color: entry.value == 'healthy'
                    ? Colors.green
                    : Theme.of(context).colorScheme.error,
              ),
              title: Text(entry.key),
              trailing: Text(entry.value),
            ),
          ),
        ],
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: _loading ? null : _loadHealth,
          icon: const Icon(Icons.refresh),
          label: const Text('Retry'),
        ),
      ],
    );
  }
}
