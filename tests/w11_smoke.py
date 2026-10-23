#!/usr/bin/env python3
"""Smoke W11: rate limit de mensajes + URLs de media firmadas (slug + HMAC).

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


def raw_get(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
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


# ------------------------------------------------------------- usuarios
u = str(int(time.time()))
A_user, A = signup(f"w11a{u}", f"w11a{u}@example.com")
B_user, B = signup(f"w11b{u}", f"w11b{u}@example.com")
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
chat = json.loads(b)["chat"]
print(f"dm ok (chat {chat['id']})")

# ------------------------------------------------- 1) rate limit mensajes
cids = []
statuses = []
for i in range(8):
    cid = str(uuid.uuid4())
    cids.append(cid)
    st, _ = http("POST", f"/api/chats/{chat['id']}/messages",
                 {"kind": "text", "body": f"m{i}", "client_msg_id": cid}, token=A)
    statuses.append(st)
print(f"  statuses 8 envíos: {statuses}")
chk("ráfaga: los 5 primeros mensajes salen 201", all(s == 201 for s in statuses[:5]), statuses)
chk("tras la ráfaga llega 429", any(s == 429 for s in statuses[5:]), statuses)

# el 429 trae retry_after numérico
st, b = None, b""
for i in range(8):
    st, b = http("POST", f"/api/chats/{chat['id']}/messages",
                 {"kind": "text", "body": "spam", "client_msg_id": str(uuid.uuid4())}, token=A)
    if st == 429:
        break
d = json.loads(b).get("detail", {})
chk("429 con retry_after numérico (>=1)", st == 429 and isinstance(d.get("retry_after"), int)
    and d["retry_after"] >= 1, (st, b))

# idempotencia gana al rate limit: reenviar el mismo client_msg_id pasa siempre
st, b = http("POST", f"/api/chats/{chat['id']}/messages",
             {"kind": "text", "body": "m0-retry", "client_msg_id": cids[0]}, token=A)
msg0 = json.loads(b).get("message", {})
chk("reintento idempotente pasa sin 429", st == 201 and msg0.get("body") == "m0", (st, b))

# el bucket recargado vuelve a dejar pasar (~2 s)
time.sleep(2.2)
st, _ = http("POST", f"/api/chats/{chat['id']}/messages",
             {"kind": "text", "body": "tras-espera", "client_msg_id": str(uuid.uuid4())}, token=A)
chk("después de esperar vuelve a pasar", st == 201, st)

# B tiene su propio cubo (el límite es por usuario)
st, _ = http("POST", f"/api/chats/{chat['id']}/messages",
             {"kind": "text", "body": "de-b", "client_msg_id": str(uuid.uuid4())}, token=B)
chk("el límite es por usuario (B pasa)", st == 201, st)

# -------------------------------------------------- 2) media firmada
st, b = multipart_post("/api/media", A, "hola.txt", b"hola w11", "text/plain")
assert st == 201, (st, b)
media = json.loads(b)
chk("upload url es /media/file/{slug}.{ext} firmada",
    media["url"].startswith("/media/file/") and "exp=" in media["url"] and "sig=" in media["url"],
    media["url"])

path_only = media["url"].split("?")[0]
st, body = raw_get(BASE + media["url"])
chk("GET firmado → 200 y contenido correcto", st == 200 and body == b"hola w11", (st, body))
st, _ = raw_get(BASE + path_only)
chk("GET sin firma → 403", st == 403, st)

tampered = re.sub(r"sig=([0-9a-f])", lambda m: ("sig=0" if m.group(1) != "0" else "sig=1"), BASE + media["url"])
st, _ = raw_get(tampered)
chk("sig alterada → 403", st == 403, st)

wrong_exp = re.sub(r"exp=\d+", "exp=1", BASE + media["url"])  # exp vencido
st, _ = raw_get(wrong_exp)
chk("exp vencido → 403", st == 403, st)

with_tok = BASE + path_only + "?token=" + A
st, _ = raw_get(with_tok)
chk("token de cuenta ya no abre /media/* (403)", st == 403, st)

st, body = raw_get(f"{BASE}/api/media/{media['id']}?token={A}")
chk("compat: /api/media/{id}?token= sigue funcionando", st == 200 and body == b"hola w11", (st, body))

# -------------------------------------------------- 3) mensaje con archivo
time.sleep(2.2)  # dejar que el cubo de A recargue un token
st, b = multipart_post("/api/media", A, "clip.bin", b"\x00\x01\x02video", "application/octet-stream")
assert st == 201, (st, b)
file_media = json.loads(b)
st, b = http("POST", f"/api/chats/{chat['id']}/messages",
             {"kind": "file", "media_id": file_media["id"], "client_msg_id": str(uuid.uuid4())}, token=A)
assert st == 201, (st, b)
murl = json.loads(b)["message"]["media"]["url"]
chk("mensaje con archivo trae url firmada /media/file/",
    murl.startswith("/media/file/") and "sig=" in murl, murl)
st, _ = raw_get(BASE + murl)
chk("esa url firmada descarga 200", st == 200, st)

# -------------------------------------------------- 4) avatar firmado
# el avatar exige una imagen: PNG 1x1 válido (base64 canónico)
import base64
png1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
st, b = multipart_post("/api/media", A, "px.png", png1, "image/png")
assert st == 201, (st, b)
img_media = json.loads(b)
chk("imagen subida se recodifica a webp", img_media["mime"] == "image/webp", img_media["mime"])
st, b = http("PUT", "/api/auth/profile", {"avatar_media_id": img_media["id"]}, token=A)
assert st == 200, (st, b)
st, b = http("GET", "/api/users/me", token=A)
me = json.loads(b)
av = me.get("avatar_url") or me.get("user", {}).get("avatar_url")
chk("avatar_url es /media/profile/ firmada",
    av and av.startswith("/media/profile/") and ".webp?" in av and "sig=" in av, av)
st, _ = raw_get(BASE + av)
chk("avatar firmado descarga 200", st == 200, st)

print(f"\n{'OK' if _fail == 0 else 'FALLÓ'}: {_ok} ok, {_fail} fail")
sys.exit(1 if _fail else 0)
