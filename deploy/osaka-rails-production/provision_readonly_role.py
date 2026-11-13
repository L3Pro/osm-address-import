#!/usr/bin/env python3
"""Provision the fixed Rails preflight role; never run on Osaka without approval.

The only secret input is a mode-0600 generated password file. SQL contains a
SCRAM verifier, not the plaintext password, and is sent to psql on stdin.
"""

import argparse
import base64
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys


ROLE = "osm_rails_preflight_ro"
MARKER = "Issue 15 read-only Rails preflight role v2"
VIEW_SCHEMA = "issue15_preflight"
SELECT_TABLES = (
    "changesets",
    "current_nodes",
    "current_node_tags",
    "current_ways",
    "current_way_nodes",
    "current_way_tags",
    "current_relations",
    "current_relation_members",
    "current_relation_tags",
)


def scram_verifier(password: str) -> str:
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 4096)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    encoded = lambda value: base64.b64encode(value).decode("ascii")
    return f"SCRAM-SHA-256$4096:{encoded(salt)}${encoded(stored_key)}:{encoded(server_key)}"


def sql_for(verifier: str) -> str:
    if not re.fullmatch(r"SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+", verifier):
        raise ValueError("invalid SCRAM verifier")
    tables = ", ".join(f"public.{table}" for table in SELECT_TABLES)
    return f"""BEGIN;
DO $guard$
BEGIN
  IF current_database() <> 'openstreetmap' THEN
    RAISE EXCEPTION 'wrong database';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
    IF NOT EXISTS (
      SELECT 1 FROM pg_roles
      WHERE rolname = '{ROLE}' AND shobj_description(oid, 'pg_authid') = '{MARKER}'
    ) THEN
      RAISE EXCEPTION 'role name already exists without provisioning marker';
    END IF;
  ELSE
    CREATE ROLE {ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 8;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{VIEW_SCHEMA}') THEN
    IF NOT EXISTS (
      SELECT 1 FROM pg_namespace
      WHERE nspname = '{VIEW_SCHEMA}'
        AND nspowner = 'postgres'::regrole
        AND obj_description(oid, 'pg_namespace') = '{MARKER}'
    ) THEN
      RAISE EXCEPTION 'preflight view schema exists without provisioning marker';
    END IF;
  ELSE
    CREATE SCHEMA {VIEW_SCHEMA} AUTHORIZATION postgres;
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member
    WHERE r.rolname = '{ROLE}'
  ) THEN
    RAISE EXCEPTION 'preflight role has unexpected membership';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
    WHERE r.rolname = '{ROLE}'
  ) THEN
    RAISE EXCEPTION 'preflight role owns database objects';
  END IF;
END
$guard$;
ALTER ROLE {ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 8 PASSWORD '{verifier}';
COMMENT ON ROLE {ROLE} IS '{MARKER}';
COMMENT ON SCHEMA {VIEW_SCHEMA} IS '{MARKER}';
CREATE OR REPLACE VIEW {VIEW_SCHEMA}.users WITH (security_barrier=true) AS
  SELECT id, display_name, data_public, creation_time FROM public.users;
COMMENT ON VIEW {VIEW_SCHEMA}.users IS '{MARKER}';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE TEMPORARY ON DATABASE openstreetmap FROM PUBLIC;
REVOKE SELECT ON TABLE public.geography_columns, public.geometry_columns,
  public.spatial_ref_sys FROM PUBLIC;
REVOKE ALL PRIVILEGES ON DATABASE openstreetmap FROM {ROLE};
REVOKE ALL PRIVILEGES ON SCHEMA public FROM {ROLE};
REVOKE ALL PRIVILEGES ON SCHEMA {VIEW_SCHEMA} FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SCHEMA {VIEW_SCHEMA} FROM {ROLE};
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {ROLE};
REVOKE ALL PRIVILEGES ON TABLE {VIEW_SCHEMA}.users FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE {VIEW_SCHEMA}.users FROM {ROLE};
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {ROLE};
GRANT CONNECT ON DATABASE openstreetmap TO {ROLE};
GRANT USAGE ON SCHEMA public TO {ROLE};
GRANT USAGE ON SCHEMA {VIEW_SCHEMA} TO {ROLE};
GRANT SELECT ON TABLE {tables} TO {ROLE};
GRANT SELECT ON TABLE {VIEW_SCHEMA}.users TO {ROLE};
ALTER ROLE {ROLE} IN DATABASE openstreetmap SET search_path = {VIEW_SCHEMA}, public;
COMMIT;
"""


def run(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=input_text, text=True, capture_output=True, check=True, timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--credential-file", required=True, type=Path)
    parser.add_argument("--allow-osaka", action="store_true", help="requires separate original-DB approval")
    args = parser.parse_args()
    if args.project == "osm-api-sandbox" and not args.allow_osaka:
        parser.error("original Osaka database requires separate approval and --allow-osaka")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.container) or not re.fullmatch(r"[a-zA-Z0-9_.-]+", args.project):
        parser.error("invalid Docker container or project name")
    mode = stat.S_IMODE(args.credential_file.stat().st_mode)
    if mode != 0o600 or args.credential_file.is_symlink():
        parser.error("credential file must be a non-symlink mode-0600 file")
    if args.credential_file.parent.is_symlink() or stat.S_IMODE(args.credential_file.parent.stat().st_mode) & 0o077:
        parser.error("credential file requires a mode-0700 parent directory")
    password = args.credential_file.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", password):
        parser.error("credential must be generated by make_private_env.py")
    try:
        label = run(["docker", "inspect", args.container, "--format", '{{index .Config.Labels "com.docker.compose.project"}}']).stdout.strip()
        if label != args.project:
            parser.error("container project label does not match expected project")
        run(
            ["docker", "exec", "-i", args.container, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "openstreetmap"],
            input_text=sql_for(scram_verifier(password)),
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"provisioning failed ({type(error).__name__}); transaction rolled back", file=sys.stderr)
        return 1
    print(f"Provisioned {ROLE} in project {args.project}; verify authentication and effective privileges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
