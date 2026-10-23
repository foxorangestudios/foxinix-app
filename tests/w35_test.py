#!/usr/bin/env python
"""E2E W35: enlaces en el texto, imágenes inline y tarjetas de portada.

Siembra A y B (DM) y maneja Firefox headless (BiDi via scripts/shot.py):

  1. un link https://… en el mensaje se pinta como <a class="msglink">
     y mailto:… también; javascript:/data:/js: NO se enlazan (quedan
     como texto)
  2. una URL con extensión de imagen (.svg/.png/.gif/…) se pinta como
     <img class="linkimg"> inline dentro del texto
  3. un link a página local (http://127.0.0.1:8899/) dispara el unfurl
     del server y aparece la tarjeta .linkcard con el título del sitio
  4. un GIF animado subido como adjunto se conserva ANIMADO en el
     servidor (n_frames > 1 servido) y su URL pegada en el texto se
     pinta como <img> que termina cargando (naturalWidth > 0)
  5. el endpoint /api/link-preview: página → type=page + título; una
     imagen → type=image; ftp/javascript → 400; sin token → 401

Uso: server/.venv/bin/python tests/w35_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
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
        print(f"  \u2713 {name}")
    else:
        _fail[0] += 1
        print(f"  \u2717 {name}: {detail}")


def shot(url, out, js=None, wait=400, timeout=150):
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
  };"""

JS_OPEN = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it = await wait('.chat-list .chat-item', 8000);
  if (!it) return 'FAIL: sin lista de chats';
  it.click();
  const msgs = await wait('.msgs .msg', 8000);
  if (!msgs) return 'FAIL: no abrió el chat';
  return 'OK';
})()"""

JS_LINKS = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it0 = await wait('.chat-list .chat-item', 8000);
  if (!it0) return 'FAIL: sin lista de chats';
  it0.click();
  if (!await wait('.msgs .msg', 8000)) return 'FAIL: no abrió el chat';
  const tl = await wait('.msgs a.msglink[href="https://example.com/pagina"]', 8000);
  const ml = document.querySelector('.msgs a.msglink[href^="mailto:"]');
  const jsA = document.querySelectorAll('.msgs a[href*="javascript"], ' +
    '.msgs a[href*="data:"], .msgs a[href^="js:"]').length;
  const texts = (document.querySelector('.msgs') || {}).textContent || '';
  return JSON.stringify({
    https: !!tl,
    httpsText: tl ? tl.textContent : '',
    mailto: ml ? ml.getAttribute('href') : '',
    jsAnchors: jsA,
    jsKept: texts.indexOf('javascript://alert(1)') >= 0 &&
            texts.indexOf('javascript:alert(2)') >= 0,
  });
})()"""

JS_IMG = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it0 = await wait('.chat-list .chat-item', 8000);
  if (!it0) return 'FAIL: sin lista de chats';
  it0.click();
  if (!await wait('.msgs .msg', 8000)) return 'FAIL: no abrió el chat';
  const im = await wait('.msgs .b-text img.linkimg[src*="icon.svg"]', 8000);
  let loaded = false;
  if (im) {
    const t0 = Date.now();
    while (Date.now() - t0 < 6000) {
      if (im.complete && im.naturalWidth > 0) { loaded = true; break; }
      await sleep(150);
    }
  }
  return JSON.stringify({
    img: !!im,
    loaded: loaded,
    href: im && im.parentNode ? im.parentNode.getAttribute('href') : '',
  });
})()"""

JS_CARD = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it0 = await wait('.chat-list .chat-item', 8000);
  if (!it0) return 'FAIL: sin lista de chats';
  it0.click();
  if (!await wait('.msgs .msg', 8000)) return 'FAIL: no abrió el chat';
  const card = await wait('.msgs .linkcard', 12000);
  const title = card && card.querySelector('.lc-title')
    ? card.querySelector('.lc-title').textContent : '';
  const site = card && card.querySelector('.lc-site')
    ? card.querySelector('.lc-site').textContent : '';
  return JSON.stringify({
    card: !!card,
    title: title,
    site: site,
    href: card ? card.getAttribute('href') : '',
  });
})()"""

JS_MEDIA = """(async () => {
  """ + W_WAIT + """
  let tb = Date.now();
  while (Date.now() - tb < 12000 && __fm.store.booting) await sleep(120);
  const it0 = await wait('.chat-list .chat-item', 8000);
  if (!it0) return 'FAIL: sin lista de chats';
  it0.click();
  if (!await wait('.msgs .msg', 8000)) return 'FAIL: no abrió el chat';
  const im = await wait('.msgs .b-text img.linkimg[src*="/media/file/"]', 8000);
  let loaded = false;
  if (im) {
    const t0 = Date.now();
    while (Date.now() - t0 < 6000) {
      if (im.complete && im.naturalWidth > 0) { loaded = true; break; }
      await sleep(150);
    }
  }
  return JSON.stringify({
    img: !!im,
    loaded: loaded,
    src: im ? im.getAttribute('src') : '',
  });
})()"""


def djson(res, default=None):
    try:
        return json.loads(res)
    except Exception:
        return default or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w35a{tag}@t.fi", f"w35a{tag}")
    B = ct.register(a.base, f"w35b{tag}@t.fi", f"w35b{tag}")
    print(f"· usuarios A={A['user']['username']} B={B['user']['username']}")

    st, g = ct.dm_between(a.base, A["access"], B["access"],
                          A["user"]["username"], B["user"]["username"])
    if st not in (200, 201):
        raise SystemExit(f"✗ crear dm: {st} {g}")
    dm = g["chat"]["id"]

    # ============ 5. endpoint /api/link-preview (sin navegador) ======
    print("→ paso5 API unfurl")
    st, prev = ct.http("POST", a.base + "/api/link-preview",
                       {"url": a.base + "/"}, token=A["access"])
    step("unfurl página local → type=page título 'Foxinix'",
         st == 200 and prev.get("type") == "page" and "Foxinix" in (prev.get("title") or ""),
         f"st={st} res={prev}")
    st, prev2 = ct.http("POST", a.base + "/api/link-preview",
                        {"url": a.base + "/static/icon.svg"}, token=A["access"])
    step("unfurl imagen → type=image",
         st == 200 and prev2.get("type") == "image" and
         (prev2.get("url") or "").endswith("icon.svg"),
         f"st={st} res={prev2}")
    st, _ = ct.http("POST", a.base + "/api/link-preview",
                    {"url": "ftp://example.com/archivo"}, token=A["access"])
    step("unfurl ftp → 400", st == 400, f"st={st}")
    st, _ = ct.http("POST", a.base + "/api/link-preview",
                    {"url": "javascript://alert(1)"}, token=A["access"])
    step("unfurl javascript: → 400", st == 400, f"st={st}")
    st, _ = ct.http("POST", a.base + "/api/link-preview", {"url": a.base + "/"})
    step("unfurl sin token → 401", st == 401, f"st={st}")

    # ============ 4. GIF animado conservado ==========================
    print("→ paso4 gif animado")
    try:
        from PIL import Image
        f1 = Image.new("RGBA", (24, 24), (255, 0, 0, 255))
        f2 = Image.new("RGBA", (24, 24), (0, 255, 0, 255))
        gif = SHOTS / "w35-anim.gif"
        f1.save(gif, "GIF", save_all=True, append_images=[f2],
                duration=200, loop=0)
        up = ct.upload(a.base, A["access"], gif)
        with urllib.request.urlopen(a.base + up["url"]) as r:
            data = r.read()
        import io
        im = Image.open(io.BytesIO(data))
        n = getattr(im, "n_frames", 1)
        step("gif animado conservado en el servidor (n_frames>1)",
             up["mime"] == "image/gif" and n > 1,
             f"mime={up['mime']} n_frames={n}")
    except Exception as e:
        step("gif animado conservado en el servidor (n_frames>1)", False, f"ex={e}")
        up = None

    # ============ siembra de mensajes ================================
    print("→ siembra de mensajes con enlaces")
    ct.send(a.base, A["access"], dm,
            {"body": "Mira https://example.com/pagina y escribe a "
                     "mailto:alguien@ejemplo.com por favor",
             "client_msg_id": str(uuid.uuid4())})
    ct.send(a.base, A["access"], dm,
            {"body": "javascript://alert(1) ni javascript:alert(2) "
                     "ni data:text/html,<h1>x</h1>",
             "client_msg_id": str(uuid.uuid4())})
    ct.send(a.base, A["access"], dm,
            {"body": "imagen: http://127.0.0.1:8899/static/icon.svg fin",
             "client_msg_id": str(uuid.uuid4())})
    ct.send(a.base, A["access"], dm,
            {"body": "portada: http://127.0.0.1:8899/ fin",
             "client_msg_id": str(uuid.uuid4())})
    if up:
        ct.send(a.base, A["access"], dm,
                {"body": "gif: " + a.base + up["url"] + " fin",
                 "client_msg_id": str(uuid.uuid4())})

    # ============ sesión de A en el navegador ========================
    ok, res, log = shot(a.base + "/", SHOTS / "w35-0-injectar.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    ok, res, log = shot(a.base + "/", SHOTS / "w35-1-abrir.png", js=JS_OPEN)
    step("chat abierto", ok and res == "OK", f"res={res!r} log={log[-200:]}")

    # ============ 1. links https/mailto + sin javascript =============
    print("→ paso1 links en el texto")
    ok, res, log = shot(a.base + "/", SHOTS / "w35-2-links.png", js=JS_LINKS)
    d = djson(res)
    step("link https como <a class=msglink>",
         ok and d.get("https") and d.get("httpsText") == "https://example.com/pagina",
         f"res={res!r} log={log[-200:]}")
    step("mailto enlazado", d.get("mailto", "").startswith("mailto:"),
         f"res={res!r}")
    step("javascript:/data: NO se enlazan y quedan como texto",
         d.get("jsAnchors") == 0 and d.get("jsKept"), f"res={res!r}")

    # ============ 2. imagen inline por extensión =====================
    print("→ paso2 imagen inline")
    ok, res, log = shot(a.base + "/", SHOTS / "w35-3-img.png", js=JS_IMG)
    d = djson(res)
    step("URL de imagen → <img class=linkimg> cargada",
         ok and d.get("img") and d.get("loaded") and
         d.get("href") == "http://127.0.0.1:8899/static/icon.svg",
         f"res={res!r} log={log[-200:]}")

    # ============ 3. tarjeta de portada ==============================
    print("→ paso3 tarjeta de portada")
    ok, res, log = shot(a.base + "/", SHOTS / "w35-4-card.png", js=JS_CARD)
    d = djson(res)
    step("tarjeta .linkcard con el título del sitio",
         ok and d.get("card") and "Foxinix" in (d.get("title") or "") and
         d.get("href", "").startswith("http://127.0.0.1:8899"),
         f"res={res!r} log={log[-200:]}")

    # ============ 4b. la URL del gif en el texto =====================
    if up:
        print("→ paso4b gif pegado en el texto")
        ok, res, log = shot(a.base + "/", SHOTS / "w35-5-gif.png", js=JS_MEDIA)
        d = djson(res)
        step("URL del gif en texto → <img> cargada",
             ok and d.get("img") and d.get("loaded") and "/media/file/" in d.get("src", ""),
             f"res={res!r} log={log[-200:]}")

    print(f"\nW35: {_pass[0]} ok, {_fail[0]} fallos")
    ct.cleanup_db()
    sys.exit(0 if _fail[0] == 0 else 1)


if __name__ == "__main__":
    main()
