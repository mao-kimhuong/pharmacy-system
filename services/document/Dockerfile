# Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# WeasyPrint renders through Pango + HarfBuzz (correct Khmer shaping).
# fonts-noto-core has Noto Sans and Noto Sans Khmer used by the labels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY shared /shared
RUN pip install /shared

COPY services/document /app
RUN pip install /app

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Apply this service's migrations, then start the API.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn document_service.main:app --host 0.0.0.0 --port 8000"]
