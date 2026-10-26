# Limited offline scan access

The production Flutter client stores at most one successful structured scan summary in platform secure storage. The cache is namespaced to the authenticated backend user, expires after 24 hours and is consulted only when the HTTP transport times out or cannot connect.

The cached representation contains the scan identifier, status, confidence, warnings, resolved product candidates, quality state and prior processing time. It deliberately excludes raw image bytes, OCR text and barcode values. The interface labels the result as an offline copy, shows its timestamp and disables server-dependent intelligence and save actions.

HTTP authorization, entitlement, validation and other server responses are authoritative and never trigger offline fallback. Corrupt, expired or wrong-user entries are deleted. Automated behavior is covered in `apps/mobile/test/scan_api_test.dart`.
