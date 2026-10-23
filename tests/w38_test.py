#!/usr/bin/env python
"""E2E W38: pantalla de arranque con fases reales + animación de
cubitos.

Siembra A con un DM de B. Firefox headless (BiDi vía scripts/shot.py)
con la sesión de A:

  1. el arranque real avanza por las fases de BOOT_PHASES en orden y
     termina en 'ready' con la app abierta.
  2. el overlay .app-boot muestra la pantalla compartida: icono de la
     app, sello "Cifrado de extremo a extremo" con el icono i-key,
     barra de progreso y texto de fase (position: fixed, w27 intacto).
  3. cada fase pinta SU texto (es) y mueve la barra (scaleX creciente
     hasta 1); en inglés el texto cambia ("Loading users…").
  4. la carga de la conversación (.msgs-load) usa la animación de
     CUBITOS (2 cubos, cubeSpinner 1.8s, retardo -0.9s) — ya no el
     spin de antes.
"""

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")

_pass = [0]
_fail = [0]


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  ✓ {name}")
    else:
        _fail[0] += 1
        print(f"  ✗ {name}: {detail}")


def shot(url, out, js=None, wait=400, timeout=240):
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
  };
  const boot = async () => {
    let tb = Date.now();
    while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  };"""


def js(tpl, **kw):
    out = W_WAIT + "\n" + tpl
    for k, v in kw.items():
        out = out.replace("«" + k + "»", v)
    return out


# 1. arranque real: fases observadas en orden y fin en 'ready'
JS_PHASES = """(async () => {
  const seen = [];
  const t0 = Date.now();
  while (Date.now() - t0 < 20000) {
    const s = window.__fm && __fm.store;
    if (!s) { await sleep(20); continue; }
    const p = s.bootPhase;
    if (seen[seen.length - 1] !== p) seen.push(p);
    if (!s.booting && seen.length) break;
    await sleep(15);
  }
  return JSON.stringify({ seen: seen, final: __fm.store.bootPhase,
                          booting: __fm.store.booting,
                          route: __fm.store.route });
})()"""

# 2. estructura del overlay .app-boot (pantalla compartida)
JS_SPLASH = """(async () => {
  await boot();
  __fm.store.booting = true;
  await sleep(250);
  const app = document.querySelector('.app-boot');
  const el = document.querySelector('.app-boot .bp-screen');
  if (!el) return 'FAIL: sin .bp-screen';
  const logo = el.querySelector('.bp-logo');
  const logoUse = logo ? logo.querySelector('use') : null;
  const e2e = el.querySelector('.bp-e2e');
  const use = e2e ? e2e.querySelector('use') : null;
  const out = {
    logo: logo ? (logo.getAttribute('src') || '') : '',
    logoMark: logoUse ? (logoUse.getAttribute('href') || '') : '',
    e2eTxt: e2e ? e2e.textContent.trim() : '',
    key: use ? (use.getAttribute('href') || '') : '',
    bar: !!el.querySelector('.bp-bar'),
    status: !!el.querySelector('.bp-status'),
    pos: app ? getComputedStyle(app).position : '',
    ikey: !!document.querySelector('svg symbol#i-key'),
  };
  __fm.store.booting = false;
  await sleep(200);
  out.gone = !document.querySelector('.app-boot');
  return JSON.stringify(out);
})()"""

# 3. cada fase: SU texto (es/en) y la barra scaleX creciente
JS_FASES = """(async () => {
  await boot();
  __fm.store.booting = true;
  const keys = ['resources', 'session', 'chats', 'people', 'previews', 'ready'];
  const out = { txts: [], scales: [] };
  for (let i = 0; i < keys.length; i++) {
    __fm.store.bootPhase = keys[i];
    await sleep(500);              /* la transición de la barra es .4s */
    const stEl = document.querySelector('.bp-status');
    out.txts.push(stEl ? stEl.textContent.trim() : '');
    const bar = document.querySelector('.bp-bar > i');
    const m = bar ? getComputedStyle(bar).transform : '';
    const mm = m.match(/matrix\\(([-\\d.]+)/);
    out.scales.push(mm ? parseFloat(mm[1]) : -1);
  }
  __fm.store.lang = 'en';
  __fm.store.bootPhase = 'people';
  await sleep(300);
  const stEn = document.querySelector('.bp-status');
  out.en = stEn ? stEn.textContent.trim() : '';
  __fm.store.lang = 'es';
  __fm.store.booting = false;
  await sleep(200);
  return JSON.stringify(out);
})()"""

# 4. la carga de la conversación usa los CUBITOS (no el spin)
JS_CUBES = """(async () => {
  await boot();
  const it = await wait('.chat-item');
  if (!it) return 'FAIL: sin chats';
  it.click();
  const cid = __fm.store.activeChatId;
  if (!cid) return 'FAIL: sin chat activo';
  let t = Date.now();
  while (Date.now() - t < 8000 && !__fm.store.loaded[cid]) await sleep(120);
  __fm.store.chatLoading = true;
  __fm.store.loaded[cid] = false;
  await sleep(250);
  const mo = document.querySelector('.msgs-load');
  if (!mo) return 'FAIL: sin .msgs-load';
  const cubes = mo.querySelectorAll('.cubes .cube');
  const c0 = cubes.length ? getComputedStyle(cubes[0]) : null;
  const out = {
    n: cubes.length,
    anim: c0 ? c0.animationName : '',
    dur: c0 ? c0.animationDuration : '',
    delay: cubes.length > 1 ? getComputedStyle(cubes[1]).animationDelay : '',
    color: c0 ? c0.backgroundColor : '',
    txt: mo.textContent.trim(),
  };
  __fm.store.loaded[cid] = true;
  __fm.store.chatLoading = false;
  return JSON.stringify(out);
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w38a{tag}@t.fi", f"w38a{tag}")
    B = ct.register(a.base, f"w38b{tag}@t.fi", f"w38b{tag}")
    BU = B["user"]["username"]
    print(f"· A={A['user']['username']} B={BU}")

    st, r = ct.dm_between(a.base, A["access"], B["access"],
                          A["user"]["username"], BU)
    assert st in (200, 201), (st, r)
    dm = r["chat"]["id"]
    ct.send(a.base, B["access"], dm,
            {"kind": "text", "body": f"hola w38 {tag}",
             "client_msg_id": str(uuid.uuid4())})
    ct.send(a.base, B["access"], dm,
            {"kind": "text", "body": f"segundo mensaje w38 {tag}",
             "client_msg_id": str(uuid.uuid4())})
    print(f"· dm={dm}")

    # ============ sesión de A en el navegador =====================
    ok, res, log = shot(a.base + "/", SHOTS / "w38-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    # ============ 1. fases del arranque real ======================
    print("→ paso1 fases reales del arranque")
    ok, res, log = shot(a.base + "/", SHOTS / "w38-1-fases.png",
                        js=js(JS_PHASES), timeout=300)
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    order = ["resources", "session", "chats", "people", "previews", "ready"]
    seen = r.get("seen") or []
    idxs = []
    for p in seen:
        if p not in order:
            idxs = []
            break
        idxs.append(order.index(p))
    monotonic = bool(idxs) and idxs == sorted(idxs)
    step("el arranque avanza por las fases en orden y termina en 'ready'",
         ok and monotonic and r.get("final") == "ready"
         and r.get("booting") is False and r.get("route") == "app",
         f"res={res!r}")

    # ============ 2. estructura del splash ========================
    print("→ paso2 pantalla de arranque (.bp-screen)")
    ok, res, log = shot(a.base + "/", SHOTS / "w38-2-splash.png",
                        js=js(JS_SPLASH))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("el overlay lleva icono de la app + sello de cifrado + i-key",
         ok and r.get("logoMark") == "#i-logo-mark"
         and r.get("e2eTxt") == "Cifrado de extremo a extremo"
         and r.get("key") == "#i-key" and r.get("ikey") is True,
         f"res={res!r}")
    step("barra de progreso y texto de fase; fixed y se retira al terminar",
         ok and r.get("bar") is True and r.get("status") is True
         and r.get("pos") == "fixed" and r.get("gone") is True,
         f"res={res!r}")

    # ============ 3. textos y barra por fase ======================
    print("→ paso3 textos (es/en) y progreso de la barra")
    ok, res, log = shot(a.base + "/", SHOTS / "w38-3-barra.png",
                        js=js(JS_FASES), timeout=300)
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    want = ["Descargando los recursos…", "Iniciando sesión…",
            "Cargando los mensajes…", "Cargando usuarios…",
            "Cargando vista previas…", "Cargando…"]
    step("cada fase pinta SU texto en español",
         ok and r.get("txts") == want, f"res={res!r}")
    scales = r.get("scales") or []
    step("la barra avanza con cada fase (scaleX creciente hasta 1)",
         len(scales) == 6 and all(x >= 0 for x in scales)
         and scales == sorted(scales) and 0.95 <= scales[-1] <= 1.01,
         f"res={res!r}")
    step("en inglés el texto se localiza (Loading users…)",
         ok and r.get("en") == "Loading users…", f"res={res!r}")

    # ============ 4. cubitos en la conversación ===================
    print("→ paso4 animación de cubitos en la carga del chat")
    ok, res, log = shot(a.base + "/", SHOTS / "w38-4-cubitos.png",
                        js=js(JS_CUBES))
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    step("la carga del chat muestra 2 cubitos (cubeSpinner 1,8s, -0,9s)",
         ok and r.get("n") == 2 and r.get("anim") == "cubeSpinner"
         and r.get("dur") == "1.8s" and r.get("delay") == "-0.9s",
         f"res={res!r}")
    step("los cubitos llevan el color de acento y el texto 'Cargando…'",
         ok and (r.get("color") or "") != ""
         and "Cargando" in (r.get("txt") or ""), f"res={res!r}")

    # ============ limpieza ========================================
    if ct.cleanup_db():
        print("· limpieza ok")
    else:
        print("· WARN: limpieza incompleta")

    print(f"\nW38: {_pass[0]} pasos OK, {_fail[0]} fallos")
    sys.exit(1 if _fail[0] else 0)


if __name__ == "__main__":
    main()
