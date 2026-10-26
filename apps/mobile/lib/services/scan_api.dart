import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import 'api_client.dart';
import 'client_inference.dart';

class NutritionValue {
  const NutritionValue({
    required this.value,
    required this.unit,
    required this.basis,
    this.resolvedServing,
    this.sourceBasisText,
  });

  factory NutritionValue.fromJson(Map<String, dynamic> json) => NutritionValue(
    value: json['value']?.toString() ?? '',
    unit: json['unit']?.toString() ?? '',
    basis: json['basis']?.toString() ?? 'UNKNOWN',
    resolvedServing: json['resolved_serving']?.toString(),
    sourceBasisText: json['source_basis_text']?.toString(),
  );

  final String value;
  final String unit;
  final String basis;
  final String? resolvedServing;
  final String? sourceBasisText;
}

class NutritionTableRow {
  const NutritionTableRow({
    required this.label,
    required this.rawLabel,
    required this.canonicalLabel,
    required this.matchConfidence,
    required this.values,
    required this.rawValues,
    required this.units,
    required this.confidence,
    this.parsedValues = const [],
  });

  factory NutritionTableRow.fromJson(Map<String, dynamic> json) =>
      NutritionTableRow(
        label: _boundedText(json['label'], 120),
        rawLabel: _boundedText(json['raw_label'], 120),
        canonicalLabel: _optionalBoundedText(json['canonical_label'], 120),
        matchConfidence: _confidence(json['match_confidence']),
        values: _boundedStrings(json['values'], maxItems: 8, maxLength: 80),
        rawValues: _boundedStrings(
          json['raw_values'],
          maxItems: 8,
          maxLength: 80,
        ),
        units: _boundedStrings(json['units'], maxItems: 8, maxLength: 24),
        confidence: _confidence(json['confidence']),
        parsedValues: (json['parsed_values'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(NutritionValue.fromJson)
            .toList(growable: false),
      );

  final String label;
  final String rawLabel;
  final String? canonicalLabel;
  final double? matchConfidence;
  final List<String> values;
  final List<String> rawValues;
  final List<String> units;
  final double? confidence;
  final List<NutritionValue> parsedValues;

  String get displayLabel => (canonicalLabel?.isNotEmpty ?? false)
      ? canonicalLabel!
      : label.isNotEmpty
      ? label
      : rawLabel;

  Map<String, dynamic> toCacheJson() => {
    'label': label,
    'raw_label': rawLabel,
    'canonical_label': canonicalLabel,
    'match_confidence': matchConfidence,
    'values': values,
    'raw_values': rawValues,
    'units': units,
    'confidence': confidence,
    'parsed_values': parsedValues
        .map((p) => {
              'value': p.value,
              'unit': p.unit,
              'basis': p.basis,
              if (p.resolvedServing != null) 'resolved_serving': p.resolvedServing,
            })
        .toList(growable: false),
  };
}

class NutritionSnapshot {
  const NutritionSnapshot({
    required this.basis,
    required this.columns,
    required this.rows,
    required this.servingSizeValue,
    required this.servingSizeUnit,
    required this.confidence,
  });

  const NutritionSnapshot.empty()
    : basis = 'UNKNOWN',
      columns = const [],
      rows = const [],
      servingSizeValue = null,
      servingSizeUnit = null,
      confidence = null;

  factory NutritionSnapshot.fromJson(Map<String, dynamic> json) =>
      NutritionSnapshot(
        basis: _nutritionBasis(json['basis']),
        columns: _boundedStrings(
          json['table_columns'],
          maxItems: 8,
          maxLength: 80,
        ),
        rows: (json['table_rows'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .take(64)
            .map(NutritionTableRow.fromJson)
            .where((row) => row.displayLabel.isNotEmpty)
            .toList(growable: false),
        servingSizeValue: _optionalBoundedText(json['serving_size_value'], 40),
        servingSizeUnit: _optionalBoundedText(json['serving_size_unit'], 24),
        confidence: _confidence(json['confidence']),
      );

  final String basis;
  final List<String> columns;
  final List<NutritionTableRow> rows;
  final String? servingSizeValue;
  final String? servingSizeUnit;
  final double? confidence;

  String? get servingSize {
    final value = servingSizeValue;
    if (value == null || value.isEmpty) return null;
    final unit = servingSizeUnit;
    return unit == null || unit.isEmpty ? value : '$value $unit';
  }

  Map<String, dynamic> toCacheJson() => {
    'basis': basis,
    'table_columns': columns,
    'table_rows': rows.map((row) => row.toCacheJson()).toList(growable: false),
    'serving_size_value': servingSizeValue,
    'serving_size_unit': servingSizeUnit,
    'confidence': confidence,
  };
}

class ScanSnapshot {
  const ScanSnapshot({
    required this.scanId,
    required this.status,
    required this.confidenceLevel,
    required this.confidence,
    required this.warnings,
    required this.ocrText,
    required this.barcodeValues,
    required this.productCandidates,
    required this.qualityStatus,
    required this.totalMilliseconds,
    this.brandCandidates = const [],
    this.qrValues = const [],
    this.nutrition = const NutritionSnapshot.empty(),
    this.ingredientText = '',
    this.allergenText = '',
    this.ingredientConfidence,
    this.allergenConfidence,
    this.stageConfidences = const {},
    this.confidenceExplanations = const [],
    this.timings = const {},
    this.clientEvidenceDecision,
    this.clientEvidenceReasons = const [],
    this.serverFallbackRequired,
    this.isOfflineCache = false,
    this.cachedAt,
    this.insightsHighlights = const [],
    this.positiveSignals = const [],
    this.thingsToWatch = const [],
    this.allergenSummary,
    this.servingContext,
    this.askNutriSuggestions = const [],
  });

  factory ScanSnapshot.fromJson(Map<String, dynamic> json) {
    final summary = json['confidence_summary'];
    final qualityMap = json['image_quality'];
    final ocrMap = json['ocr_results'];
    final nutritionMap = _jsonMap(json['nutrition']);
    final ingredientsMap = _jsonMap(json['ingredients']);
    final insightsMap = _jsonMap(json['insights']);
    if (json['scan_id'] is! String ||
        json['status'] is! String ||
        summary is! Map<String, dynamic> ||
        qualityMap is! Map<String, dynamic> ||
        ocrMap is! Map<String, dynamic>) {
      throw const FormatException('Invalid R3 scan response');
    }
    final firstQuality = qualityMap.values
        .whereType<Map<String, dynamic>>()
        .firstOrNull;
    final firstOcr = ocrMap.values
        .whereType<Map<String, dynamic>>()
        .firstOrNull;
    final timings = _nonNegativeNumberMap(json['timings']);
    return ScanSnapshot(
      scanId: json['scan_id'] as String,
      status: json['status'] as String,
      confidenceLevel: summary['level']?.toString() ?? 'UNRELIABLE',
      confidence: (summary['numeric_score'] as num?)?.toDouble(),
      warnings: _boundedStrings(json['warnings'], maxItems: 32, maxLength: 300),
      ocrText: _boundedText(firstOcr?['text'], 20_000),
      barcodeValues: _candidateValues(json['barcode_results']),
      qrValues: _candidateValues(json['qr_results']),
      productCandidates: _candidateValues(json['product_name_candidates']),
      brandCandidates: _candidateValues(json['brand_candidates']),
      qualityStatus:
          firstQuality?['quality_status']?.toString() ?? 'UNAVAILABLE',
      totalMilliseconds: timings['total_ms'] ?? 0,
      nutrition: NutritionSnapshot.fromJson(nutritionMap),
      ingredientText: _boundedText(ingredientsMap['raw_text'], 1500),
      allergenText: _boundedText(ingredientsMap['allergen_text'], 500),
      ingredientConfidence: _confidence(ingredientsMap['confidence']),
      allergenConfidence: _confidence(ingredientsMap['allergen_confidence']),
      stageConfidences: _confidenceMap(summary['sources']),
      confidenceExplanations: _boundedStrings(
        summary['explanation'],
        maxItems: 16,
        maxLength: 300,
      ),
      timings: timings,
      clientEvidenceDecision: _clientDecision(json['client_evidence_decision']),
      clientEvidenceReasons: _boundedStrings(
        json['client_evidence_reasons'],
        maxItems: 16,
        maxLength: 160,
      ),
      serverFallbackRequired: json['server_fallback_required'] is bool
          ? json['server_fallback_required'] as bool
          : null,
      insightsHighlights: _boundedStrings(
        insightsMap['highlights'],
        maxItems: 8,
        maxLength: 300,
      ),
      positiveSignals: _boundedStrings(
        insightsMap['positive_signals'],
        maxItems: 8,
        maxLength: 300,
      ),
      thingsToWatch: _boundedStrings(
        insightsMap['things_to_watch'],
        maxItems: 8,
        maxLength: 300,
      ),
      allergenSummary: _boundedText(insightsMap['allergen_summary'], 300),
      servingContext: _boundedText(insightsMap['serving_context'], 300),
      askNutriSuggestions: _boundedStrings(
        insightsMap['ask_nutri_suggestions'],
        maxItems: 4,
        maxLength: 300,
      ),
    );
  }

  factory ScanSnapshot.fromCacheJson(
    Map<String, dynamic> json,
    DateTime cachedAt,
  ) => ScanSnapshot(
    scanId: json['scan_id'] as String,
    status: json['status']?.toString() ?? 'CACHED',
    confidenceLevel: json['confidence_level']?.toString() ?? 'UNRELIABLE',
    confidence: (json['confidence'] as num?)?.toDouble(),
    warnings: _strings(json['warnings']),
    ocrText: '',
    barcodeValues: const [],
    qrValues: _strings(json['qr_values']),
    productCandidates: _strings(json['product_candidates']),
    brandCandidates: _strings(json['brand_candidates']),
    qualityStatus: json['quality_status']?.toString() ?? 'UNAVAILABLE',
    totalMilliseconds: (json['total_milliseconds'] as num?)?.toDouble() ?? 0,
    nutrition: NutritionSnapshot.fromJson(_jsonMap(json['nutrition'])),
    ingredientText: _boundedText(json['ingredient_text'], 1500),
    allergenText: _boundedText(json['allergen_text'], 500),
    ingredientConfidence: _confidence(json['ingredient_confidence']),
    allergenConfidence: _confidence(json['allergen_confidence']),
    stageConfidences: _confidenceMap(json['stage_confidences']),
    confidenceExplanations: _boundedStrings(
      json['confidence_explanations'],
      maxItems: 16,
      maxLength: 300,
    ),
    isOfflineCache: true,
    cachedAt: cachedAt,
    insightsHighlights: _strings(json['insights_highlights']),
    positiveSignals: _strings(json['positive_signals']),
    thingsToWatch: _strings(json['things_to_watch']),
    allergenSummary: _boundedText(json['allergen_summary'], 300),
    servingContext: _boundedText(json['serving_context'], 300),
    askNutriSuggestions: _strings(json['ask_nutri_suggestions']),
  );

  final String scanId;
  final String status;
  final String confidenceLevel;
  final double? confidence;
  final List<String> warnings;
  final String ocrText;
  final List<String> barcodeValues;
  final List<String> qrValues;
  final List<String> productCandidates;
  final List<String> brandCandidates;
  final String qualityStatus;
  final double totalMilliseconds;
  final NutritionSnapshot nutrition;
  final String ingredientText;
  final String allergenText;
  final double? ingredientConfidence;
  final double? allergenConfidence;
  final Map<String, double> stageConfidences;
  final List<String> confidenceExplanations;
  final Map<String, double> timings;
  final String? clientEvidenceDecision;
  final List<String> clientEvidenceReasons;
  final bool? serverFallbackRequired;
  final bool isOfflineCache;
  final DateTime? cachedAt;
  final List<String> insightsHighlights;
  final List<String> positiveSignals;
  final List<String> thingsToWatch;
  final String? allergenSummary;
  final String? servingContext;
  final List<String> askNutriSuggestions;

  Map<String, dynamic> toCacheJson() => {
    'scan_id': scanId,
    'status': status,
    'confidence_level': confidenceLevel,
    'confidence': confidence,
    'warnings': warnings,
    'qr_values': qrValues,
    'product_candidates': productCandidates,
    'brand_candidates': brandCandidates,
    'quality_status': qualityStatus,
    'total_milliseconds': totalMilliseconds,
    'nutrition': nutrition.toCacheJson(),
    'ingredient_text': ingredientText,
    'allergen_text': allergenText,
    'ingredient_confidence': ingredientConfidence,
    'allergen_confidence': allergenConfidence,
    'stage_confidences': stageConfidences,
    'confidence_explanations': confidenceExplanations,
    'insights_highlights': insightsHighlights,
    'positive_signals': positiveSignals,
    'things_to_watch': thingsToWatch,
    'allergen_summary': allergenSummary,
    'serving_context': servingContext,
    'ask_nutri_suggestions': askNutriSuggestions,
  };
}

List<String> _strings(Object? value) {
  if (value is! List<dynamic>) return const [];
  return value.map((item) => item.toString()).toList(growable: false);
}

Map<String, dynamic> _jsonMap(Object? value) =>
    value is Map<String, dynamic> ? value : const {};

String _boundedText(Object? value, int maxLength) {
  final normalized =
      value?.toString().replaceAll(RegExp(r'\s+'), ' ').trim() ?? '';
  return normalized.length <= maxLength
      ? normalized
      : normalized.substring(0, maxLength).trimRight();
}

String? _optionalBoundedText(Object? value, int maxLength) {
  final normalized = _boundedText(value, maxLength);
  return normalized.isEmpty ? null : normalized;
}

List<String> _boundedStrings(
  Object? value, {
  required int maxItems,
  required int maxLength,
}) {
  if (value is! List<dynamic>) return const [];
  return value
      .take(maxItems)
      .map((item) => _boundedText(item, maxLength))
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
}

double? _confidence(Object? value) {
  final number = (value as num?)?.toDouble();
  if (number == null || !number.isFinite) return null;
  return number.clamp(0, 1).toDouble();
}

Map<String, double> _confidenceMap(Object? value) {
  if (value is! Map<String, dynamic>) return const {};
  final result = <String, double>{};
  for (final entry in value.entries.take(24)) {
    final key = _boundedText(entry.key, 80);
    final confidence = _confidence(entry.value);
    if (key.isNotEmpty && confidence != null) result[key] = confidence;
  }
  return Map.unmodifiable(result);
}

Map<String, double> _nonNegativeNumberMap(Object? value) {
  if (value is! Map<String, dynamic>) return const {};
  final result = <String, double>{};
  for (final entry in value.entries.take(24)) {
    final key = _boundedText(entry.key, 80);
    final number = (entry.value as num?)?.toDouble();
    if (key.isNotEmpty && number != null && number.isFinite && number >= 0) {
      result[key] = number;
    }
  }
  return Map.unmodifiable(result);
}

String _nutritionBasis(Object? value) => switch (value?.toString()) {
  'PER_100_G' => 'PER_100_G',
  'PER_100_ML' => 'PER_100_ML',
  'PER_SERVING' => 'PER_SERVING',
  _ => 'UNKNOWN',
};

String? _clientDecision(Object? value) => switch (value) {
  'CLIENT_EVIDENCE_ACCEPTED' => 'CLIENT_EVIDENCE_ACCEPTED',
  'SERVER_FALLBACK_REQUIRED' => 'SERVER_FALLBACK_REQUIRED',
  'CLIENT_EVIDENCE_INVALID' => 'CLIENT_EVIDENCE_INVALID',
  _ => null,
};

List<String> _candidateValues(Object? value) {
  if (value is! List<dynamic>) return const [];
  return value
      .whereType<Map<String, dynamic>>()
      .map((item) => item['value']?.toString() ?? '')
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
}

abstract interface class ScanGateway {
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  });
}

abstract interface class ClientEvidenceScanGateway {
  Future<ScanSnapshot> scanWithClientEvidence({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
    required ClientOcrEvidence evidence,
    required ClientInferenceCapabilities capabilities,
  });
}

/// A durable pointer only: no image, OCR, token or result is stored here.
class PendingScanJob {
  const PendingScanJob({required this.ownerId, required this.jobId});

  final String ownerId;
  final String jobId;
}

abstract interface class PendingScanJobStore {
  Future<PendingScanJob?> readPending(String ownerId);
  Future<void> writePending(PendingScanJob job);
  Future<void> clearPending(String ownerId, String jobId);
}

class ScanJobProgress {
  const ScanJobProgress({
    required this.ownerId,
    required this.jobId,
    required this.state,
  });

  final String ownerId;
  final String jobId;
  final String state;

  bool get isTerminal =>
      const {'COMPLETE', 'FAILED', 'TIMED_OUT'}.contains(state);

  String get message => switch (state) {
    'QUEUED' => 'Your scan is queued.',
    // The current server emits PREPROCESSING for the whole worker interval.
    // Do not invent finer OCR/ingredient progress that it does not report.
    'PREPROCESSING' => 'Running an enhanced scan…',
    'COMPLETE' => 'Your scan is ready.',
    'FAILED' => 'The scan could not be completed.',
    'TIMED_OUT' => 'The scan reached its processing deadline.',
    'RATE_LIMITED' => 'Your scan continues. Waiting before checking again…',
    'CONNECTION_INTERRUPTED' =>
      'Connection interrupted. Your scan is saved for resuming.',
    _ => 'Checking your saved scan…',
  };
}

/// Optional capability so non-durable/test scan gateways remain compatible.
abstract interface class ResumableScanGateway {
  Stream<ScanJobProgress> get jobProgress;
  ScanJobProgress? get currentJobProgress;
  Future<bool> hasPendingJob();
  Future<ScanSnapshot?> resumePendingJob();
}

abstract interface class ScanResultCache {
  Future<ScanSnapshot?> read(String userId);
  Future<void> write(String userId, ScanSnapshot snapshot);
  Future<void> clear();
}

class SecureScanResultCache implements ScanResultCache, PendingScanJobStore {
  const SecureScanResultCache({
    FlutterSecureStorage? storage,
    this.ttl = const Duration(hours: 24),
  }) : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'nutrilens_last_scan_v1';
  final FlutterSecureStorage _storage;
  final Duration ttl;
  static Future<void> _pendingOperations = Future<void>.value();

  static String _pendingKey(String ownerId) =>
      'nutrilens_pending_scan_v1_${base64Url.encode(utf8.encode(ownerId))}';

  // Serialize compare-and-clear with writes, including across cache instances.
  Future<T> _pendingOperation<T>(Future<T> Function() action) {
    final result = _pendingOperations.then((_) => action());
    _pendingOperations = result.then<void>((_) {}, onError: (Object _) {});
    return result;
  }

  Future<PendingScanJob?> _readPending(String ownerId) async {
    final encoded = await _storage.read(key: _pendingKey(ownerId));
    if (encoded == null) return null;
    final payload = jsonDecode(encoded);
    if (payload is! Map<String, dynamic> ||
        payload['version'] != 1 ||
        payload['owner_id'] != ownerId ||
        !_validJobId(payload['job_id'])) {
      throw const ScanApiException('The saved scan reference is invalid.');
    }
    return PendingScanJob(ownerId: ownerId, jobId: payload['job_id'] as String);
  }

  @override
  Future<PendingScanJob?> readPending(String ownerId) =>
      _pendingOperation(() => _readPending(ownerId));

  @override
  Future<void> writePending(PendingScanJob job) => _pendingOperation(() async {
    if (job.ownerId.isEmpty || !_validJobId(job.jobId)) {
      throw const ScanApiException('The saved scan reference is invalid.');
    }
    await _storage.write(
      key: _pendingKey(job.ownerId),
      value: jsonEncode({
        'version': 1,
        'owner_id': job.ownerId,
        'job_id': job.jobId,
      }),
    );
  });

  @override
  Future<void> clearPending(String ownerId, String jobId) =>
      _pendingOperation(() async {
        final current = await _readPending(ownerId);
        if (current?.jobId == jobId) {
          await _storage.delete(key: _pendingKey(ownerId));
        }
      });

  @override
  Future<ScanSnapshot?> read(String userId) async {
    final encoded = await _storage.read(key: _key);
    if (encoded == null) return null;
    try {
      final payload = jsonDecode(encoded) as Map<String, dynamic>;
      final cachedAt = DateTime.parse(payload['cached_at'] as String).toUtc();
      if (payload['version'] != 1 ||
          payload['user_id'] != userId ||
          DateTime.now().toUtc().difference(cachedAt) > ttl) {
        await clear();
        return null;
      }
      return ScanSnapshot.fromCacheJson(
        payload['snapshot'] as Map<String, dynamic>,
        cachedAt,
      );
    } on Object {
      await clear();
      return null;
    }
  }

  @override
  Future<void> write(String userId, ScanSnapshot snapshot) => _storage.write(
    key: _key,
    value: jsonEncode({
      'version': 1,
      'user_id': userId,
      'cached_at': DateTime.now().toUtc().toIso8601String(),
      'snapshot': snapshot.toCacheJson(),
    }),
  );

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

typedef UserIdProvider = String? Function();
typedef ScanDelay = Future<void> Function(Duration duration);

bool _validJobId(Object? value) =>
    value is String && RegExp(r'^[A-Za-z0-9_-]{1,160}$').hasMatch(value);

class ScanApi
    implements ScanGateway, ResumableScanGateway, ClientEvidenceScanGateway {
  ScanApi({
    required this.baseUrl,
    AccessTokenProvider? accessToken,
    UserIdProvider? userId,
    this.cache,
    PendingScanJobStore? pendingJobs,
    this.pollInterval = const Duration(seconds: 12),
    this.jobTimeout = const Duration(minutes: 10),
    ScanDelay? delay,
    http.Client? client,
    this.onUnauthorized,
  }) : _accessToken = accessToken ?? _noToken,
       _userId = userId ?? _noToken,
       _pendingJobs =
           pendingJobs ??
           (cache is PendingScanJobStore ? cache as PendingScanJobStore : null),
       _delay = delay ?? Future<void>.delayed,
       _client = client ?? http.Client();

  final String baseUrl;
  final AccessTokenProvider _accessToken;
  final UserIdProvider _userId;
  final ScanResultCache? cache;
  final PendingScanJobStore? _pendingJobs;
  final Duration pollInterval;
  final Duration jobTimeout;
  final ScanDelay _delay;
  final http.Client _client;
  final FutureOr<void> Function()? onUnauthorized;
  final _progress = StreamController<ScanJobProgress>.broadcast();
  final _operations = <String, Future<ScanSnapshot?>>{};
  ScanJobProgress? _latestProgress;

  @override
  Stream<ScanJobProgress> get jobProgress =>
      _progress.stream.where((progress) => progress.ownerId == _userId());

  @override
  ScanJobProgress? get currentJobProgress =>
      _latestProgress?.ownerId == _userId() ? _latestProgress : null;

  String? get _authenticatedOwner {
    final owner = _userId();
    final token = _accessToken();
    return owner != null &&
            owner.isNotEmpty &&
            token != null &&
            token.isNotEmpty
        ? owner
        : null;
  }

  void _requireOwner(String ownerId) {
    if (_authenticatedOwner != ownerId) {
      throw const ScanApiException(
        'Sign in to the scan owner’s account to resume.',
      );
    }
  }

  void _publish(String? ownerId, String jobId, String state) {
    if (ownerId == null || _authenticatedOwner != ownerId) return;
    final progress = ScanJobProgress(
      ownerId: ownerId,
      jobId: jobId,
      state: state,
    );
    _latestProgress = progress;
    _progress.add(progress);
  }

  Future<ScanSnapshot?> _once(
    String ownerId,
    Future<ScanSnapshot?> Function() action,
  ) {
    final existing = _operations[ownerId];
    if (existing != null) return existing;
    late Future<ScanSnapshot?> operation;
    operation = Future<ScanSnapshot?>.sync(action).whenComplete(() {
      if (identical(_operations[ownerId], operation)) {
        _operations.remove(ownerId);
      }
    });
    _operations[ownerId] = operation;
    return operation;
  }

  Future<PendingScanJob?> _pendingFor(String ownerId) async {
    _requireOwner(ownerId);
    final pending = await _pendingJobs?.readPending(ownerId);
    _requireOwner(ownerId);
    if (pending != null && pending.ownerId != ownerId) {
      throw const ScanApiException(
        'The saved scan belongs to another account.',
      );
    }
    return pending;
  }

  @override
  Future<bool> hasPendingJob() async {
    final owner = _authenticatedOwner;
    return owner != null && await _pendingFor(owner) != null;
  }

  @override
  Future<ScanSnapshot?> resumePendingJob() {
    final owner = _authenticatedOwner;
    if (owner == null) return Future.value();
    return _once(owner, () async {
      final pending = await _pendingFor(owner);
      if (pending == null) return null;
      return _finishJob({'job_id': pending.jobId}, owner, immediate: true);
    });
  }

  static String? _noToken() => null;

  @override
  Future<ScanSnapshot> scan({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
  }) => _scanRequest(
    bytes: bytes,
    filename: filename,
    mimeType: mimeType,
    kind: kind,
  );

  @override
  Future<ScanSnapshot> scanWithClientEvidence({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
    required ClientOcrEvidence evidence,
    required ClientInferenceCapabilities capabilities,
  }) {
    if (capabilities.contractVersion != clientInferenceContractVersion ||
        capabilities.androidMode != AndroidClientInferenceMode.preferred ||
        capabilities.evidenceUse != 'SERVER_PARSED_CLIENT_EVIDENCE' ||
        !capabilities.serverResultAuthoritative ||
        capabilities.serverFallbackRequired) {
      throw const ScanApiException(
        'Client evidence is not enabled for this scan.',
      );
    }
    if (_authenticatedOwner == null) {
      throw const ScanApiException(
        'Sign in before submitting on-device label evidence.',
      );
    }
    if (!const {'product', 'ocr', 'image'}.contains(kind)) {
      throw const ScanApiException(
        'This scan type requires enhanced processing.',
      );
    }
    return _scanRequest(
      bytes: bytes,
      filename: filename,
      mimeType: mimeType,
      kind: kind,
      evidence: evidence,
    );
  }

  Future<ScanSnapshot> _scanRequest({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
    ClientOcrEvidence? evidence,
  }) async {
    final owner = _authenticatedOwner;
    if (owner == null) {
      return _submit(
        bytes: bytes,
        filename: filename,
        mimeType: mimeType,
        kind: kind,
      );
    }
    // Re-entry and repeated taps join the same operation. A pending job is
    // always resumed via GET, never replaced by another uploaded image.
    final result = await _once(owner, () async {
      final pending = await _pendingFor(owner);
      if (pending != null) {
        return _finishJob({'job_id': pending.jobId}, owner, immediate: true);
      }
      return _submit(
        bytes: bytes,
        filename: filename,
        mimeType: mimeType,
        kind: kind,
        ownerId: owner,
        evidence: evidence,
      );
    });
    // A concurrent initial resume may have found no job. It performed no
    // submission, so it is safe to proceed through the same serialized path.
    _requireOwner(owner);
    if (result == null) {
      return _scanRequest(
        bytes: bytes,
        filename: filename,
        mimeType: mimeType,
        kind: kind,
        evidence: evidence,
      );
    }
    return result;
  }

  Future<ScanSnapshot> _submit({
    required Uint8List bytes,
    required String filename,
    required String mimeType,
    required String kind,
    String? ownerId,
    ClientOcrEvidence? evidence,
  }) async {
    if (ownerId != null) _requireOwner(ownerId);
    final token = _accessToken();
    final asyncJob = token != null && token.isNotEmpty;
    final route = asyncJob ? '/api/v1/scan/jobs/$kind' : '/api/v1/scan/$kind';
    final endpoint = Uri.parse(
      '${baseUrl.replaceFirst(RegExp(r'/$'), '')}$route',
    );
    final request = http.MultipartRequest('POST', endpoint);
    if (asyncJob) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    request.files.add(
      http.MultipartFile.fromBytes(
        kind == 'product' ? 'files' : 'file',
        bytes,
        filename: filename,
        contentType: MediaType.parse(mimeType),
      ),
    );
    if (kind == 'product') request.fields['view_types'] = 'GENERAL';
    if (kind == 'product' || kind == 'ocr') {
      request.fields['languages'] = 'en';
    }
    if (evidence != null) {
      // Server validates untrusted evidence against these exact image bytes,
      // the current owner, rollout policy, quota and normal job idempotency.
      request.fields['evidence_json'] = jsonEncode(evidence.toJson());
    }
    http.StreamedResponse streamed;
    try {
      streamed = await _client
          .send(request)
          .timeout(const Duration(seconds: 35));
    } on TimeoutException catch (error) {
      return _offlineFallback(error);
    } on http.ClientException catch (error) {
      return _offlineFallback(error);
    }
    final response = await http.Response.fromStream(streamed);
    final decoded = jsonDecode(response.body);
    final expectedStatus = asyncJob ? 202 : 201;
    if (response.statusCode != expectedStatus) {
      if (ApiClient.isSessionExpired(response, decoded)) {
        await onUnauthorized?.call();
      }
      final detail = decoded is Map<String, dynamic> ? decoded['detail'] : null;
      final message = detail is Map<String, dynamic>
          ? detail['message']?.toString()
          : detail?.toString();
      throw ScanApiException(
        message ?? 'Backend returned ${response.statusCode}.',
      );
    }
    try {
      if (asyncJob) {
        final accepted = decoded as Map<String, dynamic>;
        final jobId = accepted['job_id'];
        if (!_validJobId(jobId)) {
          throw const ScanApiException('Backend returned an invalid scan job.');
        }
        if (ownerId != null) {
          // Persist the accepted pointer even if sign-out occurred in flight.
          // It is keyed to the owner who submitted, never the current account.
          await _pendingJobs?.writePending(
            PendingScanJob(ownerId: ownerId, jobId: jobId as String),
          );
          _requireOwner(ownerId);
        }
        return _finishJob(
          accepted,
          ownerId,
          // Fast-path responses are already terminal; do not add a polling
          // interval before showing the useful result.
          immediate: accepted['status'] == 'COMPLETE',
          fallbackToken: token,
        );
      }
      final resultJson = decoded as Map<String, dynamic>;
      final snapshot = ScanSnapshot.fromJson(resultJson);
      final userId = _userId();
      if (cache != null && userId != null && userId.isNotEmpty) {
        await cache!.write(userId, snapshot);
      }
      return snapshot;
    } on FormatException catch (error) {
      throw ScanApiException(
        'Backend returned an invalid scan response.',
        error,
      );
    }
  }

  Future<ScanSnapshot> _finishJob(
    Map<String, dynamic> accepted,
    String? ownerId, {
    bool immediate = false,
    String? fallbackToken,
  }) async {
    final jobId = accepted['job_id'] as String;
    try {
      final result = await _pollJob(
        accepted,
        ownerId,
        immediate: immediate,
        fallbackToken: fallbackToken,
      );
      if (ownerId != null) _requireOwner(ownerId);
      final snapshot = ScanSnapshot.fromJson(result);
      if (ownerId != null) {
        await cache?.write(ownerId, snapshot);
        _requireOwner(ownerId);
        await _pendingJobs?.clearPending(ownerId, jobId);
        _requireOwner(ownerId);
      }
      return snapshot;
    } on http.ClientException catch (error) {
      _publish(ownerId, jobId, 'CONNECTION_INTERRUPTED');
      throw ScanApiException(
        'Connection interrupted. Reopen the scanner or tap Resume scan; no new upload is needed.',
        error,
      );
    } on TimeoutException catch (error) {
      _publish(ownerId, jobId, 'CONNECTION_INTERRUPTED');
      throw ScanApiException(
        'The status check timed out. Your saved scan can be resumed without a new upload.',
        error,
      );
    }
  }

  Future<Map<String, dynamic>> _pollJob(
    Map<String, dynamic> accepted,
    String? ownerId, {
    bool immediate = false,
    String? fallbackToken,
  }) async {
    final jobId = accepted['job_id'];
    if (jobId is! String || jobId.isEmpty) {
      throw const ScanApiException('Backend returned an invalid scan job.');
    }
    final deadline = DateTime.now().add(jobTimeout);
    var current = accepted;
    var nextPollDelay = immediate ? Duration.zero : pollInterval;
    _publish(ownerId, jobId, current['status']?.toString() ?? 'RESUMING');
    while (DateTime.now().isBefore(deadline)) {
      if (ownerId != null) _requireOwner(ownerId);
      final state = current['status']?.toString();
      if (state == 'COMPLETE') {
        final result = current['result'];
        if (result is! Map<String, dynamic>) {
          throw const ScanApiException('Completed scan job has no result.');
        }
        return {
          ...result,
          for (final field in const [
            'client_evidence_decision',
            'client_evidence_reasons',
            'server_fallback_required',
          ])
            if ((current[field] ?? accepted[field]) != null)
              field: current[field] ?? accepted[field],
        };
      }
      if (state == 'FAILED' || state == 'TIMED_OUT') {
        if (ownerId != null) {
          await _pendingJobs?.clearPending(ownerId, jobId);
          _requireOwner(ownerId);
        }
        throw ScanApiException(
          current['error_message']?.toString() ?? 'The scan job failed safely.',
        );
      }
      await _delay(nextPollDelay);
      if (ownerId != null) _requireOwner(ownerId);
      final token = ownerId == null ? fallbackToken : _accessToken();
      final endpoint = Uri.parse(
        '${baseUrl.replaceFirst(RegExp(r'/$'), '')}/api/v1/scan/jobs/${Uri.encodeComponent(jobId)}',
      );
      final response = await _client
          .get(endpoint, headers: {'Authorization': 'Bearer $token'})
          .timeout(const Duration(seconds: 20));
      if (ownerId != null) _requireOwner(ownerId);
      if (response.statusCode == 429) {
        _publish(ownerId, jobId, 'RATE_LIMITED');
        nextPollDelay = _retryAfter(response);
        continue;
      }
      if (response.statusCode != 200) {
        Object? decodedError;
        try {
          decodedError = jsonDecode(response.body);
        } on Object {
          // Response body was not JSON
        }
        if (ApiClient.isSessionExpired(response, decodedError)) {
          await onUnauthorized?.call();
        }
        throw ScanApiException(
          'Unable to resume scan job (${response.statusCode}).',
        );
      }
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic> || decoded['job_id'] != jobId) {
        throw const ScanApiException(
          'Unable to resume scan job because its status was invalid.',
        );
      }
      current = decoded;
      _publish(ownerId, jobId, current['status']?.toString() ?? 'RESUMING');
      nextPollDelay = pollInterval;
    }
    throw const ScanApiException(
      'The scan is still processing. Reopen the scanner to resume it.',
    );
  }

  Duration _retryAfter(http.Response response) {
    final seconds = int.tryParse(response.headers['retry-after'] ?? '');
    if (seconds == null) return const Duration(seconds: 60);
    return Duration(seconds: seconds.clamp(1, 60));
  }

  Future<ScanSnapshot> _offlineFallback(Object error) async {
    final userId = _userId();
    final cached = userId == null ? null : await cache?.read(userId);
    if (cached != null) return cached;
    throw ScanApiException(
      'The scanner is offline and no recent encrypted result is available.',
      error,
    );
  }
}

class ScanApiException implements Exception {
  const ScanApiException(this.message, [this.cause]);

  final String message;
  final Object? cause;

  @override
  String toString() => message;
}
