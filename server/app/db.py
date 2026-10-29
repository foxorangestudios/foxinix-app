"""Esquema y acceso a SQLite (WAL, foreign keys activas)."""
from __future__ import annotations

import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

_local = threading.local()
_write_lock = threading.Lock()

_cipher_mod: Any = None   # driver SQLCipher diferido (si hay clave)


def _db_mod() -> Any:
    """sqlite3 estándar, o el driver SQLCipher si FOXMSG_DB_KEY está definido.

    SQLCipher cifra el archivo completo en reposo (roban el .db o un backup →
    galimbas). La clave se aplica por conexión, no viaja en el archivo y no
    cambia el esquema ni el SQL: el server sigue buscando, notificando, etc."""
    global _cipher_mod
    if _cipher_mod is None:
        if not config.DB_KEY:
            _cipher_mod = sqlite3
        else:
            try:
                from sqlcipher3 import dbapi2 as m          # type: ignore
            except ImportError:
                try:
                    from pysqlcipher3 import dbapi2 as m    # type: ignore
                except ImportError as e:
                    raise RuntimeError(
                        "FOXMSG_DB_KEY está definido pero falta el driver "
                        "SQLCipher (pip install sqlcipher3 o pysqlcipher3)"
                    ) from e
            _cipher_mod = m
    return _cipher_mod

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    username       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    username_changed_at INTEGER NOT NULL DEFAULT 0,  -- W59: último cambio (12 h)
    password_hash  TEXT NOT NULL,
    display_name   TEXT NOT NULL DEFAULT '',
    bio            TEXT NOT NULL DEFAULT '',
    status_text    TEXT NOT NULL DEFAULT '',
    status_preset  TEXT NOT NULL DEFAULT 'online',  -- online | busy | dnd | invisible (W6/W10)
    pending_email  TEXT NOT NULL DEFAULT '',  -- correo nuevo esperando código (W6)
    avatar_media_id INTEGER,
    banner_media_id INTEGER,                  -- W58: portada del perfil
    banner_position INTEGER NOT NULL DEFAULT 50,  -- W61: foco vertical (%)
    email_verified INTEGER NOT NULL DEFAULT 0,
    token_version  INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL,
    last_seen      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS email_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose    TEXT NOT NULL,              -- 'verify' | 'reset'
    code_hash  TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_codes_user ON email_codes(user_id, purpose);

CREATE TABLE IF NOT EXISTS media (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    path       TEXT NOT NULL,              -- relativo a MEDIA_DIR
    mime       TEXT NOT NULL,
    size       INTEGER NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    slug       TEXT UNIQUE,                -- W11: 32 hex aleatorios p/ URL
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chats (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    type       TEXT NOT NULL,              -- 'dm' | 'group'
    title      TEXT NOT NULL DEFAULT '',
    avatar_media_id INTEGER,
    dm_key     TEXT UNIQUE,                -- p.ej. '7:12' ordenado para DMs
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL,
    -- W45: contador monótono por chat. MAX(seq) se reutilizaba al borrar
    -- el último mensaje, y un seq repetido desordena las palomitas y los
    -- cursores de "recibido/leído". Este valor nunca baja.
    last_seq   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_members (
    chat_id      INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role         TEXT NOT NULL DEFAULT 'member',   -- 'owner' | 'admin' | 'member'
    last_read_seq INTEGER NOT NULL DEFAULT 0,
    last_delivered_seq INTEGER NOT NULL DEFAULT 0,   -- W12: 'recibido'
    pinned    INTEGER NOT NULL DEFAULT 0,            -- W13: fijado en mi lista
    muted     INTEGER NOT NULL DEFAULT 0,            -- W13: notificaciones off
    archived  INTEGER NOT NULL DEFAULT 0,            -- archivado (solo para mí)
    hidden_at INTEGER NOT NULL DEFAULT 0,            -- MD eliminado de mi lista
    joined_at    INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_members_user ON chat_members(user_id);

-- W27: solicitudes de amistad (panel Personas). Una amistad queda como la
-- fila 'accepted' en cualquier dirección; rechazar o cancelar BORRA la fila
-- (ambos pueden volver a enviar después).
CREATE TABLE IF NOT EXISTS friend_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'accepted'
    created_at  INTEGER NOT NULL,
    answered_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fri_to ON friend_requests(to_user, status);
CREATE INDEX IF NOT EXISTS idx_fri_from ON friend_requests(from_user, status);

-- W28e: bloqueos (uno por dirección). Bloquear rompe amistad y solicitudes
-- pendientes; mientras dure, no hay solicitudes ni mensajes directos entre
-- los dos (los grupos no se tocan).
CREATE TABLE IF NOT EXISTS blocks (
    blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (blocker_id, blocked_id)
);
CREATE INDEX IF NOT EXISTS idx_blocks_blocked ON blocks(blocked_id);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,        -- correlativo por chat
    sender_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind          TEXT NOT NULL DEFAULT 'text',   -- text|image|file|voice|system
    body          TEXT NOT NULL DEFAULT '',
    media_id      INTEGER REFERENCES media(id) ON DELETE SET NULL,
    reply_to      INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    client_msg_id TEXT,                    -- idempotencia del cliente
    created_at    INTEGER NOT NULL,
    edited_at     INTEGER NOT NULL DEFAULT 0,   -- W8: 0 = nunca editado
    forwarded     INTEGER NOT NULL DEFAULT 0,   -- W13: reenviado
    peaks         TEXT,                         -- W13: onda de voz (JSON 0..100)
    dur           INTEGER,                      -- W13: duración en segundos (voz)
    mentions      TEXT NOT NULL DEFAULT '',     -- W28b: miembros citados (",3,5,")
    pinned_at     INTEGER NOT NULL DEFAULT 0,   -- W28c: 0 = sin fijar
    pinned_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    spoiler       INTEGER NOT NULL DEFAULT 0,   -- W29d: contenido con spoiler
    UNIQUE (chat_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, seq DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_client
    ON messages(chat_id, sender_id, client_msg_id)
    WHERE client_msg_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS reactions (
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    emoji      TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (message_id, user_id)
);

-- W35c: caché de "portadas" de enlaces (og:title/og:image/…), TTL 7 días.
CREATE TABLE IF NOT EXISTS link_previews (
    url        TEXT PRIMARY KEY,          -- URL tal como se escribió
    final_url  TEXT NOT NULL,             -- después de los redirects
    type       TEXT NOT NULL,             -- page | image | link
    title      TEXT NOT NULL DEFAULT '',
    desc       TEXT NOT NULL DEFAULT '',
    image      TEXT NOT NULL DEFAULT '',
    icon       TEXT NOT NULL DEFAULT '',
    site       TEXT NOT NULL DEFAULT '',
    fetched_at REAL NOT NULL
);

-- W36k: favoritos de GIFs (biblioteca estática `name` o subidos `media_id`).
CREATE TABLE IF NOT EXISTS gif_favs (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    media_id   INTEGER NOT NULL DEFAULT 0,  -- 0 = GIF de la biblioteca
    name       TEXT NOT NULL DEFAULT '',    -- p. ej. "fire.gif" (biblioteca)
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, media_id, name)
);

-- W61: biblioteca personal de GIFs y stickers subidos. Cada usuario puede
-- guardar hasta 10 de cada tipo; al marcar uno recibido se copia aquí para
-- poder reenviarlo desde el selector.
CREATE TABLE IF NOT EXISTS user_assets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                 -- 'gif' | 'sticker'
    media_id   INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    UNIQUE (user_id, kind, media_id)
);
CREATE INDEX IF NOT EXISTS idx_assets_user ON user_assets(user_id, kind);
"""


def fold_str(s: Any) -> str:
    """W13: plegado para buscar sin acentos ni mayúsculas
    ('cafe' encuentra 'café con leche'). Es también el callback SQL fold()."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFD", str(s))
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return t.lower()


def get_db() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        mod = _db_mod()
        conn = mod.connect(config.DB_PATH, timeout=15, check_same_thread=False)
        conn.row_factory = mod.Row
        if config.DB_KEY:
            # SQLCipher: la clave se aplica en cada conexión nueva (con comillas
            # escapadas; la clave de prod es hex, pero se trata igual de seguro).
            conn.execute(
                "PRAGMA key = '%s'" % config.DB_KEY.replace("'", "''")
            )
        conn.create_function("fold", 1, fold_str)   # W13: búsqueda sin acentos
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        _local.conn = conn
    return conn


def _drop_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    """W67: elimina una columna en bases viejas.

    `ALTER TABLE ... DROP COLUMN` necesita SQLite 3.35+ (2021). Si el del
    servidor fuera más viejo se ignora en seco: la columna queda ahí a
    `NULL`, inofensiva, porque el server ya no la escribe ni la lee.
    """
    try:
        conn.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
    except sqlite3.Error:
        pass


def _migrate(conn: sqlite3.Connection) -> None:
    """Columnas agregadas después del esquema inicial (CREATE IF NOT EXISTS
    no altera tablas existentes): se añaden una sola vez por PRAGMA."""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if "status_preset" not in existing:
        conn.execute("ALTER TABLE users ADD COLUMN status_preset TEXT NOT NULL DEFAULT ''")
    if "pending_email" not in existing:
        conn.execute("ALTER TABLE users ADD COLUMN pending_email TEXT NOT NULL DEFAULT ''")
    if "banner_media_id" not in existing:
        conn.execute("ALTER TABLE users ADD COLUMN banner_media_id INTEGER")
    if "banner_position" not in existing:
        conn.execute(
            "ALTER TABLE users ADD COLUMN banner_position INTEGER NOT NULL DEFAULT 50"
        )
    # W59: el cambio de usuario tiene un enfriamiento de 12 horas.
    if "username_changed_at" not in existing:
        conn.execute(
            "ALTER TABLE users ADD COLUMN username_changed_at INTEGER NOT NULL DEFAULT 0"
        )
    # W45: migración del contador monótono de secuencia. El backfill usa
    # MAX(seq) actual; a partir de aquí los borrados ya no lo hacen bajar.
    ccols = {r["name"] for r in conn.execute("PRAGMA table_info(chats)")}
    if "last_seq" not in ccols:
        conn.execute("ALTER TABLE chats ADD COLUMN last_seq INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "UPDATE chats SET last_seq = COALESCE("
            " (SELECT MAX(seq) FROM messages WHERE messages.chat_id = chats.id), 0)"
        )
    mcols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    if "edited_at" not in mcols:
        conn.execute("ALTER TABLE messages ADD COLUMN edited_at INTEGER NOT NULL DEFAULT 0")
    cmem = {r["name"] for r in conn.execute("PRAGMA table_info(chat_members)")}
    if "last_delivered_seq" not in cmem:
        conn.execute(
            "ALTER TABLE chat_members ADD COLUMN last_delivered_seq"
            " INTEGER NOT NULL DEFAULT 0"
        )
    if "pinned" not in cmem:
        conn.execute("ALTER TABLE chat_members ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    if "muted" not in cmem:
        conn.execute("ALTER TABLE chat_members ADD COLUMN muted INTEGER NOT NULL DEFAULT 0")
    if "archived" not in cmem:
        conn.execute("ALTER TABLE chat_members ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
    if "hidden_at" not in cmem:
        conn.execute("ALTER TABLE chat_members ADD COLUMN hidden_at INTEGER NOT NULL DEFAULT 0")
    if "forwarded" not in mcols:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN forwarded INTEGER NOT NULL DEFAULT 0"
        )
    if "peaks" not in mcols:
        conn.execute("ALTER TABLE messages ADD COLUMN peaks TEXT")
    if "dur" not in mcols:
        conn.execute("ALTER TABLE messages ADD COLUMN dur INTEGER")
    if "mentions" not in mcols:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN mentions TEXT NOT NULL DEFAULT ''"
        )
    if "pinned_at" not in mcols:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN pinned_at INTEGER NOT NULL DEFAULT 0"
        )
    if "pinned_by" not in mcols:
        conn.execute("ALTER TABLE messages ADD COLUMN pinned_by INTEGER")
    if "spoiler" not in mcols:
        conn.execute(
            "ALTER TABLE messages ADD COLUMN spoiler INTEGER NOT NULL DEFAULT 0"
        )
    # W67: retirada del cifrado E2E. Las bases viejas traen estas dos
    # columnas y la tabla de claves; se eliminan en la migración. Todo el
    # historial estaba ya en texto plano (o era un marcador vacío), así que
    # no se pierde nada legible.
    if "e2e_iv" in mcols:
        _drop_column(conn, "messages", "e2e_iv")
    if "e2e_ct" in mcols:
        _drop_column(conn, "messages", "e2e_ct")
    conn.execute("DROP TABLE IF EXISTS e2e_keys")
    med = {r["name"] for r in conn.execute("PRAGMA table_info(media)")}
    if "slug" not in med:
        conn.execute("ALTER TABLE media ADD COLUMN slug TEXT")
        # Backfill: un slug aleatorio por archivo existente y único por fila
        # (randomblob(16) = 32 hex → 128 bits, sin colisiones prácticas).
        conn.execute(
            "UPDATE media SET slug = lower(hex(randomblob(16))) WHERE slug IS NULL"
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_media_slug ON media(slug)")
    # W22: resolución de la imagen (el chat reserva el cuadro con el
    # spinner dentro). Las filas viejas quedan a NULL y message_out las
    # rellena perezosamente (backfill en routers/media.row_dims).
    if "width" not in med:
        conn.execute("ALTER TABLE media ADD COLUMN width INTEGER")
    if "height" not in med:
        conn.execute("ALTER TABLE media ADD COLUMN height INTEGER")
    # W66c: los WebP animados se guardan tal cual (como los GIF); esta marca
    # permite que el cliente los trate como GIF (clase de burbuja, ★ favoritos).
    if "animated" not in med:
        conn.execute(
            "ALTER TABLE media ADD COLUMN animated INTEGER NOT NULL DEFAULT 0")


def init_db() -> None:
    conn = get_db()
    with _write_lock:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Transacción write-serializada (BEGIN IMMEDIATE)."""
    conn = get_db()
    with _write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


def rows(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in get_db().execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    r = get_db().execute(sql, params).fetchone()
    return dict(r) if r else None


def execute(sql: str, params: tuple | list = ()) -> int:
    """Ejecuta una escritura simple fuera de tx() (autocommit)."""
    with _write_lock:
        conn = get_db()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or 0


def run(sql: str, params: tuple | list = ()) -> int:
    """Ejecuta una escritura y devuelve las filas AFFECTADAS (rowcount).

    A diferencia de execute() (lastrowid, para INSERTs), sirve como gate:
    un UPDATE condicional que no cambió nada devuelve 0.
    """
    with _write_lock:
        conn = get_db()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount
