import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:nutrilens_x/scanner_screen.dart';
import 'package:nutrilens_x/services/local_reminders.dart';
import 'package:nutrilens_x/services/scan_api.dart';
import 'package:nutrilens_x/services/client_inference.dart';

class _ImageSource implements ScanImageSource {
  @override
  Future<PickedScanImage?> pick(ImageSource source) async {
    return PickedScanImage(
      bytes: Uint8List.fromList([1, 2, 3]),
      filename: 'fixture.png',
      mimeType: 'image/png',
    );
  }
}

class _Gateway implements ScanGateway {
  _Gateway({this.allergenText = 'MILK'});
  final String allergenText;
  int scanCalls = 0;
  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) async {
    scanCalls++;
    return ScanSnapshot(
      scanId: 'scan-test',
      status: 'COMPLETED_WITH_WARNINGS',
      confidenceLevel: 'LOW',
      confidence: 0.42,
      warnings: ['OCR model unavailable.'],
      ocrText: 'RAW OCR MUST STAY IN TECHNICAL DETAILS',
      barcodeValues: [],
      productCandidates: ['Low Fat Cow Milk'],
      brandCandidates: ['Country Delight'],
      qualityStatus: 'MEDIUM',
      totalMilliseconds: 22,
      nutrition: NutritionSnapshot(
        basis: 'PER_100_ML',
        columns: ['per 100 ml', 'per serving'],
        rows: [
          NutritionTableRow(
            label: 'protein',
            rawLabel: 'rotein',
            canonicalLabel: 'protein',
            matchConfidence: 0.9,
            values: ['3.6', '9'],
            rawValues: ['3.6 g', '9 g'],
            units: ['g', 'g'],
            confidence: 0.88,
          ),
          NutritionTableRow(
            label: 'sodium',
            rawLabel: 'sdium',
            canonicalLabel: 'sodium',
            matchConfidence: 0.89,
            values: ['45', '112'],
            rawValues: ['45 mg', '112 mg'],
            units: ['mg', 'mg'],
            confidence: 0.86,
          ),
        ],
        servingSizeValue: '250',
        servingSizeUnit: 'ml',
        confidence: 0.82,
      ),
      ingredientText: 'Pasteurized cow milk',
      allergenText: allergenText,
      ingredientConfidence: 0.9,
      allergenConfidence: 0.94,
      stageConfidences: {'ocr': 0.92, 'nutrition_parsing': 0.82},
      confidenceExplanations: ['Structured extraction needs review.'],
      timings: {'ocr_ms': 12, 'total_ms': 22},
    );
  }
}

class _ClientInference implements ClientInferenceGateway {
  _ClientInference({this.available = true});
  final bool available;
  int calls = 0;
  @override
  Future<ClientOcrEvidence?> recognizeText(Uint8List bytes) async {
    calls++;
    if (!available) return null;
    return const ClientOcrEvidence(
      contractVersion: clientInferenceContractVersion,
      platform: 'ANDROID',
      appVersion: '1.0.0+1',
      source: clientAndroidMlKit,
      ocrProvider: androidMlKitOcrProvider,
      ocrProviderVersion: '16.0.1',
      coldStart: false,
      elapsedMilliseconds: 12,
      imageWidth: 100,
      imageHeight: 100,
      sourceImageSha256:
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      orientationDegrees: 0,
      text: 'Milk',
      blocks: [],
    );
  }
}

class _ResumableGateway extends _Gateway implements ResumableScanGateway {
  final progress = StreamController<ScanJobProgress>.broadcast();
  final completion = Completer<ScanSnapshot?>();
  int resumeCalls = 0;
  int uploads = 0;
  bool failNextResume = false;
  bool pending = true;
  ScanJobProgress? latest;

  @override
  Stream<ScanJobProgress> get jobProgress => progress.stream;

  @override
  ScanJobProgress? get currentJobProgress => latest;

  @override
  Future<bool> hasPendingJob() async => pending;

  @override
  Future<ScanSnapshot?> resumePendingJob() async {
    resumeCalls++;
    if (failNextResume) {
      failNextResume = false;
      throw const ScanApiException(
        'Connection interrupted. Resume your saved scan.',
      );
    }
    return completion.future;
  }

  void emit(String state) {
    latest = ScanJobProgress(ownerId: 'owner', jobId: 'job-test', state: state);
    progress.add(latest!);
  }

  Future<void> complete() async {
    pending = false;
    emit('COMPLETE');
    completion.complete(
      await super.scan(
        bytes: Uint8List(0),
        filename: '',
        mimeType: 'image/png',
        kind: 'product',
      ),
    );
  }

  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) {
    uploads++;
    return super.scan(
      bytes: bytes,
      filename: filename,
      mimeType: mimeType,
      kind: kind,
    );
  }
}

class _EvidenceGateway implements ClientEvidenceGateway {
  _EvidenceGateway({this.mode = AndroidClientInferenceMode.shadow});
  final AndroidClientInferenceMode mode;
  int validationCalls = 0;
  @override
  Future<ClientInferenceCapabilities> capabilities() async =>
      ClientInferenceCapabilities(
        contractVersion: clientInferenceContractVersion,
        androidMode: mode,
        evidenceUse: mode == AndroidClientInferenceMode.preferred
            ? 'SERVER_PARSED_CLIENT_EVIDENCE'
            : 'SHADOW_COMPARISON_ONLY',
        serverResultAuthoritative: true,
        serverFallbackRequired: mode != AndroidClientInferenceMode.preferred,
      );

  @override
  Future<ClientEvidenceValidation> validate(
    ClientOcrEvidence evidence, {
    required Uint8List imageBytes,
    required String filename,
    required String mimeType,
  }) async {
    validationCalls++;
    return ClientEvidenceValidation(
      decision: 'CLIENT_EVIDENCE_ACCEPTED',
      acceptedFor: 'SHADOW_COMPARISON_ONLY',
      source: evidence.source,
      evidenceSha256:
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      sourceImageSha256: evidence.sourceImageSha256,
      canonicalLineCount: evidence.lineCount,
      canonicalTextSha256:
          'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
      imageBindingVerified: true,
      dimensionsBindingVerified: true,
      eligibleForPreferredPath: true,
      warnings: const ['Untrusted.'],
    );
  }
}

class _PreferredGateway extends _Gateway implements ClientEvidenceScanGateway {
  int evidenceCalls = 0;
  @override
  Future<ScanSnapshot> scanWithClientEvidence({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
    required ClientOcrEvidence evidence,
    required ClientInferenceCapabilities capabilities,
  }) async {
    evidenceCalls++;
    expect(bytes, [1, 2, 3]);
    expect(filename, 'fixture.png');
    expect(mimeType, 'image/png');
    expect(kind, 'product');
    expect(capabilities.androidMode, AndroidClientInferenceMode.preferred);
    expect(evidence.source, clientAndroidMlKit);
    return const ScanSnapshot(
      scanId: 'preferred-scan',
      status: 'COMPLETED',
      confidenceLevel: 'MEDIUM',
      confidence: 0.7,
      warnings: [],
      ocrText: 'DEVICE OCR SOURCE',
      barcodeValues: [],
      productCandidates: ['Preferred label'],
      qualityStatus: 'MEDIUM',
      totalMilliseconds: 20,
      clientEvidenceDecision: 'CLIENT_EVIDENCE_ACCEPTED',
      serverFallbackRequired: false,
    );
  }
}

class _ReminderCoordinator extends LocalReminderCoordinator {
  _ReminderCoordinator()
    : super(store: _UnusedReminderStore(), platform: _UnusedReminderPlatform());

  String? notifiedOwner;
  String? notifiedProduct;

  @override
  Future<void> notifyScanCompleted(String ownerId, String productName) async {
    notifiedOwner = ownerId;
    notifiedProduct = productName;
  }
}

class _UnusedReminderStore implements LocalReminderStore {
  @override
  Future<LocalReminderPreferences> load(String ownerId) async =>
      const LocalReminderPreferences();

  @override
  Future<void> save(
    String ownerId,
    LocalReminderPreferences preferences,
  ) async {}
}

class _UnusedReminderPlatform implements LocalReminderPlatform {
  @override
  Future<void> clearSchedules() async {}

  @override
  Future<void> initialize() async {}

  @override
  Future<ReminderPermission> permission() async => ReminderPermission.denied;

  @override
  Future<void> replaceSchedules(List<LocalReminderSchedule> schedules) async {}

  @override
  Future<ReminderPermission> requestPermission() async =>
      ReminderPermission.denied;

  @override
  Future<void> show({
    required int id,
    required String title,
    required String body,
    required String payload,
  }) async {}
}

Future<void> _runScan(WidgetTester tester) async {
  await tester.tap(find.text('Gallery'));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('run-r3-scan')));
  await tester.pumpAndSettle();
}

void main() {
  for (final mode in AndroidClientInferenceMode.values) {
    testWidgets('$mode selects only the authorized scan path', (tester) async {
      final gateway = _PreferredGateway();
      final inference = _ClientInference();
      final evidence = _EvidenceGateway(mode: mode);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ScannerScreen(
              scanGateway: gateway,
              imageSource: _ImageSource(),
              clientInferenceGateway: inference,
              clientEvidenceGateway: evidence,
            ),
          ),
        ),
      );
      await _runScan(tester);
      final preferred = mode == AndroidClientInferenceMode.preferred;
      expect(gateway.evidenceCalls, preferred ? 1 : 0);
      expect(gateway.scanCalls, preferred ? 0 : 1);
      expect(
        evidence.validationCalls,
        mode == AndroidClientInferenceMode.shadow ? 1 : 0,
      );
      expect(
        inference.calls,
        mode == AndroidClientInferenceMode.disabled ? 0 : 1,
      );
      expect(find.byKey(const Key('scan-result')), findsOneWidget);
      if (preferred) {
        expect(
          find.text('On-device label evidence validated by the server.'),
          findsOneWidget,
        );
        expect(find.byKey(const Key('client-inference-shadow')), findsNothing);
        expect(find.text('DEVICE OCR SOURCE'), findsNothing);
      }
    });
  }

  testWidgets(
    'preferred with unavailable native OCR retains enhanced fallback',
    (tester) async {
      final gateway = _PreferredGateway();
      final evidence = _EvidenceGateway(
        mode: AndroidClientInferenceMode.preferred,
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ScannerScreen(
              scanGateway: gateway,
              imageSource: _ImageSource(),
              clientInferenceGateway: _ClientInference(available: false),
              clientEvidenceGateway: evidence,
            ),
          ),
        ),
      );
      await _runScan(tester);
      expect(gateway.evidenceCalls, 0);
      expect(gateway.scanCalls, 1);
      expect(evidence.validationCalls, 0);
      expect(find.byKey(const Key('scan-result')), findsOneWidget);
    },
  );

  for (final statement in [
    'May contain Milk',
    'Free from Milk',
    'Contains no milk',
    'Contains: Milk',
  ]) {
    testWidgets(
      'allergen display preserves $statement without rewriting modality',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: ScannerScreen(
                scanGateway: _Gateway(allergenText: statement),
                imageSource: _ImageSource(),
              ),
            ),
          ),
        );
        await _runScan(tester);
        expect(find.text('Allergen statement: $statement'), findsOneWidget);
        expect(find.text('Contains: $statement'), findsNothing);
      },
    );
  }
  testWidgets(
    'reopening resumes saved job and lifecycle re-entry does not poll twice',
    (tester) async {
      final gateway = _ResumableGateway();
      final reminders = _ReminderCoordinator();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ScannerScreen(
              scanGateway: gateway,
              localReminders: reminders,
              ownerId: 'owner',
            ),
          ),
        ),
      );
      await tester.pump();
      expect(gateway.resumeCalls, 1);
      gateway.emit('QUEUED');
      await tester.pump();
      expect(find.byKey(const Key('scan-job-progress')), findsOneWidget);
      expect(find.text('Your scan is queued.'), findsWidgets);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(gateway.resumeCalls, 1);
      gateway.emit('PREPROCESSING');
      await tester.pump();
      expect(find.text('Running an enhanced scan…'), findsWidgets);
      await gateway.complete();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('scan-result')), findsOneWidget);
      expect(find.text('Low Fat Cow Milk'), findsOneWidget);
      expect(gateway.uploads, 0);
      expect(reminders.notifiedOwner, 'owner');
      expect(reminders.notifiedProduct, 'Low Fat Cow Milk');
      await tester.pumpWidget(const SizedBox());
      await gateway.progress.close();
    },
  );

  testWidgets(
    'interrupted resume exposes a retry that never requires a selected image',
    (tester) async {
      final gateway = _ResumableGateway()..failNextResume = true;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: ScannerScreen(scanGateway: gateway)),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('resume-scan')), findsOneWidget);
      expect(find.byKey(const Key('scan-error')), findsOneWidget);
      await tester.tap(find.byKey(const Key('resume-scan')));
      await tester.pump();
      expect(gateway.resumeCalls, 2);
      expect(gateway.uploads, 0);
      await gateway.complete();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('resume-scan')), findsNothing);
      expect(find.byKey(const Key('scan-result')), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await gateway.progress.close();
    },
  );

  testWidgets('picks an image, uploads it, and displays uncertainty', (
    tester,
  ) async {
    String? askedAboutScan;
    final reminders = _ReminderCoordinator();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ScannerScreen(
            scanGateway: _Gateway(),
            imageSource: _ImageSource(),
            clientInferenceGateway: _ClientInference(),
            clientEvidenceGateway: _EvidenceGateway(),
            localReminders: reminders,
            ownerId: 'owner',
            onAskNutri: (scanId) => askedAboutScan = scanId,
          ),
        ),
      ),
    );

    await tester.tap(find.text('Gallery'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('run-r3-scan')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('scan-result')), findsOneWidget);
    expect(find.text('Low Fat Cow Milk'), findsOneWidget);
    expect(find.text('Country Delight'), findsOneWidget);
    expect(find.byKey(const Key('explicit-allergen')), findsOneWidget);
    expect(find.text('Allergen statement: Milk'), findsOneWidget);
    expect(find.text('Nutrition snapshot'), findsOneWidget);
    expect(find.text('Ingredient summary'), findsOneWidget);
    expect(find.text('Pasteurized cow milk'), findsOneWidget);
    expect(find.byKey(const Key('nutrition-table')), findsOneWidget);
    expect(find.text('3.6 g'), findsWidgets);
    expect(find.text('RAW OCR MUST STAY IN TECHNICAL DETAILS'), findsNothing);
    expect(find.byKey(const Key('client-inference-shadow')), findsOneWidget);
    expect(reminders.notifiedOwner, 'owner');
    expect(reminders.notifiedProduct, 'Low Fat Cow Milk');
    expect(
      find.textContaining('Evidence suitable for faster scans.'),
      findsOneWidget,
    );

    await tester.drag(find.byType(ListView), const Offset(0, -1000));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ask-nutri-about-scan')));
    expect(askedAboutScan, 'scan-test');
    await tester.tap(find.text('Technical details'));
    await tester.pumpAndSettle();

    expect(find.textContaining('LOW (42%)'), findsOneWidget);
    expect(find.text('• OCR model unavailable.'), findsOneWidget);
    expect(find.text('RAW OCR MUST STAY IN TECHNICAL DETAILS'), findsOneWidget);
  });

  testWidgets('Retry scan clears error banner and retries successfully', (tester) async {
    final delegate = _Gateway();
    final failingGateway = _FailingThenSucceedingGateway(delegate);
    final imageSource = _ImageSource();

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ScannerScreen(
            scanGateway: failingGateway,
            imageSource: imageSource,
          ),
        ),
      ),
    );

    // Pick image
    await tester.tap(find.text('Gallery'));
    await tester.pumpAndSettle();

    // First scan attempt fails
    await tester.tap(find.byKey(const Key('run-r3-scan')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('scan-error')), findsOneWidget);
    expect(find.byKey(const Key('scan-retry-button')), findsOneWidget);

    // Tap retry button: error cleared immediately, scan retries
    await tester.tap(find.byKey(const Key('scan-retry-button')));
    await tester.pump();
    expect(find.byKey(const Key('scan-error')), findsNothing);

    await tester.pumpAndSettle();
    expect(find.byKey(const Key('scan-result')), findsOneWidget);
    expect(failingGateway.calls, 2);
  });
}

class _FailingThenSucceedingGateway implements ScanGateway {
  _FailingThenSucceedingGateway(this.delegate);
  final ScanGateway delegate;
  int calls = 0;

  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) async {
    calls++;
    if (calls == 1) {
      throw const ScanApiException('Enhanced scan is temporarily unavailable.');
    }
    return delegate.scan(
      bytes: bytes,
      filename: filename,
      mimeType: mimeType,
      kind: kind,
    );
  }
}

