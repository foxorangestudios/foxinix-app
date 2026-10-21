"""Borrado permanente de cuentas sin verificar a los 5 días."""
from __future__ import annotations

import asyncio
import logging
import time

from . import config, db

log = logging.getLogger("foxmsg.cleanup")

CHECK_INTERVAL = 3600  # cada hora


def purge_unverified() -> int:
    """Borra cuentas creadas hace >5 días sin verificar el correo."""
    cutoff = int(time.time()) - config.VERIFY_DEADLINE_DAYS * 86400
    stale = db.rows(
        "SELECT id, email, username FROM users"
        " WHERE email_verified = 0 AND created_at < ?",
        (cutoff,),
    )
    if not stale:
        return 0
    removed: list[tuple[str, int]] = []
    with db.tx() as conn:
        for u in stale:
            # W45: una cuenta sin verificar puede haber subido avatar/foto
            # antes de abandonar. Antes se borraba la fila pero el archivo
            # quedaba para siempre en MEDIA_DIR.
            for m in conn.execute(
                "SELECT path, size FROM media WHERE owner_id = ?", (u["id"],)
            ).fetchall():
                removed.append((m[0], int(m[1] or 0)))
            conn.execute("DELETE FROM media WHERE owner_id = ?", (u["id"],))
            # cascada: email_codes y chat_members por FK; chats vacíos se
            # limpian abajo.
            conn.execute("DELETE FROM users WHERE id = ?", (u["id"],))
            conn.execute(
                "DELETE FROM chats WHERE id NOT IN"
                " (SELECT DISTINCT chat_id FROM chat_members)"
            )
    from .routers import media as media_mod   # perezoso: evita ciclos
    for rel, size in removed:
        try:
            media_mod.remove_media_files(config.MEDIA_DIR / rel)
            media_mod.note_media_size(-size)
        except OSError:
            pass
    log.warning("Borradas %d cuentas sin verificar: %s", len(stale),
                [u["username"] for u in stale])
    return len(stale)


async def cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(purge_unverified)
        except Exception:
            log.exception("error en purge_unverified")
        await asyncio.sleep(CHECK_INTERVAL)
