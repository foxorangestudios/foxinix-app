#!/usr/bin/env python3
"""E2E W58: descargas en datos de la app, portada de perfil, estado
citado con propagación en vivo y onboarding de permisos.

Cubre:
  1. API de portada (banner_media_id): subir, validar (ajena, no imagen,
     inexistente), propagar a la lista de chats y a los miembros, y
     quitar.
  2. Tu perfil: portada + avatar solapado + estado citado; el menú
     Discord guarda presets y mensaje personalizado por API.
  3. Propagación en vivo: B ve el cambio de estado de A en la lista de
     chats, en los miembros y en el perfil abierto; el perfil ajeno es
     de solo lectura.
  4. Descargas: categorías, agrupación en Ajustes (conteo/tamaño),
     Abrir/Guardar/Eliminar, preferencias automáticas y el control
     "Descargar/Descargado · tamaño" siempre visible bajo cada adjunto.
  5. Permisos: sección en Ajustes, puerta a pantalla completa con
     Conceder/Saltar, saltar no rompe la app y usar la función vuelve a
     pedir el permiso.

Uso: server/.venv/bin/python tests/w58_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")
ICON = ROOT / "server" / "web" / "icon-192.png"

_pass = [0]
_fail = [0]


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  ✓ {name}")
    else:
        _fail[0] += 1
        print(f"  ✗ {name}: {detail}")


def sess_js(u):
    sess = json.dumps({"access": u["access"], "refresh": u["refresh"],
                       "user": u["user"], "pendingEmail": ""})
    return ct.JS_INJECT.replace(
        "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))


def jparse(res):
    try:
        return json.loads(res) if res and res.startswith("{") else {}
    except Exception:
        return {}


def shot(url, out, js=None, wait=400, timeout=180):
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
  const boot = async () => {
    let tb = Date.now();
    while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  };"""


def js_t(tpl, **kw):
    out = W_WAIT + "\n" + tpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return out


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w58a{tag}@t.fi", f"w58a{tag}")
    B = ct.register(a.base, f"w58b{tag}@t.fi", f"w58b{tag}")
    AU, BU = A["user"]["username"], B["user"]["username"]
    AID = A["user"]["id"]
    print(f"· A={AU} B={BU}")

    # Amistad A-B (para la lista Personas).
    st, rq = ct.http("POST", a.base + "/api/people/requests",
                     {"username": BU}, token=A["access"])
    rid = None
    st2, ppl = ct.http("GET", a.base + "/api/people", token=B["access"])
    payload = ppl.get("people") or ppl
    rows = (payload.get("received") or [])
    for row in rows:
        u = row.get("user") or {}
        if u.get("id") == AID or row.get("id") == AID:
            rid = row.get("id") or row.get("request_id") or u.get("id")
            break
    st3 = 0
    if rid is not None:
        st3, _ = ct.http("POST", a.base + f"/api/people/requests/{rid}/accept",
                         {}, token=B["access"])
    step("amistad A-B aceptada", st in (200, 201) and st3 in (200, 201),
         f"req={st} accept={st3} rid={rid}")

    dm = None
    st, dmres = ct.http("POST", a.base + "/api/chats/dm",
                        {"username": BU}, token=A["access"])
    if st in (200, 201):
        dm = dmres["chat"]["id"]

    # ---------------- 1. portada (API) ----------------
    print("→ paso1 portada de perfil (API)")
    media_a = ct.upload(a.base, A["access"], ICON)
    media_b = ct.upload(a.base, B["access"], ICON)
    txt = SHOTS / "w58-nota.txt"
    txt.write_text("no soy una imagen")
    media_txt = ct.upload(a.base, A["access"], txt)
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"banner_media_id": media_a["id"]}, token=A["access"])
    burl = ((r.get("user") or {}).get("banner_url") or "")
    step("banner propio → 200 con banner_url firmada",
         st == 200 and "/media/profile/" in burl, (st, r))
    st, _ = ct.http("PUT", a.base + "/api/auth/profile",
                    {"banner_media_id": media_b["id"]}, token=A["access"])
    step("banner de OTRO usuario → rechazado", st in (400, 403), st)
    st, _ = ct.http("PUT", a.base + "/api/auth/profile",
                    {"banner_media_id": media_txt["id"]}, token=A["access"])
    step("banner que no es imagen → rechazado", st in (400, 403), st)
    st, _ = ct.http("PUT", a.base + "/api/auth/profile",
                    {"banner_media_id": 999999}, token=A["access"])
    step("banner inexistente → rechazado", st in (400, 403), st)

    st, cl = ct.http("GET", a.base + "/api/chats", token=B["access"])
    peer = None
    for c in (cl.get("chats") or []):
        if c.get("type") == "dm" and (c.get("title") or {}).get("id") == AID:
            peer = c["title"]
    step("la lista de B trae el banner de A",
         st == 200 and peer and "/media/profile/" in (peer.get("banner_url") or ""),
         peer)
    mem_a = None
    if dm:
        st, mr = ct.http("GET", a.base + f"/api/chats/{dm}/members",
                         token=B["access"])
        for m in (mr.get("members") or []):
            if m.get("id") == AID:
                mem_a = m
    step("los miembros del DM traen el banner de A",
         bool(mem_a) and "/media/profile/" in (mem_a.get("banner_url") or ""),
         mem_a)

    # Mensaje con imagen en la DM (para el control "Descargar · tamaño").
    ct.send(a.base, A["access"], dm,
            {"kind": "image", "body": "", "media_id": media_a["id"],
             "client_msg_id": str(uuid.uuid4())})

    # ---------------- 2. Tu perfil: portada + estado ----------------
    print("→ paso2 Tu perfil: portada, avatar solapado y menú de estado")
    shot(a.base + "/", SHOTS / "w58-0-prep.png",
                js="(async () => { try { const rs = await "
                   "navigator.serviceWorker.getRegistrations(); "
                   "for (const r of rs) await r.unregister(); } catch (e) {} "
                   "try { const ks = await caches.keys(); "
                   "for (const k of ks) await caches.delete(k); } catch (e) {} "
                   "localStorage.removeItem('fm.session'); return 'limpia'; })()",
                wait=200)
    shot(a.base + "/", SHOTS / "w58-0-sesion.png",
                js=sess_js(A), wait=200)
    js_me = js_t("""(async () => {
      await boot();
      __fm.store.meProfileOpen = true;
      const mp = await wait('.modal.meprof', 6000);
      if (!mp) return 'FAIL: sin modal de perfil';
      const view = mp.querySelector('.mp-view');
      if (!view) return 'FAIL: sin ficha';
      const banner = view.querySelector('.pf-banner');
      const av = view.querySelector('.pf-avwrap.on');
      const quote = view.querySelector('.pf-status-wrap .pf-quote');
      if (!banner) return 'FAIL: sin portada';
      if (!av) return 'FAIL: sin avatar';
      if (!quote) return 'FAIL: sin burbuja de estado';
      const dotW = getComputedStyle(av, '::after').width;
      const small = document.createElement('span');
      small.className = 'av-wrap on';
      document.body.appendChild(small);
      const smallW = getComputedStyle(small, '::after').width;
      small.remove();
      quote.click();
      const menu = await wait('.pf-status-menu', 4000);
      if (!menu) return 'FAIL: sin menú de estado';
      const presets = Array.from(menu.querySelectorAll('.pf-preset'));
      const input = menu.querySelector('.pf-status-input');
      if (!input) return 'FAIL: sin campo de mensaje';
      const busy = presets.find(b => b.textContent.indexOf('No molestar') >= 0);
      if (!busy) return 'FAIL: sin preset No molestar';
      busy.click();
      let preset = '';
      let t0 = Date.now();
      while (Date.now() - t0 < 8000) {
        preset = (__fm.store.user || {}).status_preset || '';
        if (preset === 'dnd') break;
        await sleep(120);
      }
      const q2 = view.querySelector('.pf-status-wrap .pf-quote');
      if (!document.querySelector('.pf-status-menu')) q2.click();
      const menu2 = await wait('.pf-status-menu', 4000);
      const inp2 = menu2 ? menu2.querySelector('.pf-status-input') : null;
      if (!inp2) return 'FAIL: sin campo tras elegir preset';
      inp2.value = 'ocupado con W58';
      inp2.dispatchEvent(new Event('input', { bubbles: true }));
      const save = menu2.querySelector('.pf-menu-save');
      if (save) save.click();
      let msg = '';
      t0 = Date.now();
      while (Date.now() - t0 < 8000) {
        msg = (__fm.store.user || {}).status_text || '';
        if (msg === 'ocupado con W58') break;
        await sleep(120);
      }
      const qt = view.querySelector('.pf-status-wrap .pf-quote-text');
      return JSON.stringify({
        bannerImg: !!banner.querySelector('img'),
        dotW: dotW, smallW: smallW,
        presets: presets.length, preset: preset, msg: msg,
        quote: qt ? qt.textContent.trim() : '',
        readOnlyOwn: !!view.querySelector('.pf-status-menu'),
      });
    })()""")
    ok, res, log = shot(
        a.base + "/?v=w58-me", SHOTS / "w58-1-perfil.png",
        js=js_me, wait=600)
    d = jparse(res)
    step("Tu perfil: portada real + avatar solapado + estado citado",
         ok and d.get("bannerImg") and d.get("quote") is not None, d or log[-400:])
    step("el badge del perfil mide 22px (el normal 14px)",
         d.get("dotW") == "22px" and d.get("smallW") == "14px", d)
    step("el menú de estado trae 4 presets y guarda No molestar",
         d.get("presets") == 4 and d.get("preset") == "dnd", d)
    step("el mensaje personalizado se guarda y se ve en la burbuja",
         d.get("msg") == "ocupado con W58" and "ocupado con W58" in (d.get("quote") or ""),
         d)

    # ---------------- 3. propagación en vivo (B) ----------------
    print("→ paso3 propagación en vivo del estado (B)")
    shot(a.base + "/", SHOTS / "w58-0-sesion-b.png",
                js=sess_js(B), wait=200)
    js_live = js_t("""(async () => {
      await boot();
      const items = await (async () => {
        const t0 = Date.now();
        while (Date.now() - t0 < 12000) {
          const list = document.querySelectorAll('.chat-item');
          if (list.length) return Array.from(list);
          await sleep(120);
        }
        return [];
      })();
      const dm = items.find(el => el.textContent.indexOf('{AU}') >= 0);
      if (!dm) return 'FAIL: sin DM con A';
      dm.click();
      if (!await wait('.msgs .msg', 8000)) return 'FAIL: no abrió la DM';
      const head = document.querySelector('.chat-head .ch-col');
      if (head) head.click();
      const modal = await wait('.modal.pmodal', 6000);
      if (!modal) return 'FAIL: sin perfil abierto';
      const pre = (modal.querySelector('.pf-quote') || {}).textContent || '';
      const dlState = document.querySelector('.msgs .msg .b-dl-state');
      const dlTxt = dlState ? dlState.textContent.trim() : '';
      const dlVisible = dlState ? (dlState.offsetWidth > 0 &&
        getComputedStyle(dlState).display !== 'none') : false;
      const rq = await fetch('/api/auth/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json',
                   'Authorization': 'Bearer {ATOKEN}' },
        body: JSON.stringify({ status_preset: 'busy',
                               status_text: 'en llamada W58' }),
      });
      if (!rq.ok) return 'FAIL: PUT ' + rq.status;
      let chatPreset = '', memPreset = '', pplPreset = '', profTxt = '';
      let quote = '';
      const t0 = Date.now();
      while (Date.now() - t0 < 10000) {
        const c = (__fm.store.chats || []).find(x => x.type === 'dm' &&
          x.title && x.title.id === {AID});
        chatPreset = c && c.title ? (c.title.status_preset || '') : '';
        const mem = (__fm.store.info && __fm.store.info.members) || [];
        const mm = mem.find(m => m.id === {AID});
        memPreset = mm ? (mm.status_preset || '') : '';
        const fr = ((__fm.store.people || {}).friends || [])
          .find(u => u.id === {AID});
        pplPreset = fr ? (fr.status_preset || '') : '';
        profTxt = (__fm.store.profile && __fm.store.profile.user)
          ? (__fm.store.profile.user.status_text || '') : '';
        const q = modal.querySelector('.pf-quote');
        quote = q ? q.textContent.trim() : '';
        if (chatPreset === 'busy' && profTxt === 'en llamada W58' &&
            quote.indexOf('en llamada W58') >= 0) break;
        await sleep(150);
      }
      const active = document.querySelector('.chat-item.active');
      return JSON.stringify({
        pre: pre.trim(), dlTxt: dlTxt, dlVisible: dlVisible,
        chatPreset: chatPreset, memPreset: memPreset, pplPreset: pplPreset,
        profTxt: profTxt, quote: quote,
        readOnly: !modal.querySelector('.pf-status-btn'),
        itemLine: active ? active.textContent : '',
      });
    })()""", AU=AU, ATOKEN=A["access"], AID=str(AID))
    ok, res, log = shot(
        a.base + "/?v=w58-live", SHOTS / "w58-2-vivo.png",
        js=js_live, wait=600)
    d = jparse(res)
    step("el perfil abierto de B ya mostraba el estado de A",
         ok and d.get("pre") == "ocupado con W58", d or log[-400:])
    step("el control de descarga siempre visible dice «Descargar/Descargado · tamaño»",
         d.get("dlVisible") and ((d.get("dlTxt") or "").startswith("Descargar ·") or
                                 (d.get("dlTxt") or "").startswith("Descargado ·")),
         d)
    step("el cambio de estado llega a la lista, miembros y Personas",
         d.get("chatPreset") == "busy" and d.get("memPreset") == "busy" and
         d.get("pplPreset") == "busy", d)
    step("el perfil abierto se actualiza en vivo y es de solo lectura",
         d.get("profTxt") == "en llamada W58" and
         "en llamada W58" in (d.get("quote") or "") and d.get("readOnly"), d)
    st, r = ct.http("GET", a.base + "/api/users/me", token=A["access"])
    u = (r.get("user") or {})
    step("users/me refleja preset y mensaje",
         st == 200 and u.get("status_preset") == "busy" and
         u.get("status_text") == "en llamada W58", u)

    # ---------------- 4. descargas (A) ----------------
    print("→ paso4 descargas: categorías, agrupación y acciones")
    shot(a.base + "/", SHOTS / "w58-0-sesion-a2.png",
                js=sess_js(A), wait=200)
    js_dl = js_t("""(async () => {
      await boot();
      const dl = __fm.dl;
      const cats = {
        img: dl.dlCategory('image', 'image/png', 'x.png'),
        vid: dl.dlCategory('video', 'video/mp4', 'x.mp4'),
        aud: dl.dlCategory('voice', 'audio/mpeg', 'x.mp3'),
        doc: dl.dlCategory('file', 'application/pdf', 'x.pdf'),
        fil: dl.dlCategory('file', 'application/zip', 'x.zip'),
      };
      /* W59: aislar esta prueba de las descargas automáticas del chat. */
      await dl.clearDownloads();
      const off = {};
      dl.types.forEach(t => { off[t.id] = { wifi: false, mobile: false }; });
      localStorage.setItem('fm.dl.auto', JSON.stringify(off));
      localStorage.setItem('fm.dlauto.v', '2');
      await dl.saveDownload('/media/profile/w58-foto.png?sig=x1',
        'foto W58.png', new Blob(['12345'], { type: 'image/png' }),
        'image', true);
      await dl.saveDownload('/media/profile/w58-doc.pdf?sig=x2',
        'informe W58.pdf', new Blob(['1234567890'],
        { type: 'application/pdf' }), 'file', false);
      const saved = Object.keys(__fm.store.dlSaved || {}).length;
      __fm.store.settingsOpen = true;
      __fm.store.settingsTab = 'descargas';
      const modal = await wait('.modal.settings', 6000);
      if (!modal) return 'FAIL: sin ajustes';
      const heads = await (async () => {
        const t0 = Date.now();
        while (Date.now() - t0 < 8000) {
          const hs = modal.querySelectorAll('.dl-group-head');
          if (hs.length) return hs;
          await sleep(120);
        }
        return [];
      })();
      const groups = Array.from(heads).map(b =>
        b.textContent.replace(/\\s+/g, ' ').trim());
      const imgHead = Array.from(heads)
        .find(b => b.textContent.indexOf('Imágenes') >= 0);
      if (imgHead) imgHead.click();
      await sleep(250);
      const body = modal.querySelector('.dl-group-body');
      const btns = body ? Array.from(body.querySelectorAll('.btn'))
        .map(b => b.textContent.trim()) : [];
      const del = body ? body.querySelector('.icon-btn[title="Eliminar"]') : null;
      let deleted = false;
      if (del) {
        window.confirm = function () { return true; };
        del.click();
        const t0 = Date.now();
        while (Date.now() - t0 < 6000) {
          const list = await dl.listDownloads();
          if (!list.some(x => x.name === 'foto W58.png')) { deleted = true; break; }
          await sleep(150);
        }
      }
      const rest = await dl.listDownloads();
      return JSON.stringify({
        cats: cats, saved: saved, groups: groups, btns: btns,
        deleted: deleted, rest: rest.length,
        autoRows: modal.querySelectorAll('.dl-auto-row').length,
      });
    })()""")
    ok, res, log = shot(
        a.base + "/?v=w58-dl", SHOTS / "w58-3-descargas.png",
        js=js_dl, wait=600)
    d = jparse(res)
    step("dlCategory clasifica imagen/video/audio/documento/archivo",
         ok and d.get("cats") == {"img": "image", "vid": "video",
                                  "aud": "audio", "doc": "document",
                                  "fil": "file"}, d or log[-400:])
    step("los datos de la app registran las descargas (store.dlSaved)",
         (d.get("saved") or 0) >= 2, d)
    step("Ajustes agrupa por categoría con conteo y tamaño",
         len(d.get("groups") or []) >= 2 and
         any("Imágenes" in g for g in (d.get("groups") or [])) and
         any("(1)" in g for g in (d.get("groups") or [])), d.get("groups"))
    step("cada descarga ofrece Abrir y Guardar en el dispositivo",
         "Abrir" in (d.get("btns") or []) and
         "Guardar en el dispositivo" in (d.get("btns") or []), d.get("btns"))
    step("Eliminar borra la descarga de los datos de la app",
         d.get("deleted") and d.get("rest") == 1, d)
    step("las 5 categorías tienen preferencias automáticas",
         d.get("autoRows") == 5, d)

    # ---------------- 5. permisos (A) ----------------
    print("→ paso5 permisos: puerta, saltar y volver a pedir")
    js_perm = js_t("""(async () => {
      await boot();
      __fm.store.settingsOpen = true;
      const modal = await wait('.modal.settings', 6000);
      if (!modal) return 'FAIL: sin ajustes';
      const tabs = Array.from(modal.querySelectorAll('.m-tab'));
      let found = false;
      for (const tb of tabs) {
        tb.click();
        await sleep(150);
        if (modal.querySelectorAll('.perm-row').length ||
            Array.from(modal.querySelectorAll('.btn'))
              .some(b => b.textContent.indexOf('Revisar permisos') >= 0)) {
          found = true; break;
        }
      }
      if (!found) return 'FAIL: sin sección de permisos';
      const rows = modal.querySelectorAll('.perm-row').length;
      const review = Array.from(modal.querySelectorAll('.btn'))
        .find(b => b.textContent.indexOf('Revisar permisos') >= 0);
      if (!review) return 'FAIL: sin botón revisar';
      review.click();
      const first = await wait('.perm-gate', 6000);
      if (!first) return 'FAIL: sin puerta de permisos';
      const title = (first.querySelector('h2') || {}).textContent || '';
      const text = (first.querySelector('p') || {}).textContent || '';
      const buttons = Array.from(first.querySelectorAll('.perm-actions .btn'))
        .map(b => b.textContent.trim());
      const stepTxt = (first.querySelector('.perm-step') || {}).textContent || '';
      let seen = 1;
      for (let i = 0; i < 6; i++) {
        const g = document.querySelector('.perm-gate');
        if (!g) break;
        const skip = Array.from(g.querySelectorAll('.perm-actions .btn'))
          .find(b => b.textContent.indexOf('Saltar') >= 0);
        if (!skip) break;
        skip.click();
        await sleep(450);
        if (document.querySelector('.perm-gate')) seen++;
      }
      const afterGate = !document.querySelector('.perm-gate');
      const states = Object.assign({}, __fm.store.permStates || {});
      const micBtn = Array.from(modal.querySelectorAll('.mic-test-row .btn'))[0];
      /* Simula el puente Android: en escritorio ensurePermission usa el
         diálogo nativo del navegador, así que la puerta solo se prueba en
         una plataforma con onboarding. */
      window.FoxinixAndroid = {
        permissionState: function () { return 'prompt'; },
        requestPermissionFor: function () { return 'prompt'; },
      };
      if (micBtn) micBtn.click();
      const again = await wait('.perm-gate', 6000);
      const againTitle = again
        ? ((again.querySelector('h2') || {}).textContent || '') : '';
      if (again) {
        const skip2 = Array.from(again.querySelectorAll('.perm-actions .btn'))
          .find(b => b.textContent.indexOf('Saltar') >= 0);
        if (skip2) skip2.click();
      }
      await sleep(300);
      const items = document.querySelectorAll('.chat-item').length;
      return JSON.stringify({
        rows: rows, title: title.trim(), text: text.trim(),
        buttons: buttons, stepTxt: stepTxt.trim(), seen: seen,
        afterGate: afterGate, states: states,
        again: againTitle.trim(), micBtn: !!micBtn, items: items,
        closed: !document.querySelector('.perm-gate'),
      });
    })()""")
    ok, res, log = shot(
        a.base + "/?v=w58-perm", SHOTS / "w58-4-permisos.png",
        js=sess_js(A) + "\n" + js_perm, wait=600)
    d = jparse(res)
    step("Ajustes lista los 4 permisos del dispositivo",
         ok and d.get("rows") == 4, d or log[-400:])
    step("la puerta es a pantalla completa con icono, título y texto",
         d.get("title") == "Usar el micrófono" and len(d.get("text") or "") > 20 and
         "Permiso 1 de" in (d.get("stepTxt") or ""), d)
    step("ofrece Conceder y Saltar por ahora",
         "Conceder" in (d.get("buttons") or []) and
         "Saltar por ahora" in (d.get("buttons") or []), d.get("buttons"))
    step("saltar cierra la puerta y la app sigue cargando",
         d.get("afterGate") and d.get("closed") and (d.get("items") or 0) > 0, d)
    step("usar una función con permiso saltado lo vuelve a pedir",
         d.get("again") == "Usar el micrófono" and d.get("micBtn"), d)
    step("los estados quedan registrados en la app",
         d.get("states", {}).get("mic") in ("prompt", "denied", "granted"),
         d.get("states"))

    # ---------------- 6. quitar portada (API) ----------------
    print("→ paso6 quitar portada")
    st, r = ct.http("PUT", a.base + "/api/auth/profile",
                    {"banner_media_id": None}, token=A["access"])
    ub = (r.get("user") or {})
    step("quitar banner → banner_url vacío",
         st == 200 and not ub.get("banner_url"), (st, ub))

    print(f"\nW58: {_pass[0]} bien, {_fail[0]} mal")
    try:
        ct.cleanup_db()
        print("· datos de prueba eliminados de la DB local")
    except Exception as e:  # noqa: BLE001
        print("· limpieza de DB omitida:", e)
    # Deja el perfil de Firefox sin la sesión del usuario ya borrado, para
    # no contaminar la siguiente suite (carrera bootstrap/inject).
    try:
        shot(a.base + "/", SHOTS / "w58-9-limpieza.png",
             js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
    except Exception:
        pass
    return 1 if _fail[0] else 0


if __name__ == "__main__":
    sys.exit(main())
