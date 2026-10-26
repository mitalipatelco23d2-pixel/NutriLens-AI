import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/auth_service.dart';

class _Credentials implements CredentialGateway {
  var signedOut = false;
  var failSignOut = false;

  @override
  Future<String> authenticate() async => 'google-id-token';

  @override
  Future<void> signOut() async {
    signedOut = true;
    if (failSignOut) throw StateError('credential cleanup failed');
  }
}

class _Store implements SessionStore {
  String? value;

  @override
  Future<void> clear() async => value = null;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String token) async => value = token;
}

void main() {
  testWidgets('expired session removes credentials and private state', (
    tester,
  ) async {
    final store = _Store();
    var cleanupCalls = 0;
    final session = SessionController(
      baseUrl: 'https://api.example',
      credentials: _Credentials(),
      store: store,
      onSignedOut: () async => cleanupCalls++,
      publicClient: ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient(
          (_) async =>
              http.Response(_sessionResponse.replaceFirst('3600', '2'), 200),
        ),
      ),
    );
    await session.signIn();
    await tester.pump(const Duration(seconds: 1));
    expect(session.isAuthenticated, isTrue);
    await tester.pump(const Duration(seconds: 1));
    expect(session.isAuthenticated, isFalse);
    expect(store.value, isNull);
    expect(cleanupCalls, 1);
    expect(session.error, contains('session expired'));
    session.dispose();
  });

  testWidgets('a new login replaces the old expiry deadline', (tester) async {
    final store = _Store();
    var calls = 0;
    final session = SessionController(
      baseUrl: 'https://api.example',
      credentials: _Credentials(),
      store: store,
      publicClient: ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((_) async {
          calls++;
          return http.Response(
            _sessionResponse
                .replaceFirst('3600', '2')
                .replaceFirst('backend-session', 'session-$calls'),
            200,
          );
        }),
      ),
    );
    await session.signIn();
    await tester.pump(const Duration(seconds: 1));
    await session.signIn();
    await tester.pump(const Duration(seconds: 1));
    expect(session.isAuthenticated, isTrue);
    expect(store.value, 'session-2');
    await tester.pump(const Duration(seconds: 1));
    expect(session.isAuthenticated, isFalse);
    session.dispose();
  });

  test(
    'exchanges Google identity and persists only the backend session',
    () async {
      final store = _Store();
      final credentials = _Credentials();
      var privateCacheCleared = false;
      final publicClient = ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/auth/google');
          expect(request.body, '{"credential":"google-id-token"}');
          return http.Response(_sessionResponse, 200);
        }),
      );
      final session = SessionController(
        baseUrl: 'https://api.example',
        credentials: credentials,
        store: store,
        publicClient: publicClient,
        onSignedOut: () async => privateCacheCleared = true,
      );

      await session.signIn();

      expect(session.isAuthenticated, isTrue);
      expect(session.user?.email, 'person@example.com');
      expect(session.accessToken, 'backend-session');
      expect(store.value, 'backend-session');

      await session.signOut();
      expect(session.isAuthenticated, isFalse);
      expect(credentials.signedOut, isTrue);
      expect(privateCacheCleared, isTrue);
    },
  );

  test('clears the in-memory session when credential cleanup fails', () async {
    final store = _Store();
    final credentials = _Credentials()..failSignOut = true;
    final session = SessionController(
      baseUrl: 'https://api.example',
      credentials: credentials,
      store: store,
      publicClient: ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient(
          (request) async => http.Response(_sessionResponse, 200),
        ),
      ),
    );
    await session.signIn();

    await session.signOut();

    expect(session.isAuthenticated, isFalse);
    expect(session.accessToken, isNull);
    expect(store.value, isNull);
    expect(credentials.signedOut, isTrue);
    expect(session.error, contains('device cleanup'));
  });

  test(
    'GoogleCredentialGateway without serverClientId fails safely with clear explanation',
    () async {
      final gateway = GoogleCredentialGateway(serverClientId: null);
      expect(
        () => gateway.authenticate(),
        throwsA(
          isA<ApiException>().having(
            (e) => e.message,
            'message',
            'Google sign-in is not configured on this device.',
          ),
        ),
      );
      await expectLater(gateway.signOut(), completes);
    },
  );

  test(
    'SessionController surfaces safe error when Google sign-in is unconfigured',
    () async {
      final store = _Store();
      final session = SessionController(
        baseUrl: 'https://api.example',
        credentials: GoogleCredentialGateway(serverClientId: null),
        store: store,
        publicClient: ApiClient(
          baseUrl: 'https://api.example',
          client: MockClient((_) async => http.Response('{}', 200)),
        ),
      );

      await session.signIn();

      expect(session.isAuthenticated, isFalse);
      expect(session.loading, isFalse);
      expect(
        session.error,
        'Google sign-in is not configured on this device.',
      );

      session.clearError();
      expect(session.error, isNull);
    },
  );

  test(
    'SessionController sanitizes raw network and timeout errors',
    () {
      expect(
        SessionController.userFriendlyErrorMessage(
          const ApiException(
            'The server took too long to respond. Please check your connection and try again.',
          ),
        ),
        'The server took too long to respond. Please check your connection and try again.',
      );
      expect(
        SessionController.userFriendlyErrorMessage(
          Exception(
            'SocketException: OS Error: Connection refused, errno = 111',
          ),
        ),
        "We couldn't reach NutriLens right now. Check your connection and try again.",
      );
      expect(
        SessionController.userFriendlyErrorMessage(
          const ApiException('Email or password is incorrect.'),
        ),
        'Email or password is incorrect.',
      );
    },
  );

  test(
    'email OTP verification and session refresh operate on configured baseUrl',
    () async {
      final store = _Store()..value = 'initial-token';
      final requestedUrls = <String>[];
      final publicClient = ApiClient(
        baseUrl: 'http://127.0.0.1:8000',
        client: MockClient((request) async {
          requestedUrls.add(request.url.toString());
          if (request.url.path == '/api/v1/auth/email/otp/verify') {
            return http.Response(_sessionResponse, 200);
          }
          return http.Response('{}', 200);
        }),
      );

      final session = SessionController(
        baseUrl: 'http://127.0.0.1:8000',
        credentials: _Credentials(),
        store: store,
        publicClient: publicClient,
      );

      await session.verifyEmailOtp(
        email: 'person@example.com',
        otp: '123456',
      );

      expect(session.isAuthenticated, isTrue);
      expect(
        requestedUrls,
        contains('http://127.0.0.1:8000/api/v1/auth/email/otp/verify'),
      );
    },
  );
}

const _sessionResponse = '''
{
  "access_token": "backend-session",
  "expires_in_seconds": 3600,
  "user": {
    "id": "user-1",
    "email": "person@example.com",
    "name": "Person",
    "avatar_url": null,
    "plan": "FREE",
    "subscription_status": "FREE",
    "roles": [],
    "entitlements": {"scan_r3": true}
  }
}
''';
