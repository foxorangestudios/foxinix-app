#!/usr/bin/env python
"""W44 — botón "ir hacia abajo" en el chat (prueba mínima, a pedido).

1. con el chat scrolleado arriba aparece el botón .jump-bottom
2. el clic salta al final del historial
3. al llegar al final el botón se esconde
"""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode/shots")

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

JS_JUMP = """(async () => {
  await boot();
  const items = Array.from(document.querySelectorAll('.chat-item'));
  const dm = items.find(function (el) {
    return el.textContent.indexOf('{BU}') >= 0;
  });
  if (!dm) return 'FAIL: sin DM con B';
  dm.click();
  const sc = await wait('.msgs', 12000);
  if (!sc) return 'FAIL: sin .msgs';
  let t = Date.now();
  while (Date.now() - t < 10000) {
    if (sc.scrollHeight > sc.clientHeight + 200) break;   /* hay de qué scrollear */
    await sleep(200);
  }
  sc.scrollTop = 0;                /* ir arriba → el botón debe aparecer */
  await sleep(350);
  const btn = document.querySelector('.jump-bottom');
  const appeared = !!btn;
  const restBefore = sc.scrollHeight - sc.scrollTop - sc.clientHeight;
  if (btn) btn.click();            /* saltar al final */
  await sleep(500);
  const rest = sc.scrollHeight - sc.scrollTop - sc.clientHeight;
  return JSON.stringify({
    appeared: appeared,
    big: restBefore > 200,
    jumped: rest < 8,
    hidden: !document.querySelector('.jump-bottom'),
  });
})()"""


def shot(url, out, js, wait=400, timeout=180):
    cmd = [str(ct.PY), str(ct.SHOT), url, str(out), "--wait", str(wait),
           "--js", js]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    res = None
    for line in r.stdout.splitlines():
        if line.startswith("JSRES: "):
            try:
                res = json.loads(line[7:].strip())
            except Exception:
                res = line[7:].strip()
    return r.returncode == 0 and "SHOT:" in r.stdout, res, (r.stdout + r.stderr)


def sess_js(u):
    sess = json.dumps({"access": u["access"], "refresh": u["refresh"],
                       "user": u["user"], "pendingEmail": ""})
    return ct.JS_INJECT.replace(
        "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w44a{tag}@t.fi", f"w44a{tag}")
    B = ct.register(a.base, f"w44b{tag}@t.fi", f"w44b{tag}")
    BU = B["user"]["username"]
    print(f"· A={A['user']['username']} B={BU}")
    st, g = ct.http("POST", a.base + "/api/chats/dm",
                    {"username": BU}, token=A["access"])
    if st not in (200, 201):
        raise SystemExit(f"✗ dm: {st} {g}")
    dm = g["chat"]["id"]
    # historial largo (texto multi-línea) para que .msgs scrollee
    line = "fila de prueba W44 — el chat debe tener de dónde desplazarse"
    body = ("\n".join(f"{i:02d} · {line}" for i in range(10)))
    for i in range(8):
        ct.send(a.base, A["access"], dm,
                {"kind": "text", "body": body,
                 "client_msg_id": str(uuid.uuid4())})
    time.sleep(0.3)

    # inyección de sesión (disparo aparte, como el resto de suites)
    ok, _res, _log = shot(a.base + "/", SHOTS / "w44-0-injectar.png",
                          sess_js(A))
    if not ok:
        raise SystemExit("✗ inyección de sesión")
    js = W_WAIT + "\n" + JS_JUMP.replace("{BU}", BU)
    ok, res, log = shot(a.base + "/", SHOTS / "w44-1-jump.png", js)
    r = {}
    try:
        r = json.loads(res)
    except Exception:
        pass
    fails = 0

    def step(name, cond, detail=""):
        nonlocal fails
        mark = "✓" if cond else "✗"
        print(f"  {mark} {name}" + (f": {detail}" if (detail and not cond) else ""))
        if not cond:
            fails += 1

    step("el botón aparece con el chat scrolleado arriba",
         ok and r.get("appeared") and r.get("big"), f"res={res!r} log={log!r}")
    step("el clic salta al final del historial",
         r.get("jumped") is True, f"res={res!r}")
    step("al llegar al final el botón se esconde",
         r.get("hidden") is True, f"res={res!r}")

    ct.cleanup_db()
    total = 3
    print(f"W44: {total - fails} bien, {fails} mal")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
