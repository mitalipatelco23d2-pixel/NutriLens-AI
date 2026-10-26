import 'package:flutter_test/flutter_test.dart';
import 'package:nutrilens_x/services/health_api.dart';

void main() {
  const liveApiBaseUrl = String.fromEnvironment('LIVE_API_BASE_URL');

  test(
    'connects to the running FastAPI health endpoint',
    () async {
      final snapshot = await HealthApi(baseUrl: liveApiBaseUrl).fetchHealth();

      expect(snapshot.isHealthy, isTrue);
      expect(snapshot.services.values, everyElement(equals('healthy')));
    },
    skip: liveApiBaseUrl.isEmpty
        ? 'Set LIVE_API_BASE_URL to run the live connectivity check.'
        : false,
  );
}
