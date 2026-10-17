"""Single-owner login. The password lives in VIDROT_PASSWORD, not in git."""
import hashlib
import os
import secrets
from http.cookies import SimpleCookie

from vidrot import db

COOKIE = "vidrot_session"
LOCKOUT_AFTER = 8
LOCKOUT_MESSAGE = "Too many tries. Wait 15 minutes, then try again."


def passwords_match(got, expected):
    got = got or ""
    expected = expected or ""
    if not expected:
        return False
    return secrets.compare_digest(
        hashlib.sha256(got.encode("utf-8")).digest(),
        hashlib.sha256(expected.encode("utf-8")).digest(),
    )


class Auth:
    def __init__(self, password, folder, secure=False):
        self.password = password or ""
        self.enabled = bool(self.password)
        self.folder = folder
        self.secure = bool(secure)

    @classmethod
    def from_env(cls, folder):
        secure = os.environ.get("VIDROT_SECURE", "").strip() in {"1", "true", "yes"}
        return cls(os.environ.get("VIDROT_PASSWORD", ""), folder, secure=secure)

    def login(self, password, ip, user_agent):
        if not self.enabled:
            return {"ok": True, "disabled": True}
        if db.recent_failures(self.folder, ip) >= LOCKOUT_AFTER:
            return {"ok": False, "error": LOCKOUT_MESSAGE}
        if not passwords_match(password, self.password):
            db.record_attempt(self.folder, ip, False)
            return {"ok": False, "error": "Wrong password."}
        db.record_attempt(self.folder, ip, True)
        token = secrets.token_urlsafe(32)
        db.create_session(self.folder, token, user_agent)
        return {"ok": True, "token": token}

    def valid(self, token):
        if not self.enabled:
            return True
        return db.session_valid(self.folder, token)

    def issue_session(self, ip, user_agent):
        if not self.enabled:
            return {"ok": True, "disabled": True}
        if db.recent_failures(self.folder, ip) >= LOCKOUT_AFTER:
            return {"ok": False, "error": LOCKOUT_MESSAGE}
        token = secrets.token_urlsafe(32)
        db.create_session(self.folder, token, user_agent)
        db.record_attempt(self.folder, ip, True)
        return {"ok": True, "token": token}

    def note_failure(self, ip):
        if self.enabled:
            db.record_attempt(self.folder, ip, False)

    def logout(self, token):
        db.delete_session(self.folder, token)


def read_cookie(header, name=COOKIE):
    if not header:
        return ""
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:
        return ""
    morsel = jar.get(name)
    return morsel.value if morsel else ""


def cookie_path():
    path = os.environ.get("VIDROT_COOKIE_PATH", "").strip() or "/"
    return path if path.startswith("/") else "/" + path


def cookie_header(token, secure):
    if not token:
        parts = [f"{COOKIE}=", f"Path={cookie_path()}", "Max-Age=0", "HttpOnly", "SameSite=Lax"]
    else:
        parts = [f"{COOKIE}={token}", f"Path={cookie_path()}", "Max-Age=1209600", "HttpOnly", "SameSite=Lax"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
