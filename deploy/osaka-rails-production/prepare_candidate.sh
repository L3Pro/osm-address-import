#!/usr/bin/env bash
set -euo pipefail

# Export a clean copy of the audited OSM Rails revision. Never edit the live checkout.
if (( $# != 3 )); then
  echo "usage: $0 SOURCE_CHECKOUT NEW_PRIVATE_STAGE SOURCE_CONTAINER" >&2
  exit 2
fi

source_checkout=$(realpath -e -- "$1")
stage=$(realpath -m -- "$2")
source_container=$3
expected_revision=e87ef1370fc7a9675a6d7df171e15ebcd36b7513
repository_root=$(realpath -e -- "$(dirname -- "$0")/../..")

case "$stage/" in
  "$repository_root/reports/runs/"*) ;;
  *)
    echo "stage must be under the ignored reports/runs directory" >&2
    exit 1
    ;;
esac

case "$stage/" in
  "$source_checkout/"*)
    echo "stage must be outside the live source checkout" >&2
    exit 1
    ;;
esac
if [[ $stage == / ]]; then
  echo "root directory is not a valid stage" >&2
  exit 1
fi

if [[ $(git -C "$source_checkout" rev-parse HEAD) != "$expected_revision" ]]; then
  echo "OSM Rails source revision differs from the reviewed revision" >&2
  exit 1
fi
if [[ -n $(git -C "$source_checkout" status --porcelain --untracked-files=no) ]]; then
  echo "OSM Rails source has tracked modifications" >&2
  exit 1
fi
if [[ -e $stage || -L $stage ]]; then
  echo "stage already exists; refusing to overwrite" >&2
  exit 1
fi
if [[ $(docker inspect "$source_container" --format '{{index .Config.Labels "com.docker.compose.project"}}') != osm-api-sandbox ]]; then
  echo "Node dependency source is not the existing Osaka project" >&2
  exit 1
fi

mkdir -m 700 -- "$stage"
mkdir -m 700 -- "$stage/app"
git -C "$source_checkout" archive "$expected_revision" | tar -x -C "$stage/app"
docker cp "$source_container:/app/node_modules" "$stage/app/"
test -f "$stage/app/node_modules/tag2link/index.json"
test -d "$stage/app/node_modules/@openstreetmap/id/dist"
cp -- "$stage/app/config/example.storage.yml" "$stage/app/config/storage.yml"
cat > "$stage/app/config/database.yml" <<'YAML'
production:
  adapter: postgresql
  encoding: utf8
  url: <%= ENV.fetch("DATABASE_URL") %>
YAML
mkdir -p -- "$stage/app/tmp" "$stage/app/storage"
printf '%s\n' "$expected_revision" > "$stage/source-revision"
echo "Prepared isolated source copy at $stage/app"
