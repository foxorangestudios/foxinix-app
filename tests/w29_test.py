#!/usr/bin/env python
"""E2E W29a: bugs críticos + UX rápida.

Siembra A y B (DM) y maneja Firefox headless (BiDi):

  1. el caption de una imagen NO se duplica en la misma burbuja (bug
     reportado con captura: el texto salía dos veces)
  2. un archivo vacío (0 bytes) NO se envía: toast "El archivo está
     vacío" y no se crea la burbuja
  3. un audio adjunto (.mp3) renderiza controles <audio> en la burbuja
     (no la fila de descarga ni un <video> negro)
  4. un access token vencido/corrupto se recupera con el refresh y la
     app sigue en /app sin re-login (falso "Sesión expirada")
  5. el título del documento muestra "(1) Foxinix" con no leídos y
     vuelve a "Foxinix" al abrir el chat
  6. una solicitud de amistad recibida aparece como globo rojo en el
     botón "Personas" (tope 9+)
  7. un mensaje que llega por WS lleva la clase .anim (animación de
     entrada) y la suelta al terminar

Emojis Twemoji + panel estilo Discord (W29b; W40: el paso8 usa el
estilo "Emojis de Google" (Noto) elegido en el desplegable de
Ajustes — el default ahora es "Nativo del sistema"):

  8. el panel tiene buscador arriba, categorías a la izquierda y UNA
     sola lista con subtítulos; la rejilla usa <img> del estilo
     activo; ":fire:" se envía y la burbuja muestra el emoji; el chip
     de reacción también

W29d/e/f (spoilers, hora 12/24 y E2E):

 12. spoiler: long-press de 3 s en Enviar (texto) o botón "Mensaje
     Spoiler: On/Off" (SOLO con adjunto) → capa que cubre el contenido
     (la hora y las palomitas quedan visibles) con "[ojo] Mostrar
     Spoiler" → tocar revela → "[ojo] Ocultar" vuelve a tapar → al
     salir y volver reaparece; también en imagen y en la galería
 13. "Formato de hora" como desplegable: 24 h por defecto, 12 h con
     am/pm y vuelta a 24 h
 14. E2E: B publica su clave P-256, A activa el switch (SAS), envía
     cifrado; el server guarda SÓLO "[Mensaje cifrado]" + blob, B lo
     descifra en Python y su respuesta cifrada se ve descifrada en A
     (preview del sidebar con el marcador)

Uso: server/.venv/bin/python tests/w29_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")

_pass = [0]
_fail = [0]

# PNG rojo de 1x1 para simular archivos (paste)
PNG1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
        "hQGAhKmMIQAAAABJRU5ErkJggg==")


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  \u2713 {name}")
    else:
        _fail[0] += 1
        print(f"  \u2717 {name}: {detail}")


def shot(url, out, js=None, wait=400, timeout=150):
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


# --------- W29f: el lado "B" de la conversación E2E (espejo de e2e.js)
def e2e_keypair():
    """Par ECDH P-256; devuelve (privada, pública base64 de 65 B)."""
    priv = ec.generate_private_key(ec.SECP256R1())
    raw = priv.public_key().public_bytes(Encoding.X962,
                                         PublicFormat.UncompressedPoint)
    return priv, base64.b64encode(raw).decode()


def e2e_derive(priv, peer_pub_b64, uid_me, uid_you):
    """HKDF-SHA256 manual idéntico al del cliente:
       PRK = HMAC(salt, ikm); T1 = HMAC(PRK, info || 0x01) → 32 B."""
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


W_WAIT = """const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (sel, ms = 12000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(80);
    }
    return null;
  };"""

JS_OPEN = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  const msgs = await wait('.msgs .msg', 8000);
  if (!msgs) return 'FAIL: no abrió el chat';
  return 'OK chat abierto';
})()"""

# 1. imagen + caption: el texto debe aparecer UNA sola vez en la burbuja
JS_CAPTION = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  const ta = await wait('.composer-input', 8000);
  if (!ta) return 'FAIL: sin compositor';
  const bin = atob('""" + PNG1 + """');
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  const f = new File([arr], 'cap.png', { type: 'image/png' });
  const ev = new Event('paste', { bubbles: true, cancelable: true });
  ev.clipboardData = { items: [{ kind: 'file', getAsFile: function () { return f; } }] };
  document.dispatchEvent(ev);
  const strip = await wait('.cap-strip', 6000);
  if (!strip) return 'FAIL: el paste no abrió la tira de adjunto';
  ta.focus();
  ta.value = 'caption sin duplicar';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(200);
  ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  const frame = await wait('.msgs .b-media', 10000);
  if (!frame) return 'FAIL: no apareció la imagen';
  await sleep(2500);                 // deja terminar la subida
  const rows = document.querySelectorAll('.msgs .msg');
  const m = rows[rows.length - 1];
  const btexts = m.querySelectorAll('.b-text');
  const s = __fm.store;
  const last = s.msgs[s.activeChatId][s.msgs[s.activeChatId].length - 1];
  const parts = [];
  for (let i = 0; i < btexts.length; i++) parts.push(btexts[i].outerHTML.slice(0, 260));
  return JSON.stringify({
    n: btexts.length,
    body: last.body || '',
    parts: parts,
  });
})()"""

# 2. archivo vacío: toast + sin burbuja nueva
JS_EMPTY = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  const ta = await wait('.composer-input', 8000);
  /* W36fix: esperar a que los mensajes pinten antes de contar el
     "before" (antes se medía en caliente y salía 0 aunque la carga
     terminara medio segundo después) */
  await wait('.msgs .msg', 8000);
  const before = document.querySelectorAll('.msgs .msg').length;
  const f = new File([], 'vacio.txt', { type: 'text/plain' });
  const ev = new Event('paste', { bubbles: true, cancelable: true });
  ev.clipboardData = { items: [{ kind: 'file', getAsFile: function () { return f; } }] };
  document.dispatchEvent(ev);
  await sleep(600);
  const after = document.querySelectorAll('.msgs .msg').length;
  const toasts = document.querySelectorAll('.toast');
  let txt = '';
  for (let i = 0; i < toasts.length; i++) txt += toasts[i].textContent + ' | ';
  return JSON.stringify({ before: before, after: after, toast: txt });
})()"""

# 3. audio .mp3 → reproductor <audio> en la burbuja
JS_AUDIO = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  const ta = await wait('.composer-input', 8000);
  const bytes = new Uint8Array(64);
  for (let i = 0; i < 64; i++) bytes[i] = i;
  const f = new File([bytes], 'nota.mp3', { type: 'audio/mpeg' });
  const ev = new Event('paste', { bubbles: true, cancelable: true });
  ev.clipboardData = { items: [{ kind: 'file', getAsFile: function () { return f; } }] };
  document.dispatchEvent(ev);
  const el = await wait('.msgs .b-afile audio', 12000);
  if (!el) {
    const vf = document.querySelector('.msgs .b-video');
    const bf = document.querySelector('.msgs .b-file');
    return 'FAIL: sin <audio> (video=' + !!vf + ' filadescarga=' + !!bf + ')';
  }
  const s = __fm.store;
  const last = s.msgs[s.activeChatId][s.msgs[s.activeChatId].length - 1];
  return JSON.stringify({ mime: (last.media && last.media.mime) || '' });
})()"""

# 4. access vencido → refresh recuperа la sesión (sin ir a /login)
JS_CORRUPT = """(() => {
  const raw = JSON.parse(localStorage.getItem('fm.session') || 'null');
  if (!raw) return 'FAIL: sin sesión en localStorage';
  raw.access = 'expirado.basura.' + Date.now();
  localStorage.setItem('fm.session', JSON.stringify(raw));
  return 'ok';
})()"""

JS_REFRESH = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 15000 && __fm.store.booting) await sleep(120);
  await sleep(1500);
  return JSON.stringify({
    hasSession: !!__fm.store.hasSession,
    route: __fm.store.route,
    path: location.pathname,
    chats: (__fm.store.chats || []).length,
  });
})()"""

# 5. título del documento con el contador de no leídos
JS_AWAY = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const ppl = await wait('.side-people', 8000);
  if (!ppl) return 'FAIL: sin botón Personas';
  ppl.click();
  await sleep(400);
  return 'OK fuera del chat; título=' + document.title;
})()"""

JS_TITLE = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  await wait('.chat-list .chat-item', 8000);
  await sleep(600);                 // deja cargar chats y el título
  /* W37: el contador (N) sólo se muestra con la pestaña OCULTA */
  Object.defineProperty(document, 'hidden', { configurable: true,
    get: function () { return true; } });
  document.dispatchEvent(new Event('visibilitychange'));
  await sleep(250);
  const t1 = document.title;
  Object.defineProperty(document, 'hidden', { configurable: true,
    get: function () { return false; } });
  document.dispatchEvent(new Event('visibilitychange'));
  await sleep(250);
  const tvis = document.title;
  const it = document.querySelector('.chat-list .chat-item');
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  await sleep(800);
  return JSON.stringify({ with: t1, vis: tvis, after: document.title });
})()"""

# 6. globo de solicitudes en "Personas"
JS_BADGE = """(async () => {
  """ + W_WAIT + """
  const b = await wait('.side-badge', 10000);
  if (!b) return 'FAIL: sin globo en Personas';
  return 'badge=' + b.textContent.trim();
})()"""

# 7. animación de entrada del mensaje en vivo (B envía DURANTE la shot)
JS_ANIM = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  await wait('.msgs .msg', 8000);
  let found = false;
  const tb2 = Date.now();
  while (Date.now() - tb2 < 7000) {
    if (document.querySelector('.msgs .msg.anim')) { found = true; break; }
    await sleep(30);
  }
  if (!found) return 'FAIL: el mensaje nuevo no pasó por .anim';
  await sleep(700);
  const still = !!document.querySelector('.msgs .msg.anim');
  return JSON.stringify({ found: found, still: still });
})()"""


# 8. panel estilo Discord + Twemoji en burbuja y chip (W29b)
JS_PANEL = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  await wait('.msgs .msg', 8000);
  /* W40: este paso revisa el estilo "Emojis de Google" (Noto) — se
     cambia en Ajustes (reactivo, sin recargar) antes del panel. */
  const gear = document.querySelector('[title="Ajustes"]');
  if (!gear) return 'FAIL: sin Ajustes';
  gear.click();
  if (!(await wait('.m-tab', 4000))) return 'FAIL: sin pestañas de Ajustes';
  const tabs = document.querySelectorAll('.m-tab');
  for (let i = 0; i < tabs.length; i++) {
    if (tabs[i].textContent.trim() === 'Chat') { tabs[i].click(); break; }
  }
  await sleep(250);
  const emoSel = await wait('.emo-select', 4000);
  if (!emoSel) return 'FAIL: sin desplegable de estilo de emojis';
  emoSel.value = 'noto';
  emoSel.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(250);
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  await sleep(300);
  const emoBtn = await wait('.comp-emo', 6000);
  if (!emoBtn) return 'FAIL: sin botón de emojis';
  emoBtn.click();
  const p = await wait('.emo-picker', 5000);
  if (!p) return 'FAIL: no abrió el panel';
  await sleep(300);
  if (!p.querySelector('.ep-search input')) return 'FAIL: sin buscador arriba';
  const cats = p.querySelectorAll('.ep-cats .ep-cat');
  if (cats.length < 5) return 'FAIL: categorías izquierda=' + cats.length;
  const subs = p.querySelectorAll('.ep-sub');
  if (subs.length < 3) return 'FAIL: subtítulos=' + subs.length;
  const first = p.querySelector('.ep-scroll .ep-e img.emo');
  /* W40: con estilo Noto la rejilla usa los PNG de Google */
  if (!first || (first.getAttribute('src') || '')
      .indexOf('/static/emoji-noto/') !== 0) {
    return 'FAIL: la rejilla no usa imgs Noto (Google)';
  }
  /* elegir un emoji del panel + escribir :fire: y enviar */
  p.querySelector('.ep-scroll .ep-e').click();
  await sleep(200);
  const ta = document.querySelector('.composer-input');
  ta.value = (ta.value || '') + ' hola :fire:';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(200);
  document.querySelector('.comp-row .send-btn').click();
  const t1 = Date.now();
  let okFire = null;
  while (Date.now() - t1 < 8000) {
    const rows = document.querySelectorAll('.msgs .msg');
    const last = rows[rows.length - 1];
    const im = last && last.querySelector('.b-text img.emo[src*="1f525"]');
    if (im) { okFire = im; break; }
    await sleep(120);
  }
  if (!okFire) return 'FAIL: el :fire: no salió como Twemoji en la burbuja';
  /* doble clic = reacción rápida → chip con img Twemoji */
  const rows2 = document.querySelectorAll('.msgs .msg');
  const mine = rows2[rows2.length - 1];
  /* W39: el doble clic reacciona sobre el id del server; si se lanza
     con el id temporal del pendiente (ack aún no llegado) el endpoint
     da error y el chip nunca aparece (flake). Se espera a que el
     reloj de "enviado" desaparezca. */
  const tP = Date.now();
  while (Date.now() - tP < 5000 && mine.querySelector('.tick.t-pend'))
    await sleep(100);
  mine.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
  const t2 = Date.now();
  let okChip = false;
  while (Date.now() - t2 < 5000) {
    if (mine.querySelector('.react-chip img.emo')) { okChip = true; break; }
    await sleep(100);
  }
  if (!okChip) return 'FAIL: el chip de reacción no trae Twemoji';
  return JSON.stringify({ cats: cats.length, subs: subs.length,
                          sub0: subs[0].textContent.trim() });
})()"""


# 9. "escribiendo…" con nombre + pelotita en la lista (W29c)
JS_TYPING = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  await wait('.msgs .msg', 8000);
  const t0 = Date.now();
  let got = null;
  while (Date.now() - t0 < 14000) {
    const txt = document.querySelector('.msgs .msg.typ-row .typ-txt');
    if (txt && txt.textContent.indexOf('escribiendo') >= 0) {
      got = txt.textContent.trim(); break;
    }
    await sleep(120);
  }
  if (!got) return 'FAIL: sin fila de escribiendo';
  const dot = document.querySelector('.chat-list .chat-item .ci-typing i');
  if (!dot) return 'FAIL: sin pelotita en la lista (label=' + got + ')';
  return JSON.stringify({ label: got, dot: true });
})()"""

# 10. "Info del usuario" (DM) + menús sin desbordes (W29c)
JS_INFO = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista';
  it.click();
  await wait('.msgs .msg', 8000);
  /* 1) en DM el botón y la cabecera dicen "Info del usuario".
     (En pantallas anchas el panel viene YA ABIERTO — store.infoOpen
     default por ancho — así que se tolera ambos estados.) */
  const btnInfo = document.querySelector('.chat-head .icon-btn[title="Info del usuario"]') ||
    document.querySelector('.chat-head .icon-btn[title="Ocultar info del chat"]');
  if (!btnInfo) return 'FAIL: sin botón de info';
  if (!document.querySelector('.profile-panel')) btnInfo.click();
  const pp = await wait('.profile-panel', 5000);
  if (!pp) return 'FAIL: no abrió el panel de info';
  await sleep(250);
  const head = (pp.querySelector('.pp-head b') || {}).textContent || '';
  if (head.trim() !== 'Info del usuario') return 'FAIL: cabecera=' + head.trim();
  /* 2) menú ⋯ del panel: dentro de la ventana */
  pp.querySelector('.pp-more').click();
  const ctx = await wait('.ctx-menu', 4000);
  if (!ctx) return 'FAIL: no abrió el menú del panel';
  await sleep(200);
  const r1 = ctx.getBoundingClientRect();
  const ok1 = r1.left >= 0 && r1.top >= 0 &&
    r1.right <= window.innerWidth - 2 && r1.bottom <= window.innerHeight - 2;
  document.querySelector('.msgs').click();
  await sleep(250);
  /* 3) menú del mensaje lanzado cerca de la esquina: clamp */
  const target = document.querySelector('.msgs .msg:not(.system)');
  if (!target) return 'FAIL: sin mensaje';
  const br = target.querySelector('.bubble').getBoundingClientRect();
  target.dispatchEvent(new MouseEvent('contextmenu',
    { bubbles: true, cancelable: true,
      clientX: Math.min(br.left + 8, window.innerWidth - 4),
      clientY: Math.min(br.bottom + 400, window.innerHeight - 4) }));
  const ctx2 = await wait('.ctx-menu', 4000);
  if (!ctx2) return 'FAIL: no abrió el menú del mensaje';
  await sleep(200);
  const r2 = ctx2.getBoundingClientRect();
  const ok2 = r2.left >= 0 && r2.top >= 0 &&
    r2.right <= window.innerWidth - 2 && r2.bottom <= window.innerHeight - 2;
  return JSON.stringify({ head: head.trim(), panelMenu: ok1, msgMenu: ok2,
    diag: { r: [r2.left | 0, r2.top | 0, r2.right | 0, r2.bottom | 0],
      offH: ctx2.offsetHeight, offW: ctx2.offsetWidth,
      pos: getComputedStyle(ctx2).position,
      sctx: [__fm.store.ctx ? __fm.store.ctx.x | 0 : -1,
             __fm.store.ctx ? __fm.store.ctx.y | 0 : -1,
             __fm.store.ctx && __fm.store.ctx.items
               ? __fm.store.ctx.items.length : -1],
      vh: window.innerHeight, vw: window.innerWidth } });
})()"""

# 11. grupo: avatares + ✓✓ azul "todos leyeron" + tooltip de reacción (W29c)
JS_GROUP = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const title = '«GTITLE»';
  const items = document.querySelectorAll('.chat-list .chat-item');
  let target = null;
  for (let i = 0; i < items.length; i++) {
    if (items[i].textContent.indexOf(title) >= 0) { target = items[i]; break; }
  }
  if (!target) return 'FAIL: sin el grupo en la lista';
  target.click();
  await wait('.msgs .msg', 8000);
  await sleep(400);
  /* A envía un mensaje al grupo */
  const ta = document.querySelector('.composer-input');
  ta.value = 'palomitas de grupo';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(250);
  document.querySelector('.comp-row .send-btn').click();
  /* 1) cara del emisor (foto/letra) en el primero de la tanda */
  const t0 = Date.now();
  let av = false;
  while (Date.now() - t0 < 15000) {
    if (document.querySelector('.msgs .msg:not(.mine) .msg-av.is-av')) { av = true; break; }
    await sleep(150);
  }
  if (!av) return 'FAIL: sin avatar en mensajes del grupo';
  /* 2) chip de reacción con tooltip "emoji nombre" */
  let tip = null;
  const t1 = Date.now();
  while (Date.now() - t1 < 15000) {
    const chip = document.querySelector('.msgs .msg.mine .react-chip');
    if (chip) { tip = chip.getAttribute('title') || ''; break; }
    await sleep(150);
  }
  if (!tip) return 'FAIL: sin chip de reacción (avatar ok)';
  /* 3) palomita azul: B leyó el chat (POST /read con su seq) */
  let read = false;
  const t2 = Date.now();
  while (Date.now() - t2 < 13000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    const last = rows[rows.length - 1];
    const tick = last ? last.querySelector('.tick') : null;
    if (tick && tick.classList.contains('t-read')) { read = true; break; }
    await sleep(150);
  }
  /* 4) respuesta: nombre del emisor ARRIBA de la cita (DOM y píxel) */
  let rep = null;
  const t3 = Date.now();
  while (Date.now() - t3 < 15000) {
    const qs = document.querySelectorAll('.msgs .msg:not(.mine) .b-reply');
    if (qs.length) { rep = qs[qs.length - 1]; break; }
    await sleep(150);
  }
  if (!rep) return 'FAIL: sin respuesta citada (lo demás ok)';
  const box = rep.closest('.msg');
  const snd = box.querySelector('.b-sender');
  if (!snd) return 'FAIL: la respuesta no muestra el nombre del emisor';
  const domAbove = !!(snd.compareDocumentPosition(rep) &
    Node.DOCUMENT_POSITION_FOLLOWING);
  const rn = rep.querySelector('.br-name');
  const rt = rep.querySelector('.br-text');
  const nameAbove = !!(rn && rt && rn.offsetTop < rt.offsetTop);
  /* 5) columna: cara solo en el primero de la tanda; los demás, vacía */
  const avs = document.querySelectorAll('.msgs .msg:not(.mine) .msg-av');
  let withFace = 0;
  let spacer = 0;
  for (let i = 0; i < avs.length; i++) {
    if (avs[i].classList.contains('is-av')) withFace++;
    else spacer++;
  }
  return JSON.stringify({ avatar: av, tip: tip, read: read,
    domAbove: domAbove, nameAbove: nameAbove,
    withFace: withFace, spacer: spacer });
})()"""

# 12. spoilers (W29d/h): long-press 3 s en Enviar o botón con adjunto
#     → capa sobre el contenido (hora/palomitas visibles) → tocar
#     revela → "Ocultar" tapa → al salir y volver reaparece
JS_SPOIL = """(async () => {
  """ + W_WAIT + """
  const CID = '«DM»';
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const findItem = () => document.querySelector(
    '.chat-list .chat-item[data-chat-id="' + CID + '"]');
  const pickMsg = (txt) => {
    const rows = document.querySelectorAll('.msgs .msg');
    for (let i = 0; i < rows.length; i++) {
      if ((rows[i].textContent || '').indexOf(txt) >= 0) return rows[i];
    }
    return null;
  };
  const it = findItem();
  if (!it) return JSON.stringify({ stage: 'lista' });
  it.click();
  if (!(await wait('.msgs .msg', 8000)))
    return JSON.stringify({ stage: 'chat' });
  /* ---- a) texto con spoiler por long-press de 3 s (W29h) ---- */
  const noSp0 = !document.querySelector('.comp-spoil');  /* sólo con adjunto */
  const ta = document.querySelector('.composer-input');
  ta.value = 'texto spoiler w29';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(250);
  const sbtn = document.querySelector('.comp-row .send-btn');
  if (!sbtn) return JSON.stringify({ stage: 'sin-send' });
  sbtn.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  await sleep(80);
  const holdCls = sbtn.classList.contains('holding');   /* relleno 3 s */
  await sleep(3400);                                    /* hold + margen */
  let m = null;
  let t0 = Date.now();
  while (Date.now() - t0 < 12000) {
    m = pickMsg('texto spoiler w29');
    if (m && m.querySelector('.b-spoil-ov')) break;
    m = null;
    await sleep(150);
  }
  /* soltar = el click real de siempre (el flag holdFired lo salta;
     con botón ya disabled el .click() no dispara: se despacha a mano) */
  sbtn.dispatchEvent(new Event('pointerup', { bubbles: true }));
  sbtn.dispatchEvent(new Event('click', { bubbles: true }));
  if (!m) return JSON.stringify({ stage: 'sin-overlay', noSp0: noSp0 });
  const bub = m.querySelector('.bubble');
  const ov = m.querySelector('.b-spoil-ov');
  const rb = bub.getBoundingClientRect();
  const ro = ov.getBoundingClientRect();
  const covers = rb.height > 20 &&
    Math.abs(rb.height - ro.height) < 5 &&
    Math.abs(rb.width - ro.width) < 5;
  /* W29h: el texto/medios queda oculto, pero .b-meta (hora y
     palomitas) se VEN pintadas encima de la capa. */
  let hid = true, metaVis = false;
  const kids = bub.children;
  for (let i = 0; i < kids.length; i++) {
    if (kids[i] === ov) continue;
    if (kids[i].classList.contains('b-meta')) {
      metaVis = getComputedStyle(kids[i]).visibility === 'visible';
      continue;
    }
    if (getComputedStyle(kids[i]).visibility !== 'hidden') { hid = false; break; }
  }
  const ovTxtOk = (ov.textContent || '').indexOf('Mostrar Spoiler') >= 0;
  ov.click();                      /* tocar → se revela */
  await sleep(400);
  const afterShow = !m.querySelector('.b-spoil-ov');
  const dot = m.querySelector('.b-spoil-dot');
  const dotTxtOk = !!(dot && (dot.textContent || '').indexOf('Ocultar') >= 0);
  let afterHide = false;
  if (dot) {
    dot.click();                   /* ojo + "Ocultar" → vuelve a tapar */
    await sleep(400);
    afterHide = !!m.querySelector('.b-spoil-ov');
  }
  /* salir del chat y volver: se vuelve a tapar (W29d) */
  const back = document.querySelector('.chat-head button.back');
  if (back) back.click();
  await sleep(600);
  const it2 = findItem();
  if (it2) it2.click();
  if (!(await wait('.msgs .msg', 8000)))
    return JSON.stringify({ stage: 'reopen', on: on });
  let m2 = null;
  t0 = Date.now();
  while (Date.now() - t0 < 9000) {
    m2 = pickMsg('texto spoiler w29');
    if (m2) break;
    await sleep(150);
  }
  const afterReopen = !!(m2 && m2.querySelector('.b-spoil-ov'));
  /* ---- b) imagen con spoiler: el botón SÓLO aparece con adjunto ---- */
  const fi = document.querySelector('.comp-row input[type=file]');
  if (!fi) return JSON.stringify({ stage: 'sin-input-file' });
  const dt = new DataTransfer();
  dt.items.add(new File(
    [Uint8Array.from(atob('«PNG1»'), function (c) { return c.charCodeAt(0); })],
    'spoil.png', { type: 'image/png' }));
  fi.files = dt.files;
  fi.dispatchEvent(new Event('change', { bubbles: true }));
  const sb = await wait('.comp-row .send-btn:not([disabled])', 6000);
  if (!sb) return JSON.stringify({ stage: 'sin-adjunto' });
  const sp2 = await wait('.comp-spoil', 3000);  /* W29g: v-if="att" */
  if (!sp2) return JSON.stringify({ stage: 'sin-boton-adj' });
  const titleOff = sp2.getAttribute('title') || '';
  if (titleOff.indexOf('Mensaje Spoiler: Off') < 0) {
    return JSON.stringify({ stage: 'titulo-off', title: titleOff });
  }
  sp2.click();
  await sleep(250);
  const on2 = sp2.classList.contains('on') &&
    (sp2.getAttribute('title') || '').indexOf('Mensaje Spoiler: On') >= 0;
  sb.click();
  let mi = null;
  t0 = Date.now();
  while (Date.now() - t0 < 12000) {
    const rows = document.querySelectorAll('.msgs .msg');
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].querySelector('.b-media') &&
          rows[i].querySelector('.b-spoil-ov')) { mi = rows[i]; break; }
    }
    if (mi) break;
    await sleep(150);
  }
  const imgOv = !!mi;
  /* ---- c) galería: la miniatura tapada ---- */
  let panel = document.querySelector('aside.profile-panel');
  if (!panel) {
    const ib = document.querySelector(
      '.chat-head button[title="Info del usuario"]');
    if (ib) ib.click();
    panel = await wait('aside.profile-panel', 5000);
  }
  let galOv = false;
  if (panel) {
    const heads = document.querySelectorAll('.pp-pinhead');
    for (let i = 0; i < heads.length; i++) {
      if ((heads[i].textContent || '').indexOf('Archivos y medios') >= 0) {
        if (heads[i].getAttribute('aria-expanded') !== 'true') heads[i].click();
        break;
      }
    }
    const grid = await wait('.pp-galgrid', 6000);
    if (grid) {
      const t1 = Date.now();
      while (Date.now() - t1 < 6000) {
        if (document.querySelector('.pp-galgrid .gal-spoil')) { galOv = true; break; }
        await sleep(200);
      }
    }
  }
  return JSON.stringify({ stage: 'ok', noSp0: noSp0, holdCls: holdCls,
    covers: covers, hid: hid, metaVis: metaVis, ovTxtOk: ovTxtOk,
    dotTxtOk: dotTxtOk, afterShow: afterShow, afterHide: afterHide,
    afterReopen: afterReopen, on2: on2, imgOv: imgOv, galOv: galOv,
    panel: !!panel });
})()"""

# 13. "Formato de hora" como desplegable 12/24 h (W29e)
JS_H12 = """(async () => {
  """ + W_WAIT + """
  const CID = '«DM»';
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = document.querySelector(
    '.chat-list .chat-item[data-chat-id="' + CID + '"]');
  if (!it) return JSON.stringify({ stage: 'lista' });
  it.click();
  if (!(await wait('.msgs .msg', 8000)))
    return JSON.stringify({ stage: 'chat' });
  const timeEl = () => {
    const ts = document.querySelectorAll('.msgs .b-time');
    if (!ts.length) return '';
    return ts[ts.length - 1].textContent.trim();
  };
  await sleep(300);
  const t24 = timeEl();
  const gear = document.querySelector('[title="Ajustes"]');
  if (!gear) return JSON.stringify({ stage: 'sin-ajustes' });
  gear.click();
  if (!(await wait('.m-tab', 4000)))
    return JSON.stringify({ stage: 'sin-pestanas' });
  /* "Formato de hora" vive en la pestaña Chat (default: Apariencia) */
  const tabs = document.querySelectorAll('.m-tab');
  for (let i = 0; i < tabs.length; i++) {
    if (tabs[i].textContent.trim() === 'Chat') { tabs[i].click(); break; }
  }
  await sleep(300);
  const sel = await wait('select.h12-select', 6000);
  if (!sel) return JSON.stringify({ stage: 'sin-select' });
  const before = sel.value;
  sel.value = '12';
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(500);
  const t12 = timeEl();
  sel.value = '24';
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(400);
  const back24 = timeEl();
  return JSON.stringify({ stage: 'ok', t24: t24, t12: t12,
    back24: back24, before: before });
})()"""

# 14a. A activa el cifrado en el panel y envía un mensaje cifrado
JS_E2E1 = """(async () => {
  """ + W_WAIT + """
  const CID = '«DM»';
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = document.querySelector(
    '.chat-list .chat-item[data-chat-id="' + CID + '"]');
  if (!it) return JSON.stringify({ stage: 'lista' });
  it.click();
  if (!(await wait('.msgs .msg', 8000)))
    return JSON.stringify({ stage: 'chat' });
  let panel = document.querySelector('aside.profile-panel');
  if (!panel) {
    const ib = document.querySelector(
      '.chat-head button[title="Info del usuario"]');
    if (ib) ib.click();
    panel = await wait('aside.profile-panel', 5000);
  }
  if (!panel) return JSON.stringify({ stage: 'sin-panel' });
  const box = await wait('.pp-e2e', 4000);
  if (!box) return JSON.stringify({ stage: 'sin-e2e' });
  const cb = box.querySelector('input[type=checkbox]');
  /* W31c: el switch YA NO EXISTE (cifrado siempre activo). */
  if (cb) return JSON.stringify({ stage: 'quedo-switch' });
  /* W31c: el cifrado se AUTO-ACTIVA al abrir el DM (B ya publicó su
     clave). W39: el panel ya no dice "Activado" (solo queda la nota
     centrada de cifrado) — se mira el estado real del store. */
  let on = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 15000) {
    if (__fm.store.e2e && __fm.store.e2e[CID]) { on = true; break; }
    await sleep(200);
  }
  /* W39: el código YA NO está en el panel — vive en el menú ⋯ del
     chat de la lista y se muestra en un MODAL. */
  let sas = '';
  if (!sas) {
    const item0 = document.querySelector(
      '.chat-list .chat-item[data-chat-id="' + CID + '"]');
    if (item0) {
      item0.dispatchEvent(new MouseEvent('contextmenu',
        { bubbles: true, cancelable: true, clientX: 60, clientY: 120 }));
      const mi = await wait('.ctx-menu', 4000);
      if (mi) {
        const miIt = Array.prototype.slice
          .call(mi.querySelectorAll('.ctx-item'))
          .find(function (b) {
            return b.textContent.trim() === 'Ver código de verificación';
          });
        if (miIt) {
          /* W39: el menú abre un MODAL con el código (antes toast que
             se perdía); se lee y se cierra para no tapar el composer. */
          miIt.click();
          const sm = await wait('.sas-modal .sas-code', 4000);
          if (sm) sas = sm.textContent.trim();
          const xb = document.querySelector('.sas-modal header .icon-btn');
          if (xb) xb.click();
          await sleep(300);
        }
      }
    }
  }
  if (!on) return JSON.stringify({ stage: 'no-activa', sas: sas });
  /* mensaje propio: se ve DESCIFRADO en la burbuja… */
  const ta = document.querySelector('.composer-input');
  ta.value = 'secreto para ti w29';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(250);
  document.querySelector('.comp-row .send-btn').click();
  let sent = false;
  const t1 = Date.now();
  while (Date.now() - t1 < 12000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    for (let i = 0; i < rows.length; i++) {
      if ((rows[i].textContent || '').indexOf('secreto para ti w29') >= 0) {
        sent = true; break;
      }
    }
    if (sent) break;
    await sleep(150);
  }
  /* …pero el preview del sidebar muestra el marcador */
  const item = document.querySelector(
    '.chat-list .chat-item[data-chat-id="' + CID + '"]');
  const pv = item ? item.querySelector('.ci-prev') : null;
  return JSON.stringify({ stage: 'ok', on: on, noswitch: true, sas: sas,
    sent: sent,
    prev: pv ? pv.textContent : '' });
})()"""

# 14b. B (Python) manda un mensaje cifrado: A debe verlo descifrado
JS_E2E2 = """(async () => {
  """ + W_WAIT + """
  const CID = '«DM»';
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = document.querySelector(
    '.chat-list .chat-item[data-chat-id="' + CID + '"]');
  if (!it) return JSON.stringify({ stage: 'lista' });
  it.click();
  if (!(await wait('.msgs .msg', 8000)))
    return JSON.stringify({ stage: 'chat' });
  /* W30a: observa las burbujas — el marcador del server NUNCA debe
     aparecer en un mensaje (ni un frame): todo se descifra antes de
     insertar, con la clave de la caché local (IndexedDB). */
  let markerSeen = false;
  const mo = new MutationObserver(function (muts) {
    for (let i = 0; i < muts.length; i++) {
      const tgt = muts[i].target;
      const el = tgt.nodeType === 1 ? tgt : tgt.parentElement;
      if (el && el.closest && el.closest('.msgs') &&
          (el.textContent || '').indexOf('[Mensaje cifrado]') >= 0) {
        markerSeen = true;
      }
    }
  });
  mo.observe(document.body, {
    subtree: true, childList: true, characterData: true,
  });
  let found = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 30000) {
    const rows = document.querySelectorAll('.msgs .msg:not(.mine)');
    for (let i = 0; i < rows.length; i++) {
      if ((rows[i].textContent || '').indexOf('respuesta cifrada w29') >= 0) {
        found = true; break;
      }
    }
    if (found) break;
    await sleep(200);
  }
  const item = document.querySelector(
    '.chat-list .chat-item[data-chat-id="' + CID + '"]');
  const pv = item ? item.querySelector('.ci-prev') : null;
  mo.disconnect();
  return JSON.stringify({ stage: 'ok', found: found, marker: markerSeen,
    prev: pv ? pv.textContent : '' });
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w29a{tag}@t.fi", f"w29a{tag}")
    B = ct.register(a.base, f"w29b{tag}@t.fi", f"w29b{tag}")
    C = ct.register(a.base, f"w29c{tag}@t.fi", f"w29c{tag}")
    print(f"· usuarios A={A['user']['username']} B={B['user']['username']}")

    st, g = ct.dm_between(a.base, A["access"], B["access"],
                          A["user"]["username"], B["user"]["username"])
    if st not in (200, 201):
        raise SystemExit(f"✗ crear dm: {st} {g}")
    dm = g["chat"]["id"]

    # =================== sesión de A en el navegador ==================
    # Limpia una sesión vieja (usuario borrado por otra suite) antes de
    # inyectar, para evitar la carrera con el bootstrap.
    shot(a.base + "/", SHOTS / "w29-0-prep.png",
         js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
    ok, res, log = shot(a.base + "/", SHOTS / "w29-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    # =================== 1. caption sin duplicar ======================
    print("→ paso1 imagen + caption")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-1-caption.png", js=JS_CAPTION)
    n, body, parts = 0, "", []
    try:
        d = json.loads(res)
        n, body, parts = d["n"], d["body"], d["parts"]
    except Exception:
        pass
    step("caption sin duplicar", ok and n == 1 and body.count("caption sin duplicar") == 1,
         f"n={n} body={body!r} parts={parts!r} log={log[-200:]}")

    # =================== 2. archivo vacío =============================
    print("→ paso2 archivo vacío")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-2-vacio.png", js=JS_EMPTY)
    before, after, toast = -1, -1, ""
    try:
        d = json.loads(res)
        before, after, toast = d["before"], d["after"], d["toast"]
    except Exception:
        pass
    step("archivo vacío: toast y sin burbuja",
         ok and after == before and "El archivo est\u00e1 vac\u00edo" in toast,
         f"before={before} after={after} toast={toast!r} log={log[-200:]}")

    # =================== 3. audio con <audio> =========================
    print("→ paso3 audio .mp3")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-3-audio.png", js=JS_AUDIO)
    mime = ""
    try:
        mime = json.loads(res).get("mime", "")
    except Exception:
        pass
    step("audio .mp3 con reproductor <audio>",
         ok and (res or "").startswith("{") and "audio/mpeg" in mime,
         f"res={res!r} log={log[-200:]}")

    # =================== 4. refresh recupera la sesión ================
    print("→ paso4 access vencido + refresh")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-4a-corrupt.png", js=JS_CORRUPT)
    step("access corrupto escrito", ok and res == "ok", f"res={res!r} log={log[-200:]}")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-4b-refresh.png", js=JS_REFRESH)
    hs, route, path, chats = False, "", "", -1
    try:
        d = json.loads(res)
        hs, route, path, chats = d["hasSession"], d["route"], d["path"], d["chats"]
    except Exception:
        pass
    step("refresh recuperа la sesión sin re-login",
         ok and hs and route == "app" and "login" not in path and chats >= 1,
         f"res={res!r} log={log[-200:]}")

    # =================== 5. título con contador ========================
    print("→ paso5 título con no leídos")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-5a-away.png", js=JS_AWAY)
    step("A fuera del chat", ok and (res or "").startswith("OK"), f"res={res!r} log={log[-200:]}")
    ct.send(a.base, B["access"], dm, {"body": "hola titulo"})
    time.sleep(1.0)
    ok, res, log = shot(a.base + "/", SHOTS / "w29-5b-titulo.png", js=JS_TITLE)
    w1, aft = "", ""
    try:
        d = json.loads(res)
        w1, aft = d["with"], d["after"]
    except Exception:
        pass
    step("título '(1) Foxinix' con no leídos y 'Foxinix' al abrir",
         ok and w1 == "(1) Foxinix" and aft == "Foxinix",
         f"with={w1!r} after={aft!r} log={log[-200:]}")

    # =================== 6. globo de solicitudes =======================
    print("→ paso6 globo en Personas")
    st, _r = ct.http("POST", a.base + "/api/people/requests",
                     {"username": A["user"]["username"]}, token=C["access"])
    ok, res, log = shot(a.base + "/", SHOTS / "w29-6-badge.png", js=JS_BADGE)
    step("globo rojo con solicitudes recibidas",
         ok and (res or "") == "badge=1", f"res={res!r} http={st} log={log[-200:]}")

    # =================== 7. animación de entrada =======================
    print("→ paso7 animación de entrada")
    # La shot corre en un hilo y B envía MIENTRAS A mira el chat: el
    # mensaje tiene que llegar por WS para llevar la bandera .anim.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(shot, a.base + "/", SHOTS / "w29-7-anim.png",
                        JS_ANIM, 80)
        time.sleep(3.5)             # deja cargar la página y abrir el chat
        ct.send(a.base, B["access"], dm, {"body": "mensaje animado"})
        ok, res, log = fut.result(timeout=200)
    found, still = False, True
    try:
        d = json.loads(res)
        found, still = d["found"], d["still"]
    except Exception:
        pass
    step("mensaje en vivo con .anim (y la suelta al terminar)",
         ok and found and not still, f"res={res!r} log={log[-200:]}")

    # =================== 8. emojis Twemoji + panel Discord ============
    print("→ paso8 panel Twemoji (W29b)")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-8-panel.png", js=JS_PANEL)
    cats, subs, sub0 = 0, 0, ""
    try:
        d = json.loads(res)
        cats, subs, sub0 = d["cats"], d["subs"], d["sub0"]
    except Exception:
        pass
    step("panel Discord + emojis Google (Noto) en burbuja y chip",
         ok and cats >= 5 and subs >= 3 and sub0.endswith(":"),
         f"res={res!r} log={log[-200:]}")
    svg_ok = False
    try:
        with urllib.request.urlopen(a.base + "/static/emoji/1f525.svg",
                                    timeout=10) as r:
            svg_ok = r.status == 200 and b"<svg" in r.read(400)
    except Exception:
        pass
    step("SVG Twemoji servido on-demand", svg_ok)
    noto_ok = False
    try:
        with urllib.request.urlopen(a.base + "/static/emoji-noto/1f525.png",
                                    timeout=10) as r:
            noto_ok = r.status == 200 and b"\x89PNG" in r.read(8)
    except Exception:
        pass
    step("PNG de Google (Noto) servido on-demand", noto_ok)

    # =================== 9. escribiendo con nombre ====================
    print("→ paso9 escribiendo con nombre + pelotita (W29c)")
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(shot, a.base + "/", SHOTS / "w29-9-typing.png",
                        JS_TYPING, 80)
        time.sleep(3.5)             # deja cargar la página y abrir el chat
        end = time.time() + 13
        while time.time() < end:    # B teclea mientras A mira (3,5 s c/u)
            ct.http("POST", f"{a.base}/api/chats/{dm}/typing", {}, B["access"])
            time.sleep(1.2)
        ok, res, log = fut.result(timeout=240)
    lbl = ""
    try:
        lbl = json.loads(res).get("label", "")
    except Exception:
        pass
    step("fila 'está escribiendo' con nombre + pelotita en la lista",
         ok and B["user"]["username"] in lbl and "est\u00e1" in lbl,
         f"res={res!r} log={log[-200:]}")

    # =================== 10. Info del usuario + menús =================
    print("→ paso10 Info del usuario + menús (W29c)")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-10-info.png", js=JS_INFO)
    head, panelMenu, msgMenu = "", False, False
    try:
        d = json.loads(res)
        head, panelMenu, msgMenu = d["head"], d["panelMenu"], d["msgMenu"]
    except Exception:
        pass
    step("'Info del usuario' (DM) y menús dentro de la ventana",
         ok and head == "Info del usuario" and panelMenu and msgMenu,
         f"res={res!r} log={log[-200:]}")

    # =================== 11. grupo: avatares, ✓✓ y tooltip ==========
    print("→ paso11 grupo (W29c)")
    gtitle = f"grupo w29 {tag}"
    st, g = ct.http("POST", a.base + "/api/chats/group",
                    {"title": gtitle, "members": [B["user"]["username"]]},
                    token=A["access"])
    if st not in (200, 201):
        raise SystemExit(f"✗ crear grupo: {st} {g}")
    grp = g["chat"]["id"]
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(shot, a.base + "/", SHOTS / "w29-11-grupo.png",
                        JS_GROUP.replace("«GTITLE»", gtitle), 80)
        time.sleep(4)               # A abre el grupo y escribe
        # B espera el mensaje de A…
        mid, mseq = None, 0
        end = time.time() + 25
        while time.time() < end and mid is None:
            st2, msgs = ct.http("GET",
                                f"{a.base}/api/chats/{grp}/messages",
                                token=B["access"])
            for m in msgs.get("messages") or []:
                if m.get("sender") and m["sender"]["id"] == A["user"]["id"]:
                    mid, mseq = m["id"], m.get("seq", 0)
            if mid is None:
                time.sleep(0.6)
        if mid is not None:
            # …y contesta: tanda de 3 seguidos (cara + 2 columnas
            # vacías), lectura (✓✓ azul), reacción (tooltip) y una
            # RESPUESTA citada (nombre del emisor arriba de la cita).
            ct.send(a.base, B["access"], grp, {"body": "llego 1"})
            ct.send(a.base, B["access"], grp, {"body": "llego 2"})
            ct.send(a.base, B["access"], grp, {"body": "llego 3"})
            ct.http("POST", f"{a.base}/api/chats/{grp}/read",
                    {"seq": mseq}, token=B["access"])
            ct.http("POST",
                    f"{a.base}/api/chats/{grp}/reactions/{mid}",
                    {"emoji": "\U0001F602"}, token=B["access"])
            ct.http("POST", f"{a.base}/api/chats/{grp}/messages",
                    {"body": "respondiendo al citado", "reply_to": mid},
                    token=B["access"])
        ok, res, log = fut.result(timeout=240)
    av, tip, read = False, "", False
    dom_above, name_above, faces, spacers = False, False, 0, 0
    try:
        d = json.loads(res)
        av, tip, read = d["avatar"], d["tip"], d["read"]
        dom_above = d["domAbove"]
        name_above = d["nameAbove"]
        faces, spacers = d["withFace"], d["spacer"]
    except Exception:
        pass
    step("grupo: cara por tanda + ✓✓ azul + tooltip + nombre arriba de la cita",
         ok and av and read and tip.startswith("\U0001F602") and len(tip) > 2
         and dom_above and name_above and faces >= 1 and spacers >= 1,
         f"res={res!r} log={log[-200:]}")

    # =================== 12. spoilers (W29d) =========================
    print("→ paso12 spoilers (W29d)")
    ok, res, log = shot(
        a.base + "/", SHOTS / "w29-12-spoiler.png",
        js=JS_SPOIL.replace("«DM»", str(dm)).replace("«PNG1»", PNG1))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("spoiler texto (long-press 3 s en Enviar): sin botón suelto → capa cubre → hora y palomitas visibles → 'Mostrar Spoiler' → tocar revela → 'Ocultar' tapa → al salir reaparece",
         ok and d.get("stage") == "ok" and d.get("noSp0") and d.get("holdCls")
         and d.get("covers") and d.get("hid") and d.get("metaVis")
         and d.get("ovTxtOk") and d.get("dotTxtOk")
         and d.get("afterShow") and d.get("afterHide")
         and d.get("afterReopen"),
         f"res={res!r} log={log[-200:]}")
    step("spoiler en imagen (botón 'Mensaje Spoiler: On/Off' con adjunto) y miniatura tapada en la galería",
         ok and d.get("on2") and d.get("imgOv") and d.get("galOv"),
         f"res={res!r} on2={d.get('on2')} imgOv={d.get('imgOv')} galOv={d.get('galOv')}")

    # =================== 13. formato de hora 12/24 (W29e) ============
    print("→ paso13 formato de hora 12/24 (W29e)")
    ok, res, log = shot(a.base + "/", SHOTS / "w29-13-hora.png",
                        js=JS_H12.replace("«DM»", str(dm)))
    t24 = t12 = back24 = before = ""
    try:
        dd = json.loads(res)
        t24, t12, back24, before = (dd.get("t24", ""), dd.get("t12", ""),
                                    dd.get("back24", ""), dd.get("before", ""))
    except Exception:
        pass
    step("hora: 24 h por defecto → desplegable a 12 h (am/pm) → vuelve a 24 h",
         ok and re.match(r"^\d{1,2}:\d{2}$", t24 or "")
         and (" am" in (t12 or "") or " pm" in (t12 or ""))
         and back24 == t24 and before == "24",
         f"t24={t24!r} t12={t12!r} back24={back24!r} before={before!r} "
         f"log={log[-200:]}")

    # =================== 14. E2E (W29f) ==============================
    print("→ paso14 E2E cifrado de extremo a extremo (W29f)")
    b_priv, b_pub = e2e_keypair()
    st, r = ct.http("PUT", f"{a.base}/api/users/me/e2e-key",
                    {"public_key": b_pub}, token=B["access"])
    step("B publica su clave pública E2E (P-256)",
         st in (200, 201) and r.get("ok") is True, f"{st} {r}")

    ok, res, log = shot(a.base + "/", SHOTS / "w29-14-e2e-on.png",
                        js=JS_E2E1.replace("«DM»", str(dm)))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("auto-activa cifrado al abrir el DM (sin switch) + código numérico + preview descifrado",
         ok and d.get("stage") == "ok" and d.get("on") and d.get("noswitch")
         and d.get("sent")
         and (d.get("sas") or "").replace(" ", "").isdigit()
         and len((d.get("sas") or "").replace(" ", "")) == 6
         and "secreto para ti w29" in (d.get("prev") or ""),
         f"res={res!r} log={log[-200:]}")

    # el server jamás ve el texto: body = marcador; B descifra en Python
    key_b, marker, plain = None, "", ""
    st, rka = ct.http("GET",
                      f"{a.base}/api/users/{A['user']['username']}/e2e-key",
                      token=B["access"])
    st2, msgs = ct.http("GET", f"{a.base}/api/chats/{dm}/messages",
                        token=B["access"])
    e2emsg = None
    for m in msgs.get("messages") or []:
        snd = m.get("sender") or {}
        if m.get("e2e") and snd.get("id") == A["user"]["id"]:
            e2emsg = m
    if rka.get("public_key") and e2emsg:
        try:
            key_b = e2e_derive(b_priv, rka["public_key"],
                               B["user"]["id"], A["user"]["id"])
            marker = e2emsg.get("body") or ""
            plain = e2e_dec(key_b, e2emsg["e2e"])
        except Exception as ex:
            plain = f"EX {ex}"
    step("server guardó '[Mensaje cifrado]' + blob y B descifra el texto",
         key_b is not None and marker == "[Mensaje cifrado]"
         and plain == "secreto para ti w29",
         f"marker={marker!r} plain={plain!r}")

    # B responde cifrado → A debe verlo descifrado (WS) con preview descifrado
    ok2, res2, log2 = False, "", ""
    if key_b:
        enc = e2e_enc(key_b, "respuesta cifrada w29")
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(shot, a.base + "/", SHOTS / "w29-14-e2e-reply.png",
                            JS_E2E2.replace("«DM»", str(dm)), 80)
            time.sleep(10)   # A acaba de abrir el chat: WS en pie
            ct.http("POST", f"{a.base}/api/chats/{dm}/messages",
                    {"kind": "text", "body": "",
                     "client_msg_id": uuid.uuid4().hex, "e2e": enc},
                    token=B["access"])
            ok2, res2, log2 = fut.result(timeout=240)
    d2 = {}
    try:
        d2 = json.loads(res2)
    except Exception:
        pass
    step("A descifra la respuesta de B (nunca pinta marcador) y el preview se ve en claro",
         ok2 and d2.get("found") and d2.get("marker") is False
         and "respuesta cifrada w29" in (d2.get("prev") or ""),
         f"res={res2!r} log={log2[-200:]}")

    print(f"\nW29: {_pass[0]} ok, {_fail[0]} fallos")
    sys.exit(1 if _fail[0] else 0)


if __name__ == "__main__":
    main()
