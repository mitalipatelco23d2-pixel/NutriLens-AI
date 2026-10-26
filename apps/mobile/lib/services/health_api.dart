import 'dart:convert';

import 'package:http/http.dart' as http;

class HealthSnapshot {
  const HealthSnapshot({required this.status, required this.services});

  factory HealthSnapshot.fromJson(Map<String, dynamic> json) {
    final rawServices = json['services'];
    if (json['status'] is! String || rawServices is! Map<String, dynamic>) {
      throw const FormatException('Invalid health response');
    }

    return HealthSnapshot(
      status: json['status'] as String,
      services: rawServices.map(
        (key, value) => MapEntry(key, value.toString()),
      ),
    );
  }

  final String status;
  final Map<String, String> services;

  bool get isHealthy => status == 'healthy';
}

abstract interface class HealthGateway {
  Future<HealthSnapshot> fetchHealth();
}

class HealthApi implements HealthGateway {
  HealthApi({required this.baseUrl, http.Client? client})
    : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  @override
  Future<HealthSnapshot> fetchHealth() async {
    final endpoint = Uri.parse(
      '${baseUrl.replaceFirst(RegExp(r'/$'), '')}/api/v1/health',
    );
    final response = await _client
        .get(endpoint, headers: const {'Accept': 'application/json'})
        .timeout(const Duration(seconds: 5));

    if (response.statusCode != 200) {
      throw HealthApiException('Backend returned ${response.statusCode}.');
    }

    try {
      return HealthSnapshot.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    } on FormatException catch (error) {
      throw HealthApiException(
        'Backend returned an invalid health response.',
        error,
      );
    }
  }
}

class HealthApiException implements Exception {
  const HealthApiException(this.message, [this.cause]);

  final String message;
  final Object? cause;

  @override
  String toString() => message;
}
