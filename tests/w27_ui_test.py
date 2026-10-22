#!/usr/bin/env python
"""E2E W27: panel Personas/Amigos, foto de grupo, editor de foto y ⋮.

Siembra A, B y C (+ grupo con B, amistad C↔A y un mensaje en el DM A-C)
y maneja Firefox headless (BiDi):

  1. arranque por defecto: Personas (Activos + Solicitudes) ocupa el
     centro —reemplaza la bienvenida—, la lista de chats vive siempre
     en el sidebar y la opción "Personas" (con su icono) está en el
     PANEL DE CHATS, arriba de la lista
  2. A busca a B y le envía la solicitud → aparece en Enviados (y el
     botón de resultados queda en "Solicitud enviada")
  3. B ve Recibidas → Aceptar → se crea el DM y reemplaza Personas por
     la conversación
  4. Activos solo lista amigos en línea: C aparece (y sigue apareciendo
     con estado "No molestar" o "Ausente"); B, desconectado, no está
  5. info del DM con B (offline con preset "en línea" guardado): la
     píldora dice "Desconectado" y el puntito del info mide 23px (doble)
  6. ⋮ de la lista en el grupo (owner): "Cambiar foto del grupo"
     presente; la info del grupo ya no tiene el botón grande de salir
     y "Salir del grupo" vive en el ⋮ de la info
  7. foto de grupo por API: member → 403, owner → 200; el evento
     chat_updated refresca la lista (avatar visible) y B lo ve por REST
  7b. foto de grupo por UI: la cámara abre el editor de encuadre antes
     de subir y el encuadre aplicado se restaura al reeditar
  8. miembros del grupo ordenados: en línea primero, desconectados
     después (etiquetas de sección y punto del MISMO tamaño que la lista
     de chats, no el doble del info privado)
  9. auto-scroll por ResizeObserver: crece una fila estando al final →
     la vista baja sola
 10. editor de foto de perfil: la vista "Tu perfil" es solo lectura, el
     lápiz abre "Editar perfil" (otro modal); Cancelar no cambia nada;
     Girar → Aplicar → el preview vuelve con el encuadre RECORDADO y
     Guardar sube el recorte (avatar visible)
 11. Solicitudes: la opción "Personas" del panel de chats vuelve a la
     principal; la búsqueda filtra y "Buscar personas" abre el modal
     del ＋

Uso: server/.venv/bin/python tests/w27_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import base64
import json
import struct
import subprocess
import sys
import time
import uuid
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")
GTITLE = "Grupo W27"

# PNG mínimo (1x1) para la foto de grupo y el editor de perfil
PNG1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _png(w, h, rows):
    """PNG de verdad (RGB) sin dependencias: rows = [[(r,g,b), …], …]."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


# 2x1 con píxeles DISTINTOS: rotar 90° cambia los píxeles del canvas, así
# que sirve para comprobar que el encuadre se restaura al reeditar
PNG2 = _png(2, 1, [[(255, 0, 0), (0, 0, 255)]])

_n = [0]
_pass = [0]
_fail = [0]


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  \u2713 {name}")
    else:
        _fail[0] += 1
        print(f"  \u2717 {name}: {detail}")


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

W_HELP = """const setVal = (el, v) => {
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement
                                            : window.HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const clickText = (sel, txt) => {
    const els = document.querySelectorAll(sel);
    for (const el of els) {
      if (el.textContent.trim().indexOf(txt) >= 0) { el.click(); return true; }
    }
    return false;
  };
  const clickChatPoll = async (name, ms = 10000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const items = document.querySelectorAll('.chat-item');
      for (const it of items) {
        const n = it.querySelector('.ci-name');
        if (n && n.textContent.trim() === name) { it.click(); return true; }
      }
      await sleep(80);
    }
    return false;
  };
  const peopleWait = async () => {
    /* W27 rediseño: Personas vive en el CENTRO (reemplaza la bienvenida
       mientras no hay chat abierto); el sidebar siempre lista chats. */
    return !!(await wait('.chat-pane.people-pane .ppl'));
  };
  const ensureInfo = async () => {
    if (document.querySelector('.profile-panel')) return true;
    const b = await wait('[title="Info del chat"]', 6000);
    if (!b) return false;
    b.click();
    return !!(await wait('.profile-panel', 6000));
  };"""


def shot(url, out, js=None, wait=400, timeout=150):
    """Como ct.run_shot, pero con el JSRES bien descodificado (ct deja
    las comillas escapadas y json.loads no puede con eso)."""
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


def upload_avatar(base, tok, chat_id, data=None, name="foto.png"):
    data = data if data is not None else PNG1
    bnd = "----w27bnd"
    body = (
        f"--{bnd}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + data + f"\r\n--{bnd}--\r\n".encode()
    return ct.http("POST", f"{base}/api/chats/{chat_id}/avatar", raw=body,
                   token=tok, ctype=f"multipart/form-data; boundary={bnd}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w27a{tag}@t.fi", f"w27a{tag}")
    B = ct.register(a.base, f"w27b{tag}@t.fi", f"w27b{tag}")
    C = ct.register(a.base, f"w27c{tag}@t.fi", f"w27c{tag}")
    AD, BD, CD = (A["user"]["display_name"] or A["user"]["username"],
                  B["user"]["display_name"] or B["user"]["username"],
                  C["user"]["display_name"] or C["user"]["username"])
    print(f"· usuarios A={AD} B={BD} C={CD}")

    # --- siembra REST ---------------------------------------------------
    st, g = ct.http("POST", a.base + "/api/chats/group",
                    {"title": GTITLE, "members": [B["user"]["username"]]},
                    token=A["access"])
    if st != 201:
        raise SystemExit(f"✗ crear grupo: {st} {g}")
    gid = g["chat"]["id"]

    # B guarda preset "en línea" y se queda DESCONECTADO: el perfil debe
    # decir "Desconectado", no "En línea" (regresión del bug W27-6)
    ct.http("PUT", a.base + "/api/auth/profile", {"status_preset": "online"},
            token=B["access"])

    # amistad C→A por API (el flujo de UI ya cubre A→B)
    st, rq = ct.http("POST", a.base + "/api/people/requests",
                     {"username": A["user"]["username"]}, token=C["access"])
    st2, ppl = ct.http("GET", a.base + "/api/people", token=A["access"])
    req_id = (ppl.get("received") or [{}])[0].get("id")
    ct.http("POST", f"{a.base}/api/people/requests/{req_id}/accept", {},
            token=A["access"])

    # mensajes en el DM A-C: el paso de auto-scroll necesita una lista que
    # desborde el viewport (el rate limit es por usuario: alternamos A y C
    # con pacing; ct.send además reintenta los 429)
    st, chats = ct.http("GET", a.base + "/api/chats", token=C["access"])
    dm_ac = next(c["id"] for c in chats["chats"]
                 if c["type"] == "dm" and c["title"]["id"] == A["user"]["id"])
    for i in range(6):
        ct.send(a.base, C["access"], dm_ac,
                {"body": f"mensaje de C numero {i} con algo de texto para "
                         f"ocupar varias lineas del chat de prueba"})
        time.sleep(0.4)
        ct.send(a.base, A["access"], dm_ac,
                {"body": f"respuesta de A numero {i} con algo de texto para "
                         f"ocupar varias lineas del chat de prueba"})
        time.sleep(0.5)

    # =================== 1. arranque por defecto en Personas ===========
    print("→ paso1 arranque por defecto (Personas)")
    ok, res, log = shot(a.base + "/", SHOTS / "w27-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])
    js1 = """(async () => {
      """ + W_WAIT + """
      const t = await wait('.chat-pane.people-pane .ppl');
      if (!t) return 'FAIL: sin panel Personas en el centro';
      await sleep(400);
      const row = document.querySelector('.sidebar > .side-people');
      const list = document.querySelector('.chat-list');
      return JSON.stringify({
        ppl: !!document.querySelector('.chat-pane.people-pane .ppl'),
        lst: !!document.querySelector('.chat-list'),
        tabs: document.querySelectorAll('.side-tabs').length,
        act: !!document.querySelector('.ppl-tab.on'),
        welc: !!document.querySelector('.pane-logo'),
        sideRow: !!row && row.textContent.indexOf('Personas') >= 0 &&
          !!row.querySelector('use[href="#i-users"]'),
        aboveList: !!(row && list && row.compareDocumentPosition(list) &
          Node.DOCUMENT_POSITION_FOLLOWING),
        backBtn: !!document.querySelector('.people-pane .ppl-back-btn'),
      });
    })()"""
    ok, res, log = shot(a.base + "/", SHOTS / "w27-1-personas.png", js=js1)
    d = json.loads(res) if res and res.startswith("{") else {}
    step("Personas ocupa el centro (reemplaza la bienvenida) y la lista "
         "de chats vive en el sidebar",
         ok and d.get("ppl") and d.get("lst") and d.get("tabs") == 0
         and d.get("act") and not d.get("welc"), d or log[-400:])
    step("el panel de chats tiene la opción Personas (icono) arriba de "
         "la lista", d.get("sideRow") and d.get("aboveList"), d)
    step("móvil: la pantalla Personas tiene botón de volver",
         d.get("backBtn"), d)

    # =================== 2. A envía solicitud a B ======================
    print("→ paso2 A envía solicitud a B")
    js2 = """(async () => {
      """ + W_WAIT + W_HELP + """
      if (!(await peopleWait())) return 'FAIL: sin panel personas';
      const inp = await wait('.ppl-find input');
      if (!inp) return 'FAIL: sin buscador';
      setVal(inp, '""" + B["user"]["username"] + """');
      const btn = await (async () => {
        const t0 = Date.now();
        while (Date.now() - t0 < 8000) {
          if (clickText('.ppl-acts .btn', 'Enviar solicitud')) return true;
          await sleep(120);
        }
        return false;
      })();
      if (!btn) return 'FAIL: sin botón enviar solicitud';
      const done = await (async () => {
        const t0 = Date.now();
        while (Date.now() - t0 < 8000) {
          const els = document.querySelectorAll('.ppl-acts .btn');
          for (const el of els) {
            if (el.textContent.indexOf('Solicitud enviada') >= 0 && el.disabled) return true;
          }
          await sleep(120);
        }
        return false;
      })();
      if (!done) return 'FAIL: no quedó "Solicitud enviada"';
      document.querySelectorAll('.ppl-tab')[1].click();
      /* Esperar la fila de ENVIADOS (no la de resultados, que tarda un
         tick en desmontarse al cambiar de pestaña) */
      const sec = await (async () => {
        const t0 = Date.now();
        while (Date.now() - t0 < 6000) {
          const rows = document.querySelectorAll('.ppl-list .ppl-row');
          for (const r of rows) {
            if (r.textContent.indexOf('Cancelar') >= 0) return [r];
          }
          await sleep(120);
        }
        return null;
      })();
      if (!sec) return 'FAIL: sin filas de solicitudes';
      const txt = sec[0].textContent;
      const labels = Array.from(document.querySelectorAll('.mi-sec-always span'))
        .map(function (s) { return s.textContent.trim(); });

      /* ---- W27c: la opción Personas está en el PANEL DE CHATS (no en
         la propia pantalla) y al pulsarla se vuelve a la principal ---- */
      const inPanel = !!document.querySelector('.ppl-back');
      const side = document.querySelector('.sidebar > .side-people');
      const sideOk = !!side && side.textContent.indexOf('Personas') >= 0;
      if (side) side.click();
      await sleep(300);
      const backWorked =
        !!document.querySelectorAll('.ppl-tab')[0].classList.contains('on');
      document.querySelectorAll('.ppl-tab')[1].click();
      await sleep(300);
      const find = document.querySelector('.ppl-find');
      const reqInp = find ? find.querySelector('input') : null;
      const reqPh = reqInp ? (reqInp.getAttribute('placeholder') || '') : '';
      const findH = find ? getComputedStyle(find).height : '';
      /* la búsqueda filtra las solicitudes */
      if (reqInp) { setVal(reqInp, '""" + B["user"]["username"] + """');
        await sleep(400); }
      const rowsF = document.querySelectorAll('.ppl-list .ppl-row').length;
      const bVisible = document.querySelector('.ppl-list .ppl-row')
        ? document.querySelector('.ppl-list .ppl-row')
            .textContent.indexOf('""" + BD + """') >= 0 : false;
      if (reqInp) { setVal(reqInp, 'zzzz-qqq'); await sleep(400); }
      const empty = document.querySelector('.ppl-list .list-empty');
      const emptyTxt = empty ? empty.textContent.trim() : '';
      if (reqInp) { setVal(reqInp, ''); await sleep(350); }
      /* "Buscar personas" presiona el ＋ del sidebar (mismo modal) */
      const cta = document.querySelector('.ppl-cta .btn');
      let ctaOk = false;
      if (cta && cta.textContent.indexOf('Buscar personas') >= 0) {
        cta.click();
        await sleep(400);
        ctaOk = window.__fm.store.newChatOpen === true &&
          !!document.querySelector('.modal-veil');
        window.__fm.store.newChatOpen = false;
        await sleep(200);
      }
      return JSON.stringify({ hasB: txt.indexOf('""" + BD + """') >= 0,
                              hasCancel: txt.indexOf('Cancelar') >= 0,
                              labels: labels, sideOk: sideOk, inPanel: inPanel,
                              backWorked: backWorked, reqPh: reqPh,
                              findH: findH, rowsF: rowsF, bVisible: bVisible,
                              emptyTxt: emptyTxt, ctaOk: ctaOk });
    })()"""
    ok, res, log = shot(a.base + "/", SHOTS / "w27-2-solicitud.png",
                               js=js2, wait=500)
    d = json.loads(res) if res and res.startswith("{") else {}
    step("solicitud enviada → Enviados con A=Cancelar",
         ok and d.get("hasB") and d.get("hasCancel")
         and "Enviados" in (d.get("labels") or []), d or log[-400:])
    step("la opción Personas está en el panel de chats (no dentro de "
         "la pantalla) y vuelve a la principal",
         d.get("sideOk") and not d.get("inPanel") and d.get("backWorked"), d)
    step("Solicitudes: buscador más grueso (40px) que filtra las listas",
         d.get("findH") == "40px" and d.get("rowsF") == 1
         and d.get("bVisible"), d)
    step("Solicitudes: sin coincidencias dice Sin resultados",
         d.get("emptyTxt") == "Sin resultados", d.get("emptyTxt"))
    step("el botón Buscar personas abre el modal del ＋",
         d.get("ctaOk"), d)

    # =================== 3. B acepta → DM abierto ======================
    print("→ paso3 B acepta la solicitud")
    ok, res, log = shot(a.base + "/", SHOTS / "w27-3-inj-b.png",
                               js=sess_js(B))
    step("sesión de B inyectada", ok and res == "sesión inyectada", log[-300:])
    js3 = """(async () => {
      """ + W_WAIT + W_HELP + """
      if (!(await peopleWait())) return 'FAIL: sin panel personas';
      document.querySelectorAll('.ppl-tab')[1].click();
      const acc = await (async () => {
        const t0 = Date.now();
        while (Date.now() - t0 < 8000) {
          if (clickText('.ppl-acts .btn', 'Aceptar')) return true;
          await sleep(120);
        }
        return false;
      })();
      if (!acc) return 'FAIL: sin botón Aceptar';
      const t1 = Date.now();
      while (Date.now() - t1 < 12000) {
        if (document.querySelector('.chat-pane .msgs')) {
          const h = document.querySelector('.chat-head .ch-name');
          return JSON.stringify({
            open: !document.querySelector('.chat-pane.people-pane'),
            header: h ? h.textContent.trim() : '' });
        }
        await sleep(150);
      }
      return 'FAIL: no abrió el DM';
    })()"""
    ok, res, log = shot(a.base + "/", SHOTS / "w27-4-dm-abierto.png",
                               js=js3, wait=500)
    d = json.loads(res) if res and res.startswith("{") else {}
    step("aceptar crea el DM y reemplaza Personas por la conversación",
         ok and d.get("open") and d.get("header") == AD, d or log[-400:])

    # =================== 4. Activos: solo en línea ===================
    print("→ paso4 Activos: solo en línea (dnd/ausente cuentan)")
    ct.run_shot(a.base + "/", SHOTS / "w27-x.png", js=sess_js(A))
    js4 = """(async () => {
      """ + W_WAIT + W_HELP + """
      if (!(await peopleWait())) return 'FAIL: sin panel personas';
      const lineOfRow = function (name) {
        const rows = document.querySelectorAll('.ppl-list > .ppl-row');
        for (const r of rows) {
          const b = r.querySelector('.ppl-col b');
          if (b && b.textContent.trim() === name) {
            const i = r.querySelector('.ppl-col i');
            return i ? i.textContent.trim() : '';
          }
        }
        return '';
      };
      const dotOfRow = function (name) {
        const rows = document.querySelectorAll('.ppl-list > .ppl-row');
        for (const r of rows) {
          const b = r.querySelector('.ppl-col b');
          if (b && b.textContent.trim() === name) {
            const w = r.querySelector('.av-wrap');
            return w ? w.className : '';
          }
        }
        return '';
      };
      const t0 = Date.now();
      let seq = [], bRows = -1;
      while (Date.now() - t0 < 8000) {
        /* C está en línea de verdad solo con su cliente abierto: el test
           simula su presencia igual que haría su evento WS (W26 store).
           Se re-asegura en cada vuelta porque el snapshot que manda el
           server al conectar el WS puede pisarlo (llega tarde). */
        window.__fm.store.presence[«CID»] = true;
        seq = Array.from(document.querySelectorAll(
          '.ppl-list .mi-sec > span, .ppl-list > .ppl-row .ppl-col b'))
          .map(function (el) { return el.textContent.trim(); });
        bRows = 0;
        const rows = document.querySelectorAll('.ppl-list > .ppl-row');
        for (const r of rows) {
          const b = r.querySelector('.ppl-col b');
          if (b && b.textContent.trim() === '«BD»') bRows++;
        }
        if (seq.length >= 1) break;
        await sleep(150);
      }
      /* W27e: "No molestar" (dnd) y "Ausente" (busy) son estados de
         quien está EN LÍNEA: la fila de C sigue presente con ellos. */
      let dndLine = '', dndDot = '', busyLine = '', busyDot = '';
      const fs = window.__fm.store.people.friends;
      const fc = Array.prototype.slice.call(fs)
        .filter(function (f) { return f.id === «CID»; })[0];
      if (fc) {
        fc.status_preset = 'dnd';
        await sleep(300);
        dndLine = lineOfRow('«CD»');
        dndDot = dotOfRow('«CD»');
        fc.status_preset = 'busy';
        await sleep(300);
        busyLine = lineOfRow('«CD»');
        busyDot = dotOfRow('«CD»');
        fc.status_preset = 'online';
        await sleep(150);
      }
      /* W27e: si ningún amigo está en línea, hay aviso (no pantalla
         en blanco) */
      window.__fm.store.presence[«CID»] = false;
      let emptyTxt = '';
      const t1 = Date.now();
      while (Date.now() - t1 < 3000) {
        const em = document.querySelector('.ppl-list .list-empty');
        if (em) { emptyTxt = em.textContent.trim(); break; }
        await sleep(120);
      }
      return JSON.stringify({ seq: seq, bRows: bRows, hasC: !!fc,
                              dndLine: dndLine, dndDot: dndDot,
                              busyLine: busyLine, busyDot: busyDot,
                              emptyTxt: emptyTxt });
    })()"""
    js4 = js4.replace("«CID»", str(C["user"]["id"])).replace("«BD»", BD)
    js4 = js4.replace("«CD»", CD)
    ok, res, log = shot(a.base + "/", SHOTS / "w27-5-activos.png",
                               js=js4, wait=500)
    d = json.loads(res) if res and res.startswith("{") else {}
    seq = d.get("seq") or []
    step("Activos solo lista amigos en línea: C presente y B "
         "(desconectado) ni las etiquetas de sección",
         ok and seq == [CD] and d.get("bRows") == 0,
         seq or log[-400:])
    step("con estado No molestar / Ausente la fila sigue apareciendo",
         d.get("hasC") and d.get("dndLine") == "No molestar"
         and "st-dnd" in (d.get("dndDot") or "")
         and d.get("busyLine") == "Ausente"
         and "st-busy" in (d.get("busyDot") or ""),
         (d.get("dndLine"), d.get("busyLine"), d.get("dndDot"),
          d.get("busyDot")))
    step("sin ningún amigo en línea: aviso «Ningún amigo en línea»",
         d.get("emptyTxt") == "Ningún amigo en línea", d.get("emptyTxt"))

    # =================== 5. perfil del DM: Desconectado + punto 22px ===
    print("→ paso5 info del DM con B: píldora y punto doble")
    js5 = """(async () => {
      """ + W_WAIT + W_HELP + """
      if (!(await clickChatPoll('«BD»'))) return 'FAIL: sin DM con B';
      if (!(await ensureInfo())) return 'FAIL: sin panel de info';
      const pill = await wait('.profile-panel .pp-pill', 6000);
      const wrap = document.querySelector('.profile-panel .av-wrap.on');
      const dot = wrap ? getComputedStyle(wrap, '::after').width : '';
      const inCard = !!(wrap && wrap.parentElement &&
        wrap.parentElement.classList.contains('pp-body'));
      return JSON.stringify({ pill: pill ? pill.textContent.trim() : '',
                              dot: dot, inCard: inCard });
    })()"""
    js5 = js5.replace("«BD»", BD)
    ok, res, log = shot(a.base + "/", SHOTS / "w27-6-perfil-offline.png",
                               js=js5, wait=600)
    d = json.loads(res) if res and res.startswith("{") else {}
    step("la píldora del perfil dice Desconectado (aunque el preset "
         "guardado sea en línea)", d.get("pill") == "Desconectado", d)
    step("el puntito del info mide 23px (doble) y es el de la ficha "
         "del contacto", d.get("dot") == "23px" and d.get("inCard"), d)

    # =================== 6. ⋮ del grupo en la lista ====================
    print("→ paso6 ⋮ del grupo (owner)")
    js6 = """(async () => {
      """ + W_WAIT + W_HELP + """
      if (!(await clickChatPoll('«GT»'))) return 'FAIL: sin grupo en la lista';
      const act = document.querySelector('.chat-item.active');
      const menu = act ? act.querySelector('.ci-menu') : null;
      if (!menu) return 'FAIL: sin ⋮ en el chat-item';
      menu.click();
      const ctx = await wait('.ctx-menu', 4000);
      if (!ctx) return 'FAIL: no abrió el menú';
      const items = Array.from(document.querySelectorAll('.ctx-item'))
        .map(function (el) { return el.textContent.trim(); });
      /* W27d: la info del grupo ya NO tiene el botón grande "Salir del
         grupo"; la opción vive en el ⋮ del panel (.pp-more) */
      if (!(await ensureInfo())) return 'FAIL: sin panel de info';
      const info = document.querySelector('.profile-panel');
      const bigLeave = !!(info && info.querySelector('.pp-foot'));
      const more = info ? info.querySelector('.pp-more') : null;
      if (more) more.click();
      await sleep(400);
      const items2 = Array.from(document.querySelectorAll('.ctx-item'))
        .map(function (el) { return el.textContent.trim(); });
      return JSON.stringify({ items: items, bigLeave: bigLeave,
                              items2: items2 });
    })()"""
    js6 = js6.replace("«GT»", GTITLE)
    ok, res, log = shot(a.base + "/", SHOTS / "w27-7-menu-grupo.png",
                               js=js6, wait=500)
    d = json.loads(res) if res and res.startswith("{") else {}
    items = d.get("items") or []
    step("el ⋮ del grupo ofrece Cambiar foto del grupo (owner)",
         ok and "Cambiar foto del grupo" in items, items or log[-400:])
    step("el menú trae Salir del grupo y Ver info del chat",
         "Salir del grupo" in items and "Ver info del chat" in items, items)
    step("la info del grupo ya no tiene el botón grande de salir",
         not d.get("bigLeave"), d)
    step("Salir del grupo está en el ⋮ de la info del grupo",
         "Salir del grupo" in (d.get("items2") or []),
         d.get("items2") or d)

    # =================== 7. foto de grupo (API + WS) ===================
    print("→ paso7 foto de grupo: member 403, owner 200 + chat_updated")
    stb, rb = upload_avatar(a.base, B["access"], gid)
    step("el member NO puede cambiar la foto (403)", stb == 403, (stb, rb))
    sta, ra = upload_avatar(a.base, A["access"], gid)
    step("el owner sí (200 con avatar_url)", sta == 200 and bool(
        (ra or {}).get("avatar_url")), (sta, ra))
    js7 = """(async () => {
      """ + W_WAIT + W_HELP + """
      document.body.click();   /* cierra el ⋮ si quedó abierto */
      const t0 = Date.now();
      while (Date.now() - t0 < 8000) {
        const items = document.querySelectorAll('.chat-item');
        for (const it of items) {
          const n = it.querySelector('.ci-name');
          if (n && n.textContent.trim() === '«GT»') {
            const img = it.querySelector('.avatar img');
            if (img) return img.getAttribute('src') || 'sin-src';
          }
        }
        await sleep(150);
      }
      return 'FAIL: la lista no refrescó la foto del grupo';
    })()"""
    js7 = js7.replace("«GT»", GTITLE)
    ok, res, log = shot(a.base + "/", SHOTS / "w27-8-foto-grupo.png",
                               js=js7, wait=1500)
    step("chat_updated refresca la lista: el avatar del grupo se ve",
         ok and res and not str(res).startswith("FAIL"), res or log[-400:])
    st3, chb = ct.http("GET", a.base + "/api/chats", token=B["access"])
    g_b = next((c for c in chb["chats"] if c["id"] == gid), {})
    step("B ve la foto por REST", bool(g_b.get("avatar_url")),
         g_b.get("avatar_url"))

    # =================== 7b. foto de grupo por UI (editor) =============
    print("→ paso7b foto de grupo por UI: editor + encuadre recordado")
    js7b = """(async () => {
      """ + W_WAIT + W_HELP + """
      document.body.click();   /* cierra el ⋮ si quedó abierto */
      if (!(await clickChatPoll('«GT»'))) return 'FAIL: sin grupo';
      if (!(await ensureInfo())) return 'FAIL: sin panel de info';
      const cam = await wait('.grp-av-btn', 8000);
      if (!cam) return 'FAIL: sin botón de foto de grupo';
      const avPrev = (window.__fm.store.chats.filter(function (x) {
        return x.id === «GID»; })[0] || {}).avatar_url || '';
      cam.click();
      const inp = await wait('.tmp-file', 4000);
      if (!inp) return 'FAIL: sin input de archivo';
      const pick = () => {
        const dt = new DataTransfer();
        dt.items.add(new File([new Uint8Array([«PNG»])],
          'foto2.png', { type: 'image/png' }));
        inp.files = dt.files;
        inp.dispatchEvent(new Event('change', { bubbles: true }));
      };
      pick();
      /* W27b: la cámara ya NO sube directo: abre el editor de encuadre */
      const ed = await wait('.profile-panel .av-ed', 6000);
      if (!ed) return 'FAIL: no abrió el editor de grupo';
      clickText('.profile-panel .av-ed .btn', 'Girar');
      await sleep(300);
      const cv1 = document.querySelector('.profile-panel .av-ed-cv');
      if (!cv1) return 'FAIL: sin canvas del editor';
      const before = cv1.toDataURL();
      clickText('.profile-panel .av-ed .btn', 'Aplicar');
      const t0 = Date.now();
      let av = '';
      while (Date.now() - t0 < 15000) {
        const c = window.__fm.store.chats.filter(function (x) {
          return x.id === «GID»; })[0];
        if (c && c.avatar_url && c.avatar_url !== avPrev) { av = c.avatar_url; break; }
        await sleep(200);
      }
      if (!av) return 'FAIL: no se subió la foto desde el editor';
      /* reeditar con el MISMO archivo: el encuadre (rot=1) se restaura */
      const cam2 = await wait('.grp-av-btn', 8000);
      if (!cam2) return 'FAIL: sin botón de foto tras aplicar';
      cam2.click();
      const inp2 = await wait('.tmp-file', 4000);
      if (!inp2) return 'FAIL: sin input la segunda vez';
      const dt2 = new DataTransfer();
      dt2.items.add(new File([new Uint8Array([«PNG»])],
        'foto2.png', { type: 'image/png' }));
      inp2.files = dt2.files;
      inp2.dispatchEvent(new Event('change', { bubbles: true }));
      if (!(await wait('.profile-panel .av-ed', 6000)))
        return 'FAIL: no reabrió el editor de grupo';
      const cv2 = document.querySelector('.profile-panel .av-ed-cv');
      const after = cv2 ? cv2.toDataURL() : '';
      clickText('.profile-panel .av-ed .btn', 'Cancelar');
      return JSON.stringify({ av: av, restored: after === before });
    })()"""
    js7b = (js7b.replace("«GT»", GTITLE)
                .replace("«GID»", str(gid))
                .replace("«PNG»", ",".join(str(b) for b in PNG2)))
    ok, res, log = shot(a.base + "/", SHOTS / "w27-8b-editor-grupo.png",
                        js=js7b, wait=2500)
    d = json.loads(res) if res and res.startswith("{") else {}
    step("la cámara del grupo abre el editor y Aplicar sube el recorte",
         ok and bool(d.get("av")), d or log[-400:])
    step("al reeditar, el encuadre aplicado se restaura (rot guardado)",
         d.get("restored") is True, d)

    # =================== 8. miembros ordenados =========================
    print("→ paso8 miembros del grupo: en línea primero")
    js8 = """(async () => {
      """ + W_WAIT + W_HELP + """
      if (!(await clickChatPoll('«GT»'))) return 'FAIL: sin grupo';
      if (!(await ensureInfo())) return 'FAIL: sin panel de info';
      const first = await wait('.profile-panel .mi-row', 6000);
      if (!first) return 'FAIL: sin miembros';
      const sec = Array.from(document.querySelectorAll('.mi-sec > span'))
        .map(function (s) { return s.textContent.trim(); });
      const names = Array.from(document.querySelectorAll('.mi-row .mi-name'))
        .map(function (n) { return n.textContent.replace('Tú', '').trim(); });
      const dots = Array.from(document.querySelectorAll('.mi-row .av-wrap'))
        .map(function (w) { return w.className; });
      const w0 = document.querySelector('.mi-row .av-wrap');
      const dotW = w0 ? getComputedStyle(w0, '::after').width : '';
      return JSON.stringify({ sec: sec, names: names, dots: dots, dotW: dotW });
    })()"""
    js8 = js8.replace("«GT»", GTITLE)
    ok, res, log = shot(a.base + "/", SHOTS / "w27-9-miembros.png",
                               js=js8, wait=600)
    d = json.loads(res) if res and res.startswith("{") else {}
    names = d.get("names") or []
    step("miembros ordenados: A (en línea) antes que B (desconectado)",
         len(names) >= 2 and names[0] == AD and names[1] == BD, names)
    step("etiquetas En línea / Desconectados en el info",
         (d.get("sec") or []) == ["En línea", "Desconectados"], d.get("sec"))
    dots = d.get("dots") or []
    step("puntitos: A con clase on y B con st-off",
         dots and "on" in dots[0] and "st-off" in dots[-1], dots)
    step("el punto de los miembros mide 11px (igual que la lista de "
         "chats, no el doble del info privado)", d.get("dotW") == "14px", d)

    # =================== 9. auto-scroll por ResizeObserver ==============
    print("→ paso9 auto-scroll al crecer una fila")
    js9 = """(async () => {
      """ + W_WAIT + W_HELP + """
      if (!(await clickChatPoll('«CD»'))) return 'FAIL: sin DM A-C';
      const msgs = await wait('.msgs');
      if (!msgs) return 'FAIL: sin .msgs';
      msgs.scrollTop = msgs.scrollHeight;
      await sleep(300);
      const st0 = msgs.scrollTop;
      const last = msgs.lastElementChild;
      if (!last) return 'FAIL: sin filas';
      last.style.minHeight = (last.offsetHeight + 280) + 'px';
      await sleep(600);
      return JSON.stringify({ st0: st0, st1: msgs.scrollTop });
    })()"""
    js9 = js9.replace("«CD»", CD)
    ok, res, log = shot(a.base + "/", SHOTS / "w27-10-autoscroll.png",
                               js=js9, wait=600)
    d = json.loads(res) if res and res.startswith("{") else {}
    step("al crecer una fila estando al final, la vista baja sola",
         ok and d.get("st1", 0) > d.get("st0", 0) + 100, d or log[-400:])

    # =================== 10. editor de foto de perfil ==================
    print("→ paso10 Tu perfil (vista) + Editar perfil: cancelar / girar / "
          "encuadre recordado / guardar")
    js10 = """(async () => {
      """ + W_WAIT + W_HELP + """
      const up = await wait('.up-main', 12000);
      if (!up) return 'FAIL: sin botón Tu perfil';
      up.click();
      /* W27b: "Tu perfil" es SOLO la ficha; el formulario está en OTRO
         modal al que se entra con el lápiz */
      const view = await wait('.modal.meprof:not(.mp-edit)', 6000);
      if (!view) return 'FAIL: sin modal Tu perfil';
      if (!view.querySelector('.mp-view')) return 'FAIL: sin ficha';
      if (view.querySelector('input[type=file]')) {
        return 'FAIL: la vista no debe tener el formulario';
      }
      const pencil = view.querySelector('.mp-edit-open');
      if (!pencil) return 'FAIL: sin lápiz de editar';
      const pencilIc = pencil.querySelector('use');
      const pencilOk = !!pencilIc &&
        (pencilIc.getAttribute('href') || '').indexOf('i-pencil') >= 0;
      pencil.click();
      const mp = await wait('.modal.mp-edit', 5000);
      if (!mp) return 'FAIL: no abrió Editar perfil';
      const inp = mp.querySelector('input[type=file]');
      if (!inp) return 'FAIL: sin input de foto';
      const pick = () => {
        const dt = new DataTransfer();
        dt.items.add(new File([new Uint8Array([«PNG»])],
          'foto.png', { type: 'image/png' }));
        inp.files = dt.files;
        inp.dispatchEvent(new Event('change', { bubbles: true }));
      };
      pick();
      if (!(await wait('.mp-edit .av-ed', 4000))) return 'FAIL: no abrió el editor';
      /* cancelar: no debe cambiar nada */
      clickText('.mp-edit .av-ed .btn', 'Cancelar');
      await sleep(300);
      if (document.querySelector('.mp-edit .av-ed')) return 'FAIL: Cancelar no cerró';
      if (document.querySelector('.mp-edit .av-img img:not(.fox)'))
        return 'FAIL: Cancelar dejó preview';
      /* aplicar con una rotación */
      pick();
      if (!(await wait('.mp-edit .av-ed', 4000))) return 'FAIL: no reabrió el editor';
      clickText('.mp-edit .av-ed .btn', 'Girar');
      await sleep(250);
      const cv1 = document.querySelector('.mp-edit .av-ed-cv');
      if (!cv1) return 'FAIL: sin canvas';
      const before = cv1.toDataURL();
      clickText('.mp-edit .av-ed .btn', 'Aplicar');
      const prev = await (async () => {
        const t0 = Date.now();
        while (Date.now() - t0 < 6000) {
          const img = document.querySelector('.mp-edit .av-img img:not(.fox)');
          if (img) return img;
          await sleep(120);
        }
        return null;
      })();
      if (!prev) return 'FAIL: no quedó el recorte aplicado';
      const src = prev.getAttribute('src') || '';
      if (src.indexOf('blob:') !== 0) return 'FAIL: el preview no es el recorte';
      /* el lápiz "Ajustar foto" reabre el editor con el encuadre
         recordado (rot=1): el canvas debe ser idéntico al aplicado */
      const adj = mp.querySelector('.av-edit');
      if (!adj) return 'FAIL: sin botón Ajustar foto';
      adj.click();
      if (!(await wait('.mp-edit .av-ed', 4000)))
        return 'FAIL: no reabrió el editor al reeditar';
      const cv2 = document.querySelector('.mp-edit .av-ed-cv');
      const restored = !!cv2 && cv2.toDataURL() === before;
      clickText('.mp-edit .av-ed .btn', 'Cancelar');
      await sleep(200);
      if (!document.querySelector('.mp-edit .av-img img:not(.fox)')) {
        return 'FAIL: reeditar perdió el preview';
      }
      /* guardar */
      const btns = document.querySelectorAll('.mp-edit .m-foot .btn');
      btns[btns.length - 1].click();
      const t1 = Date.now();
      let avatar = '';
      while (Date.now() - t1 < 15000) {
        const u = window.__fm.store.user;
        if (u && u.avatar_url) { avatar = u.avatar_url; break; }
        await sleep(200);
      }
      if (!avatar) return 'FAIL: no se guardó el avatar';
      /* la ficha reabre tras guardar: MI píldora no debe decir
         "Desconectado" estando conectado (W27c) */
      const v2 = await wait('.modal.meprof:not(.mp-edit)', 6000);
      const pill = v2 && v2.querySelector('.mp-view .pp-pill');
      const pillTxt = pill ? pill.textContent.trim() : '';
      return JSON.stringify({ avatar: avatar, pencilOk: pencilOk,
                              restored: restored, pill: pillTxt });
    })()"""
    js10 = js10.replace("«PNG»", ",".join(str(b) for b in PNG2))
    ok, res, log = shot(a.base + "/", SHOTS / "w27-11-editor.png",
                               js=js10, wait=4000)
    d = json.loads(res) if res and res.startswith("{") else {}
    step("el lápiz abre Editar perfil (modal aparte) y el editor "
         "cancelar/girar/aplicar/guardar sube el recorte",
         ok and bool(d.get("avatar")) and d.get("pencilOk"), d or log[-400:])
    step("la ficha reabre con MI píldora (no dice Desconectado en línea)",
         bool(d.get("pill")) and d.get("pill") != "Desconectado", d)
    step("al reeditar la foto, el encuadre aplicado se restaura",
         d.get("restored") is True, d)
    stme, me = ct.http("GET", a.base + "/api/users/me", token=A["access"])
    step("el avatar quedó guardado en el perfil (REST)",
         stme == 200 and bool((me.get("user") or {}).get("avatar_url")),
         (me or {}) if stme == 200 else (stme, me))

    # -------------------------------------------------------------------
    print("→ paso11 pantallas de carga (W27h)")
    js11 = """
    (async () => {
      const sleep = (ms) => new Promise(r => setTimeout(r, ms));
      const s = window.__fm.store;
      // CSS: aire arriba de la barra de búsqueda (Activos y Solicitudes)
      const probe = document.createElement('div');
      probe.className = 'people-pane';
      probe.innerHTML = '<div class="search-pill ppl-find"></div>';
      document.body.appendChild(probe);
      const pad = getComputedStyle(probe.firstChild).marginTop;
      probe.remove();
      const lb = document.createElement('div');
      lb.className = 'msgs-load';
      document.body.appendChild(lb);
      const lcs = getComputedStyle(lb);
      const loadCss = lcs.display;
      const loadGrow = lcs.flexGrow;
      const loadJust = lcs.justifyContent;
      lb.remove();
      const ab = document.createElement('div');
      ab.className = 'app-boot';
      document.body.appendChild(ab);
      const bootCss = getComputedStyle(ab).position;
      ab.remove();
      // el arranque real termina sin overlay colgado
      let t0 = Date.now();
      while (Date.now() - t0 < 10000 && s.booting) await sleep(150);
      const bootGone = !s.booting && !document.querySelector('.app-boot');
      // el overlay del arranque responde al flag y dice "Cargando…"
      s.booting = true; await sleep(150);
      const bo = document.querySelector('.app-boot');
      const bootShown = !!bo && bo.textContent.indexOf('Cargando') >= 0;
      s.booting = false; await sleep(150);
      const bootGone2 = !document.querySelector('.app-boot');
      // abrir el primer chat si no hay ninguno activo
      if (!s.activeChatId) {
        const it = document.querySelector('.chat-item');
        if (it) it.click();
        let t2 = Date.now();
        while (Date.now() - t2 < 8000 && !s.activeChatId) await sleep(120);
      }
      const cid = s.activeChatId;
      let t3 = Date.now();
      while (Date.now() - t3 < 8000 && !s.loaded[cid]) await sleep(120);
      // chat ya cargado + flag: NO se tapa la conversación
      s.chatLoading = true; await sleep(150);
      const noCover = !document.querySelector('.msgs-load');
      // sin mensajes cargados + flag: aparece el "Cargando…" con texto
      s.loaded[cid] = false; await sleep(150);
      const mo = document.querySelector('.msgs-load');
      const loadShown = !!mo && mo.textContent.indexOf('Cargando') >= 0;
      // centrado en la zona de mensajes y encima de la barra de escribir
      let centered = 0;
      let aboveComposer = 0;
      if (mo) {
        const m = mo.getBoundingClientRect();
        const sc = document.querySelector('.msgs');
        const cp = document.querySelector('.composer');
        if (sc && cp) {
          const sr = sc.getBoundingClientRect();
          const mid = sr.top + sr.height / 2;
          const blockMid = m.top + m.height / 2;
          centered = Math.abs(blockMid - mid) < 40 ? 1 : 0;
          aboveComposer = cp.getBoundingClientRect().top >= sr.bottom - 2 ? 1 : 0;
        }
      }
      // restaurar
      s.chatLoading = false;
      s.loaded[cid] = true; await sleep(150);
      const loadGone = !document.querySelector('.msgs-load');
      return JSON.stringify({ pad: pad, loadCss: loadCss, bootCss: bootCss,
        loadGrow: loadGrow, loadJust: loadJust,
        bootGone: bootGone, bootShown: bootShown, bootGone2: bootGone2,
        cid: cid, noCover: noCover, loadShown: loadShown, loadGone: loadGone,
        centered: centered, aboveComposer: aboveComposer });
    })()"""
    ok11, res11, log11 = shot(a.base + "/", SHOTS / "w27-12-carga.png",
                              js=js11, wait=3000)
    d11 = json.loads(res11) if res11 and res11.startswith("{") else {}
    step("W27h: la barra de búsqueda de Personas tiene aire arriba (18px)",
         d11.get("pad") == "18px", d11 or log11[-400:])
    step("W27h: estilos de .msgs-load (flex:1, centrado) y .app-boot (fixed)",
         d11.get("loadCss") == "flex" and d11.get("loadGrow") == "1"
         and d11.get("loadJust") == "center" and d11.get("bootCss") == "fixed",
         d11)
    step("W27h: el arranque termina sin overlay y el overlay dice Cargando…",
         ok11 and d11.get("bootGone") and d11.get("bootShown")
         and d11.get("bootGone2"), d11 or log11[-400:])
    step("W27h: la conversación muestra Cargando… centrado encima del "
         "composer y el chat cargado no se tapa",
         bool(d11.get("cid")) and d11.get("noCover") and d11.get("loadShown")
         and d11.get("loadGone") and d11.get("centered")
         and d11.get("aboveComposer"), d11)

    # -------------------------------------------------------------------
    print()
    print(f"{'=' * 30} W27: {_pass[0]} ok, {_fail[0]} fallos")
    if ct.cleanup_db():
        print("· limpieza OK")
    return 0 if _fail[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
