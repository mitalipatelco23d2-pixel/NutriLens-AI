import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/authenticated_shell.dart';
import 'package:nutrilens_x/services/api_client.dart';
import 'package:nutrilens_x/services/assistant_voice_service.dart';
import 'package:nutrilens_x/services/product_api.dart';

void main() {
  testWidgets('dictates editable text and reads an opted-in answer aloud', (
    tester,
  ) async {
    final voice = _FakeVoice();
    String? requestBody;
    final products = ProductApi(
      ApiClient(
        baseUrl: 'https://api.example',
        client: MockClient((request) async {
          requestBody = request.body;
          return http.Response(
            '{"answer":"Fiber is a dietary carbohydrate.","evidence":["Package label"],"citations":[{"evidence_id":"nih-1","title":"Fiber guidance","authority":"NIH","url":"https://example.org/fiber"}],"remaining_today":4,"generation_mode":"DETERMINISTIC","method":"GOVERNED_RETRIEVAL","disclaimer":"General wellness guidance."}',
            200,
            headers: {'content-type': 'application/json'},
          );
        }),
      ),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: AssistantScreen(
          products: products,
          voice: voice,
          scanId: 'scan-1',
        ),
      ),
    );
    await tester.pump();
    expect(voice.initialized, isFalse);
    expect(
      find.text('Voice input is optional. Tap the microphone to enable it.'),
      findsOneWidget,
    );

    await tester.tap(find.byTooltip('Dictate question'));
    await tester.pump();
    expect(voice.initialized, isTrue);
    expect(find.text('What is fiber?'), findsOneWidget);

    await tester.tap(find.byTooltip('Read answers aloud'));
    await tester.tap(find.widgetWithText(FilledButton, 'Ask Nutri'));
    await tester.pumpAndSettle();

    expect(find.text('Fiber is a dietary carbohydrate.'), findsOneWidget);
    expect(find.text('Using the current scan'), findsOneWidget);
    expect(find.text('NIH · Fiber guidance'), findsOneWidget);
    expect(jsonDecode(requestBody!)['scan_id'], 'scan-1');
    expect(voice.spoken, 'Fiber is a dietary carbohydrate.');
  });
}

class _FakeVoice implements AssistantVoiceGateway {
  bool initialized = false;
  String? spoken;

  @override
  Future<bool> initialize({
    required void Function(String status) onStatus,
    required void Function(String error) onError,
  }) async {
    initialized = true;
    return true;
  }

  @override
  Future<void> startListening(
    void Function(String transcript) onTranscript,
  ) async {
    onTranscript('What is fiber?');
  }

  @override
  Future<void> speak(String text) async => spoken = text;

  @override
  Future<void> stopListening() async {}

  @override
  Future<void> stopSpeaking() async {}

  @override
  Future<void> dispose() async {}
}
