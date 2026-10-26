# R3 real-image acquisition and evaluation

These scripts acquire only official, pinned or source-documented datasets. Image payloads are Git-ignored; tracked manifests, checksums, source revisions and evaluation reports preserve provenance.

## Acquisition order

Run from the repository root with the data environment in `backend/requirements-r3-data.txt`:

```powershell
python scripts/data/r3/download_off_nutrition_images.py
python scripts/data/r3/download_off_front_images.py
python scripts/data/r3/download_off_product_images.py
python scripts/data/r3/download_grocery_store_dataset.py
python scripts/data/r3/download_myfoodrepo.py
python scripts/data/r3/download_food101.py
python scripts/data/r3/verify_r3_image_datasets.py
python scripts/data/r3/build_r3_evaluation_manifest.py
```

The Food-101 downloader uses resumable, exact `Content-Range` segments against the official ETH archive. The OFF product corpus uses the pinned complete product Parquet and SHA-256 ranking within a bounded eligible multi-view pool. Existing complete payloads are reused; a differing completed artifact is never silently overwritten.

MyFoodRepo must use the official AIcrowd route. If authentication or terms acceptance is required, its script records `MANUAL_ACCESS_REQUIRED` and does not bypass access controls.

## Evaluation

Install the frozen primary OCR environment separately on Windows:

```powershell
python -m venv .venv-r3-paddle
.venv-r3-paddle\Scripts\python -m pip install -r backend/requirements-r3-paddle.txt
.venv-r3-paddle\Scripts\python scripts/r3_setup_models.py --paddle
```

Then run:

```powershell
.venv-r3-paddle\Scripts\python scripts/data/r3/smoke_paddleocr_real.py --count 5
.venv-r3-paddle\Scripts\python scripts/data/r3/evaluate_r3_nutrition_regions.py --count 25
python scripts/data/r3/evaluate_r3_real_pipeline.py --samples-per-role 5
```

Use `--disable-ocr` only for explicitly isolated detector or barcode component runs. Such outputs are labelled component evaluations and cannot be presented as a full OCR pipeline result.

## Ground-truth policy

- OFF nutrition boxes are manually reviewed source annotations and support region metrics.
- OFF front labels, GroceryStore labels and Food-101 dish classes are source labels.
- OFF product ingredient/nutrition text is an associated `PRODUCT_DATABASE_REFERENCE`, not pixel-perfect OCR ground truth.
- CER and WER remain null unless a legitimate transcription reference exists.
- Source product barcodes identify records but do not prove that a barcode is visible in every candidate image.
- Food-101 is a dish-classification backup and does not replace MyFoodRepo multi-food COCO annotations.
