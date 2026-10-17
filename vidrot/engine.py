"""The daily loop: trends, editable prompts, Veo, brand, post.

A run is one JSON document. The console polls it. Failures are stored on the
run and shown in the UI; they do not kill the process.
"""
import threading
import time
from datetime import datetime
from pathlib import Path

from vidrot import brand, prompts as promptlib
from vidrot.instagram import post_reel
from vidrot import db as statedb
from vidrot.settings import load as load_settings
from vidrot.store import data_dir, now_iso, write_json, Logger
from vidrot.trends import collect_trends
from vidrot.veo import VeoClient


def _empty_run():
    return None


class Engine:
    def __init__(self, folder=None, settings_fn=None, veo_factory=None, trends_fn=None,
                 card_writer=None, stitcher=None, normalizer=None, poster_fn=None,
                 poster=None, poll_interval=5, poll_timeout=600, sleep=None):
        self.folder = Path(folder) if folder else data_dir()
        for name in ("clips", "reels", "posters", "logs", "bumpers", "runs"):
            (self.folder / name).mkdir(parents=True, exist_ok=True)
        self.settings_fn = settings_fn or (lambda: load_settings(self.folder))
        self.veo_factory = veo_factory or self._default_veo
        self.trends_fn = trends_fn or (lambda: collect_trends(self.folder, self.settings().get("trends_geo", "US")))
        self.card_writer = card_writer or (lambda dest, line: brand.write_title_card(dest, line, self.settings().get("ffmpeg_path", "")))
        self.stitcher = stitcher or (lambda clips, dest, bumper=None: brand.stitch(clips, dest, bumper, self.settings().get("ffmpeg_path", "")))
        self.normalizer = normalizer or (lambda src, dest, label: brand.normalize_clip(src, dest, label, self.settings().get("ffmpeg_path", "")))
        self.poster_fn = poster_fn or (lambda src, dest: brand.write_poster(src, dest, self.settings().get("ffmpeg_path", "")))
        self.poster = poster or post_reel
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self.sleep = sleep or time.sleep
        self.lock = threading.Lock()
        self._running = False
        self.logger = Logger(self.folder / "logs" / "console.log")
        self.run = statedb.load_run(self.folder)
        self.history = statedb.load_history(self.folder)
        self._worker = None

    def settings(self):
        return self.settings_fn()

    def _default_veo(self):
        cfg = self.settings()
        return VeoClient(cfg.get("gemini_api_key", ""), cfg.get("veo_model"), cfg.get("veo_duration_seconds", 8))

    def log(self, message):
        line = self.logger.write(message)
        with self.lock:
            if self.run is not None:
                self.run.setdefault("log", []).append(line)
                self.run["log"] = self.run["log"][-80:]
                self.run["updated_at"] = now_iso()
                self._save_locked()
        return line

    def _save_locked(self):
        statedb.save_run(self.folder, self.run)

    def snapshot(self):
        with self.lock:
            return None if self.run is None else json_copy(self.run)

    def busy(self):
        with self.lock:
            return self._running

    def _claim(self):
        with self.lock:
            if self._running:
                return False
            self._running = True
            return True

    def _release(self):
        with self.lock:
            self._running = False

    def new_batch(self, dry_run=None):
        cfg = self.settings()
        dry = cfg["dry_run"] if dry_run is None else bool(dry_run)
        try:
            topics, note = self.trends_fn()
        except Exception as exc:
            topics, note = ["a signal from nowhere"], f"Trends failed: {exc}"
        count = int(cfg.get("batch_size") or 5)
        batch = promptlib.generate_batch(topics, count=count)
        run = {
            "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "phase": "review",
            "dry_run": dry,
            "trends": topics,
            "trends_note": note or "",
            "prompts": batch,
            "reel": "",
            "poster": "",
            "error": "",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "log": [],
        }
        with self.lock:
            if self.run and self.run.get("id"):
                write_json(self.folder / "runs" / f"{self.run['id']}.json", self.run)
            self.run = run
            self._save_locked()
        self.log(f"New batch {run['id']} ({'dry run' if dry else 'live'}). {len(batch)} prompts.")
        if note:
            self.log(note)
        return {"ok": True, "run": self.snapshot()}

    def save_prompts(self, edits):
        with self.lock:
            if not self.run:
                return {"ok": False, "error": "There is no batch to edit."}
            if self.run["phase"] in ("rendering", "branding", "posting"):
                return {"ok": False, "error": "Wait until the current step finishes before editing."}
            self.run["prompts"] = promptlib.apply_edits(self.run["prompts"], edits)
            self.run["updated_at"] = now_iso()
            self._save_locked()
        self.log("Saved prompt edits.")
        return {"ok": True, "run": self.snapshot()}

    def regenerate(self, prompt_id):
        replaced = False
        with self.lock:
            if not self.run:
                return {"ok": False, "error": "There is no batch."}
            prompts = self.run["prompts"]
            trends = self.run.get("trends") or ["a signal from nowhere"]
            for index, prompt in enumerate(prompts):
                if prompt.get("id") == prompt_id:
                    fresh = promptlib.generate_one(prompt.get("trend") or trends[0], promptlib.load_banks(), __import__("random"))
                    fresh["id"] = prompt_id
                    prompts[index] = fresh
                    self.run["updated_at"] = now_iso()
                    self._save_locked()
                    replaced = True
                    break
        if not replaced:
            return {"ok": False, "error": "That prompt is not in this batch."}
        # Log after releasing the lock. log() takes the same lock.
        self.log(f"Regenerated {prompt_id}.")
        return {"ok": True, "run": self.snapshot()}

    def start_render(self):
        if not self._claim():
            return {"ok": False, "error": "A job is already running."}
        with self.lock:
            if not self.run or not self.run.get("prompts"):
                self._running = False
                return {"ok": False, "error": "Generate a batch before rendering."}
            if self.run["phase"] not in ("review", "error", "ready", "clips_ready"):
                self._running = False
                return {"ok": False, "error": f"Cannot render during {self.run['phase']}."}
            self.run["phase"] = "rendering"
            self.run["error"] = ""
            self._save_locked()
        self._worker = threading.Thread(target=self._render_and_release, name="vidrot-render", daemon=True)
        self._worker.start()
        return {"ok": True}

    def _render_and_release(self):
        try:
            self._render_safe()
        finally:
            self._release()

    def render(self):
        """Synchronous render used by tests and the morning schedule."""
        if not self._claim():
            return {"ok": False, "error": "A job is already running."}
        try:
            self._render_safe()
        finally:
            self._release()
        snap = self.snapshot()
        return {"ok": snap["phase"] != "error", "run": snap}

    def _render_safe(self):
        try:
            self._render()
        except Exception as exc:
            self._fail(f"Render crashed: {exc}")

    def _render(self):
        with self.lock:
            if not self.run or not self.run.get("prompts"):
                self._fail_locked("Generate a batch before rendering.")
                return
            self.run["phase"] = "rendering"
            self.run["error"] = ""
            self._save_locked()
        run = self.snapshot()
        dry = run["dry_run"]
        veo = None if dry else self.veo_factory()
        if not dry and not self.settings().get("gemini_api_key"):
            self._fail("Add a Gemini API key in Settings before rendering clips.")
            return
        ready = 0
        for index, prompt in enumerate(run["prompts"]):
            self._set_prompt(index, status="rendering", error="")
            self.log(f"Rendering {prompt['channel']} ({index + 1}/{len(run['prompts'])}).")
            dest = self.folder / "clips" / f"{run['id']}_{index:03d}.mp4"
            if dry:
                result = self.card_writer(dest, prompt["channel"].replace("_", " "))
            else:
                result = self._veo_clip(veo, prompt["prompt"], dest)
            if result.get("ok"):
                poster = self.folder / "posters" / f"{dest.stem}.png"
                try:
                    self.poster_fn(dest, poster)
                except Exception as exc:
                    self.log(f"Poster skipped: {exc}")
                self._set_prompt(index, status="ready", clip=dest.name, error="")
                ready += 1
            else:
                self._set_prompt(index, status="failed", error=result.get("error") or "Render failed")
                self.log(f"{prompt['channel']} failed: {result.get('error')}")
        if ready == 0:
            self._fail("Every clip failed. See each card for the reason.")
            return
        note = "" if ready == len(run["prompts"]) else (
            f"{ready} of {len(run['prompts'])} clips are ready. Failed ones can be regenerated."
        )
        with self.lock:
            self.run["phase"] = "clips_ready"
            self.run["error"] = note
            self.run["updated_at"] = now_iso()
            self._save_locked()
        self.log(f"{ready} clip(s) ready.")
        self._ping("vidrot clips ready", f"{ready} clip(s) are ready to stitch.")

    def _veo_clip(self, veo, text, dest):
        submitted = {"ok": False, "error": "Veo was not called."}
        for attempt in range(3):
            try:
                submitted = veo.submit(text)
            except Exception as exc:
                submitted = {"ok": False, "error": str(exc)}
            if submitted.get("ok"):
                break
            self.log(f"Veo submit failed ({attempt + 1}/3): {submitted.get('error')}")
            if attempt < 2:
                self.sleep(self.poll_interval)
        if not submitted.get("ok"):
            return submitted
        operation = submitted["operation"]
        self.log(f"Veo operation {operation}")
        deadline = time.monotonic() + self.poll_timeout
        while True:
            try:
                status = veo.poll(operation)
            except Exception as exc:
                status = {"done": False, "ok": False, "error": str(exc)}
            if status.get("done"):
                if not status.get("ok"):
                    return {"ok": False, "error": status.get("error") or "Veo failed"}
                try:
                    return veo.download(status["video_uri"], dest)
                except Exception as exc:
                    return {"ok": False, "error": f"Download failed: {exc}"}
            if time.monotonic() > deadline:
                return {"ok": False, "error": "Veo was still running when the wait timed out. Try this clip again."}
            self.sleep(self.poll_interval)

    def start_brand(self):
        if not self._claim():
            return {"ok": False, "error": "A job is already running."}
        with self.lock:
            if not self.run:
                self._running = False
                return {"ok": False, "error": "There is no batch."}
            ready = [p for p in self.run["prompts"] if p.get("status") == "ready" and p.get("clip")]
            if not ready:
                self._running = False
                return {"ok": False, "error": "Render at least one clip before stitching."}
            self.run["phase"] = "branding"
            self.run["error"] = ""
            self._save_locked()
        self._worker = threading.Thread(target=self._brand_and_release, name="vidrot-brand", daemon=True)
        self._worker.start()
        return {"ok": True}

    def _brand_and_release(self):
        try:
            self._brand_safe()
        finally:
            self._release()

    def _brand_safe(self):
        try:
            self._brand()
        except Exception as exc:
            self._fail(f"Branding crashed: {exc}")

    def _brand(self):
        run = self.snapshot()
        normalized = []
        work = self.folder / "clips" / "normalized"
        work.mkdir(parents=True, exist_ok=True)
        for prompt in run["prompts"]:
            if prompt.get("status") != "ready" or not prompt.get("clip"):
                continue
            src = self.folder / "clips" / prompt["clip"]
            dest = work / prompt["clip"]
            label = prompt["channel"].replace("_", " ")
            result = self.normalizer(src, dest, label)
            if not result.get("ok"):
                self.log(f"Normalize failed for {prompt['channel']}: {result.get('error')}")
                continue
            normalized.append(str(dest))
        if not normalized:
            self._fail("Branding had no usable clips.")
            return
        bumper = self._bumper()
        reel = self.folder / "reels" / f"{run['id']}.mp4"
        result = self.stitcher(normalized, reel, bumper)
        if not result.get("ok"):
            self._fail(result.get("error") or "Stitch failed")
            return
        poster = self.folder / "posters" / f"{run['id']}.png"
        try:
            self.poster_fn(reel, poster)
        except Exception as exc:
            self.log(f"Reel poster skipped: {exc}")
        with self.lock:
            self.run["reel"] = reel.name
            self.run["poster"] = poster.name if poster.exists() else ""
            self.run["phase"] = "ready"
            self.run["error"] = ""
            self.run["updated_at"] = now_iso()
            self._save_locked()
        self.log(f"Reel ready: {reel.name}")
        self._ping("vidrot reel ready", "The reel is ready to preview.")

    def _bumper(self):
        bumpers = sorted((self.folder / "bumpers").glob("*.mp4"))
        return str(bumpers[0]) if bumpers else None

    def post(self, caption="", verification_code=""):
        if self.busy():
            return {"ok": False, "error": "Wait for the current job to finish."}
        run = self.snapshot()
        if not run or not run.get("reel"):
            return {"ok": False, "error": "Brand a reel before posting."}
        if run["dry_run"]:
            entry = self._history({
                "ok": True,
                "dry_run": True,
                "url": "",
                "error": "",
                "caption": caption or self._default_caption(run),
                "file": run["reel"],
            })
            with self.lock:
                self.run["phase"] = "posted"
                self.run["error"] = ""
                self._save_locked()
            self.log("Dry run: nothing was sent to Instagram.")
            self._ping("vidrot dry run", "Nothing was sent to Instagram.")
            return {"ok": True, "dry_run": True, "history": entry}
        video = self.folder / "reels" / run["reel"]
        text = caption.strip() or self._default_caption(run)
        with self.lock:
            self.run["phase"] = "posting"
            self._save_locked()
        try:
            result = self.poster(
                self.settings(),
                self.folder,
                video,
                text,
                verification_code=verification_code,
                sleeper=lambda _seconds: None,
            )
        except Exception as exc:
            result = {"ok": False, "error": f"Post crashed: {exc}"}
        if result.get("ok"):
            self._history({
                "ok": True,
                "dry_run": False,
                "url": result.get("url") or "",
                "error": "",
                "caption": text,
                "file": run["reel"],
            })
            with self.lock:
                self.run["phase"] = "posted"
                self.run["error"] = ""
                self._save_locked()
            self.log(f"Posted {result.get('url') or run['reel']}")
            self._ping("vidrot posted", result.get("url") or "The reel was posted.")
            return {"ok": True, "url": result.get("url") or ""}
        with self.lock:
            self.run["phase"] = "ready"
            self.run["error"] = result.get("error") or "Post failed"
            self._save_locked()
        self.log(self.run["error"])
        self._ping("vidrot needs you", self.run["error"])
        return result

    def post_latest(self):
        run = self.snapshot()
        if not run or run.get("phase") not in ("ready", "posted") or not run.get("reel"):
            self.log("Post time arrived, but there is no unbranded-or-ready reel. Nothing was posted.")
            return {"ok": False, "error": "No reel is ready to post."}
        if run.get("phase") == "posted":
            self.log("Post time arrived. Today's reel was already posted.")
            return {"ok": True, "skipped": True}
        return self.post()

    def run_morning(self):
        """Scheduler path: batch, render, brand. Posting is its own clock."""
        if not self._claim():
            self.log("Morning run skipped because a job is already running.")
            return {"ok": False, "error": "busy"}
        try:
            created = self.new_batch()
            if not created.get("ok"):
                return created
            self._render_safe()
            snap = self.snapshot()
            if any(p.get("status") == "ready" for p in (snap.get("prompts") or [])):
                self._brand_safe()
            return {"ok": True, "run": self.snapshot()}
        finally:
            self._release()

    def _default_caption(self, run):
        first = (run.get("prompts") or [{}])[0]
        return first.get("caption") or "Unauthorized broadcast detected.\n\n#vidrot"

    def _history(self, entry):
        entry = dict(entry)
        entry["at"] = now_iso()
        entry["run_id"] = (self.snapshot() or {}).get("id", "")
        with self.lock:
            self.history.setdefault("posts", []).append(entry)
            self.history["posts"] = self.history["posts"][-200:]
            statedb.save_history(self.folder, self.history)
        return entry

    def _set_prompt(self, index, **fields):
        with self.lock:
            prompt = self.run["prompts"][index]
            prompt.update(fields)
            self.run["updated_at"] = now_iso()
            self._save_locked()

    def _fail_locked(self, message):
        if self.run is None:
            return
        self.run["phase"] = "error"
        self.run["error"] = message
        self.run["updated_at"] = now_iso()
        self._save_locked()

    def _fail(self, message):
        with self.lock:
            self._fail_locked(message)
        self.log(message)
        self._ping("vidrot failed", message)

    def _ping(self, title, body):
        try:
            from vidrot.push import notify
            notify(self.folder, title, body)
        except Exception:
            return

    def public_history(self):
        with self.lock:
            return list(self.history.get("posts") or [])


def json_copy(value):
    import json
    return json.loads(json.dumps(value))
