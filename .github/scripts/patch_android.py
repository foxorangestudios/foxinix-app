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

    has_create = "override fun onWebViewCreate" in activity
    if "private var appWebView" not in activity and has_create:
        marker = "    override fun onWebViewCreate(webView: WebView) {"
        if marker in activity:
            activity = activity.replace(
                marker,
                "    private var appWebView: WebView? = null\n\n" + marker,
                1,
            )

    if has_create:
        if "addJavascriptInterface" not in activity:
            marker = (
                "    override fun onWebViewCreate(webView: WebView) {\n"
                "        super.onWebViewCreate(webView)\n"
            )
            if marker in activity:
                activity = activity.replace(
                    marker,
                    marker
                    + "        appWebView = webView\n"
                    + '        webView.addJavascriptInterface(AndroidNotifier(this), "FoxinixAndroid")\n'
                    + "        webView.post { ViewCompat.requestApplyInsets(webView) }\n",
                    1,
                )
            else:
                print("Aviso: no se pudo inyectar el puente en onWebViewCreate")
        elif "appWebView = webView" not in activity:
            marker = "        super.onWebViewCreate(webView)\n"
            activity = activity.replace(
                marker,
                marker + "        appWebView = webView\n",
                1,
            )
        if ("ViewCompat.requestApplyInsets(webView)" not in activity
                and "appWebView = webView" in activity):
            marker = '        webView.addJavascriptInterface(AndroidNotifier(this), "FoxinixAndroid")\n'
            if marker in activity:
                activity = activity.replace(
                    marker,
                    marker + "        webView.post { ViewCompat.requestApplyInsets(webView) }\n",
                    1,
                )
        print("Puente de notificaciones agregado a MainActivity.kt")
    else:
        bridge_method = (
            "\n  private var appWebView: WebView? = null\n"
            "\n  override fun onWebViewCreate(webView: WebView) {\n"
            "    super.onWebViewCreate(webView)\n"
            "    appWebView = webView\n"
            '    webView.addJavascriptInterface(AndroidNotifier(this), "FoxinixAndroid")\n'
            "    webView.post { ViewCompat.requestApplyInsets(webView) }\n"
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
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.BitmapShader
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Shader
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.util.LruCache
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import androidx.annotation.Keep
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import java.net.HttpURLConnection
import java.net.URL
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

  /* W56: Android no rellena env(safe-area-inset-bottom) dentro del
     WebView. Devolvemos el inset de la barra de navegación/gestos en dp;
     boot.js lo aplica a --sab. Con el teclado abierto devolvemos 0 para
     no sumar un hueco extra sobre el compositor. */
  @JavascriptInterface
  @Keep
  fun insets(): String = latestInsets

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

  /* W55: firma antigua, conservada para las webs cacheadas que todavía
     llamen a notify() sin avatar. */
  @JavascriptInterface
  @Keep
  fun notify(title: String?, body: String?, chatId: String?, sound: String?) {
    enqueue(title, body, chatId, sound, null)
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
    enqueue(title, body, chatId, sound, avatarUrl)
  }

  private fun enqueue(
    title: String?,
    body: String?,
    chatId: String?,
    sound: String?,
    avatarUrl: String?
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
        showNotification(safeTitle, safeBody, safeChatId, withSound, avatarUrl)
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
    avatarUrl: String?
  ) {
    val channelId = if (withSound) soundChannelId else silentChannelId

    val intent = Intent(activity, MainActivity::class.java).apply {
      flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
      if (chatId != null) putExtra("foxinix_chat_id", chatId)
    }
    val pending = PendingIntent.getActivity(
      activity,
      0,
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

  companion object {
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
