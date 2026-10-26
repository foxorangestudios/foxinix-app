#!/usr/bin/env python3
"""Firma APK de Android en CI.

Tauri genera el proyecto Android en cada build. Este script agrega la
configuración de firma usando las variables de entorno y el keystore que
prepara el workflow, sin guardar credenciales en el repositorio.
"""

from pathlib import Path
import re
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
    # W55: Android 13+ pide permiso explícito para avisos; VIBRATE es
    # normal y permite que el canal de mensajes vibre.
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.VIBRATE",
    # W57: para elegir descarga automática por Wi-Fi/datos móviles.
    "android.permission.ACCESS_NETWORK_STATE",
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

# W57: guardar en Downloads/Foxinix. En Android 10+ el DownloadManager
# escribe en la colección pública sin permiso; en Android 9 o anterior
# hace falta WRITE_EXTERNAL_STORAGE (se pide en tiempo de ejecución).
for permission, max_sdk in (
    ("android.permission.WRITE_EXTERNAL_STORAGE", 28),
    ("android.permission.READ_EXTERNAL_STORAGE", 32),
):
    if permission not in manifest:
        tag = (f'    <uses-permission android:name="{permission}" '
               f'android:maxSdkVersion="{max_sdk}" />\n')
        application = manifest.find("<application")
        if application != -1:
            manifest = manifest[:application] + tag + manifest[application:]
        elif "</manifest>" in manifest:
            manifest = manifest.replace("</manifest>", tag + "</manifest>", 1)
        else:
            sys.exit("AndroidManifest.xml no tiene cierre </manifest>")
        print(f"Permiso agregado: {permission} (maxSdkVersion={max_sdk})")

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

# Rendimiento: el WebView se dibuja en la GPU. Aunque hardwareAccelerated
# suele ser true por defecto, se declara explícito para forzar el render por
# hardware en todos los dispositivos (evita software rendering en algunos).
if "android:hardwareAccelerated" not in manifest:
    manifest = manifest.replace(
        "<application",
        '<application\n        android:hardwareAccelerated="true"',
        1,
    )
    print("hardwareAccelerated=true agregado al <application>")

MANIFEST.write_text(manifest, encoding="utf-8")
print("AndroidManifest.xml listo")

# Arranque en frío: el tema base no define windowBackground, así que Android
# pinta un fondo blanco hasta que el WebView baja la web (que es oscura,
# #1e1f22). Se fija el color de la ventana al de la app para evitar ese flash.
# Vale para valores/ y values-night/: la web arranca en oscuro por defecto
# (boot.js solo cambia de tema si hay uno guardado en localStorage).
for themes_path in (
    ROOT / "app/src/main/res/values/themes.xml",
    ROOT / "app/src/main/res/values-night/themes.xml",
):
    if not themes_path.exists():
        continue
    themes = themes_path.read_text(encoding="utf-8")
    if "windowBackground" in themes:
        continue
    style_match = re.search(r"<style\b[^>]*>", themes)
    if not style_match:
        print(f"Aviso: no se encontró <style> en {themes_path.name}")
        continue
    insert_at = style_match.end()
    themes = (
        themes[:insert_at]
        + '\n        <item name="android:windowBackground">#1e1f22</item>'
        + themes[insert_at:]
    )
    themes_path.write_text(themes, encoding="utf-8")
    print(f"windowBackground=#1e1f22 agregado a {themes_path.name}")

# W54d: con edge-to-edge (Android 15+) adjustResize no achica el WebView.
# Aplicamos el inset del teclado al contenedor para que la página reciba
# un viewport más bajo y el composer quede arriba del teclado.
main_activity = next(ROOT.glob("app/src/main/java/**/MainActivity.kt"), None)
if main_activity:
    activity = main_activity.read_text(encoding="utf-8")
    if "WindowInsetsCompat.Type.ime()" not in activity:
        for imp in (
            "import android.view.View",
            "import androidx.core.view.ViewCompat",
            "import androidx.core.view.WindowInsetsCompat",
        ):
            if imp in activity:
                continue
            marker = "import androidx.activity.enableEdgeToEdge"
            if marker in activity:
                activity = activity.replace(marker, imp + "\n" + marker, 1)
            else:
                pkg = re.search(r"^package\s+[\w.]+\n", activity, re.MULTILINE)
                if pkg:
                    activity = activity[:pkg.end()] + imp + "\n" + activity[pkg.end():]
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
                "      /* W56: el inset de la barra de gestos no lo ve el CSS.\n"
                "         Se lo pasamos a boot.js; con el teclado abierto vale 0. */\n"
                "      val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())\n"
                "      val d = view.resources.displayMetrics.density\n"
                "      val safeBottom = if (ime > 0) 0 else (bars.bottom / d).toInt()\n"
                "      val safeTop = (bars.top / d).toInt()\n"
                "      val safeLeft = (bars.left / d).toInt()\n"
                "      val safeRight = (bars.right / d).toInt()\n"
                "      AndroidNotifier.rememberInsets(safeTop, safeBottom, safeLeft, safeRight)\n"
                "      val js = \"window.foxinixSetNativeInsets&&window.foxinixSetNativeInsets(\" +\n"
                "        safeTop + \",\" + safeBottom + \",\" + safeLeft + \",\" + safeRight + \")\"\n"
                "      appWebView?.post { appWebView?.evaluateJavascript(js, null) }\n"
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

# W55: Android WebView no implementa Web Notifications. Exponemos un puente
# JS mínimo que crea notificaciones nativas, respeta el permiso de Android
# 13+, usa un icono propio y abre la app al tocarlas.
if main_activity:
    activity = main_activity.read_text(encoding="utf-8")
    package_match = re.search(r"^package\s+([\w.]+)", activity, re.MULTILINE)
    package_name = package_match.group(1) if package_match else "io.foxinix.app"

    if "import android.webkit.WebView" not in activity:
        activity = activity.replace(
            "import androidx.activity.enableEdgeToEdge",
            "import android.webkit.WebView\nimport androidx.activity.enableEdgeToEdge",
            1,
        )

    has_create = bool(re.search(
        r"override fun onWebViewCreate\s*\(webView: WebView\)", activity
    ))
    if has_create:
        method_re = re.compile(
            r"(?m)^([ \t]*)override fun onWebViewCreate\(webView: WebView\) \{\n"
        )
        match = method_re.search(activity)
        if not match:
            print("Aviso: no se pudo ubicar onWebViewCreate")
        else:
            indent = match.group(1)
            if "private var appWebView" not in activity:
                activity = (
                    activity[:match.start()]
                    + indent + "private var appWebView: WebView? = null\n\n"
                    + activity[match.start():]
                )
                match = method_re.search(activity)
            # Se examina sólo el comienzo del método: ahí viven el super y
            # las inyecciones de W55/W57.
            segment = activity[match.start():match.start() + 2000]
            inject = ""
            if "appWebView = webView" not in segment:
                inject += "appWebView = webView\n"
            if "addJavascriptInterface" not in segment:
                inject += (
                    'webView.addJavascriptInterface('
                    'AndroidNotifier(this), "FoxinixAndroid")\n'
                )
            if "ViewCompat.requestApplyInsets(webView)" not in segment:
                inject += "webView.post { ViewCompat.requestApplyInsets(webView) }\n"
            if inject:
                super_re = re.compile(
                    r"(?m)^([ \t]*)super\.onWebViewCreate\(webView\)[ \t]*\n"
                )
                sm = super_re.search(activity, match.start())
                if sm:
                    body_indent = sm.group(1)
                    insert = "".join(body_indent + line + "\n"
                                     for line in inject.rstrip("\n").split("\n"))
                    activity = activity[:sm.end()] + insert + activity[sm.end():]
                else:
                    brace = activity.find("{", match.start())
                    if brace != -1:
                        body_indent = indent + "    "
                        insert = "".join(body_indent + line + "\n"
                                         for line in inject.rstrip("\n").split("\n"))
                        activity = activity[:brace + 1] + "\n" + insert + activity[brace + 1:]
        print("Puente de notificaciones agregado a MainActivity.kt")
    else:
        bridge_method = (
            "\n  private var appWebView: WebView? = null\n"
            "\n  override fun onWebViewCreate(webView: WebView) {\n"
            "    super.onWebViewCreate(webView)\n"
            "    appWebView = webView\n"
            # W66: el WebView se pinta en la GPU (más fluido al desplazar)
            # y aprovecha la caché HTTP del sistema en el arranque en frío.
            "    webView.setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null)\n"
            "    webView.settings.cacheMode = android.webkit.WebSettings.LOAD_DEFAULT\n"
            '    webView.addJavascriptInterface(AndroidNotifier(this), "FoxinixAndroid")\n'
            "    webView.post { ViewCompat.requestApplyInsets(webView) }\n"
            "  }\n"
        )
        closing = activity.rfind("}")
        if closing == -1:
            print("Aviso: no se encontró el cierre de MainActivity.kt")
        else:
            activity = activity[:closing] + bridge_method + activity[closing:]
            print("Puente de notificaciones agregado a MainActivity.kt")
    # W57: deep links desde avisos, descargas y segundo plano.
    if "import android.content.Intent" not in activity:
        activity = activity.replace(
            "import android.webkit.WebView",
            "import android.content.Intent\nimport android.webkit.WebView",
            1,
        )
    if "import android.content.pm.PackageManager" not in activity:
        activity = activity.replace(
            "import android.content.Intent",
            "import android.content.Intent\nimport android.content.pm.PackageManager",
            1,
        )
    if "import android.view.View" not in activity:
        activity = activity.replace(
            "import android.content.Intent",
            "import android.content.Intent\nimport android.view.View",
            1,
        )

    if "captureNotificationIntent(intent)" not in activity:
        create_marker = "    super.onCreate(savedInstanceState)\n"
        if create_marker in activity:
            activity = activity.replace(
                create_marker,
                create_marker + "    captureNotificationIntent(intent)\n",
                1,
            )
        else:
            print("Aviso: no se encontró onCreate para el deep link")

    target_methods = (
        "\n  /* W57: guarda el chat/mensaje del aviso y avisa al WebView.\n"
        "     Si el WebView aún no cargó, pendingTarget() lo entrega después. */\n"
        "  private fun captureNotificationIntent(intent: Intent?) {\n"
        "    val chatId = intent?.getStringExtra(\"foxinix_chat_id\") ?: return\n"
        "    val messageId = intent?.getStringExtra(\"foxinix_message_id\") ?: \"\"\n"
        "    AndroidNotifier.setPendingTarget(chatId, messageId)\n"
        "    notifyNativeTarget()\n"
        "  }\n"
        "\n"
        "  private fun notifyNativeTarget() {\n"
        "    runJs(\"window.__foxinixNativeTarget&&window.__foxinixNativeTarget()\")\n"
        "  }\n"
        "\n"
        "  /* W57: también lo usa AndroidNotifier para los popups de descarga. */\n"
        "  fun runJs(js: String) {\n"
        "    appWebView?.post { appWebView?.evaluateJavascript(js, null) }\n"
        "  }\n"
    )
    if "fun captureNotificationIntent" not in activity:
        closing = activity.rfind("}")
        if closing != -1:
            activity = activity[:closing] + target_methods + activity[closing:]

    if "override fun onNewIntent" not in activity:
        new_intent = (
            "\n  override fun onNewIntent(intent: Intent) {\n"
            "    super.onNewIntent(intent)\n"
            "    setIntent(intent)\n"
            "    captureNotificationIntent(intent)\n"
            "  }\n"
        )
        closing = activity.rfind("}")
        if closing != -1:
            activity = activity[:closing] + new_intent + activity[closing:]

    if "override fun onRequestPermissionsResult" not in activity:
        perm_method = (
            "\n  /* W57: el DownloadManager de Android 9 o anterior necesita\n"
            "     WRITE_EXTERNAL_STORAGE; al concederlo se reintenta la descarga. */\n"
            "  override fun onRequestPermissionsResult(\n"
            "    requestCode: Int,\n"
            "    permissions: Array<out String>,\n"
            "    grantResults: IntArray\n"
            "  ) {\n"
            "    super.onRequestPermissionsResult(requestCode, permissions, grantResults)\n"
            "    AndroidNotifier.onPermissionResult(requestCode, permissions, grantResults)\n"
            "    if (requestCode == 7320) {\n"
            "      AndroidNotifier.onStoragePermissionResult(\n"
            "        grantResults.isNotEmpty() &&\n"
            "          grantResults[0] == PackageManager.PERMISSION_GRANTED\n"
            "      )\n"
            "    }\n"
            "  }\n"
        )
        closing = activity.rfind("}")
        if closing != -1:
            activity = activity[:closing] + perm_method + activity[closing:]
    elif "AndroidNotifier.onPermissionResult" not in activity:
        # Proyecto generado por una versión anterior del script: enganchar
        # el callback nuevo dentro del método existente.
        activity = activity.replace(
            "    super.onRequestPermissionsResult(requestCode, permissions, grantResults)\n",
            "    super.onRequestPermissionsResult(requestCode, permissions, grantResults)\n"
            "    AndroidNotifier.onPermissionResult(requestCode, permissions, grantResults)\n",
            1,
        )

    # W57: en segundo plano NO se pausa el WebView (la WS y los avisos
    # deben seguir), pero se oculta para que Android deje de dibujarlo.
    if "override fun onPause()" in activity:
        if "appWebView?.visibility = View.INVISIBLE" not in activity:
            activity = activity.replace(
                "    super.onPause()\n",
                "    super.onPause()\n"
                "    /* W57: Wry pausa el WebView en super.onPause(); se\n"
                "       reanuda para conservar la WS, pero queda invisible. */\n"
                "    appWebView?.onResume()\n"
                "    appWebView?.visibility = View.INVISIBLE\n"
                "    runJs(\"window.foxinixNativePause&&window.foxinixNativePause()\")\n",
                1,
            )
    else:
        pause_method = (
            "\n  override fun onPause() {\n"
            "    super.onPause()\n"
            "    /* W57: ocultar el WebView detiene el dibujo sin cortar la\n"
            "       conexión ni los avisos; la UI vuelve en onResume. */\n"
            "    appWebView?.onResume()\n"
            "    appWebView?.visibility = View.INVISIBLE\n"
            "    runJs(\"window.foxinixNativePause&&window.foxinixNativePause()\")\n"
            "  }\n"
        )
        closing = activity.rfind("}")
        if closing != -1:
            activity = activity[:closing] + pause_method + activity[closing:]

    # W57b: algunos WebView pausan el JS recién en onStop. Se reanuda
    # también ahí para que la notificación siga llegando en segundo plano.
    if "override fun onStop()" in activity:
        if "appWebView?.onResume()\n" not in activity.split("override fun onStop()", 1)[1][:600]:
            activity = activity.replace(
                "    super.onStop()\n",
                "    super.onStop()\n    appWebView?.onResume()\n",
                1,
            )
    else:
        stop_method = (
            "\n  override fun onStop() {\n"
            "    super.onStop()\n"
            "    /* W57b: mantener viva la WebSocket aunque el sistema\n"
            "       detenga la actividad; el WebView sigue invisible. */\n"
            "    appWebView?.onResume()\n"
            "  }\n"
        )
        closing = activity.rfind("}")
        if closing != -1:
            activity = activity[:closing] + stop_method + activity[closing:]

    if "override fun onResume()" in activity:
        if "appWebView?.visibility = View.VISIBLE" not in activity:
            activity = activity.replace(
                "    super.onResume()\n",
                "    super.onResume()\n"
                "    appWebView?.visibility = View.VISIBLE\n"
                "    runJs(\"window.foxinixNativeResume&&window.foxinixNativeResume()\")\n",
                1,
            )
    else:
        resume_method = (
            "\n  override fun onResume() {\n"
            "    super.onResume()\n"
            "    appWebView?.visibility = View.VISIBLE\n"
            "    runJs(\"window.foxinixNativeResume&&window.foxinixNativeResume()\")\n"
            "  }\n"
        )
        closing = activity.rfind("}")
        if closing != -1:
            activity = activity[:closing] + resume_method + activity[closing:]

    print("Deep links, descargas y segundo plano listos en MainActivity.kt")
    main_activity.write_text(activity, encoding="utf-8")

    notifier = main_activity.parent / "AndroidNotifier.kt"
    notifier.write_text(
        '''package PACKAGE_NAME

import android.Manifest
import android.app.Activity
import android.app.DownloadManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Shader
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.Settings
import android.util.Base64
import android.util.LruCache
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.widget.Toast
import androidx.annotation.Keep
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.view.WindowInsetsControllerCompat
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/* W55: avisos nativos del APK. La web llama a FoxinixAndroid.notify()
   cuando está oculta; la notificación abre la app al tocarla. */
@Keep
class AndroidNotifier(private val activity: Activity) {
  private val prefs = activity.getSharedPreferences("foxinix", Context.MODE_PRIVATE)
  private val soundChannelId = "foxinix_messages_v1"
  private val silentChannelId = "foxinix_messages_silent_v1"

  /* W56: las descargas del avatar y el compositor corren fuera del hilo
     de la interfaz; una sola cola evita abrir decenas de conexiones si
     llegan mensajes seguidos. */
  private val avatarExecutor = Executors.newSingleThreadExecutor()
  private val avatarCache = object : LruCache<String, Bitmap>(6 * 1024 * 1024) {
    override fun sizeOf(key: String, value: Bitmap): Int = value.byteCount
  }
  private val appIcon: Bitmap? by lazy {
    val id = activity.applicationInfo.icon
    drawableBitmap(if (id != 0) id else R.drawable.ic_stat_foxinix)
  }

  /* W57: descargas nativas a Downloads/Foxinix. */
  private data class DownloadInfo(
    val url: String,
    val name: String,
    val mime: String,
    val type: String,
    val silent: Boolean
  )
  private val downloadIds = ConcurrentHashMap<Long, DownloadInfo>()
  private var pendingDownload: DownloadInfo? = null

  /* W58: guardado por partes en la colección pública de Descargas.
     La web manda Base64 en trozos; nunca pasamos un blob del WebView. */
  private data class PendingSave(
    val name: String,
    val stream: OutputStream,
    val uri: Uri?,
    val file: File?
  )
  private var pendingSave: PendingSave? = null
  private val downloadReceiver = object : BroadcastReceiver() {
    override fun onReceive(context: Context?, intent: Intent?) {
      if (intent?.action != DownloadManager.ACTION_DOWNLOAD_COMPLETE) return
      val id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
      if (id <= 0L) return
      val info = downloadIds.remove(id) ?: return
      var ok = false
      try {
        val manager = activity.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val cursor = manager.query(DownloadManager.Query().setFilterById(id))
        if (cursor != null) {
          cursor.use {
            if (it.moveToFirst()) {
              val status = it.getInt(
                it.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)
              )
              ok = status == DownloadManager.STATUS_SUCCESSFUL
            }
          }
        }
      } catch (e: Exception) {
        ok = false
      }
      val label = downloadTypeLabel(info.type)
      val text = if (ok) "$label guardado" else "No se pudo guardar $label"
      /* Con la app visible el popup animado lo muestra la web; este
         Toast cubre el caso de segundo plano o app cerrada. */
      activity.runOnUiThread {
        try {
          if (!activity.hasWindowFocus()) {
            Toast.makeText(activity, text, Toast.LENGTH_SHORT).show()
          }
        } catch (e: Exception) {}
      }
      notifyDownloadResult(ok, info)
    }
  }

  init {
    current = this
    try {
      val filter = IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE)
      if (Build.VERSION.SDK_INT >= 33) {
        activity.registerReceiver(downloadReceiver, filter, Context.RECEIVER_EXPORTED)
      } else {
        activity.registerReceiver(downloadReceiver, filter)
      }
    } catch (e: Exception) {
      // Si el fabricante limita receptores dinámicos, la descarga igual
      // se completa y DownloadManager muestra su propia notificación.
    }
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      val manager = activity.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
      val sound = NotificationChannel(
        soundChannelId,
        "Mensajes de Foxinix",
        NotificationManager.IMPORTANCE_HIGH
      )
      sound.description = "Mensajes nuevos de Foxinix"
      sound.enableVibration(true)
      manager.createNotificationChannel(sound)

      val silent = NotificationChannel(
        silentChannelId,
        "Mensajes silenciosos",
        NotificationManager.IMPORTANCE_DEFAULT
      )
      silent.description = "Mensajes nuevos sin sonido"
      silent.setSound(null, null)
      silent.enableVibration(false)
      manager.createNotificationChannel(silent)
    }
  }

  /* W56: Android no rellena env(safe-area-inset-bottom) dentro del
     WebView. Devolvemos el inset de la barra de navegación/gestos en dp;
     boot.js lo aplica a --sab. Con el teclado abierto devolvemos 0 para
     no sumar un hueco extra sobre el compositor. */
  @JavascriptInterface
  @Keep
  fun insets(): String = latestInsets

  /* W59: iconos de la barra de estado y de navegación según el tema.
     En claro se piden oscuros (true); en oscuro, claros (false). */
  @JavascriptInterface
  @Keep
  fun setSystemBars(light: Boolean) {
    activity.runOnUiThread {
      try {
        val controller = WindowInsetsControllerCompat(
          activity.window, activity.window.decorView
        )
        controller.isAppearanceLightStatusBars = light
        controller.isAppearanceLightNavigationBars = light
      } catch (e: Exception) {
        // Fabricantes sin soporte: la app sigue funcionando.
      }
    }
  }

  private fun notificationState(): String {
    if (Build.VERSION.SDK_INT >= 33 &&
      ContextCompat.checkSelfPermission(
        activity,
        Manifest.permission.POST_NOTIFICATIONS
      ) != PackageManager.PERMISSION_GRANTED
    ) {
      val asked = prefs.getBoolean("notif_asked", false)
      val rationale = activity.shouldShowRequestPermissionRationale(
        Manifest.permission.POST_NOTIFICATIONS
      )
      return if (asked && !rationale) "denied" else "prompt"
    }
    if (!NotificationManagerCompat.from(activity).areNotificationsEnabled()) {
      return "denied"
    }
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      val manager = activity.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
      val channel = manager.getNotificationChannel(soundChannelId)
      if (channel != null && channel.importance == NotificationManager.IMPORTANCE_NONE) {
        return "denied"
      }
    }
    return "granted"
  }

  private fun runtimeState(permissionName: String, kind: String): String {
    if (ContextCompat.checkSelfPermission(activity, permissionName) ==
      PackageManager.PERMISSION_GRANTED
    ) return "granted"
    val asked = prefs.getBoolean("perm_asked_" + kind, false)
    val rationale = activity.shouldShowRequestPermissionRationale(permissionName)
    return if (asked && !rationale) "denied" else "prompt"
  }

  private fun storageState(): String {
    if (Build.VERSION.SDK_INT > Build.VERSION_CODES.P) return "unavailable"
    return runtimeState(Manifest.permission.WRITE_EXTERNAL_STORAGE, "storage")
  }

  @JavascriptInterface
  @Keep
  fun permission(): String = notificationState()

  /* W58: estado de cada permiso para el onboarding (mismo vocabulario
     que la web: granted | prompt | denied | unavailable). */
  @JavascriptInterface
  @Keep
  fun permissionState(kind: String?): String {
    return when ((kind ?: "").lowercase()) {
      "mic" -> runtimeState(Manifest.permission.RECORD_AUDIO, "mic")
      "camera" -> runtimeState(Manifest.permission.CAMERA, "camera")
      "notif", "notification", "notifications" -> notificationState()
      "storage" -> storageState()
      else -> "unavailable"
    }
  }

  @JavascriptInterface
  @Keep
  fun storagePermission(): String = storageState()

  @JavascriptInterface
  @Keep
  fun requestPermissionFor(kind: String?): String {
    val k = (kind ?: "").lowercase()
    val permissionName = when (k) {
      "mic" -> Manifest.permission.RECORD_AUDIO
      "camera" -> Manifest.permission.CAMERA
      "notif", "notification", "notifications" -> {
        if (Build.VERSION.SDK_INT < 33) return notificationState()
        Manifest.permission.POST_NOTIFICATIONS
      }
      "storage" -> {
        if (Build.VERSION.SDK_INT > Build.VERSION_CODES.P) return "unavailable"
        Manifest.permission.WRITE_EXTERNAL_STORAGE
      }
      else -> return "unavailable"
    }
    if (ContextCompat.checkSelfPermission(activity, permissionName) ==
      PackageManager.PERMISSION_GRANTED
    ) return "granted"
    prefs.edit().putBoolean("perm_asked_" + k, true).apply()
    if (k == "notif" || k == "notification" || k == "notifications") {
      prefs.edit().putBoolean("notif_asked", true).apply()
    }
    val code = when (k) {
      "mic" -> 7401
      "camera" -> 7402
      "storage" -> 7404
      else -> 7403
    }
    activity.runOnUiThread {
      activity.requestPermissions(arrayOf(permissionName), code)
    }
    return "prompt"
  }

  @JavascriptInterface
  @Keep
  fun requestPermission() {
    if (Build.VERSION.SDK_INT < 33) return
    if (ContextCompat.checkSelfPermission(
        activity,
        Manifest.permission.POST_NOTIFICATIONS
      ) == PackageManager.PERMISSION_GRANTED
    ) {
      return
    }
    prefs.edit().putBoolean("notif_asked", true).apply()
    activity.runOnUiThread {
      activity.requestPermissions(
        arrayOf(Manifest.permission.POST_NOTIFICATIONS),
        7319
      )
    }
  }

  /* W58: pantalla de detalles de la app (permisos del sistema). */
  @JavascriptInterface
  @Keep
  fun openPermissionSettings(kind: String?) {
    activity.runOnUiThread {
      try {
        val intent = Intent(
          Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
          Uri.parse("package:" + activity.packageName)
        )
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
      } catch (e: Exception) {}
    }
  }

  @JavascriptInterface
  @Keep
  fun openSettings() {
    activity.runOnUiThread {
      try {
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
          Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName)
        } else {
          Intent(
            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
            Uri.parse("package:" + activity.packageName)
          )
        }
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity.startActivity(intent)
      } catch (e: Exception) {
        // Si el fabricante no expone esa pantalla, no bloqueamos la app.
      }
    }
  }

  /* W55: firma antigua, conservada para las webs cacheadas que todavía
     llamen a notify() sin avatar. */
  @JavascriptInterface
  @Keep
  fun notify(title: String?, body: String?, chatId: String?, sound: String?) {
    enqueue(title, body, chatId, sound, null, null)
  }

  /* W56: la web envía la foto del remitente (URL absoluta y firmada). */
  @JavascriptInterface
  @Keep
  fun notifyWithAvatar(
    title: String?,
    body: String?,
    chatId: String?,
    sound: String?,
    avatarUrl: String?
  ) {
    enqueue(title, body, chatId, sound, avatarUrl, null)
  }

  /* W57: además del chat, el mensaje exacto para abrir el chat ahí. */
  @JavascriptInterface
  @Keep
  fun notifyWithMessage(
    title: String?,
    body: String?,
    chatId: String?,
    sound: String?,
    messageId: String?
  ) {
    enqueue(title, body, chatId, sound, null, messageId)
  }

  @JavascriptInterface
  @Keep
  fun notifyWithAvatarAndMessage(
    title: String?,
    body: String?,
    chatId: String?,
    sound: String?,
    avatarUrl: String?,
    messageId: String?
  ) {
    enqueue(title, body, chatId, sound, avatarUrl, messageId)
  }

  private fun enqueue(
    title: String?,
    body: String?,
    chatId: String?,
    sound: String?,
    avatarUrl: String?,
    messageId: String?
  ) {
    if (permission() != "granted") return
    val safeTitle = if (title.isNullOrBlank()) "Foxinix" else title
    val safeBody = body ?: ""
    val safeChatId = if (chatId.isNullOrBlank()) null else chatId
    val withSound = sound == "1"
    /* La descarga del avatar no debe bloquear el hilo que atiende al
       WebView: primero se encola y la notificación sale al terminar. */
    avatarExecutor.execute {
      try {
        showNotification(
          safeTitle, safeBody, safeChatId, withSound, avatarUrl,
          if (messageId.isNullOrBlank()) null else messageId
        )
      } catch (e: Exception) {
        // Un avatar roto no puede hacer desaparecer el aviso.
      }
    }
  }

  private fun showNotification(
    title: String,
    body: String,
    chatId: String?,
    withSound: Boolean,
    avatarUrl: String?,
    messageId: String?
  ) {
    val channelId = if (withSound) soundChannelId else silentChannelId

    val intent = Intent(activity, MainActivity::class.java).apply {
      flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
      action = "foxinix.open." + (chatId ?: "") + "." + (messageId ?: "")
      if (chatId != null) putExtra("foxinix_chat_id", chatId)
      if (messageId != null) putExtra("foxinix_message_id", messageId)
    }
    /* W57: cada chat/mensaje tiene su propio PendingIntent; con uno solo
       todos los avisos abrirían el último chat que notificó. */
    val requestCode = (chatId + ":" + messageId).hashCode()
    val pending = PendingIntent.getActivity(
      activity,
      requestCode,
      intent,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    val builder = NotificationCompat.Builder(activity, channelId)
      .setSmallIcon(R.drawable.ic_stat_foxinix)
      .setContentTitle(title)
      .setContentText(body)
      .setStyle(NotificationCompat.BigTextStyle().bigText(body))
      .setContentIntent(pending)
      .setAutoCancel(true)
      .setPriority(NotificationCompat.PRIORITY_HIGH)
      .setCategory(NotificationCompat.CATEGORY_MESSAGE)
      .setOnlyAlertOnce(false)
      .setWhen(System.currentTimeMillis())
      .setColor(0xFFFF751F.toInt())

    val large = buildLargeIcon(avatarUrl)
    if (large != null) builder.setLargeIcon(large)

    if (withSound) {
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
        builder.setDefaults(NotificationCompat.DEFAULT_SOUND or NotificationCompat.DEFAULT_VIBRATE)
      }
    } else {
      builder.setSilent(true)
    }

    val id = if (chatId == null) {
      System.currentTimeMillis().toInt()
    } else {
      chatId.hashCode()
    }
    try {
      NotificationManagerCompat.from(activity).notify(id, builder.build())
    } catch (e: SecurityException) {
      // Sin permiso del sistema no hay nada más que hacer.
    }
  }

  /* W56: icono de la app como imagen grande por defecto. La foto del
     remitente se recorta en círculo y lleva el icono de Foxinix abajo a
     la derecha, como en la referencia de escritorio. */
  private fun drawableBitmap(id: Int): Bitmap? {
    return try {
      val d = ContextCompat.getDrawable(activity, id) ?: return null
      val w = if (d.intrinsicWidth > 0) d.intrinsicWidth else 192
      val h = if (d.intrinsicHeight > 0) d.intrinsicHeight else 192
      val out = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
      val canvas = Canvas(out)
      d.setBounds(0, 0, w, h)
      d.draw(canvas)
      out
    } catch (e: Exception) {
      null
    }
  }

  private fun buildLargeIcon(avatarUrl: String?): Bitmap? {
    val app = appIcon
    if (avatarUrl.isNullOrBlank()) return app
    val avatar = loadAvatar(avatarUrl) ?: return app

    val size = 192
    val out = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(out)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    val square = centerSquare(avatar, size)
    paint.shader = BitmapShader(square, Shader.TileMode.CLAMP, Shader.TileMode.CLAMP)
    canvas.drawCircle(size / 2f, size / 2f, size / 2f, paint)

    if (app != null) {
      val badgeSize = (size * .36f).toInt()
      val badge = Bitmap.createScaledBitmap(app, badgeSize, badgeSize, true)
      val cx = size - badgeSize * .86f
      val cy = size - badgeSize * .86f
      val ring = Paint(Paint.ANTI_ALIAS_FLAG)
      ring.color = 0xFFFFFFFF.toInt()
      /* Un aro blanco separa el icono de la foto aunque el fondo de la
         foto sea claro. */
      canvas.drawCircle(cx, cy, badgeSize * .60f, ring)
      canvas.drawBitmap(badge, cx - badgeSize / 2f, cy - badgeSize / 2f, null)
    }
    return out
  }

  private fun centerSquare(src: Bitmap, size: Int): Bitmap {
    val side = if (src.width < src.height) src.width else src.height
    val x = (src.width - side) / 2
    val y = (src.height - side) / 2
    val crop = Bitmap.createBitmap(src, x, y, side, side)
    return Bitmap.createScaledBitmap(crop, size, size, true)
  }

  private fun loadAvatar(url: String): Bitmap? {
    avatarCache.get(url)?.let { return it }
    var conn: HttpURLConnection? = null
    return try {
      val parsed = URL(url)
      if (parsed.protocol != "https" && parsed.protocol != "http") return null
      val connection = (parsed.openConnection() as HttpURLConnection).apply {
        connectTimeout = 3000
        readTimeout = 4000
        instanceFollowRedirects = true
        setRequestProperty("Accept", "image/*")
        setRequestProperty("User-Agent", "Foxinix-Android")
        CookieManager.getInstance().getCookie(url)?.let { setRequestProperty("Cookie", it) }
      }
      conn = connection
      if (connection.responseCode !in 200..299) return null
      val bytes = connection.inputStream.use { it.readBytes() }
      if (bytes.size > 3 * 1024 * 1024) return null
      val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
      avatarCache.put(url, bitmap)
      bitmap
    } catch (e: Exception) {
      null
    } finally {
      conn?.disconnect()
    }
  }

  /* W57: destino pendiente de una notificación (se vacía al leerlo). */
  @JavascriptInterface
  @Keep
  fun pendingTarget(): String {
    val value = pendingTargetJson
    pendingTargetJson = ""
    return value
  }

  /* W57: red activa para decidir las descargas automáticas. */
  @JavascriptInterface
  @Keep
  fun networkType(): String {
    return try {
      val cm = activity.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
      val net = cm.activeNetwork ?: return "none"
      val caps = cm.getNetworkCapabilities(net) ?: return "none"
      when {
        caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
        caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "mobile"
        else -> "other"
      }
    } catch (e: Exception) {
      "none"
    }
  }

  /* W57: guarda la URL firmada en Downloads/Foxinix con DownloadManager.
     silent=true evita el aviso nativo de inicio (descarga automática). */
  @JavascriptInterface
  @Keep
  fun download(
    url: String?,
    name: String?,
    mime: String?,
    type: String?,
    silent: Boolean
  ): Boolean {
    val cleanUrl = url ?: return false
    val parsed = try { Uri.parse(cleanUrl) } catch (e: Exception) { return false }
    val scheme = parsed.scheme ?: return false
    if (scheme != "https" && scheme != "http") return false
    val info = DownloadInfo(
      cleanUrl,
      sanitizeName(name),
      mime ?: "",
      if (type.isNullOrBlank()) "file" else type,
      silent
    )
    if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P &&
      ContextCompat.checkSelfPermission(
        activity,
        Manifest.permission.WRITE_EXTERNAL_STORAGE
      ) != PackageManager.PERMISSION_GRANTED
    ) {
      pendingDownload = info
      activity.runOnUiThread {
        activity.requestPermissions(
          arrayOf(Manifest.permission.WRITE_EXTERNAL_STORAGE),
          7320
        )
      }
      return true
    }
    return startDownload(info)
  }

  private fun startDownload(info: DownloadInfo): Boolean {
    return try {
      val manager = activity.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
      val unique = uniqueName(info.name)
      val request = DownloadManager.Request(Uri.parse(info.url))
        .setTitle(unique)
        .setDescription("Descarga de Foxinix")
        .setNotificationVisibility(
          DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED
        )
        .setDestinationInExternalPublicDir(
          Environment.DIRECTORY_DOWNLOADS,
          "Foxinix/$unique"
        )
        .setAllowedOverMetered(true)
        .setAllowedOverRoaming(false)
      if (info.mime.isNotBlank()) request.setMimeType(info.mime)
      val id = manager.enqueue(request)
      downloadIds[id] = info
      true
    } catch (e: Exception) {
      notifyDownloadResult(false, info)
      false
    }
  }

  private fun storageResult(granted: Boolean) {
    val info = pendingDownload
    pendingDownload = null
    if (info == null) return
    if (granted) {
      startDownload(info)
    } else {
      notifyDownloadResult(false, info)
    }
  }

  /* W58: resultado unificado para el onboarding web. */
  private fun permissionResult(
    requestCode: Int,
    permissions: Array<out String>,
    grantResults: IntArray
  ) {
    val kind = when (requestCode) {
      7401 -> "mic"
      7402 -> "camera"
      7403 -> "notif"
      7404 -> "storage"
      else -> return
    }
    val granted = grantResults.isNotEmpty() &&
      grantResults[0] == PackageManager.PERMISSION_GRANTED
    val permissionName = permissions.firstOrNull()
    val state = if (granted) {
      "granted"
    } else {
      val rationale = if (permissionName != null) {
        try {
          activity.shouldShowRequestPermissionRationale(permissionName)
        } catch (e: Exception) { false }
      } else false
      if (prefs.getBoolean("perm_asked_" + kind, false) && !rationale) "denied" else "prompt"
    }
    prefs.edit().putString("perm_state_" + kind, state).apply()
    val js = "window.__foxinixPermissionResult&&window.__foxinixPermissionResult(" +
      JSONObject.quote(kind) + "," + JSONObject.quote(state) + ")"
    (activity as? MainActivity)?.runJs(js)
  }

  /* W58: descarga nativa por partes a Descargas/Foxinix (MediaStore en
     Android 10+, File en Android 9 o anterior). Devuelve "ok" o un
     código que la web traduce a un permiso/error. */
  @JavascriptInterface
  @Keep
  @Synchronized
  fun beginSave(name: String?, mime: String?, size: Long): String {
    cancelSave()
    if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P &&
      ContextCompat.checkSelfPermission(
        activity,
        Manifest.permission.WRITE_EXTERNAL_STORAGE
      ) != PackageManager.PERMISSION_GRANTED
    ) return "permission"
    val safeName = sanitizeName(name)
    val safeMime = if (mime.isNullOrBlank()) "application/octet-stream" else mime
    return try {
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        val resolver = activity.contentResolver
        val unique = uniqueMediaName(safeName)
        val values = ContentValues().apply {
          put(MediaStore.Downloads.DISPLAY_NAME, unique)
          put(MediaStore.Downloads.MIME_TYPE, safeMime)
          put(
            MediaStore.Downloads.RELATIVE_PATH,
            Environment.DIRECTORY_DOWNLOADS + "/Foxinix/"
          )
          put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = resolver.insert(
          MediaStore.Downloads.EXTERNAL_CONTENT_URI,
          values
        ) ?: return "error"
        val out = resolver.openOutputStream(uri) ?: run {
          resolver.delete(uri, null, null)
          return "error"
        }
        pendingSave = PendingSave(unique, out, uri, null)
      } else {
        val dir = File(
          Environment.getExternalStoragePublicDirectory(
            Environment.DIRECTORY_DOWNLOADS
          ),
          "Foxinix"
        )
        if (!dir.exists() && !dir.mkdirs()) return "error"
        val file = File(dir, uniqueName(safeName))
        pendingSave = PendingSave(file.name, FileOutputStream(file), null, file)
      }
      "ok"
    } catch (e: Exception) {
      cancelSave()
      "error"
    }
  }

  @JavascriptInterface
  @Keep
  @Synchronized
  fun appendSave(base64: String?): Boolean {
    val save = pendingSave ?: return false
    return try {
      val data = Base64.decode(base64 ?: "", Base64.NO_WRAP)
      save.stream.write(data)
      true
    } catch (e: Exception) {
      cancelSave()
      false
    }
  }

  @JavascriptInterface
  @Keep
  @Synchronized
  fun finishSave(): String {
    val save = pendingSave ?: return "error"
    pendingSave = null
    return try {
      save.stream.flush()
      save.stream.close()
      if (save.uri != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        val values = ContentValues().apply {
          put(MediaStore.Downloads.IS_PENDING, 0)
        }
        activity.contentResolver.update(save.uri, values, null, null)
      }
      "ok:" + save.name
    } catch (e: Exception) {
      try { save.stream.close() } catch (e2: Exception) {}
      if (save.uri != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        try { activity.contentResolver.delete(save.uri, null, null) } catch (e2: Exception) {}
      }
      if (save.file != null) {
        try { save.file.delete() } catch (e2: Exception) {}
      }
      "error"
    }
  }

  @JavascriptInterface
  @Keep
  @Synchronized
  fun cancelSave() {
    val save = pendingSave ?: return
    pendingSave = null
    try { save.stream.close() } catch (e: Exception) {}
    if (save.uri != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
      try { activity.contentResolver.delete(save.uri, null, null) } catch (e: Exception) {}
    }
    if (save.file != null) {
      try { save.file.delete() } catch (e: Exception) {}
    }
  }

  private fun uniqueMediaName(raw: String): String {
    val name = sanitizeName(raw)
    val dot = name.lastIndexOf('.')
    val base = if (dot > 0) name.substring(0, dot) else name
    val ext = if (dot > 0) name.substring(dot) else ""
    var candidate = name
    var n = 1
    val rel = Environment.DIRECTORY_DOWNLOADS + "/Foxinix/"
    while (mediaNameExists(candidate, rel) && n < 1000) {
      candidate = base + " (" + n + ")" + ext
      n++
    }
    return candidate
  }

  private fun mediaNameExists(name: String, rel: String): Boolean {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return false
    return try {
      val projection = arrayOf(MediaStore.Downloads._ID)
      val selection =
        MediaStore.Downloads.DISPLAY_NAME + "=? AND " +
        MediaStore.Downloads.RELATIVE_PATH + "=?"
      val cursor = activity.contentResolver.query(
        MediaStore.Downloads.EXTERNAL_CONTENT_URI,
        projection,
        selection,
        arrayOf(name, rel),
        null
      )
      cursor?.use { it.moveToFirst() } ?: false
    } catch (e: Exception) {
      false
    }
  }

  private fun uniqueName(raw: String): String {
    val name = sanitizeName(raw)
    val dir = File(
      Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
      "Foxinix"
    )
    try { if (!dir.exists()) dir.mkdirs() } catch (e: Exception) {}
    val dot = name.lastIndexOf('.')
    val base = if (dot > 0) name.substring(0, dot) else name
    val ext = if (dot > 0) name.substring(dot) else ""
    var candidate = name
    var n = 1
    while (File(dir, candidate).exists() && n < 1000) {
      candidate = base + " (" + n + ")" + ext
      n++
    }
    return candidate
  }

  private fun notifyDownloadResult(ok: Boolean, info: DownloadInfo) {
    val json = JSONObject()
      .put("ok", ok)
      .put("type", info.type)
      .put("name", info.name)
      .toString()
    val fn = if (ok) "__foxinixDownloadDone" else "__foxinixDownloadError"
    val js = "window.$fn&&window.$fn(" + JSONObject.quote(json) + ")"
    (activity as? MainActivity)?.runJs(js)
  }

  private fun sanitizeName(raw: String?): String {
    var name = (raw ?: "archivo").replace(
      Regex("[\\\\/:*?\\\"<>|\\\\p{Cntrl}]"),
      "_"
    ).trim()
    if (name.isBlank()) name = "archivo"
    if (name.length > 120) {
      val dot = name.lastIndexOf('.')
      name = if (dot > 0) name.substring(0, 120) + name.substring(dot) else name.substring(0, 120)
    }
    return name
  }

  private fun downloadTypeLabel(type: String): String {
    return when (type) {
      "video" -> "Video"
      "image" -> "Imagen"
      "audio" -> "Audio"
      "document" -> "Documento"
      else -> "Archivo"
    }
  }

  companion object {
    /* W57: MainActivity guarda acá el aviso tocado; la web lo consume
       cuando termina de arrancar, incluso en arranque frío. */
    @Volatile
    private var pendingTargetJson = ""

    @Volatile
    private var current: AndroidNotifier? = null

    fun setPendingTarget(chatId: String?, messageId: String?) {
      if (chatId.isNullOrBlank()) return
      pendingTargetJson = JSONObject()
        .put("chat_id", chatId)
        .put("message_id", messageId ?: "")
        .toString()
    }

    fun onStoragePermissionResult(granted: Boolean) {
      current?.storageResult(granted)
    }

    fun onPermissionResult(
      requestCode: Int,
      permissions: Array<out String>,
      grantResults: IntArray
    ) {
      current?.permissionResult(requestCode, permissions, grantResults)
    }

    /* W56: MainActivity actualiza este valor en el hilo de la interfaz
       desde su listener de WindowInsets; la llamada JS lo lee sin tocar
       Views fuera del hilo principal. */
    @Volatile
    private var latestInsets = """{"top":0,"bottom":0,"left":0,"right":0}"""

    fun rememberInsets(top: Int, bottom: Int, left: Int, right: Int) {
      latestInsets = """{"top":$top,"bottom":$bottom,"left":$left,"right":$right}"""
    }
  }
}
'''.replace("PACKAGE_NAME", package_name),
        encoding="utf-8",
    )
    print("AndroidNotifier.kt listo")

    drawable = ROOT / "app/src/main/res/drawable/ic_stat_foxinix.xml"
    drawable.parent.mkdir(parents=True, exist_ok=True)
    drawable.write_text(
        '''<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="24dp"
    android:height="24dp"
    android:viewportWidth="334"
    android:viewportHeight="362">
  <!-- W56: la X de Foxinix en blanco (el icono de la barra de estado debe
       ser una silueta monocroma; Android la tiñe según el tema). -->
  <group android:translateX="7" android:translateY="30">
    <path
        android:fillColor="@android:color/transparent"
        android:strokeColor="#FFFFFFFF"
        android:strokeWidth="27"
        android:strokeLineCap="butt"
        android:strokeLineJoin="miter"
        android:pathData="M249,228 L34,10 L18,180 L160,300 L302,180 L286,10 L71,228" />
  </group>
</vector>
''',
        encoding="utf-8",
    )
    print("Icono de notificación listo")
