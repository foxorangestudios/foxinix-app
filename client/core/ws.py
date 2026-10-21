"""Cliente WebSocket en hilo propio con reconexión automática.

Emite señales Qt en el hilo principal vía `bridge` (que es un QObject).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import websockets
# websockets >= 13: `websockets.connect` apunta al cliente async, que solo
# sirve con `async with`. Este hilo es síncrono → usar el cliente sync.
from websockets.sync.client import connect as ws_connect

log = logging.getLogger("foxmsg.client.ws")


class WsClient:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._send_q: list[str] = []
        self._ws = None
        self.on_event: Callable[[dict], None] | None = None
        self.on_status: Callable[[str], None] | None = None

    # ------------------------------------------------------------ ciclo

    def start(self, url_provider: Callable[[], str]) -> None:
        """url_provider se llama en cada (re)conexión para refrescar el token."""
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(url_provider,), daemon=True, name="foxmsg-ws"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=3)
        self._thread = None

    def send(self, payload: dict[str, Any]) -> None:
        self._send_q.append(json.dumps(payload))

    # ------------------------------------------------------------ loop

    def _run(self, url_provider: Callable[[], str]) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                url = url_provider()
                with ws_connect(url, open_timeout=10, ping_interval=20) as ws:
                    self._ws = ws
                    backoff = 1.0
                    self._status("connected")
                    self._pump(ws)
            except Exception as exc:
                self._ws = None
                self._status(f"reconnecting: {exc}")
            if self._stop.is_set():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
        self._status("stopped")

    def _pump(self, ws) -> None:
        """Intercambia mensajes: envía de la cola y recibe eventos."""
        while not self._stop.is_set():
            # enviar pendientes
            while self._send_q:
                msg = self._send_q.pop(0)
                try:
                    ws.send(msg)
                except Exception:
                    self._send_q.insert(0, msg)
                    raise
            # recibir con timeout corto para poder drenar la cola
            try:
                raw = ws.recv(timeout=0.3)
            except TimeoutError:
                continue
            except TypeError:
                # websockets versions sin timeout kwarg en recv
                raw = ws.recv()
            try:
                evt = json.loads(raw)
            except Exception:
                continue
            self._dispatch(evt)

    # ------------------------------------------------------------ callbacks

    def _dispatch(self, evt: dict) -> None:
        if self.on_event:
            try:
                self.on_event(evt)
            except Exception:
                log.exception("error procesando evento %s", evt.get("type"))

    def _status(self, state: str) -> None:
        if self.on_status:
            try:
                self.on_status(state)
            except Exception:
                pass


ws_client = WsClient()
