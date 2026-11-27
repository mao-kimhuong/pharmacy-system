# syntax=docker/dockerfile:1.7
# pharmacy-base: what every Python service image (and the test runner) has in common, so apt runs once for the
# whole stack instead of once per image. Build context: the repo root. Compose builds it as the build-only `base`
# service (image pharmacy-base:local); `make build`, `make up` and `make test-docker` build it before the others.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Keep downloaded .debs in the cache mount (the image's docker-clean hook would delete them).
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

COPY infra/base/apt-install.sh /usr/local/bin/apt-install

# WeasyPrint (document service) renders through Pango + HarfBuzz (correct Khmer shaping); fonts-noto-core has Noto
# Sans and Noto Sans Khmer. The package lists live in the cache mount, not in the image.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    chmod +x /usr/local/bin/apt-install \
    && apt-install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fonts-noto-core

RUN useradd --create-home appuser
WORKDIR /app
