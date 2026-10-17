"""Status cards for the console. Network checks are short and optional."""
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from vidrot.brand import ffmpeg_bin
from vidrot.instagram import describe as describe_instagram
from vidrot.veo import VeoClient


def _probe(url, timeout=3):
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"Gateway responded ({resp.status})."
    except urllib.error.HTTPError as exc:
        return True, f"Gateway responded ({exc.code})."
    except Exception as exc:
        reason = getattr(exc, "reason", None) or exc
        return False, f"Not reachable: {reason}"


def collect(settings, folder, run=None, veo_check=True):
    folder = Path(folder)
    veo = VeoClient(
        settings.get("gemini_api_key", ""),
        settings.get("veo_model", ""),
        settings.get("veo_duration_seconds", 8),
    )
    if not veo_check:
        veo_card = {
            "ok": bool(settings.get("gemini_api_key")),
            "detail": "Key saved." if settings.get("gemini_api_key") else "No Gemini API key saved yet.",
        }
    else:
        try:
            checked = veo.check()
            veo_card = {"ok": checked["ok"], "detail": checked["detail"]}
        except Exception as exc:
            veo_card = {"ok": False, "detail": f"Could not reach Google: {exc}"}

    ig = describe_instagram(settings, folder)
    if ig["session_saved"]:
        name = ig.get("username") or "the account"
        ig_detail = f"Connected as {name}. Health does not log in on every refresh."
        ig_ok = True
    elif ig["password"]:
        ig_detail = "Password saved, not connected yet. Open Instagram and tap Connect."
        ig_ok = False
    else:
        ig_detail = "Not connected. Open Instagram and sign in."
        ig_ok = False

    binary = ffmpeg_bin(settings.get("ffmpeg_path") or "")
    if binary:
        ff_card = {"ok": True, "detail": binary}
    else:
        ff_card = {"ok": False, "detail": "ffmpeg was not found. Install it and restart the app."}

    try:
        usage = shutil.disk_usage(folder)
        free_gb = usage.free / (1024 ** 3)
        disk = {
            "ok": free_gb >= 1,
            "detail": f"{free_gb:.1f} GB free",
        }
    except OSError as exc:
        disk = {"ok": False, "detail": str(exc)}

    if settings.get("openclaw_enabled") and settings.get("openclaw_url"):
        up, detail = _probe(settings["openclaw_url"])
        openclaw = {
            "ok": up,
            "detail": detail + " Clips still use the Veo API. This check is optional.",
        }
    else:
        openclaw = {
            "ok": True,
            "detail": "Off. The PC does not need to be on. Clips use the Veo API directly.",
        }

    last = None
    if run:
        last = {
            "id": run.get("id"),
            "phase": run.get("phase"),
            "error": run.get("error") or "",
            "dry_run": run.get("dry_run"),
            "updated_at": run.get("updated_at"),
        }

    clips = list((folder / "clips").glob("*.mp4"))
    reels = list((folder / "reels").glob("*.mp4"))
    return {
        "veo": veo_card,
        "instagram": {"ok": ig_ok, "detail": ig_detail},
        "openclaw": openclaw,
        "ffmpeg": ff_card,
        "disk": disk,
        "output": {
            "ok": True,
            "detail": f"{len(clips)} clip(s), {len(reels)} reel(s) in the data folder.",
        },
        "last_run": last,
    }
