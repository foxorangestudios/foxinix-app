#!/usr/bin/env python3
"""Test de WebSocket: ana envía, bruno recibe en vivo."""
import asyncio
import json
import sys

import httpx

import os
BASE = os.environ.get("BASE", "http://127.0.0.1:8899")
WSBASE = os.environ.get("WSBASE", "ws://127.0.0.1:8899")


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE) as c:
        async def login(identifier: str) -> dict:
            for pw in ("clave12345", "nuevaclave99"):
                r = await c.post("/api/auth/login", json={"identifier": identifier, "password": pw})
                if r.status_code == 200:
                    return r.json()
            raise SystemExit(f"login falló para {identifier}: {r.text}")

        ra = await login("ana")
        rb = await login("bruno")
        ta, tb = ra["tokens"]["access"], rb["tokens"]["access"]
        chat = (await c.post("/api/chats/dm", json={"username": "bruno"},
                             headers={"Authorization": f"Bearer {ta}"})).json()["chat"]

    import websockets

    async with websockets.connect(f"{WSBASE}/api/ws?token={tb}") as ws_w:
        hello = json.loads(await asyncio.wait_for(ws_w.recv(), 5))
        assert hello["type"] == "connected", hello
        print("conectado:", hello)

        async with websockets.connect(f"{WSBASE}/api/ws?token={ta}") as ws_a:
            await asyncio.wait_for(ws_a.recv(), 5)  # connected

            # ana envía un mensaje vía REST (client_msg_id único por corrida)
            import uuid
            cmid = f"ws-{uuid.uuid4().hex[:10]}"
            async with httpx.AsyncClient(base_url=BASE) as c:
                r = await c.post(
                    f"/api/chats/{chat['id']}/messages",
                    json={"kind": "text", "body": "en vivo!", "client_msg_id": cmid},
                    headers={"Authorization": f"Bearer {ta}"},
                )
                assert r.status_code == 201, r.text

            # bruno debe recibir el evento message (salteando presencia/ping)
            evt = None
            for _ in range(10):
                e = json.loads(await asyncio.wait_for(ws_w.recv(), 5))
                print("  evt:", e.get("type"))
                if e["type"] == "message":
                    evt = e
                    break
            assert evt, "no se recibió el evento message"
            assert evt["message"]["body"] == "en vivo!", evt
            print("bruno recibió en vivo:", evt["message"]["body"])

            # ping/pong
            await ws_w.send(json.dumps({"type": "ping"}))
            pong = json.loads(await asyncio.wait_for(ws_w.recv(), 5))
            assert pong["type"] == "pong", pong
            print("ping/pong OK")

    print("=== WS TEST OK ===")
    return 0


sys.exit(asyncio.run(main()))
