import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nutrilens_x/config/app_config.dart';
import 'package:nutrilens_x/main.dart';
import 'package:nutrilens_x/services/health_api.dart';
import 'package:nutrilens_x/services/scan_api.dart';

class _HealthyGateway implements HealthGateway {
  @override
  Future<HealthSnapshot> fetchHealth() async {
    return const HealthSnapshot(
      status: 'healthy',
      services: {
        'api': 'healthy',
        'postgres': 'healthy',
        'mongodb': 'healthy',
        'neo4j': 'healthy',
        'redis': 'healthy',
      },
    );
  }
}

class _UnusedScanGateway implements ScanGateway {
  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) {
    throw UnimplementedError();
  }
}

void main() {
  testWidgets('shows foundation shell and connected backend health', (
    tester,
  ) async {
    await tester.pumpWidget(
      NutriLensApp(
        config: const AppConfig(
          apiBaseUrl: 'http://localhost:8000',
          environment: 'development',
        ),
        healthGateway: _HealthyGateway(),
        scanGateway: _UnusedScanGateway(),
      ),
    );

    expect(find.text('Understand what you’re really eating.'), findsOneWidget);
    expect(find.text('Environment: Development'), findsOneWidget);

    await tester.tap(find.text('System health'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('backend-status')), findsOneWidget);
    expect(find.text('Backend: Connected'), findsOneWidget);
    expect(find.text('postgres'), findsOneWidget);
    expect(find.text('redis'), findsOneWidget);
  });
}
