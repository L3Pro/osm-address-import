#!/usr/bin/env python3
"""Generate one private password for the approval-only writable Rails role."""

import os
from pathlib import Path
import secrets
import stat
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} NEW_ROLE_PASSWORD_FILE", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if path.exists() or path.is_symlink():
        print("role credential already exists", file=sys.stderr)
        return 1
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        print("role credential requires a mode-0700 parent directory", file=sys.stderr)
        return 1
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(secrets.token_urlsafe(32) + "\n")
    print("Private writable role credential created; keep outside Git")
    return 0


if __name__ == "__main__":
    sys.exit(main())
