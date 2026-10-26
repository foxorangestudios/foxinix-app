"""Endpoint WebSocket de tiempo real."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import security, db, auth
from ..realtime import hub
from .auth import _peer_user

log = logging.getLogger("foxmsg.ws")
router = APIRouter(tags=["ws"])

_PROTO = "foxinix"    # W14: el token viaja como subprotocolo (no en la URL:
                      # los tokens no deben aparecer en los logs de acceso)
_MSG_LIMIT = 40       # W14: mensajes por ventana para frenar floods
_MSG_WINDOW = 10.0
# W63: la señalización WebRTC de una malla de 4 usa muchos mensajes en
# ráfaga (una oferta + respuesta + ICE por cada par). Va en un cubo aparte
# para que una videollamada normal no se confunda con un flood de chat.
_CALL_MSG_LIMIT = 400

# W28h: señalización de llamadas WebRTC 1:1. El server solo relaya al otro
# miembro del DM (valida membresía y bloqueo); ni ve ni guarda media.
# W64: en grupos la sala es un "drop-in": call_start crea una sala con
# quien la abre (aunque esté solo) y call_state comparte su presencia.
_CALL_TYPES = ("call_offer", "call_answer", "call_ice", "call_hangup",
               "call_invite", "call_start", "call_join")
_CALL_MAX = 32768     # tope del mensaje crudo (un SDP ronda ~8 KB)
_SDP_MAX = 20000
_CALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_CALL_ROOM_MAX = 4    # malla de hasta 4 personas (incluido quien inicia)
# call_id -> {chat_id, call_id, members:set[int], host:int, video:bool,
#             created:float}. Efímero: si el servidor reinicia, las salas
# en curso terminan. La sala vive mientras quede al menos un miembro.
_CALL_ROOMS: dict[str, dict[str, Any]] = {}


async def _call_error(ws: WebSocket, chat_id: int, call_id: str,
                      detail: str) -> None:
    await ws.send_text(json.dumps({
        "type": "call_error", "chat_id": chat_id,
        "call_id": call_id, "detail": detail,
    }, ensure_ascii=False))


def _group_member_ids(chat_id: int, exclude: int) -> list[int]:
    rows = db.rows(
        "SELECT user_id FROM chat_members"
        " WHERE chat_id = ? AND user_id != ? AND COALESCE(hidden_at, 0) = 0",
        (chat_id, exclude),
    )
    return [int(r["user_id"]) for r in rows]


def _call_state_payload(room: dict[str, Any]) -> dict[str, Any]:
    """Presencia pública de una sala de grupo (sin datos de media)."""
    return {
        "type": "call_state",
        "chat_id": int(room["chat_id"]),
        "call_id": str(room.get("call_id") or ""),
        "group": True,
        "count": len(room["members"]),
        "video": bool(room.get("video")),
        "host": int(room.get("host") or 0),
    }


def _active_room(chat_id: int) -> dict[str, Any] | None:
    for room in _CALL_ROOMS.values():
        if room["chat_id"] == chat_id:
            return room
    return None


async def _broadcast_call_state(chat_id: int, room: dict[str, Any] | None) -> None:
    """Avisa a todos los miembros del grupo de la sala activa (o de que ya
    no hay ninguna). Se envía a todos los sockets online del usuario."""
    if room is not None and room["members"]:
        out = _call_state_payload(room)
    else:
        out = {
            "type": "call_state", "chat_id": chat_id, "call_id": "",
            "group": True, "count": 0, "video": False, "host": 0,
        }
    for mid in _group_member_ids(chat_id, 0):
        await hub.send_user(mid, out)


async def _send_active_calls(ws: WebSocket, uid: int) -> None:
    """Al abrir la WS se recuperan las salas ya activas de sus grupos.

    Las salas viven en memoria y no se guardan en la base de datos: si el
    servidor reinicia, las llamadas en curso también terminan. Un miembro
    que entra después ve el botón verde gracias a este empujón inicial.
    """
    for room in list(_CALL_ROOMS.values()):
        if not room["members"]:
            continue
        mine = db.one(
            "SELECT hidden_at FROM chat_members"
            " WHERE chat_id = ? AND user_id = ?",
            (room["chat_id"], uid),
        )
        if not mine or mine.get("hidden_at"):
            continue
        try:
            await ws.send_text(json.dumps(
                _call_state_payload(room), ensure_ascii=False))
        except Exception:
            return


async def _drop_user_calls(uid: int) -> None:
    """Al cerrar la última WS, sacar al usuario de sus salas y avisar.

    Una sala drop-in NO pertenece a quien la abrió: si el anfitrión se va
    y quedan más personas, la sala sigue viva. Solo desaparece cuando se
    va el último participante.
    """
    for call_id, room in list(_CALL_ROOMS.items()):
        if uid not in room["members"]:
            continue
        out = {
            "type": "call_hangup", "call_id": call_id,
            "chat_id": room["chat_id"], "group": True,
            "reason": "disconnected", "from": {"id": uid},
        }
        room["members"].discard(uid)
        for mid in list(room["members"]):
            await hub.send_user(mid, out)
        if not room["members"]:
            _CALL_ROOMS.pop(call_id, None)
        await _broadcast_call_state(room["chat_id"], room if room["members"] else None)


async def _handle_group_call(ws: WebSocket, uid: int, user: dict[str, Any],
                             mtype: str, msg: dict[str, Any]) -> None:
    """Señalización de una llamada de grupo (malla WebRTC de hasta 4).

    W64: no hay invitaciones ni tono. call_start crea una sala drop-in
    (aunque solo esté quien la abre) y call_state difunde cuánta gente hay.
    Cada persona que entra manda call_join; los que ya estaban dentro le
    envían una oferta dirigida. Las respuestas e ICE también llevan `to`,
    así cada PeerConnection tiene su par.
    """
    try:
        cid = int(msg.get("chat_id", 0))
    except (TypeError, ValueError):
        return
    call_id = str(msg.get("call_id") or "")
    if not cid or not _CALL_ID_RE.match(call_id):
        return
    chat = db.one("SELECT type FROM chats WHERE id = ?", (cid,))
    if not chat or chat["type"] != "group":
        if mtype in ("call_start", "call_invite", "call_join"):
            await _call_error(ws, cid, call_id, "Llamada de grupo no válida")
        return
    mine = db.one(
        "SELECT hidden_at FROM chat_members WHERE chat_id = ? AND user_id = ?",
        (cid, uid),
    )
    if not mine:
        return
    room = _CALL_ROOMS.get(call_id)
    fresh = db.one("SELECT * FROM users WHERE id = ?", (uid,)) or user
    sender = _peer_user(fresh)

    # W64: call_invite se acepta como alias de call_start para que una
    # pestaña con la web vieja en caché no vuelva a hacer sonar a nadie.
    if mtype in ("call_start", "call_invite"):
        if mine.get("hidden_at"):
            return
        if room is not None:
            if room["chat_id"] == cid and uid in room["members"]:
                await hub.send_user(uid, _call_state_payload(room))
            else:
                await _call_error(ws, cid, call_id,
                                  "Ya hay una llamada en curso en este grupo")
            return
        for r in _CALL_ROOMS.values():
            if r["chat_id"] == cid:
                await _call_error(ws, cid, call_id,
                                  "Ya hay una llamada en curso en este grupo")
                return
        room = {
            "chat_id": cid, "call_id": call_id, "members": {uid},
            "host": uid, "video": bool(msg.get("video")),
            "created": time.time(),
        }
        _CALL_ROOMS[call_id] = room
        # Nadie recibe una llamada: solo se publica la presencia de la
        # sala para que cada miembro decida entrar cuando quiera.
        await _broadcast_call_state(cid, room)
        return

    if mtype == "call_join":
        if room is None or room["chat_id"] != cid:
            # Puede haber otra sala (con otro call_id) en este mismo
            # grupo; no se debe borrar su presencia por una petición
            # vieja. Se reenvía la sala que sí existe.
            await _broadcast_call_state(cid, _active_room(cid))
            await hub.send_user(uid, {
                "type": "call_hangup", "call_id": call_id, "chat_id": cid,
                "group": True, "reason": "ended",
            })
            return
        if mine.get("hidden_at"):
            return
        if uid in room["members"]:
            await hub.send_user(uid, _call_state_payload(room))
            return
        if len(room["members"]) >= _CALL_ROOM_MAX:
            await _call_error(ws, cid, call_id, "La llamada está llena")
            return
        room["members"].add(uid)
        await _broadcast_call_state(cid, room)
        out = {
            "type": "call_join", "call_id": call_id, "chat_id": cid,
            "from": sender, "group": True,
        }
        for mid in list(room["members"]):
            if mid != uid:
                await hub.send_user(mid, out)
        return

    if room is None or room["chat_id"] != cid:
        return

    if mtype in ("call_offer", "call_answer", "call_ice"):
        try:
            to = int(msg.get("to", 0))
        except (TypeError, ValueError):
            return
        if uid not in room["members"] or to not in room["members"] or to == uid:
            return
        out = {
            "type": mtype, "call_id": call_id, "chat_id": cid,
            "from": sender, "to": to, "group": True,
        }
        if mtype in ("call_offer", "call_answer"):
            sdp = str(msg.get("sdp") or "")
            if not sdp or len(sdp) > _SDP_MAX:
                return
            out["sdp"] = sdp
            if mtype == "call_offer":
                out["video"] = bool(msg.get("video"))
        else:
            cand = msg.get("candidate")
            out["candidate"] = cand if isinstance(cand, dict) else None
        await hub.send_user(to, out)
        return

    if mtype == "call_hangup":
        try:
            to = int(msg.get("to", 0))
        except (TypeError, ValueError):
            to = 0
        reason = msg.get("reason")
        if to:
            if to not in room["members"]:
                return
            await hub.send_user(to, {
                "type": "call_hangup", "call_id": call_id, "chat_id": cid,
                "from": sender, "to": to, "group": True,
                "targeted": True,
                "reason": str(reason)[:48] if isinstance(reason, str) else None,
            })
            return
        if uid not in room["members"]:
            return
        room["members"].discard(uid)
        out = {
            "type": "call_hangup", "call_id": call_id, "chat_id": cid,
            "from": sender, "group": True,
            "reason": str(reason)[:48] if isinstance(reason, str) else None,
        }
        for mid in list(room["members"]):
            await hub.send_user(mid, out)
        if not room["members"]:
            _CALL_ROOMS.pop(call_id, None)
        # La sala puede seguir con las demás personas: solo se actualiza
        # el contador. El anfitrión no tiene privilegios para cerrarla.
        await _broadcast_call_state(cid, room if room["members"] else None)


def _blocked_any(a: int, b: int) -> bool:
    """W28e: hay bloqueo activo en cualquier dirección."""
    return bool(db.one(
        "SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?)"
        " OR (blocker_id = ? AND blocked_id = ?) LIMIT 1",
        (a, b, b, a),
    ))


def _friends(a: int, b: int) -> bool:
    """Regla del producto: los MD y sus llamadas exigen amistad aceptada."""
    return bool(db.one(
        "SELECT 1 FROM friend_requests WHERE status = 'accepted'"
        " AND ((from_user = ? AND to_user = ?) OR (from_user = ? AND to_user = ?))"
        " LIMIT 1",
        (a, b, b, a),
    ))


def _extract_token(ws: WebSocket) -> str:
    """Token por subprotocolo ['foxinix', <token>] (navegadores) o, como
    respaldo, por query (cliente QML/desktop que no puede mandar headers)."""
    parts = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    if len(parts) >= 2 and parts[0] == _PROTO:
        return parts[1]
    return ws.query_params.get("token", "")


@router.websocket("/api/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    token = _extract_token(ws)
    payload = security.decode(token)
    if not payload or payload.get("scope") != "full":
        await ws.close(code=4401, reason="no autenticado")
        return
    user = db.one("SELECT * FROM users WHERE id = ?", (payload.get("sub", ""),))
    if not user or user["token_version"] != payload.get("tv"):
        await ws.close(code=4401, reason="sesión inválida")
        return

    uid = user["id"]
    token_exp = int(payload.get("exp") or 0)
    offered = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    await hub.connect(uid, ws, subprotocol=_PROTO if _PROTO in offered else None)
    # W64: quien abre la app (o reconecta) ve las salas de grupo que ya
    # están activas, aunque la llamada se haya creado antes.
    await _send_active_calls(ws, uid)
    auth.touch_last_seen(uid, force=True)   # presencia exacta al conectar (fuerza escritura)
    window_start = time.monotonic()
    count = 0
    call_window_start = window_start
    call_count = 0
    try:
        while True:
            raw = await ws.receive_text()
            # W45g: el handshake validaba el token una sola vez. Un logout
            # (token_version++) o el vencimiento del access dejaban la WS
            # viva para siempre, recibiendo mensajes. Se revisa en cada
            # mensaje; el ping del cliente llega cada 25 s, así que una
            # sesión revocada se corta en ese plazo aunque no haya tráfico.
            if token_exp and time.time() >= token_exp:
                await ws.close(code=4401, reason="token vencido")
                return
            fresh = db.one(
                "SELECT token_version FROM users WHERE id = ?", (uid,)
            )
            if not fresh or fresh["token_version"] != payload.get("tv"):
                await ws.close(code=4401, reason="sesión revocada")
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = None
            mtype = msg.get("type") if isinstance(msg, dict) else None
            now = time.monotonic()
            if mtype in _CALL_TYPES:
                # W63: cubo separado y más amplio para la señalización.
                if now - call_window_start >= _MSG_WINDOW:
                    call_window_start = now
                    call_count = 0
                call_count += 1
                if call_count > _CALL_MSG_LIMIT:
                    log.warning("flood de señalización: user=%s", uid)
                    await ws.close(code=1008, reason="demasiados mensajes")
                    return
            else:
                count += 1
                if count > _MSG_LIMIT:
                    # W14: ráfaga de mensajes en la WS → cortar (1008 policy).
                    if now - window_start < _MSG_WINDOW:
                        log.warning("flood de ws: user=%s", uid)
                        await ws.close(code=1008, reason="demasiados mensajes")
                        return
                    window_start = now
                    count = 0
            if not isinstance(msg, dict):
                continue
            if mtype == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
            elif mtype == "seen":
                # marcar lectura rápida desde el cliente
                try:
                    chat_id, seq = int(msg.get("chat_id", 0)), int(msg.get("seq", 0))
                except (TypeError, ValueError):
                    continue   # W14: payload tonto no tira la conexión
                # W14: el UPDATE solo toca la fila donde soy miembro; el
                # rowcount (db.run) además garantiza que el seq NUEVO avanza
                # → un no-miembro ya no puede inyectar broadcasts 'read'.
                # P1: acotar a chats.last_seq; antes un seq enorme marcaba
                # como leídos todos los mensajes futuros.
                room = db.one(
                    "SELECT c.last_seq FROM chats c JOIN chat_members m"
                    " ON m.chat_id = c.id WHERE c.id = ? AND m.user_id = ?",
                    (chat_id, uid),
                )
                if room:
                    seq = min(seq, int(room["last_seq"] or 0))
                if chat_id and room and seq and db.run(
                    "UPDATE chat_members SET last_read_seq = ?,"
                    " last_delivered_seq = MAX(last_delivered_seq, ?)"
                    " WHERE chat_id = ? AND user_id = ? AND last_read_seq < ?",
                    (seq, seq, chat_id, uid, seq),
                ) and not bool(msg.get("silent")):
                    hub.emit_to_chat(
                        chat_id,
                        {"type": "read", "chat_id": chat_id, "user_id": uid, "seq": seq},
                        exclude=uid,
                    )
            elif mtype in _CALL_TYPES:
                # W28h/W62: señalización 1:1 y malla de grupos.
                if len(raw) > _CALL_MAX:
                    continue
                if (mtype in ("call_start", "call_invite", "call_join")
                        or bool(msg.get("group"))):
                    await _handle_group_call(ws, uid, user, mtype, msg)
                    continue
                try:
                    cid = int(msg.get("chat_id", 0))
                except (TypeError, ValueError):
                    continue
                chat = db.one("SELECT type FROM chats WHERE id = ?", (cid,)) if cid else None
                if not chat or chat["type"] != "dm":
                    continue   # las llamadas son 1:1 (sin SFU de grupos)
                # W37f (auditoría): el EMISOR debe ser miembro del DM —
                # antes se relayaba la señalización (SDP/ICE arbitrarios)
                # a cualquier DM ajeno, que además era oráculo de
                # existencia de chats y de presencia del par.
                mine = db.one(
                    "SELECT hidden_at FROM chat_members"
                    " WHERE chat_id = ? AND user_id = ?",
                    (cid, uid),
                )
                if not mine:
                    continue
                peer = db.one(
                    "SELECT user_id, hidden_at FROM chat_members"
                    " WHERE chat_id = ? AND user_id != ?",
                    (cid, uid),
                )
                if not peer:
                    continue
                # MD sin amistad aceptada o eliminado por cualquiera de
                # las dos partes: no se relaya la llamada.
                if not _friends(uid, peer["user_id"]):
                    if mtype == "call_offer":
                        await ws.send_text(json.dumps(
                            {"type": "call_error", "chat_id": cid,
                             "detail": "Necesitas una solicitud de amistad aceptada"}))
                    continue
                if mine.get("hidden_at") or peer.get("hidden_at"):
                    if mtype == "call_offer":
                        await ws.send_text(json.dumps(
                            {"type": "call_error", "chat_id": cid,
                             "detail": "El chat ya no está disponible"}))
                    continue
                if _blocked_any(uid, peer["user_id"]):
                    if mtype == "call_offer":
                        await ws.send_text(json.dumps(
                            {"type": "call_error", "chat_id": cid, "detail": "Usuario bloqueado"}))
                    continue
                # W61: el panel de llamada necesita el perfil COMPLETO
                # (avatar, portada, posición, bio/estado), no solo el
                # nombre. Se relee la fila para no usar datos viejos si
                # el usuario cambió su perfil después de conectar la WS.
                fresh = db.one("SELECT * FROM users WHERE id = ?", (uid,)) or user
                out: dict[str, Any] = {
                    "type": mtype,
                    "chat_id": cid,
                    "from": _peer_user(fresh),
                }
                if mtype in ("call_offer", "call_answer"):
                    sdp = str(msg.get("sdp") or "")
                    if not sdp or len(sdp) > _SDP_MAX:
                        continue
                    out["sdp"] = sdp
                    if mtype == "call_offer":
                        out["video"] = bool(msg.get("video"))
                elif mtype == "call_ice":
                    cand = msg.get("candidate")
                    out["candidate"] = cand if isinstance(cand, dict) else None
                else:   # call_hangup
                    rsn = msg.get("reason")
                    out["reason"] = str(rsn)[:48] if isinstance(rsn, str) else None
                sent = await hub.send_user(peer["user_id"], out)
                if mtype == "call_offer" and not sent:
                    # sin sockets abiertos: avisar al llamante en vez de
                    # dejarlo esperando "Llamando…" para siempre.
                    await ws.send_text(json.dumps(
                        {"type": "call_error", "chat_id": cid, "detail": "Usuario desconectado"}))
            auth.touch_last_seen(uid)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("error en ws de usuario %s", uid)
    finally:
        await hub.disconnect(uid, ws)
        if not hub.is_online(uid):
            await _drop_user_calls(uid)
