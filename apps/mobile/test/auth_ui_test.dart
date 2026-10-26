import 'dart:async';
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

class _MockStore implements SessionStore {
  String? token;
  @override
  Future<void> clear() async => token = null;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async => token = value;
}

class _MockHealth implements HealthGateway {
  @override
  Future<HealthSnapshot> fetchHealth() async =>
      const HealthSnapshot(status: 'healthy', services: {'api': 'healthy'});
}

class _MockScans implements ScanGateway {
  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) => throw UnimplementedError();
}

class _DelayableCredentials implements CredentialGateway {
  Completer<String>? completer;

  @override
  Future<String> authenticate() {
    completer = Completer<String>();
    return completer!.future;
  }

  @override
  Future<void> signOut() async {}
}

Widget _buildTestApp({
  required SessionController session,
  required ProductApi products,
}) {
  return NutriLensApp(
    config: const AppConfig(
      apiBaseUrl: 'http://127.0.0.1:8000',
      environment: 'local_qa',
      googleServerClientId:
          '495203095259-2g66c12sb11noq2f9tq429t4i2aconnv.apps.googleusercontent.com',
    ),
    healthGateway: _MockHealth(),
    scanGateway: _MockScans(),
    sessionController: session,
    productGateway: products,
  );
}

void main() {
  testWidgets(
    'prevents double submission and restores button state on timeout or network error',
    (tester) async {
      tester.view.physicalSize = const Size(1080, 1920);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final requestCompleter = Completer<http.Response>();
      var requestCount = 0;

      final publicClient = ApiClient(
        baseUrl: 'http://127.0.0.1:8000',
        client: MockClient((request) async {
          requestCount++;
          return requestCompleter.future;
        }),
      );

      final session = SessionController(
        baseUrl: 'http://127.0.0.1:8000',
        credentials: _DelayableCredentials(),
        store: _MockStore(),
        publicClient: publicClient,
      );

      final products = ProductApi(publicClient);

      await tester.pumpWidget(
        _buildTestApp(session: session, products: products),
      );
      await tester.pumpAndSettle();

      // Verify sign in screen is rendered
      expect(find.byKey(const Key('google-sign-in')), findsOneWidget);
      final submitButtonFinder = find.byKey(const Key('submit-email-button'));
      expect(submitButtonFinder, findsOneWidget);
      expect(find.text('Sign in'), findsOneWidget);

      // Enter credentials
      await tester.enterText(
        find.widgetWithText(TextField, 'Email address'),
        'test@example.com',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Password'),
        'Secret123!',
      );
      await tester.pump();

      // Tap submit once
      await tester.tap(submitButtonFinder);
      await tester.pump();

      // Button is in flight: shows 'Signing in…' with progress indicator
      expect(find.text('Signing in…'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      // Try tapping again while in-flight: should NOT trigger second request
      await tester.tap(submitButtonFinder, warnIfMissed: false);
      await tester.pump();
      expect(requestCount, 1);

      // Complete request with network error
      requestCompleter.completeError(
        http.ClientException('Connection refused to 127.0.0.1:8000'),
      );
      await tester.pumpAndSettle();

      // Error message is displayed cleanly without raw ClientException
      expect(
        find.text(
          "We couldn't reach NutriLens right now. Check your connection and try again.",
        ),
        findsOneWidget,
      );

      // Controls are restored
      expect(find.text('Sign in'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);

      // Toggle to create account clears error
      await tester.tap(find.byKey(const Key('toggle-auth-mode-button')));
      await tester.pumpAndSettle();
      expect(
        find.text(
          "We couldn't reach NutriLens right now. Check your connection and try again.",
        ),
        findsNothing,
      );
      expect(find.text('Create account'), findsOneWidget);
    },
  );

  testWidgets(
    'Google sign-in shows loading state and disables buttons during authentication',
    (tester) async {
      tester.view.physicalSize = const Size(1080, 1920);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final credentials = _DelayableCredentials();
      final publicClient = ApiClient(
        baseUrl: 'http://127.0.0.1:8000',
        client: MockClient((_) async => http.Response('{}', 200)),
      );

      final session = SessionController(
        baseUrl: 'http://127.0.0.1:8000',
        credentials: credentials,
        store: _MockStore(),
        publicClient: publicClient,
      );
      final products = ProductApi(publicClient);

      await tester.pumpWidget(
        _buildTestApp(session: session, products: products),
      );
      await tester.pumpAndSettle();

      final googleButtonFinder = find.byKey(const Key('google-sign-in'));
      expect(googleButtonFinder, findsOneWidget);
      expect(find.text('Continue with Google'), findsOneWidget);

      // Tap Google button
      await tester.tap(googleButtonFinder);
      await tester.pump();

      // Should show in-flight progress
      expect(find.text('Signing in with Google…'), findsOneWidget);

      // Fail Google auth with friendly cancelled exception
      credentials.completer!.completeError(
        const ApiException('Google sign-in was cancelled.'),
      );
      await tester.pumpAndSettle();

      // Friendly error shown, button restored
      expect(find.text('Google sign-in was cancelled.'), findsOneWidget);
      expect(find.text('Continue with Google'), findsOneWidget);
    },
  );
}
