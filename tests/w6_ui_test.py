#!/usr/bin/env python
"""E2E W6: panel de usuario, perfil propio, ajustes y salidas seguras.

Siembra A y B (+ un DM con mensaje) y una cuenta desechable C, y maneja
Firefox headless (BiDi):

  1. panel de usuario → Ajustes: 4 pestañas, toggle de sonido OFF y letra
     Pequeña persisten en la recarga (fm.p.sound / fm.font + pre-paint)
  2. Tu perfil: nombre/estado/bio/preset editados → store + fm.session +
     round-trip contra GET /api/users/me
  3. panel de perfil derecho al tocar la cabecera del DM (datos de B,
     incl. bio y estado) y Esc para cerrarlo
  4. cerrar sesión CON confirmación → login + nada residual de la sesión
  5. eliminar cuenta: zona de peligro → usuario+contraseña tipeados →
     login de C deja de funcionar, /api/users/C → 404, A sigue viva
  6. restaura preferencias por defecto (paso 2) para los otros tests

Uso: server/.venv/bin/python tests/w6_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402  (helpers: register, http, send, run_shot)

SHOTS = Path("/tmp/opencode")
PASS = "w6pass12345"

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

# v-model en inputs necesita el setter nativo + evento input
W_SET = """const setVal = (el, v) => {
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement
                                            : window.HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };"""

JS_PREP = """(() => {
  try {
    localStorage.removeItem('fm.session');
    ['sound', 'typing', 'receipts', 'enter'].forEach(function (k) {
      localStorage.setItem('fm.p.' + k, '1');
    });
    localStorage.setItem('fm.font', 'normal');
  } catch (e) {}
  document.documentElement.setAttribute('data-font', 'normal');
  return 'OK limpio';
})()"""

JS_AJUSTES = """(async () => {
  """ + W_WAIT + """
  const up = await wait('.user-panel');
  if (!up) return 'FAIL: sin panel de usuario';
  const st = document.querySelector('.up-status');
  if (!st || !st.textContent.trim()) return 'FAIL: sin línea de estado';
  const nm = document.querySelector('.up-name');
  if (!nm || !nm.textContent.trim()) return 'FAIL: sin nombre en el panel';

  const gear = await wait('button[title="Ajustes"]');
  if (!gear) return 'FAIL: sin botón Ajustes';
  gear.click();
  const modal = await wait('.modal.settings');
  if (!modal) return 'FAIL: no abrió Ajustes';
  const labels = ['Cuenta', 'Apariencia', 'Chat', 'Atajos'];
  for (let i = 0; i < labels.length; i++) {
    if (modal.textContent.indexOf(labels[i]) < 0) return 'FAIL: falta pestaña ' + labels[i];
  }
  // W8: Cuenta es la ÚLTIMA pestaña (lo de "esconder" el salir ahí)
  const tabs0 = Array.prototype.slice.call(modal.querySelectorAll('.m-tab'));
  if (tabs0[tabs0.length - 1].textContent.trim() !== 'Cuenta') {
    return 'FAIL: Cuenta no es la última pestaña';
  }
  // W8: el salir vive sólo en Ajustes → Cuenta (nada en el panel de usuario)
  if (document.querySelector('.user-panel button[title="Cerrar sesión"]')) {
    return 'FAIL: aún hay botón de salir en el panel de usuario';
  }
  const cuentaTab = tabs0.find(function (t) { return t.textContent.trim() === 'Cuenta'; });
  cuentaTab.click();
  await sleep(200);
  if (modal.textContent.indexOf('Zona de peligro') < 0) return 'FAIL: sin zona de peligro';
  if (!modal.querySelector('.btn-danger')) return 'FAIL: sin botón eliminar cuenta';
  if (!modal.querySelector('button[title="Cerrar sesión"]')) {
    return 'FAIL: sin botón cerrar sesión en Cuenta';
  }

  // pestaña Chat: apagar sonido
  const tabs = Array.prototype.slice.call(modal.querySelectorAll('.m-tab'));
  const chatTab = tabs.find(function (t) { return t.textContent.trim() === 'Chat'; });
  if (!chatTab) return 'FAIL: sin pestaña Chat';
  chatTab.click();
  await sleep(200);
  const snd = document.querySelector('.tgl input');
  if (!snd) return 'FAIL: sin toggles de chat';
  if (!snd.checked) return 'FAIL: el sonido ya estaba apagado';
  snd.click();
  await sleep(200);
  if (localStorage.getItem('fm.p.sound') !== '0') {
    return 'FAIL: fm.p.sound=' + localStorage.getItem('fm.p.sound');
  }

  // pestaña Apariencia: letra pequeña
  const apTab = tabs.find(function (t) { return t.textContent.trim() === 'Apariencia'; });
  if (!apTab) return 'FAIL: sin pestaña Apariencia';
  apTab.click();
  await sleep(200);
  const opts = Array.prototype.slice.call(document.querySelectorAll('.ap-opt'));
  const small = opts.find(function (o) { return o.textContent.trim() === 'Pequeño'; });
  if (!small) return 'FAIL: sin opciones de letra';
  small.click();
  await sleep(200);
  if (document.documentElement.getAttribute('data-font') !== 'small') {
    return 'FAIL: data-font=' + document.documentElement.getAttribute('data-font');
  }
  if (localStorage.getItem('fm.font') !== 'small') return 'FAIL: fm.font sin persistir';

  // Esc cierra (atajo global)
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  await sleep(250);
  if (document.querySelector('.modal.settings')) return 'FAIL: Esc no cerró Ajustes';
  return 'OK ajustes (pestñas, sonido OFF, letra small, Esc)';
})()"""

JS_PERSISTE = """(async () => {
  """ + W_WAIT + """
  // recarga fría: pre-paint reaplica la letra
  if (document.documentElement.getAttribute('data-font') !== 'small') {
    return 'FAIL: la letra no persistió: ' + document.documentElement.getAttribute('data-font');
  }
  const gear = await wait('button[title="Ajustes"]');
  if (!gear) return 'FAIL: sin botón Ajustes';
  gear.click();
  const modal = await wait('.modal.settings');
  if (!modal) return 'FAIL: no abrió Ajustes';
  const tabs = Array.prototype.slice.call(modal.querySelectorAll('.m-tab'));

  // sonido sigue apagado en la nueva carga → lo restauramos
  tabs.find(function (t) { return t.textContent.trim() === 'Chat'; }).click();
  await sleep(200);
  const snd = document.querySelector('.tgl input');
  if (!snd) return 'FAIL: sin toggles';
  if (snd.checked) return 'FAIL: el sonido se reactivó en la recarga';
  snd.click();
  await sleep(150);
  if (localStorage.getItem('fm.p.sound') !== '1') return 'FAIL: no restauró el sonido';

  // letra: Pequeña quedó marcada (estado del store) → volver a Normal
  tabs.find(function (t) { return t.textContent.trim() === 'Apariencia'; }).click();
  await sleep(200);
  const opts = Array.prototype.slice.call(document.querySelectorAll('.ap-opt'));
  const small = opts.find(function (o) { return o.textContent.trim() === 'Pequeño'; });
  const normal = opts.find(function (o) { return o.textContent.trim() === 'Normal'; });
  if (!small || !normal) return 'FAIL: sin opciones de letra';
  if (!small.classList.contains('on')) return 'FAIL: Pequeño no marcada tras recargar';
  normal.click();
  await sleep(150);
  if (document.documentElement.getAttribute('data-font') !== 'normal') return 'FAIL: font no restaurada';
  if (localStorage.getItem('fm.font') !== 'normal') return 'FAIL: fm.font no restaurado';

  const close = document.querySelector('.modal.settings header .icon-btn');
  if (!close) return 'FAIL: sin botón cerrar';
  close.click();
  await sleep(200);
  if (document.querySelector('.modal.settings')) return 'FAIL: no cerró Ajustes';
  return 'OK persistencia y preferencias restauradas';
})()"""

JS_PERFIL = """(async () => {
  """ + W_WAIT + """
  """ + W_SET + """
  const me = await wait('.up-main');
  if (!me) return 'FAIL: sin botón Tu perfil';
  me.click();
  const view = await wait('.modal.meprof:not(.mp-edit)');
  if (!view) return 'FAIL: no abrió Tu perfil';

  // W27b: la vista es SOLO lectura (ficha); el formulario vive en otro
  // modal y el lápiz es la puerta de entrada.
  if (!view.querySelector('.mp-view')) return 'FAIL: sin ficha de solo lectura';
  if (view.querySelector('input[placeholder="Tu nombre"]')) {
    return 'FAIL: el formulario no debería estar en la vista';
  }
  const pencil = view.querySelector('.mp-edit-open');
  if (!pencil) return 'FAIL: sin botón lápiz de editar';
  pencil.click();
  const modal = await wait('.modal.mp-edit', 4000);
  if (!modal) return 'FAIL: no abrió Editar perfil';

  const name = modal.querySelector('input[placeholder="Tu nombre"]');
  const status = modal.querySelector('input[placeholder="jugando a algo…"]');
  const bio = modal.querySelector('textarea');
  if (!name || !status || !bio) return 'FAIL: campos de perfil faltantes';
  setVal(name, 'Editado W6');
  setVal(status, 'probando ajustes');
  setVal(bio, 'Bio de prueba W6');
  const chip = Array.prototype.slice.call(modal.querySelectorAll('.ap-chip'))
    .find(function (c) { return c.textContent.trim() === 'En línea'; });
  if (!chip) return 'FAIL: sin presets de estado';
  chip.click();
  await sleep(200);

  const save = Array.prototype.slice.call(modal.querySelectorAll('.m-foot .btn'))
    .find(function (b) { return !b.classList.contains('btn-ghost'); });
  if (!save || save.disabled) return 'FAIL: guardar deshabilitado';
  save.click();

  const t0 = Date.now();
  while (Date.now() - t0 < 8000 &&
         (!__fm.store.user || __fm.store.user.display_name !== 'Editado W6')) {
    await sleep(150);
  }
  if (!__fm.store.user || __fm.store.user.display_name !== 'Editado W6') {
    return 'FAIL: store sin actualizar';
  }
  if (__fm.store.user.status_preset !== 'online') {
    return 'FAIL: preset=' + __fm.store.user.status_preset;
  }
  /* W37c: el modal cierra con la transición "veil" — esperar a que
     salga del DOM en vez de comprobarlo al instante. */
  const tc = Date.now();
  while (Date.now() - tc < 3000 &&
         document.querySelector('.modal.mp-edit')) {
    await sleep(100);
  }
  if (document.querySelector('.modal.mp-edit')) return 'FAIL: no cerró Editar perfil';

  // al guardar vuelve la ficha "Tu perfil" (sin formulario) con el
  // nombre ya actualizado
  const back = document.querySelector('.modal.meprof:not(.mp-edit)');
  if (!back) return 'FAIL: no volvió a Tu perfil';
  if (back.querySelector('input[placeholder="Tu nombre"]')) {
    return 'FAIL: el formulario se quedó en la vista';
  }
  if (back.textContent.indexOf('Editado W6') < 0) {
    return 'FAIL: la ficha no muestra el nombre nuevo';
  }
  const x = back.querySelector('header .icon-btn:last-of-type');
  if (x) x.click();
  await sleep(200);
  if (document.querySelector('.modal.meprof')) return 'FAIL: no cerró el modal';

  // round-trip: el servidor lo guardó y fm.session quedó al día
  const sess = JSON.parse(localStorage.getItem('fm.session'));
  if (!sess || !sess.user || sess.user.display_name !== 'Editado W6') {
    return 'FAIL: fm.session sin actualizar';
  }
  const r = await fetch('/api/users/me', {
    headers: { Authorization: 'Bearer ' + sess.access },
  });
  if (!r.ok) return 'FAIL: /api/users/me HTTP ' + r.status;
  const mu = (await r.json()).user;
  if (mu.display_name !== 'Editado W6') return 'FAIL: /me display_name=' + mu.display_name;
  if (mu.bio !== 'Bio de prueba W6') return 'FAIL: /me bio=' + mu.bio;
  if (mu.status_text !== 'probando ajustes') return 'FAIL: /me status=' + mu.status_text;
  if (mu.status_preset !== 'online') return 'FAIL: /me preset=' + mu.status_preset;
  return 'OK perfil editado y persistido (store, sesión y servidor)';
})()"""

JS_PANEL = """(async () => {
  """ + W_WAIT + """
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats en la lista';
  item.click();
  if (!await wait('.chat-head .ch-col', 10000)) return 'FAIL: no abrió la conversación';

  // W7: el panel derecho es la INFO del chat (abierto por defecto en
  // pantallas anchas) con los datos básicos del contacto.
  const info = await wait('.profile-panel', 8000);
  if (!info) return 'FAIL: sin panel de info del chat';
  const t0 = Date.now();
  while (Date.now() - t0 < 8000 &&
         info.textContent.indexOf('Bio de prueba B') < 0) await sleep(120);
  const itxt = info.textContent;
  if (itxt.indexOf('Beto W6') < 0) return 'FAIL: info sin nombre de B';
  if (itxt.indexOf('@' + '__BUSER__') < 0) return 'FAIL: info sin @usuario';
  if (itxt.indexOf('Bio de prueba B') < 0) return 'FAIL: info sin bio';
  // W39: el panel ya NO tiene botón "Ver perfil completo" — queda la
  // nota centrada "Cifrado de extremo a extremo" con la llave.
  if (info.querySelector('.pp-foot')) return 'FAIL: quedó botón Ver perfil';
  if (!info.querySelector('.pp-e2e-center')) return 'FAIL: sin nota de cifrado';
  if (itxt.indexOf('Cifrado de extremo a extremo') < 0)
    return 'FAIL: nota de cifrado sin texto';

  // El clic en la cabecera abre la VENTANA FLOTANTE con el perfil completo.
  document.querySelector('.chat-head .ch-col').click();
  const modal = await wait('.modal.pmodal', 8000);
  if (!modal) return 'FAIL: no abrió la ventana de perfil';
  const t1 = Date.now();
  while (Date.now() - t1 < 8000 && !modal.querySelector('.pp-name')) await sleep(120);
  if (!modal.querySelector('.pp-name')) return 'FAIL: sin datos en la ventana';
  const txt = modal.textContent;
  if (txt.indexOf('Beto W6') < 0) return 'FAIL: sin nombre de B';
  if (txt.indexOf('@' + '__BUSER__') < 0) return 'FAIL: sin @usuario';
  if (txt.indexOf('Bio de prueba B') < 0) return 'FAIL: sin bio';
  // W27-6: B está desconectado → la píldora dice "Desconectado" aunque
  // tenga estado guardado ("jugando al ajedrez" solo se ve en línea).
  if (txt.indexOf('Desconectado') < 0) return 'FAIL: sin estado';
  if (txt.indexOf('Miembro desde') < 0) return 'FAIL: sin fecha de alta';
  // W7: con este directo YA abierto no se ofrece "Mensaje".
  if (modal.querySelector('.pp-foot .btn')) {
    return 'FAIL: ofrece Mensaje con el DM activo';
  }

  // Esc cierra la ventana flotante y deja el panel de info.
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  await sleep(300);
  if (document.querySelector('.modal.pmodal')) return 'FAIL: Esc no cerró la ventana';
  if (!document.querySelector('.profile-panel')) return 'FAIL: Esc cerró el panel de info';

  // Un segundo Esc cierra el panel de info.
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
  await sleep(300);
  if (document.querySelector('.profile-panel')) return 'FAIL: Esc no cerró el panel de info';
  return 'OK panel info + ventana de perfil de __BUSER__';
})()"""

JS_LOGOUT = """(async () => {
  """ + W_WAIT + """
  const up = await wait('.user-panel');
  if (!up) return 'FAIL: sin panel de usuario';

  // espía de /api/*: cuándo se pidió y cuándo respondió cada cosa
  const flog = [];
  const t0spy = Date.now();
  const of = window.fetch;
  window.fetch = function () {
    const u = String(arguments[0]);
    if (u.indexOf('/api/') < 0) return of.apply(this, arguments);
    const tag = '@' + (Date.now() - t0spy) + 'ms ' + u.split('?')[0];
    flog.push('>' + tag);
    const p = of.apply(this, arguments);
    const q = p.then(function (r) {
      flog.push('<' + tag + ' ' + r.status);
      return r;
    }, function (e) {
      flog.push('<' + tag + ' ERR ' + e);
      throw e;
    });
    return q;
  };

  // W8: el salir está escondido en Ajustes → última pestaña (Cuenta)
  const gear = await wait('button[title="Ajustes"]');
  if (!gear) return 'FAIL: sin botón Ajustes';
  gear.click();
  const smod = await wait('.modal.settings');
  if (!smod) return 'FAIL: no abrió Ajustes';
  const ctabs = Array.prototype.slice.call(smod.querySelectorAll('.m-tab'));
  const ctab = ctabs.find(function (t) { return t.textContent.trim() === 'Cuenta'; });
  if (!ctab) return 'FAIL: sin pestaña Cuenta';
  ctab.click();
  await sleep(200);
  const out = document.querySelector('button[title="Cerrar sesión"]');
  if (!out) return 'FAIL: sin botón cerrar sesión en Cuenta';
  out.click();
  const box = await wait('.modal.confirm');
  if (!box) return 'FAIL: sin caja de confirmación';
  if (box.textContent.indexOf('Cerrar sesión') < 0) return 'FAIL: sin advertencia de logout';
  const ok = Array.prototype.slice.call(box.querySelectorAll('.m-foot .btn'))
    .find(function (b) { return !b.classList.contains('btn-ghost'); });
  if (!ok || ok.disabled) return 'FAIL: confirmar deshabilitado';

  // traza cada 50ms: chats/usuario/sesión/ruta/ws — si algo repuebla la
  // lista tras el clear, el FAIL lo muestra con marcas de tiempo.
  const trace = [];
  let last = '';
  const tClick = Date.now();
  const iv = setInterval(function () {
    const s = __fm.store;
    const sig = 'ch' + s.chats.length + '/u' + (s.user ? 1 : 0) +
      '/s' + (s.hasSession ? 1 : 0) + '/' + s.route + '/' + s.ws +
      '/dom' + (document.querySelector('#l-id') ? 'L' : 'A');
    if (sig !== last) { trace.push((Date.now() - tClick) + 'ms ' + sig); last = sig; }
  }, 50);
  ok.click();

  const t0 = Date.now();
  while (Date.now() - t0 < 8000 && !document.querySelector('#l-id')) await sleep(120);
  await sleep(400);
  clearInterval(iv);
  if (!document.querySelector('#l-id')) {
    return 'FAIL: no volvió al login | ' + trace.join(' ~ ') + ' || ' + flog.join(' ');
  }
  if (localStorage.getItem('fm.session') !== null) return 'FAIL: quedó fm.session';
  const s = __fm.store;
  if (s.user !== null) return 'FAIL: usuario residual en store';
  if (s.chats.length !== 0) {
    return 'FAIL: chats residuales: ' + s.chats.length + ' | ' + trace.join(' ~ ') +
      ' || ' + flog.join(' ');
  }
  if (s.activeChatId !== 0) return 'FAIL: activeChatId=' + s.activeChatId;
  if (s.settingsOpen || s.meProfileOpen || s.profile || s.confirmBox || s.newChatOpen) {
    return 'FAIL: paneles residuales tras logout';
  }
  return 'OK logout limpio (login + store vacío)';
})()"""

JS_ELIMINAR = """(async () => {
  """ + W_WAIT + """
  """ + W_SET + """
  const gear = await wait('button[title="Ajustes"]');
  if (!gear) return 'FAIL: sin botón Ajustes';
  gear.click();
  const modal = await wait('.modal.settings');
  if (!modal) return 'FAIL: no abrió Ajustes';
  // W8: la zona de peligro vive en la última pestaña (Cuenta)
  const tabs = Array.prototype.slice.call(modal.querySelectorAll('.m-tab'));
  const ctab = tabs.find(function (t) { return t.textContent.trim() === 'Cuenta'; });
  if (!ctab) return 'FAIL: sin pestaña Cuenta';
  ctab.click();
  await sleep(200);
  const del = await wait('.btn-danger');
  if (!del) return 'FAIL: sin botón eliminar cuenta';
  if (del.textContent.indexOf('Eliminar mi cuenta') < 0) return 'FAIL: texto de peligro';
  del.scrollIntoView();
  del.click();
  const box = await wait('.modal.confirm');
  if (!box) return 'FAIL: sin caja de confirmación';
  if (box.textContent.indexOf('PERMANENTE') < 0) return 'FAIL: sin advertencia de borrado';
  const inputs = box.querySelectorAll('input');
  if (inputs.length < 2) return 'FAIL: sin campos usuario/contraseña';
  setVal(inputs[0], '__CUSER__');
  setVal(inputs[1], '__CPASS__');
  await sleep(300);
  const ok = Array.prototype.slice.call(box.querySelectorAll('.m-foot .btn'))
    .find(function (b) { return !b.classList.contains('btn-ghost'); });
  if (!ok) return 'FAIL: sin botón de confirmación';
  if (ok.disabled) return 'FAIL: confirmar quedó deshabilitado';
  ok.click();

  const t0 = Date.now();
  while (Date.now() - t0 < 12000 && !document.querySelector('#l-id')) await sleep(150);
  if (!document.querySelector('#l-id')) return 'FAIL: no volvió al login tras eliminar';
  if (localStorage.getItem('fm.session') !== null) return 'FAIL: quedó fm.session';
  if (__fm.store.user !== null) return 'FAIL: usuario residual tras eliminar';
  if (__fm.store.chats.length !== 0) return 'FAIL: chats residuales';
  return 'OK cuenta eliminada con confirmación y sesión limpia';
})()"""


def shot(base, out, js, wait=400, label=""):
    ok, js_res, _, log = ct.run_shot(f"{base}/", SHOTS / out, js=js, wait=wait)
    print(f"{label}:", js_res or "(sin jsres)")
    if not ok or not js_res or not str(js_res).startswith("OK"):
        print(log[-1800:])
        raise SystemExit(f"✗ falló {label}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    stamp = str(int(time.time()))[-7:]
    user_a = f"w6a{stamp}"[:20]
    user_b = f"w6b{stamp}"[:20]
    user_c = f"w6c{stamp}"[:20]
    try:
        A = ct.register(a.base, f"{user_a}@test.local", user_a, PASS)
        B = ct.register(a.base, f"{user_b}@test.local", user_b, PASS)
        C = ct.register(a.base, f"{user_c}@test.local", user_c, PASS)
        print(f"→ sembrados: {user_a} (A), {user_b} (B), {user_c} (C, desechable)")

        # perfil de B para el panel derecho
        st, res = ct.http("PUT", a.base + "/api/auth/profile",
                          {"display_name": "Beto W6", "bio": "Bio de prueba B",
                           "status_text": "jugando al ajedrez", "status_preset": "busy"},
                          token=B["access"])
        if st != 200:
            raise SystemExit(f"✗ perfil B: {st} {res}")

        # DM A↔B con un mensaje (para abrir la conversación)
        st, res = ct.http("POST", a.base + "/api/chats/dm",
                          {"username": user_b}, token=A["access"])
        if st != 201:
            raise SystemExit(f"✗ dm: {st} {res}")
        ct.send(a.base, A["access"], res["chat"]["id"],
                {"kind": "text", "body": "hola B, esto es W6"})

        sess_a = json.dumps({"access": A["access"], "refresh": A["refresh"],
                             "user": A["user"], "pendingEmail": ""})
        sess_c = json.dumps({"access": C["access"], "refresh": C["refresh"],
                             "user": C["user"], "pendingEmail": ""})
        # inyector propio (el JS_INJECT de ct no devuelve prefijo "OK")
        def inj(sess_json):
            payload = sess_json.replace("\\", "\\\\").replace("'", "\\'")
            return ("(() => { localStorage.setItem('fm.session', '" + payload +
                    "'); return 'OK sesión inyectada'; })()")

        # 0) perfil limpio
        shot(a.base, "w6-0-prep.png", JS_PREP, wait=200, label="paso0 prep")
        # 1) inyectar sesión de A
        shot(a.base, "w6-1-sesion.png", inj(sess_a), wait=300, label="paso1 sesión A")
        # 2) panel de usuario + Ajustes (tabs, sonido OFF, letra small, Esc)
        shot(a.base, "w6-2-ajustes.png", JS_AJUSTES, wait=900, label="paso2 ajustes")
        # 3) recarga: persistencia + restauración de preferencias
        shot(a.base, "w6-3-persiste.png", JS_PERSISTE, wait=900, label="paso3 persistencia")
        # 4) editar Tu perfil → round-trip
        shot(a.base, "w6-4-perfil.png", JS_PERFIL, wait=900, label="paso4 mi perfil")
        # 5) panel de perfil derecho con los datos de B
        panel_js = JS_PANEL.replace("__BUSER__", user_b)
        shot(a.base, "w6-5-panel.png", panel_js, wait=900, label="paso5 panel perfil")
        # 6) logout con confirmación → pantalla principal sin rastro
        shot(a.base, "w6-6-logout.png", JS_LOGOUT, wait=900, label="paso6 logout")
        # 7) inyectar C (desechable) para probar la zona de peligro
        shot(a.base, "w6-7-sesionC.png", inj(sess_c), wait=300, label="paso7 sesión C")
        # 8) eliminar cuenta con usuario+contraseña tipeados
        del_js = (JS_ELIMINAR.replace("__CUSER__", user_c)
                  .replace("__CPASS__", PASS))
        shot(a.base, "w6-8-eliminar.png", del_js, wait=900, label="paso8 eliminar")

        # 9) verificaciones por API: C muerta, perfil 404, A intacta
        # W30e: el logout del paso6 revoca los tokens de A (token_version),
        # así que primero se re-loguea para obtener un access vigente.
        st, _ = ct.http("POST", a.base + "/api/auth/login",
                        {"identifier": user_c, "password": PASS})
        if st == 200:
            raise SystemExit("✗ la cuenta C sigue viva tras eliminarla")
        st, res_a = ct.http("POST", a.base + "/api/auth/login",
                            {"identifier": user_a, "password": PASS})
        if st != 200:
            raise SystemExit(f"✗ A quedó dañada tras borrar a C: {st}")
        st, res = ct.http("GET", a.base + f"/api/users/{user_c}",
                          token=res_a["tokens"]["access"])
        if st != 404:
            raise SystemExit(f"✗ perfil de C debería ser 404: {st} {res}")
        print("paso9 api: C eliminada (login≠200, perfil 404), A sigue viva")

        print("✓ W6 E2E completo → " + ", ".join(
            str(SHOTS / n) for n in
            ("w6-2-ajustes.png", "w6-4-perfil.png", "w6-5-panel.png",
             "w6-8-eliminar.png")))
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
