"""SQLite state on the data volume. Media files live beside the database."""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_agent TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS login_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  ip TEXT NOT NULL,
  ok INTEGER NOT NULL
);
"""

_locks = {}
_guard = threading.Lock()


def _lock(folder):
    key = str(Path(folder).resolve()) if Path(folder).exists() else str(Path(folder))
    with _guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


def connect(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / "vidrot.db", timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    return conn


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def put_kv(folder, key, value):
    with _lock(folder):
        conn = connect(folder)
        try:
            conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value if isinstance(value, str) else json.dumps(value)),
            )
        finally:
            conn.close()


def get_kv(folder, key, default=None):
    with _lock(folder):
        conn = connect(folder)
        try:
            row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        finally:
            conn.close()
    if row is None:
        return default
    return row["value"]


def get_json(folder, key, default):
    raw = get_kv(folder, key, None)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def put_json(folder, key, payload):
    put_kv(folder, key, json.dumps(payload))


def load_run(folder):
    return get_json(folder, "current_run", None)


def save_run(folder, run):
    put_json(folder, "current_run", run)


def load_history(folder):
    history = get_json(folder, "history", None)
    if isinstance(history, dict) and isinstance(history.get("posts"), list):
        return history
    return {"posts": []}


def save_history(folder, history):
    put_json(folder, "history", history)


def load_scheduler(folder):
    state = get_json(folder, "scheduler", None)
    if not isinstance(state, dict):
        state = {}
    state.setdefault("last_batch_date", "")
    state.setdefault("last_post_date", "")
    return state


def save_scheduler(folder, state):
    put_json(folder, "scheduler", state)


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(folder, token, user_agent, days=14):
    now = _now()
    expires = now + timedelta(days=days)
    with _lock(folder):
        conn = connect(folder)
        try:
            conn.execute(
                "INSERT INTO sessions(token_hash, created_at, expires_at, user_agent) VALUES(?, ?, ?, ?)",
                (token_hash(token), now.isoformat(), expires.isoformat(), (user_agent or "")[:300]),
            )
        finally:
            conn.close()


def session_valid(folder, token):
    if not token:
        return False
    now = _now()
    with _lock(folder):
        conn = connect(folder)
        try:
            row = conn.execute(
                "SELECT expires_at FROM sessions WHERE token_hash=?",
                (token_hash(token),),
            ).fetchone()
            if row is None:
                return False
            expires = datetime.fromisoformat(row["expires_at"])
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
                return False
            if expires - now < timedelta(days=7):
                conn.execute(
                    "UPDATE sessions SET expires_at=? WHERE token_hash=?",
                    ((now + timedelta(days=14)).isoformat(), token_hash(token)),
                )
            return True
        finally:
            conn.close()


def delete_session(folder, token):
    if not token:
        return
    with _lock(folder):
        conn = connect(folder)
        try:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        finally:
            conn.close()


def record_attempt(folder, ip, ok):
    now = _now()
    with _lock(folder):
        conn = connect(folder)
        try:
            conn.execute(
                "INSERT INTO login_attempts(at, ip, ok) VALUES(?, ?, ?)",
                (now.isoformat(), ip or "", 1 if ok else 0),
            )
            cutoff = (now - timedelta(days=1)).isoformat()
            conn.execute("DELETE FROM login_attempts WHERE at < ?", (cutoff,))
        finally:
            conn.close()


def recent_failures(folder, ip, minutes=15):
    now = _now()
    cutoff = (now - timedelta(minutes=minutes)).isoformat()
    with _lock(folder):
        conn = connect(folder)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM login_attempts WHERE ip=? AND ok=0 AND at>=?",
                (ip or "", cutoff),
            ).fetchone()
        finally:
            conn.close()
    return int(row["n"] if row else 0)
