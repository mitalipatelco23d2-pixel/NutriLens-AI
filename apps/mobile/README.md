# NutriLens X Mobile Foundation

This Flutter project is the R0 cross-platform foundation. It contains Android and iOS platform projects, a NutriLens theme, basic navigation, compile-time environment configuration, an injectable API client, and a backend health screen with retry/error states.

## Run

```powershell
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000 --dart-define=APP_ENVIRONMENT=development
```

Android emulators reach the host through `10.0.2.2`; iOS simulators use `localhost`. For a physical device, provide the development computer's reachable address. Android debug builds permit local cleartext HTTP; non-debug builds should use HTTPS. iOS permits local-network connections for this local academic foundation.

## Verify

```powershell
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter test --dart-define=LIVE_API_BASE_URL=http://localhost:8000 test\live_health_test.dart
flutter build bundle --debug
```

Full R17 product functionality is intentionally deferred.
