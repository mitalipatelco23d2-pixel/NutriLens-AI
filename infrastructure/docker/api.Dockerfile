FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY ai ai
COPY data/runtime data/runtime
COPY scripts scripts
RUN useradd --create-home --uid 10001 nutrilens \
    && mkdir -p /app/.model-cache/r3 \
    && chown -R nutrilens:nutrilens /app/.model-cache
USER nutrilens
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
