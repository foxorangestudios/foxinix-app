#!/usr/bin/env python
"""E2E W40: estilo de emojis configurable + iconos Material Symbols.

Siembra A y B (DM) y maneja Firefox headless (BiDi) con la sesión de A:

  1. Ajustes → Chat tiene el desplegable "Estilo de emojis" con tres
     opciones (Nativo del sistema / Emojis de Google / Twemoji) y el
     default es "Nativo del sistema" (el store arranca en 'system').
  2. en modo NATIVO todo va en texto: las celdas del picker son
     caracteres (sin <img>), ":fire:" se envía y la burbuja muestra
     el texto, y el chip de reacción también.
  3. cambiar a "Emojis de Google" (Noto) es reactivo (sin recargar):
     el picker y la burbuja usan <img> de /static/emoji-noto/*.png y
     el PNG se sirve on-demand.
  4. cambiar a "Twemoji" también: <img> de /static/emoji/*.svg.
  5. el estilo sobrevive a la recarga (localStorage fm.p.emo): la
     próxima sesión arranca en Twemoji y el desplegable lo muestra.
  6. iconos Material Symbols Outlined: el sprite conserva los ids
     #i-*, cada <use> visible apunta a un symbol existente, .ic se
     pinta con relleno (fill, no trazo) y se vuelca una hoja de
     todos los iconos para la revisión visual.
  7. W41: UN solo emoji en el mensaje se pinta GRANDE (clase
     .emo-big: mismo look que el sticker — sin caja, 42 px); con
     texto o con dos emojis va en burbuja normal.
  8. W42: la hora/palomitas de los contenidos grandes (un solo
     emoji, GIF y sticker) van en pastillita en una fila SEPARADA
     debajo del contenido — nunca encima (referencia: WhatsApp).

Uso: server/.venv/bin/python tests/w40_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import subprocess
import sys
import urllib.request
import uuid
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
  };"""


def js(tpl, **kw):
    out = W_WAIT + "\n" + tpl
    for k, v in kw.items():
        out = out.replace("«" + k + "»", v)
    return out


# abrir la DM con B (hay un solo chat sembrado)
ABRIR = """
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  if (!await wait('.msgs .msg')) return 'FAIL: sin mensajes';
  await sleep(350);"""

# Ajustes → pestaña Chat (el desplegable vive junto al de hora)
ABR_CHAT = """
  const gear = document.querySelector('[title="Ajustes"]');
  if (!gear) return 'FAIL: sin Ajustes';
  gear.click();
  if (!(await wait('.m-tab', 4000))) return 'FAIL: sin pestañas';
  const tabs = document.querySelectorAll('.m-tab');
  for (let i = 0; i < tabs.length; i++) {
    if (tabs[i].textContent.trim() === 'Chat') { tabs[i].click(); break; }
  }
  await sleep(250);"""

# el chip de reacción = 3.º por defecto (👍 😂 …) en .react-picker
REACT = """
  const bact = document.querySelectorAll('.msg.mine')[«N»].querySelectorAll('.b-act')[1];
  bact.click();
  const rp = await wait('.react-picker', 4000);
  if (!rp) return 'FAIL: sin chips de reacción';
  const chip = rp.querySelectorAll('.rp')[2];"""


# 1. desplegable en Ajustes: default 'system' + 3 opciones
JS_SETTINGS = """(async () => {
  await boot();
""" + ABR_CHAT + """
  const sel = await wait('.emo-select', 6000);
  if (!sel) return 'FAIL: sin desplegable .emo-select';
  const opts = Array.from(sel.options).map(function (o) {
    return { v: o.value, t: o.textContent.trim() };
  });
  return JSON.stringify({ val: sel.value, pref: __fm.store.prefs.emo,
                          opts: opts });
})()"""

# 2. modo NATIVO: picker/burbuja/chip en texto (sin <img>)
JS_NATIVO = """(async () => {
  await boot();
""" + ABRIR + """
  const emo = await wait('.comp-emo', 6000);
  if (!emo) return 'FAIL: sin botón de emojis';
  emo.click();
  const p = await wait('.emo-picker', 5000);
  if (!p) return 'FAIL: no abrió el panel';
  await sleep(400);
  const cells = p.querySelectorAll('.ep-scroll .ep-e');
  const cImgs = p.querySelectorAll('.ep-scroll .ep-e img.emo').length;
  const cell0 = cells[0] ? cells[0].textContent.trim() : '';
  emo.click();
  await sleep(200);
  const ta = document.querySelector('.composer-input');
  ta.value = ':fire';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  const ac = await wait('.emo-ac', 4000);
  if (!ac) return 'FAIL: sin autocompletado';
  ac.querySelector('.emo-ac-row').click();
  await sleep(250);
  document.querySelector('.comp-row .send-btn').click();
  let mine = null;
  const t0 = Date.now();
  while (Date.now() - t0 < 8000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    mine = rows[rows.length - 1];
    if (mine && mine.querySelector('.b-text')) break;
    await sleep(120);
  }
  if (!mine) return 'FAIL: sin burbuja propia';
  /* W39: esperar al ack (el id temporal flasheaba el chip) */
  const tA = Date.now();
  while (Date.now() - tA < 5000 && mine.querySelector('.tick.t-pend'))
    await sleep(100);
  const bImgs = mine.querySelectorAll('.b-text img.emo').length;
  const bTxt = mine.querySelector('.b-text').textContent.indexOf('\\u{1F525}') >= 0;
""" + REACT.replace('«N»', '0') + """
  const chipImg = !!chip.querySelector('img.emo');
  const chipTxt = chip.textContent.trim();
  chip.click();
  const t1 = Date.now();
  while (Date.now() - t1 < 7000 && !mine.querySelector('.react-chip.mine'))
    await sleep(130);
  const rc = mine.querySelector('.react-chip.mine');
  return JSON.stringify({ pref: __fm.store.prefs.emo, cells: cells.length,
                          cImgs: cImgs, cell0: cell0, bImgs: bImgs, bTxt: bTxt,
                          chipImg: chipImg, chipTxt: chipTxt,
                          reactImg: !!(rc && rc.querySelector('img.emo')),
                          reactTxt: rc ? rc.textContent : '' });
})()"""

# 3/4. cambiar el estilo en Ajustes y revisar el render de IMÁGENES
JS_ESTILO = """(async () => {
  await boot();
""" + ABRIR + ABR_CHAT + """
  const sel = await wait('.emo-select', 6000);
  if (!sel) return 'FAIL: sin desplegable .emo-select';
  sel.value = '«ESTILO»';
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(200);
  if (__fm.store.prefs.emo !== '«ESTILO»')
    return 'FAIL: el store no cambió (' + __fm.store.prefs.emo + ')';
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  await sleep(300);
  if (document.querySelector('.m-tab'))
    return 'FAIL: Ajustes no cerró con Esc';
  const emo = await wait('.comp-emo', 6000);
  emo.click();
  const p = await wait('.emo-picker', 5000);
  if (!p) return 'FAIL: no abrió el panel';
  await sleep(400);
  const first = p.querySelector('.ep-scroll .ep-e img.emo');
  const src = first ? (first.getAttribute('src') || '') : '';
  emo.click();
  await sleep(200);
  const ta = document.querySelector('.composer-input');
  ta.value = ':fire';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  const ac = await wait('.emo-ac', 4000);
  if (!ac) return 'FAIL: sin autocompletado';
  ac.querySelector('.emo-ac-row').click();
  await sleep(250);
  document.querySelector('.comp-row .send-btn').click();
  let mine = null;
  const t0 = Date.now();
  while (Date.now() - t0 < 8000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    mine = rows[rows.length - 1];
    if (mine && mine.querySelector('.b-text')) break;
    await sleep(120);
  }
  if (!mine) return 'FAIL: sin burbuja propia';
  const bImg = mine.querySelector('.b-text img.emo');
  const bSrc = bImg ? (bImg.getAttribute('src') || '') : '';
  return JSON.stringify({ pickerSrc: src, bSrc: bSrc,
                          pref: __fm.store.prefs.emo,
                          ls: localStorage.getItem('fm.p.emo') });
})()"""

# 5. persistencia: recarga y el estilo elegido (Twemoji) sigue activo
JS_RECARGA = """(async () => {
  await boot();
  const pref = __fm.store.prefs.emo;
  const ls = localStorage.getItem('fm.p.emo');
""" + ABRIR + ABR_CHAT + """
  const sel = await wait('.emo-select', 6000);
  const val = sel ? sel.value : '';
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  await sleep(300);
  const emo = await wait('.comp-emo', 6000);
  emo.click();
  const p = await wait('.emo-picker', 5000);
  await sleep(350);
  const first = p.querySelector('.ep-scroll .ep-e img.emo');
  const src = first ? (first.getAttribute('src') || '') : '';
  return JSON.stringify({ pref: pref, ls: ls, sel: val, src: src });
})()"""

# 6. iconos Material: sprite íntegro + .ic con relleno + hoja visual
JS_ICONOS = """(async () => {
  await boot();
  await sleep(400);
  const syms = document.querySelectorAll('symbol[id^="i-"]');
  if (syms.length < 50) return 'FAIL: solo ' + syms.length + ' symbols';
  const uses = document.querySelectorAll('use');
  const miss = [];
  for (let i = 0; i < uses.length; i++) {
    const h = uses[i].getAttribute('href') ||
      uses[i].getAttribute('xlink:href') || '';
    if (h.indexOf('#i-') === 0 && !document.getElementById(h.slice(1)))
      miss.push(h);
  }
  const ic = document.querySelector('.chat-list .ic') ||
    document.querySelector('.ic');
  const fill = ic ? getComputedStyle(ic).fill : '';
  /* hoja de iconos para la captura visual de revisión */
  const sheet = document.createElement('div');
  sheet.className = 'w40-sheet';
  sheet.setAttribute('style', 'position:fixed;left:0;top:0;width:100%;' +
    'z-index:99999;background:#fff;display:flex;flex-wrap:wrap;' +
    'padding:8px;font:12px sans-serif;color:#111');
  for (let i = 0; i < syms.length; i++) {
    const d = document.createElement('div');
    d.setAttribute('style', 'width:96px;height:80px;display:flex;' +
      'flex-direction:column;align-items:center;justify-content:center;' +
      'border:1px solid #ddd;margin:2px');
    const sv = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    sv.setAttribute('class', 'ic');
    const u = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    u.setAttribute('href', '#' + syms[i].id);
    sv.appendChild(u);
    d.appendChild(sv);
    const lb = document.createElement('span');
    lb.textContent = syms[i].id.slice(2);
    d.appendChild(lb);
    sheet.appendChild(d);
  }
  document.body.appendChild(sheet);
  return JSON.stringify({ n: syms.length, miss: miss, fill: fill });
})()"""

# 7. W41: UN solo emoji → mensaje grande (estilo sticker)
JS_GRANDE = """(async () => {
  await boot();
""" + ABRIR + """
  const send = async (txt) => {
    const n0 = document.querySelectorAll('.msgs .msg.mine').length;
    const ta = document.querySelector('.composer-input');
    ta.value = txt;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(150);
    document.querySelector('.comp-row .send-btn').click();
    const t0 = Date.now();
    while (Date.now() - t0 < 8000) {
      const rows = document.querySelectorAll('.msgs .msg.mine');
      if (rows.length > n0) {
        const last = rows[rows.length - 1];
        if (last.querySelector('.b-text')) return last;
      }
      await sleep(120);
    }
    return null;
  };
  const one = await send('\\ud83d\\ude06');
  if (!one) return 'FAIL: no se envió el emoji solo';
  const b = one.querySelector('.bubble');
  const bt = one.querySelector('.b-text');
  const emo = bt ? bt.querySelector('img.emo') : null;
  const meta = one.querySelector('.b-meta');
  const oneBig = b.classList.contains('emo-big');
  const fs = bt ? parseFloat(getComputedStyle(bt).fontSize) : 0;
  const emoW = emo ? Math.round(emo.getBoundingClientRect().width) : 0;
  const metaPos = meta ? getComputedStyle(meta).position : '';
  /* W42: la pastillita va en fila separada, POR DEBAJO del emoji */
  const sep = !!(meta && bt &&
    meta.getBoundingClientRect().top >= bt.getBoundingClientRect().bottom - 1);
  const withTxt = await send('hola \\ud83d\\ude06');
  const wtBig = !!(withTxt &&
    withTxt.querySelector('.bubble').classList.contains('emo-big'));
  const two = await send('\\ud83d\\ude06\\ud83d\\ude06');
  const twoBig = !!(two &&
    two.querySelector('.bubble').classList.contains('emo-big'));
  /* diagnóstico: el ":fire:" del autocompletado (¿con espacio?) y los
     fondos reales de burbuja (emo-big debe ser transparente) */
  const n1 = document.querySelectorAll('.msgs .msg.mine').length;
  const ta2 = document.querySelector('.composer-input');
  ta2.value = ':fire';
  ta2.dispatchEvent(new Event('input', { bubbles: true }));
  const ac = await wait('.emo-ac', 4000);
  if (ac) { ac.querySelector('.emo-ac-row').click(); await sleep(250); }
  const fireVal = JSON.stringify(ta2.value);
  document.querySelector('.comp-row .send-btn').click();
  let fb = null;
  const t2 = Date.now();
  while (Date.now() - t2 < 8000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    if (rows.length > n1) {
      const last = rows[rows.length - 1];
      if (last.querySelector('.b-text')) { fb = last.querySelector('.bubble'); break; }
    }
    await sleep(120);
  }
  return JSON.stringify({ oneBig: oneBig, fs: fs, emoW: emoW,
                          metaPos: metaPos, sep: sep, wtBig: wtBig,
                          twoBig: twoBig, fireVal: fireVal,
                          fireBig: !!(fb && fb.classList.contains('emo-big')),
                          fireBg: fb ? getComputedStyle(fb).backgroundColor : '',
                          oneBg: getComputedStyle(b).backgroundColor });
})()"""

# 8. W42: GIF y sticker con la pastillita en fila separada debajo
JS_GIFSTK = """(async () => {
  await boot();
""" + ABRIR + """
  /* el GIF lo envió el test por HTTP antes de la captura */
  let gb = null;
  const t0 = Date.now();
  while (Date.now() - t0 < 8000) {
    gb = document.querySelector('.bubble.gif');
    if (gb) break;
    await sleep(120);
  }
  if (!gb) return 'FAIL: sin burbuja gif';
  const gmeta = gb.querySelector('.b-meta');
  const gimg = gb.querySelector('img');
  if (!gmeta || !gimg) return 'FAIL: sin meta/media del gif';
  const gcs = getComputedStyle(gmeta);
  const gr = gmeta.getBoundingClientRect();
  const gir = gimg.getBoundingClientRect();
  /* sticker: se envía desde el panel (pestaña Stickers) */
  const emo = await wait('.comp-emo', 6000);
  emo.click();
  const p = await wait('.st-panel', 5000);
  if (!p) return 'FAIL: no abrió el panel';
  const tabs = Array.from(p.querySelectorAll('.ep-tab'));
  const stTab = tabs.find(function (t) { return t.textContent === 'Stickers'; });
  if (!stTab) return 'FAIL: sin pestaña Stickers';
  stTab.click();
  await sleep(450);
  const st = p.querySelector('.st-e');
  if (!st) return 'FAIL: sin stickers';
  const n0 = document.querySelectorAll('.msgs .msg.mine').length;
  st.click();
  let sb = null;
  const t1 = Date.now();
  while (Date.now() - t1 < 8000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    if (rows.length > n0) {
      const cand = rows[rows.length - 1].querySelector('.bubble.sticker');
      if (cand) { sb = cand; break; }
    }
    await sleep(120);
  }
  if (!sb) return 'FAIL: sin burbuja sticker';
  const smeta = sb.querySelector('.b-meta');
  const stx = sb.querySelector('.b-text');
  if (!smeta || !stx) return 'FAIL: sin meta/texto del sticker';
  const scs = getComputedStyle(smeta);
  const sr = smeta.getBoundingClientRect();
  const txr = stx.getBoundingClientRect();
  return JSON.stringify({
    gifPos: gcs.position, gifRad: gcs.borderRadius, gifBg: gcs.background,
    gifSep: gr.top >= gir.bottom - 1,
    gifBox: getComputedStyle(gb).backgroundColor,
    stPos: scs.position, stRad: scs.borderRadius, stBg: scs.background,
    stSep: sr.top >= txr.bottom - 1,
    stBox: getComputedStyle(sb).backgroundColor
  });
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w40a{tag}@t.fi", f"w40a{tag}")
    B = ct.register(a.base, f"w40b{tag}@t.fi", f"w40b{tag}")
    BU = B["user"]["username"]
    print(f"· A={A['user']['username']} B={BU}")

    st, r = ct.dm_between(a.base, A["access"], B["access"],
                          A["user"]["username"], BU)
    assert st in (200, 201), (st, r)
    dm = r["chat"]["id"]
    ct.send(a.base, B["access"], dm,
            {"kind": "text", "body": f"hola w40 {tag}",
             "client_msg_id": str(uuid.uuid4())})
    print(f"· dm={dm}")

    # ============ sesión de A en el navegador =====================
    ok, res, log = shot(a.base + "/", SHOTS / "w40-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    # ============ 1. desplegable en Ajustes =======================
    print("→ paso1 desplegable de estilo de emojis")
    ok, res, log = shot(a.base + "/", SHOTS / "w40-1-ajustes.png",
                        js=js(JS_SETTINGS))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    opts = d.get("opts") or []
    ov = [o.get("v") for o in opts]
    ot = [o.get("t") for o in opts]
    step("default 'system' (Nativo del sistema)",
         ok and d.get("val") == "system" and d.get("pref") == "system",
         f"res={res!r}")
    step("tres opciones: Nativo/Google/Twemoji",
         ov == ["system", "noto", "twemoji"]
         and ot[0] == "Nativo del sistema" and ot[1] == "Emojis de Google"
         and ot[2] == "Twemoji", f"res={res!r}")

    # ============ 2. modo nativo: todo en texto ===================
    print("→ paso2 modo nativo (texto del sistema)")
    ok, res, log = shot(a.base + "/", SHOTS / "w40-2-nativo.png",
                        js=js(JS_NATIVO))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("picker en texto: celdas sin <img>", ok and d.get("cells", 0) > 8
         and d.get("cImgs") == 0, f"res={res!r}")
    step("la burbuja :fire: muestra el texto (sin img)", d.get("bImgs") == 0
         and d.get("bTxt"), f"res={res!r}")
    step("chip de reacción en texto", not d.get("chipImg")
         and "\\ud83d" in json.dumps(d.get("chipTxt", ""))
         and not d.get("reactImg"), f"res={res!r}")

    # ============ 3. Google (Noto) reactivo =======================
    print("→ paso3 estilo Emojis de Google (Noto)")
    ok, res, log = shot(a.base + "/", SHOTS / "w40-3-noto.png",
                        js=js(JS_ESTILO, ESTILO="noto"))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("picker y burbuja usan PNG de /static/emoji-noto/",
         ok and "/static/emoji-noto/" in (d.get("pickerSrc") or "")
         and "/static/emoji-noto/" in (d.get("bSrc") or "")
         and "1f525" in (d.get("bSrc") or "")
         and d.get("ls") == "noto", f"res={res!r}")
    noto_ok = False
    try:
        with urllib.request.urlopen(a.base + "/static/emoji-noto/1f525.png",
                                    timeout=10) as r2:
            noto_ok = r2.status == 200 and b"\x89PNG" in r2.read(8)
    except Exception:
        pass
    step("PNG de Google (Noto) servido on-demand", noto_ok)

    # ============ 4. Twemoji reactivo =============================
    print("→ paso4 estilo Twemoji")
    ok, res, log = shot(a.base + "/", SHOTS / "w40-4-twemoji.png",
                        js=js(JS_ESTILO, ESTILO="twemoji"))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("picker y burbuja usan SVG de /static/emoji/",
         ok and (d.get("pickerSrc") or "").startswith("/static/emoji/")
         and ".svg" in (d.get("pickerSrc") or "")
         and (d.get("bSrc") or "").startswith("/static/emoji/")
         and ".svg" in (d.get("bSrc") or "")
         and d.get("ls") == "twemoji", f"res={res!r}")

    # ============ 5. persistencia tras recarga ====================
    print("→ paso5 el estilo sobrevive a la recarga")
    ok, res, log = shot(a.base + "/", SHOTS / "w40-5-recarga.png",
                        js=js(JS_RECARGA))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("recarga en Twemoji: store, localStorage y select",
         ok and d.get("pref") == "twemoji" and d.get("ls") == "twemoji"
         and d.get("sel") == "twemoji", f"res={res!r}")
    step("el picker de la nueva sesión pinta SVGs",
         (d.get("src") or "").startswith("/static/emoji/")
         and ".svg" in (d.get("src") or ""), f"res={res!r}")

    # ============ 6. iconos Material Symbols Outlined =============
    print("→ paso6 iconos Material + hoja de revisión")
    ok, res, log = shot(a.base + "/", SHOTS / "w40-6-iconos.png",
                        js=js(JS_ICONOS), wait=1500)
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("sprite con 53+ ids #i-* intactos", ok and (d.get("n") or 0) >= 53,
         f"res={res!r}")
    step("todo <use> visible apunta a un symbol existente",
         d.get("miss") == [], f"res={res!r}")
    step(".ic se pinta con relleno (Material), no con trazo",
         (d.get("fill") or "") != "none", f"fill={d.get('fill')!r}")
    step("hoja de iconos volcada para la captura",
         ok and (d.get("n") or 0) >= 53)

    # ============ 7. W41: UN solo emoji → grande ==================
    print("→ paso7 un solo emoji se pinta grande (estilo sticker)")
    ok, res, log = shot(a.base + "/", SHOTS / "w40-7-grande.png",
                        js=js(JS_GRANDE))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    print(f"· diag-p7={res}")
    step("el mensaje de UN solo emoji lleva .emo-big (42px, burbuja transparente)",
         ok and d.get("oneBig") and (d.get("fs") or 0) >= 40
         and d.get("oneBg") == "rgba(0, 0, 0, 0)", f"res={res!r}")
    step("la pastillita va en fila separada debajo del emoji (W42)",
         d.get("metaPos") == "static" and d.get("sep") is True,
         f"res={res!r}")
    step("el emoji Twemoji del mensaje grande mide ~52px",
         (d.get("emoW") or 0) >= 50, f"res={res!r}")
    step("'hola 😆' y '😆😆' van en burbuja normal (sin .emo-big)",
         d.get("wtBig") is False and d.get("twoBig") is False,
         f"res={res!r}")

    # ============ 8. W42: GIF y sticker con meta separada =========
    print("→ paso8 GIF y sticker: pastillita separada debajo")
    gif = SHOTS / "w42.gif"
    gif.write_bytes(bytes.fromhex(
        "47494638396101000100800000000000ffffff21f9040100000000"
        "2c000000000100010000020144003b"))
    up = ct.upload(a.base, A["access"], gif)
    ct.send(a.base, A["access"], dm,
            {"kind": "image", "media_id": up["id"],
             "client_msg_id": str(uuid.uuid4())})
    ok, res, log = shot(a.base + "/", SHOTS / "w40-8-gif-sticker.png",
                        js=js(JS_GIFSTK))
    d = {}
    try:
        d = json.loads(res)
    except Exception:
        pass
    step("GIF: pastillita en fila separada debajo (no encima)",
         ok and d.get("gifPos") == "static" and d.get("gifSep") is True
         and (d.get("gifRad") or "") != "0px"
         and (d.get("gifBg") or "none") != "none"
         and d.get("gifBox") == "rgba(0, 0, 0, 0)", f"res={res!r}")
    step("sticker: pastillita en fila separada debajo (no encima)",
         d.get("stPos") == "static" and d.get("stSep") is True
         and (d.get("stRad") or "") != "0px"
         and (d.get("stBg") or "none") != "none"
         and d.get("stBox") == "rgba(0, 0, 0, 0)", f"res={res!r}")

    # ============ limpieza ========================================
    if ct.cleanup_db():
        print("· limpieza ok")
    else:
        print("· WARN: limpieza incompleta")

    print(f"\nW40: {_pass[0]} pasos OK, {_fail[0]} fallos")
    sys.exit(1 if _fail[0] else 0)


if __name__ == "__main__":
    main()
