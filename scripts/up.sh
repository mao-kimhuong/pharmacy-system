#!/bin/sh
# `make up`: start the stack, building only when needed. It skips the build (up --no-build) when every image of the
# compose project exists and the build inputs are byte-for-byte what the last successful build used; otherwise it
# builds pharmacy-base first, then `up -d --build`, and records the inputs. FORCE_BUILD=1 always builds;
# `make up-fast` never does. COMPOSE can point at another stack (e.g. COMPOSE="docker compose -p demo").
set -eu
cd "$(dirname "$0")/.."
COMPOSE=${COMPOSE:-docker compose}

project=$($COMPOSE config --format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')
stamp=".build-stamp-$project"

# What goes into the images: tracked and new (not ignored) files under the build contexts, by name and content.
inputs_hash() {
  git ls-files -co --exclude-standard -- shared services infra web docs/design docker-compose.yml .dockerignore \
    | while IFS= read -r f; do [ -f "$f" ] && printf '%s\n' "$f"; done > "$stamp.list"
  { cat "$stamp.list"; git hash-object --stdin-paths < "$stamp.list"; } | shasum -a 256 | cut -d' ' -f1
  rm -f "$stamp.list"
}

images_exist() {
  docker image inspect pharmacy-base:local > /dev/null 2>&1 || return 1
  for image in $($COMPOSE config --images); do
    docker image inspect "$image" > /dev/null 2>&1 || return 1
  done
}

hash=none
if git rev-parse --is-inside-work-tree > /dev/null 2>&1; then hash=$(inputs_hash); fi

if [ "${FORCE_BUILD:-}" != "1" ] && [ "$hash" != none ] && [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$hash" ] && images_exist; then
  echo "up: images are current (no change since the last build) - starting without building"
  exec $COMPOSE up -d --no-build "$@"
fi

echo "up: building (images missing or build inputs changed)"
$COMPOSE build base
$COMPOSE up -d --build "$@"
[ "$hash" = none ] || echo "$hash" > "$stamp"
