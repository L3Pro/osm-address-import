#!/usr/bin/env python3
"""Read-only Osaka Rails/tunnel status; never print private config or credentials."""

import argparse
import json
from pathlib import Path
import stat
import subprocess
import sys


LIVE_CONFIG = Path("/etc/cloudflared/config.yml")
OLD = b"service: http://127.0.0.1:3002"
NEW = b"service: http://127.0.0.1:3003"
CANDIDATE = "issue15-osaka-prod-candidate-1"
ORIGINAL = "osm-api-sandbox-web-1"


def origin(data):
    """Classify only exact service lines; never return configuration contents."""
    services = [line.strip() for line in data.splitlines() if line.strip().startswith(b"service:")]
    matches = [line for line in services if line in (OLD, NEW)]
    if len(matches) != 1:
        return "unexpected"
    return "3002" if matches[0] == OLD else "3003"


def route_status(config):
    backup = config.with_name(config.name + ".issue15-backup")
    result = {"configured_origin": "unreadable", "rollback_backup": "unreadable",
              "rollback_origin": "unreadable", "route_state": "unknown",
              "config_mode": None, "backup_mode": None}
    try:
        if config.is_symlink():
            result["configured_origin"] = "unsafe_symlink"
        else:
            result["config_mode"] = oct(stat.S_IMODE(config.stat().st_mode))
            result["configured_origin"] = origin(config.read_bytes())
    except (OSError, ValueError):
        pass
    try:
        if backup.is_symlink():
            result["rollback_backup"] = "unsafe_symlink"
        elif not backup.exists():
            result["rollback_backup"] = "missing"
        elif backup.is_file():
            result["rollback_backup"] = "present"
            result["backup_mode"] = oct(stat.S_IMODE(backup.stat().st_mode))
            result["rollback_origin"] = origin(backup.read_bytes())
        else:
            result["rollback_backup"] = "unexpected_type"
    except (OSError, ValueError):
        pass
    if (result["configured_origin"] == "3003" and result["rollback_origin"] == "3002"
            and result["config_mode"] == "0o600" and result["backup_mode"] == "0o600"):
        result["route_state"] = "already_switched"
    elif result["configured_origin"] == "3002" and result["rollback_origin"] == "3002":
        result["route_state"] = "rollback_configured"
    elif result["configured_origin"] == "3002" and result["rollback_backup"] == "missing":
        result["route_state"] = "precutover"
    elif result["configured_origin"] != "unreadable":
        result["route_state"] = "review_required"
    return result


def _run(*command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def service_status():
    result = _run("systemctl", "is-active", "cloudflared")
    return result.stdout.strip() if result and result.stdout.strip() else "unavailable"


def container_status(name):
    result = _run("docker", "inspect", name)
    if not result or result.returncode:
        return {"running": None, "health": "unavailable"}
    try:
        item = json.loads(result.stdout)[0]
        state = item["State"]
        status = {"running": state["Running"],
                  "health": state.get("Health", {}).get("Status", "not_configured")}
        if name == CANDIDATE:
            env = dict(value.split("=", 1) for value in item["Config"]["Env"] if "=" in value)
            status["rails_env"] = env.get("RAILS_ENV", "unset")
            status["rack_env"] = env.get("RACK_ENV", "unset")
            bindings = item["HostConfig"]["PortBindings"] or {}
            status["port_3003_loopback"] = bindings.get("3000/tcp") == [
                {"HostIp": "127.0.0.1", "HostPort": "3003"}]
        return status
    except (KeyError, TypeError, ValueError, IndexError):
        return {"running": None, "health": "unavailable"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=LIVE_CONFIG)
    parser.add_argument("--test-config", action="store_true", help="inspect a private test copy")
    args = parser.parse_args(argv)
    if args.test_config:
        root = Path(__file__).resolve().parents[2] / "reports" / "runs"
        resolved = args.config.resolve()
        if resolved == LIVE_CONFIG or not (resolved.is_relative_to(Path("/tmp"))
                                            or resolved.is_relative_to(root)):
            parser.error("test config must be under /tmp or reports/runs")
    elif args.config != LIVE_CONFIG:
        parser.error("live config path must be /etc/cloudflared/config.yml")
    result = route_status(args.config)
    result["cloudflared"] = service_status()
    result["candidate"] = container_status(CANDIDATE)
    result["original_web"] = container_status(ORIGINAL)
    if result["route_state"] == "already_switched":
        result["guidance"] = "Preserve the rollback backup; do not rerun the candidate switch. Use operator-assisted rollback only if required."
    elif result["route_state"] == "rollback_configured":
        result["guidance"] = "The config selects 3002; preserve the rollback backup and review before any route change."
    else:
        result["guidance"] = "Route evidence is incomplete or unexpected; make no automatic change."
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if (result["route_state"] == "already_switched"
                 and result["cloudflared"] == "active"
                 and result["candidate"] == {"running": True, "health": "healthy",
                                              "rails_env": "production", "rack_env": "production",
                                              "port_3003_loopback": True}) else 1


if __name__ == "__main__":
    sys.exit(main())
