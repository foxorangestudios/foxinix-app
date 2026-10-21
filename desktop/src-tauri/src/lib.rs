//! Envoltorio de escritorio de Foxinix.
//!
//! La app carga la misma web que el navegador (una sola interfaz, sin
//! mantener un cliente paralelo). Así recibe las actualizaciones del
//! servidor sin reinstalar. El service worker y las descargas persistentes
//! de la web siguen funcionando dentro del WebView.

use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            /* FOXINIX_URL permite probar un servidor local sin recompilar
               para producción. El valor por defecto es la web pública. */
            let target = std::env::var("FOXINIX_URL")
                .unwrap_or_else(|_| "https://chat.foxinix.qzz.io/".to_string());
            let url = tauri::WebviewUrl::External(
                target.parse().expect("URL de Foxinix inválida"),
            );

            /* W50: el WebView suele dejar las descargas en el directorio
               de trabajo. Las mandamos a la carpeta Descargas del usuario
               y no pisamos archivos existentes. */
            /* En Linux sin user-dirs.dirs, download_dir puede caer al
               directorio actual; en ese caso usamos ~/Downloads. */
            let cwd = std::env::current_dir().unwrap_or_default();
            let downloads = app
                .path()
                .download_dir()
                .ok()
                .filter(|p| p.is_absolute() && *p != cwd)
                .unwrap_or_else(|| {
                    app.path()
                        .home_dir()
                        .unwrap_or(cwd)
                        .join("Downloads")
                });
            let _ = std::fs::create_dir_all(&downloads);
            let downloads_for_dl = downloads.clone();

            tauri::WebviewWindowBuilder::new(app, "main", url)
                .title("Foxinix")
                .inner_size(1180.0, 760.0)
                .min_inner_size(900.0, 600.0)
                .resizable(true)
                .on_download(move |_webview, event| {
                    if let tauri::webview::DownloadEvent::Requested {
                        destination, ..
                    } = event
                    {
                        let name = destination
                            .file_name()
                            .unwrap_or_else(|| std::ffi::OsStr::new("foxinix-download"));
                        let mut target = downloads_for_dl.join(name);
                        if target.exists() {
                            let stem = std::path::Path::new(name)
                                .file_stem()
                                .unwrap_or_else(|| std::ffi::OsStr::new("foxinix-download"))
                                .to_string_lossy()
                                .into_owned();
                            let ext = std::path::Path::new(name)
                                .extension()
                                .map(|e| format!(".{}", e.to_string_lossy()))
                                .unwrap_or_default();
                            let mut n = 1;
                            while target.exists() {
                                target = downloads_for_dl.join(format!("{stem} ({n}){ext}"));
                                n += 1;
                            }
                        }
                        *destination = target;
                    }
                    true
                })
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error al iniciar Foxinix");
}
