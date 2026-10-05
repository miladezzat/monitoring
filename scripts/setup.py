#!/usr/bin/env python3
"""Create local credentials without overwriting an existing environment."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    path = ROOT / ".env"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env already exists; kept existing credentials.")
    content = (ROOT / ".env.example").read_text().replace(
        "GRAFANA_ADMIN_PASSWORD=\n", "GRAFANA_ADMIN_PASSWORD=" + secrets.token_urlsafe(32) + "\n"
    )
    with os.fdopen(fd, "w") as file:
        file.write(content)
    print("Created .env with a random password and mode 0600. Read it locally to sign in.")
