import 'api_client.dart';

class IntelligenceSnapshot {
  const IntelligenceSnapshot({
    required this.ingredients,
    required this.additives,
    required this.allergens,
    required this.novaGroup,
    required this.warnings,
  });

  factory IntelligenceSnapshot.fromJson(Map<String, dynamic> json) {
    return IntelligenceSnapshot(
      ingredients: _resolutionLabels(json['ingredient_matches'], 'taxonomy'),
      additives: _resolutionLabels(json['additives'], 'additive'),
      allergens: _resolutionLabels(json['allergens'], 'allergen'),
      novaGroup:
          (json['nova'] as Map<String, dynamic>?)?['canonical_name']
              ?.toString() ??
          (json['nova'] as Map<String, dynamic>?)?['group_number']?.toString(),
      warnings: _strings(json['warnings']),
    );
  }

  final List<String> ingredients;
  final List<String> additives;
  final List<String> allergens;
  final String? novaGroup;
  final List<String> warnings;
}

class FitScoreSnapshot {
  const FitScoreSnapshot({
    required this.category,
    required this.label,
    required this.reasons,
    this.score,
  });

  factory FitScoreSnapshot.fromJson(Map<String, dynamic> json) => FitScoreSnapshot(
    score: json['score'] is num ? (json['score'] as num).toInt() : null,
    category: json['category']?.toString() ?? 'NOT_ENOUGH_EVIDENCE',
    label: json['label']?.toString() ?? 'Not enough evidence',
    reasons: (json['reasons'] as List<dynamic>? ?? const []).map((e) => e.toString()).toList(),
  );

  final int? score;
  final String category;
  final String label;
  final List<String> reasons;
}

class BetterAlternativeSnapshot {
  const BetterAlternativeSnapshot({
    required this.name,
    required this.category,
    required this.whyBetter,
    required this.keyNutritionAdvantage,
    required this.dietaryCompatibility,
  });

  factory BetterAlternativeSnapshot.fromJson(Map<String, dynamic> json) => BetterAlternativeSnapshot(
    name: json['name']?.toString() ?? '',
    category: json['category']?.toString() ?? '',
    whyBetter: json['why_better']?.toString() ?? '',
    keyNutritionAdvantage: json['key_nutrition_advantage']?.toString() ?? '',
    dietaryCompatibility: (json['dietary_compatibility'] as List<dynamic>? ?? const [])
        .map((e) => e.toString())
        .toList(),
  );

  final String name;
  final String category;
  final String whyBetter;
  final String keyNutritionAdvantage;
  final List<String> dietaryCompatibility;
}

class RecommendationSnapshot {
  const RecommendationSnapshot({
    required this.findings,
    required this.disclaimer,
    this.fitScore,
    this.betterAlternatives = const [],
  });

  factory RecommendationSnapshot.fromJson(
    Map<String, dynamic> json,
  ) => RecommendationSnapshot(
    findings: (json['findings'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(
          (item) =>
              '${item['level'] ?? 'INFO'} · ${item['title'] ?? 'Finding'}\n${item['explanation'] ?? ''}',
        )
        .toList(growable: false),
    disclaimer: json['disclaimer']?.toString() ?? 'Wellness guidance only.',
    fitScore: json['fit_score'] is Map<String, dynamic>
        ? FitScoreSnapshot.fromJson(json['fit_score'] as Map<String, dynamic>)
        : null,
    betterAlternatives: (json['better_alternatives'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map((item) => BetterAlternativeSnapshot.fromJson(item))
        .toList(),
  );

  final List<String> findings;
  final String disclaimer;
  final FitScoreSnapshot? fitScore;
  final List<BetterAlternativeSnapshot> betterAlternatives;
}

class CounterfactualSnapshot {
  const CounterfactualSnapshot({
    required this.state,
    required this.factors,
    required this.limitation,
  });

  factory CounterfactualSnapshot.fromJson(
    Map<String, dynamic> json,
  ) => CounterfactualSnapshot(
    state: json['state']?.toString() ?? 'NO_OBSERVED_SIGNALS',
    factors: (json['factors'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(
          (item) =>
              '${item['label'] ?? 'Observed signal'}\n'
              '${item['hypothesis'] ?? ''}\n${item['result_change'] ?? ''}\n'
              'Evidence: ${_strings(item['observed_evidence']).join(' · ')}',
        )
        .toList(growable: false),
    limitation: json['limitation']?.toString() ?? '',
  );

  final String state;
  final List<String> factors;
  final String limitation;
}

List<String> _strings(Object? value) => (value as List<dynamic>? ?? const [])
    .map((item) => item.toString())
    .toList(growable: false);

List<String> _resolutionLabels(Object? value, String resolutionKey) =>
    (value as List<dynamic>? ?? const [])
        .map((item) {
          if (item is Map<String, dynamic>) {
            final resolution = item[resolutionKey] as Map<String, dynamic>?;
            final ingredient = item['ingredient'] as Map<String, dynamic>?;
            return (resolution?['canonical_name'] ??
                    ingredient?['normalized_text'])
                ?.toString();
          }
          return item.toString();
        })
        .whereType<String>()
        .where((item) => item.isNotEmpty)
        .toList(growable: false);

abstract interface class IntelligenceGateway {
  Future<IntelligenceSnapshot> ingredients(String scanId);
  Future<RecommendationSnapshot> recommendations(String scanId);
  Future<CounterfactualSnapshot> counterfactuals(String scanId);
}

class IntelligenceApi implements IntelligenceGateway {
  IntelligenceApi(this.client);
  final ApiClient client;

  @override
  Future<IntelligenceSnapshot> ingredients(String scanId) async =>
      IntelligenceSnapshot.fromJson(
        await client.post('/api/v1/ingredient-intelligence/scan/$scanId')
            as Map<String, dynamic>,
      );

  @override
  Future<RecommendationSnapshot> recommendations(String scanId) async =>
      RecommendationSnapshot.fromJson(
        await client.get('/api/v1/recommendations/scans/$scanId')
            as Map<String, dynamic>,
      );

  @override
  Future<CounterfactualSnapshot> counterfactuals(String scanId) async =>
      CounterfactualSnapshot.fromJson(
        await client.get(
              '/api/v1/recommendations/scans/$scanId/counterfactuals',
            )
            as Map<String, dynamic>,
      );
}
