#!/usr/bin/env python3
"""Validate and atomically switch only the Osaka tunnel origin between ports 3002/3003.

This changes a configuration file, not a running tunnel. Restart is a separate
reviewed operator step. The backup may contain credentials and must stay private.
"""

import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


OLD = b"http://127.0.0.1:3002"
NEW = b"http://127.0.0.1:3003"


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


def write_atomically(path: Path, data: bytes, original_stat: os.stat_result) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".issue15-route-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, stat.S_IMODE(original_stat.st_mode))
        os.fchown(fd, original_stat.st_uid, original_stat.st_gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        validate(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("candidate", "rollback"))
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    path = args.config
    backup = path.with_name(path.name + ".issue15-backup")
    if path.is_symlink() or not path.is_file():
        raise ValueError("config must be a regular, non-symlink file")
    original_stat = path.stat()
    current = path.read_bytes()

    if args.mode == "candidate":
        if backup.exists() or backup.is_symlink():
            raise FileExistsError("private backup already exists; inspect it before retrying")
        updated = replace_origin(current, OLD, NEW)
        validate(path)
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(current)
            stream.flush()
            os.fsync(stream.fileno())
        write_atomically(path, updated, original_stat)
        print("Candidate route configured; restart the tunnel only after approval")
    else:
        if backup.is_symlink() or not backup.is_file():
            raise FileNotFoundError("private route backup is missing")
        previous = backup.read_bytes()
        if current != replace_origin(previous, OLD, NEW):
            raise ValueError("tunnel config changed since cutover; refusing automatic rollback")
        validate(backup)
        write_atomically(path, previous, original_stat)
        print("Previous route configured; restart the tunnel to activate rollback")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"route switch stopped: {error}", file=sys.stderr)
        sys.exit(1)
