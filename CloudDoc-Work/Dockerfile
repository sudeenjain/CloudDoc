# Production Dockerfile for CloudDoc AI Backend
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY backend/ /app/

# Environment defaults
ENV PYTHONUNBUFFERED=1 \
    CLOUDDOC_DATA_DIR=/app/data \
    PORT=8000

# Expose backend port
EXPOSE 8000

# Run FastAPI via Uvicorn
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
