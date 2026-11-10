#!/usr/bin/env python3
"""Exercise a disposable preflight role over its password-authenticated network path.

Run inside a disposable container at the candidate's fixed IP. The script never
prints DATABASE_URL or its password. All attempted mutations must fail.
"""

import os
import subprocess
import sys
from urllib.parse import unquote, urlparse


ROLE = "osm_rails_preflight_ro"
READ_TABLES = (
    "changesets",
    "current_nodes", "current_node_tags", "current_ways", "current_way_nodes",
    "current_way_tags", "current_relations", "current_relation_members",
    "current_relation_tags",
)


def psql(sql: str, *, role: str = ROLE, password: str | None = None) -> subprocess.CompletedProcess[str]:
    url = urlparse(os.environ["DATABASE_URL"])
    env = os.environ.copy()
    env.pop("PGOPTIONS", None)
    env["PGPASSWORD"] = unquote(url.password) if password is None else password
    return subprocess.run(
        ["psql", "-X", "-h", url.hostname, "-U", role, "-d", url.path.lstrip("/"),
         "-v", "ON_ERROR_STOP=1", "-Atc", sql],
        env=env, text=True, capture_output=True, timeout=20,
    )


def check(ok: bool, name: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    if not ok:
        raise AssertionError(name)


def main() -> int:
    attrs = psql("SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit FROM pg_roles WHERE rolname=current_user")
    check(attrs.returncode == 0 and attrs.stdout.strip() == f"{ROLE}|f|f|f|f|f|f", "restricted role attributes")
    for table in READ_TABLES:
        result = psql(f"SELECT 1 FROM public.{table} LIMIT 1")
        check(result.returncode == 0, f"SELECT {table}")
    check(psql("SELECT id, display_name, data_public, creation_time FROM users LIMIT 1").returncode == 0, "SELECT restricted users view")
    secret_column = psql("SELECT pass_crypt, email FROM users LIMIT 1")
    check(secret_column.returncode != 0 and "does not exist" in secret_column.stderr.lower(), "user secrets absent from view")
    denied = {
        "INSERT": "INSERT INTO public.current_nodes SELECT * FROM public.current_nodes WHERE false",
        "UPDATE": "UPDATE public.current_nodes SET latitude=latitude WHERE false",
        "DELETE": "DELETE FROM public.current_nodes WHERE false",
        "TRUNCATE": "TRUNCATE public.current_nodes",
        "schema DDL": "CREATE TABLE public.issue15_probe (id integer)",
        "temporary DDL": "CREATE TEMP TABLE issue15_probe (id integer)",
        "database DDL": "CREATE SCHEMA issue15_probe",
        "role creation": "CREATE ROLE issue15_probe NOLOGIN",
        "role escalation": "SET ROLE openstreetmap",
        "ungranted OAuth read": "SELECT 1 FROM public.oauth_access_tokens LIMIT 1",
        "underlying users read": "SELECT 1 FROM public.users LIMIT 1",
        "ungranted migration read": "SELECT 1 FROM public.schema_migrations LIMIT 1",
        "inherited PostGIS read": "SELECT 1 FROM public.spatial_ref_sys LIMIT 1",
    }
    for name, sql in denied.items():
        result = psql("SET default_transaction_read_only=off; " + sql)
        check(result.returncode != 0 and "permission denied" in result.stderr.lower(), f"denied {name}")
    wrong_password = psql("SELECT 1", password="deliberately-wrong-password")
    check(wrong_password.returncode != 0 and "password authentication failed" in wrong_password.stderr.lower(), "wrong password rejected by SCRAM")
    impersonation = psql("SELECT 1", role="openstreetmap", password="deliberately-wrong-password")
    check(impersonation.returncode != 0 and "pg_hba.conf rejects connection" in impersonation.stderr.lower(), "superuser impersonation rejected by HBA")
    print("Restricted role verification complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, subprocess.TimeoutExpired) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        sys.exit(1)
