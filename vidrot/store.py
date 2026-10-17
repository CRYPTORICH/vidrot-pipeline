"""Local data directory. Settings, sessions, and clips live here, never in git."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def data_dir():
    override = os.environ.get("VIDROT_DATA", "").strip()
    if override:
        path = Path(override)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / "vidrot"
    else:
        path = Path.home() / ".vidrot"
    path.mkdir(parents=True, exist_ok=True)
    for name in ("clips", "reels", "posters", "logs", "bumpers", "runs"):
        (path / name).mkdir(exist_ok=True)
    return path


def read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Logger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message):
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {message}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return line

    def tail(self, limit=200):
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-limit:]
