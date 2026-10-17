"""In-process clock. Replaces the Windows tasks that flashed a console window."""
import threading
from datetime import datetime, timedelta

from vidrot.store import read_json, write_json


def is_due(now, hhmm, enabled, weekdays, last_date, grace_minutes=10):
    if not enabled:
        return False
    if now.weekday() not in set(weekdays or []):
        return False
    if last_date == now.date().isoformat():
        return False
    try:
        hour, minute = [int(part) for part in hhmm.split(":", 1)]
    except (ValueError, AttributeError):
        return False
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (now - target).total_seconds()
    return 0 <= delta <= grace_minutes * 60


def next_fire(now, hhmm, enabled, weekdays):
    if not enabled or not weekdays:
        return None
    try:
        hour, minute = [int(part) for part in hhmm.split(":", 1)]
    except (ValueError, AttributeError):
        return None
    for offset in range(8):
        day = now + timedelta(days=offset)
        if day.weekday() not in set(weekdays):
            continue
        candidate = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate > now:
            return candidate.isoformat(timespec="minutes")
    return None


class Scheduler:
    def __init__(self, engine, interval=15):
        self.engine = engine
        self.interval = interval
        self.stop = threading.Event()
        self.thread = None

    def state_path(self):
        return self.engine.folder / "scheduler_state.json"

    def load_state(self):
        return read_json(self.state_path(), {"last_batch_date": "", "last_post_date": ""})

    def tick(self, now=None):
        now = now or datetime.now()
        settings = self.engine.settings()
        sched = settings["schedule"]
        state = self.load_state()
        changed = False
        if is_due(
            now,
            sched["batch_time"],
            sched["batch_enabled"],
            sched["weekdays"],
            state.get("last_batch_date", ""),
        ):
            state["last_batch_date"] = now.date().isoformat()
            write_json(self.state_path(), state)
            changed = True
            self.engine.run_morning()
            state = self.load_state()
        if is_due(
            now,
            sched["post_time"],
            sched["post_enabled"],
            sched["weekdays"],
            state.get("last_post_date", ""),
        ):
            state["last_post_date"] = now.date().isoformat()
            write_json(self.state_path(), state)
            changed = True
            self.engine.post_latest()
        return changed

    def summary(self, now=None):
        now = now or datetime.now()
        settings = self.engine.settings()
        sched = settings["schedule"]
        state = self.load_state()
        return {
            "batch_enabled": bool(sched["batch_enabled"]),
            "batch_time": sched["batch_time"],
            "post_enabled": bool(sched["post_enabled"]),
            "post_time": sched["post_time"],
            "weekdays": sched["weekdays"],
            "last_batch_date": state.get("last_batch_date") or "",
            "last_post_date": state.get("last_post_date") or "",
            "next_batch": next_fire(now, sched["batch_time"], sched["batch_enabled"], sched["weekdays"]),
            "next_post": next_fire(now, sched["post_time"], sched["post_enabled"], sched["weekdays"]),
            "running": bool(self.thread and self.thread.is_alive()),
        }

    def loop(self):
        while not self.stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:
                self.engine.log(f"Scheduler error: {exc}")

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()
        self.thread = threading.Thread(target=self.loop, name="vidrot-scheduler", daemon=True)
        self.thread.start()
