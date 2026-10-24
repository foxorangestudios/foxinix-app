"""W61: biblioteca personal de GIFs y stickers subidos.

Cada usuario puede guardar hasta 10 GIFs y 10 stickers. Los archivos
viven en `media`; esta tabla solo los ordena y limita. Un sticker/GIF
recibido en un chat se puede guardar aquí y reenviar después (el envío
de mensajes acepta media de la biblioteca propia además de la propia).
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, db, medialink
from ..auth import current_user

router = APIRouter(prefix="/api/assets", tags=["assets"])

MAX_PER_KIND = 10
_KINDS = ("gif", "sticker")


class AssetIn(BaseModel):
    kind: str
    media_id: int


def _mime(media: dict[str, Any]) -> str:
    return (media.get("mime") or "").split(";")[0].strip().lower()


def _can_use(media: dict[str, Any], user_id: int) -> bool:
    """El dueño siempre puede; un archivo recibido, si está en algún chat
    del usuario (igual que la regla de los favoritos de GIFs)."""
    if media.get("owner_id") == user_id:
        return True
    return bool(db.one(
        "SELECT 1 AS x FROM messages WHERE media_id = ? AND chat_id IN"
        " (SELECT chat_id FROM chat_members WHERE user_id = ?) LIMIT 1",
        (media["id"], user_id),
    ))


def _common() -> str:
    return (
        "SELECT a.id AS asset_id, a.kind, a.created_at AS added_at, m.*"
        " FROM user_assets a JOIN media m ON m.id = a.media_id"
        " WHERE a.user_id = ?"
    )


def _out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["asset_id"],
        "kind": row["kind"],
        "media_id": row["id"],
        "url": medialink.media_url(row, "file"),
        "mime": row["mime"],
        "name": row.get("name") or "",
        "size": row.get("size") or 0,
        "width": row.get("width"),
        "height": row.get("height"),
        "created_at": row.get("added_at") or 0,
    }


@router.get("")
def list_assets(user: dict = Depends(current_user)) -> dict[str, Any]:
    rows = db.rows(_common() + " ORDER BY a.created_at DESC, a.id DESC", (user["id"],))
    out: dict[str, list[dict[str, Any]]] = {"gifs": [], "stickers": []}
    for r in rows:
        key = "gifs" if r["kind"] == "gif" else "stickers"
        out[key].append(_out(r))
    return out


@router.post("", status_code=201)
def add_asset(body: AssetIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    kind = (body.kind or "").strip().lower()
    if kind not in _KINDS:
        raise HTTPException(400, "Tipo de archivo inválido")
    media = db.one("SELECT * FROM media WHERE id = ?", (body.media_id,))
    if not media or not _can_use(media, user["id"]):
        raise HTTPException(404, "Archivo no encontrado")
    mime = _mime(media)
    if kind == "gif":
        if mime != "image/gif":
            raise HTTPException(400, "El GIF debe ser un archivo .gif")
    else:
        if not mime.startswith("image/") or mime == "image/svg+xml":
            raise HTTPException(400, "El sticker debe ser una imagen")
    prev = db.one(
        "SELECT id FROM user_assets WHERE user_id = ? AND kind = ? AND media_id = ?",
        (user["id"], kind, media["id"]),
    )
    if not prev:
        # W61: cuenta e inserta dentro de la misma transacción. Si no, dos
        # POST simultáneos podían pasar el tope de 10.
        with db.tx() as conn:
            prev = conn.execute(
                "SELECT id FROM user_assets"
                " WHERE user_id = ? AND kind = ? AND media_id = ?",
                (user["id"], kind, media["id"]),
            ).fetchone()
            if not prev:
                count = conn.execute(
                    "SELECT COUNT(*) AS c FROM user_assets"
                    " WHERE user_id = ? AND kind = ?",
                    (user["id"], kind),
                ).fetchone()["c"]
                if int(count) >= MAX_PER_KIND:
                    raise HTTPException(
                        400,
                        ("Máximo 10 GIFs" if kind == "gif"
                         else "Máximo 10 stickers"),
                    )
                conn.execute(
                    "INSERT INTO user_assets"
                    " (user_id, kind, media_id, created_at) VALUES (?, ?, ?, ?)",
                    (user["id"], kind, media["id"], int(time.time())),
                )
    row = db.one(
        _common() + " AND a.media_id = ? AND a.kind = ? LIMIT 1",
        (user["id"], media["id"], kind),
    )
    return {"asset": _out(row) if row else None, "max": MAX_PER_KIND}


@router.delete("/{asset_id}")
def del_asset(asset_id: int, user: dict = Depends(current_user)) -> dict[str, Any]:
    row = db.one(
        "SELECT id, media_id FROM user_assets WHERE id = ? AND user_id = ?",
        (asset_id, user["id"]),
    )
    if not row:
        raise HTTPException(404, "Archivo no encontrado")
    db.execute(
        "DELETE FROM user_assets WHERE id = ? AND user_id = ?",
        (asset_id, user["id"]),
    )
    # Si el archivo ya no lo usa ningún mensaje/perfil/favorito, se borra
    # también del disco para no gastar cuota.
    from . import media as media_mod   # perezoso: evita el ciclo
    removed = None
    with db.tx() as conn:
        removed = media_mod.drop_media_if_unused(conn, row["media_id"])
    if removed:
        try:
            media_mod.remove_media_files(config.MEDIA_DIR / removed[0])
            media_mod.note_media_size(-removed[1])
        except OSError:
            pass
    return {"ok": True}
