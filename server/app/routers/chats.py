"""Chats: conversaciones 1:1, grupos y mensajes."""
from __future__ import annotations

import asyncio
import base64
import json
import math
import time
import mimetypes
import re
import secrets
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from .. import config, db, medialink, ratelimit
from ..auth import current_user
from ..realtime import hub
from . import media as media_mod
from .people import _blocked_pair   # W28e: corta directos con bloqueo activo
from .users import user_brief

router = APIRouter(prefix="/api/chats", tags=["chats"])


# ------------------------------------------------------------ helpers

def _member_row(chat_id: int, user_id: int) -> dict[str, Any] | None:
    return db.one(
        "SELECT * FROM chat_members WHERE chat_id = ? AND user_id = ?",
        (chat_id, user_id),
    )


def _require_member(chat_id: int, user_id: int) -> dict[str, Any]:
    chat = db.one("SELECT * FROM chats WHERE id = ?", (chat_id,))
    if not chat:
        raise HTTPException(404, "Chat no encontrado")
    if not _member_row(chat_id, user_id):
        raise HTTPException(403, "No eres miembro de este chat")
    return chat


def _next_seq(conn, chat_id: int) -> int:
    """Asigna el siguiente seq SIN reutilizar huecos.

    W45: antes era MAX(seq)+1. Al borrar el último mensaje, el siguiente
    reutilizaba su seq; clientes con el mensaje viejo podían confundir
    lecturas/entregas y ocultar mensajes. chats.last_seq solo sube.
    """
    # MAX(last_seq, MAX(seq)) cubre también datos viejos/importados donde
    # last_seq no se haya backfilleado.
    conn.execute(
        "UPDATE chats SET last_seq = MAX(last_seq, COALESCE("
        " (SELECT MAX(seq) FROM messages WHERE chat_id = ?), 0)) + 1"
        " WHERE id = ?",
        (chat_id, chat_id),
    )
    row = conn.execute(
        "SELECT last_seq FROM chats WHERE id = ?", (chat_id,)
    ).fetchone()
    return int(row["last_seq"]) if row else 1


def _mark_delivered(chat_id: int, user_id: int, seq: int) -> None:
    """W12: 'recibido' — el destinatario bajó esos mensajes (fetch) o le
    llegaron por su WS conectado. Solo sube, nunca baja."""
    if seq:
        db.execute(
            "UPDATE chat_members SET last_delivered_seq = MAX(last_delivered_seq, ?)"
            " WHERE chat_id = ? AND user_id = ?",
            (seq, chat_id, user_id),
        )


def _peaks_out(raw: Any) -> list[int] | None:
    """W13: la onda de voz viaja como JSON "[n,…]"; cualquier basura → None."""
    if not raw:
        return None
    try:
        arr = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return arr if isinstance(arr, list) and arr else None


def _mentions_list(col) -> list[int]:
    """',3,5,' → [3, 5] (columna messages.mentions, W28b)."""
    return [int(x) for x in (col or "").split(",") if x]


def _mentions_col(ids: list[int]) -> str:
    return "," + ",".join(str(i) for i in ids) + "," if ids else ""


def _parse_mentions(chat_id: int, text: str) -> list[int]:
    """Ids de los MIEMBROS del grupo citados como @usuario en el texto.

    Sólo cuenta usuarios reales del chat: escribir "@cualquiera" sin ser
    miembro no genera mención.
    W37e: menciones globales — @everyone/@todos cita a TODOS los miembros
    y @online/@activos sólo a los conectados AHORA. Se reconocen en
    cualquier idioma (escribe la forma que escribas) y el cliente la
    localiza al mostrarla."""
    text = text or ""
    rows = db.rows(
        "SELECT u.id, u.username FROM chat_members cm"
        " JOIN users u ON u.id = cm.user_id WHERE cm.chat_id = ?",
        (chat_id,),
    )
    if re.search(r"@(everyone|todos)\b", text, re.IGNORECASE):
        return [r["id"] for r in rows]
    if re.search(r"@(online|activos)\b", text, re.IGNORECASE):
        return [r["id"] for r in rows if hub.is_online(r["id"])]
    names = {n.lower() for n in re.findall(r"@([A-Za-z0-9_.]{3,20})", text)}
    if not names:
        return []
    return [r["id"] for r in rows if (r["username"] or "").lower() in names]


def message_out(
    m: dict[str, Any],
    users: dict[int, dict[str, Any]] | None = None,
    medias: dict[int, dict[str, Any]] | None = None,
    replies: dict[int, dict[str, Any]] | None = None,
    reactions_by_msg: dict[int, list[dict[str, Any]]] | None = None,
    roles: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Serializa un mensaje para la API.

    Los mapas opcionales los usa list_chats() para resolver 50/100/1000
    mensajes con unos pocos SELECT en vez de 5-6 consultas por fila.
    Con los mapas en None se mantiene el comportamiento puntual.

    W46: `roles` (user_id → rol EN ESTE CHAT) permite pintar la etiqueta
    [Admin] del remitente sin una consulta extra por mensaje. En llamadas
    puntuales sin mapa se resuelve solo para ese mensaje.
    """
    if users is None:
        sender = db.one(
            "SELECT * FROM users WHERE id = ?", (m["sender_id"],)
        ) if m["sender_id"] else None
    else:
        sender = users.get(m["sender_id"]) if m["sender_id"] else None
    sender_role = None
    if sender:
        if roles is not None:
            sender_role = roles.get(sender["id"])
        elif users is None:
            role_row = db.one(
                "SELECT role FROM chat_members WHERE chat_id = ? AND user_id = ?",
                (m["chat_id"], sender["id"]),
            )
            sender_role = role_row["role"] if role_row else None
    media = None
    if m.get("media_id"):
        row = (db.one("SELECT * FROM media WHERE id = ?", (m["media_id"],))
               if medias is None else medias.get(m["media_id"]))
        if row:
            media = {
                "id": row["id"],
                "url": medialink.media_url(row, "file"),
                "mime": row["mime"],
                "size": row["size"],
                "name": row["name"],
                # W22: resolución de la imagen ({} si no aplica/conocida)
                **media_mod.row_dims(row),
            }
    reply = None
    if m.get("reply_to"):
        orig = (db.one("SELECT * FROM messages WHERE id = ?", (m["reply_to"],))
                if replies is None else replies.get(m["reply_to"]))
        # W37f (auditoría): el citado DEBE ser del mismo chat — sin esto,
        # un reply_to ajen permitía leer 120 chars de cualquier mensaje.
        if orig and orig["chat_id"] == m.get("chat_id"):
            if users is None:
                orig_sender = db.one(
                    "SELECT username, display_name FROM users WHERE id = ?",
                    (orig["sender_id"],),
                ) if orig["sender_id"] else None
            else:
                orig_sender = users.get(orig["sender_id"]) if orig["sender_id"] else None
            reply = {
                "id": orig["id"],
                "seq": orig["seq"],
                # W45: una cita de un spoiler no debe revelar el texto.
                "body": "Spoiler" if orig.get("spoiler") else orig["body"][:120],
                "spoiler": bool(orig.get("spoiler")),
                "kind": orig["kind"],
                "sender": (orig_sender["display_name"] or orig_sender["username"])
                if orig_sender else None,
            }
    if reactions_by_msg is None:
        reactions = db.rows(
            # W29c: con nombre para el tooltip "quién reaccionó" (hover)
            "SELECT r.emoji, r.user_id, u.username,"
            " COALESCE(NULLIF(TRIM(u.display_name), ''), u.username) AS name"
            " FROM reactions r JOIN users u ON u.id = r.user_id"
            " WHERE r.message_id = ?",
            (m["id"],),
        )
    else:
        reactions = reactions_by_msg.get(m["id"], [])
    sender_out = user_brief(sender, medias) if sender else None
    if sender_out is not None and sender_role:
        sender_out["role"] = sender_role
    return {
        "id": m["id"],
        "seq": m["seq"],
        "chat_id": m["chat_id"],
        "kind": m["kind"],
        "body": m["body"],
        "media": media,
        "reply_to": reply,
        "client_msg_id": m["client_msg_id"],
        "created_at": m["created_at"],
        "edited_at": m.get("edited_at") or 0,
        "forwarded": bool(m.get("forwarded")),   # W13: reenviado
        "mentions": _mentions_list(m.get("mentions")),   # W28b: @menciones
        "pinned": bool(m.get("pinned_at")),     # W28c: fijado en el chat
        "pinned_by": m.get("pinned_by"),        # W28c: quién lo fijó
        "peaks": _peaks_out(m.get("peaks")),     # W13: onda de voz
        "dur": m.get("dur"),                    # W13: duración de la nota (s)
        "spoiler": bool(m.get("spoiler")),      # W29d: tapado hasta tocar
        # W29f: blob cifrado (si existe, body = "[Mensaje cifrado]")
        "e2e": (
            {"iv": m.get("e2e_iv"), "ct": m.get("e2e_ct")}
            if m.get("e2e_ct") else None
        ),
        "sender": sender_out,
        "reactions": reactions,
    }


def chat_brief(chat: dict[str, Any], me_id: int) -> dict[str, Any]:
    if chat["type"] == "dm":
        members = db.rows(
            "SELECT u.* FROM chat_members cm JOIN users u ON u.id = cm.user_id"
            " WHERE cm.chat_id = ? AND cm.user_id != ?",
            (chat["id"], me_id),
        )
    else:
        members = db.rows(
            "SELECT u.* FROM chat_members cm JOIN users u ON u.id = cm.user_id"
            " WHERE cm.chat_id = ?",
            (chat["id"],),
        )

    # W12: una sola query para el conteo y las semillas de palomitas
    # (peer_read_seq / peer_delivered_seq = máx. de los OTROS miembros).
    cmembers = db.rows(
        "SELECT user_id, role, last_read_seq, last_delivered_seq FROM chat_members"
        " WHERE chat_id = ?",
        (chat["id"],),
    )
    peer_read = 0
    peer_deliv = 0
    # W29c: el MÍNIMO entre los demás = "todos recibieron/leyeron"
    # (para ✓✓ de grupo; el máximo de arriba sigue sembrando el DM).
    peer_read_min = 0
    peer_deliv_min = 0
    others = 0
    for cm in cmembers:
        if cm["user_id"] != me_id:
            others += 1
            if cm["last_read_seq"] > peer_read:
                peer_read = cm["last_read_seq"]
            if cm["last_delivered_seq"] > peer_deliv:
                peer_deliv = cm["last_delivered_seq"]
            if others == 1 or cm["last_read_seq"] < peer_read_min:
                peer_read_min = cm["last_read_seq"]
            if others == 1 or cm["last_delivered_seq"] < peer_deliv_min:
                peer_deliv_min = cm["last_delivered_seq"]

    last = db.one(
        "SELECT * FROM messages WHERE chat_id = ? ORDER BY seq DESC LIMIT 1",
        (chat["id"],),
    )
    mine = _member_row(chat["id"], me_id) or {"last_read_seq": 0}
    unread = db.one(
        "SELECT COUNT(*) AS c FROM messages WHERE chat_id = ? AND seq > ? AND sender_id != ?",
        (chat["id"], mine["last_read_seq"], me_id),
    )["c"]
    # W28b: cuántos de esos no leídos me citan con @usuario (grupos)
    unread_m = 0
    if chat["type"] != "dm":
        unread_m = db.one(
            "SELECT COUNT(*) AS c FROM messages WHERE chat_id = ? AND seq > ?"
            " AND sender_id != ? AND mentions LIKE ?",
            (chat["id"], mine["last_read_seq"], me_id, f"%,{me_id},%"),
        )["c"]

    if chat["type"] == "dm":
        peer = members[0] if members else None
        title = user_brief(peer) if peer else {"display_name": "Usuario eliminado"}
        avatar = medialink.media_url_by_id(peer["avatar_media_id"], "profile") if peer else None
    else:
        title = {
            "id": None,
            "username": None,
            "display_name": chat["title"] or "Grupo",
            "bio": "",
            "status_text": "",
        }
        avatar = medialink.media_url_by_id(chat.get("avatar_media_id"), "profile")

    roles = {cm["user_id"]: cm["role"] for cm in cmembers}
    last_out = message_out(last, roles=roles) if last else None
    if last_out and last_out.get("spoiler"):
        # W45: el preview de la lista no transporta el texto del spoiler.
        last_out["body"] = "Spoiler"
    return {
        "id": chat["id"],
        "type": chat["type"],
        "title": title,
        "avatar_url": avatar,
        "member_count": len(cmembers),
        "last_message": last_out,
        "unread": unread,
        "unread_mentions": unread_m,     # W28b: badge de @menciones
        "my_role": (mine or {}).get("role", "member"),
        "pinned": bool((mine or {}).get("pinned")),   # W13: fijado en MI lista
        "muted": bool((mine or {}).get("muted")),     # W13: silenciado por mí
        "peer_read_seq": peer_read,        # W12: semilla de ✓✓ azul (leído)
        "peer_delivered_seq": peer_deliv,  # W12: semilla de ✓✓ (recibido)
        # W29c: mínimos = "todos" (✓✓ de grupos; en DM = máx)
        "peer_read_min_seq": peer_read_min,
        "peer_delivered_min_seq": peer_deliv_min,
    }


# --------------------------------------------------- P1: lista de chats en lote
# chat_brief() resuelve cada chat con ~8 consultas (miembros, último
# mensaje, no leídos, remitente, media, reacciones...). Con 100 chats eran
# ~700 consultas y con 1.000 chats ~7.000. Estas variantes precargan todo
# con unos pocos SELECT y reutilizan message_out(user/medias/...).

def _chunks(values: list[Any], size: int = 400):
    for i in range(0, len(values), size):
        yield values[i:i + size]


def _rows_in(
    sql_before: str,
    ids: list[Any],
    sql_after: str = "",
    params_before: tuple = (),
    params_after: tuple = (),
) -> list[dict[str, Any]]:
    """db.rows() con `... IN (?,...)` troceado (límite de variables SQLite)."""
    out: list[dict[str, Any]] = []
    uniq = list(dict.fromkeys(ids))
    if not uniq:
        return out
    for chunk in _chunks(uniq):
        marks = "(" + ",".join("?" for _ in chunk) + ")"
        out.extend(db.rows(
            sql_before + marks + sql_after,
            tuple(params_before) + tuple(chunk) + tuple(params_after),
        ))
    return out


def _chat_briefs(chats: list[dict[str, Any]], me_id: int) -> list[dict[str, Any]]:
    """Versión por lote de chat_brief() para GET /api/chats."""
    chat_ids = [c["id"] for c in chats]
    if not chat_ids:
        return []

    cm_rows = _rows_in(
        "SELECT * FROM chat_members WHERE chat_id IN ", chat_ids
    )
    cmembers_by_chat: dict[int, list[dict[str, Any]]] = {}
    roles_by_chat: dict[int, dict[int, str]] = {}
    for cm in cm_rows:
        cmembers_by_chat.setdefault(cm["chat_id"], []).append(cm)
        roles_by_chat.setdefault(cm["chat_id"], {})[cm["user_id"]] = cm["role"]

    last_rows = _rows_in(
        "SELECT m.* FROM messages m JOIN ("
        " SELECT chat_id, MAX(seq) AS seq FROM messages WHERE chat_id IN ",
        chat_ids,
        " GROUP BY chat_id) x ON x.chat_id = m.chat_id AND x.seq = m.seq",
    )
    last_by_chat = {m["chat_id"]: m for m in last_rows}

    unread_rows = _rows_in(
        "SELECT m.chat_id, COUNT(*) AS c,"
        " SUM(CASE WHEN m.mentions LIKE ? THEN 1 ELSE 0 END) AS mc"
        " FROM messages m JOIN chat_members cm"
        " ON cm.chat_id = m.chat_id AND cm.user_id = ?"
        " WHERE m.chat_id IN ",
        chat_ids,
        " AND m.seq > cm.last_read_seq AND m.sender_id != ?"
        " GROUP BY m.chat_id",
        params_before=(f"%,{me_id},%", me_id),
        params_after=(me_id,),
    )
    unread_by_chat = {r["chat_id"]: r for r in unread_rows}

    reply_ids = [m["reply_to"] for m in last_rows if m.get("reply_to")]
    replies = {r["id"]: r for r in _rows_in(
        "SELECT * FROM messages WHERE id IN ", reply_ids
    )}

    user_ids: list[int] = [cm["user_id"] for cm in cm_rows]
    user_ids += [m["sender_id"] for m in last_rows if m.get("sender_id")]
    user_ids += [r["sender_id"] for r in replies.values() if r.get("sender_id")]
    users = {u["id"]: u for u in _rows_in(
        "SELECT * FROM users WHERE id IN ", user_ids
    )}

    media_ids: list[int] = []
    for m in last_rows:
        if m.get("media_id"):
            media_ids.append(m["media_id"])
    for c in chats:
        if c.get("avatar_media_id"):
            media_ids.append(c["avatar_media_id"])
    for u in users.values():
        if u.get("avatar_media_id"):
            media_ids.append(u["avatar_media_id"])
    medias = {md["id"]: md for md in _rows_in(
        "SELECT * FROM media WHERE id IN ", media_ids
    )}

    msg_ids = [m["id"] for m in last_rows]
    reactions_by_msg: dict[int, list[dict[str, Any]]] = {}
    for r in _rows_in(
        "SELECT r.message_id, r.emoji, r.user_id, u.username,"
        " COALESCE(NULLIF(TRIM(u.display_name), ''), u.username) AS name"
        " FROM reactions r JOIN users u ON u.id = r.user_id"
        " WHERE r.message_id IN ",
        msg_ids,
    ):
        reactions_by_msg.setdefault(r["message_id"], []).append({
            "emoji": r["emoji"],
            "user_id": r["user_id"],
            "username": r["username"],
            "name": r["name"],
        })

    out: list[dict[str, Any]] = []
    for chat in chats:
        cmembers = cmembers_by_chat.get(chat["id"], [])
        if chat["type"] == "dm":
            members = [users[cm["user_id"]] for cm in cmembers
                       if cm["user_id"] != me_id and cm["user_id"] in users]
        else:
            members = [users[cm["user_id"]] for cm in cmembers
                       if cm["user_id"] in users]

        peer_read = peer_deliv = 0
        peer_read_min = peer_deliv_min = 0
        others = 0
        mine = None
        for cm in cmembers:
            if cm["user_id"] == me_id:
                mine = cm
                continue
            others += 1
            if cm["last_read_seq"] > peer_read:
                peer_read = cm["last_read_seq"]
            if cm["last_delivered_seq"] > peer_deliv:
                peer_deliv = cm["last_delivered_seq"]
            if others == 1 or cm["last_read_seq"] < peer_read_min:
                peer_read_min = cm["last_read_seq"]
            if others == 1 or cm["last_delivered_seq"] < peer_deliv_min:
                peer_deliv_min = cm["last_delivered_seq"]

        if chat["type"] == "dm":
            peer = members[0] if members else None
            title = user_brief(peer, medias) if peer else {"display_name": "Usuario eliminado"}
            avatar = medialink.media_url(
                medias.get(peer.get("avatar_media_id")) if peer else None, "profile"
            )
        else:
            title = {
                "id": None,
                "username": None,
                "display_name": chat["title"] or "Grupo",
                "bio": "",
                "status_text": "",
            }
            avatar = medialink.media_url(
                medias.get(chat.get("avatar_media_id")), "profile"
            )

        last = last_by_chat.get(chat["id"])
        ur = unread_by_chat.get(chat["id"]) or {}
        last_out = message_out(
            last, users=users, medias=medias, replies=replies,
            reactions_by_msg=reactions_by_msg,
            roles=roles_by_chat.get(chat["id"], {}),
        ) if last else None
        if last_out and last_out.get("spoiler"):
            last_out["body"] = "Spoiler"
        out.append({
            "id": chat["id"],
            "type": chat["type"],
            "title": title,
            "avatar_url": avatar,
            "member_count": len(cmembers),
            "last_message": last_out,
            "unread": int(ur.get("c") or 0),
            "unread_mentions": (
                int(ur.get("mc") or 0) if chat["type"] != "dm" else 0
            ),
            "my_role": (mine or {}).get("role", "member"),
            "pinned": bool((mine or {}).get("pinned")),
            "muted": bool((mine or {}).get("muted")),
            "peer_read_seq": peer_read,
            "peer_delivered_seq": peer_deliv,
            "peer_read_min_seq": peer_read_min,
            "peer_delivered_min_seq": peer_deliv_min,
        })
    return out


# ------------------------------------------------------------ modelos

class CreateDmIn(BaseModel):
    username: str = Field(max_length=32)


class CreateGroupIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    members: list[str] = Field(default_factory=list, max_length=100)


class E2EBlob(BaseModel):
    """W29f: cuerpo cifrado (AES-GCM). El server NO ve el texto: sólo
    valida tamaño/base64 (blob ≤32 KB) y guarda IV + cifrado."""
    iv: str = Field(max_length=64)       # base64 de 12 B (96 bits) = 16 chars
    ct: str = Field(max_length=46000)    # base64 de ≤32 KB

    @field_validator("iv", "ct")
    @classmethod
    def _b64(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except Exception:
            raise ValueError("no es base64 válido")
        if not raw:
            raise ValueError("blob vacío")
        return v


class SendIn(BaseModel):
    kind: str = "text"  # text | image | file | voice | system
    body: str = Field(default="", max_length=config.MAX_BODY_CHARS)
    media_id: int | None = None
    reply_to: int | None = None
    client_msg_id: str | None = Field(default=None, max_length=64)
    peaks: str | None = Field(default=None, max_length=2048)  # W13: onda de voz (JSON)
    dur: int | None = Field(default=None, ge=1, le=3600)      # W13: duración (voz)
    spoiler: bool = False                 # W29d: el destinatario debe tocar para ver
    e2e: E2EBlob | None = None            # W29f: si viene, body DEBE venir vacío

    @field_validator("peaks")
    @classmethod
    def _peaks(cls, v: Optional[str]) -> Optional[str]:
        # W13: JSON "[n,n,…]" con enteros 0..100 (picos de la grabación).
        if v is None or v == "":
            return None
        try:
            arr = json.loads(v)
        except ValueError:
            raise ValueError("peaks inválido")
        if (
            not isinstance(arr, list)
            or not arr
            or len(arr) > 128
            or any(not isinstance(x, int) or x < 0 or x > 100 for x in arr)
        ):
            raise ValueError("peaks inválido")
        return json.dumps([int(x) for x in arr])


class PinIn(BaseModel):
    pinned: bool


class MuteIn(BaseModel):
    muted: bool


class ForwardIn(BaseModel):
    target_chat_id: int


class ReadIn(BaseModel):
    seq: int = Field(ge=0)
    # W45: con los recibos apagados el usuario igual necesita que su
    # last_read_seq avance (para que la lista no le muestre no leídos);
    # silent evita el broadcast de "leído" a los demás.
    silent: bool = False


class MemberIn(BaseModel):
    username: str = Field(max_length=32)


class MemberRoleIn(BaseModel):
    # W46: sólo se promueve o se quita el rol; el owner no se cambia acá.
    role: str = Field(pattern="^(admin|member)$")


class ReactIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=8)


# ------------------------------------------------------------ endpoints

@router.get("")
def list_chats(user: dict = Depends(current_user)) -> dict[str, Any]:
    chats = db.rows(
        "SELECT c.* FROM chats c JOIN chat_members m ON m.chat_id = c.id"
        " WHERE m.user_id = ? ORDER BY c.created_at DESC",
        (user["id"],),
    )
    out = []
    # P1: una sola pasada batched en vez de chat_brief() por chat.
    for brief, c in zip(_chat_briefs(chats, user["id"]), chats):
        if brief["last_message"] or c["type"] == "dm" or c["title"]:
            out.append(brief)
    # W13: fijados primero; dentro de cada bloque, por último mensaje.
    out.sort(
        key=lambda b: (1 if b["pinned"] else 0,
                       (b["last_message"] or {}).get("created_at", 0)),
        reverse=True,
    )
    return {"chats": out}


@router.post("/dm", status_code=201)
def create_dm(body: CreateDmIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    peer = db.one(
        "SELECT * FROM users WHERE username = ? AND email_verified = 1",
        (body.username.strip().lower(),),
    )
    if not peer:
        raise HTTPException(404, "Usuario no encontrado")
    if peer["id"] == user["id"]:
        raise HTTPException(400, "No puedes chatear contigo mismo")
    if _blocked_pair(user["id"], peer["id"]):
        # W28e: bloqueo activo en cualquier dirección: ni abrir ni usar el DM
        raise HTTPException(403, "Usuario bloqueado")

    dm_key = ":".join(str(x) for x in sorted((user["id"], peer["id"])))
    existing = db.one("SELECT * FROM chats WHERE dm_key = ?", (dm_key,))
    if existing:
        return {"chat": chat_brief(existing, user["id"])}

    # W37f (auditoría): CREATIONS estaba declarado sin usarse — crear
    # DMs es ~1 por minuto sostenido (ráfaga de 3).
    espera = ratelimit.CREATIONS.take(user["id"])
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": math.ceil(espera)})

    now = int(time.time())
    try:
        with db.tx() as conn:
            cur = conn.execute(
                "INSERT INTO chats (type, dm_key, created_by, created_at)"
                " VALUES ('dm', ?, ?, ?)",
                (dm_key, user["id"], now),
            )
            chat_id = cur.lastrowid
            for uid in (user["id"], peer["id"]):
                conn.execute(
                    "INSERT INTO chat_members (chat_id, user_id, joined_at)"
                    " VALUES (?, ?, ?)",
                    (chat_id, uid, now),
                )
    except Exception:
        # carrera: otro request creó el mismo dm_key
        existing = db.one("SELECT * FROM chats WHERE dm_key = ?", (dm_key,))
        if existing:
            return {"chat": chat_brief(existing, user["id"])}
        raise
    chat = db.one("SELECT * FROM chats WHERE id = ?", (chat_id,))
    hub.notify_chat_created(chat_id, [user["id"], peer["id"]])
    return {"chat": chat_brief(chat, user["id"])}


@router.post("/group", status_code=201)
def create_group(body: CreateGroupIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    # W37f: CREATIONS — ~1 por minuto sostenido (ver create_dm).
    espera = ratelimit.CREATIONS.take(user["id"])
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": math.ceil(espera)})
    now = int(time.time())
    member_ids = [user["id"]]
    for uname in body.members:
        u = db.one(
            "SELECT * FROM users WHERE username = ? AND email_verified = 1",
            (uname.strip().lower(),),
        )
        if not u:
            raise HTTPException(404, f"Usuario no encontrado: {uname}")
        if u["id"] not in member_ids:
            member_ids.append(u["id"])

    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO chats (type, title, created_by, created_at) VALUES ('group', ?, ?, ?)",
            (body.title.strip(), user["id"], now),
        )
        chat_id = cur.lastrowid
        for uid in member_ids:
            conn.execute(
                "INSERT INTO chat_members (chat_id, user_id, role, joined_at)"
                " VALUES (?, ?, ?, ?)",
                (chat_id, uid, "owner" if uid == user["id"] else "member", now),
            )
    chat = db.one("SELECT * FROM chats WHERE id = ?", (chat_id,))
    hub.notify_chat_created(chat_id, member_ids)
    return {"chat": chat_brief(chat, user["id"])}


# W27: foto del grupo — solo owner o admin. El pipeline es el mismo que la
# subida de media (WebP, cuota, URL firmada) y a los miembros se les avisa
# con 'chat_updated' para refrescar la lista al toque.
@router.post("/{chat_id}/avatar")
async def set_group_avatar(chat_id: int, file: UploadFile,
                           user: dict = Depends(current_user)) -> dict[str, Any]:
    chat = db.one("SELECT * FROM chats WHERE id = ?", (chat_id,))
    if not chat or chat["type"] != "group":
        raise HTTPException(404, "Grupo no encontrado")
    mine = _member_row(chat_id, user["id"])
    if not mine:
        raise HTTPException(403, "No eres miembro del grupo")
    if mine.get("role") not in ("owner", "admin"):
        raise HTTPException(403, "Solo el owner o un admin pueden cambiar la foto")
    mime = file.content_type or ""
    if not mime.startswith("image/"):
        raise HTTPException(415, "La foto del grupo debe ser una imagen")
    too_big = f"El archivo supera los {config.MAX_MEDIA_BYTES // (1024*1024)} MB"
    if file.size is not None and file.size > config.MAX_MEDIA_BYTES:
        raise HTTPException(413, too_big)
    data = await file.read()
    if not data:
        raise HTTPException(400, "Archivo vacío")
    w = h = None
    converted = False
    if mime != "image/svg+xml":
        # W27/P0: mismo pipeline que /api/media, en hilo y con tope de
        # 1024 px (un avatar no necesita los 2560 de una foto de chat).
        conv = await asyncio.to_thread(media_mod._encode_webp, data, 1024, 86)
        if conv is not None:
            data, w, h = conv
            mime = "image/webp"
            converted = True
    if len(data) > config.MAX_MEDIA_BYTES:
        raise HTTPException(413, too_big)
    if media_mod.media_dir_size() + len(data) > config.MEDIA_QUOTA:
        raise HTTPException(507, "Cuota de almacenamiento llena")
    ext = (".webp" if converted else Path(file.filename or "").suffix[:10].lower()
           or mimetypes.guess_extension(mime) or "")
    rel = f"{user['id']}/{uuid.uuid4().hex}{ext}"
    dest = config.MEDIA_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    media_mod.note_media_size(len(data))
    slug = secrets.token_hex(16)
    if mime.startswith("image/") and (not w or not h):
        dims = await asyncio.to_thread(media_mod.image_size, data)
        if dims:
            w, h = dims
    media_id = db.execute(
        "INSERT INTO media (owner_id, path, mime, size, name, slug, width, height, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], rel, mime, len(data), (file.filename or "grupo")[:200],
         slug, w, h, int(time.time())),
    )
    db.run("UPDATE chats SET avatar_media_id = ? WHERE id = ?", (media_id, chat_id))
    hub.emit_to_chat(chat_id, {"type": "chat_updated", "chat_id": chat_id})
    return {"chat_id": chat_id,
            "avatar_url": medialink.media_url_by_id(media_id, "profile")}


@router.get("/{chat_id}/messages")
def get_messages(
    chat_id: int,
    before_seq: int | None = None,
    after_seq: int | None = None,
    limit: int = 50,
    user: dict = Depends(current_user),
) -> dict[str, Any]:
    _require_member(chat_id, user["id"])
    limit = max(1, min(limit, 100))
    if after_seq is not None:
        # W45: catch-up tras una reconexión de WebSocket. Devuelve en
        # orden ascendente, para que el cliente pueda pedir la página
        # siguiente con el último seq recibido.
        rows = db.rows(
            "SELECT * FROM messages WHERE chat_id = ? AND seq > ?"
            " ORDER BY seq ASC LIMIT ?",
            (chat_id, max(0, after_seq), limit),
        )
    elif before_seq:
        rows = db.rows(
            "SELECT * FROM messages WHERE chat_id = ? AND seq < ?"
            " ORDER BY seq DESC LIMIT ?",
            (chat_id, before_seq, limit),
        )
        rows.reverse()
    else:
        rows = db.rows(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY seq DESC LIMIT ?",
            (chat_id, limit),
        )
        rows.reverse()
    if rows:
        # W12: el destinatario acabó de bajarse estos mensajes → 'recibido'.
        _mark_delivered(chat_id, user["id"], rows[-1]["seq"])
        hub.emit_to_chat(
            chat_id,
            {"type": "delivered", "chat_id": chat_id, "seq": rows[-1]["seq"],
             "user_ids": [user["id"]]},
            exclude=user["id"],
        )
    roles = {
        r["user_id"]: r["role"]
        for r in db.rows(
            "SELECT user_id, role FROM chat_members WHERE chat_id = ?",
            (chat_id,),
        )
    }
    return {"messages": [message_out(m, roles=roles) for m in rows]}


def _e2e_stored(blob: "E2EBlob | None", text: str) -> tuple[str, str, str]:
    """W29f/W37a: valida un blob E2E y devuelve (iv, ct, cuerpo guardado).

    Con cifrado el server NUNCA ve texto en claro: body debe llegar
    vacío y aquí se guarda el marcador "[Mensaje cifrado]" + IV/blob
    tal cual. Sin blob, devuelve el texto limpio. Compartido entre el
    envío y la EDICIÓN (W37a: editar un mensaje cifrado re-cifra)."""
    if not blob:
        return "", "", text.strip()
    if text.strip():
        raise HTTPException(
            422, "Un mensaje cifrado no puede traer texto en claro"
        )
    if len(base64.b64decode(blob.iv)) > 32:
        raise HTTPException(413, "IV cifrado demasiado grande")
    if len(base64.b64decode(blob.ct)) > 32768:
        raise HTTPException(413, "Blob cifrado supera los 32 KB")
    return blob.iv, blob.ct, "[Mensaje cifrado]"


@router.post("/{chat_id}/messages", status_code=201)
def send_message(chat_id: int, body: SendIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    chat = _require_member(chat_id, user["id"])
    if chat["type"] == "dm":
        # W28e: en un directo, un bloqueo activo en cualquier dirección
        # corta los mensajes (los grupos no se tocan).
        other = db.one(
            "SELECT user_id FROM chat_members"
            " WHERE chat_id = ? AND user_id != ? LIMIT 1",
            (chat_id, user["id"]),
        )
        if other and _blocked_pair(user["id"], other["user_id"]):
            raise HTTPException(403, "Usuario bloqueado")
    if body.kind not in ("text", "image", "file", "voice", "sticker"):
        # 'system' es exclusivo del server (altas/bajas de miembros): un
        # cliente no puede fabricar avisos del sistema (W14).
        raise HTTPException(400, "Tipo de mensaje inválido")
    if body.kind == "text" and not body.body.strip() and not body.e2e:
        # W29f: con cifrado E2E el cuerpo llega vacío (va en e2e.ct).
        raise HTTPException(400, "El mensaje está vacío")
    if body.kind == "sticker" and not (0 < len(body.body.strip()) <= 8):
        # W28g: un sticker es un emoji corto, no un mensaje con cuerpo.
        raise HTTPException(400, "Sticker inválido")
    if body.kind in ("image", "file", "voice"):
        if not body.media_id:
            raise HTTPException(400, "Falta el archivo adjunto")
        media = db.one("SELECT * FROM media WHERE id = ?", (body.media_id,))
        if not media or media["owner_id"] != user["id"]:
            raise HTTPException(400, "Archivo inválido")

    # Idempotencia: si ya existe este client_msg_id, devolver el mensaje original
    if body.client_msg_id:
        prev = db.one(
            "SELECT * FROM messages WHERE chat_id = ? AND sender_id = ? AND client_msg_id = ?",
            (chat_id, user["id"], body.client_msg_id),
        )
        if prev:
            return {"message": message_out(prev)}

    # W18: bloqueo anti-spam escalonado. Si la cuenta está castigada, ni
    # se consume el bucket: el 429 informa cuánto falta (y el cliente
    # levanta la pantalla de aviso por la bandera "spam").
    blk = ratelimit.SPAM.remaining(user["id"])
    if blk > 0:
        raise HTTPException(
            429, detail={"retry_after": math.ceil(blk), "spam": True})

    # W11: límite de frecuencia por usuario (~3 msgs cada 5 s con ráfaga de 5).
    # Va después de la idempotencia para que un reintento del mismo
    # client_msg_id nunca reciba 429. El 429 lleva retry_after en segundos,
    # formato que api.js ya traduce a "Espera Ns antes de reintentar".
    espera = ratelimit.MESSAGES.take(user["id"])
    if espera > 0:
        # W18: cada rechazo suma un punto; desde el 5º seguido la cuenta
        # queda bloqueada (5 min, duplicando con cada punto nuevo). El
        # cliente distingue el caso por la bandera "spam" del detail.
        bloqueo = ratelimit.SPAM.hit(user["id"])
        raise HTTPException(429, detail={
            "retry_after": math.ceil(bloqueo if bloqueo > 0 else espera),
            "spam": True,
        })

    # W29f: con cifrado de extremo a extremo el server NUNCA ve texto
    # en claro: body llega vacío y aquí se guarda el marcador
    # "[Mensaje cifrado]" (los previews/notificaciones lo muestran a
    # quien no tenga la clave) + IV/cifrado como están.
    e2e_iv, e2e_ct, stored_body = _e2e_stored(body.e2e, body.body)
    # W29d: marcado de spoiler (el cliente lo tapa hasta que se toque)
    spoiler = 1 if body.spoiler else 0

    # W37f (auditoría): el mensaje citado DEBE ser de ESTE chat — sin
    # esta validación, un reply_to ajen permitía leer 120 caracteres
    # de cualquier mensaje privado de la instancia (IDOR).
    if body.reply_to:
        ref = db.one(
            "SELECT id FROM messages WHERE id = ? AND chat_id = ?",
            (body.reply_to, chat_id),
        )
        if not ref:
            raise HTTPException(400, "El mensaje citado no existe en este chat")

    # W28b: @menciones de MIEMBROS del grupo (sólo texto y sólo grupos;
    # con e2e no hay cuerpo en claro, así que no se parsea)
    mentions = ""
    if not body.e2e and chat["type"] != "dm" and body.kind == "text":
        ids = _parse_mentions(chat_id, body.body)
        if ids:
            mentions = _mentions_col(ids)

    now = int(time.time())
    try:
        with db.tx() as conn:
            seq = _next_seq(conn, chat_id)
            cur = conn.execute(
                "INSERT INTO messages (chat_id, seq, sender_id, kind, body, media_id,"
                " reply_to, client_msg_id, peaks, dur, created_at, mentions,"
                " spoiler, e2e_iv, e2e_ct)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chat_id, seq, user["id"], body.kind, stored_body,
                 body.media_id, body.reply_to, body.client_msg_id, body.peaks,
                 body.dur, now, mentions, spoiler, e2e_iv, e2e_ct),
            )
            msg_id = cur.lastrowid
    except Exception:
        prev = None
        if body.client_msg_id:
            prev = db.one(
                "SELECT * FROM messages WHERE chat_id = ? AND sender_id = ? AND client_msg_id = ?",
                (chat_id, user["id"], body.client_msg_id),
            )
        if prev:
            return {"message": message_out(prev)}
        raise

    msg = db.one("SELECT * FROM messages WHERE id = ?", (msg_id,))
    out = message_out(msg)
    hub.emit_to_chat(chat_id, {"type": "message", "message": out})
    return {"message": out}


class MsgPinIn(BaseModel):
    pin: bool


@router.post("/{chat_id}/messages/{message_id}/pin")
def set_message_pin(
    chat_id: int, message_id: int, body: MsgPinIn, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """W28c: fijar/desfijar un mensaje — el estado vive en el chat
    (cualquier miembro puede fijar) y se avisa por WS."""
    _require_member(chat_id, user["id"])
    msg = db.one(
        "SELECT * FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id)
    )
    if not msg:
        raise HTTPException(404, "Mensaje no encontrado")
    now = int(time.time())
    if body.pin:
        db.execute(
            "UPDATE messages SET pinned_at = ?, pinned_by = ? WHERE id = ?",
            (now, user["id"], message_id),
        )
    else:
        db.execute(
            "UPDATE messages SET pinned_at = 0, pinned_by = NULL WHERE id = ?",
            (message_id,),
        )
    msg = db.one("SELECT * FROM messages WHERE id = ?", (message_id,))
    out = message_out(msg)
    hub.emit_to_chat(chat_id, {
        "type": "message_pinned",
        "chat_id": chat_id,
        "message_id": message_id,
        "pinned": bool(body.pin),
        "pinned_by": user["id"] if body.pin else None,
    })
    return {"message": out}


@router.get("/{chat_id}/pins")
def list_pins(chat_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    """W28c: mensajes fijados del chat (más recientes primero)."""
    _require_member(chat_id, user["id"])
    rows = db.rows(
        "SELECT * FROM messages WHERE chat_id = ? AND pinned_at > 0"
        " ORDER BY pinned_at DESC LIMIT 50",
        (chat_id,),
    )
    # W45: la lista de fijados también respeta el spoiler; el modal muestra
    # "Spoiler" y el clic lleva a la burbuja, que sigue cubierta.
    out = []
    for r in rows:
        m = message_out(r)
        if m.get("spoiler"):
            m["body"] = "Spoiler"
        out.append(m)
    return {"messages": out}


@router.get("/{chat_id}/gallery")
def chat_gallery(chat_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    """W28d: archivos y medios enviados en el chat (más recientes
    primero): las imágenes en una lista y el resto en otra."""
    _require_member(chat_id, user["id"])
    rows = db.rows(
        "SELECT m.id AS msg_id, m.kind, m.created_at, m.spoiler, md.* FROM messages m"
        " JOIN media md ON md.id = m.media_id"
        " WHERE m.chat_id = ? AND m.media_id IS NOT NULL"
        " ORDER BY m.created_at DESC LIMIT 200",
        (chat_id,),
    )
    images: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for r in rows:
        item = {
            "msg_id": r["msg_id"],
            "spoiler": bool(r["spoiler"]),   # W29d: miniatura tapada
            "media": {
                "id": r["id"],
                "url": medialink.media_url(r, "file"),
                "mime": r["mime"],
                "size": r["size"],
                "name": r["name"],
                **media_mod.row_dims(r),
            },
        }
        if r["kind"] == "image":
            images.append(item)
        else:
            files.append(item)
    return {"images": images[:100], "files": files[:100]}


@router.get("/{chat_id}/messages/{message_id}/reads")
def message_reads(chat_id: int, message_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    """W28f: quién leyó un mensaje MÍO en un grupo. No hay tabla nueva:
    la marca por miembro (chat_members.last_read_seq) cubre cualquier seq."""
    chat = _require_member(chat_id, user["id"])
    if chat["type"] != "group":
        raise HTTPException(400, "Solo disponible en grupos")
    msg = db.one(
        "SELECT * FROM messages WHERE id = ? AND chat_id = ?",
        (message_id, chat_id),
    )
    if not msg:
        raise HTTPException(404, "Mensaje no encontrado")
    if msg["sender_id"] != user["id"]:
        # Cada quien ve las lecturas de lo suyo (los recibos no exponen
        # la actividad de otros).
        raise HTTPException(403, "Solo puedes ver las lecturas de tus mensajes")
    rows = db.rows(
        "SELECT u.* FROM chat_members cm JOIN users u ON u.id = cm.user_id"
        " WHERE cm.chat_id = ? AND cm.last_read_seq >= ? AND u.id != ?"
        " ORDER BY LOWER(COALESCE(u.display_name, u.username)), u.username",
        (chat_id, msg["seq"], msg["sender_id"]),
    )
    total = db.one(
        "SELECT COUNT(*) AS n FROM chat_members WHERE chat_id = ?",
        (chat_id,),
    )
    return {
        "reads": [user_brief(r) for r in rows],
        "total": (total or {"n": 0})["n"],
    }


class EditIn(BaseModel):
    body: str = Field(default="", max_length=config.MAX_BODY_CHARS)
    # W37a: con cifrado E2E el server recibe SÓLO el blob nuevo (body vacío)
    e2e: E2EBlob | None = None


@router.put("/{chat_id}/messages/{message_id}")
def edit_message(
    chat_id: int, message_id: int, body: EditIn, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """W8: editar el texto de un mensaje propio (avisa por WS)."""
    _require_member(chat_id, user["id"])
    msg = db.one(
        "SELECT * FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id)
    )
    if not msg:
        raise HTTPException(404, "Mensaje no encontrado")
    if msg["sender_id"] != user["id"]:
        raise HTTPException(403, "Solo puedes editar tus propios mensajes")
    if msg["kind"] != "text" or msg.get("media_id"):
        raise HTTPException(400, "Solo se pueden editar mensajes de texto")
    # W37a: la edición respeta el cifrado — un mensaje E2E se RE-CIFRA
    # (el server recibe sólo el blob nuevo); si era en claro, la
    # edición va en claro (nada de convertir claro en cifrado ni al
    # revés: eso desincronizaría a los receptores).
    was_e2e = bool(msg.get("e2e_ct"))
    if was_e2e != bool(body.e2e):
        raise HTTPException(
            400,
            "El mensaje cifrado debe editarse cifrado"
            if was_e2e
            else "Sólo se reedita cifrado un mensaje que ya lo era",
        )
    e2e_iv, e2e_ct, stored_body = _e2e_stored(body.e2e, body.body)
    if not stored_body:
        raise HTTPException(400, "El mensaje quedó vacío")
    now = int(time.time())
    db.execute(
        "UPDATE messages SET body = ?, edited_at = ?, e2e_iv = ?, e2e_ct = ?"
        " WHERE id = ?",
        (stored_body, now, e2e_iv, e2e_ct, message_id),
    )
    msg = db.one("SELECT * FROM messages WHERE id = ?", (message_id,))
    out = message_out(msg)
    hub.emit_to_chat(chat_id, {
        "type": "message_edited",
        "chat_id": chat_id,
        "message_id": message_id,
        "body": out["body"],
        "edited_at": out["edited_at"],
        # W37a: el blob nuevo para que el resto de receptores re-descifre
        "e2e": out["e2e"],
    })
    return {"message": out}


@router.delete("/{chat_id}/messages/{message_id}")
def delete_message(
    chat_id: int, message_id: int, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """W8: eliminar un mensaje propio. El archivo adjunto se borra de disco
    (libera cuota) salvo que alguien lo use de avatar."""
    _require_member(chat_id, user["id"])
    msg = db.one(
        "SELECT * FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id)
    )
    if not msg:
        raise HTTPException(404, "Mensaje no encontrado")
    if msg["sender_id"] != user["id"]:
        # W36g: en grupos, los owner/admin pueden eliminar mensajes de
        # otros miembros (el server revalida el rol en cada petición).
        chat = db.one("SELECT * FROM chats WHERE id = ?", (chat_id,))
        mine = db.one(
            "SELECT * FROM chat_members WHERE chat_id = ? AND user_id = ?",
            (chat_id, user["id"]),
        )
        role = (mine or {}).get("role") or "member"
        if not (chat and chat["type"] == "group" and role in ("owner", "admin")):
            raise HTTPException(403, "Solo puedes eliminar tus propios mensajes")
    db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
    media_id = msg.get("media_id")
    if media_id:
        as_avatar = db.one(
            "SELECT 1 AS a FROM users WHERE avatar_media_id = ?"
            " UNION SELECT 1 AS a FROM chats WHERE avatar_media_id = ?"
            " LIMIT 1",
            (media_id, media_id),
        )
        # W45e: los reenvíos comparten media_id. Antes, borrar el mensaje
        # original eliminaba el archivo y dejaba el reenvío roto (404).
        # Solo se borra el media si ya no lo usa nada más.
        still_used = db.one(
            "SELECT 1 AS x FROM messages WHERE media_id = ? LIMIT 1",
            (media_id,),
        ) or db.one(
            "SELECT 1 AS x FROM gif_favs WHERE media_id = ? LIMIT 1",
            (media_id,),
        )
        if not as_avatar and not still_used:
            row = db.one("SELECT * FROM media WHERE id = ?", (media_id,))
            if row:
                path = config.MEDIA_DIR / row["path"]
                try:
                    if path.is_file():
                        media_mod.remove_media_files(path)
                        media_mod.note_media_size(-int(row.get("size") or 0))
                except OSError:
                    pass
                db.execute("DELETE FROM media WHERE id = ?", (media_id,))
    hub.emit_to_chat(chat_id, {
        "type": "message_deleted",
        "chat_id": chat_id,
        "message_id": message_id,
        "seq": msg["seq"],
    })
    return {"ok": True}


@router.post("/{chat_id}/read")
def mark_read(chat_id: int, body: ReadIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_member(chat_id, user["id"])
    # W14: solo si el seq NUEVO avanza se escribe y se emite el evento
    # 'read' (antes cada request re-emitió el broadcast aunque no cambiara).
    # W14: el gate de broadcast es el rowcount (execute() devuelve lastrowid,
    # que tras un UPDATE queda en 0).
    if db.run(
        "UPDATE chat_members SET last_read_seq = ?,"
        " last_delivered_seq = MAX(last_delivered_seq, ?)"
        " WHERE chat_id = ? AND user_id = ? AND last_read_seq < ?",
        (body.seq, body.seq, chat_id, user["id"], body.seq),
    ) and not body.silent:
        hub.emit_to_chat(
            chat_id,
            {"type": "read", "chat_id": chat_id, "user_id": user["id"], "seq": body.seq},
            exclude=user["id"],
        )
    return {"ok": True}


@router.post("/{chat_id}/typing")
def typing(chat_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_member(chat_id, user["id"])
    # W14: exceso de "escribiendo…" se descarta en silencio (sin 429 ni
    # toast): solo sirve para frenar la amplificación de broadcasts.
    if ratelimit.TYPING.take(user["id"]) > 0:
        return {"ok": True}
    hub.emit_to_chat(
        chat_id,
        {"type": "typing", "chat_id": chat_id, "user_id": user["id"],
         "username": user["username"]},
        exclude=user["id"],
    )
    return {"ok": True}


# ------------------------------------------------------------ W13

@router.post("/{chat_id}/pin")
def set_pinned(chat_id: int, body: PinIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    """W13: fijar/desfijar el chat en MI lista (no afecta a los demás)."""
    _require_member(chat_id, user["id"])
    db.execute(
        "UPDATE chat_members SET pinned = ? WHERE chat_id = ? AND user_id = ?",
        (1 if body.pinned else 0, chat_id, user["id"]),
    )
    return {"ok": True, "pinned": bool(body.pinned)}


@router.post("/{chat_id}/mute")
def set_muted(chat_id: int, body: MuteIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    """W13: silenciar las notificaciones del chat (solo para mí)."""
    _require_member(chat_id, user["id"])
    db.execute(
        "UPDATE chat_members SET muted = ? WHERE chat_id = ? AND user_id = ?",
        (1 if body.muted else 0, chat_id, user["id"]),
    )
    return {"ok": True, "muted": bool(body.muted)}


@router.get("/{chat_id}/search")
def search_messages(
    chat_id: int, q: str = "", limit: int = 50, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """W13: buscar dentro de los mensajes del chat (por cuerpo). Primero
    coincide el texto tal cual; si no hay resultados, se repite sin
    acentos ni mayúsculas ('cafe' encuentra 'café con leche')."""
    _require_member(chat_id, user["id"])
    q = q.strip()[:200]        # W14: tope del patrón LIKE (CPU/IO)
    if not q:
        return {"messages": []}
    limit = max(1, min(limit, 50))

    def _esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    # W45: no buscar dentro de spoilers. Devolver el texto en el snippet
    # (o permitir inferirlo por coincidencias) destapaba el contenido.
    rows = db.rows(
        "SELECT * FROM messages WHERE chat_id = ? AND spoiler = 0"
        " AND body LIKE ? ESCAPE '\\'"
        " ORDER BY seq DESC LIMIT ?",
        (chat_id, "%" + _esc(q) + "%", limit),
    )
    if not rows:
        folded = db.fold_str(q)
        if folded:   # una consulta solo-emoji no pliega: no se repite
            rows = db.rows(
                "SELECT * FROM messages WHERE chat_id = ? AND spoiler = 0"
                " AND fold(body) LIKE ? ESCAPE '\\'"
                " ORDER BY seq DESC LIMIT ?",
                (chat_id, "%" + _esc(folded) + "%", limit),
            )
    return {"messages": [message_out(m) for m in rows]}


@router.post("/{chat_id}/messages/{message_id}/forward", status_code=201)
def forward_message(
    chat_id: int, message_id: int, body: ForwardIn, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """W13: reenviar un mensaje a otro de MIS chats. Copia contenido y
    archivo (el media_id queda compartido) y el nuevo mensaje es mío."""
    _require_member(chat_id, user["id"])   # debo leer el origen
    if body.target_chat_id == chat_id:
        raise HTTPException(400, "El destino es el mismo chat")
    target = db.one("SELECT * FROM chats WHERE id = ?", (body.target_chat_id,))
    if not target or not _member_row(body.target_chat_id, user["id"]):
        raise HTTPException(403, "No eres miembro del chat destino")
    # W45d: reenviar a un DM con bloqueo activo saltaba la regla de
    # send_message (se podía meter contenido en un directo bloqueado).
    if target["type"] == "dm":
        other = db.one(
            "SELECT user_id FROM chat_members"
            " WHERE chat_id = ? AND user_id != ? LIMIT 1",
            (body.target_chat_id, user["id"]),
        )
        if other and _blocked_pair(user["id"], other["user_id"]):
            raise HTTPException(403, "Usuario bloqueado")
    msg = db.one(
        "SELECT * FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id)
    )
    if not msg:
        raise HTTPException(404, "Mensaje no encontrado")
    if msg["kind"] == "system":
        raise HTTPException(400, "No se puede reenviar un mensaje del sistema")
    # W37f: la clave E2E es por PAR de usuarios (ECDH) — un blob cifrado
    # sólo es descifrable en SU chat, así que "reenviarlo" dejaría el
    # marcador "[Mensaje cifrado]" como texto literal (o compartiera
    # cifrado con quien no corresponde). Mejor rechazarlo claro.
    if msg.get("e2e_ct"):
        raise HTTPException(400, "No se puede reenviar un mensaje cifrado de extremo a extremo")
    # W18: igual que send_message: primero el bloqueo anti-spam, después
    # el bucket (el rechazo suma punto y la bandera "spam" avisa al cliente).
    blk = ratelimit.SPAM.remaining(user["id"])
    if blk > 0:
        raise HTTPException(
            429, detail={"retry_after": math.ceil(blk), "spam": True})
    espera = ratelimit.MESSAGES.take(user["id"])
    if espera > 0:
        bloqueo = ratelimit.SPAM.hit(user["id"])
        raise HTTPException(429, detail={
            "retry_after": math.ceil(bloqueo if bloqueo > 0 else espera),
            "spam": True,
        })
    now = int(time.time())
    with db.tx() as conn:
        seq = _next_seq(conn, body.target_chat_id)
        cur = conn.execute(
            "INSERT INTO messages (chat_id, seq, sender_id, kind, body, media_id,"
            " peaks, dur, forwarded, spoiler, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (body.target_chat_id, seq, user["id"], msg["kind"], msg["body"],
             msg.get("media_id"), msg.get("peaks"), msg.get("dur"),
             1 if msg.get("spoiler") else 0, now),
        )
        new_id = cur.lastrowid
    out = message_out(db.one("SELECT * FROM messages WHERE id = ?", (new_id,)))
    hub.emit_to_chat(body.target_chat_id, {"type": "message", "message": out})
    return {"message": out}


@router.post("/{chat_id}/members", status_code=201)
def add_member(chat_id: int, body: MemberIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    chat = _require_member(chat_id, user["id"])
    if chat["type"] != "group":
        raise HTTPException(400, "Solo se agregan miembros a grupos")
    target = db.one(
        "SELECT * FROM users WHERE username = ? AND email_verified = 1",
        (body.username.strip().lower(),),
    )
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    if _member_row(chat_id, target["id"]):
        return {"ok": True, "message": "Ya es miembro"}
    # W37f: CREATIONS — agregar miembros también (~1 por minuto).
    espera = ratelimit.CREATIONS.take(user["id"])
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": math.ceil(espera)})
    db.execute(
        "INSERT INTO chat_members (chat_id, user_id, joined_at) VALUES (?, ?, ?)",
        (chat_id, target["id"], int(time.time())),
    )
    sys_msg = f"{user['display_name'] or user['username']} agregó a {target['display_name'] or target['username']}"
    with db.tx() as conn:
        seq = _next_seq(conn, chat_id)
        cur = conn.execute(
            "INSERT INTO messages (chat_id, seq, sender_id, kind, body, created_at)"
            " VALUES (?, ?, ?, 'system', ?, ?)",
            (chat_id, seq, user["id"], sys_msg, int(time.time())),
        )
        sys_id = cur.lastrowid
    hub.emit_to_chat(chat_id, {"type": "members_changed", "chat_id": chat_id})
    # El mensaje system también va en vivo: los que tienen el chat abierto
    # lo ven sin tener que recargar (API.md: "+ mensaje system").
    sys_row = db.one("SELECT * FROM messages WHERE id = ?", (sys_id,))
    if sys_row:
        hub.emit_to_chat(chat_id, {"type": "message", "message": message_out(sys_row)})
    return {"ok": True}


@router.patch("/{chat_id}/members/{member_id}")
def set_member_role(
    chat_id: int,
    member_id: int,
    body: MemberRoleIn,
    user: dict = Depends(current_user),
) -> dict[str, Any]:
    """W46: ascender a admin o quitar el rol (sólo owner/admin).

    Un admin puede ascender a un miembro y quitar miembros comunes; para
    tocar a otro admin (o al owner) hace falta ser owner. El cambio deja
    un mensaje system visible para todos y un evento WS `member_role`.
    """
    chat = _require_member(chat_id, user["id"])
    if chat["type"] != "group":
        raise HTTPException(400, "Solo los grupos tienen administradores")
    if member_id == user["id"]:
        raise HTTPException(400, "No puedes cambiar tu propio rol")

    sys_id = 0
    with db.tx() as conn:
        actor = conn.execute(
            "SELECT role FROM chat_members WHERE chat_id = ? AND user_id = ?",
            (chat_id, user["id"]),
        ).fetchone()
        target = conn.execute(
            "SELECT role FROM chat_members WHERE chat_id = ? AND user_id = ?",
            (chat_id, member_id),
        ).fetchone()
        if not target:
            raise HTTPException(404, "El usuario no es miembro del grupo")
        actor_role = actor["role"] if actor else "member"
        if actor_role not in ("owner", "admin"):
            raise HTTPException(403, "Solo owner o admin pueden administrar miembros")
        if target["role"] == "owner":
            raise HTTPException(403, "No se puede cambiar el rol del owner")
        if target["role"] == "admin" and actor_role != "owner":
            raise HTTPException(403, "Solo el owner puede cambiar el rol de otro admin")
        if target["role"] == body.role:
            return {"ok": True, "role": body.role, "changed": False}

        conn.execute(
            "UPDATE chat_members SET role = ? WHERE chat_id = ? AND user_id = ?",
            (body.role, chat_id, member_id),
        )
        actor_name = (
            user.get("display_name") or user.get("username") or "Usuario"
        )
        target_name = conn.execute(
            "SELECT display_name, username FROM users WHERE id = ?", (member_id,)
        ).fetchone()
        tname = (
            (target_name["display_name"] or target_name["username"])
            if target_name else "Usuario"
        )
        if body.role == "admin":
            sys_msg = f"{actor_name} hizo admin a {tname}"
        else:
            sys_msg = f"{actor_name} quitó el rol de admin a {tname}"
        seq = _next_seq(conn, chat_id)
        cur = conn.execute(
            "INSERT INTO messages (chat_id, seq, sender_id, kind, body, created_at)"
            " VALUES (?, ?, ?, 'system', ?, ?)",
            (chat_id, seq, user["id"], sys_msg, int(time.time())),
        )
        sys_id = cur.lastrowid

    hub.emit_to_chat(chat_id, {
        "type": "member_role", "chat_id": chat_id,
        "user_id": member_id, "role": body.role, "by": user["id"],
    })
    hub.emit_to_chat(chat_id, {"type": "members_changed", "chat_id": chat_id})
    sys_row = db.one("SELECT * FROM messages WHERE id = ?", (sys_id,))
    if sys_row:
        hub.emit_to_chat(chat_id, {"type": "message", "message": message_out(sys_row)})
    return {"ok": True, "role": body.role, "changed": True}


@router.delete("/{chat_id}/members/{member_id}")
def remove_member(
    chat_id: int,
    member_id: int,
    user: dict = Depends(current_user),
) -> dict[str, Any]:
    """W46: sacar a alguien del grupo siendo owner/admin.

    El objetivo recibe `member_removed` (para cerrar el chat en vivo) y
    los que quedan ven member_left + el mensaje system de la expulsión.
    Un admin no puede tocar al owner ni a otro admin.
    """
    chat = _require_member(chat_id, user["id"])
    if chat["type"] != "group":
        raise HTTPException(400, "Solo se pueden quitar miembros de grupos")
    if member_id == user["id"]:
        raise HTTPException(400, 'Usa "Salir del grupo" para abandonarlo')

    sys_id = 0
    with db.tx() as conn:
        actor = conn.execute(
            "SELECT role FROM chat_members WHERE chat_id = ? AND user_id = ?",
            (chat_id, user["id"]),
        ).fetchone()
        target = conn.execute(
            "SELECT cm.role, u.display_name, u.username"
            " FROM chat_members cm JOIN users u ON u.id = cm.user_id"
            " WHERE cm.chat_id = ? AND cm.user_id = ?",
            (chat_id, member_id),
        ).fetchone()
        if not target:
            raise HTTPException(404, "El usuario no es miembro del grupo")
        actor_role = actor["role"] if actor else "member"
        if actor_role not in ("owner", "admin"):
            raise HTTPException(403, "Solo owner o admin pueden administrar miembros")
        if target["role"] == "owner":
            raise HTTPException(403, "No se puede eliminar al owner del grupo")
        if target["role"] == "admin" and actor_role != "owner":
            raise HTTPException(403, "Solo el owner puede eliminar a otro admin")

        conn.execute(
            "DELETE FROM chat_members WHERE chat_id = ? AND user_id = ?",
            (chat_id, member_id),
        )
        actor_name = (
            user.get("display_name") or user.get("username") or "Usuario"
        )
        tname = target["display_name"] or target["username"]
        sys_msg = f"{actor_name} eliminó a {tname} del grupo"
        seq = _next_seq(conn, chat_id)
        cur = conn.execute(
            "INSERT INTO messages (chat_id, seq, sender_id, kind, body, created_at)"
            " VALUES (?, ?, ?, 'system', ?, ?)",
            (chat_id, seq, user["id"], sys_msg, int(time.time())),
        )
        sys_id = cur.lastrowid

    # El expulsado ya no está en chat_members: el broadcast del chat no le
    # llegaría. Se le avisa por su conexión para que cierre el chat en vivo.
    hub.emit_to_user(member_id, {
        "type": "member_removed", "chat_id": chat_id,
        "user_id": member_id, "by": user["id"],
        "title": chat.get("title") or "Grupo",
    })
    hub.emit_to_chat(chat_id, {
        "type": "member_left", "chat_id": chat_id,
        "user_id": member_id, "by": user["id"],
    })
    hub.emit_to_chat(chat_id, {"type": "members_changed", "chat_id": chat_id})
    sys_row = db.one("SELECT * FROM messages WHERE id = ?", (sys_id,))
    if sys_row:
        hub.emit_to_chat(chat_id, {"type": "message", "message": message_out(sys_row)})
    return {"ok": True}


@router.get("/{chat_id}/members")
def list_members(chat_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Miembros con presencia, estado y rol: alimenta el panel derecho de
    "info del chat" (W7/W46): lista del grupo y quién está conectado."""
    _require_member(chat_id, user["id"])
    rows = db.rows(
        "SELECT u.*, cm.role AS member_role"
        " FROM chat_members cm JOIN users u ON u.id = cm.user_id"
        " WHERE cm.chat_id = ? ORDER BY cm.joined_at, u.id",
        (chat_id,),
    )
    return {
        "members": [
            {**user_brief(r), "role": r["member_role"]} for r in rows
        ]
    }


@router.post("/{chat_id}/leave")
def leave_chat(chat_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Salir de un grupo (W7): borra la membresía, avisa a los demás con
    un mensaje system + evento member_left. Si era el último miembro, el
    grupo se elimina (los mensajes caen en cascada)."""
    chat = _require_member(chat_id, user["id"])
    if chat["type"] != "group":
        raise HTTPException(400, "Solo se puede salir de grupos")
    name = user["display_name"] or user["username"]
    db.execute(
        "DELETE FROM chat_members WHERE chat_id = ? AND user_id = ?",
        (chat_id, user["id"]),
    )
    left = db.one("SELECT COUNT(*) AS n FROM chat_members WHERE chat_id = ?", (chat_id,))
    if left and left["n"] == 0:
        # Último en salir: a nadie le queda visible este grupo.
        db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        return {"ok": True, "deleted": True}
    sys_msg = f"{name} salió del grupo"
    with db.tx() as conn:
        seq = _next_seq(conn, chat_id)
        cur = conn.execute(
            "INSERT INTO messages (chat_id, seq, sender_id, kind, body, created_at)"
            " VALUES (?, ?, NULL, 'system', ?, ?)",
            (chat_id, seq, sys_msg, int(time.time())),
        )
        sys_id = cur.lastrowid
    hub.emit_to_chat(chat_id, {"type": "member_left", "chat_id": chat_id, "user_id": user["id"]})
    sys_row = db.one("SELECT * FROM messages WHERE id = ?", (sys_id,))
    if sys_row:
        hub.emit_to_chat(chat_id, {"type": "message", "message": message_out(sys_row)})
    return {"ok": True}


@router.post("/{chat_id}/reactions/{message_id}")
def react(chat_id: int, message_id: int, body: ReactIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_member(chat_id, user["id"])
    msg = db.one("SELECT * FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id))
    if not msg:
        raise HTTPException(404, "Mensaje no encontrado")
    espera = ratelimit.REACTIONS.take(user["id"])   # W14
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": math.ceil(espera)})
    db.execute(
        "INSERT OR REPLACE INTO reactions (message_id, user_id, emoji, created_at)"
        " VALUES (?, ?, ?, ?)",
        (message_id, user["id"], body.emoji, int(time.time())),
    )
    hub.emit_to_chat(chat_id, {
        "type": "reaction", "chat_id": chat_id, "message_id": message_id,
        "user_id": user["id"], "emoji": body.emoji,
        # W29c: el chip en vivo puede mostrar quién reaccionó
        "username": user["username"],
        "name": user.get("display_name") or user["username"],
    })
    return {"ok": True}


@router.delete("/{chat_id}/reactions/{message_id}")
def unreact(chat_id: int, message_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    _require_member(chat_id, user["id"])
    # W37f (auditoría): el mensaje debe ser de ESTE chat (antes se podía
    # borrar la reacción propia de un mensaje ajeno sólo con su id).
    msg = db.one("SELECT 1 AS x FROM messages WHERE id = ? AND chat_id = ?", (message_id, chat_id))
    if not msg:
        raise HTTPException(404, "Mensaje no encontrado")
    espera = ratelimit.REACTIONS.take(user["id"])   # W14: toggle spam
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": math.ceil(espera)})
    db.execute(
        "DELETE FROM reactions WHERE message_id = ? AND user_id = ?",
        (message_id, user["id"]),
    )
    hub.emit_to_chat(chat_id, {
        "type": "reaction_removed", "chat_id": chat_id,
        "message_id": message_id, "user_id": user["id"],
    })
    return {"ok": True}
