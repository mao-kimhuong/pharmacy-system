# Test runner for `make test-docker`: the whole suite inside a container, so no
# local Python is needed. Includes what the document service needs to render
# labels (Pango/HarfBuzz for WeasyPrint, Noto Sans Khmer) and psql for the
# init-script test. The repo is mounted at /repo; the venv lives in a volume.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-noto-core \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    VENV=/venv

WORKDIR /repo
CMD ["./scripts/test-all.sh"]
