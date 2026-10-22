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
from PIL import Image

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
        # W56: B tiene foto para comprobar que el aviso nativo recibe una
        # URL de avatar absoluta (la app compone foto + icono).
        bavatar = SHOTS / f"mov-bavatar-{stamp}.png"
        Image.new("RGB", (96, 96), (255, 138, 61)).save(bavatar)
        bup = base.upload(a.base, B["access"], bavatar)
        st, res = base.http("PUT", a.base + "/api/auth/profile",
                            {"avatar_media_id": bup["id"]}, token=B["access"])
        if st != 200:
            raise SystemExit(f"✗ avatar de B: {st} {res}")
        st, res = base.http("POST", a.base + "/api/chats/dm",
                            {"username": ub}, token=A["access"])
        if st != 201:
            raise SystemExit(f"✗ dm: {st} {res}")
        cid = res["chat"]["id"]
        # W56: las menciones sólo se registran en grupos; este grupo sirve
        # para comprobar la excepción de No molestar.
        st, res = base.http("POST", a.base + "/api/chats/group",
                            {"title": "Avisos DND", "members": [ub]},
                            token=A["access"])
        if st != 201:
            raise SystemExit(f"✗ grupo: {st} {res}")
        gid = res["chat"]["id"]
        # Un mensaje viejo evita que el grupo vacío quede primero en la
        # lista (los chats sin actividad se ordenan arriba).
        base.send(a.base, B["access"], gid, {"kind": "text", "body": "Grupo de prueba"})
        for who, body in [
            (B, "Hola, ¿cómo va todo? 😊"),
            (A, "Todo bien, probando la app en el celular."),
            (B, "Se ve rara la interfaz, como una página web."),
            (A, "Estoy viendo cómo mejorarla para que se sienta más de app."),
        ]:
            base.send(a.base, who["access"], cid, {"kind": "text", "body": body})
            time.sleep(0.2)
        # Una imagen alta y otra normal: el visor debe dejar libres los
        # controles de arriba y la pista inferior aun con una foto 9:16.
        tall = SHOTS / f"mov-tall-{stamp}.png"
        im = Image.new("RGB", (360, 900), (255, 138, 61))
        for y in range(900):
            for x in range(360):
                if (x + y) % 80 < 8:
                    im.putpixel((x, y), (28, 32, 36))
        im.save(tall)
        up = base.upload(a.base, B["access"], tall)
        base.send(a.base, B["access"], cid, {"kind": "image", "media_id": up["id"]})
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

        # 2b) Teclado: con --app-h la app se achica, el composer queda
        # arriba del teclado y la barra inferior no se superpone.
        js_kb = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                 "let t=Date.now();"
                 "while(Date.now()-t<12000&&!document.querySelector('.chat-list .chat-item'))"
                 "await s(120);"
                 "document.querySelector('.chat-list .chat-item').click();"
                 "await s(900);"
                 "const root=document.documentElement;"
                 "root.style.setProperty('--app-h','500px');"
                 "root.classList.add('kb-open');"
                 "await s(120);"
                 "const shell=document.querySelector('.app-shell');"
                 "const comp=document.querySelector('.composer');"
                 "const out={shell:Math.round(shell.getBoundingClientRect().height),"
                 "compBottom:Math.round(comp.getBoundingClientRect().bottom)};"
                 "root.classList.remove('kb-open');"
                 "root.style.removeProperty('--app-h');"
                 "return JSON.stringify(out)})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-keyboard", SHOTS / "mov-2b-teclado.png",
            js=js_kb, wait=500)
        print("paso2b teclado:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1600:])
            raise SystemExit("✗ no se pudo probar el ajuste del teclado")
        if js_res.get("shell") != 500 or js_res.get("compBottom", 999) > 500:
            raise SystemExit(f"✗ el composer no queda sobre el teclado: {js_res}")

        # 2c) Inset nativo de la barra de gestos: boot.js debe volcarlo en
        # --sab y la barra inferior debe dejar ese hueco.
        js_inset = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                    "let t=Date.now();"
                    "while(Date.now()-t<12000&&!document.querySelector('.mobile-tabs'))await s(120);"
                    "window.FoxinixAndroid={insets:function(){return JSON.stringify("
                    "{top:0,bottom:24,left:0,right:0});}};"
                    "window.dispatchEvent(new Event('resize')); await s(250);"
                    "const nav=document.querySelector('.mobile-tabs');"
                    "const side=document.querySelector('.sidebar');"
                    "const cs=getComputedStyle(document.documentElement);"
                    "return JSON.stringify({sab:cs.getPropertyValue('--sab').trim(),"
                    "tabs:!!nav?Math.round(nav.getBoundingClientRect().height):0,"
                    "tabsPad:nav?getComputedStyle(nav).paddingBottom:'',"
                    "sidePad:side?getComputedStyle(side).paddingBottom:'',"
                    "bridge:typeof window.foxinixSetNativeInsets==='function'})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-gesture-inset", SHOTS / "mov-2c-gestos.png",
            js=js_inset, wait=500)
        print("paso2c inset de gestos:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1600:])
            raise SystemExit("✗ no se pudo probar el inset de gestos")
        if js_res.get("sab") != "24px":
            raise SystemExit(f"✗ boot.js no aplicó el inset nativo: {js_res}")
        if js_res.get("tabs") != 82 or js_res.get("sidePad") != "82px":
            raise SystemExit(f"✗ la barra inferior no dejó el hueco de gestos: {js_res}")
        if not js_res.get("bridge"):
            raise SystemExit(f"✗ falta el puente foxinixSetNativeInsets: {js_res}")

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
                   "const h=m?m.querySelector('.ctx-head'):null;"
                   "return JSON.stringify({sheet:!!(m&&m.classList.contains('ctx-sheet')),"
                   "items:m?m.querySelectorAll('.ctx-item').length:0,"
                   "backdrop:!!document.querySelector('.ctx-backdrop'),"
                   "head:h?h.querySelector('b').textContent:'',"
                   "headAv:!!(h&&h.querySelector('.avatar'))})})()")
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
        if not st["backdrop"] or not st["head"] or not st["headAv"]:
            raise SystemExit(f"✗ falta el velo o la cabecera del chat: {st}")

        # 4) Personas: app bar propia y barra inferior activa.
        js_people = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                     "let t=Date.now();"
                     "while(Date.now()-t<12000&&!document.querySelector('.mobile-tabs'))await s(120);"
                     "document.querySelector('.mobile-tabs .mt-btn:nth-child(2)').click();"
                     "await s(900);"
                     "const lg=document.querySelector('.mobile-page-head .mobile-page-logo');"
                     "return JSON.stringify({head:(document.querySelector('.mobile-page-head b')||{}).textContent,"
                     "logo:!!lg,logoW:lg?Math.round(lg.getBoundingClientRect().width):0,"
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
        if not st["logo"] or st["logoW"] != 32:
            raise SystemExit(f"✗ falta el icono del sitio en Personas: {st}")

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
                  "const lg=document.querySelector('.modal.settings > header .mobile-page-logo');"
                  "return JSON.stringify({w:Math.round(r.width),h:Math.round(r.height),"
                  "logo:!!lg,logoW:lg?Math.round(lg.getBoundingClientRect().width):0,"
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
        if not st["logo"] or st["logoW"] != 32:
            raise SystemExit(f"✗ falta el icono del sitio en Ajustes: {st}")
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

        # 5c) En el APK, Ajustes muestra el permiso nativo de Android
        # en lugar del permiso de notificaciones del navegador.
        js_native_set = (
            "(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
            "window.FoxinixAndroid={permission:function(){return 'granted';},"
            "requestPermission:function(){},openSettings:function(){},"
            "notify:function(){}};"
            "let t=Date.now();"
            "while(Date.now()-t<12000&&!document.querySelector('.mobile-tabs'))await s(120);"
            "document.querySelector('.mobile-tabs .mt-btn:nth-child(3)').click();"
            "await s(500);"
            "const tabs=Array.from(document.querySelectorAll('.m-tab'));"
            "const chat=tabs.find(function(b){return b.textContent.trim()==='Chat';});"
            "if(chat)chat.click(); await s(400);"
            "const secs=Array.from(document.querySelectorAll('.st-sec'));"
            "let sec=null;"
            "for(const x of secs){const h=x.querySelector('.st-h');"
            "if(h&&h.textContent.indexOf('Notificaciones de Android')>=0)sec=x;}"
            "return JSON.stringify({found:!!sec,"
            "head:sec?sec.querySelector('.st-h').textContent:'',"
            "label:sec?sec.querySelector('.st-col span').textContent:'',"
            "button:sec&&sec.querySelector('button')?sec.querySelector('button').textContent:'',"
            "ok:sec&&sec.querySelector('.st-ok')?sec.querySelector('.st-ok').textContent:''})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-native-settings", SHOTS / "mov-5c-ajustes-android.png",
            js=js_native_set, wait=400)
        print("paso5c ajustes Android:", js_res)
        if not ok or not isinstance(js_res, dict) or not js_res.get("found"):
            print(log[-1800:])
            raise SystemExit("✗ Ajustes no muestra el aviso nativo de Android")
        if js_res.get("button"):
            raise SystemExit(f"✗ Ajustes ofrece activar con permiso concedido: {js_res}")
        if js_res.get("label") != "Activas: avisan con la app en segundo plano":
            raise SystemExit(f"✗ estado nativo inesperado: {js_res}")

        # 5d) Estados: en el teléfono los presets son teléfonos de color;
        # los badges del avatar mantienen círculo, luna, barra y aro.
        js_status = (
            "(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
            "let t=Date.now();"
            "while(Date.now()-t<12000&&!document.querySelector('.mobile-me'))await s(120);"
            "document.querySelector('.mobile-me').click(); await s(450);"
            "const pencil=document.querySelector('.mp-edit-open');"
            "if(!pencil)return 'FAIL: no abrió el perfil';"
            "pencil.click(); await s(450);"
            "const dots=document.querySelectorAll('.mp-presets .sdot');"
            "const by={};dots.forEach(function(d){"
            "const c=getComputedStyle(d);by[d.className.replace('sdot ','')]="
            "{w:c.width,h:c.height,r:c.borderRadius,bg:c.backgroundColor,"
            "img:c.backgroundImage,border:c.borderTopColor};});"
            "function av(cls){const w=document.createElement('span');"
            "w.className='av-wrap on '+cls;document.body.appendChild(w);"
            "const c=getComputedStyle(w,'::after');"
            "return {bg:c.backgroundColor,img:c.backgroundImage,border:c.borderTopColor};}"
            "return JSON.stringify({count:dots.length,online:by['sd-online'],"
            "busy:by['sd-busy'],dnd:by['sd-dnd'],off:by['sd-off'],"
            "avOnline:av('st-online'),avBusy:av('st-busy'),"
            "avDnd:av('st-dnd'),avOff:av('st-off')})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-status", SHOTS / "mov-5d-estados.png",
            js=js_status, wait=500)
        print("paso5d estados:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1800:])
            raise SystemExit("✗ no se pudieron probar los estados")
        st = js_res
        if st.get("count") != 4:
            raise SystemExit(f"✗ faltan presets de estado: {st}")
        if st["online"].get("w") != "14px" or st["online"].get("h") != "20px":
            raise SystemExit(f"✗ los estados móviles no son teléfonos: {st}")
        if st["busy"].get("bg") != "rgb(240, 178, 50)":
            raise SystemExit(f"✗ Ausente no es naranja: {st}")
        if st["dnd"].get("bg") != "rgb(242, 63, 67)":
            raise SystemExit(f"✗ No molestar no es rojo: {st}")
        if st["off"].get("bg") != "rgba(0, 0, 0, 0)" or st["off"].get("border") != "rgb(128, 132, 142)":
            raise SystemExit(f"✗ Invisible no es un aro gris: {st}")
        if "radial-gradient" not in (st["avBusy"].get("img") or ""):
            raise SystemExit(f"✗ el badge de Ausente no tiene luna: {st}")
        if "linear-gradient" not in (st["avDnd"].get("img") or ""):
            raise SystemExit(f"✗ el badge de No molestar no tiene barra: {st}")
        if (st["avOff"].get("bg") != "rgba(0, 0, 0, 0)"
                or st["avOff"].get("border") != "rgb(128, 132, 142)"):
            raise SystemExit(f"✗ el badge desconectado no es hueco: {st}")

        # 7) Editor de foto móvil: grande, sin barra/botón y sin el
        # formulario de abajo hasta pulsar Aplicar.
        js_avatar = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                     "let t=Date.now();"
                     "while(Date.now()-t<12000&&!document.querySelector('.mobile-me'))await s(120);"
                     "document.querySelector('.mobile-me').click();"
                     "await s(500);"
                     "const pencil=document.querySelector('.mp-edit-open');"
                     "if(!pencil)return 'FAIL: no abrió el perfil';"
                     "pencil.click(); await s(500);"
                     "const inp=document.querySelector('.mp-edit input[type=file]');"
                     "if(!inp)return 'FAIL: sin selector de foto';"
                     "const blob=await (await fetch('/static/icon-192.png')).blob();"
                     "const dt=new DataTransfer();"
                     "dt.items.add(new File([blob],'perfil.png',{type:'image/png'}));"
                     "inp.files=dt.files;"
                     "inp.dispatchEvent(new Event('change',{bubbles:true}));"
                     "await s(700);"
                     "const cv=document.querySelector('.mp-edit .av-ed-cv');"
                     "if(!cv)return 'FAIL: no abrió el editor';"
                     "const r=cv.getBoundingClientRect();"
                     "const before=cv.toDataURL();"
                     "function pe(type,id,x,y){cv.dispatchEvent(new PointerEvent(type,"
                     "{bubbles:true,cancelable:true,pointerId:id,pointerType:'touch',"
                     "clientX:x,clientY:y}));}"
                     "pe('pointerdown',1,r.left+r.width*.3,r.top+r.height*.5);"
                     "pe('pointerdown',2,r.left+r.width*.7,r.top+r.height*.5);"
                     "pe('pointermove',2,r.left+r.width*.85,r.top+r.height*.5);"
                     "pe('pointerup',1,r.left+r.width*.85,r.top+r.height*.5);"
                     "pe('pointerup',2,r.left+r.width*.85,r.top+r.height*.5);"
                     "await s(200);"
                     "const z=document.querySelector('.mp-edit .av-ed-zoom');"
                     "const rot=document.querySelector('.mp-edit .av-ed-rotate');"
                     "const out={w:Math.round(r.width),h:Math.round(r.height),"
                     "gesture:cv.toDataURL()!==before,"
                     "zoom:z?getComputedStyle(z).display:'',"
                     "rotate:rot?getComputedStyle(rot).display:'',"
                     "foot:!!document.querySelector('.mp-edit .m-foot'),"
                     "fields:document.querySelectorAll('.mp-edit .field').length};"
                     "const apply=Array.from(document.querySelectorAll('.mp-edit .av-ed .btn'))"
                     ".find(b=>b.textContent.trim()==='Aplicar');"
                     "if(apply)apply.click(); await s(600);"
                     "out.footAfter=!!document.querySelector('.mp-edit .m-foot');"
                     "out.fieldsAfter=document.querySelectorAll('.mp-edit .field').length;"
                     "return JSON.stringify(out)})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-avatar", SHOTS / "mov-7-foto.png",
            js=js_avatar, wait=500)
        print("paso7 editor de foto:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1800:])
            raise SystemExit("✗ no abrió el editor de foto móvil")
        st = js_res
        if st.get("w", 0) < 300 or st.get("h", 0) < 300:
            raise SystemExit(f"✗ el editor no es grande en móvil: {st}")
        if not st.get("gesture"):
            raise SystemExit(f"✗ los dos dedos no cambian el encuadre: {st}")
        if st.get("zoom") != "none" or st.get("rotate") != "none":
            raise SystemExit(f"✗ siguen visibles los controles de escritorio: {st}")
        if st.get("foot") or st.get("fields"):
            raise SystemExit(f"✗ el formulario tapa el editor: {st}")
        if not st.get("footAfter") or not st.get("fieldsAfter"):
            raise SystemExit(f"✗ Aplicar no devolvió el formulario: {st}")

        # 8) Visor: la imagen queda entre los controles; al ampliar se
        # esconden solo los controles.
        js_lb = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                 "let t=Date.now();"
                 "while(Date.now()-t<12000&&!document.querySelector('.chat-list .chat-item'))await s(120);"
                 "document.querySelector('.chat-list .chat-item').click();"
                 "await s(900);"
                 "const im=document.querySelector('.b-img');"
                 "if(!im)return 'FAIL: no hay imagen en el chat';"
                 "im.click(); await s(500);"
                 "const big=document.querySelector('.lightbox .lb-img');"
                 "const close=document.querySelector('.lb-close');"
                 "const dl=document.querySelector('.lb-dl');"
                 "const hint=document.querySelector('.lb-hint');"
                 "if(!big||!close||!dl)return 'FAIL: no abrió el visor';"
                 "const br=big.getBoundingClientRect(),cr=close.getBoundingClientRect(),"
                 "dr=dl.getBoundingClientRect(),hr=hint?hint.getBoundingClientRect():null;"
                 "const out={top:br.top>=cr.bottom,dl:br.top>=dr.bottom,"
                 "bottom:!hr||br.bottom<=hr.top};"
                 "big.click(); await s(350);"
                 "out.zoomed=document.querySelector('.lightbox').classList.contains('lb-zoomed');"
                 "out.closeOpacity=getComputedStyle(close).opacity;"
                 "out.closePointer=getComputedStyle(close).pointerEvents;"
                 "return JSON.stringify(out)})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-lightbox", SHOTS / "mov-8-visor.png",
            js=js_lb, wait=500)
        print("paso8 visor:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1800:])
            raise SystemExit("✗ no abrió el visor de imágenes")
        st = js_res
        for key in ("top", "dl", "bottom", "zoomed"):
            if not st.get(key):
                raise SystemExit(f"✗ el visor no respeta los controles ({key}): {st}")
        if st.get("closeOpacity") != "0" or st.get("closePointer") != "none":
            raise SystemExit(f"✗ los controles no se esconden al ampliar: {st}")

        # 9) Tema claro: la burbuja propia mantiene texto blanco legible.
        js_light = ("(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
                    "document.documentElement.setAttribute('data-theme','light');"
                    "const close=document.querySelector('.lb-close');"
                    "if(close)close.click(); await s(400);"
                    "document.querySelector('.chat-list .chat-item').click();"
                    "await s(700);"
                    "const b=document.querySelector('.msg.mine .bubble');"
                    "const cs=b?getComputedStyle(b):null;"
                    "const t=b?b.querySelector('.b-text'):null;"
                    "return JSON.stringify({bubble:cs?cs.backgroundColor:'',"
                    "color:cs?cs.color:'',text:t?getComputedStyle(t).color:''})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-light", SHOTS / "mov-9-claro.png",
            js=js_light, wait=500)
        print("paso9 tema claro:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1800:])
            raise SystemExit("✗ no cargó el tema claro")
        if js_res.get("bubble") != "rgb(184, 84, 22)":
            raise SystemExit(f"✗ burbuja propia inesperada en claro: {js_res}")
        if js_res.get("color") != "rgb(255, 255, 255)" or js_res.get("text") != "rgb(255, 255, 255)":
            raise SystemExit(f"✗ texto oscuro sobre burbuja naranja: {js_res}")

        # 10) Puente de notificaciones del APK: con el objeto nativo
        # inyectado, un mensaje entrante oculto debe llamar a notify()
        # (Android WebView no define Notification).
        tok = json.dumps(B["access"])
        js_native = (
            "(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
            "window.FoxinixAndroid={permission:function(){return 'granted';},"
            "requestPermission:function(){},openSettings:function(){},"
            "notify:function(t,b,c,snd){window.__lastNotify={t:t,b:b,c:c,s:snd};},"
            "notifyWithAvatar:function(t,b,c,snd,a){window.__lastNotify="
            "{t:t,b:b,c:c,s:snd,avatar:a};}};"
            "let t=Date.now();"
            "while(Date.now()-t<12000&&!document.querySelector('.chat-list .chat-item'))await s(120);"
            "const item=document.querySelector('.chat-list .chat-item');"
            "if(!item)return JSON.stringify({fail:'sin lista'});"
            "item.click(); await s(1100);"
            "try{Object.defineProperty(document,'hidden',{configurable:true,"
            "get:function(){return true;}});}catch(e){return JSON.stringify({fail:e.message});}"
            "const token=" + tok + ";let status=0;"
            "for(let i=0;i<3;i++){const r=await fetch('/api/chats/" + str(cid) + "/messages',"
            "{method:'POST',headers:{'Content-Type':'application/json',"
            "'Authorization':'Bearer '+token},"
            "body:JSON.stringify({kind:'text',body:'Aviso nativo móvil'})});"
            "status=r.status;if(status===201)break;await s(1200);}"
            "await s(2200);"
            "return JSON.stringify({hidden:document.hidden,status:status,"
            "note:window.__lastNotify||null});})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-native-notify", SHOTS / "mov-10-aviso.png",
            js=js_native, wait=400)
        print("paso10 aviso Android:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1800:])
            raise SystemExit("✗ no se pudo probar el aviso nativo")
        st = js_res
        if st.get("status") != 201 or st.get("hidden") is not True:
            raise SystemExit(f"✗ no llegó el mensaje de prueba: {st}")
        note = st.get("note")
        if not note or note.get("b") != "Aviso nativo móvil":
            raise SystemExit(f"✗ el APK no recibió el aviso nativo: {st}")
        if str(note.get("c")) != str(cid):
            raise SystemExit(f"✗ el aviso nativo no identifica el chat: {st}")
        av = note.get("avatar") or ""
        if not av.startswith("http") or "/media/profile/" not in av:
            raise SystemExit(f"✗ el aviso nativo no recibió el avatar de B: {st}")

        # 10b) No molestar: silencia el aviso normal, pero una mención
        # directa (@usuario) sí debe llegar al APK.
        js_dnd = (
            "(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));"
            "window.__notes=[];"
            "window.FoxinixAndroid={permission:function(){return 'granted';},"
            "requestPermission:function(){},openSettings:function(){},"
            "notify:function(t,b,c,snd){window.__notes.push({t:t,b:b,c:c,s:snd});},"
            "notifyWithAvatar:function(t,b,c,snd,a){window.__notes.push("
            "{t:t,b:b,c:c,s:snd,avatar:a});}};"
            "let t=Date.now();"
            "while(Date.now()-t<12000&&!document.querySelector('.chat-list .chat-item'))await s(120);"
            "const item=document.querySelector('.chat-list .chat-item');"
            "if(!item)return JSON.stringify({fail:'sin lista'});"
            "item.click(); await s(1100);"
            "__fm.store.user.status_preset='dnd';"
            "try{Object.defineProperty(document,'hidden',{configurable:true,"
            "get:function(){return true;}});}catch(e){return JSON.stringify({fail:e.message});}"
            "const token=" + json.dumps(B["access"]) + ";"
            "async function send(body){const r=await fetch('/api/chats/" + str(gid) + "/messages',"
            "{method:'POST',headers:{'Content-Type':'application/json',"
            "'Authorization':'Bearer '+token},body:JSON.stringify({kind:'text',body:body})});"
            "return r.status;}"
            "const st1=await send('Aviso silenciado por No molestar');"
            "await s(1800);"
            "const afterMute=window.__notes.length;"
            "const st2=await send('@" + ua + " mención directa');"
            "await s(2200);"
            "return JSON.stringify({st1:st1,st2:st2,afterMute:afterMute,"
            "notes:window.__notes})})()")
        ok, js_res, _, log = run_shot(
            f"{a.base}/?v=mobile-dnd", SHOTS / "mov-10b-dnd.png",
            js=js_dnd, wait=500)
        print("paso10b No molestar:", js_res)
        if not ok or not isinstance(js_res, dict):
            print(log[-1800:])
            raise SystemExit("✗ no se pudo probar No molestar")
        st = js_res
        if st.get("st1") != 201 or st.get("st2") != 201:
            raise SystemExit(f"✗ no llegaron los mensajes de No molestar: {st}")
        if st.get("afterMute") != 0:
            raise SystemExit(f"✗ No molestar dejó pasar un aviso normal: {st}")
        notes = st.get("notes") or []
        if len(notes) != 1 or "@" + ua not in (notes[0].get("b") or ""):
            raise SystemExit(f"✗ la mención directa no atravesó No molestar: {st}")

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
