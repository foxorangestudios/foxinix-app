#!/usr/bin/env python
"""E2E W37: cifrado en edición/citas, players, menciones globales,
título/seen con pestaña oculta y fixes de la auditoría de seguridad.

Siembra A, B y C: DM A↔B, DM B↔C y grupo A+B. Firefox headless (BiDi
vía scripts/shot.py) con la sesión de A.

  API:
  1. edición E2E: A cifra→edita (blob nuevo); B-WS recibe el evento con
     el blob y B descifra el texto editado. Mezclar claro/cifrado → 400.
  2. IDOR reply_to: citar un mensaje de un chat ajeno → 400.
  3. IDOR /api/media: dueño 200; ajeno 404; miembro del chat 200.
  4. IDOR favoritos de GIFs: media sin enviar → 404; tras enviarse → 201.
  5. unreact con message_id de OTRO chat → 404.
  6. forward de un mensaje E2E → 400 (la clave es por par de usuarios).
  7. health ya no publica nº de usuarios ni cuota.
  8. subida de HTML/JS → 415 (XSS almacenado).
  9. CREATIONS activo: el 7º chat seguido → 429.
 10. menciones globales: @todos/@everyone → todos los miembros;
     @activos sin conexión → 0; @online con B en WS → sólo B.
 11. llamadas: A→B relaya; el EMISOR no miembro (C) NO relaya.

  UI (sesión de A):
 12. título con contador sólo con la pestaña OCULTA.
 13. visto confirmado (read) aunque la pestaña esté oculta al abrir.
 14. buscador como MODAL con autofocus.
 15. menús contextuales con iconos (lista y mensaje).
 16. players: velocidad de la nota de voz (1×→1,5×), descarga del
     audio adjunto, popup de volumen del video (la hora se desvanece,
     el slider mueve volume) y botón de descarga del video.
 17. video con MIME roto → bloque de error con i-alert.
 18. mención "@everyone" mostrada localizada ("@todos" en es,
     "@everyone" en en).
 19. E2E en la UI: A envía, responde (cita con texto descifrado) y
     edita; B descifra el texto editado re-cifrado por el server.
"""

import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import queue
import re
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from websockets.sync.client import connect as wsconnect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")

_pass = [0]
_fail = [0]


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  ✓ {name}")
    else:
        _fail[0] += 1
        print(f"  ✗ {name}: {detail}")


def shot(url, out, js=None, wait=400, timeout=240):
    """Como ct.run_shot, pero con el JSRES bien descodificado."""
    cmd = [str(ct.PY), str(ct.SHOT), url, str(out), "--wait", str(wait)]
    if js:
        cmd += ["--js", js]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    res = None
    for line in r.stdout.splitlines():
        if line.startswith("JSRES: "):
            try:
                v = json.loads(line[7:].strip())
                res = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            except Exception:
                res = line[7:].strip()
    ok = r.returncode == 0 and "SHOT:" in r.stdout
    return ok, res, (r.stdout + r.stderr)


def sess_js(u):
    sess = json.dumps({"access": u["access"], "refresh": u["refresh"],
                       "user": u["user"], "pendingEmail": ""})
    return ct.JS_INJECT.replace(
        "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))


W_WAIT = """const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (sel, ms = 12000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(80);
    }
    return null;
  };
  const boot = async () => {
    let tb = Date.now();
    while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  };
  const findChat = (txt) => Array.from(document.querySelectorAll('.chat-item'))
    .find(function (el) { return el.textContent.indexOf(txt) >= 0; });"""


def js(tpl, **kw):
    out = W_WAIT + "\n" + tpl
    # VOLBLOCK primero: su texto trae sus propios placeholders («REAL»)
    if "VOLBLOCK" in kw:
        out = out.replace("«VOLBLOCK»", kw.pop("VOLBLOCK"))
    for k, v in kw.items():
        out = out.replace("«" + k + "»", v)
    return out


def http_status(method, url, token=None):
    """Descarga de archivo: sólo interesa el status (el body es binario).
    El endpoint legacy recibe el token por ?query (QML no manda headers)."""
    if token:
        url = url + ("&" if "?" in url else "?") + "token=" + token
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read(64)
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def send_ok(base, tok, chat_id, payload):
    """ct.send sin acumular puntos de SPAM: el bucket de mensajes admite
    ~3/5 s; cada 429 suma un punto y a los 4 te bloquea 5 min — los
    tests espacian los envíos en vez de pelear con el rate limit."""
    time.sleep(1.2)
    return ct.send(base, tok, chat_id, payload)


# PNG 1×1 rojo (para el paso de favoritos de GIFs: sólo acepta imágenes)
PNG1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082")


# ------------------------------------------- W29f: lado "B" del E2E (API)

def e2e_keypair():
    """Par ECDH P-256; devuelve (privada, pública base64 de 65 B)."""
    priv = ec.generate_private_key(ec.SECP256R1())
    raw = priv.public_key().public_bytes(Encoding.X962,
                                         PublicFormat.UncompressedPoint)
    return priv, base64.b64encode(raw).decode()


def e2e_derive(priv, peer_pub_b64, uid_me, uid_you):
    """HKDF-SHA256 manual idéntico al del cliente (e2e.js)."""
    peer = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), base64.b64decode(peer_pub_b64))
    ikm = priv.exchange(ec.ECDH(), peer)
    lo, hi = sorted((uid_me, uid_you))
    info = f"foxinix-e2e-v1|{lo}|{hi}".encode()
    prk = hmac.new(b"foxinix-e2e-v1-salt", ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:32]


def e2e_dec(key, blob):
    raw_iv = base64.b64decode(blob["iv"])
    raw_ct = base64.b64decode(blob["ct"])
    return AESGCM(key).decrypt(raw_iv, raw_ct, None).decode()


def e2e_enc(key, text):
    nonce = os.urandom(12)
    ct_blob = AESGCM(key).encrypt(nonce, text.encode(), None)
    return {"iv": base64.b64encode(nonce).decode(),
            "ct": base64.b64encode(ct_blob).decode()}


# ------------------------------------------------- WS en background

class WSq(threading.Thread):
    """WS simple en background: cola de eventos + cola de salida."""

    def __init__(self, base, token):
        super().__init__(daemon=True)
        self.url = base.replace("http://", "ws://") + "/api/ws?token=" + token
        self.q = queue.Queue()
        self.out = queue.Queue()
        self.ready = threading.Event()
        self._stop = False

    def run(self):
        try:
            with wsconnect(self.url, open_timeout=10, close_timeout=5) as w:
                self.ready.set()
                while not self._stop:
                    try:
                        while True:
                            w.send(self.out.get_nowait())
                    except queue.Empty:
                        pass
                    try:
                        raw = w.recv(timeout=0.2)
                    except TimeoutError:
                        continue
                    except Exception:
                        break
                    try:
                        self.q.put(json.loads(raw))
                    except Exception:
                        pass
        except Exception:
            self.ready.set()

    def send(self, obj):
        self.out.put(json.dumps(obj))

    def close(self):
        self._stop = True

    def wait_type(self, t, timeout=8):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if ev.get("type") == t:
                return ev
        return None

    def count(self, t):
        """Drena y cuenta eventos de un tipo (para 'no llegó nada')."""
        n = 0
        while True:
            try:
                ev = self.q.get_nowait()
            except queue.Empty:
                break
            if ev.get("type") == t:
                n += 1
        return n


# ------------------------------------------------------------- media

def make_wav(path, secs=1.0, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(secs * rate)):
            v = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))


def make_mp4(path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=3",
         "-pix_fmt", "yuv420p", str(path)],
        capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and path.is_file()


# ------------------------------------------------------------- UI

JS_TITLE = """(async () => {
  await boot();
  /* pestaña forzada a OCULTA: el título debe llevar "(n)" */
  Object.defineProperty(document, 'hidden', { configurable: true,
    get: function () { return true; } });
  document.dispatchEvent(new Event('visibilitychange'));
  await sleep(200);
  const r = await fetch('/api/chats/«DM»/messages', { method: 'POST',
    headers: { 'Content-Type': 'application/json',
               'Authorization': 'Bearer «BT»' },
    body: JSON.stringify({ kind: 'text', body: 'oculto w37',
                           client_msg_id: 'w37-«UID»' }) });
  const t0 = Date.now();
  let c = null;
  while (Date.now() - t0 < 9000) {
    c = (__fm.store.chats || []).find(function (x) { return x.id === «DM»; });
    if (c && c.unread) break;
    await sleep(150);
  }
  const hiddenTitle = document.title;
  /* pestaña forzada a VISIBLE: el título queda limpio */
  Object.defineProperty(document, 'hidden', { configurable: true,
    get: function () { return false; } });
  document.dispatchEvent(new Event('visibilitychange'));
  await sleep(250);
  return JSON.stringify({ st: r.status, unread: c ? c.unread : 0,
                          hiddenTitle: hiddenTitle,
                          visTitle: document.title });
})()"""

JS_SEEN = """(async () => {
  await boot();
  Object.defineProperty(document, 'hidden', { configurable: true,
    get: function () { return true; } });
  document.dispatchEvent(new Event('visibilitychange'));
  await sleep(150);
  const dm = findChat('«BU»');
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  if (!await wait('.msgs .msg', 12000)) return 'FAIL: no abrió la DM';
  await sleep(800);
  return 'abierto';
})()"""

JS_SEARCH = """(async () => {
  await boot();
  const dm = findChat('«BU»');
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  if (!await wait('.msgs .msg', 12000)) return 'FAIL: no abrió la DM';
  const btn = await wait('.chat-head button[title="Buscar en el chat"]', 6000);
  if (!btn) return 'FAIL: sin botón de búsqueda';
  btn.click();
  const modal = await wait('.search-modal', 4000);
  if (!modal) return 'FAIL: no abrió el buscador';
  await sleep(300);
  const ae = document.activeElement;
  return JSON.stringify({ modal: true,
                          focus: !!(ae && modal.contains(ae)),
                          tag: ae ? ae.tagName : '' });
})()"""

JS_CTX = """(async () => {
  await boot();
  const it = document.querySelector('.chat-item');
  if (!it) return 'FAIL: sin chats en la lista';
  it.dispatchEvent(new MouseEvent('contextmenu',
    { bubbles: true, cancelable: true, clientX: 60, clientY: 120 }));
  const menu = await wait('.ctx-menu', 4000);
  if (!menu) return 'FAIL: sin menú de la lista';
  const listIc = Array.prototype.slice
    .call(menu.querySelectorAll('.ctx-ic use'))
    .map(function (u) { return u.getAttribute('href') || ''; });
  document.body.click();
  await sleep(250);
  const dm = findChat('«BU»');
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  const more = await wait('.msg .b-more', 10000);
  if (!more) return 'FAIL: sin ⋯ de mensaje';
  more.click();
  const mm = await wait('.ctx-menu', 4000);
  if (!mm) return 'FAIL: sin menú del mensaje';
  const msgIc = Array.prototype.slice
    .call(mm.querySelectorAll('.ctx-item'))
    .map(function (b) {
      const u = b.querySelector('.ctx-ic use');
      return b.textContent.trim() + '|' + (u ? u.getAttribute('href') : '');
    });
  return JSON.stringify({ list: listIc, msg: msgIc });
})()"""

JS_PLAYERS = """(async () => {
  await boot();
  const out = {};
  const dm = findChat('«BU»');
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  if (!await wait('.msgs .msg', 12000)) return 'FAIL: no abrió la DM';
  /* --- velocidad de la nota de voz (1× → 1,5×) */
  const rate = await wait('.b-player .au-rate[title="Velocidad"]', 8000);
  if (!rate) return 'FAIL: sin botón de velocidad de voz';
  out.rate0 = rate.textContent.trim();
  rate.click();
  await sleep(200);
  out.rate1 = rate.textContent.trim();
  /* --- audio adjunto: botón de descarga (W37d) */
  const af = await wait('.b-afile', 8000);
  out.afDl = !!(af && af.querySelector('.au-rate[title="Descargar"]'));
  /* --- video con MIME roto → bloque de error (W37d) */
  let verr = document.querySelector('.msg[data-mid="«FAKE»"] .v-err');
  if (!verr) {
    const vid = document.querySelector('.msg[data-mid="«FAKE»"] .b-vid');
    if (vid) vid.dispatchEvent(new Event('error'));
    verr = await wait('.msg[data-mid="«FAKE»"] .v-err', 5000);
  }
  if (verr) {
    const use = verr.querySelector('use');
    out.vErrIcon = use ? (use.getAttribute('href') || '') : '';
    out.vErrTxt = verr.textContent.trim();
  } else {
    out.vErrIcon = '';
    out.vErrTxt = '';
  }
  /* --- video válido: popup de volumen (sólo si hay ffmpeg) */
  «VOLBLOCK»
  return JSON.stringify(out);
})()"""

VOLBLOCK = """  const vwrap = document.querySelector('.msg[data-mid="«REAL»"] .b-video');
  if (vwrap) {
    vwrap.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    await sleep(250);
    out.vBar = !!vwrap.querySelector('.v-bar');
    out.vDl = !!vwrap.querySelector('.v-bar .v-btn[title="Descargar"]');
    const volBtn = vwrap.querySelector('.v-bar .v-btn[title="Volumen"]');
    out.volBtn = !!volBtn;
    if (volBtn) {
      volBtn.click();
      await sleep(450);
      out.volOpen = !!vwrap.querySelector('.v-vol');
      out.slider = !!vwrap.querySelector('.v-vol .v-slider');
      out.timeGone = !vwrap.querySelector('.v-time');
      const sl = vwrap.querySelector('.v-slider');
      if (sl) {
        sl.value = '0.4';
        sl.dispatchEvent(new Event('input', { bubbles: true }));
        await sleep(150);
        const v = vwrap.querySelector('.b-vid');
        out.volume = v ? v.volume : null;
      }
    }
  }"""

JS_MENTION = """(async () => {
  await boot();
  const gi = findChat('«GT»');
  if (!gi) return 'FAIL: sin grupo';
  gi.click();
  if (!await wait('.msgs .msg', 12000)) return 'FAIL: no abrió el grupo';
  /* bodySegs sólo localiza con los miembros del chat cargados */
  __fm.store.info = { chatId: «GRP», members: [
    { id: «AID», username: '«AU»' },
    { id: «BID», username: '«BU»' } ] };
  const el = await wait('.msg[data-mid="«MIDM»"] .mention', 6000);
  if (!el) return 'FAIL: sin mención resaltada';
  const es = el.textContent.trim();
  __fm.store.lang = 'en';
  await sleep(400);
  const el2 = document.querySelector('.msg[data-mid="«MIDM»"] .mention');
  const en = el2 ? el2.textContent.trim() : '';
  __fm.store.lang = 'es';
  return JSON.stringify({ es: es, en: en });
})()"""

JS_E2E = """(async () => {
  await boot();
  const dm = findChat('«BU»');
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  if (!await wait('.msgs .msg', 12000)) return 'FAIL: no abrió la DM';
  /* esperar la auto-activación del cifrado (B ya publicó su clave) */
  const t0 = Date.now();
  while (Date.now() - t0 < 12000 && !__fm.store.e2e[«DM»]) await sleep(150);
  if (!__fm.store.e2e[«DM»]) return 'FAIL: el cifrado no se activó';
  /* enviar un mensaje cifrado */
  const inp = document.querySelector('.composer-input');
  if (!inp) return 'FAIL: sin compositor';
  inp.value = 'cifrado w37 ui';
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(150);
  const send = document.querySelector('.send-btn');
  if (!send || send.disabled) return 'FAIL: sin botón de enviar';
  send.click();
  let row = null;
  const t1 = Date.now();
  while (Date.now() - t1 < 10000) {
    const rows = Array.from(document.querySelectorAll('.msgs .msg'));
    for (let i = rows.length - 1; i >= 0; i--) {
      if (rows[i].textContent.indexOf('cifrado w37 ui') >= 0) { row = rows[i]; break; }
    }
    if (row) break;
    await sleep(200);
  }
  if (!row) return 'FAIL: no apareció el mensaje cifrado';
  const midUI = row.getAttribute('data-mid');
  /* responder: la cita debe mostrar el TEXTO DESCIFRADO (W37) */
  const more = row.querySelector('.b-more');
  if (!more) return 'FAIL: sin ⋯ del mensaje';
  more.click();
  const mi = await wait('.ctx-menu', 4000);
  if (!mi) return 'FAIL: sin menú del mensaje';
  const rep = Array.prototype.slice.call(mi.querySelectorAll('.ctx-item'))
    .find(function (b) { return b.textContent.trim() === 'Responder'; });
  if (!rep) return 'FAIL: sin opción Responder';
  rep.click();
  const rb = await wait('.reply-bar', 4000);
  if (!rb) return 'FAIL: sin barra de respuesta';
  const prev = rb.querySelector('.rb-col span');
  const replyPrev = prev ? prev.textContent.trim() : '';
  const xb = rb.querySelector('.icon-btn');
  if (xb) xb.click();
  await sleep(200);
  /* editar: el server debe recibir SÓLO el blob nuevo (W37a) */
  more.click();
  const mi2 = await wait('.ctx-menu', 4000);
  if (!mi2) return 'FAIL: sin menú para editar';
  const ed = Array.prototype.slice.call(mi2.querySelectorAll('.ctx-item'))
    .find(function (b) { return b.textContent.trim() === 'Editar'; });
  if (!ed) return 'FAIL: sin opción Editar';
  ed.click();
  const ta = await wait('.b-editform textarea.input', 4000);
  if (!ta) return 'FAIL: sin formulario de edición';
  ta.value = 'editado w37 ui';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(150);
  const save = document.querySelector('.b-editform .bef-btns .btn-sm:last-child');
  if (!save || save.disabled) return 'FAIL: sin botón Guardar';
  save.click();
  const t2 = Date.now();
  let edited = false;
  while (Date.now() - t2 < 8000) {
    const r2 = document.querySelector('.msg[data-mid="' + midUI + '"]');
    if (r2 && r2.textContent.indexOf('editado w37 ui') >= 0) { edited = true; break; }
    await sleep(200);
  }
  return JSON.stringify({ mid: midUI, replyPrev: replyPrev, edited: edited });
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    GT = f"W37-Grupo-{tag}"
    A = ct.register(a.base, f"w37a{tag}@t.fi", f"w37a{tag}")
    B = ct.register(a.base, f"w37b{tag}@t.fi", f"w37b{tag}")
    C = ct.register(a.base, f"w37c{tag}@t.fi", f"w37c{tag}")
    AU, BU = A["user"]["username"], B["user"]["username"]
    AID, BID = A["user"]["id"], B["user"]["id"]
    print(f"· A={AU} B={BU} C={C['user']['username']}")

    st, r = ct.http("POST", a.base + "/api/chats/dm", {"username": BU},
                    token=A["access"])
    assert st in (200, 201), (st, r)
    dm = r["chat"]["id"]
    st, r = ct.http("POST", a.base + "/api/chats/dm",
                    {"username": C["user"]["username"]}, token=B["access"])
    assert st in (200, 201), (st, r)
    dm_bc = r["chat"]["id"]
    st, r = ct.http("POST", a.base + "/api/chats/group",
                    {"title": GT, "members": [BU]}, token=A["access"])
    assert st == 201, (st, r)
    grp = r["chat"]["id"]
    print(f"· dm={dm} dmBC={dm_bc} grp={grp}")

    # claves E2E (A y B publican; el shared secret es simétrico)
    b_priv, b_pub = e2e_keypair()
    st, r = ct.http("PUT", a.base + "/api/users/me/e2e-key",
                    {"public_key": b_pub}, token=B["access"])
    assert st == 200, (st, r)
    a_priv, a_pub = e2e_keypair()
    st, r = ct.http("PUT", a.base + "/api/users/me/e2e-key",
                    {"public_key": a_pub}, token=A["access"])
    assert st == 200, (st, r)
    shared = e2e_derive(a_priv, b_pub, AID, BID)

    # ============ 1. edición E2E ===================================
    print("→ paso1 edición E2E (server re-cifra; B descifra)")
    bws = WSq(a.base, B["access"])
    bws.start()
    bws.ready.wait(8)
    blob1 = e2e_enc(shared, "secreto original w37")
    msg1 = send_ok(a.base, A["access"], dm,
                   {"kind": "text", "body": "", "e2e": blob1,
                    "client_msg_id": f"w37{tag}-1"})
    mid = msg1["id"]
    step("A envía un mensaje E2E (server sólo ve el marcador)",
         bool(mid) and msg1["body"].startswith("[")
         and bool(msg1.get("e2e")), msg1)
    blob2 = e2e_enc(shared, "secreto editado w37")
    st, r = ct.http("PUT", f"{a.base}/api/chats/{dm}/messages/{mid}",
                    {"body": "", "e2e": blob2}, token=A["access"])
    step("la edición E2E re-cifra (200 con blob nuevo)",
         st == 200 and r["message"]["e2e"]["ct"] != blob1["ct"], f"{st} {r}")
    ev = bws.wait_type("message_edited", 8)
    step("el evento WS message_edited lleva el blob",
         bool(ev) and ev.get("e2e") and ev["e2e"]["ct"] == blob2["ct"],
         f"ev={ev}")
    st, g = ct.http("GET", f"{a.base}/api/chats/{dm}/messages?limit=50",
                    token=B["access"])
    m1 = next((x for x in g.get("messages", []) if x["id"] == mid), None)
    plain = ""
    try:
        plain = e2e_dec(shared, m1["e2e"]) if m1 and m1.get("e2e") else ""
    except Exception:
        pass
    step("B descifra el TEXTO EDITADO (no el original)",
         plain == "secreto editado w37", plain)
    st, r = ct.http("PUT", f"{a.base}/api/chats/{dm}/messages/{mid}",
                    {"body": "en claro"}, token=A["access"])
    step("mezclar cifrado→claro da 400", st == 400, st)
    msg2 = send_ok(a.base, A["access"], dm,
                   {"kind": "text", "body": "hola claro",
                    "client_msg_id": f"w37{tag}-2"})
    m2 = msg2["id"]
    st, r = ct.http("PUT", f"{a.base}/api/chats/{dm}/messages/{m2}",
                    {"e2e": blob2}, token=A["access"])
    step("mezclar claro→cifrado da 400", st == 400, st)
    st, r = ct.http("PUT", f"{a.base}/api/chats/{dm}/messages/{m2}",
                    {"body": "hola claro 2"}, token=A["access"])
    step("la edición en claro sigue funcionando (200)", st == 200, st)
    bws.close()
    time.sleep(0.8)

    # ============ 2. IDOR reply_to ================================
    print("→ paso2 IDOR reply_to")
    mbc = send_ok(a.base, B["access"], dm_bc,
                  {"kind": "text", "body": "para b",
                   "client_msg_id": f"w37{tag}-3"})
    mid_bc = mbc["id"]
    time.sleep(1.2)
    st, r = ct.http("POST", f"{a.base}/api/chats/{dm}/messages",
                    {"kind": "text", "body": "reply raro", "reply_to": mid_bc,
                     "client_msg_id": f"w37{tag}-4"}, token=A["access"])
    step("citar un mensaje de un chat ajeno → 400", st == 400, st)
    msg3 = send_ok(a.base, A["access"], dm,
                   {"kind": "text", "body": "reply bueno", "reply_to": mid,
                    "client_msg_id": f"w37{tag}-5"})
    step("citar un mensaje del mismo chat → 201 (regresión)",
         bool(msg3.get("id")), msg3)

    # ============ 3. IDOR /api/media ==============================
    print("→ paso3 IDOR /api/media")
    ftxt = SHOTS / "w37-nota.txt"
    ftxt.write_text("hola w37")
    up = ct.upload(a.base, A["access"], ftxt)
    st = http_status("GET", f"{a.base}/api/media/{up['id']}", A["access"])
    step("el dueño descarga su archivo (200)", st == 200, st)
    st = http_status("GET", f"{a.base}/api/media/{up['id']}", B["access"])
    step("un ajeno recibe 404 (sin membresía)", st == 404, st)
    mf1 = send_ok(a.base, A["access"], dm,
                  {"kind": "file", "body": "", "media_id": up["id"],
                   "client_msg_id": f"w37{tag}-6"})
    step("el archivo viaja en el DM (201)", bool(mf1.get("id")), mf1)
    st = http_status("GET", f"{a.base}/api/media/{up['id']}", B["access"])
    step("el miembro del chat sí lo descarga (200)", st == 200, st)
    st = http_status("GET", f"{a.base}/api/media/{up['id']}", C["access"])
    step("un tercero sigue con 404", st == 404, st)

    # ============ 4. IDOR favoritos de GIFs =======================
    print("→ paso4 IDOR favoritos de GIFs")
    fpng = SHOTS / "w37-fav.png"
    fpng.write_bytes(PNG1)
    upf = ct.upload(a.base, A["access"], fpng)
    st, r = ct.http("POST", a.base + "/api/gifs/favorites",
                    {"media_id": upf["id"]}, token=B["access"])
    step("favorito con media ajena sin enviar → 404", st == 404, st)
    mimg = send_ok(a.base, A["access"], dm,
                   {"kind": "image", "body": "", "media_id": upf["id"],
                    "client_msg_id": f"w37{tag}-7"})
    step("el gif viaja en el DM (201)", bool(mimg.get("id")), mimg)
    st, r = ct.http("POST", a.base + "/api/gifs/favorites",
                    {"media_id": upf["id"]}, token=B["access"])
    step("tras viajar en el chat compartido → 201 (regresión)",
         st == 201, f"{st} {r}")
    ct.http("DELETE", a.base + "/api/gifs/favorites",
            {"media_id": upf["id"]}, token=B["access"])

    # ============ 5. unreact cross-chat ===========================
    print("→ paso5 unreact con message_id de otro chat")
    st, r = ct.http("POST", f"{a.base}/api/chats/{dm}/reactions/{mid}",
                    {"emoji": "👍"}, token=A["access"])
    step("reaccionar al mensaje propio (200)", st == 200, st)
    st, r = ct.http("DELETE",
                    f"{a.base}/api/chats/{grp}/reactions/{mid}",
                    token=A["access"])
    step("borrar reacción con message_id de OTRO chat → 404",
         st == 404, st)
    st, r = ct.http("DELETE", f"{a.base}/api/chats/{dm}/reactions/{mid}",
                    token=A["access"])
    step("borrar la reacción en SU chat → 200 (regresión)",
         st == 200, st)

    # ============ 6. forward de un mensaje E2E ====================
    print("→ paso6 forward E2E")
    st, r = ct.http("POST",
                    f"{a.base}/api/chats/{dm}/messages/{mid}/forward",
                    {"target_chat_id": grp}, token=A["access"])
    step("reenviar un mensaje E2E → 400 (la clave es por par)",
         st == 400, f"{st} {r}")

    # ============ 7. health sin fugas =============================
    print("→ paso7 /api/health sin nº de usuarios")
    st, h = ct.http("GET", a.base + "/api/health")
    step("health responde ok/version", st == 200 and h.get("ok") is True
         and bool(h.get("version")), h)
    step("health ya no publica users ni media_quota_bytes",
         "users" not in h and "media_quota_bytes" not in h, list(h.keys()))

    # ============ 8. subida de HTML/JS → 415 ======================
    print("→ paso8 subida de contenidos activos")
    fhtml = SHOTS / "w37-x.html"
    fhtml.write_text("<html><script>x</script></html>")
    raw, ctype = ct.multipart_field(fhtml)
    st, r = ct.http("POST", a.base + "/api/media", token=A["access"],
                    raw=raw, ctype=ctype)
    step("subir text/html → 415", st == 415, f"{st} {r}")
    fjs = SHOTS / "w37-x.js"
    fjs.write_text("var x = 1;")
    raw, ctype = ct.multipart_field(fjs)
    st, r = ct.http("POST", a.base + "/api/media", token=A["access"],
                    raw=raw, ctype=ctype)
    step("subir text/javascript → 415", st == 415, f"{st} {r}")

    # ============ 9. CREATIONS rate limit =========================
    print("→ paso9 CREATIONS (crear chats ~1/min)")
    D = ct.register(a.base, f"w37d{tag}@t.fi", f"w37d{tag}")
    c429 = None
    n_ok = 0
    for i in range(8):
        st, r = ct.http("POST", a.base + "/api/chats/group",
                        {"title": f"W37g{tag}-{i}", "members": []},
                        token=D["access"])
        if st == 429:
            c429 = r
            break
        if st == 201:
            n_ok += 1
    retry = (c429 or {}).get("detail", {}).get("retry_after", 0) \
        if isinstance((c429 or {}).get("detail"), dict) else 0
    step("el 7º chat seguido pega 429 con retry_after",
         c429 is not None and retry >= 30 and n_ok == 6,
         f"ok={n_ok} 429={c429}")

    # ============ 10. menciones globales ==========================
    print("→ paso10 menciones @todos/@everyone/@activos/@online")
    mt = send_ok(a.base, A["access"], grp,
                 {"kind": "text", "body": f"@todos hola {tag}",
                  "client_msg_id": str(uuid.uuid4())})
    ids_t = set(mt.get("mentions") or [])
    step("@todos menciona a TODOS los miembros",
         AID in ids_t and BID in ids_t, ids_t)
    me = send_ok(a.base, A["access"], grp,
                 {"kind": "text", "body": f"@everyone hola {tag}",
                  "client_msg_id": str(uuid.uuid4())})
    step("@everyone (forma EN) también menciona a todos",
         BID in set(me.get("mentions") or []), me.get("mentions"))
    ac = send_ok(a.base, A["access"], grp,
                 {"kind": "text", "body": f"@activos nadie conectado {tag}",
                  "client_msg_id": str(uuid.uuid4())})
    step("@activos sin conexiones no menciona a nadie",
         (ac.get("mentions") or []) == [], ac.get("mentions"))
    wb = WSq(a.base, B["access"])
    wb.start()
    wb.ready.wait(8)
    time.sleep(0.5)
    on = send_ok(a.base, A["access"], grp,
                 {"kind": "text", "body": f"@online solo conectados {tag}",
                  "client_msg_id": str(uuid.uuid4())})
    ids_on = set(on.get("mentions") or [])
    step("@online con B conectado menciona SÓLO a los conectados",
         ids_on == {BID}, ids_on)
    wb.close()
    time.sleep(0.8)

    # ============ 11. llamadas: emisor no miembro =================
    print("→ paso11 señalización de llamadas (sólo miembros)")
    wa = WSq(a.base, A["access"])
    wb2 = WSq(a.base, B["access"])
    wc = WSq(a.base, C["access"])
    for w in (wa, wb2, wc):
        w.start()
        w.ready.wait(8)
    time.sleep(0.5)
    wa.send({"type": "call_offer", "chat_id": dm, "sdp": "v=0",
             "video": False})
    evb = wb2.wait_type("call_offer", 8)
    step("B recibe la oferta de llamada de A (relé OK)",
         bool(evb) and evb.get("sdp") == "v=0", f"ev={evb}")
    wa.count("call_offer")
    wb2.count("call_offer")
    wc.send({"type": "call_offer", "chat_id": dm, "sdp": "v=0",
             "video": False})
    time.sleep(2)
    step("el EMISOR no miembro (C) NO relaya la señalización",
         wa.count("call_offer") == 0 and wb2.count("call_offer") == 0,
         "llegó oferta relayada")
    for w in (wa, wb2, wc):
        w.close()
    time.sleep(0.5)

    # ============ seeds para la fase UI ===========================
    print("→ sembrando media para la fase UI")
    voz = SHOTS / "w37-voz.wav"
    make_wav(voz)
    upv = ct.upload(a.base, B["access"], voz)
    send_ok(a.base, B["access"], dm,
            {"kind": "voice", "body": "", "media_id": upv["id"],
             "client_msg_id": str(uuid.uuid4())})
    fake = SHOTS / "w37-fake.mp4"
    fake.write_bytes(b"esto no es un video de verdad")
    upf2 = ct.upload(a.base, B["access"], fake)
    mf = send_ok(a.base, B["access"], dm,
                 {"kind": "file", "body": "", "media_id": upf2["id"],
                  "client_msg_id": str(uuid.uuid4())})
    real_id = None
    real = SHOTS / "w37-real.mp4"
    mp4ok = make_mp4(real)
    if mp4ok:
        upr = ct.upload(a.base, B["access"], real)
        mr = send_ok(a.base, B["access"], dm,
                     {"kind": "file", "body": "", "media_id": upr["id"],
                      "client_msg_id": str(uuid.uuid4())})
        real_id = mr["id"]
    else:
        print("  · sin ffmpeg: se omite el paso de volumen del video")
    ogg = SHOTS / "w37-audio.ogg"
    ogg.write_bytes(b"basura de audio ogg")
    upo = ct.upload(a.base, B["access"], ogg)
    send_ok(a.base, B["access"], dm,
            {"kind": "file", "body": "", "media_id": upo["id"],
             "client_msg_id": str(uuid.uuid4())})
    m_men = send_ok(a.base, B["access"], grp,
                    {"kind": "text", "body": f"@everyone prueba w37 {tag}",
                     "client_msg_id": str(uuid.uuid4())})

    # ============ sesión de A en el navegador =====================
    ok, res, log = shot(a.base + "/", SHOTS / "w37-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    # ============ 12. título sólo con pestaña oculta ==============
    print("→ paso12 título del documento")
    ok, res, log = shot(a.base + "/", SHOTS / "w37-1-titulo.png",
                        js=js(JS_TITLE, DM=str(dm), BT=B["access"],
                              UID=tag))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("con la pestaña OCULTA el título lleva el contador",
         ok and (r.get("unread") or 0) >= 1
         and re.match(r"^\(\d+\) Foxinix$", r.get("hiddenTitle") or ""),
         f"res={res!r}")
    step("con la pestaña VISIBLE el título queda limpio",
         ok and r.get("visTitle") == "Foxinix", f"res={res!r}")

    # ============ 13. visto confirmado con pestaña oculta =========
    print("→ paso13 visto (read) con pestaña oculta")
    bws2 = WSq(a.base, B["access"])
    bws2.start()
    bws2.ready.wait(8)
    ok, res, log = shot(a.base + "/", SHOTS / "w37-2-seen.png",
                        js=js(JS_SEEN, BU=BU))
    ev = bws2.wait_type("read", 10)
    step("abrir el chat confirma el visto aunque la pestaña esté oculta",
         ok and res == "abierto" and bool(ev)
         and ev.get("chat_id") == dm and ev.get("user_id") == AID,
         f"res={res!r} ev={ev}")
    bws2.close()
    time.sleep(0.5)

    # ============ 14. buscador como modal =========================
    print("→ paso14 buscador de mensajes como modal")
    ok, res, log = shot(a.base + "/", SHOTS / "w37-3-buscar.png",
                        js=js(JS_SEARCH, BU=BU))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("el buscador abre un MODAL con el cursor listo",
         ok and r.get("modal") is True and r.get("focus") is True,
         f"res={res!r}")

    # ============ 15. menús contextuales con iconos ===============
    print("→ paso15 menús con iconos")
    ok, res, log = shot(a.base + "/", SHOTS / "w37-4-menus.png",
                        js=js(JS_CTX, BU=BU))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    lst = r.get("list") or []
    step("el menú de la lista lleva iconos (#i-…)",
         ok and len(lst) >= 3 and all(x.startswith("#i-") for x in lst),
         f"res={res!r}")
    msg = r.get("msg") or []
    step("el menú del mensaje lleva iconos (Responder|i-reply)",
         "Responder|#i-reply" in msg, f"res={res!r}")

    # ============ 16/17. players ================================
    print("→ paso16/17 players (voz/audio/video)")
    vol = VOLBLOCK if (mp4ok and real_id) else ""
    ok, res, log = shot(a.base + "/", SHOTS / "w37-5-players.png",
                        js=js(JS_PLAYERS, BU=BU, FAKE=str(mf["id"]),
                              REAL=str(real_id or 0), VOLBLOCK=vol))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("velocidad de la nota de voz: 1× → 1,5×",
         ok and r.get("rate0", "").replace("×", "").strip() == "1"
         and "1.5" in (r.get("rate1") or ""),
         f"res={res!r}")
    step("el audio adjunto tiene botón de descarga (afDl)",
         ok and r.get("afDl") is True, f"res={res!r}")
    if vol:
        step("el video válido tiene barra y botón de descarga",
             ok and r.get("vBar") is True and r.get("vDl") is True,
             f"res={res!r}")
        step("el popup de volumen abre con su slider",
             ok and r.get("volBtn") is True and r.get("volOpen") is True
             and r.get("slider") is True, f"res={res!r}")
        step("al abrir el volumen la HORA se desvanece",
             ok and r.get("timeGone") is True, f"res={res!r}")
        vol_val = r.get("volume")
        step("el slider mueve el volume del video (~0.4)",
             ok and vol_val is not None and 0.35 <= vol_val <= 0.45,
             f"res={res!r}")
    step("el video con MIME roto muestra el aviso de error",
         ok and (r.get("vErrTxt") or "").find("Este video tiene un error") >= 0
         and r.get("vErrIcon") == "#i-alert", f"res={res!r}")

    # ============ 18. mención localizada ==========================
    print("→ paso18 mención @everyone localizada")
    ok, res, log = shot(a.base + "/", SHOTS / "w37-6-mencion.png",
                        js=js(JS_MENTION, GT=GT, GRP=str(grp), AID=str(AID),
                              BID=str(BID), AU=AU, BU=BU,
                              MIDM=str(m_men["id"])))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("en español la mención EN se muestra como @todos",
         ok and r.get("es") == "@todos", f"res={res!r}")
    step("en inglés la misma mención se muestra como @everyone",
         ok and r.get("en") == "@everyone", f"res={res!r}")

    # ============ 19. E2E en la UI (enviar/responder/editar) ======
    print("→ paso19 E2E en la UI: enviar, citar y editar")
    ok, res, log = shot(a.base + "/", SHOTS / "w37-7-e2e.png",
                        js=js(JS_E2E, BU=BU, DM=str(dm)))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    mid_ui = r.get("mid")
    step("A envía un mensaje cifrado y la burbuja muestra el texto",
         ok and bool(mid_ui), f"res={res!r}")
    step("la cita en el compositor muestra el TEXTO DESCIFRADO",
         r.get("replyPrev") == "cifrado w37 ui", f"res={res!r}")
    step("la edición en la UI actualiza la burbuja",
         r.get("edited") is True, f"res={res!r}")
    # verificación fuerte: B descifra lo que el server guardó
    st, keyr = ct.http("GET", f"{a.base}/api/users/{AU}/e2e-key",
                       token=B["access"])
    plain_ui = ""
    m_ui = None
    if st == 200 and keyr.get("public_key") and mid_ui:
        shared2 = e2e_derive(b_priv, keyr["public_key"], BID, AID)
        st, g = ct.http("GET", f"{a.base}/api/chats/{dm}/messages?limit=50",
                        token=B["access"])
        m_ui = next((x for x in g.get("messages", [])
                     if x["id"] == int(mid_ui)), None)
        try:
            plain_ui = e2e_dec(shared2, m_ui["e2e"]) if m_ui else ""
        except Exception:
            pass
    step("el server guardó SÓLO el blob (marcador, nunca el texto)",
         bool(m_ui) and m_ui["body"].startswith("[")
         and bool(m_ui.get("e2e")), f"m={m_ui}")
    step("B descifra el TEXTO EDITADO re-cifrado por el server",
         plain_ui == "editado w37 ui", plain_ui)

    # ============ limpieza ========================================
    if ct.cleanup_db():
        print("· limpieza ok")
    else:
        print("· WARN: limpieza incompleta")

    print(f"\nW37: {_pass[0]} pasos OK, {_fail[0]} fallos")
    sys.exit(1 if _fail[0] else 0)


if __name__ == "__main__":
    main()
