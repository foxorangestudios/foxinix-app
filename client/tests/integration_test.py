#!/usr/bin/env python3
"""Test de integración del cliente contra el servidor real.

Cubre: failover de servidor, registro->perfil->verify->login, chats,
envío con idempotencia, caché local, y WS en vivo.

Uso: BASE=http://100.125.128.82:8444 python3 tests/integration_test.py
"""
from __future__ import annotations

import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if os.environ.get("BASE"):
    os.environ["FOXMSG_SERVER"] = os.environ["BASE"]

from core import api as api_mod  # noqa: E402
from core import cache, config  # noqa: E402
from core import session as session_mod  # noqa: E402
from core.api import ApiError  # noqa: E402

api: api_mod.Api = api_mod.api
session = session_mod.session

RUN = str(int(time.time()))
UA, UB = f"cli{RUN}", f"clib{RUN}"
PASS = "clave12345"
FAIL = 0


def check(desc: str, cond: bool, extra: str = "") -> None:
    global FAIL
    if cond:
        print(f"   OK  {desc} {extra}")
    else:
        print(f"   FALLÓ {desc} {extra}")
        FAIL = 1


def main() -> int:
    # limpiar caché/sesión de pruebas previas
    cache.clear_all()
    session.clear()

    print("== 1. servidor alcanzable y failover ==")
    health = api.get("/api/health", auth=False)
    check("health", health.get("ok") is True, f"base={api.base}")

    print("== 2. registro (scope pending) ==")
    r = api.post("/api/auth/register", {
        "email": f"{UA}@{RUN}.test", "username": UA, "password": PASS})
    check("registro", "tokens" in r and r["user"]["email_verified"] is False)
    api.set_tokens(r["tokens"]["access"], r["tokens"]["refresh"])

    print("== 3. pending NO puede chatear ==")
    try:
        api.get("/api/chats")
        check("bloqueado 403", False)
    except ApiError as e:
        check("bloqueado 403", e.status == 403, f"status={e.status}")

    print("== 4. perfil con avatar (pending) ==")
    # PNG 1x1 mínimo
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
        "nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII=")
    up = api.upload("/api/media", "a.png", png, "image/png")
    check("subida", up["id"] > 0, f"id={up['id']} size={up['size']}")
    prof = api.put("/api/auth/profile", {
        "display_name": "Cliente Test", "avatar_media_id": up["id"]})
    check("profile", prof["user"]["display_name"] == "Cliente Test")
    # W11: el avatar viene como URL firmada /media/profile/… (sin token)
    av = prof["user"]["avatar_url"] or ""
    check("avatar_url firmada", av.startswith("/media/profile/") and "sig=" in av, av)

    print("== 5. media firmada (W11) ==")
    import httpx
    check("url sin token de cuenta", "token=" not in av, av)
    no_sig = httpx.get(api.base + av.split("?")[0], timeout=10)
    check("sin firma 403", no_sig.status_code == 403, f"status={no_sig.status_code}")
    with_sig = httpx.get(api.base + av, timeout=10)
    check("con firma 200", with_sig.status_code == 200 and len(with_sig.content) > 0,
          f"status={with_sig.status_code}")
    # el endpoint viejo por id sigue exigiendo token (compat con clientes legacy)
    no_tok = httpx.get(api.base + f"/api/media/{up['id']}", timeout=10)
    check("viejo sin token 401", no_tok.status_code == 401, f"status={no_tok.status_code}")

    print("== 6. cooldown de reenvío ==")
    try:
        api.post("/api/auth/resend", {"purpose": "verify"})
        check("429 dentro del cooldown", False)
    except ApiError as e:
        check("429 dentro del cooldown", e.status == 429, f"status={e.status}")

    print("== 7. código + verify ==")
    # leer código del servidor (modo prueba: mail.log)
    import subprocess
    if os.environ.get("REMOTE") != "0":
        code = subprocess.run(
            ["sshpass", "-p", os.environ.get("PASS", "123"),
             "ssh", "-o", "StrictHostKeyChecking=accept-new",
             os.environ.get("REMOTE_HOST", "1"),
             "tail -1 /home/FoxOrange/chat-server/data/mail.log"],
            capture_output=True, text=True).stdout.strip().split("|")[-1].strip()
    else:
        code = open(config.app_data_dir() / "mail.log").read().strip().split("|")[-1].strip()
    check("código leído", len(code) == 6, f"code={code}")
    v = api.post("/api/auth/verify", {"code": code})
    check("verificado", v.get("verified") is True)
    api.set_tokens(v["tokens"]["access"], v["tokens"]["refresh"])
    session.set_auth(v["tokens"], v["user"])

    print("== 8. segundo usuario + dm ==")
    r2 = api.post("/api/auth/register", {
        "email": f"{UB}@{RUN}.test", "username": UB, "password": PASS})
    tb = r2["tokens"]["access"]
    time.sleep(1)
    code2 = subprocess.run(
        ["sshpass", "-p", os.environ.get("PASS", "123"),
         "ssh", "-o", "StrictHostKeyChecking=accept-new",
         os.environ.get("REMOTE_HOST", "1"),
         "tail -1 /home/FoxOrange/chat-server/data/mail.log"],
        capture_output=True, text=True).stdout.strip().split("|")[-1].strip()
    v2 = httpx.post(api.base + "/api/auth/verify", json={"code": code2},
                    headers={"Authorization": f"Bearer {tb}"}, timeout=10)
    check("bruno verificado", v2.status_code == 200 and v2.json().get("verified"),
          f"status={v2.status_code}")
    tb = v2.json()["tokens"]["access"]  # ahora scope full

    chat = api.post("/api/chats/dm", {"username": UB})["chat"]
    check("dm creado", chat["type"] == "dm", f"id={chat['id']}")
    chat2 = api.post("/api/chats/dm", {"username": UB})["chat"]
    check("dm idempotente", chat["id"] == chat2["id"])

    print("== 9. envío + idempotencia + caché ==")
    cmid = uuid.uuid4().hex
    m1 = api.post(f"/api/chats/{chat['id']}/messages",
                  {"kind": "text", "body": "hola desde el cliente",
                   "client_msg_id": cmid})["message"]
    m2 = api.post(f"/api/chats/{chat['id']}/messages",
                  {"kind": "text", "body": "hola desde el cliente",
                   "client_msg_id": cmid})["message"]
    check("idempotente", m1["seq"] == m2["seq"], f"seq={m1['seq']}")

    cache.upsert_messages([m1])
    cache.upsert_chat(chat)
    cached = cache.cached_messages(chat["id"])
    check("caché local", any(x["id"] == m1["id"] for x in cached),
          f"last_seq={cache.last_seq(chat['id'])}")

    print("== 10. WS en vivo ==")
    from core.ws import ws_client
    import threading
    events: list[dict] = []
    got = threading.Event()

    def on_event(e):
        events.append(e)
        if e.get("type") == "message":
            got.set()

    ws_client.on_event = on_event
    ws_client.start(api.ws_url)
    time.sleep(1.5)  # dejar conectar

    # enviar por REST desde "el otro usuario"
    httpx.post(api.base + f"/api/chats/{chat['id']}/messages",
               json={"kind": "text", "body": "en vivo!", "client_msg_id": uuid.uuid4().hex},
               headers={"Authorization": f"Bearer {tb}"}, timeout=10)

    ok = got.wait(timeout=8)
    check("evento message recibido", ok,
          f"tipos={[e.get('type') for e in events]}")
    if ok:
        evt = next(e for e in events if e.get("type") == "message")
        check("payload correcto", evt["message"]["body"] == "en vivo!")

    ws_client.stop()

    print("== 11. historial y no leídos ==")
    msgs = api.get(f"/api/chats/{chat['id']}/messages", params={"limit": 50})
    check("historial", len(msgs["messages"]) >= 2, f"n={len(msgs['messages'])}")
    chats = api.get("/api/chats")["chats"]
    mine = next(c for c in chats if c["id"] == chat["id"])
    check("chat en lista", mine is not None,
          f"unread={mine['unread']} title={mine['title']['display_name']}")

    print("== 12. búsqueda ==")
    res = api.get("/api/users/search", params={"q": UB})["results"]
    check("encuentra contacto", any(x["username"] == UB for x in res),
          f"n={len(res)}")

    print("== 13. logout inválida el token (token_version) ==")
    # resetear contraseña de UB invalida sus tokens
    api.set_tokens(r2["tokens"]["access"], r2["tokens"]["refresh"])
    httpx.post(api.base + "/api/auth/forgot",
               json={"identifier": UB}, timeout=10)
    time.sleep(1)
    code3 = subprocess.run(
        ["sshpass", "-p", os.environ.get("PASS", "123"),
         "ssh", "-o", "StrictHostKeyChecking=accept-new",
         os.environ.get("REMOTE_HOST", "1"),
         "tail -1 /home/FoxOrange/chat-server/data/mail.log"],
        capture_output=True, text=True).stdout.strip().split("|")[-1].strip()
    httpx.post(api.base + "/api/auth/reset",
               json={"identifier": UB, "code": code3, "password": "otraclave99"},
               timeout=10)
    try:
        httpx.get(api.base + "/api/users/me",
                  headers={"Authorization": f"Bearer {r2['tokens']['access']}"},
                  timeout=10)
        # el refresh también debe fallar
        r = httpx.post(api.base + "/api/auth/refresh",
                       json={"refresh": r2["tokens"]["refresh"]}, timeout=10)
        check("tokens viejos invalidados", r.status_code == 401,
              f"status={r.status_code}")
    except Exception as exc:
        check("tokens viejos invalidados", False, str(exc))

    print("== 14. limite de archivo (50 MB) ==")
    # a) rechazo local: el cliente no siquiera intenta enviar 51 MB
    try:
        api.upload("/api/media", "big.bin", b"0" * (51 * 1024 * 1024),
                   "application/octet-stream")
        check("51MB rechazado en cliente", False)
    except ApiError as e:
        check("51MB rechazado en cliente", e.status == 413, f"status={e.status}")

    # b) middleware del servidor: rechaza por Content-Length ANTES de leer
    import socket as socket_mod
    from urllib.parse import urlparse
    u = urlparse(api.base)
    s = socket_mod.create_connection((u.hostname, u.port or 80), timeout=10)
    hdrs = (f"POST /api/media HTTP/1.1\r\nHost: {u.hostname}\r\n"
            f"Content-Length: {51 * 1024 * 1024}\r\n"
            f"Content-Type: application/octet-stream\r\n"
            f"Authorization: Bearer {api.access}\r\n"
            f"Connection: close\r\n\r\n")
    s.sendall(hdrs.encode())
    s.settimeout(5)
    resp = b""
    try:
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b"\r\n\r\n" in resp:
                break
    except socket_mod.timeout:
        pass
    s.close()
    status = resp.split(b" ")[1].decode() if resp.startswith(b"HTTP") else "?"
    check("servidor rechaza por Content-Length", status == "413", f"status={status}")

    print()
    if FAIL == 0:
        print("=== INTEGRATION TEST: OK ===")
    else:
        print("=== INTEGRATION TEST: FALLOS ===")
    return FAIL


if __name__ == "__main__":
    sys.exit(main())
