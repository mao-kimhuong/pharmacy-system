# syntax=docker/dockerfile:1.7
# Test runner for `make test-docker`: the whole suite inside a container, so no local Python is needed.
# pharmacy-base already has what the document service needs to render labels (Pango/HarfBuzz for WeasyPrint,
# Noto Sans Khmer); this adds psql for the init-script test. The repo is mounted at /repo; the venv lives in a volume.
FROM pharmacy-base:local

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-install postgresql-client

ENV PIP_NO_CACHE_DIR=1 \
    RUFF_CACHE_DIR=/tmp/ruff-cache \
    VENV=/venv

WORKDIR /repo
CMD ["./scripts/test-all.sh"]
