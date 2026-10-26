import 'package:flutter_test/flutter_test.dart';
import 'package:nutrilens_x/config/app_config.dart';

void main() {
  group('AppConfig Release Safety', () {
    test(
      'production release accepts only the canonical HTTPS API and OAuth audience',
      () {
        const config = AppConfig(
          apiBaseUrl: 'https://api.nutrilensx.tech',
          environment: 'production',
          googleServerClientId:
              'public-oauth-client-id.apps.googleusercontent.com',
        );
        expect(
          () => config.validateReleaseSafety(isRelease: true),
          returnsNormally,
        );
      },
    );

    test('release fails closed on emulator URL, 127.0.0.1, localhost, or non-HTTPS', () {
      const emulator = AppConfig(
        apiBaseUrl: 'http://10.0.2.2:8000',
        environment: 'production',
        googleServerClientId: 'valid-client-id',
      );
      const loopback = AppConfig(
        apiBaseUrl: 'http://127.0.0.1:8000',
        environment: 'production',
        googleServerClientId: 'valid-client-id',
      );
      const localhost = AppConfig(
        apiBaseUrl: 'http://localhost:8000',
        environment: 'production',
        googleServerClientId: 'valid-client-id',
      );
      const nonHttps = AppConfig(
        apiBaseUrl: 'http://api.nutrilensx.tech',
        environment: 'production',
        googleServerClientId: 'valid-client-id',
      );
      expect(
        () => emulator.validateReleaseSafety(isRelease: true),
        throwsStateError,
      );
      expect(
        () => loopback.validateReleaseSafety(isRelease: true),
        throwsStateError,
      );
      expect(
        () => localhost.validateReleaseSafety(isRelease: true),
        throwsStateError,
      );
      expect(
        () => nonHttps.validateReleaseSafety(isRelease: true),
        throwsStateError,
      );
    });

    test('release fails closed on non-production environment or missing Google audience', () {
      const local = AppConfig(
        apiBaseUrl: 'http://10.0.2.2:8000',
        environment: 'development',
      );
      const missingAudience = AppConfig(
        apiBaseUrl: 'https://api.nutrilensx.tech',
        environment: 'production',
      );
      expect(
        () => local.validateReleaseSafety(isRelease: true),
        throwsStateError,
      );
      expect(
        () => missingAudience.validateReleaseSafety(isRelease: true),
        throwsStateError,
      );
    });

    test('debug development remains usable without production credentials', () {
      const config = AppConfig(
        apiBaseUrl: 'http://10.0.2.2:8000',
        environment: 'development',
      );
      expect(
        () => config.validateReleaseSafety(isRelease: false),
        returnsNormally,
      );
    });
  });

  group('AppConfig Environment Resolution & Contracts', () {
    test('local QA defaults to http://127.0.0.1:8000 for adb reverse tunnel', () {
      final config = AppConfig.resolveConfig(isRelease: false);
      expect(config.apiBaseUrl, AppConfig.canonicalLocalQaApiUrl);
      expect(config.apiBaseUrl, 'http://127.0.0.1:8000');
      expect(config.environment, 'local_qa');
      expect(
        config.effectiveGoogleServerClientId,
        AppConfig.canonicalGoogleServerClientId,
      );
    });

    test('emulator QA defaults to http://10.0.2.2:8000 when specified', () {
      final config = AppConfig.resolveConfig(
        rawEnvironment: 'emulator_qa',
        isRelease: false,
      );
      expect(config.apiBaseUrl, AppConfig.canonicalEmulatorQaApiUrl);
      expect(config.apiBaseUrl, 'http://10.0.2.2:8000');
      expect(config.environment, 'emulator_qa');
    });

    test('explicit API_BASE_URL override takes precedence in non-release mode', () {
      final config = AppConfig.resolveConfig(
        rawApiUrl: 'http://192.168.1.100:8000',
        isRelease: false,
      );
      expect(config.apiBaseUrl, 'http://192.168.1.100:8000');
    });

    test('release mode defaults to canonical production API URL and passes safety checks', () {
      final config = AppConfig.resolveConfig(isRelease: true);
      expect(config.apiBaseUrl, AppConfig.canonicalProductionApiUrl);
      expect(config.apiBaseUrl, 'https://api.nutrilensx.tech');
      expect(config.environment, 'production');
      expect(
        config.effectiveGoogleServerClientId,
        AppConfig.canonicalGoogleServerClientId,
      );
      expect(() => config.validateReleaseSafety(isRelease: true), returnsNormally);
    });

    test('explicit GOOGLE_SERVER_CLIENT_ID override is preserved', () {
      final config = AppConfig.resolveConfig(
        rawServerClientId: 'custom-client-id.apps.googleusercontent.com',
        isRelease: false,
      );
      expect(
        config.effectiveGoogleServerClientId,
        'custom-client-id.apps.googleusercontent.com',
      );
    });
  });
}
