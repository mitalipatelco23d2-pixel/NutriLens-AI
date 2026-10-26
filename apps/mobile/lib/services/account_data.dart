import 'dart:convert';
import 'dart:ui';

import 'package:share_plus/share_plus.dart';

import 'product_api.dart';

enum AccountExportDisposition { success, dismissed, unavailable }

abstract interface class AccountExportSharer {
  Future<AccountExportDisposition> shareJson({
    required String filename,
    required String content,
    Rect? sharePositionOrigin,
  });
}

class PlatformAccountExportSharer implements AccountExportSharer {
  @override
  Future<AccountExportDisposition> shareJson({
    required String filename,
    required String content,
    Rect? sharePositionOrigin,
  }) async {
    final result = await SharePlus.instance.share(
      ShareParams(
        files: [
          XFile.fromData(utf8.encode(content), mimeType: 'application/json'),
        ],
        fileNameOverrides: [filename],
        subject: 'NutriLens account export',
        sharePositionOrigin: sharePositionOrigin,
        downloadFallbackEnabled: true,
      ),
    );
    return switch (result.status) {
      ShareResultStatus.success => AccountExportDisposition.success,
      ShareResultStatus.dismissed => AccountExportDisposition.dismissed,
      ShareResultStatus.unavailable => AccountExportDisposition.unavailable,
    };
  }
}

class AccountExportResult {
  const AccountExportResult({
    required this.filename,
    required this.byteLength,
    required this.disposition,
  });

  final String filename;
  final int byteLength;
  final AccountExportDisposition disposition;
}

class AccountDataCoordinator {
  AccountDataCoordinator({
    required this.gateway,
    AccountExportSharer? sharer,
    DateTime Function()? now,
  }) : _sharer = sharer ?? PlatformAccountExportSharer(),
       _now = now ?? DateTime.now;

  final ProductGateway gateway;
  final AccountExportSharer _sharer;
  final DateTime Function() _now;

  Future<AccountExportResult> export({Rect? sharePositionOrigin}) async {
    final payload = await gateway.exportAccount();
    final content = const JsonEncoder.withIndent('  ').convert(payload);
    final now = _now();
    final filename =
        'nutrilens-export-${now.year.toString().padLeft(4, '0')}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}.json';
    final disposition = await _sharer.shareJson(
      filename: filename,
      content: content,
      sharePositionOrigin: sharePositionOrigin,
    );
    return AccountExportResult(
      filename: filename,
      byteLength: utf8.encode(content).length,
      disposition: disposition,
    );
  }

  Future<void> deleteAccount() => gateway.deleteAccount();
}
