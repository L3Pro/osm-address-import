#!/usr/bin/env python3
"""Create separate, private preflight Rails and PostgreSQL credentials."""

import os
from pathlib import Path
import secrets
import stat
import sys
from urllib.parse import quote


ROLE = "osm_rails_preflight_ro"


def create_private_file(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} NEW_PREFLIGHT_ENV_FILE NEW_ROLE_PASSWORD_FILE", file=sys.stderr)
        return 2
    env_path, password_path = (Path(arg) for arg in sys.argv[1:])
    if env_path == password_path or any(path.exists() or path.is_symlink() for path in (env_path, password_path)):
        print("private output already exists or paths overlap", file=sys.stderr)
        return 1
    if any(path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077 for path in (env_path, password_path)):
        print("private outputs require mode-0700 parent directories", file=sys.stderr)
        return 1
    password = secrets.token_urlsafe(32)
    url = f"postgresql://{ROLE}:{quote(password, safe='')}@db/openstreetmap"
    created_password = False
    try:
        create_private_file(password_path, password + "\n")
        created_password = True
        create_private_file(env_path, f"DATABASE_URL={url}\nSECRET_KEY_BASE={secrets.token_hex(64)}\n")
    except Exception:
        if created_password:
            password_path.unlink(missing_ok=True)
        raise
    print("Private preflight credential and Rails env created; keep both outside Git")
    return 0


if __name__ == "__main__":
    sys.exit(main())
