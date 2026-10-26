FROM python:3.12-slim

ARG TARGETARCH

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
COPY infrastructure/docker/ai-worker-requirements.txt infrastructure/docker/ai-worker-requirements.txt
# The worker is deliberately CPU-only. Install the validated CPU wheel from
# PyTorch's CPU index before Ultralytics so a generic CUDA wheel cannot pull
# several gigabytes of unused NVIDIA runtime packages into the image.
RUN pip install --no-cache-dir \
      torch==2.11.0 torchvision==0.26.0 \
      --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r infrastructure/docker/ai-worker-requirements.txt

COPY backend backend
COPY ai ai
COPY data/runtime data/runtime
COPY scripts scripts

# These are the evaluated R3 assets, baked into the image to avoid first-request
# downloads. The custom checkpoint is checksum-verified by NutritionYOLOEngine.
COPY .model-cache/r3/custom/nutrition-table-yolo11n-v1.pt .model-cache/r3/custom/nutrition-table-yolo11n-v1.pt
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/config.json .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/config.json
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/inference.json .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/inference.json
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/inference.pdiparams .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/inference.pdiparams
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/inference.yml .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_det/inference.yml
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/config.json .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/config.json
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/inference.json .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/inference.json
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/inference.pdiparams .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/inference.pdiparams
COPY .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/inference.yml .model-cache/r3/paddle/official_models/PP-OCRv5_mobile_rec/inference.yml

# OpenCV's headless image decoding path still dynamically links libGL and
# GLib on the Debian slim base. Keep these runtime-only dependencies explicit
# so the worker imports successfully in the managed Linux container.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV R3_MODEL_CACHE=/app/.model-cache/r3 \
    R3_NUTRITION_YOLO_MODEL=/app/.model-cache/r3/custom/nutrition-table-yolo11n-v1.pt \
    R3_ALLOW_MODEL_DOWNLOADS=false \
    R3_DEVICE=cpu

RUN useradd --create-home --uid 10001 nutrilens \
    && chown -R nutrilens:nutrilens /app
USER nutrilens

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["uvicorn", "backend.ai_worker_api:app", "--host", "0.0.0.0", "--port", "8000"]
