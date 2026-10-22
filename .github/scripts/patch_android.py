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

    if "addJavascriptInterface" not in activity:
        if "override fun onWebViewCreate" in activity:
            activity = activity.replace(
                "    override fun onWebViewCreate(webView: WebView) {\n"
                "        super.onWebViewCreate(webView)\n",
                "    override fun onWebViewCreate(webView: WebView) {\n"
                "        super.onWebViewCreate(webView)\n"
                '        webView.addJavascriptInterface(AndroidNotifier(this), "FoxinixAndroid")\n',
                1,
            )
        else:
            bridge_method = (
                "\n  private var appWebView: WebView? = null\n"
                "\n  override fun onWebViewCreate(webView: WebView) {\n"
                "    super.onWebViewCreate(webView)\n"
                "    appWebView = webView\n"
                '    webView.addJavascriptInterface(AndroidNotifier(this), "FoxinixAndroid")\n'
                "  }\n"
                "\n  /* W55: Wry pausa el WebView al pasar a segundo plano; eso\n"
                "     detiene los timers del WebSocket y dejarían de llegar los\n"
                "     avisos. Lo reanudamos para mantener la conexión viva. */\n"
                "  override fun onPause() {\n"
                "    super.onPause()\n"
                "    appWebView?.onResume()\n"
                "  }\n"
            )
            closing = activity.rfind("}")
            if closing == -1:
                print("Aviso: no se encontró el cierre de MainActivity.kt")
            else:
                activity = activity[:closing] + bridge_method + activity[closing:]
        print("Puente de notificaciones agregado a MainActivity.kt")
    main_activity.write_text(activity, encoding="utf-8")

    notifier = main_activity.parent / "AndroidNotifier.kt"
    notifier.write_text(
        '''package PACKAGE_NAME

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.webkit.JavascriptInterface
import androidx.annotation.Keep
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/* W55: avisos nativos del APK. La web llama a FoxinixAndroid.notify()
   cuando está oculta; la notificación abre la app al tocarla. */
@Keep
class AndroidNotifier(private val activity: Activity) {
  private val prefs = activity.getSharedPreferences("foxinix", Context.MODE_PRIVATE)
  private val soundChannelId = "foxinix_messages_v1"
  private val silentChannelId = "foxinix_messages_silent_v1"

  init {
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

  @JavascriptInterface
  @Keep
  fun permission(): String {
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

  @JavascriptInterface
  @Keep
  fun notify(title: String?, body: String?, chatId: String?, sound: String?) {
    if (permission() != "granted") return
    val safeTitle = if (title.isNullOrBlank()) "Foxinix" else title
    val safeBody = body ?: ""
    val withSound = sound == "1"
    val channelId = if (withSound) soundChannelId else silentChannelId

    val intent = Intent(activity, MainActivity::class.java).apply {
      flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
      if (!chatId.isNullOrBlank()) putExtra("foxinix_chat_id", chatId)
    }
    val pending = PendingIntent.getActivity(
      activity,
      0,
      intent,
      PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
    )

    val builder = NotificationCompat.Builder(activity, channelId)
      .setSmallIcon(R.drawable.ic_stat_foxinix)
      .setContentTitle(safeTitle)
      .setContentText(safeBody)
      .setStyle(NotificationCompat.BigTextStyle().bigText(safeBody))
      .setContentIntent(pending)
      .setAutoCancel(true)
      .setPriority(NotificationCompat.PRIORITY_HIGH)
      .setCategory(NotificationCompat.CATEGORY_MESSAGE)
      .setOnlyAlertOnce(false)
      .setWhen(System.currentTimeMillis())
      .setColor(0xFFFF751F.toInt())

    if (withSound) {
      if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
        builder.setDefaults(NotificationCompat.DEFAULT_SOUND or NotificationCompat.DEFAULT_VIBRATE)
      }
    } else {
      builder.setSilent(true)
    }

    val id = if (chatId.isNullOrBlank()) {
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
    android:viewportWidth="24"
    android:viewportHeight="24">
  <path
      android:fillColor="#FFFFFFFF"
      android:pathData="M20,2H4C2.9,2 2,2.9 2,4v18l4,-4h14c1.1,0 2,-0.9 2,-2V4c0,-1.1 -0.9,-2 -2,-2z" />
</vector>
''',
        encoding="utf-8",
    )
    print("Icono de notificación listo")
