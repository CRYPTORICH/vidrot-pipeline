"""Console pipeline tests. No Gemini key and no Instagram account."""
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from console.server import serve
from vidrot.brand import ffmpeg_text, normalize_command
from vidrot.engine import Engine
from vidrot.instagram import classify, permalink
from vidrot.prompts import apply_edits, generate_batch
from vidrot.scheduler import is_due, next_fire
from vidrot.settings import load, public_view, save
from vidrot.veo import download_url, operation_url, parse_operation, parse_submit, submit_url


def settings_for(dry_run=True, key=""):
    return {
        "dry_run": dry_run,
        "batch_size": 2,
        "gemini_api_key": key,
        "veo_model": "veo-3.1-fast-generate-preview",
        "veo_duration_seconds": 8,
        "ffmpeg_path": "",
        "trends_geo": "US",
        "ig_username": "vidrot.ai",
        "ig_password": "",
        "openclaw_url": "http://127.0.0.1:9",
        "schedule": {
            "batch_enabled": False,
            "batch_time": "09:00",
            "post_enabled": False,
            "post_time": "12:00",
            "weekdays": [0, 1, 2, 3, 4, 5],
        },
    }


def card(dest, line):
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"clip-" + line.encode())
    return {"ok": True, "path": str(dest)}


def normalizer(src, dest, label):
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(Path(src).read_bytes())
    return {"ok": True, "path": str(dest)}


def stitcher(clips, dest, bumper=None):
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"reel")
    return {"ok": True, "path": str(dest)}


def poster(src, dest):
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_bytes(b"png")
    return {"ok": True}


def make_engine(folder, **kwargs):
    folder = Path(folder)
    cfg = kwargs.pop("settings", None) or settings_for()
    return Engine(
        folder=folder,
        settings_fn=lambda: cfg,
        trends_fn=lambda: (["ALPHA TREND", "BETA TREND"], ""),
        card_writer=card,
        normalizer=normalizer,
        stitcher=stitcher,
        poster_fn=poster,
        poll_interval=0,
        **kwargs,
    )


class VeoParseTests(unittest.TestCase):
    def test_urls_match_ralphs_script(self):
        self.assertIn(":predictLongRunning?key=abc", submit_url("veo-3.1-fast-generate-preview", "abc"))
        self.assertTrue(operation_url("models/veo/operations/op1", "abc").endswith("?key=abc"))
        self.assertIn("&key=abc", download_url("https://example.test/file?alt=media", "abc"))

    def test_submit_and_done_payload(self):
        submitted = parse_submit(200, {"name": "models/veo/operations/op1"})
        self.assertTrue(submitted["ok"])
        waiting = parse_operation({"done": False})
        self.assertFalse(waiting["done"])
        done = parse_operation({
            "done": True,
            "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "https://example.test/v"}}]}},
        })
        self.assertEqual(done["video_uri"], "https://example.test/v")
        failed = parse_operation({"done": True, "error": {"message": "filtered"}})
        self.assertIn("filtered", failed["error"])
        rejected = parse_submit(400, {"error": {"message": "API key not valid"}})
        self.assertFalse(rejected["ok"])
        self.assertIn("API key", rejected["error"])


class PromptTests(unittest.TestCase):
    def test_batch_mentions_the_trend_and_edits_stick(self):
        batch = generate_batch(["fish and chips", "quiet quitting"], count=3)
        self.assertEqual(len(batch), 3)
        self.assertIn("fish and chips", batch[0]["prompt"])
        self.assertEqual(len({item["channel"] for item in batch}), 3)
        edited = apply_edits(batch, [{"id": "p1", "prompt": "A rewritten prompt", "caption": "new caption"}])
        self.assertEqual(edited[0]["prompt"], "A rewritten prompt")
        self.assertEqual(edited[0]["caption"], "new caption")
        self.assertEqual(edited[1]["prompt"], batch[1]["prompt"])


class EngineTests(unittest.TestCase):
    def test_dry_run_finishes_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            created = engine.new_batch()
            self.assertTrue(created["ok"])
            self.assertEqual(created["run"]["phase"], "review")
            rendered = engine.render()
            self.assertTrue(rendered["ok"])
            snap = engine.snapshot()
            self.assertEqual(snap["phase"], "clips_ready")
            self.assertTrue(all(item["status"] == "ready" for item in snap["prompts"]))
            engine._brand()
            self.assertEqual(engine.snapshot()["phase"], "ready")
            posted = engine.post(caption="hello from dry run")
            self.assertTrue(posted["ok"])
            self.assertTrue(posted["dry_run"])
            self.assertEqual(engine.snapshot()["phase"], "posted")
            self.assertEqual(len(engine.public_history()), 1)
            self.assertTrue((Path(tmp) / "reels" / f"{snap['id']}.mp4").exists())

    def test_regenerate_returns_without_deadlock(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            engine.new_batch()
            prompt_id = engine.snapshot()["prompts"][0]["id"]
            result = engine.regenerate(prompt_id)
            self.assertTrue(result["ok"])
            self.assertEqual(result["run"]["prompts"][0]["id"], prompt_id)
            self.assertFalse(engine.regenerate("missing")["ok"])

    def test_veo_failure_is_a_visible_error(self):
        class BadVeo:
            def submit(self, prompt):
                return {"ok": False, "error": "quota exceeded"}

        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, settings=settings_for(dry_run=False, key="test-key"), veo_factory=lambda: BadVeo())
            engine.new_batch(dry_run=False)
            result = engine.render()
            self.assertFalse(result["ok"])
            snap = engine.snapshot()
            self.assertEqual(snap["phase"], "error")
            self.assertIn("quota exceeded", snap["prompts"][0]["error"])

    def test_veo_success_downloads_the_file(self):
        class GoodVeo:
            def submit(self, prompt):
                return {"ok": True, "operation": "models/veo/operations/abc"}

            def poll(self, operation):
                return {"done": True, "ok": True, "video_uri": "https://example.test/v?alt=media", "error": ""}

            def download(self, uri, dest):
                Path(dest).write_bytes(b"mp4")
                return {"ok": True, "path": str(dest)}

        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp, settings=settings_for(dry_run=False, key="test-key"), veo_factory=lambda: GoodVeo())
            engine.new_batch(dry_run=False)
            engine.render()
            snap = engine.snapshot()
            self.assertEqual(snap["phase"], "clips_ready")
            self.assertTrue((Path(tmp) / "clips" / snap["prompts"][0]["clip"]).read_bytes().startswith(b"mp4"))


class SchedulerTests(unittest.TestCase):
    def test_grace_window_and_once_per_day(self):
        morning = datetime(2026, 10, 19, 9, 4)  # Monday
        self.assertTrue(is_due(morning, "09:00", True, [0, 1, 2, 3, 4, 5], ""))
        self.assertFalse(is_due(morning, "09:00", True, [0, 1, 2, 3, 4, 5], "2026-10-19"))
        self.assertFalse(is_due(morning, "09:00", False, [0], ""))
        self.assertFalse(is_due(morning, "09:00", True, [6], ""))
        late = datetime(2026, 10, 19, 9, 30)
        self.assertFalse(is_due(late, "09:00", True, [0], ""))
        nxt = next_fire(datetime(2026, 10, 19, 10, 0), "09:00", True, [0])
        self.assertTrue(nxt.startswith("2026-10-26T09:00"))


class SettingsTests(unittest.TestCase):
    def test_secrets_stay_in_the_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            view, error = save({
                "gemini_api_key": "super-secret-key",
                "ig_password": "pw",
                "dry_run": False,
            }, folder)
            self.assertEqual(error, "")
            self.assertNotIn("super-secret-key", json.dumps(view))
            self.assertNotIn("pw", json.dumps(view))
            self.assertTrue(view["gemini_api_key_set"])
            stored = json.loads((folder / "settings.json").read_text())
            self.assertEqual(stored["gemini_api_key"], "super-secret-key")
            again, _ = save({"gemini_api_key": ""}, folder)
            self.assertTrue(again["gemini_api_key_set"])
            self.assertNotIn(str(folder), "")  # data dir is the temp dir, not the repo
            self.assertFalse(str(Path(__file__).resolve().parents[1]) in str(folder))
            public = public_view(load(folder), folder)
            self.assertNotIn("super-secret-key", json.dumps(public))


class BrandCommandTests(unittest.TestCase):
    def test_normalize_forces_vertical_and_escapes_text(self):
        cmd = normalize_command("ffmpeg", "in.mp4", "out.mp4", "FISH: CHIPS", None)
        joined = " ".join(cmd)
        self.assertIn("scale=1080:1920", joined)
        self.assertIn("yuv420p", joined)
        self.assertNotIn("FISH: CHIPS", joined)
        self.assertEqual(ffmpeg_text("FISH: CHIPS"), "FISH CHIPS")


class InstagramMessageTests(unittest.TestCase):
    def test_challenge_and_media_link(self):
        class ChallengeRequired(Exception):
            pass

        result = classify(ChallengeRequired("checkpoint"))
        self.assertTrue(result["challenge"])
        self.assertIn("phone", result["error"])

        class Media:
            code = "Abc"
            pk = 1

        self.assertEqual(permalink(Media()), "https://www.instagram.com/reel/Abc/")


class ApiTests(unittest.TestCase):
    def test_dry_run_through_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["VIDROT_DISABLE_SCHEDULER"] = "1"
            engine = make_engine(tmp)
            httpd = serve(0, engine=engine)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(httpd.shutdown)
            port = httpd.server_address[1]
            base = f"http://127.0.0.1:{port}"

            def call(method, path, body=None):
                data = None if body is None else json.dumps(body).encode()
                req = urllib.request.Request(base + path, data=data, method=method)
                if data is not None:
                    req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return json.loads(resp.read().decode())

            page = urllib.request.urlopen(base + "/", timeout=5)
            self.assertEqual(page.status, 200)
            self.assertIn(b"vidrot.ai", page.read())
            created = call("POST", "/api/batch", {})
            self.assertTrue(created["ok"])
            saved = call("POST", "/api/prompts", {"prompts": [{"id": "p1", "prompt": "edited prompt", "caption": "cap"}]})
            self.assertEqual(saved["run"]["prompts"][0]["prompt"], "edited prompt")
            started = call("POST", "/api/render", {})
            self.assertTrue(started["ok"])
            for _ in range(50):
                state = call("GET", "/api/state")
                if not state["busy"] and state["run"]["phase"] in ("clips_ready", "error"):
                    break
            self.assertEqual(state["run"]["phase"], "clips_ready")
            branded = call("POST", "/api/brand", {})
            self.assertTrue(branded["ok"])
            for _ in range(50):
                state = call("GET", "/api/state")
                if not state["busy"]:
                    break
            self.assertEqual(state["run"]["phase"], "ready")
            posted = call("POST", "/api/post", {"caption": "dry"})
            self.assertTrue(posted["dry_run"])
            history = call("GET", "/api/history")
            self.assertEqual(len(history["posts"]), 1)
            missing = urllib.request.Request(base + "/media/clips/..%2Fsettings.json")
            try:
                urllib.request.urlopen(missing, timeout=5)
                self.fail("path traversal should not be served")
            except urllib.error.HTTPError as exc:
                self.assertEqual(exc.code, 404)
            view = call("POST", "/api/settings", {"gemini_api_key": "super-secret-key"})
            self.assertNotIn("super-secret-key", json.dumps(view))
            fetched = call("GET", "/api/settings")
            self.assertNotIn("super-secret-key", json.dumps(fetched))


class LauncherTests(unittest.TestCase):
    def test_windows_launcher_has_no_console(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "windows" / "Start Vidrot.vbs").read_text(encoding="utf-8")
        self.assertIn("pyw -3.11", text)
        self.assertIn(", 0, False", text)
        # A comment may name the old powershell.exe task. The launcher itself must not start one.
        launched = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("'")
        )
        self.assertNotIn("powershell", launched.lower())
        stop = (root / "windows" / "Stop Vidrot.vbs").read_text(encoding="utf-8")
        self.assertIn("/api/shutdown", stop)


if __name__ == "__main__":
    unittest.main()
