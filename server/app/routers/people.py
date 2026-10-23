"""W27: panel Personas/Amigos — amigos conectados y solicitudes de amistad
(enviadas y recibidas). Aceptar una solicitud crea (o reutiliza) el DM."""
from __future__ import annotations

import math
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, medialink, ratelimit
from ..auth import current_user
from ..realtime import hub

router = APIRouter(prefix="/api/people", tags=["people"])


def _pub(u: dict[str, Any], online: bool) -> dict[str, Any]:
    avatar = None
    if u.get("avatar_media_id"):
        avatar = medialink.media_url_by_id(u["avatar_media_id"], "profile")
    banner = None
    if u.get("banner_media_id"):
        banner = medialink.media_url_by_id(u["banner_media_id"], "profile")
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"] or u["username"],
        "avatar_url": avatar,
        "banner_url": banner,
        "online": online,
        "last_seen": u.get("last_seen") or 0,
        "status_text": u.get("status_text") or "",
        "status_preset": u.get("status_preset") or "",
    }


def _online_map(ids: list[int]) -> dict[int, bool]:
    """Estado real de conexión: en el hub Y no invisible (coherente con el
    snapshot de presencia W26: los invisibles nunca se ven en línea)."""
    if not ids:
        return {}
    qs = ",".join("?" for _ in ids)
    invis = {
        r["id"]
        for r in db.rows(
            "SELECT id FROM users WHERE status_preset = 'invisible'"
            f" AND id IN ({qs})",
            tuple(ids),
        )
    }
    return {i: hub.is_online(i) and i not in invis for i in ids}


def _friend_rows(uid: int) -> list[dict[str, Any]]:
    return db.rows(
        "SELECT u.* FROM friend_requests fr"
        " JOIN users u ON u.id = CASE WHEN fr.from_user = ? THEN fr.to_user"
        "  ELSE fr.from_user END"
        " WHERE fr.status = 'accepted' AND (fr.from_user = ? OR fr.to_user = ?)"
        " ORDER BY lower(COALESCE(NULLIF(u.display_name, ''), u.username))",
        (uid, uid, uid),
    )


def _req_rows(uid: int, outgoing: bool) -> list[dict[str, Any]]:
    col = "from_user" if outgoing else "to_user"
    other = "to_user" if outgoing else "from_user"
    return db.rows(
        f"SELECT fr.id AS rid, fr.created_at, u.* FROM friend_requests fr"  # noqa: S608
        f" JOIN users u ON u.id = fr.{other}"
        f" WHERE fr.status = 'pending' AND fr.{col} = ?"
        " ORDER BY fr.created_at DESC",
        (uid,),
    )


def _are_friends(a: int, b: int) -> bool:
    return bool(db.one(
        "SELECT 1 AS x FROM friend_requests WHERE status = 'accepted'"
        " AND ((from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?))",
        (a, b, b, a),
    ))


def _blocked_pair(a: int, b: int) -> bool:
    """W28e: ¿hay un bloqueo en cualquier dirección entre a y b? Mientras
    dure, no hay solicitudes de amistad ni mensajes directos entre ellos."""
    return bool(db.one(
        "SELECT 1 AS x FROM blocks"
        " WHERE (blocker_id = ? AND blocked_id = ?)"
        "    OR (blocker_id = ? AND blocked_id = ?)",
        (a, b, b, a),
    ))


def _ensure_dm(uid_a: int, uid_b: int) -> dict[str, Any]:
    """Crea (o reutiliza) el DM entre dos usuarios — misma lógica y misma
    carrera cubierta por el dm_key único que create_dm de chats.py."""
    from .chats import chat_brief

    dm_key = ":".join(str(x) for x in sorted((uid_a, uid_b)))
    existing = db.one("SELECT * FROM chats WHERE dm_key = ?", (dm_key,))
    chat_id = existing["id"] if existing else None
    if not existing:
        now = int(time.time())
        try:
            with db.tx() as conn:
                cur = conn.execute(
                    "INSERT INTO chats (type, dm_key, created_by, created_at)"
                    " VALUES ('dm', ?, ?, ?)",
                    (dm_key, uid_a, now),
                )
                chat_id = cur.lastrowid
                for uid in (uid_a, uid_b):
                    conn.execute(
                        "INSERT INTO chat_members (chat_id, user_id, joined_at)"
                        " VALUES (?, ?, ?)",
                        (chat_id, uid, now),
                    )
        except Exception:
            existing = db.one("SELECT * FROM chats WHERE dm_key = ?", (dm_key,))
            if not existing:
                raise
            chat_id = existing["id"]
    chat = db.one("SELECT * FROM chats WHERE id = ?", (chat_id,))
    # Aceptar una solicitud reabre un MD que cualquiera hubiera borrado o
    # archivado: ambas partes acaban de dar su consentimiento.
    db.run(
        "UPDATE chat_members SET hidden_at = 0, archived = 0"
        " WHERE chat_id = ? AND user_id IN (?, ?)",
        (chat_id, uid_a, uid_b),
    )
    if not existing:
        hub.notify_chat_created(chat_id, [uid_a, uid_b])
    return chat_brief(chat, uid_a)


def _payload(uid: int) -> dict[str, Any]:
    friends = _friend_rows(uid)
    on = _online_map([r["id"] for r in friends])
    sent = _req_rows(uid, True)
    recv = _req_rows(uid, False)
    son = _online_map([r["id"] for r in sent] + [r["id"] for r in recv])

    def brief(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"id": r["rid"], "created_at": r["created_at"],
             "user": _pub(r, son.get(r["id"], False))}
            for r in rows
        ]

    return {
        "friends": [_pub(r, on.get(r["id"], False)) for r in friends],
        "sent": brief(sent),
        "received": brief(recv),
    }


class ReqIn(BaseModel):
    username: str = Field(min_length=1, max_length=50)


@router.get("")
def people(user: dict = Depends(current_user)) -> dict[str, Any]:
    return _payload(user["id"])


@router.post("/requests", status_code=201)
def send_request(body: ReqIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    espera = ratelimit.REQUESTS.take(user["id"])
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": math.ceil(espera)})
    peer = db.one(
        "SELECT * FROM users WHERE username = ? AND email_verified = 1",
        (body.username.strip().lower(),),
    )
    if not peer:
        raise HTTPException(404, "Usuario no encontrado")
    if peer["id"] == user["id"]:
        raise HTTPException(400, "No puedes enviarte una solicitud")
    if _blocked_pair(user["id"], peer["id"]):
        raise HTTPException(403, "Usuario bloqueado")
    if _are_friends(user["id"], peer["id"]):
        raise HTTPException(409, "Ya son amigos")
    dup = db.one(
        "SELECT * FROM friend_requests WHERE status = 'pending'"
        " AND ((from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?))",
        (user["id"], peer["id"], peer["id"], user["id"]),
    )
    if dup:
        raise HTTPException(409, "Ya hay una solicitud pendiente")
    rid = db.execute(
        "INSERT INTO friend_requests (from_user, to_user, created_at)"
        " VALUES (?, ?, ?)",
        (user["id"], peer["id"], int(time.time())),
    )
    hub.emit_to_user(peer["id"], {"type": "people", "kind": "request",
                                  "from": user["username"]})
    hub.emit_to_user(user["id"], {"type": "people"})
    return {"id": rid}


@router.post("/requests/{rid}/accept")
def accept_request(rid: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    req = db.one("SELECT * FROM friend_requests WHERE id = ?", (rid,))
    if not req or req["to_user"] != user["id"]:
        raise HTTPException(404, "Solicitud no encontrada")
    if req["status"] != "pending":
        raise HTTPException(409, "La solicitud ya fue respondida")
    db.run(
        "UPDATE friend_requests SET status = 'accepted', answered_at = ?"
        " WHERE id = ? AND status = 'pending'",
        (int(time.time()), rid),
    )
    chat = _ensure_dm(user["id"], req["from_user"])
    for uid in (user["id"], req["from_user"]):
        hub.emit_to_user(uid, {"type": "people"})
    return {"chat": chat}


@router.post("/requests/{rid}/reject")
def reject_request(rid: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    req = db.one("SELECT * FROM friend_requests WHERE id = ?", (rid,))
    if not req or req["to_user"] != user["id"] or req["status"] != "pending":
        raise HTTPException(404, "Solicitud no encontrada")
    db.run("DELETE FROM friend_requests WHERE id = ?", (rid,))
    for uid in (user["id"], req["from_user"]):
        hub.emit_to_user(uid, {"type": "people"})
    return {"ok": True}


@router.delete("/requests/{rid}")
def cancel_request(rid: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    req = db.one("SELECT * FROM friend_requests WHERE id = ?", (rid,))
    if not req or req["from_user"] != user["id"] or req["status"] != "pending":
        raise HTTPException(404, "Solicitud no encontrada")
    db.run("DELETE FROM friend_requests WHERE id = ?", (rid,))
    hub.emit_to_user(req["to_user"], {"type": "people"})
    return {"ok": True}


@router.delete("/friends/{fid}")
def unfriend(fid: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    if not _are_friends(user["id"], fid):
        raise HTTPException(404, "No hay amistad con ese usuario")
    db.run(
        "DELETE FROM friend_requests WHERE status = 'accepted'"
        " AND ((from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?))",
        (user["id"], fid, fid, user["id"]),
    )
    for uid in (user["id"], fid):
        hub.emit_to_user(uid, {"type": "people"})
        # El MD deja de listarse/abrirse: refrescar la lista al toque.
        hub.emit_to_user(uid, {"type": "chat_updated", "chat_id": 0})
    return {"ok": True}


# ------------------------------------------- W28e: bloquear usuarios


class BlockIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)


@router.get("/blocks")
def list_blocks(user: dict = Depends(current_user)) -> dict[str, Any]:
    """Ids de los usuarios que yo bloqueé (los que me bloquearon a mí no
    aparecen en la búsqueda ni mandarme solicitudes, pero no guardo su lista)."""
    rows = db.rows(
        "SELECT blocked_id FROM blocks WHERE blocker_id = ?"
        " ORDER BY created_at DESC",
        (user["id"],),
    )
    return {"user_ids": [r["blocked_id"] for r in rows]}


@router.post("/block", status_code=201)
def block_user(body: BlockIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Bloquea al usuario: rompe amistad y solicitudes pendientes e impide
    solicitudes y mensajes directos en ambas direcciones (W28e)."""
    peer = db.one(
        "SELECT * FROM users WHERE username = ? AND email_verified = 1",
        (body.username.strip().lower(),),
    )
    if not peer:
        raise HTTPException(404, "Usuario no encontrado")
    if peer["id"] == user["id"]:
        raise HTTPException(400, "No puedes bloquearte a ti mismo")
    db.run(
        "INSERT OR IGNORE INTO blocks (blocker_id, blocked_id, created_at)"
        " VALUES (?, ?, ?)",
        (user["id"], peer["id"], int(time.time())),
    )
    db.run(
        "DELETE FROM friend_requests"
        " WHERE (from_user = ? AND to_user = ?)"
        "    OR (from_user = ? AND to_user = ?)",
        (user["id"], peer["id"], peer["id"], user["id"]),
    )
    for uid in (user["id"], peer["id"]):
        hub.emit_to_user(uid, {"type": "people"})
        hub.emit_to_user(uid, {"type": "chat_updated", "chat_id": 0})
    return {"ok": True, "blocked": peer["id"]}


@router.post("/unblock")
def unblock_user(body: BlockIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Quita el bloqueo (idempotente): vuelven a poder ser amigos y escribirse."""
    peer = db.one("SELECT id FROM users WHERE username = ?", (body.username.strip().lower(),))
    if not peer:
        raise HTTPException(404, "Usuario no encontrado")
    db.run(
        "DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?",
        (user["id"], peer["id"]),
    )
    for uid in (user["id"], peer["id"]):
        hub.emit_to_user(uid, {"type": "people"})
    return {"ok": True, "blocked": peer["id"]}
