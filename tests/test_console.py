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
from urllib.parse import urljoin

from console.server import serve
from vidrot.auth import Auth, cookie_header, cookie_path
from vidrot.brand import ffmpeg_text, normalize_command
from vidrot.engine import Engine
from vidrot import health
from vidrot.instagram import classify, import_session, login, permalink
from vidrot.prompts import apply_edits, generate_batch
from vidrot.scheduler import Scheduler, is_due, next_fire
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

    def test_run_reloads_from_the_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            created = engine.new_batch()
            again = make_engine(tmp)
            self.assertEqual(again.snapshot()["id"], created["run"]["id"])
            self.assertEqual(again.snapshot()["phase"], "review")

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

    def test_tick_fires_each_job_once(self):
        class ClockEngine:
            def __init__(self, folder):
                self.folder = Path(folder)
                self.calls = []

            def settings(self):
                return {
                    "timezone": "UTC",
                    "schedule": {
                        "batch_enabled": True,
                        "batch_time": "09:00",
                        "post_enabled": True,
                        "post_time": "12:00",
                        "weekdays": [0],
                    },
                }

            def run_morning(self):
                self.calls.append("morning")

            def post_latest(self):
                self.calls.append("post")

            def log(self, message):
                return message

        with tempfile.TemporaryDirectory() as tmp:
            engine = ClockEngine(tmp)
            scheduler = Scheduler(engine)
            monday_morning = datetime(2026, 10, 19, 9, 4)
            self.assertTrue(scheduler.tick(monday_morning))
            self.assertFalse(scheduler.tick(datetime(2026, 10, 19, 9, 8)))
            self.assertTrue(scheduler.tick(datetime(2026, 10, 19, 12, 2)))
            self.assertEqual(engine.calls, ["morning", "post"])
            self.assertEqual(scheduler.summary(datetime(2026, 10, 19, 13, 0))["last_batch_date"], "2026-10-19")


class SettingsTests(unittest.TestCase):
    def test_secrets_stay_in_the_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            view, error = save({
                "gemini_api_key": "super-secret-key",
                "ig_password": "instagram-password-zz",
                "dry_run": False,
            }, folder)
            self.assertEqual(error, "")
            self.assertNotIn("super-secret-key", json.dumps(view))
            self.assertNotIn("instagram-password-zz", json.dumps(view))
            self.assertTrue(view["gemini_api_key_set"])
            from vidrot.db import get_kv
            stored = get_kv(folder, "settings", "")
            self.assertNotIn("super-secret-key", stored)
            self.assertNotIn("instagram-password-zz", stored)
            self.assertIn("enc:v1:", stored)
            self.assertEqual(load(folder)["gemini_api_key"], "super-secret-key")
            again, _ = save({"gemini_api_key": ""}, folder)
            self.assertTrue(again["gemini_api_key_set"])
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
            page_bytes = page.read()
            self.assertIn(b"vidrot", page_bytes)
            self.assertIn(b"Sign in", page_bytes)
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


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        os.environ["VIDROT_DISABLE_SCHEDULER"] = "1"
        self.engine = make_engine(self.folder)
        self.auth = Auth("correct-horse-battery", self.folder, secure=True)
        self.httpd = serve(0, engine=self.engine, auth=self.auth)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.cookie = ""

    def tearDown(self):
        self.httpd.shutdown()
        self.tmp.cleanup()

    def call(self, method, path, body=None, cookie=True):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("X-Vidrot-Request", "1")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if cookie and self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                self._take_cookie(resp.headers)
                return resp.status, json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            self._take_cookie(exc.headers)
            raw = exc.read().decode() or "{}"
            return exc.code, json.loads(raw)

    def _take_cookie(self, headers):
        set_cookie = headers.get("Set-Cookie") or ""
        if "vidrot_session=" in set_cookie:
            self.cookie = set_cookie.split(";", 1)[0]

    def test_login_session_and_lockout(self):
        code, session = self.call("GET", "/api/session", cookie=False)
        self.assertEqual(code, 200)
        self.assertTrue(session["auth_required"])
        self.assertFalse(session["authenticated"])
        code, denied = self.call("GET", "/api/state", cookie=False)
        self.assertEqual(code, 401)
        code, media = self.call("GET", "/media/clips/nope.mp4", cookie=False)
        self.assertEqual(code, 401)
        code, bad = self.call("POST", "/api/login", {"password": "nope"}, cookie=False)
        self.assertEqual(code, 401)
        self.assertNotIn("correct-horse", json.dumps(bad))
        code, good = self.call("POST", "/api/login", {"password": "correct-horse-battery"}, cookie=False)
        self.assertEqual(code, 200)
        # Re-read the cookie flags from a fresh login response.
        req = urllib.request.Request(
            self.base + "/api/login",
            data=json.dumps({"password": "correct-horse-battery"}).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            set_cookie = resp.headers.get("Set-Cookie")
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Lax", set_cookie)
        self.assertIn("Secure", set_cookie)
        code, state = self.call("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertTrue(state["ok"])
        bare = urllib.request.Request(
            self.base + "/api/batch",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "Cookie": self.cookie},
        )
        try:
            urllib.request.urlopen(bare, timeout=5)
            self.fail("a cookie alone should not authorize a cross-site post")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 403)
        code, _ = self.call("POST", "/api/logout", {})
        self.assertEqual(code, 200)
        code, after = self.call("GET", "/api/state")
        self.assertEqual(code, 401)
        self.assertFalse(after.get("ok"))

    def test_lockout_after_repeated_failures(self):
        for _ in range(8):
            code, _ = self.call("POST", "/api/login", {"password": "wrong"}, cookie=False)
            self.assertEqual(code, 401)
        code, locked = self.call("POST", "/api/login", {"password": "correct-horse-battery"}, cookie=False)
        self.assertEqual(code, 401)
        self.assertIn("15 minutes", locked["error"])


class BasePathTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("VIDROT_COOKIE_PATH", None)

    def test_cookie_path_defaults_to_root_and_prefixes_a_subpath(self):
        self.assertEqual(cookie_path(), "/")
        root = cookie_header("token", False)
        self.assertIn("Path=/", root)
        self.assertNotIn("Path=/vidrot", root)
        os.environ["VIDROT_COOKIE_PATH"] = "vidrot"
        self.assertEqual(cookie_path(), "/vidrot")
        os.environ["VIDROT_COOKIE_PATH"] = "/vidrot/"
        self.assertEqual(cookie_path(), "/vidrot/")
        login = cookie_header("token", True)
        self.assertIn("vidrot_session=token", login)
        self.assertIn("Path=/vidrot/", login)
        self.assertIn("HttpOnly", login)
        self.assertIn("SameSite=Lax", login)
        self.assertIn("Secure", login)
        logout = cookie_header("", True)
        self.assertIn("vidrot_session=", logout)
        self.assertIn("Path=/vidrot/", logout)
        self.assertIn("Max-Age=0", logout)
        os.environ["VIDROT_COOKIE_PATH"] = "   "
        self.assertEqual(cookie_path(), "/")

    def test_login_cookie_uses_the_configured_path(self):
        os.environ["VIDROT_COOKIE_PATH"] = "/vidrot"
        os.environ["VIDROT_DISABLE_SCHEDULER"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(tmp)
            auth = Auth("correct-horse-battery", Path(tmp), secure=True)
            httpd = serve(0, engine=engine, auth=auth)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(httpd.shutdown)
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            req = urllib.request.Request(
                base + "/api/login",
                data=json.dumps({"password": "correct-horse-battery"}).encode(),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                set_cookie = resp.headers.get("Set-Cookie")
            self.assertIn("Path=/vidrot", set_cookie)
            self.assertIn("HttpOnly", set_cookie)
            self.assertIn("Secure", set_cookie)
            logout = urllib.request.Request(
                base + "/api/logout",
                data=b"{}",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Vidrot-Request": "1",
                    "Cookie": set_cookie.split(";", 1)[0],
                },
            )
            with urllib.request.urlopen(logout, timeout=5) as resp:
                cleared = resp.headers.get("Set-Cookie")
            self.assertIn("Path=/vidrot", cleared)
            self.assertIn("Max-Age=0", cleared)

    def test_relative_urls_resolve_at_root_and_under_a_prefix(self):
        root = Path(__file__).resolve().parents[1]
        index = (root / "console" / "static" / "index.html").read_text()
        app = (root / "console" / "static" / "app.js").read_text()
        manifest = json.loads((root / "console" / "static" / "manifest.webmanifest").read_text())
        sw = (root / "console" / "static" / "sw.js").read_text()
        self.assertIn('href="static/app.css"', index)
        self.assertIn('src="static/app.js"', index)
        self.assertIn('href="manifest.webmanifest"', index)
        self.assertNotIn('href="/', index)
        self.assertNotIn('src="/', index)
        self.assertEqual(manifest["start_url"], "./")
        self.assertEqual(manifest["scope"], "./")
        for icon in manifest["icons"]:
            self.assertFalse(icon["src"].startswith("/"))
        self.assertIn('api("api/session")', app)
        self.assertIn('register("sw.js")', app)
        self.assertNotIn('"/api', app)
        self.assertNotIn("'/api", app)
        self.assertNotIn("/media/", app)
        self.assertIn('const CACHE = "vidrot-shell-6"', sw)
        self.assertIn("self.registration.scope", sw)
        self.assertIn('"static/app.js"', sw)
        self.assertNotIn('"/static/', sw)

        page_root = "http://127.0.0.1:8765/"
        page_prefix = "https://racksrewards.com/vidrot/"
        for rel in (
            "static/app.css",
            "static/app.js",
            "api/session",
            "sw.js",
            "manifest.webmanifest",
            "icons/icon-192.png",
            "media/clips/clip.mp4",
        ):
            self.assertEqual(urljoin(page_root, rel), "http://127.0.0.1:8765/" + rel)
            self.assertEqual(urljoin(page_prefix, rel), "https://racksrewards.com/vidrot/" + rel)
        # A directory URL without the trailing slash drops the prefix.
        self.assertEqual(
            urljoin("https://racksrewards.com/vidrot", "static/app.css"),
            "https://racksrewards.com/static/app.css",
        )

        def stripped(scope, pathname):
            base = scope[:-1] if scope.endswith("/") else scope
            if base and pathname.startswith(base):
                return pathname[len(base):]
            return pathname

        self.assertEqual(stripped("/", "/api/state"), "/api/state")
        self.assertEqual(stripped("/vidrot/", "/vidrot/api/state"), "/api/state")
        self.assertEqual(stripped("/vidrot/", "/vidrot/static/app.css"), "/static/app.css")
        self.assertTrue(stripped("/vidrot/", "/vidrot/healthz") == "/healthz")


class InstagramSessionTests(unittest.TestCase):
    def test_import_encrypts_and_proxy_is_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            imported = import_session(folder, {"uuids": {"phone_id": "abc"}, "cookies": {}})
            self.assertTrue(imported["ok"])
            from vidrot.db import get_kv
            stored = get_kv(folder, "ig_session", "")
            self.assertTrue(stored.startswith("enc:v1:"))
            self.assertNotIn("phone_id", stored)
            self.assertFalse(import_session(folder, {"hello": "nope"})["ok"])
            seen = {}

            class FakeClient:
                def set_proxy(self, proxy):
                    seen["proxy"] = proxy

                def set_settings(self, settings):
                    seen["settings"] = settings

                def get_timeline_feed(self):
                    return []

                def get_settings(self):
                    return {"uuids": {"phone_id": "abc"}}

            result = login(
                {"ig_username": "vidrot.ai", "ig_password": "", "ig_proxy": "http://127.0.0.1:9"},
                folder,
                client_factory=FakeClient,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(seen["proxy"], "http://127.0.0.1:9")
            self.assertEqual(seen["settings"]["uuids"]["phone_id"], "abc")


class HealthAndDeployTests(unittest.TestCase):
    def test_openclaw_stays_off_without_a_probe(self):
        def boom(url, timeout=3):
            raise AssertionError(f"probed {url}")

        original = health._probe
        health._probe = boom
        try:
            with tempfile.TemporaryDirectory() as tmp:
                card = health.collect(
                    {
                        "gemini_api_key": "",
                        "veo_model": "veo-3.1-fast-generate-preview",
                        "veo_duration_seconds": 8,
                        "ig_username": "vidrot.ai",
                        "ig_password": "",
                        "openclaw_enabled": False,
                        "ffmpeg_path": "",
                    },
                    Path(tmp),
                    veo_check=False,
                )
        finally:
            health._probe = original
        self.assertTrue(card["openclaw"]["ok"])
        self.assertIn("Off", card["openclaw"]["detail"])

    def test_phone_app_files(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "console" / "static" / "manifest.webmanifest").read_text())
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue((root / "console" / "static" / "sw.js").read_text().startswith("const CACHE"))
        self.assertTrue((root / "console" / "static" / "icons" / "icon-192.png").exists())
        self.assertTrue((root / "console" / "static" / "icons" / "icon-512.png").exists())
        docker = (root / "Dockerfile").read_text()
        self.assertIn("ffmpeg", docker)
        self.assertIn("VIDROT_DATA=/data", docker)
        fly = (root / "fly.toml").read_text()
        self.assertIn('auto_stop_machines = "off"', fly)
        self.assertIn("min_machines_running = 1", fly)
        self.assertIn("/data", fly)


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
