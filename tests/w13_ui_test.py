#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W13 UI — prueba REAL de la interfaz en Firefox headless (Mypal/78).

Cubre lo que el usuario reportó en producción y lo que las suites de API
no ejercitan en navegador:
  1. Punto de presencia: desconectado = gris (y grupo = sin punto).
  2. Cambio de estado invisible → en línea en el modal de perfil
     (el punto propio debe quedar verde, no gris).
  2b. W26: al reconectar, el server manda el snapshot de presencia de los
     contactos y corrige la cabecera si se perdió un evento de desconexión.
  3. Nota de voz grabada en el navegador (micrófono falso) con onda real
     (peaks) y duración, y reproducción: el tiempo avanza y la onda se llena.
  4. Nota de voz "vieja" (sin peaks/dur, como las de antes de W13):
     al reproducir se resuelve la duración (no más "0:00" eterno).
  5. Selector de emoji completo: abrir, buscar "pizza", insertar y enviar.
  6. Buscar en el chat: "cafe" encuentra "café" (plegado de acentos) y
     el clic en el resultado hace flash en el mensaje.
  7. Fijar y silenciar chat desde el menú contextual (iconos en la lista).
  8. Reenviar un mensaje a un grupo (etiqueta "Reenviado").

Requiere el server local de pruebas en :8899 (mismo ciclo que las demás
suites) y borra todo lo sembrado al terminar (cleanup_db).
"""
import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "scripts" / "shot.py"
DB = ROOT / "server" / "data" / "foxmsg.db"
PY = ROOT / "server" / ".venv" / "bin" / "python"
SHOTS = Path("/tmp/opencode")
MAIL_LOG = ROOT / "server" / "data" / "mail.log"


# ------------------------------------------------------------ HTTP (urllib)

def http(method, url, data=None, token=None, raw=None, ctype=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if raw is not None:
        body = raw
        headers["Content-Type"] = ctype
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8")
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def wait_code(email, purpose="verify", timeout=8.0):
    pat = re.compile(rf"\| {re.escape(email)} \| {purpose} \| (\d+)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if MAIL_LOG.is_file():
            matches = pat.findall(MAIL_LOG.read_text(encoding="utf-8"))
            if matches:
                return matches[-1]
        time.sleep(0.3)
    return None


def register(base, email, username, password="foxpass12345"):
    st, res = http("POST", base + "/api/auth/register",
                   {"email": email, "username": username, "password": password})
    if st != 201:
        raise SystemExit(f"✗ register {username}: {st} {res}")
    pending = res["tokens"]["access"]
    code = wait_code(email)
    if not code:
        raise SystemExit(f"✗ sin código de verificación para {email}")
    st, res = http("POST", base + "/api/auth/verify", {"code": code}, token=pending)
    if st != 200:
        raise SystemExit(f"✗ verify {username}: {st} {res}")
    return {"user": res["user"], "access": res["tokens"]["access"],
            "refresh": res["tokens"]["refresh"]}


def send(base, tok, chat_id, payload):
    for _ in range(5):
        st, res = http("POST", f"{base}/api/chats/{chat_id}/messages", payload, token=tok)
        if st == 429:
            wait = float((res.get("detail") or {}).get("retry_after") or 1)
            print(f"  · 429 rate limit, espero {wait:g}s y reintento…")
            time.sleep(min(wait, 10) + 0.1)
            continue
        if st != 201:
            raise SystemExit(f"✗ send: {st} {res}")
        return res["message"]
    raise SystemExit("✗ send: 429 persistente tras reintentos")


# ------------------------------------------------------------ orquestación

def run_shot(url, out, js=None, ev=None, wait=700, timeout=180, tap=False):
    cmd = [str(PY), str(SHOT), url, str(out), "--wait", str(wait)]
    if js:
        cmd += ["--js", js]
    if tap:
        cmd += ["--tap"]
    if ev:
        cmd += ["--eval", ev]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    eval_val = js_res = None
    for line in r.stdout.splitlines():
        if line.startswith("EVAL: "):
            eval_val = line[len("EVAL: "):].strip().strip('"')
        elif line.startswith("JSRES: "):
            js_res = line[len("JSRES: "):].strip().strip('"')
    ok = r.returncode == 0 and "SHOT:" in r.stdout
    return ok, js_res, eval_val, (r.stdout + r.stderr)


def step(name, url, out, js=None, ev=None, tap=False, expect_prefix="OK",
         timeout=180):
    ok, js_res, eval_val, log = run_shot(url, out, js=js, ev=ev, tap=tap,
                                         wait=900, timeout=timeout)
    final = str(eval_val if ev else js_res or "")
    extra = f" | prep: {js_res}" if (ev and js_res) else ""
    print(f"{name}: {final or '(sin resultado)'}{extra}")
    if not ok or not final.startswith(expect_prefix):
        print(log[-1800:])
        raise SystemExit(f"✗ {name}")
    return final


# ------------------------------------------------------------ limpieza

def cleanup_db():
    """Borra TODO lo sembrado (usuarios de prueba, chats, media...)."""
    media_dir = ROOT / "server" / "data" / "media"
    try:
        con = sqlite3.connect(str(DB), timeout=10)
        rows = con.execute("SELECT path FROM media").fetchall()
        for (p,) in rows:
            try:
                (media_dir / p).unlink(missing_ok=True)
            except Exception:
                pass
        for table in ("reactions", "messages", "chat_members", "chats",
                      "media", "email_codes", "users"):
            con.execute(f"DELETE FROM {table}")
        con.commit()
        con.close()
        print("→ base local limpiada")
        return True
    except Exception as e:
        print(f"WARN: cleanup: {e}")
        return False


def backdate_last_seen(username, seconds=3600):
    """Deja a B 'desconectado de verdad' (last_seen viejo → punto gris)."""
    con = sqlite3.connect(str(DB), timeout=10)
    con.execute("UPDATE users SET last_seen = ? WHERE username = ?",
                (int(time.time()) - seconds, username))
    con.commit()
    con.close()


# ------------------------------------------------------------ JS de la UI

JS_WAIT_HELPERS = """const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (sel, ms = 12000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(80);
    }
    return null;
  };
  const openChat = async (name) => {
    const item = await wait('.chat-list .chat-item');
    if (!item) return null;
    let el = null;
    const t = Date.now();
    while (Date.now() - t < 8000) {
      el = Array.from(document.querySelectorAll('.chat-item'))
        .find(i => i.textContent.indexOf(name) !== -1);
      if (el) break;
      await sleep(200);
    }
    if (el) el.click();
    return el;
  };"""

JS_DOTS = """(async () => {
  %s
  await wait('.chat-list .chat-item');
  const t0 = Date.now();
  while (Date.now() - t0 < 15000 && __fm.store.ws !== 'on') await sleep(150);
  await sleep(800);
  const it = Array.from(document.querySelectorAll('.chat-item'))
    .find(i => i.textContent.indexOf('BUSER') !== -1);
  if (!it) return 'FAIL: sin chat de B en la lista';
  const dotB = it.querySelector('.av-wrap');
  const clsB = dotB ? dotB.className : '(sin punto)';
  const grp = Array.from(document.querySelectorAll('.chat-item'))
    .find(i => i.textContent.indexOf('GRPNAME') !== -1);
  const dotG = grp ? grp.querySelector('.av-wrap') : null;
  const clsG = dotG ? dotG.className : '(sin grupo)';
  const self = document.querySelector('.user-panel .av-wrap');
  const clsS = self ? self.className : '(sin punto)';
  const okB = !!(dotB && dotB.classList.contains('on') &&
                 dotB.classList.contains('st-off'));
  const okS = !!(self && self.classList.contains('on') &&
                 !self.classList.contains('st-off'));
  const okG = !dotG || !dotG.classList.contains('on');
  const ok = okB && okS && okG;
  return (ok ? 'OK' : 'FAIL') + ' desconectado=[' + clsB + '] propio=[' +
    clsS + '] grupo=[' + clsG + '] ws=' + __fm.store.ws;
})()"""

JS_STATUS_INV = """(async () => {
  %s
  await wait('.chat-list .chat-item');
  /* W27b: el formulario vive en el modal Editar perfil */
  __fm.store.meEditOpen = true;
  if (!await wait('.mp-presets .ap-chip', 8000))
    return 'FAIL: no abrió el modal de perfil';
  const inv = Array.from(document.querySelectorAll('.mp-presets .ap-chip'))
    .find(c => c.textContent.trim() === 'Invisible');
  if (!inv) return 'FAIL: sin chip Invisible';
  inv.click();
  await sleep(150);
  const save = Array.from(document.querySelectorAll('.m-foot button.btn'))
    .find(b => !b.classList.contains('btn-ghost'));
  if (!save) return 'FAIL: sin botón Guardar';
  save.click();
  const t0 = Date.now();
  while (Date.now() - t0 < 9000 && document.querySelector('.mp-presets'))
    await sleep(150);
  if (document.querySelector('.mp-presets'))
    return 'FAIL: el modal no cerró tras guardar';
  __fm.store.meProfileOpen = false;   /* la vista no debe tapar la app */
  await sleep(500);
  const self = document.querySelector('.user-panel .av-wrap');
  const cls = self ? self.className : '(sin punto)';
  const ok = !!(self && self.classList.contains('on') &&
                self.classList.contains('st-off'));
  return (ok ? 'OK' : 'FAIL') + ' invisible → punto propio=[' + cls +
    '] preset=' + (__fm.store.user && __fm.store.user.status_preset);
})()"""

JS_STATUS_ON = """(async () => {
  %s
  await wait('.chat-list .chat-item');
  /* W27b: el formulario vive en el modal Editar perfil */
  __fm.store.meEditOpen = true;
  if (!await wait('.mp-presets .ap-chip', 8000))
    return 'FAIL: no abrió el modal de perfil';
  const on = Array.from(document.querySelectorAll('.mp-presets .ap-chip'))
    .find(c => c.textContent.trim() === 'En línea');
  if (!on) return 'FAIL: sin chip En línea';
  on.click();
  await sleep(150);
  const save = Array.from(document.querySelectorAll('.m-foot button.btn'))
    .find(b => !b.classList.contains('btn-ghost'));
  save.click();
  const t0 = Date.now();
  while (Date.now() - t0 < 9000 && document.querySelector('.mp-presets'))
    await sleep(150);
  if (document.querySelector('.mp-presets'))
    return 'FAIL: el modal no cerró tras guardar';
  __fm.store.meProfileOpen = false;   /* la vista no debe tapar la app */
  await sleep(500);
  const self = document.querySelector('.user-panel .av-wrap');
  const cls = self ? self.className : '(sin punto)';
  const ok = !!(self && self.classList.contains('on') &&
                !self.classList.contains('st-off'));
  return (ok ? 'OK' : 'FAIL') + ' en línea → punto propio=[' + cls +
    '] preset=' + (__fm.store.user && __fm.store.user.status_preset);
})()"""

# Fase 1 (js): graba la nota y deja en window.__tap el botón de play
# (shot.py lo clickea con un puntero REAL: en headless play() sin gesto
# trusted queda bloqueado aunque la política diga otra cosa).
JS_VOICE_PREP = """(async () => {
  %s
  if (!await openChat('BUSER')) return 'FAIL: sin chat de B';
  await wait('.composer-input', 10000);
  const mic = await wait('.comp-mic', 8000);
  if (!mic) return 'FAIL: sin botón de micrófono';
  mic.click();
  if (!await wait('.rec-bar', 6000)) return 'FAIL: no empezó a grabar';
  await sleep(2600);
  // W24: la onda al grabar debe ser la REAL del micrófono (no la falsa CSS)
  const wv = document.querySelector('.rec-bar .rec-wave');
  if (!wv) return 'FAIL: sin .rec-wave en la grabación';
  if (!wv.classList.contains('live'))
    return 'FAIL: la onda no está en vivo (analyser no arrancó)';
  const bars = wv.querySelectorAll('i');
  if (bars.length !== 22) return 'FAIL: barras de onda=' + bars.length;
  if (getComputedStyle(bars[0]).animationName !== 'none')
    return 'FAIL: sigue la onda falsa CSS (' + getComputedStyle(bars[0]).animationName + ')';
  const vals = [];
  for (let i = 0; i < bars.length; i++) {
    const m = /scaleY\\(([\\d.]+)\\)/.exec(bars[i].style.transform || '');
    if (!m) return 'FAIL: barra ' + i + ' sin transform de datos';
    vals.push(parseFloat(m[1]));
  }
  // el stream falso del navegador es constante: mismas barras = mismos picos
  const hi = Math.max.apply(null, vals), lo = Math.min.apply(null, vals);
  window.__wave = 'lvl=' + vals[0] + ' rango=' + (hi - lo).toFixed(2);
  const snd = document.querySelector('.rec-send');
  if (!snd) return 'FAIL: sin botón de envío de voz';
  snd.click();
  // esperar el mensaje real (con media + peaks + dur del servidor)
  const cid = __fm.store.activeChatId;
  let msg = null;
  const t0 = Date.now();
  while (Date.now() - t0 < 30000) {
    const arr = __fm.store.msgs[cid] || [];
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i].kind === 'voice' && arr[i].media) { msg = arr[i]; break; }
    }
    if (msg && msg.id && msg.peaks && msg.dur) break;
    msg = null;
    await sleep(250);
  }
  if (!msg) return 'FAIL: el mensaje de voz no llegó';
  if (!msg.peaks || !msg.peaks.length)
    return 'FAIL: la nota nueva no trae peaks (onda falsa)';
  if (!msg.dur || msg.dur < 1)
    return 'FAIL: la nota nueva no trae dur (' + msg.dur + ')';
  if (!await wait('.msgs .b-player', 10000)) return 'FAIL: sin reproductor';
  await sleep(700);
  const ps = document.querySelectorAll('.msgs .b-player');
  const first = ps[ps.length - 1];
  window.__t0 = first.querySelector('.au-time').textContent.trim();
  window.__peaks = msg.peaks.length;
  window.__dur = msg.dur;
  const r = first.querySelector('.au-btn').getBoundingClientRect();
  window.__tap = { x: Math.round(r.left + r.width / 2),
                   y: Math.round(r.top + r.height / 2) };
  return 'OK prep peaks=' + msg.peaks.length + ' dur=' + msg.dur +
    ' onda(' + window.__wave + ')' +
    ' time0=[' + window.__t0 + '] tap=' + window.__tap.x + ',' + window.__tap.y;
})()"""

JS_VOICE_EVAL = """(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  await sleep(2200);
  const ps = document.querySelectorAll('.msgs .b-player');
  if (!ps.length) return 'FAIL: desapareció el reproductor';
  const pl = ps[ps.length - 1];
  const time1 = pl.querySelector('.au-time').textContent.trim();
  const onBars = pl.querySelectorAll('.wave i.on').length;
  const totalBars = pl.querySelectorAll('.wave i').length;
  const audio = pl.querySelector('.b-audio');
  const cur = audio ? +audio.currentTime.toFixed(2) : -1;
  try { pl.querySelector('.au-btn').click(); } catch (e) {}
  const t0 = window.__t0 || '';
  const totalOk = !/\\/\\s*0:00\\s*$/.test(t0);
  const elapsed = !/^0:00\\s/.test(time1);
  const ok = totalOk && elapsed && onBars > 1;
  return (ok ? 'OK' : 'FAIL') + ' grabada time0=[' + t0 + '] time1=[' +
    time1 + '] onda=' + onBars + '/' + totalBars + ' cur=' + cur +
    ' peaks=' + window.__peaks + ' dur=' + window.__dur;
})()"""

# Fase 1 (js): nota VIEJA (sin peaks/dur, como las pre-W13): deja el
# clic listo sobre su play.
JS_OLD_PREP = """(async () => {
  %s
  if (!await openChat('BUSER')) return 'FAIL: sin chat de B';
  if (!await wait('.msgs .b-player', 12000)) return 'FAIL: sin reproductor';
  await sleep(900);
  const ps = document.querySelectorAll('.msgs .b-player');
  const first = ps[ps.length - 1];
  window.__t0 = first.querySelector('.au-time').textContent.trim();
  const r = first.querySelector('.au-btn').getBoundingClientRect();
  window.__tap = { x: Math.round(r.left + r.width / 2),
                   y: Math.round(r.top + r.height / 2) };
  return 'OK prep vieja time0=[' + window.__t0 + '] tap=' +
    window.__tap.x + ',' + window.__tap.y;
})()"""

JS_OLD_EVAL = """(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let time1 = window.__t0 || '', onBars = 0, totalBars = 0, cur = -1;
  let resolved = false, elapsed = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 16000) {
    await sleep(350);
    const ps = document.querySelectorAll('.msgs .b-player');
    if (!ps.length) continue;
    const q = ps[ps.length - 1];
    time1 = q.querySelector('.au-time').textContent.trim();
    onBars = q.querySelectorAll('.wave i.on').length;
    totalBars = q.querySelectorAll('.wave i').length;
    const a = q.querySelector('.b-audio');
    if (a) cur = +a.currentTime.toFixed(2);
    if (!/\\/\\s*0:00\\s*$/.test(time1)) resolved = true;
    if (/^0:0[1-9]/.test(time1) || /^0:[1-5][0-9]/.test(time1) ||
        /^[1-9]:/.test(time1)) elapsed = true;
    if (resolved && elapsed) break;
  }
  const ok = resolved && elapsed;
  return (ok ? 'OK' : 'FAIL') + ' vieja time0=[' + (window.__t0 || '') +
    '] → time1=[' + time1 + '] onda=' + onBars + '/' + totalBars +
    ' cur=' + cur + ' durResuelta=' + resolved + ' avanza=' + elapsed;
})()"""

JS_EMOJI = """(async () => {
  %s
  if (!await openChat('BUSER')) return 'FAIL: sin chat de B';
  await wait('.composer-input', 10000);
  const btn = await wait('.comp-emo', 8000);
  if (!btn) return 'FAIL: sin botón de emoji';
  btn.click();
  if (!await wait('.emo-picker', 6000)) return 'FAIL: no abrió el picker';
  const inp = document.querySelector('.ep-search input');
  if (!inp) return 'FAIL: sin búsqueda en el picker';
  inp.value = 'pizza';
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(450);
  const first = document.querySelector('.ep-grid .ep-e');
  if (!first) return 'FAIL: "pizza" no encontró emoji';
  /* W29b: el emoji del picker es un <img>; el Unicode va en el alt */
  const im0 = first.querySelector('img.emo');
  const emo = im0 ? im0.getAttribute('alt') : first.textContent;
  first.click();
  await sleep(300);
  const ta = document.querySelector('.composer-input');
  if (ta.value.indexOf(emo) === -1)
    return 'FAIL: no insertó el emoji en el composer (' + ta.value + ')';
  document.body.click();
  await sleep(250);
  const sendBtn = document.querySelector('.comp-row .send-btn');
  if (!sendBtn || sendBtn.disabled) return 'FAIL: send deshabilitado';
  sendBtn.click();
  let okMsg = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 12000) {
    const arr = __fm.store.msgs[__fm.store.activeChatId] || [];
    const last = arr[arr.length - 1];
    if (last && last.body === emo) { okMsg = true; break; }
    await sleep(250);
  }
  return (okMsg ? 'OK' : 'FAIL') + ' emoji=' + emo +
    ' picker=abierto búsqueda=ok insertado=ok enviado=' + okMsg;
})()"""

JS_SEARCH = """(async () => {
  %s
  if (!await openChat('BUSER')) return 'FAIL: sin chat de B';
  await wait('.msgs .msg', 10000);
  const btn = document.querySelector('.chat-head button[title="Buscar en el chat"]');
  if (!btn) return 'FAIL: sin botón de buscar en el chat';
  btn.click();
  /* W37b: el buscador es un MODAL (.search-modal), no el .search-panel */
  if (!await wait('.search-modal', 6000)) return 'FAIL: no abrió el buscador';
  const inp = document.querySelector('.search-modal .search-pill input');
  if (!inp) return 'FAIL: sin input de búsqueda';
  inp.value = 'cafe';
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  let n = 0;
  const t0 = Date.now();
  while (Date.now() - t0 < 10000) {
    n = document.querySelectorAll('.sp-res').length;
    if (n > 0) break;
    await sleep(300);
  }
  if (!n) return 'FAIL: "cafe" no encontró "café" (sin plegado)';
  document.querySelector('.sp-res').click();
  await sleep(900);
  const flash = document.querySelector('.msg.flash');
  return (flash ? 'OK' : 'FAIL') + ' resultados=' + n + ' flash=' + !!flash;
})()"""

JS_CTX = """(async () => {
  %s
  /* instrumentación: línea de tiempo de fetch y errores */
  window.__t0 = Date.now();
  window.__net = [];
  const of = window.fetch;
  window.fetch = function (u, o) {
    const m = (o && o.method) || 'GET';
    window.__net.push('→' + m + ' ' + u + '@' +
      (Date.now() - window.__t0));
    return of.apply(window, arguments).then(function (res) {
      window.__net.push('←' + res.status + ' ' + u + '@' +
        (Date.now() - window.__t0));
      return res;
    });
  };
  window.__errs = [];
  window.addEventListener('unhandledrejection', function (e) {
    window.__errs.push('REJ ' + ((e.reason && e.reason.message) || e.reason));
  });
  const diag = function (msg) {
    if (window.__obs) clearInterval(window.__obs);
    const c = (__fm.store.chats || []).find(x =>
      x.title && x.title.username === 'BUSER');
    return 'FAIL: ' + msg + ' | store=' + (c
      ? 'pinned=' + !!c.pinned + ' muted=' + !!c.muted : 'sin chat') +
      ' net=[' + window.__net.join('; ') +
      '] errs=[' + window.__errs.join('; ') + ']';
  };
  /* espera activa: aparece el icono dado o se agota el plazo */
  const hasIcon = function (sel) {
    const el = Array.from(document.querySelectorAll('.chat-item'))
      .find(i => i.textContent.indexOf('BUSER') !== -1);
    return !!(el && el.querySelector(sel));
  };
  const waitIcon = async function (sel, ms) {
    const t = Date.now();
    while (Date.now() - t < ms) {
      if (hasIcon(sel)) return true;
      await sleep(200);
    }
    return hasIcon(sel);
  };
  await wait('.chat-list .chat-item');
  /* observar reemplazos del array store.chats con timestamp */
  let lastArr = __fm.store.chats;
  window.__obs = setInterval(function () {
    if (__fm.store.chats !== lastArr) {
      window.__net.push('CHATS-REEMPLAZADA@' +
        (Date.now() - window.__t0));
      lastArr = __fm.store.chats;
    }
  }, 25);
  /* objeto ANTES del click: si queda true pero el store dice false → huérfano */
  const orig = (__fm.store.chats || []).find(c => c.title &&
    c.title.username === 'BUSER');
  let it = Array.from(document.querySelectorAll('.chat-item'))
    .find(i => i.textContent.indexOf('BUSER') !== -1);
  if (!it) return 'FAIL: sin chat de B';
  let r = it.getBoundingClientRect();
  it.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true,
    cancelable: true, clientX: r.left + 40, clientY: r.top + 20 }));
  if (!await wait('.ctx-menu', 5000)) return 'FAIL: sin menú contextual';
  const pinItem = Array.from(document.querySelectorAll('.ctx-item'))
    .find(b => b.textContent.trim() === 'Fijar chat');
  if (!pinItem) return 'FAIL: sin opción "Fijar chat"';
  const tClick = Date.now() - window.__t0;
  window.__net.push('CLICK@+' + tClick + 'ms');
  pinItem.click();
  if (!await waitIcon('.ci-icons use[href="#i-pin"]', 6000)) {
    const d = diag('no apareció el icono de fijado');
    clearInterval(window.__obs);
    return d + ' origPinned=' + !!orig.pinned +
      ' nCopias=' + (__fm.store.chats || []).filter(c => c.id === orig.id).length;
  }
  it = Array.from(document.querySelectorAll('.chat-item'))
    .find(i => i.textContent.indexOf('BUSER') !== -1);
  r = it.getBoundingClientRect();
  it.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true,
    cancelable: true, clientX: r.left + 40, clientY: r.top + 20 }));
  if (!await wait('.ctx-menu', 5000)) return diag('menú no reabrió');
  const muteItem = Array.from(document.querySelectorAll('.ctx-item'))
    .find(b => b.textContent.trim() === 'Silenciar notificaciones');
  if (!muteItem) return 'FAIL: sin opción de silenciar';
  muteItem.click();
  if (!await waitIcon('.ci-icons use[href="#i-bell-off"]', 6000))
    return diag('no apareció el icono de silenciado');
  const storeChat = (__fm.store.chats || []).find(c =>
    c.title && c.title.username === 'BUSER');
  const st = storeChat ? ('pinned=' + !!storeChat.pinned + ' muted=' +
    !!storeChat.muted) : 'chat no encontrado';
  if (window.__obs) clearInterval(window.__obs);
  return 'OK iconoFijado=ok iconoSilenciado=ok ' + st +
    ' net=[' + window.__net.join('; ') + ']';
})()"""

JS_FWD = """(async () => {
  %s
  if (!await openChat('BUSER')) return 'FAIL: sin chat de B';
  await wait('.msgs .msg', 10000);
  let target = null;
  const t0 = Date.now();
  while (Date.now() - t0 < 9000 && !target) {
    target = Array.from(document.querySelectorAll('.msgs .msg'))
      .find(m => m.textContent.indexOf('palabra clave') !== -1);
    if (!target) await sleep(400);
  }
  if (!target) return 'FAIL: sin mensaje destino';
  const r = target.getBoundingClientRect();
  target.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true,
    cancelable: true, clientX: r.left + 30, clientY: r.top + 12 }));
  await sleep(500);
  const fwdItem = Array.from(document.querySelectorAll('.ctx-item'))
    .find(b => b.textContent.trim() === 'Reenviar…');
  if (!fwdItem) return 'FAIL: sin opción "Reenviar…"';
  fwdItem.click();
  if (!await wait('.modal.fwd', 6000)) return 'FAIL: sin modal de reenvío';
  const gi = Array.from(document.querySelectorAll('.modal.fwd .res-item'))
    .find(b => b.textContent.indexOf('GRPNAME') !== -1);
  if (!gi) return 'FAIL: el grupo no figura como destino';
  gi.click();
  const t1 = Date.now();
  while (Date.now() - t1 < 9000 && document.querySelector('.modal.fwd'))
    await sleep(200);
  if (document.querySelector('.modal.fwd'))
    return 'FAIL: el modal no cerró tras reenviar';
  const t2 = Date.now();
  let g = null;
  while (Date.now() - t2 < 9000) {
    g = Array.from(document.querySelectorAll('.chat-item'))
      .find(i => i.textContent.indexOf('GRPNAME') !== -1);
    if (g) break;
    await sleep(300);
  }
  if (!g) return 'FAIL: no aparece el grupo en la lista';
  g.click();
  await wait('.msgs .msg', 10000);
  let okF = false;
  const t3 = Date.now();
  while (Date.now() - t3 < 9000) {
    if (document.querySelector('.msgs .msg .b-fwd')) { okF = true; break; }
    await sleep(300);
  }
  return (okF ? 'OK' : 'FAIL') + ' reenviadoAlGrupo=' + okF;
})()"""

# W26: presencia — el snapshot del server al (re)conectar corrige estados
# viejos: si se perdió el evento de desconexión (ventana de reconexión),
# la cabecera ya no se queda "en línea" para siempre.
JS_PRESENCE_SNAP = """(async () => {
  %s
  if (!await openChat('BUSER')) return 'FAIL: sin chat de B';
  if (!await wait('.ch-status', 8000)) return 'FAIL: sin cabecera';
  const t0 = Date.now();
  while (Date.now() - t0 < 15000 && __fm.store.ws !== 'on') await sleep(150);
  /* plantar estado VIEJO (como si el evento de offline se hubiera perdido) */
  const dm = __fm.store.chats.find(
    c => c.type === 'dm' && c.title &&
         ('' + c.title.username).indexOf('BUSER') === 0);
  if (!dm) return 'FAIL: sin dm de B en store';
  const bid = dm.title.id;
  dm.title.online = true;
  __fm.store.presence[bid] = true;
  await sleep(300);
  const st0 = document.querySelector('.ch-status').textContent.trim();
  if (st0.indexOf('en l') === -1)
    return 'FAIL: no se plantó el estado viejo ([' + st0 + '])';
  /* reconectar: el server manda el snapshot autoritativo de presencia */
  __fm.rt.stop();
  await sleep(300);
  __fm.rt.start();
  const t1 = Date.now();
  while (Date.now() - t1 < 15000 && __fm.store.ws !== 'on') await sleep(150);
  if (__fm.store.ws !== 'on') return 'FAIL: la WS no reconectó';
  await sleep(600);
  if (__fm.store.presence[bid] !== false) {
    return 'FAIL: el snapshot no corrigió presence (' +
      __fm.store.presence[bid] + ')';
  }
  const st1 = document.querySelector('.ch-status').textContent.trim();
  if (st1.indexOf('en l') !== -1)
    return 'FAIL: la cabecera sigue en línea ([' + st1 + '])';
  return 'OK snapshot presence (' + st0 + ' → ' + st1 + ')';
})()"""


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    stamp = str(int(time.time()))[-7:]
    user_a = f"w13a{stamp}"[:20]
    user_b = f"w13b{stamp}"[:20]
    grp_title = f"Equipo W13 {stamp}"

    try:
        A = register(a.base, f"{user_a}@test.local", user_a)
        B = register(a.base, f"{user_b}@test.local", user_b)
        print(f"→ sembrados: {user_a} (A) y {user_b} (B)")

        # Nueva regla: el MD exige una solicitud de amistad aceptada.
        st, res = http("POST", a.base + "/api/people/requests",
                       {"username": user_b}, token=A["access"])
        if st != 201:
            raise SystemExit(f"✗ solicitud de amistad: {st} {res}")
        st, res = http("POST",
                       f"{a.base}/api/people/requests/{res['id']}/accept",
                       {}, token=B["access"])
        if st != 200:
            raise SystemExit(f"✗ aceptar amistad: {st} {res}")
        st, res = http("POST", a.base + "/api/chats/dm",
                       {"username": user_b}, token=A["access"])
        if st != 201:
            raise SystemExit(f"✗ dm: {st} {res}")
        cid = res["chat"]["id"]

        # grupo A+B (destino de reenvío)
        st, g = http("POST", a.base + "/api/chats/group",
                     {"title": grp_title, "members": []}, token=A["access"])
        if st != 201:
            raise SystemExit(f"✗ group: {st} {g}")
        gid = g["chat"]["id"]
        st, _ = http("POST", f"{a.base}/api/chats/{gid}/members",
                     {"username": user_b}, token=A["access"])
        if st not in (200, 201):
            raise SystemExit(f"✗ members: {st}")

        # conversación con texto (una línea con acento para el plegado)
        send(a.base, B["access"], cid,
             {"kind": "text", "body": "café con leche probando"})
        time.sleep(0.7)
        send(a.base, B["access"], cid,
             {"kind": "text", "body": "palabra clave pizza"})
        st, _ = http("POST", f"{a.base}/api/chats/{cid}/read",
                     {"seq": 10 ** 6}, token=A["access"])
        print("→ conversación sembrada; B queda desconectado (last_seen viejo)")
        backdate_last_seen(user_b)

        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        JS_INJECT = ("localStorage.setItem('fm.session', '" +
                     sess.replace("\\", "\\\\").replace("'", "\\'") +
                     "'); 'sesión inyectada'")
        helpers = JS_WAIT_HELPERS
        url = a.base + "/"

        run_shot(url, SHOTS / "w13ui-0-prep.png",
                 js="localStorage.removeItem('fm.session'); 'limpia'",
                 wait=200)
        step("paso1 sesión", url, SHOTS / "w13ui-0-sesion.png", JS_INJECT,
             expect_prefix="sesión")

        js_dots = (JS_DOTS % helpers).replace("BUSER", user_b) \
            .replace("GRPNAME", grp_title)
        step("paso2 puntos", url, SHOTS / "w13ui-1-puntos.png", js_dots)

        js_inv = (JS_STATUS_INV % helpers).replace("BUSER", user_b)
        step("paso3 invisible", url, SHOTS / "w13ui-2-invisible.png", js_inv)

        js_on = (JS_STATUS_ON % helpers).replace("BUSER", user_b)
        step("paso4 en línea", url, SHOTS / "w13ui-3-enlinea.png", js_on)
        st, me = http("GET", a.base + "/api/users/me", token=A["access"])
        preset = (me.get("user") or {}).get("status_preset") if st == 200 else None
        print(f"paso4 servidor: status_preset={preset!r}")
        if preset != "online":
            raise SystemExit("✗ el servidor no persistió el preset 'online'")

        js_snap = (JS_PRESENCE_SNAP % helpers).replace("BUSER", user_b)
        step("paso4b presencia snapshot", url,
             SHOTS / "w13ui-3b-presencia.png", js_snap)

        js_voice = (JS_VOICE_PREP % helpers).replace("BUSER", user_b)
        step("paso5 voz", url, SHOTS / "w13ui-4-voz.png", js=js_voice,
             ev=JS_VOICE_EVAL, tap=True, timeout=240)

        # nota "vieja": mismo archivo sin peaks/dur (como antes de W13)
        st, res = http("GET", f"{a.base}/api/chats/{cid}/messages?limit=50",
                       token=A["access"])
        voice_media = None
        for m in res.get("messages", []):
            if m.get("kind") == "voice" and m.get("media"):
                voice_media = m["media"]
        if not voice_media:
            raise SystemExit("✗ no encontré la nota grabada para clonarla")
        send(a.base, A["access"], cid,
             {"kind": "voice", "media_id": voice_media["id"]})
        print("→ nota vieja clonada (sin peaks/dur)")

        js_old = (JS_OLD_PREP % helpers).replace("BUSER", user_b)
        step("paso6 voz vieja", url, SHOTS / "w13ui-5-vozvieja.png",
             js=js_old, ev=JS_OLD_EVAL, tap=True, timeout=240)

        js_emo = (JS_EMOJI % helpers).replace("BUSER", user_b)
        step("paso7 emoji", url, SHOTS / "w13ui-6-emoji.png", js_emo)

        js_search = (JS_SEARCH % helpers).replace("BUSER", user_b)
        step("paso8 buscar", url, SHOTS / "w13ui-7-buscar.png", js_search)

        js_ctx = (JS_CTX % helpers).replace("BUSER", user_b)
        step("paso9 fijar/silenciar", url, SHOTS / "w13ui-8-fijar.png", js_ctx)

        js_fwd = (JS_FWD % helpers).replace("BUSER", user_b) \
            .replace("GRPNAME", grp_title)
        step("paso10 reenviar", url, SHOTS / "w13ui-9-reenviar.png", js_fwd)

        print(f"✓ W13 UI completa → {SHOTS}/w13ui-*.png")
    finally:
        cleanup_db()


if __name__ == "__main__":
    main()
