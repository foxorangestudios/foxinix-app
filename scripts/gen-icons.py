#!/usr/bin/env python
"""W40: reemplaza las rutas del sprite de iconos por las oficiales de
Google Material Symbols (variante Outlined, estilo línea fino tipo
WhatsApp/Discord).

Fuente: google/material-design-icons (Apache-2.0). Los IDs `#i-*` del
sprite se MANTIENEN (los referencian plantillas y pruebas); solo
cambian las rutas internas y el viewBox (Material usa 0 -960 960 960).
Los iconos sin equivalente Material se quedan custom (reporte al
final). El logo de Foxinix no se toca.

Uso: python3 scripts/gen-icons.py [--check]

Descarga a /tmp/opencode/icons/ (una vez) y reescribe server/web/index.html.
"""
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "server/web/index.html"
CACHE = Path("/tmp/opencode/icons")

# id del sprite → nombre del símbolo Material (sufijo @variante:
# materialsymbolsoutlined por defecto; ej. star@rounded = relleno)
MAP = {
    "i-eye": "visibility",
    "i-eye-off": "visibility_off",
    "i-alert": "error",
    "i-info": "info",
    "i-check": "check",
    "i-back": "arrow_back",
    "i-plus": "add",
    "i-search": "search",
    "i-x": "close",
    "i-send": "send",
    "i-mic": "mic",
    "i-mic-off": "mic_off",
    "i-phone": "call",
    "i-phone-down": "call_end",
    "i-video": "videocam",
    "i-video-off": "videocam_off",
    "i-play": "play_arrow",
    "i-pause": "pause",
    "i-clip": "attach_file",
    "i-pin": "push_pin",
    "i-bell-off": "notifications_off",
    "i-forward": "forward",
    "i-smile": "sentiment_satisfied",
    "i-sticker": "sticker",
    "i-palette": "palette",
    "i-dots": "more_vert",
    "i-users": "group",
    "i-userplus": "person_add",
    "i-key": "key",
    "i-star": "star",
    "i-star-fill": "star@rounded",
    "i-vol": "volume_up",
    "i-mute": "volume_off",
    "i-expand": "fullscreen",
    "i-collapse": "fullscreen_exit",
    "i-user": "person",
    "i-reply": "reply",
    "i-download": "download",
    "i-refresh": "refresh",
    "i-chevron-down": "expand_more",
    "i-file": "description",
    "i-image": "image",
    "i-pencil": "edit",
    "i-check2": "done_all",
    "i-fold": "unfold_less",
    "i-unfold": "unfold_more",
    "i-clock": "schedule",
    "i-sun": "light_mode",
    "i-power": "power_settings_new",
    "i-gear": "settings",
    "i-bell": "notifications",
    "i-trash": "delete",
    "i-copy": "content_copy",
    "i-link": "link",
    "i-shield": "shield",
    "i-userminus": "person_remove",
    "i-ban": "block",
    "i-unlock": "lock_open",
    "i-pin-off": "push_pin_off",
}


def fetch(name: str) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    mat, _, variant = name.partition("@")
    if variant and not variant.startswith("materialsymbols"):
        variant = "materialsymbols" + variant
    variant = variant or "materialsymbolsoutlined"
    f = CACHE / ("%s@%s.svg" % (mat, variant))
    if f.exists() and f.stat().st_size > 100:
        return f.read_text(encoding="utf-8")
    url = ("https://raw.githubusercontent.com/google/material-design-icons/"
           "master/symbols/web/{n}/{v}/{n}_24px.svg".format(n=mat, v=variant))
    with urllib.request.urlopen(url, timeout=30) as r:
        data = r.read().decode("utf-8")
    f.write_text(data, encoding="utf-8")
    return data


def main() -> int:
    check = "--check" in sys.argv
    html = INDEX.read_text(encoding="utf-8")
    ok, kept = [], []
    for sid, mat in MAP.items():
        m = re.search(r'<symbol id="%s" viewBox="[^"]*">.*?</symbol>' % sid,
                      html, re.S)
        if not m:
            print("  ?? sin symbol %s en el sprite" % sid)
            kept.append(sid)
            continue
        try:
            svg = fetch(mat)
        except Exception as e:                      # noqa: BLE001
            print("  keep %s (sin Material '%s': %s)" % (sid, mat, e))
            kept.append(sid)
            continue
        ds = re.findall(r'<path[^>]*\bd="([^"]+)"', svg)
        vb = re.search(r'viewBox="([^"]+)"', svg)
        if not ds:
            print("  keep %s ('%s' sin paths)" % (sid, mat))
            kept.append(sid)
            continue
        body = "".join('<path d="%s"/>' % d for d in ds)
        new = ('<symbol id="%s" viewBox="%s">%s</symbol>'
               % (sid, vb.group(1) if vb else "0 0 24 24", body))
        if not check:
            html = html[:m.start()] + new + html[m.end():]
        ok.append("%s=%s" % (sid, mat))
    if not check:
        INDEX.write_text(html, encoding="utf-8")
    print("Material Symbols Outlined: %d iconos, %d custom: %s"
          % (len(ok), len(kept), ", ".join(kept) if kept else "ninguno"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
