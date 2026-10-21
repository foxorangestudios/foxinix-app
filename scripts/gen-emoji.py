#!/usr/bin/env python
"""W29b: genera server/web/js/emoji-data.js + descarga los SVG de Twemoji.

Fuentes:
  - shortcodes/descripciones/categorías: gemoji (github/gemoji, MIT)
    ya bajado a /tmp/opencode/emo/gemoji.json (npm gemoji@8.1.0).
  - imágenes: Twemoji (jdecked/twemoji, CC-BY 4.0), assets/svg por
    nombre de codepoints (U+FE0F se omite, igual que Twemoji).

Uso: server/.venv/bin/python scripts/gen-emoji.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EMO = Path("/tmp/opencode/emo")
OUT_JS = ROOT / "server/web/js/emoji-data.js"
OUT_SVG = ROOT / "server/web/emoji"
TWVER = "17.0.3"

# categoría gemoji → (id, nombre español, icono)
CATMAP = {
    "Smileys & Emotion": ("caras", "Caras y emociones", "\U0001F600"),
    "People & Body": ("gestos", "Gestos y personas", "\U0001F44D"),
    "Animals & Nature": ("naturaleza", "Naturaleza y animales", "\U0001F98A"),
    "Food & Drink": ("comida", "Comida y bebida", "\U0001F355"),
    "Travel & Places": ("viajes", "Viajes y lugares", "✈️"),
    "Activities": ("actividades", "Actividades y deportes", "⚽"),
    "Objects": ("objetos", "Objetos", "\U0001F4A1"),
    "Symbols": ("simbolos", "Símbolos", "❤️"),
    "Flags": ("banderas", "Banderas", "\U0001F3C1"),
}
ORDER = ["caras", "gestos", "naturaleza", "comida", "viajes",
         "actividades", "objetos", "simbolos", "banderas"]


def twid(s):
    """Codepoints del emoji unidos con '-' (formato de archivo Twemoji,
       sin U+FE0F)."""
    out = []
    for ch in s:
        cp = ord(ch)
        if cp == 0xFE0F:
            continue
        out.append(format(cp, "x"))
    return "-".join(out)


def js_str(s):
    return json.dumps(s, ensure_ascii=False)


def main():
    gemoji = json.loads((EMO / "gemoji.json").read_text(encoding="utf-8"))
    tw = json.loads((EMO / "tw.json").read_text(encoding="utf-8"))
    files = {
        f["name"].rsplit("/", 1)[-1][:-4]
        for f in tw["files"]
        if f["name"].startswith("/assets/svg/") and f["name"].endswith(".svg")
    }
    print(f"twemoji svg disponibles: {len(files)}")

    by_cat = {c: [] for c in ORDER}
    codes = {}
    desc = {}
    emofile = {}
    need = set()
    for e in gemoji:
        meta = CATMAP.get(e.get("category"))
        if not meta:
            continue
        ch = e.get("emoji") or ""
        if not ch:
            continue
        tid = twid(ch)
        if tid not in files:
            continue
        cat = meta[0]
        by_cat[cat].append(ch)
        emofile[ch] = tid
        need.add(tid)
        desc[ch] = (e.get("description") or "").lower()
        for n in e.get("names") or []:
            if n and n not in codes:
                codes[n] = ch
    # alias clásicos que el panel de reacciones ya usa
    codes.setdefault("+1", "\U0001F44D")
    codes.setdefault("-1", "\U0001F44E")
    codes.setdefault("thumbsup", "\U0001F44D")
    codes.setdefault("thumbsdown", "\U0001F44E")

    total = sum(len(v) for v in by_cat.values())
    print(f"emojis con imagen: {total} · shortcodes: {len(codes)}")

    js = ["/* W29b: datos de emojis — GENERADO por scripts/gen-emoji.py.",
          "   shortcodes/descripciones: gemoji (github/gemoji, MIT);",
          "   imágenes: Twemoji (jdecked/twemoji, CC-BY 4.0). */",
          ""]
    js.append("export const CATS = [")
    js.append("  { id: 'recientes', icon: '\U0001F552', name: 'Recientes', data: '' },")
    for cid in ORDER:
        icon = dict((m[0], m) for m in CATMAP.values())[cid][2]
        name = dict((m[0], m) for m in CATMAP.values())[cid][1]
        js.append("  { id: '%s', icon: %s, name: %s, data: %s }," % (
            cid, js_str(icon), js_str(name),
            js_str(" ".join(by_cat[cid]))))
    js.append("];")
    js.append("")
    js.append("export const CODES = {")
    items = sorted(codes.items())
    line = " "
    for k, v in items:
        piece = " %s: %s," % (js_str(k), js_str(v))
        if len(line) + len(piece) > 100:
            js.append(line)
            line = " "
        line += piece
    if line.strip():
        js.append(line)
    js.append("};")
    js.append("")
    js.append("export const DESC = {")
    line = " "
    for ch in sorted(emofile):
        piece = " %s: %s," % (js_str(ch), js_str(desc.get(ch, "")))
        if len(line) + len(piece) > 100:
            js.append(line)
            line = " "
        line += piece
    if line.strip():
        js.append(line)
    js.append("};")
    js.append("")
    js.append("export const EMO_FILE = {")
    line = " "
    for ch in sorted(emofile):
        piece = " %s: %s," % (js_str(ch), js_str(emofile[ch]))
        if len(line) + len(piece) > 100:
            js.append(line)
            line = " "
        line += piece
    if line.strip():
        js.append(line)
    js.append("};")
    js.append("")
    OUT_JS.write_text("\n".join(js), encoding="utf-8")
    print(f"escrito {OUT_JS.relative_to(ROOT)} "
          f"({OUT_JS.stat().st_size // 1024} KB)")

    # lista de descarga
    lst = EMO / "files.txt"
    lst.write_text("\n".join(sorted(need)) + "\n", encoding="utf-8")
    print(f"svg a bajar: {len(need)}")
    OUT_SVG.mkdir(parents=True, exist_ok=True)
    cmd = ("cd %s && xargs -P 8 -I{} curl -sfL "
           "'https://cdn.jsdelivr.net/gh/jdecked/twemoji@%s/assets/svg/{}.svg' "
           "-o '{}.svg' < %s" % (OUT_SVG, TWVER, lst))
    r = subprocess.run(["bash", "-c", cmd])
    if r.returncode != 0:
        print("algunos SVG fallaron (revisar)", file=sys.stderr)
    ok = len(list(OUT_SVG.glob("*.svg")))
    print(f"svg descargados: {ok}/{len(need)}")
    return 0 if ok >= len(need) * 0.98 else 1


# W40: imágenes de Google (Noto) — lote npm emoji-datasource-google
OUT_NOTO = ROOT / "server/web/emoji-noto"
OUT_NOTO_JS = ROOT / "server/web/js/emoji-noto-data.js"


def noto() -> int:
    """W40: genera js/emoji-noto-data.js a partir de los PNG ya
    extraídos en server/web/emoji-noto/ (emoji-datasource-google,
    MIT; arte Noto de Google, Apache-2.0). El nombre del archivo es
    el emoji en hex unido por '-' INCLUYENDO el FE0F (a diferencia
    de Twemoji, que lo omite)."""
    emofile = {}
    for png in sorted(OUT_NOTO.glob("*.png")):
        stem = png.stem                  # p. ej. "1f525" o "2764-fe0f"
        try:
            ch = "".join(chr(int(p, 16)) for p in stem.split("-"))
        except ValueError:
            continue
        if ch not in emofile:
            emofile[ch] = stem
    js = [
        "/* W40: mapa de emoji → archivo PNG de Noto (imágenes de Google,",
        "   arte de Noto Color Emoji, Apache-2.0; lote generado por",
        "   scripts/gen-emoji.py --noto desde emoji-datasource-google, MIT).",
        "   Los emojis sin archivo aquí se renderizan con la fuente del",
        "   sistema (modo reserva). GENERADO — no editar a mano. */",
        "",
        "export const EMO_FILE_NOTO = {",
    ]
    line = " "
    for ch in sorted(emofile):
        piece = " %s: %s," % (js_str(ch), js_str(emofile[ch]))
        if len(line) + len(piece) > 100:
            js.append(line)
            line = " "
        line += piece
    if line.strip():
        js.append(line)
    js.append("};")
    js.append("")
    OUT_NOTO_JS.write_text("\n".join(js), encoding="utf-8")
    print("escrito %s (%d KB, %d emojis)"
          % (OUT_NOTO_JS.relative_to(ROOT),
             OUT_NOTO_JS.stat().st_size // 1024, len(emofile)))
    return 0


if __name__ == "__main__":
    if "--noto" in sys.argv:
        sys.exit(noto())
    sys.exit(main())
