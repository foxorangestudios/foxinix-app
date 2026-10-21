#!/usr/bin/env python
"""E2E W4: apariencia (tema/acento/fondo) + PWA (manifest + service worker).

Siembra 1 usuario y maneja Firefox headless (BiDi):
  1. modal Apariencia → tema claro + acento azul + fondo Uva (asserts en DOM
     y en localStorage)
  2. recarga → persistencia vía script pre-paint + manifest 200 + service
     worker activo con su caché del shell
  3. restaura valores por defecto y desregistra el SW (deja el perfil limpio
     para los otros tests)

Uso: python tests/w4_ui_test.py            (servidor local en :8899)
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402  (helpers: register, run_shot, cleanup_db)

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

JS_APPEAR = """(async () => {
  """ + W_WAIT + """
  // W8: ya no hay botón de apariencia suelto: vive en Ajustes (1ª pestaña)
  const gear = await wait('button[title="Ajustes"]');
  if (!gear) return 'FAIL: sin botón Ajustes';
  gear.click();
  const modal = await wait('.modal.settings');
  if (!modal) return 'FAIL: no abrió Ajustes';
  if (modal.textContent.indexOf('Apariencia') < 0) return 'FAIL: modal equivocado';

  const opts = document.querySelectorAll('.ap-opt');
  if (opts.length < 2) return 'FAIL: sin opciones de tema';
  opts[1].click();                       // Claro
  if (document.documentElement.getAttribute('data-theme') !== 'light') {
    return 'FAIL: no cambió el tema';
  }

  const sws = document.querySelectorAll('.ap-sw');
  if (sws.length < 2) return 'FAIL: sin swatches de acento';
  sws[1].click();                        // #1f9dfa
  const acc = document.documentElement.style.getPropertyValue('--accent').trim().toLowerCase();
  if (acc !== '#1f9dfa') return 'FAIL: acento=' + acc;

  const wls = document.querySelectorAll('.ap-wl');
  if (wls.length < 3) return 'FAIL: sin opciones de fondo';
  wls[2].click();                        // Uva #15121c
  const wall = document.documentElement.style.getPropertyValue('--wall').trim().toLowerCase();
  if (wall !== '#15121c') return 'FAIL: fondo=' + wall;

  if (localStorage.getItem('fm.accent') !== '#1f9dfa') return 'FAIL: acento sin persistir';
  if (localStorage.getItem('fm.wall') !== '#15121c') return 'FAIL: fondo sin persistir';
  if (localStorage.getItem('fm.theme') !== 'light') return 'FAIL: tema sin persistir';
  return 'OK apariencia aplicada (tema, acento y fondo)';
})()"""

JS_PERSIST = """(async () => {
  """ + W_WAIT + """
  // 1) pre-paint: todo aplicado ANTES de Vue, en una carga fría
  if (document.documentElement.getAttribute('data-theme') !== 'light') {
    return 'FAIL: el tema no persistió';
  }
  const acc = document.documentElement.style.getPropertyValue('--accent').trim().toLowerCase();
  if (acc !== '#1f9dfa') return 'FAIL: el acento no persistió: ' + acc;
  const wall = document.documentElement.style.getPropertyValue('--wall').trim().toLowerCase();
  if (wall !== '#15121c') return 'FAIL: el fondo no persistió: ' + wall;

  // 2) manifest
  let mf = null;
  try {
    const r = await fetch('/manifest.webmanifest');
    if (!r.ok) return 'FAIL: manifest HTTP ' + r.status;
    mf = await r.json();
  } catch (e) { return 'FAIL: manifest ' + e; }
  if (!mf || mf.short_name !== 'Foxinix' || mf.display !== 'standalone') {
    return 'FAIL: manifest raro: ' + JSON.stringify(mf);
  }

  // 3) service worker activo + caché del shell
  if (!('serviceWorker' in navigator)) return 'FAIL: sin soporte de SW';
  let reg = null;
  try {
    reg = await Promise.race([
      navigator.serviceWorker.ready,
      new Promise((_, rej) => setTimeout(() => rej(new Error('timeout 8s')), 8000)),
    ]);
  } catch (e) { return 'FAIL: SW no activo: ' + e; }
  if (!reg || !reg.scope) return 'FAIL: SW sin scope';
  // la versión de la caché la lee de sw.js (sube en cada lote)
  let ver = '';
  try {
    const rsw = await fetch('/sw.js');
    const src = await rsw.text();
    /* W50: el shell pasó a SHELL_CACHE (el caché de medios es aparte). */
    const mm = src.match(/const (?:SHELL_)?CACHE = '([^']+)'/);
    if (mm) ver = mm[1];
  } catch (e) { return 'FAIL: leyendo sw.js: ' + e; }
  if (!ver) return 'FAIL: sin versión de caché en sw.js';
  const keys = await caches.keys();
  if (keys.indexOf(ver) < 0) {
    return 'FAIL: sin caché del shell ' + ver + ': ' + keys.join(',');
  }
  return 'OK pwa lista (scope=' + reg.scope + ' cache=' + ver + ' caches=' + keys.length + ')';
})()"""

JS_RESTORE = """(() => {
  try {
    localStorage.removeItem('fm.accent');
    localStorage.removeItem('fm.wall');
    localStorage.setItem('fm.theme', 'dark');
  } catch (e) {}
  document.documentElement.setAttribute('data-theme', 'dark');
  document.documentElement.style.removeProperty('--wall');
  document.documentElement.style.removeProperty('--accent');
  document.documentElement.style.removeProperty('--accent-d');
  // el SW y su caché no deben afectar a los otros tests
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.getRegistrations().then(function (rs) {
      rs.forEach(function (r) { r.unregister(); });
    });
  }
  if (window.caches) {
    caches.keys().then(function (ks) { ks.forEach(function (k) { caches.delete(k); }); });
  }
  return 'restaurado';
})()"""


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    stamp = str(int(time.time()))[-7:]
    user = f"foxui{stamp}"[:20]
    try:
        A = ct.register(a.base, f"{user}@test.local", user)
        print(f"→ sembrado: {user}")

        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))

        # 0) limpiar sesión vieja
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w4-0-prep.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        print("paso0 perfil:", js_res or "(sin jsres)")
        if not ok or not js_res:
            print(log[-1500:])
            raise SystemExit("✗ falló la limpieza de perfil")

        # 1) inyectar sesión
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w4-1-sesion.png", js=sess_js, wait=300)
        print("paso1 sesión:", js_res or "(sin jsres)")
        if not ok or not js_res:
            print(log[-1500:])
            raise SystemExit("✗ falló la inyección")

        # 2) modal apariencia: tema + acento + fondo
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w4-2-apariencia.png", js=JS_APPEAR, wait=900)
        print("paso2 apariencia:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló la apariencia")

        # 3) recarga fría: persistencia (pre-paint) + manifest + SW
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w4-3-persiste.png", js=JS_PERSIST, wait=900)
        print("paso3 persistencia+PWA:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló la persistencia/PWA")

        # 4) restaurar defaults y limpiar SW/cachés del perfil
        ok, js_res, _, log = ct.run_shot(
            f"{a.base}/", SHOTS / "w4-4-restaura.png", js=JS_RESTORE, wait=300)
        print("paso4 restaurar:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("restaurado"):
            print(log[-1500:])
            raise SystemExit("✗ falló la restauración")

        print("✓ W4 E2E completo → " + ", ".join(
            str(SHOTS / n) for n in
            ("w4-2-apariencia.png", "w4-3-persiste.png")))
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
