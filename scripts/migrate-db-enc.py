#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migra la DB Foxinix de SQLite plano a SQLCipher (cifrado en reposo).

Se ejecuta EN el host, con el servicio DETENIDO y la clave en el entorno:

  FOXMSG_DB_KEY=<hex> .venv/bin/python migrate-db-enc.py data/foxmsg.db data/foxmsg.db.enc

Pasos: sqlcipher_export (migración documentada de SQLCipher) → verificación
(conteos iguales + PRAGMA cipher_version + encabezado ilegible) → swap
(el original queda como <src>.plain.bak) → FOXMSG_DB_KEY agregado al .env.

Modo verificación (post-corte, servicio corriendo):

  FOXMSG_DB_KEY=<hex> .venv/bin/python migrate-db-enc.py --verify data/foxmsg.db
"""
import os
import sys

try:
    from sqlcipher3 import dbapi2 as sql
except ImportError:                       # alternativa válida del mismo API
    from pysqlcipher3 import dbapi2 as sql

TABLAS = ("users", "chats", "chat_members", "messages", "reactions", "media")


def counts(con):
    return {t: con.execute("SELECT count(*) FROM %s" % t).fetchone()[0]
            for t in TABLAS}


def verify(path, key):
    con = sql.connect(path, timeout=15)
    con.execute("PRAGMA key = '%s'" % key.replace("'", "''"))
    ver = con.execute("PRAGMA cipher_version").fetchone()
    if not ver or not ver[0]:
        print("✗ cipher_version vacío: el driver NO es SQLCipher")
        return 1
    print("  cipher_version:", ver[0])
    print("  conteos:", counts(con))
    con.close()
    bad = sql.connect(path, timeout=15)
    bad.execute("PRAGMA key = 'clave-mala'")
    try:
        bad.execute("SELECT count(*) FROM users").fetchone()
        print("✗ la clave mala NO fue rechazada")
        return 1
    except sql.DatabaseError:
        print("✓ clave mala rechazada")
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    key = os.environ.get("FOXMSG_DB_KEY", "").strip()
    if not key:
        print("✗ falta FOXMSG_DB_KEY en el entorno")
        return 1

    if "--verify" in sys.argv[1:]:
        if len(args) != 1:
            print(__doc__)
            return 2
        return verify(args[0], key)

    if len(args) != 2:
        print(__doc__)
        return 2
    src, dst = args
    if not os.path.isfile(src):
        print("✗ no existe el origen: %s" % src)
        return 1
    if os.path.exists(dst):
        print("✗ ya existe el destino: %s (borralo o elegí otro)" % dst)
        return 1

    plain = sql.connect(src, timeout=15)
    try:
        c0 = counts(plain)
    except sql.DatabaseError as e:
        print("✗ el origen no se pudo leer como plano (¿ya cifrado?): %s" % e)
        plain.close()
        return 1
    print("→ origen claro:", c0)

    plain.execute("ATTACH DATABASE '%s' AS enc KEY '%s'"
                  % (dst.replace("'", "''"), key.replace("'", "''")))
    plain.execute("SELECT sqlcipher_export('enc')")
    plain.execute("DETACH DATABASE enc")
    plain.close()

    enc = sql.connect(dst, timeout=15)
    enc.execute("PRAGMA key = '%s'" % key.replace("'", "''"))
    ver = enc.execute("PRAGMA cipher_version").fetchone()
    if not ver or not ver[0]:
        print("✗ el driver NO es SQLCipher: el destino sería plano, aborto")
        enc.close()
        os.unlink(dst)
        return 1
    c1 = counts(enc)
    enc.close()
    if c1 != c0:
        print("✗ los conteos no cuadran: %r vs %r" % (c0, c1))
        return 1
    with open(dst, "rb") as f:
        if f.read(16).startswith(b"SQLite format 3"):
            print("✗ el destino sigue siendo SQLite plano, aborto")
            os.unlink(dst)
            return 1

    # Swap: el claro queda como .plain.bak (borrar tras verificar el corte).
    os.replace(src, src + ".plain.bak")
    for suf in ("-wal", "-shm"):
        stale = src + suf
        if os.path.exists(stale):
            os.unlink(stale)
    os.replace(dst, src)

    # .env del server (un directorio arriba de data/): clave vigente.
    root = os.path.dirname(os.path.dirname(os.path.abspath(src)))
    env = os.path.join(root, ".env")
    line = "FOXMSG_DB_KEY=%s" % key
    out, seen = [], False
    if os.path.isfile(env):
        for ln in open(env, encoding="utf-8").read().splitlines():
            if ln.startswith("FOXMSG_DB_KEY="):
                out.append(line)
                seen = True
            else:
                out.append(ln)
    if not seen:
        out.append(line)
    with open(env, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    print("✓ DB cifrada y activa (cipher_version=%s)" % ver[0])
    print("  conteos verificados:", c1)
    print("  backup plano temporal: %s" % (src + ".plain.bak"))
    print("  .env actualizado: %s" % env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
