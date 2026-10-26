import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

typedef AccessTokenProvider = String? Function();

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({
    required this.baseUrl,
    AccessTokenProvider? accessToken,
    this.onUnauthorized,
    http.Client? client,
    this.timeout = const Duration(seconds: 20),
  }) : _accessToken = accessToken ?? _noToken,
       _client = client ?? http.Client();

  final String baseUrl;
  final AccessTokenProvider _accessToken;
  final void Function()? onUnauthorized;
  final http.Client _client;
  final Duration timeout;

  static String? _noToken() => null;

  Future<Object?> get(String path, {Map<String, String>? query}) =>
      request('GET', path, query: query);

  Future<Object?> post(String path, {Object? body}) =>
      request('POST', path, body: body);

  Future<Object?> put(String path, {Object? body}) =>
      request('PUT', path, body: body);

  Future<Object?> patch(String path, {Object? body}) =>
      request('PATCH', path, body: body);

  Future<Object?> delete(String path, {Object? body}) =>
      request('DELETE', path, body: body);

  Future<Object?> postMultipart(
    String path, {
    required Map<String, String> fields,
    required String fileField,
    required Uint8List fileBytes,
    required String filename,
    required String mimeType,
  }) async {
    final root = baseUrl.replaceFirst(RegExp(r'/$'), '');
    final request = http.MultipartRequest('POST', Uri.parse('$root$path'))
      ..headers['Accept'] = 'application/json'
      ..fields.addAll(fields)
      ..files.add(
        http.MultipartFile.fromBytes(
          fileField,
          fileBytes,
          filename: filename,
          contentType: MediaType.parse(mimeType),
        ),
      );
    final token = _accessToken();
    if (token != null && token.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    return _send(request);
  }

  Future<Object?> request(
    String method,
    String path, {
    Map<String, String>? query,
    Object? body,
  }) async {
    final root = baseUrl.replaceFirst(RegExp(r'/$'), '');
    var uri = Uri.parse('$root$path');
    if (query != null) uri = uri.replace(queryParameters: query);
    final headers = <String, String>{'Accept': 'application/json'};
    final token = _accessToken();
    if (token != null && token.isNotEmpty) {
      headers['Authorization'] = 'Bearer $token';
    }
    if (body != null) headers['Content-Type'] = 'application/json';
    final request = http.Request(method, uri)..headers.addAll(headers);
    if (body != null) request.body = jsonEncode(body);
    return _send(request);
  }

  Future<Object?> _send(http.BaseRequest request) async {
    final http.StreamedResponse streamed;
    try {
      streamed = await _client.send(request).timeout(timeout);
    } on TimeoutException {
      throw const ApiException(
        'The server took too long to respond. Please check your connection and try again.',
        statusCode: 408,
      );
    } on http.ClientException {
      throw const ApiException(
        "We couldn't reach NutriLens right now. Check your connection and try again.",
        statusCode: 503,
      );
    } on Object catch (error) {
      if (error is ApiException) rethrow;
      final errStr = error.toString().toLowerCase();
      if (errStr.contains('socket') ||
          errStr.contains('connection') ||
          errStr.contains('handshake') ||
          errStr.contains('network') ||
          errStr.contains('failed host lookup')) {
        throw const ApiException(
          "We couldn't reach NutriLens right now. Check your connection and try again.",
          statusCode: 503,
        );
      }
      throw const ApiException(
        "We couldn't reach NutriLens right now. Check your connection and try again.",
      );
    }

    final http.Response response;
    try {
      response = await http.Response.fromStream(streamed);
    } on TimeoutException {
      throw const ApiException(
        'The server took too long to respond. Please check your connection and try again.',
        statusCode: 408,
      );
    } on Object {
      throw const ApiException(
        "We couldn't reach NutriLens right now. Check your connection and try again.",
      );
    }

    Object? decoded;
    if (response.body.isNotEmpty) {
      try {
        decoded = jsonDecode(response.body);
      } on FormatException {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          throw ApiException(
            'The server returned an invalid response.',
            statusCode: response.statusCode,
          );
        }
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      if (isSessionExpired(response, decoded)) {
        onUnauthorized?.call();
      }
      final serverMsg = _errorMessage(decoded);
      final String message;
      if (serverMsg != null && serverMsg.isNotEmpty) {
        message = serverMsg;
      } else if (response.statusCode == 401) {
        message = 'Email or password is incorrect.';
      } else if (response.statusCode == 403) {
        message = 'You do not have permission to access this resource.';
      } else if (response.statusCode == 404) {
        message = 'The requested resource was not found.';
      } else if (response.statusCode >= 500) {
        message =
            'NutriLens is temporarily unavailable. Please try again shortly.';
      } else {
        message = 'Request failed (${response.statusCode}).';
      }
      throw ApiException(
        message,
        statusCode: response.statusCode,
      );
    }
    return decoded;
  }

  static bool isSessionExpired(http.Response response, Object? decoded) {
    if (response.statusCode != 401) return false;
    final authHeader = response.headers['www-authenticate']?.toLowerCase() ?? '';
    final authError = response.headers['x-auth-error']?.toUpperCase() ?? '';
    if (authError == 'SESSION_EXPIRED' || authHeader.contains('invalid_token')) {
      return true;
    }
    final message = _errorMessage(decoded)?.toLowerCase() ?? '';
    if (message.contains('session') &&
        (message.contains('expired') ||
            message.contains('revoked') ||
            message.contains('invalid') ||
            message.contains('no longer exists'))) {
      return true;
    }
    if (message == 'authentication required.' ||
        message == 'invalid session subject.') {
      return true;
    }
    return false;
  }

  static String? _errorMessage(Object? decoded) {
    if (decoded is! Map<String, dynamic>) return null;
    final detail = decoded['detail'];
    if (detail is String) return detail;
    if (detail is Map<String, dynamic>) return detail['message']?.toString();
    return null;
  }
}
