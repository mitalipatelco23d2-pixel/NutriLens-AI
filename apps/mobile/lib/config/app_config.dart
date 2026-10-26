import 'package:flutter/foundation.dart';

class AppConfig {
  const AppConfig({
    required this.apiBaseUrl,
    required this.environment,
    this.googleClientId,
    this.googleServerClientId,
    this.collegeDemoMode = false,
  });

  static const canonicalProductionApiUrl = 'https://api.nutrilensx.tech';
  static const canonicalLocalQaApiUrl = 'http://127.0.0.1:8000';
  static const canonicalEmulatorQaApiUrl = 'http://10.0.2.2:8000';
  static const canonicalGoogleServerClientId =
      '495203095259-2g66c12sb11noq2f9tq429t4i2aconnv.apps.googleusercontent.com';

  factory AppConfig.fromEnvironment() {
    return resolveConfig(
      rawApiUrl: const String.fromEnvironment('API_BASE_URL'),
      rawEnvironment: const String.fromEnvironment('APP_ENVIRONMENT'),
      rawClientId: const String.fromEnvironment('GOOGLE_CLIENT_ID'),
      rawServerClientId:
          const String.fromEnvironment('GOOGLE_SERVER_CLIENT_ID'),
      rawCollegeDemoMode:
          const bool.fromEnvironment('COLLEGE_DEMO_MODE', defaultValue: false),
      isRelease: kReleaseMode,
    );
  }

  static AppConfig resolveConfig({
    String? rawApiUrl,
    String? rawEnvironment,
    String? rawClientId,
    String? rawServerClientId,
    bool rawCollegeDemoMode = false,
    bool isRelease = false,
  }) {
    final env =
        _nonEmpty(rawEnvironment) ?? (isRelease ? 'production' : 'local_qa');
    final explicitUrl = _nonEmpty(rawApiUrl);

    final String apiBaseUrl;
    if (explicitUrl != null) {
      apiBaseUrl = explicitUrl;
    } else if (isRelease || env.toLowerCase() == 'production') {
      apiBaseUrl = canonicalProductionApiUrl;
    } else if (env.toLowerCase() == 'emulator_qa') {
      apiBaseUrl = canonicalEmulatorQaApiUrl;
    } else {
      apiBaseUrl = canonicalLocalQaApiUrl;
    }

    final googleServerClientId =
        _nonEmpty(rawServerClientId) ?? canonicalGoogleServerClientId;
    final googleClientId = _nonEmpty(rawClientId);

    final isDemoAllowed = !isRelease && (env.toLowerCase() == 'local_qa' || env.toLowerCase() == 'development');
    final collegeDemoMode = rawCollegeDemoMode && isDemoAllowed;

    final config = AppConfig(
      apiBaseUrl: apiBaseUrl,
      environment: env,
      googleClientId: googleClientId,
      googleServerClientId: googleServerClientId,
      collegeDemoMode: collegeDemoMode,
    );
    config.validateReleaseSafety(isRelease: isRelease);
    return config;
  }

  final String apiBaseUrl;
  final String environment;
  final String? googleClientId;
  final String? googleServerClientId;
  final bool collegeDemoMode;

  String? get effectiveGoogleClientId => _nonEmpty(googleClientId);
  String? get effectiveGoogleServerClientId =>
      _nonEmpty(googleServerClientId) ?? effectiveGoogleClientId;

  String get displayEnvironment {
    if (environment.isEmpty) return 'Unknown';
    return '${environment[0].toUpperCase()}${environment.substring(1)}';
  }

  void validateReleaseSafety({required bool isRelease}) {
    if (!isRelease) return;
    final uri = Uri.tryParse(apiBaseUrl);
    if (environment.toLowerCase() != 'production') {
      throw StateError(
        'Release builds require the production environment name.',
      );
    }
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host != 'api.nutrilensx.tech') {
      throw StateError(
        'Release builds require the canonical HTTPS production API (api.nutrilensx.tech).',
      );
    }
    if (uri.host == '127.0.0.1' ||
        uri.host == 'localhost' ||
        uri.host == '10.0.2.2') {
      throw StateError(
        'Release builds must never point to local development hosts.',
      );
    }
    if (effectiveGoogleServerClientId == null ||
        effectiveGoogleServerClientId!.isEmpty) {
      throw StateError(
        'Release builds require the backend-audience Google server client ID.',
      );
    }
  }

  static String? _nonEmpty(String? value) {
    final normalized = value?.trim();
    return normalized == null || normalized.isEmpty ? null : normalized;
  }
}
