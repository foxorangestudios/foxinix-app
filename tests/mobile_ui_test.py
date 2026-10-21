#!/usr/bin/env python3
"""E2E móvil (W54): comprueba la cáscara tipo app a 390x844.

La web es la misma que carga el APK de Tauri. Este test verifica que en
pantalla de teléfono:

  1. Aparece la barra inferior Chats / Personas / Ajustes.
  2. La lista usa el app bar móvil (sin el pie de usuario de escritorio).
  3. El chat oculta el sidebar y deja las llamadas dentro del menú ⋮.
  4. Personas ocupa la pantalla y Ajustes se comporta como pestaña
     de la barra inferior (sin X y sin ocultar la navegación).
  5. En escritorio (1280px) no aparece ninguna pieza exclusiva de móvil.

Uso: server/.venv/bin/python tests/mobile_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import chat_ui_test as base  # noqa: E402

SHOTS = Path("/tmp/opencode")
PY = ROOT / "server" / ".venv" / "bin" / "python"
SHOT = ROOT / "scripts" / "shot.py"


def run_shot(url, out, js=None, ev=None, wait=500, width=390, height=844,
             viewport=True, timeout=150):
    cmd = [str(PY), str(SHOT), url, str(out), "--wait", str(wait)]
    if viewport:
        cmd += ["--width", str(width), "--height", str(height), "--viewport"]
    if js:
        cmd += ["--js", js]
    if ev:
        cmd += ["--eval", ev]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def parse_value(raw):
        raw = raw.strip()
        try:
            val = json.loads(raw)      # desenvuelve la comilla externa
            if isinstance(val, str):
                try:
                    val = json.loads(val)  # y el JSON.stringify interno
                except ValueError:
                    pass
            return val
        except ValueError:
            return raw.strip('"')

    js_res = eval_val = None
    for line in r.stdout.splitlines():
        if line.startswith("JSRES: "):
            js_res = parse_value(line[len("JSRES: "):])
        elif line.startswith("EVAL: "):
            eval_val = parse_value(line[len("EVAL: "):])
    ok = r.returncode == 0 and "SHOT:" in r.stdout
    return ok, js_res, eval_val, (r.stdout + r.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    stamp = str(int(time.time()))[-7:]
    ua, ub = f"movA{stamp}"[:20].lower(), f"movB{stamp}"[:20].lower()
    try:
        A = base.register(a.base, f"{ua}@test.local", ua)
        B = base.register(a.base, f"{ub}@test.local", ub)
        st, res = base.http("POST", a.base + "/api/chats/dm",
                            {"username": ub}, token=A["access"])
        if st != 201:
            raise SystemExit(f"✗ dm: {st} {res}")
        cid = res["chat"]["id"]
        for who, body in [
            (B, "Hola, ¿cómo va todo? 😊"),
            (A, "Todo bien, probando la app en el celular."),
            (B, "Se ve rara la interfaz, como una página web."),
            (A, "Estoy viendo cómo mejorarla para que se sienta más de app."),
        ]:
            base.send(a.base, who["access"], cid, {"kind": "text", "body": body})
            time.sleep(0.2)
        print(f"→ sembrados: {ua} (A) y {ub} (B), chat {cid}")

        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = base.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))

        # El perfil de Firefox conserva la sesión entre corridas. Limpiar
        # primero evita que un bootstrap viejo pise la inyección nueva.
        ok, js_res, _, log = run_shot(
            f"{a.base}/", SHOTS / "mov-0-prep.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        if not ok or not js_res:
            print(log[-1200:])
            raise SystemExit("✗ falló la limpieza del perfil")
        ok, js_res, _, log = run_shot(
            f"{a.base}/", SHOTS / "mov-0-sesion.png", js=sess_js, wait=300)
        if not ok or not js_res:
            print(log[-1200:])
            raise SystemExit("✗ falló la inyección de sesión")

        # 1) Lista: barra inferior + app bar móvil.
        ok, js_res, ev, log = run_shot(
            f"{a.base}/?v=mobile-list", SHOTS / "mov-1-lista.png",
            js="'lista'",
            ev="JSON.stringify({tabs:getComputedStyle(document.querySelector('.mobile-tabs')).display,"
               "people:getComputedStyle(document.querySelector('.side-people')).display,"
               "user:getComputedStyle(document.querySelector('.user-panel')).display,"
               "title:document.querySelector('.side-title').textContent,"
               "plus:getComputedStyle(document.querySelector('.side-new')).backgroundColor,"
               "avatar:Math.round(document.querySelector('.mobile-me .avatar').getBoundingClientRect().width)})",
            wait=1000)
        print("paso1 lista:", ev)
        if not ok or not isinstance(ev, dict) or ev.get("tabs") != "flex":
            print(log[-1600:])
            raise SystemExit("✗ la barra inferior móvil no está visible")
        state = ev
        if state["people"] != "none" or state["user"] != "none":
            raise SystemExit("✗ quedaron piezas de escritorio en la lista móvil")
        if state["plus"] not in ("rgba(0, 0, 0, 0)", "transparent"):
            raise SystemExit(f"✗ el botón ＋ conserva fondo: {state['plus']}")
        if state["avatar"] != 40:
            raise SystemExit(f"✗ el avatar no mide lo mismo que el botón: {state['avatar']}")

        # 2) Chat: sidebar fuera, llamadas en el menú ⋮, cabecera a 390px.
        js_chat = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                   "let t=Date.now();"
                   "while(Date.now()-t<12000&&!document.querySelector('.chat-list .chat-item'))"
                   "await s(120);"
                   "document.querySelector('.chat-list .chat-item').click();"
                   "await s(1300);"
                   "return JSON.stringify({head:document.querySelector('.chat-head').getBoundingClientRect().width,"
                   "back:getComputedStyle(document.querySelector('.back')).display,"
                   "call:getComputedStyle(document.querySelector('.call-action')).display,"
                   "more:getComputedStyle(document.querySelector('.chat-more')).display,"
                   "tabs:!!document.querySelector('.mobile-tabs')})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-chat", SHOTS / "mov-2-chat.png",
            js=js_chat, wait=900)
        print("paso2 chat:", js_res)
        if not ok or not js_res:
            print(log[-1600:])
            raise SystemExit("✗ no abrió el chat móvil")
        st = js_res
        if st["call"] != "none" or st["more"] != "flex" or st["tabs"]:
            raise SystemExit(f"✗ cabecera móvil incorrecta: {st}")
        if st["head"] != 390:
            raise SystemExit(f"✗ el chat no ocupa el ancho del teléfono: {st['head']}")

        # 3) Menú ⋮ del chat (bottom sheet) con llamadas y acciones.
        js_more = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                   "let t=Date.now();"
                   "while(Date.now()-t<12000&&!document.querySelector('.chat-list .chat-item'))"
                   "await s(120);"
                   "document.querySelector('.chat-list .chat-item').click();"
                   "await s(900);"
                   "document.querySelector('.chat-more').click();"
                   "await s(450);"
                   "const m=document.querySelector('.ctx-menu');"
                   "return JSON.stringify({sheet:!!(m&&m.classList.contains('ctx-sheet')),"
                   "items:m?m.querySelectorAll('.ctx-item').length:0})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-more", SHOTS / "mov-3-mas.png",
            js=js_more, wait=500)
        print("paso3 menú ⋮:", js_res)
        if not ok or not js_res:
            print(log[-1600:])
            raise SystemExit("✗ no abrió el menú de acciones móvil")
        st = js_res
        if not st["sheet"] or st["items"] < 4:
            raise SystemExit(f"✗ menú móvil incompleto: {st}")

        # 4) Personas: app bar propia y barra inferior activa.
        js_people = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                     "let t=Date.now();"
                     "while(Date.now()-t<12000&&!document.querySelector('.mobile-tabs'))await s(120);"
                     "document.querySelector('.mobile-tabs .mt-btn:nth-child(2)').click();"
                     "await s(900);"
                     "return JSON.stringify({head:(document.querySelector('.mobile-page-head b')||{}).textContent,"
                     "on:!!document.querySelectorAll('.mobile-tabs .mt-btn.on')[0]})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-people", SHOTS / "mov-4-personas.png",
            js=js_people, wait=800)
        print("paso4 personas:", js_res)
        if not ok or not js_res:
            print(log[-1600:])
            raise SystemExit("✗ no abrió Personas en móvil")
        st = js_res
        if st["head"] != "Personas" or not st["on"]:
            raise SystemExit(f"✗ cabecera de Personas incorrecta: {st}")

        # 5) Ajustes: pestaña de abajo; la barra sigue visible y activa.
        js_set = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                  "let t=Date.now();"
                  "while(Date.now()-t<12000&&!document.querySelector('.mobile-tabs'))await s(120);"
                  "document.querySelector('.mobile-tabs .mt-btn:nth-child(3)').click();"
                  "await s(800);"
                  "const m=document.querySelector('.modal.settings');"
                  "const r=m.getBoundingClientRect();"
                  "const nav=document.querySelector('.mobile-tabs');"
                  "const on=document.querySelector('.mobile-tabs .mt-btn.on .mt-label');"
                  "const close=document.querySelector('.modal.settings > header .icon-btn');"
                  "return JSON.stringify({w:Math.round(r.width),h:Math.round(r.height),"
                  "tabs:getComputedStyle(nav).display,active:on?on.textContent.trim():'',"
                  "close:close?getComputedStyle(close).display:'',"
                  "navZ:getComputedStyle(nav).zIndex,"
                  "veilZ:getComputedStyle(document.querySelector('.settings-veil')).zIndex})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-settings", SHOTS / "mov-5-ajustes.png",
            js=js_set, wait=700)
        print("paso5 ajustes:", js_res)
        if not ok or not js_res:
            print(log[-1600:])
            raise SystemExit("✗ no abrió Ajustes en móvil")
        st = js_res
        if st["w"] != 390 or st["h"] != 844:
            raise SystemExit(f"✗ Ajustes no ocupa la pantalla: {st}")
        if st["tabs"] != "flex" or st["active"] != "Ajustes":
            raise SystemExit(f"✗ Ajustes no se comporta como pestaña: {st}")
        if st["close"] != "none":
            raise SystemExit(f"✗ la X de Ajustes sigue visible en móvil: {st}")
        if int(st["navZ"]) <= int(st["veilZ"]):
            raise SystemExit(f"✗ la barra inferior quedó debajo de Ajustes: {st}")

        # 5b) Desde Ajustes se puede volver a Chats con la barra de abajo.
        js_back = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                   "let t=Date.now();"
                   "while(Date.now()-t<12000&&!document.querySelector('.mobile-tabs'))await s(120);"
                   "document.querySelector('.mobile-tabs .mt-btn:nth-child(3)').click();"
                   "await s(600);"
                   "const opened=!!document.querySelector('.settings-veil');"
                   "document.querySelector('.mobile-tabs .mt-btn:nth-child(1)').click();"
                   "await s(700);"
                   "const on=document.querySelector('.mobile-tabs .mt-btn.on .mt-label');"
                   "return JSON.stringify({opened:opened,"
                   "closed:!document.querySelector('.settings-veil'),"
                   "active:on?on.textContent.trim():'',"
                   "title:document.querySelector('.side-title').textContent})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-settings-back", SHOTS / "mov-5b-vuelta.png",
            js=js_back, wait=500)
        print("paso5b vuelta:", js_res)
        if not ok or not js_res:
            print(log[-1600:])
            raise SystemExit("✗ no se pudo volver desde Ajustes")
        st = js_res
        if not st["opened"] or not st["closed"] or st["active"] != "Chats":
            raise SystemExit(f"✗ la barra no navega desde Ajustes: {st}")

        # 6) Escritorio: nada exclusivo de móvil.
        ok, js_res, ev, log = run_shot(
            f"{a.base}/?v=mobile-desktop", SHOTS / "mov-6-escritorio.png",
            ev="JSON.stringify({tabs:getComputedStyle(document.querySelector('.mobile-tabs')).display,"
               "me:getComputedStyle(document.querySelector('.mobile-me')).display,"
               "word:getComputedStyle(document.querySelector('.side-logo-word')).display})",
            wait=900, width=1280, height=860)
        print("paso6 escritorio:", ev)
        if not ok or not isinstance(ev, dict):
            print(log[-1600:])
            raise SystemExit("✗ no cargó la vista de escritorio")
        st = ev
        if st["tabs"] != "none" or st["me"] != "none" or st["word"] != "block":
            raise SystemExit(f"✗ el escritorio cambió: {st}")

        print(f"✓ W54 móvil OK → {SHOTS}/mov-1-lista.png … mov-6-escritorio.png")
    finally:
        if base.cleanup_db():
            print("  datos de prueba eliminados de la DB local")
        else:
            print("  WARN: la limpieza pudo ser incompleta")


if __name__ == "__main__":
    main()
