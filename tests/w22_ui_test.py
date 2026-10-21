#!/usr/bin/env python
"""E2E W22: rutas reales (sin #), imagen con cuadro reservado, voz con el
anillo en el lugar del play, sidebar y lightbox.

  1. rutas: abrir chat DM → /app/user/<id del peer>; grupo →
     /app/group/<id del chat>; Ajustes → ?settings=1; cerrar lo limpia;
     atrás cierra el chat SIN pasar por el login
  2. deep link: /login con sesión rebota a /app; /app/user/<peer> reabre
     el chat sin recargar
  3. imagen con resolución: el marco .imgbox reserva el ancho/alto
     (300×225 para 400×300) y termina cargada sin difuminado
  4. voz: subida con el anillo EN el slot del play (b-upvoice) y play
     visible solo cuando el audio está listo (dl-done)
  5. sidebar: el ＋ queda pegado al botón de contraer (gap ~4px)
  6. lightbox: la ayuda va en píldora, desaparece al hacer zoom y
     arrastrar la imagen NO hace zoom-out
  7. búsqueda → salto con permalink ?m=<id> y el mensaje destellado
  8. anillo de foco: solo al navegar con TAB (con ratón los botones
     no quedan con contorno naranja)

Uso: server/.venv/bin/python tests/w22_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
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
  };"""

# JS1: rutas reales — DM, ajustes, cierre, atrás y grupo.
JS_RUTAS = """(async () => {
  """ + W_WAIT + """
  let err = await openChat();
  if (err) return err;
  await sleep(300);
  const dm = __fm.store.chats.filter(function (c) { return c.type === 'dm'; })[0];
  if (!dm) return 'FAIL: sin chat DM sembrado';
  const peerId = dm.title.id;
  if (location.pathname !== '/app/user/' + peerId) {
    return 'FAIL: ruta DM=' + location.pathname + ' (esperaba /app/user/' + peerId + ')';
  }
  if (location.search) return 'FAIL: la ruta trae query de más: ' + location.search;
  /* abrir Ajustes → ?settings=1 sin recargar */
  const gear = document.querySelector('.user-panel .icon-btn[title="Ajustes"]');
  if (!gear) return 'FAIL: sin engranaje';
  gear.click();
  if (!await wait('.modal.settings', 5000)) return 'FAIL: no abrió Ajustes';
  await sleep(250);
  if (location.pathname + location.search !== '/app/user/' + peerId + '?settings=1') {
    return 'FAIL: ruta con ajustes=' + location.pathname + location.search;
  }
  /* cerrar Ajustes → la query se limpia y el chat sigue abierto */
  document.querySelector('.modal.settings header .icon-btn').click();
  await sleep(350);
  if (location.search) return 'FAIL: cerrar ajustes dejó ' + location.search;
  if (location.pathname !== '/app/user/' + peerId) return 'FAIL: perdió la ruta';
  if (__fm.store.activeChatId === 0) return 'FAIL: el chat se cerró con los ajustes';
  /* atrás → cierra el chat y queda /app (NUNCA el login) */
  history.back();
  await sleep(450);
  if (location.pathname !== '/app') return 'FAIL: atrás dejó ' + location.pathname;
  if (__fm.store.activeChatId !== 0) return 'FAIL: atrás no cerró el chat';
  if (document.querySelector('#l-id')) return 'FAIL: el atrás mandó al login';
  /* grupo → /app/group/<id del chat> */
  const g = __fm.store.chats.filter(function (c) { return c.type === 'group'; })[0];
  if (!g) return 'FAIL: sin grupo sembrado';
  const gi = Array.prototype.slice.call(document.querySelectorAll('.chat-list .chat-item'))
    .filter(function (el) { return el.textContent.indexOf('W22 Grupo') >= 0; })[0];
  if (!gi) return 'FAIL: el grupo no está en la lista';
  gi.click();
  await sleep(450);
  if (location.pathname !== '/app/group/' + g.id) {
    return 'FAIL: ruta grupo=' + location.pathname + ' (esperaba /app/group/' + g.id + ')';
  }
  return 'OK rutas: DM peer, ?settings, atrás sin login, grupo';
})()"""

# JS2: deep link — /login con sesión rebota; /app/user/<peer> reabre el chat.
JS_DEEP = """(async () => {
  """ + W_WAIT + """
  /* /login con sesión → rebota al /app (nada de pantalla de entrada) */
  history.pushState(null, '', '/login');
  window.dispatchEvent(new PopStateEvent('popstate'));
  await sleep(450);
  if (location.pathname !== '/app') return 'FAIL: /login con sesión quedó en ' + location.pathname;
  if (__fm.store.route !== 'app') return 'FAIL: la ruta interna quedó en ' + __fm.store.route;
  /* /app/user/<peer> con sesión → reabre ese chat */
  const dm = __fm.store.chats.filter(function (c) { return c.type === 'dm'; })[0];
  if (!dm) return 'FAIL: sin chat DM sembrado';
  history.pushState(null, '', '/app/user/' + dm.title.id);
  window.dispatchEvent(new PopStateEvent('popstate'));
  const t0 = Date.now();
  while (Date.now() - t0 < 8000 && __fm.store.activeChatId !== dm.id) await sleep(120);
  if (__fm.store.activeChatId !== dm.id) {
    return 'FAIL: no reabrió el chat (activeChatId=' + __fm.store.activeChatId + ')';
  }
  if (!await wait('.msgs .msg')) return 'FAIL: sin mensajes tras el deep link';
  if (location.pathname !== '/app/user/' + dm.title.id) return 'FAIL: la ruta cambió';
  return 'OK deep link reabre /app/user/' + dm.title.id;
})()"""

# JS3: imagen con resolución reservada.
JS_IMG = """(async () => {
  """ + W_WAIT + """
  let err = await openChat();
  if (err) return err;
  /* esperar a que el marco .imgbox termine de descargar */
  const t0 = Date.now();
  let fr = null;
  while (Date.now() - t0 < 15000) {
    fr = document.querySelector('.msgs .imgbox');
    if (fr && fr.classList.contains('dl-done')) break;
    await sleep(120);
  }
  if (!fr) return 'FAIL: sin marco .imgbox (¿sin resolución en el mensaje?)';
  if (!fr.classList.contains('dl-done')) return 'FAIL: la imagen no terminó de bajar';
  /* 400×300 → tope 300×225 (la proporción manda) */
  if (fr.style.width !== '300px' || fr.style.height !== '225px') {
    return 'FAIL: cuadro ' + fr.style.width + '×' + fr.style.height + ' (esperaba 300×225)';
  }
  const box = fr.getBoundingClientRect();
  if (Math.abs(box.width - 300) > 2 || Math.abs(box.height - 225) > 2) {
    return 'FAIL: el cuadro mide ' + Math.round(box.width) + '×' + Math.round(box.height);
  }
  const img = fr.querySelector('.b-img');
  if (!img || img.naturalWidth !== 400) return 'FAIL: la imagen no cargó completa';
  if (img.classList.contains('dl-blur')) return 'FAIL: siguió difuminada';
  /* con resolución NO va marcado como "sin anillo" */
  if (fr.getAttribute('data-noring')) return 'FAIL: marcado sin anillo con dims';
  return 'OK cuadro reservado 300×225 con imagen cargada';
})()"""

# JS4: voz — subida con anillo en el slot del play + play al terminar.
JS_VOICE = """(async () => {
  """ + W_WAIT + """
  let err = await openChat();
  if (err) return err;
  /* retrasar solo la subida de media para observar la fila pendiente */
  const X = XMLHttpRequest.prototype;
  const open0 = X.open, send0 = X.send;
  X.open = function (m, url) { this.__w22url = url; return open0.apply(this, arguments); };
  X.send = function () {
    if ((this.__w22url || '').indexOf('/api/media') >= 0) {
      const self = this;
      setTimeout(function () { send0.call(self); }, 2500);
      return;
    }
    return send0.apply(this, arguments);
  };
  const mic = await wait('.comp-mic', 6000);
  if (!mic) return 'FAIL: sin botón de micrófono';
  mic.click();
  if (!await wait('.rec-bar', 15000)) return 'FAIL: no inició la grabación';
  await sleep(1600);              // graba con el micrófono falso
  document.querySelector('.rec-send').click();
  const up = await wait('.b-upvoice', 6000);
  if (!up) return 'FAIL: sin fila .b-upvoice durante la subida';
  /* el anillo de subida ocupa el SLOT DEL PLAY (primer elemento) */
  const slot = up.querySelector('.au-btn');
  if (!slot) return 'FAIL: sin slot de play en la subida';
  if (!slot.querySelector('.up-c')) return 'FAIL: el anillo no está en el slot del play';
  if (up.firstElementChild !== slot) return 'FAIL: el slot no va primero';
  if (!up.querySelector('.wave')) return 'FAIL: sin onda en la subida';
  /* al terminar, TODOS los players (el enviado y el sembrado) quedan
     con el audio listo y el play visible */
  const done = async () => {
    const ps = document.querySelectorAll('.msgs .b-player.mframe');
    if (!ps.length) return false;
    for (let i = 0; i < ps.length; i++) {
      if (!ps[i].classList.contains('dl-done')) return false;
      const p = ps[i].querySelector('.au-btn');
      if (!p || getComputedStyle(p).visibility !== 'visible') return false;
    }
    return true;
  };
  const t1 = Date.now();
  while (Date.now() - t1 < 25000 && !(await done())) await sleep(200);
  if (!(await done())) {
    const ps = document.querySelectorAll('.msgs .b-player.mframe');
    return 'FAIL: players=' + ps.length + ' con play no visible';
  }
  return 'OK voz: anillo en el slot y play al terminar';
})()"""

# JS5: sidebar (＋ pegado a contraer) + lightbox (píldora, zoom, drag).
JS_UI = """(async () => {
  """ + W_WAIT + """
  let err = await openChat();
  if (err) return err;
  /* --- sidebar: el ＋ pegado al botón de contraer (W27c: el botón de
     Personas va entre medias, oculto en escritorio: solo se cuentan
     los visibles) --- */
  const head = document.querySelector('.side-head');
  if (!head) return 'FAIL: sin cabecera del sidebar';
  const btns = [];
  for (let i = 0; i < head.children.length; i++) {
    const c = head.children[i];
    if (c.classList.contains('icon-btn') && c.offsetParent) btns.push(c);
  }
  if (btns.length !== 2) return 'FAIL: botones del header=' + btns.length;
  const plus = btns[0].getBoundingClientRect();
  const fold = btns[1].getBoundingClientRect();
  const gap = fold.left - plus.right;
  if (gap < 0 || gap > 10) return 'FAIL: gap entre ＋ y contraer=' + gap.toFixed(1) + 'px';
  const side = document.querySelector('.sidebar').getBoundingClientRect();
  if (side.right - fold.right > 16) return 'FAIL: el par no quedó a la derecha';
  /* --- lightbox --- */
  const fr = document.querySelector('.msgs .imgbox');
  if (!fr) return 'FAIL: sin imagen para el lightbox';
  fr.click();
  const lb = await wait('.lightbox', 5000);
  if (!lb) return 'FAIL: no abrió la vista previa';
  const hint = lb.querySelector('.lb-hint');
  if (!hint) return 'FAIL: sin ayuda';
  if (!hint.querySelector('.lb-pill')) return 'FAIL: la ayuda no tiene su píldora';
  const img = lb.querySelector('.lb-img');
  img.dispatchEvent(new WheelEvent('wheel', {
    bubbles: true, cancelable: true, deltaY: -100, clientX: 200, clientY: 200 }));
  await sleep(300);
  if (lb.querySelector('.lb-hint')) return 'FAIL: la ayuda no se fue al hacer zoom';
  if (img.style.transform.indexOf('scale(1.25)') < 0) {
    return 'FAIL: la rueda no amplió (' + img.style.transform + ')';
  }
  /* arrastrar NO debe hacer zoom-out al soltar (clic de cierre) */
  img.dispatchEvent(new MouseEvent('mousedown',
    { bubbles: true, cancelable: true, clientX: 300, clientY: 300 }));
  document.dispatchEvent(new MouseEvent('mousemove',
    { bubbles: true, cancelable: true, clientX: 340, clientY: 330 }));
  document.dispatchEvent(new MouseEvent('mouseup',
    { bubbles: true, cancelable: true, clientX: 340, clientY: 330 }));
  img.dispatchEvent(new MouseEvent('click',
    { bubbles: true, cancelable: true, clientX: 340, clientY: 330 }));
  await sleep(250);
  if (img.style.transform.indexOf('scale(1.25)') < 0) {
    return 'FAIL: el arrastre hizo zoom-out (' + img.style.transform + ')';
  }
  /* un clic SIEMPRE alterna (sin arrastre de por medio) */
  img.dispatchEvent(new MouseEvent('click',
    { bubbles: true, cancelable: true, clientX: 340, clientY: 330 }));
  await sleep(250);
  if (img.style.transform.indexOf(' scale(1)') < 0) {
    return 'FAIL: el clic sin drag no redujo (' + img.style.transform + ')';
  }
  return 'OK sidebar pegado + píldora/zoom/drag del lightbox';
})()"""

# JS6: salto de búsqueda → permalink ?m=<id> y el mensaje en pantalla.
JS_JUMP = """(async () => {
  """ + W_WAIT + """
  let err = await openChat();
  if (err) return err;
  const dm = __fm.store.chats.filter(function (c) { return c.type === 'dm'; })[0];
  if (!dm) return 'FAIL: sin chat DM sembrado';
  const btn = await wait('.icon-btn[title="Buscar en el chat"]', 5000);
  if (!btn) return 'FAIL: sin botón de buscar';
  btn.click();
  /* W37b: el buscador es un MODAL (.search-modal) */
  const inp = await wait('.search-modal .search-pill input', 5000);
  if (!inp) return 'FAIL: sin buscador modal';
  inp.value = 'buenas';
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  const res = await wait('.search-modal .sp-res', 9000);
  if (!res) return 'FAIL: sin resultados de búsqueda';
  res.click();
  /* el salto deja su permalink en la URL (id exacto del mensaje) */
  const t0 = Date.now();
  while (Date.now() - t0 < 5000 && location.search.indexOf('m=') < 0) await sleep(80);
  const mm = location.search.match(/m=(\\d+)/);
  if (!mm) return 'FAIL: el salto no dejó ?m= (' + location.pathname + location.search + ')';
  const mId = parseInt(mm[1], 10);
  if (__fm.store.jumpMsg !== mId) return 'FAIL: store.jumpMsg=' + __fm.store.jumpMsg;
  if (location.pathname !== '/app/user/' + dm.title.id) {
    return 'FAIL: el salto cambió la ruta a ' + location.pathname;
  }
  /* y el mensaje quedó visible con el destello */
  const t1 = Date.now();
  let fl = null;
  while (Date.now() - t1 < 5000) {
    fl = document.querySelector('.msg.flash[data-mid="' + mId + '"]');
    if (fl) break;
    await sleep(100);
  }
  if (!fl) return 'FAIL: no marcó en pantalla el mensaje ' + mId;
  return 'OK salto ?m=' + mId;
})()"""

# W27f: el anillo de foco naranja solo con teclado (TAB). Con ratón el
# botón enfocado no debe llevar contorno (se veía como "tecla
# presionada"); :focus-visible no existe en FF78, boot.js sigue la
# modalidad con la clase html.kb-focus.
JS_FOCO = """(async () => {
  """ + W_WAIT + """
  /* W27f: en headless la ventana no tiene foco (document.hasFocus()
     false) y Gecko suprime el pseudo :focus aunque el elemento sea el
     activeElement, así que el anillo NO se puede medir con
     getComputedStyle: se verifica la modalidad (JS) y las
     declaraciones CSS que lo producen. */
  const btn = await wait('.side-head .icon-btn', 12000);
  if (!btn) return 'FAIL: sin botón en el sidebar';
  btn.focus();
  await sleep(80);
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab',
    bubbles: true }));
  await sleep(80);
  if (!document.documentElement.classList.contains('kb-focus')) {
    return 'FAIL: TAB no activó el modo teclado';
  }
  btn.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  await sleep(80);
  if (document.documentElement.classList.contains('kb-focus')) {
    return 'FAIL: el clic no apagó el modo teclado';
  }
  /* declaraciones: base SIN anillo y anillo naranja con la clase */
  let base = false, kbd = false;
  for (const sh of document.styleSheets) {
    try {
      for (const r of sh.cssRules) {
        if (!r.selectorText) continue;
        if (r.selectorText === ':focus' && r.style.outlineStyle === 'none') {
          base = true;
        }
        if (r.selectorText === 'html.kb-focus :focus') {
          /* el shorthand lleva var(): los longhand getters quedan
             vacíos, se mira el cssText tal cual */
          const t = r.style.cssText;
          if (t.indexOf('outline') >= 0 && t.indexOf('solid') >= 0 &&
              t.indexOf('2px') >= 0 && t.indexOf('--accent') >= 0) {
            kbd = true;
          }
        }
      }
    } catch (e) { /* hoja inaccesible: no aplica (solo servimos app.css) */ }
  }
  if (!base) return 'FAIL: sin la regla :focus sin anillo';
  if (!kbd) return 'FAIL: sin la regla html.kb-focus :focus';
  return 'OK foco: anillo solo con TAB (modalidad + CSS)';
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
    ua, ub = f"w22a{stamp}", f"w22b{stamp}"
    try:
        A = ct.register(a.base, f"{ua}@test.local", ua)
        B = ct.register(a.base, f"{ub}@test.local", ub)
        print(f"→ sembrados: {ua}, {ub}")

        st, res = ct.http("POST", a.base + "/api/chats/dm", {"username": ub},
                          token=A["access"])
        if st not in (200, 201):
            raise SystemExit(f"✗ dm: {st} {res}")
        dm = res["chat"]["id"]
        st, res = ct.http("POST", a.base + "/api/chats/group",
                          {"title": "W22 Grupo", "members": [ub]}, token=A["access"])
        if st not in (200, 201):
            raise SystemExit(f"✗ grupo: {st} {res}")

        ct.send(a.base, B["access"], dm,
                {"kind": "text", "body": "hola", "client_msg_id": str(uuid.uuid4())})
        ct.send(a.base, A["access"], dm,
                {"kind": "text", "body": "buenas", "client_msg_id": str(uuid.uuid4())})
        # imagen 400×300 (el server la guarda como WebP 400×300)
        png = SHOTS / "w22-400x300.png"
        png.write_bytes(make_png(400, 300))
        up = ct.upload(a.base, B["access"], png)
        ct.send(a.base, B["access"], dm,
                {"kind": "image", "body": "", "media_id": up["id"],
                 "client_msg_id": str(uuid.uuid4())})
        # nota de voz sembrada (descarga fresca al abrirla)
        wav = SHOTS / "w22-voz.wav"
        make_wav(wav)
        upv = ct.upload(a.base, B["access"], wav)
        ct.send(a.base, B["access"], dm,
                {"kind": "voice", "body": "", "media_id": upv["id"],
                 "client_msg_id": str(uuid.uuid4())})

        # perfil limpio + sesión (los shots siguientes reutilizan el perfil)
        ok0, res0, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w22-0-perfil.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        step("paso0 perfil", ok0 and res0 == "limpia", res0 or log[-300:])
        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))
        ok1, res1, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w22-0-sesion.png", js=sess_js, wait=300)
        step("paso0 sesión", ok1 and bool(res1), res1 or log[-300:])

        def shot(name, js, out, wait=500):
            j = js.replace("PEERNAME", ub)
            okk, ress, _, log = ct.run_shot(
                a.base + "/", SHOTS / out, js=j, wait=wait)
            step(name, okk and str(ress).startswith("OK"),
                 ress if ress else log[-400:])

        shot("paso1 rutas (DM, ajustes, atrás, grupo)",
             JS_RUTAS, "w22-1-rutas.png", wait=400)
        shot("paso2 deep link + rebote de /login",
             JS_DEEP, "w22-2-deep.png", wait=400)
        shot("paso3 imagen con cuadro reservado",
             JS_IMG, "w22-3-img.png")
        shot("paso4 voz: anillo en el slot del play",
             JS_VOICE, "w22-4-voz.png")
        shot("paso5 sidebar pegado + lightbox",
             JS_UI, "w22-5-ui.png")
        shot("paso6 salto de búsqueda con ?m=",
             JS_JUMP, "w22-6-jump.png")
        shot("paso7 anillo de foco solo con TAB (W27f)",
             JS_FOCO, "w22-7-foco.png")

        print(f"\nw22 UI: {ok} ok, {fail} fallas")
        sys.exit(1 if fail else 0)
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
