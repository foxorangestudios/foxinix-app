"""Usuarios: perfiles públicos y búsqueda de contactos."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .. import db, medialink
from ..auth import current_user

router = APIRouter(prefix="/api/users", tags=["users"])


def user_brief(
    u: dict[str, Any], media: dict[int, dict[str, Any]] | None = None
) -> dict[str, Any]:
    # "invisible": aparece desconectado aunque tenga WS abierto (W6).
    visible_online = (int(time.time()) - u.get("last_seen", 0)) < 300
    if (u.get("status_preset") or "") == "invisible":
        visible_online = False
    # W45/P1: al armar la lista de chats se precargan los media en un
    # solo SELECT; con media=None se mantiene el acceso puntual de siempre.
    if media is None:
        avatar = medialink.media_url_by_id(u.get("avatar_media_id"), "profile")
        banner = medialink.media_url_by_id(u.get("banner_media_id"), "profile")
    else:
        avatar = medialink.media_url(media.get(u.get("avatar_media_id")), "profile")
        banner = medialink.media_url(media.get(u.get("banner_media_id")), "profile")
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"] or u["username"],
        "avatar_url": avatar,
        "banner_url": banner,
        "banner_position": int(
            u.get("banner_position") if u.get("banner_position") is not None else 50
        ),
        "bio": u.get("bio", ""),
        "status_text": u.get("status_text", ""),
        "status_preset": u.get("status_preset", ""),
        "online": visible_online,
        "last_seen": u.get("last_seen", 0),
        "created_at": u.get("created_at", 0),
    }


@router.get("/me")
def me(user: dict = Depends(current_user)) -> dict[str, Any]:
    # /me es de la propia cuenta: además incluye el correo y la marca del
    # último cambio de @usuario (W59; no va en perfiles públicos).
    return {"user": {**user_brief(user), "email": user["email"],
                     "username_changed_at": user.get("username_changed_at", 0)}}


@router.get("/search")
def search(q: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Busca contactos por username o nombre para mostrar (mínimo 2 chars)."""
    q = q.strip().lower()[:50]      # W14: tope del patrón LIKE
    if len(q) < 2:
        return {"results": []}
    like = f"{q}%"
    rows = db.rows(
        "SELECT * FROM users WHERE email_verified = 1 AND id != ?"
        " AND (username LIKE ? OR LOWER(display_name) LIKE ?)"
        # W28e: quien me bloqueó no aparece en mi búsqueda; los que YO
        # bloqueé sí (para poder llegar a su perfil y desbloquearlos).
        " AND NOT EXISTS (SELECT 1 FROM blocks bl"
        "   WHERE bl.blocker_id = ? AND bl.blocked_id = users.id)"
        " ORDER BY username LIMIT 20",
        (user["id"], like, f"{q}%", user["id"]),
    )
    return {"results": [user_brief(r) for r in rows]}


def _relation(me_id: int, other_id: int) -> str:
    """Estado de la relación entre dos cuentas para los enlaces públicos."""
    if me_id == other_id:
        return "me"
    # W65: un bloqueo manda sobre una amistad previa; el enlace directo
    # no debe ofrecer "Mensaje"/"Enviar solicitud" a quien está bloqueado.
    if db.one(
        "SELECT 1 AS x FROM blocks"
        " WHERE (blocker_id = ? AND blocked_id = ?)"
        "    OR (blocker_id = ? AND blocked_id = ?)",
        (me_id, other_id, other_id, me_id),
    ):
        return "blocked"
    if db.one(
        "SELECT 1 AS x FROM friend_requests WHERE status = 'accepted'"
        " AND ((from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?))",
        (me_id, other_id, other_id, me_id),
    ):
        return "friend"
    if db.one(
        "SELECT 1 AS x FROM friend_requests WHERE status = 'pending'"
        " AND from_user = ? AND to_user = ?",
        (me_id, other_id),
    ):
        return "sent"
    if db.one(
        "SELECT 1 AS x FROM friend_requests WHERE status = 'pending'"
        " AND from_user = ? AND to_user = ?",
        (other_id, me_id),
    ):
        return "received"
    return "none"


@router.get("/id/{user_id}")
def profile_by_id(user_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Perfil público por ID numérico (el que viaja en /app/user/<id>).

    Incluye el estado de amistad para que un enlace directo pueda abrir
    el MD, mostrar el perfil o enviar la solicitud automáticamente sin
    depender de que la lista de Personas ya esté cargada en el cliente.
    """
    u = db.one(
        "SELECT * FROM users WHERE id = ? AND email_verified = 1",
        (user_id,),
    )
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    return {"user": user_brief(u), "relation": _relation(user["id"], u["id"])}


@router.get("/{username}")
def profile(username: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    u = db.one(
        "SELECT * FROM users WHERE username = ? AND email_verified = 1",
        (username.strip().lower(),),
    )
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    return {"user": user_brief(u)}
