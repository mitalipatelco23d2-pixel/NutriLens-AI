import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/account_data_screen.dart';
import 'package:nutrilens_x/services/account_data.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/product_api.dart';

class _FakeSharer implements AccountExportSharer {
  AccountExportDisposition disposition = AccountExportDisposition.success;
  int calls = 0;
  String? filename;
  String? content;
  Rect? origin;

  @override
  Future<AccountExportDisposition> shareJson({
    required String filename,
    required String content,
    Rect? sharePositionOrigin,
  }) async {
    calls++;
    this.filename = filename;
    this.content = content;
    origin = sharePositionOrigin;
    return disposition;
  }
}

void main() {
  test(
    'exports formatted server data only through the explicit sharer',
    () async {
      final sharer = _FakeSharer();
      final api = ProductApi(
        ApiClient(
          baseUrl: 'https://api.example',
          client: MockClient((request) async {
            expect(request.method, 'GET');
            expect(request.url.path, '/api/v1/account/export');
            return http.Response(
              '{"exported_at":"2026-09-07T00:00:00Z","account":{"id":"owner"},"diary":[]}',
              200,
            );
          }),
        ),
      );
      final coordinator = AccountDataCoordinator(
        gateway: api,
        sharer: sharer,
        now: () => DateTime(2026, 9, 7),
      );

      final result = await coordinator.export();

      expect(sharer.calls, 1);
      expect(sharer.filename, 'nutrilens-export-2026-09-07.json');
      expect(jsonDecode(sharer.content!)['account']['id'], 'owner');
      expect(sharer.content, contains('\n  "account"'));
      expect(result.byteLength, utf8.encode(sharer.content!).length);
      expect(result.disposition, AccountExportDisposition.success);
    },
  );

  testWidgets('deletion requires exact DELETE before sending the request', (
    tester,
  ) async {
    var deleteCalls = 0;
    String? deleteBody;
    var localCleanupCalls = 0;
    final api = ProductApi(
      ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((request) async {
          if (request.url.path == '/api/v1/account') {
            deleteCalls++;
            deleteBody = request.body;
            return http.Response('', 204);
          }
          return http.Response('{"detail":"not found"}', 404);
        }),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AccountDataScreen(
          accountData: AccountDataCoordinator(
            gateway: api,
            sharer: _FakeSharer(),
          ),
          afterAccountDeleted: () async => localCleanupCalls++,
        ),
      ),
    );

    await tester.tap(find.byKey(const Key('delete-account')));
    await tester.pumpAndSettle();
    final confirm = find.byKey(const Key('confirm-delete-account'));
    expect(tester.widget<FilledButton>(confirm).onPressed, isNull);

    await tester.enterText(
      find.byKey(const Key('delete-account-confirmation')),
      'delete',
    );
    await tester.pump();
    expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
    expect(deleteCalls, 0);

    await tester.enterText(
      find.byKey(const Key('delete-account-confirmation')),
      'DELETE',
    );
    await tester.pump();
    expect(tester.widget<FilledButton>(confirm).onPressed, isNotNull);
    await tester.tap(confirm);
    await tester.pumpAndSettle();

    expect(deleteCalls, 1);
    expect(jsonDecode(deleteBody!), {'confirmation': 'DELETE'});
    expect(localCleanupCalls, 1);
  });

  testWidgets('a dismissed share sheet is not presented as an export success', (
    tester,
  ) async {
    final sharer = _FakeSharer()
      ..disposition = AccountExportDisposition.dismissed;
    final api = ProductApi(
      ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient(
          (_) async => http.Response(
            '{"exported_at":"2026-09-07T00:00:00Z","account":{}}',
            200,
          ),
        ),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AccountDataScreen(
          accountData: AccountDataCoordinator(gateway: api, sharer: sharer),
          afterAccountDeleted: () async {},
        ),
      ),
    );
    await tester.tap(find.byKey(const Key('export-account-data')));
    await tester.pumpAndSettle();

    expect(sharer.calls, 1);
    expect(find.textContaining('No destination was confirmed'), findsOneWidget);
  });
}
