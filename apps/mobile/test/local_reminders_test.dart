import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nutrilens_x/reminder_settings_screen.dart';
import 'package:nutrilens_x/services/local_reminders.dart';
import 'package:timezone/timezone.dart' as timezone;

class _MemoryStore implements LocalReminderStore {
  final values = <String, LocalReminderPreferences>{};

  @override
  Future<LocalReminderPreferences> load(String ownerId) async =>
      values[ownerId] ?? const LocalReminderPreferences();

  @override
  Future<void> save(
    String ownerId,
    LocalReminderPreferences preferences,
  ) async {
    values[ownerId] = preferences;
  }
}

class _FakePlatform implements LocalReminderPlatform {
  _FakePlatform({this.currentPermission = ReminderPermission.denied});

  ReminderPermission currentPermission;
  int initializeCalls = 0;
  int clearCalls = 0;
  int permissionRequests = 0;
  List<LocalReminderSchedule> scheduled = [];
  final shown = <({int id, String title, String body, String payload})>[];

  @override
  Future<void> initialize() async => initializeCalls++;

  @override
  Future<ReminderPermission> permission() async => currentPermission;

  @override
  Future<ReminderPermission> requestPermission() async {
    permissionRequests++;
    return currentPermission;
  }

  @override
  Future<void> replaceSchedules(List<LocalReminderSchedule> schedules) async {
    scheduled = List.of(schedules);
  }

  @override
  Future<void> clearSchedules() async {
    clearCalls++;
    scheduled = [];
  }

  @override
  Future<void> show({
    required int id,
    required String title,
    required String body,
    required String payload,
  }) async {
    shown.add((id: id, title: title, body: body, payload: payload));
  }
}

void main() {
  test('accepts legacy time zone identifiers returned by Android', () {
    initializeReminderTimeZones();

    expect(timezone.getLocation('Asia/Calcutta').name, 'Asia/Calcutta');
  });

  test('builds bounded daily and weekly schedules outside quiet hours', () {
    const preferences = LocalReminderPreferences(
      hydrationEnabled: true,
      mealsEnabled: true,
      dailySummaryEnabled: true,
      weightEnabled: true,
      hydrationStartMinutes: 6 * 60,
      hydrationEndMinutes: 22 * 60,
      hydrationIntervalMinutes: 2 * 60,
      breakfastMinutes: 6 * 60,
      lunchMinutes: 13 * 60,
      dinnerMinutes: 22 * 60,
      dailySummaryMinutes: 21 * 60,
      weightMinutes: 8 * 60,
      quietStartMinutes: 22 * 60,
      quietEndMinutes: 7 * 60,
    );

    final schedules = preferences.schedules();

    expect(schedules.length, 10);
    expect(schedules.map((item) => item.id).toSet().length, schedules.length);
    expect(
      schedules.every((item) => !preferences.isQuietAt(item.minuteOfDay)),
      isTrue,
    );
    expect(
      schedules.where((item) => item.id == 1300).single.weekday,
      DateTime.monday,
    );
    expect(schedules.any((item) => item.id == 1100), isFalse);
    expect(schedules.any((item) => item.id == 1102), isFalse);
  });

  test('normalizes corrupt persisted values to conservative defaults', () {
    final preferences = LocalReminderPreferences.fromJson({
      'hydration_enabled': 'yes',
      'hydration_start_minutes': -1,
      'hydration_end_minutes': 2000,
      'hydration_interval_minutes': 5,
      'weight_weekday': 10,
      'scan_completion_enabled': false,
    });

    expect(preferences.hydrationEnabled, isFalse);
    expect(preferences.hydrationStartMinutes, 9 * 60);
    expect(preferences.hydrationEndMinutes, 21 * 60);
    expect(preferences.hydrationIntervalMinutes, 2 * 60);
    expect(preferences.weightWeekday, DateTime.monday);
    expect(preferences.scanCompletionEnabled, isFalse);
  });

  test(
    'keeps preferences owner scoped and schedules only with permission',
    () async {
      final store = _MemoryStore();
      final platform = _FakePlatform();
      final coordinator = LocalReminderCoordinator(
        store: store,
        platform: platform,
        now: () => DateTime(2026, 9, 7, 12),
      );
      const ownerOne = LocalReminderPreferences(hydrationEnabled: true);

      await coordinator.save('owner-one', ownerOne);

      expect(store.values['owner-one']?.hydrationEnabled, isTrue);
      expect(store.values.containsKey('owner-two'), isFalse);
      expect(platform.clearCalls, 1);
      expect(platform.scheduled, isEmpty);

      platform.currentPermission = ReminderPermission.granted;
      final ownerTwo = await coordinator.load('owner-two');
      expect(ownerTwo.preferences.hydrationEnabled, isFalse);
      expect(platform.scheduled, isEmpty);

      await coordinator.load('owner-one');
      expect(platform.scheduled, isNotEmpty);
    },
  );

  test(
    'quiet hours suppress event reminders without checking permission',
    () async {
      final store = _MemoryStore()
        ..values['owner'] = const LocalReminderPreferences(
          scanCompletionEnabled: true,
        );
      final platform = _FakePlatform(
        currentPermission: ReminderPermission.granted,
      );
      final coordinator = LocalReminderCoordinator(
        store: store,
        platform: platform,
        now: () => DateTime(2026, 9, 7, 23),
      );

      await coordinator.notifyScanCompleted('owner', 'Milk');

      expect(platform.shown, isEmpty);
    },
  );

  test(
    'event reminders honor settings and permission without prompting',
    () async {
      final store = _MemoryStore()
        ..values['owner'] = const LocalReminderPreferences(
          scanCompletionEnabled: true,
          lowStockEnabled: false,
        );
      final platform = _FakePlatform(
        currentPermission: ReminderPermission.granted,
      );
      final coordinator = LocalReminderCoordinator(
        store: store,
        platform: platform,
        now: () => DateTime(2026, 9, 7, 12),
      );

      await coordinator.notifyScanCompleted('owner', 'Low Fat Cow Milk');
      await coordinator.notifyLowStock(
        'owner',
        itemName: 'Oats',
        quantity: 0.5,
        unit: 'kg',
      );

      expect(platform.permissionRequests, 0);
      expect(platform.shown, hasLength(1));
      expect(platform.shown.single.title, 'Scan complete');
      expect(platform.shown.single.body, contains('Low Fat Cow Milk'));
    },
  );

  testWidgets('permission is requested only after explicit Allow action', (
    tester,
  ) async {
    final store = _MemoryStore();
    final platform = _FakePlatform();
    final coordinator = LocalReminderCoordinator(
      store: store,
      platform: platform,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ReminderSettingsScreen(ownerId: 'owner', reminders: coordinator),
      ),
    );
    await tester.pumpAndSettle();

    expect(platform.permissionRequests, 0);
    expect(find.text('Notification permission required'), findsOneWidget);

    await tester.tap(find.byKey(const Key('request-reminder-permission')));
    await tester.pumpAndSettle();

    expect(platform.permissionRequests, 1);
    expect(platform.currentPermission, ReminderPermission.denied);
  });

  testWidgets('saves configured schedules without hidden permission prompt', (
    tester,
  ) async {
    final store = _MemoryStore();
    final platform = _FakePlatform(
      currentPermission: ReminderPermission.granted,
    );
    final coordinator = LocalReminderCoordinator(
      store: store,
      platform: platform,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: ReminderSettingsScreen(ownerId: 'owner', reminders: coordinator),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('hydration-reminder-toggle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(
      find.byKey(const Key('summary-reminder-toggle')),
    );
    await tester.tap(find.byKey(const Key('summary-reminder-toggle')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('save-reminders')));
    await tester.tap(find.byKey(const Key('save-reminders')));
    await tester.pumpAndSettle();

    expect(platform.permissionRequests, 0);
    expect(store.values['owner']?.hydrationEnabled, isTrue);
    expect(store.values['owner']?.dailySummaryEnabled, isTrue);
    expect(platform.scheduled, isNotEmpty);
  });
}
