"""Settings stored only in the local data directory."""
import copy
import re

from vidrot.store import data_dir, read_json, write_json

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

DEFAULTS = {
    "gemini_api_key": "",
    "veo_model": "veo-3.1-fast-generate-preview",
    "veo_duration_seconds": 8,
    "ig_username": "vidrot.ai",
    "ig_password": "",
    "openclaw_url": "http://127.0.0.1:18790",
    "trends_geo": "US",
    "batch_size": 5,
    "ffmpeg_path": "",
    "dry_run": True,
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


def load(folder=None):
    folder = folder or data_dir()
    saved = read_json(folder / "settings.json", {})
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
    return merged


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
    return {
        "veo_model": settings["veo_model"],
        "veo_duration_seconds": settings["veo_duration_seconds"],
        "ig_username": settings["ig_username"],
        "openclaw_url": settings["openclaw_url"],
        "trends_geo": settings["trends_geo"],
        "batch_size": settings["batch_size"],
        "ffmpeg_path": settings["ffmpeg_path"],
        "dry_run": bool(settings["dry_run"]),
        "schedule": settings["schedule"],
        "gemini_api_key_set": bool(settings["gemini_api_key"]),
        "gemini_api_key_mask": mask(settings["gemini_api_key"]),
        "ig_password_set": bool(settings["ig_password"]),
        "data_dir": str(folder),
    }


def save(updates, folder=None):
    folder = folder or data_dir()
    current = load(folder)
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
        if isinstance(value, str) and value.startswith("••••"):
            continue
        if key in ("gemini_api_key", "ig_password") and value == "":
            continue
        if key == "batch_size":
            value = min(8, max(1, int(value)))
        if key == "veo_duration_seconds":
            value = int(value)
            if value not in (4, 6, 8):
                return None, "Veo duration must be 4, 6, or 8 seconds"
        if key == "dry_run":
            value = bool(value)
        current[key] = value
    secret = {
        "gemini_api_key": current["gemini_api_key"],
        "veo_model": current["veo_model"],
        "veo_duration_seconds": current["veo_duration_seconds"],
        "ig_username": current["ig_username"],
        "ig_password": current["ig_password"],
        "openclaw_url": current["openclaw_url"],
        "trends_geo": current["trends_geo"],
        "batch_size": current["batch_size"],
        "ffmpeg_path": current["ffmpeg_path"],
        "dry_run": current["dry_run"],
        "schedule": current["schedule"],
    }
    write_json(folder / "settings.json", secret)
    return public_view(current, folder), ""
