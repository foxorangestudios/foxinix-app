#!/usr/bin/env python3
"""W46: administración de grupos (owner/admin).

Cubre lo mínimo del lote:
  1. `GET /members` expone el rol; un miembro común no puede expulsar.
  2. El owner asciende a admin; ese admin envía un mensaje con
     `sender.role=admin` y el panel muestra [Admin].
  3. Un admin puede ascender a un miembro; no puede degradar/sacar a
     otro admin ni al owner.
  4. El expulsado recibe `member_removed` por WS y deja de ver el chat;
     los que quedan reciben los avisos `system` de ascenso y expulsión.
  5. El owner puede degradar/sacar a un admin.

Uso: server/.venv/bin/python tests/w46_test.py [--base http://127.0.0.1:8899]

Deja usuarios de prueba (como el resto de las suites); usa una base
desechable para correrlo.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402

SHOTS = Path("/tmp/opencode/w46shots")
BASE = "http://127.0.0.1:8899"

_pass = 0
_fail = 0


def step(name, cond, detail=""):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  \u2713 {name}")
    else:
        _fail += 1
        print(f"  \u2717 {name}: {detail}")


def http(base, method, path, body=None, token=None):
    return ct.http(method, base + path, body, token=token)


def shot(url, out, js=None, wait=500, timeout=180):
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
    return ok, res, r.stdout + r.stderr


def sess_js(u):
    sess = json.dumps({"access": u["access"], "refresh": u["refresh"],
                       "user": u["user"], "pendingEmail": ""})
    js = ct.JS_INJECT.replace(
        "SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))
    # La UI de esta suite verifica textos en español.
    return js + ";localStorage.setItem('fm.lang','es');"


def open_ws(token):
    ws = ws_connect(
        BASE.replace("http://", "ws://") + "/api/ws",
        subprotocols=["foxinix", token], open_timeout=5, legacy=True,
    )
    for _ in range(10):
        try:
            ev = json.loads(ws.recv(timeout=1.0))
            if ev.get("type") == "connected":
                break
        except TimeoutError:
            break
    return ws


def wait_type(ws, wanted, timeout=8):
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        try:
            raw = ws.recv(timeout=max(0.1, deadline - time.time()))
        except TimeoutError:
            break
        try:
            ev = json.loads(raw)
        except Exception:
            continue
        seen.append(ev.get("type"))
        if ev.get("type") == wanted:
            return ev, seen
    return None, seen


# La UI de A: tags y menús del panel de miembros. Se ejecuta después de
# ascender a B y antes de tocar los roles de C.
JS_PANEL = """(async () => {
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
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const gi = Array.from(document.querySelectorAll('.chat-item')).find(function (el) {
    return el.textContent.indexOf('«GT»') >= 0;
  });
  if (!gi) return JSON.stringify({ fail: 'sin grupo' });
  gi.click();
  if (!await wait('.msgs .msg', 12000)) return JSON.stringify({ fail: 'sin mensajes' });
  if (!document.querySelector('.profile-panel')) {
    const info = await wait('[title="Info del chat"]', 6000);
    if (!info) return JSON.stringify({ fail: 'sin boton info' });
    info.click();
  }
  if (!await wait('.profile-panel .mi-row', 8000)) {
    return JSON.stringify({ fail: 'sin miembros' });
  }
  const rows = Array.from(document.querySelectorAll('.profile-panel .mi-row'));
  const rowOf = function (u) {
    return rows.find(function (row) { return row.textContent.indexOf(u) >= 0; });
  };
  const roleOf = function (u) {
    const row = rowOf(u);
    const tag = row && row.querySelector('.mi-role');
    return tag ? tag.textContent.trim() : '';
  };
  const menuOf = function (u) {
    const row = rowOf(u);
    return row ? row.querySelector('.mi-more') : null;
  };
  const labelsOf = async function (u) {
    const b = menuOf(u);
    if (!b) return [];
    b.click();
    if (!await wait('.ctx-menu', 4000)) return [];
    const labels = Array.from(document.querySelectorAll('.ctx-menu .ctx-item'))
      .map(function (x) { return x.textContent.trim(); });
    b.click();
    await sleep(200);
    return labels;
  };
  const out = {
    aTag: roleOf('«AU»'),
    bTag: roleOf('«BU»'),
    cTag: roleOf('«CU»'),
    aMenu: !!menuOf('«AU»'),
    bMenu: !!menuOf('«BU»'),
    cMenu: !!menuOf('«CU»'),
    bLabels: await labelsOf('«BU»'),
    cLabels: await labelsOf('«CU»'),
    bMsgTag: Array.from(document.querySelectorAll('.msgs .b-sender'))
      .filter(function (x) { return x.textContent.indexOf('«BU»') >= 0; })
      .map(function (x) {
        const tag = x.querySelector('.b-role');
        return tag ? tag.textContent.trim() : '';
      }),
  };
  return JSON.stringify(out);
})()"""


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    BASE = a.base
    mail = os.environ.get("FOXMSG_MAIL_LOG")
    if mail:
        ct.MAIL_LOG = Path(mail)
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(BASE, f"w46a{tag}@t.fi", f"w46a{tag}")
    B = ct.register(BASE, f"w46b{tag}@t.fi", f"w46b{tag}")
    C = ct.register(BASE, f"w46c{tag}@t.fi", f"w46c{tag}")
    au, bu, cu = (A["user"], B["user"], C["user"])
    gtitle = f"W46-Grupo {tag}"
    print(f"· owner={au['username']} admin={bu['username']} member={cu['username']}")

    st, r = http(BASE, "POST", "/api/chats/group", {
        "title": gtitle, "members": [bu["username"], cu["username"]],
    }, token=A["access"])
    step("crear grupo con owner y dos miembros", st == 201, (st, r))
    if st != 201:
        print(f"W46: {_pass} bien, {_fail} mal")
        sys.exit(1)
    gid = r["chat"]["id"]

    st, r = http(BASE, "GET", f"/api/chats/{gid}/members", token=A["access"])
    roles = {m["username"]: m.get("role") for m in r.get("members", [])}
    step("GET members expone owner/admin/member",
         st == 200 and roles.get(au["username"]) == "owner"
         and roles.get(bu["username"]) == "member"
         and roles.get(cu["username"]) == "member", (st, r))

    st, r = http(BASE, "DELETE",
                 f"/api/chats/{gid}/members/{cu['id']}", token=B["access"])
    step("un miembro común no puede sacar a otro", st == 403, (st, r))

    st, r = http(BASE, "PATCH",
                 f"/api/chats/{gid}/members/{bu['id']}",
                 {"role": "admin"}, token=A["access"])
    step("el owner asciende a admin", st == 200 and r.get("role") == "admin",
         (st, r))

    st, r = http(BASE, "GET", "/api/chats", token=B["access"])
    chats = {c["id"]: c for c in r.get("chats", [])}
    step("la lista del nuevo admin trae my_role=admin",
         chats.get(gid, {}).get("my_role") == "admin", r)

    st, r = http(BASE, "POST", f"/api/chats/{gid}/messages",
                 {"kind": "text", "body": "mensaje de admin W46 " + tag},
                 token=B["access"])
    sender = (r.get("message") or {}).get("sender") or {}
    step("el mensaje del admin trae sender.role=admin",
         st == 201 and sender.get("role") == "admin", (st, r))

    # UI de A: etiquetas y menús del panel de miembros.
    ok, _res, _log = shot(BASE + "/", SHOTS / "w46-0-inject.png",
                          sess_js(A), wait=700)
    if not ok:
        step("inyectar la sesión de A en Firefox", False, _log[-500:])
    else:
        js = (JS_PANEL.replace("«GT»", gtitle).replace("«AU»", au["username"])
              .replace("«BU»", bu["username"]).replace("«CU»", cu["username"]))
        ok, res, log = shot(BASE + "/", SHOTS / "w46-1-panel.png", js, wait=700)
        try:
            d = json.loads(res)
        except Exception:
            d = {}
        step("el panel muestra [Admin] al owner y al admin, no al miembro",
             ok and d.get("aTag") == "[Admin]" and d.get("bTag") == "[Admin]"
             and d.get("cTag") == "", d or log[-500:])
        step("solo owner/admin ven el menú; el owner puede degradar/sacar",
             d.get("aMenu") is False and d.get("bMenu") is True
             and d.get("cMenu") is True
             and "Quitar admin" in d.get("bLabels", [])
             and "Eliminar del grupo" in d.get("bLabels", [])
             and "Hacer admin" in d.get("cLabels", []), d)
        step("el nombre del remitente admin lleva [Admin]",
             "[Admin]" in d.get("bMsgTag", []), d)

    # Un admin puede ascender a un miembro; luego ya no puede tocarlo.
    st, r = http(BASE, "PATCH",
                 f"/api/chats/{gid}/members/{cu['id']}",
                 {"role": "admin"}, token=B["access"])
    step("un admin asciende a un miembro común",
         st == 200 and r.get("role") == "admin", (st, r))
    st, r = http(BASE, "PATCH",
                 f"/api/chats/{gid}/members/{cu['id']}",
                 {"role": "member"}, token=B["access"])
    step("un admin no puede degradar a otro admin", st == 403, (st, r))
    st, r = http(BASE, "DELETE",
                 f"/api/chats/{gid}/members/{cu['id']}", token=B["access"])
    step("un admin no puede sacar a otro admin", st == 403, (st, r))

    # WS del objetivo: primero el cambio de rol, luego la expulsión.
    wsc = open_ws(C["access"])
    st, r = http(BASE, "PATCH",
                 f"/api/chats/{gid}/members/{cu['id']}",
                 {"role": "member"}, token=A["access"])
    step("el owner degrada al admin", st == 200 and r.get("role") == "member",
         (st, r))
    ev, seen = wait_type(wsc, "member_role")
    step("el degradado recibe member_role por WS",
         ev is not None and ev.get("role") == "member", (ev, seen))

    st, r = http(BASE, "DELETE",
                 f"/api/chats/{gid}/members/{cu['id']}", token=B["access"])
    step("un admin saca a un miembro común", st == 200, (st, r))
    ev, seen = wait_type(wsc, "member_removed")
    step("el expulsado recibe member_removed por WS",
         ev is not None and ev.get("chat_id") == gid and ev.get("title"),
         (ev, seen))
    wsc.close()

    st, r = http(BASE, "GET", "/api/chats", token=C["access"])
    step("el expulsado ya no ve el grupo",
         all(c["id"] != gid for c in r.get("chats", [])), r)
    st, r = http(BASE, "GET", f"/api/chats/{gid}/members", token=C["access"])
    step("el expulsado recibe 403 al leer miembros", st == 403, (st, r))

    st, r = http(BASE, "PATCH",
                 f"/api/chats/{gid}/members/{bu['id']}",
                 {"role": "member"}, token=A["access"])
    step("el owner degrada al admin restante", st == 200, (st, r))
    st, r = http(BASE, "DELETE",
                 f"/api/chats/{gid}/members/{bu['id']}", token=A["access"])
    step("el owner saca al admin restante", st == 200, (st, r))
    st, r = http(BASE, "GET", "/api/chats", token=B["access"])
    step("el segundo expulsado ya no ve el grupo",
         all(c["id"] != gid for c in r.get("chats", [])), r)

    st, r = http(BASE, "PATCH",
                 f"/api/chats/{gid}/members/{au['id']}",
                 {"role": "member"}, token=A["access"])
    step("nadie cambia su propio rol", st == 400, (st, r))
    st, r = http(BASE, "DELETE",
                 f"/api/chats/{gid}/members/{au['id']}", token=A["access"])
    step("el owner no puede sacarse a sí mismo", st == 400, (st, r))

    st, r = http(BASE, "GET", f"/api/chats/{gid}/messages?limit=100",
                 token=A["access"])
    sys_bodies = [m.get("body", "") for m in r.get("messages", [])
                  if m.get("kind") == "system"]
    step("quedan avisos system de ascenso y expulsión",
         any("hizo admin" in x for x in sys_bodies)
         and any("eliminó a" in x for x in sys_bodies), sys_bodies)

    total = _pass + _fail
    print(f"W46: {_pass} bien, {_fail} mal ({total} comprobaciones)")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
