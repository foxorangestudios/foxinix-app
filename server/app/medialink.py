"""URLs de media con slug aleatorio y firma HMAC (W11).

Antes: `/api/media/{id}` con `?token=<JWT de la cuenta>` en la query, así
que "copiar dirección de imagen" filtraba el token entero. Ahora:

    /media/profile/{slug}.webp?exp=..&sig=..   (avatares de usuario/grupo)
    /media/file/{slug}.webm?exp=..&sig=..      (archivos de mensajes)

El slug es aleatorio de 32 hex (no adivinable) y `sig` caduca con `exp`;
el token de cuenta ya no viaja en ninguna URL. Las firmas se renuevan en
cada respuesta de la API, así que el cliente siempre recibe una fresca.
`/api/media/{id}` sigue vivo como compatibilidad con clientes viejos.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import config, db, security

TTL = config.MEDIA_URL_TTL  # vida de la firma (segundos)


def signed_url(kind: str, slug: str, ext: str) -> str:
    """URL firmada de un slug ya conocido (subida, filas en mano)."""
    exp, sig = security.sign_media(slug, TTL)
    return f"/media/{kind}/{slug}{ext}?exp={exp}&sig={sig}"


def media_url(row: dict[str, Any] | None, kind: str = "file") -> str | None:
    """URL firmada a partir de una fila de media (None si no hay fila)."""
    if not row or not row.get("slug"):
        return None
    ext = Path(row["path"]).suffix.lower()
    return signed_url(kind, row["slug"], ext)


def media_url_by_id(media_id: int | None, kind: str = "file") -> str | None:
    """URL firmada a partir del id (hace un SELECT; sin fila → None)."""
    if not media_id:
        return None
    row = db.one("SELECT * FROM media WHERE id = ?", (media_id,))
    return media_url(row, kind)
