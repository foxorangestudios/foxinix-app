#!/usr/bin/env python
"""E2E W28a/W28b: reacción rápida, copiar enlace y @menciones.

Siembra A y B (DM con dos mensajes de B) y maneja Firefox headless
(BiDi):

  1. doble clic en un mensaje de A = reacciona con su emoji reciente
     (👍 por defecto); un segundo doble clic la quita (toggle); con
     '🔥' como reciente, el doble clic usa '🔥'
  2. el menú del mensaje tiene "Copiar enlace al mensaje": copia la URL
     profunda del chat + ?m=<id> y muestra el toast "Enlace copiado"
  3. abrir ese enlace entra al chat correcto con jumpMsg apuntando al
     mensaje (deep link ?m=)

Y con un grupo A+B (W28b):

  4. el server guarda la mención de un miembro (@usuario) y la cuenta
     en unread_mentions del chat
  5. en la app de A el badge rojo aparece al llegar la mención (WS),
     abrir el grupo pinta la burbuja con la mención resaltada (propia,
     clase .me) y limpia el badge; el server queda en 0 tras el seen
  6. el compositor del grupo autocompleta @ con los miembros (el clic
     inserta "@usuario " en el draft)

Y mensajes fijados (W28c):

  7. el server acepta fijar/desfijar por API y GET /pins lista los
     fijados del chat
  8. el menú del mensaje alterna "Fijar/Desfijar mensaje", la info
     tiene la sección "Mensajes fijados" (clic = salto al mensaje) y
     un fijado de B que llega por WS refresca el panel abierto

Y galería del chat (W28d):

  9. GET /gallery devuelve las imágenes y los archivos enviados al
     chat con sus URLs y nombres
  10. la sección "Archivos y medios" de la info muestra la cuadrícula
      de fotos y las filas de archivos; el clic salta al mensaje

Bloquear usuario (W28e):

 11. bloquear corta el DM y las solicitudes de amistad en ambas
     direcciones (403) y desbloquear lo devuelve a la normalidad
 12. el ⋮ del perfil ofrece "Bloquear/Desbloquear usuario" con
     confirmación y actualiza store.blocks

Visto por en grupos (W28f):

 13. GET .../reads devuelve los miembros que superan al seq del mensaje
     propio (sin el autor), con total de miembros; mensajes ajenos 403
 14. el menú del mensaje solo ofrece "Visto por" en mensajes propios de
     un grupo y el modal lista a los lectores con su recuento

Stickers y GIFs (W28g):

 15. el server acepta kind 'sticker' (emoji corto; vacío = 400) y los
     GIF se suben como image/gif sin convertir a WebP
 16. el botón del compositor abre el panel con pestañas Stickers/GIFs:
     el sticker sale como burbuja grande sin caja y el GIF se envía
     como mensaje de imagen con la URL .gif

Llamadas de voz/video (W28h):

 17. llamar desde la cabecera del DM envía call_offer por la WS de B
     (SDP de audio) con el panel "Llamando…"; colgar cierra todo y B
     recibe call_hangup; una entrante pinta Contestar/Rechazar y
     contestar entrega la respuesta SDP a B (WebRTC 1:1; el server solo
     relaya la señalización)
 18. rechazar llega a B como 'rejected', con A ocupado la segunda
     oferta se auto-rechaza (busy) y la videollamada manda oferta con
     m=video y muestra el PIP local

Uso: server/.venv/bin/python tests/w28_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import base64
import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from websockets.sync.client import connect as wsconnect

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


def shot(url, out, js=None, wait=400, timeout=150):
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
  };"""


# W28h: SDP de oferta "válido" mínimo que B (Python) manda a A para que su
# navegador cree la respuesta sin necesidad de un peer real (no hay aiortc).
_SDP = (
    "v=0\r\n"
    "o=- 4611731400430051336 2 IN IP4 127.0.0.1\r\n"
    "s=-\r\n"
    "t=0 0\r\n"
    "a=group:BUNDLE 0\r\n"
    "a=msid-semantic: WMS\r\n"
    "m=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    "c=IN IP4 0.0.0.0\r\n"
    "a=rtcp-mux\r\n"
    "a=ice-ufrag:abcd\r\n"
    "a=ice-pwd:abcdefghijklmnopqrstuvwx\r\n"
    "a=fingerprint:sha-256 00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:"
    "00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF\r\n"
    "a=setup:actpass\r\n"
    "a=mid:0\r\n"
    "a=sendrecv\r\n"
    "a=rtpmap:111 opus/48000/2\r\n"
    "a=fmtp:111 minptime=10;useinbandfec=1\r\n"
)


class BWS(threading.Thread):
    """WS de B en segundo plano: guarda eventos en una cola y permite
    enviar mensajes de señalización (el hilo es el único que toca el
    socket: recv con timeout corto drena la cola de salida)."""

    def __init__(self, base, token):
        super().__init__(daemon=True)
        self.url = base.replace("http://", "ws://") + "/api/ws?token=" + token
        self.q = queue.Queue()
        self.out = queue.Queue()
        self.ready = threading.Event()
        self.err = None
        self._stop = False

    def run(self):
        try:
            with wsconnect(self.url, open_timeout=10, close_timeout=5) as w:
                self.ready.set()
                while not self._stop:
                    try:
                        while True:
                            w.send(self.out.get_nowait())
                    except queue.Empty:
                        pass
                    try:
                        raw = w.recv(timeout=0.2)
                    except TimeoutError:
                        continue
                    except Exception:
                        break   # conexión cerrada
                    try:
                        self.q.put(json.loads(raw))
                    except Exception:
                        pass
        except Exception as e:   # noqa: BLE001
            self.err = e
        finally:
            self.ready.set()

    def send(self, obj):
        self.out.put(json.dumps(obj))

    def wait_type(self, typ, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = self.q.get(timeout=0.3)
            except queue.Empty:
                continue
            if m.get("type") == typ:
                return m
        return None

    def wait_presence(self, uid, timeout=15):
        """Espera a que el usuario (re)conecte su WS: el hub anuncia
        presence online a los contactos en cada conexión."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                m = self.q.get(timeout=0.3)
            except queue.Empty:
                continue
            if (m.get("type") == "presence" and m.get("user_id") == uid
                    and m.get("online")):
                return m
        return None

    def drain(self):
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w28a{tag}@t.fi", f"w28a{tag}")
    B = ct.register(a.base, f"w28b{tag}@t.fi", f"w28b{tag}")
    print(f"· usuarios A={A['user']['username']} B={B['user']['username']}")

    # --- siembra REST: DM A-B con dos mensajes de B --------------------
    st, g = ct.http("POST", a.base + "/api/chats/dm",
                    {"username": B["user"]["username"]}, token=A["access"])
    if st != 200 and st != 201:
        raise SystemExit(f"✗ crear dm: {st} {g}")
    dm = g["chat"]["id"]
    for i in range(2):
        ct.send(a.base, B["access"], dm, {"body": f"mensaje de prueba {i}"})
        time.sleep(0.5)
    st, ms = ct.http("GET", f"{a.base}/api/chats/{dm}/messages",
                     token=A["access"])
    msgs = (ms or {}).get("messages") or []
    if st != 200 or len(msgs) < 2:
        raise SystemExit(f"✗ sembrar mensajes: {st} {ms}")
    mid = msgs[-1]["id"]          # último mensaje de B (el de arriba)

    # =================== sesión de A en el navegador ==================
    ok, res, log = shot(a.base + "/", SHOTS / "w28-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    # =================== 1. doble clic = reacción rápida ==============
    print("→ paso1 doble clic = reacción con el emoji reciente")
    js1 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = await wait('.chat-item', 8000);
      if (!it) return 'FAIL: sin chat en la lista';
      it.click();
      const el = await wait('.msg[data-mid=\"«MID»\"]', 12000);
      if (!el) return 'FAIL: sin mensaje en la conversación';
      let t0 = Date.now();
      while (Date.now() - t0 < 8000 && !s.loaded[«DM»]) await sleep(120);
      const myReact = (emoji) => {
        const arr = s.msgs[«DM»] || [];
        for (let i = 0; i < arr.length; i++) {
          if (arr[i].id === «MID») {
            const rs = arr[i].reactions || [];
            for (let j = 0; j < rs.length; j++) {
              if (rs[j].emoji === emoji) return true;
            }
          }
        }
        return false;
      };
      const dbl = () => el.dispatchEvent(
        new MouseEvent('dblclick', { bubbles: true, cancelable: true,
                                     view: window }));
      // doble clic 1: 👍 por defecto (sin recientes)
      localStorage.removeItem('fm.emo.recent');
      dbl(); await sleep(500);
      const react1 = myReact('👍');
      // doble clic 2: toggle → se quita
      dbl(); await sleep(500);
      const react2 = !myReact('👍');
      // emoji reciente '🔥' → el doble clic lo usa
      localStorage.setItem('fm.emo.recent', '🔥');
      dbl(); await sleep(500);
      const react3 = myReact('🔥');
      return JSON.stringify({ react1: react1, react2: react2, react3: react3 });
    })()"""
    js1 = js1.replace("«MID»", str(mid)).replace("«DM»", str(dm))
    ok1, res1, log1 = shot(a.base + "/", SHOTS / "w28-1-dblclick.png",
                           js=js1, wait=1500)
    d1 = json.loads(res1) if res1 and res1.startswith("{") else {}
    step("el doble clic reacciona con 👍 (sin recientes) y lo quita al repetir",
         ok1 and d1.get("react1") and d1.get("react2"), d1 or log1[-400:])
    step("con '🔥' como reciente, el doble clic reacciona con '🔥'",
         d1.get("react3") is True, d1)
    stm, msv = ct.http("GET", f"{a.base}/api/chats/{dm}/messages",
                       token=A["access"])
    last = ((msv or {}).get("messages") or [{}])[-1]
    emos = [r.get("emoji") for r in (last.get("reactions") or [])]
    step("la reacción quedó guardada en el server", "🔥" in emos, emos)

    # =================== 2. copiar enlace al mensaje ==================
    print("→ paso2 menú: copiar enlace al mensaje")
    js2 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = await wait('.chat-item', 8000);
      if (it) it.click();
      const el = await wait('.msg[data-mid=\"«MID»\"]', 12000);
      if (!el) return 'FAIL: sin mensaje en la conversación';
      window.__copied = '';
      document.execCommand = function (cmd) {
        if (cmd === 'copy') {
          const a = document.activeElement;
          const ta = (a && a.tagName === 'TEXTAREA') ? a
                     : document.querySelector('body > textarea');
          window.__copied = ta ? ta.value : '';
          return true;
        }
        return true;
      };
      el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true,
        cancelable: true, clientX: 240, clientY: 200, view: window }));
      const menu = await wait('.ctx-menu', 6000);
      if (!menu) return 'FAIL: no abrió el menú del mensaje';
      let mi = null;
      const items = menu.querySelectorAll('.ctx-item');
      for (let i = 0; i < items.length; i++) {
        if (items[i].textContent.indexOf('Copiar enlace') >= 0) { mi = items[i]; break; }
      }
      if (!mi) return 'FAIL: sin item "Copiar enlace al mensaje"';
      mi.click();
      await sleep(400);
      const expected = location.origin + '/app/user/«BID»?m=«MID»';
      const toasts = (document.querySelector('.toasts') || { textContent: '' })
        .textContent;
      return JSON.stringify({ copied: window.__copied, expected: expected,
                              toast: toasts.indexOf('Enlace copiado') >= 0 });
    })()"""
    js2 = js2.replace("«MID»", str(mid)).replace("«BID»", str(B["user"]["id"]))
    ok2, res2, log2 = shot(a.base + "/", SHOTS / "w28-2-enlace.png",
                           js=js2, wait=1500)
    d2 = json.loads(res2) if res2 and res2.startswith("{") else {}
    step("el menú copia el enlace /app/user/<peer>?m=<id>",
         ok2 and bool(d2.get("copied")) and d2.get("copied") == d2.get("expected"),
         d2 or log2[-400:])
    step("aparece el toast 'Enlace copiado'", d2.get("toast") is True, d2)

    # =================== 3. el enlace abre el chat + salto ============
    print("→ paso3 el enlace entra al chat con salto al mensaje")
    deep = f"{a.base}/app/user/{B['user']['id']}?m={mid}"
    ct.run_shot(deep.replace(f"?m={mid}", ""), SHOTS / "w28-x.png",
                js=sess_js(A))
    js3 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let t0 = Date.now();
      while (Date.now() - t0 < 12000 && (s.booting || !s.activeChatId)) {
        await sleep(150);
      }
      const el = await wait('.msg[data-mid=\"«MID»\"]', 8000);
      return JSON.stringify({ chat: s.activeChatId, jump: s.jumpMsg,
                              el: !!el });
    })()"""
    js3 = js3.replace("«MID»", str(mid))
    ok3, res3, log3 = shot(deep, SHOTS / "w28-3-deeplink.png",
                           js=js3, wait=2500)
    d3 = json.loads(res3) if res3 and res3.startswith("{") else {}
    step("el enlace abre el chat del DM",
         ok3 and d3.get("chat") == dm, d3 or log3[-400:])
    step("y jumpMsg apunta al mensaje enlazado (con el .msg en pantalla)",
         d3.get("jump") == mid and d3.get("el") is True, d3)

    # =================== W28b: menciones @ en grupos ==================
    st, gr = ct.http("POST", a.base + "/api/chats/group",
                     {"title": "Grupo W28",
                      "members": [B["user"]["username"]]},
                     token=A["access"])
    if st not in (200, 201):
        raise SystemExit(f"✗ crear grupo: {st} {gr}")
    gid = gr["chat"]["id"]

    print("→ paso4 el server guarda la mención y la contabiliza")
    ct.send(a.base, B["access"], gid,
            {"body": f"@{A['user']['username']} te menciono"})
    time.sleep(0.7)
    st4, ch4 = ct.http("GET", a.base + "/api/chats", token=A["access"])
    g4 = next((c for c in ch4["chats"] if c["id"] == gid), {})
    step("unread_mentions del grupo = 1 para A",
         g4.get("unread_mentions") == 1, g4.get("unread_mentions"))
    st4b, ms4 = ct.http("GET", f"{a.base}/api/chats/{gid}/messages",
                        token=A["access"])
    mid_m = ((ms4 or {}).get("messages") or [{}])[-1]
    step("el mensaje guarda mentions = [A]",
         mid_m.get("mentions") == [A["user"]["id"]], mid_m.get("mentions"))

    print("→ paso5 badge de mención + burbuja resaltada + limpieza")
    js5 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      await sleep(500);   // dejar terminar el apretón del WS
      // B menciona a A mientras la página de A está viva (llega por WS)
      const r = await fetch('/api/chats/«GID»/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',
                   'Authorization': 'Bearer «BTOK»' },
        body: JSON.stringify({ body: '@«AUSER» hola de nuevo' })
      });
      if (!r.ok) return 'FAIL: no pudo mencionar B (' + r.status + ')';
      let badge = null;
      let t0 = Date.now();
      while (Date.now() - t0 < 8000) {
        badge = document.querySelector(
          '.chat-item[data-chat-id="«GID»"] .badge.mention');
        if (badge) break;
        await sleep(120);
      }
      const badgeTxt = badge ? badge.textContent.trim() : '';
      if (badge) badge.closest('.chat-item').click();
      const el = await wait('.msg[data-mid=\"«MIDM»\"] .mention', 12000);
      const elTxt = el ? el.textContent.trim() : '';
      const isMe = el ? el.className.indexOf(' me') >= 0 : false;
      const chat = s.chats.find(function (c) { return c.id === «GID»; });
      return JSON.stringify({ badge: badgeTxt, el: elTxt, me: isMe,
                              cleared: chat ? !chat.unread_mentions : null });
    })()"""
    js5 = (js5.replace("«GID»", str(gid))
              .replace("«BTOK»", B["access"])
              .replace("«AUSER»", A["user"]["username"])
              .replace("«MIDM»", str(mid_m.get("id"))))
    ok5, res5, log5 = shot(a.base + "/", SHOTS / "w28-5-mencion.png",
                           js=js5, wait=2500)
    d5 = json.loads(res5) if res5 and res5.startswith("{") else {}
    step("el badge rojo de menciones aparece en la lista",
         ok5 and (d5.get("badge") or "").isdigit(), d5 or log5[-400:])
    step("la burbuja resalta @usuario (clase .me: es su mención)",
         d5.get("el") == f"@{A['user']['username']}" and d5.get("me") is True,
         d5)
    step("abrir el chat limpia el badge (unread_mentions = 0)",
         d5.get("cleared") is True, d5)
    st5, ch5 = ct.http("GET", a.base + "/api/chats", token=A["access"])
    g5 = next((c for c in ch5["chats"] if c["id"] == gid), {})
    step("y el server queda en 0 tras el seen",
         g5.get("unread_mentions") == 0 and g5.get("unread") == 0,
         (g5.get("unread_mentions"), g5.get("unread")))

    print("→ paso6 el compositor autocompleta @menciones en el grupo")
    js6 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = document.querySelector('.chat-item[data-chat-id="«GID»"]');
      if (!it) return 'FAIL: sin el grupo en la lista';
      it.click();
      await wait('.msg', 12000);
      const ta = await wait('.composer-input', 8000);
      if (!ta) return 'FAIL: sin compositor';
      ta.focus();
      const setV = function (v) {
        Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,
          'value').set.call(ta, v);
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      };
      setV('@');
      const pop = await wait('.m-mention', 6000);
      if (!pop) return 'FAIL: sin popup de mención';
      let row = null;
      const rows = pop.querySelectorAll('.mm-row');
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].textContent.indexOf('«BUSER»') >= 0) { row = rows[i]; break; }
      }
      if (!row) return 'FAIL: «BUSER» no está en el popup';
      row.click();
      await sleep(250);
      const picked = (ta.value || '').indexOf('@«BUSER» ') === 0;
      setV('');   // limpiar el draft (sin enviar)
      return JSON.stringify({ picked: picked, val: ta.value });
    })()"""
    js6 = (js6.replace("«GID»", str(gid))
              .replace("«BUSER»", B["user"]["username"]))
    ok6, res6, log6 = shot(a.base + "/", SHOTS / "w28-6-acmencion.png",
                           js=js6, wait=2000)
    d6 = json.loads(res6) if res6 and res6.startswith("{") else {}
    step("escribir '@' lista a los miembros y el clic inserta '@usuario '",
         ok6 and d6.get("picked") is True, d6 or log6[-400:])

    # =================== W28c: mensajes fijados =======================
    print("→ paso7 el server fijar/desfijar y listar pins")
    st7, p7 = ct.http("POST",
                      f"{a.base}/api/chats/{gid}/messages/{mid_m['id']}/pin",
                      {"pin": True}, token=A["access"])
    step("fijar por API → 200 con pinned=true",
         st7 == 200 and (p7.get("message") or {}).get("pinned") is True,
         (st7, p7))
    st7b, l7 = ct.http("GET", f"{a.base}/api/chats/{gid}/pins",
                       token=A["access"])
    ids7 = [m["id"] for m in (l7 or {}).get("messages", [])]
    step("GET /pins lista el mensaje fijado", mid_m["id"] in ids7, ids7)
    st7c, _ = ct.http("POST",
                      f"{a.base}/api/chats/{gid}/messages/{mid_m['id']}/pin",
                      {"pin": False}, token=A["access"])
    st7d, l7d = ct.http("GET", f"{a.base}/api/chats/{gid}/pins",
                        token=A["access"])
    step("desfijar deja la lista vacía",
         st7c == 200 and not (l7d or {}).get("messages"), (st7c, l7d))

    # segundo mensaje de B para el fijado por WS del paso8
    ct.send(a.base, B["access"], gid, {"body": "segundo mensaje"})
    time.sleep(0.6)
    st8s, ms8s = ct.http("GET", f"{a.base}/api/chats/{gid}/messages",
                         token=A["access"])
    mid2 = ((ms8s or {}).get("messages") or [{}])[-1]["id"]

    print("→ paso8 menú + sección de fijados en la info + WS")
    js8 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = document.querySelector('.chat-item[data-chat-id="«GID»"]');
      if (!it) return 'FAIL: sin el grupo en la lista';
      it.click();
      const el = await wait('.msg[data-mid="«MIDM»"]', 12000);
      if (!el) return 'FAIL: sin el mensaje en la conversación';
      const openMenu = () => el.dispatchEvent(
        new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
          clientX: 240, clientY: 200, view: window }));
      const findItem = (menu, txt) => {
        if (!menu) return null;
        const its = menu.querySelectorAll('.ctx-item');
        for (let i = 0; i < its.length; i++) {
          if (its[i].textContent.indexOf(txt) >= 0) return its[i];
        }
        return null;
      };
      // fijar desde el menú
      openMenu();
      const menu = await wait('.ctx-menu', 6000);
      const pi = findItem(menu, 'Fijar mensaje');
      if (!pi) return 'FAIL: sin item "Fijar mensaje"';
      pi.click();
      await sleep(500);
      const msg = (s.msgs[«GID»] || []).find(function (m) {
        return m.id === «MIDM»; });
      const pinned1 = !!(msg && msg.pinned);
      // el menú ahora ofrece desfijar (sin clicarlo: solo comprobar)
      openMenu();
      const menu2 = await wait('.ctx-menu', 6000);
      const hasDesfijar = !!findItem(menu2, 'Desfijar mensaje');
      // sección de fijados en la info (clic fuera cierra el menú)
      s.infoOpen = true;
      const head = await wait('.pp-pinhead', 6000);
      if (!head) return 'FAIL: sin la sección de mensajes fijados';
      head.click();
      const row = await wait('.pp-pinrow', 6000);
      const rowTxt = row ? row.textContent : '';
      // B fija OTRO mensaje por WS con el panel abierto
      const r = await fetch('/api/chats/«GID»/messages/«MID2»/pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',
                   'Authorization': 'Bearer «BTOK»' },
        body: JSON.stringify({ pin: true })
      });
      if (!r.ok) return 'FAIL: B no pudo fijar (' + r.status + ')';
      let rows2 = 0;
      let t0 = Date.now();
      while (Date.now() - t0 < 8000) {
        rows2 = document.querySelectorAll('.pp-pinrow').length;
        if (rows2 >= 2) break;
        await sleep(150);
      }
      // clic en la fila del mensaje original = salto
      const rows = document.querySelectorAll('.pp-pinrow');
      let go = null;
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].textContent.indexOf('te menciono') >= 0) { go = rows[i]; break; }
      }
      if (go) go.click();
      await sleep(400);
      const jumped = s.jumpMsg;
      const el2 = document.querySelector('.msg[data-mid="«MIDM»"]');
      return JSON.stringify({ pinned1: pinned1, hasDesfijar: hasDesfijar,
                              row: rowTxt, rows2: rows2, jump: jumped,
                              el: !!el2 });
    })()"""
    js8 = (js8.replace("«GID»", str(gid))
              .replace("«MIDM»", str(mid_m["id"]))
              .replace("«MID2»", str(mid2))
              .replace("«BTOK»", B["access"]))
    ok8, res8, log8 = shot(a.base + "/", SHOTS / "w28-8-fijados.png",
                           js=js8, wait=2500)
    d8 = json.loads(res8) if res8 and res8.startswith("{") else {}
    step("el menú fija el mensaje y luego ofrece desfijar",
         ok8 and d8.get("pinned1") is True and d8.get("hasDesfijar") is True,
         d8 or log8[-400:])
    step("la info lista 'Mensajes fijados' con la burbuja",
         'te menciono' in (d8.get("row") or ""), d8)
    step("un fijado de B que llega por WS refresca el panel (2 filas)",
         d8.get("rows2") == 2, d8)
    step("clic en la fila = jumpMsg al mensaje fijado (en pantalla)",
         d8.get("jump") == mid_m["id"] and d8.get("el") is True, d8)
    st8f, l8f = ct.http("GET", f"{a.base}/api/chats/{gid}/pins",
                        token=A["access"])
    ids8 = [m["id"] for m in (l8f or {}).get("messages", [])]
    step("y el server tiene los 2 fijados",
         len(ids8) == 2 and mid_m["id"] in ids8 and mid2 in ids8, ids8)

    # =================== W28d: galería del chat =======================
    print("→ paso9 la galería del server lista imágenes y archivos")
    png = SHOTS / "w28-pixel.png"
    png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    txtf = SHOTS / "w28-nota.txt"
    txtf.write_text("archivo de prueba galería", encoding="utf-8")
    up_img = ct.upload(a.base, A["access"], png)
    mi = ct.send(a.base, A["access"], gid,
                 {"kind": "image", "body": "", "media_id": up_img["id"]})
    time.sleep(0.5)
    up_txt = ct.upload(a.base, B["access"], txtf)
    mf = ct.send(a.base, B["access"], gid,
                 {"kind": "file", "body": "", "media_id": up_txt["id"]})
    time.sleep(0.5)
    st9, gal9 = ct.http("GET", f"{a.base}/api/chats/{gid}/gallery",
                        token=A["access"])
    imgs9 = (gal9 or {}).get("images") or []
    files9 = (gal9 or {}).get("files") or []
    step("GET /gallery devuelve la imagen enviada con su URL",
         st9 == 200 and bool(imgs9) and imgs9[0]["msg_id"] == mi["id"]
         and bool(imgs9[0]["media"].get("url")), (st9, imgs9[:1]))
    step("…y el archivo con su nombre",
         bool(files9) and files9[0]["msg_id"] == mf["id"]
         and files9[0]["media"].get("name") == "w28-nota.txt", files9[:1])

    print("→ paso10 la sección de la info muestra la galería")
    js10 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = document.querySelector('.chat-item[data-chat-id="«GID»"]');
      if (!it) return 'FAIL: sin el grupo en la lista';
      it.click();
      await wait('.msg', 12000);
      s.infoOpen = true;
      const heads = document.querySelectorAll('.pp-pinhead');
      let gh = null;
      for (let i = 0; i < heads.length; i++) {
        if (heads[i].textContent.indexOf('Archivos y medios') >= 0) { gh = heads[i]; break; }
      }
      if (!gh) return 'FAIL: sin la sección de archivos y medios';
      gh.click();
      const im = await wait('.pp-galimg img', 8000);
      let frow = null;
      const all = document.querySelectorAll('.gal-veil .pp-pinrow');
      for (let i = 0; i < all.length; i++) {
        if (all[i].textContent.indexOf('w28-nota.txt') >= 0) { frow = all[i]; break; }
      }
      if (!frow) return 'FAIL: sin la fila del archivo (filas=' + all.length + ')';
      frow.click();
      await sleep(500);
      const el = document.querySelector('.msg[data-mid="«MFID»"]');
      return JSON.stringify({ img: !!im, jump: s.jumpMsg, el: !!el });
    })()"""
    js10 = (js10.replace("«GID»", str(gid))
                .replace("«MFID»", str(mf["id"])))
    ok10, res10, log10 = shot(a.base + "/", SHOTS / "w28-10-galeria.png",
                              js=js10, wait=2000)
    d10 = json.loads(res10) if res10 and res10.startswith("{") else {}
    step("la galería de la info muestra la miniatura de la imagen",
         ok10 and d10.get("img") is True, d10 or log10[-400:])
    step("y el clic en el archivo salta a su mensaje",
         d10.get("jump") == mf["id"] and d10.get("el") is True, d10)

    # =================== W28e: bloquear usuario =======================
    print("→ paso11 A bloquea a B: DM y solicitudes cortados")
    st11, r11 = ct.http("POST", f"{a.base}/api/people/block",
                        {"username": B["user"]["username"]},
                        token=A["access"])
    step("POST /people/block bloquea a B", st11 == 201, (st11, r11))
    st11b, bl11 = ct.http("GET", f"{a.base}/api/people/blocks",
                          token=A["access"])
    ids11 = (bl11 or {}).get("user_ids") or []
    step("GET /people/blocks lista a B",
         st11b == 200 and B["user"]["id"] in ids11, ids11)
    st11c, rc11 = ct.http("POST", f"{a.base}/api/chats/{dm}/messages",
                          {"kind": "text", "body": "no debo pasar"},
                          token=B["access"])
    step("B ya no puede escribir en el DM (403)", st11c == 403, (st11c, rc11))
    st11d, rd11 = ct.http("POST", f"{a.base}/api/people/requests",
                          {"username": A["user"]["username"]},
                          token=B["access"])
    step("ni pedir amistad a A (403)", st11d == 403, (st11d, rd11))

    st11e, re11 = ct.http("POST", f"{a.base}/api/people/unblock",
                          {"username": B["user"]["username"]},
                          token=A["access"])
    st11f, bl11f = ct.http("GET", f"{a.base}/api/people/blocks",
                           token=A["access"])
    step("desbloquear devuelve ok y vacía la lista",
         st11e == 200 and bool((re11 or {}).get("ok")) and st11f == 200
         and not (bl11f or {}).get("user_ids"), (st11e, st11f, bl11f))
    st11g, rg11 = ct.http("POST", f"{a.base}/api/chats/{dm}/messages",
                          {"kind": "text", "body": "otra vez sí"},
                          token=B["access"])
    step("…y B vuelve a poder escribir en el DM",
         st11g in (200, 201), (st11g, rg11))

    print("→ paso12 el ⋮ del perfil bloquea y desbloquea a B")
    js12 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      if (!s.blocks) s.blocks = [];
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = document.querySelector('.chat-item[data-chat-id="«GID»"]');
      if (!it) return 'FAIL: sin el grupo en la lista';
      it.click();
      await wait('.msg', 12000);
      s.infoOpen = true;
      await sleep(400);
      let row = null;
      const rows = document.querySelectorAll('.mi-row');
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].textContent.indexOf('«BUN»') >= 0) { row = rows[i]; break; }
      }
      if (!row) return 'FAIL: sin la fila de B (filas=' + rows.length + ')';
      row.click();
      const more = await wait('.pmodal .pp-more', 8000);
      if (!more) return 'FAIL: sin el botón ⋮ del perfil';
      more.click();
      let menu = await wait('.ctx-menu', 4000);
      let blk = null;
      if (menu) {
        const its = document.querySelectorAll('.ctx-item');
        for (let i = 0; i < its.length; i++) {
          if (its[i].textContent.indexOf('Bloquear usuario') >= 0) { blk = its[i]; break; }
        }
      }
      if (!blk) return 'FAIL: sin el ítem Bloquear usuario';
      blk.click();
      const cf = await wait('.modal.confirm', 4000);
      if (!cf) return 'FAIL: sin la caja de confirmación';
      const okBtn = cf.querySelector('button.btn-danger');
      if (!okBtn) return 'FAIL: sin el botón de confirmar';
      okBtn.click();
      tb = Date.now();
      while (Date.now() - tb < 6000 && s.blocks.indexOf(«BID») < 0) await sleep(120);
      const blocked = s.blocks.indexOf(«BID») >= 0;
      more.click();
      menu = await wait('.ctx-menu', 4000);
      let unblk = null;
      if (menu) {
        const its = document.querySelectorAll('.ctx-item');
        for (let i = 0; i < its.length; i++) {
          if (its[i].textContent.indexOf('Desbloquear usuario') >= 0) { unblk = its[i]; break; }
        }
      }
      if (!unblk) return 'FAIL: sin el ítem Desbloquear usuario';
      unblk.click();
      tb = Date.now();
      while (Date.now() - tb < 6000 && s.blocks.indexOf(«BID») >= 0) await sleep(120);
      const unblocked = s.blocks.indexOf(«BID») < 0;
      return JSON.stringify({ blocked: blocked, unblocked: unblocked });
    })()"""
    js12 = (js12.replace("«GID»", str(gid))
                .replace("«BUN»", B["user"]["username"])
                .replace("«BID»", str(B["user"]["id"])))
    ok12, res12, log12 = shot(a.base + "/", SHOTS / "w28-12-bloqueo.png",
                              js=js12, wait=2000)
    d12 = json.loads(res12) if res12 and res12.startswith("{") else {}
    step("el menú del perfil bloquea a B (store.blocks lo sabe)",
         ok12 and d12.get("blocked") is True, d12 or log12[-400:])
    step("y el mismo menú lo desbloquea", d12.get("unblocked") is True, d12)

    # =================== W28f: visto por en grupos =====================
    print("→ paso13 las lecturas por miembro del grupo")
    mid13 = ct.send(a.base, A["access"], gid, {"body": "mensaje con visto por"})
    time.sleep(0.5)
    st13, r13 = ct.http("POST", f"{a.base}/api/chats/{gid}/read",
                        {"seq": mid13["seq"]}, token=B["access"])
    step("B marca leído hasta ese seq", st13 == 200, (st13, r13))
    st13b, r13b = ct.http(
        "GET", f"{a.base}/api/chats/{gid}/messages/{mid13['id']}/reads",
        token=A["access"])
    ids13 = [u["id"] for u in (r13b or {}).get("reads") or []]
    step("GET /reads lista a B y excluye al autor",
         st13b == 200 and B["user"]["id"] in ids13
         and A["user"]["id"] not in ids13
         and (r13b or {}).get("total") == 2,
         (st13b, ids13, (r13b or {}).get("total")))
    st13c, _r13c = ct.http(
        "GET", f"{a.base}/api/chats/{gid}/messages/{mid13['id']}/reads",
        token=B["access"])
    step("las lecturas de un mensaje ajeno son 403", st13c == 403, st13c)

    print("→ paso14 el menú 'Visto por' y su modal en la interfaz")
    js14 = """(async () => {
      """ + W_WAIT + """
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = document.querySelector('.chat-item[data-chat-id="«GID»"]');
      if (!it) return 'FAIL: sin el grupo en la lista';
      it.click();
      await wait('.msg', 12000);
      const findItem = (menu, txt) => {
        if (!menu) return null;
        const its = menu.querySelectorAll('.ctx-item');
        for (let i = 0; i < its.length; i++) {
          if (its[i].textContent.indexOf(txt) >= 0) return its[i];
        }
        return null;
      };
      const openMenu = (el) => el.dispatchEvent(
        new MouseEvent('contextmenu', { bubbles: true, cancelable: true,
          clientX: 240, clientY: 200, view: window }));
      /* en un mensaje de B el menú NO ofrece 'Visto por' */
      const other = await wait('.msg[data-mid="«MID2»"]', 10000);
      if (!other) return 'FAIL: sin el mensaje de B';
      openMenu(other);
      const menu1 = await wait('.ctx-menu', 6000);
      const foreign = findItem(menu1, 'Visto por');
      document.body.dispatchEvent(new MouseEvent('click',
        { bubbles: true, view: window }));
      await sleep(250);
      /* en un mensaje propio sí: y el modal lista a B */
      const mine = await wait('.msg[data-mid="«MID13»"]', 10000);
      if (!mine) return 'FAIL: sin el mensaje propio';
      openMenu(mine);
      const menu2 = await wait('.ctx-menu', 6000);
      const own = findItem(menu2, 'Visto por');
      if (!own) return 'FAIL: sin el ítem Visto por en mensaje propio';
      own.click();
      const rows = await wait('.reads-list .mi-row', 8000);
      await sleep(300);
      const lst = document.querySelector('.reads-list');
      const res = {
        foreign: !!foreign,
        own: !!rows,
        hasB: !!lst && lst.textContent.indexOf('«BUN»') >= 0,
        rows: (s.readsBox && s.readsBox.rows) ? s.readsBox.rows.length : -1,
        close: false,
      };
      const closeBtn = document.querySelector('.reads-box .icon-btn');
      if (closeBtn) {
        closeBtn.click();
        await sleep(300);
        res.close = !s.readsBox;
      }
      return JSON.stringify(res);
    })()"""
    js14 = (js14.replace("«GID»", str(gid))
                .replace("«MID2»", str(mid2))
                .replace("«MID13»", str(mid13["id"]))
                .replace("«BUN»", B["user"]["username"]))
    ok14, res14, log14 = shot(a.base + "/", SHOTS / "w28-14-vistopor.png",
                              js=js14, wait=2000)
    d14 = json.loads(res14) if res14 and res14.startswith("{") else {}
    step("el menú oculta 'Visto por' en mensajes de otros",
         ok14 and d14.get("foreign") is False, d14 or log14[-400:])
    step("…y en el propio abre la lista con B (1 lector), cerrable",
         d14.get("own") is True and d14.get("hasB") is True
         and d14.get("rows") == 1 and d14.get("close") is True, d14)

    # =================== W28g: stickers y GIFs =========================
    print("→ paso15 el server acepta stickers y conserva los GIF")
    st15, r15 = ct.http("POST", f"{a.base}/api/chats/{gid}/messages",
                        {"kind": "sticker", "body": "🔥"},
                        token=A["access"])
    m15 = (r15 or {}).get("message") or {}
    step("enviar sticker '🔥' → 201 con kind sticker",
         st15 in (200, 201) and m15.get("kind") == "sticker"
         and m15.get("body") == "🔥", (st15, m15.get("kind"), m15.get("body")))
    st15b, _r15b = ct.http("POST", f"{a.base}/api/chats/{gid}/messages",
                           {"kind": "sticker", "body": ""},
                           token=A["access"])
    step("sticker vacío → 400", st15b == 400, st15b)
    gif = (Path(__file__).resolve().parent.parent
           / "server" / "web" / "gifs" / "heart-pulse.gif")
    up_gif = ct.upload(a.base, A["access"], gif)
    step("la biblioteca GIF sube como image/gif (sin convertir a WebP)",
         up_gif.get("mime") == "image/gif", up_gif.get("mime"))
    mg = ct.send(a.base, A["access"], gid,
                 {"kind": "image", "body": "", "media_id": up_gif["id"]})
    med15 = mg.get("media") or {}
    step("…y viaja como mensaje de imagen con su GIF",
         med15.get("mime") == "image/gif" and ".gif" in (med15.get("url") or ""),
         (med15.get("mime"), med15.get("url")))

    print("→ paso16 el panel de stickers y GIFs del compositor")
    js16 = """(async () => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const wait = async (sel, ms = 12000) => {
        const t = Date.now();
        while (Date.now() - t < ms) {
          const el = document.querySelector(sel);
          if (el) return el;
          await sleep(80);
        }
        return null;
      };
      const T0 = Date.now();
      const s = window.__fm.store;
      let tb = Date.now();
      while (Date.now() - tb < 12000 && s.booting) await sleep(120);
      const it = document.querySelector('.chat-item[data-chat-id="«GID»"]');
      if (!it) return JSON.stringify({ err: 'sin el grupo en la lista' });
      it.click();
      await wait('.msg', 12000);
      const snap = () => ({
        msgs: (s.msgs[«GID»] || []).map(function (m) {
          return m.id + ':' + m.kind + ':' + (m.body || '') +
            (m.media ? '{' + (m.media.mime || '?') + ' ' +
              String(m.media.url || '').slice(-14) + '}' : '') +
            (m.pending ? ':P' : '');
        }),
        bubbles: Array.prototype.map.call(
          document.querySelectorAll('.msg .bubble'),
          function (b) { return b.className + '|' + b.textContent.slice(0, 8); }),
        imgs: Array.prototype.map.call(
          document.querySelectorAll('.msg img'),
          function (i) { return String(i.getAttribute('src') || '').slice(-24); }),
        spam: s.spamUntil || 0,
      });
      /* W29g: stickers y GIFs viven en las pestañas del panel único
         (el botón .comp-stk ya no existe: se abre con el de emojis) */
      const btn = document.querySelector('.comp-emo');
      if (!btn) return JSON.stringify({ err: 'sin botón', ...snap() });
      btn.click();
      const panel = await wait('.st-panel', 4000);
      if (!panel) return JSON.stringify({ err: 'sin panel', ...snap() });
      const tabSt = panel.querySelectorAll('.ep-tabs .ep-tab')[1];
      if (!tabSt) return JSON.stringify({ err: 'sin pestañas', ...snap() });
      tabSt.click();
      /* W36j: la pestaña entra con animación de página: esperar al
         elemento en vez de dormir (y el sticker va como <img alt>) */
      let ts = Date.now();
      let stk = null;
      while (Date.now() - ts < 4000) {
        stk = panel.querySelector('.st-e');
        if (stk) break;
        await sleep(120);
      }
      if (!stk) return JSON.stringify({ err: 'sin stickers', ...snap() });
      const stkImg = stk.querySelector('img.emo');
      const emoji = stkImg ? stkImg.getAttribute('alt') : stk.textContent;
      if (!emoji) return JSON.stringify({ err: 'sin emoji del sticker', ...snap() });
      stk.click();
      const tSend = Date.now() - T0;
      /* espera al sticker en el store (no en el DOM) y anota tardanzas */
      let inStore = false, inDom = false;
      tb = Date.now();
      while (Date.now() - tb < 12000 && !(inStore && inDom)) {
        const arr = s.msgs[«GID»] || [];
        inStore = arr.some(function (m) {
          return m.kind === 'sticker' && m.body === emoji && !m.pending;
        });
        const bs = document.querySelectorAll('.bubble.sticker');
        inDom = false;
        for (let i = 0; i < bs.length; i++) {
          /* W29b: la burbuja del sticker renderiza el emoji como <img> */
          if (bs[i].textContent.indexOf(emoji) >= 0 ||
              bs[i].querySelector('img.emo[alt="' + emoji + '"]')) inDom = true;
        }
        if (!(inStore && inDom)) await sleep(200);
      }
      const sticker = { store: inStore, dom: inDom, click: tSend,
                        got: Date.now() - T0 };
      /* pestaña GIFs: miniaturas y envío */
      btn.click();
      const panel2 = await wait('.st-panel', 4000);
      if (!panel2) return JSON.stringify({ err: 'sin panel2', sticker: sticker, ...snap() });
      const tabs = panel2.querySelectorAll('.ep-tab');
      if (tabs.length < 3) return JSON.stringify({ err: 'sin tabs', sticker: sticker, ...snap() });
      tabs[2].click();
      await sleep(500);
      const g = await wait('.st-g img', 5000);
      if (!g) return JSON.stringify({ err: 'sin gif', sticker: sticker, ...snap() });
      const srcOk = (g.getAttribute('src') || '').indexOf('/static/gifs/') >= 0;
      /* El nuevo mensaje: id mayor que los ya vistos. OJO: el <img> usa el
         directorio v-dl (W15) que lo reescribe a blob: al bajarse, así que
         la señal es el mensaje nuevo + su fila con img.b-img en el DOM. */
      const maxBefore = Math.max.apply(null,
        (s.msgs[«GID»] || []).map(function (m) { return m.id; }));
      g.parentNode.click();
      let newMsg = null, gifDom = false;
      tb = Date.now();
      while (Date.now() - tb < 15000 && !(newMsg && gifDom)) {
        const arr = s.msgs[«GID»] || [];
        newMsg = null;
        for (let i = 0; i < arr.length; i++) {
          const m = arr[i];
          if (m.id > maxBefore && m.kind === 'image' && !m.pending &&
              m.media && m.media.mime === 'image/gif') { newMsg = m; break; }
        }
        gifDom = !!(newMsg &&
          document.querySelector('.msg[data-mid="' + newMsg.id + '"] img.b-img'));
        if (!(newMsg && gifDom)) await sleep(250);
      }
      return JSON.stringify({
        panel: true, tabs: tabs.length,
        sticker: sticker.store && sticker.dom,
        stickerDetail: sticker,
        src: srcOk, gif: !!(newMsg && gifDom),
        newMsg: newMsg ? (newMsg.id + ':' + (newMsg.media || {}).mime) : null,
        snap: snap(),
      });
    })()"""
    js16 = js16.replace("«GID»", str(gid))
    ok16, res16, log16 = shot(a.base + "/", SHOTS / "w28-16-stickers.png",
                              js=js16, wait=2000)
    d16 = json.loads(res16) if res16 and res16.startswith("{") else {}
    step("el panel abre y el sticker elegido sale como burbuja grande",
         ok16 and d16.get("panel") is True and d16.get("sticker") is True,
         d16 or log16[-400:])
    step("la pestaña GIFs lista la biblioteca y envía el GIF como imagen",
         d16.get("tabs") == 3 and d16.get("src") is True
         and d16.get("gif") is True, d16)

    # ---------------------------------------------------- paso17: llamadas (W28h)
    print("→ paso17 llamada de voz saliente y llamada entrante")
    bw = BWS(a.base, B["access"])
    bw.start()
    if not bw.ready.wait(10) or bw.err:
        raise SystemExit(f"✗ la WS de B no conectó: {bw.err}")
    pool = ThreadPoolExecutor(max_workers=1)

    # CADA shot() recarga la página y el estado de llamada vive en el
    # módulo call.js (no persiste), así que el flujo entero de una
    # llamada va en UN solo shot: B (hilo principal) entretiene la
    # señalización por su WS mientras la UI de A corre en segundo plano.
    js_open = """      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const s = window.__fm.store;
      let t0 = Date.now();
      while (Date.now() - t0 < 12000 && s.booting) await sleep(120);
      if (s.activeChatId !== «DM») {
        const it = document.querySelector('.chat-item[data-chat-id="«DM»"]');
        if (it) {
          it.click();
          t0 = Date.now();
          while (Date.now() - t0 < 8000 && s.activeChatId !== «DM») await sleep(120);
        }
      }
      /* el store cambia antes del repintado de Vue: esperar al elemento */
      const waitBtn = async function (sel, ms) {
        t0 = Date.now();
        while (Date.now() - t0 < (ms || 8000)) {
          const el = document.querySelector(sel);
          if (el) return el;
          await sleep(120);
        }
        return null;
      };
      const out = {};
"""
    js17 = ("(async () => {\n" + js_open + """
      // 1) saliente: llamar; después B cuelga (cierre remoto)
      const btn = await waitBtn('.chat-head button[title="Llamar"]');
      if (!btn) return JSON.stringify({ err: 'sin botón Llamar' });
      btn.click();
      t0 = Date.now();
      while (Date.now() - t0 < 10000 && !s.call) await sleep(150);
      out.out = s.call ? { state: s.call.state, video: s.call.video,
                           chatId: s.call.chatId,
                           peer: s.call.peer ? (s.call.peer.username || '') : '' } : null;
      out.outBox = !!document.querySelector('.callbox');
      /* muestreo rápido: en localhost B cuelga casi al instante; el test
         deja 1,5 s de ventana "sin llamada" antes de la entrante */
      t0 = Date.now();
      while (Date.now() - t0 < 12000 && s.call) await sleep(50);
      out.hang1 = !s.call;
      // 2) entrante: B llama → Contestar → 'conectando'
      t0 = Date.now();
      while (Date.now() - t0 < 12000 &&
             !(s.call && s.call.state === 'incoming')) await sleep(150);
      out.in = s.call ? s.call.state : null;
      out.inPeer = s.call && s.call.peer ? (s.call.peer.username || '') : '';
      out.accept = !!document.querySelector('.callbox .call-accept');
      out.reject = !!document.querySelector('.callbox .call-reject');
      const acc = document.querySelector('.callbox .call-accept');
      if (acc) acc.click();
      /* 'conectando' es de milisegundos en el test (sin peer real el ICE
         falla y auto-corta la llamada): lo que se valida es que la UI
         salga de 'entrante' y de que B reciba la respuesta SDP real */
      t0 = Date.now();
      while (Date.now() - t0 < 8000 && s.call && s.call.state === 'incoming')
        await sleep(30);
      out.ans = s.call ? s.call.state : 'ended';
      // 3) B cuelga la llamada aceptada → A se limpia
      t0 = Date.now();
      while (Date.now() - t0 < 12000 && s.call) await sleep(150);
      out.hang2 = !s.call;
      return JSON.stringify(out);
    })()""").replace("«DM»", str(dm))
    fut17 = pool.submit(shot, a.base + "/", SHOTS / "w28-17-llamada.png",
                        js=js17, wait=1500)
    off = bw.wait_type("call_offer", 25)
    # en localhost la cadena offer→busy→hangup es instantánea: darle a la
    # UI de A un segundo para fotografiar su estado 'llamando' ANTES
    time.sleep(1.0)
    # con A en 'llamando' (sin ICE de por medio), B lo llama → busy seguro
    bw.send({"type": "call_offer", "chat_id": dm, "video": False, "sdp": _SDP})
    hb = bw.wait_type("call_hangup", 10)
    bw.send({"type": "call_hangup", "chat_id": dm, "reason": "hangup"})
    time.sleep(1.5)   # margen: A debe pintar la limpieza ANTES de la entrante
    bw.send({"type": "call_offer", "chat_id": dm, "video": False, "sdp": _SDP})
    ans = bw.wait_type("call_answer", 15)
    bw.send({"type": "call_hangup", "chat_id": dm, "reason": "hangup"})
    ok17, res17, log17 = fut17.result(timeout=180)
    d17 = json.loads(res17) if res17 and res17.startswith("{") else {}
    o17 = d17.get("out") or {}
    step("la llamada de voz saliente abre el panel y B recibe la oferta",
         ok17 and o17.get("state") in ("outgoing", "connecting")
         and o17.get("video") is False and o17.get("chatId") == dm
         and o17.get("peer") == B["user"]["username"]
         and d17.get("outBox") is True and bool(off)
         and off.get("video") is False
         and str(off.get("sdp") or "").startswith("v=0")
         and (off.get("from") or {}).get("username") == A["user"]["username"],
         {"ui": d17, "ws": off})
    step("el cierre remoto de B limpia la llamada en A",
         d17.get("hang1") is True, d17)
    step("la llamada entrante pinta Contestar/Rechazar con el nombre de B",
         d17.get("in") == "incoming"
         and d17.get("inPeer") == B["user"]["username"]
         and d17.get("accept") is True and d17.get("reject") is True, d17)
    step("contestar dispara la respuesta SDP hacia B y la UI sale de 'entrante'",
         d17.get("ans") in ("connecting", "active", "ended") and bool(ans)
         and str(ans.get("sdp") or "").startswith("v=0"), {"ui": d17, "ws": ans})
    step("con A ocupado la segunda oferta se auto-rechaza (busy)",
         bool(hb) and hb.get("reason") == "busy", hb)
    step("el segundo cierre de B también limpia la llamada",
         d17.get("hang2") is True, d17)

    # ---------------------------------------------------- paso18: rechazo + video
    print("→ paso18 rechazo de la entrante y videollamada")
    bw.drain()
    js18 = ("(async () => {\n" + js_open + """
      // 1) entrante que A RECHAZA
      t0 = Date.now();
      while (Date.now() - t0 < 15000 &&
             !(s.call && s.call.state === 'incoming')) await sleep(150);
      out.in = s.call ? s.call.state : null;
      const rej = document.querySelector('.callbox .call-reject');
      if (rej) rej.click();
      t0 = Date.now();
      while (Date.now() - t0 < 10000 && s.call) await sleep(150);
      out.clean = !s.call;
      // 2) videollamada saliente con PIP local; A cuelga con su botón
      const btn = await waitBtn('.chat-head button[title="Videollamada"]');
      if (!btn) { out.err = 'sin botón Videollamada'; return JSON.stringify(out); }
      btn.click();
      t0 = Date.now();
      while (Date.now() - t0 < 10000 && !s.call) await sleep(150);
      out.vid = s.call ? { state: s.call.state, video: s.call.video } : null;
      out.pip = !!document.querySelector('.callbox .call-pip');
      const hang = document.querySelector('.callbox .call-hang');
      if (hang) hang.click();
      t0 = Date.now();
      while (Date.now() - t0 < 10000 && s.call) await sleep(150);
      out.clean2 = !s.call;
      return JSON.stringify(out);
    })()""").replace("«DM»", str(dm))
    fut18 = pool.submit(shot, a.base + "/", SHOTS / "w28-18-video.png",
                        js=js18, wait=1500)
    # A acaba de recargar: si su WS aún no está, el offer rebotaría con
    # call_error; la presencia online delata que su socket ya vive.
    pres = bw.wait_presence(A["user"]["id"], 20)
    bw.send({"type": "call_offer", "chat_id": dm, "video": False, "sdp": _SDP})
    rj = bw.wait_type("call_hangup", 15)
    vb = bw.wait_type("call_offer", 15)
    hg = bw.wait_type("call_hangup", 10)
    ok18, res18, log18 = fut18.result(timeout=180)
    d18 = json.loads(res18) if res18 and res18.startswith("{") else {}
    step("la llamada entrante se puede rechazar (B recibe 'rejected')",
         ok18 and d18.get("in") == "incoming" and d18.get("clean") is True
         and bool(rj) and rj.get("reason") == "rejected", {"ui": d18, "ws": rj})
    step("la videollamada manda oferta con video y muestra el PIP local",
         bool(pres) and (d18.get("vid") or {}).get("video") is True
         and (d18.get("vid") or {}).get("state") in ("outgoing", "connecting")
         and d18.get("pip") is True and bool(vb) and vb.get("video") is True
         and "m=video" in str(vb.get("sdp") or ""), {"ui": d18, "ws": vb})
    step("el botón Colgar de A cierra la videollamada y avisa a B",
         d18.get("clean2") is True and bool(hg) and hg.get("reason") == "hangup",
         {"ui": d18, "ws": hg})
    bw._stop = True
    pool.shutdown(wait=False)

    # -------------------------------------------------------------------
    print()
    print(f"{'=' * 30} W28: {_pass[0]} ok, {_fail[0]} fallos")
    if ct.cleanup_db():
        print("· limpieza OK")
    return 0 if _fail[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
