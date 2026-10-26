import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:image_picker/image_picker.dart';
import 'package:nutrilens_x/authenticated_shell.dart';
import 'package:nutrilens_x/config/app_config.dart';
import 'package:nutrilens_x/main.dart';
import 'package:nutrilens_x/scanner_screen.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/auth_service.dart';
import 'package:nutrilens_x/services/health_api.dart';
import 'package:nutrilens_x/services/product_api.dart';
import 'package:nutrilens_x/services/scan_api.dart';

class _FakeStore implements SessionStore {
  String? token;
  @override
  Future<void> clear() async => token = null;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String value) async => token = value;
}

class _DummyCredentials implements CredentialGateway {
  @override
  Future<String> authenticate() async => 'dummy-id-token';
  @override
  Future<void> signOut() async {}
}

class _DummyHealth implements HealthGateway {
  @override
  Future<HealthSnapshot> fetchHealth() async =>
      const HealthSnapshot(status: 'healthy', services: {'api': 'healthy'});
}

class _FakeImageSource implements ScanImageSource {
  @override
  Future<PickedScanImage?> pick(ImageSource source) async {
    return PickedScanImage(
      bytes: Uint8List.fromList([1, 2, 3]),
      filename: 'fixture.png',
      mimeType: 'image/png',
    );
  }
}

class _DummyScanGateway implements ScanGateway {
  ScanSnapshot? nextResult;
  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) async {
    return nextResult ??
        const ScanSnapshot(
          scanId: 'empty',
          status: 'COMPLETED',
          confidenceLevel: 'HIGH',
          confidence: 1.0,
          warnings: [],
          ocrText: '',
          barcodeValues: [],
          productCandidates: [],
          qualityStatus: 'ACCEPTABLE',
          totalMilliseconds: 10,
        );
  }
}

void main() {
  group('QA-SESSION-EXP-001 & Session Invalidation Matrix', () {
    testWidgets('pantry save with expired session transitions cleanly to sign-in without red screen', (tester) async {
      tester.view.physicalSize = const Size(1080, 1920);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final store = _FakeStore()..token = 'valid-token';
      late SessionController session;

      final httpClient = MockClient((request) async {
        final path = request.url.path;
        if (path == '/api/v1/auth/me') {
          return http.Response(
            jsonEncode({
              'id': 'user-1',
              'email': 'user@example.com',
              'name': 'Pantry User',
              'email_verified': true,
              'has_google_identity': false,
              'has_password_identity': true,
              'has_phone_identity': false,
              'plan': 'FREE',
              'client_metadata': {},
            }),
            200,
          );
        }
        if (path == '/api/v1/account/profile') {
          return http.Response(
            jsonEncode({
              'full_name': 'Pantry User',
              'onboarding_complete': true,
              'country_region': 'IN',
              'unit_system': 'METRIC',
              'phone_state': 'UNVERIFIED',
              'phone_verification_availability': 'BLOCKED_EXTERNAL_COST',
              'research_insights_consent': false,
            }),
            200,
          );
        }
        if (path == '/api/v1/profile/account') {
          return http.Response(
            jsonEncode({
              'name': 'Pantry User',
              'onboarding_complete': true,
              'locale': 'en',
              'region': 'IN',
              'unit_system': 'METRIC',
            }),
            200,
          );
        }
        if (path == '/api/v1/analytics') {
          return http.Response(
            jsonEncode({
              'period_days': 30,
              'diary_entries': 0,
              'totals': {},
              'daily_averages': {},
              'limitation': '',
            }),
            200,
          );
        }
        if (path == '/api/v1/pantry') {
          if (request.method == 'GET') {
            return http.Response(
              jsonEncode([
                {
                  'id': 'pantry-item-1',
                  'name': 'Rolled Oats',
                  'quantity': 500,
                  'unit': 'g',
                  'low_stock_threshold': 100,
                  'item_role': 'INGREDIENT',
                }
              ]),
              200,
            );
          }
        }
        if (path == '/api/v1/pantry/pantry-item-1' && request.method == 'PATCH') {
          // Backend returns session expired 401
          return http.Response(
            jsonEncode({
              'detail': 'Session expired. Please sign in again.',
              'code': 'SESSION_EXPIRED',
            }),
            401,
            headers: {'www-authenticate': 'Bearer error="invalid_token"'},
          );
        }
        if (path == '/api/v1/recipes/recommendations') {
          return http.Response(jsonEncode([]), 200);
        }
        if (path == '/api/v1/recipes/use-soon') {
          return http.Response(
            jsonEncode({'suggestions': [], 'limitation': ''}),
            200,
          );
        }
        if (path == '/api/v1/auth/session/refresh') {
          return http.Response(
            jsonEncode({
              'access_token': 'refreshed-token',
              'expires_in_seconds': 3600,
              'user': {
                'id': 'user-1',
                'email': 'user@example.com',
                'name': 'Pantry User',
                'email_verified': true,
                'has_google_identity': false,
                'has_password_identity': true,
                'has_phone_identity': false,
                'plan': 'FREE',
                'client_metadata': {},
              },
            }),
            200,
          );
        }
        if (path == '/api/v1/shopping-list') {
          return http.Response(jsonEncode([]), 200);
        }
        if (path == '/api/v1/hydration/entries') {
          return http.Response(jsonEncode([]), 200);
        }
        if (path == '/api/v1/hydration/target') {
          return http.Response(jsonEncode({'target_ml': 2000}), 200);
        }
        if (path == '/api/v1/weight/summary') {
          return http.Response(
            jsonEncode({'state': 'DISABLED', 'records': []}),
            200,
          );
        }
        return http.Response('{"detail":"not found"}', 404);
      });

      final publicClient = ApiClient(baseUrl: 'http://127.0.0.1:8000', client: httpClient);
      final authorizedClient = ApiClient(
        baseUrl: 'http://127.0.0.1:8000',
        accessToken: () => store.token,
        client: httpClient,
        onUnauthorized: () {
          session.handleSessionExpired();
        },
      );
      session = SessionController(
        baseUrl: 'http://127.0.0.1:8000',
        credentials: _DummyCredentials(),
        store: store,
        publicClient: publicClient,
        authorizedClient: authorizedClient,
      );
      final products = ProductApi(authorizedClient);

      await tester.pumpWidget(
        NutriLensApp(
          config: const AppConfig(
            apiBaseUrl: 'http://127.0.0.1:8000',
            environment: 'local_qa',
          ),
          healthGateway: _DummyHealth(),
          scanGateway: _DummyScanGateway(),
          sessionController: session,
          productGateway: products,
        ),
      );
      await tester.pumpAndSettle();

      // Authenticated and on Today tab. Navigate to Pantry tab (index 3).
      await tester.tap(find.text('Pantry'));
      await tester.pumpAndSettle();

      expect(find.text('Rolled Oats'), findsOneWidget);

      // Tap to edit Rolled Oats
      await tester.tap(find.text('Rolled Oats'));
      await tester.pumpAndSettle();

      expect(find.text('Update Rolled Oats'), findsOneWidget);

      // Tap Save button -> triggers PATCH /api/v1/pantry/pantry-item-1 which returns 401 SESSION_EXPIRED
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      // Expect safe dismissal of dialog, return to sign-in screen, and expiry notice
      expect(find.byType(ErrorWidget), findsNothing);
      expect(find.text('Your session expired. Please sign in again.'), findsOneWidget);
      expect(find.text('Sign in'), findsOneWidget);
    });

    testWidgets('concurrent 401 session-expired triggers only ONE sign-out transition', (tester) async {
      final store = _FakeStore()..token = 'active-token';
      var notifyCount = 0;

      final httpClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'detail': 'Session expired.',
            'code': 'SESSION_EXPIRED',
          }),
          401,
        );
      });

      final publicClient = ApiClient(baseUrl: 'http://127.0.0.1:8000', client: httpClient);
      final session = SessionController(
        baseUrl: 'http://127.0.0.1:8000',
        credentials: _DummyCredentials(),
        store: store,
        publicClient: publicClient,
      );
      session.addListener(() {
        notifyCount++;
      });

      // Fire 5 concurrent expired-session calls
      session.handleSessionExpired();
      session.handleSessionExpired();
      session.handleSessionExpired();
      session.handleSessionExpired();

      // Only the first one invalidates credentials and emits notification
      expect(session.isAuthenticated, isFalse);
      expect(notifyCount, 1);
      expect(session.error, 'Your session expired. Please sign in again.');
    });
  });

  group('QA-SCAN-MILK-002 & QA-SCAN-RESULT-003 Consumer Rendering', () {
    testWidgets('renders explicit per 100 ml and per serving columns cleanly without Value 2', (tester) async {
      final snapshot = ScanSnapshot(
        scanId: 's1',
        status: 'COMPLETED',
        confidenceLevel: 'HIGH',
        confidence: 0.95,
        warnings: const [],
        ocrText: 'Raw OCR preserved in technical details',
        barcodeValues: const [],
        totalMilliseconds: 120,
        qualityStatus: 'ACCEPTABLE',
        productCandidates: const ['Low Fat Cow Milk'],
        brandCandidates: const ['Country Delight'],
        allergenText: 'Milk',
        ingredientText: 'Pasteurized cow milk',
        nutrition: const NutritionSnapshot(
          basis: 'PER_100_ML',
          columns: ['per 100 ml', 'per serving', '% RDA per serving'],
          servingSizeValue: '250',
          servingSizeUnit: 'ml',
          confidence: 0.92,
          rows: [
            NutritionTableRow(
              label: 'energy',
              rawLabel: 'Energy',
              canonicalLabel: 'energy',
              matchConfidence: 0.95,
              values: ['50', '125', '6%'],
              rawValues: ['50', '125', '6%'],
              units: ['kcal', 'kcal', '%'],
              confidence: 0.95,
              parsedValues: [
                NutritionValue(value: '50', unit: 'kcal', basis: 'PER_100_ML'),
                NutritionValue(value: '125', unit: 'kcal', basis: 'PER_SERVING', resolvedServing: '250 ml'),
                NutritionValue(value: '6', unit: '%', basis: 'RDA_PERCENT'),
              ],
            ),
            NutritionTableRow(
              label: 'total fat',
              rawLabel: 'Total Fat',
              canonicalLabel: 'total fat',
              matchConfidence: 0.95,
              values: ['1.5', '4', '6%'],
              rawValues: ['1.5', '3.75', '6%'],
              units: ['g', 'g', '%'],
              confidence: 0.95,
              parsedValues: [
                NutritionValue(value: '1.5', unit: 'g', basis: 'PER_100_ML'),
                NutritionValue(value: '4', unit: 'g', basis: 'PER_SERVING', resolvedServing: '250 ml'),
                NutritionValue(value: '6', unit: '%', basis: 'RDA_PERCENT'),
              ],
            ),
          ],
        ),
        positiveSignals: const ['Low fat'],
        thingsToWatch: const [],
        insightsHighlights: const [],
      );

      final dummyGateway = _DummyScanGateway()..nextResult = snapshot;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ScannerScreen(
              scanGateway: dummyGateway,
              imageSource: _FakeImageSource(),
              ownerId: 'user-1',
            ),
          ),
        ),
      );

      // Trigger scan presentation
      await tester.tap(find.text('Gallery'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('run-r3-scan')));
      await tester.pumpAndSettle();

      // Expect clean table columns
      expect(find.text('Per 100 ml'), findsWidgets);
      expect(find.text('Per serving (250 ml)'), findsOneWidget);
      expect(find.text('Value 2'), findsNothing);
      expect(find.text('Value 3'), findsNothing);
      expect(find.text('Basis unknown'), findsNothing);

      // Verify nutrient row contents
      expect(find.text('50 kcal'), findsWidgets);
      expect(find.text('125 kcal'), findsOneWidget);
      expect(find.text('1.5 g'), findsWidgets);
      expect(find.text('4 g'), findsOneWidget);
    });

    testWidgets('raw noisy OCR product candidates fallback to clean consumer title', (tester) async {
      final snapshot = const ScanSnapshot(
        scanId: 's2',
        status: 'COMPLETED',
        confidenceLevel: 'HIGH',
        confidence: 0.88,
        warnings: [],
        ocrText: 'Noisy OCR text',
        barcodeValues: [],
        totalMilliseconds: 100,
        qualityStatus: 'ACCEPTABLE',
        productCandidates: ['Low Fat Cow Milk pasteurized cow milk 500ml pouch'],
        brandCandidates: [],
        allergenText: '',
        ingredientText: '',
        nutrition: NutritionSnapshot.empty(),
      );

      final dummyGateway = _DummyScanGateway()..nextResult = snapshot;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ScannerScreen(
              scanGateway: dummyGateway,
              imageSource: _FakeImageSource(),
              ownerId: 'user-1',
            ),
          ),
        ),
      );

      await tester.tap(find.text('Gallery'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('run-r3-scan')));
      await tester.pumpAndSettle();

      expect(find.text('Scanned packaged food'), findsOneWidget);
    });
  });

  group('QA-SHOPPING-PROVENANCE-005 & QA-SMART-PANTRY-006', () {
    testWidgets('preserves USER_ADDED, LOW_STOCK, and RECIPE_PLAN provenance badges', (tester) async {
      final httpClient = MockClient((request) async {
        final path = request.url.path;
        if (path == '/api/v1/pantry') {
          return http.Response(jsonEncode([]), 200);
        }
        if (path == '/api/v1/recipes/recommendations') {
          return http.Response(jsonEncode([]), 200);
        }
        if (path == '/api/v1/recipes/use-soon') {
          return http.Response(jsonEncode({'suggestions': [], 'limitation': ''}), 200);
        }
        if (path == '/api/v1/shopping-list') {
          return http.Response(
            jsonEncode([
              {
                'id': 'item-user',
                'name': 'Almond Milk',
                'checked': false,
                'source': 'USER_ADDED',
              },
              {
                'id': 'item-low',
                'name': 'Olive Oil',
                'checked': false,
                'source': 'LOW_STOCK',
              },
              {
                'id': 'item-plan',
                'name': 'Lentils',
                'checked': false,
                'source': 'RECIPE_PLAN',
                'quantity': 200,
                'unit': 'g',
              },
            ]),
            200,
          );
        }
        return http.Response('{"detail":"not found"}', 404);
      });

      final products = ProductApi(ApiClient(baseUrl: 'http://127.0.0.1:8000', client: httpClient));

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: PantryScreen(products: products),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(find.text('Added by you'), 500);
      expect(find.text('Added by you'), findsOneWidget);
      expect(find.text('From your low-stock threshold'), findsOneWidget);
      expect(find.textContaining('From your planned recipe'), findsOneWidget);
    });

    testWidgets('exposes all 5 Smart Pantry modes and displays deficits', (tester) async {
      final httpClient = MockClient((request) async {
        final path = request.url.path;
        if (path == '/api/v1/pantry') {
          return http.Response(
            jsonEncode([
              {
                'id': 'p1',
                'name': 'Chickpeas',
                'quantity': 400,
                'unit': 'g',
                'item_role': 'INGREDIENT',
              }
            ]),
            200,
          );
        }
        if (path == '/api/v1/recipes/recommendations') {
          return http.Response(
            jsonEncode([
              {
                'recipe_id': 'curry-1',
                'title': 'Chickpea Curry',
                'coverage': 0.67,
                'required_ingredients': ['Chickpeas', 'Coconut Milk', 'Curry Paste'],
                'missing_required': ['Coconut Milk'],
                'available_substitutions': [],
                'source_version': '1.0',
                'preparation_complexity': {
                  'band': 'SIMPLE',
                  'written_steps': 4,
                  'required_ingredients': 3,
                  'limitation': '',
                },
                'deficits': [
                  {
                    'name': 'Coconut Milk',
                    'required_amount': 200,
                    'available_amount': 0,
                    'deficit_amount': 200,
                    'unit': 'ml',
                  }
                ],
              }
            ]),
            200,
          );
        }
        if (path == '/api/v1/recipes/use-soon') {
          return http.Response(jsonEncode({'suggestions': [], 'limitation': ''}), 200);
        }
        if (path == '/api/v1/shopping-list') {
          return http.Response(jsonEncode([]), 200);
        }
        return http.Response('{"detail":"not found"}', 404);
      });

      final products = ProductApi(ApiClient(baseUrl: 'http://127.0.0.1:8000', client: httpClient));

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: PantryScreen(products: products),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Verify all 5 Smart Pantry modes exist
      expect(find.text('All pantry'), findsOneWidget);
      expect(find.text('Selected ingredients'), findsOneWidget);
      expect(find.text('Expiring soon'), findsOneWidget);
      expect(find.text('Leftovers'), findsOneWidget);
      expect(find.text('Meal plan'), findsOneWidget);

      // Verify recipe recommendation card
      expect(find.text('Chickpea Curry'), findsOneWidget);
      expect(find.text('67%'), findsOneWidget);

      // Tap recipe to open dialog
      await tester.tap(find.text('Chickpea Curry'));
      await tester.pumpAndSettle();

      expect(find.text('Coverage: 67%'), findsOneWidget);
      expect(find.text('Required: Chickpeas, Coconut Milk, Curry Paste'), findsOneWidget);
      expect(find.text('Missing: Coconut Milk'), findsOneWidget);
      expect(find.textContaining('deficit 200.0 ml'), findsOneWidget);

      // Tap + button in dialog to scale to 2 servings
      await tester.tap(find.descendant(
        of: find.byType(AlertDialog),
        matching: find.byIcon(Icons.add),
      ));
      await tester.pumpAndSettle();
      expect(find.textContaining('deficit 400.0 ml'), findsOneWidget);
    });

    testWidgets('QA-SCAN-GEN-007 renders Per cookie column and preserved decimals', (tester) async {
      final snapshot = const ScanSnapshot(
        scanId: 'cookie-scan',
        status: 'COMPLETED',
        confidenceLevel: 'HIGH',
        confidence: 0.94,
        warnings: [],
        ocrText: 'Energy 2098 kJ 502 kcal Fat 26.0g Salt 0.90g',
        barcodeValues: [],
        totalMilliseconds: 150,
        qualityStatus: 'ACCEPTABLE',
        productCandidates: ['Oat Biscuits'],
        brandCandidates: ['Bakery'],
        allergenText: 'Gluten',
        ingredientText: 'Oats, wheat flour, sugar, butter, salt',
        nutrition: NutritionSnapshot(
          basis: 'PER_100_G',
          columns: ['per 100 g', 'per cookie'],
          servingSizeValue: '23',
          servingSizeUnit: 'g',
          confidence: 0.92,
          rows: [
            NutritionTableRow(
              label: 'total fat',
              rawLabel: 'Fat',
              canonicalLabel: 'total fat',
              matchConfidence: 0.95,
              values: ['26.0', '5.9'],
              rawValues: ['26.0g', '5.9g'],
              units: ['g', 'g'],
              confidence: 0.95,
              parsedValues: [
                NutritionValue(value: '26.0', unit: 'g', basis: 'PER_100_G', sourceBasisText: 'per 100 g'),
                NutritionValue(value: '5.9', unit: 'g', basis: 'PER_SERVING', sourceBasisText: 'per cookie'),
              ],
            ),
            NutritionTableRow(
              label: 'salt',
              rawLabel: 'Salt',
              canonicalLabel: 'salt',
              matchConfidence: 0.95,
              values: ['0.90', '0.20'],
              rawValues: ['0.90g', '0.20g'],
              units: ['g', 'g'],
              confidence: 0.95,
              parsedValues: [
                NutritionValue(value: '0.90', unit: 'g', basis: 'PER_100_G', sourceBasisText: 'per 100 g'),
                NutritionValue(value: '0.20', unit: 'g', basis: 'PER_SERVING', sourceBasisText: 'per cookie'),
              ],
            ),
          ],
        ),
        positiveSignals: [],
        thingsToWatch: [],
        insightsHighlights: [],
      );

      final dummyGateway = _DummyScanGateway()..nextResult = snapshot;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ScannerScreen(
              scanGateway: dummyGateway,
              imageSource: _FakeImageSource(),
              ownerId: 'user-1',
            ),
          ),
        ),
      );

      await tester.tap(find.text('Gallery'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('run-r3-scan')));
      await tester.pumpAndSettle();

      // Expect Per 100 g and Per cookie columns (never fake % RDA)
      expect(find.text('Per 100 g'), findsWidgets);
      expect(find.text('Per cookie'), findsWidgets);
      expect(find.text('% RDA'), findsNothing);

      // Verify decimal precision preserved
      expect(find.text('26.0 g'), findsWidgets);
      expect(find.text('5.9 g'), findsWidgets);
      expect(find.text('0.90 g'), findsWidgets);
      expect(find.text('0.20 g'), findsWidgets);
    });

    testWidgets('QA-SMART-PANTRY-006 deficit with UNIT_UNCERTAIN displays unit conversion uncertain warning', (tester) async {
      final httpClient = MockClient((request) async {
        final path = request.url.path;
        if (path == '/api/v1/pantry') {
          return http.Response(jsonEncode([]), 200);
        }
        if (path == '/api/v1/recipes/recommendations') {
          return http.Response(
            jsonEncode([
              {
                'recipe_id': 'chili-1',
                'title': 'Bean Chili',
                'coverage': 0.5,
                'servings': 1.0,
                'required_ingredients': ['Beans', 'Tomatoes'],
                'missing_required': ['Beans'],
                'available_substitutions': [],
                'source_version': '1.0',
                'preparation_complexity': {
                  'band': 'SIMPLE',
                  'written_steps': 3,
                  'required_ingredients': 2,
                  'limitation': '',
                },
                'deficits': [
                  {
                    'ingredient': 'Beans',
                    'required_quantity': 150,
                    'available_quantity': null,
                    'missing_quantity': null,
                    'unit': 'g',
                    'status': 'UNIT_UNCERTAIN',
                  }
                ],
              }
            ]),
            200,
          );
        }
        if (path == '/api/v1/recipes/use-soon') {
          return http.Response(jsonEncode({'suggestions': [], 'limitation': ''}), 200);
        }
        if (path == '/api/v1/shopping-list') {
          return http.Response(jsonEncode([]), 200);
        }
        return http.Response('{"detail":"not found"}', 404);
      });

      final products = ProductApi(ApiClient(baseUrl: 'http://127.0.0.1:8000', client: httpClient));

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: PantryScreen(products: products),
          ),
        ),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('Bean Chili'));
      await tester.pumpAndSettle();

      expect(find.textContaining('(unit conversion uncertain)'), findsOneWidget);
    });

    test('QA-SCAN-PNG-008: PNG input transcoded to JPEG bytes aligns extension to .jpg and MIME to image/jpeg', () {
      final jpegBytes = Uint8List.fromList([0xFF, 0xD8, 0xFF, 0xE1, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46]);
      final resolved = DeviceScanImageSource.resolvePickedImage(
        bytes: jpegBytes,
        rawFilename: 'scaled_qa-576a7c-milk-fresh.png',
      );
      expect(resolved.mimeType, 'image/jpeg');
      expect(resolved.filename, 'scaled_qa-576a7c-milk-fresh.jpg');
      expect(resolved.bytes, jpegBytes);
    });

    test('QA-SCAN-PNG-008: True PNG bytes preserve .png and image/png', () {
      final pngBytes = Uint8List.fromList([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00]);
      final resolved = DeviceScanImageSource.resolvePickedImage(
        bytes: pngBytes,
        rawFilename: 'nutrition_label.png',
      );
      expect(resolved.mimeType, 'image/png');
      expect(resolved.filename, 'nutrition_label.png');
      expect(resolved.bytes, pngBytes);
    });
  });
}
