# NutriLens X Testing Guide

## Start the web application

```powershell
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Test the main journey

1. Confirm the overview dashboard loads.
2. Confirm `82/100` is centered inside the score ring.
3. Select **Scan food**.
4. Upload a JPG, PNG, or WebP label, or select **Use sample granola**.
5. Confirm the Almond & Honey Granola result appears.
6. Switch between **Overview**, **Ingredients**, and **Nutrition facts**.
7. Select **Save** and confirm it changes to **Saved**.
8. Open **My nutrition** and switch among calories, protein, and sugar.
9. Open **Smart pantry**, use an item, and tick a shopping-list item.
10. Open **Ask Nutri**, select a suggested question, and confirm a reply appears.

The uploaded image currently demonstrates the interface flow. Real OCR and computer-vision inference are not implemented yet.

## Test responsive behavior

Use browser developer tools at:

- Desktop: `1440 × 900`
- Tablet: `768 × 1024`
- Mobile: `390 × 844`

At mobile width, confirm the sidebar becomes a navigation drawer, cards stack without horizontal scrolling, and the score value remains centered.

## Test the API

```powershell
& '.\.venv\Scripts\python.exe' -m uvicorn backend.main:app --reload
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) and test `GET /health` and `POST /api/v1/analyze`.

Example request:

```json
{
  "product_name": "Test granola",
  "serving_grams": 45,
  "ingredients": "Whole grain oats, almonds, honey, sunflower oil",
  "nutrients": {
    "calories": 186,
    "protein": 6.8,
    "carbs": 28,
    "fat": 6.4,
    "sugar": 7.2,
    "sodium": 92
  },
  "goal": "balanced"
}
```

## Automated verification

```powershell
npm run build
npm audit --omit=dev
& '.\.venv\Scripts\python.exe' -m pytest tests -q
```

These commands validate the production frontend, TypeScript, production dependencies, and backend scoring behavior. Visual alignment must still be checked in a browser because unit tests cannot prove that text looks centered.

## Test R2 dataset engineering

```powershell
& '.\.venv\Scripts\python.exe' scripts\validate_r1.py
& '.\.venv\Scripts\python.exe' scripts\data\verify_downloads.py
& '.\.venv\Scripts\python.exe' scripts\data_engineering\run_r2_pipeline.py --mode sample
& '.\.venv\Scripts\python.exe' scripts\data_engineering\run_r2_pipeline.py --mode full
& '.\.venv\Scripts\python.exe' scripts\validate_r2.py
& '.\.venv\Scripts\pytest.exe' tests\test_r2_normalization.py tests\test_r2_parsers.py tests\test_r2_governance.py
```

The full command processes only R1 sources already marked `DOWNLOADED`; it never acquires a gated
dataset. A clean CI checkout uses `scripts/validate_r2.py --governance-only` plus the explicitly
synthetic non-nutrition software fixture, so large/ignored payloads are not required.

## Test the Flutter foundation

With the Docker stack running:

```powershell
Set-Location apps\mobile
dart format --output=none --set-exit-if-changed lib test
flutter analyze
flutter test
flutter test --dart-define=LIVE_API_BASE_URL=http://localhost:8000 test\live_health_test.dart
flutter build bundle --debug
```

The regular suite verifies the navigation shell, healthy-state UI, error contract and response parsing. The live test proves that the mobile API abstraction reaches the running FastAPI endpoint and receives healthy database statuses.
