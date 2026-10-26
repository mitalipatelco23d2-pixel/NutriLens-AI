class HydrationEntry {
  const HydrationEntry({
    required this.id,
    required this.amountMl,
    required this.consumedAt,
    this.source = 'USER_ENTERED',
  });

  factory HydrationEntry.fromJson(Map<String, dynamic> json) => HydrationEntry(
    id: json['id'] as String,
    amountMl: json['amount_ml'] as int,
    consumedAt: DateTime.parse(json['consumed_at'] as String),
    source: json['source'] as String? ?? 'USER_ENTERED',
  );

  final String id;
  final int amountMl;
  final DateTime consumedAt;
  final String source;

  Map<String, dynamic> toJson() => {
    'id': id,
    'amount_ml': amountMl,
    'consumed_at': consumedAt.toUtc().toIso8601String(),
  };
}

class HydrationSummary {
  const HydrationSummary({
    required this.day,
    required this.timezoneOffsetMinutes,
    required this.targetMl,
    required this.totalMl,
    required this.remainingMl,
    required this.entries,
  });

  factory HydrationSummary.fromJson(Map<String, dynamic> json) =>
      HydrationSummary(
        day: json['day'] as String,
        timezoneOffsetMinutes: json['timezone_offset_minutes'] as int,
        targetMl: json['target_ml'] as int?,
        totalMl: json['total_ml'] as int,
        remainingMl: json['remaining_ml'] as int?,
        entries: (json['entries'] as List<dynamic>)
            .map(
              (item) => HydrationEntry.fromJson(item as Map<String, dynamic>),
            )
            .toList(growable: false),
      );

  final String day;
  final int timezoneOffsetMinutes;
  final int? targetMl;
  final int totalMl;
  final int? remainingMl;
  final List<HydrationEntry> entries;
}

class HydrationBucket {
  const HydrationBucket({
    required this.label,
    required this.startTime,
    required this.endTime,
    required this.totalMl,
    this.targetMl,
    this.targetAttained = false,
  });

  factory HydrationBucket.fromJson(Map<String, dynamic> json) => HydrationBucket(
    label: json['label'] as String,
    startTime: DateTime.parse(json['start_time'] as String),
    endTime: DateTime.parse(json['end_time'] as String),
    totalMl: json['total_ml'] as int,
    targetMl: json['target_ml'] as int?,
    targetAttained: json['target_attained'] as bool? ?? false,
  );

  final String label;
  final DateTime startTime;
  final DateTime endTime;
  final int totalMl;
  final int? targetMl;
  final bool targetAttained;
}

class HydrationAnalytics {
  const HydrationAnalytics({
    required this.period,
    required this.startDate,
    required this.endDate,
    required this.totalMl,
    required this.dailyAverageMl,
    required this.targetMl,
    required this.daysTargetMet,
    required this.totalDays,
    required this.attainmentRatePct,
    required this.buckets,
  });

  factory HydrationAnalytics.fromJson(Map<String, dynamic> json) => HydrationAnalytics(
    period: json['period'] as String,
    startDate: json['start_date'] as String,
    endDate: json['end_date'] as String,
    totalMl: json['total_ml'] as int,
    dailyAverageMl: json['daily_average_ml'] as int,
    targetMl: json['target_ml'] as int?,
    daysTargetMet: json['days_target_met'] as int,
    totalDays: json['total_days'] as int,
    attainmentRatePct: (json['attainment_rate_pct'] as num).toDouble(),
    buckets: (json['buckets'] as List<dynamic>)
        .map((b) => HydrationBucket.fromJson(b as Map<String, dynamic>))
        .toList(growable: false),
  );

  final String period;
  final String startDate;
  final String endDate;
  final int totalMl;
  final int dailyAverageMl;
  final int? targetMl;
  final int daysTargetMet;
  final int totalDays;
  final double attainmentRatePct;
  final List<HydrationBucket> buckets;
}

abstract interface class HydrationGateway {
  Future<HydrationSummary> hydration({required DateTime day});
  Future<int?> saveHydrationTarget(int? targetMl);
  Future<HydrationEntry> addHydration(HydrationEntry entry);
  Future<HydrationEntry> updateHydration(HydrationEntry entry);
  Future<void> deleteHydration(String id);
  Future<HydrationAnalytics> hydrationAnalytics({
    String period = 'WEEK',
    DateTime? day,
    DateTime? startDate,
    DateTime? endDate,
  });
}

String hydrationDay(DateTime day) =>
    '${day.year.toString().padLeft(4, '0')}-'
    '${day.month.toString().padLeft(2, '0')}-'
    '${day.day.toString().padLeft(2, '0')}';

String formatWater(int amountMl) {
  if (amountMl < 1000) return '$amountMl ml';
  final liters = (amountMl / 1000)
      .toStringAsFixed(3)
      .replaceFirst(RegExp(r'0+$'), '')
      .replaceFirst(RegExp(r'\.$'), '');
  return '$liters L';
}
