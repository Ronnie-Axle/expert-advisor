import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  const ApiException(this.message);

  final String message;

  @override
  String toString() => message;
}

class ScalperApi {
  ScalperApi(String baseUrl, {http.Client? client})
      : baseUrl = baseUrl.trim().replaceFirst(RegExp(r'/+$'), ''),
        _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Future<Map<String, dynamic>> fetchStatus() async {
    final response = await _send('GET', '/api/v1/bot/status');
    return _decodeMap(response);
  }

  Future<List<Map<String, dynamic>>> fetchTraces() async {
    final response = await _send('GET', '/api/v1/traces?limit=30');
    final decoded = jsonDecode(response.body);
    if (decoded is! List) {
      throw const ApiException('The API returned an invalid activity response.');
    }
    return decoded.whereType<Map<String, dynamic>>().toList();
  }

  Future<Map<String, dynamic>> scanNow() async {
    final response = await _send('POST', '/api/v1/bot/scan-now');
    return _decodeMap(response);
  }

  Future<Map<String, dynamic>> emergencyCloseAll() async {
    final response = await _send('POST', '/api/v1/bot/emergency-close-all');
    return _decodeMap(response);
  }

  Future<http.Response> _send(String method, String path) async {
    final uri = Uri.parse('$baseUrl$path');
    try {
      final response = method == 'GET'
          ? await _client.get(uri).timeout(const Duration(seconds: 8))
          : await _client.post(uri).timeout(const Duration(seconds: 20));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        var message = 'API request failed (${response.statusCode}).';
        try {
          final body = jsonDecode(response.body);
          if (body is Map && body['detail'] is String) {
            message = body['detail'] as String;
          }
        } on FormatException {
          // Keep the useful HTTP status message when the response is not JSON.
        }
        throw ApiException(message);
      }
      return response;
    } on ApiException {
      rethrow;
    } on Exception catch (error) {
      throw ApiException('Cannot reach $baseUrl. ${error.toString()}');
    }
  }

  Map<String, dynamic> _decodeMap(http.Response response) {
    final decoded = jsonDecode(response.body);
    if (decoded is! Map<String, dynamic>) {
      throw const ApiException('The API returned an invalid response.');
    }
    return decoded;
  }

  void close() => _client.close();
}
