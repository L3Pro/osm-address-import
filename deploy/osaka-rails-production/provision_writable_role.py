#!/usr/bin/env python3
"""Provision the Issue #15 writable candidate role on a disposable database.

Original Osaka use requires a separate approval and --allow-osaka. The role
cannot own objects or perform DDL; no migrations are permitted at cutover.
"""

import argparse
from pathlib import Path
import re
import stat
import subprocess
import sys

from provision_readonly_role import scram_verifier


ROLE = "osm_rails_cutover_rw"
MARKER = "Issue 15 writable Rails candidate role v1"
READ_ONLY_TABLES = ("ar_internal_metadata", "schema_migrations", "spatial_ref_sys")


def sql_for(verifier: str) -> str:
    if not re.fullmatch(r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+", verifier):
        raise ValueError("invalid SCRAM verifier")
    readonly = ", ".join(f"public.{name}" for name in READ_ONLY_TABLES)
    return f"""BEGIN;
DO $guard$
BEGIN
  IF current_database() <> 'openstreetmap' THEN
    RAISE EXCEPTION 'wrong database';
  END IF;
  IF (SELECT count(*) FROM pg_tables WHERE schemaname='public') <> 58
     OR (SELECT count(*) FROM pg_sequences WHERE schemaname='public') <> 35 THEN
    RAISE EXCEPTION 'application schema inventory changed; review grants';
  END IF;
  IF has_schema_privilege('public', 'public', 'CREATE')
     OR has_database_privilege('public', 'openstreetmap', 'TEMP') THEN
    RAISE EXCEPTION 'PUBLIC CREATE or TEMP privilege remains; review existing grants';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{ROLE}') THEN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{ROLE}'
      AND shobj_description(oid, 'pg_authid')='{MARKER}') THEN
      RAISE EXCEPTION 'role name exists without provisioning marker';
    END IF;
  ELSE
    CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 8;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
             WHERE r.rolname='{ROLE}')
    OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
               WHERE r.rolname='{ROLE}') THEN
    RAISE EXCEPTION 'candidate role has membership or owns objects';
  END IF;
END
$guard$;
ALTER ROLE {ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 8 PASSWORD '{verifier}';
COMMENT ON ROLE {ROLE} IS '{MARKER}';
REVOKE ALL PRIVILEGES ON DATABASE openstreetmap FROM {ROLE};
REVOKE ALL PRIVILEGES ON SCHEMA public FROM {ROLE};
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {ROLE};
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {ROLE};
GRANT CONNECT ON DATABASE openstreetmap TO {ROLE};
GRANT USAGE ON SCHEMA public TO {ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE};
REVOKE INSERT, UPDATE, DELETE ON TABLE {readonly} FROM {ROLE};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE};
COMMIT;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--credential-file", required=True, type=Path)
    parser.add_argument("--allow-osaka", action="store_true")
    args = parser.parse_args()
    if args.project == "osm-api-sandbox" and not args.allow_osaka:
        parser.error("original Osaka database requires separate approval and --allow-osaka")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.container) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.project):
        parser.error("invalid Docker container or project name")
    path = args.credential_file
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        parser.error("credential must be a non-symlink mode-0600 file")
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        parser.error("credential requires a mode-0700 parent directory")
    password = path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", password):
        parser.error("credential must be a generated 43-character token")
    try:
        label = subprocess.run(["docker", "inspect", args.container, "--format", '{{index .Config.Labels "com.docker.compose.project"}}'],
                               capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        if label != args.project:
            parser.error("container project label does not match expected project")
        subprocess.run(["docker", "exec", "-i", args.container, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "openstreetmap"],
                       input=sql_for(scram_verifier(password)), capture_output=True, text=True, check=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"provisioning failed ({type(error).__name__}); transaction rolled back", file=sys.stderr)
        return 1
    print(f"Provisioned {ROLE} in disposable project {args.project}; verify privileges and authentication")
    return 0


if __name__ == "__main__":
    sys.exit(main())
