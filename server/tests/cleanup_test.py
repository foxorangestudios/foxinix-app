#!/usr/bin/env python3
"""Test de purge: cuenta sin verificar creada hace 6 días debe borrarse."""
import sys
import time

sys.path.insert(0, ".")
from app import cleanup, db, security  # noqa: E402


def main() -> int:
    db.init_db()
    now = int(time.time())
    old = now - 6 * 86400

    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, username, password_hash, created_at)"
            " VALUES ('vieja@test.com', 'vieja', ?, ?)",
            (security.hash_password("x" * 10), old),
        )
        stale_id = cur.lastrowid
        cur2 = conn.execute(
            "INSERT INTO users (email, username, password_hash, created_at)"
            " VALUES ('nueva@test.com', 'nueva', ?, ?)",
            (security.hash_password("x" * 10), now),
        )
        fresh_id = cur2.lastrowid

    purged = cleanup.purge_unverified()
    stale = db.one("SELECT * FROM users WHERE id = ?", (stale_id,))
    fresh = db.one("SELECT * FROM users WHERE id = ?", (fresh_id,))

    assert purged >= 1, f"purge no borró nada ({purged})"
    assert stale is None, "la cuenta vieja sigue viva"
    assert fresh is not None, "la cuenta nueva se borró por mistake"
    print(f"purge borró {purged} cuentas; vieja=borrada nueva=intacta OK")

    # limpiar la cuenta nueva de prueba
    db.execute("DELETE FROM users WHERE id = ?", (fresh_id,))
    print("=== CLEANUP TEST OK ===")
    return 0


sys.exit(main())
