FROM python:3.12-slim

# System dependencies for OCR backends and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV / image processing
    libgl1 \
    libglib2.0-0 \
    # Tesseract OCR (optional backend)
    tesseract-ocr \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    # PDF rendering
    poppler-utils \
    # Health check
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8090

# Use 1 worker because Docling models are memory-heavy and share GPU context.
# Concurrency is handled by uvicorn's async loop.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
