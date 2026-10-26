import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/services/api_client.dart';

void main() {
  test('adds the session token and decodes JSON', () async {
    final api = ApiClient(
      baseUrl: 'https://api.example',
      accessToken: () => 'secret-token',
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/profile');
        expect(request.headers['Authorization'], 'Bearer secret-token');
        return http.Response('{"goal":"balanced"}', 200);
      }),
    );

    expect(await api.get('/api/v1/profile'), {'goal': 'balanced'});
  });

  test(
    'surfaces structured backend errors without leaking response bodies',
    () async {
      final api = ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient(
          (_) async => http.Response(
            '{"detail":{"message":"Plan entitlement required."}}',
            403,
          ),
        ),
      );

      expect(
        api.get('/api/v1/restricted'),
        throwsA(
          isA<ApiException>()
              .having((error) => error.statusCode, 'status', 403)
              .having(
                (error) => error.message,
                'message',
                'Plan entitlement required.',
              ),
        ),
      );
    },
  );

  test(
    'sends authenticated multipart evidence with the original image',
    () async {
      final api = ApiClient(
        baseUrl: 'https://api.example',
        accessToken: () => 'secret-token',
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/scan/client-evidence/classify');
          expect(request.headers['Authorization'], 'Bearer secret-token');
          expect(
            request.headers['content-type'],
            startsWith('multipart/form-data;'),
          );
          final body = utf8.decode(request.bodyBytes, allowMalformed: true);
          expect(body, contains('evidence_json'));
          expect(body, contains('{"contract":"1.0.0"}'));
          expect(body, contains('fixture.png'));
          return http.Response('{"accepted":true}', 200);
        }),
      );

      expect(
        await api.postMultipart(
          '/api/v1/scan/client-evidence/classify',
          fields: {'evidence_json': '{"contract":"1.0.0"}'},
          fileField: 'file',
          fileBytes: Uint8List.fromList([1, 2, 3]),
          filename: 'fixture.png',
          mimeType: 'image/png',
        ),
        {'accepted': true},
      );
    },
  );

  test('only triggers onUnauthorized for true session expiration', () async {
    var unauthorizedCalls = 0;
    final apiWrongPassword = ApiClient(
      baseUrl: 'https://api.example',
      onUnauthorized: () => unauthorizedCalls++,
      client: MockClient(
        (_) async => http.Response('{"detail":"Current password is incorrect."}', 401),
      ),
    );

    await expectLater(
      apiWrongPassword.post('/api/v1/auth/password/change'),
      throwsA(isA<ApiException>()),
    );
    expect(unauthorizedCalls, 0);

    final apiSessionExpired = ApiClient(
      baseUrl: 'https://api.example',
      onUnauthorized: () => unauthorizedCalls++,
      client: MockClient(
        (_) async => http.Response(
          '{"detail":"Invalid or expired session."}',
          401,
          headers: {'x-auth-error': 'SESSION_EXPIRED'},
        ),
      ),
    );

    await expectLater(
      apiSessionExpired.get('/api/v1/profile'),
      throwsA(isA<ApiException>()),
    );
    expect(unauthorizedCalls, 1);
  });

  test('normalizes TimeoutException to user-friendly message', () async {
    final api = ApiClient(
      baseUrl: 'https://api.example',
      timeout: const Duration(milliseconds: 10),
      client: MockClient((_) async {
        await Future.delayed(const Duration(milliseconds: 50));
        return http.Response('{}', 200);
      }),
    );

    expect(
      api.get('/api/v1/slow'),
      throwsA(
        isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 408)
            .having(
              (e) => e.message,
              'message',
              'The server took too long to respond. Please check your connection and try again.',
            ),
      ),
    );
  });

  test('normalizes ClientException to user-friendly unreachable message', () async {
    final api = ApiClient(
      baseUrl: 'https://api.example',
      client: MockClient((_) async {
        throw http.ClientException('Connection refused');
      }),
    );

    expect(
      api.get('/api/v1/unreachable'),
      throwsA(
        isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 503)
            .having(
              (e) => e.message,
              'message',
              "We couldn't reach NutriLens right now. Check your connection and try again.",
            ),
      ),
    );
  });

  test('falls back to friendly copy for 401 and 503 without detail', () async {
    final api401 = ApiClient(
      baseUrl: 'https://api.example',
      client: MockClient((_) async => http.Response('', 401)),
    );
    expect(
      api401.post('/api/v1/auth/email/login'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          'Email or password is incorrect.',
        ),
      ),
    );

    final api503 = ApiClient(
      baseUrl: 'https://api.example',
      client: MockClient((_) async => http.Response('', 503)),
    );
    expect(
      api503.get('/api/v1/health'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          'NutriLens is temporarily unavailable. Please try again shortly.',
        ),
      ),
    );
  });
}
