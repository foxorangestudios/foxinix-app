#!/usr/bin/env python3
"""E2E de la UI web: registro → cancelación al recargar → reemplazo → app.

Orquesta scripts/shot.py (Firefox headless + WebDriver BiDi) contra el
servidor local. El perfil de Firefox conserva el localStorage entre pasos.

  1. #/register → perfil → pantalla de verificación (cuenta creada, sin verificar).
  2. Recarga: la verificación se CANCELA y vuelve al login (sesión borrada,
     sin "token inválido").  [regresión del bug de recarga]
  3. Registrarse otra VEZ con el mismo correo: el server reemplaza la cuenta
     sin verificar y manda un código nuevo.  [regresión del 409 por correo]
  4. Recarga → cancela de nuevo → ingresar con usuario/clave → pantalla de
     verificación (retome por login) → código → app.
  5. Limpia la sesión, captura screenshots en /tmp/opencode/ y borra el usuario.

Uso: server/.venv/bin/python tests/web_e2e.py [--base http://127.0.0.1:8899]
"""
import argparse
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "scripts" / "shot.py"
MAIL_LOG = ROOT / "server" / "data" / "mail.log"
DB = ROOT / "server" / "data" / "foxmsg.db"
PY = ROOT / "server" / ".venv" / "bin" / "python"
SHOTS = Path("/tmp/opencode")

HELPERS = """
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const $ = s => document.querySelector(s);
  const wait = async (sel, ms = 8000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const el = $(sel);
      if (el) return el;
      await sleep(80);
    }
    return null;
  };
  const setVal = (sel, v) => {
    const el = $(sel);
    el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const err = () => { const e = $('.form-err'); return e ? e.innerText : ''; };
"""

STEP1 = ("""
(async () => {
%s
  __fm.go('register');
  if (!await wait('#r-mail')) return 'FAIL: no abrió /register';
  setVal('#r-mail', 'EMAIL');
  setVal('#r-user', 'USERNAME');
  setVal('#r-pw', 'clave12345');
  setVal('#r-pw2', 'clave12345');
  $('form button[type=submit]').click();
  if (!await wait('#p-name')) return 'FAIL: no pasó al perfil → ' + err();

  setVal('#p-name', 'Fox UI E2E');
  setVal('#p-status', 'Probando Foxinix');
  $('form button[type=submit]').click();
  if (!await wait('.code-input')) return 'FAIL: no pasó a verificar → ' + err();
  return 'OK registro+perfil';
})()
""") % HELPERS

# Recarga con sesión pending → bootstrap debe cancelar y volver al login.
STEP2 = ("""
(async () => {
%s
  const l = await wait('#l-id');
  if (!l) return 'FAIL: no volvió al login (ruta=' + location.pathname + ')';
  if ($('.code-input')) return 'FAIL: sigue en la pantalla de verificación';
  if (localStorage.getItem('fm.session')) return 'FAIL: quedó la sesión pending | raw=' + localStorage.getItem('fm.session') + ' | route=' + (__fm.store.route) + ' | booting=' + (__fm.store.booting) + ' | ws=' + (__fm.store.ws) + ' | toasts=' + ((window.__fm && __fm.store.toasts || []).map(t => t.msg).join(' / '));
  const fe = $('.form-err');
  if (fe && /inválid|expirad/i.test(fe.innerText)) return 'FAIL: ' + fe.innerText;
  const toasts = ((window.__fm && window.__fm.store && window.__fm.store.toasts) || [])
    .map(t => t.msg).join(' / ');
  if (!/Verificación cancelada/.test(toasts)) return 'FAIL: sin toast de cancelación → ' + toasts;
  return 'OK cancelada → login | toasts=' + toasts;
})()
""") % HELPERS

# Registrarse otra vez con el MISMO correo: el server debe reemplazar (201).
STEP3 = ("""
(async () => {
%s
  __fm.go('register');
  if (!await wait('#r-mail')) return 'FAIL: no abrió /register';
  setVal('#r-mail', 'EMAIL');
  setVal('#r-user', 'USERNAME');
  setVal('#r-pw', 'clave12345');
  setVal('#r-pw2', 'clave12345');
  $('form button[type=submit]').click();
  // Si no reemplazara la cuenta vieja, acá llega un 409 en .form-err.
  if (!await wait('#p-name')) return 'FAIL: no reemplazó la cuenta → ' + err();
  setVal('#p-name', 'Fox UI E2E');
  $('form button[type=submit]').click();
  if (!await wait('.code-input')) return 'FAIL: no pasó a verificar → ' + err();
  return 'OK reemplazo → verificar';
})()
""") % HELPERS

# Recarga (cancela otra vez) → ingresar con usuario/clave → código → app.
STEP4 = ("""
(async () => {
%s
  const l = await wait('#l-id');
  if (!l) return 'FAIL: no volvió al login (ruta=' + location.pathname + ')';
  if (localStorage.getItem('fm.session')) return 'FAIL: quedó la sesión pending';
  setVal('#l-id', 'USERNAME');
  setVal('#l-pw', 'clave12345');
  $('form button[type=submit]').click();
  const inp = await wait('.code-input', 10000);
  if (!inp) return 'FAIL: el login no retomó la verificación → ' + err();
  inp.value = 'CODE';
  inp.dispatchEvent(new Event('input', { bubbles: true }));  // auto-submit
  const list = await wait('.chat-list');
  if (!list) return 'FAIL: no entró a la app → ' + err();
  return 'OK app';
})()
""") % HELPERS


def run_shot(url, out, js=None, ev=None, wait=400):
    cmd = [str(PY), str(SHOT), url, str(out), "--wait", str(wait)]
    if js:
        cmd += ["--js", js]
    if ev:
        cmd += ["--eval", ev]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    eval_val = None
    js_res = None
    for line in r.stdout.splitlines():
        if line.startswith("EVAL: "):
            eval_val = line[len("EVAL: "):].strip()
        elif line.startswith("JSRES: "):
            js_res = line[len("JSRES: "):].strip().strip('"')
    ok = r.returncode == 0 and "SHOT:" in r.stdout
    return ok, js_res, eval_val, (r.stdout + r.stderr)


def wait_code(email, purpose="verify", timeout=8.0):
    """Último código para email/purpose en data/mail.log."""
    pat = re.compile(rf"\| {re.escape(email)} \| {purpose} \| (\d+)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if MAIL_LOG.is_file():
            matches = pat.findall(MAIL_LOG.read_text(encoding="utf-8"))
            if matches:
                return matches[-1]
        time.sleep(0.3)
    return None


def cleanup(email):
    """Borra el usuario de prueba (sin chats ni media: cuenta recién creada)."""
    try:
        con = sqlite3.connect(str(DB))
        cur = con.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = cur.fetchone()
        if row:
            con.execute("DELETE FROM email_codes WHERE user_id = ?", (row[0],))
            con.execute("DELETE FROM users WHERE id = ?", (row[0],))
            con.commit()
        con.close()
        return bool(row)
    except Exception as e:  # el servidor usa WAL; tolerar bloqueos
        print(f"WARN: cleanup: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()

    stamp = str(int(time.time()))[-7:]
    email = f"foxui{stamp}@test.local"
    user = f"foxui{stamp}"[:20]
    print(f"→ usuario de prueba: {user} <{email}>")

    def step(name, out, js, ev, expect_session=None, wait=400):
        ok, js_res, eval_val, log = run_shot(
            f"{a.base}" + ("/" if out != "e2e-1-registro.png" else "/#/register"),
            SHOTS / out, js=js, ev=ev, wait=wait,
        )
        print(f"{name}:", js_res or "(sin jsres)", "|", eval_val)
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            print(f"✗ falló {name}")
            sys.exit(1)
        if expect_session is not None:
            want = f"session={expect_session}"
            if want not in (eval_val or ""):
                print(f"✗ {name}: se esperaba '{want}' en: {eval_val}")
                sys.exit(1)
        return eval_val

    try:
        # 1) registro + perfil hasta la pantalla de código (cuenta sin verificar)
        step(
            "paso1 registro", "e2e-1-registro.png",
            STEP1.replace("EMAIL", email).replace("USERNAME", user),
            "location.pathname + '|' + (document.querySelector('.code-input') ? 'verify' : 'otra')"
            " + ' | ' + (localStorage.getItem('fm.session') ? 'session=si' : 'session=no')",
            expect_session="si",
        )

        # 2) recarga → la verificación se cancela y vuelve al login
        step(
            "paso2 recarga", "e2e-2-cancela.png", STEP2,
            "'ruta=' + location.pathname"
            " + ' | session=' + (localStorage.getItem('fm.session') ? 'si' : 'no')",
            expect_session="no",
        )

        # 3) mismo correo otra vez → el server reemplaza la cuenta pendiente
        step(
            "paso3 reemplazo", "e2e-3-reemplazo.png",
            STEP3.replace("EMAIL", email).replace("USERNAME", user),
            "location.pathname + '|' + (document.querySelector('.code-input') ? 'verify' : 'otra')"
            " + ' | ' + (localStorage.getItem('fm.session') ? 'session=si' : 'session=no')",
            expect_session="si",
        )

        # 4) código del registro nuevo (mail.log: última línea de este correo)
        code = wait_code(email)
        if not code:
            print("✗ no llegó el código a", MAIL_LOG)
            sys.exit(1)
        print("paso4: código =", code)

        # 5) cancela de nuevo → login con usuario/clave → código → app
        step(
            "paso5 verificar", "e2e-4-app.png",
            STEP4.replace("CODE", code).replace("USERNAME", user),
            "((document.querySelector('.side-logo')||{}).alt||'sin shell')"
            " + ' | ' + (((window.__fm||{}).store||{}).user||{}).username"
            " + ' | session=' + (localStorage.getItem('fm.session')?'si':'no')"
            " + ' | ruta=' + location.pathname",
            expect_session="si",
        )

        # 6) limpia la sesión para el próximo arranque y captura login final
        run_shot(
            f"{a.base}/", SHOTS / "e2e-5-login.png",
            js="localStorage.removeItem('fm.session'); location.reload();",
            ev="'ok'", wait=600,
        )
        print(f"✓ E2E completo → {SHOTS}/e2e-1-registro.png, e2e-2-cancela.png, "
              "e2e-3-reemplazo.png, e2e-4-app.png, e2e-5-login.png")
    finally:
        removed = cleanup(email)
        print("  usuario de prueba eliminado de la DB local" if removed
              else "  (no había usuario de prueba que limpiar)")


if __name__ == "__main__":
    main()
