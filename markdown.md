# Plan W29 — Bugs, UX, emojis Twemoji, spoilers y E2E

Lote grande solicitado por el usuario (16/10/2026). Se implementa por
sub-lotes; entre sub-lotes corre la regresión completa
(`/tmp/opencode/regress_w23.sh`, server y tests en :8899).

Estado: **W29a–W29l + W30a–W30e + W31a–W31d + W32 + W33 + W34 +
W35 + W36 COMPLETADOS** — regresión completa **18/18**
(`/tmp/opencode/regress_w36_final2.log`), **deploy SW v65 en prod**
(health 200 + marcadores). Lotes W30–W36 cerrados.

## W29a — Bugs críticos + UX rápida (COMPLETADO)

| # | Item | Archivos | Estado |
|---|------|----------|--------|
| 1 | Caption duplicado en la misma burbuja (imagen+texto) | views/chat.js MessageRow | ✅ fix: los bloques caption (v-if) y body genérico (v-else-if) eran DIVS IDÉNTICOS con `bodySegs`; en la cadena compilada de prod pintaban AMBOS. Fusionados en UN bloque `v-if="!editing && row.ref.body"` (mismo aspecto, sin duplicar). Test w29 paso1. |
| 2 | Archivo vacío (0 bytes): avisar y NO enviar (antes: burbuja con error server-side) | actions.js sendMedia, chat.js pickFiles | ✅ guard en sendMedia (toast 'El archivo está vacío', sin burbuja) + guard al elegir archivos; i18n EN. Test paso2. |
| 3 | Audios adjuntos se ven como "video negro": audio/* → `<audio controls>`; webm sin pista de video → probe `loadedmetadata` (videoHeight=0) → audio | views/chat.js MessageRow, css | ✅ isAudio() + probe vidOk/vidMeta + bloque .b-afile. Test paso3 (.mp3). |
| 4 | Falso "Sesión expirada": refreshTokens con 3 reintentos (backoff 800ms·n), reintentable en red/5xx, authLost SOLO en 401/403 real del refresh | js/api.js | ✅ Test paso4 (access corrupto → refresh → sigue en /app). |
| 5 | Título con contador de no leídos: "(3) Foxinix", tope "999+" | js/main.js (watchEffect) | ✅ Test paso5. |
| 6 | Globo rojo en el botón "Personas" con solicitudes recibidas, tope "9+" | views/chat.js sidebar, css .side-badge | ✅ Test paso6 (solicitud REST → badge). |
| 7 | Animación de entrada de mensajes (aparecer agrandándose): .msg.anim scale+opacity; solo mensajes EN VIVO (WS) y propios optimistas; bandera _in se limpia en animationend | actions.js, chat.js, css | ✅ Test paso7 (WS en vivo con hilo). |

## W29b — Emojis Twemoji + panel estilo Discord (COMPLETADO)

Implementado y probado (suite W29 paso8 + emoji_ui 13/13 + w28 55/55):

- **Datos generados** por `scripts/gen-emoji.py` → `js/emoji-data.js`
  (133 KB): shortcodes/descripciones/categorías de **gemoji**
  (github/gemoji v8, MIT) cruzados con los assets de **Twemoji**
  (jdecked/twemoji 17.0.3, CC-BY 4.0). Resultado: **1746 emojis con
  imagen + 1781 shortcodes** (antes: 419 códigos sin imagen).
- **1746 SVG** en `server/web/emoji/` (nombre = codepoints hex unidos
  con '-', sin U+FE0F, convención Twemoji). Servidos on-demand; el SW
  (v49) NO los precachea (network-first runtime).
- `js/emoji.js` reescrito: importa CATS/CODES/DESC/EMO_FILE; la API
  pública no cambia (`emojiCats/emojiCat/emojiSearch/emojiRecent/
  emojiPush/emojiCode/shortcodesToEmoji/emojiCodesPrefix/reactBump/
  reactRank`) + nuevos `emoFile`, `emoSrc` y `splitEmojis(text)` (trocea
  en {t} texto / {t,e} emoji, con secuencias ZWJ y banderas reconocidas
  enteras vía índice por primer codepoint). Búsqueda ampliada con las
  descripciones gemoji (EN) además de NAMES en español y :códigos:.
- **Render Twemoji**: los mensajes (`bodySegs` → `splitSegs`), los chips
  de reacción, los chips rápidos `.rp`, los stickers y el panel usan
  `<img class="emo" src="/static/emoji/<id>.svg" alt="<Unicode>">`
  (sin v-html: todo por atributos, sin riesgo de XSS). El envío sigue
  siendo texto Unicode normal (`:fire:` → 🔥 al enviar, Twemoji solo
  renderiza).
- **Panel estilo Discord**: buscador arriba; categorías como botones-icono
  a la IZQUIERDA (con scroll-spy: el ícono activo se ilumina al pasar);
  UNA sola lista scrolleable con subtítulos pegajosos ("Recientes:",
  "Caras y emociones:", …). `clampPanel` adaptado: achica `.ep-body` si
  la ventana es corta (el `.ep-grid` interno quedó para stickers/GIFs,
  que conservan `.ep-tabs`).
- i18n: 'Viajes y lugares', 'Actividades y deportes', 'Objetos',
  'Banderas' (EN). Tests actualizados donde leían `textContent` de
  emojis (ahora `<img alt>`): emoji_ui, w28 (burbuja sticker), w29.
- Limitación anotada: gemoji no incluye variaciones de tono de piel
  (se pueden añadir después generándolas por codepoint).

## W29c — UX de grupos/mensajes (COMPLETADO)

Implementado y probado (suite W29 paso9–11, 15/15):

- **"Escribiendo…" por usuario** (antes 1 por chat): `store.typing
  [chatId] = { userId: {u, exp} }` con timeout individual (3,5 s);
  realtime.js marca/limpia por usuario (y al llegar SU mensaje).
  Fila del chat: `° ° ° juan está escribiendo…` (grupos: `u1, u2 y 2
  más…`); en grupos, avatares apilados (máx 3) junto a los puntos.
  El header conserva "escribiendo…" corto.
- **Pelotita** (3 puntos con rebote, solo transform/opacity) en la
  lista de chats (DM y grupos) y en la lista de miembros del panel.
- **Avatar junto a mensajes** en grupos (refinado tras petición del
  usuario): TODOS los entrantes de grupo llevan una columna de
  avatar de 24 px (burbujas alineadas), pero la CARA —foto o letra—
  solo aparece donde se ve el nombre del emisor (primero de la tanda
  y respuestas), estilo WhatsApp; alineado ARRIBA, a la altura del
  nombre. Mensajes del sistema y DMs: sin columna.
- **Respuestas: nombre del emisor ARRIBA de la cita** — el markup
  estaba al revés (la cita se dibujaba antes que `.b-sender`);
  orden ahora: nombre → etiqueta reenviado → cita (`.br-name` sobre
  `.br-text`) → cuerpo. Las respuestas SIEMPRE muestran el nombre
  (`withName = ... && (!tight || reply_to)`), así que la cara del
  avatar también sale en ellas.
- **Hover en una reacción** → "😂 juan, maria" (+ "y N más" si >3).
  El server ya manda `username`/`name` en las reacciones (message_out
  con JOIN a users + evento WS 'reaction').
- **Palomitas de grupos**: ✓ = solo enviado; ✓✓ gris = TODOS los
  demás miembros lo recibieron; ✓✓ azul = todos lo vieron. El server
  añade `peer_read_min_seq`/`peer_delivered_min_seq` (mínimo entre los
  demás) al brief del chat; el cliente combina esa semilla con los
  eventos en vivo 'read'/'delivered' (si los cubren a todos, manda el
  mínimo en vivo).
- **"Info del usuario"**: en DM el panel y su botón dicen "Info del
  usuario" (grupos: "Info del chat").
- **Menús sin desbordes (bug real)**: `openCtx` solo corregía la
  posición cuando había ancla (burbuja) y medía con
  `getBoundingClientRect()` DURANTE la animación de entrada
  (transform: scale → altura subestimada → menú cortado abajo). Ahora
  la rama sin ancla también estima con `estH` y la corrección con
  medida real (`offsetWidth/Height`, inmune al transform) corre
  SIEMPRE.
- i18n EN: '{n} está escribiendo…', '{n} están escribiendo…',
  '{a}, {b} y {m} más están escribiendo…', 'y {n} más', 'Info del
  usuario'. Tests: w29 paso9 (typing+pelotita), paso10 (Info del
  usuario + clamp de menús), paso11 (grupo: cara por tanda + columna
  vacía en el resto + ✓✓ azul + tooltip + respuesta con nombre sobre
  la cita — B leyendo/reaccionando/citando vía REST mientras corre
  la JS). SW v51.

## W29d — Spoilers (COMPLETADO)

> Actualizado por **W29h**: el botón `.comp-spoil` ahora es sólo con
> adjunto (texto: long-press 3 s en Enviar), la capa deja visible la
> hora y las palomitas, y los textos son "Mostrar Spoiler"/"Ocultar".

- Marcar archivo/mensaje como SPOILER: interruptor con ojo-tachado en
  el compositor (`.comp-spoil`); marca UN solo mensaje (texto, adjunto
  con pie, archivos en lote o nota de voz) y se suelta al enviar.
  Flag `spoiler` en messages (migración + `SendIn` + `message_out`).
- Burbuja con capa opaca `.b-spoil-ov` "👁 Toca para mostrar"
  (i-eye-off) que cubre TODO (texto, medios y acciones): mientras
  tapa, los hijos se ocultan con `visibility` (con sólo el fondo
  translúcido el texto asomaba sobre burbujas naranjas). Al tocar se
  muestra; el puntito `.b-spoil-dot` del pie (ojo) lo vuelve a
  ocultar; al SALIR del chat se tapa otra vez (`closeChat` limpia
  `store.spoilSeen[chatId]`).
- En medios: overlay sobre `.b-media` (el lightbox no se abre hasta
  revelar) y `.gal-spoil` en la miniatura de la galería (el primer
  toque revela, el segundo salta): el endpoint `/gallery` incluye
  `spoiler`.

## W29e — Ajustes y vídeo (COMPLETADO)

- "Formato de hora" como menú desplegable 12/24 h (`.h12-select`,
  handler `setH12`; `store.prefs.h12` sigue marcando 12 h).
- **Vídeos en Mypal78**: ffmpeg YA está en la máquina
  (`/usr/bin/ffmpeg`, la misma de prod) → `media.py` transcodifica al
  subir: vídeo → WebM/VP9+Opus (`-deadline realtime -cpu-used 8
  -crf 34`) y audio no-MP3/OGG/WebM → MP3; tope 8 MB / 60 s por
  archivo, en `asyncio.to_thread` (no congela el loop) y con
  fallback: cualquier error se guarda el original tal cual. Verificado
  en local: mp4→webm (0,11 s), wav→mp3, webm se salta.

## W29f — E2E cifrado de extremo a extremo (COMPLETADO, FEATURE GRANDE)

**Alcance: sólo DMs** — los grupos quedan FUERA de alcance (el switch
sólo aparece en `chat.type === 'dm'`; una fase 2 podría llevar claves
por miembro/grupo).

El amigo del usuario lo toma en serio; switch por chat (default OFF):

- **Algoritmo**: WebCrypto (FF78): ECDH P-256 → HKDF-SHA-256 manual
  (HMAC de WebCrypto: `PRK = HMAC(salt, ikm)`, `T1 = HMAC(PRK,
  info||0x01)`; `info = foxinix-e2e-v1|<uidMin>|<uidMax>`) → clave
  AES-GCM 256 por pareja (DM). Verificación SAS:6 emojis derivados de
  la clave, comparados fuera de banda (`.pp-e2e-code`).
- **Claves**: par propio en IndexedDB (`foxinix-e2e`, jwk privada +
  pública); la pública viaja por `PUT /api/users/me/e2e-key` y se lee
  con `GET /api/users/{u}/e2e-key` (tabla `e2e_keys`; el server sólo
  valida P-256 sin comprimir). Al activar: subo la mía, pido la del
  par (si falta: toast "{n} aún no publicó su clave…") y derivo.
- **Mensajes**: `SendIn.e2e {iv, ct}` (base64 validado; blob ≤32 KB;
  el server RECHAZA cuerpo en claro junto a e2e). El server guarda
  body = "[Mensaje cifrado]" + `e2e_iv`/`e2e_ct`; previews y
  notificaciones muestran el marcador solos. El cliente descifra en
  memoria (`m._plain` en `upsertMessage` → `bodySegs` lo pinta);
  quien envía conoce el texto (sin parpadeo). Stickers van en claro
  (el emoji ES el contenido y el server exige cuerpo corto).
- **Multimedia**: archivos por URL normal sin cifrar (diseño acordado;
  fase 2 podría cifrarlos).
- **Compatibilidad**: sin E2E → "[Mensaje cifrado]"; mensajes
  anteriores a la activación quedan en claro. Editar/reenviar/copiar
  de mensajes cifrados: deshabilitados (el server sólo tiene el
  marcador). Estado por chat persistido en `fm.e2e.<uid>`.
- Tests w29 paso14: B publica clave → A activa (SAS) → A envía → el
  server ve SÓLO el marcador y B descifra en Python (cryptography) → B
  responde cifrado → A lo ve descifrado con preview en marcador.

## W29g — Panel unificado: Emojis / Stickers / GIFs (COMPLETADO)

Un SOLO panel flotante con 3 pestañas arriba (`.ep-tabs`: **Emojis |
Stickers | GIFs**), abierto por el botón 😀 del compositor; se quitó el
botón `.comp-stk` de la fila (ahorro de espacio abajo, junto al
recuadro de escritura):

- `store.stOpen`, `stTab` y `toggleSt` ELIMINADOS (store.js + chat.js);
  queda `store.emoOpen` + refs locales `pickTab` ('emo'/'st'/'gif'),
  `pickEl` y `setPickTab` (re-clampea al cambiar de pestaña). Al
  abrir, el panel muestra la pestaña Emojis.
- `EmojiPicker` gana la prop `embed`: embebido NO hace su propio
  clamp ni registra resize/ResizeObserver; el padre `.st-panel` llama a
  `clampPanel(pickEl, true)` al abrir/cambiar de pestaña y en window
  resize. Fuera de ahí (react-picker de chips) sigue flotando igual.
- CSS: `.st-panel .emo-picker` en flujo estático (sin borde/sombra/
  animación propios); `.st-grid` con `max-height: 236px; overflow-y:
  auto` (scroll interno en pantallas cortas); el panel hereda la
  animación `modal-in`.
- Tests: w28 paso16 migrado (abrir con `.comp-emo` → pestaña
  Stickers/GIFs; aserción `tabs == 3`); emoji_ui 13/13 y w13 siguen
  verdes con el picker anidado.

## W29h — Spoiler: botón sólo con adjunto + long-press de 3 s (COMPLETADO)

- **Texto**: NO hay botón suelto en el compositor; se mantiene
  presionado **ENVIAR 3 s** → el mensaje se envía como spoiler (con
  relleno de progreso `.send-fill` en el botón, animado SOLO con
  transform, y toast "Enviado como spoiler"). Soltar antes = clic
  normal. `clickSend` salta el click de soltar si ya disparó el
  hold (`holdFired`; en uso real el `pointerdown` siguiente lo
  reinicia) y el spoiler de UN envío vive en `spoilOnce`
  (consumido por `send()`/`sendAtt`).
- **Adjunto**: el botón `.comp-spoil` aparece SÓLO con `v-if="att"`
  y su título refleja el estado: **"Mensaje Spoiler: On/Off"**. El
  interruptor se suelta al quitar el adjunto (`cancelAtt`) y si el
  envío falla, para que el próximo archivo no salga spoiler sin
  querer.
- **Cobertura parcial**: la capa `.b-spoil-ov` ya NO tapa la hora ni
  las palomitas: `.b-meta` queda visible PINTADA ENCIMA de la capa
  (`z-index: 5` + color fijo claro legible sobre la capa oscura en
  cualquier tema). Textos: la capa dice "[ojo tachado] **Mostrar
  Spoiler**" y el control del pie "[ojo] **Ocultar**" (con texto, no
  sólo ícono; `.b-spoil-dot` ahora es una píldora con borde). i18n:
  claves nuevas 'Mostrar Spoiler', 'Ocultar', 'Mensaje Spoiler',
  'Enviado como spoiler' (fuera 'Toca para mostrar' y 'Ocultar de
  nuevo').
- Test w29 paso12 reescrito: sin botón suelto (`noSp0`), long-press
  con relleno (`holdCls`), capa cubre (`covers`/`hid`), hora visible
  (`metaVis`), textos (`ovTxtOk`/`dotTxtOk`), revelar/tapar/reabrir,
  imagen con botón "Mensaje Spoiler: On/Off" (`on2`) y galería.

## W29i — Scrollbar visible (COMPLETADO)

`scrollbar-width: thin` se veía diminuto en Gecko (Mypal/XP): pasa a
`auto` (ancho nativo) con pulgar `var(--t2)`; las reglas webkit
suben de 8 a 12 px para navegadores Chromium.

## W29j — "Mostrar Spoiler" al lado del ojo (COMPLETADO)

La capa `.b-spoil-ov` pasa de `flex-direction: column` a `row`: el
texto va en la MISMA línea que el ícono (`[ojo tachado] Mostrar
Spoiler`, `span { margin-left: 4px }` sin gap por FF78). En dos
líneas el texto caía abajo y se encimaba con la hora del `.b-meta`.
Suite w29 22/22; deploy SW v54.

## W29k — El rótulo nunca pisa la hora (COMPLETADO)

Reporte con captura: en burbujas CORTAS ("xd", min-width 74 px) el
rótulo se partía en 2 líneas y llenaba toda la burbuja, encimándose
sobre la hora (medido con sonda de geometría: el texto caía 13 px
dentro de la franja `.b-meta`; en 1 línea aún solapaba 5 px). Fix
(CSS puro):

- `.bubble.is-spoiled { min-width: 160px }` → la burbuja crece para
  que "[ojo] Mostrar Spoiler" (115 px + paddings) quepa SIN cortar.
- `.b-spoil-ov span { white-space: nowrap }` → siempre UNA línea.
- `.b-spoil-ov { align-items: flex-start }` → el rótulo queda
  ARRLIBADO ARRIBA de la burbuja (fuera de la zona de `.b-meta`);
  `span { margin-top: 2px }` lo centra a ojo contra el icono.

Verificado con sonda (burbujas de 74→160 px): `spanLines=1`,
separación sobre `.b-meta` = **-7 px**, contenido dentro de la
burbuja; captura limpia (rótulo arriba, hora/palomitas abajo). Suite
w29 22/22; deploy SW v55.

## W29l — Info del chat: modales de fijados y archivos (COMPLETADO)

Reporte con captura de prod: los accesos "Mensajes fijados" y
"Archivos y medios" quedaban como acordeones colgados y cortados al
fondo del panel, los conteos no se veían nunca (los datos solo se
cargaban al expandir) y el usuario pidió abrirlos en MODALES "con su
visualizador", contando de una los archivos y los fijados.

- **Accesos (`.pp-acts`)**: bloque fijo al fondo del panel (`flex:none`
  para que no se corte + separador superior) con dos botones con borde:
  icono + etiqueta + **badge con el conteo** (fondo `--accent`) +
  chevron "abrir"; `aria-haspopup="dialog"` y `aria-expanded` ligado al
  estado del modal (por eso w29 no se tocó).
- **Conteos "de una"**: al abrir la info se piden `GET /pins` y
  `GET /gallery` (LIMIT 200, solo metadatos); un `message_pinned` por
  WS refresca el badge vía `pinsRev`; cambiar de chat re-carga; abrir
  cada modal vuelve a pedir (números nunca viejos); cerrar la info
  apaga los modales (watcher `infoOpen`).
- **Modal de fijados** (patrón `reads-box`): velo con cierre al clicar
  fuera + cabecera con (n) + ✕; filas remitente/texto; clic = cierra
  el modal y salta al mensaje (`goPin`).
- **Modal de archivos (visor)**: cabecera con (n) + ✕; grid de
  miniaturas de 96 px con la tapa `.gal-spoil` intacta; **imagen →
  lightbox** (estado movido a `store.lb` con watcher que reinicia el
  zoom en 1x, así se abre desde la info; z-index 55 > velo 40) y
  archivo → cierra y salta (`goGal`).
- **ESC** en la cadena de `onEsc` antes del panel: visor → modal →
  panel (el visor siempre cierra primero).
- Tests: solo `w28` paso10 migró su selector `.pp-gal .pp-pinrow` →
  `.gal-veil .pp-pinrow`; w29 y w27 sin cambios (clases `pp-pinhead`,
  `pp-galgrid`, `gal-spoil` y `aria-expanded` se conservaron).

Verificado: pre-check w29 22/22 + w28 55/55 + w27 39/39, **regresión
completa 16/16** (log `/tmp/opencode/regress_w29l.log`), lint 0;
deploy **SW v56** (health 200 + marcadores por `/static/` verificados).

## W30a — E2E sin parpadeo (COMPLETADO)

Parte del reporte del amigo dev: `chatKey()` hacía un RTT a
`/e2e-key` en **cada recarga** (la clave solo se cacheaba en memoria),
así que al abrir un chat con E2E el mensaje pintaba `[Mensaje cifrado]`
y "de la nada" cambiaba a texto real (flash molesto).

- **Claves derivadas en IndexedDB** (store `chats`, DB v2 con
  `idbChatGet/Put/Del`): al derivar la AES-GCM por pareja se guarda
  `raw` + `peerPub` + `me`/`peerUid`. Al recargar se **importa la
  clave local** (sin red) → los mensajes se descifran desde el primer
  pintado.
- **Revalidación en segundo plano** (`revalidateChatKey`): tras usar la
  caché se pide la clave pública del par; si no cambió, no se hace nada
  (solo 1 petición por chat/pestaña); si cambió (el par rotó su clave)
  se rederiva, se actualiza caché/SAS y se `retryDecrypt` de todo.
- **Invalidación por fallo** (`invalidateChatKey`): si el blob no abre
  con la clave cacheada se descarta y se reintenta **una vez** con la de
  red (fallback `_e2eReFetched`); clave distinta/blob dañido de red →
  queda el marcador (silencioso, como antes).
- **Descifrar ANTES de insertar**: historial (`openChat`), paginación
  (`loadOlder`) y WS entrante (`onIncomingMessage` con `chatKeyReady`)
  descifran el blob **antes** de meterlo al store → la burbuja nace con
  texto real y el marcador del server **nunca se pinta ni un frame**.
  `upsertMessage` quedó como respaldo, enganchando `decryptInto` sobre
  el objeto **reactivo** (antes escribía sobre el crudo y Vue no se
  enteraba hasta el siguiente render ajeno).
- **Prewarm**: al abrir un chat DM con E2E se lanza `chatKey(id)` en
  paralelo con la petición del historial.
- Test w29 reforzado: paso14b añade un `MutationObserver` sobre las
  burbujas → aserción `marker is False` (el marcador jamás aparece en
  `.msgs`), además del texto descifrado y el preview con marcador.

## W30b — Emojis: cache-first + prefetch (COMPLETADO)

Segunda parte del reporte: "demasiadas solicitudes" al abrir el panel
de emojis — el SW genérico (stale-while-revalidate) **re-pedía en cada
apertura** SVGs inmutables ya cacheados.

- **`sw.js`**: rama nueva para `/static/emoji/` → **cache-first SIN
  revalidar** (los SVG self-hosted son inmutables); solo va a la red la
  1.ª vez. Queda antes del handler genérico SWR.
- **Prefetch escalonado en idle** (`prefetchEmojis` en `emoji.js`,
  llamado desde `main.js` al confirmarse `store.user`): lotes de 24
  SVG con ~220 ms entre franjas vía `requestIdleCallback` (+fallback),
  guarda de una sola vez por pestaña, respeta `saveData` y se detiene
  sin conexión (reanuda a los 3 s). Evita el "hueco azul" de la 1.ª
  apertura en conexiones lentas; el SW los cachea por la ruta normal.

Verificado: lint 0; emoji 13/13 + w13 OK; **regresión completa 16/16**
(log `/tmp/opencode/regress_w30ab.log`); **deploy SW v57** (health 200
+ marcadores W30a/W30b por `/static/` verificados).

## W30c — Preview de la lista descifrado (COMPLETADO)

Decisión del usuario: el `[Mensaje cifrado]` de la lista de chats era
molesto ("ya se sabe"). El server ya mandaba el blob `e2e` en
`last_message` (usa `message_out` completo); faltaba el cliente.

- **`decryptChatPreviews()`** (`loadChats`): recorre los DMs con blob
  E2E en `last_message` y los descifra con `decryptInto` (claves ya en
  caché de W30a → solo un AES local por chat, **sin RTT**). Se reactiva
  por reactividad Vue (objeto reactivo).
- **`previewText`** lee `lm._plain` si existe (sino `lm.body`): con
  clave → texto en claro; sin clave → el marcador del server.
- Las **notificaciones del navegador NO cambian**: `previewBody`
  (`realtime.js`) sigue devolviendo `m.body` → conservan el marcador
  (decisión W30c: solo la preview de lista se descifra).
- Tests w29: las aserciones de preview pasan de `"cifrado" in prev` a
  `secreto para ti w29` / `respuesta cifrada w29` (texto en claro).

## W30d — E2E ON por defecto "al 100%" (COMPLETADO, FEATURE GRANDE)

Decisión del usuario (como WhatsApp): claves autogeneradas/publicadas,
cifrado activo por defecto, **pero que funcione al 100%** (no se
enciende si no puede cifrar). El amigo advirtió que el boceto de clave
por IDs es más débil que el actual (HKDF+SAS) → no se adopta.

- **MI clave siempre publicada**: `ensurePublishedKey()` genera el par
  (si no existe) y hace `PUT /e2e-key` **sólo si cambió** (compara la
  huella con `fm.e2e.pub` en localStorage → no re-envía la misma clave
  en cada arranque). Se llama al confirmar la sesión (`main.js` watcher
  sobre `store.user`), al crear un DM y al activar.
- **Auto-activación al ABRIR un DM** (`maybeAutoActivate` en
  `openChat`): si el par ya publicó su clave y no la apagué, enciende
  el cifrado **solo** (comparte la misma petición de clave `chatKey`
  que el descifrado del historial → 1 request); si el par AÚN no
  publicó, queda "pendiente" y se reactiva al reabrir cuando publique.
  Corre también en re-aperturas (antes del `return` de `store.loaded`).
- **Opt-out respetado**: `store.e2eOff` (persistido en `fm.e2eoff.<uid>`)
  — apagar el switch a mano deja el chat fuera de la auto-activación;
  volver a encenderlo lo limpia. Se carga en `loadE2eState`.
- **Aviso "Pendiente"** (sólo en DMs *deseados* `store.e2eWant`, para
  no saturar los DMs viejos): estado `Pendiente` en el panel `.pp-e2e`
  + hint `pp-e2e-pend` y **tira visible en el composer**
  `e2e-pend-bar` ("Se activará cuando {n} publique sus claves"). El
  flag `e2eWant` lo marcan `createDm` (DM nuevo) y `activate`
  (intento manual), persistido en `fm.e2ewant.<uid>`.
- Test w29 migrado: JS_E2E1 **ya NO pulsa el switch** — sólo comprueba
  que quede "Activado" con SAS (auto-activación) + aserción `sw`
  (checkbox marcado).

Verificado: lint 0; w29 22/22 (paso14 migrado a auto-activación) y
**regresión completa 16/16** (log `/tmp/opencode/regress_w30cd.log`);
**deploy SW v58** (health 200 + marcadores W30c/W30d por `/static/`
verificados). Pendiente: W30e (tokens cookie HttpOnly).

## W30e — Refresh en cookie HttpOnly + logout con revocación (COMPLETADO)

Cierre del lote W30. El refresh token ya NO vive en localStorage: solo
queda el access **en memoria** y una cookie HttpOnly `fm_rt`; además
aparece `POST /api/auth/logout`, que revoca la sesión en el server.

- **Cookie `fm_rt`**: HttpOnly, Path=/api/auth, SameSite=Lax,
  max-age = REFRESH_TTL (30 d) y `Secure` si `X-Forwarded-Proto: https`
  o `url.scheme == https` (cloudflared envía el header en prod; en http
  local queda sin `Secure`). Se setea con rotación en register, verify
  (ambos returns), login, refresh, reset_password y change_password;
  se borra en logout.
- **`POST /api/auth/refresh`**: body primero (`body.refresh or cookie
  or ""`) — compat total con pruebas y sesiones legadas. Fix de
  robustez: el `or ""` final evita que `decode(None)` reviente con 500
  cuando no hay ni body ni cookie (responde 401).
- **`POST /api/auth/logout`** (nuevo, `LogoutIn.refresh` opcional):
  lee cookie > body, sube `token_version` si el `tv` coincide (invalida
  TODOS los refresh/access emitidos: una cookie robada ya no sirve),
  borra la cookie y siempre responde `{"ok":true}` (idempotente). El
  body cubre las sesiones legadas sin cookie (las inyecciones de
  pruebas).
- **Cliente** (`api.js`): flag `session.legacy`; `saveSession` escribe
  solo `{user, pendingEmail}` salvo modo legacy (las sesiones
  inyectadas con tokens se conservan intactas); `loadSession` acepta
  ambos formatos; `applyAuth` deja el refresh solo en la cookie y el
  access en memoria; el reintento 401 de `api()` y del upload XHR ya
  no exigen `session.refresh` en memoria; `refreshTokens` con
  `credentials:'same-origin'` y body `{refresh: session.refresh || ''}`;
  `logout()` dispara el POST de revocación (fire-and-forget) antes de
  `clearSession`.
- **`realtime.js`**: `connect()` sin access pero con sesión → pide
  refresh y vuelve a conectar (los WS de recarga no se quedan sin
  token); sin sesión → return.
- **Carrera encontrada y fix**: un `401` tardío tras liberarse el
  dedupe disparaba un SEGUNDO refresh cuyo `saveSession()` corría
  DESPUÉS del `clearSession` de bootstrap y reescribía `fm.session`
  (login con la clave "resucitada"). `refreshTokens` ahora aborta con
  401 si `store.hasSession` está en falso — al iniciar cada intento y
  justo al aplicar `res.ok`, antes de tocar memoria/localStorage.
- **Tests**: w6 paso9 reordenado (el logout revoca el `token_version`
  de A → re-login de A antes de consultar el perfil de C); diagnóstico
  enriquecido en el FAIL de web_e2e paso2 (raw/route/booting/ws/toasts).

Verificado: lint 0 (16 módulos); suites afectadas **6/6** (w29 22/22,
chat_ui, web_e2e, w3, w4, w6) y **regresión completa 16/16**
(`/tmp/opencode/regress_w30e.log`); **deploy SW v59 en prod** (health
200, `foxinix-shell-v59`, 9 marcadores W30e por `/static/js/api.js`,
`POST /logout` → `{"ok":true}` y `/refresh` sin token → 401). **Lote
W30 cerrado.**

## W31a–W31d — Anim única, E2E siempre activo, SAS numérico, reintentos (COMPLETADO)

Lote solicitado por el usuario (18/10/2026). Cuatro cambios de UX:

| # | Item | Archivos | Estado |
|---|------|----------|--------|
| W31a | El mensaje enviado NO re-anima al cambiar de palomita (✓→✓✓ re-disparaba la animación de aparecer) | actions.js `upsertMessage`/`finishIncoming` | ✅ `upsertMessage` preserva `_in` del objeto reemplazado (el ack REST/WS no corta ni re-dispara la anim en curso); `finishIncoming` solo marca `_in=true` en filas que NO existían antes (insert nuevo). El mensaje anima UNA vez al aparecer. |
| W31b | El código de verificación (SAS) son NÚMEROS de verdad, p. ej. `8 2 0 7 0 2` (antes 6 emojis) | e2e.js `sasOf`, chat.js template, i18n | ✅ `sasOf` → 6 dígitos (`raw[i] % 10`) con espacio; texto pasivo «Código de verificación» (sin «Compara este código…»); `SAS_EMOJI` eliminado. |
| W31c | Quitar la opción de E2E: SIEMPRE activo (sin switch, sin opt-out); aviso «Pendiente» en TODOS los DMs sin clave del par | chat.js, e2e.js, actions.js, store.js, api.js, i18n | ✅ switch/`onE2EToggle`/`activate`/`deactivate`/`e2eWantSet` eliminados; flags `fm.e2eoff.*`/`fm.e2ewant.*` retirados (localStorage se limpia en `loadE2eState`); `maybeAutoActivate` activa todo DM al abrir y marca pendiente sin filtro; estados solo «Activado»/«Pendiente» (nunca «Desactivado»). |
| W31d | Si los códigos no coinciden (clave no abre o par sin clave), la app reintenta HASTA que den los dos — sin comparación manual | e2e.js `scheduleRekey` + `decryptInto` | ✅ reintento con backoff 1s→30s (tope 12 ≈ 5 min) por chat: descarta clave local → reconsulta la pública del par → rederiva → `retryDecrypt` de todo el chat; se cancela si el chat desaparece; reintento inmediato W30a conservado como primera pasada. El usuario no compara nada. |

**Nota de seguridad**: al retirar la comparación manual SAS, la
detección de MITM activa queda delegada a la consistencia de las claves
publicadas + los reintentos automáticos (decisión del usuario).

**Tests**: w29 paso14 migrado (sin switch → `quedo-switch` si aparece;
`noswitch` + SAS numérico de 6 dígitos en el payload; runner verifica
`.isdigit()`). paso7 (anim WS) intacto.

Verificado: lint 0 (16 módulos + link OK); suites afectadas **3/3**
(w29 22/22, chat_ui, web_e2e) y **regresión completa 16/16**
(`/tmp/opencode/regress_w31.log`); **deploy SW v60 en prod** (health
200, `foxinix-shell-v60`, 3+8+3+7 marcadores W31 por `/static/js/`,
0 restos de `onE2EToggle`/«Compara este código», :8899 libre). **Lote
W31 cerrado.**

## W32 — Sin parpadeo de "[Mensaje cifrado]" (COMPLETADO)

Solicitado por el usuario (18/10/2026): los mensajes cifrados no deben
pintar el marcador del server ni "parpadear" — **que la burbuja no
aparezca hasta tener el texto descifrado**. (Las NOTIFICACIONES del
navegador siguen mostrando "[Mensaje cifrado]" — requisito intacto,
`previewBody` de realtime.js no se toca.)

- **`views/chat.js` `rows`**: filtro — si `m.e2e && m._plain == null`
  la fila NO entra en el computed (lee `e2e`/`_plain` de TODOS para
  que Vue rastree los ocultos; el agrupado corre sobre visibles).
  Cuando `decryptInto` setea `_plain` (objeto reactivo), `rows`
  re-evalúa → la fila nace ya con texto; el `Vue.watch(rows)` existente
  hace el scroll si está en stick. El MutationObserver de w29 paso14
  ("nunca pinta marcador") queda aún más fuerte.
- **Preview de la lista**: `lm.e2e && lm._plain == null` → `''`
  (sin "Tú: " con marcador; nunca "[Mensaje cifrado]" en la lista).
- **Citas (`replyStub`)** y **edición (`editDraft` ×2)**: usan
  `_plain` si existe → la cita y el draft muestran el texto real,
  nunca el marcador.
- Historial: `loadMessages` ya descifraba ANTES de insertar (filas
  nacen con texto) — sin cambios. Pines/búsqueda server-side: fuera de
  alcance (estáticos, no parpadean).

Verificado: lint 0 (16 módulos + link OK); suites afectadas **3/3**
(w29 22/22 — incluye "nunca pinta marcador" y "preview en claro",
chat_ui, web_e2e) y **regresión completa 16/16**
(`/tmp/opencode/regress_w32.log`); **deploy SW v61 en prod** (health
200, `foxinix-shell-v61`, 4+1 marcadores W32 por `/static/`, :8899
libre). **Lote W32 cerrado.**

## W33 — Icono y logo a SVG (diseño nuevo) (COMPLETADO)

Solicitado por el usuario (18/10/2026): reemplazar los WebP (diseño
desactualizado) por los SVGs nuevos que puso en la raíz del proyecto
(`icon.svg` marca / `logo.svg` marca+palabra, naranja #FF6A13).

- **Referencias web migradas**: favicon (`index.html` →
  `/static/icon.svg`, `image/svg+xml`); logo en auth ×5 y side-logo
  del sidebar (`/static/logo.svg`); avatar-zorro por defecto `.fox`
  (auth + chat ×2 → `icon.svg`); precache del SW.
- **Binaries REGENERADOS del SVG nuevo** (`rsvg-convert` + ImageMagick,
  mismas dimensiones que los originales, icono al 80 % centrado =
  safe-zone maskable): `icon.png`/`icon-512.png` (512 RGBA),
  `icon-192.png`, `apple-touch-icon.png` (180, fondo blanco como el
  original), `logo.webp` (500×200 alfa, para el MAILER — los clientes
  de email no renderizan SVG) e `icon.webp` (200 lossless, huérfano
  pero coherente). Respaldo de los viejos en
  `/tmp/opencode/old-icons/`.
- **No tocados**: manifest icons PNG (PWA/iOS), mailer.py (sigue con
  logo.webp, ya regenerado con el diseño nuevo).

Verificado: lint 0; **regresión completa 16/16**
(`/tmp/opencode/regress_w33.log` — incluye mailer_test con el webp
nuevo); **deploy SW v62 en prod** (health 200,
`foxinix-shell-v62`, `icon.svg`/`logo.svg` servidos como
`image/svg+xml`, favicon vía `/static/`, 9402B del icon-512 nuevo).
**Lote W33 cerrado.**

## W34 — Iconos de panel, slot de info, notificaciones ricas, título persistente (COMPLETADO)

Cuatro cambios solicitados por el usuario (18/10/2026):

- **W34a — iconos de contraer/abrir panel**: nuevo symbol `i-fold`
  (cuadro con flecha ← hacia donde se pliega el sidebar) para
  "Contraer menú" y `i-unfold` (flecha →) para los dos "Mostrar
  chats"; `i-menu` (hamburguesa) eliminado del sprite y de los 3
  usos. w19 intacto (usa clases, no el href).
- **W34b — info en el slot del +**: en `chat-head` se intercambiaron
  "Agregar miembros" (i-users) y el panel derecho (i-info): el + va
  primero y la info queda en el último slot. Tests por `title=`
  (w3/w29) sin impacto.
- **W34c — notificaciones del navegador con más info**: `title`
  contextual (DM = emisor; grupo = "emisor · nombre del grupo"), foto
  de perfil del emisor como `icon` (fallback avatar del chat →
  icon-192), `body` = sólo `previewBody` (el marcador
  "[Mensaje cifrado]" de e2e intacto — requisito).
- **W34d — contador del título persistente**: extraído
  `markChatRead(id)` (clear de unread + seen) usado por `openChat`;
  `finishIncoming` NO confirma visto con `document.hidden` (pestaña
  oculta); `visibilitychange` en main.js → al volver con un chat
  activo no leído cuenta como visita y limpia. El "(N) Foxinix" sólo
  se quita al ir al chat (o volver con él activo).

**Incidencia de proceso**: la primera corrida de las 5 suites afectadas
falló por un bug real mío (`const chat` eliminado de `openChat` pero
seguido usándose → ReferenceError al abrir chats) + w29 afectado por
interferencia de suites en el script (perfil compartido); w29 corrió
aislado → 22/22. Fix aplicado antes de la regresión.

Verificado: lint 0; suites w19 11/11, w3, web_e2e, chat_ui, w29 22/22
(aislado) y **regresión completa 16/16** (`/tmp/opencode/regress_w34.log`);
**deploy SW v63 en prod** (health 200, `foxinix-shell-v63`, marcadores
W34 en main/actions/realtime/chat.js, `i-fold` en `/`). **Lote W34
cerrado.**

## W35 — Enlaces multi-protocolo, imágenes inline y tarjetas de portada (COMPLETADO)

Pedido del usuario (18/10/2026): el chat debe renderizar enlaces con
cualquier protocolo (`https://`, `mailto:`, etc.), imágenes (con GIFs
animados) y páginas web (sólo la "portada": título/descripción).

- **W35a — enlaces en el texto**: `splitSegs` ahora pasa cada trozo de
  texto por `splitLinks` (antes de Twemoji) y emite segmentos `{u}`
  que la plantilla pinta como `<a class="msglink">` (target _blank +
  rel noopener). Detección por esquema con **allowlist segura**
  (https/http, ftp/ftps, mailto, tel, sms, geo, magnet, xmpp, irc,
  news, matrix, skype, tg, whatsapp, steam, spotify, market, callto):
  `javascript:`, `data:`, `vbscript:` y demás NO están en la lista,
  así que quedan como texto plano (un `javascript://…%0a…` tampoco —
  no por llevar `//` entra). Se trae la puntuación final (`,;.!?)`)
  fuera del enlace y se ignora el prefijo `algo:` no permitido
  buscando dentro del mismo texto. Sólo se enlaza con protocolo
  explícito (un `www.` suelto no).
- **W35b — imagen inline**: un segmento link con extensión de imagen
  (.png/.jpg/.gif/.webp/.bmp/.avif/.svg, con o sin query) se pinta
  como `<img class="linkimg">` dentro del texto — los `.gif` se ven
  **animados** (el servidor ya los guarda tal cual desde W28g; el
  test aserciona `n_frames > 1` en el archivo servido).
- **W35c — tarjetas de portada (unfurl)**: endpoint
  `POST /api/link-preview` (nuevo router `app/routers/links.py`,
  bucket `LINKPREVIEWS`): hace GET con User-Agent propio, sólo
  http/https, corta en 1,5 MB, sigue hasta 4 redirects validando el
  host de cada salto (SSRF: con `FOXMSG_PUBLIC_URL` fijada se bloquean
  loopback/privadas/link-local/reservadas salvo el host propio; sin
  PUBLIC_URL —entorno local/tests— se permite loopback para poder
  unfurlar contra el propio servidor de prueba), parsea og:/twitter:,
  `<title>`, description y `<link rel=icon>` con regex (sin bs4),
  devuelve `{type: page|image|link, url final, title, desc, image,
  icon, site}` y cachea 7 días en la tabla nueva `link_previews` (DB
  cifrada). Imagen remota sólo se informa (el `<img>` apunta a la URL
  original, sin re-Hostear bytes). Límite documentado: no se resuelve
  el DNS del hostname (instancia personal).
  Cliente: `ensurePreview(url)` (api.js, dedupe por URL en
  `store.linkPrev`, sin reintentos en error) sólo para links http(s)
  sin extensión de imagen; cuando la portada es `type=page` aparece
  la tarjeta `.linkcard` (favicon + título + descripción + sitio,
  clic abre la URL final) bajo el texto del mensaje; `type=image`
  reutiliza el `<img>` inline. Con E2E el unfurl viaja del cliente
  (el server ve sólo la URL del enlace, no el mensaje).
- **Tests**: nueva suite `tests/w35_test.py` (añadida a la regresión,
  ahora 17 suites): API unfurl (página→page+Foxinix, imagen→image,
  ftp/javascript→400, sin token→401), GIF animado conservado
  (Pillow `n_frames>1`), y E2E en el navegador (https/mailto
  enlazados, javascript:/data: como texto, linkimg de icon.svg
  cargada, tarjeta con título, URL del gif pegada en texto → img).

**Incidencias de proceso**: la 1ª corrida falló porque los JS de
aserción asumían el chat abierto y cada `shot()` es una carga de
página nueva (el panel volvía a Personas) — se añadió la apertura
del chat al inicio de cada JS.

Verificado: lint 0; **suite w35 14/14**; **regresión completa 17/17**
(`/tmp/opencode/regress_w35.log`); **deploy SW v64 en prod** (health
200, `foxinix-shell-v64`, marcadores W35 en chat/api/store/app.css,
`POST /api/link-preview` vivo → 401 sin token). **Lote W35 cerrado.**

## W36 — Lote de optimización y detalle de UI (COMPLETADO)

Pedido del usuario (18/10/2026), doce mejoras de acabado:

- **W36a — emojis en caché "para siempre"**: SW **v65** con
  `precacheExtras()` — baja `/static/emoji-manifest.json` (1756
  assets: 1746 SVG Twemoji + 10 GIFs de la biblioteca, generado en
  `web/emoji-manifest.json`) y los precachea en tandas de 4 con 100 ms
  de pausa, comprobando `c.match()` antes de bajar: una instalación
  cortada (navegador cerrado) REANUDA en vez de re-descargar, sin
  saturar el pool de conexiones del origen; lo que falte se baja al
  primer uso (la regla cache-first ya existía). Stickers del panel y
  fila de autocompletado se pintan con `<img>` Twemoji del sitio (la
  opción nativa `v-else` queda de red de seguridad).
- **W36b — GIF dentro del mensaje**: `.bubble.gif` con fondo
  transparente (borde/sombra quitados, radio 12px) y chip `.b-meta`
  (hora + palomitas) absoluto DENTRO del gif (abajo-derecha, z-index
  por encima del spoiler).
- **W36c — reproductores propios**: video SIN `controls` nativos —
  play/pausa al centro (56px), barra `.v-bar` abajo-izquierda
  (fullscreen, tiempo, seek, mute) y chip `.v-meta` con hora/palomitas
  DENTRO del video (la meta exterior del bubble queda `display:none`,
  sin duplicar); los controles se ocultan a los 1 s reproduciendo
  (`.vhide`) y vuelven con `mousemove`/`touchstart`; clic en el video
  alterna play. El probe `videoHeight` sigue vivo en `vMeta`
  (fallback a audio si falla). Audio adjunto: player propio (play,
  seek, tiempo, velocidad 1×/1.5×/2×) conservando el `<audio>` oculto
  en el DOM (selector `.b-afile audio` de w29 intacto); exclusión
  mutua con `currentAudioEl`.
- **W36d — "Desconectado" en el perfil**: `myStatusLine` devuelve
  `'Desconectado'` cuando `store.ws !== 'on'` (la pelotica gris ya la
  ponía `dotClass(store.user, store.ws === 'on')`).
- **W36e — pelotica doble en "Tu perfil"**: `.meprof .mp-view
  .av-wrap.on::after` a 22×22 con borde 3px (2× de los 11px
  normales).
- **W36f — añadir miembros**: symbol nuevo `i-userplus` en el sprite;
  el botón "Agregar miembros" del chat-head de grupo lo usa.
- **W36g — admins borran mensajes ajenos**: `delete_message` del
  server acepta a otro autor sólo si `chats.type == 'group'` y el rol
  propio es `owner|admin` (miembro → 403); `msgMenu` en cliente añade
  "Eliminar mensaje" (con `askDeleteMessage`) en mensajes ajenos
  cuando `activeChat.my_role` es owner/admin.
- **W36h — indicadores "(N)"**: `.pp-ncount` como texto plano "(N)"
  sin píldora (filas de fijados y archivos) y cabeceras de los
  modales con título+(N) a la izquierda y el botón cerrar al extremo
  (`<span>` + flex space-between).
- **W36i — menús con toggle**: `openCtx(e, items, anchor, key)` — el
  segundo clic del MISMO botón cierra; keys por origen
  (`'chat:'+id`, `'person:'+id`, `'info'`, `'msg:'+id). El ⋮ de la
  info usa `'info'` propia para no interferir con el de la lista.
- **W36j — panel del compositor de tamaño fijo**: `.st-panel` de
  344px en las tres pestañas (misma altura, sin salto), animación
  `pageflip` al abrir y `pgflip` (rotateY, mode out-in) al cambiar de
  pestaña — sólo transform/opacity; `clampPanel` lo recorta a la
  altura disponible en ventanas bajas (el alto fijo sólo aplica cuando
  hay sitio).
- **W36k — favoritos de GIFs**: tabla `gif_favs` + router nuevo
  `app/routers/gifs.py` (`GET/POST/DELETE /api/gifs/favorites`; nombre
  de biblioteca validado contra `web/gifs/<n>.gif`, o `media_id`
  image/* con URL firmada fresca en cada listado; bucket
  `FAVORITES` burst 10 / rate 2). Cliente: ★ en la barra flotante de
  los GIFs de mensajes (`i-star`/`i-star-fill`, sólo `kind=image` con
  `mime=image/gif`), ★ en las miniaturas de la biblioteca y sección
  "Favoritos" en la pestaña GIFs (`ensureGifFavs` perezoso e
  idempotente al pintar).
- **W36l — barra flotante encima del mensaje**: `.b-actions` a
  `top:-36px` (completa sobre la burbuja, no atravesada) con el
  picker de reacciones compensado a `-53px` (misma posición absoluta
  de siempre: −15−74 = −36−53) y `.msgs { padding-top: 40px }` para
  que la primera no se salga.
- **Tests**: nueva suite `tests/w36_test.py` (añadida a la
  regresión, ahora **18 suites**): API de favoritos (biblioteca/media
  + traversal/404/campo ausente), admin-delete 200 y 403, y E2E en el
  navegador (Desconectado con WS caído, dot 22px en el modal,
  i-userplus, toggle del ⋯, panel 344px + pageflip + stickers
  Twemoji, menú admin con "Eliminar mensaje", modal de fijados
  título+(1) y cerrar al extremo, burbuja GIF transparente con chip,
  players de audio/video con `.vhide` a los 1,3 s y meta dentro del
  video, ★ de mensaje y ★ de biblioteca con la sección Favoritos).

**Incidencias de proceso**:

1. Los endpoints de favoritos se definieron en `""` (→ `/api/gifs`)
   en vez de `"/favorites"` — 405/404 en la suite.
2. `_WEB_DIR` con `parents[1]` (un nivel menos: el router vive en
   `app/routers/`) — 404 "GIF no encontrado" en biblioteca.
3. `emoFile`/`emoSrc` usados en la plantilla de ChatShell sin estar
   en su `return` — error de render (`… is not a function`) que
   rompía el chat al abrir la pestaña Stickers.
4. El modal de fijados vive dentro del `<aside>` del panel de info:
   re-clicar el chat YA activo dispara closeChat/openChat y el
   watcher de `chat.id` cerraba el modal a mitad de uso (en el test:
   no re-abrir el chat activo; en el cliente: clave `'info'` propia).
5. `.msg.mine .bubble` ganaba por especificidad a `.bubble.gif`
   (fondo seguía naranja) — subido a `.msg .bubble.gif`.
6. **El SW v65 precachaba sin comprobar la caché**: cada `shot()`
   cerraba el navegador a mitad de instalación y el siguiente
   re-descargaba los 1756 SVG (2106 peticiones en una sola suite) —
   saturaba las 6 conexiones por host y rompía tests con carreras de
   tiempo (w29). Fix: `c.match()` antes de bajar + tandas de 4 con
   100 ms de pausa (reanuda, no re-descarga).
7. `chatMenu` compartía key con el ⋮ de la info → el toggle del W36i
   cerraba el menú de info en lugar de abrirlo (w27): key `'info'`
   propia.
8. El alto fijo (344px) impedía el `clampPanel` en ventanas bajas
   (`y = B − h` negativo → panel fuera de la caja): recorte en
   `clampPanel` sólo si no cabe.
9. Tests adaptados a los cambios de UI: w28 lee el sticker del
   `alt` del `<img>` y espera al `.st-e` (la pestaña entra con
   out-in); emoji_ui acepta el emoji del autocompletado como
   `<img alt>`; w29 espera a que pinten los mensajes antes de contar
   el "before"; w20 espera al deviceId (~1 s tras el permiso, sonda
   `enumerateDevices` confirmada) y acepta UN micrófono (la caja
   expone 1; antes exigía ≥2).
10. La precarga de emojis dentro del `install` del SW bloqueaba la
   activación (>8 s con 1756 archivos) y w4 fallaba ("SW no
   activo"): movida a segundo plano DESPUÉS de `activate` (fuera de
   `waitUntil`), con marcador `/.emoji-precache-done` en la caché y
   reanudación en el `fetch` del SW si se duerme a mitad; el
   `install` sólo precachea el shell (activación inmediata).

Verificado: lint 0; **suite w36 33/33**; **regresión completa 18/18**
(`/tmp/opencode/regress_w36_final2.log`); **deploy SW v65 en prod**
(health 200, `foxinix-shell-v65` + `maybeExtras` en `/static/sw.js`,
`/static/emoji-manifest.json` con 1756 assets,
`GET /api/gifs/favorites` → 401 sin token, `i-userplus`/`pageflip`/
`i-star-fill` presentes en chat.js/app.css/index.html). **Lote W36
cerrado.**

## W37 — Lote UI/UX + auditoría de seguridad (COMPLETADO)

Pedido del usuario (19/10/2026), diecinueve peticiones + auditoría:

- **W37a — cifrado, título y vistos**:
  - *Notificaciones con texto descifrado*: la notificación del
    navegador muestra el texto real cuando el cliente lo tiene
    (se descifra antes de notificar); sólo sin clave aparece el
    marcador `[Mensaje cifrado]`.
  - *Citas con texto descifrado*: la cita de la burbuja
    (`message_out.reply.replyText`) y la barra de respuesta del
    compositor (`.reply-bar`, `replyPreview`) resuelven `_plain` —
    antes el compositor enseñaba el marcador.
  - *Título sólo con pestaña oculta*: `refreshTitle` (main.js) suma
    `(N)` únicamente cuando `document.hidden` (watchEffect +
    visibilitychange); con la pestaña visible queda `Foxinix`.
  - *Edición E2E arreglada*: `editMessage` re-cifra con la clave del
    chat y manda SÓLO el blob (`body=''` + `e2e`); el server valida
    `was_e2e == bool(e2e)` (mezclar claro/cifrado → 400) y emite el
    campo `e2e` en el evento WS `message_edited` para que el resto
    re-descifre.
  - *Palomitas de visto*: `markChatRead` siempre envía `sendSeen`
    (apertura del chat incluida, después de cargar el historial);
    en mensajes entrantes el seen sólo se manda con la pestaña
    visible (W34d intacto).
- **W37b — UI**: barra `.b-actions` un poco más abajo sin
  "desaparecer" al acercar el ratón; selector de idioma como `<select>`
  (estándar, navegable con teclado); código de verificación escondido
  en el menú ⋯ de la información; buscador de mensajes como MODAL con
  autofocus (`.search-modal input`, cierre con Esc); menús contextuales
  con iconos (`.ctx-item .ctx-ic` en menú de lista, persona y mensaje);
  móvil: al pulsar un mensaje se abre `.ctx-sheet` (bottom sheet) en
  vez del menú flotante (`openCtx` con `isTouchUI()`).
- **W37c — animaciones**: `<transition name="veil">` en los modales
  (fade + ligera expansión) y transición de `width` en el colapso de
  paneles (sidebar). **Decisión documentada**: la transición de width
  es la ÚNICA excepción permitida a la regla "sólo transform/opacity"
  — `width` no se puede animar con transform sin reflow forzado ni
  simulación, y el colapso de paneles es de baja frecuencia; el resto
  de animaciones del lote siguen sólo transform/opacity.
- **W37d — players**:
  - *Video*: la X de descarga residual (chip `.v-meta` duplicado) se
    fue con la meta dentro del video (W36c); popup de VOLUMEN en la
    barra (mute + `.v-slider`) — al abrirlo la hora `.v-time` se
    desvanece (transition `fade`, `v-if="!vVolOpen"`); fullscreen y
    volumen YA NO hacen play/pausa (`vFull`/`vToggleVol` no llaman a
    `toggleV`); botón de descarga `.v-btn[title=Descargar]` en `.v-bar`.
  - *Videos con MIME roto*: si `<video>` dispara `error` se muestra el
    bloque `.v-err` (icono `i-alert` + "Este video tiene un error y no
    se puede reproducir") en vez de un rectángulo negro mudo — la
    cadena del MessageRow pasa a video(vidOk && !vErr) → .v-err →
    audio → archivo.
  - *Audios*: descarga del audio adjunto (`afDl`, `.au-rate[title=
    Descargar]` en `.b-afile`) y descarga de video (`vDownload`).
  - *Hora del video* se desvanece al abrir volumen (arriba).
  - *Velocidad de notas de voz*: `auRate` ciclo 1× → 1,5× → 2× en el
    player `.b-player`.
- **W37e — menciones globales**: `@everyone`/`@todos` (todos los
  miembros) y `@online`/`@activos` (sólo conectados) reconocidos
  escritos en CUALQUIER idioma (`_parse_mentions` en chats.py) y
  mostrados localizados en la burbuja (`bodySegs` → `t('@todos')` /
  `t('@activos')`, clase `m: everyone|online`); en EN se ven
  `@everyone`/`@online`.
- **W37f — auditoría de seguridad + correcciones** (informe completo
  con hallazgos priorizados; todos los fixes aplicados):
  1. **IDOR reply_to**: `send` valida que `reply_to` pertenezca al
     mismo chat (400) y `message_out` filtra la cita ajena.
  2. **IDOR `/api/media/{id}`**: el endpoint legacy sólo sirve el
     archivo a su dueño o a miembros del chat (y avatares de chat);
     404 para el resto (antes era cualquier autenticado).
  3. **IDOR favoritos de GIFs**: `_resolve(user_id)` exige que la
     media sea tuya o enviada en un chat tuyo (404 si no).
  4. **SSRF en previews de links**: `_host_ok` resuelve con
     getaddrinfo y bloquea IPs privadas/loopback/link-local (residual
     TOCTOU documentado: la resolución se repite en la conexión).
  5. **WS - llamadas**: exige membresía del EMISOR en el DM antes de
     relayear oferta/respuesta/ICE (antes: señalización arbitraria a
     cualquier DM ajeno + oráculo de presencia).
  6. **Fuga de email vía WS** (`profile` a peers): `_peer_user()`
     (auth.py) devuelve el perfil sin `email`/`email_verified` en
     `hub.emit_to_peers` — el cliente sólo usa display_name/username/
     avatar_url.
  7. **unreact cross-chat**: valida que el mensaje pertenezca al chat
     de la URL (404 si no).
  8. **CREATIONS rate limit activado**: bucket `CREATIONS` (burst 6,
     1/min) en `create_dm` (sólo si no existía), `create_group` y
     `add_member` (sólo si inserta).
  9. **Forward de E2E → 400**: "No se puede reenviar un mensaje
     cifrado de extremo a extremo" — la clave es por par ECDH, el
     blob no sirve en otro chat.
  10. **Body chunked → 411** en el middleware de main.py (los
      legítimos mandan Content-Length; antes se leía el body entero a
      ciegas).
  11. **health slimmed**: sólo `ok`/`version`/`uptime` (antes
      publicaba nº de usuarios y `media_quota_bytes`).
  12. **Rate limit sin reinicio**: `_rate` poda las entradas vencidas
      en vez de `_rate.clear()` (un atacante podía vaciar su límite
      reiniciando el tracking).
  13. **XSS almacenado en media**: `_ACTIVE_MIMES` (text/html, xhtml,
      javascript, ecmascript, xml) rechazado al subir (415) y
      neutralizado a `application/octet-stream` al servir
      (`_serve_mime`); `Content-Disposition: attachment` con filename
      siempre presente (`row["name"] or "archivo"`); SVG se mantiene
      (no ejecuta dentro de `<img>`).
  14. **mdToHtml** escapa `'` → `&#39;` (atributos con comilla simple).
- **SW v66** (cambios JS/CSS del lote).
- **Tests**: nueva suite `tests/w37_test.py` (añadida a la
  regresión, ahora **19 suites**) — 53 pasos: edición E2E end-to-end
  (B descifra el texto editado + evento WS con blob + rechazos de
  mezcla), IDORs (reply_to/media/gifs/unreact), forward E2E 400,
  health slimmed, subidas activas 415, CREATIONS 429 al 7º chat,
  menciones globales (con/sin conexión WS), relé de llamadas sólo para
  miembros, y en navegador: título sólo oculta, seen con pestaña
  oculta, buscador modal + autofocus, iconos de menús, players
  (velocidad voz 1×→1,5×, descargas de audio/video, popup de volumen
  con hora desvanecida y volume ~0.4, `.v-err` con `i-alert`),
  mención `@everyone` → `@todos`/`@everyone` por idioma y E2E en la
  UI (enviar → citar con texto descifrado → editar → B descifra lo
  que el server guardó).

**Incidencias de proceso**:

1. `replyPreview` del compositor leía `s.body` (marcador en E2E) —
   fix con `_plain` antes de verificar la cita descifrada en el test.
2. La suite subía `text/html` con body crudo → el endpoint de upload
   exige multipart (422): tests con `.html`/`.js` reales vía
   `multipart_field`.
3. Los envíos rápidos del test acumulaban puntos de SPAM (cada 429
   suma; a los 4 → bloqueo 5 min): helper `send_ok` con 1,2 s de
   pausa entre envíos en vez de pelear con el rate limit.
4. El endpoint legacy de media recibe el token por `?query` (QML no
   manda headers) — `http_status` con query, no con Authorization.
5. En `js()` los placeholders se reemplazaban en orden de kwargs: el
   bloque `«VOLBLOCK»` se insertaba DESPUÉS de sustituir `«REAL»` y
   el selector del video quedaba literal → el popup de volumen nunca
   encontraba el wrap (4 falsos negativos). VOLBLOCK primero.
6. Los `PUT` de edición devuelven **200** (no 201): los asserts de la
   suite apuntaban a 201.
7. Favoritos de GIFs exigen media image/* (un `.txt` daba 400 antes
   del chequeo de propiedad): PNG 1×1 en el test.

Verificado: lint 0; **suite w37 53/53**; **regresión completa 20/20**
(`/tmp/opencode/regress_w38_final.log`, con las suites w29/w22/w13/w6
adaptadas a los cambios de W37: título sólo oculto, código de
verificación en el menú ⋯, buscador modal y cierre animado de
modales); **deploy en prod junto con W38 (SW v67)** — W38 tocó
JS/CSS después de W37 y el despliegue es unitario (health 200,
`foxinix-shell-v67` en `/static/sw.js`). **Lote W37 cerrado.**

## W38 — Pantalla de arranque con fases + animación de cubitos (COMPLETADO)

Pedido del usuario (19/10/2026, "actualización de interfaz"):

- **W38a — animación de cubitos**: los "Cargando…" con spin pasan a
  la animación de DOS CUBOS que recorren la esquina girando
  (`.cubes`/`.cube`, keyframes `cubeSpinner` 1,8 s con retardo
  −0,9 s — sólo transform, regla FF78; color `var(--accent)`).
  La usan la carga de la conversación (`.msgs-load`); el spin queda
  sólo para los botones ocupados (Ingresar/Continuar…).
- **W38b — pantalla de arranque compartida**: componente nuevo
  `views/bootscreen.js` (`<boot-screen>`, registrado globalmente en
  main.js) con TODO centrado: icono de la app (`icon.svg`), sello
  "Cifrado de extremo a extremo" con el símbolo nuevo `i-key`,
  barra de progreso (`.bp-bar > i` con `scaleX` — sólo transform)
  y el texto de la fase. La usan el `BootView` (auth.js) y el
  overlay `.app-boot` del chat (antes: spin + "Cargando…").
- **W38c — fases reales del arranque** (`store.bootPhase` +
  `BOOT_PHASES` en store.js; barra y texto derivan de la fase):
  1. **Descargando los recursos…** — alta del SW y su caché
     (`navigator.serviceWorker.ready` con tope de 2,5 s; se ve en la
     primera visita, en las demás es instantáneo);
  2. **Iniciando sesión…** — `GET /api/users/me` con retry401
     (bootstrap, api.js);
  3. **Cargando los mensajes…** — `loadChats()` (bootAll, chat.js);
  4. **Cargando usuarios…** — `loadPeople()` + `loadBlocks()`;
  5. **Cargando vista previas…** — `warmPreviews()`: precarga las
     fotos de la lista (avatares + última imagen de cada chat + los
     perfiles), acotada a 40 imágenes y 3 s (las ondas de audio ya
     vienen con el último mensaje);
  6. **Cargando…** — instante final antes de revelar la app
     (`store.booting = false`, W27h intacto).
  Textos en i18n (EN: Downloading resources… / Signing in… / Loading
  messages… / Loading users… / Loading previews…).
- **SW v67** (+ `bootscreen.js` en la lista del shell).
- **Tests**: nueva suite `tests/w38_test.py` (añadida a la
  regresión, ahora **20 suites**) — 9 pasos: el arranque real avanza
  por las fases en orden hasta 'ready'; el overlay lleva icono +
  sello + `i-key` + barra + texto (fixed, w27 intacto); cada fase
  pinta SU texto (es y en) y la barra avanza (scaleX creciente hasta
  1); la carga del chat muestra 2 cubitos (`cubeSpinner` 1,8 s,
  retardo −0,9s, color de acento).

**Incidencias de proceso**:

1. Los bloques JS de la suite se pasaron a `shot()` sin envolver con
   el helper `js()` (W_WAIT define `sleep`) → `ReferenceError` en
   todas las shots (JSRES vacío).
2. w27 seguía pasando sin cambios: `.app-boot` conserva position
   fixed y el texto de la fase final ("Cargando…") contiene
   "Cargando" — el test no se rompe con la pantalla nueva.

Verificado: lint 0; **suite w38 9/9**; w27 y w4 OK por separado;
**regresión completa 20/20** (`/tmp/opencode/regress_w38_final.log`);
**deploy SW v67 en prod** (health 200, `foxinix-shell-v67`,
`/static/js/views/bootscreen.js` → 200, `cubeSpinner` en el css e
`i-key` en el sprite servidos). **Lote W38 cerrado.**

## W39 — Parpadeos, modal del código E2E y panel de info (COMPLETADO)

Peticiones del usuario tras el despliegue W38 (con captura):

1. **Splash sin parpadeo**: al cargar, la pantalla de arranque salía
   ARRIBA y "se acomodaba" al medio. Causa: W38b dejó `BootView` como
   `<boot-screen>` pelado y perdió el envoltorio `.boot` (flex
   centrado, `min-height: 100vh`) → se pintaba como bloque normal
   hasta que aparecía el overlay `.app-boot` fijo y centrado del
   chat. Fix: `BootView = '<div class="boot"><boot-screen></boot-screen></div>'`
   — centrado desde el primer frame (la ruta inicial es `route: 'boot'`).
2. **Envío sin parpadeo**: el mensaje "salía, se borraba y
   reaparecía". Causa: la `v-for` de las filas usaba
   `:key="r.ref.id"`; el pendiente lleva id NEGATIVO temporal y al
   llegar el ack/WS el id real cambiaba → Vue destruía y recreaba el
   nodo y `msgIn` (arranca en opacity 0) se reproducía como un envío
   nuevo. Fix: `:key="r.ref.client_msg_id || r.ref.id"` — clave
   estable entre el pendiente y su ack. Colisiones imposibles: el
   server guarda `client_msg_id = NULL` en mensajes de sistema y en
   reenvíos (INSERT sin esa columna) y es único por (chat, emisor);
   los mensajes sin cid usan el `id`.
3. **Código de verificación en MODAL**: el menú ⋯ "Ver código de
   verificación" ya no lanza un toast (se perdía en la esquina):
   activa `store.sasOpen` (+ `store.sasFor`) y abre
   `.modal.sas-modal` (transition `veil`) con icono `i-key`, los 6
   números grandes (`sasCode` computed en **ChatShell** sobre
   `store.sasFor` — el modal vive en su plantilla, no en el panel),
   pista de comparación y cierre por Esc/clic fuera/botón X (Esc
   añadido a la cadena `onEsc`). i18n EN añadido.
4. **Panel de info minimal**: fuera el estado "Activado" y el botón
   "Ver perfil completo" (`.pp-foot` del panel); queda SOLO la nota
   centrada `[llave] Cifrado de extremo a extremo`
   (`.pp-e2e-center`, icono con `margin-right` — sin `gap`, FF78). El
   aviso de par pendiente W30d se mantiene. Eliminados sin uso
   `showProfile()` y `e2eStatus`; CSS muerto `.pp-e2e-txt`,
   `.pp-e2e-sas` y `.pp-e2e-code` retirado. El perfil completo sigue
   abriéndose con un clic en la cabecera (`.pmodal` conserva su
   `.pp-foot` condicionado `v-if="!inActiveDm"`).

**Tests**: w29 adaptado — estado E2E leído de `store.e2e[CID]` (el
panel ya no dice "Activado") y SAS leído de `.sas-modal .sas-code`
con cierre del modal antes de seguir; además el paso8 espera a que
desaparezca `.tick.t-pend` antes del doble clic (el quick-react con
el id temporal daba error y el chip no aparecía — **flake** que solo
saltó en la regresión). w6 adaptado — sin `.pp-foot` en el panel y
nota `.pp-e2e-center` con su texto. w27 pasa sin cambios
(`bigLeave=false`).

SW **v68** (`foxinix-shell-v68`; solo cambian CACHE — sin módulos
nuevos en SHELL).

Verificado: lint 0 (17 módulos); **regresión 19/20 con el único
flake de w29** (`/tmp/opencode/regress_w39.log`) y **w29 22/22 dos
veces seguidas** tras la espera del ack → efectivamente 20/20;
**deploy SW v68 en prod** (servicio active, health `{"ok":true}`,
`foxinix-shell-v68` en `/static/sw.js`, `.sas-code`/`.pp-e2e-center`
en el css servido, `class="boot"` en auth.js y bootscreen → 200).
**Lote W39 cerrado.**

## W40 — Estilo de emojis configurable + iconos Material Symbols (COMPLETADO)

Peticiones del usuario: desplegable de emojis en Ajustes (Nativo /
Twemoji / Google Noto — "los de mi amigo") y que los iconos sean de
una fuente oficial tipo Material, con aspecto WhatsApp/Discord
("Outlined" — línea fina). El default es **Nativo del sistema**: cero
descargas de emoji en la netbook (era el cuello de botella).

**Fuente COLR de Twemoji (gate, investigado y descartado):** el repo
mozilla/twemoji-colr ya no publica el .ttf compilado (solo el código
fuente del pipeline `layerize`); reconstruirlo con nanoemoji no sirve
porque COLRv0 admite solo colores planos y los SVG de Twemoji usan
degradados (el font de Mozilla los resolvía por capas). Los fonts Noto
COLRv1 exigen FF125+. Decisión: Twemoji se queda como **imágenes
SVG** propias (como hasta W39) y la opción de "un solo archivo" queda
anotada como bloqueada por licencia/binario.

**Interruptor central (reactivo, sin recargar):**
- `store.prefs.emo`: `'system' | 'noto' | 'twemoji'` (default
  `'system'`) + `setPrefStr()` (variante string de `setPref`) y
  `fm.p.emo` en localStorage.
- `emoji.js`: `emoStyle()`, `emoFile()` y `emoSrc()` deciden por el
  estilo activo (system → '' → rama de texto existente; noto →
  `/static/emoji-noto/<id>.png`; twemoji → `/static/emoji/<id>.svg`).
  `splitEmojis()` ahora pone el **carácter** en el segmento (no el
  archivo) y la burbuja decide al renderizar → el cambio de estilo
  repinta picker, burbujas, chips y stickers al instante (todos los
  renderizadores ya tenían rama `<span v-else>`).
- `prefetchEmojis()`: en `'system'` NO baja nada (y no se marca como
  hecho, para poder lanzarlo si el usuario cambia de estilo);
  `'noto'` baja los PNG en idle por lotes; `'twemoji'` el lote de
  siempre.
- Ajustes → Chat: fila "Estilo de emojis" con `.emo-select`
  (Nativo del sistema / Emojis de Google / Twemoji), i18n ES/EN.

**Imágenes de Google (Noto):** 3786 PNG de 64 px (21 MB) en
`/static/emoji-noto/`, del paquete npm `emoji-datasource-google@16`
(MIT; arte Noto Color Emoji de Google, Apache-2.0 — atribución en
`emoji-noto-data.js`). El mapa char → archivo lo genera
`scripts/gen-emoji.py --noto` (nombres hex unidos por `-`, INCLUYENDO
el FE0F, a diferencia de Twemoji). Sin archivo → reserva en texto.

**SW v69:** el cliente avisa su estilo (`postMessage 'emo-style'` al
registrar y al cambiarlo — `main.js`); la precarga TOTAL de SVG del
W36a solo corre si el usuario usa Twemoji (con `system` no se
descarga NADA de emoji; `noto` lo baja el cliente en idle).
`isEmoji` cache-first cubre también `/static/emoji-noto/`.

**Iconos Material Symbols Outlined:** `scripts/gen-icons.py` reescribe
el sprite de `index.html` con las rutas oficiales de
google/material-design-icons (Apache-2.0): 57 de 58 ids `#i-*`
cambiados (viewBox `0 -960 960 960`), **los ids se conservan** (los
usan plantillas y pruebas). Solo `i-pin-off` ("Desfijar mensaje") se
queda custom — Material no tiene `push_pin_off` — con override
`#i-pin-off path` que le mantiene el trazo. `i-star` = estrella de
contorno (outlined) y `i-star-fill` = `star` de la variante rounded
(sólida). CSS `.ic`: `fill: currentColor` (antes stroke); `.tick` sin
stroke-width. El logo de Foxinix no se toca.

**Pruebas:** suite nueva `w40_test.py` (15 pasos: desplegable +
default, modo nativo en texto — picker/burbuja/chip —, Noto reactivo
+ PNG on-demand, Twemoji reactivo, persistencia tras recarga e
íntegridad del sprite + `.ic` con relleno + hoja de iconos para
captura visual); `w29` paso8 ahora elige "Emojis de Google" en
Ajustes y valida los PNG (más el check on-demand); `w36` fija
`prefs.emo='twemoji'` en su bloque de panel; `emoji_ui`/`w13`/`w28`
ya eran tolerantes (img **o** texto).

Verificado: lint 0 (18 módulos); **suite nueva w40 15/15**; **w29
23/23** (paso8 con estilo Noto elegido en el desplegable pasa);
regresión **20/21 con el único flake del paso12 de w29** (spoiler en
galería — ajeno a W40) que **pasó al re-ejecutar w29** → 21/21
(`/tmp/opencode/regress_w40.log`); **deploy SW v69 en prod** (servicio
active, health `{"ok":true}`, `foxinix-shell-v69` con `maybeEmo` en
`/static/sw.js`, `.emo-select`/`setEmo` en chat.js servido,
`/static/emoji-noto/1f525.png` → 200, `emoji-noto-data.js` servido,
viewBox `0 -960 960 960` en el sprite, `.ic { fill: currentColor }` y
el override `#i-pin-off path` en el css). Tar de deploy: 22,5 MB (los
PNG de Noto suman 21 MB).
**Lote W40 cerrado.**

## W41 — Un solo emoji se pinta grande (estilo sticker) (COMPLETADO)

Petición del usuario (con captura de referencia de WhatsApp): cuando
el mensaje contiene **UN SOLO emoji**, debe verse grande y directo
sobre el fondo del chat (como un sticker), no pequeñito dentro de una
burbuja normal. Elegido: umbral de **1 emoji exacto** y look **igual
que los stickers**.

- `emoji.js`: `isOneEmoji(txt)` — el texto coincide con una clave de
  `EMO_FILE` (exactamente un carácter-emoji del set).
- `chat.js` (MessageRow): `emoBig()` = `kind === 'text'` + no en
  edición + sin cita (`reply_to`, el bloque rompería el look
  transparente) + `isOneEmoji(body)` → la burbuja lleva la clase
  `emo-big` (reactivo: al editar o citar vuelve a burbuja normal).
- CSS: `.emo-big` comparte el look de `.bubble.sticker` (fondo
  transparente, `.b-text` a 42 px, `.emo` a 52 px — funciona en los
  tres estilos: glyph grande en nativo, PNG/SVG grande en noto/
  twemoji) y añade la **pastillita** de hora/palomitas abajo a la
  derecha (`.b-meta` absoluta, chip oscuro, como los GIF y como la
  referencia de WhatsApp).
- SW **v70** (cambian JS y CSS).

Pruebas: `w40_test.py` paso7 (3 aserciones: `.emo-big` + 42 px +
pastillita absoluta; el emoji Twemoji ~52 px; "hola 😆" y "😆😆" en
burbuja normal) — **18/18**.

Verificado: lint 0 (18 módulos); **w40 18/18** (los 3 pasos nuevos
del emoji grande pasan); **regresión completa 21/21, 0 fallos**
(`/tmp/opencode/regress_w41.log`); **deploy SW v70 en prod** (servicio
active, health `{"ok":true}`, `foxinix-shell-v70` en `/static/sw.js`,
`emoBig`/`emo-big` en chat.js, `isOneEmoji` en emoji.js y las reglas
`.bubble.emo-big` en el css servido).
**Lote W41 cerrado.**

## W42 — Pastillita de hora separada (emoji grande, GIF, sticker) (COMPLETADO)

Petición del usuario (misma referencia de WhatsApp): en W41 la
pastillita de la hora quedaba **encima** de la esquina del emoji;
debe ir en una **fila separada debajo** del contenido, y lo mismo
para **GIFs y stickers**.

- CSS (regla compartida `W42`): `.bubble.emo-big .b-meta`,
  `.bubble.gif .b-meta` y `.bubble.sticker .b-meta` → `position:
  static`, `width: max-content`, `margin-top: 6px`, pastillita oscura
  (radio 999 px, texto blanco); recibido → abajo a la izquierda,
  enviado → abajo a la derecha (`margin-left: auto`). `z-index: 5`
  la mantiene visible sobre el tapado spoiler (`z-index: 4`). Se
  eliminaron los chips ABSOLUTOS de W36b (GIF, dentro de la imagen)
  y W41 (emoji grande, encima).
- **Fondo transparente arreglado**: `.msg .bubble.sticker` /
  `.msg .bubble.emo-big` — la regla `.msg.mine .bubble` (3 clases)
  le ganaba a `.bubble.emo-big` (2 clases): en MIS mensajes la caja
  naranja tapaba el look sticker. El mismo bug latía en los stickers
  desde W28g.
- `emoji.js`: `isOneEmoji` con `.trim()` (resguardo: el autocompletado
  ":fire:" podría dejar un espacio suelto; el diagnóstico confirmó
  que no lo hace — `fireVal:"🔥"`).
- SW **v71** (cambian JS y CSS).

Pruebas: `w40_test.py` → **21/21**; el paso7 ahora exige además
fondo `rgba(0,0,0,0)` y separación geométrica (top del meta ≥
bottom del texto), con línea de diagnóstico `diag-p7`; paso8 nuevo:
GIF subido por HTTP (`ct.upload` + `media_id`) y sticker enviado
desde el panel → ambos con meta `static`, separada, pastillita y
burbuja transparente.

Verificado y CERRADO: regresión completa **21/21** (W36 adaptado:
su aserción del chip del GIF pasaba de `absolute` a `static` —
33/33 al re-ejecutar; log `/tmp/opencode/regress_w42.log`). Deploy
prod **v71** verificado: `active`, health `{"ok":true}`,
`foxinix-shell-v71`, CSS servido con la regla compartida
`position: static` y `EMO_FILE[txt.trim()]` en emoji.js.
Capturas: `/tmp/opencode/w40-7-grande.png` (emoji grande +
pastillita separada, fondo transparente) y
`/tmp/opencode/w40-8-gif-sticker.png` (GIF y sticker).

## W43 — Arreglos del reproductor de video (COMPLETADO)

Petición del usuario con capturas: (1) la barra de volumen debe ser
**vertical** porque la horizontal no cabe en videos angostos; (2) el
botón de pantalla completa debe **funcionar estando en pantalla
completa**; (3) el video debe **ajustarse a la pantalla**; (4) al
quitar el ratón del video aparecía la ✕ de "cancelar descarga"
**aunque la descarga ya terminó**.

- **Bug4 (causa raíz, diagnosticado con probe `/tmp/opencode/probe_dl.py`)**:
  Vue escribe el atributo `class` COMPLETO del marco cuando cambia un
  `:class` (`.vhide` del video se activa a los 1 s de dejar de mover
  el ratón) y **borraba `dl-done`**, que `mediadl.js` añadía a mano →
  sin `dl-done` el overlay (`.mf-ov`, creado una vez) volvía a pintar
  la ✕. Fix genérico en `mediadl.js`: estado `dl-*` como fuente de
  verdad (`setDlCls`/`syncDlCls`) y re-assert en el hook `updated` de
  la directiva (post-flush: DESPUÉS del parche de Vue). Todas las
  transiciones pasan por `setDlCls`; `chat.js` usa el nuevo export
  `markDlDone()` en `vClearDlState` (si no, el sync revertiría el
  estado). Afecta también (latente) a imágenes/players.
- **Volumen (1)**: popup `.v-vol` **vertical** (`flex-direction:
  column`) con `position: absolute` por ENCIMA del botón (`bottom:
  44px; right: 6px`, fondo negro, radio 10px); el slider va dentro de
  una caja fija `.v-vol-vt` (20×64) girado `rotate(-90deg)` (arriba =
  más alto) — sin ensanchar la barra.
- **Fullscreen (2)**: `vFull` ahora **alterna** (si
  `document.fullscreenElement === el` → `exitFullscreen()`); estado
  `vFs` con listener `fullscreenchange` (+ webkit, cleanup en
  `onUnmounted`) que cambia icono (`#i-expand` ↔ `#i-collapse`) y
  rótulo ("Pantalla completa"/"Salir de pantalla completa", i18n EN
  añadido). Icono `i-collapse` = Material `fullscreen_exit`
  (gen-icons MAP;58 iconos).
- **Ajuste (3)**: CSS `.b-video:fullscreen` (fixed, 100vw/vh, margin 0,
  bg #000) + `.b-video:fullscreen .b-vid` (`width/height: 100%`,
  `max-*: none`, `border-radius: 0`, `object-fit: contain`).
- SW **v72** (cambian JS y CSS).

Pruebas: `w36_test.py` ampliado a **37/37** con paso11b: pop-up
vertical (column, slider vertical geométrico, estrecho, por encima,
cierre), fullscreen (intento REAL primero; en headless FF no entra →
fallback con MOCK del trio fullscreenElement/request/exit que valida
la lógica del botón + icono i-collapse; `fit` real solo con
fullscreen real, si no `ruleFit` = presencia de las reglas CSS), y
"al ocultarse los controles la ✕ NO reaparece"
(`hideCls && dlKept && ovHidden && playing`).

Nota: una corrida intermedia de w36 falló de forma masiva (13 pasos)
sin reproducirse; se detectaron2 procesos Firefox `ffprof`
residuales — se atribuye a contención de perfil, no al lote.

Verificado: w36 **37/37** con perfil fresco; **regresión completa
21/21** (`/tmp/opencode/regress_w43.log`); deploy prod **v72**
activo, health OK, SW `foxinix-shell-v72`, CSS con `.v-vol-vt` y
reglas `:fullscreen`, sprite con `i-collapse`.

## W44 — Botón "ir hacia abajo" en el chat (COMPLETADO)

Petición del usuario: "que los chats tengan un botón para ir hacia
abajo" (con test mínimo, a su petición explícita).

- Botón `.jump-bottom` (36px, circular, `--float` + borde, icono
  `#i-chevron-down`) flotante sobre el compositor (`position: absolute;
  right: 18px; bottom: 66px; z-index: 10` dentro de `.chat-pane`).
- **Reaprovecha el estado existente**: `stick` (ref que ya marcaba
  "pegado al final" en `onScroll`) + `scrollBottom()` — ambos añadidos
  al `return` del setup. El botón es `v-if="!stick"`: aparece al
  scrollear arriba y se esconde solo al llegar abajo (sin lógica ni
  animación extra, a pedido de simplicidad).
- i18n EN `'Ir hacia abajo': 'Jump to bottom'`. SW **v73**.
- Prueba mínima `tests/w44_test.py` (**3/3**): DM con historial largo
  (8 mensajes multi-línea, `ct.send` reintenta los 429 que el server
  manda al sembrar), un solo shot JS: scrollTop=0 → `.jump-bottom`
  presente; clic → `scrollHeight - scrollTop - clientHeight < 8`;
  botón oculto al final.
- Verificado: lint 0; w44 **3/3**; suite del chat w23 **7/7**; deploy
  prod **v73** activo, health OK, SW `foxinix-shell-v73`, CSS con
  `.jump-bottom` e i18n con la clave nueva. `regress_w23.sh` queda en
  **22 suites** (w44 incluida al inicio de la lista).

## Notas de proceso

- Regresión entre sub-lotes; nunca correr suites locales mientras la
  regresión usa :8899; `pkill -f` con corchetes (`[r]egress`).
- Subir versión del SW ante cambios JS/CSS (W29a = v48, W29b = v49,
  W29c = v51, W29d–f = v52, W29g–i = v53, W29j = v54, W29k = v55,
  W29l = v56, W30a–b = v57, W30c–d = v58, W30e = v59, W31 = v60,
  W32 = v61, W33 = v62, W34 = v63, W35 = v64, W36 = v65, W37 = v66,
  W38 = v67, W39 = v68, W40 = v69, W41 = v70).
- FF78: sin backdrop-filter, gap, :has(), dvh, ??=, :focus-visible,
  aspect-ratio, accent-color; animaciones SOLO transform/opacity.
- Español neutro sin voseo; linter `node scripts/check-js.mjs`.
