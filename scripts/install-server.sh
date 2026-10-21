#!/usr/bin/env bash
# Instala/actualiza Foxinix server en el host remoto (host SSH "1").
# El shell de login del servidor es fish: todo lo remoto va por "bash -s" (stdin).
# Uso: bash scripts/install-server.sh
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-1}"
REMOTE_DIR="/home/FoxOrange/chat-server"
PASS="${PASS:-123}"
SSHPASS="$PASS"

run_remote() {  # run_remote <comando-bash-en-una-linea>
  SSHPASS="$PASS" sshpass -e ssh -o StrictHostKeyChecking=accept-new "$REMOTE_HOST" bash -s <<< "$1"
}

echo "==> Subiendo código a $REMOTE_HOST:$REMOTE_DIR"
SSHPASS="$PASS" sshpass -e ssh -o StrictHostKeyChecking=accept-new "$REMOTE_HOST" \
  "mkdir -p $REMOTE_DIR"

TAR="$(mktemp /tmp/foxmsg-server-XXXXXX.tar.gz)"
tar czf "$TAR" \
  --exclude '.venv' --exclude 'data' --exclude '__pycache__' --exclude '.env' \
  -C server .
SSHPASS="$PASS" sshpass -e scp -o StrictHostKeyChecking=accept-new "$TAR" \
  "$REMOTE_HOST:/tmp/foxmsg-server.tar.gz"
rm -f "$TAR"

run_remote "cd $REMOTE_DIR && tar xzf /tmp/foxmsg-server.tar.gz && rm /tmp/foxmsg-server.tar.gz && echo '  extraído:' && ls"

echo "==> Setup (venv, .env, systemd)"
SSHPASS="$PASS" sshpass -e ssh -o StrictHostKeyChecking=accept-new "$REMOTE_HOST" \
  bash -s < scripts/remote-setup.sh
