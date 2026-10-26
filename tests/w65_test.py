#!/usr/bin/env python3
"""E2E W65: enlaces por ID, menciones seguras, ajustes y apariencias.

  - /api/users/id/<id> devuelve la relación (me/friend/sent/received/blocked)
    y los enlaces directos sin MD generan la solicitud automáticamente.
  - Las menciones se guardan como @<id> y se muestran con el @usuario actual,
    sobreviviendo a un cambio de nombre.
  - Las URLs de Ajustes usan slugs (appearance/notifications/...), el tema
    Oscuro puro se elige con muestras de color y el móvil no desborda.
  - Emojis: la rejilla no cae a glifos del sistema; texto pegado se convierte
    sólo al enviar. Selección, tacto y hitboxes móviles.

Uso: server/.venv/bin/python tests/w65_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def jparse(res):
    try:
        return json.loads(res) if res and res.startswith("{") else {}
    except Exception:
        return {}


def sess_js(u):
    sess = json.dumps({"access": u["access"], "refresh": u["refresh"],
                       "user": u["user"], "pendingEmail": ""})
    return ct.JS_INJECT.replace(
        "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))


def shot(url, out, js=None, wait=700, width=1280, height=860, viewport=False,
         timeout=240):
    cmd = [str(ct.PY), str(ct.SHOT), url, str(out), "--wait", str(wait),
           "--width", str(width), "--height", str(height)]
    if viewport:
        cmd.append("--viewport")
    if js:
        cmd += ["--js", js]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    res = None
    for line in r.stdout.splitlines():
        if line.startswith("JSRES: "):
            try:
                v = json.loads(line[7:].strip())
                res = v if isinstance(v, str) else json.dumps(
                    v, ensure_ascii=False)
            except Exception:
                res = line[7:].strip()
    ok = r.returncode == 0 and "SHOT:" in r.stdout
    return ok, res, (r.stdout + r.stderr)


W_WAIT = """
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (fn, ms = 12000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      let v = null;
      try { v = fn(); } catch (e) {}
      if (v) return v;
      await sleep(80);
    }
    return null;
  };
  const boot = async () => {
    let t = Date.now();
    while (Date.now() - t < 18000) {
      if (window.__fm && __fm.store && !__fm.store.booting) break;
      await sleep(120);
    }
    t = Date.now();
    while (Date.now() - t < 12000 && __fm.store && __fm.store.ws !== 'on')
      await sleep(120);
  };
"""

JS_DEEP = """(async () => {
  «WAIT»
  const out = { stage: 'inicio' };
  await boot();
  out.urlInicial = location.pathname + location.search;
  const modal = await wait(() => document.querySelector('.req-sent'), 16000);
  out.modal = !!modal;
  if (!modal) {
    out.stage = 'sin-modal';
    out.relation = __fm.store.profile && __fm.store.profile.relation;
    out.error = __fm.store.profile && __fm.store.profile.error;
    return JSON.stringify(out);
  }
  out.titulo = (modal.querySelector('header') || {}).textContent || '';
  out.texto = (modal.querySelector('.req-sent-body') || {}).textContent || '';
  out.check = !!modal.querySelector('.req-sent-check use[href="#i-check"]');
  out.enlace = (modal.querySelector('.req-link') || {}).textContent || '';
  out.okey = (modal.querySelector('.req-ok') || {}).textContent || '';
  out.relation = __fm.store.profile && __fm.store.profile.relation;
  out.sentStore = !!__fm.store.requestSent;
  out.urlAntes = location.pathname + location.search;
  out.perfilId = __fm.store.profile && __fm.store.profile.user &&
    __fm.store.profile.user.id;
  const link = modal.querySelector('.req-link');
  if (link) link.click();
  await sleep(800);
  out.modalTrasLink = !!document.querySelector('.req-sent');
  out.urlTrasLink = location.pathname + location.search;
  out.pestana = __fm.store.peopleTab;
  out.people = !!document.querySelector('.ppl-tabs');
  out.sentC = ((__fm.store.people && __fm.store.people.sent) || [])
    .some(x => x.user && x.user.id === «CID»);
  out.stage = 'ok';
  return JSON.stringify(out);
})()"""

JS_FRIEND = """(async () => {
  «WAIT»
  const out = { stage: 'inicio' };
  await boot();
  const chat = await wait(() => __fm.store.activeChatId, 16000);
  out.chatId = chat || 0;
  out.url = location.pathname + location.search;
  const c = (__fm.store.chats || []).find(x => x.id === __fm.store.activeChatId);
  out.tipo = c ? c.type : '';
  out.peerId = c && c.title ? c.title.id : 0;
  out.composer = !!document.querySelector('.composer-input');
  out.modal = !!document.querySelector('.req-sent');
  out.sentStore = !!__fm.store.requestSent;
  out.stage = out.chatId ? 'ok' : 'sin-chat';
  return JSON.stringify(out);
})()"""

JS_EDGE = """(async () => {
  «WAIT»
  const out = { stage: 'inicio', casos: {} };
  await boot();
  const cases = [
    ['sent', «DID», 'Solicitud pendiente', true],
    ['received', «EID», 'Aceptar solicitud', false],
    ['blocked', «FID», 'Bloqueado', true]
  ];
  for (const [rel, id, label, disabled] of cases) {
    history.replaceState(null, '', '/app/user/' + id);
    window.dispatchEvent(new PopStateEvent('popstate'));
    const p = await wait(() => __fm.store.profile && __fm.store.profile.user &&
      __fm.store.profile.user.id === id, 14000);
    await sleep(350);
    const btn = document.querySelector('.pmodal .pp-foot .btn');
    out.casos[rel] = {
      abierto: !!p,
      relation: __fm.store.profile && __fm.store.profile.relation,
      label: btn ? (btn.textContent || '').trim() : '',
      disabled: btn ? !!btn.disabled : null,
      esperadoLabel: label,
      esperadoDisabled: disabled,
      modalSolicitud: !!document.querySelector('.req-sent')
    };
    __fm.store.profile = null;
    await sleep(200);
  }
  history.replaceState(null, '', '/app/user/«AID»');
  window.dispatchEvent(new PopStateEvent('popstate'));
  const me = await wait(() => __fm.store.meProfileOpen, 12000);
  out.yo = { abierto: !!me, modal: !!document.querySelector('.meprof'),
    modalSolicitud: !!document.querySelector('.req-sent') };
  out.stage = 'ok';
  return JSON.stringify(out);
})()"""

JS_PLUS = """(async () => {
  «WAIT»
  const out = { stage: 'inicio' };
  await boot();
  const plus = await wait(() => document.querySelector('.side-new'));
  if (!plus) return JSON.stringify({ stage: 'sin-plus' });
  plus.click();
  const input = await wait(() => document.querySelector('.m-search input'));
  if (!input) return JSON.stringify({ stage: 'sin-buscador' });
  input.value = '«GUSER»';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  const row = await wait(() => {
    const rows = Array.from(document.querySelectorAll('.results .res-item'));
    return rows.find(el => (el.textContent || '').indexOf('«GUSER»') >= 0);
  }, 12000);
  out.buscado = !!row;
  if (!row) return JSON.stringify(out);
  row.click();
  const modal = await wait(() => document.querySelector('.req-sent'), 12000);
  out.modal = !!modal;
  out.titulo = modal ? (modal.querySelector('header') || {}).textContent || '' : '';
  out.pickerCerrado = __fm.store.newChatOpen === false;
  out.sentStore = !!__fm.store.requestSent;
  out.usuario = __fm.store.requestSent && __fm.store.requestSent.username;
  const ok = modal && modal.querySelector('.req-ok');
  if (ok) ok.click();
  await sleep(300);
  out.modalCerrado = !document.querySelector('.req-sent');
  out.stage = modal ? 'ok' : 'sin-modal';
  return JSON.stringify(out);
})()"""

JS_SETTINGS = """(async () => {
  «WAIT»
  const out = { stage: 'inicio', slugs: {} };
  await boot();
  const cases = [
    ['appearance', 'apariencia'], ['notifications', 'notificaciones'],
    ['chat', 'chat'], ['privacy', 'privacidad'], ['downloads', 'descargas'],
    ['shortcuts', 'atajos'], ['account', 'cuenta']
  ];
  for (const [slug, tab] of cases) {
    history.replaceState(null, '', '/app?settings=' + slug);
    window.dispatchEvent(new PopStateEvent('popstate'));
    await sleep(220);
    out.slugs[slug] = {
      open: __fm.store.settingsOpen,
      tab: __fm.store.settingsTab,
      esperado: tab,
      url: location.pathname + location.search,
      body: !!document.querySelector('.modal.settings .st-body')
    };
  }
  /* La UI debe emitir el slug semántico al cambiar de pestaña. */
  __fm.store.settingsTab = 'privacidad';
  await sleep(260);
  out.slugGenerado = location.search;
  __fm.store.settingsTab = 'apariencia';
  await sleep(260);
  const sw = Array.from(document.querySelectorAll('.ap-theme'));
  out.swatches = sw.length;
  out.swatchTexto = sw.map(x => (x.textContent || '').trim());
  out.swatchNombres = sw.map(x => x.getAttribute('title'));
  const black = sw.find(x => x.getAttribute('title') === 'Oscuro puro');
  if (black) black.click();
  await sleep(260);
  out.theme = __fm.store.theme;
  out.themeAttr = document.documentElement.getAttribute('data-theme');
  out.bg = getComputedStyle(document.documentElement)
    .getPropertyValue('--bg').trim();
  const dark = sw.find(x => x.getAttribute('title') === 'Intermedio');
  if (dark) dark.click();
  await sleep(180);
  out.dark = __fm.store.theme;
  out.darkBg = getComputedStyle(document.documentElement)
    .getPropertyValue('--bg').trim();
  out.stage = 'ok';
  return JSON.stringify(out);
})()"""

JS_MOBILE_SETTINGS = """(async () => {
  «WAIT»
  const out = { stage: 'inicio' };
  await boot();
  const tabAjustes = await wait(() => Array.from(
    document.querySelectorAll('.mobile-tabs .mt-btn'))
    .find(x => (x.textContent || '').indexOf('Ajustes') >= 0));
  if (!tabAjustes) return JSON.stringify({ stage: 'sin-boton-ajustes' });
  tabAjustes.click();
  const home = await wait(() => document.querySelector('.st-mobile-home'));
  out.home = !!home;
  out.urlHome = location.search;
  out.atHome = __fm.store.settingsAtHome;
  out.cats = document.querySelectorAll('.st-cat').length;
  out.navHome = !!document.querySelector('.mobile-tabs');
  out.catBox = (() => {
    const c = document.querySelector('.st-cat');
    if (!c) return null;
    const r = c.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  })();
  const notif = Array.from(document.querySelectorAll('.st-cat'))
    .find(x => (x.textContent || '').indexOf('Notificaciones') >= 0);
  out.hayNotif = !!notif;
  if (notif) notif.click();
  await sleep(500);
  out.notifTab = __fm.store.settingsTab;
  out.notifUrl = location.search;
  out.atHomeTras = __fm.store.settingsAtHome;
  out.navDentro = !!document.querySelector('.mobile-tabs');
  out.back = !!document.querySelector('.st-back');
  const body = document.querySelector('.modal.settings .st-body');
  out.overflowBody = body ? body.scrollWidth - body.clientWidth : -1;
  out.overflowModal = (() => {
    const m = document.querySelector('.modal.settings');
    return m ? m.scrollWidth - m.clientWidth : -1;
  })();
  out.tone = !!document.querySelector('.modal.settings .tone-sec');
  const back = document.querySelector('.st-back');
  if (back) back.click();
  await sleep(350);
  out.homeVolvio = __fm.store.settingsAtHome;
  out.urlVolvio = location.search;
  out.navVolvio = !!document.querySelector('.mobile-tabs');
  out.stage = 'ok';
  return JSON.stringify(out);
})()"""

JS_MOBILE_CHAT = """(async () => {
  «WAIT»
  const out = { stage: 'inicio' };
  await boot();
  const item = await wait(() => document.querySelector(
    '.chat-list .chat-item[data-chat-id="«GID»"]'));
  if (!item) return JSON.stringify({ stage: 'sin-chat' });
  item.click();
  const ok = await wait(() => !!__fm.store.loaded[«GID»], 14000);
  if (!ok) return JSON.stringify({ stage: 'sin-cargar' });
  await sleep(400);
  const st = await import('/static/js/store.js');
  st.setPrefStr('emo', 'twemoji');
  await sleep(250);
  const pick = await wait(() => document.querySelector('.comp-emo'));
  pick.click();
  await sleep(450);
  const cells = Array.from(document.querySelectorAll(
    '.emo-picker .ep-body .ep-e'));
  out.cells = cells.length;
  out.conImg = cells.filter(x => !!x.querySelector('img')).length;
  out.glifos = cells.filter(x => !x.querySelector('img') &&
    (x.textContent || '').trim()).length;
  out.alts = cells.filter(x => {
    const im = x.querySelector('img');
    return im && (im.getAttribute('alt') || '') !== '';
  }).length;
  out.rutas = cells.filter(x => {
    const im = x.querySelector('img');
    return im && /^https?:|^\\/static\\/emoji\\//.test(im.getAttribute('src') || '');
  }).length;
  const cats = document.querySelector('.ep-cats');
  const cat = document.querySelector('.ep-cat');
  const tabs = document.querySelector('.ep-tabs');
  out.catBox = cats ? Math.round(cats.getBoundingClientRect().width) : 0;
  out.catUno = cat ? Math.round(cat.getBoundingClientRect().width) : 0;
  out.tabAlto = tabs ? Math.round(tabs.getBoundingClientRect().height) : 0;
  pick.click();
  await sleep(200);
  const input = document.querySelector('.composer-input');
  input.focus();
  input.value = ':fire: 😂';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await sleep(300);
  out.antesEnviar = input.value;
  const before = __fm.store.msgs[«GID»].length;
  const send = document.querySelector('.send-btn');
  send.click();
  await sleep(900);
  const arr = __fm.store.msgs[«GID»] || [];
  const last = arr[arr.length - 1];
  out.enviados = arr.length - before;
  out.cuerpo = last ? last.body : '';
  out.trasEnviar = input.value;
  out.selPane = (() => {
    const p = document.querySelector('.chat-pane');
    return p ? getComputedStyle(p).userSelect : '';
  })();
  out.selMsg = (() => {
    const m = document.querySelector('.msgs .msg');
    return m ? getComputedStyle(m).userSelect : '';
  })();
  out.selInput = getComputedStyle(input).userSelect;
  out.touchSend = getComputedStyle(send).touchAction;
  out.stage = 'ok';
  return JSON.stringify(out);
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:6]
    try:
        print("→ preparar cuentas y relaciones")
        A = ct.register(a.base, f"w65a{tag}@t.fi", f"w65a{tag}")
        B = ct.register(a.base, f"w65b{tag}@t.fi", f"w65b{tag}")
        C = ct.register(a.base, f"w65c{tag}@t.fi", f"w65c{tag}")
        D = ct.register(a.base, f"w65d{tag}@t.fi", f"w65d{tag}")
        E = ct.register(a.base, f"w65e{tag}@t.fi", f"w65e{tag}")
        F = ct.register(a.base, f"w65f{tag}@t.fi", f"w65f{tag}")
        G = ct.register(a.base, f"w65g{tag}@t.fi", f"w65g{tag}")
        AU, BU, CU, DU, EU, FU, GU = (
            A["user"]["username"], B["user"]["username"], C["user"]["username"],
            D["user"]["username"], E["user"]["username"], F["user"]["username"],
            G["user"]["username"])
        ids = {x["user"]["username"]: x["user"]["id"]
               for x in (A, B, C, D, E, F, G)}

        ct.ensure_friends(a.base, A["access"], B["access"], AU, BU)
        st, r = ct.http("POST", a.base + "/api/people/requests",
                        {"username": DU}, token=A["access"])
        step("A envía solicitud pendiente a D", st == 201, f"{st} {r}")
        st, r = ct.http("POST", a.base + "/api/people/requests",
                        {"username": AU}, token=E["access"])
        step("E deja una solicitud pendiente a A", st == 201, f"{st} {r}")
        st, r = ct.http("POST", a.base + "/api/people/block",
                        {"username": FU}, token=A["access"])
        step("A bloquea a F", st == 201, f"{st} {r}")

        print("→ /api/users/id y estados de relación")
        esperados = {
            "me": ids[AU], "friend": ids[BU], "none": ids[CU],
            "sent": ids[DU], "received": ids[EU], "blocked": ids[FU],
        }
        for rel, uid in esperados.items():
            st, r = ct.http("GET", f"{a.base}/api/users/id/{uid}",
                            token=A["access"])
            step(f"perfil por ID: relación {rel}",
                 st == 200 and r.get("relation") == rel
                 and (r.get("user") or {}).get("id") == uid, f"{st} {r}")
        st, r = ct.http("GET", f"{a.base}/api/users/id/{ids[GU]}",
                        token=A["access"])
        step("perfil por ID: cuenta sin relación", st == 200
             and r.get("relation") == "none", f"{st} {r}")
        st, r = ct.http("GET", f"{a.base}/api/users/id/99999999",
                        token=A["access"])
        step("perfil por ID inexistente → 404", st == 404, f"{st} {r}")

        print("→ menciones @<id> seguras al cambiar de @usuario")
        st, r = ct.http("POST", a.base + "/api/chats/group",
                        {"title": f"W65-{tag}", "members": [BU]},
                        token=A["access"])
        step("crear grupo A+B", st == 201, f"{st} {r}")
        grp = (r.get("chat") or r).get("id")
        msg = ct.send(a.base, A["access"], grp,
                      {"kind": "text", "body": f"hola @{BU} y @everyone",
                       "client_msg_id": str(uuid.uuid4())})
        mid = msg["id"]
        con = sqlite3.connect(str(ct.DB), timeout=10)
        raw = con.execute("SELECT body, mentions FROM messages WHERE id = ?",
                          (mid,)).fetchone()
        con.close()
        step("el cuerpo se guarda canónicamente como @<id>",
             raw is not None and f"@<{ids[BU]}>" in raw[0]
             and f",{ids[BU]}," in (raw[1] or ""), raw)
        step("la respuesta ya muestra @usuario actual",
             f"@{BU}" in msg["body"] and f"@<{ids[BU]}>" not in msg["body"],
             msg.get("body"))

        nuevo_bu = f"w65b2{tag}"
        st, r = ct.http("PUT", a.base + "/api/auth/username",
                        {"username": nuevo_bu, "password": "foxpass12345"},
                        token=B["access"])
        step("B cambia su @usuario", st == 200
             and (r.get("user") or {}).get("username") == nuevo_bu,
             f"{st} {r}")
        st, r = ct.http("GET", f"{a.base}/api/chats/{grp}/messages",
                        token=A["access"])
        m = next((x for x in (r.get("messages") or [])
                  if x.get("id") == mid), {})
        step("la mención antigua muestra el NUEVO @usuario",
             st == 200 and f"@{nuevo_bu}" in (m.get("body") or "")
             and f"@{BU}" not in (m.get("body") or ""), m.get("body"))
        st, r = ct.http("GET", f"{a.base}/api/users/id/{ids[BU]}",
                        token=A["access"])
        step("el perfil por ID refleja el nuevo nombre", st == 200
             and (r.get("user") or {}).get("username") == nuevo_bu, f"{st} {r}")
        edit = ct.http("PUT", f"{a.base}/api/chats/{grp}/messages/{mid}",
                       {"body": f"editado @{nuevo_bu}"}, token=A["access"])
        st = edit[0]
        con = sqlite3.connect(str(ct.DB), timeout=10)
        raw2 = con.execute("SELECT body FROM messages WHERE id = ?",
                           (mid,)).fetchone()
        con.close()
        step("editar vuelve a canonicalizar por nombre actual",
             st == 200 and raw2 and f"@<{ids[BU]}>" in raw2[0], raw2)

        # ---------------- sesión de UI ----------------
        print("→ enlaces directos y solicitud automática")
        shot(a.base + "/", SHOTS / "w65-0-prep.png",
             js="(async()=>{try{const rs=await navigator.serviceWorker"
                ".getRegistrations();for(const r of rs)await r.unregister();}"
                "catch(e){};try{const ks=await caches.keys();for(const k of ks)"
                "await caches.delete(k);}catch(e){};"
                "localStorage.removeItem('fm.session');return 'ok';})()",
             wait=350)
        ok, res, log = shot(a.base + "/", SHOTS / "w65-1-sesion.png",
                            js=sess_js(A), wait=350)
        step("sesión de A inyectada", ok and res == "sesión inyectada",
             res or log[-400:])

        js = (JS_DEEP.replace("«WAIT»", W_WAIT)
              .replace("«CID»", str(ids[CU])))
        ok, res, log = shot(a.base + f"/app/user/{ids[CU]}?v=w65-deep",
                            SHOTS / "w65-2-deeplink.png", js=js, wait=900,
                            timeout=260)
        d = jparse(res)
        step("el enlace sin relación abre el modal 'Solicitud enviada.'",
             ok and d.get("stage") == "ok" and d.get("modal") is True
             and "Solicitud enviada." in (d.get("titulo") or ""), d or log[-500:])
        step("el modal muestra @usuario, Solicitudes y Okey",
             f"@{CU}" in (d.get("texto") or "")
             and "Solicitudes" in (d.get("enlace") or "")
             and "Okey" in (d.get("okey") or "")
             and d.get("check") is True, d)
        step("el perfil queda en 'sent' y la URL no salta antes de tiempo",
             d.get("relation") == "sent" and d.get("sentStore") is True
             and d.get("urlAntes") == f"/app/user/{ids[CU]}", d)
        step("el enlace Solicitudes abre Personas → Solicitudes",
             d.get("modalTrasLink") is False
             and d.get("urlTrasLink") == "/app"
             and d.get("pestana") == "req" and d.get("people") is True
             and d.get("sentC") is True, d)

        js = JS_FRIEND.replace("«WAIT»", W_WAIT)
        ok, res, log = shot(a.base + f"/app/user/{ids[BU]}?v=w65-friend",
                            SHOTS / "w65-3-amigo.png", js=js, wait=900,
                            timeout=260)
        d = jparse(res)
        step("un amigo sin MD abre/crea el MD al entrar por ID",
             ok and d.get("stage") == "ok" and d.get("tipo") == "dm"
             and d.get("peerId") == ids[BU] and d.get("composer") is True
             and d.get("modal") is False, d or log[-500:])

        js = (JS_EDGE.replace("«WAIT»", W_WAIT)
              .replace("«AID»", str(ids[AU]))
              .replace("«DID»", str(ids[DU]))
              .replace("«EID»", str(ids[EU]))
              .replace("«FID»", str(ids[FU])))
        ok, res, log = shot(a.base + "/?v=w65-edge",
                            SHOTS / "w65-4-edge.png", js=js, wait=900,
                            timeout=260)
        d = jparse(res)
        casos = d.get("casos") or {}
        edge_ok = ok and d.get("stage") == "ok"
        for rel in ("sent", "received", "blocked"):
            c = casos.get(rel) or {}
            edge_ok = edge_ok and c.get("abierto") is True \
                and c.get("relation") == rel \
                and c.get("label") == c.get("esperadoLabel") \
                and c.get("disabled") is c.get("esperadoDisabled") \
                and c.get("modalSolicitud") is False
        step("enlaces con relación abren el perfil sin auto-solicitud",
             edge_ok, casos)
        step("el enlace a mi propia cuenta abre Mi perfil",
             (d.get("yo") or {}).get("abierto") is True
             and (d.get("yo") or {}).get("modal") is True
             and (d.get("yo") or {}).get("modalSolicitud") is False, d.get("yo"))

        js = (JS_PLUS.replace("«WAIT»", W_WAIT)
              .replace("«GUSER»", GU))
        ok, res, log = shot(a.base + "/?v=w65-plus",
                            SHOTS / "w65-4-plus.png", js=js, wait=900,
                            timeout=260)
        d = jparse(res)
        step("el flujo ＋ muestra el mismo modal y cierra el buscador",
             ok and d.get("stage") == "ok" and d.get("modal") is True
             and d.get("pickerCerrado") is True
             and d.get("usuario") == GU and d.get("sentStore") is True, d)
        step("Okey cierra el modal de solicitud", d.get("modalCerrado") is True, d)

        print("→ ajustes: slugs, temas y notificaciones")
        js = (JS_SETTINGS.replace("«WAIT»", W_WAIT))
        ok, res, log = shot(a.base + "/?v=w65-settings",
                            SHOTS / "w65-5-settings.png", js=js, wait=900,
                            timeout=260)
        d = jparse(res)
        slugs = d.get("slugs") or {}
        all_ok = ok and len(slugs) == 7
        for slug, tab in (("appearance", "apariencia"),
                          ("notifications", "notificaciones"),
                          ("chat", "chat"), ("privacy", "privacidad"),
                          ("downloads", "descargas"),
                          ("shortcuts", "atajos"), ("account", "cuenta")):
            v = slugs.get(slug) or {}
            all_ok = all_ok and v.get("open") is True \
                and v.get("tab") == tab and v.get("body") is True
        step("las 7 URLs de Ajustes abren su categoría", all_ok, slugs)
        step("la UI genera slugs semánticos al navegar",
             d.get("slugGenerado") == "?settings=privacy", d.get("slugGenerado"))
        step("hay 3 muestras de color y ninguna usa texto",
             d.get("swatches") == 3
             and all(not x for x in (d.get("swatchTexto") or []))
             and "Intermedio" in (d.get("swatchNombres") or [])
             and "Oscuro puro" in (d.get("swatchNombres") or []), d)
        step("Oscuro puro aplica negro y 'Intermedio' conserva dark",
             d.get("themeAttr") == "black"
             and d.get("bg") == "#000000"
             and d.get("dark") == "dark"
             and d.get("darkBg") == "#1e1f22", d)

        print("→ ajustes móviles sin desbordes")
        js = JS_MOBILE_SETTINGS.replace("«WAIT»", W_WAIT)
        ok, res, log = shot(a.base + "/?v=w65-mobile-settings",
                            SHOTS / "w65-6-settings-mobile.png", js=js,
                            wait=900, width=390, height=844, viewport=True,
                            timeout=260)
        d = jparse(res)
        step("Ajustes móvil abre la portada con ?settings=main",
             ok and d.get("stage") == "ok" and d.get("home") is True
             and d.get("atHome") is True and d.get("cats") == 7
             and d.get("urlHome") == "?settings=main"
             and d.get("navHome") is True, d or log[-500:])
        step("Notificaciones es una categoría propia y usa ?settings=notifications",
             d.get("hayNotif") is True
             and d.get("notifTab") == "notificaciones"
             and d.get("notifUrl") == "?settings=notifications"
             and d.get("tone") is True and d.get("back") is True
             and d.get("navDentro") is False, d)
        step("el contenido de Ajustes no desborda el ancho móvil",
             (d.get("overflowBody") or 0) <= 1
             and (d.get("overflowModal") or 0) <= 1, d)
        step("categorías y Atrás devuelven a la portada",
             d.get("homeVolvio") is True
             and d.get("urlVolvio") == "?settings=main"
             and d.get("navVolvio") is True, d)
        step("la hitbox de categoría es táctil (≥44 px)",
             (d.get("catBox") or {}).get("w", 0) >= 44
             and (d.get("catBox") or {}).get("h", 0) >= 44, d.get("catBox"))

        print("→ emojis, selección y toques móviles")
        js = JS_MOBILE_CHAT.replace("«WAIT»", W_WAIT).replace(
            "«GID»", str(grp))
        ok, res, log = shot(a.base + "/?v=w65-emoji",
                            SHOTS / "w65-7-emoji.png", js=js, wait=900,
                            width=390, height=844, viewport=True,
                            timeout=300)
        d = jparse(res)
        step("Twemoji: la rejilla usa sólo imágenes, sin glifos del sistema",
             ok and d.get("stage") == "ok" and d.get("cells", 0) > 30
             and d.get("glifos") == 0 and d.get("conImg") == d.get("cells")
             and d.get("alts") == 0 and d.get("rutas") == d.get("cells"), d)
        step("el texto pegado se conserva hasta enviar y se convierte al enviar",
             d.get("antesEnviar") == ":fire: 😂"
             and d.get("enviados") == 1 and d.get("cuerpo") == "🔥 😂"
             and d.get("trasEnviar") == "", d)
        step("selección desactivada salvo en mensajes/entrada",
             d.get("selPane") == "none" and d.get("selMsg") == "text"
             and d.get("selInput") == "text", d)
        step("botones con touch-action manipulation (sin doble toque)",
             d.get("touchSend") == "manipulation", d)
        step("hitboxes de emoji/categorías/pestañas ≥44 px",
             (d.get("catBox") or 0) >= 44 and (d.get("catUno") or 0) >= 44
             and (d.get("tabAlto") or 0) >= 44, d)
    finally:
        try:
            n = ct.cleanup_db()
            print(f"· datos de prueba eliminados de la DB local ({n})")
        except Exception as e:
            print(f"· no se pudo limpiar: {e}")

    print(f"\nW65: {_pass[0]} bien, {_fail[0]} mal")
    return 0 if _fail[0] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
