# syntax=docker/dockerfile:1.7
# Build context is the repo root (see docker-compose.yml). pharmacy-base (infra/base/Dockerfile, `docker compose build base` first) brings Python,
# the system packages and the appuser account; pip downloads stay in a BuildKit cache between builds.
FROM pharmacy-base:local

COPY shared /shared
RUN --mount=type=cache,target=/root/.cache/pip pip install "/shared[storage,uploads]"

COPY services/inventory /app
RUN --mount=type=cache,target=/root/.cache/pip pip install /app

USER appuser

EXPOSE 8000
# Apply this service's migrations, then start the API.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn inventory_service.main:app --host 0.0.0.0 --port 8000"]
