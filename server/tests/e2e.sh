#!/usr/bin/env bash
# Test E2E del flujo de autenticación + chat.
# Re-ejecutable: usa un sufijo único por corrida (no necesita DB limpia).
#
# Local:   bash tests/e2e.sh
# Remoto:  BASE="http://100.125.128.82:8444" MAILLOG="ssh" bash tests/e2e.sh
set -e
BASE="${BASE:-http://127.0.0.1:8899}"
MAILLOG="${MAILLOG:-server/data/mail.log}"   # o "ssh" para leer el del servidor remoto
REMOTE_HOST="${REMOTE_HOST:-1}"

RUN="t$(date +%s)"
SUF="@$RUN.test"      # email: ana@t123.test
UA="ana$RUN"          # usuario: ana1791403931
UB="bruno$RUN"

last_code() {
  if [ "$MAILLOG" = "ssh" ]; then
    sshpass -p "${PASS:-123}" ssh -o StrictHostKeyChecking=accept-new "$REMOTE_HOST" \
      "tail -1 /home/FoxOrange/chat-server/data/mail.log" | awk -F' \\| ' '{print $4}'
  else
    tail -1 "$MAILLOG" | awk -F' \\| ' '{print $4}'
  fi
}
J() { python3 -c "import sys,json; d=json.load(sys.stdin); print(d$1)"; }
FAIL=0
check() {  # check <desc> <expected_http> <actual_http>
  if [ "$2" = "$3" ]; then echo "   OK ($3)"; else echo "   FALLÓ: esperaba HTTP $2, llegó $3"; FAIL=1; fi
}

echo "== 1. registro ($UA) =="
R1=$(curl -s -w "\n%{http_code}" -X POST $BASE/api/auth/register -H 'Content-Type: application/json' \
  -d "{\"email\":\"ana$SUF\",\"username\":\"$UA\",\"password\":\"clave12345\"}")
C1=$(echo "$R1" | tail -1); check "registro" 201 "$C1"
TOKEN=$(echo "$R1" | head -n -1 | J "['tokens']['access']")

echo "== 2. perfil (pending scope) =="
P2=$(curl -s -o /tmp/e2e-out.json -w "%{http_code}" -X PUT $BASE/api/auth/profile \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"display_name":"Ana Pérez","bio":"Hola, soy Ana"}')
check "profile con token pending" 200 "$P2"
DN=$(python3 -c "import json;print(json.load(open('/tmp/e2e-out.json'))['user']['display_name'])")
[ "$DN" = "Ana Pérez" ] && echo "   OK display_name=$DN" || { echo "   FALLÓ display_name=$DN"; FAIL=1; }

echo "== 3. acceso con scope pendiente (debe 403 en /chats) =="
C3=$(curl -s -o /dev/null -w "%{http_code}" $BASE/api/chats -H "Authorization: Bearer $TOKEN")
check "chats con pending" 403 "$C3"

echo "== 4. reenviar código (cooldown 60s) =="
# register ya creó un código => el primer reenvío dentro de los 60s debe dar 429
C4=$(curl -s -o /tmp/e2e-out.json -w "%{http_code}" -X POST $BASE/api/auth/resend \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"purpose":"verify"}')
check "primer reenvío dentro del cooldown" 429 "$C4"
python3 -c "import json;d=json.load(open('/tmp/e2e-out.json'))['detail'];print('   retry_after:',d['retry_after'],'msg:',d['message'])" 2>/dev/null || true
C4b=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth/resend \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"purpose":"verify"}')
check "segundo reenvío inmediato" 429 "$C4b"

echo "== 5. código incorrecto =="
C5=$(curl -s -o /tmp/e2e-out.json -w "%{http_code}" -X POST $BASE/api/auth/verify \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"code":"999999"}')
check "verify código malo" 401 "$C5"
grep -o "quedan [0-9]* intentos" /tmp/e2e-out.json || echo "   (sin detalle de intentos)"

echo "== 6. código correcto =="
sleep 1
CODE=$(last_code)
if [ -z "$CODE" ]; then echo "   no se pudo leer el código"; exit 1; fi
echo "   código=$CODE"
R6=$(curl -s -w "\n%{http_code}" -X POST $BASE/api/auth/verify -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d "{\"code\":\"$CODE\"}")
C6=$(echo "$R6" | tail -1); check "verify" 200 "$C6"
FULL=$(echo "$R6" | head -n -1 | J "['tokens']['access']")
VER=$(echo "$R6" | head -n -1 | J "['verified']")
[ "$VER" = "True" ] && echo "   OK verified=true" || { echo "   FALLÓ verified=$VER"; FAIL=1; }

echo "== 7. segundo usuario (bruno) =="
R7=$(curl -s -X POST $BASE/api/auth/register -H 'Content-Type: application/json' \
  -d "{\"email\":\"bruno$SUF\",\"username\":\"$UB\",\"password\":\"clave12345\"}")
TB=$(echo "$R7" | J "['tokens']['access']")
sleep 1; CODEB=$(last_code)
curl -s -X POST $BASE/api/auth/verify -H "Authorization: Bearer $TB" \
  -H 'Content-Type: application/json' -d "{\"code\":\"$CODEB\"}" > /dev/null
TB=$(curl -s -X POST $BASE/api/auth/login -H 'Content-Type: application/json' \
  -d "{\"identifier\":\"bruno$SUF\",\"password\":\"clave12345\"}" | J "['tokens']['access']")
echo "   OK bruno logueado con correo"

echo "== 8. login con contraseña incorrecta =="
C8=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' -d "{\"identifier\":\"$UA\",\"password\":\"mala12345\"}")
check "login malo" 401 "$C8"

echo "== 9. login con correo (recién verificado) =="
C9=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' -d "{\"identifier\":\"ana$SUF\",\"password\":\"clave12345\"}")
check "login por correo" 200 "$C9"

echo "== 10. dm ana<->bruno =="
CHAT=$(curl -s -X POST $BASE/api/chats/dm -H "Authorization: Bearer $FULL" \
  -H 'Content-Type: application/json' -d "{\"username\":\"$UB\"}" | J "['chat']['id']")
echo "   chat_id=$CHAT"
CHAT2=$(curl -s -X POST $BASE/api/chats/dm -H "Authorization: Bearer $FULL" \
  -H 'Content-Type: application/json' -d "{\"username\":\"$UB\"}" | J "['chat']['id']")
[ "$CHAT" = "$CHAT2" ] && echo "   OK idempotente (mismo chat=$CHAT2)" || { echo "   FALLÓ creó chat nuevo"; FAIL=1; }

echo "== 11. enviar mensaje =="
CMID="e2e-$RUN"
MSG=$(curl -s -X POST $BASE/api/chats/$CHAT/messages -H "Authorization: Bearer $FULL" \
  -H 'Content-Type: application/json' \
  -d "{\"kind\":\"text\",\"body\":\"¡hola Bruno!\",\"client_msg_id\":\"$CMID\"}")
echo "$MSG" | python3 -m json.tool | head -12

echo "== 11b. idempotencia (mismo client_msg_id) =="
SEQ1=$(echo "$MSG" | J "['message']['seq']")
SEQ2=$(curl -s -X POST $BASE/api/chats/$CHAT/messages -H "Authorization: Bearer $FULL" \
  -H 'Content-Type: application/json' \
  -d "{\"kind\":\"text\",\"body\":\"¡hola Bruno!\",\"client_msg_id\":\"$CMID\"}" | J "['message']['seq']")
[ "$SEQ1" = "$SEQ2" ] && echo "   OK seq1=$SEQ1 seq2=$SEQ2" || { echo "   FALLÓ seq1=$SEQ1 seq2=$SEQ2"; FAIL=1; }

echo "== 12. bruno responde =="
BR=$(curl -s -X POST $BASE/api/chats/$CHAT/messages -H "Authorization: Bearer $TB" \
  -H 'Content-Type: application/json' -d '{"kind":"text","body":"hola ana! todo bien"}')
echo "   $(echo "$BR" | J "['message']['body']")"

echo "== 13. historial =="
curl -s "$BASE/api/chats/$CHAT/messages?limit=10" -H "Authorization: Bearer $TB" \
  | python3 -c "import sys,json; [print('   ',m['seq'], m['sender']['username'], repr(m['body'])) for m in json.load(sys.stdin)['messages']]"

echo "== 14. no leídos de bruno =="
UNR=$(curl -s "$BASE/api/chats" -H "Authorization: Bearer $TB" \
  | python3 -c "import sys,json; print([c['unread'] for c in json.load(sys.stdin)['chats'] if c['id']==$CHAT][0])")
[ "$UNR" = "1" ] && echo "   OK unread=$UNR" || { echo "   FALLÓ unread=$UNR (esperaba 1)"; FAIL=1; }

echo "== 15. marcar leído =="
curl -s -X POST $BASE/api/chats/$CHAT/read -H "Authorization: Bearer $TB" \
  -H 'Content-Type: application/json' -d "{\"seq\":$SEQ1}" > /dev/null
UNR2=$(curl -s "$BASE/api/chats" -H "Authorization: Bearer $TB" \
  | python3 -c "import sys,json; print([c['unread'] for c in json.load(sys.stdin)['chats'] if c['id']==$CHAT][0])")
[ "$UNR2" = "0" ] && echo "   OK unread=$UNR2" || { echo "   FALLÓ unread=$UNR2 (esperaba 0)"; FAIL=1; }

echo "== 16. búsqueda de contactos =="
NRES=$(curl -s "$BASE/api/users/search?q=$UA" -H "Authorization: Bearer $TB" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)['results']))")
[ "$NRES" -ge 1 ] && echo "   OK resultados=$NRES" || { echo "   FALLÓ resultados=$NRES"; FAIL=1; }

echo "== 17. forgot + reset password =="
curl -s -X POST $BASE/api/auth/forgot -H 'Content-Type: application/json' \
  -d "{\"identifier\":\"$UA\"}" | python3 -m json.tool | head -5
sleep 1; CODER=$(last_code)
CR=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth/reset \
  -H 'Content-Type: application/json' \
  -d "{\"identifier\":\"$UA\",\"code\":\"$CODER\",\"password\":\"nuevaclave99\"}")
check "reset" 200 "$CR"
C17=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' -d "{\"identifier\":\"$UA\",\"password\":\"nuevaclave99\"}")
check "login con contraseña nueva" 200 "$C17"
C17b=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth/login \
  -H 'Content-Type: application/json' -d "{\"identifier\":\"$UA\",\"password\":\"clave12345\"}")
check "contraseña vieja rechazada" 401 "$C17b"

echo "== 18. registro duplicado (debe 409) =="
C18=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/auth/register \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"ana$SUF\",\"username\":\"otro$RUN\",\"password\":\"clave12345\"}")
check "email duplicado" 409 "$C18"

echo "== 19. registro sin verificar no puede chatear =="
RU="nuev$RUN"
RN=$(curl -s -X POST $BASE/api/auth/register -H 'Content-Type: application/json' \
  -d "{\"email\":\"n$SUF\",\"username\":\"$RU\",\"password\":\"clave12345\"}" | J "['tokens']['access']")
C19=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/chats" -H "Authorization: Bearer $RN")
check "chats con cuenta sin verificar" 403 "$C19"

echo ""
if [ "$FAIL" = "0" ]; then
  echo "=== TEST COMPLETADO: TODOS LOS CASOS OK ==="
else
  echo "=== TEST COMPLETADO CON FALLOS ==="
fi
exit $FAIL
