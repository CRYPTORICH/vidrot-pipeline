"""Instagram Reel upload using a saved instagrapi session.

A challenge or a 2FA prompt is returned to the phone. Nothing calls input().
The session is encrypted in the database. A plaintext session.json in the
data folder is imported once and then removed.
"""
import json
import os
from pathlib import Path

from vidrot.crypto import decrypt, encrypt
from vidrot.db import get_kv, put_kv

CHALLENGE = {
    "ChallengeRequired",
    "ChallengeError",
    "CaptchaChallengeRequired",
    "FeedbackRequired",
    "SentryBlock",
    "PleaseWaitFewMinutes",
}
SESSION_MARKERS = {"uuids", "authorization_data", "cookies", "device_settings", "mid"}


def session_file(folder):
    return Path(folder) / "session.json"


def session_saved(folder):
    if get_kv(folder, "ig_session", ""):
        return True
    return session_file(folder).exists()


def describe(settings, folder):
    return {
        "username": settings.get("ig_username") or "vidrot.ai",
        "password": bool(settings.get("ig_password")),
        "session_saved": session_saved(folder),
        "session_file": str(session_file(folder)) if session_file(folder).exists() else "",
        "ready": bool(settings.get("ig_password") or session_saved(folder)),
    }


def classify(exc):
    kind = type(exc).__name__
    if kind == "TwoFactorRequired":
        return {
            "ok": False,
            "needs_code": True,
            "challenge": False,
            "error": "Instagram wants the current 6-digit authenticator code. Enter it on your phone and try again.",
        }
    if kind in CHALLENGE or kind == "ChallengeRequired":
        return {
            "ok": False,
            "needs_code": True,
            "challenge": True,
            "error": (
                "Instagram is asking you to approve this login on your phone. "
                "If the Instagram app shows a prompt, approve it, then tap Try again. "
                "If it texted or emailed a code, enter that code here. "
                "A datacenter IP often causes this check. Settings has an optional proxy "
                "so the request can leave from an IP you control."
            ),
        }
    if kind == "BadPassword":
        return {
            "ok": False,
            "needs_code": False,
            "challenge": False,
            "error": "Instagram rejected the username or password.",
        }
    return {
        "ok": False,
        "needs_code": False,
        "challenge": False,
        "error": f"Instagram login failed ({kind}): {str(exc)[:220]}",
    }


def import_session(folder, payload):
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return {"ok": False, "error": "That file is not JSON."}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "The session file must be a JSON object."}
    if not SESSION_MARKERS.intersection(payload):
        return {"ok": False, "error": "That file does not look like an instagrapi session.json."}
    raw = json.dumps(payload)
    if len(raw) > 1_500_000:
        return {"ok": False, "error": "That session file is too large."}
    put_kv(folder, "ig_session", encrypt(folder, raw))
    path = session_file(folder)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    return {"ok": True, "error": ""}


def _absorb_plaintext(folder):
    path = session_file(folder)
    if not path.exists() or get_kv(folder, "ig_session", ""):
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(payload, dict) and SESSION_MARKERS.intersection(payload):
        import_session(folder, payload)


def _session_dict(folder):
    _absorb_plaintext(folder)
    raw = get_kv(folder, "ig_session", "")
    if not raw:
        return None
    try:
        payload = json.loads(decrypt(folder, raw))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _remember_client(folder, client):
    try:
        payload = client.get_settings()
    except Exception:
        return
    if isinstance(payload, dict):
        put_kv(folder, "ig_session", encrypt(folder, json.dumps(payload)))


def _client():
    try:
        from instagrapi import Client
    except ImportError:
        return None
    client = Client()
    client.delay_range = [3, 8]
    return client


def _apply_proxy(client, settings):
    proxy = (settings.get("ig_proxy") or "").strip()
    if not proxy:
        return None
    try:
        client.set_proxy(proxy)
    except Exception as exc:
        return f"The proxy setting was rejected: {exc}"
    return None


def login(settings, folder, verification_code="", client_factory=None):
    info = describe(settings, folder)
    if not info["ready"] and not verification_code:
        return {
            "ok": False,
            "needs_code": False,
            "challenge": False,
            "error": "Add an Instagram password in Settings, or import a session.json.",
        }
    factory = client_factory or _client
    client = factory()
    if client is None:
        return {
            "ok": False,
            "needs_code": False,
            "challenge": False,
            "error": "instagrapi is not installed in this server image.",
        }
    proxy_error = _apply_proxy(client, settings)
    if proxy_error:
        return {"ok": False, "needs_code": False, "challenge": False, "error": proxy_error}
    loaded = _session_dict(folder)
    if loaded:
        try:
            client.set_settings(loaded)
        except Exception:
            try:
                path = session_file(folder)
                path.write_text(json.dumps(loaded), encoding="utf-8")
                os.chmod(path, 0o600)
                client.load_settings(path)
            except Exception as exc:
                return classify(exc)
            finally:
                session_file(folder).unlink(missing_ok=True)
    username = settings.get("ig_username") or "vidrot.ai"
    password = settings.get("ig_password") or ""
    try:
        if password:
            client.login(username, password, verification_code=verification_code or "")
        elif loaded:
            client.get_timeline_feed()
        else:
            return {
                "ok": False,
                "needs_code": False,
                "challenge": False,
                "error": "No Instagram password or session file.",
            }
    except Exception as exc:
        return classify(exc)
    _remember_client(folder, client)
    return {"ok": True, "client": client, "error": "", "needs_code": False, "challenge": False}


def permalink(media):
    if media is None:
        return ""
    code = media.get("code") if isinstance(media, dict) else getattr(media, "code", "")
    code = str(code or "")
    return f"https://www.instagram.com/reel/{code}/" if code else ""


def upload(client, video, caption):
    try:
        media = client.clip_upload(str(video), caption)
    except Exception as exc:
        kind = type(exc).__name__
        if kind in CHALLENGE or kind in {"TwoFactorRequired", "BadPassword"}:
            return classify(exc)
        return {
            "ok": False,
            "needs_code": False,
            "challenge": kind in CHALLENGE,
            "error": f"Upload failed ({kind}): {str(exc)[:220]}",
        }
    url = permalink(media)
    if not url:
        return {"ok": False, "error": "Instagram returned no reel link.", "needs_code": False, "challenge": False}
    return {"ok": True, "url": url, "error": "", "needs_code": False, "challenge": False}


def post_reel(settings, folder, video, caption, verification_code="", client_factory=None, attempts=3, sleeper=None):
    import time
    sleep = sleeper or time.sleep
    logged = login(settings, folder, verification_code, client_factory=client_factory)
    if not logged.get("ok"):
        return logged
    last = {"ok": False, "error": "Upload did not run."}
    for attempt in range(attempts):
        last = upload(logged["client"], video, caption)
        if last.get("ok") or last.get("challenge") or last.get("needs_code"):
            return last
        if attempt < attempts - 1:
            sleep(0 if sleeper else 2 * (attempt + 1))
    return last
