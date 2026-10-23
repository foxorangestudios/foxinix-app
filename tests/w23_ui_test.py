#!/usr/bin/env python
"""E2E W23: ✕/↻ DENTRO del círculo de carga y ficha informativa del adjunto.

  1. ficha: pegar una imagen abre la ficha [nombre.ext] [tipo] [tamaño]
     SIN input, el placeholder del compositor es "Mensaje" y Enter (con
     el texto vacío) envía el archivo
  2. imagen subiendo: el anillo está centrado en la burbuja y el ✕ cabe
     DENTRO del círculo; el clic en cancelar funciona (pointer-events)
  3. voz subiendo: anillo y ✕ centrados en el slot del play
  4. archivo subiendo: anillo y ✕ centrados en .up-slot
  5. descarga: ✕ dentro del anillo (imagen y archivo), anillo y ✕
     centrados en el slot del play de la voz; clic → cancela (dl-err)

Uso: server/.venv/bin/python tests/w23_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import base64
import io
import json
import math
import struct
import sys
import time
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "server"))

import chat_ui_test as ct  # noqa: E402  (helpers: register, send, run_shot…)

SHOTS = Path("/tmp/opencode")

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
  const openChat = async () => {
    const t0 = Date.now();
    let items = [];
    while (Date.now() - t0 < 12000) {
      items = document.querySelectorAll('.chat-list .chat-item');
      if (items.length) break;
      await sleep(100);
    }
    let item = null;
    for (let i = 0; i < items.length; i++) {
      if (items[i].textContent.indexOf('PEERNAME') >= 0) { item = items[i]; break; }
    }
    if (!item) {
      return 'FAIL: sin chat con PEERNAME (items=' + items.length +
        ' text0="' + (items[0] ? items[0].textContent.slice(0, 40) : '') + '")';
    }
    item.click();
    if (!await wait('.msgs .msg')) return 'FAIL: sin mensajes';
    return '';
  };
  const ctr = function (el) {
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height };
  };
  const dist = function (a, b) { return Math.sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y)); };"""

# Retrasa subida/bajada de media para observar el estado en vuelo.
# Las subidas van a /api/media y las bajadas a /media/{kind}/{fname} (ruta
# pública), así que el match es '/media' (cubre ambas).
# OJO: hay que conservar los argumentos de send() (si no, el POST va sin
# body y el server responde 422) y no enviar si xhr abortó durante la pausa.
XHR_DELAY = """const X = XMLHttpRequest.prototype;
  const open0 = X.open, send0 = X.send;
  X.open = function (m, url) { this.__w23url = url; return open0.apply(this, arguments); };
  X.send = function () {
    if ((this.__w23url || '').indexOf('/media') >= 0) {
      const self = this, args = arguments;
      setTimeout(function () {
        if (self.readyState === 1) send0.apply(self, args);
      }, DELAY_MS);
      return;
    }
    return send0.apply(this, arguments);
  };"""

# Pega un archivo sintético por Ctrl+V (mismo camino que el usuario).
PASTE_JS = """const mkFile = function (b64, name, type) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    return new File([arr], name, { type: type });
  };
  const firePaste = function (f) {
    const ev = new Event('paste', { bubbles: true, cancelable: true });
    ev.clipboardData = { items: [{ kind: 'file', getAsFile: function () { return f; } }] };
    document.dispatchEvent(ev);
  };"""

# JS1: ficha informativa + placeholder "Mensaje" + Enter sin texto envía.
JS_FICHA = """(async () => {
  """ + W_WAIT + """
  """ + PASTE_JS + """
  let err = await openChat();
  if (err) return err;
  const ta = document.querySelector('.composer-input');
  if (!ta) return 'FAIL: sin compositor';
  if (ta.getAttribute('placeholder') !== 'Mensaje') {
    return 'FAIL: placeholder=' + ta.getAttribute('placeholder');
  }
  """ + XHR_DELAY.replace("DELAY_MS", "2500") + """
  /* pegar una imagen abre la ficha (ya sin input de caption) */
  firePaste(mkFile('__PNG64__', 'pegado.png', 'image/png'));
  const strip = await wait('.cap-strip', 6000);
  if (!strip) return 'FAIL: el Ctrl+V no abrió la ficha de adjunto';
  if (strip.querySelector('input, textarea')) {
    return 'FAIL: la ficha trae un input (debería ser solo informativa)';
  }
  const nm = strip.querySelector('.cs-name');
  if (!nm || nm.textContent.indexOf('pegado.png') < 0) {
    return 'FAIL: sin nombre en la ficha (' + (nm ? nm.textContent : 'nulo') + ')';
  }
  const ty = strip.querySelector('.cs-type');
  if (!ty || ty.textContent.trim() !== 'Imagen') {
    return 'FAIL: tipo=' + (ty ? ty.textContent : 'nulo');
  }
  const sz = strip.querySelector('.cs-size');
  if (!sz || !/\\d/.test(sz.textContent)) return 'FAIL: sin tamaño en la ficha';
  /* enviar habilitado y foco en el compositor (Enter basta) */
  const sb = document.querySelector('.send-btn');
  if (!sb || sb.disabled) return 'FAIL: enviar deshabilitado con adjunto y sin texto';
  if (document.activeElement !== ta) return 'FAIL: el foco no quedó en el compositor';
  ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  const up = await wait('.b-upmedia', 6000);
  if (!up) return 'FAIL: Enter no envió el archivo adjunto';
  const t0 = Date.now();
  while (Date.now() - t0 < 20000 && document.querySelector('.b-upmedia')) await sleep(150);
  if (document.querySelector('.b-upmedia')) {
    const ms = __fm.store.msgs[__fm.store.activeChatId];
    const l = ms[ms.length - 1];
    return 'FAIL: la subida no terminó (state=' +
      (l && l.upload ? l.upload.state + '/' + (l.upload.err || '') : '?') + ')';
  }
  if (document.querySelector('.composer-input').value !== '') return 'FAIL: no limpió el borrador';
  const msgs = __fm.store.msgs[__fm.store.activeChatId];
  const last = msgs[msgs.length - 1];
  if (!last || last.kind !== 'image' || last.pending) {
    return 'FAIL: el último mensaje no es la imagen enviada';
  }
  if (last.body) return 'FAIL: el mensaje quedó con texto "' + last.body + '"';
  return 'OK ficha informativa y Enter envía sin texto';
})()"""

# JS2: imagen subiendo — anillo centrado en la burbuja y ✕ DENTRO del círculo.
JS_IMGSUB = """(async () => {
  """ + W_WAIT + """
  """ + PASTE_JS + """
  let err = await openChat();
  if (err) return err;
  """ + XHR_DELAY.replace("DELAY_MS", "2500") + """
  firePaste(mkFile('__PNG64__', 'pendiente.png', 'image/png'));
  const strip = await wait('.cap-strip', 6000);
  if (!strip) return 'FAIL: el Ctrl+V no abrió la ficha de adjunto';
  const ta = document.querySelector('.composer-input');
  ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  const up = await wait('.b-upmedia', 6000);
  if (!up) return 'FAIL: sin burbuja .b-upmedia';
  const ov = up.querySelector('.up-ov');
  if (!ov) return 'FAIL: sin .up-ov en la subida';
  /* el círculo queda centrado sobre la burbuja */
  const uc = ctr(up), oc = ctr(ov);
  if (dist(uc, oc) > 1.2) return 'FAIL: .up-ov descentrado por ' + dist(uc, oc).toFixed(2) + 'px';
  const ring = ov.querySelector('.up-c');
  if (!ring) return 'FAIL: sin anillo en la subida';
  const btn = ov.querySelector('.up-btn');
  if (!btn || btn.parentNode !== ov) return 'FAIL: el ✕ no está dentro de .up-ov';
  const pct = ov.querySelector('.up-pct');
  if (!pct || pct.textContent.indexOf('%') < 0) return 'FAIL: sin porcentaje en el círculo';
  /* el ✕ debe caber DENTRO del anillo (interior = 19.5/48 del diámetro) */
  const inner = 19.5 / 48 * oc.w;
  const far = dist(oc, ctr(btn)) + ctr(btn).w / 2;
  if (far > inner + 0.5) {
    return 'FAIL: el ✕ se sale del círculo (' + far.toFixed(1) + ' > ' + inner.toFixed(1) + ')';
  }
  btn.click();                     /* cancelar desde dentro del círculo */
  const t0 = Date.now();
  while (Date.now() - t0 < 4000 && document.querySelector('.b-upmedia')) await sleep(100);
  if (document.querySelector('.b-upmedia')) return 'FAIL: el ✕ no canceló la subida';
  return 'OK imagen: anillo centrado y ✕ dentro (cancela)';
})()"""

# JS3: voz subiendo — anillo y ✕ centrados en el slot del play.
JS_VOZ = """(async () => {
  """ + W_WAIT + """
  let err = await openChat();
  if (err) return err;
  """ + XHR_DELAY.replace("DELAY_MS", "2500") + """
  const mic = await wait('.comp-mic', 6000);
  if (!mic) return 'FAIL: sin botón de micrófono';
  mic.click();
  if (!await wait('.rec-bar', 15000)) return 'FAIL: no inició la grabación';
  await sleep(1600);               // graba con el micrófono falso
  document.querySelector('.rec-send').click();
  const up = await wait('.b-upvoice', 6000);
  if (!up) return 'FAIL: sin fila .b-upvoice durante la subida';
  const slot = up.querySelector('.au-btn');
  if (!slot) return 'FAIL: sin slot de play en la subida';
  if (up.firstElementChild !== slot) return 'FAIL: el slot no va primero';
  const ring = slot.querySelector('.up-c');
  if (!ring) return 'FAIL: el anillo no está en el slot del play';
  const btn = slot.querySelector('.up-btn-static');
  if (!btn || btn.parentNode !== slot) return 'FAIL: el ✕ no está dentro del slot';
  const sc = ctr(slot), rc = ctr(ring), bc = ctr(btn);
  if (dist(sc, rc) > 1.2) return 'FAIL: anillo descentrado del slot por ' + dist(sc, rc).toFixed(2) + 'px';
  if (dist(sc, bc) > 1.2) return 'FAIL: ✕ descentrado del slot por ' + dist(sc, bc).toFixed(2) + 'px';
  const inner = 19.5 / 48 * rc.w;              /* interior del anillo de 30px */
  if (dist(rc, bc) + bc.w / 2 > inner + 0.6) return 'FAIL: el ✕ se sale del anillo';
  btn.click();                     /* cancelar desde dentro del slot */
  const t0 = Date.now();
  while (Date.now() - t0 < 4000 && document.querySelector('.b-upvoice')) await sleep(100);
  if (document.querySelector('.b-upvoice')) return 'FAIL: el ✕ no canceló la voz';
  return 'OK voz: anillo y ✕ centrados en el slot (cancela)';
})()"""

# JS4: archivo subiendo — anillo y ✕ centrados en .up-slot.
JS_FILE = """(async () => {
  """ + W_WAIT + """
  """ + PASTE_JS + """
  let err = await openChat();
  if (err) return err;
  """ + XHR_DELAY.replace("DELAY_MS", "2500") + """
  firePaste(mkFile('__TXT64__', 'nota.txt', 'text/plain'));
  const up = await wait('.b-upfile', 6000);
  if (!up) return 'FAIL: sin fila .b-upfile durante la subida';
  const slot = up.querySelector('.up-slot');
  if (!slot) return 'FAIL: sin .up-slot en la subida';
  const ring = slot.querySelector('.up-c');
  if (!ring) return 'FAIL: sin anillo en el slot';
  const btn = slot.querySelector('.up-btn-static');
  if (!btn || btn.parentNode !== slot) return 'FAIL: el ✕ no está dentro del slot';
  const sc = ctr(slot), rc = ctr(ring), bc = ctr(btn);
  if (dist(sc, rc) > 1.2) return 'FAIL: anillo descentrado del slot por ' + dist(sc, rc).toFixed(2) + 'px';
  if (dist(sc, bc) > 1.2) return 'FAIL: ✕ descentrado del slot por ' + dist(sc, bc).toFixed(2) + 'px';
  const inner = 19.5 / 48 * rc.w;
  if (dist(rc, bc) + bc.w / 2 > inner + 0.6) return 'FAIL: el ✕ se sale del anillo';
  btn.click();                     /* cancelar desde dentro del slot */
  const t0 = Date.now();
  while (Date.now() - t0 < 4000 && document.querySelector('.b-upfile')) await sleep(100);
  if (document.querySelector('.b-upfile')) return 'FAIL: el ✕ no canceló el archivo';
  return 'OK archivo: anillo y ✕ centrados en el slot (cancela)';
})()"""

# JS5: descarga — ✕ dentro del anillo y voz centrada en el slot del play.
JS_DL = """(async () => {
  """ + W_WAIT + """
  """ + XHR_DELAY.replace("DELAY_MS", "6000") + """
  let err = await openChat();
  if (err) return err;
  /* imagen: ✕ centrado dentro del anillo de 48 */
  const iov = await wait('.msgs .b-media.mframe .mf-ov', 8000);
  if (!iov) return 'FAIL: sin overlay de descarga en la imagen';
  const iring = iov.querySelector('.up-c');
  const ibtn = iov.querySelector('.mf-btn');
  if (!iring || !ibtn) return 'FAIL: sin anillo/✕ en la descarga de la imagen';
  const ic = ctr(iring), ib = ctr(ibtn);
  if (dist(ic, ib) > 1.2) return 'FAIL: ✕ descentrado del anillo por ' + dist(ic, ib).toFixed(2) + 'px';
  const iinner = 19.5 / 48 * ic.w;
  if (dist(ic, ib) + ib.w / 2 > iinner + 0.6) return 'FAIL: el ✕ se sale del anillo de la imagen';
  /* voz: el anillo vive EN el slot del play y queda centrado en él */
  const pov = await wait('.msgs .b-player.mframe .mf-ov', 8000);
  if (!pov) return 'FAIL: sin overlay de descarga en la voz';
  const pframe = pov.closest('.b-player');
  const pslot = pframe.querySelector('.au-btn');
  if (!pslot) return 'FAIL: sin slot de play';
  const pring = pov.querySelector('.up-c');
  const pbtn = pov.querySelector('.mf-btn');
  if (!pring || !pbtn) return 'FAIL: sin anillo/✕ en la descarga de la voz';
  const ps = ctr(pslot), pr = ctr(pring), pb = ctr(pbtn);
  if (dist(ps, pr) > 1.2 || dist(ps, pb) > 1.2) {
    return 'FAIL: voz descarga slot/anello/✕ = ' + dist(ps, pr).toFixed(1) + '/' +
      dist(ps, pb).toFixed(1) + 'px (ov=' + JSON.stringify(ctr(pov)) +
      ' frame=' + JSON.stringify(ctr(pframe)) + ' slot=' + JSON.stringify(ps) +
      ' ring=' + JSON.stringify(pr) + ' btn=' + JSON.stringify(pb) + ')';
  }
  const pinner = 19.5 / 48 * pr.w;
  if (dist(pr, pb) + pb.w / 2 > pinner + 0.6) return 'FAIL: el ✕ se sale del anillo de la voz';
  /* archivo: se baja al hacer clic (dlFile) → ✕ dentro del anillo chico */
  const fframe = document.querySelector('.msgs .b-file.mframe');
  if (!fframe) return 'FAIL: sin mensaje de archivo para descargar';
  fframe.click();
  const fov = await wait('.msgs .b-file.mframe .mf-ov', 8000);
  if (!fov) return 'FAIL: sin overlay de descarga en el archivo';
  const fring = fov.querySelector('.up-c');
  const fbtn = fov.querySelector('.mf-btn');
  if (!fring || !fbtn) return 'FAIL: sin anillo/✕ en la descarga del archivo';
  const fc = ctr(fring), fb = ctr(fbtn);
  if (dist(fc, fb) > 1.2) return 'FAIL: ✕ descentrado del anillo del archivo por ' + dist(fc, fb).toFixed(2) + 'px';
  const finner = 19.5 / 48 * fc.w;
  if (dist(fc, fb) + fb.w / 2 > finner + 0.6) return 'FAIL: el ✕ se sale del anillo del archivo';
  /* el ✕ dentro del anillo cancela la descarga (dl-err) */
  ibtn.click();
  const t0 = Date.now();
  let dead = null;
  while (Date.now() - t0 < 3000) {
    dead = document.querySelector('.msgs .b-media.dl-err');
    if (dead) break;
    await sleep(100);
  }
  if (!dead) return 'FAIL: el clic en el ✕ no canceló la descarga';
  return 'OK descargas: ✕ dentro del anillo y voz centrada en el slot';
})()"""


def make_wav(path: Path, secs: float = 1.0, rate: int = 8000):
    """WAV PCM de `secs` segundos (tono suave): el player lo decodifica."""
    n = int(rate * secs)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(n)
        )
        w.writeframes(frames)


def make_png(width: int, height: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (60, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    ok = fail = 0

    def step(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}  {detail}")
        else:
            fail += 1
            print(f"  FAIL {name}  {detail}")

    stamp = str(int(time.time()))[-7:]
    ua, ub = f"w23a{stamp}", f"w23b{stamp}"
    png64 = base64.b64encode(make_png(64, 48)).decode()
    txt64 = base64.b64encode(b"hola, esto es una nota de prueba").decode()
    try:
        A = ct.register(a.base, f"{ua}@test.local", ua)
        B = ct.register(a.base, f"{ub}@test.local", ub)
        print(f"→ sembrados: {ua}, {ub}")

        st, res = ct.dm_between(a.base, A["access"], B["access"], ua, ub)
        if st not in (200, 201):
            raise SystemExit(f"✗ dm: {st} {res}")
        dm = res["chat"]["id"]

        # semilla: texto + imagen + voz + archivo (todo lo que mira W23)
        ct.send(a.base, B["access"], dm,
                {"kind": "text", "body": "hola", "client_msg_id": str(uuid.uuid4())})
        png = SHOTS / "w23-400x300.png"
        png.write_bytes(make_png(400, 300))
        up = ct.upload(a.base, B["access"], png)
        ct.send(a.base, B["access"], dm,
                {"kind": "image", "body": "", "media_id": up["id"],
                 "client_msg_id": str(uuid.uuid4())})
        wav = SHOTS / "w23-voz.wav"
        make_wav(wav)
        upv = ct.upload(a.base, B["access"], wav)
        ct.send(a.base, B["access"], dm,
                {"kind": "voice", "body": "", "media_id": upv["id"],
                 "client_msg_id": str(uuid.uuid4())})
        txt = SHOTS / "w23-nota.txt"
        txt.write_bytes(b"nota de prueba W23")
        upt = ct.upload(a.base, B["access"], txt)
        ct.send(a.base, B["access"], dm,
                {"kind": "file", "body": "", "media_id": upt["id"],
                 "client_msg_id": str(uuid.uuid4())})

        # perfil limpio + sesión (los shots siguientes reutilizan el perfil)
        ok0, res0, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w23-0-perfil.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        step("paso0 perfil", ok0 and res0 == "limpia", res0 or log[-300:])
        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))
        ok1, res1, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w23-0-sesion.png", js=sess_js, wait=300)
        step("paso0 sesión", ok1 and bool(res1), res1 or log[-300:])

        def shot(name, js, out, wait=500):
            j = js.replace("PEERNAME", ub).replace("__PNG64__", png64) \
                  .replace("__TXT64__", txt64)
            okk, ress, _, log = ct.run_shot(
                a.base + "/", SHOTS / out, js=j, wait=wait)
            step(name, okk and str(ress).startswith("OK"),
                 ress if ress else log[-400:])

        # Las descargas van PRIMERO: el SW cachea /media/* y las pruebas
        # de geometría necesitan el overlay en vuelo (sin caché).
        shot("paso1 descargas: ✕ dentro del anillo",
             JS_DL, "w23-1-dl.png", wait=600)
        shot("paso2 ficha + Enter sin texto envía",
             JS_FICHA, "w23-2-ficha.png", wait=400)
        shot("paso3 imagen: anillo centrado y ✕ dentro",
             JS_IMGSUB, "w23-3-img.png")
        shot("paso4 voz: anillo y ✕ centrados en el slot",
             JS_VOZ, "w23-4-voz.png")
        shot("paso5 archivo: anillo y ✕ centrados en el slot",
             JS_FILE, "w23-5-file.png")

        print(f"\nw23 UI: {ok} ok, {fail} fallas")
        sys.exit(1 if fail else 0)
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
