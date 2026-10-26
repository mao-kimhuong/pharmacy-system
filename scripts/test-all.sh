#!/usr/bin/env bash
# Lint and test the shared library and every service.
# Needs Python 3.12+ and the test databases (make test starts them with
# docker-compose.test.yml). Creates .venv in the repo root on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

export TEST_PG_ADMIN_URL="${TEST_PG_ADMIN_URL:-postgresql://postgres:postgres@localhost:55432/postgres}"
export TEST_REDIS_URL="${TEST_REDIS_URL:-redis://localhost:56379/15}"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements-dev.txt
pip install -q -e shared

ruff check .

echo "== shared"
(cd shared && python -m pytest -q)

for dir in services/*/; do
  name=$(basename "$dir")
  echo "== $name"
  pip install -q -e "$dir"
  (cd "$dir" && python -m pytest -q)
done
