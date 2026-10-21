"""Hub de WebSockets: broadcast en vivo por chat.

Conexión:  WS /api/ws?token=<access_token>
Eventos servidor->cliente:
  {"type":"connected", "server_time"}
  {"type":"message", "message": {...}}
  {"type":"delivered", "chat_id", "seq", "user_ids"}   -- W12: 'recibido'
  {"type":"typing", "chat_id", "user_id", "username"}
  {"type":"read", "chat_id", "user_id", "seq"}
  {"type":"reaction" | "reaction_removed", ...}
  {"type":"members_changed", "chat_id"}
  {"type":"member_role", "chat_id", "user_id", "role", "by"}
  {"type":"member_removed", "chat_id", "user_id", "by", "title"}
  {"type":"chat_created", "chat_id"}
  {"type":"presence", "user_id", "online"}
Eventos cliente->servidor (JSON): {"type":"ping"} -> {"type":"pong"}
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("foxmsg.ws")


def _mark_delivered(chat_id: int, user_id: int, seq: int) -> None:
    """W12: 'recibido' — el mensaje seq llegó al dispositivo del usuario
    (push por su WS o fetch por REST). Solo sube, nunca baja."""
    from . import db

    try:
        db.execute(
            "UPDATE chat_members SET last_delivered_seq = MAX(last_delivered_seq, ?)"
            " WHERE chat_id = ? AND user_id = ?",
            (seq, chat_id, user_id),
        )
    except Exception:  # pragma: no cover - el hub nunca debe caerse por esto
        log.warning("mark_delivered falló chat=%s user=%s", chat_id, user_id, exc_info=True)


class Hub:
    def __init__(self) -> None:
        # user_id -> conjunto de websockets (varios dispositivos/pestañas)
        self._conns: dict[int, set[WebSocket]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._futures: set = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self) -> None:
        """Llamar desde el evento loop de la app (startup)."""
        with contextlib.suppress(RuntimeError):
            self._loop = asyncio.get_running_loop()

    # ---------------------------------------------------------- conexión

    async def connect(
        self, user_id: int, ws: WebSocket, subprotocol: str | None = None
    ) -> None:
        conns = self._conns.setdefault(user_id, set())
        # W14: tope de conexiones por usuario (pestañas/dispositivos);
        # el exceso cierra la más vieja en lugar de acumular sockets.
        while len(conns) >= 8:
            old = conns.pop()
            try:
                await old.close(code=4408, reason="demasiadas conexiones")
            except Exception:  # pragma: no cover - cierre de un socket ajeno
                pass
        conns.add(ws)
        await ws.accept(subprotocol)
        await self.send_user(user_id, {"type": "connected", "server_time": int(time.time())})
        # W26: snapshot de presencia de los contactos. Cada (re)conexión
        # re-sincroniza el estado autoritativo: sin esto, un evento perdido
        # en una ventana de reconexión dejaba al contacto "en línea" para
        # siempre (hasta recargar). Los invisibles nunca se ven en línea.
        peers = self._peers_of(user_id)
        if peers:
            from . import db

            qs = ",".join("?" for _ in peers)
            invis = {
                r["id"]
                for r in db.rows(
                    "SELECT id FROM users WHERE status_preset = 'invisible'"
                    f" AND id IN ({qs})",
                    tuple(peers),
                )
            }
            for peer in peers:
                await self.send_user(
                    user_id,
                    {
                        "type": "presence",
                        "user_id": peer,
                        "online": self.is_online(peer) and peer not in invis,
                    },
                )
        if self._is_invisible(user_id):
            return   # estado "invisible": los contactos no ven el cambio a en línea
        for peer in peers:
            await self.send_user(peer, {"type": "presence", "user_id": user_id, "online": True})

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        conns = self._conns.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self._conns.pop(user_id, None)
                if self._is_invisible(user_id):
                    return   # nunca los avisó en línea: no avisar la salida
                for peer in self._peers_of(user_id):
                    await self.send_user(
                        peer, {"type": "presence", "user_id": user_id, "online": False}
                    )

    async def close_user(
        self, user_id: int, code: int = 4401, reason: str = "sesión cerrada"
    ) -> None:
        """Cierra todas las WS de un usuario (logout, reset, borrado).

        W45g: la WS no debe sobrevivir a la revocación de la sesión. No
        borra las conexiones del mapa a mano: cada endpoint, al recibir
        el cierre, pasa por disconnect() y avisa la presencia offline.
        """
        for ws in list(self._conns.get(user_id, ())):
            try:
                await ws.close(code=code, reason=reason)
            except Exception:  # pragma: no cover - socket ya cerrado
                pass

    def kick_user(self, user_id: int) -> None:
        """Programa close_user desde un endpoint sync."""
        self.schedule(self.close_user(user_id))

    def is_online(self, user_id: int) -> bool:
        return user_id in self._conns

    def _is_invisible(self, user_id: int) -> bool:
        from . import db

        row = db.one("SELECT status_preset FROM users WHERE id = ?", (user_id,))
        return bool(row) and (row.get("status_preset") or "") == "invisible"

    # ---------------------------------------------------------- consulta

    def _peers_of(self, user_id: int) -> list[int]:
        from . import db

        rows = db.rows(
            "SELECT DISTINCT cm2.user_id AS uid FROM chat_members cm1"
            " JOIN chat_members cm2 ON cm2.chat_id = cm1.chat_id"
            " WHERE cm1.user_id = ? AND cm2.user_id != ?",
            (user_id, user_id),
        )
        return [r["uid"] for r in rows]

    # ---------------------------------------------------------- envío async

    async def send_user(self, user_id: int, payload: dict[str, Any]) -> int:
        """Envía a todos los sockets del usuario. Devuelve cuántos lo recibieron
        (W12: sirve para marcar 'recibido' solo si de verdad llegó)."""
        data = json.dumps(payload, ensure_ascii=False)
        conns = self._conns.get(user_id, ())
        log.debug("send_user=%s conns=%s tipo=%s", user_id, len(conns), payload.get("type"))
        sent = 0
        for ws in list(conns):
            try:
                await ws.send_text(data)
                sent += 1
            except Exception:
                with contextlib.suppress(KeyError):
                    self._conns[user_id].discard(ws)
        return sent

    async def broadcast_peers(self, user_id: int, payload: dict[str, Any]) -> None:
        """Envía un evento a todos los contactos (quienes comparten chat).

        W15: se usa para difundir cambios de perfil (nombre, avatar…).
        """
        for peer in self._peers_of(user_id):
            await self.send_user(peer, payload)

    async def broadcast_chat(
        self, chat_id: int, payload: dict[str, Any], exclude: int | None = None
    ) -> None:
        from . import db

        rows = db.rows("SELECT user_id FROM chat_members WHERE chat_id = ?", (chat_id,))
        log.debug("broadcast_chat chat=%s a %s: %s", chat_id, [r["user_id"] for r in rows], payload.get("type"))
        msg_seq = 0
        if payload.get("type") == "message":
            msg_seq = int((payload.get("message") or {}).get("seq") or 0)
        got: list[int] = []
        for r in rows:
            if exclude is not None and r["user_id"] == exclude:
                continue
            if await self.send_user(r["user_id"], payload) > 0 and msg_seq:
                got.append(r["user_id"])
        if msg_seq and got:
            # W12: 'recibido' — llegó por su conexión. Se avisa al chat entero
            # (el emisor pinta ✓✓; en los demás clientes es inofensivo).
            for uid in got:
                _mark_delivered(chat_id, uid, msg_seq)
            with contextlib.suppress(Exception):
                await self.broadcast_chat(
                    chat_id,
                    {"type": "delivered", "chat_id": chat_id, "seq": msg_seq,
                     "user_ids": got},
                )

    # ---------------------------------------------------------- desde routers sync

    def emit_to_chat(
        self, chat_id: int, payload: dict[str, Any], exclude: int | None = None
    ) -> None:
        """Programa un broadcast desde código síncrono (routers FastAPI)."""
        self.schedule(self.broadcast_chat(chat_id, payload, exclude))

    def emit_to_user(self, user_id: int, payload: dict[str, Any]) -> None:
        self.schedule(self.send_user(user_id, payload))

    def emit_to_peers(self, user_id: int, payload: dict[str, Any]) -> None:
        """Programa un envío a los contactos (desde routers síncronos)."""
        self.schedule(self.broadcast_peers(user_id, payload))

    def notify_chat_created(self, chat_id: int, user_ids: list[int]) -> None:
        for uid in user_ids:
            self.emit_to_user(uid, {"type": "chat_created", "chat_id": chat_id})

    def schedule(self, coro) -> None:
        """Programa una coroutina de forma thread-safe.

        Los endpoints sync de FastAPI corren en un threadpool: desde ahí hay
        que usar run_coroutine_threadsafe (create_task no es thread-safe).
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            log.warning("schedule: loop no disponible (loop=%s) — coroutina descartada", loop)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                coro.close()
                return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        log.debug("schedule: running=%s loop=%s mismo=%s", running, loop, running is loop)

        if running is loop:
            task = loop.create_task(coro)
            self._tasks.add(task)
            task.add_done_callback(self._task_done)
        else:
            try:
                fut = asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                coro.close()
                return
            self._futures.add(fut)
            fut.add_done_callback(self._future_done)

    def _future_done(self, fut: "asyncio.Future") -> None:
        self._futures.discard(fut)
        try:
            exc = fut.exception()
        except (asyncio.CancelledError, Exception):
            return
        if exc:
            log.error("tarea de hub falló: %s", exc, exc_info=exc)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            log.error("tarea de hub falló: %s", exc, exc_info=exc)


hub = Hub()
