#!/usr/bin/env python3
"""Create a private, single-use Rails env file without echoing credentials."""

import getpass
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import quote


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} NEW_PRIVATE_ENV_FILE", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if path.is_symlink() or path.exists():
        print("private env file already exists", file=sys.stderr)
        return 1
    password = getpass.getpass("Existing Osaka database role password: ")
    if not password:
        print("empty database password refused", file=sys.stderr)
        return 1
    url = "postgresql://openstreetmap:" + quote(password, safe="") + "@db/openstreetmap"
    content = f"DATABASE_URL={url}\nSECRET_KEY_BASE={secrets.token_hex(64)}\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    print("Private environment file created; keep it outside Git and delete after rollback window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
