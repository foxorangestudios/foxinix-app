#!/usr/bin/env python
"""E2E W20: panel de "Fondo del chat" + micrófono configurable.

  1. panel dedicado (donde está la lista de chats): preview con la
     conversación de ejemplo (Carlos/Javier, horas 12 h), foto de
     fondo, opacidad del velo y difuminado en vivo sobre la real;
     sin foto, las opciones del fondo no están disponibles (W27d)
  2. persistencia: opacidad/difuminado sobreviven a la recarga (se
     aplican en el pre-paint) y "Quitar foto" funciona desde el panel
  3. Ajustes → Chat → Micrófono: selector de dispositivo (persistido)
     y prueba de nivel con el micrófono falso

Uso: server/.venv/bin/python tests/w20_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "server"))

import chat_ui_test as ct  # noqa: E402  (helpers: register, send, run_shot…)

SHOTS = Path("/tmp/opencode")

PNG1 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE"
        "hQGAhKmMIQAAAABJRU5ErkJggg==")

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
    const item = await wait('.chat-list .chat-item');
    if (!item) return 'FAIL: sin chats';
    item.click();
    if (!await wait('.msgs .msg')) return 'FAIL: sin mensajes';
    return '';
  };
  const openWallPanel = async () => {
    const gear = document.querySelector('.user-panel .icon-btn[title="Ajustes"]');
    if (!gear) return 'FAIL: sin engranaje de ajustes';
    gear.click();
    const openBtn = await wait('.ap-wallrow .btn', 6000);
    if (!openBtn) return 'FAIL: sin botón Personalizar fondo';
    openBtn.click();
    if (!await wait('.wall-panel', 6000)) return 'FAIL: no abrió el panel';
    return '';
  };"""

JS_FOTO_DIM = """(async () => {
  """ + W_WAIT + """
  let err = await openChat();
  if (err) return err;
  err = await openWallPanel();
  if (err) return err;
  /* W27d: sin foto de fondo las opciones (opacidad/difuminado) no
     están disponibles */
  const pre = document.querySelectorAll('.wp-range');
  if (pre.length < 2 || !pre[0].disabled || !pre[1].disabled) {
    return 'FAIL: las opciones del fondo están activas sin foto';
  }
  /* foto desde el panel */
  const inp = await wait('.ap-wall-input', 4000);
  if (!inp) return 'FAIL: sin input de foto';
  const bin = atob('""" + PNG1 + """');
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  const f = new File([arr], 'fondo.png', { type: 'image/png' });
  const dt = new DataTransfer();
  dt.items.add(f);
  inp.files = dt.files;
  inp.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(600);
  if (!document.documentElement.classList.contains('wallimg')) {
    return 'FAIL: no se aplicó .wallimg';
  }
  /* sliders: opacidad 80 y difuminado 8 (ya disponibles con foto) */
  const ranges = document.querySelectorAll('.wp-range');
  if (ranges.length < 2) return 'FAIL: faltan sliders (' + ranges.length + ')';
  if (ranges[0].disabled || ranges[1].disabled) {
    return 'FAIL: las opciones siguen deshabilitadas con foto';
  }
  ranges[0].value = '80';
  ranges[0].dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(150);
  ranges[1].value = '8';
  ranges[1].dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(200);
  const cssVar = function (n) {
    return document.documentElement.style.getPropertyValue(n).trim();
  };
  if (cssVar('--wall-dim') !== '0.80') return 'FAIL: --wall-dim=' + cssVar('--wall-dim');
  if (cssVar('--wall-blur') !== '8px') return 'FAIL: --wall-blur=' + cssVar('--wall-blur');
  /* la vista previa (ahora el centro) refleja los sliders */
  const pane = document.querySelector('.wall-preview');
  if (!pane) return 'FAIL: sin vista previa en el centro';
  const after = getComputedStyle(pane, '::after');
  if (Math.abs(parseFloat(after.opacity) - 0.8) > 0.02) {
    return 'FAIL: velo real opacity=' + after.opacity;
  }
  const before = getComputedStyle(pane, '::before');
  if (before.filter.indexOf('blur(8px)') < 0) return 'FAIL: filter=' + before.filter;
  if (before.backgroundImage.indexOf('url(') < 0) return 'FAIL: sin foto en ::before';
  if (localStorage.getItem('fm.wdim') !== '80') return 'FAIL: no persistió opacidad';
  if (localStorage.getItem('fm.wblur') !== '8') return 'FAIL: no persistió difuminado';
  /* la conversación de ejemplo vive en el centro, a tamaño real */
  const prev = document.querySelector('.wall-preview .wp-prev');
  if (!prev || prev.textContent.indexOf('Carlos') < 0) {
    return 'FAIL: la vista previa no trae a Carlos';
  }
  if (prev.textContent.indexOf('6:10 p.m.') < 0) return 'FAIL: sin horas de ejemplo';
  /* y el chat REAL quedó oculto mientras el panel está abierto */
  if (document.querySelector('.chat-pane')) return 'FAIL: el chat real sigue en el centro';
  /* cerrar el panel devuelve el sidebar */
  document.querySelector('.wall-panel .side-head .icon-btn').click();
  await sleep(250);
  if (document.querySelector('.wall-panel')) return 'FAIL: el panel no se cerró';
  const aside = document.querySelector('.sidebar');
  if (!aside || aside.getBoundingClientRect().width < 200) {
    return 'FAIL: el sidebar no volvió';
  }
  return 'OK foto + opacidad 80% + difuminado 8px en vivo';
})()"""

JS_PREPAINT = """(async () => {
  """ + W_WAIT + """
  /* recarga frescha: el pre-paint reaplica los ajustes sin parpadeo */
  const cssVar = function (n) {
    return document.documentElement.style.getPropertyValue(n).trim();
  };
  if (cssVar('--wall-dim') !== '0.80') return 'FAIL: pre-paint --wall-dim=' + cssVar('--wall-dim');
  if (cssVar('--wall-blur') !== '8px') return 'FAIL: pre-paint --wall-blur=' + cssVar('--wall-blur');
  let err = await openChat();
  if (err) return err;
  const pane = document.querySelector('.chat-pane');
  const before = getComputedStyle(pane, '::before');
  if (before.backgroundImage.indexOf('url(') < 0) return 'FAIL: sin foto tras recargar';
  if (before.filter.indexOf('blur(8px)') < 0) return 'FAIL: perdió el difuminado';
  /* "Quitar foto" desde el panel */
  err = await openWallPanel();
  if (err) return err;
  const del = Array.prototype.slice
    .call(document.querySelectorAll('.wp-row .btn'))
    .filter(function (b) { return b.textContent.trim() === 'Quitar foto'; })[0];
  if (!del) return 'FAIL: sin botón Quitar foto';
  del.click();
  await sleep(300);
  if (document.documentElement.classList.contains('wallimg')) {
    return 'FAIL: no se quitó .wallimg';
  }
  if (localStorage.getItem('fm.wallimg')) return 'FAIL: siguió la foto en localStorage';
  /* cerrar el panel para dejar el sidebar como estaba */
  document.querySelector('.wall-panel .side-head .icon-btn').click();
  await sleep(250);
  return 'OK pre-paint + quitar foto';
})()"""

JS_MIC = """(async () => {
  """ + W_WAIT + """
  /* Firefox oculta deviceIds/etiquetas sin permiso: concederlo primero
     para que el selector traiga el dispositivo real */
  try { await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) {}
  const gear = await wait('.user-panel .icon-btn[title="Ajustes"]', 8000);
  if (!gear) return 'FAIL: sin engranaje de ajustes';
  gear.click();
  if (!await wait('.m-tabs .m-tab', 4000)) return 'FAIL: no abrió Ajustes';
  const tabs = Array.prototype.slice.call(document.querySelectorAll('.m-tab'));
  const chatTab = tabs.filter(function (x) { return x.textContent.trim() === 'Chat'; })[0];
  if (!chatTab) return 'FAIL: sin pestaña Chat';
  chatTab.click();
  const sel = await wait('.mic-select', 4000);
  if (!sel) return 'FAIL: sin selector de micrófono';
  /* W36fix: enumerateDevices tarda en traer el deviceId (a veces ~1 s
     tras el permiso): esperar al dato en vez de leer en caliente, y
     basta UN dispositivo real (la caja puede exponer sólo un micrófono) */
  let pickOpt = null;
  let tm = Date.now();
  while (Date.now() - tm < 5000) {
    const opts = sel.querySelectorAll('option');
    for (let i = 0; i < opts.length; i++) {
      if (opts[i].value) { pickOpt = opts[i]; break; }
    }
    if (pickOpt) break;
    await sleep(150);
  }
  if (!pickOpt) return 'FAIL: sin dispositivos con deviceId';
  sel.value = pickOpt.value;
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(300);
  if (!localStorage.getItem('fm.mic')) return 'FAIL: no persistió el micrófono';
  const btn = document.querySelector('.mic-test-row .btn');
  if (!btn) return 'FAIL: sin botón de prueba';
  btn.click();
  await sleep(800);
  if (btn.textContent.indexOf('Escuchando') < 0) {
    return 'FAIL: no arrancó la prueba (' + btn.textContent.trim() + ')';
  }
  if (!document.querySelector('.mic-bar i')) return 'FAIL: sin barra de nivel';
  btn.click();
  await sleep(300);
  if (btn.textContent.indexOf('Probar') < 0) return 'FAIL: no paró la prueba';
  return 'OK micrófono (dispositivo + prueba de nivel)';
})()"""


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
    ua, ub = f"w20a{stamp}", f"w20b{stamp}"
    try:
        A = ct.register(a.base, f"{ua}@test.local", ua)
        B = ct.register(a.base, f"{ub}@test.local", ub)
        print(f"→ sembrados: {ua}, {ub}")

        st, res = ct.dm_between(a.base, A["access"], B["access"], ua, ub)
        if st not in (200, 201):
            raise SystemExit(f"✗ dm: {st} {res}")
        dm = res["chat"]["id"]
        ct.send(a.base, B["access"], dm,
                {"kind": "text", "body": "hola", "client_msg_id": str(uuid.uuid4())})
        ct.send(a.base, A["access"], dm,
                {"kind": "text", "body": "buenas", "client_msg_id": str(uuid.uuid4())})

        # perfil limpio + sesión (los shots siguientes reutilizan el perfil)
        ok0, res0, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w20-0-perfil.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        step("paso0 perfil", ok0 and res0 == "limpia", res0 or log[-300:])
        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))
        ok1, res1, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w20-0-sesion.png", js=sess_js, wait=300)
        step("paso0 sesión", ok1 and bool(res1), res1 or log[-300:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w20-1-fondo.png", js=JS_FOTO_DIM, wait=500)
        step("paso1 panel: foto + opacidad + difuminado",
             okk and str(ress).startswith("OK"), ress if ress else log[-400:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w20-2-persist.png", js=JS_PREPAINT, wait=500)
        step("paso2 pre-paint tras recarga + quitar foto",
             okk and str(ress).startswith("OK"), ress if ress else log[-400:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w20-3-mic.png", js=JS_MIC, wait=400)
        step("paso3 micrófono: dispositivo + prueba",
             okk and str(ress).startswith("OK"), ress if ress else log[-400:])

        print(f"\nw20 UI: {ok} ok, {fail} fallas")
        sys.exit(1 if fail else 0)
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
