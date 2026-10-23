#!/usr/bin/env python3
"""Smoke de seguridad (W14 + W15): endurecimiento del server.

Corre contra el server local (8899 por defecto) con datos desechables
(registra 3 usuarios nuevos). Sale con 1 si algo falla.

Cubre:
  - Cabeceras de seguridad en TODAS las respuestas + /docs apagado.
  - Token inválido/expirado → 401 en endpoints autenticados.
  - IDOR: leer/marcar un chat del que no soy miembro → 403.
  - kind=system fabricado por cliente → 400.
  - Límites de tamaño: body JSON gigante → 413; media > 15 MB → 413.
  - Buckets de rate limit: ráfaga de mensajes → 429 con retry_after.
  - URL firmada: sin firma o firma mala → 403; ?thumb=1 → 200.
  - WebSocket: subprotocolo conecta; token malo rechazado; 'seen' a un
    chat ajeno NO emite broadcast; flood → cierre 1008.

Ojo: el registro tiene cooldown por IP; si corridas seguidas devuelven 429
en register, espera ~1 min entre corridas."""
import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8899")
BASE = ap.parse_args().base

ROOT = Path(__file__).resolve().parent.parent
# FOXMSG_MAIL_LOG: apunta al mail.log del runtime de prod (p. ej.
# /home/FoxOrange/chat-server/data/mail.log) al correr contra prod.
MAIL = Path(os.environ.get("FOXMSG_MAIL_LOG", ROOT / "server" / "data" / "mail.log"))

_ok = 0
_fail = 0


def chk(name, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ok   {name}")
    else:
        _fail += 1
        print(f"  FAIL {name}  {extra}")


def http(method, path, body=None, token=None, raw=None, ctype=None):
    """Devuelve (status, body_bytes, headers_dict)."""
    headers = {}
    data = None
    if raw is not None:
        data = raw
        headers["Content-Type"] = ctype or "application/octet-stream"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def wait_code(email, timeout=8):
    pat = re.compile(rf"\| {re.escape(email)} \| verify \| (\d+)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = pat.findall(open(MAIL, encoding="utf-8").read())
            if m:
                return m[-1]
        except FileNotFoundError:
            pass
        time.sleep(0.3)
    return None


def signup(uname, email):
    st, b, _ = http("POST", "/api/auth/register",
                    {"email": email, "username": uname, "password": "foxpass12345"})
    assert st == 201, (st, b, "¿cooldown de registro por IP? Espera ~1 min")
    pending = json.loads(b)["tokens"]["access"]
    code = wait_code(email)
    assert code, f"sin código para {email}"
    st, b, _ = http("POST", "/api/auth/verify", {"code": code}, token=pending)
    assert st == 200, (st, b)
    r = json.loads(b)
    return r["user"], r["tokens"]["access"]


def multipart_post(path, token, filename, content, mime):
    bd = uuid.uuid4().hex
    body = (f"--{bd}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
    body += content + f"\r\n--{bd}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path, data=body, method="POST",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": f"multipart/form-data; boundary={bd}"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# --------------------------------------------------------------- usuarios
u = str(int(time.time()))
A_user, A = signup(f"seca{u}", f"seca{u}@example.com")
B_user, B = signup(f"secb{u}", f"secb{u}@example.com")
C_user, C = signup(f"secc{u}", f"secc{u}@example.com")   # no miembro del dm
print("registro+verify de A, B y C ok")

# Nueva regla: antes de abrir el MD hay que aceptar la solicitud de amistad.
st, b, _ = http("POST", "/api/people/requests",
                {"username": B_user["username"]}, token=A)
assert st == 201, (st, b)
rid = json.loads(b)["id"]
st, b, _ = http("POST", f"/api/people/requests/{rid}/accept", {}, token=B)
assert st == 200, (st, b)
st, b, _ = http("POST", "/api/chats/dm", {"username": B_user["username"]}, token=A)
assert st in (200, 201), (st, b)
dm = json.loads(b)["chat"]["id"]
st, b, _ = http("POST", "/api/chats/group", {"title": f"Priv {u}", "members": []}, token=A)
assert st == 201, (st, b)
priv = json.loads(b)["chat"]["id"]      # solo A es miembro (para el 403 de C)
print(f"dm={dm} priv={priv}")

# semilla: un mensaje de A en el dm (B no lo ha leído aún)
st, b, _ = http("POST", f"/api/chats/{dm}/messages",
                {"kind": "text", "body": "hola", "client_msg_id": str(uuid.uuid4())},
                token=A)
assert st == 201, (st, b)
time.sleep(1.2)

# ------------------------------------------------------- 1) cabeceras + /docs
# uvicorn serializa las cabeceras en minúscula; dict(r.headers) las respeta.
SEC_HEADERS = ["x-content-type-options", "x-frame-options", "referrer-policy",
               "permissions-policy", "content-security-policy",
               "strict-transport-security"]
st, b, h = http("GET", "/api/health")
faltan = [k for k in SEC_HEADERS if k not in h]
chk("cabeceras de seguridad presentes en /api/health", st == 200 and not faltan, faltan)
_csp = h.get("content-security-policy", "")
chk("CSP bloquea scripts inline (sin unsafe-inline en script-src)",
    "script-src 'self' 'unsafe-eval'" in _csp
    and "script-src 'self' 'unsafe-inline'" not in _csp, _csp)
st, b, _ = http("GET", "/docs")
chk("/docs apagado (404)", st == 404, st)
st, b, _ = http("GET", "/openapi.json")
chk("/openapi.json apagado (404)", st == 404, st)

# ------------------------------------------------------- 2) token inválido
st, b, _ = http("GET", "/api/chats", token="token.basura.no.valido")
chk("GET /chats con token basura → 401", st == 401, st)
st, b, _ = http("GET", "/api/users/me", token="token.basura.no.valido")
chk("GET /users/me con token basura → 401", st == 401, st)
st, b, _ = http("POST", f"/api/chats/dm", {"username": B_user["username"]},
                token="token.basura.no.valido")
chk("crear chat con token basura → 401", st == 401, st)

# ------------------------------------------------------------- 3) IDOR 403
st, b, _ = http("GET", f"/api/chats/{dm}/messages", token=C)
chk("leer mensajes de un chat ajeno → 403", st == 403, st)
st, b, _ = http("POST", f"/api/chats/{dm}/read", {"seq": 1}, token=C)
chk("marcar leído un chat ajeno → 403", st == 403, st)
st, b, _ = http("GET", f"/api/chats/{dm}/members", token=C)
chk("listar miembros de un chat ajeno → 403", st == 403, st)
st, b, _ = http("POST", f"/api/chats/{priv}/messages",
                {"kind": "text", "body": "intruso", "client_msg_id": str(uuid.uuid4())},
                token=C)
chk("escribir en un chat privado ajeno → 403", st == 403, st)

# ------------------------------------------- 4) kind=system y body gigante
st, b, _ = http("POST", f"/api/chats/{dm}/messages",
                {"kind": "system", "body": "soy el server"},
                token=A)
chk("kind=system fabricado por cliente → 400", st == 400, st)

big_body = {"kind": "text", "body": "x" * (100 * 1024)}   # ~100 KB > tope 64 KB
st, b, _ = http("POST", f"/api/chats/{dm}/messages", big_body, token=A)
chk("body JSON > 64 KB → 413", st == 413, st)

# --------------------------------------------------------- 5) media > 15 MB
# El server rechaza por content-length ANTES de leer el body (middleware).
# Mandamos los headers con Content-Length de 16 MB pero solo unos KB de
# cuerpo por un socket crudo, y leemos la 413 sin tener que subir los 16 MB
# (con urllib completo el server cerraría el socket a media subida y el
# cliente vería Connection reset en vez del 413).
_host = BASE.split("//")[1].split("/")[0].split(":")[0]
_port = int(BASE.rsplit(":", 1)[1].rstrip("/")) if ":" in BASE.split("//")[1].split("/")[0] else 80
_req = (
    "POST /api/media HTTP/1.1\r\n"
    f"Host: {_host}:{_port}\r\n"
    f"Authorization: Bearer {A}\r\n"
    "Content-Type: application/octet-stream\r\n"
    f"Content-Length: {16 * 1024 * 1024}\r\n"
    "Connection: close\r\n\r\n"
).encode()
_s = socket.create_connection((_host, _port), timeout=10)
_s.sendall(_req + b"\x00" * 4096)          # headers + un poco de cuerpo
_data = b""
try:
    while True:
        _chunk = _s.recv(4096)
        if not _chunk:
            break
        _data += _chunk
except OSError:
    pass
_s.close()
_status = _data.split(b"\r\n", 1)[0].decode(errors="replace")
_code = int(_status.split()[1]) if len(_status.split()) > 1 and _status.split()[1].isdigit() else 0
chk("subida de media > 15 MB → 413", _code == 413, _status)

# ------------------------------------------------------ 6) bucket mensajes
time.sleep(3)                            # deja que el bucket reparta unos tokens
codes = []
for i in range(12):
    st, b, _ = http("POST", f"/api/chats/{dm}/messages",
                    {"kind": "text", "body": f"rafaga {i}",
                     "client_msg_id": str(uuid.uuid4())}, token=A)
    codes.append(st)
chk("ráfaga de mensajes dispara 429", 429 in codes, codes)
st, b, _ = http("POST", f"/api/chats/{dm}/messages",
                {"kind": "text", "body": "tras la ráfaga"}, token=A)
chk("el 429 trae retry_after numérico",
    st != 429 or isinstance(json.loads(b).get("detail", {}).get("retry_after"), int),
    (st, b))

# --------------------------------------------------- 7) URL firmada + thumb
png = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")
st, b = multipart_post("/api/media", B, "thumb.png", png, "image/png")
assert st == 201, (st, b)
img_url = json.loads(b)["url"]           # /media/file/<slug>.webp?exp=..&sig=..
st, b, _ = http("GET", img_url)
chk("URL firmada válida → 200", st == 200, st)
st, b, _ = http("GET", f"{img_url}&thumb=1")
chk("?thumb=1 sirve la miniatura → 200", st == 200, st)
# firma manipulada (cambia el sig) → 403
bad_sig = re.sub(r"sig=[0-9a-f]+", "sig=" + "0" * 32, img_url)
st, b, _ = http("GET", bad_sig)
chk("firma manipulada → 403", st == 403, st)
# media por id sin token → 401
st, b, _ = http("GET", "/api/media/1")
chk("/api/media/{id} sin token → 401", st == 401, st)

# ----------------------------------------------------------- 8) WebSocket
# Ojo: `import websockets` NO trae el submódulo sync; hay que importarlo.
from websockets.sync.client import connect as ws_connect   # noqa: E402
from websockets.exceptions import ConnectionClosed         # noqa: E402

WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")


def ws_open(token):
    """Conecta por subprotocolo ['foxinix', <token>]. Devuelve el socket o
    None si el server lo rechaza (token malo → cierre antes de aceptar)."""
    try:
        return ws_connect(WS_BASE + "/api/ws", subprotocols=["foxinix", token],
                          open_timeout=5)
    except Exception:
        return None


def ws_recv_type(ws, timeout=5):
    """Recibe un evento y devuelve su 'type' (o None si expira)."""
    try:
        return json.loads(ws.recv(timeout=timeout)).get("type")
    except TimeoutError:
        return None


# 8a) subprotocolo válido conecta y responde ping/pong
wsA = ws_open(A)
chk("WS conecta con subprotocolo foxinix", wsA is not None)
if wsA:
    with wsA:
        chk("el primer evento es 'connected'", ws_recv_type(wsA) == "connected")
        wsA.send(json.dumps({"type": "ping"}))
        # El snapshot inicial de presencia puede llegar entre 'connected'
        # y 'pong'; no es un fallo del ping, así que se ignora.
        pong = None
        for _ in range(8):
            pong = ws_recv_type(wsA, timeout=2.0)
            if pong == "pong":
                break
        chk("ping → pong", pong == "pong", pong)

# 8b) token malo → rechazado (no se establece)
wsBad = ws_open("token.basura.no.valido")
chk("WS con token malo se rechaza", wsBad is None)
if wsBad:
    wsBad.close()

# 8c) 'seen' a un chat AJENO no emite broadcast 'read' a los miembros
wsA = ws_open(A)
wsC = ws_open(C)
if wsA and wsC:
    with wsA, wsC:
        ws_recv_type(wsA)   # consume 'connected'
        ws_recv_type(wsC)   # consume 'connected'
        # C no es miembro del dm: el UPDATE toca 0 filas → sin broadcast.
        wsC.send(json.dumps({"type": "seen", "chat_id": dm, "seq": 5}))
        got = ws_recv_type(wsA, timeout=2.0)
        chk("'seen' de un no-miembro no emite broadcast 'read'", got != "read", got)
else:
    chk("'seen' ajeno sin broadcast (no se pudo abrir WS)", False, "wsA/wsC")

# 8d) flood de mensajes → cierre 1008 (policy)
wsA = ws_open(A)
if wsA:
    with wsA:
        ws_recv_type(wsA)   # consume 'connected'
        code = None
        for i in range(45):
            try:
                wsA.send(json.dumps({"type": "x", "n": i}))
            except ConnectionClosed as e:
                code = e.code
                break
        if code is None:
            # Consumir presencia/snapshot antes del frame de cierre; el
            # cierre real sigue siendo obligatorio (si no llega, code=None).
            for _ in range(8):
                try:
                    ev = ws_recv_type(wsA, timeout=4)
                except ConnectionClosed as e:
                    code = e.code
                    break
                if ev is None:
                    break
        chk("flood de 45 mensajes → cierre 1008", code == 1008, code)
else:
    chk("flood WS (no se pudo abrir WS)", False)

print(f"\nsecurity smoke: {_ok} ok, {_fail} fallas")
sys.exit(1 if _fail else 0)
