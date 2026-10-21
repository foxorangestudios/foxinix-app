#!/usr/bin/env python3
"""W28g: genera los GIF animados de la biblioteca del chat.

    server/.venv/bin/python scripts/gen-gifs.py

Escribe server/web/gifs/*.gif (128x128, bucle infinito). El cliente los
lista en la pestaña "GIFs" y los envía por el flujo normal de media
(image/gif viaja tal cual: media.py NO los convierte a WebP).
"""
from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw

SIZE = 128
BG = (246, 247, 249)
OUT = pathlib.Path(__file__).resolve().parent.parent / "server" / "web" / "gifs"


def canvas():
    im = Image.new("RGB", (SIZE, SIZE), BG)
    return im, ImageDraw.Draw(im)


def save(name: str, frames: list[Image.Image], duration: int = 90) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT / name, save_all=True, append_images=frames[1:],
        duration=duration, loop=0, optimize=True,
    )
    print(f"  · {name} ({len(frames)} fotogramas)")


def heart_points(scale: float, cx: float, cy: float) -> list[tuple[float, float]]:
    pts = []
    for i in range(48):
        t = i * 2 * math.pi / 48
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * scale, cy - y * scale))
    return pts


def star_points(cx: float, cy: float, r: float, rot: float) -> list[tuple[float, float]]:
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.42
        a = rot + i * math.pi / 5 - math.pi / 2
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    return pts


def gif_heart_pulse() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        s = 1.0 + 0.16 * abs(math.sin(f * math.pi / 6))
        d.polygon(heart_points(2.6 * s, 64, 62), fill=(230, 55, 90))
        frames.append(im)
    save("heart-pulse.gif", frames, 100)


def gif_ball_bounce() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        t = f / 11
        y = 26 + (1 - abs(1 - 2 * t)) ** 1.4 * 62   # parábola de rebote
        sq = 1.0
        r = 22.0
        if y > 96:                                   # aplastado al chocar
            sq, r = 0.55, 26.0
        d.ellipse((64 - r, y - r * sq, 64 + r, y + r * sq), fill=(52, 120, 246))
        d.ellipse((64 - r * 0.32, y - r * sq * 0.8, 64 - r * 0.05, y - r * sq * 0.45),
                  fill=(160, 200, 255))
        frames.append(im)
    save("ball-bounce.gif", frames)


def gif_star_spin() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        d.polygon(star_points(64, 64, 46, f * math.pi / 6), fill=(255, 196, 32))
        d.polygon(star_points(64, 64, 24, f * math.pi / 6 + math.pi / 10),
                  fill=(255, 226, 120))
        frames.append(im)
    save("star-spin.gif", frames)


def gif_smiley_wink() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        d.ellipse((14, 14, 114, 114), fill=(255, 208, 48), outline=(226, 176, 20), width=3)
        wink = 5 <= f <= 6
        if wink:                                     # parpadea con el ojo izquierdo
            d.line((38, 52, 54, 52), fill=(60, 44, 10), width=5)
        else:
            d.ellipse((40, 42, 54, 58), fill=(60, 44, 10))
        d.ellipse((74, 42, 88, 58), fill=(60, 44, 10))
        d.arc((40, 58, 90, 96), 20, 160, fill=(60, 44, 10), width=6)
        frames.append(im)
    save("smiley-wink.gif", frames)


def gif_fire() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        w = 1.0 + 0.12 * math.sin(f * 1.7)
        h = 1.0 + 0.18 * math.cos(f * 1.3)
        d.polygon([(64, 18 + (1 - h) * 14), (96, 66), (64, 112), (32, 66)],
                  fill=(255, 120, 24))
        d.polygon([(64, 44 + (1 - w) * 12), (84, 74), (64, 104), (44, 74)],
                  fill=(255, 196, 40))
        frames.append(im)
    save("fire.gif", frames)


def gif_sparkle() -> None:
    spots = [(34, 36), (92, 44), (60, 76), (96, 96), (30, 96)]
    frames = []
    for f in range(12):
        im, d = canvas()
        for i, (x, y) in enumerate(spots):
            phase = (f + i * 3) % 12
            r = 4 + 10 * math.sin(phase * math.pi / 6) ** 2
            if r > 5:
                d.polygon(star_points(x, y, r, 0), fill=(120, 90, 240))
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(255, 255, 255))
        frames.append(im)
    save("sparkle.gif", frames)


def gif_confetti() -> None:
    cols = [(230, 55, 90), (52, 120, 246), (255, 196, 32), (60, 180, 120), (160, 80, 220)]
    seeds = [(i * 23 % 118 + 5, i * 41 % 118 + 5, cols[i % 5]) for i in range(9)]
    frames = []
    for f in range(12):
        im, d = canvas()
        for i, (x0, y0, col) in enumerate(seeds):
            y = (y0 + f * 11) % 126
            x = x0 + 7 * math.sin((f + i) * 0.8)
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=col)
        frames.append(im)
    save("confetti.gif", frames)


def gif_loader() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        d.ellipse((24, 24, 104, 104), outline=(214, 218, 226), width=9)
        start = f * 30
        d.arc((24, 24, 104, 104), start, start + 100, fill=(52, 120, 246), width=9)
        frames.append(im)
    save("loader.gif", frames)


def gif_boom_ring() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        t = f / 11
        r = 12 + t * 46
        col = int(246 - t * 130)
        col = max(col, 60)
        d.ellipse((64 - r, 64 - r, 64 + r, 64 + r), outline=(col, col, col), width=9)
        if f < 5:
            d.ellipse((52, 52, 76, 76), fill=(255, 196, 32))
        frames.append(im)
    save("boom-ring.gif", frames)


def gif_clock_spin() -> None:
    frames = []
    for f in range(12):
        im, d = canvas()
        d.ellipse((16, 16, 112, 112), fill=(255, 255, 255), outline=(70, 76, 92), width=5)
        a = f * 30
        rad = math.radians(a - 90)
        d.line((64, 64, 64 + 36 * math.cos(rad), 64 + 36 * math.sin(rad)),
               fill=(70, 76, 92), width=6)
        d.ellipse((58, 58, 70, 70), fill=(230, 55, 90))
        frames.append(im)
    save("clock-spin.gif", frames)


def main() -> None:
    print("W28g: generando GIFs en", OUT)
    gif_heart_pulse()
    gif_ball_bounce()
    gif_star_spin()
    gif_smiley_wink()
    gif_fire()
    gif_sparkle()
    gif_confetti()
    gif_loader()
    gif_boom_ring()
    gif_clock_spin()
    total = sum(p.stat().st_size for p in OUT.glob("*.gif"))
    print(f"listo: {len(list(OUT.glob('*.gif')))} GIF, {total // 1024} KB")


if __name__ == "__main__":
    main()
