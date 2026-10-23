#!/usr/bin/env python
"""E2E W18: anti-spam — bloqueo escalonado en el server + pantalla de aviso.

API (contra el server local):
  1. ráfaga de mensajes → 429 con retry_after y bandera spam (los 4
     primeros rechazos solo avisan, sin bloqueo)
  2. 5º rechazo seguido → la cuenta queda bloqueada ~5 min
  3. enviar estando bloqueado sigue en 429 y NO duplica el tiempo
  4. unidad: los puntos decaen con el tiempo (SpamBlock puro)

UI (Firefox headless):
  5. el 429 levanta la pantalla de aviso: título SPAM, botón con cuenta
     regresiva "[Ok, perdón (10s)]"; Esc y el fondo NO la cierran; el
     botón se activa a los 10 s y solo con él desaparece

Uso: server/.venv/bin/python tests/spam_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "server"))

import chat_ui_test as ct  # noqa: E402  (helpers: register, send, run_shot…)

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

# Martilla el envío en el composer hasta que el server responda 429 y
# verifica la pantalla de aviso: título, cuenta regresiva, que Esc y el
# fondo no la cierran, y que el botón solo se activa tras los 10 s.
JS_SPAM_UI = """(async () => {
  """ + W_WAIT + """
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  if (!await wait('.composer-input')) return 'FAIL: sin composer';
  await sleep(300);
  const ta = document.querySelector('.composer-input');
  const send = document.querySelector('.comp-row .send-btn');
  // 7 envíos en ~0.5 s (la ráfaga del server admite 5)
  for (let i = 0; i < 7; i++) {
    ta.value = 'spam ' + i;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(70);          // deja renderizar el enabled del botón
    send.click();
  }
  const veil = await wait('.spam-veil', 15000);
  if (!veil) return 'FAIL: no apareció el aviso anti-spam';
  if (veil.textContent.indexOf('SPAM') < 0) return 'FAIL: sin título SPAM';
  const btn = veil.querySelector('.spam-ok');
  if (!btn) return 'FAIL: sin botón Ok';
  if (!btn.disabled) return 'FAIL: el botón arranca habilitado';
  if (!/\\(\\d+s\\)/.test(btn.textContent)) {
    return 'FAIL: sin cuenta regresiva (' + btn.textContent.trim() + ')';
  }
  // Esc no la cierra
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await sleep(300);
  if (!document.querySelector('.spam-veil')) return 'FAIL: Esc la cerró';
  // el fondo tampoco
  veil.click();
  await sleep(300);
  if (!document.querySelector('.spam-veil')) return 'FAIL: el fondo la cerró';
  // la cuenta regresiva termina y el botón se activa
  const t0 = Date.now();
  while (Date.now() - t0 < 13000 && btn.disabled) { await sleep(400); }
  if (btn.disabled) return 'FAIL: el botón nunca se activó';
  if (/\\(\\d+s\\)/.test(btn.textContent)) return 'FAIL: aún muestra la cuenta regresiva';
  btn.click();
  await sleep(300);
  if (document.querySelector('.spam-veil')) return 'FAIL: el botón no la cerró';
  return 'OK aviso anti-spam (título + cuenta regresiva + solo el botón)';
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    ok = fail = 0

    def step(name, cond, detail=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print(f"  ok   {name}  {detail}")
        else:
            fail += 1
            print(f"  FAIL {name}  {detail}")

    stamp = str(int(time.time()))[-7:]
    ua, ub, uc = f"spma{stamp}", f"spmb{stamp}", f"spmc{stamp}"
    try:
        A = ct.register(a.base, f"{ua}@test.local", ua)
        B = ct.register(a.base, f"{ub}@test.local", ub)
        C = ct.register(a.base, f"{uc}@test.local", uc)
        print(f"→ sembrados: {ua}, {ub}, {uc}")

        st, res = ct.dm_between(a.base, A["access"], B["access"], ua, ub)
        if st not in (200, 201):
            raise SystemExit(f"✗ dm A-B: {st} {res}")
        dm = res["chat"]["id"]

        def blast(token, chat, n, tag):
            codes = []
            details = []
            for i in range(n):
                st_, b = ct.http("POST", f"{a.base}/api/chats/{chat}/messages",
                                 {"kind": "text", "body": f"{tag}{i}",
                                  "client_msg_id": str(uuid.uuid4())}, token=token)
                codes.append(st_)
                details.append(b.get("detail", {}) if isinstance(b, dict) else {})
            return codes, details

        # 1) ráfaga: los primeros pasan, el exceso responde 429 con spam
        codes, details = blast(A["access"], dm, 8, "rafaga ")
        first429 = next((i for i, s in enumerate(codes) if s == 429), -1)
        d429 = details[first429] if first429 >= 0 else {}
        step("paso1 ráfaga → 429 spam",
             codes[:5] == [201] * 5 and first429 >= 5
             and isinstance(d429.get("retry_after"), int)
             and d429.get("spam") is True,
             f"codes={codes} detail={d429}")

        # 2) seguir martillando: el 5º rechazo seguido bloquea ~5 min
        blocked = {}
        for wave in range(3):
            _, det2 = blast(A["access"], dm, 3, f"mas{wave} ")
            for d in det2:
                if d.get("spam") and d.get("retry_after", 0) >= 290:
                    blocked = d
                    break
            if blocked:
                break
        step("paso2 5º rechazo → bloqueo ~5 min", bool(blocked)
             and blocked["retry_after"] >= 290, blocked)

        # 3) estando bloqueado: sigue 429 y NO se duplica el tiempo
        st, b = ct.http("POST", f"{a.base}/api/chats/{dm}/messages",
                        {"kind": "text", "body": "estando bloqueado",
                         "client_msg_id": str(uuid.uuid4())}, token=A["access"])
        d = b.get("detail", {}) if isinstance(b, dict) else {}
        step("paso3 bloqueado: 429 sin duplicar", st == 429
             and d.get("spam") is True
             and 290 <= d.get("retry_after", 0) <= blocked.get("retry_after", 0) + 2,
             f"st={st} detail={d}")

        # 4) unidad: los puntos decaen (1 por cada 30 min sin spam)
        from app.ratelimit import SpamBlock  # noqa: E402
        sb = SpamBlock()
        a1 = sb.hit(1)
        a2 = sb.hit(1)
        a3 = sb.hit(1)
        a4 = sb.hit(1)                        # 4 avisos sin bloqueo
        s5 = sb.hit(1)                        # 5º → 5 min
        sb._state[1][1] -= 31 * 60            # 31 min sin spam → -1 punto
        s6 = sb.hit(1)                        # vuelve a 5 min (no 10)
        sb._state[1][1] -= 20 * 3600          # días sin spam → puntos a 0
        s7 = sb.hit(1)                        # otra vez solo aviso
        step("paso4 decay de puntos",
             a1 == a2 == a3 == a4 == 0.0 and 280 <= s5 <= 300
             and 280 <= s6 <= 300 and s7 == 0.0,
             f"s5={s5:.0f} s6={s6:.0f} s7={s7:.0f}")

        # 5) UI: C (sin bloquear) martilla el composer → pantalla de aviso
        st, res = ct.dm_between(a.base, C["access"], B["access"], uc, ub)
        if st not in (200, 201):
            raise SystemExit(f"✗ dm C-B: {st} {res}")
        dm_c = res["chat"]["id"]
        ct.send(a.base, B["access"], dm_c,
                {"kind": "text", "body": "hola C", "client_msg_id": str(uuid.uuid4())})

        ok0, res0, _, log = ct.run_shot(
            a.base + "/", SHOTS / "spam-0-perfil.png",
            js="localStorage.removeItem('fm.session'); 'limpia'", wait=200)
        step("paso5 perfil", ok0 and res0 == "limpia", res0 or log[-400:])

        sess = json.dumps({"access": C["access"], "refresh": C["refresh"],
                           "user": C["user"], "pendingEmail": ""})
        sess_js = ct.JS_INJECT.replace(
            "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))
        ok1, res1, _, log = ct.run_shot(
            a.base + "/", SHOTS / "spam-1-sesion.png", js=sess_js, wait=300)
        step("paso6 sesión", ok1 and bool(res1), res1 or log[-400:])

        okk, ress, _, log = ct.run_shot(
            a.base + "/", SHOTS / "spam-2-aviso.png", js=JS_SPAM_UI,
            wait=500, timeout=200)
        step("paso7 pantalla anti-spam",
             okk and str(ress).startswith("OK"),
             ress if ress else log[-600:])

        print(f"\nspam UI: {ok} ok, {fail} fallas")
        sys.exit(1 if fail else 0)
    finally:
        print("  datos de prueba eliminados de la DB local"
              if ct.cleanup_db() else "  WARN: limpieza incompleta")


if __name__ == "__main__":
    main()
