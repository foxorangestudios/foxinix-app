/* Foxinix — WebSocket de tiempo real. Reconecta con backoff y refresca
   la lista al reconectar (API.md §tiempo real). */
import { store, toast } from './store.js';
import { session, refreshTokens, authLost, ApiError, sessionHooks } from './api.js';
import { hooks, loadChats, loadMembers, loadPeople, loadBlocks,
  onIncomingMessage, catchUpChat } from './actions.js';
import { t } from './i18n.js';
/* W37a: los avisos y las citas muestran el texto DESCIFRADO (igual que
   el chat); si no hay clave, el aviso usa un texto neutro. */
import { decryptInto } from './e2e.js';
/* W28h: la señalización de llamadas WebRTC reutiliza este socket */
import { initCall, handleCallEvent } from './call.js';

let ws = null;
let pingTimer = null;
let reconnectTimer = null;
let backoff = 1000;
let stopped = true;
let hasOpened = false;

/* W55: el APK inyecta este puente; en web/escritorio no existe y se
   sigue usando la Notification del navegador. Se consulta en cada aviso
   porque el objeto nativo puede inyectarse después del módulo. */
function androidNotifier() {
  if (typeof window === 'undefined' || !window.FoxinixAndroid) return null;
  if (typeof window.FoxinixAndroid.notify !== 'function') return null;
  return window.FoxinixAndroid;
}

/* Solo cuenta como aviso nativo si Android ya concedió el permiso. Si no,
   el bip sigue sonando y el usuario puede activarlo desde Ajustes. */
function nativeNotifyReady() {
  const a = androidNotifier();
  if (!a) return null;
  try { return a.permission() === 'granted' ? a : null; } catch (e) { return null; }
}

/* W45g: cualquier clearSession() (logout, 401 real, cancelación) corta
   la WS en el acto; no queda recibiendo eventos de una cuenta cerrada. */
sessionHooks.onLogout = stopWS;

/* chatId → timer para ocultar "escribiendo…". */
const typingTimers = {};

function findChatById(id) {
  for (let i = 0; i < store.chats.length; i++) {
    if (store.chats[i].id === id) return store.chats[i];
  }
  return null;
}

/* Preview del chat, solo si el mensaje editado/borrado es el último. */
function findChatPreview(chatId, msgId) {
  const chat = findChatById(chatId);
  if (chat && chat.last_message && chat.last_message.id === msgId) return chat.last_message;
  return null;
}

export function startWS() {
  stopped = false;
  backoff = 1000;
  hasOpened = false;
  connect();
}

export function stopWS() {
  stopped = true;
  if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  if (ws) { try { ws.close(); } catch (e) {} ws = null; }
  store.ws = 'off';
}

function connect() {
  if (stopped || ws) return;
  if (!session.access) {
    /* W30e: con la sesión en cookie el access llega del refresh después
       de recargar; si aún no está y hay sesión, pídalo y vuelva. */
    if (!store.hasSession) return;
    refreshTokens().then(connect).catch(function (e) {
      /* Si el refresh rechazó el token, la sesión terminó de verdad.
         Un 5xx/red se reintenta con backoff (no cerrar la sesión). */
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) authLost();
      else scheduleReconnect();
    });
    return;
  }
  store.ws = 'connecting';
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = proto + '//' + location.host + '/api/ws';
  let sock;
  try {
    /* W14: el token viaja como subprotocolo (2.º valor), no en la URL,
       para que no quede en los logs de acceso del servidor. */
    sock = new WebSocket(url, ['foxinix', session.access]);
  } catch (e) {
    scheduleReconnect();
    return;
  }
  ws = sock;

  sock.onopen = function () {
    if (stopped) { try { sock.close(); } catch (e) {} return; }
    const reconnected = hasOpened;
    hasOpened = true;
    store.ws = 'on';
    backoff = 1000;
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(function () { send({ type: 'ping' }); }, 25000);
    if (!reconnected) {
      /* Primera conexión: si bootAll ya terminó y hay un chat abierto,
         lo que llegó entre la carga inicial y este handshake se recupera
         con el mismo catch-up. Durante el arranque, bootAll sigue en vuelo. */
      const firstActive = store.activeChatId;
      if (store.bootPhase === 'ready' && firstActive && store.loaded[firstActive]) {
        catchUpChat(firstActive).catch(function () {});
      }
      return;
    }
    /* W45a: al reconectar pueden faltar mensajes de CUALQUIER chat
       abierto antes. La lista se refresca (previews/no leídos) y los
       chats ya cargados se marcan para catch-up; el activo se pide ya
       mismo y el resto al abrirlos. */
    for (const id in store.loaded) store.syncNeeded[id] = true;
    if (store.bootPhase === 'ready') loadChats();
    const active = store.activeChatId;
    if (active && store.loaded[active]) {
      catchUpChat(active).catch(function () {});
    }
  };

  sock.onmessage = function (e) {
    let ev;
    try { ev = JSON.parse(e.data); } catch (err) { return; }
    handle(ev);
  };

  sock.onclose = function (e) {
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    if (ws === sock) ws = null;
    store.ws = 'off';
    if (stopped) return;
    if (e.code === 4401) refreshThenReconnect();   // token vencido
    else scheduleReconnect();
  };

  sock.onerror = function () {};   // onclose se encarga
}

function scheduleReconnect() {
  if (stopped || reconnectTimer) return;
  reconnectTimer = setTimeout(function () {
    reconnectTimer = null;
    connect();
  }, backoff);
  backoff = Math.min(backoff * 2, 30000);
}

async function refreshThenReconnect() {
  try {
    await refreshTokens();
  } catch (e) {
    /* Solo cerrar si el refresh rechazó el token; si fue red/5xx,
       mantener la sesión y reintentar la conexión. */
    if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
      authLost();
      return;
    }
  }
  scheduleReconnect();
}

function send(obj) {
  if (ws && ws.readyState === 1) {
    try { ws.send(JSON.stringify(obj)); return true; } catch (e) {}
  }
  return false;
}

/* W28h: la señalización de llamadas usa este mismo socket */
initCall(send);

/* 'seen' por WS si está conectado; si no, que REST lo intente. */
hooks.sendSeen = function (chatId, seq) {
  return send({ type: 'seen', chat_id: chatId, seq: seq });
};

/* ------------------------------------------------- avisos (W6) */

let actx = null;

/* Bip corto con WebAudio (sin assets: funciona en XP/Mypal). */
function blip() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    if (!actx) actx = new AC();
    const t = actx.currentTime;
    const o = actx.createOscillator();
    const g = actx.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(880, t);
    o.frequency.exponentialRampToValueAtTime(620, t + 0.12);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.10, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
    o.connect(g);
    g.connect(actx.destination);
    o.start(t);
    o.stop(t + 0.2);
  } catch (e) {}
}

function previewBody(m) {
  // Notificación del navegador: se arma en el idioma vigente (no es reactiva).
  /* W45: no destapar spoilers en la notificación del sistema. */
  if (m.spoiler) return t('Spoiler');
  if (m.kind === 'voice') return t('Nota de voz');
  if (m.kind === 'image') return t('Imagen');
  if (m.kind === 'file') return t('Archivo adjunto');
  /* W37a: con E2E el aviso muestra el texto DESCIFRADO (el mismo que
     ve el usuario en el chat). W54d: si todavía no hay clave, NUNCA
     mostramos el marcador interno del servidor; un texto neutro evita
     que la notificación parezca un error. */
  if (m._plain != null) return m._plain;
  if (m.e2e) return t('Nuevo mensaje');
  return m.body || '';
}

/* Aviso del navegador — se extrae para poder esperar al descifrado
   (W37a): con E2E el cuerpo es el MISMO texto que ve el chat. */
function browserNotify(m) {
  /* W55: resolver el puente ANTES del guard de Notification: el WebView
     de Android no define Notification, pero sí FoxinixAndroid. */
  const native = nativeNotifyReady();
  if (!native && (typeof Notification === 'undefined' ||
      Notification.permission !== 'granted')) return;
  const who = m.sender ? (m.sender.display_name || m.sender.username) : '';
  /* W34c: más contexto — quién escribió, en qué grupo, y su foto de
     perfil como icono de la notificación. */
  const c = findChatById(m.chat_id);
  const chatName = c && c.title
    ? (c.title.display_name || c.title.username || '')
    : ((c && c.name) || '');
  let title;
  if (c && c.type === 'dm') title = who || chatName || 'Foxinix';
  else title = who ? (chatName ? who + ' · ' + chatName : who)
    : (chatName || 'Foxinix');
  const icon = (m.sender && m.sender.avatar_url) ||
    (c && c.avatar_url) || '/static/icon-192.png';

  /* W55: dentro del APK, Android WebView no tiene Notification. Usamos
     la notificación nativa (funciona con la app en segundo plano). */
  if (native) {
    try {
      native.notify(
        title,
        previewBody(m),
        String(m.chat_id == null ? '' : m.chat_id),
        store.prefs && store.prefs.sound ? '1' : '0'
      );
    } catch (e) {}
    return;
  }

  try {
    const n = new Notification(title, {
      body: previewBody(m),
      icon: icon,
      tag: 'foxmsg-' + m.chat_id,
    });
    n.onclick = function () {
      window.focus();
      try { n.close(); } catch (e) {}
    };
  } catch (e) {}
}

/* Sonido + notificación del navegador para mensajes entrantes.
   El sonido suena solo si el chat NO está abierto o la pestaña está
   oculta (si no, sería ruido mientras charlas). */
function notifyIncoming(m) {
  if (!m || !store.user) return;
  const mine = !!(m.sender && m.sender.id === store.user.id);
  if (mine) return;
  const open = store.activeChatId === m.chat_id;
  /* W13: chat silenciado → sin sonido ni notificación del navegador */
  let muted = false;
  for (let i = 0; i < store.chats.length; i++) {
    if (store.chats[i].id === m.chat_id) { muted = !!store.chats[i].muted; break; }
  }
  if (muted) return;
  /* W55: el sonido del aviso nativo lo pone Android; no duplicamos el bip. */
  if (store.prefs.sound && (!open || document.hidden) && !nativeNotifyReady()) blip();
  if (document.hidden) {
    /* W37a: con cifrado E2E se espera a descifrar (si hay clave) para
       avisar con el texto real — igual que en el chat. Sin clave
       (aún) se avisa con un texto neutro, nunca con el marcador. */
    if (m.e2e && m._plain == null) {
      Promise.resolve(decryptInto(m)).then(function () {
        browserNotify(m);
      });
      return;
    }
    browserNotify(m);
  }
}

function markTyping(chatId, userId, username) {
  if (store.user && userId === store.user.id) return;
  /* W29c: lista por chat y por usuario (varios pueden escribir a la vez);
     cada quien tiene su propio timeout de 3,5 s. */
  if (!store.typing[chatId]) store.typing[chatId] = {};
  store.typing[chatId][userId] = { u: username || '', exp: Date.now() + 3500 };
  if (!typingTimers[chatId]) typingTimers[chatId] = {};
  if (typingTimers[chatId][userId]) clearTimeout(typingTimers[chatId][userId]);
  typingTimers[chatId][userId] = setTimeout(function () {
    clearTyping(chatId, userId);
  }, 3500);
}

function clearTyping(chatId, userId) {
  const c = store.typing[chatId];
  const ts = typingTimers[chatId];
  if (userId == null) {                     // limpiar el chat entero
    if (ts) {
      for (const k in ts) clearTimeout(ts[k]);
      delete typingTimers[chatId];
    }
    if (c) delete store.typing[chatId];
    return;
  }
  if (ts && ts[userId]) {
    clearTimeout(ts[userId]);
    delete ts[userId];
  }
  if (c) delete c[userId];
}

/* W15: aplica un cambio de perfil (evento 'profile') a todo lo cargado:
   lista de chats (DM), mensajes ya renderizados (incl. respuestas),
   panel de miembros y el perfil propio si cambió en otra pestaña. */
function applyProfileUpdate(u) {
  if (!u || u.id == null) return;
  if (store.user && store.user.id === u.id) {
    store.user.display_name = u.display_name;
    store.user.avatar_url = u.avatar_url;
  }
  for (let i = 0; i < store.chats.length; i++) {
    const c = store.chats[i];
    if (c.type === 'dm' && c.title && c.title.id === u.id) {
      c.title.display_name = u.display_name;
      c.title.username = u.username;
      c.title.avatar_url = u.avatar_url;
    }
  }
  for (const k in store.msgs) {
    const arr = store.msgs[k];
    for (let j = 0; j < arr.length; j++) {
      const s = arr[j].sender;
      if (s && typeof s === 'object' && s.id === u.id) {
        s.display_name = u.display_name;
        s.username = u.username;
        s.avatar_url = u.avatar_url;
      }
      const r = arr[j].ref && arr[j].ref.sender;
      if (r && typeof r === 'object' && r.id === u.id) {
        r.display_name = u.display_name;
        r.username = u.username;
        r.avatar_url = u.avatar_url;
      }
    }
  }
  if (store.info && store.info.members) {
    for (let m = 0; m < store.info.members.length; m++) {
      const mb = store.info.members[m];
      if (mb.id === u.id) {
        mb.display_name = u.display_name;
        mb.username = u.username;
        mb.avatar_url = u.avatar_url;
      }
    }
  }
}

/* W46: un cambio de rol se refleja YA en la etiqueta [Admin] de los
   mensajes ya cargados, en el panel de miembros y en mi propio rol
   (para habilitar/ocultar las acciones de administración sin esperar
   a que termine loadChats). */
function applyMemberRole(chatId, userId, role) {
  if (store.info && store.info.chatId === chatId && store.info.members) {
    for (let i = 0; i < store.info.members.length; i++) {
      if (store.info.members[i].id === userId) {
        store.info.members[i].role = role;
        break;
      }
    }
  }
  const arr = store.msgs[chatId];
  if (arr) {
    for (let i = 0; i < arr.length; i++) {
      const s = arr[i].sender;
      if (s && typeof s === 'object' && s.id === userId) s.role = role;
      const r = arr[i].ref && arr[i].ref.sender;
      if (r && typeof r === 'object' && r.id === userId) r.role = role;
    }
  }
  const c = findChatById(chatId);
  if (c) {
    const lm = c.last_message;
    if (lm && lm.sender && lm.sender.id === userId) lm.sender.role = role;
    if (store.user && store.user.id === userId) c.my_role = role;
  }
}

/* W46: al expulsarme, el server no puede usar el broadcast del chat
   (ya no soy miembro); llega un evento puntual y cerramos el chat. */
function dropRemovedChat(chatId) {
  if (store.activeChatId === chatId) {
    store.activeChatId = 0;
    store.infoOpen = false;
    store.info = null;
    store.pinsModal = false;
    store.galModal = false;
    store.readsBox = null;
  }
  store.chats = store.chats.filter(function (c) { return c.id !== chatId; });
  delete store.msgs[chatId];
  delete store.loaded[chatId];
  delete store.syncNeeded[chatId];
  delete store.hasMore[chatId];
  clearTyping(chatId);
}

function chatName(chatId) {
  const c = findChatById(chatId);
  if (!c) return '';
  return (c.title && (c.title.display_name || c.title.username)) || '';
}

function handle(ev) {
  // W6: la sesión se cerró → ignorar cualquier evento que llegue tarde
  // (el WS se corta en el desmontaje, pero puede haber uno en vuelo).
  if (!store.hasSession) return;
  switch (ev.type) {
    case 'connected':
      return;

    case 'pong':
      return;

    case 'message':
      if (ev.message) {
        /* UX: el "escribiendo…" del emisor desaparece EN EL MOMENTO en que
           llega su mensaje (sin esperar los 3,5 s del timeout). En grupos
           solo se limpia si el que escribía era ese emisor. */
        const wt = store.typing[ev.message.chat_id];
        const senderId = ev.message.sender ? ev.message.sender.id : 0;
        if (wt && senderId && wt[senderId]) {
          clearTyping(ev.message.chat_id, senderId);
        }
        /* W37a: si el chat es E2E y la clave está en memoria, el aviso
           espera al descifrado y muestra el texto REAL (igual que el
           chat); sin clave queda el marcador del server. */
        const done = onIncomingMessage(ev.message);
        if (done && done.then) {
          const nm = ev.message;
          done.then(function () { notifyIncoming(nm); });
        } else {
          notifyIncoming(ev.message);
        }
      }
      return;

    case 'chat_created':
      loadChats();
      return;

    case 'chat_updated':
      /* W27: cambió algo del chat (p. ej. la foto del grupo). */
      loadChats();
      return;

    case 'people':
      /* W27: cambió una solicitud de amistad o una amistad.
         W28e: también un bloqueo (la lista de ids manda para el menú). */
      loadPeople();
      loadBlocks();
      if (ev.kind === 'request' && ev.from) {
        toast(t('Nueva solicitud de amistad de {n}', { n: ev.from }), 'info');
      }
      return;

    case 'typing':
      markTyping(ev.chat_id, ev.user_id, ev.username);
      return;

    case 'read': {
      const chatId = ev.chat_id;
      if (!store.readSeqs[chatId]) store.readSeqs[chatId] = {};
      const cur = store.readSeqs[chatId][ev.user_id] || 0;
      if (ev.seq > cur) store.readSeqs[chatId][ev.user_id] = ev.seq;
      return;
    }

    case 'delivered': {
      /* W12: 'recibido' — el seq llegó a los dispositivos de user_ids.
         (El propio receptor lo ignora: sus filas solo miran a los demás.) */
      const chatId = ev.chat_id;
      if (!store.deliveredSeqs[chatId]) store.deliveredSeqs[chatId] = {};
      const ids = ev.user_ids || [];
      for (let i = 0; i < ids.length; i++) {
        const cur = store.deliveredSeqs[chatId][ids[i]] || 0;
        if (ev.seq > cur) store.deliveredSeqs[chatId][ids[i]] = ev.seq;
      }
      return;
    }

    case 'presence': {
      const uid = ev.user_id;
      store.presence[uid] = ev.online;   // W26: fuente única (sobrevive a loadChats)
      for (let i = 0; i < store.chats.length; i++) {
        const c = store.chats[i];
        if (c.type === 'dm' && c.title && c.title.id === uid) c.title.online = ev.online;
      }
      // W7: el panel de info y la ventana de perfil abiertos también.
      if (store.info && store.info.members) {
        for (let k = 0; k < store.info.members.length; k++) {
          if (store.info.members[k].id === uid) store.info.members[k].online = ev.online;
        }
      }
      if (store.profile && store.profile.user && store.profile.user.id === uid) {
        store.profile.user.online = ev.online;
      }
      return;
    }

    case 'reaction':
    case 'reaction_removed': {
      const arr = store.msgs[ev.chat_id];
      if (!arr) return;
      for (let i = 0; i < arr.length; i++) {
        const m = arr[i];
        if (m.id !== ev.message_id) continue;
        const rs = m.reactions ? m.reactions.slice() : [];
        if (ev.type === 'reaction') {
          // 1 reacción por usuario (PK message+user en el server): el
          // emoji nuevo REEMPLAZA al anterior en TODOS los clientes.
          // Antes solo se agregaba y el otro veía los dos (bug W7).
          for (let j = rs.length - 1; j >= 0; j--) {
            if (rs[j].user_id === ev.user_id && rs[j].emoji !== ev.emoji) rs.splice(j, 1);
          }
          let found = false;
          for (let k = 0; k < rs.length; k++) {
            if (rs[k].user_id === ev.user_id && rs[k].emoji === ev.emoji) found = true;
          }
          if (!found) {
            /* W29c: el evento trae el nombre (tooltip "quién reaccionó") */
            rs.push({
              emoji: ev.emoji, user_id: ev.user_id,
              username: ev.username || '', name: ev.name || ev.username || '',
            });
          }
        } else {
          // reaction_removed: sin emoji = el server borró la única
          // reacción de ese usuario; con emoji, solo esa.
          for (let j = rs.length - 1; j >= 0; j--) {
            if (rs[j].user_id === ev.user_id &&
                (!ev.emoji || rs[j].emoji === ev.emoji)) rs.splice(j, 1);
          }
        }
        arr[i] = Object.assign({}, m, { reactions: rs });
        return;
      }
      return;
    }

    /* W28c: alguien fijó/desfijó un mensaje del chat — se pinta la
       bandera en la burbuja y se refresca el panel si está abierto. */
    case 'message_pinned': {
      const arr = store.msgs[ev.chat_id];
      if (arr) {
        for (let i = 0; i < arr.length; i++) {
          const m = arr[i];
          if (m.id === ev.message_id) {
            arr[i] = Object.assign({}, m, {
              pinned: ev.pinned, pinned_by: ev.pinned_by,
            });
            break;
          }
        }
      }
      store.pinsRev = (store.pinsRev || 0) + 1;
      return;
    }

    case 'message_edited': {
      const arr = store.msgs[ev.chat_id];
      if (arr) {
        for (let i = 0; i < arr.length; i++) {
          if (arr[i].id === ev.message_id) {
            arr[i] = Object.assign({}, arr[i], {
              body: ev.body, edited_at: ev.edited_at,
            });
            /* W37a: edición cifrada — el blob cambió; limpiar el texto
               descifrado viejo y re-descifrar con la clave del chat. */
            if (ev.e2e) {
              arr[i].e2e = ev.e2e;
              delete arr[i]._plain;
              delete arr[i]._e2eTried;
              decryptInto(arr[i]);
            }
            break;
          }
        }
      }
      const ce = findChatPreview(ev.chat_id, ev.message_id);
      if (ce) {
        ce.body = ev.body;
        if (ev.e2e) {
          ce.e2e = ev.e2e;
          delete ce._plain;
          delete ce._e2eTried;
          decryptInto(ce);
        }
      }
      return;
    }

    case 'message_deleted': {
      const arr = store.msgs[ev.chat_id];
      if (arr) {
        for (let i = arr.length - 1; i >= 0; i--) {
          if (arr[i].id === ev.message_id) arr.splice(i, 1);
        }
      }
      const chat = findChatById(ev.chat_id);
      // si el borrado era el último mensaje, refrescar el preview
      if (chat && chat.last_message && chat.last_message.id === ev.message_id) {
        loadChats();
      }
      return;
    }

    case 'member_role': {
      applyMemberRole(ev.chat_id, ev.user_id, ev.role);
      if (store.user && ev.user_id === store.user.id) {
        const n = chatName(ev.chat_id) || t('el grupo');
        toast(ev.role === 'admin'
          ? t('Ahora eres admin de "{n}"', { n: n })
          : t('Ya no eres admin de "{n}"', { n: n }),
          ev.role === 'admin' ? 'ok' : 'info');
      }
      return;
    }

    case 'member_removed': {
      const n = ev.title || chatName(ev.chat_id) || t('el grupo');
      dropRemovedChat(ev.chat_id);
      toast(t('Te eliminaron de "{n}"', { n: n }), 'err');
      return;
    }

    case 'members_changed':
    case 'member_joined':
    case 'member_left':
      loadChats();
      // W7: el panel de info abierto se refresca con la lista nueva.
      if (store.info && store.info.chatId) loadMembers(store.info.chatId);
      return;

    case 'profile':
      // W15: el server avisa cuando alguien cambió su perfil (en los chats
      // que comparten): se aplica en vivo sin refrescar nada.
      applyProfileUpdate(ev.user);
      return;

    /* W28h: señalización de llamadas WebRTC (solo relé del server) */
    case 'call_offer':
    case 'call_answer':
    case 'call_ice':
    case 'call_hangup':
    case 'call_error':
      handleCallEvent(ev);
      return;

    default:
      return;   // eventos futuros: ignorar (compatibilidad)
  }
}
