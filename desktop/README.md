# Foxinix Desktop y Android (Tauri)

Envoltorio instalable de la misma web de Foxinix. No es un cliente
paralelo: carga `https://chat.foxinix.qzz.io/` en una ventana nativa o en el
WebView de Android y recibe las actualizaciones del servidor sin reinstalar.

## Plataformas

| Sistema | Paquete | Requisitos |
|---|---|---|
| Debian/Ubuntu | `.deb` amd64 | `webkit2gtk-4.1`, GTK 3, librsvg |
| Fedora | `.rpm` x86_64 | `webkit2gtk4.1`, GTK 3, librsvg |
| Arch Linux y otras | `.AppImage` x86_64 | `webkit2gtk-4.1`; FUSE 2 para ejecutar el AppImage |
| Windows 10/11 | instalador NSIS `.exe` x64 | WebView2 (lo instala el instalador si falta) |
| Android 7+ | APK arm64 | WebView moderno del sistema |

Windows 7/8 y macOS no se publican por ahora. Windows 7/8 no tienen
WebView2 oficial; en esos equipos se puede usar la web/PWA. macOS requiere
compilar en macOS.

## Icono y descripción

El icono fuente es `src-tauri/icons/icon.svg` (SVG cuadrado con el logo de
Foxinix). `tauri icon` genera los PNG, ICO, ICNS y los iconos de Android a
partir de ese archivo. La descripción, editorial, copyright y licencia se
declaran en `src-tauri/tauri.conf.json`; Linux usa esos datos para el
`.desktop` y los paquetes `.deb`/`.rpm`, y Windows para las propiedades del
instalador.

## Desarrollo

La URL se puede cambiar sin recompilar:

```bash
FOXINIX_URL=http://127.0.0.1:8899/ npm run dev
```

Las descargas del WebView de escritorio van a la carpeta **Descargas** del
usuario y no pisan archivos existentes (agregan `(1)`, `(2)`, …).

```bash
cd desktop
npm install
npm run dev
```

## Compilar

```bash
cd desktop
npm install
npm run build
```

Los paquetes quedan en `src-tauri/target/release/bundle/`:

- Linux: `.deb`, `.rpm` y `.AppImage`.
- Windows: instalador NSIS `.exe` (compilar en Windows).
- Android: APK (requiere Android SDK/NDK y Java 17; ver workflow).

El workflow `.github/workflows/release.yml` compila Linux, Windows y Android
en GitHub Actions y publica los archivos en **Releases**. Para Android usa
un keystore guardado en secretos (`ANDROID_KEY_BASE64`, `ANDROID_KEY_ALIAS`,
`ANDROID_KEY_STORE_PASSWORD`); el APK queda firmado y se verifica con
`apksigner`.

## Android

- La app carga la misma web remota por HTTPS; no incrusta una copia de la
  interfaz ni del servidor.
- Se publica un APK **arm64** para celulares modernos (Android 7 o superior).
- Pide permiso de micrófono y cámara solo cuando la web los usa (notas de
  voz, adjuntos). El cifrado E2E de los chats individuales sigue activo.
- Para actualizar hay que conservar el mismo keystore. Sin esa clave Android
  rechaza la instalación sobre la versión anterior.

## Notas

- La app usa la web remota para mantener una sola interfaz. Si el servidor
  no está disponible, el service worker de la web puede servir el shell y
  los medios ya guardados.
- Las descargas explícitas se guardan en el perfil del WebView (Cache
  Storage + IndexedDB) y se pueden volver a guardar desde Ajustes →
  Descargas.
- El WebView de Linux es WebKitGTK; el de Windows es WebView2 (Chromium), el
  de Android es el WebView del sistema y el de macOS es WKWebView. La app
  web está probada para Firefox 78 y usa APIs estándar, pero conviene probar
  cada instalador en su sistema.
