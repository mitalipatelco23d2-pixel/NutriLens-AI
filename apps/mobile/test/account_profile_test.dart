import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/account_profile_screen.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/product_api.dart';

void main() {
  testWidgets('profile editor keeps masked phone and saves explicit consent', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1080, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    String? accountBody;
    String? healthBody;
    final httpClient = MockClient((request) async {
      if (request.url.path == '/api/v1/profile') {
        if (request.method == 'PUT') healthBody = request.body;
        return http.Response(_healthProfile, 200);
      }
      if (request.url.path == '/api/v1/account/profile' &&
          request.method == 'PUT') {
        accountBody = request.body;
        return http.Response(
          _savedAccountProfile,
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('{"detail":"not found"}', 404);
    });
    final products = ProductApi(
      ApiClient(baseUrl: 'https://api.example', client: httpClient),
    );
    AccountProfile? result;

    await tester.pumpWidget(
      MaterialApp(
        home: AccountProfileEditor(
          initial: AccountProfile.fromJson(
            jsonDecode(_accountProfile) as Map<String, dynamic>,
          ),
          email: 'owner@example.com',
          products: products,
          onboarding: false,
          onSaved: (profile) async => result = profile,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('+••••••••3210'), findsNWidgets(2));
    expect(find.textContaining('+919876543210'), findsNothing);
    expect(
      find.textContaining('SMS verification is not enabled'),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const Key('profile-next-0')).hitTestable());
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('profile-phone')),
      '+447700900123',
    );
    await tester.tap(find.byKey(const Key('profile-next-1')).hitTestable());
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('profile-goal')));
    await tester.tap(find.byKey(const Key('profile-goal')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Custom goal').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('profile-custom-goal')),
      'Cook at home more often',
    );
    await tester.ensureVisible(find.byKey(const Key('research-consent')));
    await tester.tap(find.byKey(const Key('research-consent')));
    final saveButton = find.byKey(const Key('save-profile')).at(2);
    await tester.ensureVisible(saveButton);
    await tester.tap(saveButton);
    await tester.pumpAndSettle();

    expect(result?.fullName, 'Yash Owner');
    final savedAccount = jsonDecode(accountBody!) as Map<String, dynamic>;
    expect(savedAccount['phone_update'], 'SET');
    expect(savedAccount['phone_number'], '+447700900123');
    expect(savedAccount['research_insights_consent'], isTrue);
    expect(savedAccount['complete_onboarding'], isFalse);
    final savedHealth = jsonDecode(healthBody!) as Map<String, dynamic>;
    expect(savedHealth['goal'], 'custom');
    expect(savedHealth['custom_goal'], 'Cook at home more often');
    expect(savedHealth['consent_personalization'], isFalse);
  });
}

const _accountProfile = '''
{"full_name":"Yash Owner","date_of_birth":"1990-01-02","masked_phone_number":"+••••••••3210","phone_state":"UNVERIFIED","phone_verification_availability":"BLOCKED_EXTERNAL_COST","country_region":"IN","unit_system":"METRIC","research_insights_consent":false,"onboarding_complete":true}
''';

const _savedAccountProfile = '''
{"full_name":"Yash Owner","date_of_birth":"1990-01-02","masked_phone_number":"+••••••••0123","phone_state":"UNVERIFIED","phone_verification_availability":"BLOCKED_EXTERNAL_COST","country_region":"IN","unit_system":"METRIC","research_insights_consent":true,"onboarding_complete":true}
''';

const _healthProfile = '''
{"goal":"balanced","allergens":[],"dietary_preferences":[],"consent_personalization":false,"daily_targets":{},"body_context":{"adult_attestation":false,"consent_bmi_context":false,"height_cm":null,"weight_kg":null}}
''';
