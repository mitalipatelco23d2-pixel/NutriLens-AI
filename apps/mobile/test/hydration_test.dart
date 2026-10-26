import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/hydration_screen.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/hydration_controller.dart';
import 'package:nutrilens_x/services/hydration_models.dart';
import 'package:nutrilens_x/services/product_api.dart';

class _MemoryStore implements PendingHydrationStore {
  final values = <String, HydrationEntry>{};
  @override
  Future<HydrationEntry?> read(String ownerId) async => values[ownerId];
  @override
  Future<void> write(String ownerId, HydrationEntry entry) async {
    values[ownerId] = entry;
  }

  @override
  Future<void> clear(String ownerId) async {
    values.remove(ownerId);
  }
}

class _WaterGateway implements HydrationGateway {
  int? target;
  final entries = <String, HydrationEntry>{};
  final submitted = <HydrationEntry>[];
  bool loseNextResponse = false;
  bool failRead = false;
  ApiException? rejectAdd;
  bool loseDeleteResponse = false;
  Completer<HydrationSummary>? delayedRead;

  @override
  Future<HydrationSummary> hydration({required DateTime day}) async {
    if (delayedRead != null) return delayedRead!.future;
    if (failRead) {
      throw const ApiException('Service unavailable', statusCode: 503);
    }
    final items = entries.values
        .where(
          (entry) =>
              hydrationDay(entry.consumedAt.toLocal()) == hydrationDay(day),
        )
        .toList();
    final total = items.fold(0, (sum, entry) => sum + entry.amountMl);
    return HydrationSummary(
      day: hydrationDay(day),
      timezoneOffsetMinutes: day.timeZoneOffset.inMinutes,
      targetMl: target,
      totalMl: total,
      remainingMl: target == null ? null : (target! - total).clamp(0, 10000),
      entries: items,
    );
  }

  @override
  Future<int?> saveHydrationTarget(int? targetMl) async => target = targetMl;
  @override
  Future<HydrationEntry> addHydration(HydrationEntry entry) async {
    submitted.add(entry);
    if (rejectAdd != null) throw rejectAdd!;
    entries.putIfAbsent(entry.id, () => entry);
    if (loseNextResponse) {
      loseNextResponse = false;
      throw TimeoutException('Response was lost');
    }
    return entries[entry.id]!;
  }

  @override
  Future<HydrationEntry> updateHydration(HydrationEntry entry) async =>
      entries[entry.id] = entry;
  @override
  Future<void> deleteHydration(String id) async {
    if (entries.remove(id) == null) {
      throw const ApiException('Entry not found', statusCode: 404);
    }
    if (loseDeleteResponse) {
      loseDeleteResponse = false;
      throw TimeoutException('Delete reply was lost');
    }
  }

  @override
  Future<HydrationAnalytics> hydrationAnalytics({
    String period = 'WEEK',
    DateTime? day,
    DateTime? startDate,
    DateTime? endDate,
  }) async => HydrationAnalytics(
    period: period,
    startDate: '2026-01-01',
    endDate: '2026-01-07',
    totalMl: 2000,
    dailyAverageMl: 285,
    targetMl: target,
    daysTargetMet: target != null && 2000 >= target! ? 1 : 0,
    totalDays: 7,
    attainmentRatePct: 14.3,
    buckets: const [],
  );
}

void main() {
  final date = DateTime(2026, 9, 2, 14, 30);
  HydrationController controller(
    _WaterGateway gateway, {
    _MemoryStore? store,
  }) => HydrationController(
    gateway: gateway,
    ownerId: 'owner-a',
    currentOwnerId: () => 'owner-a',
    store: store ?? _MemoryStore(),
    now: () => date,
  );

  test(
    'hydration HTTP contract sends authenticated CRUD, midnight offsets and UTC',
    () async {
      final requests = <http.Request>[];
      const id = '1c3af280-eed6-4aee-a0ff-e695dc6a25d5';
      final entry = HydrationEntry(id: id, amountMl: 375, consumedAt: date);
      final api = ProductApi(
        ApiClient(
          baseUrl: 'https://api.example',
          accessToken: () => 'test-token',
          client: MockClient((request) async {
            requests.add(request);
            expect(request.headers['Authorization'], 'Bearer test-token');
            if (request.method == 'DELETE') return http.Response('', 204);
            if (request.url.path.endsWith('/target')) {
              return http.Response(request.body, 200);
            }
            if (request.method == 'GET') {
              return http.Response(
                jsonEncode({
                  'day': '2026-09-02',
                  'timezone_offset_minutes': date.timeZoneOffset.inMinutes,
                  'target_ml': null,
                  'total_ml': 0,
                  'remaining_ml': null,
                  'entries': [],
                }),
                200,
              );
            }
            return http.Response(
              jsonEncode({
                ...jsonDecode(request.body) as Map<String, dynamic>,
                'id': id,
                'source': 'USER_ENTERED',
              }),
              201,
            );
          }),
        ),
      );
      final summary = await api.hydration(day: date);
      expect(summary.targetMl, isNull);
      expect(summary.remainingMl, isNull);
      expect(requests.single.url.queryParameters, {
        'day': '2026-09-02',
        'timezone_offset_minutes':
            '${DateTime(2026, 9, 2).timeZoneOffset.inMinutes}',
        'next_day_timezone_offset_minutes':
            '${DateTime(2026, 9, 3).timeZoneOffset.inMinutes}',
      });
      expect((await api.addHydration(entry)).amountMl, 375);
      expect(
        jsonDecode(requests.last.body)['consumed_at'],
        date.toUtc().toIso8601String(),
      );
      await api.updateHydration(entry);
      expect(requests.last.method, 'PUT');
      expect(jsonDecode(requests.last.body).containsKey('id'), isFalse);
      expect(await api.saveHydrationTarget(1800), 1800);
      expect(await api.saveHydrationTarget(null), isNull);
      await api.deleteHydration(id);
      expect(requests.last.url.path, '/api/v1/hydration/entries/$id');
    },
  );

  test(
    'lost response retries exactly the durable payload after recreation',
    () async {
      final gateway = _WaterGateway()..loseNextResponse = true;
      final store = _MemoryStore();
      final first = controller(gateway, store: store);
      await first.initialize();
      expect(first.summary!.targetMl, isNull);
      await first.add(250);
      expect(first.pendingAdd, isNotNull);
      expect(first.canMutate, isFalse);
      await first.add(500);
      expect(gateway.submitted.length, 1);
      first.dispose();
      final restored = controller(gateway, store: store);
      await restored.initialize();
      final pending = restored.pendingAdd!;
      expect(
        pending.id,
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
      await restored.retryAdd();
      expect(gateway.submitted.length, 2);
      expect(gateway.submitted.first.toJson(), gateway.submitted.last.toJson());
      expect(gateway.entries.length, 1);
      expect(restored.summary!.totalMl, 250);
      expect(store.values, isEmpty);
      restored.dispose();
    },
  );

  test(
    'targets, edits and deletion refresh shared daily totals without seed',
    () async {
      final water = controller(_WaterGateway());
      await water.initialize();
      await water.saveTarget(1500);
      await water.add(500);
      expect(water.todaySummary!.remainingMl, 1000);
      await water.edit(water.summary!.entries.single, 375);
      expect(water.todaySummary!.totalMl, 375);
      await water.saveTarget(null);
      expect(water.todaySummary!.remainingMl, isNull);
      await water.delete(water.summary!.entries.single.id);
      expect(water.todaySummary!.totalMl, 0);
      water.dispose();
    },
  );

  test('past-day entries and Today summary stay separate', () async {
    final water = controller(_WaterGateway());
    await water.initialize();
    await water.selectDay(DateTime(2026, 9, 1));
    await water.add(500);
    expect(water.summary!.day, '2026-09-01');
    expect(water.summary!.totalMl, 500);
    expect(water.todaySummary!.day, '2026-09-02');
    expect(water.todaySummary!.totalMl, 0);
    water.dispose();
  });

  test(
    'account changes discard in-flight display and cannot resend another owner pending entry',
    () async {
      var owner = 'owner-a';
      final gateway = _WaterGateway();
      final store = _MemoryStore();
      final water = HydrationController(
        gateway: gateway,
        ownerId: owner,
        currentOwnerId: () => owner,
        store: store,
        now: () => date,
      );
      await water.initialize();
      gateway.loseNextResponse = true;
      await water.add(250);
      gateway.delayedRead = Completer<HydrationSummary>();
      final refresh = water.refresh();
      owner = 'owner-b';
      water.invalidate();
      await water.retryAdd();
      expect(gateway.submitted.length, 1);
      gateway.delayedRead!.complete(
        HydrationSummary(
          day: '2026-09-02',
          timezoneOffsetMinutes: 0,
          targetMl: null,
          totalMl: 250,
          remainingMl: null,
          entries: gateway.entries.values.toList(),
        ),
      );
      await refresh;
      expect(water.summary, isNull);
      expect(water.todaySummary, isNull);
      expect(store.values.containsKey('owner-a'), isTrue);
      expect(await store.read('owner-b'), isNull);
      water.dispose();
    },
  );

  test('water formatting retains meaningful milliliters', () {
    expect(formatWater(250), '250 ml');
    expect(formatWater(1000), '1 L');
    expect(formatWater(1250), '1.25 L');
    expect(formatWater(1001), '1.001 L');
  });

  test(
    'rejected additions clear pending identity and retain rejection after refresh',
    () async {
      for (final status in [409, 422]) {
        final gateway = _WaterGateway()
          ..rejectAdd = ApiException('Amount rejected', statusCode: status);
        final store = _MemoryStore();
        final water = controller(gateway, store: store);
        await water.initialize();
        await water.add(250);
        expect(water.pendingAdd, isNull);
        expect(store.values, isEmpty);
        expect(water.canMutate, isTrue);
        expect(gateway.submitted.length, 1);
        expect(water.summary!.totalMl, 0);
        expect(
          water.error,
          status == 409
              ? 'This addition was changed or deleted. Refresh your water log.'
              : 'Amount rejected',
        );
        water.dispose();
      }
    },
  );

  test(
    'retry of a committed deletion accepts absence and refreshes canonical log',
    () async {
      final gateway = _WaterGateway();
      final water = controller(gateway);
      await water.initialize();
      await water.add(250);
      final id = water.summary!.entries.single.id;
      gateway.loseDeleteResponse = true;
      await water.delete(id);
      expect(water.error, isNotNull);
      await water.delete(id);
      expect(water.error, isNull);
      expect(water.summary!.entries, isEmpty);
      water.dispose();
    },
  );

  testWidgets(
    'water screen logs, chooses and clears target, validates custom input',
    (tester) async {
      final water = controller(_WaterGateway());
      await water.initialize();
      await tester.pumpWidget(
        MaterialApp(home: HydrationScreen(controller: water)),
      );
      expect(
        find.text('No daily target set. Choose a target that works for you.'),
        findsOneWidget,
      );
      await tester.tap(find.text('+ 250 ml'));
      await tester.pumpAndSettle();
      expect(find.text('250 ml logged'), findsOneWidget);
      await tester.tap(find.text('Set daily target'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '1500');
      await tester.tap(find.text('Save target'));
      await tester.pumpAndSettle();
      expect(
        find.text('1.25 L remaining · 1.5 L daily target'),
        findsOneWidget,
      );
      await tester.tap(find.text('Change daily target'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Clear target'));
      await tester.pumpAndSettle();
      expect(water.summary!.targetMl, isNull);
      await tester.tap(find.text('Custom amount'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField), '1.5');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(
        find.text('Enter a whole amount from 1 to 5000 ml.'),
        findsOneWidget,
      );
      expect(water.summary!.totalMl, 250);
      await tester.enterText(find.byType(TextFormField), '375');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(water.summary!.totalMl, 625);
      await tester.pumpWidget(const SizedBox());
      water.dispose();
    },
  );

  testWidgets('read errors have a real refresh recovery', (tester) async {
    final gateway = _WaterGateway()..failRead = true;
    final water = controller(gateway);
    await water.initialize();
    await tester.pumpWidget(
      MaterialApp(home: HydrationScreen(controller: water)),
    );
    expect(find.text('Service unavailable'), findsOneWidget);
    gateway.failRead = false;
    await tester.tap(find.text('Refresh water log'));
    await tester.pumpAndSettle();
    expect(find.text('0 ml logged'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    water.dispose();
  });

  testWidgets('entry menu edits and confirms deletion of saved water', (
    tester,
  ) async {
    final water = controller(_WaterGateway());
    await water.initialize();
    await water.add(500);
    await tester.pumpWidget(
      MaterialApp(home: HydrationScreen(controller: water)),
    );
    await tester.ensureVisible(find.byTooltip('Water entry options'));
    await tester.tap(find.byTooltip('Water entry options'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Edit'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField), '300');
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(water.summary!.totalMl, 300);
    await tester.ensureVisible(find.byTooltip('Water entry options'));
    await tester.tap(find.byTooltip('Water entry options'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(find.text('Delete water entry?'), findsOneWidget);
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();
    expect(water.summary!.entries, isEmpty);
    await tester.pumpWidget(const SizedBox());
    water.dispose();
  });
}
