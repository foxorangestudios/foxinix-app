#!/usr/bin/env python3
"""Firma APK de Android en CI.

Tauri genera el proyecto Android en cada build. Este script agrega la
configuración de firma usando las variables de entorno y el keystore que
prepara el workflow, sin guardar credenciales en el repositorio.
"""

from pathlib import Path
import sys

ROOT = Path("src-tauri/gen/android")
GRADLE = ROOT / "app/build.gradle.kts"
MANIFEST = ROOT / "app/src/main/AndroidManifest.xml"

if not GRADLE.exists():
    sys.exit(f"No existe {GRADLE}; ejecutá primero `tauri android init`.")

gradle = GRADLE.read_text(encoding="utf-8")

if 'signingConfigs.getByName("release")' not in gradle:
    # Kotlin no importa java.util ni java.io por defecto en todos los templates.
    imports = []
    if "import java.io.FileInputStream" not in gradle:
        imports.append("import java.io.FileInputStream")
    if "import java.util.Properties" not in gradle:
        imports.append("import java.util.Properties")
    if imports:
        gradle = "\n".join(imports) + "\n" + gradle

    create_block = '''        create("release") {
            val keystorePropertiesFile = rootProject.file("keystore.properties")
            val keystoreProperties = Properties()
            if (keystorePropertiesFile.exists()) {
                keystoreProperties.load(FileInputStream(keystorePropertiesFile))
            }
            keyAlias = keystoreProperties["keyAlias"] as String
            keyPassword = keystoreProperties["password"] as String
            storeFile = file(keystoreProperties["storeFile"] as String)
            storePassword = keystoreProperties["password"] as String
        }
'''

    if "signingConfigs {" not in gradle:
        signing_block = "    signingConfigs {\n" + create_block + "    }\n\n"
        marker = "    buildTypes {"
        if marker not in gradle:
            sys.exit("No se encontró el bloque buildTypes en build.gradle.kts")
        gradle = gradle.replace(marker, signing_block + marker, 1)
    elif 'create("release")' not in gradle:
        gradle = gradle.replace(
            "signingConfigs {", "signingConfigs {\n" + create_block, 1
        )

    release_marker = 'getByName("release") {'
    if release_marker not in gradle:
        sys.exit("No se encontró el bloque release en build.gradle.kts")
    if 'signingConfig = signingConfigs.getByName("release")' not in gradle:
        gradle = gradle.replace(
            release_marker,
            release_marker
            + '\n            signingConfig = signingConfigs.getByName("release")',
            1,
        )

    GRADLE.write_text(gradle, encoding="utf-8")
    print("Configuración de firma agregada a build.gradle.kts")
else:
    print("La configuración de firma ya estaba presente")

if not MANIFEST.exists():
    sys.exit(f"No existe {MANIFEST}")

manifest = MANIFEST.read_text(encoding="utf-8")
for permission in (
    "android.permission.INTERNET",
    "android.permission.RECORD_AUDIO",
    # W54d: Wry pide este permiso junto con RECORD_AUDIO al conceder el
    # micrófono al WebView. Si no está declarado, Android rechaza el
    # paquete de permisos y la nota de voz queda sin acceso.
    "android.permission.MODIFY_AUDIO_SETTINGS",
    "android.permission.CAMERA",
):
    if permission not in manifest:
        tag = f'    <uses-permission android:name="{permission}" />\n'
        application = manifest.find("<application")
        if application != -1:
            manifest = manifest[:application] + tag + manifest[application:]
        elif "</manifest>" in manifest:
            manifest = manifest.replace("</manifest>", tag + "</manifest>", 1)
        else:
            sys.exit("AndroidManifest.xml no tiene cierre </manifest>")
        print(f"Permiso agregado: {permission}")

# W54d: el WebView ocupa toda la pantalla y el teclado debe reducir la
# ventana en vez de tapar el composer. Sin esto Android elige adjustPan
# y el campo de mensaje queda debajo del teclado.
if 'android:windowSoftInputMode="adjustResize"' not in manifest:
    activity_name = 'android:name=".MainActivity"'
    if activity_name in manifest:
        manifest = manifest.replace(
            activity_name,
            activity_name + '\n            android:windowSoftInputMode="adjustResize"',
            1,
        )
        print("windowSoftInputMode=adjustResize agregado")
    else:
        print("Aviso: no se encontró MainActivity para ajustar el teclado")

MANIFEST.write_text(manifest, encoding="utf-8")
print("AndroidManifest.xml listo")

# W54d: con edge-to-edge (Android 15+) adjustResize no achica el WebView.
# Aplicamos el inset del teclado al contenedor para que la página reciba
# un viewport más bajo y el composer quede arriba del teclado.
main_activity = next(ROOT.glob("app/src/main/java/**/MainActivity.kt"), None)
if main_activity:
    activity = main_activity.read_text(encoding="utf-8")
    if "WindowInsetsCompat.Type.ime()" not in activity:
        activity = activity.replace(
            "import androidx.activity.enableEdgeToEdge",
            "import android.view.View\n"
            "import androidx.activity.enableEdgeToEdge\n"
            "import androidx.core.view.ViewCompat\n"
            "import androidx.core.view.WindowInsetsCompat",
            1,
        )
        marker = "    super.onCreate(savedInstanceState)\n"
        if marker not in activity:
            print("Aviso: no se encontró onCreate en MainActivity.kt")
        else:
            inset_code = (
                "    val content = findViewById<View>(android.R.id.content)\n"
                "    ViewCompat.setOnApplyWindowInsetsListener(content) { view, insets ->\n"
                "      val ime = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom\n"
                "      if (view.paddingBottom != ime) {\n"
                "        view.setPadding(view.paddingLeft, view.paddingTop, view.paddingRight, ime)\n"
                "      }\n"
                "      insets\n"
                "    }\n"
                "    ViewCompat.requestApplyInsets(content)\n"
            )
            activity = activity.replace(marker, marker + inset_code, 1)
            main_activity.write_text(activity, encoding="utf-8")
            print("Inset del teclado agregado a MainActivity.kt")
    else:
        print("El inset del teclado ya estaba presente")
else:
    print("Aviso: no se encontró MainActivity.kt para ajustar el teclado")
