#!/usr/bin/env python3
"""Local vidrot console. Binds to 127.0.0.1 only.

Double-click Vidrot.pyw or windows/Start Vidrot.vbs. Both start pythonw,
so no console window appears.
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

from vidrot.engine import Engine
from vidrot.health import collect as collect_health
from vidrot.scheduler import Scheduler
from vidrot.settings import load as load_settings
from vidrot.settings import public_view, save as save_settings
from vidrot.store import data_dir
from vidrot.veo import VeoClient

STATIC = Path(__file__).resolve().parent / "static"
MEDIA_KINDS = {"clips": "clips", "reels": "reels", "posters": "posters"}


def make_handler(engine, scheduler):
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
                engine.log(traceback.format_exc())
                self._json(500, {"ok": False, "error": str(exc)[:300]})

        def _get(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._file(STATIC / "index.html")
                return
            if path.startswith("/static/"):
                name = unquote(path[len("/static/"):])
                target = (STATIC / name).resolve()
                if STATIC.resolve() not in target.parents and target != STATIC.resolve():
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                self._file(target)
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
            body = self._body()
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
                self._json(200, engine.post(body.get("caption") or "", body.get("verification_code") or ""))
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
                from vidrot.instagram import login
                result = login(load_settings(engine.folder), engine.folder, body.get("verification_code") or "")
                result.pop("client", None)
                self._json(200, result)
                return
            if path == "/api/shutdown":
                self._json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._json(404, {"ok": False, "error": "Not found"})

        def _state(self):
            cfg = load_settings(engine.folder)
            self._json(200, {
                "ok": True,
                "run": engine.snapshot(),
                "busy": engine.busy(),
                "dry_run": bool(cfg["dry_run"]),
                "scheduler": scheduler.summary(),
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

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > 1_000_000:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def _json(self, code, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
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
                ".mp4": "video/mp4",
                ".png": "image/png",
                ".json": "application/json",
            }
            kind = extra.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def build(folder=None):
    folder = folder or data_dir()
    engine = Engine(folder=folder, settings_fn=lambda: load_settings(folder))
    scheduler = Scheduler(engine)
    if os.environ.get("VIDROT_DISABLE_SCHEDULER") != "1":
        scheduler.start()
    return engine, scheduler


def serve(port=8765, folder=None, engine=None, scheduler=None):
    if engine is None:
        engine, scheduler = build(folder)
    elif scheduler is None:
        scheduler = Scheduler(engine)
        if os.environ.get("VIDROT_DISABLE_SCHEDULER") != "1":
            scheduler.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine, scheduler))
    httpd.engine = engine
    httpd.scheduler = scheduler
    return httpd


def main():
    port = int(os.environ.get("VIDROT_PORT", "8765"))
    try:
        httpd = serve(port)
    except OSError:
        if os.environ.get("VIDROT_NO_BROWSER") != "1":
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    url = f"http://127.0.0.1:{port}/"
    httpd.engine.log(f"Console listening on {url}")
    if os.environ.get("VIDROT_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.engine.log("Console stopped.")


if __name__ == "__main__":
    main()
