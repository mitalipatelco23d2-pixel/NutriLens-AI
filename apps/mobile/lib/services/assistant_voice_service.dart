import 'package:flutter_tts/flutter_tts.dart';
import 'package:speech_to_text/speech_to_text.dart';

abstract interface class AssistantVoiceGateway {
  Future<bool> initialize({
    required void Function(String status) onStatus,
    required void Function(String error) onError,
  });
  Future<void> startListening(void Function(String transcript) onTranscript);
  Future<void> stopListening();
  Future<void> speak(String text);
  Future<void> stopSpeaking();
  Future<void> dispose();
}

class PlatformAssistantVoice implements AssistantVoiceGateway {
  PlatformAssistantVoice({SpeechToText? speech, FlutterTts? tts})
    : _speech = speech ?? SpeechToText(),
      _tts = tts ?? FlutterTts();

  final SpeechToText _speech;
  final FlutterTts _tts;

  @override
  Future<bool> initialize({
    required void Function(String status) onStatus,
    required void Function(String error) onError,
  }) => _speech.initialize(
    onStatus: onStatus,
    onError: (error) => onError(error.errorMsg),
  );

  @override
  Future<void> startListening(
    void Function(String transcript) onTranscript,
  ) async {
    await _speech.listen(
      onResult: (result) => onTranscript(result.recognizedWords),
      listenOptions: SpeechListenOptions(
        listenMode: ListenMode.dictation,
        partialResults: true,
      ),
    );
  }

  @override
  Future<void> stopListening() => _speech.stop();

  @override
  Future<void> speak(String text) async {
    await _tts.stop();
    await _tts.setLanguage('en-IN');
    await _tts.speak(text);
  }

  @override
  Future<void> stopSpeaking() => _tts.stop();

  @override
  Future<void> dispose() async {
    await _speech.stop();
    await _tts.stop();
  }
}
