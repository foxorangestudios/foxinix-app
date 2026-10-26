# Foxinix — API

Base URL: `http://<host>:8444` (Tailscale: `http://100.125.128.82:8444`)

- **Formato**: JSON, UTF-8.
- **Auth**: header `Authorization: Bearer <access_token>` (excepto donde se indique).
- **Errores**: `{"detail": "mensaje"}` o `{"detail": {"retry_after": n, ...}}`. Códigos: `400` datos inválidos, `401` sin credenciales o token vencido (el cliente refresca y reintenta una vez), `403` token válido pero cuenta sin verificar, `404` no existe, `409` duplicado, `410` código expirado/invalidado, `413` archivo muy grande, `415` tipo no permitido, `429` rate limit, `507` cuota llena.

## Scopes de token

| scope | cuándo | puede |
|---|---|---|
| `pending` | tras registro / login con cuenta sin verificar | `PUT /auth/profile`, `POST /auth/verify`, `POST /auth/resend`, `POST /media` |
| `full` | cuenta verificada | todo |

Nota de cliente: si **recargás la página** con scope `pending`, la verificación se
**cancela** (se borra la sesión local y volvés al login); la cuenta queda sin usar y un
registro nuevo con el mismo correo (o usuario) la **reemplaza** enviando un código fresco.

## Autenticación

### `POST /api/auth/register` — 201
```json
{"email": "ana@mail.com", "username": "ana", "password": "mínimo 8"}
```
→ `{"user": {...}, "tokens": {"access", "refresh"}, "verification": {"required": true, "email_masked": "an*@mail.com", "expires_in": 600, "resend_after": 60, "attempts_left": 5}}`

Regla: el **primer registro es abierto**; el usuario queda `email_verified=false`.

- Si el correo **o** el usuario pertenecen a una cuenta **sin verificar** (registro
  abandonado o cancelado por recarga), esa cuenta se **descarta** (media incluida) y se
  crea la nueva con un código recién enviado: un registro sin verificar no prueba la
  propiedad de nada. Las cuentas verificadas jamás se reemplazan → `409`.

### `PUT /api/auth/profile` — pending o full
```json
{"display_name": "Ana Pérez", "bio": "...", "status_text": "...",
 "status_preset": "online", "avatar_media_id": 1, "banner_media_id": 2}
```
- `display_name` opcional (si vacío se usa el `username`), `bio` opcional ≤150, `status_text` ≤80.
- `status_preset` (W6): `"" | "online" | "busy" | "dnd" | "invisible"`. `invisible` además
  avisa a los contactos que dejo de aparecer en línea (`online: false` en sus briefs).
- `avatar_media_id`: id de un archivo subido por vos; `null` explícito → quitar avatar.
- `banner_media_id` (W58): id de un archivo **imagen** subido por vos para la portada del
  perfil; `null` explícito → quitarla. Si el id no existe, es de otro usuario o no es una
  imagen → `400`. La respuesta y los briefs incluyen `banner_url` firmada (`/media/profile/...`).
- Para saber si el campo fue enviado, el servidor usa `model_fields_set` (no confundir `null` con ausente).

### `PUT /api/auth/username` — full (W59)
```json
{"username": "ana_nueva", "password": "tu contraseña actual"}
```
→ `{"user": {...}}`
- Cambia el **@usuario** (también sirve para iniciar sesión y para las menciones `@`).
- Exige la **contraseña actual** y solo se permite **una vez cada 12 horas**.
- Formato: 3–20 caracteres, minúsculas, números, `.` y `_`; empieza por letra o número.
- `409` si ya está en uso; `429` con el tiempo restante si el enfriamiento está activo.
- Los chats, el `id` y la cuota **no cambian**. Los contactos reciben un
  evento WS `profile` con el `username` nuevo; las menciones `@viejo` ya escritas no se reescriben.

### `POST /api/auth/verify` — pending
`{"code": "123456"}` → `{"verified": true, "user": {...}, "tokens": {...}}`
- Código de 6 dígitos, **válido 10 min**, **5 intentos** fallidos lo invalidan.
- Éxito → tokens con scope `full` (**acceso inmediato**).

### `POST /api/auth/resend` — pending
`{"purpose": "verify" | "reset"}` → `{"ok", "expires_in", "resend_after", "attempts_left"}`
- **Cooldown 60 s**: si apura → `429 {"detail": {"retry_after": n, "message"}}`.

### `POST /api/auth/login`
`{"identifier": "ana" | "ana@mail.com", "password": "..."}` →
```json
{"user": {...}, "tokens": {...},
 "verification": {"required": true, "email_masked": "...", "resend_after": 59, "resend_ready": false}}
```
`verification` **solo aparece si la cuenta no está verificada** → el cliente debe mostrar la pantalla de código.

### `POST /api/auth/refresh`
`{"refresh": "..."}` → `{"tokens": {...}}` — el refresh rota la sesión; si el `token_version` cambió (password reset) devuelve `401`.

### `POST /api/auth/forgot` → `{"ok": true, "retry_after": n}` (respuesta idéntica exista o no la cuenta)
### `POST /api/auth/reset`
`{"identifier", "code", "password"}` → `{"ok": true, "tokens": {...}}` (invalida todos los tokens anteriores).

### `POST /api/auth/password` — full (W6)
```json
{"current_password": "...", "new_password": "mínimo 8"}
```
→ `{"ok": true, "user": {...}, "tokens": {...}}`
- Sube el `token_version`: **todos** los tokens anteriores quedan inválidos; el servidor
  devuelve tokens frescos para que esta sesión siga viva.
- Contraseña actual distinta → `400`.

### `POST /api/auth/email/change` — full (W6)
```json
{"email": "nuevo@mail.com"}
```
→ `{"ok": true, "email_masked": "nu*@mail.com", "expires_in": 600, "resend_after": 60, "attempts_left": 5}`
- Guarda `pending_email` y manda el código al **nuevo** correo (asunto
  "Foxinix — Confirmá tu nuevo correo", `purpose: emailchange`). El correo actual sigue
  activo hasta confirmar; mismo cooldown de 60 s y límite de 5 intentos.

### `POST /api/auth/email/change/verify` — full (W6)
`{"code": "123456"}` → `{"ok": true, "user": {...}}` — al confirmar, `pending_email`
pasa a ser el correo definitivo (y el código queda borrado).

### `DELETE /api/auth/account` — full (W6)
```json
{"username": "ana", "password": "..."}
```
→ `{"ok": true}`
- Exige **usuario y contraseña** escritos (el cliente los pide en la caja de confirmación).
- El borrado es **transaccional**: elimina sus mensajes, sus archivos (solo si ningún
  mensaje, avatar, grupo o GIF favorito de otra cuenta sigue usándolos) y la cuenta.
- Sus **MD se eliminan completos** (el otro miembro deja de verlos). En los **grupos**
  queda un mensaje de sistema **"La cuenta de X fue eliminada"** (remitente nulo) y, si
  era owner, la propiedad pasa al admin/miembro más antiguo. Los tokens dejan de servir.

## Usuarios

- `GET /api/users/me` → `{"user": {...}}` — única vista que incluye `email`
- `GET /api/users/search?q=an` → `{"results": [user]}` (mín. 2 chars, solo verificados, excluye yo)
- `GET /api/users/{username}` → `{"user": {...}}` (404 si no existe o no está verificado)

**user**: `{id, username, display_name, avatar_url, banner_url, bio, status_text, status_preset, online, last_seen, created_at}`. En la respuesta de la cuenta propia se añade `username_changed_at` (segundos Unix; `0` = nunca) para calcular el enfriamiento de 12 h.
- `status_preset`: `"" | online | busy | dnd | invisible` (W6); con `invisible` el servidor
  lo reporta `online: false` a los demás aunque tenga la sesión abierta.

## Chats

- `GET /api/chats` → `{"chats": [chat]}` ordenado por actividad (**fijados primero**, W13).
  Incluye archivados (con `archived: true`) y **oculta** los MD sin una solicitud de
  amistad aceptada, además de los MD que yo haya eliminado (`hidden_at`). Al recibir un
  mensaje nuevo, un MD eliminado vuelve a aparecer.
- `POST /api/chats/dm` `{"username"}` → `{"chat"}` (idempotente: si ya existe, lo devuelve).
  **Requiere amistad aceptada**; si no, → `403`. Crear el MD reabre uno archivado o
  eliminado por cualquiera de las dos partes.
- `POST /api/chats/group` `{"title", "members": ["bruno"]}` → `{"chat"}` (yo = owner)

**chat**: `{id, type: "dm"|"group", title: {user|{display_name}}, avatar_url, member_count, last_message, unread, my_role, pinned, muted, archived, peer_read_seq, peer_delivered_seq}`
- `peer_read_seq` / `peer_delivered_seq` (W12): el **máximo** de esos contadores entre los OTROS miembros — el cliente los usa para sembrar las palomitas (✓ enviado · ✓✓ recibido · ✓✓ azul leído) tras recargar.
- `pinned` / `muted` / `archived`: ajustes **personales** por miembro (`chat_members`); cada usuario fija, silencia o archiva solo su propia lista.

- `GET /api/chats/{id}/messages?before_seq=&limit=50` → `{"messages": [...]}` (asc, `limit≤100`)
- `POST /api/chats/{id}/messages` → 201 `{"message": {...}}`
```json
{"kind": "text|image|file|voice", "body": "...", "media_id": 7, "reply_to": 12, "client_msg_id": "uuid", "peaks": "[5,50,100]", "dur": 7}
```
  - `client_msg_id` = **idempotencia**: reenviar el mismo devuelve el mensaje original (no duplica).
  - `kind` con archivo requiere `media_id` de un archivo subido por el mismo usuario.
  - `peaks` / `dur` (W13, solo voz): onda de la nota como JSON de enteros 0..100 (≤128 valores) y duración en segundos (1..3600). El cliente los calcula al grabar porque los WebM de `MediaRecorder` **no traen duración en el encabezado** (el `<audio>` reportaría `Infinity` y se vería "0:00").
  - **Rate limit (W11)**: ~3 mensajes cada 5 s por usuario (ráfaga de 5). Al superarlo → `429` con `{"detail": {"retry_after": N}}` (segundos); el cliente muestra "Espera Ns antes de reintentar". Un reintento idempotente (mismo `client_msg_id`) **nunca** recibe 429. El `body` puede llevar el **caption** de una imagen/video.
- `POST /api/chats/{id}/read` `{"seq": n}` → marca leído hasta `seq`.
  - **Palomitas (W12)**: `last_delivered_seq` por miembro se actualiza (a) cuando el mensaje se empuja con éxito por su WS conectado (evento `delivered`), (b) cuando el miembro baja mensajes por REST y (c) al marcar `read` (leer implica haber recibido). Solo sube, nunca baja.
- `POST /api/chats/{id}/typing` → avisa "escribiendo" por WS a los demás.
- `POST /api/chats/{id}/pin` `{"pinned": true|false}` → `{"ok": true, "pinned"}` (W13) — fija/desfija el chat en **mi** lista; solo miembros.
- `POST /api/chats/{id}/mute` `{"muted": true|false}` → `{"ok": true, "muted"}` (W13) — silencia sonido y notificaciones del chat **para mí**; el cliente también atenúa el badge.
- `POST /api/chats/{id}/archive` `{"archived": true|false}` → `{"ok": true, "archived"}` — archiva/desarchiva **para mí** un MD o un grupo; no afecta al otro miembro.
- `DELETE /api/chats/{id}` → `{"ok": true}` — **solo MD**: lo elimina de **mi** lista (`hidden_at`). El otro conserva su copia y mis mensajes; si llega un mensaje nuevo, el chat reaparece. En un grupo → `400`.
- `POST /api/chats/{id}/transfer-owner` `{"username"}` → `{"ok": true}` — **solo el owner** de un grupo cede la propiedad a otro miembro (pasa a `admin`); deja mensaje de sistema y evento `members_changed`.
- `GET /api/chats/{id}/search?q=&limit=50` → `{"messages": [...]}` (W13) — busca por **cuerpo** dentro del chat (más recientes primero). Primero coincide el texto literal (con `%`/`_` escapados); sin resultados, repite con el texto **plegado** sin acentos ni mayúsculas ("cafe" encuentra "café").
- `POST /api/chats/{id}/messages/{message_id}/forward` → 201 `{"message"}` (W13) — `{"target_chat_id": n}`: reenvía a otro **de mis chats**. Copia `kind`/`body`/`media_id` (el archivo queda compartido)/`peaks`/`dur` y marca `forwarded: true`; el nuevo mensaje es mío y consume el rate limit. `system` → `400`; destino = origen → `400`; no-miembro del destino → `403`; mensaje inexistente → `404`.
- `POST /api/chats/{id}/members` `{"username"}` → agrega a un grupo (+ mensaje `system`).
- `GET /api/chats/{id}/members` → `{"members": [...]}` (W7/W46) — cada miembro como `user_brief` + presencia (`online`, `last_seen`) + `role` (`owner|admin|member`), en orden de ingreso; en un directo son los dos, incluido yo.
- `PATCH /api/chats/{id}` `{"title": "Nuevo nombre"}` → **solo owner/admin** de un grupo (W57). El título tiene 1..60 caracteres; emite `chat_updated` a todos los miembros para refrescar la lista y la cabecera. Un no-miembro → `403`; un directo o un chat inexistente → `404`.
- `PATCH /api/chats/{id}/members/{user_id}` `{"role": "admin"|"member"}` → **solo owner/admin**. Asciende o quita el rol de admin, deja un mensaje `system` visible para todos y emite `member_role` + `members_changed`. El owner no puede cambiarse; un admin sólo puede ascender a miembros comunes (no toca a otro admin ni al owner) → `403`/`400`.
- `DELETE /api/chats/{id}/members/{user_id}` → **solo owner/admin** saca a un miembro del grupo. Deja un mensaje `system` para los que quedan, emite `member_left` + `members_changed` y avisa al expulsado con `member_removed` (aunque ya no pertenezca al chat). El owner no puede ser eliminado; un admin sólo puede sacar a miembros comunes → `403`/`400`.
- `POST /api/chats/{id}/leave` → `{"ok": true}` o `{"ok": true, "deleted": true}` (W7) — **solo grupos**: elimina mi membresía y manda mensaje `system` + evento `member_left`; si era owner, la propiedad pasa al admin/miembro más antiguo; si era el último miembro, borra el chat entero. En un directo → `400`.
- `POST|DELETE /api/chats/{id}/reactions/{message_id}` `{"emoji": "👍"}`
  - **1 reacción por usuario por mensaje**: el server guarda por `(message_id, user_id)`; un POST nuevo **reemplaza** el emoji anterior del mismo usuario y DELETE (con o sin emoji) la quita.
- `PUT /api/chats/{id}/messages/{message_id}` `{"body"}` → `{"message"}` (W8) — **solo texto propio**: actualiza `body` y `edited_at` (el cliente lo muestra como "editado") y avisa a todos por WS `message_edited`. Ajeno → `403`; no-texto o vacío → `400`.
- `DELETE /api/chats/{id}/messages/{message_id}` → `{"ok": true}` (W8) — **solo mensajes propios**: borra la fila (las reacciones caen en cascada y las citas quedan sin origen) y, si tenía archivo adjunto que ya no usa ningún mensaje, avatar, banner, grupo ni GIF favorito, borra el archivo de disco y libera cuota. Avisa por WS `message_deleted`. Ajeno → `403`.

**message**: `{id, seq, chat_id, kind, body, media, reply_to, client_msg_id, created_at, edited_at, forwarded, peaks, dur, sender, reactions}`
- `seq` es **correlativo por chat** (base para caché incremental y `unread`).
- `edited_at` (W8): `0` = nunca editado; `>0` = timestamp de la última edición.
- `forwarded` (W13): `true` si el mensaje fue reenviado (el cliente muestra "Reenviado").
- `peaks` / `dur` (W13): onda (lista de enteros 0..100) y duración en segundos de las notas de voz; `null` en mensajes viejos (el reproductor dibuja un perfil neutro y resuelve la duración al primer play: seek lejano + `decodeAudioData` de respaldo).
- `sender.role` (W46): `owner|admin|member` **en ese chat**; el cliente pinta `[Admin]` junto al nombre en grupos.

## Media

- `POST /api/media` (multipart `file`) → 201 `{id, url, mime, size, name}`
  - Límites: 15 MB/archivo, cuota global 1 GB (→ `507`), tipos: imagen/video/audio/pdf/texto/zip.
  - **Imágenes → WebP** (W8): todo lo que Pillow pueda leer se recodifica a `image/webp` calidad 95, **sin redimensionar**, con orientación EXIF aplicada y sin metadatos (GIF animados → WebP animado). El `mime` y el `size` de la respuesta ya son los convertidos. SVG y formatos que Pillow no soporta quedan como se subieron (requiere `Pillow` instalado; sin él, se guarda el original).
  - `url` (W11) viene **firmada**: `/media/file/{slug}.{ext}?exp={unix}&sig={hmac}` — el slug es aleatorio de 32 hex y `sig` (HMAC-SHA256 truncado) caduca con `exp` (**24 h** por defecto, `FOXMSG_MEDIA_URL_TTL`; se renueva en cada respuesta de la API). **El token de cuenta ya no viaja en ninguna URL.**
- `GET /media/profile/{slug}.{ext}?exp=&sig=` → avatar (de usuario o de grupo).
- `GET /media/file/{slug}.{ext}?exp=&sig=` → archivo de mensaje.
  - La firma **es** la credencial: sin `sig` válido → `403` (vencida, alterada o ausente). El slug se valida contra la firma **antes** de consultar la base, así que no hay enumeración posible.
- `GET /api/media/{id}?token=<access>` → **legacy** (compat con clientes viejos): sigue requiriendo token por header o query (QML no manda headers en `Image.source`).
- `GET /api/media/quota/stats` → `{used_bytes, quota_bytes, percent}`

## WebSocket — `GET /api/ws`

El access token viaja como **subprotocolo** `['foxinix', <access>]` (no en la URL ni en headers); un token inválido se rechaza con `403`.

**Servidor → cliente**
| tipo | payload |
|---|---|
| `connected` | `{server_time}` |
| `message` | `{message}` (mensaje nuevo en un chat mío) |
| `delivered` | `{chat_id, seq, user_ids}` (W12: el seq llegó a los dispositivos de `user_ids` → ✓✓ "recibido") |
| `typing` | `{chat_id, user_id, username}` |
| `read` | `{chat_id, user_id, seq}` |
| `reaction` / `reaction_removed` | `{chat_id, message_id, user_id, emoji}` |
| `message_edited` | `{chat_id, message_id, body, edited_at}` (W8: edición de texto propio) |
| `message_deleted` | `{chat_id, message_id, seq}` (W8: borrado de mensaje propio) |
| `members_changed` | `{chat_id}` (alta/baja/cambio de rol de miembros) |
| `member_role` | `{chat_id, user_id, role, by}` (W46: ascenso o quita de admin) |
| `member_removed` | `{chat_id, user_id, by, title}` (W46: expulsión; llega al usuario aunque ya no sea miembro) |
| `member_left` | `{chat_id, user_id}` (salida de grupo; si era el último, el chat se borra) |
| `chat_created` | `{chat_id}` |
| `presence` | `{user_id, online}` |
| `call_offer` / `call_answer` / `call_ice` / `call_hangup` | `{chat_id, from, sdp|candidate, video?}` — solo se relayan en un MD con **amistad aceptada**, sin bloqueo y visible para ambas partes |
| `call_error` | `{chat_id, detail}` — la llamada no se puede entregar (sin amistad, chat eliminado o usuario bloqueado) |

**Cliente → servidor**
- `{"type": "ping"}` → `{"type": "pong"}` (keepalive)
- `{"type": "seen", "chat_id": n, "seq": n}` → marcar leído sin round-trip REST
- `{"type": "call_offer|call_answer|call_ice|call_hangup", ...}` → señalización WebRTC 1:1 (el servidor no ve ni guarda media)

**Reconexión**: al reconectar, refrescar `GET /api/chats` y pedir mensajes con `before_seq = último_seq_caché` por chat.

## Ciclo de vida de cuentas

Creada y **sin verificar a los 5 días** → borrada permanentemente (job horario en el servidor: `app/cleanup.py`).
