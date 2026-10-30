#!/usr/bin/env bash
# Lint and test the shared library and every service.
# Needs Python 3.12+ and the test databases (make test starts them with
# docker-compose.test.yml). Creates .venv in the repo root on first run.
# No local Python? Use `make test-docker`, which runs this inside a container.
set -euo pipefail
cd "$(dirname "$0")/.."

export TEST_PG_ADMIN_URL="${TEST_PG_ADMIN_URL:-postgresql://postgres:postgres@localhost:55432/postgres}"
export TEST_REDIS_URL="${TEST_REDIS_URL:-redis://localhost:56379/15}"
export TEST_S3_ENDPOINT="${TEST_S3_ENDPOINT:-http://localhost:58333}"
VENV="${VENV:-.venv}"

is_312_or_newer() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null
}

PYTHON=""
for candidate in python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && is_312_or_newer "$candidate"; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "Python 3.12 or newer is needed (found: $(python3 --version 2>&1 || echo none))." >&2
  echo "  macOS:  brew install python@3.12" >&2
  echo "  Linux:  install python3.12 and python3.12-venv from your package manager" >&2
  echo "Or run the tests in Docker without a local Python:  make test-docker" >&2
  exit 1
fi

if [ -x "$VENV/bin/python" ] && ! is_312_or_newer "$VENV/bin/python"; then
  echo "Recreating $VENV: it was made with $("$VENV/bin/python" --version 2>&1)"
  rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating $VENV with $("$PYTHON" --version)"
  "$PYTHON" -m venv "$VENV"
fi
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q -r requirements-dev.txt
pip install -q -e "shared[storage,uploads]"

ruff check .

echo "== shared"
(cd shared && python -m pytest -q)

# Install every service first: some test suites run other services' apps in-process.
for dir in services/*/; do
  pip install -q -e "$dir"
done
for dir in services/*/; do
  echo "== $(basename "$dir")"
  (cd "$dir" && python -m pytest -q)
done
