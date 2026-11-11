#!/usr/bin/env python3
"""Prepare an approval-only writable Rails env from the dedicated role secret."""

import os
from pathlib import Path
import re
import secrets
import stat
import sys
from urllib.parse import quote


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} ROLE_PASSWORD_FILE NEW_CUTOVER_ENV_FILE", file=sys.stderr)
        return 2
    credential, path = (Path(arg) for arg in sys.argv[1:])
    if not credential.is_file() or credential.is_symlink() or stat.S_IMODE(credential.stat().st_mode) != 0o600:
        print("role credential must be a non-symlink mode-0600 file", file=sys.stderr)
        return 1
    if path.exists() or path.is_symlink():
        print("cutover env already exists", file=sys.stderr)
        return 1
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        print("cutover env requires a mode-0700 parent directory", file=sys.stderr)
        return 1
    password = credential.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", password):
        print("invalid generated role credential", file=sys.stderr)
        return 1
    url = "postgresql://osm_rails_cutover_rw:" + quote(password, safe="") + "@db/openstreetmap"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(f"DATABASE_URL={url}\nSECRET_KEY_BASE={secrets.token_hex(64)}\n")
    print("Private cutover env created; use only after separate cutover approval")
    return 0


if __name__ == "__main__":
    sys.exit(main())
