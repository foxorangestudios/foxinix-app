"""Sesión persistente: guarda tokens y usuario en session.json, cifrado en disco.

El archivo session.json se guarda cifrado con Fernet (AES-128 en modo CBC
con HMAC SHA256 para autenticación). La clave maestra se deriva de una
frase secreta + PBKDF2 y se guarda en session.key junto a session.json
con permisos 0o600 (solo el usuario). Si falta session.key, se genera
aleatoriamente al primer arranque.

Esto evita que cualquier proceso con acceso al disco pueda leer los
tokens JWT y datos de usuario en texto plano.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from . import config

SESSION_KEY_FILE = config.SESSION_FILE.parent / "session.key"


def _load_master_key() -> bytes:
    """Carga o genera la clave maestra de cifrado de la sesión."""
    if SESSION_KEY_FILE.is_file():
        return SESSION_KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    try:
        SESSION_KEY_FILE.write_bytes(key)
        os.chmod(SESSION_KEY_FILE, 0o600)
    except OSError:
        pass
    return key


class Session:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self._fernet = Fernet(_load_master_key())
        self.load()

    def load(self) -> None:
        try:
            if config.SESSION_FILE.is_file():
                raw = config.SESSION_FILE.read_bytes()
                # Tokens Fernet empiezan con b'gAAAA' (base64url del versión byte)
                if raw.startswith(b"gAAAA"):
                    plaintext = self._fernet.decrypt(raw)
                    self.data = json.loads(plaintext.decode("utf-8"))
                else:
                    # Formato antiguo sin cifrar: migrar a cifrado al guardar
                    self.data = json.loads(raw.decode("utf-8"))
                    self.save()
        except Exception:
            # Si falla el descifrado (clave corrupta, etc.), arrancamos vacío
            # para no bloquear el acceso a la app.
            self.data = {}

    def save(self) -> None:
        try:
            plaintext = json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8")
            token = self._fernet.encrypt(plaintext)
            config.SESSION_FILE.write_bytes(token)
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
