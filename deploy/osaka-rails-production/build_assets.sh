#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo "usage: $0 PRIVATE_STAGE RAILS_IMAGE_DIGEST PRIVATE_ENV_FILE PRIVATE_SETTINGS_FILE" >&2
  exit 2
fi

stage=$(realpath -e -- "$1")
image=$2
private_env=$(realpath -e -- "$3")
private_settings=$(realpath -e -- "$4")
expected_revision=e87ef1370fc7a9675a6d7df171e15ebcd36b7513

if [[ $(cat "$stage/source-revision") != "$expected_revision" ]]; then
  echo "candidate source revision is not the reviewed revision" >&2
  exit 1
fi
if [[ ! -f $stage/app/node_modules/tag2link/index.json || ! -d $stage/app/node_modules/@openstreetmap/id/dist ]]; then
  echo "Node and iD dependencies are missing" >&2
  exit 1
fi
if [[ ! $image =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo "pin the Rails image by sha256 digest" >&2
  exit 1
fi

docker run --rm --network none --memory 1536m --cpus 1.5 \
  --env-file "$private_env" \
  -e RAILS_ENV=production -e RACK_ENV=production -e RAILS_SERVE_STATIC_FILES=true \
  -v "$stage/app:/app" \
  -v "$private_settings:/app/config/settings.local.yml:ro" \
  -w /app "$image" /bin/sh -c 'bundle exec i18n export && bundle exec rails assets:precompile'

test -s "$stage/app/tmp/manifest.json"
test -n "$(find "$stage/app/public/assets" -maxdepth 1 -name 'id-*.js' -print -quit)"
test -n "$(find "$stage/app/public/assets" -maxdepth 1 -name 'id-*.css' -print -quit)"
echo "Production assets built in the private candidate copy"
