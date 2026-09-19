FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download EasyOCR models to avoid delays on first API call
RUN python -c "import easyocr; easyocr.Reader(['en'], gpu=False, verbose=False)"

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
