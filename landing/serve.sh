#!/usr/bin/env bash
# Servidor estático mínimo para la portada de Foxinix Chat.
# En producción se sirve detrás del túnel de Cloudflare en el puerto 6070.
set -euo pipefail
cd "$(dirname "$0")"
exec /usr/bin/python3 -m http.server "${PORT:-6070}" --bind 127.0.0.1 --directory .
