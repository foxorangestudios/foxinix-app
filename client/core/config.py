"""Configuración del cliente: servidor primario/fallback y rutas locales."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Orden de preferencia: Tailscale primero (privado), luego Cloudflare (público).
SERVERS = [
    ("tailscale", "http://100.125.128.82:8444"),
    ("cloudflare", "https://chat.foxinix.qzz.io"),
]
WS_SERVERS = [
    ("tailscale", "ws://100.125.128.82:8444"),
    ("cloudflare", "wss://chat.foxinix.qzz.io"),
]

# Override manual (desarrollo): FOXMSG_SERVER=http://127.0.0.1:8899
if os.environ.get("FOXMSG_SERVER"):
    s = os.environ["FOXMSG_SERVER"].rstrip("/")
    w = s.replace("http://", "ws://").replace("https://", "wss://")
    SERVERS = [("manual", s)]
    WS_SERVERS = [("manual", w)]


def app_data_dir() -> Path:
    """Datos locales del cliente (config, caché SQLite)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "foxmsg"
    d.mkdir(parents=True, exist_ok=True)
    return d


SESSION_FILE = app_data_dir() / "session.json"
DB_FILE = app_data_dir() / "cache.db"
SETTINGS_FILE = app_data_dir() / "settings.json"

# Límites (deben coincidir con server/app/config.py)
MAX_UPLOAD_BYTES = 50 * 1024 * 1024   # 50 MB por archivo
