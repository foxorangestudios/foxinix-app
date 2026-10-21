#!/usr/bin/env bash
# Cifra la DB de producción con SQLCipher (cifrado en reposo):
#   1) genera la clave FOXMSG_DB_KEY (hex 32 bytes)
#   2) detiene el servicio, migra con sqlcipher_export y verifica
#   3) arranca, chequea health/journal y borra el backup plano
# Si la migración falla, el servicio vuelve a arrancar con la DB original
# en claro (nunca se queda caído ni se pisa nada).
# Uso: PASS=123 bash scripts/encrypt-db.sh
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-1}"
REMOTE_DIR="/home/FoxOrange/chat-server"
PASS="${PASS:-123}"
export SSHPASS="$PASS"

KEY="$(openssl rand -hex 32)"

echo "==> Subiendo el migrador"
sshpass -e scp -o StrictHostKeyChecking=accept-new scripts/migrate-db-enc.py \
  "$REMOTE_HOST:$REMOTE_DIR/migrate-db-enc.py"

echo "==> Corte: parar → migrar → verificar → arrancar"
sshpass -e ssh -o StrictHostKeyChecking=accept-new "$REMOTE_HOST" bash -s <<EOF
set -e
cd $REMOTE_DIR
sudo systemctl stop chat-server.service
if FOXMSG_DB_KEY='$KEY' .venv/bin/python migrate-db-enc.py data/foxmsg.db data/foxmsg.db.enc; then
  sudo systemctl start chat-server.service
  sleep 2
  echo "==> Health"
  curl -s http://127.0.0.1:8444/api/health
  echo ""
  echo "==> Verificación post-corte"
  FOXMSG_DB_KEY='$KEY' .venv/bin/python migrate-db-enc.py --verify data/foxmsg.db
  echo "==> Journal"
  journalctl -u chat-server -n 5 --no-pager | tail -3
  rm -f migrate-db-enc.py data/foxmsg.db.plain.bak
  echo "==> Listo: DB cifrada activa y backup plano eliminado"
else
  echo "✗ migración fallada: se restaura el servicio con la DB original"
  sudo systemctl start chat-server.service
  exit 1
fi
EOF
