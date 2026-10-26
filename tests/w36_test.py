#!/usr/bin/env python
"""E2E W36: lote de optimización y detalle de UI.

Siembra A (owner) y B (member): DM entre ambos + grupo "W36-Grupo…" con
B. Maneja Firefox headless (BiDi via scripts/shot.py):

  API:
  1. favoritos de GIFs de la biblioteca: POST/GET/DELETE y validaciones
     (400 nombre raro, 404 inexistente)
  2. favoritos de GIFs subidos (media_id): el listado devuelve URL
     firmada fresca
  3. admin-delete: en el grupo el owner A elimina el mensaje de B (200
     y desaparece); el miembro B NO puede eliminar el de A (403)

  UI (sesión de A):
  4. WS caído → el pie del sidebar muestra "Desconectado"
  5. modal "Tu perfil": la pelotica de estado mide 22px (doble)
  6. chat-head del grupo: "Agregar miembros" con icono i-userplus
  7. menús: segundo clic en el ⋯ de la lista cierra el menú
  8. panel del compositor: altura fija entre pestañas + animación de
     apertura + stickers Twemoji (<img>, no texto nativo)
  9. en el grupo, el ⋯ de un mensaje ajeno ofrece "Eliminar mensaje"
     (A es owner); y el modal de fijados junta título+(1) y el
     conteo de la fila es texto plano transparente
 10. el GIF en la DM: burbuja transparente (.bubble.gif), hora/palomitas
     sin pastilla oscura y botón ★ en la barra flotante
 11. reproductores propios: audio adjunto con player (.au-btn + <audio>
     oculto) y video con controles dentro (.v-center/.v-bar/.v-fs/.v-meta)
     que se ocultan a los 1 s reproduciendo (.vhide)
 11b. W43: volumen en pop-up VERTICAL por encima del botón; el botón
     de pantalla completa ENTRA y SALE (icono i-collapse) y el video
     llena la pantalla; al ocultarse los controles no reaparece la ✕
     de descarga (Vue no borra dl-done)
 12. favoritos en la UI: ★ del mensaje → pestaña GIFs con sección
     "Favoritos"; ★ de una miniatura de la biblioteca

Uso: server/.venv/bin/python tests/w36_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import math
import struct
import subprocess
import sys
import time
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")

_pass = [0]
_fail = [0]


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  \u2713 {name}")
    else:
        _fail[0] += 1
        print(f"  \u2717 {name}: {detail}")


def shot(url, out, js=None, wait=400, timeout=180):
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
  };"""


def js_t(tpl, **kw):
    out = W_WAIT + "\n" + tpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return out


# ------------------------------------------------------------------ UI

JS_STATUS = """(async () => {
  await boot();
  __fm.store.ws = 'off';
  await sleep(400);
  const el = await wait('.up-status', 4000);
  const off = el ? el.textContent : '';
  __fm.store.ws = 'on';
  await sleep(300);
  const on = el ? el.textContent : '';
  return JSON.stringify({ off: off, on: on });
})()"""

JS_MEPROF = """(async () => {
  await boot();
  __fm.store.meProfileOpen = true;
  const mp = await wait('.meprof', 6000);
  if (!mp) return 'FAIL: sin modal de perfil';
  const av = mp.querySelector('.mp-view .av-wrap');
  if (!av) return 'FAIL: sin avatar en el modal';
  const aft = getComputedStyle(av, '::after');
  return JSON.stringify({ dotW: aft.width, dotH: aft.height });
})()"""

JS_GHEAD = """(async () => {
  await boot();
  const head0 = document.querySelector('.chat-head');
  if (!head0 || head0.textContent.indexOf('{GT}') < 0) {
    const items = Array.from(document.querySelectorAll('.chat-item'));
    const gi = items.find(function (el) {
      return el.textContent.indexOf('{GT}') >= 0;
    });
    if (!gi) return 'FAIL: sin grupo en la lista';
    gi.click();
  }
  if (!await wait('.chat-head', 8000)) return 'FAIL: no abrió el grupo';
  const btn = document.querySelector('.chat-head button[title="Agregar miembros"]');
  const use = btn ? btn.querySelector('use') : null;
  return JSON.stringify({
    btn: !!btn,
    icon: use ? (use.getAttribute('href') || '') : '',
  });
})()"""

JS_CTX = """(async () => {
  await boot();
  const m = await wait('.chat-list .ci-menu', 8000);
  if (!m) return 'FAIL: sin ⋯ de la lista';
  m.click();
  if (!await wait('.ctx-menu', 4000)) return 'FAIL: no abrió el menú';
  m.click();
  await sleep(300);
  return JSON.stringify({ open: !!document.querySelector('.ctx-menu') });
})()"""

JS_PANEL = """(async () => {
  await boot();
  /* W40: este paso revisa el render con IMÁGENES del panel — se fija
     el estilo Twemoji (el default ahora es "Nativo del sistema"):
     el desplegable de Ajustes es lo que lo cambia en producto. */
  __fm.store.prefs.emo = 'twemoji';
  await sleep(200);
  const items = Array.from(document.querySelectorAll('.chat-item'));
  const dm = items.find(function (el) {
    return el.textContent.indexOf('{BU}') >= 0;
  });
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  if (!await wait('.msgs .msg', 8000)) return 'FAIL: no abrió la DM';
  const b = await wait('.comp-emo', 8000);
  if (!b) return 'FAIL: sin botón de emojis';
  b.click();
  const p = await wait('.st-panel', 5000);
  if (!p) return 'FAIL: no abrió el panel';
  const hEmo = p.offsetHeight;
  const w = p.offsetWidth;
  const anim = getComputedStyle(p).animationName;
  const tabs = Array.from(p.querySelectorAll('.ep-tab'));
  const gifTab = tabs.find(function (t) { return t.textContent === 'GIFs'; });
  const stTab = tabs.find(function (t) { return t.textContent === 'Stickers'; });
  if (!gifTab || !stTab) return 'FAIL: sin pestañas';
  gifTab.click();
  await sleep(500);
  const hGif = p.offsetHeight;
  stTab.click();
  await sleep(500);
  const hSt = p.offsetHeight;
  const stImg = p.querySelectorAll('.st-grid .st-e img.emo').length;
  const stTxt = p.querySelectorAll('.st-grid .st-e > span').length;
  return JSON.stringify({ hEmo: hEmo, hGif: hGif, hSt: hSt, w: w,
                          anim: anim, stImg: stImg, stTxt: stTxt });
})()"""

JS_ADMENU = """(async () => {
  await boot();
  const head0 = document.querySelector('.chat-head');
  if (!head0 || head0.textContent.indexOf('{GT}') < 0) {
    const items = Array.from(document.querySelectorAll('.chat-item'));
    const gi = items.find(function (el) {
      return el.textContent.indexOf('{GT}') >= 0;
    });
    if (!gi) return 'FAIL: sin grupo en la lista';
    gi.click();
  }
  if (!await wait('.msgs .msg', 8000)) return 'FAIL: no abrió el grupo';
  let t = Date.now();
  let row = null;
  while (Date.now() - t < 8000) {
    row = Array.from(document.querySelectorAll('.msgs .msg')).find(function (el) {
      return el.textContent.indexOf('{BM}') >= 0;
    });
    if (row) break;
    await sleep(150);
  }
  if (!row) return 'FAIL: sin mensaje de B';
  const acts = row.querySelector('.b-actions');
  if (acts) acts.style.pointerEvents = 'auto';
  const more = row.querySelector('.b-more');
  if (!more) return 'FAIL: sin ⋯ del mensaje';
  more.click();
  const menu = await wait('.ctx-menu', 4000);
  if (!menu) return 'FAIL: no abrió el menú del mensaje';
  const texts = Array.from(menu.querySelectorAll('button'))
    .map(function (b2) { return b2.textContent; });
  return JSON.stringify({ texts: texts });
})()"""

JS_PINS = """(async () => {
  await boot();
  /* el chat activo no se re-abre: un clic al ya activo dispara
     closeChat/openChat y el watcher cierra el modal (vive en el aside) */
  const head0 = document.querySelector('.chat-head');
  if (!head0 || head0.textContent.indexOf('{GT}') < 0) {
    const items = Array.from(document.querySelectorAll('.chat-item'));
    const gi = items.find(function (el) {
      return el.textContent.indexOf('{GT}') >= 0;
    });
    if (!gi) return 'FAIL: sin grupo en la lista';
    gi.click();
    await wait('.chat-head', 8000);
  }
  /* info cerrada → se abre; abierta (cargando) → sólo se espera */
  if (!document.querySelector('.pp-acts')) {
    const openBtn = await wait('.chat-head button[title="Info del chat"]', 8000);
    if (!openBtn) return 'FAIL: sin botón de info';
    openBtn.click();
  }
  const ph = await wait('.pp-acts .pp-pinhead', 8000);
  if (!ph) return 'FAIL: sin accesos de fijados';
  /* los pins llegan por API: esperar al dato antes de medir el texto */
  let tc = Date.now();
  while (Date.now() - tc < 6000) {
    const c0 = ph.querySelector('.pp-ncount');
    if (c0 && c0.textContent.trim()) break;
    await sleep(150);
  }
  const cnt = ph.querySelector('.pp-ncount');
  const cbg = cnt ? getComputedStyle(cnt).backgroundColor : '';
  const ctxt = cnt ? cnt.textContent.trim() : '';
  ph.click();
  const md = await wait('.pp-modal', 6000);
  if (!md) return 'FAIL: sin modal de fijados';
  let tm = Date.now();
  while (Date.now() - tm < 6000) {
    const sp = md.querySelector('header span');
    if (sp && sp.textContent.indexOf('(') >= 0) break;
    await sleep(150);
  }
  const head = md.querySelector('header');
  const kids = head ? Array.from(head.children) : [];
  return JSON.stringify({
    cnt: ctxt, cbg: cbg,
    headSpan: !!(kids.length && kids[0].tagName === 'SPAN'),
    spanText: kids.length ? kids[0].textContent : '',
    lastIsBtn: !!(kids.length && kids[kids.length - 1].tagName === 'BUTTON'),
  });
})()"""

JS_GIFBUB = """(async () => {
  await boot();
  const items = Array.from(document.querySelectorAll('.chat-item'));
  const dm = items.find(function (el) {
    return el.textContent.indexOf('{BU}') >= 0;
  });
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  const b = await wait('.msgs .bubble.gif', 10000);
  if (!b) return 'FAIL: sin .bubble.gif';
  const bg = getComputedStyle(b).backgroundColor;
  const meta = b.querySelector('.b-meta');
  const mpos = meta ? getComputedStyle(meta).position : '';
  const mbg = meta ? getComputedStyle(meta).backgroundColor : '';
  const mradius = meta ? parseFloat(getComputedStyle(meta).borderRadius) : 0;
  const acts = b.querySelector('.b-actions');
  if (acts) acts.style.pointerEvents = 'auto';
  const starBtn = b.querySelector(
    '.b-actions button[title="Agregar a favoritos"]');
  const star = starBtn ? starBtn.querySelector('use') : null;
  return JSON.stringify({
    bg: bg, mpos: mpos, mbg: mbg, mradius: mradius,
    starHref: star ? (star.getAttribute('href') || '') : '',
  });
})()"""

JS_PLAYERS = """(async () => {
  await boot();
  const items = Array.from(document.querySelectorAll('.chat-item'));
  const dm = items.find(function (el) {
    return el.textContent.indexOf('{BU}') >= 0;
  });
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  // --- audio adjunto: player propio + <audio> oculto en el DOM
  let t = Date.now();
  let au = null;
  while (Date.now() - t < 15000) {
    au = document.querySelector('.msgs .b-afile');
    if (au) break;
    await sleep(200);
  }
  const auBtn = au ? !!au.querySelector('.au-btn') : false;
  const auAudio = au ? !!au.querySelector('audio') : false;
  const auRate = au ? !!au.querySelector('.au-rate') : false;
  // --- video: controles dentro del video
  t = Date.now();
  let vd = null;
  while (Date.now() - t < 20000) {
    vd = document.querySelector('.msgs .b-video');
    if (vd) break;
    await sleep(200);
  }
  let vInfo = null;
  if (vd) {
    const v = vd.querySelector('video');
    // esperar a que el blob del reproductor esté listo (v-dl)
    let t2 = Date.now();
    while (Date.now() - t2 < 12000) {
      if (v && v.readyState >= 1 && v.videoHeight) break;
      await sleep(200);
    }
    const center = !!vd.querySelector('.v-center');
    const fs = !!vd.querySelector('.v-bar .v-fs');
    const seek = !!vd.querySelector('.v-seek');
    const vmeta = !!vd.querySelector('.v-meta');
    const outer = vd.closest('.bubble');
    /* W62: el .b-meta exterior sigue en el DOM (puede llevar el botón de
       spoiler), pero su hora/palomitas no se duplican: deben estar
       ocultas y vivir sólo dentro del video. */
    let outerMeta = true;
    if (outer) {
      const om = outer.querySelector(':scope > .b-meta');
      if (om) {
        Array.from(om.children).forEach(function (ch) {
          if ((ch.classList.contains('b-time') || ch.classList.contains('tick')) &&
              getComputedStyle(ch).display !== 'none') outerMeta = false;
        });
      }
    }
    // play → a los 1,3 s los controles deben estar ocultos (.vhide)
    vd.style.pointerEvents = 'auto';
    vd.querySelector('.v-center').click();
    await sleep(1300);
    const hide = vd.classList.contains('vhide');
    vd.dispatchEvent(new MouseEvent('mousemove', { bubbles: true }));
    await sleep(150);
    const peek = vd.classList.contains('vhide');
    vInfo = { center: center, fs: fs, seek: seek, vmeta: vmeta,
              outerMeta: outerMeta, hide: hide, peek: peek,
              dur: v ? (v.duration || 0) : 0 };
  }
  return JSON.stringify({ auBtn: auBtn, auAudio: auAudio, auRate: auRate,
                          v: vInfo });
})()"""

# W43: volumen vertical + pantalla completa alterna + ✕ no residual
JS_VOLFS = """(async () => {
  await boot();
  const items = Array.from(document.querySelectorAll('.chat-item'));
  const dm = items.find(function (el) {
    return el.textContent.indexOf('{BU}') >= 0;
  });
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  let vd = null;
  const t = Date.now();
  while (Date.now() - t < 15000) {
    vd = document.querySelector('.msgs .b-video');
    if (vd) break;
    await sleep(200);
  }
  if (!vd) return 'FAIL: sin video';
  const v = vd.querySelector('video');
  let t2 = Date.now();
  while (Date.now() - t2 < 12000) {
    if (v.readyState >= 1 && v.videoHeight) break;
    await sleep(200);
  }
  vd.style.pointerEvents = 'auto';

  /* --- volumen: pop-up VERTICAL por encima del botón --- */
  const volBtn = vd.querySelector('.v-bar button[title="Volumen"]');
  if (!volBtn) return 'FAIL: sin botón de volumen';
  volBtn.click();
  await sleep(350);
  const vp = await wait('.v-vol', 3000);
  if (!vp) return 'FAIL: sin popup de volumen';
  const vcs = getComputedStyle(vp);
  const sl = vp.querySelector('.v-slider');
  const vt = vp.querySelector('.v-vol-vt');
  const slr = sl ? sl.getBoundingClientRect() : null;
  const vtr = vt ? vt.getBoundingClientRect() : null;
  const barR = vd.querySelector('.v-bar').getBoundingClientRect();
  const vpR = vp.getBoundingClientRect();
  const vol = {
    col: vcs.flexDirection === 'column',
    vert: !!(slr && slr.height >= 50 && slr.width <= 20),
    narrow: !!(vtr && vtr.width <= 24),
    above: vpR.bottom <= barR.top + 4,
  };
  const closeBtn = vd.querySelector('.v-bar button[title="Cerrar volumen"]');
  if (closeBtn) { closeBtn.click(); await sleep(350); }
  vol.closed = !document.querySelector('.v-vol');

  /* --- pantalla completa: el botón ENTRA y SALE. En headless FF el
     fullscreen real no se activa: si la entrada real falla, se mockea
     el trio fullscreenElement/requestFullscreen/exitFullscreen para
     probar la LÓGICA del botón (entrada/salida + icono i-collapse). --- */
  const doc = document;
  const fsBtn = vd.querySelector('.v-bar .v-fs');
  if (!fsBtn) return 'FAIL: sin botón fullscreen';
  let useEl = fsBtn.querySelector('use');
  const hrefIn = useEl ? (useEl.getAttribute('href') || '') : '';
  fsBtn.click();
  let entered = false;
  let t3 = Date.now();
  while (Date.now() - t3 < 4000) {
    if (doc.fullscreenElement === vd) { entered = true; break; }
    await sleep(120);
  }
  const real = entered;
  let mockFs = null;
  if (!entered) {
    Object.defineProperty(doc, 'fullscreenElement', {
      configurable: true,
      get: function () { return mockFs; }
    });
    vd.requestFullscreen = function () {
      mockFs = vd;
      doc.dispatchEvent(new Event('fullscreenchange'));
      return Promise.resolve();
    };
    doc.exitFullscreen = function () {
      mockFs = null;
      doc.dispatchEvent(new Event('fullscreenchange'));
      return Promise.resolve();
    };
    fsBtn.click();
    await sleep(300);
    entered = (mockFs === vd);
  }
  await sleep(300);
  useEl = fsBtn.querySelector('use');
  const hrefOut = useEl ? (useEl.getAttribute('href') || '') : '';

  /* el video ajusta a la pantalla: geometría real solo con fullscreen
     real; si no, deben existir las reglas CSS :fullscreen */
  let fit = false;
  if (real) {
    const vr = v.getBoundingClientRect();
    fit = Math.abs(vr.width - window.innerWidth) <= 4
      && Math.abs(vr.height - window.innerHeight) <= 4;
  }
  let ruleFs = false;
  let ruleVid = false;
  try {
    const sheets = Array.from(document.styleSheets);
    for (let i = 0; i < sheets.length; i++) {
      let rules;
      try { rules = sheets[i].cssRules; } catch (e) { continue; }
      for (let j = 0; j < rules.length; j++) {
        const ru = rules[j];
        if (!ru.selectorText) continue;
        const sel = ru.selectorText;
        const txt = ru.cssText || '';
        if (sel === '.b-video:fullscreen' &&
            txt.indexOf('100vw') >= 0 && txt.indexOf('100vh') >= 0) {
          ruleFs = true;
        }
        if (sel.indexOf('.b-video:fullscreen .b-vid') === 0 &&
            txt.indexOf('object-fit') >= 0) ruleVid = true;
      }
    }
  } catch (e) {}
  const ruleFit = ruleFs && ruleVid;

  let exited = false;
  fsBtn.click();                      /* salir (real o mock) */
  t3 = Date.now();
  while (Date.now() - t3 < 4000) {
    if (!doc.fullscreenElement) { exited = true; break; }
    await sleep(120);
  }

  /* --- W43: al ocultarse los controles (.vhide) Vue reescribe el
     class del marco: dl-done NO debe perderse (si se pierde, reaparece
     la ✕ de cancelar de una descarga ya terminada) --- */
  const c = vd.querySelector('.v-center');
  if (c) c.click();                   /* reproducir → vhide a los 1 s */
  await sleep(1500);
  const ov = vd.querySelector('.mf-ov');
  const ovDisp = ov ? getComputedStyle(ov).display : '';
  return JSON.stringify({
    vol: vol, hrefIn: hrefIn, entered: entered, hrefOut: hrefOut,
    fit: fit, ruleFit: ruleFit, real: real, exited: exited,
    hideCls: vd.classList.contains('vhide'),
    dlKept: vd.className.indexOf('dl-done') >= 0,
    ovHidden: ovDisp === 'none',
    playing: !v.paused,
  });
})()"""

JS_FAVS = """(async () => {
  await boot();
  const items = Array.from(document.querySelectorAll('.chat-item'));
  const dm = items.find(function (el) {
    return el.textContent.indexOf('{BU}') >= 0;
  });
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  const b = await wait('.msgs .bubble.gif', 10000);
  if (!b) return 'FAIL: sin .bubble.gif';
  const acts = b.querySelector('.b-actions');
  if (acts) acts.style.pointerEvents = 'auto';
  const btn = b.querySelector('.b-actions button[title="Agregar a favoritos"]');
  if (!btn) return 'FAIL: sin botón ★ del mensaje';
  btn.click();
  await sleep(600);
  const href = btn.querySelector('use').getAttribute('href') || '';
  /* W63: un GIF de la biblioteca ya guardado por nombre también debe
     mostrar la estrella rellena en el mensaje (no sólo por media_id). */
  const libMsg = document.querySelector('.msg[data-mid="{LIBGIFMID}"]');
  const libBtn = libMsg
    ? libMsg.querySelector('.b-actions button[title="Quitar de favoritos"]')
    : null;
  const libMsgUse = libBtn ? libBtn.querySelector('use') : null;
  // pestaña GIFs: sección Favoritos con la miniatura recién marcada
  const eb = document.querySelector('.comp-emo');
  if (!eb) return 'FAIL: sin botón de emojis';
  eb.click();
  const p = await wait('.st-panel', 5000);
  const tabs = Array.from(p.querySelectorAll('.ep-tab'));
  const gifTab = tabs.find(function (t2) { return t2.textContent === 'GIFs'; });
  gifTab.click();
  await sleep(700);
  const body = p.querySelector('.st-body');
  const secs = body
    ? Array.from(body.querySelectorAll('.st-sec')).map(function (s) {
        return s.textContent;
      })
    : [];
  const favWraps = body ? body.querySelectorAll('.st-grid .st-g-wrap').length : 0;
  const mediaFav = body
    ? !!body.querySelector('.st-grid .st-g-wrap img[src^="blob:"], ' +
      '.st-grid .st-g-wrap img[src*="/media/"]')
    : false;
  // ★ de una miniatura de la biblioteca (no marcada aún)
  const libStar = body
    ? body.querySelector('.st-grid .st-fav:not(.on)')
    : null;
  let libOn = false;
  if (libStar) {
    libStar.click();
    await sleep(600);
    libOn = !!body.querySelector('.st-grid .st-fav.on');
  }
  return JSON.stringify({ starHref: href, secs: secs, favWraps: favWraps,
                          libMsgStar: libMsgUse
                            ? (libMsgUse.getAttribute('href') || '') : '',
                          mediaFav: mediaFav, libStar: !!libStar, libOn: libOn });
})()"""


# ------------------------------------------------------------------ API


def make_wav(path, secs=0.4, rate=16000):
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    GT = f"W36-Grupo-{tag}"
    BM = f"msg-de-b-{tag}"
    A = ct.register(a.base, f"w36a{tag}@t.fi", f"w36a{tag}")
    B = ct.register(a.base, f"w36b{tag}@t.fi", f"w36b{tag}")
    BU = B["user"]["username"]
    print(f"· A={A['user']['username']} B={BU} grupo={GT}")

    st, g = ct.dm_between(a.base, A["access"], B["access"],
                          A["user"]["username"], BU)
    if st not in (200, 201):
        raise SystemExit(f"✗ crear dm: {st} {g}")
    dm = g["chat"]["id"]

    st, g2 = ct.http("POST", a.base + "/api/chats/group",
                     {"title": GT, "members": [BU]}, token=A["access"])
    if st not in (200, 201):
        raise SystemExit(f"✗ crear grupo: {st} {g2}")
    grp = g2["chat"]["id"]

    # ============ 1. favoritos de la biblioteca (API) =================
    print("→ paso1 favoritos biblioteca")
    st, r1 = ct.http("POST", a.base + "/api/gifs/favorites",
                     {"name": "fire.gif"}, token=A["access"])
    step("POST favorito biblioteca → 201", st == 201, f"st={st} {r1}")
    st, r2 = ct.http("GET", a.base + "/api/gifs/favorites", token=A["access"])
    names = [f.get("name") for f in r2.get("favorites", [])]
    step("GET favoritos contiene fire.gif",
         st == 200 and "fire.gif" in names, f"st={st} {names}")
    st, _ = ct.http("POST", a.base + "/api/gifs/favorites",
                    {"name": "../../etc.gif"}, token=A["access"])
    step("nombre con traversal → 400", st == 400, f"st={st}")
    st, _ = ct.http("POST", a.base + "/api/gifs/favorites",
                    {"name": "no-existe.gif"}, token=A["access"])
    step("biblioteca inexistente → 404", st == 404, f"st={st}")
    st, _ = ct.http("POST", a.base + "/api/gifs/favorites", token=A["access"])
    step("sin nombre ni media → 400/422", st in (400, 422), f"st={st}")
    st, _ = ct.http("DELETE", a.base + "/api/gifs/favorites",
                    {"name": "fire.gif"}, token=A["access"])
    st, r3 = ct.http("GET", a.base + "/api/gifs/favorites", token=A["access"])
    step("DELETE favorito biblioteca",
         st == 200 and "fire.gif" not in
         [f.get("name") for f in r3.get("favorites", [])], f"st={st}")

    # ============ 2. favoritos de GIFs subidos (API) ==================
    print("→ paso2 favoritos media")
    from PIL import Image
    f1 = Image.new("RGBA", (24, 24), (255, 0, 0, 255))
    f2 = Image.new("RGBA", (24, 24), (0, 255, 0, 255))
    gif = SHOTS / "w36-fav.gif"
    f1.save(gif, "GIF", save_all=True, append_images=[f2],
            duration=200, loop=0)
    upgif = ct.upload(a.base, A["access"], gif)
    st, r4 = ct.http("POST", a.base + "/api/gifs/favorites",
                     {"media_id": upgif["id"]}, token=A["access"])
    step("POST favorito media → 201", st == 201, f"st={st} {r4}")
    st, r5 = ct.http("GET", a.base + "/api/gifs/favorites", token=A["access"])
    mfav = [f for f in r5.get("favorites", []) if f.get("media_id")]
    step("GET favoritos media con URL firmada",
         st == 200 and mfav and "?exp=" in (mfav[0].get("url") or ""),
         f"st={st} {mfav[:1]}")
    st, _ = ct.http("DELETE", a.base + "/api/gifs/favorites",
                    {"media_id": upgif["id"]}, token=A["access"])
    step("DELETE favorito media", st == 200, f"st={st}")

    # ============ 3. admin-delete (API) ===============================
    print("→ paso3 admin borra mensajes ajenos")
    msgB = ct.send(a.base, B["access"], grp,
                   {"body": BM, "client_msg_id": str(uuid.uuid4())})
    st, r6 = ct.http("DELETE",
                     f"{a.base}/api/chats/{grp}/messages/{msgB['id']}",
                     token=A["access"])
    step("owner A borra el mensaje de B → 200", st == 200, f"st={st} {r6}")
    st, r7 = ct.http("GET", f"{a.base}/api/chats/{grp}/messages?limit=50",
                     token=A["access"])
    step("el mensaje borrado ya no está",
         st == 200 and all(m["id"] != msgB["id"] for m in r7.get("messages", [])),
         f"st={st}")
    msgA = ct.send(a.base, A["access"], grp,
                   {"body": f"msg-de-a-{tag}", "client_msg_id": str(uuid.uuid4())})
    st, _ = ct.http("DELETE",
                    f"{a.base}/api/chats/{grp}/messages/{msgA['id']}",
                    token=B["access"])
    step("miembro B no puede borrar el de A → 403", st == 403, f"st={st}")

    # ============ siembra de mensajes multimedia (DM) =================
    print("→ siembra multimedia en la DM")
    ct.send(a.base, A["access"], dm,
            {"kind": "image", "body": "", "media_id": upgif["id"],
             "client_msg_id": str(uuid.uuid4())})
    # W63: GIF de la biblioteca enviado como imagen. Al guardarlo por
    # nombre, la estrella del mensaje debe salir rellena aunque su
    # media_id no coincida con el favorito.
    uplib = ct.upload(a.base, A["access"],
                      ROOT / "server/web/gifs/fire.gif")
    libgif_msg = ct.send(a.base, A["access"], dm,
                         {"kind": "image", "body": "",
                          "media_id": uplib["id"],
                          "client_msg_id": str(uuid.uuid4())})
    st, favlib = ct.http("POST", a.base + "/api/gifs/favorites",
                         {"name": "fire.gif"}, token=A["access"])
    if st != 201:
        raise SystemExit(f"✗ favorito fire.gif: {st} {favlib}")
    wav = SHOTS / "w36-nota.wav"
    make_wav(wav)
    upwav = ct.upload(a.base, A["access"], wav)
    ct.send(a.base, A["access"], dm,
            {"kind": "file", "body": "", "media_id": upwav["id"],
             "client_msg_id": str(uuid.uuid4())})
    mp4 = SHOTS / "w36-clip.mp4"
    upvid = None
    if make_mp4(mp4):
        upvid = ct.upload(a.base, A["access"], mp4)
        ct.send(a.base, A["access"], dm,
                {"kind": "file", "body": "", "media_id": upvid["id"],
                 "client_msg_id": str(uuid.uuid4())})
    else:
        print("  · ffmpeg no generó el mp4 (se omite el paso del video)")

    # fijar un mensaje de B en el grupo (paso 9)
    msgB2 = ct.send(a.base, B["access"], grp,
                    {"body": f"fijado-{tag}", "client_msg_id": str(uuid.uuid4())})
    st, _ = ct.http("POST",
                    f"{a.base}/api/chats/{grp}/messages/{msgB2['id']}/pin",
                    {"pin": True}, token=A["access"])
    if st not in (200, 201):
        raise SystemExit(f"✗ fijar mensaje: {st}")

    # ============ sesión de A en el navegador =========================
    # W65: limpiar SW/caché y cualquier sesión anterior ANTES de inyectar.
    # Si queda la sesión de otro lote (usuario ya borrado), el arranque
    # puede recibir un 401 tardío y borrar la sesión recién inyectada.
    shot(a.base + "/", SHOTS / "w36-0-prep.png",
         js="(async()=>{try{const rs=await navigator.serviceWorker"
            ".getRegistrations();for(const r of rs)await r.unregister();}"
            "catch(e){};try{const ks=await caches.keys();for(const k of ks)"
            "await caches.delete(k);}catch(e){};"
            "localStorage.removeItem('fm.session');return 'ok';})()",
         wait=350)
    ok, res, log = shot(a.base + "/", SHOTS / "w36-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    # ============ 4. desconectado en el pie ===========================
    print("→ paso4 estado Desconectado")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-1-status.png", js=js_t(JS_STATUS))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("pie muestra 'Desconectado' con WS caído",
         ok and r.get("off") == "Desconectado", f"res={res!r}")
    step("con WS 'on' no dice Desconectado",
         ok and "Desconectado" not in (r.get("on") or ""), f"res={res!r}")

    # ============ 5. dot doble en el modal de perfil ==================
    print("→ paso5 pelotica doble en Tu perfil")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-2-meprof.png", js=js_t(JS_MEPROF))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("la pelotica del modal mide 22px",
         ok and r.get("dotW") == "22px" and r.get("dotH") == "22px",
         f"res={res!r}")

    # ============ 6. i-userplus en el chat-head =======================
    print("→ paso6 icono añadir miembros")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-3-head.png",
                        js=js_t(JS_GHEAD, GT=GT))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("botón 'Agregar miembros' con icono i-userplus",
         ok and r.get("btn") and r.get("icon") == "#i-userplus", f"res={res!r}")

    # ============ 7. toggle del menú de la lista ======================
    print("→ paso7 toggle de menú")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-4-ctx.png", js=js_t(JS_CTX))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("segundo clic en ⋯ cierra el menú", ok and r.get("open") is False,
         f"res={res!r}")

    # ============ 8. panel fijo + pageflip + stickers ================
    print("→ paso8 panel del compositor")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-5-panel.png", js=js_t(JS_PANEL, BU=BU))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("altura fija en las 3 pestañas",
         ok and r.get("hEmo") and r.get("hEmo") == r.get("hGif") == r.get("hSt"),
         f"res={res!r}")
    step("animación de apertura del panel (fundido)",
         ok and r.get("anim") == "epfadeIn", f"res={res!r}")
    step("stickers con Twemoji <img> (sin texto nativo)",
         ok and (r.get("stImg") or 0) >= 8 and not r.get("stTxt"),
         f"res={res!r}")

    # ============ 9. menú admin + modal de fijados ====================
    print("→ paso9 admin-delete en UI + fijados")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-6-admenu.png",
                        js=js_t(JS_ADMENU, GT=GT, BM=fijado_txt(tag)))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("menú de mensaje ajeno incluye 'Eliminar mensaje' (owner)",
         ok and "Eliminar mensaje" in (r.get("texts") or []), f"res={res!r}")

    ok, res, log = shot(a.base + "/", SHOTS / "w36-7-pins.png",
                        js=js_t(JS_PINS, GT=GT))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("conteo de la fila: texto '(1)' sin fondo",
         ok and r.get("cnt") == "(1)" and r.get("cbg") == "rgba(0, 0, 0, 0)",
         f"res={res!r}")
    step("modal: título+(1) juntos a la izquierda y cerrar al extremo",
         ok and r.get("headSpan") and "(1)" in (r.get("spanText") or "")
         and r.get("lastIsBtn"), f"res={res!r}")

    # ============ 10. burbuja GIF transparente ========================
    print("→ paso10 GIF dentro del mensaje")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-8-gifbub.png",
                        js=js_t(JS_GIFBUB, BU=BU))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    # W62/W65: el GIF conserva la burbuja transparente, pero la
    # hora/palomitas lleva una pastilla oscura legible debajo.
    step("GIF transparente con pastilla oscura legible de hora/palomitas",
         ok and r.get("bg") == "rgba(0, 0, 0, 0)"
         and r.get("mpos") == "static"
         and r.get("mbg") == "rgba(0, 0, 0, 0.52)"
         and (r.get("mradius") or 0) >= 10,
         f"res={res!r}")
    step("barra flotante con ★ (i-star)", ok and r.get("starHref") == "#i-star",
         f"res={res!r}")

    # ============ 11. reproductores propios ===========================
    print("→ paso11 reproductores propios")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-9-players.png",
                        js=js_t(JS_PLAYERS, BU=BU), timeout=200)
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("audio: player propio con <audio> oculto",
         ok and r.get("auBtn") and r.get("auAudio") and r.get("auRate"),
         f"res={res!r}")
    if upvid:
        v = r.get("v") or {}
        step("video: controles dentro (centro, fullscreen, seek, meta)",
             ok and v.get("center") and v.get("fs") and v.get("seek")
             and v.get("vmeta") and v.get("dur", 0) > 0.2,
             f"res={res!r}")
        step("hora/palomitas viven DENTRO del video (sin duplicar fuera)",
             ok and v.get("outerMeta") is True, f"res={res!r}")
        step("controles ocultos a los 1 s y reaparecen al mover",
             ok and v.get("hide") is True and v.get("peek") is False,
             f"res={res!r}")

        # ============ 11b. W43: volumen vertical + fullscreen ======
        print("→ paso11b volumen vertical + pantalla completa (W43)")
        ok, res, log = shot(a.base + "/", SHOTS / "w36-9b-fs.png",
                            js=js_t(JS_VOLFS, BU=BU), timeout=200)
        r = {}
        try:
            r = json.loads(res)
        except Exception:
            pass
        vol = r.get("vol") or {}
        step("volumen: pop-up vertical por encima del botón (no en la barra)",
             ok and vol.get("col") and vol.get("vert") and vol.get("narrow")
             and vol.get("above") and vol.get("closed"), f"res={res!r}")
        step("fullscreen: el botón ENTRA y SALE (alterna, i-collapse)",
             ok and r.get("hrefIn") == "#i-expand"
             and r.get("entered") is True and r.get("exited") is True
             and r.get("hrefOut") == "#i-collapse",
             f"real={r.get('real')} res={res!r}")
        step("en pantalla completa el video se ajusta a la pantalla",
             r.get("fit") is True or r.get("ruleFit") is True, f"res={res!r}")
        step("al ocultarse los controles la ✕ de descarga NO reaparece",
             ok and r.get("hideCls") is True and r.get("dlKept") is True
             and r.get("ovHidden") is True and r.get("playing") is True,
             f"res={res!r}")

    # ============ 12. favoritos en la UI ==============================
    print("→ paso12 favoritos en la UI")
    ok, res, log = shot(a.base + "/", SHOTS / "w36-10-favs.png",
                        js=js_t(JS_FAVS, BU=BU,
                                LIBGIFMID=str(libgif_msg["id"])))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("★ del mensaje se llena (#i-star-fill)",
         ok and r.get("starHref") == "#i-star-fill", f"res={res!r}")
    step("★ del GIF de biblioteca ya guardado sale rellena",
         ok and r.get("libMsgStar") == "#i-star-fill", f"res={res!r}")
    secs = r.get("secs") or []
    step("pestaña GIFs con sección Favoritos y la miniatura del mensaje",
         ok and secs and "Favoritos" in secs[0] and r.get("mediaFav"),
         f"res={res!r}")
    step("★ de la biblioteca marca la miniatura",
         ok and r.get("libStar") and r.get("libOn"), f"res={res!r}")

    print(f"\nW36: {_pass[0]} bien, {_fail[0]} mal")
    return 1 if _fail[0] else 0


def fijado_txt(tag):
    """Texto del mensaje fijado (se siembra en el paso 9)."""
    return f"fijado-{tag}"


if __name__ == "__main__":
    sys.exit(main())
