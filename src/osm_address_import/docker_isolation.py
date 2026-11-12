"""Verify that an isolated API listener belongs to a disposable Docker project.

This is an operational guard, not a security boundary against a host administrator
who can replace containers or change the Docker daemon during a request.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


class IsolationError(RuntimeError):
    pass


PROJECT = re.compile(r"osaka-api-harness-[0-9]{8}-[0-9a-f]{8}\Z")
WEB_IMAGE = "sha256:16a161d5016f1158c556bdb9b4aaf359c4fce60b22d5f592bfa47dbe750d1332"
DB_IMAGE = "sha256:7e04bfcf1b20b7ccd558f1977e9f08f72c5683b4b59b021a127cbe370a7ee574"
WEB_COMMAND = ["bundle", "exec", "rails", "s", "-p", "3000", "-b", "0.0.0.0"]


def _check_project(project):
    if not isinstance(project, str) or not PROJECT.fullmatch(project):
        raise IsolationError("isolated project must be osaka-api-harness-YYYYMMDD-8hex")


def _project_resources(project):
    resources = {}
    for kind, command in (("container", ["docker", "container", "ls", "--all"]),
                          ("volume", ["docker", "volume", "ls"]),
                          ("network", ["docker", "network", "ls"])):
        try:
            output_format = "{{.Names}}" if kind == "container" else "{{.Name}}"
            all_items = subprocess.run(command + ["--format", output_format],
                                       capture_output=True, text=True, check=True, timeout=10)
            labeled = subprocess.run(command + ["--filter", f"label=com.docker.compose.project={project}",
                                              "--format", output_format],
                                     capture_output=True, text=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise IsolationError(f"Docker {kind} listing failed; isolated operation refused") from None
        resources[kind] = ({name for name in all_items.stdout.splitlines() if name.startswith(project)}
                           | set(labeled.stdout.splitlines()))
    return resources


def assert_fresh_project(project):
    """Refuse Compose creation if any names in this unique namespace exist."""
    _check_project(project)
    if any(_project_resources(project).values()):
        raise IsolationError("disposable project namespace already contains Docker resources")


def verify_cleanup_scope(project):
    """Refuse volume cleanup unless the project owns exactly the expected resources."""
    verify_isolated_docker(project)
    resources = _project_resources(project)
    expected = {"container": {f"{project}-web-1", f"{project}-db-1"},
                "volume": {f"{project}_db-data", f"{project}_web-storage"},
                "network": {f"{project}_isolated", f"{project}_frontend"}}
    if resources != expected:
        raise IsolationError("disposable cleanup resource set differs from expected project objects")


def _inspect(kind, *names):
    try:
        process = subprocess.run(["docker", kind, "inspect", *names],
                                 capture_output=True, text=True, check=True, timeout=10)
        return json.loads(process.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        # Docker inspect can contain DATABASE_URL and other secrets. Never echo it.
        raise IsolationError(f"Docker {kind} inspection failed; isolated write refused") from None


def verify_isolated_docker(project):
    """Fail unless port 39003 reaches a project-owned web with only its own DB."""
    _check_project(project)
    web_name, db_name = f"{project}-web-1", f"{project}-db-1"
    try:
        web, db = _inspect("container", web_name, db_name)
        isolated_name, frontend_name = f"{project}_isolated", f"{project}_frontend"
        isolated, frontend = _inspect("network", isolated_name, frontend_name)
        db_volume, storage_volume = _inspect("volume", f"{project}_db-data", f"{project}_web-storage")
        expected_port = {"3000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "39003"}]}
        if web["Name"] != "/" + web_name or db["Name"] != "/" + db_name:
            raise IsolationError("unexpected disposable container names")
        if web["Image"] != WEB_IMAGE or db["Image"] != DB_IMAGE:
            raise IsolationError("disposable container image digest mismatch")
        if web["Config"]["Cmd"] != WEB_COMMAND or web["Config"]["WorkingDir"] != "/app":
            raise IsolationError("disposable Rails command or working directory mismatch")
        for container, service in ((web, "web"), (db, "db")):
            labels = container["Config"]["Labels"]
            if (labels.get("com.docker.compose.project") != project
                    or labels.get("com.docker.compose.service") != service
                    or not container["State"]["Running"]):
                raise IsolationError(f"{service} ownership or running state mismatch")
        if web["HostConfig"]["PortBindings"] != expected_port:
            raise IsolationError("disposable web port binding mismatch")
        if web["NetworkSettings"]["Ports"] != expected_port:
            raise IsolationError("disposable web published listener mismatch")
        if db["HostConfig"]["PortBindings"] not in (None, {}):
            raise IsolationError("disposable database must have no published ports")
        if web["HostConfig"].get("ExtraHosts"):
            raise IsolationError("disposable web may not override DNS with extra hosts")
        if set(web["NetworkSettings"]["Networks"]) != {isolated_name, frontend_name}:
            raise IsolationError("disposable web network attachments mismatch")
        if set(db["NetworkSettings"]["Networks"]) != {isolated_name}:
            raise IsolationError("disposable database network attachments mismatch")
        for network, name, internal, members in (
            (isolated, isolated_name, True, {web_name, db_name}),
            (frontend, frontend_name, False, {web_name}),
        ):
            if (network["Name"] != name or network["Internal"] is not internal
                    or network["Labels"].get("com.docker.compose.project") != project
                    or {item["Name"] for item in network["Containers"].values()} != members):
                raise IsolationError("disposable network ownership or membership mismatch")
        db_mounts = db["Mounts"]
        if (len(db_mounts) != 1 or db_mounts[0]["Type"] != "volume"
                or db_mounts[0]["Name"] != f"{project}_db-data"
                or db_mounts[0]["Destination"] != "/var/lib/postgresql/data"):
            raise IsolationError("disposable database volume mismatch")
        app_root = Path(__file__).resolve().parents[2]
        expected_app = app_root / "reports" / "runs" / project / "app"
        app_mounts = [m for m in web["Mounts"] if m["Destination"] == "/app"]
        if (len(app_mounts) != 1 or app_mounts[0]["Type"] != "bind"
                or Path(app_mounts[0]["Source"]) != expected_app
                or expected_app.is_symlink() or expected_app.parent.is_symlink()
                or expected_app.parent.parent.is_symlink()):
            raise IsolationError("disposable web source mount mismatch")
        other_mounts = [m for m in web["Mounts"] if m["Destination"] != "/app"]
        if (len(other_mounts) != 1 or other_mounts[0]["Type"] != "volume"
                or other_mounts[0]["Name"] != f"{project}_web-storage"
                or other_mounts[0]["Destination"] != "/app/storage"):
            raise IsolationError("disposable web storage mount mismatch")
        for volume, name, mount in ((db_volume, f"{project}_db-data", db_mounts[0]),
                                    (storage_volume, f"{project}_web-storage", other_mounts[0])):
            if (volume["Name"] != name or volume["Driver"] != "local"
                    or volume.get("Options") not in (None, {})
                    or volume["Labels"].get("com.docker.compose.project") != project
                    or volume["Mountpoint"] != mount["Source"]):
                raise IsolationError("disposable volume ownership or driver mismatch")
        env = dict(item.split("=", 1) for item in web["Config"]["Env"] if "=" in item)
        if env.get("RAILS_ENV") != "production" or env.get("RACK_ENV") != "production":
            raise IsolationError("disposable Rails environment mismatch")
        url = urlsplit(env.get("DATABASE_URL", ""))
        if (url.scheme not in ("postgres", "postgresql") or url.hostname != "db"
                or url.port not in (None, 5432) or url.path != "/openstreetmap"
                or url.query or url.fragment):
            raise IsolationError("disposable web database target mismatch")
        database_config = expected_app / "config" / "database.yml"
        if 'ENV.fetch("DATABASE_URL")' not in database_config.read_text():
            raise IsolationError("disposable Rails database configuration mismatch")
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        raise IsolationError("incomplete Docker isolation evidence; write refused") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("fresh", "verify", "cleanup-check"))
    parser.add_argument("project")
    args = parser.parse_args(argv)
    try:
        if args.action == "fresh":
            assert_fresh_project(args.project)
        elif args.action == "verify":
            verify_isolated_docker(args.project)
        else:
            verify_cleanup_scope(args.project)
    except IsolationError as exc:
        parser.exit(1, str(exc) + "\n")
    print(f"{args.action}: disposable Docker project verified")


if __name__ == "__main__":
    main()
