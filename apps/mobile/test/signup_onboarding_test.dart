import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/config/app_config.dart';
import 'package:nutrilens_x/main.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/auth_service.dart';
import 'package:nutrilens_x/services/health_api.dart';
import 'package:nutrilens_x/services/product_api.dart';
import 'package:nutrilens_x/services/scan_api.dart';

class _Credentials implements CredentialGateway {
  @override
  Future<String> authenticate() async => 'google-id-token-for-widget-test';

  @override
  Future<void> signOut() async {}
}

class _MemoryStore implements SessionStore {
  String? token;

  @override
  Future<void> clear() async => token = null;

  @override
  Future<String?> read() async => null;

  @override
  Future<void> write(String value) async => token = value;
}

class _Health implements HealthGateway {
  @override
  Future<HealthSnapshot> fetchHealth() async =>
      const HealthSnapshot(status: 'healthy', services: {'api': 'healthy'});
}

class _Scans implements ScanGateway {
  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) => throw UnimplementedError();
}

void main() {
  testWidgets(
    'email signup requires explicit terms and privacy acknowledgement',
    (tester) async {
      tester.view.physicalSize = const Size(1080, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var signupRequests = 0;
      String? signupBody;
      final publicHttp = MockClient((request) async {
        if (request.url.path == '/api/v1/auth/email/signup') {
          signupRequests++;
          signupBody = request.body;
        }
        return http.Response('{"message":"sent"}', 202);
      });
      final session = SessionController(
        baseUrl: 'https://api.example',
        credentials: _Credentials(),
        store: _MemoryStore(),
        publicClient: ApiClient(
          baseUrl: 'https://api.example',
          client: publicHttp,
        ),
      );
      final products = ProductApi(
        ApiClient(
          baseUrl: 'https://api.example',
          client: MockClient((_) async => http.Response('{}', 200)),
        ),
      );

      await tester.pumpWidget(_app(session, products));
      await tester.pumpAndSettle();
      await tester.tap(find.text('New here? Create account'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextField, 'Name'),
        'Example Owner',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Email address'),
        'owner@example.com',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Password'),
        'StrongPassword!2',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Create account'));
      await tester.pump();

      expect(
        find.text('Accept the Terms and Privacy Policy to create an account.'),
        findsOneWidget,
      );
      expect(signupRequests, 0);

      await tester.tap(find.byKey(const Key('signup-terms')));
      await tester.tap(find.widgetWithText(FilledButton, 'Create account'));
      await tester.pumpAndSettle();
      expect(signupRequests, 1);
      expect(signupBody, contains('"accepted_terms":true'));
      expect(signupBody, contains('"accepted_privacy":true'));
    },
  );

  testWidgets(
    'authenticated incomplete account enters provider-prefilled onboarding',
    (tester) async {
      final authHttp = MockClient(
        (request) async => http.Response(
          _session,
          200,
          headers: {'content-type': 'application/json'},
        ),
      );
      final session = SessionController(
        baseUrl: 'https://api.example',
        credentials: _Credentials(),
        store: _MemoryStore(),
        publicClient: ApiClient(
          baseUrl: 'https://api.example',
          client: authHttp,
        ),
      );
      await session.signIn();
      expect(session.isAuthenticated, isTrue);

      final productHttp = MockClient((request) async {
        return switch (request.url.path) {
          '/api/v1/account/profile' => http.Response(_incompleteProfile, 200),
          '/api/v1/profile' => http.Response(_healthProfile, 200),
          _ => http.Response('{"detail":"not found"}', 404),
        };
      });
      final products = ProductApi(
        ApiClient(baseUrl: 'https://api.example', client: productHttp),
      );

      await tester.pumpWidget(_app(session, products));
      await tester.pumpAndSettle();

      expect(find.text('Set up NutriLens X'), findsOneWidget);
      expect(find.text('owner@example.com'), findsOneWidget);
      expect(
        find.text(
          'Your verified account identity is reused; NutriLens does not ask you to retype it.',
        ),
        findsOneWidget,
      );
      final nameField = tester.widget<TextFormField>(
        find.byKey(const Key('profile-full-name')),
      );
      expect(nameField.controller?.text, 'Google Owner');
      expect(find.text('Today'), findsNothing);
    },
  );

  testWidgets(
    'email signup shows 6-digit OTP verification screen and verifies session',
    (tester) async {
      tester.view.physicalSize = const Size(1080, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      var otpVerified = false;
      final publicHttp = MockClient((request) async {
        if (request.url.path == '/api/v1/auth/email/signup') {
          return http.Response('{"message":"A 6-digit verification code has been sent."}', 202);
        }
        if (request.url.path == '/api/v1/auth/email/otp/verify') {
          otpVerified = true;
          return http.Response(_session, 200, headers: {'content-type': 'application/json'});
        }
        return http.Response('{"detail":"not found"}', 404);
      });
      final session = SessionController(
        baseUrl: 'https://api.example',
        credentials: _Credentials(),
        store: _MemoryStore(),
        publicClient: ApiClient(
          baseUrl: 'https://api.example',
          client: publicHttp,
        ),
      );
      final products = ProductApi(
        ApiClient(
          baseUrl: 'https://api.example',
          client: MockClient((_) async => http.Response('{}', 200)),
        ),
      );

      await tester.pumpWidget(_app(session, products));
      await tester.pumpAndSettle();
      await tester.tap(find.text('New here? Create account'));
      await tester.pumpAndSettle();

      await tester.enterText(find.widgetWithText(TextField, 'Name'), 'New User');
      await tester.enterText(find.widgetWithText(TextField, 'Email address'), 'newuser@example.com');
      await tester.enterText(find.widgetWithText(TextField, 'Password'), 'ValidPass123!');
      await tester.tap(find.byKey(const Key('signup-terms')));
      await tester.tap(find.widgetWithText(FilledButton, 'Create account'));
      await tester.pumpAndSettle();

      // Verify OTP screen is shown
      expect(find.text('Verify your email'), findsOneWidget);
      expect(find.textContaining('newuser@example.com'), findsOneWidget);
      expect(find.byKey(const Key('otp-input')), findsOneWidget);
      expect(find.byKey(const Key('verify-otp-button')), findsOneWidget);
      expect(find.byKey(const Key('resend-otp-button')), findsOneWidget);
      expect(find.byKey(const Key('change-email-button')), findsOneWidget);

      // Verify with 6-digit OTP
      await tester.enterText(find.byKey(const Key('otp-input')), '123456');
      await tester.pump();
      await tester.tap(find.byKey(const Key('verify-otp-button')));
      await tester.pumpAndSettle();

      expect(otpVerified, isTrue);
      expect(session.isAuthenticated, isTrue);
    },
  );
}

Widget _app(SessionController session, ProductGateway products) => NutriLensApp(
  config: const AppConfig(
    apiBaseUrl: 'https://api.example',
    environment: 'test',
  ),
  healthGateway: _Health(),
  scanGateway: _Scans(),
  sessionController: session,
  productGateway: products,
);

const _session = '''
{"access_token":"access-token","user":{"id":"owner-1","email":"owner@example.com","name":"Google Owner","avatar_url":null,"plan":"FREE","subscription_status":"FREE","roles":[],"entitlements":{}}}
''';

const _incompleteProfile = '''
{"full_name":"Google Owner","date_of_birth":null,"masked_phone_number":null,"phone_state":"NOT_ADDED","phone_verification_availability":"BLOCKED_EXTERNAL_COST","country_region":null,"unit_system":"METRIC","research_insights_consent":false,"onboarding_complete":false}
''';

const _healthProfile = '''
{"goal":"balanced","allergens":[],"dietary_preferences":[],"consent_personalization":false,"daily_targets":{},"body_context":{"adult_attestation":false,"consent_bmi_context":false,"height_cm":null,"weight_kg":null}}
''';
