/* Punto de entrada: crea la app Vue, conecta el router (W22: rutas
   reales con History API) y los toasts. */
import { store, syncPath, go as goRef, goReplace as goReplaceRef,
  setTheme, toggleTheme } from './store.js';
import { bootstrap, loadSession } from './api.js';
import { t } from './i18n.js';
import {
  BootView, LoginView, RegisterView, ProfileView,
  VerifyView, ForgotView, ResetView,
} from './views/auth.js';
import { ChatShell } from './views/chat.js';
import { BootScreen } from './views/bootscreen.js';
import { dlDirective, startDownload } from './mediadl.js';
import { startWS, stopWS } from './realtime.js';
import { markChatRead } from './actions.js';
import {
  dlCategory, saveDownload, saveDownloadToDevice, listDownloads,
  deleteDownload, hasDownload, clearDownloads, autoDlPrefs, setAutoDl,
  DL_TYPES,
} from './downloads.js';
import { prefetchEmojis } from './emoji.js';
import { ensurePublishedKey } from './e2e.js';

const views = {
  boot: BootView,
  login: LoginView,
  register: RegisterView,
  profile: ProfileView,
  verify: VerifyView,
  forgot: ForgotView,
  reset: ResetView,
  app: ChatShell,
};

const Root = {
  name: 'Root',
  setup() {
    const comp = Vue.computed(() => views[store.route] || LoginView);
    Vue.onMounted(() => {
      // Orden: sesión → URL inicial (deep links) → arranque.
      loadSession();
      syncPath();
      bootstrap();
    });
    return { comp, store };
  },
  template: `
    <transition name="fade" mode="out-in">
      <component :is="comp" :key="store.route"></component>
    </transition>
    <transition-group name="pop" tag="div" class="toasts">
      <div v-for="tw in store.toasts" :key="tw.id" class="toast"
           :class="'toast-' + tw.kind" role="status">
        <svg class="ic ic-sm"><use :href="tw.kind === 'err' ? '#i-alert' : '#i-check'"></use></svg>
        <span>{{ t(tw.msg) }}</span>
      </div>
    </transition-group>`,
};

/* Superficie los errores de render/hooks a consola: los captura shot.py
   (log.entryAdded) y los tests los ven como JS: [...] en stderr.
   W23: el stack de Firefox no trae el mensaje, así que va aparte. */
const app = Vue.createApp(Root);
app.config.errorHandler = function (err, _inst, info) {
  const msg = err && err.message ? err.message + ' | ' : '';
  console.error('[fox] ' + info + ' → ' + (msg + ((err && err.stack) || err)));
};
/* W10: t() disponible en TODOS los templates (lee store.lang reactivo, así
   que cambiar el idioma repinta la interfaz sin recargar). */
app.config.globalProperties.t = t;
/* W15: v-dl="url" → descarga con anillo de progreso, ✕ de cancelar y
   reintento (mediadl.js); en imágenes empieza difuminada con la miniatura. */
app.directive('dl', dlDirective);
/* W38: la pantalla de arranque (icono + cifrado + barra + fase) se
   usa en BootView (auth.js) y en el overlay .app-boot del chat. */
app.component('boot-screen', BootScreen);
app.mount('#app');

/* W29a/W37a: el título del documento refleja los no leídos — "(3)
   Foxinix", con tope "999+" — pero SOLO con la pestaña OCULTA (otra
   pestaña o ventana minimizada): con la app a la vista el título
   queda limpio. Se recalcula al cambiar los no leídos Y al cambiar
   la visibilidad de la pestaña. */
function refreshTitle() {
  let n = 0;
  const chats = store.chats || [];
  for (let i = 0; i < chats.length; i++) n += chats[i].unread || 0;
  const hidden = document.hidden;
  document.title = (n > 0 && hidden)
    ? '(' + (n > 999 ? '999+' : n) + ') Foxinix'
    : 'Foxinix';
}
Vue.watchEffect(refreshTitle);
document.addEventListener('visibilitychange', refreshTitle);

/* W34d: el (N) del título sólo se quita al VISITAR el chat — al volver
   a la pestaña con un chat activo no leído cuenta como visita; con la
   pestaña oculta los mensajes ya no se confirman solos
   (finishIncoming no manda seen si document.hidden). */
document.addEventListener('visibilitychange', function () {
  if (document.hidden) return;
  if (store.activeChatId) markChatRead(store.activeChatId);
});

/* W30b/W30d: tras iniciar sesión se precacenan los SVG del selector de
   emojis en idle y se publica MI clave E2E (una sola vez por pestaña;
   sin re-enviar la misma clave). Así los contactos pueden cifrarme. */
Vue.watch(function () { return store.user && store.user.id; },
  function (uid) {
    if (!uid) return;
    prefetchEmojis();
    ensurePublishedKey().catch(function () {});
  });

/* PWA (W4): el SW da shell offline + caché con actualización en segundo
   plano. En http no seguro (o sin soporte) el registro falla y listo.
   W40: el cliente le AVISA el estilo de emojis activo — el SW solo
   precarga el lote completo de Twemoji si el usuario lo usa (con
   'system' no se descarga NADA de emoji; 'noto' lo baja el cliente
   en idle con prefetchEmojis). */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(function () {});
  const tellStyle = function () {
    const msg = { type: 'emo-style', style: store.prefs.emo };
    const c = navigator.serviceWorker.controller;
    if (c) { c.postMessage(msg); return; }
    navigator.serviceWorker.ready.then(function (reg) {
      if (reg.active) reg.active.postMessage(msg);
    }).catch(function () {});
  };
  tellStyle();
  /* W40: al cambiar el estilo en Ajustes se avisa al SW y se lanza
     el prefetch del lote nuevo (si lo hay). */
  Vue.watch(function () { return store.prefs.emo; }, function () {
    tellStyle();
    prefetchEmojis();
  });
}

/* Ayuda de prueba/desarrollo: permite conducir la UI desde fuera
   (herramientas de screenshot, tests). No usar en lógica de producto. */
window.__fm = { store, go: goRef, goReplace: goReplaceRef, bootstrap,
                theme: setTheme, toggleTheme,
                rt: { start: startWS, stop: stopWS },
                dl: { dlCategory, saveDownload, saveDownloadToDevice,
                      listDownloads, deleteDownload, hasDownload,
                      clearDownloads, autoDlPrefs, setAutoDl,
                      types: DL_TYPES },
                mediadl: { startDownload } };

