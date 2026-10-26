# OCR

R3 uses a lazy PaddleOCR primary adapter, EasyOCR fallback, and disabled-by-default
experimental TrOCR adapter. Missing optional runtimes are returned as structured
`UNAVAILABLE` attempts, and contradictory text is never merged.

The frozen real-evaluation primary is PaddleOCR 3.7.0 on PaddlePaddle 3.3.1 with
the official PP-OCRv5 mobile detector/recognizer in `.model-cache/r3/paddle`.
Normal scans require the cache to exist and cannot implicitly download models.
