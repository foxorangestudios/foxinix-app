# Foxinix Desktop (Tauri)

Envoltorio instalable de la misma web de Foxinix. No es un cliente
paralelo: carga `https://chat.foxinix.qzz.io/` en una ventana nativa y
recibe las actualizaciones del servidor sin reinstalar.

## Requisitos

- Node.js 20+ y Rust estable.
- Linux: `webkit2gtk-4.1`, `librsvg`, `patchelf` (para AppImage).
- Windows: WebView2 (Windows 10/11; en Windows 7/8 ya no hay soporte
  oficial de WebView2).
- macOS: WebKit del sistema.

La URL se puede cambiar sin recompilar:

```bash
FOXINIX_URL=http://127.0.0.1:8899/ npm run dev
```

Las descargas del WebView van a la carpeta **Descargas** del usuario y no
pisan archivos existentes (agregan `(1)`, `(2)`, …).

## Desarrollo

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

Los instaladores quedan en `src-tauri/target/release/bundle/`:

- Linux: `.deb`, `.rpm` y `.AppImage`.
- Windows: `.msi`/`.exe` (compilar en Windows).
- macOS: `.dmg`/`.app` (compilar en macOS).

## Notas

- La app usa la web remota para mantener una sola interfaz. Si el servidor
  no está disponible, el service worker de la web puede servir el shell y
  los medios ya guardados.
- Las descargas explícitas se guardan en el perfil del WebView (Cache
  Storage + IndexedDB) y se pueden volver a guardar desde Ajustes →
  Descargas.
- El WebView de Linux es WebKitGTK; el de Windows es WebView2 (Chromium) y
  el de macOS es WKWebView. La app web está probada para Firefox 78 y usa
  APIs estándar, pero conviene probar cada instalador en su sistema.
