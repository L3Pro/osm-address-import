#!/usr/bin/env python3
"""Install or roll back the fixed-IP PostgreSQL preflight HBA guard.

Original Osaka use requires a separate approval and --allow-osaka. The backup
must be a new path in a private directory. No PostgreSQL service restart occurs.
"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import stat
import subprocess
import sys


HBA = "/var/lib/postgresql/data/pg_hba.conf"
BEGIN = "# BEGIN OSM ISSUE15 PREFLIGHT"
END = "# END OSM ISSUE15 PREFLIGHT"
ROLE = "osm_rails_preflight_ro"


def run(argv: list[str], input_text: str | None = None) -> str:
    result = subprocess.run(argv, input=input_text, text=True, capture_output=True, check=True, timeout=30)
    return result.stdout


def block(address: str) -> str:
    ip = ipaddress.IPv4Address(address)
    if ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        raise ValueError("candidate IP must be a Docker network address")
    return (
        f"{BEGIN}\n"
        f"host openstreetmap {ROLE} {ip}/32 scram-sha-256\n"
        f"host all all {ip}/32 reject\n"
        f"{END}\n"
    )


def write_hba(container: str, content: str) -> None:
    command = (
        f"set -eu; tmp=$(mktemp {HBA}.issue15.XXXXXX); "
        f"cat > \"$tmp\"; chmod 600 \"$tmp\"; mv \"$tmp\" {HBA}; "
        "psql -X -U postgres -d openstreetmap -Atc 'SELECT pg_reload_conf()'"
    )
    if run(["docker", "exec", "-i", "-u", "postgres", container, "sh", "-c", command], content).strip() != "t":
        raise RuntimeError("PostgreSQL rejected configuration reload")


def verify_rules(container: str, address: str) -> None:
    query = (
        "SELECT type||'|'||array_to_string(database,',')||'|'||"
        "array_to_string(user_name,',')||'|'||address||'|'||auth_method "
        "FROM pg_hba_file_rules WHERE type='host' ORDER BY line_number LIMIT 2"
    )
    actual = run(["docker", "exec", container, "psql", "-X", "-U", "postgres", "-d", "openstreetmap", "-Atc", query]).strip().splitlines()
    expected = [f"host|openstreetmap|{ROLE}|{address}|scram-sha-256", f"host|all|all|{address}|reject"]
    if actual != expected:
        raise RuntimeError("candidate-IP HBA rules are missing or out of order")
    errors = run(["docker", "exec", container, "psql", "-X", "-U", "postgres", "-d", "openstreetmap", "-Atc", "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL"]).strip()
    if errors != "0":
        raise RuntimeError("PostgreSQL found HBA parse errors")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "rollback"))
    parser.add_argument("--container", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--candidate-ip", required=True)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--allow-osaka", action="store_true")
    args = parser.parse_args()
    if args.project == "osm-api-sandbox" and not args.allow_osaka:
        parser.error("original Osaka HBA requires separate approval and --allow-osaka")
    if args.backup.parent.is_symlink() or stat.S_IMODE(args.backup.parent.stat().st_mode) & 0o077:
        parser.error("HBA backup requires a mode-0700 parent directory")
    try:
        expected_block = block(args.candidate_ip)
        container = json.loads(run(["docker", "inspect", args.container]))[0]
        network = json.loads(run(["docker", "network", "inspect", args.network]))[0]
        if container["Config"]["Labels"].get("com.docker.compose.project") != args.project:
            raise ValueError("database container project label mismatch")
        if network["Labels"].get("com.docker.compose.project") != args.project:
            raise ValueError("network project label mismatch")
        if args.network not in container["NetworkSettings"]["Networks"]:
            raise ValueError("database container is not attached to expected network")
        subnets = [ipaddress.ip_network(item["Subnet"]) for item in network["IPAM"]["Config"]]
        if not any(ipaddress.ip_address(args.candidate_ip) in subnet for subnet in subnets):
            raise ValueError("candidate IP is outside expected network")
        if any(item.get("IPv4Address", "").split("/")[0] == args.candidate_ip for item in network.get("Containers", {}).values()):
            raise ValueError("candidate IP is already in use; stop candidate before HBA change")
        hba_path = run(["docker", "exec", args.container, "psql", "-X", "-U", "postgres", "-d", "openstreetmap", "-Atc", "SHOW hba_file"]).strip()
        if hba_path != HBA:
            raise ValueError("unexpected HBA path")
        current = run(["docker", "exec", "-u", "postgres", args.container, "cat", HBA])
        if args.action == "install":
            if current.startswith(expected_block):
                verify_rules(args.container, args.candidate_ip)
                print("Candidate-IP HBA guard already installed")
                return 0
            if BEGIN in current or END in current or args.backup.is_symlink():
                raise ValueError("existing HBA marker or symlink backup; refusing overwrite")
            if args.backup.exists():
                if stat.S_IMODE(args.backup.stat().st_mode) != 0o600 or args.backup.read_text() != current:
                    raise ValueError("existing backup differs from current HBA")
            else:
                fd = os.open(args.backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(current)
            try:
                write_hba(args.container, expected_block + current)
                verify_rules(args.container, args.candidate_ip)
            except Exception:
                write_hba(args.container, current)
                raise
            print("Installed candidate-IP SCRAM/reject HBA guard; private backup retained")
        else:
            if args.backup.is_symlink() or stat.S_IMODE(args.backup.stat().st_mode) != 0o600:
                raise ValueError("backup must be a non-symlink mode-0600 file")
            prior = args.backup.read_text()
            if current != expected_block + prior:
                raise ValueError("HBA changed since install; refusing rollback")
            try:
                write_hba(args.container, prior)
            except Exception:
                write_hba(args.container, current)
                raise
            print("Restored exact prior HBA; private backup retained for review")
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"HBA {args.action} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
