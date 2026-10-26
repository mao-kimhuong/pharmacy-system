# Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY shared /shared
RUN pip install /shared

COPY services/purchasing /app
RUN pip install /app

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Apply this service's migrations, then start the API.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn purchasing_service.main:app --host 0.0.0.0 --port 8000"]
