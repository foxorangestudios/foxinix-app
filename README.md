# 🦊 Foxinix

Centro de mensajería propio: servidor en tu máquina host `1` (firuserver) + **cliente web** (Vue 3 sin build, PWA) servido por el mismo FastAPI. Liviano: corre bien incluso en máquinas muy modestas (objetivo mínimo: Mypal 78 / Firefox 78, 1 GB de RAM).

> El cliente Python + Qt6 (PySide6/QML) de las fases 2-6 quedó **reemplazado por la web** y vive congelado en `client/` como referencia. La dirección actual es web + PWA (notificaciones del navegador, Ctrl+V, drag&drop) y un **envoltorio Tauri** en `desktop/` que carga la misma web para tener instalador de escritorio sin mantener dos interfaces.

## Estado

| Fase | Descripción | Estado |
|---|---|---|
| 0 | Scaffold + contrato API | ✅ `docs/API.md` |
| 1 | Servidor core (auth, chats, WS, media, systemd) | ✅ desplegado en firuserver |
| W1 | Frontend web: login/registro/perfil/verificación/recuperación | ✅ E2E local (`tests/web_e2e.py`) |
| W2 | Chat list + conversación + realtime (mensajes, typing, presencia, ✓✓) | ✅ E2E local (`tests/chat_ui_test.py`) |
| W3 | Media (imágenes, archivos, notas de voz, avatares), reacciones, responder, grupos | ✅ E2E local (`tests/w3_ui_test.py`) |
| W4 | Temas (claro/oscuro/acento/fondo) + PWA (manifest + service worker) | ✅ E2E local (`tests/w4_ui_test.py`) |
| W5 | Pase de rendimiento en condiciones XP + QA | ✅ auditoría FF78 (`check-js.mjs`) + 4 suites |
| W6 | Panel de usuario, perfil editable, ajustes (cuenta/apariencia/chat/atajos) y salidas seguras | ✅ E2E local (`tests/w6_ui_test.py`, 5 suites) + desplegado |
| W7 | Reacciones sincronizadas (1/usuario), emojis en el composer, menús contextuales, panel derecho = info del chat (miembros) y ventanas flotantes de perfil | ✅ E2E local (5 suites) + desplegado |
| W8 | Config solo en el engranaje (Cuenta = última pestaña; salir escondido ahí), perfil = foto/nombre/estado/bio, bios con markdown seguro, imágenes siempre WebP + lightbox con zoom, reproductor de audio propio, editar/eliminar mensajes, logo Foxinix nuevo, buscador "Buscar chats y grupos", cambiar correo/contraseña en ventanas propias | ✅ E2E local (5 suites) + desplegado |
| W9 | Restyle estilo Discord: paleta de capas grises con acento naranja Foxinix, burbujas radio 8px con meta 12px, toolbar de acciones flotante, filas de chats sin separadores, Ajustes con nav lateral agrupada (Cuenta última), estados de perfil con puntos Discord (En línea/Ausente/No molestar/Invisible) | ✅ E2E local (5 suites) + desplegado |
| W10 | Sin "Sin estado" (default En línea), iconos regenerados limpios (favicon + avatar), Ajustes con tamaño fijo (scroll interno por pestaña), español neutro en toda la app (sin voseo), **i18n ES/EN** (`js/i18n.js`, sección "Idioma de la interfaz" en Apariencia), grupo de Ajustes renombrado a "Preferencias" | ✅ E2E local (5 suites) + desplegado |
| W11 | **Media y subidas (seguridad + UX)**: rate limit de mensajes ~3/5 s por usuario (ráfaga de 5; `429` + `retry_after`; la idempotencia gana), URLs de media firmadas `/media/profile/{slug}.webp` y `/media/file/{slug}.webm` (`?exp=&sig=` HMAC, slug aleatorio de 32 hex; el token de cuenta ya no viaja en ninguna URL), subida con **círculo de progreso** en la burbuja (cancelar/reintentar, sin toast "Subiendo…"), videos adjuntables con player inline, caption en imagen/video, Ctrl+V pegar y arrastrar-y-soltar, botón de descarga en el lightbox | ✅ E2E local (5 suites) + desplegado |
| W12 | **Pulido estilo WhatsApp**: palomitas de 3 estados (✓ enviado · ✓✓ recibido por WS/fetch · ✓✓ azul leído; `last_delivered_seq` + evento WS `delivered` + semillas `peer_*_seq` en `GET /chats`), hora y palomitas en **blanco o negro automático** según la luminancia del fondo real de la burbuja (`--meta-mine`/`--meta-you`), hora visible **solo en el último mensaje del minuto** de cada emisor, **sin toasts de éxito** por acciones propias (solo quedan errores), bio y estado **borrables** vaciando el campo (`''` ≠ `None` en `ProfileIn`) | ✅ E2E local (5 suites) + desplegado |
| W13 | **WhatsApp plus**: selector de **emoji completo** (`js/emoji.js`: 6 categorías + búsqueda por nombre en español + recientes; en composer y en reacciones — **fix**: al botón de categorías le faltaba el `v-for`, el picker no abría en ningún navegador), **onda de voz** real (picos vía `AnalyserNode` al grabar → `peaks`/`dur` en el server; barra con progreso y clic para buscar posición; **fix del "0:00" eterno**: los WebM de `MediaRecorder` no traen duración y ahora se guarda la real; **notas viejas sin `dur`** resuelven su duración al reproducir vía `decodeAudioData`), **buscar dentro del chat** (panel derecho, doblegte de acentos —"cafe" encuentra "café"—, salto al mensaje con destello), **fijar/silenciar chats** (por miembro, orden fijados-primero, silenciado sin sonido/notificación y badge atenuado), **reenviar mensajes** (modal con lista+buscador, etiqueta "Reenviado", archivo compartido) y **puntos de presencia** (siempre hay puntito con usuario: verde en línea, ámbar/rojo por preset, **gris si está desconectado o invisible**; grupos sin punto) | ✅ E2E local (8 suites: `chat_ui_test`, `w6`, `w4`, `w3`, `web_e2e`, `w11_smoke`, `w13_smoke`, `w13_ui_test`) + desplegado |
| W14 | **Cifrado en reposo (SQLCipher)**: la DB de producción queda cifrada con SQLCipher (clave `FOXMSG_DB_KEY` en `.env`, driver `sqlcipher3-binary`, migración con `sqlcipher_export` + verificación de conteos/cipher_version y borrado del backup plano); dev/local sigue con SQLite en claro y las mismas 8 suites. Fix extra: fijar/silenciar re-resuelve el chat tras el `await` (race con reconexión WS) | ✅ desplegado |
| W50 | **Descargas persistentes + escritorio**: caché de medios separado del shell (sobrevive a las actualizaciones, poda por 512 MB/500 entradas, migra lo ya cacheado), descargas explícitas en `foxinix-downloads-v1` + IndexedDB con lista en Ajustes → Descargas, y app Tauri (`desktop/`) que carga la misma web con instaladores `.deb`/`.rpm`/`.AppImage` | ✅ local + Tauri probado |
| W54 | **Cáscara móvil tipo app** (la misma web que carga el APK): app bar propio con ＋ limpio y avatar a juego, barra inferior Chats/Personas/Ajustes, chat a pantalla completa, llamadas y acciones del chat en un menú ⋮, Ajustes como pestaña con la barra inferior visible, login sin tarjeta flotante y burbujas/composer con radios táctiles. El escritorio y Mypal 78 conservan la interfaz anterior | ✅ E2E local (`tests/mobile_ui_test.py`) |
| W54c | **Pulido móvil**: menús contextuales como hoja con fondo oscurecido y cabecera (foto + nombre) para chats/grupos, visor con controles fuera de la imagen, zoom con dos dedos y arrastre, editor de foto a pantalla completa con pinza/giro (sin barra ni botón Girar), tema claro legible dentro de las burbujas, sin rectángulo azul al tocar, logos del sitio en Chats/Personas/Ajustes, safe-area en barras y modales, e iconos Tauri/Android con padding y fondo propio | ✅ E2E local (`tests/mobile_ui_test.py`, `tests/w27_ui_test.py`) |
| W54d | **Teclado, micrófono y avisos**: el composer queda sobre el teclado de Android (`adjustResize`, inset nativo y `visualViewport`), permiso `MODIFY_AUDIO_SETTINGS` para que el WebView pueda pedir el micrófono, y las notificaciones E2E muestran el texto descifrado o “Nuevo mensaje”, nunca el marcador interno | ✅ E2E móvil local (`tests/mobile_ui_test.py`) + APK pendiente de prueba física |

## Estructura

```
chat/
├── server/          # FastAPI + WebSockets + SQLite
│   ├── app/         #   config, db, security, mailer, realtime, cleanup
│   │   └── routers/ #   auth, users, chats, media, ws
│   ├── web/         #   frontend Vue 3 sin build (se sirve en "/")
│   │   ├── index.html, css/, js/, vendor/vue.global.prod.js
│   ├── deploy/      #   unidad systemd
│   ├── tests/       #   e2e.sh, ws_test.py, cleanup_test.py
│   └── requirements.txt
├── client/          # PySide6 + QML — CONGELADO (superseded por server/web)
├── desktop/         # Tauri 2: instalador de escritorio que carga la misma web
├── tests/           # web_e2e.py (E2E de la UI vía Firefox headless + BiDi)
├── docs/            # API.md (contrato)
└── scripts/         # install-server.sh, remote-setup.sh, shot.py, check-js.mjs
```

## Cliente web

```bash
cd server && .venv/bin/uvicorn app.main:app --port 8899
# → http://127.0.0.1:8899/  (FastAPI sirve server/web en "/")
```

- **Sin bundler ni node**: Vue 3 global build servido desde `/static/vendor/`, módulos ES nativos.
- **Compat FF78 (W5)**: `node scripts/check-js.mjs` valida el JS como ES2020 **y** tiene lista negra de CSS/APIs posteriores a FF78. Hallazgo clave: `gap` en flexbox recién llegó en FF84 — los 34 contenedores usan **márgenes** (bloque W5 en `app.css`); reintroducir un `gap:` rompe el chequeo.
- **Sintaxis/perf**: sin blur/backdrop-filter, animaciones solo con transform/opacity, listas acotadas, avatares con `loading="lazy"`, payload frío ≈ 284 KB sin comprimir (≈90 KB con gzip en Cloudflare).
- **Descargas persistentes (W50)**: `sw.js` separa `foxinix-shell-*`, `foxinix-media-v1` y `foxinix-downloads-v1`; las actualizaciones ya no borran los medios. Las descargas explícitas se listan en **Ajustes → Descargas** y se pueden volver a guardar sin red. Se pide almacenamiento persistente al navegador.

## Cliente de escritorio (Tauri)

```bash
cd desktop
npm install
npm run dev       # desarrollo
npm run build     # instaladores en src-tauri/target/release/bundle/
```

Carga `https://chat.foxinix.qzz.io/` en una ventana nativa (se puede cambiar con `FOXINIX_URL` para probar un servidor local). No reescribe la UI: la app web sigue siendo la única interfaz. Los instaladores se publican en [**Releases**](https://github.com/foxorangestudios/foxinix-app/releases/latest); no se versionan los binarios:

- **Debian/Ubuntu:** `.deb` amd64.
- **Fedora:** `.rpm` x86_64.
- **Arch Linux y otras:** `.AppImage` x86_64.
- **Windows 10/11:** instalador NSIS `.exe` x64 (requiere WebView2; en Windows 7/8 no hay soporte oficial, usar la web/PWA).
- **Android 7+:** APKs arm64 y armv7 (32 bits) firmados, probados en emulador Android 15.

El icono SVG fuente y los detalles de compilación están en `desktop/README.md`.

## Servidor

```bash
# local
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8899

# desplegar en firuserver (host SSH "1") — sube app/ y web/
bash scripts/install-server.sh
```

Servicio: `sudo systemctl status chat-server` · logs: `journalctl -u chat-server -f`

- **Tailscale**: `http://100.125.128.82:8444` · la web queda en la raíz: `http://100.125.128.82:8444/`
- **Datos**: `~/chat-server/data/` (DB SQLite + media + `mail.log`)
- **Correos**: con `RESEND_API_KEY` en `server/.env` usa Resend; sin ella, los códigos se escriben en `data/mail.log` (modo prueba).

## Tests

```bash
# UI web (Firefox headless + WebDriver BiDi): registro → perfil → código → app
server/.venv/bin/python tests/web_e2e.py

# cáscara móvil (390x844): menús, visor, editor de foto y tema claro
server/.venv/bin/python tests/mobile_ui_test.py

# compat del frontend con Mypal 78: sintaxis ES2020 + CSS/APIs en lista negra
node scripts/check-js.mjs

# captura de pantallas: scripts/shot.py <url> <salida.png> [--js '...'] [--eval '...']
server/.venv/bin/python scripts/shot.py http://127.0.0.1:8899/ /tmp/opencode/login.png

cd server
# contra el servidor remoto (requiere DB con usuarios ana/bruno o una corrida previa del e2e)
BASE="http://100.125.128.82:8444" MAILLOG="ssh" bash tests/e2e.sh
BASE="http://100.125.128.82:8444" WSBASE="ws://100.125.128.82:8444" .venv/bin/python tests/ws_test.py
.venv/bin/python tests/cleanup_test.py
```

## Seguridad actual

- Contraseñas con **scrypt**, JWT HS256 con `token_version` (logout global al resetear contraseña).
- Códigos de verificación hasheados, cooldown de reenvío y rate limit por IP/usuario.
- Media protegida con URLs firmadas (HMAC con expiración), MIME whitelist, cuota 1 GB.
- **DB cifrada en reposo con SQLCipher** (activa en producción): la clave vive en `.env` (`FOXMSG_DB_KEY`), se aplica por conexión y sin ella la base es ilegible (robos de archivo o backup → galimbas). Activar/migrar: `PASS=123 bash scripts/encrypt-db.sh` (migra con `sqlcipher_export`, verifica conteos + `cipher_version`, borra el backup plano). Sin clave, dev/local usa SQLite normal con las mismas suites. Limitación: los archivos de `data/media/` (fotos, notas de voz) siguen en claro en disco (en tránsito van por TLS con URLs firmadas).
- Sin Docker, sin dependencias de sistema: solo Python + systemd (el driver `sqlcipher3-binary` se instala solo si `.env` tiene la clave).

## Licencia

**Foxinix App** (este repositorio) se distribuye bajo la licencia **Apache-2.0**. Consulta `LICENSE` y `NOTICE`.

**Foxinix Nitro** es un módulo y servicio privado, con licencia propietaria
y todos los derechos reservados. No forma parte de este repositorio ni queda
cubierto por Apache-2.0. Su código, pagos, licencias y configuración de
producción viven en un repositorio privado separado.

Las dependencias y recursos de terceros conservan sus propias licencias.
