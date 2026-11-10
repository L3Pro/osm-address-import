#!/usr/bin/env python3
"""Prepare a separate, approval-only writable cutover Rails environment."""

import getpass
import os
from pathlib import Path
import secrets
import stat
import sys
from urllib.parse import quote


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} NEW_CUTOVER_ENV_FILE", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if path.exists() or path.is_symlink():
        print("cutover env already exists", file=sys.stderr)
        return 1
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        print("cutover env requires a mode-0700 parent directory", file=sys.stderr)
        return 1
    password = getpass.getpass("Existing Osaka database role password (cutover approval only): ")
    if not password:
        print("empty database password refused", file=sys.stderr)
        return 1
    url = "postgresql://openstreetmap:" + quote(password, safe="") + "@db/openstreetmap"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(f"DATABASE_URL={url}\nSECRET_KEY_BASE={secrets.token_hex(64)}\n")
    print("Private cutover env created; use only after separate cutover approval")
    return 0


if __name__ == "__main__":
    sys.exit(main())
