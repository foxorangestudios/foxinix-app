#!/usr/bin/env python
"""E2E W16: panel de emojis — geometría (no se sale ni se corta) + funciones.

Siembra 2 usuarios con una conversación larga (para que el último mensaje
quede abajo del todo) y maneja Firefox headless (BiDi):

  1. composer: el panel queda DENTRO del área de mensajes (no tapa la
     cabecera, no se corta en los bordes, no se sale del viewport)
  2. composer: funciones (categorías, buscar, sin resultados, Esc, insertar,
     recientes, clic interno no cierra, clic exterior cierra, enviar)
  3. W17: ranking de reacciones por uso (usar 😂 la sube al 1er puesto);
     va antes de las suites que reaccionan para que fm.react.counts esté
     limpio y el orden base sea determinista
  4. reacciones desde un mensaje entrante (izquierda): chips + panel
     completo dentro del área; rp-more abre/cierra; elegir del panel
     completo → chip propio
  5. reacciones desde mensaje propio (derecha): chips + panel dentro;
     elegir de los chips rápidos → chip propio
  6. reacciones desde el último mensaje (abajo): chips + panel dentro
  7. ventana corta (shell simulado a 1000x420 con CSS, porque Firefox
     ignora --window-size): el panel del composer se achica y sigue dentro
  8. W17: un solo panel flotante a la vez (composer/menú/chips se cierran
     entre sí) y el clic exterior cierra los chips
  9. W17: autocompletado ":fire" → 🔥 y ":código:" convertido al enviar
  10. W17: el ⋯ de la barra hover abre el menú anclado al lado de la
      burbuja (no la tapa)
  11. W17: Ajustes → Chat → hora 12h (am/pm) en la lista

La caja de referencia es .msgs: si el panel la excede, el overflow lo corta
(overflow-x: hidden) o tapa la cabecera/sidebar — ambos casos son el bug.

Uso: server/.venv/bin/python tests/emoji_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

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
  };"""

# abre el DM sembrado y espera los mensajes
ABRIR = """
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  if (!await wait('.msg')) return 'FAIL: sin mensajes';
  await sleep(400);"""

# geometría: el panel debe quedar dentro de .msgs (si lo excede, se corta
# con el overflow o tapa la cabecera/sidebar)
GEO = """
  const geo = function (el) {
    const b = document.querySelector('.msgs').getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const dentro = r.left >= b.left - 2 && r.top >= b.top - 2 &&
      r.right <= b.right + 2 && r.bottom <= b.bottom + 2;
    return (dentro ? 'dentro ' : 'FUERA ') + '[' + Math.round(r.left) + ',' +
      Math.round(r.top) + '→' + Math.round(r.right) + ',' + Math.round(r.bottom) +
      '] caja[' + Math.round(b.left) + ',' + Math.round(b.top) + '→' +
      Math.round(b.right) + ',' + Math.round(b.bottom) + '] vh=' + window.innerHeight;
  };"""

JS_COMP_GEO = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  const emo = document.querySelector('.comp-emo');
  if (!emo) return 'FAIL: sin botón de emojis';
  emo.click();
  const p = await wait('.emo-picker');
  if (!p) return 'FAIL: no abrió el panel';
  await sleep(800);
  const g = geo(p);
  return (g.indexOf('FUERA') === 0 ? 'FAIL composer se sale: ' : 'OK composer ') + g;
})()"""

JS_COMP_FUNCS = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  document.querySelector('.comp-emo').click();
  const p = await wait('.emo-picker');
  if (!p) return 'FAIL: no abrió el panel';
  await sleep(250);
  const inp = p.querySelector('.ep-search input');
  const tabs = p.querySelectorAll('.ep-cat');
  if (tabs.length < 4) return 'FAIL: categorías=' + tabs.length;
  // 1) cada categoría (salvo recientes, vacío al inicio) trae emojis
  for (let i = 1; i < tabs.length; i++) {
    tabs[i].click(); await sleep(90);
    if (!p.querySelectorAll('.ep-e').length) {
      return 'FAIL: categoría sin emojis (tab ' + i + ')';
    }
  }
  // 2) búsqueda con resultados
  inp.value = 'pizza';
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(280);
  const hit = p.querySelector('.ep-grid .ep-e');
  /* W29b: los emojis son <img> Twemoji; el :shortcode: va en el título */
  if (!hit || hit.getAttribute('title') !== ':pizza:') {
    return 'FAIL: buscar pizza → ' + (hit ? hit.getAttribute('title') : 'vacío');
  }
  // 3) búsqueda sin resultados
  inp.value = 'zzqqxx';
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(280);
  if (!p.querySelector('.ep-empty')) return 'FAIL: sin .ep-empty para zzqqxx';
  // 4) Esc limpia la búsqueda y vuelve a la categoría
  inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await sleep(220);
  if (inp.value !== '') return 'FAIL: Esc no limpió la búsqueda (' + inp.value + ')';
  if (p.querySelector('.ep-empty')) return 'FAIL: .ep-empty tras Esc';
  if (!p.querySelectorAll('.ep-e').length) return 'FAIL: grid vacío tras Esc';
  // 5) insertar un emoji en el composer
  p.querySelector('.ep-grid .ep-e').click();
  await sleep(200);
  const ta = document.querySelector('.composer-input');
  const ch = ta ? ta.value : '';
  if (!ch) return 'FAIL: no insertó en el composer';
  // 6) recientes poblados
  p.querySelectorAll('.ep-cat')[0].click();
  await sleep(180);
  if (!p.querySelectorAll('.ep-e').length) return 'FAIL: recientes vacío tras insertar';
  // 7) clic dentro del panel NO lo cierra
  p.querySelector('.ep-search').click();
  await sleep(180);
  if (!document.querySelector('.emo-picker')) return 'FAIL: cerró con clic interno';
  // 8) clic fuera SÍ lo cierra
  document.querySelector('.msgs').click();
  await sleep(250);
  if (document.querySelector('.emo-picker')) return 'FAIL: no cerró con clic exterior';
  // 9) reabrir y enviar: el mensaje llega con el emoji y el panel se cierra
  document.querySelector('.comp-emo').click();
  if (!await wait('.emo-picker')) return 'FAIL: no reabrió el panel';
  document.querySelector('.comp-row .send-btn').click();
  let enviado = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 7000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    const last = rows[rows.length - 1];
    /* W29b: el emoji se renderiza como <img alt="😀"> (no en textContent) */
    const im = last && last.querySelector('.b-text img.emo[alt="' + ch + '"]');
    if (last && (last.textContent.indexOf(ch) >= 0 || im)) { enviado = true; break; }
    await sleep(150);
  }
  if (!enviado) return 'FAIL: no se envió el mensaje con emoji';
  if (document.querySelector('.emo-picker')) return 'FAIL: no cerró al enviar';
  return 'OK funciones (tabs=' + tabs.length + ', insert=' + ch + ')';
})()"""

JS_REACT_LEFT = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  const sc = document.querySelector('.msgs');
  sc.scrollTop = 0;
  await sleep(350);
  const target = document.querySelector('.msgs .msg:not(.mine)');
  if (!target) return 'FAIL: sin mensaje entrante';
  const acts = target.querySelectorAll('.b-act');
  if (acts.length < 2) return 'FAIL: sin acciones de mensaje';
  acts[1].click();                       // reaccionar
  const rp = await wait('.react-picker');
  if (!rp) return 'FAIL: no abrieron los chips';
  await sleep(280);
  const g1 = geo(rp);
  if (g1.indexOf('FUERA') === 0) return 'FAIL chips: ' + g1;
  rp.querySelector('.rp-more').click();  // panel completo
  const p = await wait('.emo-picker');
  if (!p) return 'FAIL: sin panel completo';
  await sleep(800);
  const g2 = geo(p);
  if (g2.indexOf('FUERA') === 0) return 'FAIL panel completo: ' + g2;
  // rp-more cierra el panel y deja los chips
  document.querySelector('.react-picker .rp-more').click();
  await sleep(220);
  if (document.querySelector('.emo-picker')) return 'FAIL: rp-more no cerró el panel';
  if (!document.querySelector('.react-picker')) return 'FAIL: se fueron los chips';
  // reabrir y elegir un emoji del panel completo
  document.querySelector('.react-picker .rp-more').click();
  const p2 = await wait('.emo-picker');
  if (!p2) return 'FAIL: no reabrió el panel';
  await sleep(250);
  let cell = p2.querySelector('.ep-grid .ep-e');
  if (!cell) {
    p2.querySelectorAll('.ep-cat')[1].click();
    await sleep(180);
    cell = p2.querySelector('.ep-grid .ep-e');
  }
  if (!cell) return 'FAIL: sin emoji para elegir';
  cell.click();
  const t0 = Date.now();
  while (Date.now() - t0 < 7000 && !target.querySelector('.react-chip.mine')) {
    await sleep(130);
  }
  if (!target.querySelector('.react-chip.mine')) return 'FAIL: sin chip tras elegir del panel';
  return 'OK panel entrante (' + g1 + ' | ' + g2 + ')';
})()"""

JS_REACT_MINE = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  const sc = document.querySelector('.msgs');
  sc.scrollTop = sc.scrollHeight;
  await sleep(350);
  const mines = document.querySelectorAll('.msgs .msg.mine');
  const target = mines[mines.length - 1];
  if (!target) return 'FAIL: sin mensaje propio';
  const acts = target.querySelectorAll('.b-act');
  if (acts.length < 2) return 'FAIL: sin acciones de mensaje';
  acts[1].click();
  const rp = await wait('.react-picker');
  if (!rp) return 'FAIL: no abrieron los chips';
  await sleep(280);
  const g1 = geo(rp);
  if (g1.indexOf('FUERA') === 0) return 'FAIL chips: ' + g1;
  rp.querySelector('.rp-more').click();
  const p = await wait('.emo-picker');
  if (!p) return 'FAIL: sin panel completo';
  await sleep(800);
  const g2 = geo(p);
  if (g2.indexOf('FUERA') === 0) return 'FAIL panel completo: ' + g2;
  // elegir de los chips rápidos (el panel completo se cierra solo)
  document.querySelector('.react-picker .rp').click();
  const t0 = Date.now();
  while (Date.now() - t0 < 7000 && !target.querySelector('.react-chip.mine')) {
    await sleep(130);
  }
  if (!target.querySelector('.react-chip.mine')) return 'FAIL: sin chip de los chips rápidos';
  return 'OK panel propio (' + g1 + ' | ' + g2 + ')';
})()"""

JS_REACT_LAST = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  const sc = document.querySelector('.msgs');
  sc.scrollTop = sc.scrollHeight;
  await sleep(350);
  const all = document.querySelectorAll('.msgs .msg');
  const target = all[all.length - 1];
  if (!target) return 'FAIL: sin mensajes';
  const acts = target.querySelectorAll('.b-act');
  if (acts.length < 2) return 'FAIL: sin acciones de mensaje';
  acts[1].click();
  const rp = await wait('.react-picker');
  if (!rp) return 'FAIL: no abrieron los chips';
  await sleep(280);
  const g1 = geo(rp);
  if (g1.indexOf('FUERA') === 0) return 'FAIL chips: ' + g1;
  rp.querySelector('.rp-more').click();
  const p = await wait('.emo-picker');
  if (!p) return 'FAIL: sin panel completo';
  await sleep(800);
  const g2 = geo(p);
  if (g2.indexOf('FUERA') === 0) return 'FAIL panel completo: ' + g2;
  return 'OK panel último mensaje (' + g1 + ' | ' + g2 + ')';
})()"""


JS_COMP_GEO_CORTO = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  // Firefox ignora --window-size: simulamos una ventana corta acotando el shell
  const st = document.createElement('style');
  st.textContent = '.app-shell { height: 420px !important; width: 1000px !important; }';
  document.head.appendChild(st);
  await sleep(350);
  const emo = document.querySelector('.comp-emo');
  if (!emo) return 'FAIL: sin botón de emojis';
  emo.click();
  const p = await wait('.emo-picker');
  if (!p) return 'FAIL: no abrió el panel';
  await sleep(800);
  const g = geo(p);
  return (g.indexOf('FUERA') === 0 ? 'FAIL ventana corta se sale: ' : 'OK ventana corta ') + g;
})()"""

# W17: un solo panel flotante a la vez + clic exterior cierra los chips
JS_UN_PANEL = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  // 1) abrir el selector del composer…
  document.querySelector('.comp-emo').click();
  if (!await wait('.emo-picker')) return 'FAIL: no abrió el panel del composer';
  // 2) …y clic derecho en un mensaje: el del composer debe cerrarse
  const target = document.querySelector('.msgs .msg:not(.mine)');
  if (!target) return 'FAIL: sin mensaje entrante';
  const r = target.querySelector('.bubble').getBoundingClientRect();
  target.dispatchEvent(new MouseEvent('contextmenu',
    { bubbles: true, cancelable: true, clientX: r.left + 10, clientY: r.top + 10 }));
  if (!await wait('.ctx-menu')) return 'FAIL: no abrió el menú contextual';
  if (document.querySelector('.emo-picker')) return 'FAIL: el menú no cerró el panel del composer';
  // 3) abrir los chips: el menú contextual debe cerrarse
  target.querySelectorAll('.b-act')[1].click();
  if (!await wait('.react-picker')) return 'FAIL: no abrieron los chips';
  if (document.querySelector('.ctx-menu')) return 'FAIL: los chips no cerraron el menú';
  // 4) clic fuera: los chips se cierran
  document.querySelector('.msgs').click();
  await sleep(250);
  if (document.querySelector('.react-picker')) return 'FAIL: no cerró con clic exterior';
  return 'OK un solo panel (ctx + chips + composer)';
})()"""

# W17: autocompletado ":fire" → 🔥 y conversión ":pizza:" al enviar
JS_CODIGOS = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  const ta = document.querySelector('.composer-input');
  ta.value = 'fuego :fire';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  const ac = await wait('.emo-ac');
  if (!ac) return 'FAIL: no abrió el autocompletado';
  const row0 = ac.querySelector('.emo-ac-row');
  /* W36a: el emoji de la fila es <img alt="🔥"> (Twemoji), no texto plano */
  const row0Emoji = !!row0.querySelector('img.emo[alt="🔥"]') ||
    row0.textContent.indexOf('🔥') >= 0;
  if (!row0Emoji || row0.textContent.indexOf(':fire:') < 0) {
    return 'FAIL: primer resultado = ' + row0.textContent.trim();
  }
  row0.click();                              // Enter/clic insertan el emoji
  await sleep(250);
  if (ta.value !== 'fuego 🔥') return 'FAIL: no reemplazó el token (' + ta.value + ')';
  if (document.querySelector('.emo-ac')) return 'FAIL: no cerró tras elegir';
  // ":código:" completo se convierte al enviar
  ta.value = 'vamos :pizza: y :joy:';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(150);
  document.querySelector('.comp-row .send-btn').click();
  let enviado = false;
  const t0 = Date.now();
  while (Date.now() - t0 < 7000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    const last = rows[rows.length - 1];
    /* W29b: los emojis salen como <img alt="…"> (no en textContent) */
    if (last &&
        (last.textContent.indexOf('🍕') >= 0 ||
         last.querySelector('.b-text img.emo[alt="🍕"]')) &&
        (last.textContent.indexOf('😂') >= 0 ||
         last.querySelector('.b-text img.emo[alt="😂"]'))) { enviado = true; break; }
    await sleep(150);
  }
  if (!enviado) return 'FAIL: no convirtió :código: al enviar';
  return 'OK códigos (autocomplete + envío)';
})()"""

# W17: el ⋯ de la barra hover abre el menú SIN tapar la burbuja
JS_MENU_ANCLADO = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  const target = document.querySelector('.msgs .msg:not(.mine)');
  if (!target) return 'FAIL: sin mensaje entrante';
  const more = target.querySelector('.b-more');
  if (!more) return 'FAIL: sin botón ⋯ en la barra';
  more.click();
  const ctx = await wait('.ctx-menu');
  if (!ctx) return 'FAIL: ⋯ no abrió el menú';
  await sleep(250);                          // deja medir tras el ajuste
  const cb = target.querySelector('.bubble').getBoundingClientRect();
  const cm = ctx.getBoundingClientRect();
  const tapa = !(cm.right <= cb.left || cm.left >= cb.right ||
                 cm.bottom <= cb.top || cm.top >= cb.bottom);
  if (tapa) {
    return 'FAIL: el menú tapa la burbuja [' +
      Math.round(cm.left) + ',' + Math.round(cm.top) + '→' +
      Math.round(cm.right) + ',' + Math.round(cm.bottom) + '] burbuja [' +
      Math.round(cb.left) + ',' + Math.round(cb.top) + '→' +
      Math.round(cb.right) + ',' + Math.round(cb.bottom) + ']';
  }
  return 'OK menú anclado al lado (' +
    Math.round(cm.left) + ',' + Math.round(cm.top) + ')';
})()"""

# W17: ranking de reacciones — usar 😂 la suba al primer puesto
JS_RANKING = """(async () => {
  """ + W_WAIT + GEO + ABRIR + """
  const target = document.querySelector('.msgs .msg:not(.mine)');
  if (!target) return 'FAIL: sin mensaje entrante';
  target.querySelectorAll('.b-act')[1].click();
  const rp = await wait('.react-picker');
  if (!rp) return 'FAIL: no abrieron los chips';
  const rpCh = function (btn) {                 // W29b: los .rp son <img>
    const im = btn.querySelector('img.emo');
    return im ? im.getAttribute('alt') : btn.textContent.trim();
  };
  const first0 = rpCh(rp.querySelector('.rp'));
  if (first0 !== '👍') return 'FAIL: orden base inicial = ' + first0;
  // reaccionar con 😂 (3º chip por defecto) y verificar que sube al 1º
  rp.querySelectorAll('.rp')[2].click();
  const t0 = Date.now();
  while (Date.now() - t0 < 7000 && !target.querySelector('.react-chip.mine')) {
    await sleep(130);
  }
  if (!target.querySelector('.react-chip.mine')) return 'FAIL: no quedó la reacción';
  target.querySelectorAll('.b-act')[1].click();
  const rp2 = await wait('.react-picker');
  if (!rp2) return 'FAIL: no reabrieron los chips';
  const first1 = rpCh(rp2.querySelector('.rp'));
  if (first1 !== '😂') return 'FAIL: 😂 no subió al 1er puesto (' + first1 + ')';
  return 'OK ranking (👍 → 😂 como más usada)';
})()"""

# W17/W29e: Ajustes → Chat → formato de hora 12h (am/pm)
# (W29e: antes era un interruptor .tgl; ahora es un menú desplegable)
JS_H12 = """(async () => {
  """ + W_WAIT + ABRIR + """
  const t0 = document.querySelector('.ci-time');
  if (!t0) return 'FAIL: sin hora en la lista';
  const antes = t0.textContent.trim();
  if (/(am|pm)/.test(antes)) return 'FAIL: ya venía en 12h (' + antes + ')';
  const gear = await wait('button[title="Ajustes"]');
  gear.click();
  const modal = await wait('.modal.settings');
  if (!modal) return 'FAIL: no abrió Ajustes';
  const tabs = modal.querySelectorAll('.m-tab');
  let chatTab = null;
  for (let i = 0; i < tabs.length; i++) {
    if (tabs[i].textContent.indexOf('Chat') >= 0) { chatTab = tabs[i]; break; }
  }
  if (!chatTab) return 'FAIL: sin pestaña Chat';
  chatTab.click();
  await sleep(250);
  let sel = null;
  const rowsSel = modal.querySelectorAll('.st-row');
  for (let i = 0; i < rowsSel.length; i++) {
    if (rowsSel[i].textContent.indexOf('Formato de hora') >= 0) {
      sel = rowsSel[i].querySelector('select');
      break;
    }
  }
  if (!sel) return 'FAIL: sin desplegable de formato de hora';
  sel.value = '12';                      /* W29e: 12 h en el menú */
  sel.dispatchEvent(new Event('change', { bubbles: true }));
  await sleep(300);
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await sleep(300);
  const t1 = document.querySelector('.ci-time');
  const desp = t1.textContent.trim();
  if (!/(am|pm)/.test(desp)) return 'FAIL: la lista sigue en 24h (' + desp + ')';
  // volver a 24h para no dejar suciedad en la preferencia
  localStorage.removeItem('fm.p.h12');
  return 'OK hora 12h (' + antes + ' → ' + desp + ')';
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    ok = fail = 0

    def step(name, good, detail=""):
        nonlocal ok, fail
        if good:
            ok += 1
            print(f"  ok   {name}  {detail}")
        else:
            fail += 1
            print(f"  FAIL {name}  {detail}")

    stamp = str(int(time.time()))[-7:]
    ua, ub = f"emoa{stamp}", f"emob{stamp}"
    try:
        A = ct.register(a.base, f"{ua}@test.local", ua)
        B = ct.register(a.base, f"{ub}@test.local", ub)
        print(f"→ sembrados: {ua} y {ub}")

        st, res = ct.dm_between(a.base, A["access"], B["access"], ua, ub)
        if st not in (200, 201):
            raise SystemExit(f"✗ dm: {st} {res}")
        cid = res["chat"]["id"]

        largo = ("Mensaje largo para llenar el área de conversación y que "
                 "el último mensaje quede abajo del todo. ") * 3
        seed = [
            ("B", "hola!"),
            ("A", "propio uno. " + largo),
            ("B", "entrante uno. " + largo),
            ("A", "propio dos. " + largo),
            ("B", "entrante dos. " + largo),
            ("A", "propio tres. " + largo),
            ("B", "último mensaje, abajo del todo. " + largo),
        ]
        for who, body in seed:
            tok = A if who == "A" else B
            ct.send(a.base, tok["access"], cid,
                    {"kind": "text", "body": body,
                     "client_msg_id": str(uuid.uuid4())})
        print(f"→ {len(seed)} mensajes sembrados")

        # 0) perfil limpio
        ok0, res0, _, log = ct.run_shot(
            a.base + "/", SHOTS / "emo-0-perfil.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        step("paso0 perfil", ok0 and res0 == "limpia", res0 or log[-400:])

        # 1) sesión inyectada
        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))
        ok1, res1, _, log = ct.run_shot(
            a.base + "/", SHOTS / "emo-1-sesion.png", js=sess_js, wait=300)
        step("paso1 sesión", ok1 and bool(res1), res1 or log[-400:])

        def do(name, js, png):
            okk, ress, _, log = ct.run_shot(
                a.base + "/", SHOTS / png, js=js, wait=400)
            detail = ress if ress else log[-600:]
            step(name, okk and ress is not None and str(ress).startswith("OK"),
                 detail)

        do("paso2 composer geometría", JS_COMP_GEO, "emo-2-composer.png")
        do("paso3 composer funciones", JS_COMP_FUNCS, "emo-3-funciones.png")
        # W17: el ranking va ANTES de las suites que reaccionan, para que
        # fm.react.counts esté limpio y el orden base sea determinista
        do("paso4 ranking de reacciones", JS_RANKING, "emo-4-ranking.png")
        do("paso5 reacción entrante", JS_REACT_LEFT, "emo-5-react-izq.png")
        do("paso6 reacción propia", JS_REACT_MINE, "emo-6-react-propia.png")
        do("paso7 último mensaje", JS_REACT_LAST, "emo-7-react-ultimo.png")
        do("paso8 ventana corta 1000x420", JS_COMP_GEO_CORTO,
           "emo-8-ventana-corta.png")
        # W17
        do("paso9 un solo panel flotante", JS_UN_PANEL, "emo-9-panel-unico.png")
        do("paso10 :código: autocomplete", JS_CODIGOS, "emo-10-codigos.png")
        do("paso11 menú ⋯ anclado", JS_MENU_ANCLADO, "emo-11-menu-anclado.png")
        do("paso12 hora 12h", JS_H12, "emo-12-hora12.png")

        print(f"\nemoji UI: {ok} ok, {fail} fallas")
        sys.exit(1 if fail else 0)
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
