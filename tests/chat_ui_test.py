#!/usr/bin/env python3
"""E2E visual del chat (W2): siembra 2 usuarios + conversación por REST y
conduce Firefox (scripts/shot.py) para capturar:

  1. Lista de chats con badge de no leídos.
  2. Conversación abierta (burbujas, agrupación, día HOY, cita, imagen, archivo).
  3. Corrida "live": mientras el navegador está abierto, B marca leído y envía
     un mensaje nuevo → se ven ✓✓ azules y el mensaje entrante por WS.

También valida el flujo "nuevo chat" (modal de búsqueda) en la lista.

Uso: server/.venv/bin/python tests/chat_ui_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import mimetypes
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "scripts" / "shot.py"
MAIL_LOG = ROOT / "server" / "data" / "mail.log"
DB = ROOT / "server" / "data" / "foxmsg.db"
PY = ROOT / "server" / ".venv" / "bin" / "python"
SHOTS = Path("/tmp/opencode")


# ------------------------------------------------------------ HTTP (urllib)

def http(method, url, data=None, token=None, raw=None, ctype=None):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if raw is not None:
        body = raw
        headers["Content-Type"] = ctype
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8")
            return r.status, (json.loads(txt) if txt else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


def multipart_field(file_path):
    """Cuerpo multipart/form-data para POST /api/media (campo 'file')."""
    boundary = "----fox" + uuid.uuid4().hex
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + file_path.read_bytes() + tail, f"multipart/form-data; boundary={boundary}"


# ------------------------------------------------------------ registro/verify

def wait_code(email, purpose="verify", timeout=8.0):
    pat = re.compile(rf"\| {re.escape(email)} \| {purpose} \| (\d+)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if MAIL_LOG.is_file():
            matches = pat.findall(MAIL_LOG.read_text(encoding="utf-8"))
            if matches:
                return matches[-1]
        time.sleep(0.3)
    return None


def register(base, email, username, password="foxpass12345"):
    st, res = http("POST", base + "/api/auth/register",
                   {"email": email, "username": username, "password": password})
    if st != 201:
        raise SystemExit(f"✗ register {username}: {st} {res}")
    pending = res["tokens"]["access"]
    code = wait_code(email)
    if not code:
        raise SystemExit(f"✗ sin código de verificación para {email}")
    st, res = http("POST", base + "/api/auth/verify", {"code": code}, token=pending)
    if st != 200:
        raise SystemExit(f"✗ verify {username}: {st} {res}")
    return {"user": res["user"], "access": res["tokens"]["access"],
            "refresh": res["tokens"]["refresh"]}


def send(base, tok, chat_id, payload):
    # W11: el server limita ~3 msgs/5 s con ráfaga de 5; un cliente real
    # espera retry_after y reintenta — el test hace lo mismo (y así la
    # suite cubre también la ruta del 429).
    for _ in range(5):
        st, res = http("POST", f"{base}/api/chats/{chat_id}/messages", payload, token=tok)
        if st == 429:
            wait = float((res.get("detail") or {}).get("retry_after") or 1)
            print(f"  · 429 rate limit, espero {wait:g}s y reintento…")
            time.sleep(min(wait, 10) + 0.1)
            continue
        if st != 201:
            raise SystemExit(f"✗ send: {st} {res}")
        return res["message"]
    raise SystemExit("✗ send: 429 persistente tras reintentos")


def ensure_friends(base, a_tok, b_tok, a_user, b_user):
    """Regla del producto: un MD exige solicitud de amistad aceptada.

    Los tests históricos creaban el DM directamente. Este helper deja la
    amistad lista (o reutiliza una existente) antes de abrir el chat.
    """
    st, res = http("POST", base + "/api/people/requests",
                   {"username": b_user}, token=a_tok)
    if st == 201:
        rid = res["id"]
        st, res = http("POST", f"{base}/api/people/requests/{rid}/accept",
                       {}, token=b_tok)
        if st != 200:
            raise SystemExit(f"✗ aceptar amistad: {st} {res}")
        return
    if st != 409:
        raise SystemExit(f"✗ solicitud de amistad: {st} {res}")
    # 409 = ya amigos o solicitud pendiente (en cualquier dirección).
    for tok, other in ((b_tok, a_user), (a_tok, b_user)):
        st, data = http("GET", base + "/api/people", token=tok)
        if st != 200:
            continue
        for f in data.get("friends", []):
            if f.get("username", "").lower() == other.lower():
                return
        for r in data.get("received", []):
            u = r.get("user") or {}
            if u.get("username", "").lower() == other.lower():
                st, res = http(
                    "POST", f"{base}/api/people/requests/{r['id']}/accept",
                    {}, token=tok)
                if st != 200:
                    raise SystemExit(f"✗ aceptar amistad pendiente: {st} {res}")
                return
    raise SystemExit("✗ no se pudo establecer la amistad de prueba")


def dm_between(base, a_tok, b_tok, a_user, b_user):
    """Crea/reutiliza el MD después de asegurar la amistad."""
    ensure_friends(base, a_tok, b_tok, a_user, b_user)
    return http("POST", base + "/api/chats/dm", {"username": b_user},
                token=a_tok)


def max_seq(base, tok, chat_id):
    st, res = http("GET", f"{base}/api/chats/{chat_id}/messages?limit=100", token=tok)
    msgs = res.get("messages", [])
    return max((m["seq"] for m in msgs), default=0)


def upload(base, tok, path):
    raw, ctype = multipart_field(path)
    st, res = http("POST", base + "/api/media", token=tok, raw=raw, ctype=ctype)
    if st != 201:
        raise SystemExit(f"✗ upload {path.name}: {st} {res}")
    return res


# ------------------------------------------------------------ orquestación

def run_shot(url, out, js=None, ev=None, wait=400, timeout=150):
    cmd = [str(PY), str(SHOT), url, str(out), "--wait", str(wait)]
    if js:
        cmd += ["--js", js]
    if ev:
        cmd += ["--eval", ev]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    eval_val = js_res = None
    for line in r.stdout.splitlines():
        if line.startswith("EVAL: "):
            eval_val = line[len("EVAL: "):].strip()
        elif line.startswith("JSRES: "):
            js_res = line[len("JSRES: "):].strip().strip('"')
    ok = r.returncode == 0 and "SHOT:" in r.stdout
    return ok, js_res, eval_val, (r.stdout + r.stderr)


def spawn_shot(url, out, js, wait=400):
    cmd = [str(PY), str(SHOT), url, str(out), "--wait", str(wait), "--js", js]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


# ------------------------------------------------------------ limpieza

def cleanup_db():
    """Borra TODO lo sembrado (usuarios de prueba, chats, media...)."""
    media_dir = ROOT / "server" / "data" / "media"
    try:
        con = sqlite3.connect(str(DB), timeout=10)
        rows = con.execute("SELECT path FROM media").fetchall()
        for (p,) in rows:
            try:
                (media_dir / p).unlink(missing_ok=True)
            except Exception:
                pass
        for table in ("reactions", "messages", "chat_members", "chats",
                      "media", "email_codes", "friend_requests", "users"):
            con.execute(f"DELETE FROM {table}")
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        con.close()
        return n == 0
    except Exception as e:
        print(f"WARN: cleanup: {e}")
        return False


# ------------------------------------------------------------ JS de la UI

JS_INJECT = """(() => {
  localStorage.setItem('fm.session', 'SESSION_JSON');
  return 'sesión inyectada';
})()"""

JS_LIST = """(async () => {
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
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: no apareció la lista de chats';
  await sleep(300);
  return 'OK lista, items=' + document.querySelectorAll('.chat-item').length +
    ' ws=' + __fm.store.ws;
})()"""

JS_OPEN = """(async () => {
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
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  const msgs = await wait('.msg', 10000);
  if (!msgs) return 'FAIL: no abrió la conversación';
  const t0 = Date.now();
  while (Date.now() - t0 < 6000 &&
         document.querySelectorAll('.msgs .msg').length < 6) await sleep(120);
  await sleep(300);
  return 'OK conversación, msgs=' + document.querySelectorAll('.msgs .msg').length;
})()"""

JS_LIVE = """(async () => {
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
  const item = await wait('.chat-list .chat-item');
  if (!item) return 'FAIL: sin chats';
  item.click();
  if (!await wait('.msg', 10000)) return 'FAIL: no abrió';
  const t0 = Date.now();
  while (Date.now() - t0 < 6000 &&
         document.querySelectorAll('.msgs .msg').length < 6) await sleep(120);
  // Base solo con el canal vivo listo (si no, medimos contra un fetch inicial)
  const tWs = Date.now();
  while (Date.now() - tWs < 15000 && __fm.store.ws !== 'on') await sleep(120);
  const base = document.querySelectorAll('.msgs .msg').length;
  // Espera a que el servidor (B) marque leído y envíe algo por WS.
  const t1 = Date.now();
  let got = false;
  while (Date.now() - t1 < 25000) {
    if (document.querySelectorAll('.msgs .msg').length > base ||
        document.querySelector('.msg.mine .t-read')) { got = true; break; }
    await sleep(200);
  }
  if (!got) return 'FAIL: sin evento WS (msgs=' +
    document.querySelectorAll('.msgs .msg').length + '/' + base +
    ' ws=' + __fm.store.ws + ')';
  await sleep(700);
  const reads = document.querySelectorAll('.msg.mine .t-read').length;
  return 'OK live, msgs=' + document.querySelectorAll('.msgs .msg').length +
    ' ticksAzules=' + reads + ' ws=' + __fm.store.ws;
})()"""

JS_MODAL = """(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (sel, ms = 8000) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(80);
    }
    return null;
  };
  const btn = await wait('.side-head .icon-btn');
  if (!btn) return 'FAIL: sin barra lateral';
  btn.click();
  if (!await wait('.modal')) return 'FAIL: no abrió el modal';
  const inp = document.querySelector('.m-search input');
  const t = Date.now();
  while (Date.now() - t < 6000 && !document.querySelector('.res-item')) {
    inp.value = 'BUSER';
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    await sleep(500);
  }
  if (!document.querySelector('.res-item')) return 'FAIL: sin resultados';
  await sleep(200);
  return 'OK modal, resultados=' + document.querySelectorAll('.res-item').length;
})()"""


# ------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    stamp = str(int(time.time()))[-7:]
    email_a, user_a = f"foxui{stamp}@test.local", f"foxui{stamp}"[:20]
    email_b, user_b = f"nena{stamp}@test.local", f"nena{stamp}"[:20]
    seed = {}

    try:
        # 1) dos usuarios verificados vía REST (más rápido que por UI)
        A = register(a.base, email_a, user_a)
        B = register(a.base, email_b, user_b)
        print(f"→ sembrados: {user_a} (A) y {user_b} (B)")

        # 2) DM A→B (con amistad aceptada, regla nueva)
        st, res = dm_between(a.base, A["access"], B["access"],
                             user_a, user_b)
        if st != 201:
            raise SystemExit(f"✗ dm: {st} {res}")
        cid = res["chat"]["id"]
        seed["chat"] = cid

        # 3) conversación variada
        send(a.base, B["access"], cid,
             {"kind": "text", "body": "¡Hola! ¿Probaste el chat nuevo?"})
        send(a.base, A["access"], cid,
             {"kind": "text", "body": "Sí: corre en mi servidor propio 🦊"})

        shots_png = sorted(SHOTS.glob("e2e-*.png")) or sorted(SHOTS.glob("chat-*.png"))
        if shots_png:
            up = upload(a.base, B["access"], shots_png[0])
            send(a.base, B["access"], cid,
                 {"kind": "image", "media_id": up["id"]})
            print(f"→ imagen: {shots_png[0].name}")

        m_cap = send(a.base, A["access"], cid,
                     {"kind": "text", "body": "¡Qué buena la captura!"})
        send(a.base, B["access"], cid,
             {"kind": "text", "body": "¡Gracias! La saqué recién",
              "reply_to": m_cap["id"]})

        api_txt = ROOT / "docs" / "API.md"
        if api_txt.is_file():
            up = upload(a.base, A["access"], api_txt)
            send(a.base, A["access"], cid, {"kind": "file", "media_id": up["id"]})
            print("→ archivo: API.md")

        send(a.base, B["access"], cid,
             {"kind": "text", "body": "Te dejo el contrato acá arriba."})

        # A lee hasta acá → badge de no leídos = 2
        seq_a = max_seq(a.base, A["access"], cid)
        st, _ = http("POST", f"{a.base}/api/chats/{cid}/read",
                     {"seq": seq_a}, token=A["access"])
        if st != 200:
            print(f"WARN: read A: {st}")

        send(a.base, B["access"], cid,
             {"kind": "text", "body": "¿Me pasás el enlace del túnel cuando puedas?"})
        send(a.base, B["access"], cid,
             {"kind": "text", "body": "Ah, y probá el botón de sol: hay tema claro ☀"})
        print("→ conversación lista (2 no leídos para A)")

        # B NO lee todavía: el evento 'read' live pondrá los ✓✓ azules.

        sess = json.dumps({"access": A["access"], "refresh": A["refresh"],
                           "user": A["user"], "pendingEmail": ""})
        sess_js = JS_INJECT.replace("SESSION_JSON", sess.replace("\\", "\\\\").replace("'", "\\'"))

        # 0) limpiar la sesión vieja del perfil: si había tokens de un usuario
        #    ya borrado, el bootstrap en vuelo haría clearSession DESPUÉS de
        #    nuestra inyección y la pisaría (carrera vista en diagnósticos).
        ok, js_res, ev, log = run_shot(f"{a.base}/", SHOTS / "chat-0-prep.png",
                                       js="localStorage.removeItem('fm.session'); 'limpia'",
                                       ev="'ok'", wait=200)
        print("paso0 perfil:", js_res or "(sin jsres)")
        if not ok or not js_res:
            print(log[-1500:])
            raise SystemExit("✗ falló la limpieza de perfil")

        # 4) inyectar sesión de A en el navegador
        ok, js_res, ev, log = run_shot(f"{a.base}/", SHOTS / "chat-0-sesion.png",
                                       js=sess_js, ev="'inyectada'")
        print("paso1 sesión:", js_res or ev)
        if not ok or not js_res:
            print(log[-1500:])
            raise SystemExit("✗ falló la inyección de sesión")

        # 5) lista con badges
        ok, js_res, ev, log = run_shot(f"{a.base}/", SHOTS / "chat-1-lista.png",
                                       js=JS_LIST, ev="__fm.store.ws + '|' + __fm.store.chats.length",
                                       wait=900)
        print("paso2 lista:", js_res or "(sin jsres)", "|", ev)
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló la lista")

        # 6) conversación abierta
        ok, js_res, ev, log = run_shot(f"{a.base}/", SHOTS / "chat-2-conversacion.png",
                                       js=JS_OPEN, ev="1", wait=900)
        print("paso3 conversación:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló la conversación")

        # 7) modal "nuevo chat" con búsqueda de B
        ok, js_res, ev, log = run_shot(f"{a.base}/", SHOTS / "chat-3-nuevo.png",
                                       js=JS_MODAL.replace("BUSER", user_b[:6]),
                                       ev="1", wait=700)
        print("paso4 modal:", js_res or "(sin jsres)")
        if not ok or not js_res or not str(js_res).startswith("OK"):
            print(log[-1500:])
            raise SystemExit("✗ falló el modal de nuevo chat")

        # 8) corrida live: navegador en paralelo → B lee y escribe por rondas.
        #    Primero esperamos que el navegador conecte SU WS: last_seen solo
        #    lo toca ws.py, así que un salto de la marca = conectó. Sin esta
        #    sincronía B terminaba antes que el navegador arrancara y todo
        #    llegaba por el fetch inicial (sin evento vivo que observar).
        st, res = http("GET", f"{a.base}/api/users/{user_a}", token=B["access"])
        seen0 = res.get("user", {}).get("last_seen", 0) if st == 200 else 0
        p = spawn_shot(f"{a.base}/", SHOTS / "chat-4-live.png", JS_LIVE, wait=900)
        t0 = time.time()
        while time.time() - t0 < 40:
            st, res = http("GET", f"{a.base}/api/users/{user_a}", token=B["access"])
            if st == 200 and res.get("user", {}).get("last_seen", 0) > seen0:
                print("paso5 live: WS del navegador conectado")
                break
            time.sleep(0.5)
        else:
            print("paso5 live: WARN sin confirmación de WS; rondas igual")
        time.sleep(2)   # que JS abra el chat y tome la línea base
        for i in range(5):
            if p.poll() is not None:
                break
            time.sleep(3)
            st, _ = http("POST", f"{a.base}/api/chats/{cid}/read",
                         {"seq": max_seq(a.base, B["access"], cid)}, token=B["access"])
            body = ("¡Live! Este mensaje llegó por WebSocket ⚡" if i == 0
                    else f"Live #{i + 1} ⚡ (ronda de reintento)")
            send(a.base, B["access"], cid, {"kind": "text", "body": body})
            print(f"paso5 live: ronda {i + 1} — B leyó (HTTP {st}) y escribió")
        out, err = p.communicate(timeout=180)
        js_res = None
        for line in out.splitlines():
            if line.startswith("JSRES: "):
                js_res = line[len("JSRES: "):].strip().strip('"')
        print("paso5 live:", js_res or "(sin jsres)")
        if p.returncode != 0 or not js_res or not str(js_res).startswith("OK"):
            print(out[-1500:], err[-800:])
            raise SystemExit("✗ falló la corrida live (WS)")

        print(f"✓ chat UI E2E completo → {SHOTS}/chat-1-lista.png, "
              f"chat-2-conversacion.png, chat-3-nuevo.png, chat-4-live.png")
    finally:
        if cleanup_db():
            print("  datos de prueba eliminados de la DB local")
        else:
            print("  WARN: la limpieza pudo ser incompleta")


if __name__ == "__main__":
    main()
