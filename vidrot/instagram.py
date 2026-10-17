"""Instagram Reel upload using a saved instagrapi session.

A challenge or a 2FA prompt is returned to the console. Nothing calls input(),
so a scheduled run cannot hang on a hidden window.
"""
import json
from pathlib import Path

CHALLENGE = {
    "ChallengeRequired",
    "ChallengeError",
    "CaptchaChallengeRequired",
    "FeedbackRequired",
    "SentryBlock",
    "PleaseWaitFewMinutes",
}


def session_file(folder):
    return Path(folder) / "session.json"


def describe(settings, folder):
    path = session_file(folder)
    return {
        "username": settings.get("ig_username") or "vidrot.ai",
        "password": bool(settings.get("ig_password")),
        "session_file": str(path) if path.exists() else "",
        "ready": bool(settings.get("ig_password") or path.exists()),
    }


def classify(exc):
    kind = type(exc).__name__
    if kind == "TwoFactorRequired":
        return {
            "ok": False,
            "needs_code": True,
            "challenge": False,
            "error": "Instagram wants the current 6-digit authenticator code. Enter it and try again.",
        }
    if kind in CHALLENGE or kind == "ChallengeRequired":
        return {
            "ok": False,
            "needs_code": False,
            "challenge": True,
            "error": (
                "Instagram is asking you to approve this login on the phone or in a browser. "
                "Approve it, then try again. A datacenter IP usually cannot finish this prompt."
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


def _client():
    try:
        from instagrapi import Client
    except ImportError:
        return None
    client = Client()
    client.delay_range = [3, 8]
    return client


def login(settings, folder, verification_code="", client_factory=None):
    info = describe(settings, folder)
    if not info["ready"] and not verification_code:
        return {
            "ok": False,
            "needs_code": False,
            "challenge": False,
            "error": "Add an Instagram password in Settings, or place a session.json in the data folder.",
        }
    factory = client_factory or _client
    client = factory()
    if client is None:
        return {
            "ok": False,
            "needs_code": False,
            "challenge": False,
            "error": "instagrapi is not installed. On the PC run: py -3.11 -m pip install instagrapi",
        }
    path = session_file(folder)
    if path.exists():
        try:
            client.load_settings(path)
        except Exception as exc:
            return classify(exc)
    username = settings.get("ig_username") or "vidrot.ai"
    password = settings.get("ig_password") or ""
    try:
        if password:
            client.login(username, password, verification_code=verification_code or "")
        elif path.exists():
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
    try:
        client.dump_settings(path)
    except Exception:
        try:
            payload = client.get_settings()
            path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception:
            pass
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
        result = classify(exc) if kind in CHALLENGE or kind in {"TwoFactorRequired", "BadPassword"} else {
            "ok": False,
            "needs_code": False,
            "challenge": kind in CHALLENGE,
            "error": f"Upload failed ({kind}): {str(exc)[:220]}",
        }
        return result
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
