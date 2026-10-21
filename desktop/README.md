# Foxinix Desktop y Android (Tauri)

Envoltorio instalable de la misma web de Foxinix. No es un cliente
paralelo: carga `https://chat.foxinix.qzz.io/` en una ventana nativa o en el
WebView de Android y recibe las actualizaciones del servidor sin reinstalar.

## Plataformas

| Sistema | Paquete | Requisitos |
|---|---|---|
| Debian/Ubuntu | `.deb` amd64 | `webkit2gtk-4.1`, GTK 3, librsvg |
| Fedora | `.rpm` x86_64 | `webkit2gtk4.1`, GTK 3, librsvg |
| Arch Linux y otras | `.AppImage` x86_64 | `webkit2gtk-4.1`; FUSE 2; el AppImage ya incluye GStreamer |
| Windows 10/11 | instalador NSIS `.exe` x64 | WebView2 (lo instala el instalador si falta) |
| Android 7+ | APK arm64 / armv7 (32 bits) | WebView moderno del sistema |

Windows 7/8 y macOS no se publican por ahora. Windows 7/8 no tienen
WebView2 oficial; en esos equipos se puede usar la web/PWA. macOS requiere
compilar en macOS.

Para ejecutar el AppImage en Arch Linux:

```bash
chmod +x Foxinix-0.1.3-linux-x86_64.AppImage
./Foxinix-0.1.3-linux-x86_64.AppImage
```

Los paquetes `.deb` y `.rpm` recomiendan los plugins de GStreamer para
audio/video; en Arch el AppImage los incluye. En Debian/Ubuntu, si el
reproductor no anda, instalá `gstreamer1.0-plugins-good`,
`gstreamer1.0-plugins-bad` y `gstreamer1.0-libav`.

## Icono y descripción

El icono fuente es `src-tauri/icons/icon.svg` (SVG cuadrado con el logo de
Foxinix sobre una placa oscura y margen interno). `icon.json` es el manifiesto
de `tauri icon`: usa ese SVG para escritorio y `android-fg.svg`/`android-bg.svg`
para el icono adaptativo de Android, con el logo al 60 % para que respire
dentro de las máscaras circular, cuadrada y rounded. El comando
`tauri icon src-tauri/icons/icon.json` regenera los PNG, ICO, ICNS y los
iconos de Android. En Android, el proyecto debe existir primero
(`tauri android init --ci`): si `gen/android/app/src/main/res` ya está,
`tauri icon` escribe ahí los mipmaps; si se ejecuta antes, quedan en
`src-tauri/icons/android` y el APK conserva el icono de Tauri. La
descripción, editorial, copyright y licencia se
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
- Se publican APKs **arm64** y **armv7 (32 bits)** para Android 7 o superior.
  La pantalla de login se probó en un emulador Android 15 x86_64 con un APK
  compilado desde el mismo código.
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
