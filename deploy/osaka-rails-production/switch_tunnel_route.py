#!/usr/bin/env python3
"""Validate and atomically switch only the Osaka tunnel origin between ports 3002/3003.

This changes a configuration file, not a running tunnel. Restart is a separate
reviewed operator step. The backup may contain credentials and must stay private.
"""

import argparse
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


OLD = b"http://127.0.0.1:3002"
NEW = b"http://127.0.0.1:3003"
LIVE_CONFIG = Path("/etc/cloudflared/config.yml")


def replace_origin(data: bytes, before: bytes, after: bytes) -> bytes:
    lines = data.splitlines(keepends=True)
    found = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == b"service: " + before:
            found.append(index)
    if len(found) != 1 or any(line.strip() == b"service: " + after for line in lines):
        raise ValueError("expected exactly one old origin and no new origin")
    index = found[0]
    lines[index] = lines[index].replace(before, after, 1)
    return b"".join(lines)


def validate(path: Path) -> None:
    result = subprocess.run(
        ["cloudflared", "tunnel", "--config", str(path), "ingress", "validate"],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("cloudflared rejected the proposed ingress configuration")


def sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_atomically(
    path: Path, data: bytes, original_stat: os.stat_result, expected_current: bytes
) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".issue15-route-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        # The current live file is 0644. Never stage or leave private config
        # world-readable, even if its previous permissions were broader.
        os.fchmod(fd, stat.S_IMODE(original_stat.st_mode) & 0o600)
        os.fchown(fd, original_stat.st_uid, original_stat.st_gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        validate(temporary)
        current_stat = path.stat()
        if (
            current_stat.st_dev != original_stat.st_dev
            or current_stat.st_ino != original_stat.st_ino
            or current_stat.st_mtime_ns != original_stat.st_mtime_ns
            or path.read_bytes() != expected_current
        ):
            raise RuntimeError("tunnel config changed during validation; refusing overwrite")
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("candidate", "rollback"))
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--test-config", action="store_true", help="allow a private test copy instead of the live config"
    )
    args = parser.parse_args()
    path = args.config
    if args.test_config:
        test_root = Path(__file__).resolve().parents[2] / "reports/runs"
        resolved = path.resolve()
        if resolved == LIVE_CONFIG or not (
            resolved.is_relative_to(Path("/tmp")) or resolved.is_relative_to(test_root)
        ):
            raise ValueError("test config must be a private copy under /tmp or reports/runs")
    elif path != LIVE_CONFIG:
        raise ValueError("live route target must be /etc/cloudflared/config.yml")
    backup = path.with_name(path.name + ".issue15-backup")
    if path.is_symlink() or not path.is_file():
        raise ValueError("config must be a regular, non-symlink file")
    lock_path = path.with_name(path.name + ".issue15.lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original_stat = path.stat()
        current = path.read_bytes()

        if args.mode == "candidate":
            if backup.exists() or backup.is_symlink():
                raise FileExistsError("private backup already exists; inspect it before retrying")
            updated = replace_origin(current, OLD, NEW)
            validate(path)
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(current)
                    stream.flush()
                    os.fsync(stream.fileno())
                sync_directory(path.parent)
                write_atomically(path, updated, original_stat, current)
            except Exception:
                if path.read_bytes() == current and backup.read_bytes() == current:
                    backup.unlink()
                raise
            print("Candidate route configured; restart the tunnel only after approval")
        else:
            if backup.is_symlink() or not backup.is_file():
                raise FileNotFoundError("private route backup is missing")
            previous = backup.read_bytes()
            if current != replace_origin(previous, OLD, NEW):
                raise ValueError("tunnel config changed since cutover; refusing automatic rollback")
            validate(backup)
            write_atomically(path, previous, original_stat, current)
            print("Previous route configured; restart the tunnel to activate rollback")
    finally:
        os.close(lock_fd)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"route switch stopped: {error}", file=sys.stderr)
        sys.exit(1)
