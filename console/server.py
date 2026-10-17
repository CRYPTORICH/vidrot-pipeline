#!/usr/bin/env python3
"""vidrot console. Localhost for a laptop, or 0.0.0.0 behind HTTPS in the cloud.

The phone talks to this process. The scheduler runs in the same process, so
the PC does not need to be on.
"""
import json
import mimetypes
import os
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vidrot.auth import COOKIE, Auth, cookie_header, read_cookie
from vidrot.crypto import require_env_key
from vidrot.db import get_json, put_json
from vidrot.engine import Engine
from vidrot.health import collect as collect_health
from vidrot.instagram import import_session, login as ig_login
from vidrot.push import add_subscription, configured as push_configured, public_key
from vidrot.scheduler import Scheduler
from vidrot.settings import load as load_settings
from vidrot.settings import public_view, save as save_settings
from vidrot.store import data_dir
from vidrot.veo import VeoClient

STATIC = Path(__file__).resolve().parent / "static"
MEDIA_KINDS = {"clips": "clips", "reels": "reels", "posters": "posters"}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class QuietServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def client_ip(handler):
    if os.environ.get("VIDROT_TRUST_PROXY") == "1":
        forwarded = handler.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:80]
    host = handler.client_address[0] if handler.client_address else ""
    return host


def request_is_secure(handler, auth):
    if auth.secure:
        return True
    proto = (handler.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    return proto == "https"


def remember_ig(folder, result):
    if not isinstance(result, dict):
        return
    if result.get("ok"):
        put_json(folder, "ig_notice", {})
        return
    if result.get("challenge") or result.get("needs_code"):
        put_json(folder, "ig_notice", {
            "challenge": bool(result.get("challenge")),
            "needs_code": bool(result.get("needs_code")),
            "error": result.get("error") or "Instagram needs a look on your phone.",
        })


def make_handler(engine, scheduler, auth):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            try:
                self._get()
            except Exception as exc:
                engine.log(f"Request error: {exc}")
                self._json(500, {"ok": False, "error": "The console hit an unexpected error. It is in the log."})

        def do_POST(self):
            try:
                self._post()
            except Exception as exc:
                engine.log(traceback.format_exc().splitlines()[-1])
                self._json(500, {"ok": False, "error": str(exc)[:300]})

        def _public_get(self, path):
            if path in ("/", "/index.html"):
                self._file(STATIC / "index.html")
                return True
            if path == "/healthz":
                self._json(200, {"ok": True})
                return True
            if path == "/manifest.webmanifest":
                self._file(STATIC / "manifest.webmanifest")
                return True
            if path == "/sw.js":
                self._file(STATIC / "sw.js")
                return True
            if path.startswith("/icons/"):
                name = Path(unquote(path[len("/icons/"):])).name
                self._file(STATIC / "icons" / name)
                return True
            if path.startswith("/static/"):
                name = unquote(path[len("/static/"):])
                target = (STATIC / name).resolve()
                if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                    self._json(404, {"ok": False, "error": "Not found"})
                    return True
                self._file(target)
                return True
            if path == "/api/session":
                self._session()
                return True
            return False

        def _authorized(self):
            if not auth.enabled:
                return True
            token = read_cookie(self.headers.get("Cookie"), COOKIE)
            return auth.valid(token)

        def _deny(self):
            self._json(401, {"ok": False, "error": "Sign in required.", "auth": True})

        def _get(self):
            path = urlparse(self.path).path
            if self._public_get(path):
                return
            if not self._authorized():
                self._deny()
                return
            if path.startswith("/media/"):
                self._media(path[len("/media/"):])
                return
            routes = {
                "/api/state": self._state,
                "/api/health": self._health,
                "/api/settings": self._settings_get,
                "/api/history": self._history,
                "/api/logs": self._logs,
            }
            if path not in routes:
                self._json(404, {"ok": False, "error": "Not found"})
                return
            routes[path]()

        def _post(self):
            path = urlparse(self.path).path
            if path == "/api/login":
                self._login()
                return
            if path == "/api/shutdown":
                host = self.client_address[0] if self.client_address else ""
                if host not in LOOPBACK:
                    self._json(403, {"ok": False, "error": "Shutdown is only available on the machine itself."})
                    return
            if not self._authorized():
                self._deny()
                return
            if auth.enabled and path != "/api/login":
                if self.headers.get("X-Vidrot-Request") != "1":
                    self._json(403, {"ok": False, "error": "Blocked a request that did not come from the app."})
                    return
            limit = 2_000_000 if path == "/api/instagram/session" else 1_000_000
            body = self._body(limit)
            if path == "/api/logout":
                auth.logout(read_cookie(self.headers.get("Cookie"), COOKIE))
                self._json(200, {"ok": True}, cookie=cookie_header("", request_is_secure(self, auth)))
                return
            if path == "/api/shutdown":
                self._json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if path == "/api/batch":
                if engine.busy():
                    self._json(409, {"ok": False, "error": "A job is already running."})
                    return
                dry = body.get("dry_run")
                self._json(200, engine.new_batch(dry_run=dry if dry is not None else None))
                return
            if path == "/api/prompts":
                self._json(200, engine.save_prompts(body.get("prompts") or []))
                return
            if path == "/api/prompts/regenerate":
                self._json(200, engine.regenerate(body.get("id") or ""))
                return
            if path == "/api/render":
                self._json(200, engine.start_render())
                return
            if path == "/api/brand":
                self._json(200, engine.start_brand())
                return
            if path == "/api/post":
                result = engine.post(body.get("caption") or "", body.get("verification_code") or "")
                remember_ig(engine.folder, result)
                self._json(200, result)
                return
            if path == "/api/settings":
                view, error = save_settings(body, engine.folder)
                if error:
                    self._json(400, {"ok": False, "error": error})
                    return
                self._json(200, {"ok": True, "settings": view})
                return
            if path == "/api/schedule":
                view, error = save_settings({"schedule": body}, engine.folder)
                if error:
                    self._json(400, {"ok": False, "error": error})
                    return
                self._json(200, {"ok": True, "settings": view, "scheduler": scheduler.summary()})
                return
            if path == "/api/veo/test":
                cfg = load_settings(engine.folder)
                try:
                    result = VeoClient(cfg["gemini_api_key"], cfg["veo_model"], cfg["veo_duration_seconds"]).check()
                except Exception as exc:
                    result = {"ok": False, "detail": str(exc)[:300]}
                self._json(200, result)
                return
            if path == "/api/instagram/test":
                result = ig_login(load_settings(engine.folder), engine.folder, body.get("verification_code") or "")
                result.pop("client", None)
                remember_ig(engine.folder, result)
                self._json(200, result)
                return
            if path == "/api/instagram/session":
                result = import_session(engine.folder, body.get("session"))
                if result.get("ok"):
                    engine.log("Imported an Instagram session.")
                    remember_ig(engine.folder, {"ok": True})
                self._json(200 if result.get("ok") else 400, result)
                return
            if path == "/api/push/subscribe":
                saved = add_subscription(engine.folder, body.get("subscription") or {})
                self._json(200 if saved else 400, {"ok": saved, "error": "" if saved else "That push subscription was empty."})
                return
            self._json(404, {"ok": False, "error": "Not found"})

        def _login(self):
            body = self._body(20_000)
            if not auth.enabled:
                self._json(200, {"ok": True, "disabled": True})
                return
            result = auth.login(body.get("password") or "", client_ip(self), self.headers.get("User-Agent", ""))
            if not result.get("ok"):
                self._json(401, {"ok": False, "error": result["error"]})
                return
            self._json(200, {"ok": True}, cookie=cookie_header(result["token"], request_is_secure(self, auth)))

        def _session(self):
            self._json(200, {
                "ok": True,
                "auth_required": auth.enabled,
                "authenticated": self._authorized(),
                "push": {"enabled": push_configured(), "publicKey": public_key() if push_configured() else ""},
            })

        def _state(self):
            cfg = load_settings(engine.folder)
            notice = get_json(engine.folder, "ig_notice", {}) or {}
            if not notice.get("error"):
                notice = None
            self._json(200, {
                "ok": True,
                "run": engine.snapshot(),
                "busy": engine.busy(),
                "dry_run": bool(cfg["dry_run"]),
                "scheduler": scheduler.summary(),
                "notice": notice,
            })

        def _health(self):
            self._json(200, {
                "ok": True,
                "health": collect_health(load_settings(engine.folder), engine.folder, engine.snapshot(), veo_check=False),
            })

        def _settings_get(self):
            cfg = load_settings(engine.folder)
            self._json(200, {"ok": True, "settings": public_view(cfg, engine.folder)})

        def _history(self):
            self._json(200, {"ok": True, "posts": engine.public_history()})

        def _logs(self):
            self._json(200, {"ok": True, "lines": engine.logger.tail(200)})

        def _media(self, rest):
            parts = [unquote(part) for part in rest.split("/") if part]
            if len(parts) != 2 or parts[0] not in MEDIA_KINDS:
                self._json(404, {"ok": False, "error": "Not found"})
                return
            name = Path(parts[1]).name
            target = (engine.folder / MEDIA_KINDS[parts[0]] / name).resolve()
            root = (engine.folder / MEDIA_KINDS[parts[0]]).resolve()
            if root not in target.parents or not target.is_file():
                self._json(404, {"ok": False, "error": "Not found"})
                return
            self._file(target)

        def _body(self, limit):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > limit:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def _json(self, code, payload, cookie=None):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._security_headers(cache="no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path):
            path = Path(path)
            if not path.is_file():
                self._json(404, {"ok": False, "error": "Not found"})
                return
            data = path.read_bytes()
            extra = {
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".html": "text/html; charset=utf-8",
                ".webmanifest": "application/manifest+json",
                ".mp4": "video/mp4",
                ".png": "image/png",
                ".json": "application/json",
            }
            kind = extra.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            cache = "no-store" if path.suffix.lower() in {".html", ""} else "public, max-age=300"
            self._security_headers(cache=cache)
            self.end_headers()
            self.wfile.write(data)

        def _security_headers(self, cache):
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; manifest-src 'self'",
            )

    return Handler


def build(folder=None):
    folder = folder or data_dir()
    engine = Engine(folder=folder, settings_fn=lambda: load_settings(folder))
    scheduler = Scheduler(engine)
    if os.environ.get("VIDROT_DISABLE_SCHEDULER") != "1":
        scheduler.start()
    return engine, scheduler


def serve(port=8765, folder=None, engine=None, scheduler=None, auth=None, host=None):
    if engine is None:
        engine, scheduler = build(folder)
    elif scheduler is None:
        scheduler = Scheduler(engine)
        if os.environ.get("VIDROT_DISABLE_SCHEDULER") != "1":
            scheduler.start()
    if auth is None:
        auth = Auth.from_env(engine.folder)
    bind = host or "127.0.0.1"
    httpd = QuietServer((bind, port), make_handler(engine, scheduler, auth))
    httpd.engine = engine
    httpd.scheduler = scheduler
    httpd.auth = auth
    return httpd


def main():
    host = os.environ.get("VIDROT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get("PORT") or os.environ.get("VIDROT_PORT") or "8765")
    public = host not in LOOPBACK
    if public and not os.environ.get("VIDROT_PASSWORD", "").strip():
        sys.stderr.write("VIDROT_PASSWORD is required when the server is reachable beyond this machine.\n")
        raise SystemExit(1)
    if public:
        require_env_key()
    try:
        httpd = serve(port, host=host)
    except OSError:
        if host in LOOPBACK and os.environ.get("VIDROT_NO_BROWSER") != "1":
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    url = f"http://{host}:{port}/"
    httpd.engine.log(f"Console listening on {url}")
    if host in LOOPBACK and os.environ.get("VIDROT_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.engine.log("Console stopped.")


if __name__ == "__main__":
    main()
