#!/usr/bin/env bash
# Root-only, staged LOCAL installation. Never edits Cloudflare, Rails, or PostgreSQL.
set -euo pipefail
umask 027

usage() {
  echo "usage: $0 {prepare|publish|start|verify} REPOSITORY RELEASE_SHA PRIVATE_RUN_DIR" >&2
  exit 2
}

[[ $# == 4 ]] || usage
phase=$1
[[ $phase == prepare || $phase == publish || $phase == start || $phase == verify ]] || usage
[[ $EUID == 0 ]] || { echo 'Run from an operator-controlled root session; this script never asks for a password.' >&2; exit 1; }
[[ $3 =~ ^[0-9a-f]{40}$ ]] || { echo 'Release must be a full commit SHA.' >&2; exit 1; }

repo=$(realpath -e -- "$2")
sha=$3
source_run=$(realpath -e -- "$4")
[[ -d $source_run && $(git -C "$repo" rev-parse --is-inside-work-tree) == true ]] || {
  echo 'Repository or private run is unavailable.' >&2; exit 1;
}
git -C "$repo" cat-file -e "$sha^{commit}"
git -C "$repo" merge-base --is-ancestor "$sha" refs/heads/main
[[ $(git -C "$repo" rev-parse "$sha") == "$sha" ]] || exit 1

base=/opt/osm-console
release=$base/releases/$sha
venv=$base/venv
reports=/var/lib/osm-console/reports
run_id=$(basename -- "$source_run")
published=$reports/brazil-seven-cities/$run_id

check_account() {
  [[ $(id -u osm-console) != 0 ]] || { echo 'Console account must be unprivileged.' >&2; exit 1; }
  [[ $(id -gn osm-console) == osm-console ]] || { echo 'Unexpected console primary group.' >&2; exit 1; }
  [[ $(id -nG osm-console) == osm-console ]] || { echo 'Console account has supplementary groups.' >&2; exit 1; }
  [[ $(getent passwd osm-console | cut -d: -f6) == /nonexistent ]] || { echo 'Unexpected console home.' >&2; exit 1; }
  [[ $(getent passwd osm-console | cut -d: -f7) == /usr/sbin/nologin ]] || { echo 'Console account has a login shell.' >&2; exit 1; }
}

check_private_boundary() {
  runuser -u osm-console -- test ! -r "$source_run/summary.json" || {
    echo 'Console account can read the private operational report; stop.' >&2; exit 1;
  }
}

check_publication() {
  [[ -d $published && ! -L $published ]] || { echo 'Curated run is absent or linked.' >&2; exit 1; }
  runuser -u osm-console -- env PYTHONPATH="$release/src" "$venv/bin/python" - "$reports" "$run_id" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
from osm_address_import.console_data import ReportRepository
root = Path(sys.argv[1])
published = root / 'brazil-seven-cities' / sys.argv[2]
manifest = json.loads((published / 'publication.json').read_text())
files = manifest['files']
assert len(files) == 19
assert {path.name for path in published.iterdir()} == set(files) | {'publication.json'}
for name, digest in files.items():
    path = published / name
    assert path.is_file() and not path.is_symlink()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
data = ReportRepository(root, require_publication=True).inventory()
assert not data['warnings'], data['warnings']
assert len(data['areas']) == 8 and data['successful_cities'] == 7 and data['failed_attempts'] == 1
assert {area['name'] for area in data['areas']} == {
    'Osaka', 'Manaus', 'Natal', 'Canoas', 'Novo Hamburgo', 'Itu', 'Jundiaí', 'Atibaia'
}
assert next(area for area in data['areas'] if area['name'] == 'Atibaia')['relation_id'] == 298253
canoas = next(area for area in data['areas'] if area['name'] == 'Canoas')
assert canoas['loaded']['report']['status'] == 'SUCCESS'
assert any(item['archived'] and item['report']['status'] == 'BLOCKED' for item in canoas['history'])
print('Curated report integrity and eight-area inventory: PASS')
PY
}

case $phase in
  prepare)
    [[ -z $(ss -H -ltn '( sport = :8765 )') ]] || {
      echo 'Port 8765 already has a listener.' >&2; exit 1;
    }
    [[ ! -L $base && ! -L $base/releases && ! -L /etc/osm-console && ! -L /var/lib/osm-console ]] || exit 1
    [[ ! -e $release && ! -L $release && ! -e $venv && ! -L $venv && ! -e $base/current && ! -L $base/current ]] || {
      echo 'An installation target exists; inspect it before proceeding.' >&2; exit 1;
    }
    if id osm-console &>/dev/null; then
      check_account
    else
      useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin osm-console
    fi
    check_private_boundary
    install -d -o root -g root -m 0755 "$base" "$base/releases"
    install -d -o root -g osm-console -m 0750 /etc/osm-console /var/lib/osm-console "$reports"
    install -d -o root -g root -m 0755 "$release"
    git -C "$repo" archive "$sha" | tar -xf - -C "$release"
    chown -R root:root "$release"
    python3 -m venv "$venv"
    "$venv/bin/python" -m pip install --no-cache-dir --only-binary=:all: -r "$release/requirements-console.txt"
    "$venv/bin/python" -m pip check
    ln -s "$release" "$base/current"
    PYTHONPATH="$release/src" "$venv/bin/python" -m osm_address_import.console_publish \
      --source-run-dir "$source_run" --destination-root "$reports"
    echo 'Review the dry-run artifact list and source hashes, then run the publish phase.'
    ;;
  publish)
    check_account
    check_private_boundary
    [[ -x $venv/bin/python && -d $release && ! -e $published && ! -L $published ]] || {
      echo 'Release is unavailable or curated run already exists; do not overwrite it.' >&2; exit 1;
    }
    PYTHONPATH="$release/src" "$venv/bin/python" -m osm_address_import.console_publish \
      --source-run-dir "$source_run" --destination-root "$reports" --publish
    chown -R root:osm-console "$published"
    find "$published" -type d -exec chmod 0750 {} +
    find "$published" -type f -exec chmod 0640 {} +
    check_publication
    echo 'Review and create /etc/osm-console/console.env and roles.json before start.'
    ;;
  start)
    check_account
    check_private_boundary
    check_publication
    [[ -f /etc/osm-console/console.env && ! -L /etc/osm-console/console.env &&
       -f /etc/osm-console/roles.json && ! -L /etc/osm-console/roles.json ]] || {
      echo 'Production environment and role files are required.' >&2; exit 1;
    }
    [[ $(stat -c '%U:%G:%a' /etc/osm-console/console.env) == root:osm-console:640 ]] || exit 1
    [[ $(stat -c '%U:%G:%a' /etc/osm-console/roles.json) == root:osm-console:640 ]] || exit 1
    grep -qx 'OSM_CONSOLE_ENV=production' /etc/osm-console/console.env
    grep -qx 'OSM_CONSOLE_REPORT_ROOT=/var/lib/osm-console/reports' /etc/osm-console/console.env
    grep -qx 'OSM_CONSOLE_ROLE_FILE=/etc/osm-console/roles.json' /etc/osm-console/console.env
    grep -Eq '^OSM_CONSOLE_ISSUER=https://[a-zA-Z0-9-]+\.cloudflareaccess\.com$' /etc/osm-console/console.env
    grep -Eq '^OSM_CONSOLE_AUDIENCE=[^[:space:]]+$' /etc/osm-console/console.env
    ! grep -q 'OSM_CONSOLE_DEV_MODE\|REPLACE_WITH\|replace-team' /etc/osm-console/console.env
    ! grep -q 'example.invalid' /etc/osm-console/roles.json
    [[ ! -e /etc/systemd/system/osm-console.service && ! -L /etc/systemd/system/osm-console.service ]] || {
      echo 'Console unit already exists; inspect it before replacing.' >&2; exit 1;
    }
    runuser -u osm-console -- env PYTHONPATH="$release/src" "$venv/bin/python" - \
      /etc/osm-console/roles.json <<'PY'
import sys
from osm_address_import.console_auth import RolePolicy
RolePolicy.from_file(sys.argv[1])
print('Role allowlist: valid')
PY
    install -o root -g root -m 0644 "$release/deploy/osm-console/osm-console.service" \
      /etc/systemd/system/osm-console.service
    systemd-analyze verify /etc/systemd/system/osm-console.service
    systemctl daemon-reload
    systemctl enable --now osm-console.service
    "$0" verify "$repo" "$sha" "$source_run"
    ;;
  verify)
    check_account
    check_private_boundary
    check_publication
    systemctl is-active --quiet osm-console.service
    listeners=$(ss -H -ltn '( sport = :8765 )')
    [[ $listeners == *127.0.0.1:8765* ]]
    [[ $listeners != *0.0.0.0:8765* && $listeners != *\*:8765* && $listeners != *\[::\]:8765* ]]
    [[ $(curl --noproxy '*' -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/livez) == 204 ]]
    [[ $(curl --noproxy '*' -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/) == 401 ]]
    [[ $(curl --noproxy '*' -sS --max-time 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/readyz) == 401 ]]
    echo 'Local service, loopback binding, missing-token rejection: PASS'
    ;;
esac
