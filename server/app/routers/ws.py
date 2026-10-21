"""Endpoint WebSocket de tiempo real."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import security, db, auth
from ..realtime import hub

log = logging.getLogger("foxmsg.ws")
router = APIRouter(tags=["ws"])

_PROTO = "foxinix"    # W14: el token viaja como subprotocolo (no en la URL:
                      # los tokens no deben aparecer en los logs de acceso)
_MSG_LIMIT = 40       # W14: mensajes por ventana para frenar floods
_MSG_WINDOW = 10.0

# W28h: señalización de llamadas WebRTC 1:1. El server solo relaya al otro
# miembro del DM (valida membresía y bloqueo); ni ve ni guarda media.
_CALL_TYPES = ("call_offer", "call_answer", "call_ice", "call_hangup")
_CALL_MAX = 32768     # tope del mensaje crudo (un SDP ronda ~8 KB)
_SDP_MAX = 20000


def _blocked_any(a: int, b: int) -> bool:
    """W28e: hay bloqueo activo en cualquier dirección."""
    return bool(db.one(
        "SELECT 1 FROM blocks WHERE (blocker_id = ? AND blocked_id = ?)"
        " OR (blocker_id = ? AND blocked_id = ?) LIMIT 1",
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
    auth.touch_last_seen(uid, force=True)   # presencia exacta al conectar (fuerza escritura)
    window_start = time.monotonic()
    count = 0
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
            count += 1
            if count > _MSG_LIMIT:
                # W14: ráfaga de mensajes en la WS → cortar (1008 policy).
                now = time.monotonic()
                if now - window_start < _MSG_WINDOW:
                    log.warning("flood de ws: user=%s", uid)
                    await ws.close(code=1008, reason="demasiados mensajes")
                    return
                window_start = now
                count = 0
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            mtype = msg.get("type")
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
                if chat_id and seq and db.run(
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
                # W28h: oferta/respuesta/ICE/colgar de una llamada 1:1.
                if len(raw) > _CALL_MAX:
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
                    "SELECT 1 AS x FROM chat_members"
                    " WHERE chat_id = ? AND user_id = ?",
                    (cid, uid),
                )
                if not mine:
                    continue
                peer = db.one(
                    "SELECT user_id FROM chat_members WHERE chat_id = ? AND user_id != ?",
                    (cid, uid),
                )
                if not peer:
                    continue
                if _blocked_any(uid, peer["user_id"]):
                    if mtype == "call_offer":
                        await ws.send_text(json.dumps(
                            {"type": "call_error", "chat_id": cid, "detail": "Usuario bloqueado"}))
                    continue
                out: dict[str, Any] = {
                    "type": mtype,
                    "chat_id": cid,
                    "from": {"id": uid, "username": user["username"],
                             "display_name": user["display_name"] or user["username"]},
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
