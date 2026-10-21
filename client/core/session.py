"""Sesión persistente: guarda tokens y usuario en session.json."""
from __future__ import annotations

import json
from typing import Any

from . import config


class Session:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        try:
            if config.SESSION_FILE.is_file():
                self.data = json.loads(config.SESSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def save(self) -> None:
        try:
            config.SESSION_FILE.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ------------------------------------------------------------ campos

    @property
    def tokens(self) -> dict | None:
        return self.data.get("tokens")

    @property
    def user(self) -> dict | None:
        return self.data.get("user")

    @property
    def server(self) -> str | None:
        return self.data.get("server")

    def set_auth(self, tokens: dict, user: dict, server: str | None = None) -> None:
        self.data["tokens"] = tokens
        self.data["user"] = user
        if server:
            self.data["server"] = server
        self.save()

    def update_user(self, user: dict) -> None:
        self.data["user"] = user
        self.save()

    def set_server(self, server: str) -> None:
        self.data["server"] = server
        self.save()

    def clear(self) -> None:
        self.data = {}
        self.save()


session = Session()
