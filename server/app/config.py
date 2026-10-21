"""Configuración del servidor Foxinix (variables de entorno + .env)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # server/
APP_DIR = BASE_DIR / "app"


def _load_dotenv(path: Path) -> None:
    """Carga .env simple (KEY=VALUE) sin dependencias externas."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("FOXMSG_DATA", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "foxmsg.db"
# Cifrado en reposo de la base (SQLCipher): clave vacía = SQLite en claro
# (dev/local); con clave, la DB se abre con el driver SQLCipher (sqlcipher3
# o pysqlcipher3). Se aplica por conexión, así que va en cada get_db().
DB_KEY = os.environ.get("FOXMSG_DB_KEY", "").strip()
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
MAIL_LOG = DATA_DIR / "mail.log"

SECRET = os.environ.get("FOXMSG_SECRET", "")
if not SECRET:
    # En desarrollo se genera y persiste; en producción debe venir del .env
    secret_file = DATA_DIR / "dev_secret"
    if secret_file.is_file():
        SECRET = secret_file.read_text(encoding="utf-8").strip()
    else:
        SECRET = secrets.token_urlsafe(48)
        secret_file.write_text(SECRET, encoding="utf-8")

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "Foxinix <no-reply@foxinix.qzz.io>")
# Transporte SMTP (p. ej. Gmail con contraseña de aplicación); tiene prioridad
# sobre la API de Resend si SMTP_HOST y SMTP_PASSWORD están definidos.
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
PUBLIC_URL = os.environ.get("FOXMSG_PUBLIC_URL", "").rstrip("/")

PORT = int(os.environ.get("FOXMSG_PORT", "8444"))
MEDIA_QUOTA = int(os.environ.get("FOXMSG_MEDIA_QUOTA", str(1024**3)))  # 1 GB

# Tokens
ACCESS_TTL = 60 * 60 * 3            # 3 h (acceso)
REFRESH_TTL = 60 * 60 * 24 * 30     # 30 días
PENDING_TTL = 60 * 60 * 24 * 5      # 5 días: ventana de verificación de correo

# Códigos de verificación
CODE_TTL = 60 * 10                  # 10 minutos de validez
CODE_RESEND_COOLDOWN = 60           # 1 minuto entre reenvíos
CODE_MAX_ATTEMPTS = 5               # intentos fallidos antes de invalidar
VERIFY_DEADLINE_DAYS = 5            # borrado permanente si no verifica en 5 días

# Límites
MAX_MEDIA_BYTES = 15 * 1024 * 1024  # W48: 15 MB por archivo
MAX_BODY_CHARS = 4000
RATE_WINDOW = 300                   # ventana de rate limit (5 min)
RATE_MAX = 30                       # intentos por ventana (login/envíos)
