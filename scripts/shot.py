#!/usr/bin/env python3
"""Screenshot de páginas web vía WebDriver BiDi (Firefox headless).

Uso:
  server/.venv/bin/python scripts/shot.py <url> <out.png> [--eval 'js'] [--wait 300]
  server/.venv/bin/python scripts/shot.py <url> <out.png> --js 'js'   # ejecuta y espera
  server/.venv/bin/python scripts/shot.py <url> <out.png> --width 390 --height 844 --viewport

Espera a que la app quede "ready" (sin el estado .boot), captura e imprime
los errores de JS registrados (log.entryAdded level=error).
Requiere: firefox en PATH y `websockets` (venv del server/client).
"""
import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

import websockets

PORT = 9333
PROFILE = "/tmp/opencode/ffprof"
READY_JS = (
    "document.readyState === 'complete' && "
    "document.querySelector('#app') && document.querySelector('#app').firstElementChild && "
    "!document.querySelector('.boot')"
)


def launch_firefox(width, height):
    os.makedirs(PROFILE, exist_ok=True)
    # El micrófono falso para E2E de voz no es un flag de Firefox sino prefs
    # en <PROFILE>/user.js (media.navigator.*): se reescriben en CADA arranque
    # para no depender de un archivo suelto (si se pierde, la voz deja de
    # funcionar y getUserMedia se cuelga en headless sin backend de audio).
    with open(os.path.join(PROFILE, "user.js"), "w") as f:
        f.write(
            'user_pref("media.navigator.streams.fake", true);\n'
            'user_pref("media.navigator.permission.disabled", true);\n'
        )
    return subprocess.Popen(
        [
            "firefox", "--headless", "--profile", PROFILE, "-no-remote",
            f"--remote-debugging-port={PORT}",
            f"--window-size={width},{height}", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def find_ws_url(timeout=15.0):
    """Firefox anuncia 'WebDriver BiDi listening on ws://127.0.0.1:PORT',
    pero el handshake real ocurre en /session (GET / devuelve httpd.js 200)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = __import__("socket").create_connection(("127.0.0.1", PORT), 1)
            s.close()
            return f"ws://127.0.0.1:{PORT}/session"
        except OSError:
            time.sleep(0.2)
    return f"ws://127.0.0.1:{PORT}/session"


class BiDi:
    def __init__(self, ws):
        self.ws = ws
        self.mid = 0
        self.logs = []

    async def send(self, method, params=None):
        self.mid += 1
        wid = self.mid
        await self.ws.send(json.dumps({"id": wid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.recv())
            if msg.get("id") == wid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {json.dumps(msg['error'])[:300]}")
                return msg.get("result", {})
            self._note(msg)

    async def recv(self):
        return await self.ws.recv()

    def _note(self, msg):
        if msg.get("method") == "log.entryAdded":
            p = msg.get("params", {}) or {}
            # Firefox envía la entrada DIRECTO en params (sin anidar "entry")
            # y usa "method" (log/warn/error) como nivel, con el texto en "text"
            # o en "args" (spec LogEntry admite ambas formas).
            e = p.get("entry", p)
            lvl = e.get("level") or e.get("method") or ""
            if lvl in ("error", "warning", "warn"):
                text = e.get("text")
                if not text:
                    text = " ".join(
                        str((a or {}).get("value", a)) for a in (e.get("args") or [])
                    )
                self.logs.append(f"[{lvl}] {text}")
        elif msg.get("method", "").endswith("exception"):  # por si acaso
            self.logs.append(json.dumps(msg.get("params", {}))[:300])

    async def events_until(self, timeout, pred=None):
        """Barría eventos hasta timeout, opcionalmente corta con pred(result)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.recv(), max(0.05, deadline - time.time()))
            except asyncio.TimeoutError:
                return None
            msg = json.loads(raw)
            if "id" in msg:
                if "error" in msg:
                    raise RuntimeError(json.dumps(msg["error"])[:300])
                if pred and pred(msg.get("result", {})):
                    return msg.get("result")
                continue
            self._note(msg)

    async def evaluate(self, ctx, expr, await_promise=False):
        r = await self.send("script.evaluate", {
            "expression": expr,
            "target": {"context": ctx},
            "awaitPromise": await_promise,
            "resultOwnership": "none",
        })
        # Éxito: {realm, type:'success', result:{type, value/description}}
        # Error:  {realm, type:'exception', exceptionDetails:{text, ...}}  ← SIN "result"
        if r.get("type") == "exception":
            desc = (r.get("exceptionDetails") or {}).get("text") or "excepción"
            return f"__EXC__ {desc}"
        res = r.get("result", {})
        if "value" in res:
            return res["value"]
        return res.get("description")


async def run(a):
    proc = launch_firefox(a.width, a.height)
    code = 0
    b = None
    try:
        ws_url = find_ws_url()
        async with websockets.connect(
            ws_url, max_size=128 * 1024 * 1024, open_timeout=10,
        ) as raw:
            b = BiDi(raw)
            await b.send("session.new", {"capabilities": {}})
            try:
                await b.send("session.subscribe", {"events": ["log.entryAdded"]})
            except RuntimeError:
                pass

            tree = await b.send("browsingContext.getTree", {"maxDepth": 0})
            contexts = tree.get("contexts") or []
            if not contexts:
                created = await b.send("browsingContext.create", {"type": "tab"})
                ctx = created["context"]
            else:
                ctx = contexts[0]["context"]

            if a.viewport:
                try:
                    await b.send("browsingContext.setViewport", {
                        "context": ctx,
                        "viewport": {"width": a.width, "height": a.height},
                        "devicePixelRatio": 1,
                    })
                except RuntimeError as e:
                    b.logs.append(f"[shot] no se pudo fijar viewport: {e}")

            await b.send("browsingContext.navigate",
                         {"context": ctx, "url": a.url, "wait": "complete"})

            if a.js:
                # awaitPromise: los flujos de prueba suelen ser async IIFE
                js_res = await b.evaluate(ctx, a.js, True)
                if isinstance(js_res, str) and js_res.startswith("__EXC__"):
                    b.logs.append(f"[js] {js_res}")
                elif js_res is not None:
                    print("JSRES:", json.dumps(js_res, ensure_ascii=False))

            # Espera a que la app montó
            deadline = time.time() + a.timeout
            ready = False
            while time.time() < deadline:
                try:
                    ready = (await b.evaluate(ctx, READY_JS)) is True
                except RuntimeError:
                    ready = False
                if ready:
                    break
                await asyncio.sleep(0.2)
            if not ready:
                b.logs.append("[shot] la app no quedó 'ready'")
                code = 2

            if a.wait:
                await asyncio.sleep(a.wait / 1000.0)

            # W13: clic de PUNTERO REAL (input.performActions). Un gesto
            # trusted concede activación de usuario y desbloquea play()
            # (en headless la política de autoplay queda "disallowed" y
            # los prefs no la mueven: el clic real es lo único que vale).
            if a.tap:
                try:
                    # evaluate devuelve objetos como 'description' (no como
                    # dict): pedimos JSON.stringify y lo parseamos.
                    raw = await b.evaluate(
                        ctx, "window.__tap ? JSON.stringify(window.__tap) : 'null'")
                    pt = json.loads(raw) if isinstance(raw, str) else raw
                    if not isinstance(pt, dict) or "x" not in pt:
                        b.logs.append(f"[shot] --tap: no hay window.__tap ({raw!r})")
                    else:
                        await b.send("input.performActions", {
                            "context": ctx,
                            "actions": [{
                                "type": "pointer", "id": "p1",
                                "parameters": {"pointerType": "mouse"},
                                "actions": [
                                    {"type": "pointerMove", "duration": 0,
                                     "origin": "viewport",
                                     "x": int(pt["x"]), "y": int(pt["y"])},
                                    {"type": "pointerDown", "button": 0},
                                    {"type": "pause", "duration": 60},
                                    {"type": "pointerUp", "button": 0},
                                ],
                            }],
                        })
                except Exception as e:
                    b.logs.append(f"[shot] --tap falló: {e}")

            if a.eval is not None:
                print("EVAL:", json.dumps(await b.evaluate(ctx, a.eval, True),
                                          ensure_ascii=False))

            shot = None
            for params in ({"context": ctx, "format": {"type": "image/png"}},
                           {"context": ctx}):
                try:
                    shot = await b.send("browsingContext.captureScreenshot", params)
                    break
                except RuntimeError as e:
                    last_err = e
            if not shot or "data" not in shot:
                b.logs.append(f"[shot] sin datos: {str(shot or last_err)[:200]}")
                code = max(code, 3)
            else:
                with open(a.out, "wb") as f:
                    f.write(base64.b64decode(shot["data"]))
                print("SHOT:", a.out)

            # Events pendientes (errores de consola tardíos)
            await b.events_until(0.3)

            # Cierre GRACEFUL: SIGTERM perdía la cola WAL del localStorage
            # (la sesión no sobrevivía entre capturas).
            try:
                await asyncio.wait_for(b.send("browser.close"), timeout=5)
            except Exception:
                pass
    finally:
        try:
            proc.wait(timeout=8)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    for line in (b.logs if b else ["[shot] no se pudo conectar por BiDi"]):
        print("JS:", line, file=sys.stderr)
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--eval", default=None, help="expresión JS a evaluar (se imprime)")
    ap.add_argument("--js", default=None, help="JS a ejecutar antes de esperar/capturar")
    ap.add_argument("--wait", type=int, default=300, help="ms extra tras estar ready")
    ap.add_argument("--tap", action="store_true",
                    help="tras --js y --wait: clic de puntero real en "
                         "window.__tap={x,y} (gesto trusted para play())")
    ap.add_argument("--timeout", type=float, default=8.0, help="segundos máx de espera")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=860)
    ap.add_argument("--viewport", action="store_true",
                    help="usar --width/--height como viewport exacto")
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a)))


if __name__ == "__main__":
    main()
