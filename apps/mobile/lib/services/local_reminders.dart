import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:timezone/data/latest_all.dart' as timezone_data;
import 'package:timezone/timezone.dart' as timezone;

const _managedReminderIds = <int>{
  1000,
  1001,
  1002,
  1003,
  1004,
  1005,
  1006,
  1007,
  1008,
  1009,
  1010,
  1011,
  1012,
  1013,
  1014,
  1015,
  1100,
  1101,
  1102,
  1200,
  1300,
  2000,
  2001,
  2099,
};

enum ReminderPermission { granted, denied, unavailable }

class LocalReminderPreferences {
  const LocalReminderPreferences({
    this.hydrationEnabled = false,
    this.mealsEnabled = false,
    this.dailySummaryEnabled = false,
    this.weightEnabled = false,
    this.scanCompletionEnabled = false,
    this.lowStockEnabled = false,
    this.hydrationStartMinutes = 9 * 60,
    this.hydrationEndMinutes = 21 * 60,
    this.hydrationIntervalMinutes = 2 * 60,
    this.breakfastMinutes = 8 * 60,
    this.lunchMinutes = 13 * 60,
    this.dinnerMinutes = 20 * 60,
    this.dailySummaryMinutes = 21 * 60,
    this.weightMinutes = 8 * 60,
    this.weightWeekday = DateTime.monday,
    this.quietStartMinutes = 22 * 60,
    this.quietEndMinutes = 7 * 60,
  });

  factory LocalReminderPreferences.fromJson(Map<String, dynamic> json) {
    int minutes(String key, int fallback) {
      final value = json[key];
      return value is int && value >= 0 && value < 24 * 60 ? value : fallback;
    }

    int interval(String key, int fallback) {
      final value = json[key];
      return value is int && value >= 30 && value <= 6 * 60 ? value : fallback;
    }

    int weekday(String key, int fallback) {
      final value = json[key];
      return value is int &&
              value >= DateTime.monday &&
              value <= DateTime.sunday
          ? value
          : fallback;
    }

    bool flag(String key, bool fallback) =>
        json[key] is bool ? json[key] as bool : fallback;

    return LocalReminderPreferences(
      hydrationEnabled: flag('hydration_enabled', false),
      mealsEnabled: flag('meals_enabled', false),
      dailySummaryEnabled: flag('daily_summary_enabled', false),
      weightEnabled: flag('weight_enabled', false),
      scanCompletionEnabled: flag('scan_completion_enabled', false),
      lowStockEnabled: flag('low_stock_enabled', false),
      hydrationStartMinutes: minutes('hydration_start_minutes', 9 * 60),
      hydrationEndMinutes: minutes('hydration_end_minutes', 21 * 60),
      hydrationIntervalMinutes: interval('hydration_interval_minutes', 2 * 60),
      breakfastMinutes: minutes('breakfast_minutes', 8 * 60),
      lunchMinutes: minutes('lunch_minutes', 13 * 60),
      dinnerMinutes: minutes('dinner_minutes', 20 * 60),
      dailySummaryMinutes: minutes('daily_summary_minutes', 21 * 60),
      weightMinutes: minutes('weight_minutes', 8 * 60),
      weightWeekday: weekday('weight_weekday', DateTime.monday),
      quietStartMinutes: minutes('quiet_start_minutes', 22 * 60),
      quietEndMinutes: minutes('quiet_end_minutes', 7 * 60),
    );
  }

  final bool hydrationEnabled;
  final bool mealsEnabled;
  final bool dailySummaryEnabled;
  final bool weightEnabled;
  final bool scanCompletionEnabled;
  final bool lowStockEnabled;
  final int hydrationStartMinutes;
  final int hydrationEndMinutes;
  final int hydrationIntervalMinutes;
  final int breakfastMinutes;
  final int lunchMinutes;
  final int dinnerMinutes;
  final int dailySummaryMinutes;
  final int weightMinutes;
  final int weightWeekday;
  final int quietStartMinutes;
  final int quietEndMinutes;

  bool get hasScheduledReminders =>
      hydrationEnabled || mealsEnabled || dailySummaryEnabled || weightEnabled;

  bool isQuietAt(int minuteOfDay) {
    if (quietStartMinutes == quietEndMinutes) return false;
    if (quietStartMinutes < quietEndMinutes) {
      return minuteOfDay >= quietStartMinutes && minuteOfDay < quietEndMinutes;
    }
    return minuteOfDay >= quietStartMinutes || minuteOfDay < quietEndMinutes;
  }

  List<LocalReminderSchedule> schedules() {
    final schedules = <LocalReminderSchedule>[];
    if (hydrationEnabled && hydrationStartMinutes <= hydrationEndMinutes) {
      var index = 0;
      for (
        var minute = hydrationStartMinutes;
        minute <= hydrationEndMinutes && index < 16;
        minute += hydrationIntervalMinutes
      ) {
        if (!isQuietAt(minute)) {
          schedules.add(
            LocalReminderSchedule(
              id: 1000 + index,
              title: 'Hydration check-in',
              body: 'A small glass now can make today’s water goal easier.',
              minuteOfDay: minute,
            ),
          );
        }
        index++;
      }
    }
    if (mealsEnabled) {
      for (final entry in <(int, String, int)>[
        (1100, 'Breakfast check-in', breakfastMinutes),
        (1101, 'Lunch check-in', lunchMinutes),
        (1102, 'Dinner check-in', dinnerMinutes),
      ]) {
        if (!isQuietAt(entry.$3)) {
          schedules.add(
            LocalReminderSchedule(
              id: entry.$1,
              title: entry.$2,
              body: 'Log what you ate when it is convenient.',
              minuteOfDay: entry.$3,
            ),
          );
        }
      }
    }
    if (dailySummaryEnabled && !isQuietAt(dailySummaryMinutes)) {
      schedules.add(
        LocalReminderSchedule(
          id: 1200,
          title: 'Daily nutrition summary',
          body: 'Review today’s evidence and fill any missing diary entries.',
          minuteOfDay: dailySummaryMinutes,
        ),
      );
    }
    if (weightEnabled && !isQuietAt(weightMinutes)) {
      schedules.add(
        LocalReminderSchedule(
          id: 1300,
          title: 'Optional weight check-in',
          body: 'Log only if weighing supports your goals and wellbeing.',
          minuteOfDay: weightMinutes,
          weekday: weightWeekday,
        ),
      );
    }
    return schedules;
  }

  LocalReminderPreferences copyWith({
    bool? hydrationEnabled,
    bool? mealsEnabled,
    bool? dailySummaryEnabled,
    bool? weightEnabled,
    bool? scanCompletionEnabled,
    bool? lowStockEnabled,
    int? hydrationStartMinutes,
    int? hydrationEndMinutes,
    int? hydrationIntervalMinutes,
    int? breakfastMinutes,
    int? lunchMinutes,
    int? dinnerMinutes,
    int? dailySummaryMinutes,
    int? weightMinutes,
    int? weightWeekday,
    int? quietStartMinutes,
    int? quietEndMinutes,
  }) => LocalReminderPreferences(
    hydrationEnabled: hydrationEnabled ?? this.hydrationEnabled,
    mealsEnabled: mealsEnabled ?? this.mealsEnabled,
    dailySummaryEnabled: dailySummaryEnabled ?? this.dailySummaryEnabled,
    weightEnabled: weightEnabled ?? this.weightEnabled,
    scanCompletionEnabled: scanCompletionEnabled ?? this.scanCompletionEnabled,
    lowStockEnabled: lowStockEnabled ?? this.lowStockEnabled,
    hydrationStartMinutes: hydrationStartMinutes ?? this.hydrationStartMinutes,
    hydrationEndMinutes: hydrationEndMinutes ?? this.hydrationEndMinutes,
    hydrationIntervalMinutes:
        hydrationIntervalMinutes ?? this.hydrationIntervalMinutes,
    breakfastMinutes: breakfastMinutes ?? this.breakfastMinutes,
    lunchMinutes: lunchMinutes ?? this.lunchMinutes,
    dinnerMinutes: dinnerMinutes ?? this.dinnerMinutes,
    dailySummaryMinutes: dailySummaryMinutes ?? this.dailySummaryMinutes,
    weightMinutes: weightMinutes ?? this.weightMinutes,
    weightWeekday: weightWeekday ?? this.weightWeekday,
    quietStartMinutes: quietStartMinutes ?? this.quietStartMinutes,
    quietEndMinutes: quietEndMinutes ?? this.quietEndMinutes,
  );

  Map<String, dynamic> toJson() => {
    'hydration_enabled': hydrationEnabled,
    'meals_enabled': mealsEnabled,
    'daily_summary_enabled': dailySummaryEnabled,
    'weight_enabled': weightEnabled,
    'scan_completion_enabled': scanCompletionEnabled,
    'low_stock_enabled': lowStockEnabled,
    'hydration_start_minutes': hydrationStartMinutes,
    'hydration_end_minutes': hydrationEndMinutes,
    'hydration_interval_minutes': hydrationIntervalMinutes,
    'breakfast_minutes': breakfastMinutes,
    'lunch_minutes': lunchMinutes,
    'dinner_minutes': dinnerMinutes,
    'daily_summary_minutes': dailySummaryMinutes,
    'weight_minutes': weightMinutes,
    'weight_weekday': weightWeekday,
    'quiet_start_minutes': quietStartMinutes,
    'quiet_end_minutes': quietEndMinutes,
  };
}

class LocalReminderSchedule {
  const LocalReminderSchedule({
    required this.id,
    required this.title,
    required this.body,
    required this.minuteOfDay,
    this.weekday,
  });

  final int id;
  final String title;
  final String body;
  final int minuteOfDay;
  final int? weekday;
}

abstract interface class LocalReminderStore {
  Future<LocalReminderPreferences> load(String ownerId);
  Future<void> save(String ownerId, LocalReminderPreferences preferences);
}

class SharedPreferencesLocalReminderStore implements LocalReminderStore {
  SharedPreferencesLocalReminderStore({SharedPreferencesAsync? preferences})
    : _preferences = preferences ?? SharedPreferencesAsync();

  final SharedPreferencesAsync _preferences;

  String _key(String ownerId) =>
      'nutrilens.reminders.v1.${base64Url.encode(utf8.encode(ownerId))}';

  @override
  Future<LocalReminderPreferences> load(String ownerId) async {
    final raw = await _preferences.getString(_key(ownerId));
    if (raw == null) return const LocalReminderPreferences();
    try {
      final json = jsonDecode(raw);
      if (json is Map<String, dynamic>) {
        return LocalReminderPreferences.fromJson(json);
      }
    } on FormatException {
      // A corrupt preference record is non-critical and resets to safe defaults.
    }
    return const LocalReminderPreferences();
  }

  @override
  Future<void> save(String ownerId, LocalReminderPreferences preferences) =>
      _preferences.setString(_key(ownerId), jsonEncode(preferences.toJson()));
}

abstract interface class LocalReminderPlatform {
  Future<void> initialize();
  Future<ReminderPermission> permission();
  Future<ReminderPermission> requestPermission();
  Future<void> replaceSchedules(List<LocalReminderSchedule> schedules);
  Future<void> clearSchedules();
  Future<void> show({
    required int id,
    required String title,
    required String body,
    required String payload,
  });
}

class PlatformLocalReminderPlatform implements LocalReminderPlatform {
  PlatformLocalReminderPlatform({FlutterLocalNotificationsPlugin? plugin})
    : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  static const _channel = AndroidNotificationDetails(
    'nutrilens_wellness_reminders_v1',
    'Wellness reminders',
    channelDescription:
        'Optional hydration, meal, summary, weight, scan and pantry reminders.',
    importance: Importance.defaultImportance,
    priority: Priority.defaultPriority,
  );

  final FlutterLocalNotificationsPlugin _plugin;
  Future<void>? _initialization;

  bool get _supported =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);

  @override
  Future<void> initialize() => _initialization ??= _initialize();

  Future<void> _initialize() async {
    if (!_supported) return;
    initializeReminderTimeZones();
    final zone = await FlutterTimezone.getLocalTimezone();
    timezone.setLocalLocation(timezone.getLocation(zone.identifier));
    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('ic_notification'),
        iOS: DarwinInitializationSettings(
          requestAlertPermission: false,
          requestBadgePermission: false,
          requestSoundPermission: false,
        ),
      ),
    );
  }

  @override
  Future<ReminderPermission> permission() async {
    if (!_supported) return ReminderPermission.unavailable;
    await initialize();
    if (defaultTargetPlatform == TargetPlatform.android) {
      final enabled = await _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >()
          ?.areNotificationsEnabled();
      return enabled == true
          ? ReminderPermission.granted
          : ReminderPermission.denied;
    }
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      final options = await _plugin
          .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin
          >()
          ?.checkPermissions();
      return options?.isEnabled == true
          ? ReminderPermission.granted
          : ReminderPermission.denied;
    }
    return ReminderPermission.unavailable;
  }

  @override
  Future<ReminderPermission> requestPermission() async {
    if (!_supported) return ReminderPermission.unavailable;
    await initialize();
    if (defaultTargetPlatform == TargetPlatform.android) {
      final granted = await _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >()
          ?.requestNotificationsPermission();
      return granted == true
          ? ReminderPermission.granted
          : ReminderPermission.denied;
    }
    if (defaultTargetPlatform == TargetPlatform.iOS) {
      final granted = await _plugin
          .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin
          >()
          ?.requestPermissions(alert: true, badge: false, sound: true);
      return granted == true
          ? ReminderPermission.granted
          : ReminderPermission.denied;
    }
    return ReminderPermission.unavailable;
  }

  @override
  Future<void> clearSchedules() async {
    if (!_supported) return;
    await initialize();
    for (final id in _managedReminderIds) {
      await _plugin.cancel(id: id);
    }
  }

  @override
  Future<void> replaceSchedules(List<LocalReminderSchedule> schedules) async {
    if (!_supported) return;
    await clearSchedules();
    for (final schedule in schedules) {
      final now = timezone.TZDateTime.now(timezone.local);
      var first = timezone.TZDateTime(
        timezone.local,
        now.year,
        now.month,
        now.day,
        schedule.minuteOfDay ~/ 60,
        schedule.minuteOfDay % 60,
      );
      if (schedule.weekday case final weekday?) {
        while (first.weekday != weekday || !first.isAfter(now)) {
          first = first.add(const Duration(days: 1));
        }
      } else if (!first.isAfter(now)) {
        first = first.add(const Duration(days: 1));
      }
      await _plugin.zonedSchedule(
        id: schedule.id,
        title: schedule.title,
        body: schedule.body,
        scheduledDate: first,
        notificationDetails: const NotificationDetails(
          android: _channel,
          iOS: DarwinNotificationDetails(),
        ),
        androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
        matchDateTimeComponents: schedule.weekday == null
            ? DateTimeComponents.time
            : DateTimeComponents.dayOfWeekAndTime,
        payload: 'scheduled-reminder',
      );
    }
  }

  @override
  Future<void> show({
    required int id,
    required String title,
    required String body,
    required String payload,
  }) async {
    if (!_supported) return;
    await initialize();
    await _plugin.show(
      id: id,
      title: title,
      body: body,
      notificationDetails: const NotificationDetails(
        android: _channel,
        iOS: DarwinNotificationDetails(),
      ),
      payload: payload,
    );
  }
}

/// Loads the complete IANA database because Android can return legacy aliases
/// such as `Asia/Calcutta` that are intentionally absent from the compact data.
void initializeReminderTimeZones() => timezone_data.initializeTimeZones();

class LocalReminderState {
  const LocalReminderState({
    required this.preferences,
    required this.permission,
  });

  final LocalReminderPreferences preferences;
  final ReminderPermission permission;
}

class LocalReminderCoordinator {
  LocalReminderCoordinator({
    LocalReminderStore? store,
    LocalReminderPlatform? platform,
    DateTime Function()? now,
  }) : _store = store ?? SharedPreferencesLocalReminderStore(),
       _platform = platform ?? PlatformLocalReminderPlatform(),
       _now = now ?? DateTime.now;

  final LocalReminderStore _store;
  final LocalReminderPlatform _platform;
  final DateTime Function() _now;

  Future<LocalReminderState> load(String ownerId) async {
    final preferences = await _store.load(ownerId);
    final permission = await _platform.permission();
    if (permission == ReminderPermission.granted) {
      await _platform.replaceSchedules(preferences.schedules());
    }
    return LocalReminderState(preferences: preferences, permission: permission);
  }

  Future<void> save(
    String ownerId,
    LocalReminderPreferences preferences,
  ) async {
    await _store.save(ownerId, preferences);
    if (await _platform.permission() == ReminderPermission.granted) {
      await _platform.replaceSchedules(preferences.schedules());
    } else {
      await _platform.clearSchedules();
    }
  }

  Future<ReminderPermission> requestPermissionAndSync(String ownerId) async {
    final permission = await _platform.requestPermission();
    if (permission == ReminderPermission.granted) {
      final preferences = await _store.load(ownerId);
      await _platform.replaceSchedules(preferences.schedules());
    }
    return permission;
  }

  Future<void> notifyScanCompleted(String ownerId, String productName) async {
    final preferences = await _store.load(ownerId);
    if (!preferences.scanCompletionEnabled ||
        _isQuietNow(preferences) ||
        await _platform.permission() != ReminderPermission.granted) {
      return;
    }
    final label = _notificationLabel(productName);
    await _platform.show(
      id: 2000,
      title: 'Scan complete',
      body: label.isEmpty
          ? 'Your NutriLens result is ready.'
          : '$label is ready to review.',
      payload: 'scan-complete',
    );
  }

  Future<void> notifyLowStock(
    String ownerId, {
    required String itemName,
    required double quantity,
    required String unit,
  }) async {
    final preferences = await _store.load(ownerId);
    if (!preferences.lowStockEnabled ||
        _isQuietNow(preferences) ||
        await _platform.permission() != ReminderPermission.granted) {
      return;
    }
    final label = _notificationLabel(itemName);
    await _platform.show(
      id: 2001,
      title: '${label.isEmpty ? 'Pantry item' : label} is running low',
      body: '${_formatQuantity(quantity)} $unit remaining.',
      payload: 'pantry-low-stock',
    );
  }

  Future<void> showTest(String ownerId) async {
    if (ownerId.isEmpty) return;
    if (await _platform.permission() == ReminderPermission.granted) {
      await _platform.show(
        id: 2099,
        title: 'NutriLens reminders are ready',
        body: 'You control every reminder and can change them anytime.',
        payload: 'reminder-test',
      );
    }
  }

  Future<void> signOut() => _platform.clearSchedules();

  bool _isQuietNow(LocalReminderPreferences preferences) {
    final current = _now();
    return preferences.isQuietAt(current.hour * 60 + current.minute);
  }
}

String _formatQuantity(double value) => value == value.roundToDouble()
    ? value.toStringAsFixed(0)
    : value.toStringAsFixed(1);

String _notificationLabel(String value) {
  final normalized = value.trim().replaceAll(RegExp(r'\s+'), ' ');
  return normalized.length <= 80 ? normalized : normalized.substring(0, 80);
}
