#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Elimina un usuario de la base de Foxinix (moderación).

Borra en orden seguro (claves foráneas):
  - DMs de 2 miembros donde participa (chats enteros: mensajes y
    reacciones caen por CASCADE) y chats donde es el único miembro.
  - Sus media (filas + archivos en disco).
  - Sus mensajes restantes (grupos u otros chats), reacciones,
    membresías, códigos de verificación y la fila del usuario.
Los grupos que quedan sin él sobreviven (se elimina solo su membresía;
las menciones a sus mensajes quedan como "reply_to = NULL").

Uso:
  python3 del_user.py <username> <ruta/db> [--dry]

--dry solo informa lo que se borraría (no escribe nada).
"""
import os
import sqlite3
import sys


def main():
    args = [a for a in sys.argv[1:] if a != "--dry"]
    dry = "--dry" in sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    username, db = args
    if not os.path.isfile(db):
        print(f"✗ no existe la base: {db}")
        return 1

    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()

    row = cur.execute(
        "SELECT id, username, display_name FROM users WHERE username = ?",
        (username,)).fetchone()
    if not row:
        print(f"· el usuario '{username}' no existe (¿ya borrado?)")
        con.close()
        return 0
    uid = row[0]
    print(f"→ usuario: {row[1]} (id={uid}, nombre={row[2] or '-'})")

    # chats que mueren enteros: DMs de 2 miembros y chats donde es el
    # único miembro (los grupos de 2+ sobreviven, solo sale su membresía)
    dead = [r[0] for r in cur.execute("""
        SELECT cm.chat_id FROM chat_members cm
        JOIN chats c ON c.id = cm.chat_id
        WHERE cm.user_id = ?
          AND ((c.type = 'dm' AND (SELECT COUNT(*) FROM chat_members x
                                   WHERE x.chat_id = cm.chat_id) = 2)
            OR (SELECT COUNT(*) FROM chat_members x
                WHERE x.chat_id = cm.chat_id) = 1)
    """, (uid,))]
    n_msgs_dead = 0
    for cid in dead:
        n_msgs_dead += cur.execute(
            "SELECT COUNT(*) FROM messages WHERE chat_id = ?", (cid,)).fetchone()[0]
    n_msgs = cur.execute(
        "SELECT COUNT(*) FROM messages WHERE sender_id = ?", (uid,)).fetchone()[0]
    n_media = cur.execute(
        "SELECT COUNT(*) FROM media WHERE owner_id = ?", (uid,)).fetchone()[0]
    paths = [r[0] for r in cur.execute(
        "SELECT path FROM media WHERE owner_id = ?", (uid,))]
    n_chats = len(dead)
    n_groups = cur.execute("""
        SELECT COUNT(*) FROM chat_members cm
        WHERE cm.user_id = ?
          AND (SELECT COUNT(*) FROM chat_members x
               WHERE x.chat_id = cm.chat_id) > 2
    """, (uid,)).fetchone()[0]

    print(f"  · {n_chats} chats enteros ({n_msgs_dead} mensajes) — "
          f"DMs/grupos de 1")
    print(f"  · {n_msgs} mensajes sueltos en otros chats")
    print(f"  · {n_media} media ({len(paths)} archivos en disco)")
    print(f"  · {n_groups} grupos donde solo se va su membresía")

    if dry:
        print("· --dry: no se escribió nada")
        con.close()
        return 0

    for cid in dead:
        cur.execute("DELETE FROM chats WHERE id = ?", (cid,))
    cur.execute("DELETE FROM media WHERE owner_id = ?", (uid,))
    cur.execute("DELETE FROM messages WHERE sender_id = ?", (uid,))
    cur.execute("DELETE FROM reactions WHERE user_id = ?", (uid,))
    cur.execute("DELETE FROM chat_members WHERE user_id = ?", (uid,))
    cur.execute("DELETE FROM email_codes WHERE user_id = ?", (uid,))
    cur.execute("DELETE FROM users WHERE id = ?", (uid,))
    con.commit()
    con.close()

    media_dir = os.path.join(os.path.dirname(db), "media")
    okf = 0
    for p in paths:
        try:
            os.unlink(os.path.join(media_dir, p))
            okf += 1
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"  ! archivo {p}: {e}")
    print(f"✓ usuario id={uid} eliminado (archivos borrados: {okf}/{len(paths)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
