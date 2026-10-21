"""Caché local SQLite: chats y mensajes (funciona offline, sync incremental)."""
from __future__ import annotations

import sqlite3
import threading
from typing import Any

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    id INTEGER PRIMARY KEY,
    payload TEXT NOT NULL,          -- JSON del chat brief
    last_seq INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    payload TEXT NOT NULL,          -- JSON del mensaje
    UNIQUE (chat_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id, seq);
CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_FILE, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn


def upsert_chat(chat: dict[str, Any]) -> None:
    import json

    with _lock:
        c = _db()
        last_seq = (chat.get("last_message") or {}).get("seq", 0)
        c.execute(
            "INSERT INTO chats (id, payload, last_seq, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,"
            "  last_seq=MAX(chats.last_seq, excluded.last_seq),"
            "  updated_at=excluded.updated_at",
            (chat["id"], json.dumps(chat, ensure_ascii=False), last_seq,
             (chat.get("last_message") or {}).get("created_at", 0)),
        )
        c.commit()


def upsert_messages(messages: list[dict[str, Any]]) -> None:
    import json

    if not messages:
        return
    with _lock:
        c = _db()
        for m in messages:
            c.execute(
                "INSERT INTO messages (id, chat_id, seq, payload) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(chat_id, seq) DO UPDATE SET payload=excluded.payload",
                (m["id"], m["chat_id"], m["seq"], json.dumps(m, ensure_ascii=False)),
            )
            c.execute(
                "UPDATE chats SET last_seq = MAX(last_seq, ?) WHERE id = ?",
                (m["seq"], m["chat_id"]),
            )
        c.commit()


def cached_chats() -> list[dict[str, Any]]:
    import json

    with _lock:
        rows = _db().execute(
            "SELECT payload FROM chats ORDER BY updated_at DESC"
        ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def cached_messages(chat_id: int, limit: int = 50) -> list[dict[str, Any]]:
    import json

    with _lock:
        rows = _db().execute(
            "SELECT payload FROM messages WHERE chat_id = ? ORDER BY seq DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    out = [json.loads(r["payload"]) for r in rows]
    out.reverse()
    return out


def last_seq(chat_id: int) -> int:
    with _lock:
        row = _db().execute(
            "SELECT COALESCE(MAX(seq), 0) AS s FROM messages WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    return int(row["s"])


def set_kv(k: str, v: str) -> None:
    with _lock:
        _db().execute(
            "INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, v),
        )
        _db().commit()


def get_kv(k: str) -> str | None:
    with _lock:
        row = _db().execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
    return row["v"] if row else None


def clear_all() -> None:
    with _lock:
        c = _db()
        c.execute("DELETE FROM chats")
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM kv")
        c.commit()
