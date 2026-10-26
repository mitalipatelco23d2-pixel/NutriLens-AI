import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/account_security_screen.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/auth_service.dart';
import 'package:nutrilens_x/services/product_api.dart';

class _Credentials implements CredentialGateway {
  @override
  Future<String> authenticate() async => 'google-token-for-test';

  @override
  Future<void> signOut() async {}
}

class _Store implements SessionStore {
  @override
  Future<void> clear() async {}

  @override
  Future<String?> read() async => null;

  @override
  Future<void> write(String token) async {}
}

void main() {
  testWidgets('shows truthful login and phone state and protects sole login', (
    tester,
  ) async {
    final session = SessionController(
      baseUrl: 'https://api.example',
      credentials: _Credentials(),
      store: _Store(),
      publicClient: ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((_) async => http.Response(_session, 200)),
      ),
    );
    await session.signIn();
    var passwordRequest = '';
    final products = ProductApi(
      ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((request) async {
          if (request.url.path == '/api/v1/auth/identities' &&
              request.method == 'GET') {
            return http.Response(
              _identities,
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (request.url.path == '/api/v1/account/profile') {
            return http.Response(
              _profile,
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (request.url.path == '/api/v1/auth/identities/email/password') {
            passwordRequest = request.body;
            return http.Response('{"message":"Verification sent."}', 202);
          }
          return http.Response('{"detail":"not found"}', 404);
        }),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AccountSecurityScreen(session: session, products: products),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      find.textContaining('add and verify email/password'),
      findsOneWidget,
    );
    expect(find.text('+••••••••3210 · unverified'), findsOneWidget);
    final disconnect = tester.widget<TextButton>(
      find.byKey(const Key('disconnect-google')),
    );
    expect(disconnect.onPressed, isNull);

    await tester.tap(find.byKey(const Key('add-password-login')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('new-password')),
      'Strong-password-42!',
    );
    await tester.tap(find.byKey(const Key('confirm-password-action')));
    await tester.pumpAndSettle();

    expect(passwordRequest, contains('Strong-password-42!'));
  });

  testWidgets('verifies and links phone identity via dialog', (tester) async {
    final session = SessionController(
      baseUrl: 'https://api.example',
      credentials: _Credentials(),
      store: _Store(),
      publicClient: ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((_) async => http.Response(_session, 200)),
      ),
    );
    await session.signIn();
    var phoneConnectPayload = '';
    final products = ProductApi(
      ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((request) async {
          if (request.url.path == '/api/v1/auth/identities' &&
              request.method == 'GET') {
            return http.Response(
              phoneConnectPayload.isNotEmpty ? _identitiesPhoneVerified : _identities,
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (request.url.path == '/api/v1/account/profile') {
            return http.Response(
              phoneConnectPayload.isNotEmpty ? _profilePhoneVerified : _profile,
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          if (request.url.path == '/api/v1/auth/phone/link') {
            phoneConnectPayload = request.body;
            return http.Response(
              '{"google_connected":true,"email_password_connected":false,"email_verified":false,"phone_verified":true,"terms_accepted":true,"privacy_accepted":true}',
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          return http.Response('{"detail":"not found"}', 404);
        }),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AccountSecurityScreen(session: session, products: products),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('verify-phone-action')), findsOneWidget);
    await tester.tap(find.byKey(const Key('verify-phone-action')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('verify-phone-number-input')), findsOneWidget);
    expect(find.byKey(const Key('verify-phone-token-input')), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('verify-phone-number-input')),
      '+919876543210',
    );
    await tester.enterText(
      find.byKey(const Key('verify-phone-token-input')),
      'simulated-test-token-proof',
    );
    await tester.tap(find.byKey(const Key('submit-phone-verification-btn')));
    await tester.pumpAndSettle();

    expect(phoneConnectPayload, contains('+919876543210'));
    expect(phoneConnectPayload, contains('simulated-test-token-proof'));
    expect(find.text('Phone number verified and linked.'), findsOneWidget);
  });

  testWidgets('safely defers phone verification when collegeDemoMode is true', (tester) async {
    final session = SessionController(
      baseUrl: 'https://api.example',
      credentials: _Credentials(),
      store: _Store(),
      publicClient: ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((_) async => http.Response(_session, 200)),
      ),
    );
    await session.signIn();
    final products = ProductApi(
      ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((request) async {
          if (request.url.path == '/api/v1/auth/identities') {
            return http.Response(_identities, 200, headers: {'content-type': 'application/json'});
          }
          if (request.url.path == '/api/v1/account/profile') {
            return http.Response(_profile, 200, headers: {'content-type': 'application/json'});
          }
          return http.Response('{"detail":"not found"}', 404);
        }),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AccountSecurityScreen(
          session: session,
          products: products,
          collegeDemoMode: true,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('optional'), findsOneWidget);
    expect(find.textContaining('deferred'), findsNothing);
    expect(find.byKey(const Key('verify-phone-action')), findsNothing);
  });
}

const _session = '''
{"access_token":"access-token","user":{"id":"owner-1","email":"owner@example.com","name":"Owner","avatar_url":null,"plan":"FREE","subscription_status":"FREE","roles":[],"entitlements":{}}}
''';

const _identities = '''
{"google_connected":true,"email_password_connected":false,"email_verified":false,"terms_accepted":true,"privacy_accepted":true}
''';

const _profile = '''
{"full_name":"Owner","date_of_birth":"1990-01-01","masked_phone_number":"+••••••••3210","phone_state":"UNVERIFIED","phone_verification_availability":"BLOCKED_EXTERNAL_COST","country_region":"IN","unit_system":"METRIC","research_insights_consent":false,"onboarding_complete":true,"age_eligibility":"ELIGIBLE_18_PLUS","minimum_account_age":18,"legal_acceptance_complete":true}
''';

const _identitiesPhoneVerified = '''
{"google_connected":true,"email_password_connected":false,"email_verified":false,"phone_verified":true,"terms_accepted":true,"privacy_accepted":true}
''';

const _profilePhoneVerified = '''
{"full_name":"Owner","date_of_birth":"1990-01-01","masked_phone_number":"+••••••••3210","phone_state":"VERIFIED","phone_verification_availability":"BLOCKED_EXTERNAL_COST","country_region":"IN","unit_system":"METRIC","research_insights_consent":false,"onboarding_complete":true,"age_eligibility":"ELIGIBLE_18_PLUS","minimum_account_age":18,"legal_acceptance_complete":true}
''';

