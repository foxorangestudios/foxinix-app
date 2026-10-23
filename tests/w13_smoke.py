#!/usr/bin/env python3
"""Smoke W13: fijar/silenciar chats, buscar en mensajes, reenviar y onda de voz.

Corre contra el server local (8899 por defecto) con datos desechables
(registra 2 usuarios nuevos). Sale con 1 si algo falla.
Ojo: el registro tiene cooldown por IP; si corridas seguidas devuelven 429
en register, espera ~1 min entre corridas."""
import argparse
import json
import os
import re
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


def http(method, path, body=None, token=None):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


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
    st, b = http("POST", "/api/auth/register",
                 {"email": email, "username": uname, "password": "foxpass12345"})
    assert st == 201, (st, b, "¿cooldown de registro por IP? Espera ~1 min")
    pending = json.loads(b)["tokens"]["access"]
    code = wait_code(email)
    assert code, f"sin código para {email}"
    st, b = http("POST", "/api/auth/verify", {"code": code}, token=pending)
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
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def send_text(token, chat_id, text):
    st, b = http("POST", f"/api/chats/{chat_id}/messages",
                 {"kind": "text", "body": text, "client_msg_id": str(uuid.uuid4())},
                 token=token)
    time.sleep(1.2)   # respetar el rate limit (~3/5 s)
    return st, json.loads(b)


# ------------------------------------------------------------- usuarios
u = str(int(time.time()))
A_user, A = signup(f"w13a{u}", f"w13a{u}@example.com")
B_user, B = signup(f"w13b{u}", f"w13b{u}@example.com")
print("registro+verify de A y B ok")

# Nueva regla: antes de abrir el MD hay que aceptar la solicitud de amistad.
st, b = http("POST", "/api/people/requests",
             {"username": B_user["username"]}, token=A)
assert st == 201, (st, b)
rid = json.loads(b)["id"]
st, b = http("POST", f"/api/people/requests/{rid}/accept", {}, token=B)
assert st == 200, (st, b)
st, b = http("POST", "/api/chats/dm", {"username": B_user["username"]}, token=A)
assert st in (200, 201), (st, b)
dm = json.loads(b)["chat"]["id"]
print(f"dm ok (chat {dm})")

# grupo A+B (B entra con POST /members para que quede un mensaje system)
# y grupo solo de A (para el 403 de reenvío)
st, b = http("POST", "/api/chats/group", {"title": f"Grp {u}", "members": []}, token=A)
assert st == 201, (st, b)
grp = json.loads(b)["chat"]["id"]
st, b = http("POST", f"/api/chats/{grp}/members",
             {"username": B_user["username"]}, token=A)
assert 200 <= st < 300, (st, b)
st, b = http("POST", "/api/chats/group", {"title": f"Priv {u}", "members": []}, token=A)
assert st == 201, (st, b)
priv = json.loads(b)["chat"]["id"]

# --------------------------------------------------- 1) fijar y silenciar
st, b = http("POST", f"/api/chats/{dm}/pin", {"pinned": True}, token=A)
chk("pin responde ok", st == 200 and json.loads(b).get("pinned") is True, (st, b))
st, b = http("POST", f"/api/chats/{dm}/mute", {"muted": True}, token=A)
chk("mute responde ok", st == 200 and json.loads(b).get("muted") is True, (st, b))

st, b = http("GET", "/api/chats", token=A)
chats = json.loads(b)["chats"]
by_id = {c["id"]: c for c in chats}
chk("pin/mute persisten en GET /chats (solo míos)",
    by_id[dm]["pinned"] and by_id[dm]["muted"] and not by_id[grp]["pinned"], (st, b))
chk("el chat fijado queda primero en la lista", chats[0]["id"] == dm,
    [c["id"] for c in chats])
st, b = http("GET", "/api/chats", token=B)
b_by = {c["id"]: c for c in json.loads(b)["chats"]}
chk("pin/mute no afectan al otro miembro",
    not b_by[dm]["pinned"] and not b_by[dm]["muted"], (st, b))

st, b = http("POST", f"/api/chats/{dm}/pin", {"pinned": False}, token=A)
chk("desfijar funciona", st == 200 and json.loads(b).get("pinned") is False, (st, b))

# ------------------------------------------------------- 2) buscar en el chat
st, _ = send_text(A, dm, "Traje manzana 100% natural")
st, _ = send_text(A, dm, "café con leche")
chk("semilla de mensajes ok", st == 201, st)

st, b = http("GET", f"/api/chats/{dm}/search?q=manzana", token=A)
res = json.loads(b)["messages"]
chk("busca por texto", len(res) == 1 and "manzana" in res[0]["body"], (st, res))
st, b = http("GET", f"/api/chats/{dm}/search?q=%25", token=A)   # % escapado
res = json.loads(b)["messages"]
chk("el comodín % se busca literal", len(res) == 1 and "100%" in res[0]["body"], (st, res))
st, b = http("GET", f"/api/chats/{dm}/search?q=zzzzno", token=A)
chk("sin resultados → lista vacía", json.loads(b)["messages"] == [], (st, b))
st, b = http("GET", f"/api/chats/{dm}/search?q=", token=A)
chk("query vacía → lista vacía", json.loads(b)["messages"] == [], (st, b))
st, b = http("GET", f"/api/chats/{dm}/search?q=cafe", token=B)
chk("el otro miembro también busca", len(json.loads(b)["messages"]) >= 1, (st, b))

# --------------------------------------------------- 3) onda de voz (peaks)
webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 48   # firma EBML + relleno
st, b = multipart_post("/api/media", A, "nota.webm", webm, "audio/webm")
assert st == 201, (st, b)
voice_id = json.loads(b)["id"]
st, b = http("POST", f"/api/chats/{dm}/messages",
             {"kind": "voice", "body": "", "media_id": voice_id,
              "peaks": "[5,50,100,20]", "dur": 7},
             token=A)
time.sleep(1.2)
vm = json.loads(b).get("message", {})
chk("peaks y dur se guardan y vuelven",
    st == 201 and vm.get("peaks") == [5, 50, 100, 20] and vm.get("dur") == 7,
    (st, b))
st, b = http("POST", f"/api/chats/{dm}/messages",
             {"kind": "voice", "body": "", "peaks": "[200]"}, token=A)
chk("peaks fuera de rango → 422", st == 422, (st, b))
st, b = http("POST", f"/api/chats/{dm}/messages",
             {"kind": "voice", "body": "", "dur": 0}, token=A)
chk("dur 0 → 422 (mínimo 1 s)", st == 422, (st, b))

# ------------------------------------------------------- 4) reenviar mensajes
# A sube una imagen al DM y la reenvía al grupo (media compartido)
png = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")
st, b = multipart_post("/api/media", A, "w13.png", png, "image/png")
assert st == 201, (st, b)
img_id = json.loads(b)["id"]
st, b = http("POST", f"/api/chats/{dm}/messages",
             {"kind": "image", "body": "para el grupo", "media_id": img_id},
             token=A)
time.sleep(1.2)
img_msg = json.loads(b)["message"]

st, b = http("POST", f"/api/chats/{dm}/messages/{img_msg['id']}/forward",
             {"target_chat_id": grp}, token=A)
time.sleep(1.2)
fw = json.loads(b).get("message", {})
chk("reenvío al grupo: es mío, marcado y con el mismo archivo",
    st == 201 and fw.get("forwarded") and fw["media"]["id"] == img_id
    and fw["sender"]["id"] == A_user["id"], (st, b))

st, b = http("GET", f"/api/chats/{grp}/search?q=para%20el%20grupo", token=B)
res = json.loads(b)["messages"]
chk("B ve el mensaje reenviado en el grupo (con media)",
    len(res) == 1 and res[0]["forwarded"] and res[0]["media"], (st, b))

# el reenvío también conserva la onda y la duración de la nota de voz
st, b = http("POST", f"/api/chats/{dm}/messages/{vm['id']}/forward",
             {"target_chat_id": grp}, token=A)
time.sleep(1.2)
fwv = json.loads(b).get("message", {})
chk("el reenvío conserva onda y duración",
    st == 201 and fwv.get("peaks") == [5, 50, 100, 20] and fwv.get("dur") == 7,
    (st, b))

# reenviar mensaje del sistema → 400
st, b = http("GET", f"/api/chats/{grp}/messages", token=A)
sysm = [m for m in json.loads(b)["messages"] if m["kind"] == "system"]
st, b = http("POST", f"/api/chats/{grp}/messages/{sysm[0]['id']}/forward",
             {"target_chat_id": dm}, token=A)
chk("reenviar un system → 400", st == 400, (st, b))

# reenviar a un chat del que no soy miembro → 403
st, b = http("POST", f"/api/chats/{dm}/messages/{img_msg['id']}/forward",
             {"target_chat_id": priv}, token=B)
chk("reenviar a chat ajeno → 403", st == 403, (st, b))

# reenviar al mismo chat → 400
st, b = http("POST", f"/api/chats/{dm}/messages/{img_msg['id']}/forward",
             {"target_chat_id": dm}, token=A)
chk("reenviar al mismo chat → 400", st == 400, (st, b))

# mensaje inexistente → 404
st, b = http("POST", f"/api/chats/{dm}/messages/999999/forward",
             {"target_chat_id": grp}, token=A)
chk("reenviar mensaje inexistente → 404", st == 404, (st, b))

print(f"\nw13 smoke: {_ok} ok, {_fail} fallas")
sys.exit(1 if _fail else 0)
