import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nutrilens_x/services/weight_models.dart';
import 'package:nutrilens_x/weight_screen.dart';

class _WeightMemory implements WeightGateway {
  var enabled = false;
  double? target;
  final entries = <WeightEntry>[];

  @override
  Future<WeightSummary> weightSummary({int limit = 180}) async {
    final returned = entries.take(limit).toList(growable: false);
    final latest = returned.isEmpty ? null : returned.first.weightKg;
    final first = returned.length > 1 ? returned.last.weightKg : null;
    return WeightSummary(
      state: enabled ? 'ACTIVE' : 'DISABLED',
      targetWeightKg: target,
      latestWeightKg: latest,
      changeFromFirstKg: latest == null || first == null
          ? null
          : latest - first,
      differenceFromTargetKg: latest == null || target == null
          ? null
          : latest - target!,
      entries: enabled ? returned : const [],
      method: 'SELF_REPORTED_WEIGHT_DIFFERENCE_V1',
      limitation:
          'Descriptive self-reported records only. NutriLens does not assign an ideal weight.',
    );
  }

  @override
  Future<WeightSettings> enableWeightTracking(double? targetWeightKg) async {
    enabled = true;
    target = targetWeightKg;
    return WeightSettings(state: 'ACTIVE', targetWeightKg: target);
  }

  @override
  Future<void> disableWeightTracking() async {
    enabled = false;
    target = null;
    entries.clear();
  }

  @override
  Future<WeightEntry> addWeight(WeightEntry entry) async {
    entries.insert(0, entry);
    return entry;
  }

  @override
  Future<WeightEntry> updateWeight(WeightEntry entry) async {
    final index = entries.indexWhere((item) => item.id == entry.id);
    entries[index] = entry;
    return entry;
  }

  @override
  Future<void> deleteWeight(String id) async {
    entries.removeWhere((entry) => entry.id == id);
  }
}

void main() {
  testWidgets(
    'weight tracking requires consent and can erase account history',
    (tester) async {
      tester.view.physicalSize = const Size(1080, 2200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final gateway = _WeightMemory();

      await tester.pumpWidget(
        MaterialApp(home: WeightScreen(gateway: gateway)),
      );
      await tester.pumpAndSettle();

      expect(find.text('Weight tracking is off'), findsOneWidget);
      expect(find.textContaining('ideal weight'), findsOneWidget);
      await tester.tap(find.byKey(const Key('enable-weight')));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('stored in your NutriLens account'),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('confirm-enable-weight')));
      await tester.pumpAndSettle();
      expect(gateway.enabled, isTrue);
      expect(find.text('No weight records yet.'), findsOneWidget);

      await tester.tap(find.byKey(const Key('add-weight')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('weight-value')), '70');
      await tester.pump();
      await tester.tap(find.byKey(const Key('confirm-add-weight')));
      await tester.pumpAndSettle();
      expect(find.text('70 kg'), findsNWidgets(2));
      expect(gateway.entries, hasLength(1));

      await tester.ensureVisible(find.byKey(const Key('disable-weight')));
      await tester.tap(find.byKey(const Key('disable-weight')));
      await tester.pumpAndSettle();
      expect(find.textContaining('permanently deletes'), findsOneWidget);
      await tester.tap(find.byKey(const Key('confirm-disable-weight')));
      await tester.pumpAndSettle();
      expect(gateway.enabled, isFalse);
      expect(gateway.entries, isEmpty);
      expect(find.text('Weight tracking is off'), findsOneWidget);
    },
  );
}
