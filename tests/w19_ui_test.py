#!/usr/bin/env python
"""E2E W19: lote de mejoras del chat (pedido del chat).

  1. sidebar colapsable: el hamburger lo contrae (ancho ~0), el del
     chat-header lo devuelve y la preferencia persiste
  2. foto de fondo: se elige (se achica a data-URL), se aplica la clase
     .wallimg + background-image en .msgs y "Quitar foto" la borra
  3. Ctrl+V: un archivo pegado crea la burbuja de subida (y por REST
     queda confirmado como mensaje con media)
  4. hora: la hora NO aparece en la burbuja pendiente (solo reloj) y sí
     tras confirmarse el envío
  5. editar (⋯ → Editar → Guardar: cuerpo nuevo + chip "editado") y
     eliminar (⋯ → Eliminar → confirmación → se va)
  6. puntos de "escribiendo…" centrados (burbuja compacta), aviso claro
     del micrófono sin contexto seguro y chips de reacción en píldora
  7. los puntos de "escribiendo…" bajan la vista solos si estás cerca
     del final; leyendo historial no arrastran la posición

Uso: server/.venv/bin/python tests/w19_ui_test.py [--base http://127.0.0.1:8899]
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

# PNG rojo de 1x1 para simular archivos (paste y foto de fondo)
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
  };"""

JS_SIDE = """(async () => {
  """ + W_WAIT + """
  const err = await openChat();
  if (err) return err;
  const aside = document.querySelector('.sidebar');
  const w0 = aside.getBoundingClientRect().width;
  if (w0 < 200) return 'FAIL: sidebar inicial angosto (' + w0 + ')';
  const fold = document.querySelector('.side-fold');
  if (!fold) return 'FAIL: sin botón de contraer';
  fold.click();
  await sleep(250);
  const w1 = aside.getBoundingClientRect().width;
  if (w1 > 4) return 'FAIL: no colapsó (' + w1 + ')';
  const open = document.querySelector('.chat-head .side-open');
  if (!open) return 'FAIL: sin hamburger en el chat-header';
  if (getComputedStyle(open).display === 'none') {
    return 'FAIL: el hamburger no se muestra con el sidebar colapsado';
  }
  if (localStorage.getItem('fm.side') !== '1') return 'FAIL: no persistió';
  open.click();
  await sleep(250);
  const w2 = aside.getBoundingClientRect().width;
  if (w2 < 200) return 'FAIL: no se devolvió (' + w2 + ')';
  if (getComputedStyle(open).display !== 'none') {
    return 'FAIL: el hamburger sigue visible con el sidebar abierto';
  }
  if (localStorage.getItem('fm.side') !== '0') return 'FAIL: no persistió la apertura';
  return 'OK colapso (' + Math.round(w0) + '→' + Math.round(w1) + '→' + Math.round(w2) + ')';
})()"""

JS_WALL = """(async () => {
  """ + W_WAIT + """
  const err = await openChat();
  if (err) return err;
  const gear = document.querySelector('.user-panel .icon-btn[title="Ajustes"]');
  if (!gear) return 'FAIL: sin engranaje de ajustes';
  gear.click();
  /* W20: la foto vive en el panel dedicado, abierto desde Ajustes */
  const openBtn = await wait('.ap-wallrow .btn', 6000);
  if (!openBtn) return 'FAIL: sin botón Personalizar fondo';
  openBtn.click();
  const inp = await wait('.ap-wall-input', 6000);
  if (!inp) return 'FAIL: sin input de foto de fondo';
  /* W20: la preview trae la conversación de ejemplo (Carlos/Javier) */
  const prev = document.querySelector('.wp-prev');
  if (!prev || prev.textContent.indexOf('Carlos') < 0 ||
      prev.textContent.indexOf('Javier') < 0) {
    return 'FAIL: la preview no trae a Carlos y Javier';
  }
  if (prev.textContent.indexOf('6:10 p.m.') < 0) return 'FAIL: sin horas de ejemplo';
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
    return 'FAIL: no se aplicó la clase .wallimg';
  }
  if ((localStorage.getItem('fm.wallimg') || '').slice(0, 5) !== 'data:') {
    return 'FAIL: no persistió la foto';
  }
  const bi = getComputedStyle(document.querySelector('.wall-preview'), '::before')
    .backgroundImage;
  if (bi.indexOf('url(') < 0) return 'FAIL: .chat-pane sin foto de fondo (' + bi + ')';
  const del = Array.prototype.slice
    .call(document.querySelectorAll('.wp-row .btn'))
    .filter(function (b) { return b.textContent.trim() === 'Quitar foto'; })[0];
  if (!del) return 'FAIL: sin botón Quitar foto';
  del.click();
  await sleep(300);
  if (document.documentElement.classList.contains('wallimg')) return 'FAIL: no se quitó la clase';
  if (localStorage.getItem('fm.wallimg')) return 'FAIL: siguió en localStorage';
  return 'OK panel de fondo (preview + foto + quitar)';
})()"""

JS_PASTE = """(async () => {
  """ + W_WAIT + """
  const err = await openChat();
  if (err) return err;
  const ta = document.querySelector('.composer-input');
  ta.focus();
  const bin = atob('""" + PNG1 + """');
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  const f = new File([arr], 'pegado.png', { type: 'image/png' });
  const ev = new Event('paste', { bubbles: true, cancelable: true });
  ev.clipboardData = { items: [{ kind: 'file', getAsFile: function () { return f; } }] };
  document.dispatchEvent(ev);
  /* una imagen sola abre la ficha de adjunto (W23): se manda con Enter
     en el compositor (con o sin texto) */
  const strip = await wait('.cap-strip', 5000);
  if (!strip) return 'FAIL: el Ctrl+V no abrió la tira de adjunto';
  ta.focus();
  ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  const frame = await wait('.msgs .b-media', 8000);   /* subiendo o ya subida */
  if (!frame) return 'FAIL: el Ctrl+V no creó burbuja de archivo';
  await sleep(1500);                    // deja terminar la subida
  return 'OK Ctrl+V sube archivos';
})()"""

JS_TIME_EDIT_DEL = """(async () => {
  """ + W_WAIT + """
  const err = await openChat();
  if (err) return err;
  /* reloj: demorar el POST para observar la burbuja pendiente */
  const ofetch = window.fetch;
  window.fetch = function () {
    const args = arguments;
    return new Promise(function (res, rej) {
      setTimeout(function () { ofetch.apply(window, args).then(res, rej); }, 900);
    });
  };
  const lastMine = function () {
    const n = document.querySelectorAll('.msgs .msg.mine');
    return n[n.length - 1];
  };
  const ta = document.querySelector('.composer-input');
  const send = document.querySelector('.comp-row .send-btn');
  ta.value = 'mensaje con hora';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(60);
  send.click();
  await sleep(250);                     // a mitad del vuelo (pendiente)
  const pend = lastMine();
  if (!pend) return 'FAIL: sin burbuja pendiente';
  if (pend.querySelector('.b-time')) return 'FAIL: la hora aparece antes de enviar';
  if (!pend.querySelector('.t-pend')) return 'FAIL: sin ícono de pendiente';
  const t0 = Date.now();
  while (Date.now() - t0 < 4000 && !lastMine().querySelector('.b-time')) await sleep(100);
  if (!lastMine().querySelector('.b-time')) return 'FAIL: la hora no aparece tras enviar';
  window.fetch = ofetch;
  /* editar vía ⋯ */
  const more = lastMine().querySelector('.b-more');
  if (!more) return 'FAIL: sin botón ⋯';
  more.click();
  await sleep(200);
  const itEdit = Array.prototype.slice.call(document.querySelectorAll('.ctx-item'))
    .filter(function (x) { return x.textContent.indexOf('Editar') >= 0; })[0];
  if (!itEdit) return 'FAIL: sin opción Editar';
  itEdit.click();
  await sleep(200);
  const edt = document.querySelector('.b-editform textarea');
  if (!edt) return 'FAIL: sin formulario de edición';
  edt.value = 'mensaje editado en w19';
  edt.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(80);
  const save = Array.prototype.slice.call(document.querySelectorAll('.b-editform .btn'))
    .filter(function (b) { return b.textContent.indexOf('Guardar') >= 0; })[0];
  if (!save) return 'FAIL: sin botón Guardar';
  save.click();
  await sleep(700);
  if (lastMine().textContent.indexOf('mensaje editado en w19') < 0) return 'FAIL: no se editó';
  if (!lastMine().querySelector('.b-edit')) return 'FAIL: sin chip "editado"';
  /* eliminar vía ⋯ */
  const more2 = lastMine().querySelector('.b-more');
  more2.click();
  await sleep(200);
  const itDel = Array.prototype.slice.call(document.querySelectorAll('.ctx-item'))
    .filter(function (x) { return x.textContent.indexOf('Eliminar') >= 0; })[0];
  if (!itDel) return 'FAIL: sin opción Eliminar';
  itDel.click();
  await sleep(300);
  const cf = document.querySelector('.modal.confirm');
  if (!cf) return 'FAIL: sin confirmación';
  const okBtn = cf.querySelector('.m-foot .btn:last-child');
  if (!okBtn) return 'FAIL: sin botón de confirmar';
  okBtn.click();
  await sleep(800);
  const txt = document.querySelector('.msgs').textContent;
  if (txt.indexOf('mensaje editado en w19') >= 0) return 'FAIL: el mensaje no se borró';
  return 'OK hora pendiente + editar + eliminar';
})()"""

JS_DOTS_MIC_CHIP = """(async () => {
  """ + W_WAIT + """
  const err = await openChat();
  if (err) return err;
  /* chips de reacción: píldora y alto decente */
  const chip = document.querySelector('.react-chip');
  if (!chip) return 'FAIL: sin chip de reacción';
  const ccs = getComputedStyle(chip);
  if (parseFloat(ccs.borderTopLeftRadius) < 12) {
    return 'FAIL: chip sin píldora (' + ccs.borderTopLeftRadius + ')';
  }
  if (parseFloat(ccs.height) < 25) return 'FAIL: chip bajo (' + ccs.height + ')';
  /* puntos de "escribiendo…" compactos y centrados */
  document.querySelector('.msgs').insertAdjacentHTML('beforeend',
    '<div class="msg theirs tight" id="w19-dots"><div class="bubble dots">' +
    '<i></i><i></i><i></i></div></div>');
  const dh = document.querySelector('#w19-dots .bubble').getBoundingClientRect().height;
  if (dh > 30) return 'FAIL: burbuja de puntos alta (' + dh + ')';
  document.querySelector('#w19-dots').remove();
  /* micrófono sin contexto seguro: aviso claro, no "navegador no soporta" */
  try {
    Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true });
    Object.defineProperty(window, 'isSecureContext', { value: false, configurable: true });
  } catch (e) { return 'FAIL: no se pudo simular contexto inseguro'; }
  const mic = document.querySelector('.comp-mic');
  if (!mic) return 'FAIL: sin botón de micrófono';
  mic.click();
  await sleep(400);
  const toasts = document.querySelector('.toasts');
  if (!toasts || toasts.textContent.indexOf('HTTPS') < 0) {
    return 'FAIL: sin aviso de HTTPS (' + (toasts ? toasts.textContent : 'sin toasts') + ')';
  }
  return 'OK chips + puntos + aviso de micrófono';
})()"""

# W25: los puntos de "escribiendo…" bajan la vista solos SOLO si estás
# cerca del final; leyendo historial no deben arrastrar la posición.
JS_TYPING_SCROLL = """(async () => {
  """ + W_WAIT + """
  const err = await openChat();
  if (err) return err;
  const cid = __fm.store.activeChatId;
  const sc = document.querySelector('.msgs');
  const maxScroll = () => sc.scrollHeight - sc.clientHeight;
  if (maxScroll() < 160)
    return 'FAIL: la lista apenas scrollea (max=' + maxScroll() + ')';
  /* 1) cerca del final: al aparecer los puntos, la vista baja hasta ellos */
  sc.scrollTop = maxScroll();
  await sleep(200);              /* onScroll marca stick=true */
  __fm.store.typing[cid] = { 999: { u: 'w19', exp: Date.now() + 99999 } };
  const dots = await wait('.msgs .msg.tight .dots', 3000);
  if (!dots) return 'FAIL: no aparecieron los puntos de escribiendo';
  await sleep(300);              /* watcher: nextTick + scrollBottom */
  const rest = maxScroll() - sc.scrollTop;
  if (rest > 2) return 'FAIL: no bajó con los puntos (faltan ' + rest + 'px)';
  const dr = dots.getBoundingClientRect(), scr = sc.getBoundingClientRect();
  if (dr.bottom > scr.bottom + 1) return 'FAIL: los puntos quedaron fuera de vista';
  /* 2) lejos del final: NO debe arrastrar la vista hacia abajo */
  delete __fm.store.typing[cid];
  await sleep(200);
  sc.scrollTop = Math.round(maxScroll() / 2);   /* punto medio del rango */
  await sleep(250);              /* onScroll marca stick=false */
  const top0 = sc.scrollTop;
  if (maxScroll() - top0 < 80)
    return 'FAIL: no quedó lejos del final para la prueba';
  __fm.store.typing[cid] = { 999: { u: 'w19', exp: Date.now() + 99999 } };
  await sleep(700);
  if (Math.abs(sc.scrollTop - top0) > 2) {
    return 'FAIL: arrastró la vista (' + top0 + ' → ' + sc.scrollTop + ')';
  }
  delete __fm.store.typing[cid];
  return 'OK escribiendo… baja solo cerca del final';
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
    ua, ub = f"w19a{stamp}", f"w19b{stamp}"
    try:
        A = ct.register(a.base, f"{ua}@test.local", ua)
        B = ct.register(a.base, f"{ub}@test.local", ub)
        print(f"→ sembrados: {ua}, {ub}")

        st, res = ct.dm_between(a.base, A["access"], B["access"], ua, ub)
        if st not in (200, 201):
            raise SystemExit(f"✗ dm: {st} {res}")
        dm = res["chat"]["id"]

        m_b = ct.send(a.base, B["access"], dm,
                      {"kind": "text", "body": "hola", "client_msg_id": str(uuid.uuid4())})
        m_a = ct.send(a.base, A["access"], dm,
                      {"kind": "text", "body": "pregunta", "client_msg_id": str(uuid.uuid4())})
        st, res = ct.http("POST", f"{a.base}/api/chats/{dm}/reactions/{m_a['id']}",
                          {"emoji": "🔥"}, token=B["access"])
        if st not in (200, 201):
            raise SystemExit(f"✗ reacción: {st} {res}")
        print(f"→ dm {dm} con semillas y reacción")

        # perfil limpio + sesión inyectada (una sola vez; los shots
        # siguientes reutilizan el mismo perfil de Firefox)
        ok0, res0, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-0-perfil.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        step("paso0 perfil", ok0 and res0 == "limpia", res0 or log[-300:])
        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))
        ok1, res1, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-0-sesion.png", js=sess_js, wait=300)
        step("paso0 sesión", ok1 and bool(res1), res1 or log[-300:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-1-colapso.png", js=JS_SIDE, wait=400)
        step("paso1 sidebar colapsable", okk and str(ress).startswith("OK"),
             ress if ress else log[-400:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-2-fondo.png", js=JS_WALL, wait=400)
        step("paso2 foto de fondo", okk and str(ress).startswith("OK"),
             ress if ress else log[-400:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-3-pegar.png", js=JS_PASTE, wait=400)
        step("paso3 Ctrl+V", okk and str(ress).startswith("OK"),
             ress if ress else log[-400:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-4-hora.png", js=JS_TIME_EDIT_DEL, wait=400)
        step("paso4 hora + editar + eliminar", okk and str(ress).startswith("OK"),
             ress if ress else log[-400:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-5-chips.png", js=JS_DOTS_MIC_CHIP, wait=400)
        step("paso5 chips + puntos + micrófono", okk and str(ress).startswith("OK"),
             ress if ress else log[-400:])

        # W25: semillas para que la lista sea scrolleable de verdad. El
        # bucket de mensajes (burst 5, ~0.6/s) es por usuario: se alternan
        # A y B con 1 s de pausa (2 s por usuario → sin 429 ni spam).
        for i in range(24):
            who = B if i % 2 else A
            ct.send(a.base, who["access"], dm,
                    {"kind": "text", "body": f"semilla {i}",
                     "client_msg_id": str(uuid.uuid4())})
            time.sleep(1.0)

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "w19-6-typing.png", js=JS_TYPING_SCROLL, wait=400)
        step("paso5b escribiendo… auto-scroll", okk and str(ress).startswith("OK"),
             ress if ress else log[-400:])

        # verificación REST final: la pegada quedó como imagen, el
        # editado/borrado se fue y la reacción sigue viva
        st, res = ct.http("GET", f"{a.base}/api/chats/{dm}/messages?limit=100",
                          token=A["access"])
        msgs = res.get("messages", []) if isinstance(res, dict) else []
        imgs = [m for m in msgs if m["kind"] == "image" and m.get("media")]
        step("paso6 REST: pegado = mensaje con media", bool(imgs),
             f"{len(imgs)} imagen(es)")
        leaky = [m for m in msgs if "mensaje" in (m.get("body") or "")]
        step("paso7 REST: editado/eliminado fuera", not leaky,
             [m["body"] for m in leaky])
        reacts = [m for m in msgs
                  if m["body"] == "pregunta"
                  and any(r.get("emoji") == "🔥" for r in m.get("reactions") or [])]
        step("paso8 REST: reacción intacta", bool(reacts), f"{len(reacts)}")

        print(f"\nw19 UI: {ok} ok, {fail} fallas")
        sys.exit(1 if fail else 0)
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
