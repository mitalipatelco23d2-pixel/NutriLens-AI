import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/services/health_api.dart';

void main() {
  test('parses the backend health contract', () async {
    final client = MockClient((request) async {
      expect(request.url.path, '/api/v1/health');
      return http.Response(
        '{"status":"healthy","services":{"api":"healthy","redis":"healthy"}}',
        200,
      );
    });
    final api = HealthApi(baseUrl: 'http://localhost:8000/', client: client);

    final result = await api.fetchHealth();

    expect(result.isHealthy, isTrue);
    expect(result.services['redis'], 'healthy');
  });

  test('reports a non-success backend response', () async {
    final client = MockClient((_) async => http.Response('unavailable', 503));
    final api = HealthApi(baseUrl: 'http://localhost:8000', client: client);

    expect(api.fetchHealth(), throwsA(isA<HealthApiException>()));
  });
}
