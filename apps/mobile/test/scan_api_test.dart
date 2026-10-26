import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nutrilens_x/services/scan_api.dart';
import 'package:nutrilens_x/services/client_inference.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final kind in ['product', 'ocr', 'image']) {
    test(
      'preferred $kind sends bound evidence and completes without polling',
      () async {
        final pending = _PendingStore();
        final cache = _MemoryScanCache();
        var requests = 0;
        final api = ScanApi(
          baseUrl: 'https://api.example',
          accessToken: () => 'session',
          userId: () => 'owner',
          pendingJobs: pending,
          cache: cache,
          delay: (_) async => fail('Immediate COMPLETE must not delay or poll'),
          client: MockClient((request) async {
            requests++;
            expect(request.method, 'POST');
            expect(request.url.path, '/api/v1/scan/jobs/$kind');
            expect(request.headers['authorization'], 'Bearer session');
            final body = latin1.decode(request.bodyBytes);
            expect(body, contains('name="evidence_json"'));
            expect(body, contains(jsonEncode(_evidence.toJson())));
            expect(
              body,
              contains(
                'name="${kind == 'product' ? 'files' : 'file'}"; filename="label.png"',
              ),
            );
            expect(body, contains(String.fromCharCodes([1, 2, 3])));
            return http.Response(
              jsonEncode({
                ...jsonDecode(_completedJob) as Map<String, dynamic>,
                'client_evidence_decision': 'CLIENT_EVIDENCE_ACCEPTED',
                'client_evidence_reasons': <String>[],
                'server_fallback_required': false,
              }),
              202,
            );
          }),
        );
        final result = await _preferredScan(api, kind: kind);
        expect(result.scanId, 'scan-test');
        expect(result.clientEvidenceDecision, 'CLIENT_EVIDENCE_ACCEPTED');
        expect(result.serverFallbackRequired, isFalse);
        expect(requests, 1);
        expect(await pending.readPending('owner'), isNull);
        expect((await cache.read('owner'))?.scanId, 'scan-test');
        expect(await cache.read('other'), isNull);
      },
    );
  }

  test(
    'rejected preferred evidence uses existing polling and retains fallback decision',
    () async {
      final calls = <String>[];
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        pendingJobs: _PendingStore(),
        pollInterval: Duration.zero,
        client: MockClient((request) async {
          calls.add(request.method);
          if (request.method == 'POST') {
            return http.Response(
              jsonEncode({
                ...jsonDecode(_acceptedJob) as Map<String, dynamic>,
                'client_evidence_decision': 'SERVER_FALLBACK_REQUIRED',
                'client_evidence_reasons': ['INSUFFICIENT_NUTRIENT_ROWS'],
                'server_fallback_required': true,
              }),
              202,
            );
          }
          expect(request.url.path, '/api/v1/scan/jobs/job-test');
          return http.Response(_completedJob, 200);
        }),
      );
      final result = await _preferredScan(api);
      expect(calls, ['POST', 'GET']);
      expect(result.clientEvidenceDecision, 'SERVER_FALLBACK_REQUIRED');
      expect(result.clientEvidenceReasons, ['INSUFFICIENT_NUTRIENT_ROWS']);
      expect(result.serverFallbackRequired, isTrue);
    },
  );

  test(
    'preferred submission resumes an existing owner job without uploading evidence',
    () async {
      final pending = _PendingStore()
        ..jobs['owner'] = const PendingScanJob(
          ownerId: 'owner',
          jobId: 'job-test',
        );
      var calls = 0;
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        pendingJobs: pending,
        client: MockClient((request) async {
          calls++;
          expect(request.method, 'GET');
          expect(request.body, isEmpty);
          return http.Response(_completedJob, 200);
        }),
      );
      expect((await _preferredScan(api)).scanId, 'scan-test');
      expect(calls, 1);
      expect(await pending.readPending('owner'), isNull);
    },
  );

  test(
    'preferred API refuses shadow, disabled, unknown kind and ownerless requests',
    () async {
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        client: MockClient((_) async => throw StateError('must not send')),
      );
      for (final mode in [
        AndroidClientInferenceMode.shadow,
        AndroidClientInferenceMode.disabled,
      ]) {
        final capabilities = ClientInferenceCapabilities(
          contractVersion: clientInferenceContractVersion,
          androidMode: mode,
          evidenceUse: 'SHADOW_COMPARISON_ONLY',
          serverResultAuthoritative: true,
          serverFallbackRequired: true,
        );
        expect(
          () => _preferredScan(api, capabilities: capabilities),
          throwsA(isA<ScanApiException>()),
        );
      }
      expect(
        () => _preferredScan(api, kind: 'barcode'),
        throwsA(isA<ScanApiException>()),
      );
      final anonymous = ScanApi(
        baseUrl: 'https://api.example',
        client: MockClient((_) async => throw StateError('must not send')),
      );
      expect(() => _preferredScan(anonymous), throwsA(isA<ScanApiException>()));
    },
  );

  test(
    'preferred COMPLETE cannot leak a result after the authenticated owner changes',
    () async {
      var owner = 'owner-a';
      final cache = _MemoryScanCache();
      final pending = _PendingStore();
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => owner,
        pendingJobs: pending,
        cache: cache,
        client: MockClient((request) async {
          expect(request.method, 'POST');
          owner = 'owner-b';
          return http.Response(_completedJob, 202);
        }),
      );
      await expectLater(_preferredScan(api), throwsA(isA<ScanApiException>()));
      expect(cache.snapshot, isNull);
      expect(await pending.readPending('owner-b'), isNull);
      expect((await pending.readPending('owner-a'))?.jobId, 'job-test');
      expect(api.currentJobProgress, isNull);
    },
  );

  test(
    'secure pending pointers survive recreation and clear only a matching owner job',
    () async {
      FlutterSecureStorage.setMockInitialValues({});
      const first = SecureScanResultCache();
      await first.writePending(
        const PendingScanJob(ownerId: 'owner-a', jobId: 'job-a'),
      );
      await first.writePending(
        const PendingScanJob(ownerId: 'owner-b', jobId: 'job-b'),
      );
      const recreated = SecureScanResultCache();
      expect((await recreated.readPending('owner-a'))?.jobId, 'job-a');
      expect(await recreated.readPending('unknown-owner'), isNull);
      await recreated.clearPending('owner-a', 'wrong-job');
      expect((await recreated.readPending('owner-a'))?.jobId, 'job-a');
      await recreated.clearPending('owner-a', 'job-a');
      expect(await recreated.readPending('owner-a'), isNull);
      expect((await recreated.readPending('owner-b'))?.jobId, 'job-b');
      final stored = await const FlutterSecureStorage().readAll();
      final payload = jsonDecode(stored.values.single) as Map<String, dynamic>;
      expect(payload.keys, unorderedEquals(['version', 'owner_id', 'job_id']));
      // Signing out clears the last result, not the other owner's durable pointer.
      await recreated.clear();
      expect((await recreated.readPending('owner-b'))?.jobId, 'job-b');
    },
  );

  test(
    'accepted job survives transport failure and a recreated API resumes with GET only',
    () async {
      final pending = _PendingStore();
      final cache = _MemoryScanCache();
      var uploads = 0;
      final first = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        pendingJobs: pending,
        cache: cache,
        pollInterval: Duration.zero,
        client: MockClient((request) async {
          if (request.method == 'POST') {
            uploads++;
            return http.Response(_acceptedJob, 202);
          }
          expect((await pending.readPending('owner'))?.jobId, 'job-test');
          throw http.ClientException('offline');
        }),
      );
      await expectLater(_scan(first), throwsA(isA<ScanApiException>()));
      expect(await first.hasPendingJob(), isTrue);
      var resumedRequests = 0;
      final recreated = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'refreshed-session',
        userId: () => 'owner',
        pendingJobs: pending,
        cache: cache,
        pollInterval: Duration.zero,
        client: MockClient((request) async {
          resumedRequests++;
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/scan/jobs/job-test');
          expect(request.headers['authorization'], 'Bearer refreshed-session');
          return http.Response(_completedJob, 200);
        }),
      );
      expect((await recreated.resumePendingJob())?.scanId, 'scan-test');
      expect(await recreated.hasPendingJob(), isFalse);
      expect((await cache.read('owner'))?.scanId, 'scan-test');
      expect(uploads, 1);
      expect(resumedRequests, 1);
    },
  );

  test(
    're-entry and repeated scan calls share one polling loop with no upload',
    () async {
      final pending = _PendingStore()
        ..jobs['owner'] = const PendingScanJob(
          ownerId: 'owner',
          jobId: 'job-test',
        );
      final response = Completer<http.Response>();
      final requested = Completer<void>();
      var requests = 0;
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        pendingJobs: pending,
        pollInterval: Duration.zero,
        client: MockClient((request) {
          requests++;
          expect(request.method, 'GET');
          requested.complete();
          return response.future;
        }),
      );
      final first = api.resumePendingJob();
      await requested.future;
      final reentry = api.resumePendingJob();
      final scanAgain = _scan(api);
      response.complete(http.Response(_completedJob, 200));
      expect((await first)?.scanId, 'scan-test');
      expect((await reentry)?.scanId, 'scan-test');
      expect((await scanAgain).scanId, 'scan-test');
      expect(requests, 1);
    },
  );

  test('simultaneous submissions and reopen do not create two jobs', () async {
    final pending = _PendingStore();
    final accepted = Completer<http.Response>();
    final submitted = Completer<void>();
    var uploads = 0;
    var polls = 0;
    final api = ScanApi(
      baseUrl: 'https://api.example',
      accessToken: () => 'session',
      userId: () => 'owner',
      pendingJobs: pending,
      pollInterval: Duration.zero,
      client: MockClient((request) {
        if (request.method == 'POST') {
          uploads++;
          submitted.complete();
          return accepted.future;
        }
        polls++;
        return Future.value(http.Response(_completedJob, 200));
      }),
    );
    final first = _scan(api);
    await submitted.future;
    final second = _scan(api);
    final reopened = api.resumePendingJob();
    accepted.complete(http.Response(_acceptedJob, 202));
    await Future.wait([first, second, reopened]);
    expect(uploads, 1);
    expect(polls, 1);
  });

  test(
    '429 keeps the pointer and reports backoff before resuming the same job',
    () async {
      final pending = _PendingStore()
        ..jobs['owner'] = const PendingScanJob(
          ownerId: 'owner',
          jobId: 'job-test',
        );
      var requests = 0;
      final states = <String>[];
      final delays = <Duration>[];
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        pendingJobs: pending,
        delay: (duration) async {
          delays.add(duration);
          expect((await pending.readPending('owner'))?.jobId, 'job-test');
        },
        client: MockClient((request) async {
          expect(request.method, 'GET');
          requests++;
          return requests == 1
              ? http.Response('busy', 429, headers: {'retry-after': '37'})
              : http.Response(_completedJob, 200);
        }),
      );
      final subscription = api.jobProgress.listen(
        (value) => states.add(value.state),
      );
      await api.resumePendingJob();
      await subscription.cancel();
      expect(delays, [Duration.zero, const Duration(seconds: 37)]);
      expect(
        states,
        containsAllInOrder(['RESUMING', 'RATE_LIMITED', 'COMPLETE']),
      );
      expect(await pending.readPending('owner'), isNull);
    },
  );

  for (final state in ['FAILED', 'TIMED_OUT']) {
    test('$state clears only the matching terminal pointer', () async {
      final pending = _PendingStore()
        ..jobs['owner'] = const PendingScanJob(
          ownerId: 'owner',
          jobId: 'job-test',
        )
        ..jobs['other'] = const PendingScanJob(
          ownerId: 'other',
          jobId: 'job-other',
        );
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        pendingJobs: pending,
        pollInterval: Duration.zero,
        client: MockClient(
          (_) async => http.Response(
            jsonEncode({'job_id': 'job-test', 'status': state}),
            200,
          ),
        ),
      );
      await expectLater(
        api.resumePendingJob(),
        throwsA(isA<ScanApiException>()),
      );
      expect(await pending.readPending('owner'), isNull);
      expect((await pending.readPending('other'))?.jobId, 'job-other');
    });
  }

  for (final status in [401, 403, 404, 503]) {
    test('HTTP $status retains pending job without resubmitting', () async {
      final pending = _PendingStore()
        ..jobs['owner'] = const PendingScanJob(
          ownerId: 'owner',
          jobId: 'job-test',
        );
      final api = ScanApi(
        baseUrl: 'https://api.example',
        accessToken: () => 'session',
        userId: () => 'owner',
        pendingJobs: pending,
        pollInterval: Duration.zero,
        client: MockClient((request) async {
          expect(request.method, 'GET');
          return http.Response('unavailable', status);
        }),
      );
      await expectLater(
        api.resumePendingJob(),
        throwsA(isA<ScanApiException>()),
      );
      expect(await api.hasPendingJob(), isTrue);
    });
  }

  test('polling deadline retains pending job for a later resume', () async {
    final pending = _PendingStore()
      ..jobs['owner'] = const PendingScanJob(
        ownerId: 'owner',
        jobId: 'job-test',
      );
    final api = ScanApi(
      baseUrl: 'https://api.example',
      accessToken: () => 'session',
      userId: () => 'owner',
      pendingJobs: pending,
      jobTimeout: Duration.zero,
      client: MockClient((_) async => throw StateError('No request expected')),
    );
    await expectLater(api.resumePendingJob(), throwsA(isA<ScanApiException>()));
    expect(await api.hasPendingJob(), isTrue);
  });

  test('another owner cannot load or display an in-flight result', () async {
    final pending = _PendingStore()
      ..jobs['owner-a'] = const PendingScanJob(
        ownerId: 'owner-a',
        jobId: 'job-test',
      );
    var owner = 'owner-a';
    final response = Completer<http.Response>();
    final requested = Completer<void>();
    final cache = _MemoryScanCache();
    var requests = 0;
    final api = ScanApi(
      baseUrl: 'https://api.example',
      accessToken: () => 'session-$owner',
      userId: () => owner,
      pendingJobs: pending,
      cache: cache,
      pollInterval: Duration.zero,
      client: MockClient((_) {
        requests++;
        requested.complete();
        return response.future;
      }),
    );
    final first = api.resumePendingJob();
    final rejected = expectLater(first, throwsA(isA<ScanApiException>()));
    await requested.future;
    owner = 'owner-b';
    expect(api.currentJobProgress, isNull);
    expect(await api.hasPendingJob(), isFalse);
    expect(await api.resumePendingJob(), isNull);
    response.complete(http.Response(_completedJob, 200));
    await rejected;
    expect(requests, 1);
    expect(cache.snapshot, isNull);
    expect((await pending.readPending('owner-a'))?.jobId, 'job-test');
  });

  test('mismatched result job cannot clear the pending pointer', () async {
    final pending = _PendingStore()
      ..jobs['owner'] = const PendingScanJob(
        ownerId: 'owner',
        jobId: 'job-test',
      );
    final api = ScanApi(
      baseUrl: 'https://api.example',
      accessToken: () => 'session',
      userId: () => 'owner',
      pendingJobs: pending,
      pollInterval: Duration.zero,
      client: MockClient(
        (_) async => http.Response(
          _completedJob.replaceAll('job-test', 'job-other'),
          200,
        ),
      ),
    );
    await expectLater(api.resumePendingJob(), throwsA(isA<ScanApiException>()));
    expect(await api.hasPendingJob(), isTrue);
  });

  test('uploads a product image and parses the R3 response', () async {
    var requests = 0;
    final client = MockClient((request) async {
      expect(request.headers['authorization'], 'Bearer mobile-session');
      requests += 1;
      if (request.method == 'POST') {
        expect(request.url.path, '/api/v1/scan/jobs/product');
        return http.Response(_acceptedJob, 202);
      }
      expect(request.method, 'GET');
      expect(request.url.path, '/api/v1/scan/jobs/job-test');
      return http.Response(_completedJob, 200);
    });
    final api = ScanApi(
      baseUrl: 'http://localhost:8000',
      accessToken: () => 'mobile-session',
      client: client,
      pollInterval: Duration.zero,
    );

    final result = await api.scan(
      bytes: Uint8List.fromList([1, 2, 3]),
      filename: 'label.png',
      mimeType: 'image/png',
      kind: 'product',
    );

    expect(result.scanId, 'scan-test');
    expect(result.productCandidates, ['Test label']);
    expect(result.brandCandidates, ['Test brand']);
    expect(result.qualityStatus, 'MEDIUM');
    expect(result.warnings, ['Manual review required.']);
    expect(result.nutrition.basis, 'PER_100_ML');
    expect(result.nutrition.servingSize, '250 ml');
    expect(result.nutrition.columns, ['per 100 ml', 'per serving']);
    expect(result.nutrition.rows, hasLength(2));
    expect(result.nutrition.rows.first.displayLabel, 'energy');
    expect(result.nutrition.rows.first.values, ['50', '125']);
    expect(result.nutrition.rows.first.units, ['kcal', 'kcal']);
    expect(result.ingredientText, 'Pasteurized cow milk');
    expect(result.allergenText, 'MILK');
    expect(result.stageConfidences['ocr'], 0.92);
    expect(result.confidenceExplanations, ['Structured evidence is partial.']);
    expect(result.timings['ocr_ms'], 8.5);
    expect(requests, 2);
  });

  test(
    'production secure result cache also provides the pending store automatically',
    () async {
      FlutterSecureStorage.setMockInitialValues({});
      const cache = SecureScanResultCache();
      await cache.writePending(
        const PendingScanJob(ownerId: 'owner', jobId: 'job-test'),
      );
      final api = ScanApi(
        baseUrl: 'https://api.example',
        cache: cache,
        accessToken: () => 'session',
        userId: () => 'owner',
        client: MockClient((request) async {
          expect(request.method, 'GET');
          return http.Response(_completedJob, 200);
        }),
      );
      expect((await api.resumePendingJob())?.scanId, 'scan-test');
      expect(await cache.readPending('owner'), isNull);
      expect((await cache.read('owner'))?.scanId, 'scan-test');
    },
  );

  test(
    'accepted upload keeps original owner when account changes before acknowledgement',
    () async {
      final pending = _PendingStore();
      var owner = 'owner-a';
      final submitted = Completer<void>();
      final response = Completer<http.Response>();
      var requests = 0;
      final api = ScanApi(
        baseUrl: 'https://api.example',
        pendingJobs: pending,
        accessToken: () => 'session-$owner',
        userId: () => owner,
        client: MockClient((request) {
          requests++;
          expect(request.method, 'POST');
          expect(request.headers['authorization'], 'Bearer session-owner-a');
          submitted.complete();
          return response.future;
        }),
      );
      final scan = _scan(api);
      final rejected = expectLater(scan, throwsA(isA<ScanApiException>()));
      await submitted.future;
      owner = 'owner-b';
      response.complete(http.Response(_acceptedJob, 202));
      await rejected;
      expect((await pending.readPending('owner-a'))?.jobId, 'job-test');
      expect(await api.hasPendingJob(), isFalse);
      expect(requests, 1);
    },
  );

  test('backs off on a polling 429 and resumes the same scan job', () async {
    var requests = 0;
    final delays = <Duration>[];
    final client = MockClient((request) async {
      requests += 1;
      if (request.method == 'POST') {
        return http.Response(_acceptedJob, 202);
      }
      if (requests == 2) {
        return http.Response(
          '{"detail":"Rate limit exceeded."}',
          429,
          headers: {'retry-after': '37'},
        );
      }
      return http.Response(_completedJob, 200);
    });
    final api = ScanApi(
      baseUrl: 'http://localhost:8000',
      accessToken: () => 'mobile-session',
      client: client,
      pollInterval: const Duration(seconds: 12),
      delay: (duration) async => delays.add(duration),
    );

    final result = await api.scan(
      bytes: Uint8List.fromList([1, 2, 3]),
      filename: 'label.png',
      mimeType: 'image/png',
      kind: 'product',
    );

    expect(result.scanId, 'scan-test');
    expect(requests, 3);
    expect(delays, const [Duration(seconds: 12), Duration(seconds: 37)]);
  });

  test('surfaces structured backend errors', () async {
    final client = MockClient(
      (_) async => http.Response(
        '{"detail":{"message":"Image content is invalid."}}',
        422,
      ),
    );
    final api = ScanApi(baseUrl: 'http://localhost:8000', client: client);

    expect(
      () => api.scan(
        bytes: Uint8List(0),
        filename: 'bad.png',
        mimeType: 'image/png',
        kind: 'ocr',
      ),
      throwsA(
        isA<ScanApiException>().having(
          (error) => error.message,
          'message',
          'Image content is invalid.',
        ),
      ),
    );
  });

  test(
    'uses a user-scoped minimized cache only for transport failures',
    () async {
      final cache = _MemoryScanCache();
      final online = ScanApi(
        baseUrl: 'http://localhost:8000',
        userId: () => 'owner-1',
        cache: cache,
        client: MockClient((_) async => http.Response(_response, 201)),
      );
      await online.scan(
        bytes: Uint8List.fromList([1, 2, 3]),
        filename: 'label.png',
        mimeType: 'image/png',
        kind: 'product',
      );
      final offline = ScanApi(
        baseUrl: 'http://localhost:8000',
        userId: () => 'owner-1',
        cache: cache,
        client: MockClient((_) async => throw http.ClientException('offline')),
      );

      final result = await offline.scan(
        bytes: Uint8List.fromList([9]),
        filename: 'new.png',
        mimeType: 'image/png',
        kind: 'product',
      );

      expect(result.isOfflineCache, isTrue);
      expect(result.scanId, 'scan-test');
      expect(result.ocrText, isEmpty);
      expect(result.barcodeValues, isEmpty);
      expect(result.nutrition.rows, hasLength(2));
      expect(result.ingredientText, 'Pasteurized cow milk');
      expect(result.allergenText, 'MILK');
      expect(await cache.read('another-user'), isNull);
    },
  );
}

Future<ScanSnapshot> _scan(ScanApi api) => api.scan(
  bytes: Uint8List.fromList([1, 2, 3]),
  filename: 'label.png',
  mimeType: 'image/png',
  kind: 'product',
);

Future<ScanSnapshot> _preferredScan(
  ScanApi api, {
  String kind = 'product',
  ClientInferenceCapabilities capabilities = _preferredCapabilities,
}) => api.scanWithClientEvidence(
  bytes: Uint8List.fromList([1, 2, 3]),
  filename: 'label.png',
  mimeType: 'image/png',
  kind: kind,
  evidence: _evidence,
  capabilities: capabilities,
);

const _preferredCapabilities = ClientInferenceCapabilities(
  contractVersion: clientInferenceContractVersion,
  androidMode: AndroidClientInferenceMode.preferred,
  evidenceUse: 'SERVER_PARSED_CLIENT_EVIDENCE',
  serverResultAuthoritative: true,
  serverFallbackRequired: false,
);

const _evidence = ClientOcrEvidence(
  contractVersion: clientInferenceContractVersion,
  platform: 'ANDROID',
  appVersion: '1.0.0+1',
  source: clientAndroidMlKit,
  ocrProvider: androidMlKitOcrProvider,
  ocrProviderVersion: '16.0.1',
  coldStart: false,
  elapsedMilliseconds: 20,
  imageWidth: 100,
  imageHeight: 100,
  sourceImageSha256:
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  orientationDegrees: 0,
  text: 'A generic label',
  blocks: [],
);

class _PendingStore implements PendingScanJobStore {
  final jobs = <String, PendingScanJob>{};

  @override
  Future<PendingScanJob?> readPending(String ownerId) async => jobs[ownerId];

  @override
  Future<void> writePending(PendingScanJob job) async =>
      jobs[job.ownerId] = job;

  @override
  Future<void> clearPending(String ownerId, String jobId) async {
    if (jobs[ownerId]?.jobId == jobId) jobs.remove(ownerId);
  }
}

class _MemoryScanCache implements ScanResultCache {
  String? userId;
  ScanSnapshot? snapshot;

  @override
  Future<void> clear() async {
    userId = null;
    snapshot = null;
  }

  @override
  Future<ScanSnapshot?> read(String userId) async {
    if (this.userId != userId || snapshot == null) return null;
    return ScanSnapshot.fromCacheJson(
      jsonDecode(jsonEncode(snapshot!.toCacheJson())) as Map<String, dynamic>,
      DateTime.utc(2026, 8, 26),
    );
  }

  @override
  Future<void> write(String userId, ScanSnapshot snapshot) async {
    this.userId = userId;
    this.snapshot = snapshot;
  }
}

const _response = '''
{
  "scan_id": "scan-test",
  "status": "COMPLETED_WITH_WARNINGS",
  "confidence_summary": {
    "level": "MEDIUM",
    "numeric_score": 0.7,
    "sources": {"image_quality": 0.8, "ocr": 0.92, "nutrition_parsing": 0.76},
    "explanation": ["Structured evidence is partial."]
  },
  "image_quality": {"view-1": {"quality_status": "MEDIUM"}},
  "ocr_results": {"view-1": {"text": "RAW OCR NUTRITION ENERGY MILK"}},
  "barcode_results": [],
  "brand_candidates": [{"value": "Test brand"}],
  "product_name_candidates": [{"value": "Test label"}],
  "nutrition": {
    "basis": "PER_100_ML",
    "table_columns": ["per 100 ml", "per serving"],
    "serving_size_value": "250",
    "serving_size_unit": "ml",
    "confidence": 0.76,
    "table_rows": [
      {
        "label": "energy",
        "raw_label": "Calories",
        "canonical_label": "energy",
        "match_confidence": 0.95,
        "values": ["50", "125"],
        "raw_values": ["50 kcal", "125 kcal"],
        "units": ["kcal", "kcal"],
        "confidence": 0.91
      },
      {
        "label": "protein",
        "raw_label": "rotein",
        "canonical_label": "protein",
        "match_confidence": 0.9,
        "values": ["3.6", "9"],
        "raw_values": ["3.6 g", "9 g"],
        "units": ["g", "g"],
        "confidence": 0.88
      }
    ]
  },
  "ingredients": {
    "raw_text": "Pasteurized cow milk",
    "allergen_text": "MILK",
    "confidence": 0.89,
    "allergen_confidence": 0.94
  },
  "warnings": ["Manual review required."],
  "timings": {"ocr_ms": 8.5, "extraction_ms": 3.0, "total_ms": 14.5}
}
''';

const _acceptedJob = '''
{
  "job_id": "job-test",
  "status": "QUEUED",
  "input_kind": "PRODUCT",
  "created_at": "2026-09-01T00:00:00Z"
}
''';

const _completedJob =
    '''
{
  "job_id": "job-test",
  "status": "COMPLETE",
  "input_kind": "PRODUCT",
  "created_at": "2026-09-01T00:00:00Z",
  "result": $_response
}
''';
