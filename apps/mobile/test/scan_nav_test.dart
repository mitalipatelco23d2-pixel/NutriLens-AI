import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/config/app_config.dart';
import 'package:nutrilens_x/main.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/auth_service.dart';
import 'package:nutrilens_x/services/client_inference.dart';
import 'package:nutrilens_x/services/health_api.dart';
import 'package:nutrilens_x/services/intelligence_api.dart';
import 'package:nutrilens_x/services/product_api.dart';
import 'package:nutrilens_x/services/scan_api.dart';

class _Credentials implements CredentialGateway {
  @override
  Future<String> authenticate() async => 'test-token';
  @override
  Future<void> signOut() async {}
}

class _MemoryStore implements SessionStore {
  String? token;
  @override
  Future<void> clear() async => token = null;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async => token = value;
}

void main() {
  testWidgets(
    'QA-SCAN-NAV-001: reproducing from launch -> sign in -> Today -> tap Scan tab',
    (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final store = _MemoryStore();

      final mockHttp = MockClient((request) async {
        final path = request.url.path;
        if (path == '/api/v1/auth/email/login') {
          return http.Response(_sessionResponse, 200);
        }
        if (path == '/api/v1/account/profile') {
          return http.Response(_completeProfile, 200);
        }
        if (path == '/api/v1/analytics/summary') {
          return http.Response(_analyticsSummary, 200);
        }
        if (path == '/api/v1/weight/summary') {
          return http.Response('{"state":"DISABLED"}', 200);
        }
        if (path == '/api/v1/hydration/today') {
          return http.Response(_hydrationToday, 200);
        }
        if (path == '/api/v1/scan/jobs/pending') {
          return http.Response('{"has_pending":false}', 200);
        }
        return http.Response('{"detail":"not found"}', 404);
      });

      final session = SessionController(
        baseUrl: 'https://api.example',
        credentials: _Credentials(),
        store: store,
        publicClient: ApiClient(
          baseUrl: 'https://api.example',
          client: mockHttp,
        ),
      );

      final authorizedClient = ApiClient(
        baseUrl: 'https://api.example',
        accessToken: () => session.accessToken,
        client: mockHttp,
      );

      final products = ProductApi(authorizedClient);
      final scanGateway = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => session.accessToken,
        userId: () => session.user?.id,
        client: mockHttp,
      );

      await tester.pumpWidget(
        NutriLensApp(
          config: const AppConfig(
            apiBaseUrl: 'https://api.example',
            environment: 'local_qa',
          ),
          healthGateway: HealthApi(
            baseUrl: 'https://api.example',
            client: mockHttp,
          ),
          scanGateway: scanGateway,
          sessionController: session,
          productGateway: products,
          intelligenceGateway: IntelligenceApi(authorizedClient),
          clientEvidenceGateway: ClientEvidenceApi(authorizedClient),
        ),
      );

      // Wait for initial restore to complete and show sign in screen
      await tester.pumpAndSettle();

      // Sign in screen is displayed
      expect(find.byKey(const Key('submit-email-button')), findsOneWidget);
      // QA-AUTH-UX-001: Consumer copy only, no environment prefix in normal UI
      expect(find.text('Wellness guidance only'), findsOneWidget);
      expect(find.textContaining('Local_qa'), findsNothing);

      // Enter email and password
      await tester.enterText(
        find.widgetWithText(TextField, 'Email address'),
        'user@example.com',
      );
      await tester.enterText(
        find.widgetWithText(TextField, 'Password'),
        'Password123!',
      );

      // Tap Sign in
      await tester.tap(find.byKey(const Key('submit-email-button')));
      await tester.pumpAndSettle();

      // Today shell renders
      expect(find.text('Hello, Test User'), findsOneWidget);
      expect(find.text('Today'), findsOneWidget);
      expect(find.text('Scan'), findsOneWidget);

      // Tap Scan tab
      await tester.tap(find.text('Scan'));
      await tester.pumpAndSettle();

      final navBar = tester.widget<NavigationBar>(find.byType(NavigationBar));
      expect(navBar.selectedIndex, 1);

      // Verify Scanner screen opens
      expect(find.text('Food scanner'), findsOneWidget);

      // Tap Today tab
      await tester.tap(find.text('Today'));
      await tester.pumpAndSettle();
      expect(find.text('Hello, Test User'), findsOneWidget);

      // Tap Scan tab again
      await tester.tap(find.text('Scan'));
      await tester.pumpAndSettle();
      expect(find.text('Food scanner'), findsOneWidget);

      // Tap Today tab
      await tester.tap(find.text('Today'));
      await tester.pumpAndSettle();

      // Tap Ask Nutri from Today
      await tester.tap(find.text('Ask Nutri'));
      await tester.pumpAndSettle();
      expect(find.text('Ask Nutri'), findsWidgets);

      // Go back
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      // Tap Scan
      await tester.tap(find.text('Scan'));
      await tester.pumpAndSettle();
      expect(find.text('Food scanner'), findsOneWidget);

      // Test background and resume lifecycle
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await tester.pump();
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pumpAndSettle();
      expect(find.text('Food scanner'), findsOneWidget);

      // Switch to Diary, Pantry, and back to Scan
      await tester.tap(find.text('Diary'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Pantry'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Scan'));
      await tester.pumpAndSettle();
      expect(find.text('Food scanner'), findsOneWidget);

      session.dispose();
    },
  );
}

const _sessionResponse = '''
{
  "access_token": "valid-token",
  "expires_in_seconds": 3600,
  "user": {
    "id": "user-1",
    "email": "user@example.com",
    "name": "Test User",
    "avatar_url": null,
    "plan": "FREE",
    "subscription_status": "FREE",
    "roles": [],
    "entitlements": {}
  }
}
''';

const _completeProfile = '''
{
  "full_name": "Test User",
  "date_of_birth": null,
  "masked_phone_number": null,
  "phone_state": "NOT_ADDED",
  "phone_verification_availability": "AVAILABLE",
  "country_region": null,
  "unit_system": "METRIC",
  "research_insights_consent": false,
  "onboarding_complete": true
}
''';

const _analyticsSummary = '''
{
  "diary_entries": 0,
  "daily_averages": {
    "calories": 0.0,
    "protein_g": 0.0,
    "calcium_mg": 0.0
  },
  "insights": []
}
''';

const _hydrationToday = '''
{
  "current_ml": 0,
  "target_ml": 2000,
  "percentage": 0,
  "history": []
}
''';
