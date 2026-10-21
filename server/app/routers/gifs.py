"""W36k: favoritos de GIFs.

Dos orígenes: la biblioteca estática (/static/gifs/<name>.gif) y los
GIFs subidos que viajan en mensajes (media_id → URL firmada fresca en
cada listado, así el favorito sigue funcionando cuando expira la firma
que trajo el mensaje original)."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db, medialink, ratelimit
from ..auth import current_user

router = APIRouter(prefix="/api/gifs", tags=["gifs"])

# Mismo criterio que main.WEB_DIR (sin importar main: ciclo de imports).
_WEB_DIR = Path(os.environ.get("FOXMSG_WEB_DIR")
                or Path(__file__).resolve().parents[2] / "web")

_GIF_RE = re.compile(r"[a-z0-9-]{1,40}\.gif")


class FavIn(BaseModel):
    media_id: int | None = None
    name: str | None = None


def _resolve(body: FavIn, user_id: int) -> tuple[int, str]:
    """Valida la entrada y devuelve (media_id, name) normalizados.

    W37f (auditoría): con media_id, el archivo debe ser del USUARIO o
    venir de un chat donde sea MIEMBRO — antes cualquier image/* ajena
    servía URL firmada de archivos privados (IDOR)."""
    if body.media_id:
        row = db.one("SELECT * FROM media WHERE id = ?", (body.media_id,))
        if not row:
            raise HTTPException(404, "GIF no encontrado")
        if not (row["mime"] or "").startswith("image/"):
            raise HTTPException(400, "Sólo se pueden marcar imágenes")
        if row["owner_id"] != user_id:
            seen = db.one(
                "SELECT 1 AS x FROM messages"
                " WHERE media_id = ? AND chat_id IN"
                " (SELECT chat_id FROM chat_members WHERE user_id = ?)"
                " LIMIT 1",
                (body.media_id, user_id),
            )
            if not seen:
                raise HTTPException(404, "GIF no encontrado")
        return row["id"], ""
    n = (body.name or "").strip().lower()
    if not _GIF_RE.fullmatch(n):
        raise HTTPException(400, "GIF no válido")
    if not (Path(_WEB_DIR) / "gifs" / n).is_file():
        raise HTTPException(404, "GIF no encontrado")
    return 0, n


@router.get("/favorites")
def list_favs(user: dict = Depends(current_user)) -> dict[str, Any]:
    """Favoritos del usuario con URLs firmadas frescas (los media)."""
    rows = db.rows(
        "SELECT * FROM gif_favs WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["media_id"]:
            m = db.one("SELECT * FROM media WHERE id = ?", (r["media_id"],))
            if not m:
                continue                      # el archivo se borró: se omite
            out.append({"media_id": r["media_id"], "name": "",
                        "url": medialink.media_url(m, "file")})
        else:
            out.append({"media_id": 0, "name": r["name"],
                        "url": "/static/gifs/" + r["name"]})
    return {"favorites": out}


@router.post("/favorites", status_code=201)
def add_fav(body: FavIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    espera = ratelimit.FAVORITES.take(user["id"])
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": espera})
    media_id, name = _resolve(body, user["id"])
    db.execute(
        "INSERT OR IGNORE INTO gif_favs (user_id, media_id, name, created_at)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], media_id, name, int(time.time())),
    )
    return {"ok": True, "media_id": media_id, "name": name}


@router.delete("/favorites")
def del_fav(body: FavIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    media_id, name = _resolve(body, user["id"])
    db.execute(
        "DELETE FROM gif_favs WHERE user_id = ? AND media_id = ? AND name = ?",
        (user["id"], media_id, name),
    )
    return {"ok": True}
