"""Usuarios: perfiles públicos y búsqueda de contactos."""
from __future__ import annotations

import base64
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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


@router.get("/{username}")
def profile(username: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    u = db.one(
        "SELECT * FROM users WHERE username = ? AND email_verified = 1",
        (username.strip().lower(),),
    )
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    return {"user": user_brief(u)}


# ---------------------------------------------- W29f: claves E2E (ECDH)

class E2EKeyIn(BaseModel):
    # P-256 sin comprimir = 65 B → base64 = 88 chars (+ relleno '=').
    public_key: str = Field(min_length=88, max_length=120)


@router.put("/me/e2e-key")
def put_e2e_key(body: E2EKeyIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Publica MI clave pública ECDH. La privada jamás sale del
    navegador (IndexedDB del usuario): aquí sólo se reenvía ésta."""
    try:
        raw = base64.b64decode(body.public_key, validate=True)
    except Exception:
        raise HTTPException(422, "La clave pública no es base64 válido")
    if len(raw) != 65 or raw[0] != 4:
        raise HTTPException(422, "Se espera una clave P-256 sin comprimir (65 B)")
    db.run(
        "INSERT OR REPLACE INTO e2e_keys (user_id, pubkey, created_at)"
        " VALUES (?, ?, ?)",
        (user["id"], body.public_key, int(time.time())),
    )
    return {"ok": True}


@router.get("/{username}/e2e-key")
def get_e2e_key(username: str, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Clave pública E2E de OTRO usuario (null si aún no la publicó)."""
    u = db.one(
        "SELECT id FROM users WHERE username = ? AND email_verified = 1",
        (username.strip().lower(),),
    )
    if not u:
        raise HTTPException(404, "Usuario no encontrado")
    row = db.one("SELECT pubkey FROM e2e_keys WHERE user_id = ?", (u["id"],))
    return {"public_key": row["pubkey"] if row else None}
