"""Borrado permanente de cuentas sin verificar a los 5 días."""
from __future__ import annotations

import asyncio
import logging
import time

from . import config, db

log = logging.getLogger("foxmsg.cleanup")

CHECK_INTERVAL = 3600  # cada hora


def _reassign_group_owner(conn, chat_id: int, leaving_uid: int) -> None:
    """Si el que se va era owner, pasa la propiedad al admin/miembro más
    antiguo. Sin esto un grupo podía quedar sin nadie que lo administre."""
    row = conn.execute(
        "SELECT role FROM chat_members WHERE chat_id = ? AND user_id = ?",
        (chat_id, leaving_uid),
    ).fetchone()
    if not row or row["role"] != "owner":
        return
    nxt = conn.execute(
        "SELECT user_id FROM chat_members"
        " WHERE chat_id = ? AND user_id != ?"
        " ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, joined_at, user_id"
        " LIMIT 1",
        (chat_id, leaving_uid),
    ).fetchone()
    if nxt:
        conn.execute(
            "UPDATE chat_members SET role = 'owner'"
            " WHERE chat_id = ? AND user_id = ?",
            (chat_id, nxt["user_id"]),
        )


def prune_orphan_chats() -> int:
    """Limpia conversaciones que ya no pueden existir.

    - DMs con menos/más de dos miembros (una cuenta eliminada o datos
      viejos dejan un "Usuario eliminado" que no se puede abrir).
    - Grupos sin ningún miembro.
    - Grupos cuyo owner ya no es miembro: se asigna al admin más antiguo.
    """
    changed = 0
    with db.tx() as conn:
        for row in conn.execute(
            "SELECT c.id FROM chats c LEFT JOIN chat_members m"
            " ON m.chat_id = c.id WHERE c.type = 'dm'"
            " GROUP BY c.id HAVING COUNT(m.user_id) != 2"
        ).fetchall():
            conn.execute("DELETE FROM chats WHERE id = ?", (row["id"],))
            changed += 1
        for row in conn.execute(
            "SELECT c.id FROM chats c LEFT JOIN chat_members m"
            " ON m.chat_id = c.id WHERE c.type = 'group'"
            " GROUP BY c.id HAVING COUNT(m.user_id) = 0"
        ).fetchall():
            conn.execute("DELETE FROM chats WHERE id = ?", (row["id"],))
            changed += 1
        for row in conn.execute(
            "SELECT c.id FROM chats c WHERE c.type = 'group' AND NOT EXISTS ("
            " SELECT 1 FROM chat_members m WHERE m.chat_id = c.id AND m.role = 'owner')"
        ).fetchall():
            nxt = conn.execute(
                "SELECT user_id FROM chat_members WHERE chat_id = ?"
                " ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END, joined_at, user_id"
                " LIMIT 1",
                (row["id"],),
            ).fetchone()
            if nxt:
                conn.execute(
                    "UPDATE chat_members SET role = 'owner'"
                    " WHERE chat_id = ? AND user_id = ?",
                    (row["id"], nxt["user_id"]),
                )
                changed += 1
    return changed


def prune_orphan_media(older_than: int = 86400) -> int:
    """Borra subidas que nunca llegaron a usarse (ni mensaje, ni avatar,
    ni grupo, ni GIF favorito). Se deja un día de margen para no borrar
    una subida que aún está en curso."""
    cutoff = int(time.time()) - max(3600, int(older_than))
    from .routers import media as media_mod   # perezoso: evita ciclos
    removed: list[tuple[str, int]] = []
    with db.tx() as conn:
        for m in conn.execute(
            "SELECT id, path, size FROM media WHERE created_at < ?"
            " AND NOT EXISTS (SELECT 1 FROM messages WHERE media_id = media.id)"
            " AND NOT EXISTS (SELECT 1 FROM users WHERE avatar_media_id = media.id"
            "                 OR banner_media_id = media.id)"
            " AND NOT EXISTS (SELECT 1 FROM chats WHERE avatar_media_id = media.id)"
            " AND NOT EXISTS (SELECT 1 FROM gif_favs WHERE media_id = media.id)",
            (cutoff,),
        ).fetchall():
            mid = int(m["id"])
            conn.execute("DELETE FROM media WHERE id = ?", (mid,))
            removed.append((m["path"], int(m["size"] or 0)))
    for rel, size in removed:
        try:
            media_mod.remove_media_files(config.MEDIA_DIR / rel)
            media_mod.note_media_size(-size)
        except OSError:
            pass
    if removed:
        log.info("Limpiados %d medios huérfanos", len(removed))
    return len(removed)


def purge_unverified() -> int:
    """Borra cuentas creadas hace >5 días sin verificar el correo.

    Además limpia chats huérfanos aunque no haya cuentas vencidas: el
    borrado normal de cuentas puede dejar DMs de un solo lado o grupos
    sin owner si el proceso se interrumpió.
    """
    cutoff = int(time.time()) - config.VERIFY_DEADLINE_DAYS * 86400
    stale = db.rows(
        "SELECT id, email, username FROM users"
        " WHERE email_verified = 0 AND created_at < ?",
        (cutoff,),
    )
    removed: list[tuple[str, int]] = []
    from .routers import media as media_mod   # perezoso: evita ciclos
    with db.tx() as conn:
        for u in stale:
            # Antes de borrar la cuenta, que ningún grupo quede sin owner.
            for cm in conn.execute(
                "SELECT chat_id FROM chat_members WHERE user_id = ?", (u["id"],)
            ).fetchall():
                chat = conn.execute(
                    "SELECT type FROM chats WHERE id = ?", (cm["chat_id"],)
                ).fetchone()
                if chat and chat["type"] == "group":
                    _reassign_group_owner(conn, cm["chat_id"], u["id"])
            # W45: una cuenta sin verificar puede haber subido avatar/foto
            # antes de abandonar. Se recuerdan los ids: después de borrar
            # users, owner_id queda NULL y ya no se pueden localizar.
            owned = conn.execute(
                "SELECT id, path, size FROM media WHERE owner_id = ?", (u["id"],)
            ).fetchall()
            # cascada: email_codes y chat_members por FK.
            conn.execute("DELETE FROM users WHERE id = ?", (u["id"],))
            # No borrar archivos que otros sigan usando (reenvíos, avatar
            # de grupo o GIF favorito de otra cuenta).
            for m in owned:
                mid = int(m["id"])
                if media_mod.media_in_use(conn, mid):
                    conn.execute(
                        "UPDATE media SET owner_id = NULL WHERE id = ?", (mid,)
                    )
                else:
                    conn.execute("DELETE FROM media WHERE id = ?", (mid,))
                    removed.append((m["path"], int(m["size"] or 0)))
    # Fuera de la transacción de cuentas, pero antes de borrar archivos.
    pruned = prune_orphan_chats()
    prune_orphan_media()
    for rel, size in removed:
        try:
            media_mod.remove_media_files(config.MEDIA_DIR / rel)
            media_mod.note_media_size(-size)
        except OSError:
            pass
    if stale:
        log.warning("Borradas %d cuentas sin verificar: %s", len(stale),
                    [u["username"] for u in stale])
    if pruned:
        log.info("Limpiados %d chats huérfanos", pruned)
    return len(stale)


async def cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(purge_unverified)
        except Exception:
            log.exception("error en purge_unverified")
        await asyncio.sleep(CHECK_INTERVAL)
