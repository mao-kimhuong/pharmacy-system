#!/bin/sh
# apt-get update + install that survives a flaky mirror or proxy (exit 100 on deb.debian.org):
# HTTPS sources (Docker Desktop's proxy has broken plain-HTTP trixie-updates before), per-request retries and
# timeouts, and up to 3 tries of the whole update + install. Used by infra/base/Dockerfile and infra/test/Dockerfile
# under BuildKit cache mounts for /var/cache/apt and /var/lib/apt, so a rebuild downloads nothing new.
# Usage: apt-install <package>...
set -eu

for f in /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; do
  [ -f "$f" ] && sed -i 's|http://deb.debian.org|https://deb.debian.org|g' "$f"
done

opts="-o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30"
attempt=1
while :; do
  # shellcheck disable=SC2086
  if apt-get $opts update && DEBIAN_FRONTEND=noninteractive apt-get $opts install -y --no-install-recommends "$@"; then
    exit 0
  fi
  if [ "$attempt" -ge 3 ]; then
    echo "apt-install: update + install failed $attempt times" >&2
    exit 100
  fi
  attempt=$((attempt + 1))
  echo "apt-install: failed, try $attempt of 3 in $((attempt * 10)) s" >&2
  sleep $((attempt * 10))
done
