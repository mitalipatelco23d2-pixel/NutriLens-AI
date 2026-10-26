import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'services/scan_api.dart';
import 'services/intelligence_api.dart';
import 'services/local_reminders.dart';
import 'services/product_api.dart';
import 'services/client_inference.dart';

class PickedScanImage {
  const PickedScanImage({
    required this.bytes,
    required this.filename,
    required this.mimeType,
  });

  final Uint8List bytes;
  final String filename;
  final String mimeType;
}

enum MobileScanState {
  idle,
  imageSelected,
  submitting,
  clientProcessing,
  serverFallbackProcessing,
  completed,
  failed,
  retrying,
}

abstract interface class ScanImageSource {
  Future<PickedScanImage?> pick(ImageSource source);
}

class DeviceScanImageSource implements ScanImageSource {
  DeviceScanImageSource({ImagePicker? picker})
    : _picker = picker ?? ImagePicker();

  final ImagePicker _picker;

  static PickedScanImage resolvePickedImage({
    required Uint8List bytes,
    required String rawFilename,
  }) {
    String detectedExt;
    String mimeType;
    if (bytes.length >= 3 && bytes[0] == 0xFF && bytes[1] == 0xD8 && bytes[2] == 0xFF) {
      detectedExt = 'jpg';
      mimeType = 'image/jpeg';
    } else if (bytes.length >= 8 &&
        bytes[0] == 0x89 &&
        bytes[1] == 0x50 &&
        bytes[2] == 0x4E &&
        bytes[3] == 0x47 &&
        bytes[4] == 0x0D &&
        bytes[5] == 0x0A &&
        bytes[6] == 0x1A &&
        bytes[7] == 0x0A) {
      detectedExt = 'png';
      mimeType = 'image/png';
    } else if (bytes.length >= 12 &&
        bytes[0] == 0x52 &&
        bytes[1] == 0x49 &&
        bytes[2] == 0x46 &&
        bytes[3] == 0x46 &&
        bytes[8] == 0x57 &&
        bytes[9] == 0x45 &&
        bytes[10] == 0x42 &&
        bytes[11] == 0x50) {
      detectedExt = 'webp';
      mimeType = 'image/webp';
    } else {
      final ext = rawFilename.split('.').last.toLowerCase();
      detectedExt = ext == 'png'
          ? 'png'
          : ext == 'webp'
          ? 'webp'
          : 'jpg';
      mimeType = ext == 'png'
          ? 'image/png'
          : ext == 'webp'
          ? 'image/webp'
          : 'image/jpeg';
    }

    final baseName = rawFilename.contains('.')
        ? rawFilename.substring(0, rawFilename.lastIndexOf('.'))
        : rawFilename;
    final normalizedFilename = '$baseName.$detectedExt';

    return PickedScanImage(
      bytes: bytes,
      filename: normalizedFilename,
      mimeType: mimeType,
    );
  }

  @override
  Future<PickedScanImage?> pick(ImageSource source) async {
    final file = await _picker.pickImage(
      source: source,
      imageQuality: 92,
      maxWidth: 2400,
      maxHeight: 2400,
      requestFullMetadata: false,
    );
    if (file == null) return null;
    final bytes = await file.readAsBytes();
    return resolvePickedImage(bytes: bytes, rawFilename: file.name);
  }
}

class ScannerScreen extends StatefulWidget {
  const ScannerScreen({
    required this.scanGateway,
    this.intelligenceGateway,
    this.productGateway,
    this.imageSource,
    this.clientInferenceGateway,
    this.clientEvidenceGateway,
    this.onAskNutri,
    this.localReminders,
    this.ownerId,
    super.key,
  });

  final ScanGateway scanGateway;
  final IntelligenceGateway? intelligenceGateway;
  final ProductGateway? productGateway;
  final ScanImageSource? imageSource;
  final ClientInferenceGateway? clientInferenceGateway;
  final ClientEvidenceGateway? clientEvidenceGateway;
  final ValueChanged<String>? onAskNutri;
  final LocalReminderCoordinator? localReminders;
  final String? ownerId;

  @override
  State<ScannerScreen> createState() => _ScannerScreenState();
}

class _ScannerScreenState extends State<ScannerScreen>
    with WidgetsBindingObserver {
  PickedScanImage? _image;
  ScanSnapshot? _result;
  IntelligenceSnapshot? _intelligence;
  RecommendationSnapshot? _recommendations;
  CounterfactualSnapshot? _counterfactuals;
  String? _error;
  String? _clientInferenceWarning;
  ClientOcrEvidence? _clientEvidence;
  ClientEvidenceValidation? _clientValidation;
  var _preferredEvidenceSubmitted = false;
  var _scanStage = null as String?;
  final _kind = 'product';
  var _loading = false;
  var _favorite = false;
  var _hasPendingJob = false;
  var _resuming = false;
  var _scanState = MobileScanState.idle;
  StreamSubscription<ScanJobProgress>? _jobSubscription;
  ScanJobProgress? _jobProgress;
  var _gatewayRevision = 0;

  bool get _isProcessing =>
      _scanState == MobileScanState.submitting ||
      _scanState == MobileScanState.clientProcessing ||
      _scanState == MobileScanState.serverFallbackProcessing ||
      _scanState == MobileScanState.retrying;

  ResumableScanGateway? get _resumable =>
      widget.scanGateway is ResumableScanGateway
      ? widget.scanGateway as ResumableScanGateway
      : null;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _listenForJob();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _resumeSavedScan();
    });
  }

  @override
  void didUpdateWidget(covariant ScannerScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.scanGateway != widget.scanGateway) {
      _gatewayRevision++;
      _jobSubscription?.cancel();
      _loading = false;
      _resuming = false;
      _hasPendingJob = false;
      _scanState = MobileScanState.idle;
      _result = null;
      _error = null;
      _clientEvidence = null;
      _clientValidation = null;
      _preferredEvidenceSubmitted = false;
      _listenForJob();
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _resumeSavedScan();
      });
    }
  }

  void _listenForJob() {
    final gateway = _resumable;
    _jobProgress = gateway?.currentJobProgress;
    _jobSubscription = gateway?.jobProgress.listen((progress) {
      if (!mounted) return;
      setState(() {
        _jobProgress = progress;
        _scanStage = progress.message;
      });
    });
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _resumeSavedScan();
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _jobSubscription?.cancel();
    super.dispose();
  }

  Future<void> _updatePendingState() async {
    final revision = _gatewayRevision;
    try {
      final pending = await _resumable?.hasPendingJob() ?? false;
      if (mounted && revision == _gatewayRevision) {
        setState(() => _hasPendingJob = pending);
      }
    } on Object {
      // Keep the recovery action available if secure storage cannot be read.
      if (mounted && revision == _gatewayRevision) {
        setState(() => _hasPendingJob = true);
      }
    }
  }

  Future<void> _resumeSavedScan() async {
    final gateway = _resumable;
    if (gateway == null || _loading || _resuming) return;
    final revision = _gatewayRevision;
    setState(() {
      _resuming = true;
      _loading = true;
      _error = null;
      _scanStage = 'Checking your saved scan…';
    });
    try {
      final result = await gateway.resumePendingJob();
      if (mounted && revision == _gatewayRevision && result != null) {
        setState(() {
          _result = result;
          _scanState = MobileScanState.completed;
        });
        unawaited(_notifyScanCompleted(result));
      }
    } on Object catch (error) {
      if (mounted && revision == _gatewayRevision) {
        setState(() {
          _error = error.toString();
          _scanState = MobileScanState.failed;
        });
      }
    } finally {
      if (mounted && revision == _gatewayRevision) {
        await _updatePendingState();
        if (mounted && revision == _gatewayRevision) {
          setState(() {
            _resuming = false;
            _loading = false;
            _scanStage = null;
          });
        }
      }
    }
  }

  ScanImageSource get _source => widget.imageSource ?? DeviceScanImageSource();

  Future<void> _pick(ImageSource source) async {
    try {
      final selected = await _source.pick(source);
      if (!mounted || selected == null) return;
      setState(() {
        _image = selected;
        _scanState = MobileScanState.imageSelected;
        _result = null;
        _intelligence = null;
        _recommendations = null;
        _counterfactuals = null;
        _error = null;
        _clientInferenceWarning = null;
        _clientEvidence = null;
        _clientValidation = null;
        _preferredEvidenceSubmitted = false;
        _scanStage = null;
        _favorite = false;
        _jobProgress = null;
      });
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _addToDiary() async {
    final result = _result;
    final gateway = widget.productGateway;
    if (result == null || gateway == null) return;
    setState(() => _loading = true);
    try {
      final productName = result.productCandidates.isNotEmpty
          ? result.productCandidates.first
          : 'Scanned food item';

      // Determine serving mass in grams
      double? servingGrams;
      if (result.nutrition.servingSizeValue != null) {
        final sv = double.tryParse(result.nutrition.servingSizeValue!.replaceAll(RegExp(r'[^0-9.]'), ''));
        if (sv != null && (result.nutrition.servingSizeUnit == null || result.nutrition.servingSizeUnit!.toLowerCase().contains('g'))) {
          servingGrams = sv;
        }
      }

      // Check if table has a per-serving column
      int servingColIdx = -1;
      int per100ColIdx = -1;
      for (var i = 0; i < result.nutrition.columns.length; i++) {
        final col = result.nutrition.columns[i].toLowerCase();
        if (col.contains('serving')) {
          servingColIdx = i;
        } else if (col.contains('100')) {
          per100ColIdx = i;
        }
      }

      // Extract nutrients prioritizing per-serving column if present, else column 0
      double? parsedCalories;
      double? parsedProtein;
      double? parsedCarbs;
      double? parsedFat;
      double? parsedSugar;
      double? parsedSodium;
      double? parsedFiber;

      for (final row in result.nutrition.rows) {
        final label = row.displayLabel.toLowerCase();
        final targetIdx = servingColIdx >= 0 && servingColIdx < row.values.length
            ? servingColIdx
            : (per100ColIdx >= 0 && per100ColIdx < row.values.length ? per100ColIdx : 0);
        
        if (targetIdx < row.values.length) {
          final valClean = row.values[targetIdx].replaceAll(RegExp(r'[^0-9.]'), '');
          final numVal = double.tryParse(valClean);
          if (numVal != null) {
            if (label.contains('energy') || label.contains('calorie')) {
              parsedCalories ??= numVal;
            } else if (label.contains('protein')) {
              parsedProtein ??= numVal;
            } else if (label.contains('carb')) {
              parsedCarbs ??= numVal;
            } else if (label.contains('fat') && !label.contains('trans') && !label.contains('sat')) {
              parsedFat ??= numVal;
            } else if (label.contains('sugar')) {
              parsedSugar ??= numVal;
            } else if (label.contains('sodium')) {
              parsedSodium ??= numVal;
            } else if (label.contains('fiber') || label.contains('fibre')) {
              parsedFiber ??= numVal;
            }
          }
        }
      }

      await gateway.addDiary(
        name: productName,
        servingGrams: servingGrams,
        scanId: result.scanId,
        nutrients: Nutrients(
          calories: parsedCalories,
          proteinG: parsedProtein,
          carbsG: parsedCarbs,
          fatG: parsedFat,
          sugarG: parsedSugar,
          sodiumMg: parsedSodium,
          fiberG: parsedFiber,
        ),
      );
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Added $productName to your diary!')),
        );
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = 'Could not add to diary: $error');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _saveFavorite() async {
    final result = _result;
    final gateway = widget.productGateway;
    if (result == null || gateway == null) return;
    setState(() => _loading = true);
    try {
      await gateway.saveFavorite(result.scanId);
      if (mounted) setState(() => _favorite = true);
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadIntelligence() async {
    final result = _result;
    final gateway = widget.intelligenceGateway;
    if (result == null || gateway == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final intelligence = await gateway.ingredients(result.scanId);
      final recommendations = await gateway.recommendations(result.scanId);
      final counterfactuals = await gateway.counterfactuals(result.scanId);
      if (mounted) {
        setState(() {
          _intelligence = intelligence;
          _recommendations = recommendations;
          _counterfactuals = counterfactuals;
        });
      }
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _scan() async {
    final image = _image;
    if (image == null || _loading || _isProcessing) return;
    final revision = _gatewayRevision;
    final isRetry = _scanState == MobileScanState.failed;
    setState(() {
      _scanState = isRetry ? MobileScanState.retrying : MobileScanState.submitting;
      _loading = true;
      _error = null;
      _clientInferenceWarning = null;
    });
    
    if (_hasPendingJob) {
      await _resumeSavedScan();
      return;
    }
    
    setState(() {
      _clientEvidence = null;
      _clientValidation = null;
      _preferredEvidenceSubmitted = false;
      _scanStage = (_kind == 'product' || _kind == 'ocr')
          ? 'Reading label on this device…'
          : 'Sending scan securely…';
    });
    try {
      final canReadLabel = _kind == 'product' || _kind == 'ocr';
      final evidenceGateway = widget.clientEvidenceGateway;
      ClientInferenceCapabilities? capabilities;
      var clientMode = AndroidClientInferenceMode.disabled;
      if (canReadLabel && evidenceGateway != null) {
        try {
          capabilities = await evidenceGateway.capabilities();
          if (!mounted || revision != _gatewayRevision) return;
          clientMode = capabilities.androidMode;
        } on Object catch (error) {
          if (mounted && revision == _gatewayRevision) {
            setState(() => _clientInferenceWarning = error.toString());
          }
        }
      }
      if (canReadLabel && clientMode != AndroidClientInferenceMode.disabled) {
        if (mounted && revision == _gatewayRevision) {
          setState(() => _scanState = MobileScanState.clientProcessing);
        }
        try {
          final evidence =
              await (widget.clientInferenceGateway ??
                      const AndroidMlKitClientInference())
                  .recognizeText(image.bytes);
          if (!mounted || revision != _gatewayRevision) return;
          setState(() => _clientEvidence = evidence);
        } on Object catch (error) {
          // Failed on-device reading always retains the server scan path.
          if (mounted && revision == _gatewayRevision) {
            setState(() => _clientInferenceWarning = error.toString());
          }
        }
      }
      if (!mounted || revision != _gatewayRevision) return;
      final evidence = _clientEvidence;
      final gateway = widget.scanGateway;
      final preferred =
          clientMode == AndroidClientInferenceMode.preferred &&
          capabilities != null &&
          evidence != null &&
          gateway is ClientEvidenceScanGateway;
      final preferredEvidence = evidence;
      final preferredCapabilities = capabilities;
      setState(() {
        _preferredEvidenceSubmitted = preferred;
        _scanState = preferred
            ? MobileScanState.submitting
            : MobileScanState.serverFallbackProcessing;
        _scanStage = preferred
            ? 'Validating on-device label evidence…'
            : 'Running an enhanced scan…';
      });
      final ScanSnapshot result;
      if (preferred) {
        if (preferredEvidence == null || preferredCapabilities == null) {
          throw StateError('Preferred scan evidence was not prepared.');
        }
        // The normal authenticated job endpoint decides whether evidence is
        // acceptable. Client eligibility never bypasses the server gate.
        result = await (gateway as ClientEvidenceScanGateway)
            .scanWithClientEvidence(
              bytes: image.bytes,
              filename: image.filename,
              mimeType: image.mimeType,
              kind: _kind,
              evidence: preferredEvidence,
              capabilities: preferredCapabilities,
            );
      } else {
        final validationFuture = clientMode == AndroidClientInferenceMode.shadow
            ? _validateEvidenceInShadow(evidence, image)
            : Future<void>.value();
        result = await gateway.scan(
          bytes: image.bytes,
          filename: image.filename,
          mimeType: image.mimeType,
          kind: _kind,
        );
        await validationFuture;
      }
      if (mounted && revision == _gatewayRevision) {
        setState(() {
          _result = result;
          _scanState = MobileScanState.completed;
          _scanStage = null;
        });
        unawaited(_notifyScanCompleted(result));
        if (widget.intelligenceGateway != null && !result.isOfflineCache) {
          unawaited(_loadIntelligence());
        }
      }
    } on Object catch (error) {
      if (mounted && revision == _gatewayRevision) {
        setState(() {
          _error = error.toString();
          _scanState = MobileScanState.failed;
        });
      }
    } finally {
      if (mounted && revision == _gatewayRevision) {
        await _updatePendingState();
      }
      if (mounted && revision == _gatewayRevision) {
        setState(() {
          _loading = false;
          _scanStage = null;
        });
      }
    }
  }

  Future<void> _notifyScanCompleted(ScanSnapshot result) async {
    final reminders = widget.localReminders;
    final ownerId = widget.ownerId;
    if (reminders == null || ownerId == null) return;
    final productName = result.productCandidates.isEmpty
        ? ''
        : result.productCandidates.first;
    try {
      await reminders.notifyScanCompleted(ownerId, productName);
    } on Object {
      // The persisted scan result is authoritative; notification is best effort.
    }
  }

  Future<void> _validateEvidenceInShadow(
    ClientOcrEvidence? evidence,
    PickedScanImage image,
  ) async {
    final gateway = widget.clientEvidenceGateway;
    if (evidence == null || gateway == null) return;
    try {
      final validation = await gateway.validate(
        evidence,
        imageBytes: image.bytes,
        filename: image.filename,
        mimeType: image.mimeType,
      );
      if (mounted) setState(() => _clientValidation = validation);
    } on Object catch (error) {
      if (mounted) setState(() => _clientInferenceWarning = error.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    final result = _result;
    return ListView(
      padding: const EdgeInsets.all(20),
      children: [
        Text('Food scanner', style: Theme.of(context).textTheme.headlineMedium),
        const SizedBox(height: 6),
        const Text(
          'Choose a food label photo to read its nutrition and ingredients.',
        ),
        if (_jobProgress case final progress?) ...[
          const SizedBox(height: 12),
          Semantics(
            liveRegion: true,
            child: Card(
              key: const Key('scan-job-progress'),
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(progress.message),
                    if (!progress.isTerminal)
                      const Text(
                        'You can leave this screen. Reopening resumes the same scan without another upload.',
                      ),
                  ],
                ),
              ),
            ),
          ),
        ],
        if (_hasPendingJob && !_loading)
          FilledButton.icon(
            key: const Key('resume-scan'),
            onPressed: _resumeSavedScan,
            icon: const Icon(Icons.refresh),
            label: const Text('Resume scan'),
          ),
        const SizedBox(height: 12),
        if (_image != null)
          ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: Image.memory(
              _image!.bytes,
              height: 220,
              fit: BoxFit.contain,
              errorBuilder: (_, _, _) => const SizedBox(
                height: 120,
                child: Center(child: Text('Preview unavailable')),
              ),
            ),
          ),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _loading || _isProcessing || _hasPendingJob
                    ? null
                    : () => _pick(ImageSource.gallery),
                icon: const Icon(Icons.photo_library_outlined),
                label: const Text('Gallery'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _loading || _isProcessing || _hasPendingJob
                    ? null
                    : () => _pick(ImageSource.camera),
                icon: const Icon(Icons.camera_alt_outlined),
                label: const Text('Camera'),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        FilledButton.icon(
          key: const Key('run-r3-scan'),
          onPressed: _loading || _isProcessing || _hasPendingJob || _image == null
              ? null
              : _scan,
          icon: const Icon(Icons.document_scanner_outlined),
          label: Text(
            _isProcessing || _loading
                ? (_scanStage ?? 'Analysing…')
                : (_scanState == MobileScanState.failed
                    ? 'Retry analyse'
                    : 'Analyse food'),
          ),
        ),
        if (_loading) ...[
          const SizedBox(height: 12),
          const LinearProgressIndicator(),
        ],
        if (_clientEvidence case final evidence?) ...[
          const SizedBox(height: 12),
          Card(
            key: Key(
              _preferredEvidenceSubmitted
                  ? 'client-inference-preferred'
                  : 'client-inference-shadow',
            ),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                _preferredEvidenceSubmitted
                    ? result?.clientEvidenceDecision ==
                                  'CLIENT_EVIDENCE_ACCEPTED' &&
                              result?.serverFallbackRequired == false
                          ? 'On-device label evidence validated by the server.'
                          : _loading
                          ? 'Checking device label evidence; an enhanced scan is used when needed.'
                          : result != null
                          ? result.serverFallbackRequired == true
                                ? 'Enhanced scan completed using the uploaded label.'
                                : 'Scan completed. The server result is shown below.'
                          : 'Your label evidence has not been confirmed. Resume the saved scan if available.'
                    : 'Device label reading · ${evidence.lineCount} lines. '
                          '${_clientValidation == null
                              ? 'Checking evidence. '
                              : _clientValidation!.eligibleForPreferredPath
                              ? 'Evidence suitable for faster scans. '
                              : 'Enhanced scan required during validation. '}'
                          'An enhanced result remains authoritative during validation.',
              ),
            ),
          ),
        ],
        if (_clientInferenceWarning != null) ...[
          const SizedBox(height: 8),
          Text(
            'On-device OCR was unavailable; secure server processing continued.',
            key: const Key('client-inference-warning'),
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
        if (_error != null) ...[
          const SizedBox(height: 12),
          Card(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(_error!, key: const Key('scan-error')),
                  if (_image != null) ...[
                    const SizedBox(height: 10),
                    FilledButton.tonalIcon(
                      key: const Key('scan-retry-button'),
                      onPressed: _loading || _isProcessing ? null : _scan,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Try again'),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
        if (result != null) ...[
          const SizedBox(height: 18),
          _ScanResultCard(result: result),
          if (widget.productGateway != null && !result.isOfflineCache) ...[
            const SizedBox(height: 12),
            FilledButton.icon(
              key: const Key('add-to-diary-from-scan'),
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(48),
              ),
              onPressed: _loading ? null : _addToDiary,
              icon: const Icon(Icons.bookmark_add_outlined),
              label: const Text('Add to Diary / I ate this'),
            ),
          ],
          if (widget.onAskNutri != null && !result.isOfflineCache) ...[
            const SizedBox(height: 10),
            FilledButton.icon(
              key: const Key('ask-nutri-about-scan'),
              onPressed: () => widget.onAskNutri!(result.scanId),
              icon: const Icon(Icons.chat_bubble_outline),
              label: const Text('Ask Nutri about this scan'),
            ),
          ],
          if (widget.productGateway != null && !result.isOfflineCache) ...[
            const SizedBox(height: 10),
            OutlinedButton.icon(
              key: const Key('save-favorite'),
              onPressed: _loading || _favorite ? null : _saveFavorite,
              icon: Icon(_favorite ? Icons.favorite : Icons.favorite_outline),
              label: Text(_favorite ? 'Saved to account' : 'Save food'),
            ),
          ],
          if (widget.intelligenceGateway != null && !result.isOfflineCache) ...[
            const SizedBox(height: 10),
            FilledButton.tonalIcon(
              key: const Key('load-intelligence'),
              onPressed: _loading ? null : _loadIntelligence,
              icon: const Icon(Icons.psychology_outlined),
              label: const Text('Ingredient intelligence & guidance'),
            ),
          ],
          if (_intelligence != null)
            _IntelligenceCard(
              intelligence: _intelligence!,
              recommendations: _recommendations!,
              counterfactuals: _counterfactuals!,
            ),
        ],
      ],
    );
  }
}

class _IntelligenceCard extends StatelessWidget {
  const _IntelligenceCard({
    required this.intelligence,
    required this.recommendations,
    required this.counterfactuals,
  });
  final IntelligenceSnapshot intelligence;
  final RecommendationSnapshot recommendations;
  final CounterfactualSnapshot counterfactuals;

  @override
  Widget build(BuildContext context) => Card(
    key: const Key('ingredient-intelligence'),
    child: Padding(
      padding: const EdgeInsets.all(18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Ingredient intelligence',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          if (intelligence.ingredients.isNotEmpty)
            Text('Ingredients: ${intelligence.ingredients.join(', ')}'),
          if (intelligence.additives.isNotEmpty)
            Text('Additives: ${intelligence.additives.join(', ')}'),
          if (intelligence.allergens.isNotEmpty)
            Text('Allergen signals: ${intelligence.allergens.join(', ')}'),
          if (intelligence.novaGroup != null)
            Text('Processing group: ${intelligence.novaGroup}'),
          for (final warning in intelligence.warnings) Text('• $warning'),
          const Divider(height: 28),
          if (recommendations.fitScore case final fitScore?) ...[
            Container(
              key: const Key('personal-fit-score-card'),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: fitScore.category == 'GREAT_FIT' || fitScore.category == 'GOOD_FIT'
                    ? Colors.green.withValues(alpha: 0.12)
                    : fitScore.category == 'POOR_FIT'
                        ? Colors.red.withValues(alpha: 0.12)
                        : Colors.orange.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: fitScore.category == 'GREAT_FIT' || fitScore.category == 'GOOD_FIT'
                      ? Colors.green.shade400
                      : fitScore.category == 'POOR_FIT'
                          ? Colors.red.shade400
                          : Colors.orange.shade400,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                        fitScore.category == 'GREAT_FIT' || fitScore.category == 'GOOD_FIT'
                            ? Icons.verified_outlined
                            : fitScore.category == 'POOR_FIT'
                                ? Icons.warning_amber_rounded
                                : Icons.info_outline,
                        color: fitScore.category == 'GREAT_FIT' || fitScore.category == 'GOOD_FIT'
                            ? Colors.green.shade800
                            : fitScore.category == 'POOR_FIT'
                                ? Colors.red.shade800
                                : Colors.orange.shade800,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                         child: Text(
                          fitScore.score != null
                              ? 'Personal Fit Score: ${fitScore.score}/100 · ${fitScore.label}'
                              : 'Personal Fit: ${fitScore.label}',
                          style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (fitScore.reasons.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    for (final reason in fitScore.reasons)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: Text('• $reason', style: Theme.of(context).textTheme.bodySmall),
                      ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 16),
          ],
          if (recommendations.betterAlternatives.isNotEmpty) ...[
            Text(
              'Better alternatives for you',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 6),
            for (final alt in recommendations.betterAlternatives)
              Card(
                key: Key('better-alternative-${alt.name}'),
                margin: const EdgeInsets.only(bottom: 8),
                color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Expanded(
                            child: Text(
                              alt.name,
                              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          Chip(
                            label: Text(alt.category, style: const TextStyle(fontSize: 10)),
                            visualDensity: VisualDensity.compact,
                            padding: EdgeInsets.zero,
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(alt.whyBetter, style: Theme.of(context).textTheme.bodySmall),
                      if (alt.keyNutritionAdvantage.isNotEmpty) ...[
                        const SizedBox(height: 2),
                        Text(
                          'Advantage: ${alt.keyNutritionAdvantage}',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: Colors.green.shade700,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 10),
          ] else if (recommendations.fitScore?.category == 'POOR_FIT' ||
              recommendations.fitScore?.category == 'MODERATE_FIT') ...[
            Card.outlined(
              margin: const EdgeInsets.only(bottom: 12),
              child: const Padding(
                padding: EdgeInsets.all(12),
                child: Row(
                  children: [
                    Icon(Icons.inventory_2_outlined, size: 20, color: Colors.grey),
                    SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'No verified catalogue alternatives available yet for this category.',
                        style: TextStyle(fontSize: 12, color: Colors.grey),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          Text(
            'Personalized guidance',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          for (final finding in recommendations.findings)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(finding),
            ),
          const SizedBox(height: 10),
          Text(
            recommendations.disclaimer,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const Divider(height: 28),
          Text(
            'What-if evidence view',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          if (counterfactuals.factors.isEmpty)
            const Text(
              'No recognized label-signal category is available for a bounded counterfactual.',
            ),
          for (final factor in counterfactuals.factors)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(factor),
            ),
          if (counterfactuals.limitation.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              counterfactuals.limitation,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
      ),
    ),
  );
}

class _ScanResultCard extends StatelessWidget {
  const _ScanResultCard({required this.result});

  final ScanSnapshot result;

  @override
  Widget build(BuildContext context) {
    final confidence = result.confidence == null
        ? 'Unavailable'
        : '${(result.confidence! * 100).round()}%';
    final rawProduct = result.productCandidates.firstOrNull;
    final product = _cleanConsumerProductTitle(rawProduct, result);
    final brand = result.brandCandidates.firstOrNull;
    final nutritionRows = _nutritionSnapshotRows(result.nutrition.rows);
    final takeaways = _takeaways(result, nutritionRows);
    final allergen = _allergenStatement(result.allergenText);
    var valueColumnCount = result.nutrition.columns.length;
    for (final row in result.nutrition.rows) {
      if (row.values.length > valueColumnCount) {
        valueColumnCount = row.values.length;
      }
    }
    final valueColumns = [
      for (var index = 0; index < valueColumnCount; index++)
        _deriveColumnLabel(result.nutrition, index),
    ];
    return Card(
      key: const Key('scan-result'),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (result.isOfflineCache)
              Card(
                color: Theme.of(context).colorScheme.secondaryContainer,
                child: Padding(
                  padding: const EdgeInsets.all(10),
                  child: Text(
                    'Offline copy from ${result.cachedAt?.toLocal()}. Raw image, OCR text, and barcode values were not cached.',
                  ),
                ),
              ),
            Semantics(
              header: true,
              child: Text(
                product ?? 'Product name needs review',
                key: const Key('scan-product-name'),
                style: Theme.of(context).textTheme.headlineSmall,
              ),
            ),
            if (result.barcodeValues.isNotEmpty) ...[
              const SizedBox(height: 6),
              Container(
                key: const Key('barcode-detected-banner'),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primaryContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.qr_code_2, size: 16),
                    const SizedBox(width: 6),
                    Text(
                      'Barcode: ${result.barcodeValues.join(', ')}',
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (result.qrValues.isNotEmpty) ...[
              const SizedBox(height: 6),
              Container(
                key: const Key('qr-detected-banner'),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.secondaryContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.qr_code, size: 16),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        'QR: ${result.qrValues.join(', ')} (Raw text preserved; external links are not auto-opened for security)',
                        style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
            if (brand != null && brand.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                brand,
                key: const Key('scan-brand-name'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ],
            if (result.status.toLowerCase().contains('meal') ||
                (result.servingContext?.toLowerCase().contains('prepared') ?? false)) ...[
              const SizedBox(height: 8),
              Container(
                key: const Key('prepared-meal-estimate-notice'),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Colors.amber.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.amber.shade700),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                          decoration: BoxDecoration(
                            color: Colors.amber.shade800,
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: const Text(
                            'EXPERIMENTAL',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          'Estimated meal nutrition',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontWeight: FontWeight.bold,
                            color: Colors.amber.shade900,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'Portions and components are estimates based on visual recognition and typical culinary preparations. Adjust portions or ingredients manually in your diary if needed.',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Colors.amber.shade900,
                      ),
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 22),
            _SectionHeading(label: 'Key takeaways'),
            if (takeaways.isEmpty)
              const Text(
                'The label was read, but its structured details need review.',
              )
            else
              for (final takeaway in takeaways)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(
                        Icons.check_circle_outline,
                        size: 20,
                        color: Theme.of(context).colorScheme.primary,
                      ),
                      const SizedBox(width: 8),
                      Expanded(child: Text(takeaway)),
                    ],
                  ),
                ),
            if (result.positiveSignals.isNotEmpty ||
                result.thingsToWatch.isNotEmpty) ...[
              const SizedBox(height: 16),
              if (result.positiveSignals.isNotEmpty)
                Card(
                  color: Colors.green.withValues(alpha: 0.08),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.check_circle,
                              size: 18,
                              color: Colors.green,
                            ),
                            const SizedBox(width: 6),
                            Text(
                              'Positive signals',
                              style: Theme.of(context).textTheme.titleSmall
                                  ?.copyWith(
                                    color: Colors.green.shade800,
                                    fontWeight: FontWeight.bold,
                                  ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        for (final sig in result.positiveSignals)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              '• $sig',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              if (result.thingsToWatch.isNotEmpty) ...[
                const SizedBox(height: 8),
                Card(
                  color: Colors.amber.withValues(alpha: 0.08),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.info_outline,
                              size: 18,
                              color: Colors.amber,
                            ),
                            const SizedBox(width: 6),
                            Text(
                              'Things to watch',
                              style: Theme.of(context).textTheme.titleSmall
                                  ?.copyWith(
                                    color: Colors.amber.shade900,
                                    fontWeight: FontWeight.bold,
                                  ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 6),
                        for (final watch in result.thingsToWatch)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              '• $watch',
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ],
            if (allergen != null) ...[
              const SizedBox(height: 20),
              Semantics(
                container: true,
                label: 'Package allergen statement. $allergen',
                child: Card(
                  key: const Key('explicit-allergen'),
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.warning_amber_rounded),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Important allergen information',
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                              const SizedBox(height: 4),
                              Text(
                                allergen,
                                key: const Key('allergen-statement'),
                              ),
                              const Text('Source: package allergen statement'),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
            if (nutritionRows.isNotEmpty) ...[
              const SizedBox(height: 20),
              _SectionHeading(label: 'Nutrition snapshot'),
              if (_nutritionContext(result.nutrition) case final contextText?)
                Padding(
                  padding: const EdgeInsets.only(top: 4, bottom: 8),
                  child: Text(contextText),
                ),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final row in nutritionRows)
                    Semantics(
                      label:
                          '${_sentenceCase(row.displayLabel)}: ${_nutritionValue(row, 0)}',
                      child: Card.outlined(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 14,
                            vertical: 10,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                _sentenceCase(row.displayLabel),
                                style: Theme.of(context).textTheme.labelLarge,
                              ),
                              Text(
                                _nutritionValue(row, 0),
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ],
            if (result.ingredientText.isNotEmpty) ...[
              const SizedBox(height: 20),
              _SectionHeading(label: 'Ingredient summary'),
              const SizedBox(height: 6),
              Text(
                result.ingredientText.replaceAll(';', ', '),
                key: const Key('ingredient-summary'),
              ),
              const Text('Source: package ingredient statement'),
            ],
            if (result.nutrition.rows.isNotEmpty &&
                valueColumns.isNotEmpty) ...[
              const SizedBox(height: 20),
              _SectionHeading(label: 'Full nutrition table'),
              const SizedBox(height: 8),
              Semantics(
                container: true,
                label: 'Structured nutrition facts table',
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    key: const Key('nutrition-table'),
                    columns: [
                      const DataColumn(label: Text('Nutrient')),
                      for (final column in valueColumns)
                        DataColumn(label: Text(column)),
                    ],
                    rows: [
                      for (final row in result.nutrition.rows)
                        DataRow(
                          cells: [
                            DataCell(Text(_sentenceCase(row.displayLabel))),
                            for (
                              var index = 0;
                              index < valueColumns.length;
                              index++
                            )
                              DataCell(Text(_nutritionValue(row, index))),
                          ],
                        ),
                    ],
                  ),
                ),
              ),
            ],
            const SizedBox(height: 18),
            ExpansionTile(
              key: const Key('technical-details'),
              tilePadding: EdgeInsets.zero,
              childrenPadding: const EdgeInsets.only(bottom: 8),
              title: const Text('Technical details'),
              subtitle: const Text('Confidence, processing and source text'),
              children: [
                Align(
                  alignment: Alignment.centerLeft,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${result.status} · ${result.confidenceLevel} ($confidence)',
                      ),
                      Text('Image quality: ${result.qualityStatus}'),
                      if (result.clientEvidenceDecision
                          case final decision?) ...[
                        Text('Device evidence decision: $decision'),
                        for (final reason in result.clientEvidenceReasons)
                          Text('• $reason'),
                      ],
                      Text(
                        'Total processing: ${result.totalMilliseconds.round()} ms',
                      ),
                      if (result.nutrition.confidence case final value?)
                        Text(
                          'Nutrition parsing confidence: ${(value * 100).round()}%',
                        ),
                      if (result.ingredientConfidence case final value?)
                        Text(
                          'Ingredient extraction confidence: ${(value * 100).round()}%',
                        ),
                      if (result.allergenConfidence case final value?)
                        Text(
                          'Allergen evidence confidence: ${(value * 100).round()}%',
                        ),
                      if (result.stageConfidences.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        Text(
                          'Stage confidence',
                          style: Theme.of(context).textTheme.titleSmall,
                        ),
                        for (final entry in result.stageConfidences.entries)
                          Text(
                            '${_sentenceCase(entry.key.replaceAll('_', ' '))}: '
                            '${(entry.value * 100).round()}%',
                          ),
                      ],
                      if (result.confidenceExplanations.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        for (final explanation in result.confidenceExplanations)
                          Text('• $explanation'),
                      ],
                      if (result.timings.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        Text(
                          'Stage timing',
                          style: Theme.of(context).textTheme.titleSmall,
                        ),
                        for (final entry in result.timings.entries)
                          Text(
                            '${_sentenceCase(entry.key.replaceAll('_ms', '').replaceAll('_', ' '))}: '
                            '${entry.value.round()} ms',
                          ),
                      ],
                      if (result.barcodeValues.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        Text('Barcode: ${result.barcodeValues.join(', ')}'),
                      ],
                      if (result.warnings.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        for (final warning in result.warnings)
                          Text(
                            '• $warning',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                      ],
                      const SizedBox(height: 10),
                      Text(
                        'Recognized source text',
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      SelectableText(
                        result.ocrText.isEmpty
                            ? result.isOfflineCache
                                  ? 'Source text is intentionally unavailable offline.'
                                  : 'No source text was recognized.'
                            : result.ocrText,
                        key: const Key('raw-ocr-details'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionHeading extends StatelessWidget {
  const _SectionHeading({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) => Semantics(
    header: true,
    child: Text(label, style: Theme.of(context).textTheme.titleLarge),
  );
}

List<NutritionTableRow> _nutritionSnapshotRows(List<NutritionTableRow> rows) {
  const priority = [
    'energy',
    'calories',
    'protein',
    'carbohydrate',
    'total sugar',
    'added sugar',
    'total fat',
    'sodium',
  ];
  final selected = <NutritionTableRow>[];
  for (final label in priority) {
    for (final row in rows) {
      if (selected.length >= 4) return selected;
      if (row.values.isNotEmpty &&
          row.displayLabel.toLowerCase() == label &&
          !selected.contains(row)) {
        selected.add(row);
      }
    }
  }
  for (final row in rows) {
    if (selected.length >= 4) break;
    if (row.values.isNotEmpty && !selected.contains(row)) selected.add(row);
  }
  return selected;
}

List<String> _takeaways(
  ScanSnapshot result,
  List<NutritionTableRow> snapshotRows,
) {
  if (result.insightsHighlights.isNotEmpty) {
    return result.insightsHighlights;
  }
  final takeaways = <String>[];
  final context = _nutritionContext(result.nutrition);
  if (context != null) takeaways.add(context);
  for (final row in snapshotRows.take(2)) {
    final value = _nutritionValue(row, 0);
    if (value != '—') {
      takeaways.add(
        'Label reports $value ${_sentenceCase(row.displayLabel).toLowerCase()}${_basisSuffix(result.nutrition.basis)}.',
      );
    }
  }
  return takeaways;
}

String? _nutritionContext(NutritionSnapshot nutrition) {
  final basis = _basisLabel(nutrition.basis);
  final serving = nutrition.servingSize;
  if (basis != null && serving != null) {
    return 'Nutrition is reported $basis. Serving size: $serving.';
  }
  if (basis != null) return 'Nutrition is reported $basis.';
  if (serving != null) return 'Serving size: $serving.';
  return null;
}

String? _basisLabel(String basis) => switch (basis) {
  'PER_100_G' => 'per 100 g',
  'PER_100_ML' => 'per 100 ml',
  'PER_SERVING' => 'per serving',
  _ => null,
};

String _basisSuffix(String basis) {
  final label = _basisLabel(basis);
  return label == null ? '' : ' $label';
}

String _nutritionValue(NutritionTableRow row, int index) {
  if (index >= row.values.length || row.values[index].isEmpty) return '—';
  final value = row.values[index];
  if (index >= row.units.length || row.units[index].isEmpty) return value;
  final unit = row.units[index];
  if (value.toLowerCase().endsWith(unit.toLowerCase())) return value;
  return unit == '%' ? '$value%' : '$value $unit';
}

String? _allergenStatement(String raw) {
  final value = raw.trim();
  if (value.isEmpty) return null;
  // Preserve the package's modality, including negation and precautionary
  // wording. A bare allergen name is not an explicit "contains" declaration.
  return 'Allergen statement: ${_sentenceCase(value)}';
}

String _sentenceCase(String value) {
  final trimmed = value.trim();
  if (trimmed.isEmpty) return trimmed;
  final normalized = trimmed == trimmed.toUpperCase()
      ? trimmed.toLowerCase()
      : trimmed;
  return '${normalized[0].toUpperCase()}${normalized.substring(1)}';
}

String _deriveColumnLabel(NutritionSnapshot nutrition, int index) {
  // Collect parsed values and units at this column across all rows
  final colValues = <String>[];
  final colUnits = <String>[];
  final colBases = <String>[];
  String? colSourceBasis;

  for (final row in nutrition.rows) {
    if (index < row.values.length && row.values[index].trim().isNotEmpty) {
      colValues.add(row.values[index].trim());
    }
    if (index < row.units.length && row.units[index].trim().isNotEmpty) {
      colUnits.add(row.units[index].trim().toLowerCase());
    }
    if (index < row.parsedValues.length) {
      final p = row.parsedValues[index];
      if (p.basis.isNotEmpty && p.basis != 'UNKNOWN') {
        colBases.add(p.basis);
      }
      if (colSourceBasis == null && p.sourceBasisText != null && p.sourceBasisText!.trim().isNotEmpty) {
        colSourceBasis = p.sourceBasisText!.trim();
      }
    }
  }

  final hasOnlyPercentUnits = colUnits.isNotEmpty && colUnits.every((u) => u == '%');
  final hasAmountUnits = colUnits.any((u) => u == 'g' || u == 'mg' || u == 'mcg' || u == 'kcal' || u == 'kj' || u == 'ml');
  final isPercentBasis = colBases.isNotEmpty && colBases.every((b) => b == 'PERCENT_RDA' || b == 'PERCENT_DV' || b == 'RDA_PERCENT' || b == 'DV_PERCENT');
  final isPerServingBasis = colBases.contains('PER_SERVING');
  final isPer100gBasis = colBases.contains('PER_100_G');
  final isPer100mlBasis = colBases.contains('PER_100_ML');

  if (index < nutrition.columns.length) {
    final rawCol = nutrition.columns[index].trim();
    if (rawCol.isNotEmpty) {
      final rawLower = rawCol.toLowerCase();
      final isRdaHeader = rawLower.contains('%') || rawLower.contains('rda') || rawLower.contains('dv') || rawLower.contains('reference');
      // If header says % RDA or % DV but values are amounts and not %, it is NOT an RDA column!
      if (isRdaHeader && (hasAmountUnits || (!hasOnlyPercentUnits && !isPercentBasis))) {
        // Discard fake % RDA header and fall through to basis detection
      } else {
        if (!isRdaHeader && rawLower.contains('serving') && nutrition.servingSize != null && !rawCol.contains('(')) {
          return 'Per serving (${nutrition.servingSize})';
        }
        return _sentenceCase(rawCol);
      }
    }
  }

  if (colSourceBasis != null && colSourceBasis.isNotEmpty) {
    return _sentenceCase(colSourceBasis);
  }

  if (isPer100gBasis) return 'Per 100 g';
  if (isPer100mlBasis) return 'Per 100 ml';
  if (isPerServingBasis) {
    return nutrition.servingSize != null
        ? 'Per serving (${nutrition.servingSize})'
        : 'Per serving';
  }
  if (isPercentBasis || hasOnlyPercentUnits) return '% RDA';

  if (index == 0) {
    if (nutrition.basis == 'PER_100_G') return 'Per 100 g';
    if (nutrition.basis == 'PER_100_ML') return 'Per 100 ml';
    if (nutrition.basis == 'PER_SERVING') {
      return nutrition.servingSize != null
          ? 'Per serving (${nutrition.servingSize})'
          : 'Per serving';
    }
  } else if (index == 1 && nutrition.servingSize != null) {
    return 'Per serving (${nutrition.servingSize})';
  }
  return 'Basis unknown';
}

String? _cleanConsumerProductTitle(String? rawTitle, ScanSnapshot result) {
  if (rawTitle == null || rawTitle.trim().isEmpty) {
    return result.status == 'COMPLETED' ? 'Scanned packaged food' : null;
  }
  final title = rawTitle.trim();
  final lower = title.toLowerCase();
  // Filter out raw uncurated OCR fragments, table headers, multilingual nutrition headers, or noisy lines.
  final noisyIndicators = [
    'pasteurized', 'valeurs moyennes', 'gemiddelde', 'typical values',
    'specially brev', 'nutrition declaration', 'ingredients:', 'storage:',
    'per 100g', 'per 100ml', 'batch no', 'mfg date', 'exp date',
  ];
  for (final indicator in noisyIndicators) {
    if (lower.contains(indicator)) {
      return 'Scanned packaged food';
    }
  }
  return title;
}

