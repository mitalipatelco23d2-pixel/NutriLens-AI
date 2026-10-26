import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'api_client.dart';

const clientAndroidMlKit = 'CLIENT_ANDROID_MLKIT';
const clientInferenceContractVersion = '1.0.0';
const androidMlKitOcrProvider = 'ML_KIT_TEXT_RECOGNITION_V2';

enum AndroidClientInferenceMode { disabled, shadow, preferred }

class ClientInferenceCapabilities {
  const ClientInferenceCapabilities({
    required this.contractVersion,
    required this.androidMode,
    required this.evidenceUse,
    required this.serverResultAuthoritative,
    required this.serverFallbackRequired,
    this.configurationWarning,
  });

  factory ClientInferenceCapabilities.fromJson(Map<String, dynamic> json) {
    final version = json['client_inference_contract_version'];
    if (version != clientInferenceContractVersion) {
      throw FormatException('Unsupported client inference contract: $version');
    }
    final mode = switch (json['android_mode']) {
      'disabled' => AndroidClientInferenceMode.disabled,
      'shadow' => AndroidClientInferenceMode.shadow,
      'preferred' => AndroidClientInferenceMode.preferred,
      final value => throw FormatException(
        'Unsupported Android client inference mode: $value',
      ),
    };
    final preferred = mode == AndroidClientInferenceMode.preferred;
    if (json['evidence_use'] !=
            (preferred
                ? 'SERVER_PARSED_CLIENT_EVIDENCE'
                : 'SHADOW_COMPARISON_ONLY') ||
        json['server_result_authoritative'] != true ||
        json['server_fallback_required'] != !preferred ||
        (preferred &&
            json['rejected_evidence_requires_server_fallback'] != true)) {
      throw const FormatException('Unsafe client inference capabilities');
    }
    return ClientInferenceCapabilities(
      contractVersion: version as String,
      androidMode: mode,
      evidenceUse: json['evidence_use'] as String,
      serverResultAuthoritative: true,
      serverFallbackRequired: !preferred,
      configurationWarning: json['configuration_warning'] as String?,
    );
  }

  final String contractVersion;
  final AndroidClientInferenceMode androidMode;
  final String evidenceUse;
  final bool serverResultAuthoritative;
  final bool serverFallbackRequired;
  final String? configurationWarning;
}

class ClientInferenceBounds {
  const ClientInferenceBounds({
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
  });

  factory ClientInferenceBounds.fromMap(Map<Object?, Object?> map) =>
      ClientInferenceBounds(
        left: _requiredInt(map, 'left'),
        top: _requiredInt(map, 'top'),
        right: _requiredInt(map, 'right'),
        bottom: _requiredInt(map, 'bottom'),
      );

  final int left;
  final int top;
  final int right;
  final int bottom;

  Map<String, int> toJson() => {
    'left': left,
    'top': top,
    'right': right,
    'bottom': bottom,
  };
}

class ClientTextLine {
  const ClientTextLine({
    required this.text,
    required this.bounds,
    required this.recognizedLanguages,
    this.confidence,
  });

  factory ClientTextLine.fromMap(Map<Object?, Object?> map) => ClientTextLine(
    text: _requiredString(map, 'text'),
    bounds: _parseBounds(map['bounds']),
    recognizedLanguages: _stringList(map['recognized_languages']),
    confidence: (map['confidence'] as num?)?.toDouble(),
  );

  final String text;
  final ClientInferenceBounds? bounds;
  final List<String> recognizedLanguages;
  final double? confidence;

  Map<String, Object?> toJson() => {
    'text': text,
    'bounds': bounds?.toJson(),
    'recognized_languages': recognizedLanguages,
    'confidence': confidence,
  };
}

class ClientTextBlock {
  const ClientTextBlock({
    required this.text,
    required this.bounds,
    required this.lines,
    required this.recognizedLanguages,
  });

  factory ClientTextBlock.fromMap(Map<Object?, Object?> map) => ClientTextBlock(
    text: _requiredString(map, 'text'),
    bounds: _parseBounds(map['bounds']),
    lines: _mapList(map['lines']).map(ClientTextLine.fromMap).toList(),
    recognizedLanguages: _stringList(map['recognized_languages']),
  );

  final String text;
  final ClientInferenceBounds? bounds;
  final List<ClientTextLine> lines;
  final List<String> recognizedLanguages;

  Map<String, Object?> toJson() => {
    'text': text,
    'bounds': bounds?.toJson(),
    'lines': lines.map((line) => line.toJson()).toList(),
    'recognized_languages': recognizedLanguages,
  };
}

class ClientOcrEvidence {
  const ClientOcrEvidence({
    required this.contractVersion,
    required this.platform,
    required this.appVersion,
    required this.source,
    required this.ocrProvider,
    required this.ocrProviderVersion,
    required this.coldStart,
    required this.elapsedMilliseconds,
    required this.imageWidth,
    required this.imageHeight,
    required this.sourceImageSha256,
    required this.orientationDegrees,
    required this.text,
    required this.blocks,
    this.confidence,
    this.detectorProvider,
    this.detectorProviderVersion,
  });

  factory ClientOcrEvidence.fromMap(Map<Object?, Object?> map) {
    final contractVersion = _requiredString(
      map,
      'client_inference_contract_version',
    );
    final platform = _requiredString(map, 'platform');
    final ocrProvider = _requiredString(map, 'ocr_provider');
    final ocrProviderVersion = _requiredString(map, 'ocr_provider_version');
    if (contractVersion != clientInferenceContractVersion ||
        platform != 'ANDROID' ||
        ocrProvider != androidMlKitOcrProvider ||
        ocrProviderVersion != '16.0.1') {
      throw const FormatException('Unsupported client inference protocol');
    }
    final source = _requiredString(map, 'source');
    if (source != clientAndroidMlKit) {
      throw FormatException('Unsupported client inference source: $source');
    }
    final orientation = _requiredInt(map, 'orientation_degrees');
    if (orientation != 0 &&
        orientation != 90 &&
        orientation != 180 &&
        orientation != 270) {
      throw const FormatException('Invalid image orientation');
    }
    return ClientOcrEvidence(
      contractVersion: contractVersion,
      platform: platform,
      appVersion: _requiredString(map, 'app_version'),
      source: source,
      ocrProvider: ocrProvider,
      ocrProviderVersion: ocrProviderVersion,
      detectorProvider: map['detector_provider'] as String?,
      detectorProviderVersion: map['detector_provider_version'] as String?,
      coldStart: map['cold_start'] as bool? ?? false,
      elapsedMilliseconds: _requiredInt(map, 'elapsed_ms'),
      imageWidth: _requiredInt(map, 'image_width'),
      imageHeight: _requiredInt(map, 'image_height'),
      sourceImageSha256: _requiredSha256(map, 'source_image_sha256'),
      orientationDegrees: orientation,
      text: _requiredString(map, 'text'),
      blocks: _mapList(map['blocks']).map(ClientTextBlock.fromMap).toList(),
      confidence: (map['confidence'] as num?)?.toDouble(),
    );
  }

  final String contractVersion;
  final String platform;
  final String appVersion;
  final String source;
  final String ocrProvider;
  final String ocrProviderVersion;
  final String? detectorProvider;
  final String? detectorProviderVersion;
  final bool coldStart;
  final int elapsedMilliseconds;
  final int imageWidth;
  final int imageHeight;
  final String sourceImageSha256;
  final int orientationDegrees;
  final String text;
  final List<ClientTextBlock> blocks;
  final double? confidence;

  int get lineCount =>
      blocks.fold(0, (count, block) => count + block.lines.length);

  Map<String, Object?> toJson() => {
    'client_inference_contract_version': contractVersion,
    'platform': platform,
    'app_version': appVersion,
    'source': source,
    'ocr_provider': ocrProvider,
    'ocr_provider_version': ocrProviderVersion,
    'detector_provider': detectorProvider,
    'detector_provider_version': detectorProviderVersion,
    'cold_start': coldStart,
    'elapsed_ms': elapsedMilliseconds,
    'image_width': imageWidth,
    'image_height': imageHeight,
    'source_image_sha256': sourceImageSha256,
    'orientation_degrees': orientationDegrees,
    'text': text,
    'blocks': blocks.map((block) => block.toJson()).toList(),
    'confidence': confidence,
  };
}

class ClientEvidenceValidation {
  const ClientEvidenceValidation({
    this.decision = 'CLIENT_EVIDENCE_ACCEPTED',
    this.accepted = true,
    this.acceptedFor,
    this.source,
    this.evidenceSha256,
    this.sourceImageSha256,
    required this.canonicalLineCount,
    this.canonicalTextSha256,
    this.imageBindingVerified = false,
    this.dimensionsBindingVerified = false,
    this.eligibleForPreferredPath = false,
    this.serverFallbackRequired = true,
    this.nutritionBasis = 'UNKNOWN',
    this.nutritionRowCount = 0,
    this.majorNutrientCount = 0,
    this.nutritionConfidence,
    this.reasons = const [],
    required this.warnings,
  });

  factory ClientEvidenceValidation.fromJson(Map<String, dynamic> json) {
    final accepted = json['accepted'] == true;
    final decision = json['decision']?.toString() ?? 'CLIENT_EVIDENCE_ACCEPTED';
    const decisions = {
      'CLIENT_EVIDENCE_ACCEPTED',
      'SERVER_FALLBACK_REQUIRED',
      'CLIENT_EVIDENCE_INVALID',
      'CLIENT_CONTRACT_UNSUPPORTED',
    };
    if (!decisions.contains(decision) ||
        (accepted && json['accepted_for'] != 'SHADOW_COMPARISON_ONLY')) {
      throw const FormatException(
        'Invalid client evidence classification response',
      );
    }
    return ClientEvidenceValidation(
      decision: decision,
      accepted: accepted,
      acceptedFor: json['accepted_for'] as String?,
      source: json['source'] as String?,
      evidenceSha256: _optionalJsonSha256(json, 'evidence_sha256'),
      sourceImageSha256: _optionalJsonSha256(json, 'source_image_sha256'),
      canonicalLineCount: (json['canonical_line_count'] as num?)?.toInt() ?? 0,
      canonicalTextSha256: _optionalJsonSha256(json, 'canonical_text_sha256'),
      imageBindingVerified: json['image_binding_verified'] == true,
      dimensionsBindingVerified: json['dimensions_binding_verified'] == true,
      eligibleForPreferredPath: json['eligible_for_preferred_path'] == true,
      serverFallbackRequired: json['server_fallback_required'] != false,
      nutritionBasis: json['nutrition_basis']?.toString() ?? 'UNKNOWN',
      nutritionRowCount: (json['nutrition_row_count'] as num?)?.toInt() ?? 0,
      majorNutrientCount: (json['major_nutrient_count'] as num?)?.toInt() ?? 0,
      nutritionConfidence: (json['nutrition_confidence'] as num?)?.toDouble(),
      reasons: (json['reasons'] as List<dynamic>? ?? const [])
          .map((value) => value.toString())
          .toList(growable: false),
      warnings: (json['warnings'] as List<dynamic>? ?? const [])
          .map((value) => value.toString())
          .toList(growable: false),
    );
  }

  final String decision;
  final bool accepted;
  final String? acceptedFor;
  final String? source;
  final String? evidenceSha256;
  final String? sourceImageSha256;
  final int canonicalLineCount;
  final String? canonicalTextSha256;
  final bool imageBindingVerified;
  final bool dimensionsBindingVerified;
  final bool eligibleForPreferredPath;
  final bool serverFallbackRequired;
  final String nutritionBasis;
  final int nutritionRowCount;
  final int majorNutrientCount;
  final double? nutritionConfidence;
  final List<String> reasons;
  final List<String> warnings;
}

abstract interface class ClientEvidenceGateway {
  Future<ClientInferenceCapabilities> capabilities();
  Future<ClientEvidenceValidation> validate(
    ClientOcrEvidence evidence, {
    required Uint8List imageBytes,
    required String filename,
    required String mimeType,
  });
}

class ClientEvidenceApi implements ClientEvidenceGateway {
  const ClientEvidenceApi(this.client);

  final ApiClient client;

  @override
  Future<ClientInferenceCapabilities> capabilities() async {
    final response = await client.get(
      '/api/v1/scan/client-inference/capabilities',
    );
    if (response is! Map<String, dynamic>) {
      throw const FormatException('Invalid client inference capabilities');
    }
    return ClientInferenceCapabilities.fromJson(response);
  }

  @override
  Future<ClientEvidenceValidation> validate(
    ClientOcrEvidence evidence, {
    required Uint8List imageBytes,
    required String filename,
    required String mimeType,
  }) async {
    final response = await client.postMultipart(
      '/api/v1/scan/client-evidence/classify',
      fields: {'evidence_json': jsonEncode(evidence.toJson())},
      fileField: 'file',
      fileBytes: imageBytes,
      filename: filename,
      mimeType: mimeType,
    );
    if (response is! Map<String, dynamic>) {
      throw const FormatException(
        'Invalid client evidence validation response',
      );
    }
    final validation = ClientEvidenceValidation.fromJson(response);
    if ((validation.sourceImageSha256 != null &&
            validation.sourceImageSha256 != evidence.sourceImageSha256) ||
        (validation.source != null && validation.source != evidence.source)) {
      throw const FormatException(
        'Client evidence validation binding mismatch',
      );
    }
    return validation;
  }
}

abstract interface class ClientInferenceGateway {
  Future<ClientOcrEvidence?> recognizeText(Uint8List bytes);
}

class AndroidMlKitClientInference implements ClientInferenceGateway {
  const AndroidMlKitClientInference({MethodChannel? channel})
    : _channel =
          channel ?? const MethodChannel('ai.nutrilens/client_inference');

  final MethodChannel _channel;

  @override
  Future<ClientOcrEvidence?> recognizeText(Uint8List bytes) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return null;
    final response = await _channel.invokeMethod<Object?>('recognizeText', {
      'bytes': bytes,
    });
    if (response is! Map<Object?, Object?>) {
      throw const FormatException('Invalid native client inference response');
    }
    return ClientOcrEvidence.fromMap(response);
  }
}

Map<Object?, Object?>? _optionalMap(Object? value) =>
    value is Map<Object?, Object?> ? value : null;

ClientInferenceBounds? _parseBounds(Object? value) {
  final map = _optionalMap(value);
  return map == null ? null : ClientInferenceBounds.fromMap(map);
}

List<Map<Object?, Object?>> _mapList(Object? value) => value is List<Object?>
    ? value.whereType<Map<Object?, Object?>>().toList(growable: false)
    : const [];

List<String> _stringList(Object? value) => value is List<Object?>
    ? value.whereType<String>().toList(growable: false)
    : const [];

String _requiredString(Map<Object?, Object?> map, String key) {
  final value = map[key];
  if (value is! String) throw FormatException('Missing $key');
  return value;
}

int _requiredInt(Map<Object?, Object?> map, String key) {
  final value = map[key];
  if (value is! num) throw FormatException('Missing $key');
  return value.toInt();
}

String _requiredSha256(Map<Object?, Object?> map, String key) {
  final value = _requiredString(map, key).toLowerCase();
  if (!RegExp(r'^[a-f0-9]{64}$').hasMatch(value)) {
    throw FormatException('Invalid $key');
  }
  return value;
}

String? _optionalJsonSha256(Map<String, dynamic> map, String key) {
  final value = map[key];
  if (value == null) return null;
  if (value is! String || !RegExp(r'^[a-f0-9]{64}$').hasMatch(value)) {
    throw FormatException('Invalid $key');
  }
  return value;
}
