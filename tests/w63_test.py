#!/usr/bin/env python3
"""E2E W63: regresiones del lote de rendimiento y UI.

  - LRU de conversaciones: sólo quedan hidratados los 3 últimos chats y
    el más viejo se libera al pasar la ventana de 45 s.
  - URLs de avatar estables por ruta (misma foto reutilizada aunque la
    firma cambie entre respuestas).
  - Solicitudes de amistad EN VIVO: llegan por WS sin recargar.
  - Ajustes móviles: portada con barra inferior y categoría con atrás.
  - Spoiler multimedia: fondo propio difuminado + píldora centrada.

Uso: server/.venv/bin/python tests/w63_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
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

JS_LIVE_REQ = """(async () => {
  «WAIT»
  await boot();
  const out = { stage: 'ini' };
  const pb = await wait(() => document.querySelector('.side-people'), 10000);
  if (!pb) return JSON.stringify({ stage: 'sin-personas' });
  pb.click();
  const tabs = await wait(() => document.querySelector('.ppl-tabs'), 8000);
  if (!tabs) return JSON.stringify({ stage: 'sin-panel' });
  const req = Array.from(tabs.querySelectorAll('.ppl-tab')).find(
    x => (x.textContent || '').indexOf('Solicitudes') >= 0);
  if (!req) return JSON.stringify({ stage: 'sin-pestana' });
  req.click();
  await sleep(500);
  out.before = document.querySelectorAll('.ppl-list .ppl-row').length;
  out.mark = window.__w63mark = 1;
  const r = await fetch('/api/people/requests', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json',
               'Authorization': 'Bearer «CTOK»' },
    body: JSON.stringify({ username: '«AU»' })
  });
  out.status = r.status;
  let row = null;
  const t0 = Date.now();
  while (Date.now() - t0 < 9000) {
    const rows = Array.from(document.querySelectorAll('.ppl-list .ppl-row'));
    row = rows.find(el => (el.textContent || '').indexOf('«CU»') >= 0 &&
      (el.textContent || '').indexOf('Aceptar') >= 0) || null;
    if (row) break;
    await sleep(150);
  }
  out.live = !!row;
  out.after = document.querySelectorAll('.ppl-list .ppl-row').length;
  out.badge = (document.querySelector('.ppl-badge') || {}).textContent || '';
  out.noReload = window.__w63mark === 1;
  out.stage = 'ok';
  return JSON.stringify(out);
})()"""

JS_LRU = """(async () => {
  «WAIT»
  await boot();
  const out = { stage: 'ini' };
  const mod = await import('/static/js/actions.js');
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const p1 = '/media/profile/w63-avatar.webp';
  const p2 = '/media/profile/w63-otro.webp';
  const u1 = mod.mediaUrl(p1 + '?exp=' + exp + '&sig=aaa');
  const u2 = mod.mediaUrl(p1 + '?exp=' + exp + '&sig=bbb');
  const u3 = mod.mediaUrl(p2 + '?exp=' + exp + '&sig=ccc');
  out.avatarSame = u1 === u2;
  out.avatarDiff = u1 !== u3;
  out.avatarPath = (u1 || '').indexOf(p1) === 0;
  const items = await wait(
    () => document.querySelectorAll('.chat-list .chat-item').length >= 4
      ? document.querySelectorAll('.chat-list .chat-item') : null, 12000);
  if (!items) return JSON.stringify({ stage: 'pocos-chats',
    n: document.querySelectorAll('.chat-item').length });
  const ids = Array.from(items).slice(0, 4).map(
    el => el.getAttribute('data-chat-id'));
  out.ids = ids;
  /* Acelerar sólo el temporizador de 15 s del LRU. */
  const realST = window.setTimeout;
  window.setTimeout = function (fn, ms) {
    const args = Array.prototype.slice.call(arguments, 2);
    return realST.apply(window, [fn, ms === 15000 ? 200 : ms].concat(args));
  };
  let abriendo = true;
  try {
    for (let i = 0; i < ids.length; i++) {
      const it = document.querySelector(
        '.chat-item[data-chat-id="' + ids[i] + '"]');
      if (!it) { out.stage = 'sin-item-' + ids[i]; abriendo = false; break; }
      it.click();
      const ok = await wait(() => !!__fm.store.loaded[ids[i]], 12000);
      if (!ok) { out.stage = 'sin-carga-' + ids[i]; abriendo = false; break; }
      await sleep(220);
    }
  } finally {
    if (!abriendo) window.setTimeout = realST;
  }
  if (!abriendo) return JSON.stringify(out);
  out.loadedBefore = ids.filter(id => !!__fm.store.loaded[id]).length;
  const realNow = Date.now;
  try {
    Date.now = () => realNow() + 61000;
    await sleep(1000);
  } finally {
    Date.now = realNow;
    window.setTimeout = realST;
  }
  out.after = ids.filter(id => !!__fm.store.loaded[id]);
  out.loadedAfter = out.after.length;
  out.oldGone = !__fm.store.loaded[ids[0]] && !__fm.store.msgs[ids[0]];
  out.activeKept = !!__fm.store.loaded[ids[3]];
  out.chip = !!document.querySelector(
    '.chat-item[data-chat-id="' + ids[0] + '"]');
  out.stage = 'ok';
  return JSON.stringify(out);
})()"""

JS_SPOIL = """(async () => {
  «WAIT»
  await boot();
  const item = await wait(
    () => document.querySelector('.chat-item[data-chat-id="«DM»"]'), 12000);
  if (!item) return JSON.stringify({ stage: 'sin-chat' });
  item.click();
  const m = await wait(
    () => document.querySelector('.msg[data-mid="«MID»"]'), 12000);
  if (!m) return JSON.stringify({ stage: 'sin-mensaje' });
  const out = { stage: 'ok' };
  const bg = m.querySelector('.b-spoil-bg');
  const ov = m.querySelector('.b-spoil-ov');
  const pill = ov ? ov.querySelector('.b-spoil-pill') : null;
  const media = m.querySelector('.b-media');
  out.hasBg = !!bg;
  out.hasOv = !!ov;
  out.hasPill = !!pill;
  out.bgImage = bg ? getComputedStyle(bg).backgroundImage : '';
  out.bgFilter = bg ? getComputedStyle(bg).filter : '';
  out.pillText = pill ? (pill.textContent || '').trim() : '';
  out.radius = pill ? parseFloat(getComputedStyle(pill).borderRadius) : 0;
  if (ov && pill) {
    const r = ov.getBoundingClientRect();
    const p = pill.getBoundingClientRect();
    out.center = Math.abs((r.left + r.width / 2) - (p.left + p.width / 2)) < 8 &&
      Math.abs((r.top + r.height / 2) - (p.top + p.height / 2)) < 12;
  }
  out.mediaHidden = media
    ? getComputedStyle(media).visibility === 'hidden' : false;
  if (ov) ov.click();
  await sleep(350);
  out.revealed = !m.querySelector('.b-spoil-ov') && !m.querySelector('.b-spoil-bg');
  out.dot = !!m.querySelector('.b-spoil-dot');
  out.mediaVisible = media
    ? getComputedStyle(media).visibility !== 'hidden' : false;
  /* W65: un mensaje de sólo emojis lleva una pastilla oscura legible
     detrás de la hora/palomitas (antes el texto blanco se perdía). */
  const em = document.querySelector('.msg[data-mid="«EMO»"] .bubble.emo-big');
  const emMeta = em ? em.querySelector('.b-meta') : null;
  out.emoBig = !!em;
  out.emoMeta = !!emMeta;
  out.emoPos = emMeta ? getComputedStyle(emMeta).position : '';
  out.emoBg = emMeta ? getComputedStyle(emMeta).backgroundColor : '';
  out.emoRadius = emMeta ? parseFloat(getComputedStyle(emMeta).borderRadius) : 0;
  return JSON.stringify(out);
})()"""

JS_MOBILE_SETTINGS = """(async () => {
  «WAIT»
  await boot();
  const out = { stage: 'ini' };
  const nav = await wait(() => document.querySelector('.mobile-tabs'), 12000);
  if (!nav) return JSON.stringify({ stage: 'sin-barra' });
  out.navHome = true;
  const btn = nav.querySelector('.mt-btn:last-child');
  if (!btn) return JSON.stringify({ stage: 'sin-ajustes' });
  btn.click();
  await sleep(400);
  out.open = !!__fm.store.settingsOpen;
  out.home = !!__fm.store.settingsAtHome;
  out.homeList = !!document.querySelector('.st-mobile-home');
  out.cats = document.querySelectorAll('.st-cat').length;
  out.navOnHome = !!document.querySelector('.mobile-tabs');
  const cat = document.querySelector('.st-cat');
  if (!cat) return JSON.stringify({ stage: 'sin-categorias', out: out });
  cat.click();
  await sleep(400);
  out.inside = __fm.store.settingsAtHome === false;
  out.navInside = !!document.querySelector('.mobile-tabs');
  out.backBtn = !!document.querySelector('.st-back');
  out.cols = !!document.querySelector('.st-cols');
  const back = document.querySelector('.st-back');
  if (back) back.click();
  await sleep(400);
  out.backHome = __fm.store.settingsAtHome === true;
  out.navBack = !!document.querySelector('.mobile-tabs');
  out.catsBack = document.querySelectorAll('.st-cat').length;
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
        print("→ preparar usuarios y chats")
        A = ct.register(a.base, f"w63a{tag}@t.fi", f"w63a{tag}")
        B = ct.register(a.base, f"w63b{tag}@t.fi", f"w63b{tag}")
        C = ct.register(a.base, f"w63c{tag}@t.fi", f"w63c{tag}")
        AU, BU, CU = (A["user"]["username"], B["user"]["username"],
                      C["user"]["username"])

        ct.ensure_friends(a.base, A["access"], B["access"], AU, BU)
        st, r = ct.http("POST", a.base + "/api/chats/dm",
                        {"username": BU}, token=A["access"])
        if st not in (200, 201):
            raise SystemExit(f"✗ DM: {st} {r}")
        dm = r["chat"]["id"]

        groups = []
        for i in range(3):
            st, r = ct.http("POST", a.base + "/api/chats/group",
                            {"title": f"W63-G{i}-{tag}", "members": [BU]},
                            token=A["access"])
            if st not in (200, 201):
                raise SystemExit(f"✗ grupo {i}: {st} {r}")
            groups.append(r["chat"]["id"])
            ct.send(a.base, A["access"], groups[-1],
                    {"body": f"w63 relleno {i} {tag}",
                     "client_msg_id": str(uuid.uuid4())})

        up = ct.upload(a.base, A["access"],
                       ROOT / "server" / "web" / "icon-192.png")
        spoiler = ct.send(a.base, A["access"], dm,
                          {"kind": "image", "body": "",
                           "media_id": up["id"], "spoiler": True,
                           "client_msg_id": str(uuid.uuid4())})
        emoji = ct.send(a.base, A["access"], dm,
                        {"body": "\U0001f602\U0001f602\U0001f602",
                         "client_msg_id": str(uuid.uuid4())})
        print(f"  · dm={dm} grupos={groups} spoiler={spoiler['id']} "
              f"emoji={emoji['id']}")

        # Limpiar service worker/caché y dejar la sesión de A inyectada.
        shot(a.base + "/", SHOTS / "w63-0-prep.png",
             js="(async()=>{try{const rs=await navigator.serviceWorker"
                ".getRegistrations();for(const r of rs)await r.unregister();}"
                "catch(e){};try{const ks=await caches.keys();for(const k of ks)"
                "await caches.delete(k);}catch(e){};"
                "localStorage.removeItem('fm.session');return 'ok';})()",
             wait=350)
        ok, res, log = shot(a.base + "/", SHOTS / "w63-1-sesion.png",
                            js=sess_js(A), wait=350)
        step("sesión de A inyectada", ok and res == "sesión inyectada",
             res or log[-400:])

        # ---------------- solicitud de amistad en vivo ----------------
        print("→ solicitud de amistad en vivo")
        js = (JS_LIVE_REQ.replace("«WAIT»", W_WAIT)
              .replace("«CTOK»", C["access"])
              .replace("«AU»", AU).replace("«CU»", CU))
        ok, res, log = shot(a.base + "/?v=w63-people",
                            SHOTS / "w63-2-solicitud.png", js=js, wait=800)
        d = jparse(res)
        step("Solicitudes abre vacío antes de la petición",
             ok and d.get("stage") == "ok" and d.get("before") == 0,
             d or log[-400:])
        step("la petición POST de C responde 201",
             d.get("status") == 201, d)
        step("la solicitud aparece EN VIVO sin recargar y con Aceptar",
             d.get("live") is True and d.get("noReload") is True
             and d.get("after", 0) >= 1,
             d)

        # ---------------- LRU + URL de avatar estable ----------------
        print("→ memoria LRU de chats y URL de avatar")
        ok, res, log = shot(a.base + "/?v=w63-lru", SHOTS / "w63-3-lru.png",
                            js=JS_LRU.replace("«WAIT»", W_WAIT),
                            wait=800, timeout=240)
        d = jparse(res)
        step("mediaUrl reutiliza la misma URL para la misma ruta de avatar",
             ok and d.get("avatarSame") is True and d.get("avatarDiff") is True
             and d.get("avatarPath") is True, d or log[-400:])
        step("abrir 4 chats los hidrata", d.get("loadedBefore") == 4, d)
        step("tras 45 s queda el activo + 3 recientes y se libera el más viejo",
             d.get("loadedAfter") == 3 and d.get("oldGone") is True
             and d.get("activeKept") is True, d)
        step("la ficha del chat liberado sigue en la lista",
             d.get("chip") is True, d)

        # ---------------- spoiler multimedia ----------------
        print("→ spoiler multimedia con fondo propio")
        js = (JS_SPOIL.replace("«WAIT»", W_WAIT)
              .replace("«DM»", str(dm))
              .replace("«MID»", str(spoiler["id"]))
              .replace("«EMO»", str(emoji["id"])))
        ok, res, log = shot(a.base + "/?v=w63-spoiler",
                            SHOTS / "w63-4-spoiler.png", js=js, wait=800)
        d = jparse(res)
        step("capa, fondo propio y píldora están presentes",
             ok and d.get("stage") == "ok" and d.get("hasBg")
             and d.get("hasOv") and d.get("hasPill"), d or log[-400:])
        step("el fondo es la imagen difuminada",
             "url(" in (d.get("bgImage") or "")
             and "blur" in (d.get("bgFilter") or ""), d)
        step("la píldora 'Mostrar Spoiler' es redondeada y está centrada",
             "Mostrar Spoiler" in (d.get("pillText") or "")
             and (d.get("radius") or 0) >= 20 and d.get("center") is True,
             d)
        step("el contenido queda oculto y al tocar se revela",
             d.get("mediaHidden") is True and d.get("revealed") is True
             and d.get("mediaVisible") is True and d.get("dot") is True,
             d)
        step("mensaje de sólo emojis con pastilla oscura de hora/palomitas",
             d.get("emoBig") is True and d.get("emoMeta") is True
             and d.get("emoPos") == "static"
             and d.get("emoBg") == "rgba(0, 0, 0, 0.52)"
             and (d.get("emoRadius") or 0) >= 10, d)

        # ---------------- ajustes móviles ----------------
        print("→ ajustes móviles: portada con pestañas y categoría con atrás")
        ok, res, log = shot(a.base + "/?v=w63-mobile",
                            SHOTS / "w63-5-ajustes.png",
                            js=JS_MOBILE_SETTINGS.replace("«WAIT»", W_WAIT),
                            wait=800, width=390, height=844, viewport=True)
        d = jparse(res)
        step("la portada de Ajustes conserva la barra inferior y 6 categorías",
             ok and d.get("stage") == "ok" and d.get("open") is True
             and d.get("home") is True and d.get("homeList") is True
             and (d.get("cats") or 0) >= 6 and d.get("navOnHome") is True,
             d or log[-400:])
        step("entrar a una categoría oculta la barra y muestra Atrás",
             d.get("inside") is True and d.get("navInside") is False
             and d.get("backBtn") is True and d.get("cols") is True, d)
        step("Atrás vuelve a la portada con la barra inferior",
             d.get("backHome") is True and d.get("navBack") is True
             and (d.get("catsBack") or 0) >= 6, d)
    finally:
        try:
            n = ct.cleanup_db()
            print(f"· datos de prueba eliminados de la DB local (users={n})")
        except Exception as e:
            print(f"WARN cleanup: {e}")

    print(f"\nW63: {_pass[0]} bien, {_fail[0]} mal")
    return 1 if _fail[0] else 0


if __name__ == "__main__":
    sys.exit(main())
