#!/usr/bin/env python
"""E2E W3: responder, reaccionar, nota de voz y grupos (con WS en vivo).

Siembra 3 usuarios verificados + un DM por REST, maneja Firefox headless
(vía BiDi con micrófono falso) y verifica todo por REST al final:
  - respuesta con cita (reply_to)
  - reacción propia (chip .mine + fila en la DB)
  - nota de voz (MediaRecorder → upload → kind=voice)
  - grupo nuevo + alta de miembro con mensaje system en vivo por WS
Limpia TODOS los datos sembrados al terminar (aunque falle).

Uso: python tests/w3_ui_test.py            (servidor local en :8899)
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
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

JS_REPLY = """(async () => {
  """ + W_WAIT + """
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  if (!await wait('.msg')) return 'FAIL: sin mensajes';
  await sleep(400);
  const acts = document.querySelectorAll('.msg .bubble .b-act');
  if (acts.length < 2) return 'FAIL: sin acciones de mensaje';
  acts[0].click();                       // responder
  const bar = await wait('.reply-bar');
  if (!bar) return 'FAIL: no abrió la reply-bar';
  const ta = document.querySelector('.composer-input');
  ta.value = 'Respuesta de prueba W3';
  ta.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(150);
  document.querySelector('.comp-row .send-btn').click();
  const t = Date.now();
  let ok = false;
  while (Date.now() - t < 8000) {
    const rows = document.querySelectorAll('.msgs .msg.mine');
    const last = rows[rows.length - 1];
    if (last && last.querySelector('.b-reply')) { ok = true; break; }
    await sleep(150);
  }
  if (!ok) return 'FAIL: no se envió la respuesta';
  if (document.querySelector('.reply-bar')) return 'FAIL: no se cerró la reply-bar';
  return 'OK respuesta con cita';
})()"""

JS_REACT = """(async () => {
  """ + W_WAIT + """
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  if (!await wait('.msg')) return 'FAIL: sin mensajes';
  await sleep(400);
  const acts = document.querySelectorAll('.msg .bubble .b-act');
  if (acts.length < 2) return 'FAIL: sin acciones de mensaje';
  acts[1].click();                       // reaccionar
  if (!await wait('.react-picker')) return 'FAIL: no abrió el picker';
  document.querySelector('.react-picker .rp').click();   // primer emoji (👍)
  const t = Date.now();
  while (Date.now() - t < 6000 && !document.querySelector('.react-chip.mine')) {
    await sleep(120);
  }
  if (!document.querySelector('.react-chip.mine')) return 'FAIL: sin chip propio';
  return 'OK reacción propia';
})()"""

JS_VOICE = """(async () => {
  """ + W_WAIT + """
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  await wait('.msg');
  const mic = await wait('.comp-mic', 6000);
  if (!mic) return 'FAIL: sin botón de micrófono';
  mic.click();
  // El primer getUserMedia (dispositivo falso) puede tardar varios segundos
  if (!await wait('.rec-bar', 15000)) return 'FAIL: no inició la grabación';
  await sleep(1800);                    // graba con el micrófono falso
  document.querySelector('.rec-send').click();
  const t = Date.now();
  while (Date.now() - t < 12000 && !document.querySelector('.b-audio')) {
    await sleep(200);
  }
  if (!document.querySelector('.b-audio')) return 'FAIL: no llegó la nota de voz';
  if (document.querySelector('.rec-bar')) return 'FAIL: no se cerró la grabación';
  return 'OK nota de voz enviada';
})()"""


def js_group(user_b, user_c):
    return """(async () => {
  """ + W_WAIT + """
  const plus = await wait('.side-head .icon-btn');
  if (!plus) return 'FAIL: sin barra lateral';
  plus.click();
  if (!await wait('.modal')) return 'FAIL: no abrió el modal';
  const tabs = document.querySelectorAll('.m-tab');
  if (tabs.length < 2) return 'FAIL: sin tabs de grupo';
  tabs[1].click();                       // pestaña "Grupo"
  const ti = await wait('.m-title input');
  ti.value = 'Equipo Fox';
  ti.dispatchEvent(new Event('input', { bubbles: true }));
  const si = document.querySelector('.m-search input');
  si.value = '""" + user_b[:6] + """';
  si.dispatchEvent(new Event('input', { bubbles: true }));
  if (!await wait('.res-item', 7000)) return 'FAIL: sin resultados para el miembro';
  await sleep(200);
  document.querySelector('.res-item').click();
  if (!await wait('.g-chip')) return 'FAIL: no sumó al miembro';
  const create = await wait('.m-foot .btn', 4000);
  if (!create) return 'FAIL: sin botón crear';
  create.click();
  const name = await wait('.chat-head .ch-name', 8000);
  if (!name || name.textContent.indexOf('Equipo Fox') < 0) {
    return 'FAIL: no abrió el grupo';
  }
  const add = document.querySelector('.chat-head .icon-btn[title="Agregar miembros"]');
  if (!add) return 'FAIL: sin botón "agregar miembros"';
  add.click();
  if (!await wait('.modal')) return 'FAIL: no abrió "agregar al grupo"';
  const si2 = document.querySelector('.m-search input');
  si2.value = '""" + user_c[:6] + """';
  si2.dispatchEvent(new Event('input', { bubbles: true }));
  if (!await wait('.res-item', 7000)) return 'FAIL: sin resultados para C';
  await sleep(200);
  document.querySelector('.res-item').click();
  const sys = await wait('.sys-msg', 8000);   // system por WS (en vivo)
  if (!sys) return 'FAIL: sin mensaje system';
  if (sys.textContent.indexOf('agregó a') < 0) {
    return 'FAIL: system raro: ' + sys.textContent;
  }
  return 'OK grupo + alta con system en vivo';
})()"""


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    stamp = str(int(time.time()))[-7:]
    user_a, user_b = f"foxui{stamp}"[:20], f"nena{stamp}"[:20]
    user_c = f"solfox{stamp}"[:20]
    cid = None
    try:
        A = ct.register(a.base, f"{user_a}@test.local", user_a)
        B = ct.register(a.base, f"{user_b}@test.local", user_b)
        C = ct.register(a.base, f"{user_c}@test.local", user_c)
        print(f"→ sembrados: {user_a} (A), {user_b} (B), {user_c} (C)")

        # DM + conversación mínima (objetivo de respuesta/reacción)
        st, res = ct.dm_between(a.base, A["access"], B["access"],
                                user_a, user_b)
        if st != 201:
            raise SystemExit(f"✗ dm: {st} {res}")
        cid = res["chat"]["id"]
        ct.send(a.base, B["access"], cid,
                {"kind": "text", "body": "Probando el chat nuevo 🚀"})
        ct.send(a.base, A["access"], cid,
                {"kind": "text", "body": "Recibido, arrancamos W3"})
        print("→ DM con 2 mensajes listo")

        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))

        # 0) limpiar sesión vieja (carrera clearSession vs inyección)
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w3-0-prep.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        print("paso0 perfil:", js_res or "(sin jsres)")
        if not ok or not js_res:
            print(log[-1500:])
            raise SystemExit("✗ falló la limpieza de perfil")

        # 1) inyectar sesión de A
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w3-1-sesion.png", js=sess_js, wait=300)
        print("paso1 sesión:", js_res or "(sin jsres)")
        if not ok or not js_res:
            print(log[-1500:])
            raise SystemExit("✗ falló la inyección")

        # 2) responder con cita
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w3-1-respuesta.png", js=JS_REPLY, wait=800)
        print("paso2 respuesta:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló la respuesta")

        # 3) reaccionar
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w3-2-reaccion.png", js=JS_REACT, wait=800)
        print("paso3 reacción:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló la reacción")

        # 4) nota de voz (micrófono falso de Firefox)
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w3-3-voz.png", js=JS_VOICE, wait=800)
        print("paso4 voz:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló la nota de voz")

        # 5) grupo + alta de miembro (system en vivo por WS)
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w3-4-grupo.png",
            js=js_group(user_b, user_c), wait=800)
        print("paso5 grupo:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló el grupo")

        # 6) verificación REST de todo lo anterior
        st, res = ct.http("GET", f"{a.base}/api/chats/{cid}/messages?limit=100",
                          token=A["access"])
        msgs = res.get("messages", []) if st == 200 else []
        reply = next((m for m in msgs if m["body"] == "Respuesta de prueba W3"), None)
        if not reply or not reply.get("reply_to") or \
                reply["reply_to"].get("sender") != user_b:
            raise SystemExit(f"✗ REST: respuesta sin cita correcta: {reply}")
        reacted = next((m for m in msgs if m.get("reactions")), None)
        if not reacted:
            raise SystemExit("✗ REST: ninguna reacción en la DB")
        if not any(r["user_id"] == A["user"]["id"] for r in reacted["reactions"]):
            raise SystemExit(f"✗ REST: la reacción no es de A: {reacted['reactions']}")
        voice = next((m for m in msgs if m["kind"] == "voice"), None)
        if not voice or not voice.get("media"):
            raise SystemExit("✗ REST: no hay mensaje kind=voice con media")
        # descarga binaria (webm): urllib directo, ct.http decodifica utf-8.
        # W11: la URL ya viene firmada (?exp=&sig=) y se usa tal cual, sin
        # token de cuenta (con clientes viejos aún agrega ?token=).
        url = voice["media"]["url"]
        if "sig=" not in url:
            url += ("&" if "?" in url else "?") + "token=" + A["access"]
        try:
            with urllib.request.urlopen(a.base + url, timeout=15) as vr:
                if vr.status != 200:
                    raise SystemExit(f"✗ REST: media de voz HTTP {vr.status}")
                if not vr.read(4):
                    raise SystemExit("✗ REST: media de voz vacía")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"✗ REST: la media de voz no descarga ({e.code})")

        st, res = ct.http("GET", a.base + "/api/chats", token=A["access"])
        group = next((c for c in res.get("chats", []) if c["type"] == "group"), None)
        if not group:
            raise SystemExit("✗ REST: A no ve el grupo")
        st, res = ct.http(
            "GET", f"{a.base}/api/chats/{group['id']}/messages?limit=100",
            token=A["access"])
        sysmsg = next((m for m in res.get("messages", [])
                       if m["kind"] == "system" and "agregó a" in m["body"]), None)
        if not sysmsg:
            raise SystemExit("✗ REST: sin mensaje system en el grupo")
        st, res = ct.http("GET", a.base + "/api/chats", token=B["access"])
        if not any(c["type"] == "group" for c in res.get("chats", [])):
            raise SystemExit("✗ REST: B no ve el grupo")
        print("✓ REST: cita, reacción, voz, grupo y system confirmados")

        print("✓ W3 E2E completo → " + ", ".join(
            str(SHOTS / n) for n in
            ("w3-1-respuesta.png", "w3-2-reaccion.png",
             "w3-3-voz.png", "w3-4-grupo.png")))
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
