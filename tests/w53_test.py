#!/usr/bin/env python
"""W53: audio compatible con Mypal 78 / Windows XP.

Mypal no tiene el decodificador MP3 de WMF y responde
  "Cannot play media. No decoders for requested formats: audio/mpeg".
El servidor genera Ogg Vorbis (decodificador interno de Firefox) y, si
hasta Vorbis falla, WAV PCM.

  1. ?fmt=ogg devuelve audio/ogg real (cabecera OggS) y reproducible.
  2. ?fmt=wav devuelve audio/wav PCM (RIFF/WAVE), admite Range.
  3. En la UI, con audio/mpeg marcado como fallido, el <audio> pide
     directamente el Ogg y lo decodifica sin error.
  4. Si Ogg/Vorbis también está marcado como fallido, pide WAV PCM.

Uso: server/.venv/bin/python tests/w53_test.py [--base http://127.0.0.1:8899]
"""
import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

import chat_ui_test as ct  # noqa: E402

SHOTS = Path("/tmp/opencode")
PROFILE = Path("/tmp/opencode/ffprof")

_pass = [0]
_fail = [0]


def step(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print(f"  \u2713 {name}")
    else:
        _fail[0] += 1
        print(f"  \u2717 {name}: {detail}")


def shot(url, out, js=None, wait=400, timeout=180):
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


def get_media(url, fmt=None, headers=None):
    u = url + (("&" if "?" in url else "?") + "fmt=" + fmt if fmt else "")
    req = urllib.request.Request(u, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.headers, r.read()


def make_mp3(path):
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1.2",
         "-c:a", "libmp3lame", "-q:a", "5", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return r.returncode == 0 and path.is_file()


OPEN_CHAT_JS = """(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const wait = async (sel, ms) => {
    const t = Date.now();
    while (Date.now() - t < ms) {
      const el = document.querySelector(sel);
      if (el) return el;
      await sleep(100);
    }
    return null;
  };
  localStorage.setItem('fm.mc.audio/mpeg', '1');
  if ({ogg}) localStorage.setItem('fm.mc.audio/ogg-vorbis', '1');
  else localStorage.removeItem('fm.mc.audio/ogg-vorbis');
  const item = await wait('.chat-list .chat-item', 15000);
  if (!item) return JSON.stringify({fail: 'sin lista'});
  item.click();
  const au = await wait('.b-afile audio', 15000);
  if (!au) return JSON.stringify({fail: 'sin audio'});
  const t0 = Date.now();
  while (Date.now() - t0 < 12000 && !(au.duration > 0) && !au.error) {
    await sleep(150);
  }
  let type = '';
  try {
    const r = await fetch(au.currentSrc || au.src);
    const b = await r.blob();
    type = b.type;
  } catch (e) {}
  const frame = document.querySelector('.b-afile');
  return JSON.stringify({
    src: (au.currentSrc || au.src || '').slice(0, 24),
    type: type,
    dur: au.duration,
    err: au.error ? au.error.code : 0,
    frame: frame ? frame.className : '',
  });
})()"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8899")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)

    # El perfil fijo de shot.py puede conservar una sesión de otro test.
    shutil.rmtree(PROFILE, ignore_errors=True)

    tag = uuid.uuid4().hex[:6]
    A = ct.register(a.base, f"w53a{tag}@t.fi", f"w53a{tag}")
    B = ct.register(a.base, f"w53b{tag}@t.fi", f"w53b{tag}")

    st, g = ct.http("POST", a.base + "/api/chats/dm",
                    {"username": B["user"]["username"]}, token=A["access"])
    if st not in (200, 201):
        raise SystemExit(f"✗ crear dm: {st} {g}")
    dm = g["chat"]["id"]

    mp3 = SHOTS / "w53-voz.mp3"
    if not make_mp3(mp3):
        raise SystemExit("✗ ffmpeg no pudo generar el MP3 de prueba")
    up = ct.upload(a.base, A["access"], mp3)
    ct.send(a.base, A["access"], dm,
            {"kind": "file", "body": "", "media_id": up["id"],
             "client_msg_id": str(uuid.uuid4())})
    signed = a.base + up["url"]

    print("→ 1/2 formatos del servidor")
    st, h, ogg = get_media(signed, "ogg")
    step("?fmt=ogg → 200 audio/ogg",
         st == 200 and h.get_content_type() == "audio/ogg" and ogg[:4] == b"OggS",
         f"st={st} type={h.get('Content-Type')} head={ogg[:8]!r}")

    st, h, wav = get_media(signed, "wav")
    step("?fmt=wav → 200 audio/wav PCM",
         st == 200 and h.get_content_type() == "audio/wav" and
         wav[:4] == b"RIFF" and wav[8:12] == b"WAVE",
         f"st={st} type={h.get('Content-Type')} head={wav[:12]!r}")
    st, h, part = get_media(signed, "wav", {"Range": "bytes=0-99"})
    step("?fmt=wav admite Range (206)",
         st == 206 and len(part) == 100 and
         str(h.get("Content-Range", "")).startswith("bytes 0-99/"),
         f"st={st} range={h.get('Content-Range')}")

    print("→ 3/4 fallback de la UI")
    ok, res, log = shot(a.base + "/", SHOTS / "w53-0-sesion.png",
                        js=sess_js(A))
    step("sesión inyectada", ok and res == "sesión inyectada", log[-300:])

    ok, res, log = shot(
        a.base + "/", SHOTS / "w53-1-ogg.png", wait=800,
        js=OPEN_CHAT_JS.replace("{ogg}", "false"))
    try:
        d = json.loads(res) if res else {}
    except Exception:
        d = {}
    step("UI pide Ogg Vorbis y decodifica",
         ok and d.get("type") == "audio/ogg" and d.get("dur", 0) > 0 and
         d.get("err") == 0, f"{res} {log[-300:]}")

    ok, res, log = shot(
        a.base + "/", SHOTS / "w53-2-wav.png", wait=800,
        js=OPEN_CHAT_JS.replace("{ogg}", "true"))
    try:
        d = json.loads(res) if res else {}
    except Exception:
        d = {}
    step("UI cae a WAV PCM y decodifica",
         ok and d.get("type") == "audio/wav" and d.get("dur", 0) > 0 and
         d.get("err") == 0, f"{res} {log[-300:]}")

    # No dejar la sesión/flags en el perfil compartido de las otras suites.
    shutil.rmtree(PROFILE, ignore_errors=True)
    ct.cleanup_db()

    print(f"\nW53: {_pass[0]} bien, {_fail[0]} mal")
    sys.exit(1 if _fail[0] else 0)


if __name__ == "__main__":
    main()
