"""Settings on the data volume. Secrets are encrypted. Env vars win."""
import copy
import json
import os
import re
from zoneinfo import ZoneInfo

from vidrot.crypto import decrypt, encrypt
from vidrot.db import get_kv, put_kv
from vidrot.store import data_dir, read_json

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SECRET_FIELDS = ("gemini_api_key", "ig_password", "ig_proxy")

DEFAULTS = {
    "gemini_api_key": "",
    "veo_model": "veo-3.1-fast-generate-preview",
    "veo_duration_seconds": 8,
    "ig_username": "vidrot.ai",
    "ig_password": "",
    "ig_proxy": "",
    "openclaw_enabled": False,
    "openclaw_url": "",
    "trends_geo": "US",
    "batch_size": 5,
    "ffmpeg_path": "",
    "dry_run": True,
    "timezone": "America/New_York",
    "schedule": {
        "batch_enabled": False,
        "batch_time": "09:00",
        "post_enabled": False,
        "post_time": "12:00",
        "weekdays": [0, 1, 2, 3, 4, 5],
    },
}


def mask(secret):
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return "••••" + secret[-4:]


def _timezone(value):
    name = (value or "").strip() or DEFAULTS["timezone"]
    try:
        ZoneInfo(name)
    except Exception:
        return DEFAULTS["timezone"]
    return name


def _apply_env(merged):
    if os.environ.get("GEMINI_API_KEY", "").strip():
        merged["gemini_api_key"] = os.environ["GEMINI_API_KEY"].strip()
    if os.environ.get("GOOGLE_API_KEY", "").strip() and not merged["gemini_api_key"]:
        merged["gemini_api_key"] = os.environ["GOOGLE_API_KEY"].strip()
    if os.environ.get("IG_USERNAME", "").strip():
        merged["ig_username"] = os.environ["IG_USERNAME"].strip()
    if os.environ.get("IG_PASSWORD", "").strip():
        merged["ig_password"] = os.environ["IG_PASSWORD"].strip()
    if os.environ.get("IG_PROXY", "").strip():
        merged["ig_proxy"] = os.environ["IG_PROXY"].strip()
    if os.environ.get("VIDROT_TZ", "").strip():
        merged["timezone"] = _timezone(os.environ["VIDROT_TZ"])
    return merged


def _decode_stored(folder, saved):
    decoded = {}
    for key, value in saved.items():
        if key in SECRET_FIELDS and isinstance(value, str):
            decoded[key] = decrypt(folder, value)
        else:
            decoded[key] = value
    return decoded


def _read_stored(folder):
    raw = get_kv(folder, "settings", None)
    if raw:
        try:
            saved = json.loads(raw)
        except json.JSONDecodeError:
            saved = {}
        if isinstance(saved, dict):
            return _decode_stored(folder, saved)
    legacy = read_json(folder / "settings.json", None)
    if isinstance(legacy, dict):
        return legacy
    return {}


def load(folder=None):
    folder = folder or data_dir()
    saved = _read_stored(folder)
    merged = copy.deepcopy(DEFAULTS)
    for key, value in saved.items():
        if key == "schedule" and isinstance(value, dict):
            merged["schedule"].update(value)
        elif key in merged and key != "schedule":
            merged[key] = value
    merged["schedule"]["weekdays"] = _weekdays(merged["schedule"].get("weekdays"))
    if not TIME_RE.match(str(merged["schedule"].get("batch_time", ""))):
        merged["schedule"]["batch_time"] = "09:00"
    if not TIME_RE.match(str(merged["schedule"].get("post_time", ""))):
        merged["schedule"]["post_time"] = "12:00"
    try:
        merged["batch_size"] = min(8, max(1, int(merged["batch_size"])))
    except (TypeError, ValueError):
        merged["batch_size"] = 5
    if int(merged.get("veo_duration_seconds") or 0) not in (4, 6, 8):
        merged["veo_duration_seconds"] = 8
    merged["openclaw_enabled"] = bool(merged.get("openclaw_enabled"))
    merged["dry_run"] = bool(merged.get("dry_run"))
    merged["timezone"] = _timezone(merged.get("timezone"))
    return _apply_env(merged)


def _weekdays(value):
    days = []
    for item in value or []:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in days:
            days.append(day)
    return days or [0, 1, 2, 3, 4, 5]


def public_view(settings, folder):
    from vidrot.instagram import session_saved
    from vidrot.push import configured as push_configured

    return {
        "veo_model": settings["veo_model"],
        "veo_duration_seconds": settings["veo_duration_seconds"],
        "ig_username": settings["ig_username"],
        "openclaw_enabled": bool(settings.get("openclaw_enabled")),
        "openclaw_url": settings.get("openclaw_url") or "",
        "trends_geo": settings["trends_geo"],
        "batch_size": settings["batch_size"],
        "ffmpeg_path": settings["ffmpeg_path"],
        "dry_run": bool(settings["dry_run"]),
        "timezone": settings.get("timezone") or DEFAULTS["timezone"],
        "schedule": settings["schedule"],
        "gemini_api_key_set": bool(settings["gemini_api_key"]),
        "gemini_api_key_mask": mask(settings["gemini_api_key"]),
        "ig_password_set": bool(settings["ig_password"]),
        "ig_proxy_set": bool(settings.get("ig_proxy")),
        "ig_proxy_mask": mask(settings.get("ig_proxy") or ""),
        "session_saved": session_saved(folder),
        "push_configured": push_configured(),
        "data_dir": str(folder),
    }


def _store(folder, current):
    stored = {}
    for key, value in current.items():
        if key in SECRET_FIELDS:
            stored[key] = encrypt(folder, value) if value else ""
        else:
            stored[key] = value
    put_kv(folder, "settings", json.dumps(stored))


def save(updates, folder=None):
    folder = folder or data_dir()
    current = load(folder)
    # Env-provided secrets stay in the environment. A blank UI field must not
    # wipe them, and saving the masked preview must not replace them.
    env_locked = set()
    if os.environ.get("GEMINI_API_KEY", "").strip() or (
        os.environ.get("GOOGLE_API_KEY", "").strip() and not updates.get("gemini_api_key")
    ):
        if os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip():
            env_locked.add("gemini_api_key")
    if os.environ.get("IG_PASSWORD", "").strip():
        env_locked.add("ig_password")
    if os.environ.get("IG_PROXY", "").strip():
        env_locked.add("ig_proxy")
    updates = updates or {}
    for key, value in updates.items():
        if key == "schedule" and isinstance(value, dict):
            proposed = dict(current["schedule"])
            proposed.update(value)
            if "batch_time" in value and not TIME_RE.match(str(value["batch_time"])):
                return None, "Batch time must look like 09:00"
            if "post_time" in value and not TIME_RE.match(str(value["post_time"])):
                return None, "Post time must look like 12:00"
            if "weekdays" in value:
                proposed["weekdays"] = _weekdays(value["weekdays"])
            current["schedule"] = proposed
            continue
        if key not in current or key == "schedule":
            continue
        if key in env_locked:
            continue
        if isinstance(value, str) and value.startswith("••••"):
            continue
        if key in SECRET_FIELDS and value == "":
            continue
        if key == "batch_size":
            value = min(8, max(1, int(value)))
        if key == "veo_duration_seconds":
            value = int(value)
            if value not in (4, 6, 8):
                return None, "Veo duration must be 4, 6, or 8 seconds"
        if key in ("dry_run", "openclaw_enabled"):
            value = bool(value)
        if key == "timezone":
            value = _timezone(value)
        current[key] = value
    persisted = copy.deepcopy(current)
    # Don't write env-only secrets into the database. They stay in the host.
    for key in env_locked:
        stored_only = _decode_stored(folder, json.loads(get_kv(folder, "settings", "{}") or "{}"))
        persisted[key] = stored_only.get(key, "")
    _store(folder, persisted)
    return public_view(load(folder), folder), ""
