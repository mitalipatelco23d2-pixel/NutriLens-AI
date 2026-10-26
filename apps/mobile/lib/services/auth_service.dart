import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:google_sign_in/google_sign_in.dart';

import 'api_client.dart';

class AuthenticatedUser {
  const AuthenticatedUser({
    required this.id,
    required this.email,
    required this.name,
    required this.plan,
    required this.subscriptionStatus,
    required this.entitlements,
    required this.hasGoogleIdentity,
    this.avatarUrl,
  });

  factory AuthenticatedUser.fromJson(Map<String, dynamic> json) {
    return AuthenticatedUser(
      id: json['id'] as String,
      hasGoogleIdentity: json['has_google_identity'] == true,
      email: json['email'] as String,
      name: json['name'] as String,
      avatarUrl: json['avatar_url'] as String?,
      plan: json['plan']?.toString() ?? 'FREE',
      subscriptionStatus: json['subscription_status']?.toString() ?? 'FREE',
      entitlements: Map<String, dynamic>.from(
        json['entitlements'] as Map<String, dynamic>? ?? const {},
      ),
    );
  }

  final String id;
  final String email;
  final String name;
  final String? avatarUrl;
  final String plan;
  final String subscriptionStatus;
  final Map<String, dynamic> entitlements;
  final bool hasGoogleIdentity;
}

class AuthSession {
  const AuthSession({required this.accessToken, required this.user});

  final String accessToken;
  final AuthenticatedUser user;
}

abstract interface class CredentialGateway {
  Future<String> authenticate();
  Future<void> signOut();
}

class GoogleCredentialGateway implements CredentialGateway {
  GoogleCredentialGateway({this.clientId, this.serverClientId});

  final String? clientId;
  final String? serverClientId;
  Future<void>? _initialization;

  Future<void> _initialize() {
    if (serverClientId == null || serverClientId!.trim().isEmpty) {
      throw const ApiException(
        'Google sign-in is not configured on this device.',
      );
    }
    return _initialization ??= GoogleSignIn.instance
        .initialize(clientId: clientId, serverClientId: serverClientId);
  }

  @override
  Future<String> authenticate() async {
    await _initialize();
    if (!GoogleSignIn.instance.supportsAuthenticate()) {
      throw const ApiException(
        'Google sign-in on web requires the Google-rendered button.',
      );
    }
    final GoogleSignInAccount account;
    try {
      account = await GoogleSignIn.instance.authenticate();
    } on PlatformException catch (e) {
      final code = e.code.toLowerCase();
      final message = (e.message ?? '').toLowerCase();
      if (code == 'sign_in_canceled' ||
          code == 'canceled' ||
          message.contains('cancel')) {
        throw const ApiException('Google sign-in was cancelled.');
      }
      debugPrint('Google Sign-In PlatformException: ${e.code} ${e.message}');
      throw const ApiException(
        'Google sign-in could not be completed. Please try again or use email sign-in.',
      );
    } catch (e) {
      if (e is ApiException) rethrow;
      debugPrint('Google Sign-In error: $e');
      throw const ApiException(
        'Google sign-in could not be completed. Please try again or use email sign-in.',
      );
    }
    final token = account.authentication.idToken;
    if (token == null || token.isEmpty) {
      throw const ApiException('Google did not return an identity token.');
    }
    return token;
  }

  @override
  Future<void> signOut() async {
    if (serverClientId == null || serverClientId!.trim().isEmpty) {
      return;
    }
    try {
      await _initialize();
      await GoogleSignIn.instance.signOut();
    } catch (e) {
      debugPrint('Google Sign-In signOut warning: $e');
    }
  }
}

abstract interface class SessionStore {
  Future<String?> read();
  Future<void> write(String token);
  Future<void> clear();
}

class SecureSessionStore implements SessionStore {
  const SecureSessionStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'nutrilens_access_token';
  final FlutterSecureStorage _storage;

  @override
  Future<String?> read() => _storage.read(key: _key);

  @override
  Future<void> write(String token) => _storage.write(key: _key, value: token);

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

class SessionController extends ChangeNotifier {
  SessionController({
    required this.baseUrl,
    required this.credentials,
    required this.store,
    this.onSignedOut,
    ApiClient? publicClient,
    ApiClient? authorizedClient,
  })  : _publicClient = publicClient ?? ApiClient(baseUrl: baseUrl),
        _providedAuthorizedClient = authorizedClient;

  final String baseUrl;
  final CredentialGateway credentials;
  final SessionStore store;
  final Future<void> Function()? onSignedOut;
  final ApiClient _publicClient;
  final ApiClient? _providedAuthorizedClient;

  Timer? _expiryTimer;
  String? _accessToken;
  AuthenticatedUser? _user;
  bool _loading = true;
  bool _restoring = false;
  String? _error;

  String? get accessToken => _accessToken;
  AuthenticatedUser? get user => _user;
  bool get loading => _loading;
  bool get restoring => _restoring;
  bool get isAuthenticated => _accessToken != null && _user != null;
  String? get error => _error;
  bool _isSigningOut = false;

  ApiClient get authorizedClient =>
      _providedAuthorizedClient ??
      ApiClient(
        baseUrl: baseUrl,
        accessToken: () => _accessToken,
        onUnauthorized: () {
          handleSessionExpired();
        },
      );

  void handleSessionExpired({String reason = 'Your session expired. Please sign in again.'}) {
    if (_isSigningOut) return;
    if (_accessToken == null && _user == null) {
      if (_error != reason) {
        _error = reason;
        notifyListeners();
      }
      return;
    }
    _isSigningOut = true;
    _expiryTimer?.cancel();
    final previousToken = _accessToken;
    _accessToken = null;
    _user = null;
    _loading = false;
    _restoring = false;
    _error = reason;
    notifyListeners();

    unawaited(() async {
      try {
        if (previousToken != null) {
          try {
            await authorizedClient.post('/api/v1/auth/logout');
          } on Object {
            // Server logout best-effort
          }
        }
        try {
          await store.clear();
        } on Object {
          // Clear store best-effort
        }
        try {
          await onSignedOut?.call();
        } on Object {
          // Signout hook best-effort
        }
        try {
          await credentials.signOut();
        } on Object {
          // Credentials signOut best-effort
        }
      } finally {
        _isSigningOut = false;
      }
    }());
  }

  Future<void> restore() async {
    _restoring = true;
    _setLoading(true);
    final saved = await store.read();
    if (saved == null) {
      _restoring = false;
      _setLoading(false);
      return;
    }
    _accessToken = saved;
    try {
      _user = await _fetchMe();
      await refreshSession();
      _error = null;
    } on Object {
      await store.clear();
      await onSignedOut?.call();
      _accessToken = null;
      _user = null;
    } finally {
      _restoring = false;
      _setLoading(false);
    }
  }

  void clearError() {
    if (_error != null) {
      _error = null;
      notifyListeners();
    }
  }

  static String userFriendlyErrorMessage(Object error) {
    if (error is ApiException) {
      return error.message;
    }
    final msg = error.toString();
    final lower = msg.toLowerCase();
    if (lower.contains('timeoutexception') || lower.contains('timeout')) {
      return 'The server took too long to respond. Please check your connection and try again.';
    }
    if (lower.contains('socketexception') ||
        lower.contains('clientexception') ||
        lower.contains('connection refused') ||
        lower.contains('failed host lookup') ||
        lower.contains('network is unreachable')) {
      return "We couldn't reach NutriLens right now. Check your connection and try again.";
    }
    if (lower.contains('serverclientid must be provided')) {
      return 'Google sign-in is not configured on this device.';
    }
    if (msg.startsWith('Exception: ')) {
      return msg.substring(11);
    }
    return msg;
  }

  Future<void> signIn() async {
    _setLoading(true);
    try {
      final credential = await credentials.authenticate();
      final payload = await _publicClient.post(
        '/api/v1/auth/google',
        body: {'credential': credential},
      );
      await _establishSession(payload);
      _error = null;
    } on Object catch (error) {
      _error = userFriendlyErrorMessage(error);
    } finally {
      _setLoading(false);
    }
  }

  Future<void> signInWithEmail({
    required String email,
    required String password,
  }) async {
    _setLoading(true);
    try {
      final payload = await _publicClient.post(
        '/api/v1/auth/email/login',
        body: {'email': email, 'password': password},
      );
      await _establishSession(payload);
      _error = null;
    } on Object catch (error) {
      _error = userFriendlyErrorMessage(error);
    } finally {
      _setLoading(false);
    }
  }

  Future<void> signInWithPhone({
    required String phone,
    required String firebaseIdToken,
  }) async {
    _setLoading(true);
    try {
      final payload = await _publicClient.post(
        '/api/v1/auth/phone/verify',
        body: {'phone': phone, 'firebase_id_token': firebaseIdToken},
      );
      await _establishSession(payload);
      _error = null;
    } on Object catch (error) {
      _error = userFriendlyErrorMessage(error);
      rethrow;
    } finally {
      _setLoading(false);
    }
  }

  Future<void> signInWithDemoUser() async {
    _setLoading(true);
    try {
      final payload = await _publicClient.post('/api/v1/auth/demo/login');
      await _establishSession(payload);
      _error = null;
    } on Object catch (error) {
      _error = userFriendlyErrorMessage(error);
    } finally {
      _setLoading(false);
    }
  }

  Future<String> signUpWithEmail({
    required String name,
    required String email,
    required String password,
    required bool acceptedTerms,
    required bool acceptedPrivacy,
  }) async {
    try {
      final payload = await _publicClient.post(
        '/api/v1/auth/email/signup',
        body: {
          'name': name,
          'email': email,
          'password': password,
          'accepted_terms': acceptedTerms,
          'accepted_privacy': acceptedPrivacy,
        },
      );
      final json = payload as Map<String, dynamic>;
      return json['message']?.toString() ??
          'Check your inbox to verify your email.';
    } on Object catch (error) {
      throw ApiException(userFriendlyErrorMessage(error));
    }
  }

  Future<void> verifyEmailOtp({
    required String email,
    required String otp,
  }) async {
    _setLoading(true);
    try {
      final payload = await _publicClient.post(
        '/api/v1/auth/email/otp/verify',
        body: {'email': email, 'otp': otp},
      );
      await _establishSession(payload);
      _error = null;
    } on Object catch (error) {
      final friendly = userFriendlyErrorMessage(error);
      _error = friendly;
      throw ApiException(friendly);
    } finally {
      _setLoading(false);
    }
  }

  Future<String> requestEmailOtp(String email) async {
    try {
      final payload = await _publicClient.post(
        '/api/v1/auth/email/otp/request',
        body: {'email': email},
      );
      final json = payload as Map<String, dynamic>;
      return json['message']?.toString() ??
          'A new verification code has been sent to your email.';
    } on Object catch (error) {
      throw ApiException(userFriendlyErrorMessage(error));
    }
  }

  Future<String> requestPasswordReset(String email) async {
    try {
      final payload = await _publicClient.post(
        '/api/v1/auth/password/forgot',
        body: {'email': email},
      );
      final json = payload as Map<String, dynamic>;
      return json['message']?.toString() ??
          'Check your inbox for a reset link.';
    } on Object catch (error) {
      throw ApiException(userFriendlyErrorMessage(error));
    }
  }

  Future<String> acquireGoogleCredential() => credentials.authenticate();

  Future<void> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final payload = await authorizedClient.post(
      '/api/v1/auth/password/change',
      body: {'current_password': currentPassword, 'new_password': newPassword},
    );
    await _establishSession(payload);
    _error = null;
    notifyListeners();
  }

  Future<void> refreshSession() async {
    final payload = await authorizedClient.post('/api/v1/auth/session/refresh');
    await _establishSession(payload);
  }

  Future<void> refreshUser() async {
    _user = await _fetchMe();
    notifyListeners();
  }

  Future<void> signOut({String? reason}) async {
    if (_isSigningOut) return;
    _isSigningOut = true;
    _expiryTimer?.cancel();
    var localCleanupFailed = false;
    try {
      if (_accessToken != null) {
        await authorizedClient.post('/api/v1/auth/logout');
      }
    } on Object {
      // Local credential removal still completes if the server is unavailable.
    }
    try {
      await store.clear();
    } on Object {
      localCleanupFailed = true;
    }
    try {
      await onSignedOut?.call();
    } on Object {
      localCleanupFailed = true;
    }
    try {
      await credentials.signOut();
    } on Object {
      localCleanupFailed = true;
    }
    _accessToken = null;
    _user = null;
    _error = reason ??
        (localCleanupFailed
            ? 'Signed out, but some device cleanup could not be completed.'
            : null);
    _isSigningOut = false;
    notifyListeners();
  }

  Future<AuthenticatedUser> _fetchMe() async {
    final payload = await authorizedClient.get('/api/v1/auth/me');
    return AuthenticatedUser.fromJson(payload as Map<String, dynamic>);
  }

  Future<void> _establishSession(Object? payload) async {
    final json = payload as Map<String, dynamic>;
    _accessToken = json['access_token'] as String;
    _user = AuthenticatedUser.fromJson(json['user'] as Map<String, dynamic>);
    await store.write(_accessToken!);
    _expiryTimer?.cancel();
    final lifetime = json['expires_in_seconds'];
    if (lifetime is num && lifetime.isFinite && lifetime > 0) {
      final token = _accessToken!;
      _expiryTimer = Timer(
        Duration(milliseconds: (lifetime * 1000).floor()),
        () => unawaited(_expireSession(token)),
      );
    }
  }

  Future<void> _expireSession(String token) async {
    if (_accessToken != token) return;
    handleSessionExpired(reason: 'Your session expired. Please sign in again.');
  }

  @override
  void dispose() {
    _expiryTimer?.cancel();
    super.dispose();
  }

  void _setLoading(bool value) {
    _loading = value;
    notifyListeners();
  }
}
