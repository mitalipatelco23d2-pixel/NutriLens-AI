import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nutrilens_x/health_connect_screen.dart';
import 'package:nutrilens_x/services/health_connect.dart';

class _MemoryStore implements HealthConnectPreferenceStore {
  final values = <String, bool>{};

  @override
  Future<bool> loadSyncEnabled(String ownerId) async =>
      values[ownerId] ?? false;

  @override
  Future<void> saveSyncEnabled(String ownerId, bool enabled) async {
    values[ownerId] = enabled;
  }
}

class _FakeGateway implements HealthConnectGateway {
  HealthConnectAvailability currentAvailability =
      HealthConnectAvailability.available;
  HealthConnectReadAccess currentAccess = HealthConnectReadAccess.none;
  HealthConnectReadAccess authorizationResult = HealthConnectReadAccess.none;
  int availabilityCalls = 0;
  int permissionChecks = 0;
  int permissionRequests = 0;
  int readCalls = 0;
  int revokeCalls = 0;
  int installCalls = 0;
  bool failRevoke = false;
  DateTime? readStart;
  DateTime? readEnd;
  List<HealthConnectRecord> records = [];

  @override
  Future<HealthConnectAvailability> availability() async {
    availabilityCalls++;
    return currentAvailability;
  }

  @override
  Future<HealthConnectReadAccess> readAccess() async {
    permissionChecks++;
    return currentAccess;
  }

  @override
  Future<HealthConnectReadAccess> requestReadAccess() async {
    permissionRequests++;
    currentAccess = authorizationResult;
    return authorizationResult;
  }

  @override
  Future<List<HealthConnectRecord>> read({
    required DateTime start,
    required DateTime end,
    required Set<HealthConnectRecordKind> kinds,
  }) async {
    readCalls++;
    readStart = start;
    readEnd = end;
    return records.where((record) => kinds.contains(record.kind)).toList();
  }

  @override
  Future<void> revokeAccess() async {
    revokeCalls++;
    if (failRevoke) throw StateError('system revoke failed');
    currentAccess = HealthConnectReadAccess.none;
  }

  @override
  Future<void> openInstallFlow() async => installCalls++;
}

void main() {
  test(
    'loading checks availability only and keeps opt-in owner scoped',
    () async {
      final gateway = _FakeGateway();
      final store = _MemoryStore()..values['owner-one'] = true;
      final coordinator = HealthConnectCoordinator(
        gateway: gateway,
        store: store,
      );

      final ownerOne = await coordinator.load('owner-one');
      final ownerTwo = await coordinator.load('owner-two');

      expect(ownerOne.syncEnabled, isTrue);
      expect(ownerTwo.syncEnabled, isFalse);
      expect(gateway.availabilityCalls, 2);
      expect(gateway.permissionChecks, 0);
      expect(gateway.permissionRequests, 0);
      expect(gateway.readCalls, 0);
    },
  );

  test(
    'connect is blocked while sync is off and only explicit when on',
    () async {
      final gateway = _FakeGateway()
        ..authorizationResult = const HealthConnectReadAccess(
          water: true,
          weight: true,
        );
      final store = _MemoryStore();
      final coordinator = HealthConnectCoordinator(
        gateway: gateway,
        store: store,
      );

      expect((await coordinator.connect('owner')).any, isFalse);
      expect(gateway.permissionRequests, 0);

      await coordinator.setSyncEnabled('owner', true);
      expect((await coordinator.connect('owner')).all, isTrue);
      expect(gateway.permissionRequests, 1);
    },
  );

  test('sync never prompts and does not read without permission', () async {
    final gateway = _FakeGateway();
    final store = _MemoryStore()..values['owner'] = true;
    final coordinator = HealthConnectCoordinator(
      gateway: gateway,
      store: store,
    );

    await expectLater(coordinator.sync('owner'), throwsStateError);

    expect(gateway.permissionChecks, 1);
    expect(gateway.permissionRequests, 0);
    expect(gateway.readCalls, 0);
  });

  test('builds a bounded in-memory hydration and weight preview', () async {
    final now = DateTime(2026, 9, 7, 12);
    final gateway = _FakeGateway()
      ..currentAccess = const HealthConnectReadAccess(water: true, weight: true)
      ..records = [
        HealthConnectRecord(
          kind: HealthConnectRecordKind.water,
          value: 0.5,
          recordedAt: DateTime(2026, 9, 7, 8),
          sourceName: 'Watch',
        ),
        HealthConnectRecord(
          kind: HealthConnectRecordKind.water,
          value: 0.75,
          recordedAt: DateTime(2026, 9, 6, 8),
          sourceName: 'Phone',
        ),
        HealthConnectRecord(
          kind: HealthConnectRecordKind.weight,
          value: 71,
          recordedAt: DateTime(2026, 8, 30),
          sourceName: 'Scale',
        ),
        HealthConnectRecord(
          kind: HealthConnectRecordKind.weight,
          value: 70.2,
          recordedAt: DateTime(2026, 9, 7, 7),
          sourceName: 'Scale',
        ),
        HealthConnectRecord(
          kind: HealthConnectRecordKind.water,
          value: 99,
          recordedAt: DateTime(2026, 7, 1),
          sourceName: 'Outside window',
        ),
      ];
    final store = _MemoryStore()..values['owner'] = true;
    final coordinator = HealthConnectCoordinator(
      gateway: gateway,
      store: store,
      now: () => now,
    );

    final snapshot = await coordinator.sync('owner');

    expect(gateway.readStart, now.subtract(const Duration(days: 30)));
    expect(gateway.readEnd, now);
    expect(snapshot.waterTodayLiters, 0.5);
    expect(snapshot.latestWeightKg, 70.2);
    expect(snapshot.latestWeightAt, DateTime(2026, 9, 7, 7));
    expect(snapshot.waterRecordCount, 2);
    expect(snapshot.weightRecordCount, 2);
    expect(snapshot.sourceNames, ['Phone', 'Scale', 'Watch']);
  });

  test('partial permission reads only the granted data type', () async {
    final now = DateTime(2026, 9, 7, 12);
    final gateway = _FakeGateway()
      ..currentAccess = const HealthConnectReadAccess(
        water: true,
        weight: false,
      )
      ..records = [
        HealthConnectRecord(
          kind: HealthConnectRecordKind.water,
          value: 0.4,
          recordedAt: DateTime(2026, 9, 7, 9),
          sourceName: 'Phone',
        ),
        HealthConnectRecord(
          kind: HealthConnectRecordKind.weight,
          value: 70,
          recordedAt: DateTime(2026, 9, 7, 9),
          sourceName: 'Scale',
        ),
      ];
    final coordinator = HealthConnectCoordinator(
      gateway: gateway,
      store: _MemoryStore()..values['owner'] = true,
      now: () => now,
    );

    final snapshot = await coordinator.sync('owner');

    expect(snapshot.access.water, isTrue);
    expect(snapshot.access.weight, isFalse);
    expect(snapshot.waterTodayLiters, 0.4);
    expect(snapshot.latestWeightKg, isNull);
    expect(snapshot.weightRecordCount, 0);
  });

  testWidgets('permission is requested only after Connect is tapped', (
    tester,
  ) async {
    final gateway = _FakeGateway()
      ..authorizationResult = const HealthConnectReadAccess(
        water: true,
        weight: true,
      );
    final coordinator = HealthConnectCoordinator(
      gateway: gateway,
      store: _MemoryStore(),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: HealthConnectScreen(ownerId: 'owner', healthConnect: coordinator),
      ),
    );
    await tester.pumpAndSettle();

    expect(gateway.permissionRequests, 0);
    await tester.tap(find.byKey(const Key('health-connect-sync-toggle')));
    await tester.pumpAndSettle();
    expect(gateway.permissionRequests, 0);

    await tester.tap(find.byKey(const Key('connect-health-connect')));
    await tester.pumpAndSettle();
    expect(gateway.permissionRequests, 1);
    expect(find.textContaining('Hydration and weight'), findsOneWidget);
  });

  testWidgets('disconnect confirmation revokes access and pauses sync', (
    tester,
  ) async {
    final gateway = _FakeGateway()
      ..currentAccess = const HealthConnectReadAccess(
        water: true,
        weight: true,
      );
    final store = _MemoryStore()..values['owner'] = true;
    final coordinator = HealthConnectCoordinator(
      gateway: gateway,
      store: store,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: HealthConnectScreen(ownerId: 'owner', healthConnect: coordinator),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('disconnect-health-connect')));
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const Key('confirm-health-connect-disconnect')),
    );
    await tester.pumpAndSettle();

    expect(gateway.revokeCalls, 1);
    expect(store.values['owner'], isFalse);
    expect(find.textContaining('access revoked'), findsOneWidget);
  });

  test('disconnect still pauses local sync when system revoke fails', () async {
    final gateway = _FakeGateway()..failRevoke = true;
    final store = _MemoryStore()..values['owner'] = true;
    final coordinator = HealthConnectCoordinator(
      gateway: gateway,
      store: store,
    );

    await expectLater(coordinator.disconnect('owner'), throwsStateError);

    expect(gateway.revokeCalls, 1);
    expect(store.values['owner'], isFalse);
  });
}
