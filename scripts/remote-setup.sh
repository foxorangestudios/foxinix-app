#!/usr/bin/env bash
# Se ejecuta EN el servidor remoto (invocado como: bash -s < remote-setup.sh)
set -euo pipefail

REMOTE_DIR="/home/FoxOrange/chat-server"
cd "$REMOTE_DIR"

echo "==> Venv"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> .env"
if [ ! -f .env ]; then
  FOXMSG_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  printf '# Opcional: FOXMSG_DB_KEY=<hex 64> cifra la DB con SQLCipher\n# (activar con: PASS=123 bash scripts/encrypt-db.sh)\nFOXMSG_SECRET=%s\nFOXMSG_PORT=8444\n' "$FOXMSG_SECRET" > .env
  chmod 600 .env
  echo "  .env creado (modo prueba: correos a data/mail.log)"
else
  echo "  .env existente conservado"
fi

echo "==> SQLCipher (solo si la DB está cifrada)"
if grep -q '^FOXMSG_DB_KEY=..*' .env 2>/dev/null; then
  .venv/bin/pip install -q sqlcipher3-binary
  echo "  driver instalado (FOXMSG_DB_KEY activo)"
else
  echo "  sin FOXMSG_DB_KEY → SQLite en claro"
fi

echo "==> Import + init DB"
.venv/bin/python -c 'from app.main import app; from app import db; db.init_db(); print("  OK")'

echo "==> Unidad systemd"
sudo cp "$REMOTE_DIR/deploy/chat-server.service" /etc/systemd/system/chat-server.service
sudo systemctl daemon-reload
sudo systemctl enable chat-server.service
sudo systemctl restart chat-server.service
sleep 2
echo "==> Estado"
systemctl --no-pager status chat-server.service | head -8 || true
echo "==> Health local"
curl -s http://127.0.0.1:8444/api/health || echo "sin respuesta"
echo ""
echo "==> Listo"
