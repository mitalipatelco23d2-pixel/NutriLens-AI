import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/product_api.dart';
import 'package:nutrilens_x/session_management_screen.dart';

void main() {
  testWidgets(
    'lists truthful session metadata and revokes only after confirmation',
    (tester) async {
      tester.view.physicalSize = const Size(1080, 1600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var revoked = false;
      final httpClient = MockClient((request) async {
        if (request.url.path == '/api/v1/auth/sessions' &&
            request.method == 'GET') {
          return http.Response(revoked ? _currentSession : _sessions, 200);
        }
        if (request.url.path == '/api/v1/auth/sessions/session-other' &&
            request.method == 'DELETE') {
          revoked = true;
          return http.Response('', 204);
        }
        return http.Response('{"detail":"not found"}', 404);
      });
      final products = ProductApi(
        ApiClient(baseUrl: 'https://api.example', client: httpClient),
      );

      await tester.pumpWidget(
        MaterialApp(home: SessionManagementScreen(products: products)),
      );
      await tester.pumpAndSettle();

      expect(find.text('This session'), findsOneWidget);
      expect(find.text('Session …on-other'), findsOneWidget);
      expect(
        find.textContaining('not device names or location'),
        findsOneWidget,
      );
      expect(find.widgetWithText(Chip, 'Current'), findsOneWidget);
      expect(find.byIcon(Icons.logout), findsOneWidget);

      await tester.tap(find.byKey(const Key('revoke-session-session-other')));
      await tester.pumpAndSettle();
      expect(revoked, isFalse);
      expect(find.text('Sign out this session?'), findsOneWidget);
      await tester.tap(find.byKey(const Key('confirm-revoke-session')));
      await tester.pumpAndSettle();

      expect(revoked, isTrue);
      expect(find.text('Session signed out.'), findsOneWidget);
      expect(find.text('Session …on-other'), findsNothing);
      expect(find.text('This session'), findsOneWidget);
    },
  );
}

const _sessions = '''
[{"id":"session-current","current":true,"created_at":"2026-09-07T08:00:00Z","last_seen_at":"2026-09-07T09:00:00Z","expires_at":"2026-09-07T10:00:00Z"},{"id":"session-other","current":false,"created_at":"2026-09-06T08:00:00Z","last_seen_at":"2026-09-06T09:00:00Z","expires_at":"2026-09-07T10:00:00Z"}]
''';

const _currentSession = '''
[{"id":"session-current","current":true,"created_at":"2026-09-07T08:00:00Z","last_seen_at":"2026-09-07T09:00:00Z","expires_at":"2026-09-07T10:00:00Z"}]
''';
