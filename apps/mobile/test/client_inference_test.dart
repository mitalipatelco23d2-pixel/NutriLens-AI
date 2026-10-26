import 'package:flutter_test/flutter_test.dart';
import 'package:nutrilens_x/services/client_inference.dart';

void main() {
  test('capabilities retain strict disabled and shadow contracts', () {
    for (final mode in ['disabled', 'shadow']) {
      final parsed = ClientInferenceCapabilities.fromJson({
        ..._shadowCapabilities,
        'android_mode': mode,
      });
      expect(parsed.serverFallbackRequired, isTrue);
      expect(parsed.evidenceUse, 'SHADOW_COMPARISON_ONLY');
    }
  });

  test(
    'preferred capabilities require server authority and rejected fallback',
    () {
      final preferred = {
        ..._shadowCapabilities,
        'android_mode': 'preferred',
        'evidence_use': 'SERVER_PARSED_CLIENT_EVIDENCE',
        'server_fallback_required': false,
        'rejected_evidence_requires_server_fallback': true,
      };
      final parsed = ClientInferenceCapabilities.fromJson(preferred);
      expect(parsed.androidMode, AndroidClientInferenceMode.preferred);
      expect(parsed.serverFallbackRequired, isFalse);
      for (final invalid in [
        {...preferred, 'server_result_authoritative': false},
        {...preferred, 'server_fallback_required': true},
        {...preferred, 'rejected_evidence_requires_server_fallback': false},
        {...preferred, 'evidence_use': 'SHADOW_COMPARISON_ONLY'},
        {...preferred, 'client_inference_contract_version': 'future'},
        {...preferred, 'android_mode': 'automatic'},
        {..._shadowCapabilities, 'server_fallback_required': false},
        {
          ..._shadowCapabilities,
          'evidence_use': 'SERVER_PARSED_CLIENT_EVIDENCE',
        },
      ]) {
        expect(
          () => ClientInferenceCapabilities.fromJson(invalid),
          throwsFormatException,
        );
      }
    },
  );

  test('parses honest ML Kit provenance without manufacturing confidence', () {
    final evidence = ClientOcrEvidence.fromMap({
      'client_inference_contract_version': '1.0.0',
      'platform': 'ANDROID',
      'app_version': '1.0.0+1',
      'source': 'CLIENT_ANDROID_MLKIT',
      'ocr_provider': 'ML_KIT_TEXT_RECOGNITION_V2',
      'ocr_provider_version': '16.0.1',
      'detector_provider': null,
      'detector_provider_version': null,
      'cold_start': true,
      'elapsed_ms': 321,
      'image_width': 1080,
      'image_height': 1920,
      'source_image_sha256':
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'orientation_degrees': 0,
      'text': 'Ingredients: Milk',
      'confidence': null,
      'blocks': [
        {
          'text': 'Ingredients: Milk',
          'bounds': {'left': 10, 'top': 20, 'right': 500, 'bottom': 90},
          'recognized_languages': ['en'],
          'lines': [
            {
              'text': 'Ingredients: Milk',
              'bounds': {'left': 10, 'top': 20, 'right': 500, 'bottom': 90},
              'recognized_languages': ['en'],
              'confidence': null,
            },
          ],
        },
      ],
    });

    expect(evidence.source, clientAndroidMlKit);
    expect(evidence.lineCount, 1);
    expect(evidence.confidence, isNull);
    expect(evidence.blocks.single.lines.single.bounds?.left, 10);
  });

  test('rejects ungoverned client inference provenance', () {
    expect(
      () => ClientOcrEvidence.fromMap({
        'client_inference_contract_version': '1.0.0',
        'platform': 'ANDROID',
        'app_version': '1.0.0+1',
        'source': 'CLIENT_UNKNOWN',
        'ocr_provider': 'ML_KIT_TEXT_RECOGNITION_V2',
        'ocr_provider_version': '16.0.1',
        'detector_provider': null,
        'detector_provider_version': null,
        'elapsed_ms': 1,
        'image_width': 1,
        'image_height': 1,
        'source_image_sha256':
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        'orientation_degrees': 0,
        'text': '',
        'blocks': const [],
      }),
      throwsFormatException,
    );
  });

  test('requires a bound shadow-only server validation response', () {
    final validation = ClientEvidenceValidation.fromJson({
      'accepted': true,
      'accepted_for': 'SHADOW_COMPARISON_ONLY',
      'source': 'CLIENT_ANDROID_MLKIT',
      'evidence_sha256':
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'source_image_sha256':
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      'canonical_line_count': 2,
      'canonical_text_sha256':
          'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
      'warnings': ['Untrusted.'],
    });
    expect(validation.canonicalLineCount, 2);
    expect(validation.acceptedFor, 'SHADOW_COMPARISON_ONLY');
  });

  test('parses an image-bound conservative acceptance classification', () {
    final validation = ClientEvidenceValidation.fromJson({
      'decision': 'CLIENT_EVIDENCE_ACCEPTED',
      'accepted': true,
      'accepted_for': 'SHADOW_COMPARISON_ONLY',
      'source': 'CLIENT_ANDROID_MLKIT',
      'evidence_sha256':
          'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      'source_image_sha256':
          'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      'canonical_line_count': 10,
      'canonical_text_sha256':
          'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
      'image_binding_verified': true,
      'dimensions_binding_verified': true,
      'eligible_for_preferred_path': true,
      'server_fallback_required': true,
      'nutrition_basis': 'PER_100_ML',
      'nutrition_row_count': 6,
      'major_nutrient_count': 5,
      'nutrition_confidence': 0.72,
      'reasons': const [],
      'warnings': ['Server remains authoritative.'],
    });
    expect(validation.decision, 'CLIENT_EVIDENCE_ACCEPTED');
    expect(validation.imageBindingVerified, isTrue);
    expect(validation.eligibleForPreferredPath, isTrue);
    expect(validation.serverFallbackRequired, isTrue);
    expect(validation.nutritionBasis, 'PER_100_ML');
  });

  test('treats a conservative fallback decision as a valid response', () {
    final validation = ClientEvidenceValidation.fromJson({
      'decision': 'SERVER_FALLBACK_REQUIRED',
      'accepted': true,
      'accepted_for': 'SHADOW_COMPARISON_ONLY',
      'canonical_line_count': 1,
      'server_fallback_required': true,
      'reasons': ['INSUFFICIENT_NUTRIENT_ROWS'],
    });
    expect(validation.eligibleForPreferredPath, isFalse);
    expect(validation.reasons, contains('INSUFFICIENT_NUTRIENT_ROWS'));
  });
}

const _shadowCapabilities = <String, Object>{
  'client_inference_contract_version': '1.0.0',
  'android_mode': 'shadow',
  'evidence_use': 'SHADOW_COMPARISON_ONLY',
  'server_result_authoritative': true,
  'server_fallback_required': true,
};
