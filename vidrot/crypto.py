"""Encrypt secrets at rest. The key comes from VIDROT_SECRET_KEY on a host.

On a laptop with no env key, a key file is created inside the data directory
so settings are still not stored in the clear. A public bind refuses to
start without VIDROT_SECRET_KEY, so the cloud key is not sitting next to
the database on the only copy of the disk.
"""
import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"


def secret_material(folder):
    env = os.environ.get("VIDROT_SECRET_KEY", "").strip()
    if env:
        return env
    path = Path(folder) / ".secret_key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_text(encoding="utf-8").strip()


def _fernet(folder):
    digest = hashlib.sha256(secret_material(folder).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(folder, text):
    if not text:
        return ""
    token = _fernet(folder).encrypt(str(text).encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt(folder, text):
    if not text:
        return ""
    if not str(text).startswith(PREFIX):
        return str(text)
    try:
        raw = _fernet(folder).decrypt(str(text)[len(PREFIX):].encode("ascii"))
    except (InvalidToken, ValueError):
        return ""
    return raw.decode("utf-8")


def require_env_key():
    if not os.environ.get("VIDROT_SECRET_KEY", "").strip():
        raise SystemExit("VIDROT_SECRET_KEY is required when the server is reachable beyond this machine.")
