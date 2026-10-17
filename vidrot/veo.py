"""Google Veo via the Gemini predictLongRunning call Ralph's scripts used.

Submit:
  POST https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning?key=
Poll:
  GET  https://generativelanguage.googleapis.com/v1beta/{operation}?key=
Download the video.uri from the finished operation.
"""
import json
import urllib.error
import urllib.request

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


def submit_url(model, api_key):
    return f"{API_ROOT}/models/{model}:predictLongRunning?key={api_key}"


def operation_url(operation, api_key):
    op = (operation or "").strip()
    if op.startswith("https://"):
        base = op
    else:
        base = f"{API_ROOT}/{op.lstrip('/')}"
    joiner = "&" if "?" in base else "?"
    return f"{base}{joiner}key={api_key}"


def download_url(uri, api_key):
    joiner = "&" if "?" in uri else "?"
    return f"{uri}{joiner}key={api_key}"


def _error_message(payload, status):
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])[:400]
    if err:
        return str(err)[:400]
    return f"Veo request failed ({status})"


def parse_submit(status, payload):
    payload = payload or {}
    if status == 200 and payload.get("name"):
        return {"ok": True, "operation": payload["name"], "error": ""}
    return {"ok": False, "operation": "", "error": _error_message(payload, status)}


def parse_operation(payload):
    payload = payload or {}
    if payload.get("error"):
        return {"done": True, "ok": False, "error": _error_message(payload, "error"), "video_uri": ""}
    if not payload.get("done"):
        return {"done": False, "ok": True, "error": "", "video_uri": ""}
    response = payload.get("response") or {}
    samples = (response.get("generateVideoResponse") or {}).get("generatedSamples") or []
    uri = ""
    if samples:
        uri = ((samples[0].get("video") or {}).get("uri")) or ""
    if not uri:
        return {
            "done": True,
            "ok": False,
            "error": "Veo finished without a video file. The prompt may have been filtered.",
            "video_uri": "",
        }
    return {"done": True, "ok": True, "error": "", "video_uri": uri}


def http_request(method, url, body=None, timeout=60):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": {"message": raw[:300] or exc.reason}}
        return exc.code, payload


class VeoClient:
    def __init__(self, api_key, model="veo-3.1-fast-generate-preview", duration=8, request=None):
        self.api_key = api_key or ""
        self.model = model
        self.duration = duration if duration in (4, 6, 8) else 8
        self.request = request or http_request

    def check(self):
        if not self.api_key:
            return {"ok": False, "detail": "No Gemini API key saved yet."}
        status, payload = self.request(
            "GET",
            f"{API_ROOT}/models?key={self.api_key}&pageSize=50",
            timeout=15,
        )
        if status != 200:
            return {"ok": False, "detail": _error_message(payload, status)}
        names = " ".join(
            (item.get("name") or "") for item in (payload.get("models") or [])
        ).lower()
        if self.model.lower() in names or "veo" in names:
            return {"ok": True, "detail": f"Key accepted. Model {self.model} is available."}
        if names:
            return {
                "ok": True,
                "detail": f"Key accepted. {self.model} was not in the first page of models; rendering will confirm it.",
            }
        return {"ok": True, "detail": "Key accepted."}

    def submit(self, prompt):
        if not self.api_key:
            return {"ok": False, "operation": "", "error": "No Gemini API key saved."}
        body = {
            "instances": [{"prompt": prompt}],
            "parameters": {"aspectRatio": "9:16", "durationSeconds": self.duration},
        }
        status, payload = self.request("POST", submit_url(self.model, self.api_key), body, timeout=40)
        return parse_submit(status, payload)

    def poll(self, operation):
        status, payload = self.request("GET", operation_url(operation, self.api_key), timeout=40)
        if status != 200:
            return {"done": True, "ok": False, "error": _error_message(payload, status), "video_uri": ""}
        return parse_operation(payload)

    def download(self, uri, dest):
        url = download_url(uri, self.api_key)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"Download failed ({exc.code})", "path": ""}
        except urllib.error.URLError as exc:
            return {"ok": False, "error": f"Download failed: {exc.reason}", "path": ""}
        if not data:
            return {"ok": False, "error": "Veo returned an empty video.", "path": ""}
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return {"ok": True, "error": "", "path": str(dest)}
