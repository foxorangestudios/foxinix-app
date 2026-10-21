"""Dependencias FastAPI: extracción y validación de tokens."""
from __future__ import annotations

import time
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import db, security

_bearer = HTTPBearer(auto_error=False)


def _load_user(payload: dict[str, Any]) -> dict[str, Any]:
    user = db.one("SELECT * FROM users WHERE id = ?", (payload.get("sub", ""),))
    if not user:
        raise HTTPException(401, "Sesión inválida")
    if user["token_version"] != payload.get("tv"):
        raise HTTPException(401, "Sesión expirada, vuelve a iniciar sesión")
    return user


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Usuario autenticado (requiere scope 'full' — cuenta verificada)."""
    if not creds:
        raise HTTPException(401, "Falta el token de autorización")
    payload = security.decode(creds.credentials)
    if not payload:
        # Token vencido o ilegible → 401: el cliente refresca y reintenta.
        # (Antes era 403 y la UI confundía "sesión vencida" con "cuenta sin
        # verificar": reabría la pantalla de verificación con un token muerto.)
        raise HTTPException(401, "Sesión expirada, vuelve a iniciar sesión")
    if payload.get("scope") != "full":
        raise HTTPException(403, "Verifica tu correo para continuar")
    user = _load_user(payload)
    user["_scope"] = "full"
    return user


def pending_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Usuario autenticado aunque NO haya verificado el correo.

    Alcance limitado: perfil y verificación (ver routers/auth.py).
    """
    if not creds:
        raise HTTPException(401, "Falta el token de autorización")
    payload = security.decode(creds.credentials)
    if not payload:
        raise HTTPException(401, "Sesión expirada, vuelve a iniciar sesión")
    if payload.get("scope") not in ("full", "pending"):
        raise HTTPException(401, "Token inválido")
    user = _load_user(payload)
    user["_scope"] = payload["scope"]
    return user


_seen_written: dict[int, float] = {}


def touch_last_seen(user_id: int, force: bool = False) -> None:
    """Actualiza last_seen, como máximo ~1 vez por 30 s por usuario.

    Sin el throttle, un flood de pings/seen por la WS generaría una
    escritura en disco por cada mensaje (amplificación de abuso).

    force=True (solo al conectar la WS) salta el throttle: abrir la conexión
    es un evento real de presencia (uno por connect, con auth) y debe dejar
    la marca exacta; el throttle sigue protegiendo el camino de alta
    frecuencia (pings/seen por mensaje).
    """
    now = time.time()
    last = _seen_written.get(user_id)
    if not force and last is not None and now - last < 30:
        return
    if len(_seen_written) > 10000:            # poda defensiva de memoria
        _seen_written.clear()
    _seen_written[user_id] = now
    db.execute("UPDATE users SET last_seen = ? WHERE id = ?", (int(now), user_id))
