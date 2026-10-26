class WeightEntry {
  const WeightEntry({
    required this.id,
    required this.weightKg,
    required this.recordedAt,
    this.source = 'USER_ENTERED',
  });

  factory WeightEntry.fromJson(Map<String, dynamic> json) => WeightEntry(
    id: json['id'] as String,
    weightKg: (json['weight_kg'] as num).toDouble(),
    recordedAt: DateTime.parse(json['recorded_at'] as String),
    source: json['source']?.toString() ?? 'USER_ENTERED',
  );

  final String id;
  final double weightKg;
  final DateTime recordedAt;
  final String source;

  Map<String, dynamic> toJson() => {
    'id': id,
    'weight_kg': weightKg,
    'recorded_at': recordedAt.toUtc().toIso8601String(),
  };
}

class WeightSettings {
  const WeightSettings({required this.state, required this.targetWeightKg});

  factory WeightSettings.fromJson(Map<String, dynamic> json) => WeightSettings(
    state: json['state']?.toString() ?? 'DISABLED',
    targetWeightKg: (json['target_weight_kg'] as num?)?.toDouble(),
  );

  final String state;
  final double? targetWeightKg;
}

class WeightSummary {
  const WeightSummary({
    required this.state,
    required this.targetWeightKg,
    required this.latestWeightKg,
    required this.changeFromFirstKg,
    required this.differenceFromTargetKg,
    required this.entries,
    required this.method,
    required this.limitation,
  });

  factory WeightSummary.fromJson(Map<String, dynamic> json) => WeightSummary(
    state: json['state']?.toString() ?? 'DISABLED',
    targetWeightKg: (json['target_weight_kg'] as num?)?.toDouble(),
    latestWeightKg: (json['latest_weight_kg'] as num?)?.toDouble(),
    changeFromFirstKg: (json['change_from_first_kg'] as num?)?.toDouble(),
    differenceFromTargetKg: (json['difference_from_target_kg'] as num?)
        ?.toDouble(),
    entries: (json['entries'] as List<dynamic>? ?? const [])
        .map((item) => WeightEntry.fromJson(item as Map<String, dynamic>))
        .toList(growable: false),
    method: json['method']?.toString() ?? 'SELF_REPORTED_WEIGHT_DIFFERENCE_V1',
    limitation: json['limitation']?.toString() ?? '',
  );

  final String state;
  final double? targetWeightKg;
  final double? latestWeightKg;
  final double? changeFromFirstKg;
  final double? differenceFromTargetKg;
  final List<WeightEntry> entries;
  final String method;
  final String limitation;
}

abstract interface class WeightGateway {
  Future<WeightSummary> weightSummary({int limit = 180});
  Future<WeightSettings> enableWeightTracking(double? targetWeightKg);
  Future<void> disableWeightTracking();
  Future<WeightEntry> addWeight(WeightEntry entry);
  Future<WeightEntry> updateWeight(WeightEntry entry);
  Future<void> deleteWeight(String id);
}
