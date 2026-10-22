/* Foxinix — pantalla principal: lista de chats + conversación (W2). */
import {
  store, toast, toggleTheme, setTheme, setAccent, setWall, setPref, setFont,
  setPrefStr,   /* W40: estilo de emojis (valor libre) */
  setWallImg, setWallDim, setWallBlur, setSideCollapsed, setMicDev,
} from '../store.js';
import { logout, api, session, saveSession, uploadMedia,
  uploadChatAvatar, ensurePreview } from '../api.js';
import { t, setLang, LANGS } from '../i18n.js';
/* W28h: llamadas de voz/video 1:1 (WebRTC) */
import { startCall, acceptCall, rejectCall, hangupCall,
  toggleMute, toggleCam, getLocalStream, getRemoteStream } from '../call.js';
/* W29f/W31c: cifrado de extremo a extremo por chat (DM) — siempre
   activo: ya no hay switch ni activación manual. */
import { chatKey as e2eChatKey } from '../e2e.js';
import {
  listDownloads, saveDownloadToDisk, deleteDownload, clearDownloads,
} from '../downloads.js';
import {
  openChat, closeChat, loadChats, loadOlder, sendText, sendMedia,
  createDm, createGroup, addMember, setMemberRole, removeMember,
  toggleReaction, loadMembers, leaveGroup,
  /* W28c */
  togglePin,
  /* W28g */
  sendGif,
  /* W8 */
  editMessage, askDeleteMessage,
  searchUsers, notifyTyping, chatTitle, mediaUrl, fmtSize,
  /* W11 */
  cancelUpload, retryUpload,
  /* W13 */
  setPinned, setMuted, forwardMessage, mergeMessages,
  /* W22 */
  resolvePendingChat,
  /* W27: panel Personas/Amigos */
  loadPeople, sendFriendRequest, acceptFriendRequest,
  rejectFriendRequest, cancelFriendRequest, unfriend,
  /* W28e */
  loadBlocks, blockUser, unblockUser,
} from '../actions.js';
/* W15: descarga de archivos con progreso, cancelación y reintento. */
import {
  startDownload, getBlob, markDlDone, compatUrl, markMediaCompat,
  markOggBroken, audioFallbackFmt, forgetCached, cacheMedia,
} from '../mediadl.js';
import { emojiCats, emojiCat, emojiRecent, emojiSearch, emojiPush,
  emojiCode, shortcodesToEmoji, emojiCodesPrefix,
  emoFile, emoSrc, splitEmojis, isOneEmoji,
  reactBump, reactRank } from '../emoji.js';
import { startWS, stopWS } from '../realtime.js';
import { AvatarEditor } from './avatar-editor.js';

/* ------------------------------------------------------- fechas/horas */

const pad = function (n) { return n < 10 ? '0' + n : '' + n; };

function dayKey(d) {
  return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate();
}

function dayLabel(d) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const that = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diff = Math.round((today - that) / 86400000);
  if (diff === 0) return t('HOY');
  if (diff === 1) return t('AYER');
  if (d.getFullYear() === now.getFullYear()) return d.getDate() + '/' + (d.getMonth() + 1);
  return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + String(d.getFullYear()).slice(2);
}

/* W17: 12/24 h. fmtTime es llamado dentro de computed/render, así que
   leer store.prefs.h12 lo vuelve reactivo: cambiarlo repinta los tiempos. */
function fmtTime(d) {
  const h = d.getHours();
  if (store.prefs.h12) {
    const h12 = h % 12 || 12;
    return h12 + ':' + pad(d.getMinutes()) + (h < 12 ? ' am' : ' pm');
  }
  return pad(h) + ':' + pad(d.getMinutes());
}

function fmtListTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  if (dayKey(d) === dayKey(now)) return fmtTime(d);
  /* W17: ayer se muestra como "Ayer" en vez de la fecha. */
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (d >= new Date(today - 86400000)) return t('Ayer');
  if (d.getFullYear() === now.getFullYear()) return d.getDate() + '/' + (d.getMonth() + 1);
  return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + String(d.getFullYear()).slice(2);
}

function fmtLastSeen(ts) {
  if (!ts) return t('desconectado');
  const d = new Date(ts * 1000);
  const now = new Date();
  if (dayKey(d) === dayKey(now)) return t('últ. vez {n}', { n: fmtTime(d) });
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (d >= new Date(today - 86400000)) return t('últ. vez ayer, {n}', { n: fmtTime(d) });
  return t('últ. vez {n}', { n: d.getDate() + '/' + (d.getMonth() + 1) + ' ' + fmtTime(d) });
}

/* ------------------------------------------------------- estados (W6)

   W9: presets con los nombres y colores de Discord —
   En línea (verde #23a55a), Ausente (ámbar idle #f0b232),
   No molestar (rojo #f23f43), Invisible (gris offline #80848e).
   El valor interno 'busy' se conserva por compatibilidad con el server
   (validador + datos ya guardados).
   W10: se quitó "Sin estado" (como en Discord todo el mundo tiene estado):
   el default de las cuentas nuevas es 'online' y el valor vacío heredado
   se trata como En línea. */

const STATUS_PRESETS = [
  { val: 'online', label: 'En línea', dot: 'sd-online' },
  { val: 'busy', label: 'Ausente', dot: 'sd-busy' },
  { val: 'dnd', label: 'No molestar', dot: 'sd-dnd' },
  { val: 'invisible', label: 'Invisible', dot: 'sd-off' },
];

function presetLabel(val) {
  for (let i = 0; i < STATUS_PRESETS.length; i++) {
    if (STATUS_PRESETS[i].val === val) return t(STATUS_PRESETS[i].label);
  }
  return '';
}

/* ------------------------------------------------------- W7: utilidades */

/* Puntito de estado en el avatar (W9, colores Discord):
   En línea → verde; Ausente → ámbar; No molestar → rojo;
   Invisible → gris. W13: **desconectado también muestra el puntito,
   pero gris** (lo pidió el usuario); los grupos (sin usuario) no llevan
   puntito. selfOn (opcional) = yo mismo: el "online" sale del WS. */
function dotClass(u, selfOn) {
  const explicit = selfOn !== undefined;
  if (!explicit && !u) return { on: false };   // grupo/sin usuario
  /* W26: u.online (REST) es solo el primer relleno; manda store.presence
     (eventos WS + snapshot al reconectar). */
  const on = explicit ? !!selfOn
    : !!(u && (store.presence[u.id] != null ? store.presence[u.id] : u.online));
  const out = { on: true };
  if (!on) { out['st-off'] = true; return out; }   // gris si desconectado
  const p = (u && u.status_preset) || '';
  if (p === 'busy') out['st-busy'] = true;
  else if (p === 'dnd') out['st-dnd'] = true;
  else if (p === 'invisible') out['st-off'] = true;
  return out;
}

function statusOf(u) {
  if (u && u.status_text) return u.status_text;
  if (u && u.status_preset) return presetLabel(u.status_preset);
  return '';
}

function connLine(u) {
  const on = u && (store.presence[u.id] != null ? store.presence[u.id] : u.online);
  return on ? t('En línea') : fmtLastSeen(u ? u.last_seen : 0);
}

/* W27: píldora de estado (perfil y info del directo) — si está
   DESCONECTADO se dice "Desconectado": el preset "en línea" guardado en
   el perfil no es un estado del usuario. Si está activo, manda SU estado
   (texto o preset) por encima de lo genérico. */
function connPill(u) {
  if (!u) return '';
  const on = store.presence[u.id] != null ? store.presence[u.id] : u.online;
  return on ? statusOf(u) : t('Desconectado');
}

/* Perfil de otro usuario en ventana flotante (clic repetido = cerrar). */
async function openProfile(username) {
  if (!username) return;
  const cur = store.profile;
  if (cur && cur.user && cur.user.username === username) {
    store.profile = null;
    return;
  }
  store.profile = { loading: true, user: null, error: '' };
  try {
    const r = await api('GET', '/api/users/' + encodeURIComponent(username),
      undefined, { retry401: true });
    store.profile = { loading: false, user: r.user, error: '' };
  } catch (e) {
    store.profile = {
      loading: false, user: null,
      error: (e && e.detail) || 'No se pudo cargar el perfil',
    };
  }
}

/* Confirmación antes de salirse de un grupo (menú contextual / panel). */
function askLeave(c) {
  if (!c) return;
  store.confirmBox = {
    title: 'Salir del grupo',
    // Dinámico: se arma ya traducido (ConfirmBox solo repite el texto).
    text: t('Vas a salir de "{n}".\nEste chat se borra de tu lista y no vas a recibir más mensajes. Puedes volver si alguien te vuelve a agregar.',
      { n: chatTitle(c) }),
    danger: true,
    okLabel: 'Salir del grupo',
    onOk: async function () {
      await leaveGroup(c.id);
    },
  };
}

/* W46: confirmación y aviso al ascender/quitar admin o sacar del grupo.
   El mensaje system del server es el aviso permanente en el chat; acá
   además se pide confirmación y se muestra un toast al actor. */
function askSetRole(c, m, role) {
  if (!c || !m) return;
  const name = m.display_name || m.username;
  const promoting = role === 'admin';
  store.confirmBox = {
    title: promoting ? 'Hacer admin' : 'Quitar admin',
    text: promoting
      ? t('¿Hacer admin a {n}? Podrá administrar el grupo y todos verán el aviso en el chat.',
          { n: name })
      : t('¿Quitar admin a {n}? Ya no podrá administrar el grupo y todos verán el aviso en el chat.',
          { n: name }),
    danger: false,
    okLabel: promoting ? 'Hacer admin' : 'Quitar admin',
    onOk: async function () {
      await setMemberRole(c.id, m.id, role);
      toast(promoting
        ? t('{n} ahora es admin', { n: name })
        : t('{n} ya no es admin', { n: name }), 'ok');
    },
  };
}

function askRemoveMember(c, m) {
  if (!c || !m) return;
  const name = m.display_name || m.username;
  store.confirmBox = {
    title: 'Eliminar del grupo',
    text: t('¿Eliminar a {n} del grupo? Dejará de ver el chat y todos verán el aviso de la expulsión.',
      { n: name }),
    danger: true,
    okLabel: 'Eliminar del grupo',
    onOk: async function () {
      await removeMember(c.id, m.id);
      toast(t('{n} fue eliminado del grupo', { n: name }), 'ok');
    },
  };
}

/* --------------------------------------------------------- W27: ⋮ y foto */

/* Menú contextual compartido: lo abren la lista (⋮), el panel de info (⋮)
   y la ventana de perfil (⋮). Antes vivía solo en ChatShell; ahora está
   al nivel del módulo para que cualquier vista lo use (el ancla del menú
   se resuelve por clase porque no hay ref compartida). */
const clampPos = function (v, max) {
  return Math.max(4, Math.min(v, max - 8));
};
/* W37b: en móvil/táctil no hay hover — la barra flotante no sirve y el
   menú contextual se abre como BOTTOM SHEET abajo de la pantalla. */
function isTouchUI() {
  try {
    return window.matchMedia('(pointer: coarse)').matches ||
      window.innerWidth < 640;
  } catch (e) { return window.innerWidth < 640; }
}
const openCtx = function (e, items, anchor, key, head) {
  /* W36i: si el menú de ESTE botón ya está abierto, un segundo clic
     lo cierra (antes sólo se cerraba tocando afuera). */
  if (key && store.ctx && store.ctx.key === key) {
    store.ctx = null;
    return;
  }
  /* W17: un solo panel flotante: abrir el menú cierra pickers. */
  store.emoOpen = false;
  store.reactFor = 0;
  /* W37b: bottom sheet en táctil — sin anclas ni cálculo de posición.
     W54c: en el teléfono la hoja lleva una cabecera con la foto y el
     nombre cuando el menú pertenece a un chat o grupo. */
  if (isTouchUI()) {
    store.ctx = {
      x: 0, y: 0, items: items, key: key || '', sheet: true,
      head: head || null,
    };
    return;
  }
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const estW = 200;
  const estH = items.length * 37 + 10;
  let x;
  let y;
  if (anchor) {
    const r = anchor.getBoundingClientRect();
    /* A la derecha de la burbuja si cabe; si no, a su izquierda. */
    x = (r.right + 8 + estW <= vw - 4) ? r.right + 8 : r.left - estW - 8;
    if (x < 4) x = clampPos(r.right, vw);
    y = clampPos(r.top, vh);
    if (y + estH > vh - 4) y = clampPos(vh - estH, vh);
  } else {
    x = clampPos(e.clientX, vw);
    y = clampPos(e.clientY, vh);
    /* W29c: la rama sin ancla también estimaba y NO corregía: el menú
       podía desbordar por abajo (p. ej. clic derecho cerca del borde). */
    if (y + estH > vh - 4) y = clampPos(vh - estH, vh);
  }
  store.ctx = { x: x, y: y, items: items, key: key || '', head: head || null };
  /* W29c: corrección con medida REAL — corre SIEMPRE (antes solo con
     ancla); offset* es inmune al transform de la animación de entrada. */
  Vue.nextTick(function () {
    const el = document.querySelector('.ctx-menu');
    if (!el || !store.ctx) return;
    const w = el.offsetWidth;
    const h = el.offsetHeight;
    let nx = store.ctx.x;
    let ny = store.ctx.y;
    if (nx + w > vw - 4) nx = Math.max(4, vw - w - 4);
    if (ny + h > vh - 4) ny = Math.max(4, vh - h - 4);
    store.ctx.x = nx;
    store.ctx.y = ny;
  });
};

/* W27b: encuadre aplicado a la última foto editada, por contexto
   ('me' para mi perfil, 'chat-<id>' para el grupo). Vive en MEMORIA:
   se restaura al reeditar dentro de la sesión (decisión W27b; el archivo
   original solo existe en memoria, así que no tiene sentido más allá). */
const cropStates = {};
function cropStateFor(key) { return cropStates[key] || null; }
function saveCropState(key, st) { if (key && st) cropStates[key] = st; }

/* Foto del grupo (W27b): selector de imagen y, ANTES de subirla, el
   editor de encuadre en el panel de info (mismo componente que el
   perfil). El resultado compuesto se sube ya recortado. Solo owner/admin
   la usan (c.my_role) y el server vuelve a validar el rol. */
function pickGroupPhoto(c) {
  if (!c) return;
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = 'image/*';
  /* W27b: va al DOM (oculto) para poder manipularlo desde fuera */
  inp.className = 'tmp-file';
  inp.style.display = 'none';
  document.body.appendChild(inp);
  inp.addEventListener('change', function () {
    inp.remove();
    const f = inp.files && inp.files[0];
    if (!f) return;
    if (!/^image\//.test(f.type)) { toast('Elige una imagen', 'err'); return; }
    if (f.size > 15 * 1024 * 1024) { toast('La imagen supera los 15 MB', 'err'); return; }
    /* el editor vive en el panel de info: abre ese chat con el panel */
    store.infoOpen = true;
    openChat(c.id);
    loadMembers(c.id);
    if (store.grpEdit && store.grpEdit.src) URL.revokeObjectURL(store.grpEdit.src);
    store.grpEdit = {
      chatId: c.id,
      src: URL.createObjectURL(f),
      initial: cropStateFor('chat-' + c.id),
    };
  });
  inp.click();
}

/* W54c: cabecera de la hoja móvil para los menús de chat/grupo. */
function ctxChatHead(c) {
  if (!c) return null;
  const name = chatTitle(c) || '';
  const raw = c.type === 'dm'
    ? (c.title && c.title.avatar_url)
    : c.avatar_url;
  return {
    name: name,
    avatar: raw ? mediaUrl(raw) : '',
    ini: name ? name.charAt(0).toUpperCase() : '?',
    sub: c.type === 'group'
      ? t('Grupo')
      : (c.title && c.title.username ? '@' + c.title.username : t('Chat')),
  };
}

/* ⋮ de la lista de chats y del panel de info: administrar el chat. */
function chatMenu(e, c, key) {
  if (!c) return;
  const items = [{
    label: 'Abrir chat', icon: 'i-users',
    fn: function () { openChat(c.id); },
  }];
  if (c.type === 'group') {
    items.push({
      label: 'Ver info del chat', icon: 'i-info',
      fn: function () { store.infoOpen = true; openChat(c.id); loadMembers(c.id); },
    });
    /* W27: foto del grupo — solo owner/admin (el server también lo valida). */
    if (c.my_role === 'owner' || c.my_role === 'admin') {
      items.push({
        label: 'Cambiar foto del grupo', icon: 'i-image',
        fn: function () { pickGroupPhoto(c); },
      });
    }
    items.push({
      label: 'Salir del grupo', icon: 'i-back', danger: true,
      fn: function () { askLeave(c); },
    });
  } else if (c.title && c.title.username) {
    items.push({
      label: 'Ver perfil', icon: 'i-user',
      fn: function () { openChat(c.id); openProfile(c.title.username); },
    });
    /* W37b: el código de verificación E2E vive escondido aquí (antes
       ocupaba el panel de info y sobraba — la app verifica sola).
       W39: se muestra en un MODAL (antes un toast que se perdía). */
    if (store.e2e && store.e2e[c.id]) {
      items.push({
        label: 'Ver código de verificación',
        icon: 'i-shield',
        fn: function () {
          const sas = store.e2eSas ? store.e2eSas[c.id] : '';
          if (sas) { store.sasFor = c.id; store.sasOpen = true; }
          else toast(t('El código estará disponible al abrir el chat'), 'info');
        },
      });
    }
  }
  /* W13: fijar / silenciar (ajustes personales, por chat) */
  items.push({
    label: c.pinned ? 'Desfijar chat' : 'Fijar chat',
    icon: c.pinned ? 'i-x' : 'i-pin',
    fn: function () { setPinned(c.id, !c.pinned); },
  });
  items.push({
    label: c.muted ? 'Activar notificaciones' : 'Silenciar notificaciones',
    icon: c.muted ? 'i-bell' : 'i-bell-off',
    fn: function () { setMuted(c.id, !c.muted); },
  });
  /* W36i: key = el mismo botón alterna abrir/cerrar. El ⋮ de la INFO
     usa 'info' (distinta de la lista): abrir uno no cierra el otro
     con un segundo clic, cada botón se auto-gestiona. */
  openCtx(e, items, null, key || 'chat:' + c.id, ctxChatHead(c));
}

/* ⋮ de la ventana de perfil de OTRO usuario: administrar la amistad
   (enviar / cancelar / aceptar solicitud, eliminar amistad). */
function personMenu(e, u) {
  if (!u || !u.username) return;
  const meId = store.user ? store.user.id : 0;
  if (u.id === meId) return;
  const p = store.people;
  let isFriend = false;
  let sentId = 0;
  let recvId = 0;
  if (p) {
    let i;
    for (i = 0; i < (p.friends || []).length; i++) {
      if (p.friends[i].id === u.id) { isFriend = true; break; }
    }
    for (i = 0; i < (p.sent || []).length; i++) {
      if (p.sent[i].user && p.sent[i].user.id === u.id) sentId = p.sent[i].id;
    }
    for (i = 0; i < (p.received || []).length; i++) {
      if (p.received[i].user && p.received[i].user.id === u.id) recvId = p.received[i].id;
    }
  }
  const run = function (fn) {
    Promise.resolve(fn()).catch(function (err) {
      toast((err && err.detail) || 'No se pudo completar la acción', 'err');
    });
  };
  const items = [];
  if (isFriend) {
    items.push({
      label: 'Eliminar amistad', icon: 'i-userminus', danger: true,
      fn: function () {
        store.confirmBox = {
          title: 'Eliminar amistad',
          /* Armado ya traducido: ConfirmBox lo repite vía t() y las
             claves con {n} ya sustituido no vuelven a coincidir (ok). */
          text: t('¿Dejar de ser amigos con {n}?',
            { n: u.display_name || u.username }),
          okLabel: 'Eliminar amistad',
          danger: true,
          onOk: function () { run(function () { return unfriend(u.id); }); },
        };
      },
    });
  } else if (sentId) {
    items.push({
      label: 'Cancelar solicitud', icon: 'i-x',
      fn: function () { run(function () { return cancelFriendRequest(sentId); }); },
    });
  } else if (recvId) {
    items.push({
      label: 'Aceptar solicitud', icon: 'i-check',
      fn: function () { run(function () { return acceptFriendRequest(recvId); }); },
    });
    items.push({
      label: 'Rechazar solicitud', icon: 'i-x', danger: true,
      fn: function () { run(function () { return rejectFriendRequest(recvId); }); },
    });
  } else {
    items.push({
      label: 'Enviar solicitud de amistad', icon: 'i-userplus',
      fn: function () {
        run(function () {
          return sendFriendRequest(u.username).then(function () {
            toast('Solicitud enviada', 'ok');
          });
        });
      },
    });
  }
  /* W28e: bloquear / desbloquear — siempre al final del menú de OTRO
     usuario; mientras dure, el server corta solicitudes y directos. */
  const blocked = (store.blocks || []).indexOf(u.id) >= 0;
  if (!blocked) {
    items.push({
      label: 'Bloquear usuario', icon: 'i-ban', danger: true,
      fn: function () {
        store.confirmBox = {
          title: 'Bloquear usuario',
          /* Armado ya traducido (mismo criterio que 'Eliminar amistad'). */
          text: t('¿Bloquear a {n}?', { n: u.display_name || u.username }),
          okLabel: 'Bloquear usuario',
          danger: true,
          onOk: function () {
            run(function () {
              return blockUser(u.username).then(function () {
                toast('Usuario bloqueado');
              });
            });
          },
        };
      },
    });
  } else {
    items.push({
      label: 'Desbloquear usuario', icon: 'i-unlock',
      fn: function () {
        run(function () {
          return unblockUser(u.username).then(function () {
            toast('Usuario desbloqueado');
          });
        });
      },
    });
  }
  /* W36i: el mismo ⋮ alterna abrir/cerrar */
  openCtx(e, items, null, 'person:' + (u && u.id ? u.id : 0));
}

/* Apertura del ⋮ con teclado (Enter sobre el span): mismo menú que con
   el ratón, posicionado bajo el elemento. */
function menuKey(ev, c) {
  const el = ev.target;
  const r = el && el.getBoundingClientRect ? el.getBoundingClientRect() : null;
  chatMenu({ clientX: r ? r.left : 8, clientY: r ? r.bottom : 8 }, c);
}

/* Copiar al portapapeles (FF78: execCommand, sin depender de clipboard API). */
function copyText(t) {
  try {
    const ta = document.createElement('textarea');
    ta.value = t;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  } catch (e) {
    toast('No se pudo copiar el texto', 'err');
  }
}

/* W19: achica una imagen para el fondo de la conversación (≤1280px,
   JPEG) y la devuelve como data-URL por callback(url, err). Se guarda
   en el dispositivo (mismo criterio que el color de pared). */
function shrinkWall(file, cb) {
  const img = new Image();
  const url = URL.createObjectURL(file);
  img.onload = function () {
    const max = 1280;
    let w = img.width, h = img.height;
    if (w > max || h > max) {
      const k = Math.min(max / w, max / h);
      w = Math.round(w * k);
      h = Math.round(h * k);
    }
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    c.getContext('2d').drawImage(img, 0, 0, w, h);
    URL.revokeObjectURL(url);
    try {
      let out = c.toDataURL('image/jpeg', 0.75);
      if (out.length > 3000000) out = c.toDataURL('image/jpeg', 0.5);
      /* prueba de espacio: si no entra, avisar sin romper nada */
      localStorage.setItem('fm.wallimg.probe', out);
      localStorage.removeItem('fm.wallimg.probe');
      cb(out, '');
    } catch (e) {
      cb('', 'La foto es muy pesada: prueba con una más chica');
    }
  };
  img.onerror = function () {
    URL.revokeObjectURL(url);
    cb('', 'No se pudo leer la imagen');
  };
  img.src = url;
}

/* W16: panel flotante a dentro del área de mensajes.
   El overflow de .msgs (hidden/auto) recortaba los paneles de emojis que
   se salían de la caja: los chips quedaban cortados a la izquierda/arriba
   y el panel completo se cortaba por abajo. La solución es el mismo
   patrón que el menú contextual: position: fixed + clamp a la caja de
   .msgs (nunca tapa la cabecera ni el sidebar y nunca se sale).
   - el panel completo dentro de los chips: si no cabe debajo, va arriba
     (para no tapar los propios chips);
   - los chips en el toolbar: si quedaron sobre la cabecera, van debajo;
   - el grid se achica si la altura disponible no da. */
const clampPanel = function (el, anim) {
  if (!el) return;
  const par = el.parentElement;
  const enChips = !!(par && par.classList && par.classList.contains('react-picker'));
  const sonChips = !!(el.classList && el.classList.contains('react-picker'));
  const msgsEl = document.querySelector('.msgs');
  const bb = msgsEl ? msgsEl.getBoundingClientRect() : null;
  const vw = window.innerWidth, vh = window.innerHeight;
  const L = Math.max(bb ? bb.left : 0, 4);
  const T = Math.max(bb ? bb.top : 0, 4);
  const R = Math.min(bb ? bb.right : vw, vw - 4);
  const B = Math.min(bb ? bb.bottom : vh, vh - 4);
  const animWas = el.style.animation;
  if (anim) el.style.animation = 'none';     // medir sin la animación de entrada
  // volver al ancla natural (CSS) para no arrastrar un clamp anterior
  el.style.position = ''; el.style.left = ''; el.style.top = '';
  el.style.right = ''; el.style.bottom = ''; el.style.maxWidth = '';
  el.style.height = '';              /* W36fix: recorte previo del panel */
  const nat = el.getBoundingClientRect();
  // achicar la zona scrolleable si la altura no da (el resto es fijo):
  // W29b: el panel de emoji scrollea en .ep-body (estilo Discord); el
  // de stickers/gif conserva el .ep-grid con scroll interno (W28g).
  const body = el.querySelector('.ep-body');
  const grid = body || el.querySelector('.ep-grid');
  if (grid) {
    const rest = el.offsetHeight - grid.offsetHeight;
    grid.style.maxHeight = Math.max(body ? 140 : 60,
      Math.min(body ? 258 : 236, B - T - rest - 6)) + 'px';
  }
  /* W36fix: el panel del compositor tiene alto FIJO (344px, igual en
     las 3 pestañas); si la ventana no da (msgs acotado), se recorta
     aquí para que SIEMPRE quepa — en ventanas normales no se toca. */
  if (el.classList && el.classList.contains('st-panel')
      && el.offsetHeight > B - T - 6) {
    el.style.height = Math.max(200, B - T - 6) + 'px';
  }
  if (R - L < el.offsetWidth) {
    el.style.maxWidth = Math.max(200, Math.floor(R - L)) + 'px';
  }
  const w = el.offsetWidth, h = el.offsetHeight;
  let y = nat.top;
  if (enChips && nat.top + h > B) {          // panel completo sin aire abajo
    const above = par.getBoundingClientRect().top - 4 - h;
    y = above >= T ? above : nat.top;        // mejor arriba de los chips
  }
  if (sonChips && nat.top < T && par) {      // chips sobre la cabecera
    y = par.getBoundingClientRect().bottom + 4;
  }
  const x = Math.min(Math.max(nat.left, L), R - w);
  y = Math.min(Math.max(y, T), B - h);
  el.style.position = 'fixed';
  // right/bottom del CSS siguen vigentes y, con position: fixed, estiran el
  // panel (height:auto + top + bottom ⇒ altura resuelta por el viewport):
  // hay que anularlos explícitamente.
  el.style.right = 'auto';
  el.style.bottom = 'auto';
  el.style.left = Math.round(x) + 'px';
  el.style.top = Math.round(y) + 'px';
  // Gecko puede renderizar el panel corrido unos píxeles (márgenes u otro
  // quirk del ancestro): se mide el rectángulo real y se corrige el delta.
  const r2 = el.getBoundingClientRect();
  el.style.left = Math.round(x + (x - r2.left)) + 'px';
  el.style.top = Math.round(y + (y - r2.top)) + 'px';
  if (anim) el.style.animation = animWas || '';  // la entrada arranca en su sitio
};

/* W13: selector de emoji completo (buscar + categorías + recientes).
   Se usa en el composer (insertar) y en el picker de reacciones. */
/* W28g: stickers (emojis grandes que viajan como kind 'sticker') y
   biblioteca local de GIFs (generados en web/gifs, subidos por el
   flujo normal de media como image/gif). */
const STICKERS = ['👍', '🔥', '🎉', '❤️', '😂', '🤔', '👻', '🎃',
  '👏', '🙌', '💪', '☕', '🌈', '⭐', '🎯', '💌', '🤝', '😺',
  '💩', '🥶', '🥳', '😴', '🫡', '🎄'];
const GIF_LIST = ['heart-pulse.gif', 'ball-bounce.gif', 'star-spin.gif',
  'smiley-wink.gif', 'fire.gif', 'sparkle.gif', 'confetti.gif',
  'loader.gif', 'boom-ring.gif', 'clock-spin.gif'];

/* W36k: favoritos de GIFs — la biblioteca estática (name) y los GIFs
   subidos que viajan en mensajes (media_id). Se cargan una vez al abrir
   la pestaña GIFs o al pintar una estrella; viven en store.gifFavs. */
const ensureGifFavs = function () {
  if (store.gifFavsLoaded) return Promise.resolve();
  store.gifFavsLoaded = true;
  return api('GET', '/api/gifs/favorites').then(function (r) {
    store.gifFavs = (r && r.favorites) || [];
  }).catch(function () { store.gifFavsLoaded = false; });
};
const isGifFav = function (m) {
  ensureGifFavs();
  const fid = m && m.media ? m.media.id : 0;
  const fs = store.gifFavs || [];
  for (let i = 0; i < fs.length; i++) if (fs[i].media_id === fid) return true;
  return false;
};
const isLibGifFav = function (name) {
  ensureGifFavs();
  const fs = store.gifFavs || [];
  for (let i = 0; i < fs.length; i++) if (fs[i].name === name) return true;
  return false;
};
const toggleFavGif = function (m) {
  const fid = m && m.media ? m.media.id : 0;
  if (!fid) return;
  const on = isGifFav(m);
  api(on ? 'DELETE' : 'POST', '/api/gifs/favorites', { media_id: fid })
    .then(function () {
      if (on) {
        store.gifFavs = store.gifFavs.filter(function (f) {
          return f.media_id !== fid;
        });
      } else {
        store.gifFavs.unshift({ media_id: fid, name: '', url: m.media.url });
      }
    })
    .catch(function () { toast('No se pudo guardar el favorito', 'err'); });
};
const toggleLibGif = function (name) {
  const on = isLibGifFav(name);
  api(on ? 'DELETE' : 'POST', '/api/gifs/favorites', { name: name })
    .then(function () {
      if (on) {
        store.gifFavs = store.gifFavs.filter(function (f) {
          return f.name !== name;
        });
      } else {
        store.gifFavs.unshift({ media_id: 0, name: name,
          url: '/static/gifs/' + name });
      }
    })
    .catch(function () { toast('No se pudo guardar el favorito', 'err'); });
};

const EmojiPicker = {
  /* W29g: embed = embebido en el panel unificado del compositor (3
     pestañas); ahí el tamaño y el clamp los lleva el padre. */
  props: { embed: Boolean },
  emits: ['pick'],
  setup: function (props, ctxEmit) {
    const q = Vue.ref('');
    const tab = Vue.ref('recientes');
    const cats = emojiCats();
    /* W29b: UNA sola lista con subtítulos por categoría ("Recientes:",
       "Caras y emociones:", …); la búsqueda plana reemplaza la lista. */
    const sections = Vue.computed(function () {
      if (q.value.trim()) return [];
      const rec = emojiRecent();
      const out = [];
      if (rec.length) out.push({ id: 'recientes', label: 'Recientes', items: rec });
      for (let i = 0; i < cats.length; i++) {
        if (cats[i].id === 'recientes') continue;
        const items = emojiCat(cats[i].id);
        if (items.length) {
          out.push({ id: cats[i].id, label: cats[i].name, items: items });
        }
      }
      return out;
    });
    const flat = Vue.computed(function () {
      return q.value.trim() ? emojiSearch(q.value) : [];
    });
    const empty = Vue.computed(function () {
      return q.value.trim() ? t('Sin coincidencias.') : t('Aún no usas emojis.');
    });
    const pick = function (ch) {
      emojiPush(ch);          // recientes compartidos entre ambos usos
      ctxEmit.emit('pick', ch);
    };
    /* W29b: clic en el ícono de categoría → salta la lista a ella. */
    const scrollEl = Vue.ref(null);
    const jump = function (id) {
      q.value = '';
      tab.value = id;
      Vue.nextTick(function () {
        const sc = scrollEl.value;
        const el = sc && sc.querySelector('#ep-' + id);
        if (sc && el) sc.scrollTop = el.offsetTop;
      });
    };
    /* W29b: al pasar de sección (o al saltar) el ícono activo se ilumina. */
    const onScroll = function () {
      if (q.value.trim()) return;
      const sc = scrollEl.value;
      if (!sc) return;
      const subs = sc.querySelectorAll('.ep-sub');
      const list = sections.value;
      if (!list.length) return;
      let cur = list[0].id;
      for (let i = 0; i < subs.length; i++) {
        if (subs[i].offsetTop <= sc.scrollTop + 4) {
          cur = subs[i].id.slice(3);
        }
      }
      tab.value = cur;
    };
    const fileOf = function (ch) { return emoFile(ch); };
    const srcOf = function (ch) { return emoSrc(ch); };
    const titleOf = function (ch) { return emojiCode(ch); };
    /* W16: el panel queda fijo y clampeado al área de mensajes; se recalcula
       al abrir (sin la animación de entrada) y al redimensionar la ventana. */
    const rootEl = Vue.ref(null);
    const doClamp = function (first) { clampPanel(rootEl.value, !!first); };
    /* W29g: embebido, el padre (.st-panel) hace el clamp; aquí la
       posición no se toca. */
    if (!props.embed) Vue.onMounted(function () { doClamp(true); });
    const onPanelResize = function () { if (!props.embed) doClamp(false); };
    window.addEventListener('resize', onPanelResize);
    /* W16: el panel puede crecer después de montar (fuentes, lista, etc.):
       el ResizeObserver vuelve a ajustarlo, dejando pasar la animación
       de entrada (140 ms) para no medir a mitad del transform. */
    let roTimer = 0;
    const roPanel = new ResizeObserver(function () {
      clearTimeout(roTimer);
      roTimer = setTimeout(function () { doClamp(false); }, 180);
    });
    if (!props.embed) Vue.onMounted(function () { roPanel.observe(rootEl.value); });
    Vue.onUnmounted(function () {
      window.removeEventListener('resize', onPanelResize);
      clearTimeout(roTimer);
      roPanel.disconnect();
    });
    return { q, tab, cats, sections, flat, empty, pick, t, rootEl,
             scrollEl, jump, onScroll, fileOf, srcOf, titleOf };
  },
  template:
    '<div class="emo-picker" ref="rootEl" @click.stop>' +
      '<div class="ep-search">' +
        '<svg class="ic ic-sm"><use href="#i-search"></use></svg>' +
        '<input v-model="q" :placeholder="t(\'Buscar emoji\')" ' +
          ':aria-label="t(\'Buscar emoji\')" @keydown.esc.stop="q = \'\'">' +
      '</div>' +
      '<div class="ep-body">' +
        '<div class="ep-cats">' +
          '<button class="ep-cat" v-for="c in cats" :key="c.id" ' +
            ':class="{ on: !q.trim() && tab === c.id }" type="button" ' +
            ':title="t(c.name)" @click="jump(c.id)">' +
            '<img v-if="fileOf(c.icon)" class="emo" :src="srcOf(c.icon)" ' +
              ':alt="c.icon" loading="lazy">' +
            '<span v-else>{{ c.icon }}</span>' +
          '</button>' +
        '</div>' +
        '<div class="ep-scroll" ref="scrollEl" @scroll.passive="onScroll">' +
          '<template v-if="!q.trim()">' +
            '<div class="ep-sec" v-for="s in sections" :key="s.id">' +
              '<div class="ep-sub" :id="\'ep-\' + s.id">{{ t(s.label) }}:</div>' +
              '<div class="ep-grid">' +
                '<button class="ep-e" type="button" v-for="e in s.items" ' +
                  ':key="e" @click="pick(e)" :title="titleOf(e)">' +
                  '<img v-if="fileOf(e)" class="emo" :src="srcOf(e)" ' +
                    ':alt="e" loading="lazy">' +
                  '<span v-else>{{ e }}</span>' +
                '</button>' +
              '</div>' +
            '</div>' +
          '</template>' +
          '<div class="ep-grid" v-else>' +
            '<button class="ep-e" type="button" v-for="e in flat" :key="e" ' +
              '@click="pick(e)" :title="titleOf(e)">' +
              '<img v-if="fileOf(e)" class="emo" :src="srcOf(e)" ' +
                ':alt="e" loading="lazy">' +
              '<span v-else>{{ e }}</span>' +
            '</button>' +
          '</div>' +
          '<div class="ep-empty" v-if="!q.trim() ? !sections.length : !flat.length">' +
            '{{ empty }}</div>' +
        '</div>' +
      '</div>' +
    '</div>',
};

/* ------------------------------------------------------- MessageRow */

/* W8: sólo un audio suena a la vez en toda la app. */
let currentAudioEl = null;

const MessageRow = {
  components: { EmojiPicker },
  props: { row: { type: Object, required: true } },
  emits: ['imgload', 'reply', 'react', 'openprofile', 'zoom', 'saveedit', 'upcancel', 'upretry', 'menu'],
  setup: function (props, ctx) {
    const emit = ctx.emit;
    /* W17: el picker vive en store.reactFor (antes era un ref local por
       fila). Así solo hay UN panel de reacciones abierto a la vez, el
       clic exterior lo cierra (onDocClick) y el composer/menú contextual
       lo cierran al abrirse. */

    const replyName = function (row) {
      const rp = row.ref.reply_to;
      if (!rp || !rp.sender) return '';
      // El servidor manda sender como string (display_name o username).
      if (typeof rp.sender === 'string') return rp.sender;
      return rp.sender.display_name || rp.sender.username || '';
    };
    const replyText = function (row) {
      const rp = row.ref.reply_to;
      if (!rp) return '';
      /* W45: citar un spoiler no lo destapa (ni con el texto local). */
      if (rp.spoiler) return t('Spoiler');
      /* W37a: con E2E el server sólo manda el marcador; el texto real
         vive en el mensaje original ya descifrado (store.msgs). Si
         está local, se cita el texto REAL (igual que en el chat). */
      let txt = rp.body;
      if (txt === '[Mensaje cifrado]' || !txt) {
        const arr = store.msgs[store.activeChatId];
        if (arr) {
          for (let i = arr.length - 1; i >= 0; i--) {
            if (arr[i].id === rp.id && arr[i]._plain != null) {
              txt = arr[i]._plain;
              break;
            }
          }
        }
      }
      if (txt) return txt;
      if (rp.kind === 'voice') return t('Nota de voz');
      if (rp.kind === 'image') return t('Imagen');
      if (rp.kind === 'system') return '';
      return t('Archivo adjunto');
    };
    const groupReactions = function (m) {
      const out = [];
      const rs = m.reactions || [];
      for (let i = 0; i < rs.length; i++) {
        let g = null;
        for (let j = 0; j < out.length; j++) if (out[j].emoji === rs[i].emoji) g = out[j];
        if (g) g.count++;
        else out.push({ emoji: rs[i].emoji, count: 1 });
      }
      return out;
    };

    /* Mi reacción actual en este mensaje (server: 1 por usuario). */
    const myReaction = function (m) {
      if (!store.user) return '';
      const rs = m.reactions || [];
      for (let i = 0; i < rs.length; i++) {
        if (rs[i].user_id === store.user.id) return rs[i].emoji;
      }
      return '';
    };

    const doReply = function (row) {
      store.reactFor = 0;
      emit('reply', row.ref);
    };
    const doReact = function (row, emoji) {
      store.reactFor = 0;
      fullReact.value = false;
      /* W17: quitar la propia reacción no cuenta como "uso"; agregar
         sí la sube de puesto en la barra rápida. */
      if (myReaction(row.ref) !== emoji) reactBump(emoji);
      emit('react', row.ref, emoji);
    };

    /* Picker de reacciones: hover (botón emoji) o menú contextual
       (store.reactFor). Clic en el chip propio = quitar. */
    const pickerOpen = function (row) {
      return store.reactFor !== 0 && store.reactFor === row.ref.id;
    };
    const togglePicker = function () {
      const open = pickerOpen(props.row);
      store.emoOpen = false;     // W17: un solo panel flotante a la vez
      store.ctx = null;
      store.reactFor = open ? 0 : props.row.ref.id;
      fullReact.value = false;
    };
    /* W13: desde el picker chico se abre el selector completo. */
    const fullReact = Vue.ref(false);
    const toggleFull = function () {
      fullReact.value = !fullReact.value;
    };
    /* W17: ⋯ de la barra hover → el menú contextual del mensaje. */
    const openMenu = function (row, ev) {
      emit('menu', { row: row, ev: ev });
    };
    /* W17: al cerrar el picker se resetea el panel completo. */
    Vue.watch(function () { return store.reactFor; }, function () {
      if (!pickerOpen(props.row)) fullReact.value = false;
    });

    /* W17: los 12 chips rápidos ordenados por uso (reactRank es reactivo:
       al reaccionar se reordena al instante). */
    const emojis = Vue.computed(function () { return reactRank(12); });

    /* W16: al abrir los chips se clampean al área de mensajes (si no, en
       mensajes cortos a la izquierda o arriba del todo quedaban cortados
       por el overflow de .msgs). */
    const rpEl = Vue.ref(null);
    Vue.watch(function () { return store.reactFor; }, function () {
      if (!pickerOpen(props.row)) return;
      Vue.nextTick(function () { clampPanel(rpEl.value, false); });
    });

    /* ---- W8: reproductor de audio propio (no usa <audio controls>) ---- */
    const aEl = Vue.ref(null);
    const aPlaying = Vue.ref(false);
    const aCur = Vue.ref(0);
    const aDur = Vue.ref(0);

    const fmtTime = function (s) {
      if (!s || s < 0 || !isFinite(s)) return '0:00';
      const m = Math.floor(s / 60);
      const ss = Math.floor(s % 60);
      return m + ':' + (ss < 10 ? '0' : '') + ss;
    };
    /* W51: play() puede rechazar (sin fuente, códec ausente, gesto
       bloqueado). Sin .catch, Mypal llenaba la consola de
       "Uncaught (in promise) NotSupportedError". */
    const safePlay = function (el) {
      if (!el) return;
      try {
        const p = el.play();
        if (p && p.catch) p.catch(function () {});
      } catch (e) {}
    };
    /* W53: qué formato tiene realmente la fuente actual. Con blob no se
       puede leer ?fmt=, así que miramos el MIME del Blob descargado. */
    const audioSrcFmt = function (el) {
      if (!el) return '';
      const src = el.currentSrc || el.src || '';
      const fm = /[?&]fmt=([a-z0-9]+)/i.exec(src);
      if (fm) return fm[1].toLowerCase();
      const raw = getBlob(src);
      const mt = raw && raw.type
        ? String(raw.type).split(';')[0].trim().toLowerCase() : '';
      if (mt === 'audio/ogg' || mt === 'application/ogg') return 'ogg';
      if (mt === 'audio/wav' || mt === 'audio/x-wav') return 'wav';
      if (mt === 'audio/mpeg') return 'mp3';
      if (mt === 'audio/webm') return 'webm';
      return '';
    };
    /* W51/W53: si el navegador no decodifica el original, cambia el src
       al derivado compatible del server (MP4/Ogg/WAV), conserva la
       descarga en segundo plano y deja la URL para la próxima apertura.
       Audio: Ogg Vorbis primero y WAV PCM como último recurso. */
    const compatFallback = function (el, tag, tries) {
      const m = props.row.ref.media;
      if (!m || !m.url) return '';
      const cur = tag === 'AUDIO' ? audioSrcFmt(el) : '';
      let forceFmt = '';
      if (tag === 'AUDIO') {
        if (cur === 'wav') return '';
        if (cur === 'ogg' || tries > 0) forceFmt = 'wav';
        else forceFmt = audioFallbackFmt();
      }
      const alt = compatUrl(m.url, m.mime, tag, true, forceFmt);
      if (!alt || alt === m.url) return '';
      if (tag === 'AUDIO' && cur === 'ogg') markOggBroken();
      markMediaCompat(m.mime);
      forgetCached(m.url);
      el.__dlNoSwap = true;
      cacheMedia(alt);
      return alt;
    };
    const aTime = Vue.computed(function () {
      return fmtTime(aCur.value) + ' / ' + fmtTime(aDur.value);
    });
    const aPct = Vue.computed(function () {
      if (!aDur.value) return 0;
      return Math.min(100, (aCur.value / aDur.value) * 100);
    });
    let aWantPlay = false;
    const togglePlay = function () {
      const el = aEl.value;
      if (!el) return;
      if (el.paused) {
        if (currentAudioEl && currentAudioEl !== el) {
          try { currentAudioEl.pause(); } catch (e) {}
        }
        currentAudioEl = el;
        aWantPlay = true;
        /* W51: si por cualquier motivo el <audio> aún no tiene fuente,
           empieza a reproducir la URL firmada (sin esperar al blob). */
        if (!el.currentSrc && !el.src) {
          const m = props.row.ref.media;
          if (!m || !m.url) return;
          el.__dlNoSwap = true;
          el.src = compatUrl(m.url, m.mime, 'AUDIO');
          try { el.load(); } catch (e) {}
        }
        /* W13 fix: notas viejas sin dur → resolverla al primer play */
        if (!aDur.value) resolveDur(el);
        safePlay(el);
      } else {
        el.pause();
      }
    };

    /* W13: último recurso para WebM sin duración (notas viejas): decodifica
       el archivo. Solo al pulsar reproducir (no al cargar).
       W15: usa el blob YA descargado (mediadl.js) — sin fetch, sin red y
       sin depender del CSP; si no está en memoria, cae al fetch de antes. */
    const aResolving = Vue.ref(false);
    const decodeDurBuf = function (buf) {
      if (!buf) { aResolving.value = false; return; }
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) { aResolving.value = false; return; }
      let ctx;
      try { ctx = new AC(); } catch (e) { aResolving.value = false; return; }
      let closed = false;
      const finish = function () {
        aResolving.value = false;
        if (closed) return;
        closed = true;
        try { ctx.close(); } catch (e) {}
      };
      const got = function (ab) {
        /* decodeAudioData entrega un AudioBuffer (no un número): la duración
           está en ab.duration. (Antes se hacía isFinite(sobre el buffer) y
           nunca guardaba; solo se enmascaraba porque el seek resolvía antes.) */
        const dd = ab && ab.duration;
        if (dd && isFinite(dd) && dd > 0) aDur.value = dd;
        finish();
      };
      const failed = function () { finish(); };
      try {
        /* FF78 devuelve una promesa aunque se pasen callbacks. Si el códec
           no está disponible, esa promesa se rechaza y sin catch quedaba
           "Uncaught (in promise) EncodingError" en Mypal. */
        const p = ctx.decodeAudioData(buf, got, failed);
        if (p && typeof p.catch === 'function') p.catch(failed);
      } catch (e) { finish(); }
    };
    const resolveDur = function (el) {
      if (aResolving.value || aDur.value) return;
      const src = el.currentSrc || el.src;
      if (!src) return;
      aResolving.value = true;
      const raw = getBlob(src);
      if (raw && raw.arrayBuffer) {            // en memoria: decodificar ya
        raw.arrayBuffer()
          .then(decodeDurBuf)
          .catch(function () { aResolving.value = false; });
        return;
      }
      if (typeof fetch !== 'function') { aResolving.value = false; return; }
      fetch(src, { credentials: 'omit' })
        .then(function (r) { return r.ok ? r.arrayBuffer() : null; })
        .then(decodeDurBuf)
        .catch(function () { aResolving.value = false; });
    };
    const seek = function (e) {
      const el = aEl.value;
      if (!el || !aDur.value) return;
      const bar = e.currentTarget.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - bar.left) / bar.width));
      el.currentTime = ratio * aDur.value;
    };
    /* W37d: velocidad de la NOTA DE VOZ (1× → 1,5× → 2× → 1×) */
    const aRateV = Vue.ref(1);
    const aRate = function () {
      const el = aEl.value;
      const next = aRateV.value === 1 ? 1.5 : (aRateV.value === 1.5 ? 2 : 1);
      aRateV.value = next;
      if (el) el.playbackRate = next;
    };
    const aMeta = function (e) {
      const d = e.target.duration;
      /* Fix W13: los WebM de MediaRecorder no traen duración en el
         encabezado (el elemento reporta Infinity → se veía "0:00").
         Preferimos la duración que guardó quien grabó; si no la hay
         (audios viejos), forzamos la carga total con un seek lejano. */
      if (isFinite(d) && d > 0) { aDur.value = d; return; }
      const known = props.row.ref.dur;
      if (known && known > 0) { aDur.value = known; return; }
      aDur.value = 0;
      /* W15: si el blob está en memoria lo decodificamos para la duración;
         el truco del seek lejano (W13) rompía la reproducción cuando el
         audio ya venía cargado entero como blob (webm de MediaRecorder
         sin duración en el encabezado). Solo se usa el seek en streaming. */
      const msrc = e.target.currentSrc || e.target.src;
      if (getBlob(msrc)) { resolveDur(e.target); return; }
      try { e.target.currentTime = 1e6; } catch (err) {}
    };
    /* W51/W53: el audio original no se pudo decodificar (Mypal 78 con
       WebM/Opus o MP3/WMF). Se prueba Ogg Vorbis y, si también falla,
       WAV PCM; no se muestra un error porque el reproductor sigue siendo
       el mismo. */
    let aErrTries = 0;
    const aErrEv = function (e) {
      if (aErrTries >= 2) return;
      const el = e.target;
      const alt = compatFallback(el, 'AUDIO', aErrTries);
      if (!alt) return;
      aErrTries++;
      el.src = alt;
      try { el.load(); } catch (err) {}
      /* Si el usuario ya había pulsado play, el cambio de formato no debe
         costarle un segundo clic. */
      if (aWantPlay) safePlay(el);
    };
    /* Tras el seek lejano el navegador calcula la duración real; si no,
       el extremo cargado da una pista (W13 fix del "0:00" eterno). */
    const aDurEv = function (e) {
      const el = e.target;
      if (isFinite(el.duration) && el.duration > 0) { aDur.value = el.duration; return; }
      try {
        if (el.seekable && el.seekable.length && el.seekable.end(0) > 0.5) {
          aDur.value = el.seekable.end(0);
        }
      } catch (err) { /* sin seekable: seguir esperando */ }
    };
    const aTimeUpd = function (e) { aCur.value = e.target.currentTime || 0; };
    /* W16: progreso suave. En Firefox timeupdate llega ~1 vez por segundo
       (y con 34 barras la onda se movía literalmente a "1 fps"): mientras
       suena, requestAnimationFrame mantiene barra y tiempo a ~60 fps.
       timeupdate queda como respaldo (seek con el audio pausado). */
    let aRaf = 0;
    const aRafStop = function () {
      if (aRaf) { cancelAnimationFrame(aRaf); aRaf = 0; }
      const el = aEl.value;
      if (el) aCur.value = el.currentTime || 0;   /* estado final exacto */
    };
    const aTick = function () {
      aRaf = 0;
      const el = aEl.value;
      if (!el || el.paused || el.ended) return;   /* sin nueva tanda */
      aCur.value = el.currentTime || 0;
      aRaf = requestAnimationFrame(aTick);
    };
    const aPlayEv = function () {
      aWantPlay = false;
      aPlaying.value = true;
      if (!aRaf) aRaf = requestAnimationFrame(aTick);
    };
    const aPauseEv = function () {
      aWantPlay = false;
      aPlaying.value = false;
      aRafStop();
    };
    const aEndEv = function () {
      aPlaying.value = false;
      aRafStop();
      /* W13: tras escucharla completa ya sabemos cuánto dura */
      if (!aDur.value && aCur.value) aDur.value = aCur.value;
      aCur.value = 0;
      try { aEl.value.currentTime = 0; } catch (e) {}
    };
    Vue.onUnmounted(aRafStop);

    /* ---- W36c: reproductor PROPIO de video (controles dentro del
       video): play/pausa al centro, barra + hora + silencio + pantalla
       completa abajo; los controles se ocultan a los 1 s de inactividad
       mientras reproduce (con pausa siempre se ven). ---- */
    const vEl = Vue.ref(null);
    const vWrapEl = Vue.ref(null);
    const vPlaying = Vue.ref(false);
    const vCur = Vue.ref(0);
    const vDur = Vue.ref(0);
    const vMuted = Vue.ref(false);
    const vHide = Vue.ref(false);
    let vHideT = 0;
    const vArmHide = function () {
      if (vHideT) { clearTimeout(vHideT); vHideT = 0; }
      if (!vPlaying.value) { vHide.value = false; return; }
      vHideT = setTimeout(function () { vHide.value = true; }, 1000);
    };
    const vPeek = function () {
      vHide.value = false;
      vArmHide();
    };
    const vCurTxt = Vue.computed(function () { return fmtTime(vCur.value); });
    const vDurTxt = Vue.computed(function () { return fmtTime(vDur.value); });
    const vPct = Vue.computed(function () {
      if (!vDur.value) return '0%';
      return Math.min(100, (vCur.value / vDur.value) * 100) + '%';
    });
    let vWantPlay = false;
    const toggleV = function () {
      const el = vEl.value;
      if (!el) return;
      if (el.paused) {
        if (currentAudioEl && currentAudioEl !== el) {
          try { currentAudioEl.pause(); } catch (e) {}
        }
        currentAudioEl = el;
        vWantPlay = true;
        /* W51: primer clic mientras v-dl todavía baja el archivo. Antes
           el video no tenía src y el clic se perdía. Ahora arranca el
           streaming firmado al instante; la descarga completa sigue en
           segundo plano y NO reemplaza la fuente que ya suena. */
        if (!el.currentSrc && !el.src) {
          const m = props.row.ref.media;
          if (!m || !m.url) return;
          el.__dlNoSwap = true;
          el.src = compatUrl(m.url, m.mime, 'VIDEO');
          try { el.load(); } catch (e) {}
        }
        safePlay(el);
      } else {
        el.pause();
      }
    };
    const vSeekTo = function (e) {
      const el = vEl.value;
      if (!el || !vDur.value) return;
      const bar = e.currentTarget.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - bar.left) / bar.width));
      el.currentTime = ratio * vDur.value;
      vPeek();
    };
    const vMute = function () {
      const el = vEl.value;
      if (!el) return;
      el.muted = !el.muted;
      vMuted.value = el.muted;
    };
    /* W43: el botón ALTERNA — si este video ya está en pantalla
       completa, el segundo clic SALE (antes pedir fullscreen estando
       en fullscreen era no-op: no había forma de salir con el botón).
       vFs cambia icono (expand/collapse) y rótulo. */
    const vFs = Vue.ref(false);
    const vFsChange = function () {
      const doc = document;
      vFs.value = (doc.fullscreenElement || doc.webkitFullscreenElement)
        === vWrapEl.value;
    };
    document.addEventListener('fullscreenchange', vFsChange);
    document.addEventListener('webkitfullscreenchange', vFsChange);
    Vue.onUnmounted(function () {
      document.removeEventListener('fullscreenchange', vFsChange);
      document.removeEventListener('webkitfullscreenchange', vFsChange);
    });
    const vFull = function () {
      const el = vWrapEl.value;
      const doc = document;
      if (!el) return;
      const cur = doc.fullscreenElement || doc.webkitFullscreenElement;
      if (cur === el) {
        if (doc.exitFullscreen) doc.exitFullscreen();
        else if (doc.webkitExitFullscreen) doc.webkitExitFullscreen();
        return;
      }
      let p = null;
      if (el.requestFullscreen) p = el.requestFullscreen();
      else if (el.webkitRequestFullscreen) p = el.webkitRequestFullscreen();
      if (p && p.catch) p.catch(function () {});   /* bloqueado: no-op */
    };
    const vMeta = function (e) {
      const d = e.target.duration;
      vDur.value = (isFinite(d) && d > 0) ? d : 0;
      /* W29a: sin pista de video (sonido solo) → el bloque cae al
         reproductor de audio (misma prueba que antes en vidMeta). */
      if (e.target && !e.target.videoHeight) vidOk.value = false;
      const nw = e.target && +e.target.videoWidth;
      const nh = e.target && +e.target.videoHeight;
      if (nw > 0 && nh > 0) {
        vNatW.value = nw;
        vNatH.value = nh;
      }
    };
    const vTimeUpd = function (e) { vCur.value = e.target.currentTime || 0; };
    const vPlayEv = function () {
      vWantPlay = false;
      vPlaying.value = true;
      vArmHide();
      /* W37d: si reproduce, la descarga ya terminó: limpia el overlay
         residual (anillo/✕) que a veces quedaba visible. */
      vClearDlState();
    };
    const vPauseEv = function () {
      vWantPlay = false;
      vPlaying.value = false;
      if (vHideT) { clearTimeout(vHideT); vHideT = 0; }
      vHide.value = false;
    };
    const vEndEv = function () {
      vPlaying.value = false;
      vHide.value = false;
      vCur.value = 0;
      try { vEl.value.currentTime = 0; } catch (e) {}
    };
    /* W37d: control de VOLUMEN con popup (slider) — al abrirlo la hora
       se desvanece (transition) para no amontonar la barra. */
    const vVol = Vue.ref(1);
    const vVolOpen = Vue.ref(false);
    const vSetVol = function (e) {
      const el = vEl.value;
      const v = Math.max(0, Math.min(1, parseFloat(e.target.value)));
      vVol.value = v;
      if (!el) return;
      el.volume = v;
      if (v > 0 && el.muted) { el.muted = false; vMuted.value = false; }
    };
    const vToggleVol = function () {
      vVolOpen.value = !vVolOpen.value;
      vPeek();
    };
    /* W37d: errores de decodificación/mime — "Este video tiene un error
       y no se puede reproducir" con icono de advertencia. */
    const vErr = Vue.ref(false);
    let vErrTried = false;
    const vErrEv = function (e) {
      if (!vErrTried) {
        vErrTried = true;
        const alt = compatFallback(e.target, 'VIDEO');
        if (alt) {                       /* sigue el player con MP4 */
          e.target.src = alt;
          try { e.target.load(); } catch (err) {}
          /* El primer clic en Mypal no se pierde: si el usuario quiso
             reproducir, el MP4 arranca al estar listo. */
          if (vWantPlay) safePlay(e.target);
          return;
        }
      }
      vErr.value = true;
    };
    /* W37d: si el video ya REPRODUCE, la descarga terminó — cualquier
       estado de overlay (anillo/✕) es residual: se limpia aquí (el bug
       era que la ✕ de cancelar quedaba visible con el video sonando).
       W43: markDlDone actualiza la fuente de verdad de las clases dl-*
       (si no, el re-assert de mediadl restauraría el estado viejo). */
    const vClearDlState = function () {
      markDlDone(vWrapEl.value);
    };
    /* W37d: guardar el video — si ya está en RAM (v-dl lo bajó) la
       descarga es instantánea; si no, pasa por startDownload. */
    const vDownload = function () {
      const m = props.row.ref.media;
      if (!m) return;
      startDownload(mediaUrl(m.url), m.name || 'video', vWrapEl.value);
    };
    /* clic en el centro del video = play/pausa (como en los players
       comerciales); el botón central usa .stop para no duplicar */
    const vClickCenter = function () {
      vPeek();
      toggleV();
    };
    Vue.onUnmounted(function () {
      if (vHideT) clearTimeout(vHideT);
    });

    /* ---- W36c: audio adjunto (mp3/ogg/…) con el MISMO player propio
       que las notas de voz: play/pausa, barra, hora y velocidad. El
       <audio> queda oculto (los tests y la descarga lo siguen usando). ---- */
    const afEl = Vue.ref(null);
    const afPlaying = Vue.ref(false);
    const afCur = Vue.ref(0);
    const afDur = Vue.ref(0);
    const afRateV = Vue.ref(1);
    const afCurTxt = Vue.computed(function () { return fmtTime(afCur.value); });
    const afDurTxt = Vue.computed(function () { return fmtTime(afDur.value); });
    const afPct = Vue.computed(function () {
      if (!afDur.value) return '0%';
      return Math.min(100, (afCur.value / afDur.value) * 100) + '%';
    });
    let afWantPlay = false;
    const afToggle = function () {
      const el = afEl.value;
      if (!el) return;
      if (el.paused) {
        if (currentAudioEl && currentAudioEl !== el) {
          try { currentAudioEl.pause(); } catch (e) {}
        }
        currentAudioEl = el;
        afWantPlay = true;
        if (!el.currentSrc && !el.src) {
          const m = props.row.ref.media;
          if (!m || !m.url) return;
          el.__dlNoSwap = true;
          el.src = compatUrl(m.url, m.mime, 'AUDIO');
          try { el.load(); } catch (e) {}
        }
        safePlay(el);
      } else {
        el.pause();
      }
    };
    const afSeek = function (e) {
      const el = afEl.value;
      if (!el || !afDur.value) return;
      const bar = e.currentTarget.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - bar.left) / bar.width));
      el.currentTime = ratio * afDur.value;
    };
    const afRate = function () {
      const el = afEl.value;
      const next = afRateV.value === 1 ? 1.5 : (afRateV.value === 1.5 ? 2 : 1);
      afRateV.value = next;
      if (el) el.playbackRate = next;
    };
    /* W37d: guardar el audio adjunto (en RAM la descarga es al toque) */
    const afDl = function () {
      const m = props.row.ref.media;
      if (!m) return;
      startDownload(mediaUrl(m.url), m.name || 'audio');
    };
    const afMeta = function (e) {
      const d = e.target.duration;
      afDur.value = (isFinite(d) && d > 0) ? d : 0;
    };
    let afErrTries = 0;
    const afErrEv = function (e) {
      if (afErrTries >= 2) return;
      const alt = compatFallback(e.target, 'AUDIO', afErrTries);
      if (!alt) return;
      afErrTries++;
      e.target.src = alt;
      try { e.target.load(); } catch (err) {}
      if (afWantPlay) safePlay(e.target);
    };
    const afTimeUpd = function (e) { afCur.value = e.target.currentTime || 0; };
    const afPlayEv = function () { afWantPlay = false; afPlaying.value = true; };
    const afPauseEv = function () { afWantPlay = false; afPlaying.value = false; };
    const afEndEv = function () {
      afPlaying.value = false;
      afCur.value = 0;
      try { afEl.value.currentTime = 0; } catch (e) {}
    };

    /* W13: onda de voz — 34 barras. Si el server trae los picos de la
       grabación se dibuja la forma real; si no (grabaciones viejas),
       un perfil neutro. La barra clickeada hace seek. */
    const WAVE_N = 34;
    const wave = Vue.computed(function () {
      const p = props.row.ref.peaks;
      const out = [];
      if (p && p.length) {
        const step = p.length / WAVE_N;
        for (let i = 0; i < WAVE_N; i++) {
          const a = Math.floor(i * step);
          const b = Math.max(a + 1, Math.floor((i + 1) * step));
          let s = 0;
          for (let j = a; j < b && j < p.length; j++) if (p[j] > s) s = p[j];
          out.push(Math.max(10, Math.min(100, s)));
        }
      } else {
        for (let i = 0; i < WAVE_N; i++) out.push(30 + ((i * 7) % 5) * 9);
      }
      return out;
    });
    const aBarF = Vue.computed(function () {
      return (aPct.value / 100) * WAVE_N;
    });
    const aBar = Vue.computed(function () {
      return Math.floor(aBarF.value);
    });
    /* W16: la barra "líder" (a medio llenar) se atenúa con opacity para
       que el borde de la onda avance de forma continua en vez de saltar
       de a 34 escalones; en el resto devuelve null (sin estilo inline).
       Sólo opacity → permitido y barato en FF78. */
    const waveOp = function (i) {
      if (i !== aBar.value + 1) return null;
      return (0.35 + 0.6 * (aBarF.value - aBar.value)).toFixed(3);
    };

    /* ---- W8: edición en línea (store.editFor desde el menú contextual) ---- */
    const editing = Vue.computed(function () {
      return store.editFor !== 0 && store.editFor === props.row.ref.id;
    });
    const editEl = Vue.ref(null);
    Vue.watch(editing, function (on) {
      if (!on) return;
      /* W32: el texto DESCIFRADO al editar (nunca el marcador). */
      const ref0e = props.row.ref;
      store.editDraft = (ref0e._plain != null ? ref0e._plain : ref0e.body) || '';
      Vue.nextTick(function () {
        const el = editEl.value;
        if (el) {
          el.focus();
          try {
            el.setSelectionRange(el.value.length, el.value.length);
          } catch (e) {}
        }
      });
    });
    const cancelEdit = function () {
      store.editFor = 0;
      store.editDraft = '';
    };
    const saveEdit = function () {
      const txt = store.editDraft;
      if (!txt.trim()) { cancelEdit(); return; }
      /* W17: los ":código:" se convierten igual que al enviar. */
      emit('saveedit', props.row.ref, shortcodesToEmoji(txt));
    };

    /* W11: helpers del círculo de subida (r=21 → circunferencia 132) */
    const isVideo = function (m) {
      return !!(m && /^video\//.test(m.mime || ''));
    };
    /* W29a: archivos de AUDIO (mp3/ogg/m4a/…) → reproductor <audio>
       nativo en vez de la fila de descarga. */
    const isAudio = function (m) {
      if (!m) return false;
      if (/^audio\//.test(m.mime || '')) return true;
      const n = (m.name || '').toLowerCase();
      return /\.(mp3|ogg|oga|m4a|wav|flac|aac|opus|weba)$/.test(n);
    };
    /* W29a: probe del <video> — si al cargar los metadatos no hay
       pista de video (videoHeight = 0, p. ej. un webm de audio) la
       burbuja cambia a <audio> en vez de mostrar un recuadro negro. */
    const vidOk = Vue.ref(true);
    /* W51: resolución real del video para reservar el marco antes de
       descargarlo (el server ya la manda en media.width/height; este
       respaldo cubre filas viejas hasta que se rellenen). */
    const vNatW = Vue.ref(0);
    const vNatH = Vue.ref(0);
    const vBox = Vue.computed(function () {
      const md = props.row.ref.media;
      const w = (md && +md.width) || vNatW.value;
      const h = (md && +md.height) || vNatH.value;
      if (w < 1 || h < 1) return null;
      /* tope 360×340, manteniendo la proporción; en móvil se ajusta al
         ancho visible para que el marco no desborde la burbuja. */
      const vw = (typeof window !== 'undefined' && window.innerWidth) || 1000;
      const cap = Math.max(160, Math.min(360, vw - 96));
      const bw = Math.min(cap, Math.round(340 * w / h), w);
      return {
        width: bw + 'px',
        height: Math.max(1, Math.round(bw * h / w)) + 'px',
      };
    });
    /* W36c: la prueba de pista de video ahora vive en vMeta (player propio). */
    /* W29a: la animación de entrada corre una sola vez; al terminar se
       quita la bandera para no repetirla en re-renders. */
    const animEnd = function (e) {
      if (e.target !== e.currentTarget) return;
      if (props.row.ref && props.row.ref._in) props.row.ref._in = false;
    };
    /* W22: si el server conoce la resolución de la imagen, el marco se
       reserva con esa proporción desde el principio y el spinner de
       descarga/subida queda dentro del cuadro. Sin resolución conocida
       (archivos viejos, SVG) → null: solo la miniatura difuminada. */
    const imgBox = Vue.computed(function () {
      const md = props.row.ref.media;
      const w = (md && +md.width) || 0;
      const h = (md && +md.height) || 0;
      if (w < 1 || h < 1) return null;
      /* tope 300×340 (los mismos del .b-img), manteniendo la proporción;
         en pantallas angostas se descuenta el avatar/margen para que la
         imagen no desborde la burbuja (W51, sin aspect-ratio). */
      const vw = (typeof window !== 'undefined' && window.innerWidth) || 1000;
      const cap = Math.max(120, Math.min(300, vw - 96));
      const bw = Math.min(cap, Math.round(340 * w / h), w);
      return {
        width: bw + 'px',
        height: Math.max(1, Math.round(bw * h / w)) + 'px',
      };
    });
    const upPct = function (up) {
      return Math.round((up.p || 0) * 100) + '%';
    };
    const upOff = function (up) {
      return 132 - 132 * (up.p || 0);
    };

    /* W15: clic en un archivo adjunto → baja con anillo de progreso y ✕ de
       cancelar; si ya está en memoria (o en el SW) lo guarda al toque. */
    const dlFile = function (row, ev) {
      if (ev && ev.preventDefault) ev.preventDefault();
      if (!row || !row.media || !row.media.url) return;
      const frame = ev && ev.currentTarget ? ev.currentTarget : null;
      startDownload(mediaUrl(row.media.url), row.media.name || 'archivo', frame);
    };

    /* W29b: dentro de cada trozo de texto, los emojis salen como
       segmentos propios con su archivo Twemoji (e); las menciones se
       conservan enteras. */

    /* W35a: enlaces con cualquier protocolo seguro de la lista (https,
       ftp, mailto, tel, …). javascript:/data: NO están en la lista,
       así que quedan como texto plano. Se trae la puntuación final
       (",." del final de la oración) fuera del enlace. */
    const LINK_OK = /^(?:https?|ftps?|mailto|tel|sms|geo|magnet|xmpp|ircs?|news|matrix|skype|tg|whatsapp|steam|spotify|market|callto)$/i;
    const LINK_RE = /[a-z][a-z0-9+.\-]*:(?:\/\/)?[^\s<>"']*/gi;

    const splitLinks = function (txt) {
      const res = [];
      let last = 0;
      LINK_RE.lastIndex = 0;
      let m = LINK_RE.exec(txt);
      while (m) {
        const raw = m[0];
        const start = m.index;
        const colon = raw.indexOf(':');
        const scheme = raw.slice(0, colon).toLowerCase();
        const url = raw.replace(/[.,;:!?)\]}'"]+$/, '');
        if (LINK_OK.test(scheme) && url.length > colon + 2) {
          if (start > last) res.push({ t: txt.slice(last, start) });
          res.push({ t: url, u: url });
          last = start + url.length;
          LINK_RE.lastIndex = last;
        } else {
          LINK_RE.lastIndex = start + colon + 1;   // sigue buscando dentro
        }
        m = LINK_RE.exec(txt);
      }
      if (last < txt.length) res.push({ t: txt.slice(last) });
      return res;
    };

    const splitSegs = function (arr) {
      const res = [];
      for (let i = 0; i < arr.length; i++) {
        const sg = arr[i];
        if (sg.m) { res.push(sg); continue; }
        const lks = splitLinks(sg.t);          /* W35a */
        for (let k = 0; k < lks.length; k++) {
          if (lks[k].u) { res.push(lks[k]); continue; }
          const parts = splitEmojis(lks[k].t);
          for (let j = 0; j < parts.length; j++) {
            res.push({ t: parts[j].t, e: parts[j].e || '', m: '', me: false });
          }
        }
      }
      return res;
    };

    /* W29b: título de un emoji = su :shortcode: (o el carácter solo). */
    const titleOf = function (ch) { return emojiCode(ch); };

    /* W41: UN solo emoji en el cuerpo → el mensaje se pinta como
       sticker (emoji grande, sin caja y con la hora en pastillita).
       No con cita (el bloque .b-reply rompería el look transparente)
       ni en edición (se ve el textarea). */
    const emoBig = function () {
      return props.row.ref.kind === 'text' && !editing.value &&
        !props.row.ref.reply_to && isOneEmoji(props.row.ref.body);
    };

    /* W29c: hover en un chip → quiénes reaccionaron ("😂 juan, maria"). */
    const reactTitle = function (msg, emoji) {
      const rs = msg.reactions || [];
      const names = [];
      for (let i = 0; i < rs.length; i++) {
        if (rs[i].emoji === emoji) {
          names.push(rs[i].name || rs[i].username || ('#' + rs[i].user_id));
        }
      }
      if (!names.length) return emojiCode(emoji);
      if (names.length > 3) {
        return emoji + ' ' + names.slice(0, 3).join(', ') + ' ' +
          t('y {n} más', { n: names.length - 3 });
      }
      return emoji + ' ' + names.join(', ');
    };

    /* W28b: texto de la burbuja partido en trozos, con las @menciones
       de los MIEMBROS del grupo marcadas (sólo en grupos: el server
       sólo cuenta menciones ahí). */
    const bodySegs = Vue.computed(function () {
      /* W29f: con E2E el server sólo ve el marcador; el texto real es
         _plain (se rellena al descifrar — o el mío al enviar). */
      const ref0 = props.row.ref;
      const txt = (ref0._plain != null ? ref0._plain : ref0.body) || '';
      const c = store.chats.find(function (x) {
        return x.id === store.activeChatId;
      });
      const inf = store.info;
      const mem = (c && c.type === 'group' && inf &&
                   inf.chatId === store.activeChatId && inf.members)
        ? inf.members : null;
      if (!mem || !mem.length) return splitSegs([{ t: txt, m: '', me: false }]);
      const names = {};
      for (let i = 0; i < mem.length; i++) {
        if (mem[i].username) names[mem[i].username.toLowerCase()] = 1;
      }
      const me = ((store.user && store.user.username) || '').toLowerCase();
      const out = [];
      const re = /@([A-Za-z0-9_.]{3,20})/g;
      let last = 0;
      let mm = re.exec(txt);
      while (mm) {
        const w = mm[1].toLowerCase();
        /* W37e: menciones globales — se reconocen escritas en CUALQUIER
           idioma (@everyone/@todos, @online/@activos) y se muestran en
           EL IDIOMA DEL LECTOR (@todos en es, @everyone en en). */
        if (w === 'everyone' || w === 'todos') {
          if (mm.index > last) out.push({ t: txt.slice(last, mm.index), m: '' });
          out.push({ t: t('@todos'), m: 'everyone', me: false });
          last = mm.index + mm[0].length;
        } else if (w === 'online' || w === 'activos') {
          if (mm.index > last) out.push({ t: txt.slice(last, mm.index), m: '' });
          out.push({ t: t('@activos'), m: 'online', me: false });
          last = mm.index + mm[0].length;
        } else if (names[w]) {
          if (mm.index > last) out.push({ t: txt.slice(last, mm.index), m: '' });
          out.push({ t: '@' + mm[1], m: mm[1], me: w === me });
          last = mm.index + mm[0].length;
        }
        mm = re.exec(txt);
      }
      if (last < txt.length || !out.length) out.push({ t: txt.slice(last), m: '' });
      return splitSegs(out);
    });

    /* W35b: imagen inline — una URL con extensión de imagen (.gif se
       ve ANIMADO) se pinta como <img>; el resto de links http(s) pide
       la "portada" al server (W35c) y, si resulta ser una imagen, se
       pinta igual. */
    const IMG_EXT = /\.(?:png|jpe?g|gif|webp|bmp|avif|svg)(?:$|\?)/i;
    const isHttp = function (u) { return /^https?:\/\//i.test(u); };
    const imgInline = function (u) {
      if (IMG_EXT.test(u)) return true;
      const p = store.linkPrev[u];
      return !!(p && p.status === 'ok' && p.type === 'image');
    };

    /* W35c: links http(s) sin extensión de imagen → tarjeta "portada"
       con título/descripción/imagen del sitio. */
    const msgLinks = Vue.computed(function () {
      const out = [];
      const segs = bodySegs.value;
      for (let i = 0; i < segs.length; i++) {
        const u = segs[i].u;
        if (u && isHttp(u) && !IMG_EXT.test(u) && out.indexOf(u) < 0) out.push(u);
      }
      return out;
    });
    Vue.watch(function () { return msgLinks.value; }, function (ls) {
      for (let i = 0; i < ls.length; i++) ensurePreview(ls[i]);
    }, { immediate: true });

    const linkCards = Vue.computed(function () {
      const out = [];
      const segs = bodySegs.value;
      const seen = {};
      for (let i = 0; i < segs.length; i++) {
        const u = segs[i].u;
        if (!u || !isHttp(u) || IMG_EXT.test(u) || seen[u]) continue;
        seen[u] = 1;
        const p = store.linkPrev[u];
        if (p && p.status === 'ok' && p.type === 'page') out.push({ url: u, d: p });
      }
      return out;
    });

    /* W29d: spoilers — tapado hasta que el usuario toque la capa. El
       estado vive en store.spoilSeen[chatId] y se vacía al salir. */
    const isSeen = function (m) {
      const s = store.spoilSeen[store.activeChatId];
      return !!(s && s[m.id]);
    };
    const spoiled = Vue.computed(function () {
      return !!props.row.ref.spoiler && !isSeen(props.row.ref);
    });
    const spoilShow = function (m) {
      if (!store.spoilSeen[store.activeChatId]) {
        store.spoilSeen[store.activeChatId] = {};
      }
      store.spoilSeen[store.activeChatId][m.id] = 1;
    };
    const spoilHide = function (m) {
      const s = store.spoilSeen[store.activeChatId];
      if (s && s[m.id]) delete s[m.id];
    };

    return {
      store, emojis, rpEl,
      bodySegs,
      /* W35a–c: enlaces, imagen inline y tarjetas */
      imgInline, linkCards,
      /* W36c: reproductores propios de video y audio adjunto */
      vEl, vWrapEl, vPlaying, vMuted, vHide, vCurTxt, vDurTxt, vPct,
      vPeek, toggleV, vSeekTo, vMute, vFull, vMeta, vTimeUpd, vFs,
      vPlayEv, vPauseEv, vEndEv, vClickCenter,
      /* W37d: volumen con popup, error de mime y descarga del video */
      vVol, vVolOpen, vSetVol, vToggleVol, vErr, vErrEv, vDownload, vBox,
      afEl, afPlaying, afRateV, afCurTxt, afDurTxt, afPct,
      afToggle, afSeek, afRate, afDl, afMeta, afTimeUpd, afPlayEv, afErrEv,
      afPauseEv, afEndEv,
      /* W37d: velocidad de la nota de voz */
      aRate, aRateV,
      /* W36k: ★ favorito del GIF */
      isGifFav, toggleFavGif,
      spoiled, spoilShow, spoilHide,   /* W29d */
      replyName, replyText, groupReactions, myReaction,
      doReply, doReact, mediaUrl, fmtSize, dlFile,
      pickerOpen, togglePicker, openMenu,
      /* W13 */
      fullReact, toggleFull, wave, aBar, waveOp,
      /* W22 */
      imgBox,
      /* W8 */
      aEl, aPlaying, aTime, aPct, togglePlay, seek,
      aMeta, aTimeUpd, aPlayEv, aPauseEv, aEndEv, aDurEv, aErrEv,
      editing, editEl, cancelEdit, saveEdit,
      /* W11: círculo de subida + video */
      isVideo, upPct, upOff,
      /* W29a */
      isAudio, vidOk, animEnd,
      /* W29b */
      emoFile, emoSrc, titleOf, reactTitle,
      emoBig,   /* W41 */
    };
  },
  template:
    '<div class="msg" :class="{ mine: row.mine, tight: row.tight, system: row.ref.kind === \'system\', reacts: !!(row.ref.reactions && row.ref.reactions.length), anim: !!row.ref._in }" @animationend="animEnd">' +
      /* W29c: columna de avatar en todos los entrantes de grupo; la
         cara (foto/letra) solo donde se ve el nombre del emisor */
      '<span class="msg-av" v-if="row.avCol" :class="{ \'is-av\': row.avatar }" ' +
        ':title="row.avatar ? row.avatar.name : \'\'">' +
        '<img v-if="row.avatar && row.avatar.url" :src="mediaUrl(row.avatar.url)" alt="" loading="lazy">' +
        '<i v-else-if="row.avatar">{{ row.avatar.ini }}</i>' +
      '</span>' +
      '<div v-if="row.ref.kind === \'system\'" class="sys-msg">{{ row.ref.body }}</div>' +
      '<div v-else class="bubble" :class="{ picking: pickerOpen(row), sticker: row.ref.kind === \'sticker\', \'emo-big\': emoBig(), \'is-spoiled\': spoiled, gif: !!(row.ref.kind === \'image\' && row.ref.media && row.ref.media.mime === \'image/gif\'), vid: !!(row.ref.kind === \'file\' && row.ref.media && isVideo(row.ref.media) && vidOk) }">' +
        /* W29d: capa de spoiler — tapa TODO lo de adentro (texto,
           medios y acciones) hasta que se toque; al tocar se muestra
           y el puntito del pie lo vuelve a ocultar. Mientras está
           tapado, los hijos se ocultan (visibility): con sólo el
           fondo translúcido el texto asomaba sobre burbujas claras. */
        '<button v-if="spoiled" class="b-spoil-ov" type="button" ' +
          '@click.stop="spoilShow(row.ref)">' +
          '<svg class="ic"><use href="#i-eye-off"></use></svg>' +
          '<span>{{ t(\'Mostrar Spoiler\') }}</span>' +
        '</button>' +
        '<div class="b-actions">' +
          '<button class="b-act" type="button" :title="t(\'Responder\')" @click="doReply(row)">' +
            '<svg class="ic ic-sm"><use href="#i-reply"></use></svg>' +
          '</button>' +
          '<button class="b-act" type="button" :title="t(\'Reaccionar\')" @click.stop="togglePicker">' +
            '<svg class="ic ic-sm"><use href="#i-smile"></use></svg>' +
          '</button>' +
          /* W36k: ★ favorito — sólo para GIFs (biblioteca o subidos) */
          '<button v-if="row.ref.kind === \'image\' && row.ref.media && ' +
            'row.ref.media.mime === \'image/gif\'" class="b-act" type="button" ' +
            ':title="isGifFav(row.ref) ? t(\'Quitar de favoritos\') : t(\'Agregar a favoritos\')" ' +
            '@click.stop="toggleFavGif(row.ref)">' +
            '<svg class="ic ic-sm"><use :href="isGifFav(row.ref) ? \'#i-star-fill\' : \'#i-star\'"></use></svg>' +
          '</button>' +
          /* W17: ⋯ abre el mismo menú del clic derecho, anclado a la
             burbuja (no tapa el mensaje). */
          '<button class="b-act b-more" type="button" :title="t(\'Más opciones\')" ' +
            '@click.stop="openMenu(row, $event)">' +
            '<svg class="ic ic-sm"><use href="#i-dots"></use></svg>' +
          '</button>' +
          '<span class="react-picker" ref="rpEl" v-if="pickerOpen(row)" @click.stop>' +
            '<button class="rp" :class="{ mine: myReaction(row.ref) === e }" type="button" ' +
              'v-for="e in emojis" :key="e" :title="titleOf(e)" @click="doReact(row, e)">' +
              '<img v-if="emoFile(e)" class="emo" :src="emoSrc(e)" ' +
                ':alt="e" loading="lazy">' +
              '<span v-else>{{ e }}</span></button>' +
            '<button class="rp rp-more" type="button" :title="t(\'Más emojis\')" ' +
              '@click="toggleFull">{{ fullReact ? \'–\' : \'＋\' }}</button>' +
            '<emoji-picker v-if="fullReact" @pick="doReact(row, $event)"></emoji-picker>' +
          '</span>' +
        '</div>' +
        /* W29c: el nombre del emisor va ARRIBA de la cita (antes la
           cita se dibujaba primero y "tapaba" al nombre); después la
           etiqueta de reenviado, la cita y el cuerpo del mensaje. */
        '<div v-if="row.showSender" class="b-sender">' +
          '<button type="button" :title="t(\'Ver perfil\')" ' +
            '@click="$emit(\'openprofile\', row.ref.sender.username)">' +
            '{{ row.ref.sender.display_name || row.ref.sender.username }}</button>' +
          '<span class="b-role" v-if="row.ref.sender.role === \'admin\' || row.ref.sender.role === \'owner\'">[Admin]</span>' +
        '</div>' +
        /* W13: etiqueta de mensaje reenviado (estilo WhatsApp) */
        '<div class="b-fwd" v-if="row.ref.forwarded">{{ t(\'Reenviado\') }}</div>' +
        '<div v-if="row.ref.reply_to" class="b-reply">' +
          '<span class="br-name">{{ replyName(row) }}</span>' +
          '<span class="br-text">{{ replyText(row) }}</span>' +
        '</div>' +
        /* W11: subida en curso → burbuja con círculo de progreso.
           W22: si la resolución local ya se conoce, el cuadro se reserva
           igual que con la imagen descargada. */
        '<span class="b-media b-upmedia" v-if="row.ref.pending && row.ref.upload && row.ref.kind === \'image\'" ' +
          ':class="{ imgbox: imgBox }" :style="imgBox">' +
          '<img class="b-img" :src="row.ref.localUrl || \'\'" alt="" @load="$emit(\'imgload\')">' +
          /* W23: anillo + ✕/↻ DENTRO del círculo (centrados al 50%) */
          '<span class="up-ov" :class="{ \'is-fail\': row.ref.upload.state === \'fail\' }">' +
            '<svg class="up-c" viewBox="0 0 48 48" aria-hidden="true" v-if="row.ref.upload.state === \'up\'">' +
              '<circle class="up-c-bg" cx="24" cy="24" r="21"></circle>' +
              '<circle class="up-c-fg" cx="24" cy="24" r="21" stroke-dasharray="132" ' +
                ':stroke-dashoffset="upOff(row.ref.upload)"></circle>' +
            '</svg>' +
            '<span class="up-pct" v-if="row.ref.upload.state === \'up\'">{{ upPct(row.ref.upload) }}</span>' +
            '<button class="up-btn" v-if="row.ref.upload.state === \'up\'" type="button" ' +
              ':title="t(\'Cancelar subida\')" @click.stop="$emit(\'upcancel\', row.ref)">' +
              '<svg class="ic ic-sm"><use href="#i-x"></use></svg></button>' +
            '<button class="up-btn" v-else type="button" ' +
              ':title="t(\'Reintentar subida\')" @click.stop="$emit(\'upretry\', row.ref)">' +
              '<svg class="ic ic-sm"><use href="#i-refresh"></use></svg></button>' +
          '</span>' +
        '</span>' +
        /* W22: nota de voz subiendo → fila con el aspecto del player y
           el anillo de progreso EN EL LUGAR DEL PLAY; el botón real de
           reproducción aparece cuando el server ya la tiene. */
        '<div class="b-player b-upvoice" v-else-if="row.ref.pending && row.ref.upload && row.ref.kind === \'voice\'">' +
          /* W23: anillo + ✕/↻ dentro del slot del play (centrado) */
          '<span class="au-btn">' +
            '<svg class="up-c" viewBox="0 0 48 48" v-if="row.ref.upload.state === \'up\'">' +
              '<circle class="up-c-bg" cx="24" cy="24" r="21"></circle>' +
              '<circle class="up-c-fg" cx="24" cy="24" r="21" stroke-dasharray="132" ' +
                ':stroke-dashoffset="upOff(row.ref.upload)"></circle>' +
            '</svg>' +
            '<button class="up-btn-static" v-if="row.ref.upload.state === \'up\'" type="button" ' +
              ':title="t(\'Cancelar subida\')" @click.stop="$emit(\'upcancel\', row.ref)">' +
              '<svg class="ic ic-sm"><use href="#i-x"></use></svg></button>' +
            '<button class="up-btn-static" v-else type="button" ' +
              ':title="t(\'Reintentar subida\')" @click.stop="$emit(\'upretry\', row.ref)">' +
              '<svg class="ic ic-sm"><use href="#i-refresh"></use></svg></button>' +
          '</span>' +
          '<span class="wave">' +
            '<i v-for="(h, i) in wave" :key="i" :style="{ height: h + \'%\' }"></i>' +
          '</span>' +
          '<span class="au-time" :class="{ \'is-err\': row.ref.upload.state === \'fail\' }">' +
            '{{ row.ref.upload.state === \'fail\' ? (row.ref.upload.err || t(\'No se pudo enviar la nota de voz\')) : fmtSize(row.ref.fsize) }}' +
          '</span>' +
        '</div>' +
        '<div class="b-file b-upfile" v-else-if="row.ref.pending && row.ref.upload">' +
          '<svg class="ic ic-sm"><use href="#i-file"></use></svg>' +
          '<span class="bf-col">' +
            '<span class="bf-name">{{ row.ref.fname || (row.ref.kind === \'voice\' ? t(\'Nota de voz\') : t(\'Archivo\')) }}</span>' +
            '<span class="bf-size" :class="{ \'is-err\': row.ref.upload.state === \'fail\' }">' +
              '{{ row.ref.upload.state === \'fail\' ? (row.ref.upload.err || t(\'No se pudo enviar el archivo\')) : fmtSize(row.ref.fsize) }}' +
            '</span>' +
          '</span>' +
          /* W23: anillo + ✕/↻ dentro de un slot circulante */
          '<span class="up-slot">' +
            '<svg class="up-c" viewBox="0 0 48 48" aria-hidden="true" v-if="row.ref.upload.state === \'up\'">' +
              '<circle class="up-c-bg" cx="24" cy="24" r="21"></circle>' +
              '<circle class="up-c-fg" cx="24" cy="24" r="21" stroke-dasharray="132" ' +
                ':stroke-dashoffset="upOff(row.ref.upload)"></circle>' +
            '</svg>' +
            '<button class="up-btn-static" v-if="row.ref.upload.state === \'up\'" type="button" ' +
              ':title="t(\'Cancelar subida\')" @click.stop="$emit(\'upcancel\', row.ref)">' +
              '<svg class="ic ic-sm"><use href="#i-x"></use></svg></button>' +
            '<button class="up-btn-static" v-else type="button" ' +
              ':title="t(\'Reintentar subida\')" @click.stop="$emit(\'upretry\', row.ref)">' +
              '<svg class="ic ic-sm"><use href="#i-refresh"></use></svg></button>' +
          '</span>' +
        '</div>' +
        /* W8: clic en la imagen → vista previa con zoom (lightbox).
           W15: v-dl baja el original con anillo; mientras tanto se ve la
           miniatura del server difuminada (?thumb=1).
           W22: con resolución conocida el marco se reserva (imgbox) y el
           anillo queda dentro del cuadro; sin ella solo la miniatura
           difuminada, sin anillo (data-noring). */
        '<span class="b-media mframe" v-else-if="row.ref.kind === \'image\' && row.ref.media" ' +
          ':class="{ imgbox: imgBox }" :style="imgBox" :data-noring="imgBox ? null : \'1\'" ' +
          'role="button" :title="t(\'Ver con zoom\')" ' +
          '@click="$emit(\'zoom\', mediaUrl(row.ref.media.url))">' +
          '<img class="b-img" v-dl="mediaUrl(row.ref.media.url)" :alt="row.ref.media.name || \'\'" @load="$emit(\'imgload\')">' +
        '</span>' +
        /* W11: video adjunto → player inline (W15: baja con anillo y ✕).
           W29a: si el archivo NO tiene pista de video (vidOk=false tras
           el probe de metadatos) cae al reproductor de audio.
           W36c: reproductor PROPIO — controles dentro del video (play
           al centro, hora/barra/fullscreen abajo, ocultos a los 1 s). */
        '<div class="b-video mframe" ref="vWrapEl" v-else-if="row.ref.kind === \'file\' && row.ref.media && isVideo(row.ref.media) && vidOk && !vErr" ' +
          ':class="{ vhide: vHide, vbox: vBox }" :style="vFs ? null : vBox" ' +
          '@mousemove="vPeek" @touchstart="vPeek" @click="vClickCenter">' +
          '<video class="b-vid" ref="vEl" playsinline preload="metadata" ' +
            ':data-mime="row.ref.media.mime" ' +
            'v-dl="mediaUrl(row.ref.media.url)" @loadedmetadata="vMeta" ' +
            '@timeupdate="vTimeUpd" @play="vPlayEv" @pause="vPauseEv" ' +
            '@ended="vEndEv" @error="vErrEv"></video>' +
          '<button class="v-center" type="button" ' +
            ':title="vPlaying ? t(\'Pausar\') : t(\'Reproducir\')" @click.stop="toggleV">' +
            '<svg class="ic"><use :href="vPlaying ? \'#i-pause\' : \'#i-play\'"></use></svg>' +
          '</button>' +
          '<div class="v-bar" @click.stop>' +
            '<button class="v-btn v-fs" type="button" ' +
              ':title="vFs ? t(\'Salir de pantalla completa\') : t(\'Pantalla completa\')" ' +
              '@click.stop="vFull"><svg class="ic ic-sm">' +
              '<use :href="vFs ? \'#i-collapse\' : \'#i-expand\'"></use></svg></button>' +
            /* W37d: al abrir el control de VOLUMEN la hora se desvanece */
            '<transition name="fade">' +
            '<span class="v-time" v-if="!vVolOpen">{{ vCurTxt }} / {{ vDurTxt }}</span>' +
            '</transition>' +
            '<span class="v-seek" @click.stop="vSeekTo"><i :style="{ width: vPct }"></i></span>' +
            /* W43: popup de volumen VERTICAL por ENCIMA del botón (en
               videos angostos el slider horizontal no cabía en la
               barra); mute abajo, slider girado arriba; fade al abrir */
            '<transition name="fade">' +
            '<span class="v-vol" v-if="vVolOpen" @click.stop>' +
              '<span class="v-vol-vt">' +
                '<input class="v-slider" type="range" min="0" max="1" step="0.05" ' +
                  ':value="vVol" aria-label="Volumen" @input="vSetVol">' +
              '</span>' +
              '<button class="v-btn" type="button" ' +
                ':title="vMuted ? t(\'Activar sonido\') : t(\'Silenciar\')" @click.stop="vMute">' +
                '<svg class="ic ic-sm"><use :href="vMuted ? \'#i-mute\' : \'#i-vol\'"></use></svg>' +
              '</button>' +
            '</span>' +
            '</transition>' +
            '<button class="v-btn" type="button" ' +
              ':title="vVolOpen ? t(\'Cerrar volumen\') : t(\'Volumen\')" @click.stop="vToggleVol">' +
              '<svg class="ic ic-sm"><use :href="vMuted ? \'#i-mute\' : \'#i-vol\'"></use></svg>' +
            '</button>' +
            /* W37d: guardar el video (si ya está en RAM, al toque) */
            '<button class="v-btn" type="button" :title="t(\'Descargar\')" ' +
              '@click.stop="vDownload"><svg class="ic ic-sm"><use href="#i-download"></use></svg></button>' +
          '</div>' +
          /* W36c: hora y palomitas DENTRO del video (abajo a la derecha) */
          '<div class="b-meta v-meta">' +
            '<span class="b-time" v-if="row.showTime && !row.ref.pending">{{ row.time }}</span>' +
            '<svg v-if="row.ref.pending" class="ic tick t-pend"><use href="#i-clock"></use></svg>' +
            '<svg v-else-if="row.mine" class="ic tick" :class="\'t-\' + row.state">' +
              '<use :href="row.state === \'sent\' ? \'#i-check\' : \'#i-check2\'"></use></svg>' +
          '</div>' +
        '</div>' +
        /* W37d: video con error (mime roto o decodificación imposible):
           aviso claro con icono en vez de un rectángulo negro mudo. */
        '<div class="b-video v-err" v-else-if="row.ref.kind === \'file\' && row.ref.media && isVideo(row.ref.media)">' +
          '<svg class="ic"><use href="#i-alert"></use></svg>' +
          '<span>{{ t(\'Este video tiene un error y no se puede reproducir\') }}</span>' +
        '</div>' +
        /* W29a: audio adjunto (mp3/ogg/… o webm sin video). W36c: player
           propio (play/pausa, barra, hora y velocidad); el <audio> queda
           oculto pero en el DOM (tests y descarga lo usan). */
        '<div class="b-afile mframe" v-else-if="row.ref.kind === \'file\' && row.ref.media && (isAudio(row.ref.media) || isVideo(row.ref.media))">' +
          '<audio ref="afEl" class="b-audio" preload="metadata" ' +
            ':data-mime="row.ref.media.mime" ' +
            'v-dl="mediaUrl(row.ref.media.url)" @loadedmetadata="afMeta" ' +
            '@timeupdate="afTimeUpd" @play="afPlayEv" @pause="afPauseEv" ' +
            '@ended="afEndEv" @error="afErrEv"></audio>' +
          '<button class="au-btn" type="button" ' +
            ':title="afPlaying ? t(\'Pausar\') : t(\'Reproducir\')" @click="afToggle">' +
            '<svg class="ic"><use :href="afPlaying ? \'#i-pause\' : \'#i-play\'"></use></svg>' +
          '</button>' +
          '<span class="au-seek" @click="afSeek"><i :style="{ width: afPct }"></i></span>' +
          '<span class="au-time">{{ afCurTxt }} / {{ afDurTxt }}</span>' +
          '<button class="au-rate" type="button" :title="t(\'Velocidad\')" ' +
            '@click="afRate">{{ afRateV }}×</button>' +
          /* W37d: guardar el audio adjunto */
          '<button class="au-rate" type="button" :title="t(\'Descargar\')" ' +
            '@click.stop="afDl"><svg class="ic ic-sm"><use href="#i-download"></use></svg></button>' +
        '</div>' +
        /* W15: el archivo ya no es un <a> nativo: la descarga pasa por
           mediadl.js (anillo de progreso, ✕ de cancelar y reintento). */
        '<span v-else-if="row.ref.kind === \'file\' && row.ref.media" class="b-file mframe" ' +
          'role="button" :title="t(\'Descargar\')" @click="dlFile(row.ref, $event)">' +
          '<svg class="ic ic-sm"><use href="#i-file"></use></svg>' +
          '<span class="bf-col"><span class="bf-name">{{ row.ref.media.name || t(\'archivo\') }}</span>' +
          '<span class="bf-size">{{ fmtSize(row.ref.media.size) }}</span></span>' +
          '<svg class="ic ic-sm"><use href="#i-download"></use></svg>' +
        '</span>' +
        /* W8: reproductor propio (el <audio> queda oculto para los tests).
           W15: el audio se baja con anillo (v-dl) y queda listo para sonar. */
        '<div class="b-player mframe" v-else-if="row.ref.kind === \'voice\' && row.ref.media">' +
          '<audio ref="aEl" class="b-audio" ' +
            ':data-mime="row.ref.media.mime" ' +
            'v-dl="mediaUrl(row.ref.media.url)" ' +
            '@loadedmetadata="aMeta" @durationchange="aDurEv" ' +
            '@timeupdate="aTimeUpd" @play="aPlayEv" ' +
            '@pause="aPauseEv" @ended="aEndEv" @error="aErrEv"></audio>' +
          '<button class="au-btn" type="button" ' +
            ':title="aPlaying ? t(\'Pausar\') : t(\'Reproducir\')" @click="togglePlay">' +
            '<svg class="ic ic-sm"><use :href="aPlaying ? \'#i-pause\' : \'#i-play\'"></use></svg>' +
          '</button>' +
          /* W13: onda con progreso (clic = buscar posición) */
          '<span class="wave" @click="seek">' +
            '<i v-for="(h, i) in wave" :key="i" :class="{ on: i <= aBar }" ' +
              ':style="{ height: h + \'%\', opacity: waveOp(i) }"></i>' +
          '</span>' +
          '<span class="au-time">{{ aTime }}</span>' +
          /* W37d: velocidad de la nota de voz (1×/1,5×/2×) */
          '<button class="au-rate" type="button" :title="t(\'Velocidad\')" ' +
            '@click="aRate">{{ aRateV }}×</button>' +
        '</div>' +
        '<div v-else-if="row.ref.kind === \'voice\'" class="b-voice">' +
          '<svg class="ic ic-sm"><use href="#i-mic"></use></svg> {{ t(\'Nota de voz\') }}' +
        '</div>' +
        /* W11: texto bajo imagen/video (caption) y de mensajes de
           texto: UN solo bloque (W29a: eran dos bloques gemelos con
           cadena v-if y el caption salía DUPLICADO en la burbuja). */
        '<div class="b-text" v-if="!editing && row.ref.body">' +
          '<span v-for="(sg, i) in bodySegs" :key="i">' +
            '<b class="mention" :class="{ me: sg.me }" v-if="sg.m">{{ sg.t }}</b>' +
            /* W40: el segmento trae el carácter; el estilo activo
               decide imagen (noto/twemoji) o texto del sistema. */
            '<img v-else-if="emoFile(sg.e)" class="emo" :src="emoSrc(sg.e)" ' +
              ':alt="sg.t" :title="sg.t" loading="lazy">' +
            /* W35b: link a imagen → la imagen misma (gif animado) */
            '<a v-else-if="sg.u && imgInline(sg.u)" class="msgimg" ' +
              ':href="sg.u" target="_blank" rel="noopener noreferrer">' +
              '<img class="linkimg" :src="sg.u" alt="" loading="lazy"></a>' +
            /* W35a: cualquier link con protocolo de la lista segura */
            '<a v-else-if="sg.u" class="msglink" :href="sg.u" ' +
              'target="_blank" rel="noopener noreferrer">{{ sg.t }}</a>' +
            '<template v-else>{{ sg.t }}</template>' +
          '</span></div>' +
        /* W35c: tarjetas "portada" bajo el texto del mensaje */
        '<div class="b-cards" v-if="!editing && linkCards.length">' +
          '<a class="linkcard" v-for="lc in linkCards" :key="lc.url" ' +
            ':href="lc.d.url" target="_blank" rel="noopener noreferrer">' +
            '<img v-if="lc.d.image" class="lc-img" :src="lc.d.image" ' +
              'alt="" loading="lazy">' +
            '<div class="lc-meta">' +
              '<img v-if="lc.d.icon" class="lc-fav" :src="lc.d.icon" ' +
                'alt="" loading="lazy">' +
              '<div class="lc-txt">' +
                '<div class="lc-title">{{ lc.d.title || lc.d.site }}</div>' +
                '<div class="lc-desc" v-if="lc.d.desc">{{ lc.d.desc }}</div>' +
                '<div class="lc-site">{{ lc.d.site }}</div>' +
              '</div>' +
            '</div>' +
          '</a>' +
        '</div>' +
        /* W8: edición en línea del mensaje propio */
        '<div class="b-editform" v-if="editing">' +
          '<textarea class="input" ref="editEl" rows="2" v-model="store.editDraft" ' +
            '@keydown.esc="cancelEdit" @keydown.ctrl.enter="saveEdit"></textarea>' +
          '<div class="bef-btns">' +
            '<button class="btn btn-ghost btn-sm" type="button" @click="cancelEdit">{{ t(\'Cancelar\') }}</button>' +
            '<button class="btn btn-sm" type="button" :disabled="!store.editDraft.trim()" ' +
              '@click="saveEdit">{{ t(\'Guardar\') }}</button>' +
          '</div>' +
        '</div>' +
        /* W7: la hora va ABAJO del texto (antes flotaba arriba). */
        '<div class="b-meta">' +
          /* W29d/h: revelado → ojo + "Ocultar" para volver a tapar */
          '<button v-if="row.ref.spoiler && !spoiled" class="b-spoil-dot" ' +
            'type="button" :title="t(\'Ocultar\')" ' +
            '@click.stop="spoilHide(row.ref)">' +
            '<svg class="ic ic-sm"><use href="#i-eye"></use></svg>' +
            '<span>{{ t(\'Ocultar\') }}</span>' +
          '</button>' +
          '<svg v-if="row.ref.pinned" class="ic ic-sm b-pin" ' +
            ':title="t(\'Fijado\')"><use href="#i-pin"></use></svg>' +
          '<span class="b-edit" v-if="row.ref.edited_at">{{ t(\'editado\') }}</span>' +
          '<span class="b-time" v-if="row.showTime && !row.ref.pending">{{ row.time }}</span>' +
          '<svg v-if="row.ref.pending" class="ic tick t-pend"><use href="#i-clock"></use></svg>' +
          '<svg v-else-if="row.mine" class="ic tick" :class="\'t-\' + row.state">' +
            '<use :href="row.state === \'sent\' ? \'#i-check\' : \'#i-check2\'"></use></svg>' +
        '</div>' +
        '<div class="b-reacts" v-if="row.ref.reactions && row.ref.reactions.length">' +
          '<button class="react-chip" type="button" ' +
            ':class="{ mine: myReaction(row.ref) === rr.emoji }" ' +
            'v-for="(rr, i) in groupReactions(row.ref)" :key="i" ' +
            '@click="doReact(row, rr.emoji)" :title="reactTitle(row.ref, rr.emoji)">' +
            '<img v-if="emoFile(rr.emoji)" class="emo" :src="emoSrc(rr.emoji)" ' +
              ':alt="rr.emoji" loading="lazy">' +
            '<span v-else>{{ rr.emoji }}</span>' +
            '<i>{{ rr.count > 1 ? rr.count : \'\' }}</i>' +
          '</button>' +
        '</div>' +
      '</div>' +
    '</div>',
};

/* ------------------------------------------------------- NewChatModal */

const NewChatModal = {
  setup: function () {
    const q = Vue.ref('');
    const results = Vue.ref([]);
    const inputEl = Vue.ref(null);
    const gtitle = Vue.ref('');
    const picked = Vue.ref([]);   // modo group: [{id, username, display_name, avatar_url}]
    let timer = null;

    Vue.onMounted(function () {
      // inputEl es un ref: el foco se le pide al .value (antes fallaba
      // con TypeError y el autofocus nunca funcionaba).
      if (inputEl.value) inputEl.value.focus();
    });

    const title = Vue.computed(function () {
      if (store.newChatMode === 'group') return t('Nuevo grupo');
      if (store.newChatMode === 'add') return t('Agregar al grupo');
      return t('Nuevo chat');
    });

    const onQuery = function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(run, 300);
    };

    const run = async function () {
      if (q.value.trim().length < 2) { results.value = []; return; }
      try {
        results.value = await searchUsers(q.value);
      } catch (e) { results.value = []; }
    };

    /* dm: crear chat; group: sumar a la selección; add: agregar al grupo. */
    const pick = async function (u) {
      const mode = store.newChatMode;
      if (mode === 'group') {
        let found = -1;
        for (let i = 0; i < picked.value.length; i++) {
          if (picked.value[i].id === u.id) found = i;
        }
        if (found >= 0) picked.value.splice(found, 1);
        else picked.value.push(u);
        q.value = '';
        results.value = [];
        if (inputEl.value) inputEl.value.focus();
        return;
      }
      if (mode === 'add') {
        try {
          await addMember(store.activeChatId, u.username);
          close();
        } catch (e) {
          toast((e && e.detail) || 'No se pudo agregar', 'err');
        }
        return;
      }
      try {
        await createDm(u.username);
      } catch (e) {
        toast((e && e.detail) || 'No se pudo crear el chat', 'err');
      }
    };

    const unpick = function (u) {
      for (let i = 0; i < picked.value.length; i++) {
        if (picked.value[i].id === u.id) { picked.value.splice(i, 1); return; }
      }
    };

    const isSelected = function (u) {
      for (let i = 0; i < picked.value.length; i++) {
        if (picked.value[i].id === u.id) return true;
      }
      return false;
    };

    const createTheGroup = async function () {
      const gname = gtitle.value.trim();
      if (!gname) { toast('Escribe un nombre para el grupo', 'err'); return; }
      try {
        const names = picked.value.map(function (u) { return u.username; });
        await createGroup(gname, names);
      } catch (e) {
        toast((e && e.detail) || 'No se pudo crear el grupo', 'err');
      }
    };

    const pickFirst = function () {
      if (results.value.length) pick(results.value[0]);
    };

    const close = function () { store.newChatOpen = false; };

    return {
      store, title, q, results, inputEl, gtitle, picked,
      onQuery, pick, pickFirst, unpick, isSelected, createTheGroup, close, mediaUrl,
    };
  },
  template:
    '<div class="modal-veil" @click.self="close">' +
      '<div class="modal" role="dialog" :aria-label="title">' +
        '<header>{{ title }}' +
          '<button class="icon-btn" type="button" :title="t(\'Cerrar\')" @click="close">' +
            '<svg class="ic"><use href="#i-x"></use></svg>' +
          '</button>' +
        '</header>' +
        '<div class="m-tabs" v-if="store.newChatMode !== \'add\'">' +
          '<button class="m-tab" type="button" :class="{ on: store.newChatMode === \'dm\' }" ' +
            '@click="store.newChatMode = \'dm\'">{{ t(\'Chat\') }}</button>' +
          '<button class="m-tab" type="button" :class="{ on: store.newChatMode === \'group\' }" ' +
            '@click="store.newChatMode = \'group\'">{{ t(\'Grupo\') }}</button>' +
        '</div>' +
        '<div class="m-title" v-if="store.newChatMode === \'group\'">' +
          '<input v-model="gtitle" :placeholder="t(\'Nombre del grupo (máx. 60)\')" maxlength="60">' +
        '</div>' +
        '<div class="g-chips" v-if="store.newChatMode === \'group\' && picked.length">' +
          '<span class="g-chip" v-for="u in picked" :key="u.id">' +
            '{{ u.display_name || u.username }}' +
            '<button type="button" :title="t(\'Quitar\')" @click="unpick(u)">' +
              '<svg class="ic ic-xs"><use href="#i-x"></use></svg>' +
            '</button>' +
          '</span>' +
        '</div>' +
        '<div class="m-search">' +
          '<svg class="ic ic-sm"><use href="#i-search"></use></svg>' +
          '<input ref="inputEl" v-model="q" :placeholder="t(\'Buscar por nombre o usuario…\')" ' +
            '@input="onQuery" @keydown.enter.prevent="pickFirst">' +
        '</div>' +
        '<div class="results">' +
          '<button class="res-item" type="button" v-for="u in results" :key="u.id" @click="pick(u)">' +
            '<span class="avatar av36">' +
              '<img v-if="u.avatar_url" :src="mediaUrl(u.avatar_url)" alt="" loading="lazy">' +
              '<span v-else>{{ (u.display_name || u.username).charAt(0).toUpperCase() }}</span>' +
            '</span>' +
            '<span class="ri-col"><span class="ri-name">{{ u.display_name }}</span>' +
            '<span class="ri-user">@{{ u.username }}</span></span>' +
            '<svg class="ic ic-sm ri-check" v-if="store.newChatMode === \'group\' && isSelected(u)">' +
              '<use href="#i-check"></use></svg>' +
          '</button>' +
          '<div class="res-empty" v-if="q.trim().length >= 2 && !results.length">{{ t(\'Sin resultados\') }}</div>' +
          '<div class="res-empty dim" v-else-if="q.trim().length < 2">{{ t(\'Escribe al menos 2 letras\') }}</div>' +
        '</div>' +
        '<div class="m-foot" v-if="store.newChatMode === \'group\'">' +
          '<button class="btn" type="button" :disabled="!gtitle.trim()" @click="createTheGroup">' +
            '{{ t(\'Crear grupo\') }}</button>' +
        '</div>' +
      '</div>' +
    '</div>',
};

/* ------------------------------------------- W6: ajustes, perfil, avisos */

/* Confirmación antes de cerrar sesión: al confirmar, clearSession() deja
   la pantalla principal sin rastro de la cuenta. */
function askLogout() {
  store.confirmBox = {
    title: 'Cerrar sesión',
    text: 'Vas a salir de Foxinix en este dispositivo.\nSe limpia todo lo local: la sesión, los chats en memoria y los borradores. Puedes volver a entrar cuando quieras.',
    danger: false,
    okLabel: 'Cerrar sesión',
    onOk: async function () {
      logout();
    },
  };
}

/* Borrado definitivo: exige usuario + contraseña (advertencia explícita). */
function askDeleteAccount() {
  store.confirmBox = {
    title: 'Eliminar cuenta',
    text: 'Esta acción es PERMANENTE y no se puede deshacer:\n• Se borra tu cuenta, tu perfil y tu correo.\n• Se borran tus mensajes y tus archivos (fotos, notas de voz).\n• En cada chat queda un aviso de que tu cuenta fue eliminada.\n\nEscribe tu usuario y contraseña para confirmar.',
    danger: true,
    requireUser: true,
    requirePassword: true,
    okLabel: 'Eliminar mi cuenta',
    onOk: async function (creds) {
      await api('DELETE', '/api/auth/account', {
        password: creds.password,
        username: creds.username,
      }, { retry401: true });
      logout();
    },
  };
}

/* ------------------------------------------------------- SettingsModal */

const SettingsModal = {
  setup: function () {
    /* Acentos/fondos: viven en el dispositivo, no en la cuenta (W4). */
    const accents = ['#ff751f', '#1f9dfa', '#7c6cf0', '#e64980', '#f59f00', '#e8590c'];
    const walls = [
      { val: '', name: 'Auto' },
      { val: '#0d1614', name: 'Petróleo' },
      { val: '#15121c', name: 'Uva' },
      { val: '#171310', name: 'Madera' },
      { val: '#e9e3d8', name: 'Papel' },
      { val: '#dfe9e7', name: 'Menta' },
    ];
    /* W8: "Cuenta" queda como ÚLTIMA pestaña: ahí se administra la cuenta
       (correo, contraseña, sesión y baja) y así el cierre de sesión no queda
       a la vista. W9: `group` abre un rótulo de sección en la nav lateral.
       W10: "Ajustes de la aplicación" pasa a llamarse "Preferencias". */
    const tabs = [
      { val: 'apariencia', name: 'Apariencia', group: 'Preferencias' },
      { val: 'chat', name: 'Chat' },
      { val: 'descargas', name: 'Descargas' },
      { val: 'atajos', name: 'Atajos' },
      { val: 'cuenta', name: 'Cuenta', group: 'Cuenta' },
    ];

    const close = function () { store.settingsOpen = false; };
    const setTab = function (tv) { store.settingsTab = tv; };
    const pickTheme = function (m) { setTheme(m); };
    const pickAccent = function (c) { setAccent(c); };
    const pickWall = function (v) { setWall(v); };
    /* W20: la foto de fondo y sus ajustes (opacidad, difuminado) viven
       en el panel dedicado, que se abre donde está la lista de chats. */
    const openWallPanel = function () {
      store.settingsOpen = false;
      store.wallPanelOpen = true;
    };
    /* W20: micrófono — dispositivo preferido + prueba de nivel */
    const micDev = Vue.ref(store.micDev);
    const micDevices = Vue.ref([]);
    const micTesting = Vue.ref(false);
    const micLevel = Vue.ref(0);
    let testStream = null;
    let testTimer = 0;
    let testCtx = null;
    const loadMics = async function () {
      try {
        if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
        const list = await navigator.mediaDevices.enumerateDevices();
        micDevices.value = list.filter(function (d) { return d.kind === 'audioinput'; });
      } catch (e) {}
    };
    Vue.onMounted(loadMics);
    /* Con el permiso concedido aparecen las etiquetas reales: recargar. */
    const pickMic = function () { setMicDev(micDev.value); loadMics(); };
    const stopMicTest = function () {
      if (testTimer) { clearInterval(testTimer); testTimer = 0; }
      if (testStream) {
        testStream.getTracks().forEach(function (tr) { tr.stop(); });
        testStream = null;
      }
      if (testCtx) { try { testCtx.close(); } catch (e) {} testCtx = null; }
      micTesting.value = false;
      micLevel.value = 0;
    };
    const testMic = async function () {
      if (micTesting.value) { stopMicTest(); return; }
      try {
        testStream = await navigator.mediaDevices.getUserMedia({
          audio: store.micDev ? { deviceId: { exact: store.micDev } } : true,
        });
      } catch (e) {
        /* W20: si el dispositivo guardado ya no existe, con el del sistema */
        if (store.micDev) {
          try { testStream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
          catch (e2) { testStream = null; }
        }
      }
      if (!testStream) {
        toast(window.isSecureContext === false
          ? 'El micrófono necesita HTTPS (o abrir Foxinix en localhost)'
          : 'No se pudo acceder al micrófono', 'err');
        return;
      }
      loadMics();                     /* con permiso aparecen las etiquetas */
      micTesting.value = true;
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        testCtx = new AC();
        const aSrc = testCtx.createMediaStreamSource(testStream);
        const an = testCtx.createAnalyser();
        an.fftSize = 512;
        aSrc.connect(an);
        const buf = new Uint8Array(an.fftSize);
        testTimer = setInterval(function () {
          an.getByteTimeDomainData(buf);
          let peak = 0;
          for (let i = 0; i < buf.length; i++) {
            const v = Math.abs(buf[i] - 128) / 128;
            if (v > peak) peak = v;
          }
          micLevel.value = Math.min(100, Math.round(peak * 160));
        }, 120);
      } catch (e) { micLevel.value = 0; }
    };
    Vue.onUnmounted(stopMicTest);
    const pickFont = function (v) { setFont(v); };
    /* W10: idioma de la interfaz (es | en), por dispositivo. */
    const pickLang = function (v) { setLang(v); };
    const langs = LANGS;
    const toggle = function (key) { setPref(key, !store.prefs[key]); };
    /* W29e: "Formato de hora" como menú desplegable 12/24 h (antes
       era un interruptor); store.prefs.h12 sigue marcando 12 h. */
    const setH12 = function (e) { setPref('h12', e.target.value === '12'); };
    /* W40: estilo de emojis — system (fuente del SO), noto (imágenes
       de Google) o twemoji (imágenes Twemoji del sitio). */
    const setEmo = function (e) { setPrefStr('emo', e.target.value); };

    /* ---- cambiar contraseña ---- */
    const pwCur = Vue.ref('');
    const pwNew = Vue.ref('');
    const pwRep = Vue.ref('');
    const pwErr = Vue.ref('');
    const pwBusy = Vue.ref(false);
    const pwReady = Vue.computed(function () {
      return !!pwCur.value && pwNew.value.length >= 8 && pwNew.value === pwRep.value;
    });

    const changePw = async function () {
      pwErr.value = '';
      if (pwNew.value.length < 8) {
        pwErr.value = 'La contraseña nueva necesita 8 caracteres o más';
        return;
      }
      if (pwNew.value !== pwRep.value) {
        pwErr.value = 'Las contraseñas nuevas no coinciden';
        return;
      }
      pwBusy.value = true;
      try {
        const r = await api('POST', '/api/auth/password', {
          current_password: pwCur.value,
          new_password: pwNew.value,
        }, { retry401: true });
        // token_version subió: el servidor manda tokens frescos para esta sesión
        if (r.tokens) {
          session.access = r.tokens.access;
          session.refresh = r.tokens.refresh;
        }
        if (r.user) {
          session.user = r.user;
          store.user = r.user;
        }
        saveSession();
        pwCur.value = '';
        pwNew.value = '';
        pwRep.value = '';
        store.pwOpen = false;              // W8: cerrar la ventana al terminar
      } catch (e) {
        pwErr.value = (e && e.detail) || 'No se pudo cambiar la contraseña';
      } finally {
        pwBusy.value = false;
      }
    };

    /* ---- cambiar correo (código al correo nuevo) ---- */
    const emNew = Vue.ref('');
    const emCode = Vue.ref('');
    const emMask = Vue.ref('');
    const emStep = Vue.ref(0);   // 0: escribir correo | 1: ingresar código
    const emErr = Vue.ref('');
    const emBusy = Vue.ref(false);

    const sendEmCode = async function () {
      emErr.value = '';
      if (!emNew.value.trim()) return;
      emBusy.value = true;
      try {
        const r = await api('POST', '/api/auth/email/change',
          { email: emNew.value.trim() }, { retry401: true });
        emMask.value = r.email_masked || emNew.value.trim();
        emStep.value = 1;
        emCode.value = '';
      } catch (e) {
        emErr.value = (e && e.detail) || 'No se pudo enviar el código';
      } finally {
        emBusy.value = false;
      }
    };

    const confirmEmCode = async function () {
      emErr.value = '';
      if (emCode.value.length !== 6) {
        emErr.value = 'El código tiene 6 dígitos';
        return;
      }
      emBusy.value = true;
      try {
        const r = await api('POST', '/api/auth/email/change/verify',
          { code: emCode.value }, { retry401: true });
        if (r.user) {
          session.user = r.user;
          store.user = r.user;
          saveSession();
        }
        emStep.value = 0;
        emNew.value = '';
        emCode.value = '';
        store.emOpen = false;              // W8: cerrar la ventana al terminar
      } catch (e) {
        emErr.value = (e && e.detail) || 'Código incorrecto';
      } finally {
        emBusy.value = false;
      }
    };

    const cancelEmCode = function () {
      emStep.value = 0;
      emCode.value = '';
      emErr.value = '';
    };

    /* ---- notificaciones (navegador o APK Android) ---- */
    const nativeNotif = (function () {
      try {
        const a = window.FoxinixAndroid;
        return a && typeof a.notify === 'function' ? a : null;
      } catch (e) { return null; }
    })();
    const nativeNotifAvail = !!nativeNotif;
    const nativeNotifPerm = function () {
      if (!nativeNotif) return 'unsupported';
      try { return nativeNotif.permission() || 'prompt'; } catch (e) { return 'prompt'; }
    };
    const notifOn = nativeNotifAvail || typeof Notification !== 'undefined';
    const notifPerm = Vue.ref(nativeNotifAvail
      ? nativeNotifPerm()
      : (typeof Notification !== 'undefined' ? Notification.permission : 'unsupported'));
    const notifTitle = Vue.computed(function () {
      return nativeNotifAvail
        ? t('Notificaciones de Android')
        : t('Notificaciones del navegador');
    });
    const notifLabel = Vue.computed(function () {
      if (!notifOn) return t('Este navegador no las soporta');
      if (notifPerm.value === 'granted') {
        return nativeNotifAvail
          ? t('Activas: avisan con la app en segundo plano')
          : t('Activas: avisan con la pestaña oculta');
      }
      if (notifPerm.value === 'denied') {
        return nativeNotifAvail
          ? t('Bloqueadas: actívalas en Ajustes de Android')
          : t('Bloqueadas: actívalas en el navegador');
      }
      return nativeNotifAvail
        ? t('Android te va a pedir permiso')
        : t('El navegador te va a pedir permiso');
    });
    const refreshNotif = function () {
      if (nativeNotif) notifPerm.value = nativeNotifPerm();
    };
    const openNotifSettings = function () {
      if (!nativeNotif) return;
      try { nativeNotif.openSettings(); } catch (e) {}
    };
    const askNotif = function () {
      if (!notifOn) return;
      if (nativeNotif) {
        try { nativeNotif.requestPermission(); } catch (e) {}
        refreshNotif();
        let tries = 0;
        const timer = setInterval(function () {
          refreshNotif();
          tries++;
          if (tries >= 8) clearInterval(timer);
        }, 750);
        return;
      }
      try {
        const p = Notification.requestPermission(function (r) { notifPerm.value = r; });
        if (p && typeof p.then === 'function') {
          p.then(function (r) { notifPerm.value = r; });
        }
      } catch (e) {}
    };
    Vue.onMounted(function () {
      window.addEventListener('focus', refreshNotif);
      document.addEventListener('visibilitychange', refreshNotif);
    });
    Vue.onUnmounted(function () {
      window.removeEventListener('focus', refreshNotif);
      document.removeEventListener('visibilitychange', refreshNotif);
    });

    /* ---- W50: descargas persistentes (Cache Storage + IndexedDB) ---- */
    const dlList = Vue.ref([]);
    const dlTotal = Vue.ref(0);
    const dlBusy = Vue.ref(false);
    const dlMsg = Vue.ref('');
    const dlLoad = function () {
      dlBusy.value = true;
      dlMsg.value = '';
      listDownloads().then(function (list) {
        dlList.value = list;
        let total = 0;
        for (let i = 0; i < list.length; i++) total += list[i].size || 0;
        dlTotal.value = total;
      }).catch(function () {
        dlMsg.value = t('No se pudieron cargar las descargas');
      }).then(function () { dlBusy.value = false; });
    };
    const dlSave = function (item) {
      dlMsg.value = '';
      saveDownloadToDisk(item.key, item.name).then(function (ok) {
        if (!ok) {
          dlMsg.value = t('El archivo ya no está disponible');
          dlLoad();
        }
      }).catch(function () {
        dlMsg.value = t('El archivo ya no está disponible');
      });
    };
    const dlDelete = function (item) {
      if (!window.confirm(t('¿Eliminar esta descarga guardada?'))) return;
      deleteDownload(item.key).then(dlLoad);
    };
    const dlClear = function () {
      if (!window.confirm(t('¿Eliminar todas las descargas guardadas?'))) return;
      clearDownloads().then(dlLoad);
    };
    const dlDate = function (item) {
      if (!item || !item.saved_at) return '';
      try {
        return new Date(item.saved_at).toLocaleDateString(store.lang === 'en' ? 'en' : 'es');
      } catch (e) { return ''; }
    };
    Vue.onMounted(dlLoad);

    return {
      store, tabs, close, setTab, accents, walls,
      pickTheme, pickAccent, pickWall, pickFont, pickLang, langs, toggle, setH12,
      setEmo,   /* W40 */
      /* W20: panel de fondo + micrófono */
      openWallPanel, micDev, micDevices, micTesting, micLevel, pickMic, testMic,
      pwCur, pwNew, pwRep, pwErr, pwBusy, pwReady, changePw,
      emNew, emCode, emMask, emStep, emErr, emBusy,
      sendEmCode, confirmEmCode, cancelEmCode,
      notifOn, notifPerm, notifLabel, notifTitle, askNotif,
      nativeNotifAvail, openNotifSettings,
      /* W50: descargas persistentes */
      dlList, dlTotal, dlBusy, dlMsg, dlSave, dlDelete, dlClear, dlDate, fmtSize,
      doLogout: askLogout, doDelete: askDeleteAccount,
    };
  },
  template: `
    <div class="modal-veil settings-veil" @click.self="close">
      <div class="modal settings" role="dialog" :aria-label="t('Ajustes')">
        <header>
          <span class="m-head-title">
            <img class="mobile-page-logo" src="/static/icon.svg" alt="">
            <b>{{ t('Ajustes') }}</b>
          </span>
          <button class="icon-btn" type="button" :title="t('Cerrar')" @click="close">
            <svg class="ic"><use href="#i-x"></use></svg>
          </button>
        </header>
        <!-- W9: navegación lateral agrupada (estilo Discord); .m-tab y el
             orden se conservan: Cuenta siempre la ÚLTIMA pestaña. -->
        <div class="st-cols">
        <div class="m-tabs" role="tablist">
          <template v-for="tb in tabs">
            <div class="st-group" v-if="tb.group" :key="'g-' + tb.val">{{ t(tb.group) }}</div>
            <button class="m-tab" type="button" :key="tb.val"
              :class="{ on: store.settingsTab === tb.val }" @click="setTab(tb.val)">{{ t(tb.name) }}</button>
          </template>
        </div>

        <div class="st-body">
          <!-- ============ cuenta ============ -->
          <template v-if="store.settingsTab === 'cuenta'">
            <div class="st-title">{{ t('Cuenta') }}</div>
            <div class="st-sec">
              <div class="st-h">{{ t('Tu cuenta') }}</div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Usuario') }}</b><span>@{{ store.user ? store.user.username : '' }}</span></div>
              </div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Correo') }}</b><span>{{ (store.user && store.user.email) || '—' }}</span></div>
              </div>
            </div>

            <!-- W8: cambiar correo/contraseña cada uno en su propia ventana -->
            <div class="st-sec">
              <div class="st-h">{{ t('Seguridad') }}</div>
              <div class="st-btns st-btns-left">
                <button class="btn btn-ghost" type="button" @click="store.emOpen = true">{{ t('Cambiar correo') }}</button>
                <button class="btn btn-ghost" type="button" @click="store.pwOpen = true">{{ t('Cambiar contraseña') }}</button>
              </div>
            </div>

            <div class="st-sec">
              <div class="st-h">{{ t('Sesión') }}</div>
              <button class="btn btn-ghost btn-full" type="button" :title="t('Cerrar sesión')" @click="doLogout">{{ t('Cerrar sesión') }}</button>
            </div>

            <div class="st-sec">
              <div class="st-h">{{ t('Zona de peligro') }}</div>
              <div class="danger-zone">
                <p><b>{{ t('Eliminar cuenta') }}</b>: {{ t('borra para siempre tu perfil, tus mensajes y tus archivos. En cada chat queda un aviso. No se puede deshacer.') }}</p>
                <button class="btn btn-danger btn-full" type="button" @click="doDelete">{{ t('Eliminar mi cuenta') }}</button>
              </div>
            </div>
          </template>

          <!-- ============ apariencia ============ -->
          <template v-else-if="store.settingsTab === 'apariencia'">
            <div class="st-title">{{ t('Apariencia') }}</div>
            <div class="ap-sec">{{ t('Tema') }}</div>
            <div class="ap-row">
              <button class="ap-opt" type="button" :class="{ on: store.theme === 'dark' }"
                @click="pickTheme('dark')">{{ t('Oscuro') }}</button>
              <button class="ap-opt" type="button" :class="{ on: store.theme === 'light' }"
                @click="pickTheme('light')">{{ t('Claro') }}</button>
            </div>
            <div class="ap-sec">{{ t('Color de acento') }}</div>
            <div class="ap-swatches">
              <button class="ap-sw" type="button" v-for="c in accents" :key="c"
                :style="{ background: c }"
                :class="{ on: store.accent.toLowerCase() === c }"
                :title="c" @click="pickAccent(c)"></button>
            </div>
            <div class="ap-sec">{{ t('Fondo de la conversación') }}</div>
            <div class="ap-walls">
              <button class="ap-wl" type="button" v-for="w in walls" :key="w.val"
                :class="{ on: store.wall === w.val }" @click="pickWall(w.val)">
                <span class="wl-chip" :style="{ background: w.val || 'var(--bg)' }"></span>{{ t(w.name) }}</button>
            </div>
            <!-- W20: foto de fondo + opacidad/difuminado: panel dedicado
                 que ocupa la columna del lista de chats (hoja inferior
                 en celular) y trae una preview de ejemplo -->
            <div class="ap-row ap-wallrow">
              <button class="btn btn-ghost btn-sm" type="button" @click="openWallPanel">
                {{ t('Personalizar fondo…') }}</button>
            </div>
            <div class="ap-sec">{{ t('Tamaño de letra') }}</div>
            <div class="ap-row">
              <button class="ap-opt" type="button" :class="{ on: store.font === 'small' }"
                @click="pickFont('small')">{{ t('Pequeño') }}</button>
              <button class="ap-opt" type="button" :class="{ on: store.font === 'normal' }"
                @click="pickFont('normal')">{{ t('Normal') }}</button>
              <button class="ap-opt" type="button" :class="{ on: store.font === 'large' }"
                @click="pickFont('large')">{{ t('Grande') }}</button>
            </div>
            <!-- W10: idioma de la interfaz (es | en), guardado por dispositivo.
                 W37b: ahora es un cuadro desplegable (select). -->
            <div class="ap-sec">{{ t('Idioma de la interfaz') }}</div>
            <div class="ap-row">
              <select class="input lang-select" :value="store.lang"
                @change="pickLang($event.target.value)">
                <option v-for="lg in langs" :key="lg.val" :value="lg.val">{{ lg.name }}</option>
              </select>
            </div>
          </template>

          <!-- ============ chat ============ -->
          <template v-else-if="store.settingsTab === 'chat'">
            <div class="st-title">{{ t('Chat') }}</div>
            <div class="st-sec">
              <div class="st-h">{{ t('Mensajes') }}</div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Sonido de notificaciones') }}</b><span>{{ t('Bip cuando llega un mensaje') }}</span></div>
                <label class="tgl"><input type="checkbox" :checked="store.prefs.sound"
                  @change="toggle('sound')"><span class="tgl-track"><span class="tgl-knob"></span></span></label>
              </div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Avisar cuando escribo') }}</b><span>{{ t('Tus contactos ven “escribiendo…”') }}</span></div>
                <label class="tgl"><input type="checkbox" :checked="store.prefs.typing"
                  @change="toggle('typing')"><span class="tgl-track"><span class="tgl-knob"></span></span></label>
              </div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Recibos de lectura') }}</b><span>{{ t('Mostrar ✓✓ y avisar cuando lees') }}</span></div>
                <label class="tgl"><input type="checkbox" :checked="store.prefs.receipts"
                  @change="toggle('receipts')"><span class="tgl-track"><span class="tgl-knob"></span></span></label>
              </div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Enter para enviar') }}</b><span>{{ t('Shift + Enter hace un salto de línea') }}</span></div>
                <label class="tgl"><input type="checkbox" :checked="store.prefs.enter"
                  @change="toggle('enter')"><span class="tgl-track"><span class="tgl-knob"></span></span></label>
              </div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Formato de hora') }}</b><span>{{ t('En vez de 20:30, mostrar 8:30 pm') }}</span></div>
                <!-- W29e: desplegable 12/24 h (antes era un interruptor) -->
                <select class="input h12-select" :value="store.prefs.h12 ? '12' : '24'"
                  @change="setH12" :aria-label="t('Formato de hora')">
                  <option value="24">24 h</option>
                  <option value="12">12 h</option>
                </select>
              </div>
              <!-- W40: estilo de los emojis — nativo (fuente del SO,
                   cero descargas), Google (Noto) o Twemoji -->
              <div class="st-row">
                <div class="st-col"><b>{{ t('Estilo de emojis') }}</b>
                  <span>{{ t('Nativo usa la fuente de tu sistema') }}</span></div>
                <select class="input emo-select" :value="store.prefs.emo"
                  @change="setEmo" :aria-label="t('Estilo de emojis')">
                  <option value="system">{{ t('Nativo del sistema') }}</option>
                  <option value="noto">{{ t('Emojis de Google') }}</option>
                  <option value="twemoji">Twemoji</option>
                </select>
              </div>
            </div>
            <!-- W20: micrófono — dispositivo preferido y prueba de nivel -->
            <div class="st-sec">
              <div class="st-h">{{ t('Micrófono') }}</div>
              <div class="st-row">
                <select class="input mic-select" v-model="micDev" @change="pickMic">
                  <option value="">{{ t('Micrófono del sistema') }}</option>
                  <option v-for="(d, i) in micDevices" :key="d.deviceId" :value="d.deviceId">
                    {{ d.label || t('Micrófono {n}', { n: i + 1 }) }}</option>
                </select>
              </div>
              <div class="st-row mic-test-row">
                <button class="btn btn-ghost btn-sm" type="button" @click="testMic">
                  {{ micTesting ? t('Escuchando…') : t('Probar micrófono') }}</button>
                <span class="mic-bar"><i :style="{ width: micLevel + '%' }"></i></span>
              </div>
            </div>
            <div class="st-sec" v-if="notifOn">
              <div class="st-h">{{ notifTitle }}</div>
              <div class="st-row">
                <div class="st-col"><b>{{ t('Avisos del sistema') }}</b><span>{{ notifLabel }}</span></div>
                <button class="btn btn-ghost btn-sm" type="button"
                  v-if="nativeNotifAvail && notifPerm === 'denied'"
                  @click="openNotifSettings">{{ t('Abrir ajustes') }}</button>
                <button class="btn btn-ghost btn-sm" type="button"
                  v-else-if="notifPerm !== 'granted'"
                  @click="askNotif">{{ t('Activar') }}</button>
                <span class="st-ok" v-else>{{ t('Activas ✓') }}</span>
              </div>
            </div>
          </template>

          <!-- ============ descargas (W50) ============ -->
          <template v-else-if="store.settingsTab === 'descargas'">
            <div class="st-title">{{ t('Descargas') }}</div>
            <div class="st-sec">
              <div class="st-h">{{ t('Archivos guardados') }}</div>
              <p class="st-hint">{{ t('Se guardan en este dispositivo para abrirlos sin volver a descargarlos.') }}</p>
              <div class="dl-empty" v-if="dlBusy">{{ t('Cargando…') }}</div>
              <div class="dl-empty" v-else-if="!dlList.length">{{ t('No hay descargas guardadas.') }}</div>
              <div class="dl-list" v-else>
                <div class="dl-item" v-for="d in dlList" :key="d.key">
                  <div class="dl-info">
                    <b>{{ d.name }}</b>
                    <span>{{ fmtSize(d.size) }}<template v-if="dlDate(d)"> · {{ dlDate(d) }}</template></span>
                  </div>
                  <button class="btn btn-ghost btn-sm" type="button" @click="dlSave(d)">{{ t('Guardar') }}</button>
                  <button class="icon-btn" type="button" :title="t('Eliminar')" @click="dlDelete(d)">
                    <svg class="ic"><use href="#i-trash"></use></svg>
                  </button>
                </div>
              </div>
              <div class="form-err st-err" v-if="dlMsg" role="alert">
                <svg class="ic ic-sm"><use href="#i-alert"></use></svg><span>{{ dlMsg }}</span>
              </div>
            </div>
            <div class="st-sec" v-if="dlList.length">
              <div class="st-row">
                <div class="st-col"><b>{{ t('Espacio usado') }}</b><span>{{ fmtSize(dlTotal) }}</span></div>
                <button class="btn btn-ghost btn-sm" type="button" @click="dlClear">{{ t('Borrar todas') }}</button>
              </div>
            </div>
          </template>

          <!-- ============ atajos ============ -->
          <template v-else-if="store.settingsTab === 'atajos'">
            <div class="st-title">{{ t('Atajos') }}</div>
            <div class="st-sec">
              <div class="st-h">{{ t('Atajos de teclado') }}</div>
              <div class="kbd-row"><span class="kbd">Enter</span><span>{{ t('Enviar mensaje') }}</span></div>
              <div class="kbd-row"><span class="kbd">Shift + Enter</span><span>{{ t('Salto de línea') }}</span></div>
              <div class="kbd-row"><span class="kbd">Ctrl + Enter</span><span>{{ t('Enviar con “Enter para enviar” apagado') }}</span></div>
              <div class="kbd-row"><span class="kbd">Esc</span><span>{{ t('Cerrar ventanas y paneles') }}</span></div>
            </div>
          </template>
        </div><!-- /.st-body -->
        </div><!-- /.st-cols -->
      </div>

      <!-- W8: ventana propia para cambiar la contraseña -->
      <div class="modal-veil" v-if="store.pwOpen" @click.self="store.pwOpen = false">
        <div class="modal small" role="dialog" :aria-label="t('Cambiar contraseña')">
          <header>{{ t('Cambiar contraseña') }}
            <button class="icon-btn" type="button" :title="t('Cerrar')" @click="store.pwOpen = false">
              <svg class="ic"><use href="#i-x"></use></svg>
            </button>
          </header>
          <div class="m-body">
            <div class="field">
              <label>{{ t('Contraseña actual') }}</label>
              <input class="input" type="password" v-model="pwCur" autocomplete="current-password">
            </div>
            <div class="field">
              <label>{{ t('Contraseña nueva') }}</label>
              <input class="input" type="password" v-model="pwNew" autocomplete="new-password">
            </div>
            <div class="field">
              <label>{{ t('Repite la contraseña nueva') }}</label>
              <input class="input" type="password" v-model="pwRep" autocomplete="new-password">
            </div>
            <div class="form-err st-err" v-if="pwErr" role="alert">
              <svg class="ic ic-sm"><use href="#i-alert"></use></svg><span>{{ t(pwErr) }}</span>
            </div>
          </div>
          <div class="m-foot st-btns">
            <button class="btn btn-ghost" type="button" :disabled="pwBusy" @click="store.pwOpen = false">{{ t('Cancelar') }}</button>
            <button class="btn" type="button" :disabled="!pwReady || pwBusy" @click="changePw">
              {{ pwBusy ? t('Guardando…') : t('Guardar') }}</button>
          </div>
        </div>
      </div>

      <!-- W8: ventana propia para cambiar el correo -->
      <div class="modal-veil" v-if="store.emOpen" @click.self="store.emOpen = false">
        <div class="modal small" role="dialog" :aria-label="t('Cambiar correo')">
          <header>{{ t('Cambiar correo') }}
            <button class="icon-btn" type="button" :title="t('Cerrar')" @click="store.emOpen = false">
              <svg class="ic"><use href="#i-x"></use></svg>
            </button>
          </header>
          <div class="m-body">
            <template v-if="emStep === 0">
              <div class="field">
                <label>{{ t('Nuevo correo') }}</label>
                <input class="input" type="email" v-model.trim="emNew"
                  :placeholder="t('tucorreo@ejemplo.com')" autocomplete="email">
              </div>
              <p class="st-hint">{{ t('Te enviamos un código de 6 dígitos. Tu correo actual sigue activo hasta que confirmes.') }}</p>
            </template>
            <template v-else>
              <p class="st-hint">{{ t('Enviamos un código de 6 dígitos a {n}. Tu correo actual sigue activo hasta que confirmes.', { n: emMask }) }}</p>
              <div class="field">
                <label>{{ t('Código') }}</label>
                <input class="input" inputmode="numeric" maxlength="6" v-model.trim="emCode" placeholder="123456">
              </div>
            </template>
            <div class="form-err st-err" v-if="emErr" role="alert">
              <svg class="ic ic-sm"><use href="#i-alert"></use></svg><span>{{ t(emErr) }}</span>
            </div>
          </div>
          <div class="m-foot st-btns" v-if="emStep === 0">
            <button class="btn btn-ghost" type="button" :disabled="emBusy" @click="store.emOpen = false">{{ t('Cancelar') }}</button>
            <button class="btn" type="button" :disabled="!emNew || emBusy" @click="sendEmCode">
              {{ emBusy ? t('Enviando…') : t('Enviar código') }}</button>
          </div>
          <div class="m-foot st-btns" v-else>
            <button class="btn btn-ghost" type="button" :disabled="emBusy" @click="cancelEmCode">{{ t('Cancelar') }}</button>
            <button class="btn btn-ghost" type="button" :disabled="emBusy" @click="sendEmCode">{{ t('Reenviar') }}</button>
            <button class="btn" type="button" :disabled="emCode.length !== 6 || emBusy" @click="confirmEmCode">
              {{ emBusy ? t('Confirmando…') : t('Confirmar') }}</button>
          </div>
        </div>
      </div>
    </div>`,
};

/* ---------------------------------------------------- MeProfileModal */

const MeProfileModal = {
  setup: function () {
    const close = function () { store.meProfileOpen = false; };
    /* W27c: MI píldora — para mí manda la conexión del WS (el mapa de
       presencia no me incluye de forma fiable, como el punto propio). */
    const myPill = Vue.computed(function () {
      return store.ws === 'on' ? statusOf(store.user) : t('Desconectado');
    });
    /* W27b: la edición vive en OTRO modal para no confundir: aquí solo
       se ve la ficha; el lápiz abre el formulario aparte. */
    const edit = function () {
      store.meProfileOpen = false;
      store.meEditOpen = true;
    };
    return {
      store, close, edit, myPill,
      dotClass, statusOf, connPill, connLine, joinedLine,
      md: mdToHtml, mediaUrl,
    };
  },
  template: `
    <div class="modal-veil" @click.self="close">
      <div class="modal meprof" role="dialog" :aria-label="t('Tu perfil')">
        <header>{{ t('Tu perfil') }}
          <button class="icon-btn mp-edit-open" type="button" :title="t('Editar perfil')"
            @click="edit">
            <svg class="ic"><use href="#i-pencil"></use></svg>
          </button>
          <button class="icon-btn" type="button" :title="t('Cerrar')" @click="close">
            <svg class="ic"><use href="#i-x"></use></svg>
          </button>
        </header>
        <div class="mp-body">
          <div class="mp-view" v-if="store.user">
            <span class="av-wrap" :class="dotClass(store.user, store.ws === 'on')">
              <span class="avatar mp-av">
                <img v-if="store.user.avatar_url" :src="mediaUrl(store.user.avatar_url)" alt="">
                <img v-else class="fox" src="/static/icon.svg" alt="">
              </span>
            </span>
            <div class="pp-name">{{ store.user.display_name || store.user.username }}</div>
            <div class="pp-user">@{{ store.user.username }}</div>
            <div class="pp-pill" v-if="myPill">{{ myPill }}</div>
            <div class="pp-bio md-body" v-if="store.user.bio" v-html="md(store.user.bio)"></div>
            <div class="pp-rows">
              <div class="pp-row"><b>{{ t('Conexión') }}</b><span>{{ store.ws === 'on' ? t('En línea') : t('Desconectado') }}</span></div>
              <div class="pp-row" v-if="store.user.created_at"><b>{{ t('Miembro desde') }}</b><span>{{ joinedLine(store.user) }}</span></div>
            </div>
          </div>
        </div>
        <div class="m-foot st-btns">
          <button class="btn btn-full" type="button" @click="edit">
            <svg class="ic ic-sm"><use href="#i-pencil"></use></svg>{{ t('Editar perfil') }}</button>
        </div>
      </div>
    </div>`,
};

/* W27b: el formulario (foto + nombre + estado + bio) vive en un modal
   PROPIO; "Tu perfil" solo muestra la ficha y el lápiz entra aquí. */
const MeProfileEditModal = {
  setup: function () {
    const u = store.user || {};
    const name = Vue.ref(u.display_name || '');
    const bio = Vue.ref(u.bio || '');
    const statusText = Vue.ref(u.status_text || '');
    /* W10: todo el mundo tiene estado (como en Discord). El valor vacío
       heredado se abre como En línea y se guarda como tal al guardar. */
    const preset = Vue.ref(u.status_preset || 'online');
    const file = Vue.ref(null);
    const preview = Vue.ref('');
    const hadAvatar = !!u.avatar_url;
    const avatarGone = Vue.ref(false);
    const busy = Vue.ref(false);
    const err = Vue.ref('');
    /* W27: al elegir foto se abre el editor (encuadre + rotación); el
       archivo y el preview viejos NO cambian hasta APLICAR. */
    const edSrc = Vue.ref('');
    const edInitial = Vue.ref(null);
    const rawFile = Vue.ref(null);

    const hasPhoto = Vue.computed(function () {
      return !!preview.value ||
        (!avatarGone.value && !!(store.user && store.user.avatar_url));
    });

    const pick = function (e) {
      const f = e.target.files && e.target.files[0];
      e.target.value = '';
      if (!f) return;
      if (!/^image\//.test(f.type)) { err.value = 'Elige una imagen'; return; }
      if (f.size > 15 * 1024 * 1024) { err.value = 'La imagen supera los 15 MB'; return; }
      err.value = '';
      rawFile.value = f;
      if (edSrc.value) URL.revokeObjectURL(edSrc.value);
      edInitial.value = null;          // foto nueva: encuadre fresco
      edSrc.value = URL.createObjectURL(f);
    };

    /* W27: reencuadrar la foto actual (o la última elegida ya cargada);
       el encuadre aplicado antes se restaura (guardado en sesión). */
    const startEdit = function () {
      if (edSrc.value) URL.revokeObjectURL(edSrc.value);
      edInitial.value = cropStateFor('me');
      if (rawFile.value) {
        edSrc.value = URL.createObjectURL(rawFile.value);
      } else if (store.user && store.user.avatar_url) {
        edSrc.value = mediaUrl(store.user.avatar_url);
      }
    };
    const onEdCancel = function () {
      if (edSrc.value) { URL.revokeObjectURL(edSrc.value); edSrc.value = ''; }
    };
    const onEdConfirm = function (blob, st) {
      onEdCancel();
      if (preview.value) URL.revokeObjectURL(preview.value);
      if (st) saveCropState('me', st);
      file.value = new File([blob], 'avatar.png', { type: 'image/png' });
      preview.value = URL.createObjectURL(file.value);
      avatarGone.value = false;
    };

    const removeAvatar = function () {
      if (!preview.value && !hadAvatar) return;
      /* W17: quitar la foto pide confirmación (es un cambio que se
         aprecia en todo el chat; no debe pasar por accidente). */
      store.confirmBox = {
        title: 'Quitar foto de perfil',
        text: '¿Seguro que quieres quitar tu foto de perfil? Se quitará cuando guardes los cambios.',
        okLabel: 'Quitar foto',
        danger: true,
        onOk: function () {
          if (preview.value) URL.revokeObjectURL(preview.value);
          file.value = null;
          rawFile.value = null;
          preview.value = '';
          if (hadAvatar) avatarGone.value = true;
        },
      };
    };

    Vue.onUnmounted(function () {
      if (preview.value) URL.revokeObjectURL(preview.value);
      if (edSrc.value) URL.revokeObjectURL(edSrc.value);
    });

    /* Cancelar (o guardar) vuelve a la ficha "Tu perfil". */
    const close = function () {
      store.meEditOpen = false;
      store.meProfileOpen = true;
    };

    const save = async function () {
      err.value = '';
      if (name.value.length > 50) { err.value = 'El nombre supera los 50 caracteres'; return; }
      if (bio.value.length > 150) { err.value = 'La bio supera los 150 caracteres'; return; }
      if (statusText.value.length > 80) { err.value = 'El estado supera los 80 caracteres'; return; }
      busy.value = true;
      try {
        const body = {
          display_name: name.value.trim(),
          bio: bio.value.trim(),
          status_text: statusText.value.trim(),
          status_preset: preset.value,
        };
        if (file.value) {
          const up = await uploadMedia(file.value);
          body.avatar_media_id = up.id;
        } else if (avatarGone.value) {
          body.avatar_media_id = null;
        }
        const r = await api('PUT', '/api/auth/profile', body, { retry401: true });
        if (r.user) {
          session.user = r.user;
          store.user = r.user;
          saveSession();
        }
        close();
      } catch (e) {
        err.value = (e && e.detail) || 'No se pudo guardar el perfil';
      } finally {
        busy.value = false;
      }
    };

    return {
      store, name, bio, statusText, preset, preview, hasPhoto, avatarGone,
      busy, err, pick, removeAvatar, close, save,
      /* W27: editor de foto (encuadre + rotación); W27b: recuerda el
         encuadre de la sesión */
      edSrc, edInitial, startEdit, onEdConfirm, onEdCancel,
      presets: STATUS_PRESETS, mediaUrl,
      /* W8: la config de la cuenta vive SOLO en el engranaje (Ajustes). */
    };
  },
  components: { AvatarEditor },
  template: `
    <div class="modal-veil" :class="{ 'veil-cropping': !!edSrc }" @click.self="close">
      <div class="modal meprof mp-edit" :class="{ 'is-cropping': !!edSrc }"
        role="dialog" :aria-label="t('Editar perfil')">
        <header>{{ edSrc ? t('Ajustar foto') : t('Editar perfil') }}
          <button class="icon-btn" type="button" :title="t('Cerrar')"
            @click="edSrc ? onEdCancel() : close()">
            <svg class="ic"><use href="#i-x"></use></svg>
          </button>
        </header>
        <div class="mp-body">
          <!-- W27: con el editor abierto ocupa el centro; al aplicar
               vuelve la ficha con el recorte ya aplicado -->
          <div class="avatar-pick" v-if="!edSrc">
            <div class="av-img">
              <img v-if="preview" :src="preview" alt="">
              <img v-else-if="hasPhoto && store.user && store.user.avatar_url"
                :src="mediaUrl(store.user.avatar_url)" alt="">
              <img v-else class="fox" src="/static/icon.svg" alt="">
            </div>
            <label class="av-btn" :title="t('Elegir foto')">
              <svg class="ic ic-sm"><use href="#i-image"></use></svg>
              <input type="file" accept="image/*" style="display:none" @change="pick">
            </label>
            <button v-if="hasPhoto" type="button" class="av-edit" :title="t('Ajustar foto')" @click="startEdit">
              <svg class="ic ic-sm"><use href="#i-pencil"></use></svg>
            </button>
            <button v-if="hasPhoto" type="button" class="av-clear" @click="removeAvatar" :aria-label="t('Quitar foto')">
              <svg class="ic ic-sm"><use href="#i-x"></use></svg>
            </button>
          </div>
          <avatar-editor v-else :src="edSrc" :initial="edInitial"
            @confirm="onEdConfirm" @cancel="onEdCancel"></avatar-editor>
          <template v-if="!edSrc">
            <div class="form-err st-err" v-if="err" role="alert">
              <svg class="ic ic-sm"><use href="#i-alert"></use></svg><span>{{ t(err) }}</span>
            </div>
            <div class="field">
              <label>{{ t('Nombre') }}</label>
              <input class="input" v-model.trim="name" maxlength="50" :placeholder="t('Tu nombre')">
            </div>
            <div class="field">
              <label>{{ t('Estado') }}</label>
              <input class="input" v-model.trim="statusText" maxlength="80" :placeholder="t('jugando a algo…')">
            </div>
            <div class="mp-presets">
              <button class="ap-chip" type="button" v-for="p in presets" :key="p.val"
                :class="{ on: preset === p.val }" @click="preset = p.val"><span
                class="sdot" :class="p.dot"></span>{{ t(p.label) }}</button>
            </div>
            <div class="field">
              <label>Bio</label>
              <textarea class="input" v-model.trim="bio" maxlength="150" rows="2"
                :placeholder="t('Cuéntanos algo sobre ti…')"></textarea>
              <p class="st-hint">{{ t('Se muestra con') }} <b>markdown</b>: {{ t('**negrita**, *cursiva*, \`código\`, ~~tachado~~ y [links](https://…)') }}</p>
            </div>
          </template>
        </div>
        <div class="m-foot st-btns" v-if="!edSrc">
          <button class="btn btn-ghost" type="button" @click="close" :disabled="busy">{{ t('Cancelar') }}</button>
          <button class="btn" type="button" @click="save" :disabled="busy">
            {{ busy ? t('Guardando…') : t('Guardar') }}</button>
        </div>
      </div>
    </div>`,
};

/* --------------------------------------------------------- ConfirmBox */

const ConfirmBox = {
  setup: function () {
    const uname = Vue.ref('');
    const pw = Vue.ref('');

    const okDisabled = Vue.computed(function () {
      const b = store.confirmBox;
      if (!b || b.busy) return true;
      if (b.requireUser) {
        const me = store.user ? store.user.username : '';
        if (uname.value.trim().toLowerCase() !== me) return true;
      }
      if (b.requirePassword && !pw.value) return true;
      return false;
    });

    const cancel = function () {
      if (store.confirmBox && !store.confirmBox.busy) store.confirmBox = null;
    };

    const confirm = async function () {
      const b = store.confirmBox;
      if (!b || okDisabled.value) return;
      b.busy = true;
      b.error = '';
      try {
        await b.onOk({ username: uname.value.trim(), password: pw.value });
      } catch (e) {
        if (store.confirmBox === b) {
          b.busy = false;
          b.error = (e && e.detail) || 'No se pudo completar la acción';
        }
        return;
      }
      if (store.confirmBox === b) store.confirmBox = null;
    };

    return { store, uname, pw, okDisabled, cancel, confirm };
  },
  template: `
    <div class="modal-veil" @click.self="cancel">
      <div class="modal confirm" role="alertdialog" :aria-label="t(store.confirmBox.title)">
        <header>{{ t(store.confirmBox.title) }}</header>
        <div class="cf-body">
          <p class="cf-text">{{ t(store.confirmBox.text) }}</p>
          <div class="field" v-if="store.confirmBox.requireUser">
            <label>{{ t('Escribe tu usuario para confirmar') }}</label>
            <input class="input" v-model.trim="uname"
              :placeholder="'@' + (store.user ? store.user.username : '')" autocomplete="off">
          </div>
          <div class="field" v-if="store.confirmBox.requirePassword">
            <label>{{ t('Contraseña') }}</label>
            <input class="input" type="password" v-model="pw" autocomplete="current-password">
          </div>
          <div class="form-err st-err" v-if="store.confirmBox.error" role="alert">
            <svg class="ic ic-sm"><use href="#i-alert"></use></svg><span>{{ t(store.confirmBox.error) }}</span>
          </div>
        </div>
        <div class="m-foot st-btns">
          <button class="btn btn-ghost" type="button" :disabled="store.confirmBox.busy" @click="cancel">
            {{ t('Cancelar') }}</button>
          <button class="btn" :class="{ 'btn-danger': store.confirmBox.danger }" type="button"
            :disabled="okDisabled" @click="confirm">
            {{ store.confirmBox.busy ? t('Un momento…') : t(store.confirmBox.okLabel || 'Confirmar') }}</button>
        </div>
      </div>
    </div>`,
};

/* ----------------------------------------------------- ReadsBox (W28f)

   "Visto por": lista de miembros que ya leyeron un mensaje mío en un
   grupo. No hay eventos en vivo: se carga al abrir (y el header lleva
   el recuento "N"). */

const ReadsBox = {
  setup: function () {
    const close = function () { store.readsBox = null; };
    return { store, close, mediaUrl };
  },
  template: `
    <div class="modal-veil" v-if="store.readsBox" @click.self="close" role="dialog" :aria-label="t('Visto por')">
      <div class="modal reads-box">
        <header>{{ t('Visto por') }}<i v-if="store.readsBox.rows"> ({{ store.readsBox.rows.length }})</i>
          <button class="icon-btn" type="button" :title="t('Cerrar')" @click="close">
            <svg class="ic"><use href="#i-x"></use></svg>
          </button>
        </header>
        <div class="pp-loading" v-if="store.readsBox.loading">{{ t('Cargando…') }}</div>
        <div class="pp-loading" v-else-if="store.readsBox.error">{{ t(store.readsBox.error) }}</div>
        <div class="pp-loading" v-else-if="!store.readsBox.rows || !store.readsBox.rows.length">{{ t('Nadie lo ha leído todavía') }}</div>
        <ul class="reads-list" v-else>
          <li class="mi-row" v-for="u in store.readsBox.rows" :key="u.id">
            <span class="avatar av36">
              <img v-if="u.avatar_url" :src="mediaUrl(u.avatar_url)" alt="" loading="lazy">
              <span v-else>{{ (u.display_name || u.username).charAt(0).toUpperCase() }}</span>
            </span>
            <span class="mi-col">
              <span class="mi-name">{{ u.display_name || u.username }}</span>
              <span class="mi-sub">@{{ u.username }}</span>
            </span>
          </li>
        </ul>
      </div>
    </div>`,
};

/* ------------------------------------------------------- CallBox (W28h)

   Panel de llamada: entrante (Contestar/Rechazar) o en curso (video
   remoto + PIP local + silencio/cámara/colgar + cronómetro). Los
   MediaStream viven en call.js (fuera del store: Vue los envolvería en
   proxies y los métodos nativos se rompen) y se enganchan a los
   <video> en cada render; los cambios de estado reactivos provocan el
   updated que los pinta. */

const CallBox = {
  setup: function () {
    const elapsed = Vue.ref('00:00');
    const remoteEl = Vue.ref(null);
    const pipEl = Vue.ref(null);
    let timer = null;

    const fmt = function (ms) {
      const s = Math.max(0, Math.floor(ms / 1000));
      const mm = Math.floor(s / 60);
      const ss = s % 60;
      return (mm < 10 ? '0' : '') + mm + ':' + (ss < 10 ? '0' : '') + ss;
    };
    const retick = function () {
      const c = store.call;
      elapsed.value = (c && c.startedAt) ? fmt(Date.now() - c.startedAt) : '00:00';
    };
    const attach = function () {
      const st = getRemoteStream();
      if (remoteEl.value && st && remoteEl.value.srcObject !== st) {
        remoteEl.value.srcObject = st;
        try {
          const p = remoteEl.value.play();
          if (p && typeof p.catch === 'function') p.catch(function () {});
        } catch (e) {}
      }
      const st2 = getLocalStream();
      if (pipEl.value && st2 && pipEl.value.srcObject !== st2) {
        pipEl.value.srcObject = st2;
        try {
          const p2 = pipEl.value.play();
          if (p2 && typeof p2.catch === 'function') p2.catch(function () {});
        } catch (e) {}
      }
    };
    Vue.onMounted(function () {
      retick();
      timer = setInterval(retick, 1000);
      attach();
    });
    Vue.onUpdated(attach);
    Vue.onUnmounted(function () { if (timer) clearInterval(timer); });

    const peerName = function () {
      const c = store.call;
      if (!c || !c.peer) return '';
      return c.peer.display_name || c.peer.username || '';
    };
    const peerIni = function () { return peerName().charAt(0).toUpperCase(); };
    const inCall = function () {
      const c = store.call;
      return !!c && (c.state === 'connecting' || c.state === 'active');
    };
    const stateLine = function () {
      const c = store.call;
      if (!c) return '';
      if (c.state === 'incoming') return t('Llamada entrante');
      if (c.state === 'outgoing') return t('Llamando…');
      if (c.state === 'connecting') return t('Conectando…');
      return elapsed.value;   // activa: cronómetro
    };
    return {
      store, t, remoteEl, pipEl, peerName, peerIni, inCall, stateLine,
      accept: acceptCall, reject: rejectCall, hangup: hangupCall,
      mute: toggleMute, cam: toggleCam,
    };
  },
  template:
    '<div class="callbox" :class="{ incoming: store.call.state === \'incoming\' }"' +
      ' role="dialog" :aria-label="t(\'Llamada entrante\')">' +
      '<div class="call-head">' +
        '<span class="avatar av36"><span>{{ peerIni() }}</span></span>' +
        '<span class="call-col">' +
          '<b>{{ peerName() }}</b>' +
          '<span class="call-state">{{ stateLine() }}</span>' +
        '</span>' +
      '</div>' +
      /* video remoto: solo cuando ya llegó pista (ontrack) */
      '<video class="call-remote" ref="remoteEl" autoplay playsinline' +
        ' v-if="store.call.video && store.call.remote"></video>' +
      /* PIP local (muted: nunca la retroalimentación del propio micrófono) */
      '<video class="call-pip" ref="pipEl" autoplay muted playsinline' +
        ' v-if="store.call.video"></video>' +
      '<div class="call-ctl">' +
        /* entrante: Contestar / Rechazar */
        '<button type="button" class="btn call-accept" v-if="store.call.state === \'incoming\'" ' +
          '@click="accept">{{ t(\'Contestar\') }}</button>' +
        '<button type="button" class="btn call-reject" v-if="store.call.state === \'incoming\'" ' +
          '@click="reject">{{ t(\'Rechazar\') }}</button>' +
        /* en curso: silencio / cámara / colgar */
        '<button type="button" class="icon-btn" v-if="inCall()" ' +
          ':title="store.call.muted ? t(\'Activar el micrófono\') : t(\'Silenciar\')" @click="mute">' +
          '<svg class="ic"><use :href="store.call.muted ? \'#i-mic-off\' : \'#i-mic\'"></use></svg>' +
        '</button>' +
        '<button type="button" class="icon-btn" v-if="inCall() && store.call.video" ' +
          ':title="store.call.camOff ? t(\'Encender la cámara\') : t(\'Apagar la cámara\')" @click="cam">' +
          '<svg class="ic"><use :href="store.call.camOff ? \'#i-video-off\' : \'#i-video\'"></use></svg>' +
        '</button>' +
        '<button type="button" class="icon-btn call-hang" v-if="store.call.state !== \'incoming\'" ' +
          ':title="t(\'Colgar\')" @click="hangup">' +
          '<svg class="ic"><use href="#i-phone-down"></use></svg>' +
        '</button>' +
      '</div>' +
    '</div>',
};

/* --------------------------------------------------------- SpamBox (W18)

   Aviso anti-spam: pantalla completa que bloquea la UI 10 s y solo se
   cierra con el botón (ni Esc ni el fondo la cierran). El server manda
   el 429 con {retry_after, spam} al exceder el límite de mensajes y
   api.js levanta store.spamUntil. El botón se activa al terminar la
   cuenta regresiva: "Ok, perdón (3s)" → "Ok, perdón". */

const SpamBox = {
  setup: function () {
    const now = Vue.ref(Date.now());
    let timer = 0;
    Vue.onMounted(function () {
      timer = setInterval(function () { now.value = Date.now(); }, 500);
    });
    Vue.onUnmounted(function () { clearInterval(timer); });
    const left = Vue.computed(function () {
      return Math.max(0, Math.ceil((store.spamUntil - now.value) / 1000));
    });
    const close = function () { store.spamUntil = 0; };
    return { left, close };
  },
  template:
    '<div class="spam-veil" role="alertdialog" ' +
      ':aria-label="t(\'¡OYE! Estás haciendo SPAM!\')">' +
      '<div class="spam-box">' +
        '<svg class="ic spam-ic"><use href="#i-alert"></use></svg>' +
        '<h2 class="spam-title">{{ t(\'¡OYE! Estás haciendo SPAM!\') }}</h2>' +
        '<p class="spam-text">' +
          '{{ t(\'Si sigues así pueden bloquearte la cuenta por 5 minutos; ' +
          'si sigues otra vez, el tiempo aumentará, pero disminuirá poco a poco ' +
          'si dejas de hacer spam por un tiempo.\') }}</p>' +
        '<button class="btn spam-ok" type="button" :disabled="left > 0" @click="close">' +
          '{{ left > 0 ? t(\'Ok, perdón ({n}s)\', { n: left }) : t(\'Ok, perdón\') }}' +
        '</button>' +
      '</div>' +
    '</div>',
};

/* ------------------------------------------------------- ProfilePanel */

function joinedLine(u) {
  if (!u || !u.created_at) return '—';
  const d = new Date(u.created_at * 1000);
  return d.getDate() + '/' + (d.getMonth() + 1) + '/' + d.getFullYear();
}

/* W8: markdown mínimo y SEGURO para las bios. Primero se escapa todo el
   texto del usuario y recién después se agregan etiquetas propias:
   **negrita**, *cursiva*, ~~tachado~~, `código`, [links](https://…) y
   saltos de línea. No se acepta HTML ajeno (sin riesgo de inyección). */
function mdToHtml(text) {
  let out = String(text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    /* W37f: la comilla simple también se escapa (defensa en profundidad
       si algún atributo futuro usa comillas simples). */
    .replace(/'/g, '&#39;');
  out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  out = out.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
  out = out.replace(/\*([^*\n]+)\*/g, '<i>$1</i>');
  out = out.replace(/~~([^~\n]+)~~/g, '<s>$1</s>');
  out = out.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  out = out.replace(/\n/g, '<br>');
  return out;
}

const ProfilePanel = {
  setup: function () {
    const close = function () { store.profile = null; };

    const startChat = async function () {
      const p = store.profile;
      if (!p || !p.user) return;
      const username = p.user.username;
      close();
      try {
        await createDm(username);
      } catch (e) {
        toast((e && e.detail) || 'No se pudo abrir el chat', 'err');
      }
    };

    /* "Mensaje" solo si NO estoy ya en el directo con esa persona (W7). */
    const inActiveDm = Vue.computed(function () {
      const p = store.profile;
      if (!p || !p.user) return false;
      const id = store.activeChatId;
      for (let i = 0; i < store.chats.length; i++) {
        const c = store.chats[i];
        if (c.id === id && c.type === 'dm' && c.title && c.title.id === p.user.id) return true;
      }
      return false;
    });

    /* W27: la píldora de estado la resuelve connPill (módulo): fuera de
       línea dice "Desconectado"; activo manda SU estado (texto o preset). */

    return {
      store, close, startChat, inActiveDm, dotClass,
      statusOf, connPill, personMenu, connLine, joinedLine, md: mdToHtml,
      mediaUrl,
    };
  },
  template: `
    <div class="modal-veil" v-if="store.profile" @click.self="close" role="dialog" :aria-label="t('Perfil')">
      <div class="modal pmodal">
        <header>{{ t('Perfil') }}
          <button class="icon-btn pp-more" type="button" :title="t('Administrar')"
            v-if="store.profile.user && store.user && store.profile.user.id !== store.user.id"
            @click.stop="personMenu($event, store.profile.user)">
            <svg class="ic"><use href="#i-dots"></use></svg>
          </button>
          <button class="icon-btn" type="button" :title="t('Cerrar')" @click="close">
            <svg class="ic"><use href="#i-x"></use></svg>
          </button>
        </header>
        <div class="pp-loading" v-if="store.profile.loading">{{ t('Cargando perfil…') }}</div>
        <div class="pp-loading" v-else-if="store.profile.error">{{ t(store.profile.error) }}</div>
        <template v-else-if="store.profile.user">
          <div class="pp-body">
            <span class="av-wrap" :class="dotClass(store.profile.user)">
              <span class="avatar pp-av">
                <img v-if="store.profile.user.avatar_url"
                  :src="mediaUrl(store.profile.user.avatar_url)" alt="" loading="lazy">
                <span v-else>{{ (store.profile.user.display_name || store.profile.user.username).charAt(0).toUpperCase() }}</span>
              </span>
            </span>
            <div class="pp-name">{{ store.profile.user.display_name }}</div>
            <div class="pp-user">@{{ store.profile.user.username }}</div>
            <div class="pp-pill" v-if="connPill(store.profile.user)">{{ connPill(store.profile.user) }}</div>
            <div class="pp-bio md-body" v-if="store.profile.user.bio" v-html="md(store.profile.user.bio)"></div>
            <div class="pp-rows">
              <div class="pp-row"><b>{{ t('Conexión') }}</b><span>{{ connLine(store.profile.user) }}</span></div>
              <div class="pp-row"><b>{{ t('Miembro desde') }}</b><span>{{ joinedLine(store.profile.user) }}</span></div>
            </div>
          </div>
          <div class="pp-foot" v-if="!inActiveDm">
            <button class="btn btn-full" type="button" @click="startChat">{{ t('Mensaje') }}</button>
          </div>
        </template>
      </div>
    </div>`,
};

/* --------------------------------------------------- ChatInfoPanel (W7)
   Panel derecho con la info del chat activo: en directos, la ficha del
   contacto (sin botón "Mensaje": ya estás en la conversación); en
   grupos, la lista de miembros con quién está conectado y la salida
   del grupo. Se abre con el botón de la cabecera. */

const ChatInfoPanel = {
  setup: function () {
    const close = function () { store.infoOpen = false; };

    const chat = Vue.computed(function () {
      const id = store.activeChatId;
      for (let i = 0; i < store.chats.length; i++) if (store.chats[i].id === id) return store.chats[i];
      return null;
    });

    /* Directo: el contacto (el OTRO miembro, no yo) con presencia
       fresca; si todavía no cargó, el title de la lista. */
    const peer = Vue.computed(function () {
      const c = chat.value;
      if (!c || c.type !== 'dm') return null;
      const info = store.info;
      if (info && info.chatId === c.id && info.members && info.members.length) {
        const meId = store.user ? store.user.id : 0;
        for (let i = 0; i < info.members.length; i++) {
          if (info.members[i].id !== meId) return info.members[i];
        }
      }
      return c.title || null;
    });

    const members = Vue.computed(function () {
      const info = store.info;
      const c = chat.value;
      if (!info || !c || info.chatId !== c.id) return [];
      /* W27: en línea primero y desconectados al final (orden estable). */
      const ms = info.members || [];
      return ms.slice().sort(function (a, b) {
        return (memberOn(b) ? 1 : 0) - (memberOn(a) ? 1 : 0);
      });
    });

    /* W26: presencia del panel de info desde el mapa único (eventos WS +
       snapshot al reconectar); el online del REST es solo el primer relleno. */
    const memberOn = function (m) {
      return !!(m && (store.presence[m.id] != null ? store.presence[m.id] : m.online));
    };

    const onlineCount = Vue.computed(function () {
      const ms = members.value;
      let n = 0;
      for (let i = 0; i < ms.length; i++) if (memberOn(ms[i])) n++;
      return n;
    });

    const infoError = Vue.computed(function () {
      const info = store.info;
      const c = chat.value;
      if (!info || !c || info.chatId !== c.id) return '';
      return info.error || '';
    });

    const loading = Vue.computed(function () {
      const info = store.info;
      const c = chat.value;
      return !!(info && c && info.chatId === c.id && info.loading && !info.members.length);
    });

    const isMe = function (m) {
      return !!(m && store.user && m.id === store.user.id);
    };

    const memberLine = function (m) {
      if (!memberOn(m)) return fmtLastSeen(m.last_seen);
      if (m.status_text) return m.status_text;
      if (m.status_preset) return presetLabel(m.status_preset);
      return t('En línea');
    };

    const openMember = function (m) {
      if (m && m.username) openProfile(m.username);
    };

    /* W46: etiqueta [Admin] para owner y admin del grupo. El owner
       conserva ese rol superior para las acciones sensibles. */
    const isAdmin = function (m) {
      return !!(m && (m.role === 'owner' || m.role === 'admin'));
    };

    /* El menú de administración sólo aparece cuando la acción tiene
       sentido: no sobre uno mismo, ni sobre el owner; un admin sólo
       administra miembros comunes. */
    const canManageMember = function (m) {
      const c = chat.value;
      if (!c || c.type !== 'group' || !m || isMe(m) || m.role === 'owner') {
        return false;
      }
      if (c.my_role === 'owner') return true;
      return c.my_role === 'admin' && m.role === 'member';
    };

    const memberMenu = function (e, m) {
      const c = chat.value;
      if (!c || !canManageMember(m)) return;
      const items = [];
      if (m.role === 'member') {
        items.push({
          label: 'Hacer admin', icon: 'i-shield',
          fn: function () { askSetRole(c, m, 'admin'); },
        });
      } else if (m.role === 'admin') {
        items.push({
          label: 'Quitar admin', icon: 'i-user',
          fn: function () { askSetRole(c, m, 'member'); },
        });
      }
      items.push({
        label: 'Eliminar del grupo', icon: 'i-trash', danger: true,
        fn: function () { askRemoveMember(c, m); },
      });
      openCtx(e, items, null, 'member:' + c.id + ':' + m.id);
    };

    /* W29c: pelotita si este miembro está escribiendo en ESTE chat. */
    const memberTyping = function (m) {
      const c = chat.value;
      const bag = c && store.typing[c.id];
      return !!(bag && bag[m.id]);
    };

    /* W39: showProfile() (botón "Ver perfil completo" al pie del panel)
       se eliminó junto con el botón — el perfil completo se abre con
       un clic en la cabecera del chat. */

    /* W27d: "Salir del grupo" ya no es un botón grande al pie (poco
       estético); vive en el ⋮ del panel (chatMenu). */

    /* W27: ⋮ del panel — administrar el grupo (o el directo). */
    const infoMenu = function (e) {
      const c = chat.value;
      if (!c) return;
      if (c.type === 'group') {
        chatMenu(e, c, 'info');
        return;
      }
      const items = [];
      const p = peer.value;
      if (p && p.username && !isMe(p)) {
        items.push({
          label: 'Ver perfil', icon: 'i-user',
          fn: function () { openProfile(p.username); },
        });
      }
      items.push({
        label: c.pinned ? 'Desfijar chat' : 'Fijar chat',
        icon: c.pinned ? 'i-x' : 'i-pin',
        fn: function () { setPinned(c.id, !c.pinned); },
      });
      items.push({
        label: c.muted ? 'Activar notificaciones' : 'Silenciar notificaciones',
        icon: c.muted ? 'i-bell' : 'i-bell-off',
        fn: function () { setMuted(c.id, !c.muted); },
      });
      /* W36i: el mismo ⋮ alterna abrir/cerrar */
      openCtx(e, items, null, 'info');
    };

    /* W27: la lista en dos bloques: en línea primero y desconectados
       después, con etiqueta solo cuando conviven los dos. */
    const memberSections = Vue.computed(function () {
      const ms = members.value;
      const on = [];
      const off = [];
      for (let i = 0; i < ms.length; i++) {
        if (memberOn(ms[i])) on.push(ms[i]);
        else off.push(ms[i]);
      }
      const both = on.length > 0 && off.length > 0;
      const out = [];
      if (on.length) out.push({ key: 'on', label: 'En línea', show: both, ms: on });
      if (off.length) out.push({ key: 'off', label: 'Desconectados', show: both, ms: off });
      return out;
    });

    /* W27: foto del grupo en la info; quien puede cambiarla ve el botón. */
    const grpAvatar = Vue.computed(function () {
      const c = chat.value;
      return c && c.avatar_url ? mediaUrl(c.avatar_url) : '';
    });
    const canPhoto = Vue.computed(function () {
      const c = chat.value;
      return !!(c && (c.my_role === 'owner' || c.my_role === 'admin'));
    });
    const pickPhoto = function () { pickGroupPhoto(chat.value); };

    /* W27b: mientras store.grpEdit apunte a ESTE chat, el panel muestra
       el editor de encuadre en lugar de la foto; al aplicar se sube el
       PNG compuesto y el encuadre queda guardado para reeditar. */
    const grpEditing = Vue.computed(function () {
      const c = chat.value;
      const ge = store.grpEdit;
      return !!(c && ge && ge.src && ge.chatId === c.id);
    });
    const onGrpPhotoCancel = function () {
      const ge = store.grpEdit;
      if (ge && ge.src) URL.revokeObjectURL(ge.src);
      store.grpEdit = { chatId: 0, src: '' };
    };
    const onGrpPhoto = function (blob, st) {
      const c = chat.value;
      onGrpPhotoCancel();
      if (!c) return;
      const f = new File([blob], 'grupo.png', { type: 'image/png' });
      Promise.resolve(uploadChatAvatar(c.id, f)).then(function () {
        saveCropState('chat-' + c.id, st);
        toast('Foto del grupo actualizada', 'ok');
      }).catch(function (err) {
        toast((err && err.detail) || 'No se pudo subir la foto', 'err');
      });
    };

    /* W28c/W29l: mensajes fijados — el CONTEO se carga al abrir el
       panel de la info (W29l: modal, no acordeón) y un message_pinned
       por WS mantiene el badge siempre al día. */
    const pins = Vue.ref([]);
    const pinsLoading = Vue.ref(false);
    const loadPins = async function () {
      const c = chat.value;
      if (!c) return;
      pinsLoading.value = true;
      try {
        const r = await api('GET', '/api/chats/' + c.id + '/pins');
        if (!chat.value || chat.value.id !== c.id) return;
        pins.value = r.messages || [];
      } catch (e) {
        pins.value = [];            // sin permiso/chat cerrado: vacío
      } finally {
        pinsLoading.value = false;
      }
    };
    const openPins = function () {
      store.pinsModal = true;
      loadPins();                  // siempre fresco al abrir el modal
    };
    const closePins = function () { store.pinsModal = false; };
    const goPin = function (msg) {
      if (!msg) return;
      store.pinsModal = false;     // W29l: el modal deja ver el chat
      store.jumpMsg = msg.id;      // el watcher de ChatShell hace el scroll
    };
    Vue.watch(function () { return store.pinsRev; }, function () {
      if (store.infoOpen) loadPins();  // W29l: badge y modal al día
    });
    Vue.watch(function () { return chat.value && chat.value.id; }, function () {
      pins.value = [];
      gal.value = null;
      store.pinsModal = false;
      store.galModal = false;
      if (store.infoOpen) { loadPins(); loadGal(); }   // W29l: al cambiar de chat
    });

    /* W28d/W29l: archivos y medios del chat — el modal "Archivos y
       medios" (visor) con el conteo cargado junto con los fijados. */
    const gal = Vue.ref(null);
    const galLoading = Vue.ref(false);
    const loadGal = async function () {
      const c = chat.value;
      if (!c) return;
      galLoading.value = true;
      try {
        const r = await api('GET', '/api/chats/' + c.id + '/gallery');
        if (!chat.value || chat.value.id !== c.id) return;
        gal.value = { images: r.images || [], files: r.files || [] };
      } catch (e) {
        gal.value = { images: [], files: [] };
      } finally {
        galLoading.value = false;
      }
    };
    const openGal = function () {
      store.galModal = true;
      loadGal();                    // siempre fresco al abrir el modal
    };
    const closeGal = function () { store.galModal = false; };
    const goGal = function (item) {
      if (!item) return;
      store.galModal = false;       // W29l: el modal deja ver el chat
      store.jumpMsg = item.msg_id;   // el watcher de ChatShell hace el scroll
    };
    /* W29d: miniatura con spoiler — el primer toque revela (y también
       la burbuja); el segundo abre el visor (W29l: lightbox). */
    const galSpoiled = function (item) {
      if (!item || !item.spoiler) return false;
      const s = store.spoilSeen[store.activeChatId];
      return !(s && s[item.msg_id]);
    };
    const galClick = function (item) {
      if (galSpoiled(item)) {
        if (!store.spoilSeen[store.activeChatId]) {
          store.spoilSeen[store.activeChatId] = {};
        }
        store.spoilSeen[store.activeChatId][item.msg_id] = 1;
        return;
      }
      /* W29l: en el modal, la imagen se ve en el visor (lightbox);
         el salto al mensaje queda para los archivos (goGal). */
      store.lb = { url: mediaUrl(item.media.url) };
    };

    /* W29l: al abrir la info se piden fijados y galería de una vez
       (los conteos de los accesos se ven "de una"); al cerrar, los
       modales que hubiera se apagan. */
    Vue.watch(function () { return store.infoOpen; }, function (open) {
      if (open) { loadPins(); loadGal(); }
      else { store.pinsModal = false; store.galModal = false; }
    }, { immediate: true });

    /* -------- W29f/W31c: cifrado de extremo a extremo (sólo DM) ------
       Siempre activo: ya no hay switch ni activación manual; el único
       estado no activo es "Pendiente" (el par aún no publica clave). */
    /* W30d/W31c: aviso mientras no se puede cifrar (el par no publica);
       vale para TODOS los DMs. (W39: e2eStatus/"Activado" se eliminó
       con la nota centrada del panel.) */
    const e2ePendHint = Vue.computed(function () {
      const c = chat.value;
      if (!c || c.type !== 'dm') return '';
      if (store.e2e[c.id]) return '';
      if (!(store.e2ePend && store.e2ePend[c.id])) return '';
      const n = (c.title && (c.title.display_name || c.title.username)) || '';
      return t('Se activará cuando {n} publique sus claves', { n: n });
    });
    const e2eSas = Vue.computed(function () {
      const c = chat.value;
      if (!c || !store.e2e[c.id]) return '';
      return store.e2eSas[c.id] || '';
    });
    /* (W39: el modal del código vive en ChatShell — su sasCode se
       calcula allí sobre store.sasFor.) */
    /* Al abrir el panel de un chat activado sin huella en memoria (p. ej.
       tras recargar), se recalcula la clave/SAS. */
    Vue.watch(chat, function (c) {
      if (c && c.type === 'dm' && store.e2e[c.id] && !store.e2eSas[c.id]) {
        e2eChatKey(c.id).catch(function () {});
      }
    }, { immediate: true });

    return {
      store, close, chat, peer, members, onlineCount, infoError, loading,
      isMe, memberLine, openMember,
      isAdmin, canManageMember, memberMenu,
      infoMenu, memberSections, grpAvatar, canPhoto, pickPhoto,
      grpEditing, onGrpPhoto, onGrpPhotoCancel,
      dotClass, statusOf, connPill, connLine, joinedLine, mediaUrl, md: mdToHtml,
      titleOf: chatTitle,
      /* W28c/W29l */
      pins, pinsLoading, openPins, closePins, goPin,
      /* W28d/W29l */
      gal, galLoading, openGal, closeGal, goGal, galClick, galSpoiled, fmtSize,
      /* W29c */
      memberTyping,
      /* W29f/W31c */
      e2eSas, e2ePendHint,
    };
  },
  components: { AvatarEditor },
  template: `
    <aside class="profile-panel" v-if="store.infoOpen && chat" :aria-label="t(chat.type === 'dm' ? 'Info del usuario' : 'Info del chat')">
      <header class="pp-head">
        <b>{{ t(chat.type === 'dm' ? 'Info del usuario' : 'Info del chat') }}</b>
        <button class="icon-btn pp-more" type="button" :title="t('Administrar')"
          @click.stop="infoMenu($event)">
          <svg class="ic"><use href="#i-dots"></use></svg>
        </button>
        <button class="icon-btn" type="button" :title="t('Cerrar')" @click="close">
          <svg class="ic"><use href="#i-x"></use></svg>
        </button>
      </header>

      <template v-if="chat.type === 'dm'">
        <div class="pp-body" v-if="peer">
          <span class="av-wrap" :class="dotClass(peer)">
            <span class="avatar pp-av">
              <img v-if="peer.avatar_url" :src="mediaUrl(peer.avatar_url)" alt="" loading="lazy">
              <span v-else>{{ (peer.display_name || peer.username).charAt(0).toUpperCase() }}</span>
            </span>
          </span>
          <div class="pp-name">{{ peer.display_name || peer.username }}</div>
          <div class="pp-user">@{{ peer.username }}</div>
          <div class="pp-pill" v-if="connPill(peer)">{{ connPill(peer) }}</div>
          <div class="pp-bio md-body" v-if="peer.bio" v-html="md(peer.bio)"></div>
          <div class="pp-rows">
            <div class="pp-row"><b>{{ t('Conexión') }}</b><span>{{ connLine(peer) }}</span></div>
            <div class="pp-row" v-if="peer.created_at"><b>{{ t('Miembro desde') }}</b><span>{{ joinedLine(peer) }}</span></div>
          </div>
        </div>
        <!-- W29f/W31c/W39: cifrado de extremo a extremo (DM) — una sola
             línea centrada con el icono de llave: al usuario le basta
             con saber que la conversación ES cifrada (sin "Activado"
             ni botón de perfil: eso sobraba en el panel). -->
        <div class="pp-e2e" v-if="chat && chat.type === 'dm'">
          <div class="pp-e2e-row pp-e2e-center">
            <svg class="ic ic-sm"><use href="#i-key"></use></svg>
            <b>{{ t('Cifrado de extremo a extremo') }}</b>
          </div>
          <!-- W30d: aviso mientras el par no publica su clave -->
          <div class="pp-e2e-pend" v-if="e2ePendHint">
            <svg class="ic ic-sm"><use href="#i-info"></use></svg>
            <span>{{ e2ePendHint }}</span>
          </div>
          <!-- W37b: el código vive en el menú ⋯ → ahora en un MODAL (W39). -->
        </div>
      </template>

      <template v-else>
        <div class="pp-body pp-left" v-if="infoError">
          <div class="pp-loading">{{ t(infoError) }}</div>
        </div>
        <div class="pp-body pp-left" v-else-if="loading">
          <div class="pp-loading">{{ t('Cargando miembros…') }}</div>
        </div>
        <div class="pp-body pp-left" v-else-if="members.length">
          <!-- W27: foto del grupo; subirla solo owner/admin. W27b: al
               elegirla se abre el editor de encuadre ANTES de subir -->
          <avatar-editor v-if="grpEditing" :src="store.grpEdit.src"
            :initial="store.grpEdit.initial"
            @confirm="onGrpPhoto" @cancel="onGrpPhotoCancel"></avatar-editor>
          <div class="grp-av" v-else-if="chat.type === 'group'">
            <span class="av-wrap">
              <span class="avatar av72 grp-av-img">
                <img v-if="grpAvatar" :src="grpAvatar" alt="" loading="lazy">
                <span v-else>{{ titleOf(chat).charAt(0).toUpperCase() }}</span>
              </span>
            </span>
            <button class="grp-av-btn" type="button" v-if="canPhoto"
              :title="t('Cambiar foto del grupo')" @click="pickPhoto">
              <svg class="ic ic-sm"><use href="#i-image"></use></svg>
            </button>
          </div>
          <div class="mi-head">
            <b>{{ titleOf(chat) }}</b>
            <span>{{ t('{n} miembro{p}', { n: members.length, p: members.length === 1 ? '' : 's' }) }}<i v-if="onlineCount"> · {{ t('{n} en línea', { n: onlineCount }) }}</i></span>
          </div>
          <!-- W27: en línea primero, desconectados después (con etiqueta
               solo si conviven los dos bloques) -->
          <template v-for="sec in memberSections" :key="sec.key">
            <div class="mi-sec" v-if="sec.show"><span>{{ t(sec.label) }}</span></div>
            <div class="mi-row" role="button" tabindex="0" v-for="m in sec.ms" :key="m.id" @click="openMember(m)" @keydown.enter.prevent="openMember(m)" @keydown.space.prevent="openMember(m)">
              <span class="av-wrap" :class="dotClass(m)">
                <span class="avatar av36">
                  <img v-if="m.avatar_url" :src="mediaUrl(m.avatar_url)" alt="" loading="lazy">
                  <span v-else>{{ (m.display_name || m.username).charAt(0).toUpperCase() }}</span>
                </span>
              </span>
              <span class="mi-col">
                <span class="mi-name-line">
                  <span class="mi-name">{{ m.display_name || m.username }}<i class="mi-me" v-if="isMe(m)">{{ t('Tú') }}</i></span>
                  <i class="mi-role" v-if="isAdmin(m)" :title="t(m.role === 'owner' ? 'Propietario' : 'Administrador')">[Admin]</i>
                </span>
                <span class="mi-sub">{{ memberLine(m) }}</span>
              </span>
              <span class="ci-typing" v-if="memberTyping(m)" :title="t('escribiendo…')"><i></i><i></i><i></i></span>
              <button class="mi-more" type="button" v-if="canManageMember(m)" :title="t('Administrar')" aria-haspopup="menu" @click.stop="memberMenu($event, m)" @keydown.enter.stop @keydown.space.stop>
                <svg class="ic ic-sm"><use href="#i-dots"></use></svg>
              </button>
            </div>
          </template>
        </div>
        <div class="pp-body pp-left" v-else>
          <div class="pp-loading">{{ t('Sin miembros') }}</div>
        </div>
      </template>

      <!-- W29l: fijados y archivos abren MODALES; aquí solo quedan
           los accesos con su conteo (los datos se cargan al abrir la
           info: el número se ve de una) -->
      <div class="pp-acts">
        <button class="pp-pinhead" type="button" aria-haspopup="dialog"
          :aria-expanded="store.pinsModal ? 'true' : 'false'"
          :title="t('Mensajes fijados')" @click="openPins">
          <svg class="ic ic-sm"><use href="#i-pin"></use></svg>
          <b>{{ t('Mensajes fijados') }}</b>
          <i class="pp-ncount" v-if="pins.length">({{ pins.length }})</i>
          <svg class="ic ic-sm pp-chev"><use href="#i-chevron-down"></use></svg>
        </button>
        <button class="pp-pinhead" type="button" aria-haspopup="dialog"
          :aria-expanded="store.galModal ? 'true' : 'false'"
          :title="t('Archivos y medios')" @click="openGal">
          <svg class="ic ic-sm"><use href="#i-file"></use></svg>
          <b>{{ t('Archivos y medios') }}</b>
          <i class="pp-ncount" v-if="gal && (gal.images.length + gal.files.length)">({{ gal.images.length + gal.files.length }})</i>
          <svg class="ic ic-sm pp-chev"><use href="#i-chevron-down"></use></svg>
        </button>
      </div>

      <!-- W29l: modal de mensajes fijados (clic en la fila = salto) -->
      <div class="modal-veil" v-if="store.pinsModal" @click.self="closePins"
        role="dialog" :aria-label="t('Mensajes fijados')">
        <div class="modal pp-modal">
          <!-- W36h: título + (cantidad) juntos; cerrar al extremo derecho -->
          <header><span>{{ t('Mensajes fijados') }}<i v-if="pins.length"> ({{ pins.length }})</i></span>
            <button class="icon-btn" type="button" :title="t('Cerrar')" @click="closePins">
              <svg class="ic"><use href="#i-x"></use></svg>
            </button>
          </header>
          <div class="pp-mbody">
            <div class="pp-loading" v-if="pinsLoading && !pins.length">{{ t('Cargando…') }}</div>
            <div class="pp-loading" v-else-if="!pins.length">{{ t('Sin mensajes fijados') }}</div>
            <button class="pp-pinrow" type="button" v-for="p in pins" :key="p.id"
              @click="goPin(p)">
              <b>{{ p.sender ? (p.sender.display_name || p.sender.username) : '' }}</b>
              <span>{{ p.spoiler ? t('Spoiler') : (p.body || (p.kind === 'voice' ? t('Nota de voz') : (p.media ? (p.media.name || t('Archivo')) : ''))) }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- W29l: modal de archivos y medios — el visor: miniaturas
           grandes con spoiler + lightbox; los archivos saltan al mensaje -->
      <div class="modal-veil gal-veil" v-if="store.galModal" @click.self="closeGal"
        role="dialog" :aria-label="t('Archivos y medios')">
        <div class="modal pp-modal">
          <!-- W36h: título + (cantidad) juntos; cerrar al extremo derecho -->
          <header><span>{{ t('Archivos y medios') }}<i v-if="gal && (gal.images.length + gal.files.length)"> ({{ gal.images.length + gal.files.length }})</i></span>
            <button class="icon-btn" type="button" :title="t('Cerrar')" @click="closeGal">
              <svg class="ic"><use href="#i-x"></use></svg>
            </button>
          </header>
          <div class="pp-mbody">
            <div class="pp-loading" v-if="galLoading && !gal">{{ t('Cargando…') }}</div>
            <div class="pp-loading" v-else-if="!gal || (!gal.images.length && !gal.files.length)">{{ t('Sin archivos') }}</div>
            <div class="pp-galgrid" v-if="gal && gal.images.length">
              <button class="pp-galimg" type="button" v-for="im in gal.images"
                :key="im.msg_id" :title="galSpoiled(im) ? t('Spoiler') : (im.media.name || '')" @click="galClick(im)">
                <img :src="mediaUrl(im.media.url)" alt="" loading="lazy">
                <!-- W29d: miniatura de spoiler tapada hasta tocarla -->
                <span class="gal-spoil" v-if="galSpoiled(im)">
                  <svg class="ic"><use href="#i-eye-off"></use></svg>
                </span>
              </button>
            </div>
            <button class="pp-pinrow" type="button" v-for="f in gal && gal.files"
              :key="f.msg_id" @click="goGal(f)">
              <b>{{ galSpoiled(f) ? t('Spoiler') : (f.media.name || t('Archivo')) }}</b>
              <span>{{ fmtSize(f.media.size) }}</span>
            </button>
          </div>
        </div>
      </div>
    </aside>`,
};

/* ----------------------------------------------------- WallPanel (W20)

   Panel de "Fondo del chat": en desktop/tablet ocupa la columna del
   lista de chats (v-else del <aside class="sidebar">) y en celular es
   una hoja inferior. Muestra una conversación de EJEMPLO —Carlos y
   Javier, con las horas del pedido— con el fondo actual mientras se
   ajustan foto, opacidad del velo y difuminado: los sliders tocan las
   mismas variables (:root) que la conversación real, así que el cambio
   se ve en vivo de los dos lados. */
const WallPanel = {
  setup: function () {
    const wallEl = Vue.ref(null);
    const pickWallImg = function () { if (wallEl.value) wallEl.value.click(); };
    const clearWallImg = function () { setWallImg(''); };
    const onWallFile = function (e) {
      const f = e.target.files && e.target.files[0];
      e.target.value = '';
      if (!f) return;
      shrinkWall(f, function (url, err) {
        if (err) { toast(err, 'err'); return; }
        setWallImg(url);
        toast('Foto de fondo aplicada');
      });
    };
    const dim = Vue.computed({
      get: function () { return store.wdim; },
      set: function (v) { setWallDim(+v); },
    });
    const blur = Vue.computed({
      get: function () { return store.wblur; },
      set: function (v) { setWallBlur(+v); },
    });
    const close = function () { store.wallPanelOpen = false; };

    return {
      store, wallEl, pickWallImg, clearWallImg, onWallFile,
      dim, blur, close,
    };
  },
  template:
    '<aside class="wall-panel">' +
      '<header class="side-head">' +
        '<b>{{ t(\'Fondo del chat\') }}</b>' +
        '<button class="icon-btn" type="button" :title="t(\'Cerrar\')" @click="close">' +
          '<svg class="ic"><use href="#i-x"></use></svg>' +
        '</button>' +
      '</header>' +
      '<div class="wp-body">' +
        '<p class="wp-hint">{{ t(\'La vista previa se ve en el centro, con la conversación de ejemplo.\') }}</p>' +
        '<div class="wp-ctl">' +
          '<div class="ap-sec">{{ t(\'Foto de fondo\') }}</div>' +
          '<div class="wp-row">' +
            '<img v-if="store.wallimg" class="ap-wp-prev" :src="store.wallimg" alt="">' +
            '<button class="btn btn-ghost btn-sm" type="button" @click="pickWallImg">' +
              '{{ t(\'Elegir foto\') }}</button>' +
            '<button v-if="store.wallimg" class="btn btn-ghost btn-sm" type="button"' +
              ' @click="clearWallImg">{{ t(\'Quitar foto\') }}</button>' +
            '<input ref="wallEl" type="file" accept="image/*" class="ap-wall-input"' +
              ' @change="onWallFile">' +
          '</div>' +
        '</div>' +
        /* W27d: sin foto de fondo las opciones no están disponibles
           (opacidad y difuminado solo aplican a la imagen) */
        '<div class="wp-ctl" :class="{ off: !store.wallimg }">' +
          '<div class="ap-sec">{{ t(\'Opacidad del velo\') }}:' +
            ' <span class="wp-val">{{ dim }}%</span></div>' +
          '<input class="wp-range" type="range" min="0" max="100" step="5" v-model="dim"' +
            ' :disabled="!store.wallimg" :aria-label="t(\'Opacidad del velo\')">' +
        '</div>' +
        '<div class="wp-ctl" :class="{ off: !store.wallimg }">' +
          '<div class="ap-sec">{{ t(\'Difuminado\') }}:' +
            ' <span class="wp-val">{{ blur }} px</span></div>' +
          '<input class="wp-range" type="range" min="0" max="20" step="1" v-model="blur"' +
            ' :disabled="!store.wallimg" :aria-label="t(\'Difuminado\')">' +
        '</div>' +
      '</div>' +
    '</aside>',
};

/* --------------------------------------------------- WallPreview (W21c)

   Vista previa a TAMAÑO REAL: ocupa el centro (donde va la
   conversación) mientras el panel de fondo está abierto. Copia el
   layout de .chat-pane, así que las MISMAS capas --wallimg /
   --wall-dim / --wall-blur le aplican: lo que se ve es exactamente lo
   que se verá en el chat real al cerrar el panel. */
const WallPreview = {
  setup: function () {
    /* Muestra del pedido: Carlos (derecha) y Javier (izquierda), con
       nombre en la primera de la ronda y hora en la última (W12). */
    const SAMPLE = [
      { mine: true, name: 'Carlos', time: '6:10 p.m.',
        texts: ['¡Hola!', '¿Qué tal tu día?'] },
      { mine: false, name: 'Javier', time: '6:11 p.m.',
        texts: ['¡Hola! Todo bien por aquí', 'Acomodando unas cosas', '¿Y tú qué tal?'] },
      { mine: true, name: 'Carlos', time: '6:11 p.m.',
        texts: ['Bien también, descansando un rato', 'Hablamos más tarde'] },
      { mine: false, name: 'Javier', time: '6:12 p.m.',
        texts: ['¡Dale, perfecto!', 'Un abrazo 👍'] },
    ];
    const rows = [];
    SAMPLE.forEach(function (g) {
      g.texts.forEach(function (tx, i) {
        rows.push({
          mine: g.mine,
          name: g.name,
          showName: i === 0,
          time: i === g.texts.length - 1 ? g.time : '',
          text: tx,
        });
      });
    });
    const bodyEl = Vue.ref(null);
    Vue.onMounted(function () {
      /* como un chat real: abierta al último mensaje */
      if (bodyEl.value) bodyEl.value.scrollTop = bodyEl.value.scrollHeight;
    });
    return { rows, bodyEl };
  },
  template:
    '<main class="wall-preview">' +
      '<header class="chat-head wp-head">' +
        '<div class="ch-col">' +
          '<div class="ch-name">{{ t(\'Vista previa del fondo\') }}</div>' +
          '<div class="ch-status">{{ t(\'Así se verá tu conversación con el fondo.\') }}</div>' +
        '</div>' +
      '</header>' +
      '<div class="msgs wp-prev" ref="bodyEl">' +
        '<div class="msg" :class="{ mine: r.mine }" v-for="(r, i) in rows" :key="i">' +
          '<div class="bubble">' +
            '<div class="b-sender wp-name" v-if="r.showName">{{ r.name }}</div>' +
            '<div class="b-text">{{ r.text }}</div>' +
            '<div class="b-meta" v-if="r.time"><span class="b-time">{{ r.time }}</span></div>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</main>',
};

/* ------------------------------------------- PeoplePanel (W27)
   Panel Personas/Amigos del sidebar: pestañas "Activos" (amigos, en
   línea primero) y "Solicitudes" (bloques Enviados y Recibidas con
   Aceptar / Rechazar / Cancelar). La app arranca en esta vista. */
const PeoplePanel = {
  name: 'PeoplePanel',
  setup: function () {
    /* W27c: la pestaña vive en el store: la opción "Personas" del
       sidebar (o abrir un chat) la devuelve a la pantalla principal. */
    const tab = Vue.computed({
      get: function () { return store.peopleTab; },
      set: function (v) { store.peopleTab = v; },
    });
    const q = Vue.ref('');
    const results = Vue.ref([]);

    const people = Vue.computed(function () {
      return store.people || { friends: [], sent: [], received: [] };
    });
    const nReq = Vue.computed(function () {
      return people.value.received.length;
    });
    const loaded = Vue.computed(function () { return !!store.people; });

    const friendOn = function (u) {
      return !!(u && (store.presence[u.id] != null ? store.presence[u.id] : u.online));
    };
    const lineOf = function (u) {
      if (!friendOn(u)) return t('Desconectado');
      if (u.status_text) return u.status_text;
      if (u.status_preset) return presetLabel(u.status_preset);
      return t('En línea');
    };

    /* W27e: Activos muestra SOLO amigos conectados. "Ausente" (busy)
       y "No molestar" (dnd) son estados de quien está en línea, así
       que sus filas siguen aquí; los desconectados no aparecen (los
       invisibles ya llegan marcados como desconectados por el server). */
    const activeOnline = Vue.computed(function () {
      const fs = people.value.friends;
      const out = [];
      for (let i = 0; i < fs.length; i++) if (friendOn(fs[i])) out.push(fs[i]);
      return out;
    });

    /* Búsqueda de personas para enviar solicitud (mismo debounce que la
       lupa de chats: 300 ms y mínimo 2 caracteres). */
    let timer = 0;
    Vue.watch(q, function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () {
        const s = q.value.trim();
        if (s.length < 2) { results.value = []; return; }
        searchUsers(s).then(function (rs) {
          results.value = rs;
        }).catch(function () {
          results.value = [];
        });
      }, 300);
    });

    const isFriend = function (u) {
      const fs = people.value.friends;
      for (let i = 0; i < fs.length; i++) if (fs[i].id === u.id) return true;
      return false;
    };
    const sentTo = function (u) {
      const rs = people.value.sent;
      for (let i = 0; i < rs.length; i++) {
        if (rs[i].user && rs[i].user.id === u.id) return rs[i].id;
      }
      return 0;
    };

    const run = function (fn, okMsg) {
      Promise.resolve(fn()).then(function () {
        if (okMsg) toast(okMsg, 'ok');
      }).catch(function (err) {
        toast((err && err.detail) || 'No se pudo completar la acción', 'err');
      });
    };

    /* Clic en un amigo: abre el DM (o lo crea si aún no existe). */
    const openFriend = function (u) {
      for (let i = 0; i < store.chats.length; i++) {
        const c = store.chats[i];
        if (c.type === 'dm' && c.title && c.title.id === u.id) {
          openChat(c.id);
          return;
        }
      }
      run(function () { return createDm(u.username); });
    };

    const send = function (u) {
      run(function () { return sendFriendRequest(u.username); }, 'Solicitud enviada');
    };
    const cancel = function (r) {
      run(function () { return cancelFriendRequest(r.id); });
    };
    const reject = function (r) {
      run(function () { return rejectFriendRequest(r.id); });
    };
    /* Aceptar crea (o abre) el DM y salta a la pestaña Chats con el chat
       listo (acceptFriendRequest lo hace en actions). */
    const accept = function (r) {
      run(function () { return acceptFriendRequest(r.id); });
    };

    /* W27b: en Solicitudes la búsqueda filtra las listas. */
    const qReq = Vue.ref('');
    const matchR = function (r) {
      const s = qReq.value.trim().toLowerCase();
      if (!s) return true;
      const u = r.user || {};
      return (u.display_name || '').toLowerCase().indexOf(s) >= 0 ||
        (u.username || '').toLowerCase().indexOf(s) >= 0;
    };
    const sentF = Vue.computed(function () {
      return people.value.sent.filter(matchR);
    });
    const recF = Vue.computed(function () {
      return people.value.received.filter(matchR);
    });
    /* "Buscar personas": mismo efecto que el ＋ del sidebar (abre el
       modal de chat nuevo con la búsqueda de personas). */
    const buscarPersonas = function () {
      store.newChatMode = 'dm';
      store.newChatOpen = true;
    };

    return {
      store, tab, q, results, people, nReq, loaded, activeOnline,
      lineOf, isFriend, sentTo, openFriend, send, cancel, reject, accept,
      qReq, sentF, recF, buscarPersonas,
      dotClass, mediaUrl,
    };
  },
  template: `
    <div class="ppl">
      <div class="ppl-tabs">
        <button class="ppl-tab" type="button" :class="{ on: tab === 'active' }"
          @click="tab = 'active'">{{ t('Activos') }}</button>
        <button class="ppl-tab" type="button" :class="{ on: tab === 'req' }"
          @click="tab = 'req'">{{ t('Solicitudes') }}
          <i class="ppl-badge" v-if="nReq">{{ nReq }}</i></button>
      </div>

      <template v-if="tab === 'active'">
        <div class="search-pill ppl-find">
          <svg class="ic ic-sm"><use href="#i-search"></use></svg>
          <input v-model="q" :placeholder="t('Buscar personas por usuario')"
            :aria-label="t('Buscar personas por usuario')">
        </div>

        <div class="ppl-list" v-if="q.trim().length >= 2">
          <div class="ppl-row" v-for="u in results" :key="u.id">
            <span class="av-wrap" :class="dotClass(u)">
              <span class="avatar av36">
                <img v-if="u.avatar_url" :src="mediaUrl(u.avatar_url)" alt="" loading="lazy">
                <span v-else>{{ (u.display_name || u.username).charAt(0).toUpperCase() }}</span>
              </span>
            </span>
            <span class="ppl-col">
              <b>{{ u.display_name || u.username }}</b>
              <i>@{{ u.username }}</i>
            </span>
            <span class="ppl-acts">
              <button class="btn btn-xs" v-if="isFriend(u)" type="button"
                @click="openFriend(u)">{{ t('Mensaje') }}</button>
              <button class="btn btn-xs btn-ghost" v-else-if="sentTo(u)" type="button"
                disabled>{{ t('Solicitud enviada') }}</button>
              <button class="btn btn-xs" v-else type="button"
                @click="send(u)">{{ t('Enviar solicitud') }}</button>
            </span>
          </div>
          <div class="list-empty" v-if="!results.length">{{ t('Sin resultados') }}</div>
        </div>

        <div class="ppl-list" v-else>
          <button class="ppl-row" type="button" v-for="u in activeOnline" :key="u.id"
            @click="openFriend(u)">
            <span class="av-wrap" :class="dotClass(u)">
              <span class="avatar av36">
                <img v-if="u.avatar_url" :src="mediaUrl(u.avatar_url)" alt="" loading="lazy">
                <span v-else>{{ (u.display_name || u.username).charAt(0).toUpperCase() }}</span>
              </span>
            </span>
            <span class="ppl-col">
              <b>{{ u.display_name || u.username }}</b>
              <i>{{ lineOf(u) }}</i>
            </span>
          </button>
          <div class="list-empty" v-if="loaded && !people.friends.length">
            {{ t('Aún no tienes amigos. ¡Busca personas arriba para empezar!') }}
          </div>
          <div class="list-empty" v-else-if="loaded && !activeOnline.length">
            {{ t('Ningún amigo en línea') }}
          </div>
        </div>
      </template>

      <template v-else>
        <div class="search-pill ppl-find">
          <svg class="ic ic-sm"><use href="#i-search"></use></svg>
          <input v-model="qReq" :placeholder="t('Buscar solicitudes')"
            :aria-label="t('Buscar solicitudes')">
        </div>
        <div class="ppl-cta">
          <button class="btn btn-ghost btn-full" type="button" @click="buscarPersonas">
            <svg class="ic ic-sm"><use href="#i-plus"></use></svg>{{ t('Buscar personas') }}
          </button>
        </div>
        <div class="ppl-list">
          <template v-if="sentF.length">
            <div class="mi-sec mi-sec-always"><span>{{ t('Enviados') }}</span></div>
            <div class="ppl-row" v-for="r in sentF" :key="'s' + r.id">
              <span class="av-wrap" :class="dotClass(r.user)">
                <span class="avatar av36">
                  <img v-if="r.user.avatar_url" :src="mediaUrl(r.user.avatar_url)" alt="" loading="lazy">
                  <span v-else>{{ (r.user.display_name || r.user.username).charAt(0).toUpperCase() }}</span>
                </span>
              </span>
              <span class="ppl-col">
                <b>{{ r.user.display_name || r.user.username }}</b>
                <i>@{{ r.user.username }}</i>
              </span>
              <span class="ppl-acts">
                <button class="btn btn-xs btn-ghost" type="button"
                  @click="cancel(r)">{{ t('Cancelar') }}</button>
              </span>
            </div>
          </template>
          <template v-if="recF.length">
            <div class="mi-sec mi-sec-always"><span>{{ t('Recibidas') }}</span></div>
            <div class="ppl-row" v-for="r in recF" :key="'r' + r.id">
              <span class="av-wrap" :class="dotClass(r.user)">
                <span class="avatar av36">
                  <img v-if="r.user.avatar_url" :src="mediaUrl(r.user.avatar_url)" alt="" loading="lazy">
                  <span v-else>{{ (r.user.display_name || r.user.username).charAt(0).toUpperCase() }}</span>
                </span>
              </span>
              <span class="ppl-col">
                <b>{{ r.user.display_name || r.user.username }}</b>
                <i>@{{ r.user.username }}</i>
              </span>
              <span class="ppl-acts">
                <button class="btn btn-xs" type="button"
                  @click="accept(r)">{{ t('Aceptar') }}</button>
                <button class="btn btn-xs btn-ghost" type="button"
                  @click="reject(r)">{{ t('Rechazar') }}</button>
              </span>
            </div>
          </template>
          <div class="list-empty" v-if="!sentF.length && !recF.length">
            {{ qReq.trim() ? t('Sin resultados') : t('No hay solicitudes pendientes') }}
          </div>
        </div>
      </template>
    </div>`,
};

/* ------------------------------------------------------- ChatShell */

export const ChatShell = {
  components: { MessageRow, NewChatModal, SettingsModal, MeProfileModal, MeProfileEditModal, ConfirmBox, ReadsBox, CallBox, ProfilePanel, ChatInfoPanel, EmojiPicker, SpamBox, WallPanel, WallPreview, PeoplePanel },
  setup: function () {
    const scroller = Vue.ref(null);
    const input = Vue.ref(null);
    const fileInput = Vue.ref(null);
    const draft = Vue.ref('');
    const stick = Vue.ref(true);
    /* W29d: marcar el PRÓXIMO mensaje/archivo/nota como spoiler. */
    const spoilNext = Vue.ref(false);
    /* W29h: mantener ENVIAR 3 s → el mensaje sale como spoiler. */
    const holdOn = Vue.ref(false);
    let holdTimer = 0;
    let holdFired = false;     /* el clic al soltar ya no reenvía */
    let spoilOnce = false;     /* spoiler de UN solo envío (long-press) */
    const rootEl = Vue.ref(null);     // W11: raíz p/ drag & drop de archivos
    /* W27h: al (re)montar la pantalla principal, el "Cargando…" del
       arranque cubre la carga de chats, gente y mensajes iniciales. */
    store.booting = true;

    /* W39: código que muestra el MODAL de verificación — el menú ⋯ del
       chat puede pedirlo para cualquier chat de la lista (el modal vive
       en esta plantilla, no en el panel de info). */
    const sasCode = Vue.computed(function () {
      return (store.e2eSas && store.e2eSas[store.sasFor]) || '';
    });

    /* ---------- lista ---------- */

    const filteredChats = Vue.computed(function () {
      const q = store.search.trim().toLowerCase();
      if (!q) return store.chats;
      return store.chats.filter(function (c) {
        return chatTitle(c).toLowerCase().indexOf(q) >= 0 ||
          (c.title && c.title.username && c.title.username.toLowerCase().indexOf(q) >= 0);
      });
    });

    const listEmpty = Vue.computed(function () {
      return !filteredChats.value.length;
    });

    const activeChat = Vue.computed(function () {
      const id = store.activeChatId;
      for (let i = 0; i < store.chats.length; i++) if (store.chats[i].id === id) return store.chats[i];
      return null;
    });

    /* W27h: "Cargando…" de la conversación — solo mientras el chat
       activo aún no tiene mensajes (si el flag quedó de otro chat que
       sigue en vuelo, un chat ya cargado no se tapa). */
    const chatLoading = Vue.computed(function () {
      return !!(store.chatLoading && store.activeChatId &&
        !store.loaded[store.activeChatId]);
    });

    const avatarOf = function (c) {
      if (!c) return '';
      const url = c.type === 'dm' ? (c.title && c.title.avatar_url) : c.avatar_url;
      return url ? mediaUrl(url) : '';
    };
    const initialsOf = function (c) {
      const t = chatTitle(c);
      return t ? t.charAt(0).toUpperCase() : '?';
    };

    const previewText = function (c) {
      const lm = c.last_message;
      if (!lm) return c.type === 'dm' ? t('Escribe para empezar') : t('Grupo nuevo');
      const mine = !!(lm.sender && store.user && lm.sender.id === store.user.id);
      let who = '';
      if (mine) who = t('Tú: ');
      else if (c.type === 'group' && lm.sender) who = (lm.sender.display_name || lm.sender.username) + ': ';
      if (lm.kind === 'system') return lm.body || '';
      /* W45: el preview de la lista no debe destapar un spoiler. */
      if (lm.spoiler) return who + t('Spoiler');
      if (lm.kind === 'image') return who + t('Imagen');
      if (lm.kind === 'voice') return who + t('Nota de voz');
      if (lm.kind === 'file') {
        /* W11: los videos se distinguen de los archivos comunes */
        return who + (lm.media && /^video\//.test(lm.media.mime || '') ? t('Video') : t('Archivo'));
      }
      /* W30c/W32: el preview de la lista se muestra DESCIFRADO; si el
         mensaje cifrado todavía no se descifra, no se pinta nada —
         nunca el marcador "[Mensaje cifrado]". */
      if (lm.e2e && lm._plain == null) return '';
      return who + (lm._plain != null ? lm._plain : (lm.body || ''));
    };

    /* W29c: pelotita de "escribiendo…" para la lista de chats. */
    const chatTyping = function (c) {
      const bag = store.typing[c.id];
      if (!bag) return 0;
      let n = 0;
      for (const k in bag) n++;
      return n;
    };

    const listTime = function (c) {
      return c.last_message ? fmtListTime(c.last_message.created_at) : '';
    };

    /* ---------- conversación ---------- */

    const rows = Vue.computed(function () {
      const all = store.msgs[store.activeChatId];
      const out = [];
      if (!all) return out;
      /* W32: un mensaje cifrado AÚN sin descifrar NO se pinta: así no
         aparece (ni parpadea) el marcador "[Mensaje cifrado]" — la
         fila nace cuando llega _plain. Se leen e2e/_plain de TODOS
         los mensajes para que Vue rastree los ocultos (al descifrar,
         el computed se re-evalúa y la fila aparece), y el agrupado
         corre sólo sobre los visibles. */
      const arr = [];
      for (let i = 0; i < all.length; i++) {
        const x = all[i];
        if (x.e2e && x._plain == null) continue;
        arr.push(x);
      }
      const meId = store.user ? store.user.id : 0;
      const chat = activeChat.value;
      const isGroup = !!(chat && chat.type === 'group');
      /* W12: ✓ enviado → ✓✓ recibido → ✓✓ azul leído.
         W29c: en GRUPOS ✓✓ = "todos" → MÍNIMO entre los demás (semilla
         peer_*_min_seq + eventos en vivo); en DM (un solo par) máx y
         mín dan lo mismo y sigue sembrándose con peer_*_seq. */
      let rseq; let dseq;
      const rs = store.readSeqs[store.activeChatId];
      const ds = store.deliveredSeqs[store.activeChatId];
      if (isGroup) {
        /* W29c: ✓✓ de grupo = "todos" → mínimo entre los demás. La
           semilla (peer_*_min_seq) vale para quienes no han dicho nada
           en vivo; si los eventos en vivo ya cubren a todos los demás,
           manda el mínimo en vivo (la semilla 0 ya no estorba). */
        const others = Math.max(1,
          (chat && chat.member_count ? chat.member_count : 2) - 1);
        const liveMin = function (bag) {
          let cov = 0; let mn = 0; let seen = 0;
          if (bag) {
            for (const k in bag) {
              if (+k === meId) continue;
              cov++;
              if (!seen || bag[k] < mn) { mn = bag[k]; seen = 1; }
            }
          }
          return seen ? { cov: cov, mn: mn } : null;
        };
        const lr = liveMin(rs);
        rseq = chat && chat.peer_read_min_seq != null ? chat.peer_read_min_seq : 0;
        if (lr) rseq = lr.cov >= others ? lr.mn : Math.min(rseq, lr.mn);
        const ld = liveMin(ds);
        dseq = chat && chat.peer_delivered_min_seq != null ? chat.peer_delivered_min_seq : 0;
        if (ld) dseq = ld.cov >= others ? ld.mn : Math.min(dseq, ld.mn);
      } else {
        rseq = chat && chat.peer_read_seq ? chat.peer_read_seq : 0;
        if (rs) for (const k in rs) { if (+k !== meId && rs[k] > rseq) rseq = rs[k]; }
        dseq = chat && chat.peer_delivered_seq ? chat.peer_delivered_seq : 0;
        if (ds) for (const k in ds) { if (+k !== meId && ds[k] > dseq) dseq = ds[k]; }
      }
      let prevDay = null;
      for (let i = 0; i < arr.length; i++) {
        const m = arr[i];
        const p = i > 0 ? arr[i - 1] : null;
        const n = i + 1 < arr.length ? arr[i + 1] : null;
        const d = new Date(m.created_at * 1000);
        const dk = dayKey(d);
        const mine = !!(m.sender && meId && m.sender.id === meId);
        const sameSender = !!(p && p.sender && m.sender && p.sender.id === m.sender.id);
        const tight = !!(p && sameSender && dk === prevDay && m.kind !== 'system' &&
          p.kind !== 'system' && m.created_at - p.created_at < 600);
        /* W12: la hora se ve SOLO en el último mensaje del minuto (WhatsApp):
           mismo emisor, mismo minuto y siguiente no-sistema → sin hora. */
        const sameRun = !!(n && n.sender && m.sender && n.sender.id === m.sender.id &&
          n.kind !== 'system' && m.kind !== 'system');
        const showTime = !sameRun ||
          Math.floor(n.created_at / 60) !== Math.floor(m.created_at / 60);
        /* W29c: nombre visible del emisor —la cara del avatar usa el
           MISMO criterio (solo en la primera fila de la tanda). Las
           RESPUESTAS siempre lo muestran: el nombre va sobre la cita. */
        const withName = isGroup && !mine && m.kind !== 'system' &&
          !!m.sender && (!tight || !!m.reply_to);
        out.push({
          ref: m,
          day: dk !== prevDay ? dayLabel(d) : null,
          tight: tight,
          mine: mine,
          /* W29c: columna de avatar en TODOS los entrantes de grupo
             (burbujas alineadas); foto/letra solo en el primero de la
             tanda —donde se ve el nombre del emisor—, estilo WhatsApp.
             Los mensajes del sistema van centrados: sin columna. */
          avCol: isGroup && !mine && m.kind !== 'system',
          avatar: (withName && m.sender) ? {
            url: m.sender.avatar_url || '',
            ini: (m.sender.display_name || m.sender.username || '?')
              .charAt(0).toUpperCase(),
            name: m.sender.display_name || m.sender.username || '',
          } : null,
          showSender: withName,
          /* recibos apagados (W6): solo ✓, nunca ✓✓ ni azul */
          state: !mine || !m.seq ? 'sent'
            : (!store.prefs.receipts ? 'sent'
              : (rseq >= m.seq ? 'read'
                : (dseq >= m.seq ? 'delivered' : 'sent'))),
          showTime: showTime,
          time: fmtTime(d),
        });
        prevDay = dk;
      }
      return out;
    });

    /* W29c: "escribiendo…" por USUARIO: varios pueden escribir a la vez
       (grupos); store.typing[chatId] = { userId: {u, exp} }. */
    const typingIds = Vue.computed(function () {
      const c = store.typing[store.activeChatId] || {};
      const out = [];
      for (const k in c) out.push(+k);
      return out;
    });
    const typingActive = Vue.computed(function () {
      return typingIds.value.length > 0;
    });
    const typingNames = Vue.computed(function () {
      const ids = typingIds.value;
      const c = activeChat.value;
      const bag = store.typing[store.activeChatId] || {};
      const mem = (store.info && store.info.chatId === store.activeChatId &&
                   store.info.members) ? store.info.members : null;
      const out = [];
      for (let i = 0; i < ids.length; i++) {
        const ent = bag[ids[i]];
        let nm = ent && ent.u ? ent.u : '';
        if (!nm && c && c.type === 'dm' && c.title && c.title.id === ids[i]) {
          nm = c.title.display_name || c.title.username || '';
        }
        if (!nm && mem) {
          for (let j = 0; j < mem.length; j++) {
            if (mem[j].id === ids[i]) {
              nm = mem[j].display_name || mem[j].username || '';
              break;
            }
          }
        }
        if (!nm) nm = '#' + ids[i];
        out.push(nm);
      }
      return out;
    });
    const typingLabel = Vue.computed(function () {
      const ns = typingNames.value;
      if (!ns.length) return '';
      const c = activeChat.value;
      if (ns.length === 1) {
        return t('{n} está escribiendo…', { n: ns[0] });
      }
      if (c && c.type !== 'dm' && ns.length > 3) {
        return t('{a}, {b} y {m} más están escribiendo…',
          { a: ns[0], b: ns[1], m: ns.length - 2 });
      }
      return t('{n} están escribiendo…', { n: ns.join(', ') });
    });
    /* Avatares apilados tipo cartas junto a los puntos (sólo grupos). */
    const typingAvs = Vue.computed(function () {
      const c = activeChat.value;
      const ids = typingIds.value;
      if (!c || c.type !== 'group' || !ids.length) return [];
      const mem = (store.info && store.info.chatId === store.activeChatId &&
                   store.info.members) ? store.info.members : null;
      const out = [];
      if (!mem) return out;
      for (let i = 0; i < ids.length && out.length < 3; i++) {
        for (let j = 0; j < mem.length; j++) {
          if (mem[j].id === ids[i] && mem[j].avatar_url) {
            out.push(mediaUrl(mem[j].avatar_url));
            break;
          }
        }
      }
      return out;
    });

    /* W26: la presencia del peer se lee de store.presence (eventos WS +
       snapshot al reconectar); c.title.online del REST es solo el primer
       relleno y puede traer un estado con fecha vieja. */
    const peerOn = Vue.computed(function () {
      const c = activeChat.value;
      if (!c || c.type !== 'dm' || !c.title) return false;
      const tt = c.title;
      return !!(store.presence[tt.id] != null ? store.presence[tt.id] : tt.online);
    });

    const statusLine = Vue.computed(function () {
      const c = activeChat.value;
      if (!c) return '';
      if (typingActive.value) return t('escribiendo…');
      if (c.type === 'group') {
        const n = c.member_count || 0;
        return t('{n} participante{p}', { n: n, p: n === 1 ? '' : 's' });
      }
      const tt = c.title || {};
      const on = store.presence[tt.id] != null ? store.presence[tt.id] : tt.online;
      return on ? t('en línea') : fmtLastSeen(tt.last_seen);
    });

    /* ---------- scroll ---------- */

    const scrollBottom = function () {
      const el = scroller.value;
      if (el) el.scrollTop = el.scrollHeight;
    };

    /* W54d: al abrir el teclado el alto cambia después de la animación
       del sistema; bajamos la conversación para que el último mensaje
       quede a la vista junto al composer. */
    const keepComposerVisible = function () {
      setTimeout(function () {
        if (document.activeElement === input.value) scrollBottom();
      }, 280);
    };
    const onKeyboardViewport = function () {
      if (document.activeElement !== input.value) return;
      setTimeout(function () {
        if (document.activeElement === input.value) scrollBottom();
      }, 80);
    };

    /* La imagen crece el layout al terminar de cargar: si estábamos
       pegados al final, volver a scrollear. */
    const onImgLoad = async function () {
      if (!stick.value) return;
      await Vue.nextTick();
      scrollBottom();
    };

    const onScroll = function () {
      const el = scroller.value;
      if (!el) return;
      stick.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      if (el.scrollTop <= 40 && store.hasMore[store.activeChatId] &&
          !store.loadingOlder && store.loaded[store.activeChatId]) {
        doLoadOlder();
      }
    };

    const doLoadOlder = async function () {
      const el = scroller.value;
      const id = store.activeChatId;
      const prevH = el ? el.scrollHeight : 0;
      const prevTop = el ? el.scrollTop : 0;
      await loadOlder(id);
      if (store.activeChatId !== id) return;
      await Vue.nextTick();
      if (el) el.scrollTop = el.scrollHeight - prevH + prevTop;
    };

    /* W27: el alto de una fila cambia cuando un medio termina de cargar
       (imagen, video, nota, archivo) o una subida se confirma. Un
       ResizeObserver por fila (no por .msgs: su alto propio no varía al
       cargar medios) y, si estamos cerca del final, la vista baja sola. */
    let rowRO = null;
    const syncRowsRO = function () {
      const el = scroller.value;
      if (!el || !window.ResizeObserver) return;
      if (!rowRO) {
        rowRO = new ResizeObserver(function () {
          if (stick.value) scrollBottom();
        });
      }
      rowRO.disconnect();
      for (let i = 0; i < el.children.length; i++) rowRO.observe(el.children[i]);
    };

    Vue.watch(rows, async function () {
      await Vue.nextTick();
      syncRowsRO();
      if (stick.value) scrollBottom();
    });

    /* W25: los puntos de "escribiendo…" se montan al final de la lista y
       empujan el alto del scroll: si estamos cerca del final (stick), la
       vista baja solita para mostrarlos; si el usuario está leyendo
       historial, no se la arrastra. */
    Vue.watch(typingActive, async function (on) {
      if (!on || !stick.value) return;
      await Vue.nextTick();
      scrollBottom();
    });

    Vue.watch(function () { return store.activeChatId; }, async function (id) {
      stick.value = true;
      draft.value = '';
      replyTo.value = null;
      /* W7: al cambiar de chat se limpian menú, picker y panel de info */
      store.ctx = null;
      store.reactFor = 0;
      store.emoOpen = false;
      clearAc();
      store.info = null;
      /* W13: nada de búsqueda ni reenvío cruzando chats */
      searchOpen.value = false;
      sQ.value = '';
      sResults.value = [];
      sErr.value = '';
      fwdFor.value = null;
      /* W8: nada de zoom ni ediciones cruzando chats */
      closeLb();
      store.editFor = 0;
      store.editDraft = '';
      /* W28b: en grupos los miembros se cargan aunque el panel de info
         esté cerrado (la burbuja pinta las @menciones con esa lista). */
      const esGrupo = id && store.chats.some(function (c) {
        return c.id === id && c.type === 'group';
      });
      if (id && (store.infoOpen || esGrupo) &&
          (!store.info || store.info.chatId !== id || store.info.error)) {
        loadMembers(id);
      }
      if (rec.value === 'on') stopRec(false);   // no mandar media al cambiar de chat
      if (input.value) input.value.style.height = 'auto';
      if (!id) return;
      await Vue.nextTick();
      scrollBottom();
    });

    /* ---------- responder ---------- */

    const replyTo = Vue.ref(null);

    const startReply = function (m) {
      replyTo.value = m;
      if (input.value) input.value.focus();
    };
    const cancelReply = function () { replyTo.value = null; };

    const replySender = Vue.computed(function () {
      const s = replyTo.value;
      if (!s || !s.sender) return '';
      if (typeof s.sender === 'string') return s.sender;
      return s.sender.display_name || s.sender.username || '';
    });

    const replyPreview = Vue.computed(function () {
      const s = replyTo.value;
      if (!s) return '';
      /* W45: al responder un spoiler, la barra de respuesta tampoco lo
         muestra. */
      if (s.spoiler) return t('Spoiler');
      /* W37: el texto descifrado manda (los E2E guardan el marcador en
         body y el claro en _plain). */
      const txt = (s._plain != null ? s._plain : s.body) || '';
      if (txt) return txt.length > 90 ? txt.slice(0, 90) + '…' : txt;
      if (s.kind === 'voice') return t('Nota de voz');
      if (s.kind === 'image') return t('Imagen');
      if (s.kind === 'system') return '';
      return t('Archivo adjunto');
    });

    const onReact = function (m, emoji) {
      toggleReaction(store.activeChatId, m.id, emoji);
    };

    /* W30d: aviso visible mientras el cifrado NO puede activarse
       (el par aún no publica su clave) — se ve mientras se chatea. */
    const e2ePendBar = Vue.computed(function () {
      const c = activeChat.value;
      if (!c || c.type !== 'dm') return '';
      if (store.e2e[c.id]) return '';
      if (!(store.e2ePend && store.e2ePend[c.id])) return '';
      const n = (c.title && (c.title.display_name || c.title.username)) || '';
      return t('Cifrado pendiente: se activará cuando {n} publique sus claves', { n: n });
    });

    /* ---------- notas de voz ---------- */

    const rec = Vue.ref('off');        // off | on
    const recSecs = Vue.ref(0);
    let recorder = null;
    let recStream = null;
    let recTimer = null;
    let recChunks = [];
    let recSend = false;
    /* W13: onda de voz (picos tomados del stream mientras graba) */
    let recCtx = null;
    let recAnalyser = null;
    let recPeaks = [];
    let recPeakTimer = null;
    /* W24: onda EN VIVO del micrófono (estilo WhatsApp): ventana móvil con
       los últimos picos; las barras se dibujan con esos datos reales. Si el
       AnalyserNode falla, la grabación sigue y se ve la onda falsa de CSS. */
    const REC_WAVE_N = 22;
    const recWave = Vue.ref([]);

    const recTime = Vue.computed(function () {
      const s = recSecs.value;
      return Math.floor(s / 60) + ':' + pad(s % 60);
    });

    function clearRec() {
      if (recTimer) { clearInterval(recTimer); recTimer = null; }
      if (recPeakTimer) { clearTimeout(recPeakTimer); recPeakTimer = null; }
      recAnalyser = null;
      if (recCtx) { try { recCtx.close(); } catch (e) {} recCtx = null; }
      recPeaks = [];
      recWave.value = [];
      if (recStream) {
        const ts = recStream.getTracks();
        for (let i = 0; i < ts.length; i++) { try { ts[i].stop(); } catch (e) {} }
        recStream = null;
      }
      recorder = null;
      recChunks = [];
      rec.value = 'off';
      recSecs.value = 0;
    }

    /* W24: escala Y (scaleY) de la barra i de la onda en vivo. Sin dato aún
       (analyser caído o primeros 80 ms) devuelve el valor plano de la onda. */
    const recBar = function (i) {
      const v = recWave.value[i];
      if (v == null) return 0.18;
      return Math.max(0.07, Math.min(1, v / 100));
    };

    const startRec = async function () {
      if (rec.value === 'on') return;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
        /* W19: sobre HTTP con IP ajena a localhost el navegador BLOQUEA
           el micrófono (contexto inseguro): decirlo claro, no culpar al
           navegador. */
        toast(window.isSecureContext === false
          ? 'El micrófono necesita HTTPS (o abrir Foxinix en localhost)'
          : 'Tu navegador no soporta notas de voz', 'err');
        return;
      }
      try {
        /* W20: si hay un micrófono elegido en Ajustes → Chat, se usa ese
           (deviceId exact); si ya no existe o falla, el del sistema. */
        recStream = await navigator.mediaDevices.getUserMedia({
          audio: store.micDev ? { deviceId: { exact: store.micDev } } : true,
        });
      } catch (e) {
        let lastErr = e;
        if (store.micDev) {
          try {
            recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
          } catch (e2) {
            lastErr = e2;
            recStream = null;
          }
        }
        if (!recStream) {
          toast(lastErr && (lastErr.name === 'NotAllowedError' ||
            lastErr.name === 'SecurityError')
            ? 'Permiso de micrófono bloqueado. Actívalo en Ajustes de Android > Foxinix > Permisos.'
            : 'No se pudo acceder al micrófono', 'err');
          return;
        }
      }
      /* W13/W24: picos de la onda — mismo stream, AnalyserNode cada 80 ms
         (alimenta la onda EN VIVO mientras graba y la del mensaje enviado).
         Si falla, el audio se manda igual (onda falsa CSS al grabar). */
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (AC) {
          recCtx = new AC();
          const aSrc = recCtx.createMediaStreamSource(recStream);
          recAnalyser = recCtx.createAnalyser();
          recAnalyser.fftSize = 1024;
          aSrc.connect(recAnalyser);
          recPeaks = [];
          const buf = new Uint8Array(recAnalyser.fftSize);
          const tick = function () {
            if (!recAnalyser) return;
            recAnalyser.getByteTimeDomainData(buf);
            let peak = 0;
            for (let i = 0; i < buf.length; i++) {
              const v = Math.abs(buf[i] - 128) / 128;
              if (v > peak) peak = v;
            }
            const p = Math.min(100, Math.round(peak * 130));
            recPeaks.push(p);
            /* W24: onda en vivo — media móvil (ataque rápido, caída suave)
               para que las barras sigan el volumen real del micrófono. */
            const last = recWave.value.length ? recWave.value[recWave.value.length - 1] : p;
            recWave.value.push(Math.round(p * 0.65 + last * 0.35));
            while (recWave.value.length > REC_WAVE_N) recWave.value.shift();
            recPeakTimer = setTimeout(tick, 80);
          };
          tick();
        }
      } catch (e) { recAnalyser = null; }
      let rec1;
      try {
        let mime = '';
        const cands = ['audio/webm', 'audio/ogg;codecs=opus', 'audio/ogg'];
        for (let i = 0; i < cands.length; i++) {
          if (window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(cands[i])) {
            mime = cands[i]; break;
          }
        }
        rec1 = mime
          ? new window.MediaRecorder(recStream, { mimeType: mime })
          : new window.MediaRecorder(recStream);
      } catch (e) {
        clearRec();
        toast('No se pudo iniciar la grabación', 'err');
        return;
      }
      recorder = rec1;
      recChunks = [];
      rec1.ondataavailable = function (e) {
        if (e.data && e.data.size) recChunks.push(e.data);
      };
      rec1.onstop = function () {
        const blob = new Blob(recChunks, { type: rec1.mimeType || 'audio/webm' });
        const doSend = recSend;
        const chatId = store.activeChatId;
        const durBefore = recSecs.value;   // ANTES de clearRec (lo reinicia)
        /* W13: onda — downsample a ≤96 picos (0..100), ANTES de clearRec */
        let peaks = null;
        if (recPeaks.length) {
          const N = Math.min(96, recPeaks.length);
          const step = recPeaks.length / N;
          peaks = [];
          for (let i = 0; i < N; i++) {
            const a = Math.floor(i * step);
            const b = Math.max(a + 1, Math.floor((i + 1) * step));
            let s = 0;
            for (let j = a; j < b && j < recPeaks.length; j++) if (recPeaks[j] > s) s = recPeaks[j];
            peaks.push(s);
          }
        }
        clearRec();
        if (doSend && blob.size) {
          const f = new File([blob], 'nota-de-voz.webm', { type: blob.type || 'audio/webm' });
          stick.value = true;
          /* dur = segundos grabados (el WebM no los trae en el header) */
          const durSecs = Math.max(1, Math.round(durBefore));
          /* W29d: la nota de voz también respeta el interruptor. */
          const spoV = spoilNext.value;
          sendMedia(chatId, f, 'voice', null, null, peaks, durSecs,
            { spoiler: spoV })
            .catch(function () { /* toast ya mostrado */ });
          if (spoV) spoilNext.value = false;
        }
      };
      try {
        rec1.start(250);
      } catch (e) {
        clearRec();
        toast('No se pudo iniciar la grabación', 'err');
        return;
      }
      rec.value = 'on';
      recSecs.value = 0;
      recTimer = setInterval(function () {
        recSecs.value++;
        if (recSecs.value >= 300) stopRec(true);   // tope 5 min
      }, 1000);
    };

    const stopRec = function (sendIt) {
      if (!recorder) return;
      recSend = !!sendIt;
      if (recorder.state === 'inactive') { clearRec(); return; }
      try { recorder.stop(); } catch (e) { clearRec(); }
    };

    /* ---------- entrada ---------- */

    const send = async function () {
      const text = shortcodesToEmoji(draft.value);   // W17: :fire: → 🔥
      /* W23: con adjunto, el texto (aunque sea vacío) viaja como mensaje */
      if (att.value) { await sendAtt(text.trim() ? text : ''); return; }
      if (!text.trim()) return;
      const src = replyTo.value;
      const spo = spoilNext.value || spoilOnce;   // W29d/h: interruptor o long-press
      spoilOnce = false;
      draft.value = '';
      replyTo.value = null;
      store.emoOpen = false;                  // W7: se cierra al enviar
      clearAc();
      mOpen.value = false;                    // W28b
      if (input.value) input.value.style.height = 'auto';
      stick.value = true;
      try {
        await sendText(store.activeChatId, text, src, undefined, { spoiler: spo });
        /* W29d: el spoiler marca UN mensaje; suelto el interruptor. */
        if (spo && !att.value && !draft.value.trim()) spoilNext.value = false;
      } catch (e) {
        if (!draft.value) { draft.value = text; replyTo.value = src; }   // devolver texto y respuesta
      }
    };

    const onInput = function (e) {
      const el = e.target;
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 120) + 'px';
      notifyTyping(store.activeChatId);
      updAc();                                  // W17: :código: → emoji
    };

    const onAttach = async function (e) {
      const files = e.target.files ? Array.prototype.slice.call(e.target.files) : [];
      e.target.value = '';
      pickFiles(files);
    };

    /* ---------- W11/W23: adjuntar (ficha con datos + texto del compositor) ---------- */

    const att = Vue.ref(null);   // {file, thumb} antes de enviar

    /* Ficha: nombre con extensión, tipo y tamaño. */
    const attName = Vue.computed(function () {
      return (att.value && att.value.file.name) || t('Archivo');
    });
    const attType = Vue.computed(function () {
      const mime = (att.value && att.value.file.type) || '';
      if (/^image\//.test(mime)) return t('Imagen');
      if (/^video\//.test(mime)) return t('Video');
      return t('Archivo');
    });
    const attSize = Vue.computed(function () {
      return att.value ? fmtSize(att.value.file.size || 0) : '';
    });

    const cancelAtt = function () {
      const a = att.value;
      att.value = null;
      spoilNext.value = false;   /* W29g: el interruptor vive con el adjunto */
      if (a && a.thumb) { try { URL.revokeObjectURL(a.thumb); } catch (e) {} }
    };

    const sendAtt = async function (cap) {
      const a = att.value;
      if (!a) return;
      const src = replyTo.value;
      /* W23: el mensaje se escribe en el compositor (puede venir vacío) */
      const body = typeof cap === 'string' ? cap : draft.value;
      /* W29d/h: el interruptor (o el long-press) marca este adjunto. */
      const spo = spoilNext.value || spoilOnce;
      spoilOnce = false;
      replyTo.value = null;
      att.value = null;
      stick.value = true;
      if (a.thumb) { try { URL.revokeObjectURL(a.thumb); } catch (e) {} }
      draft.value = '';
      store.emoOpen = false;                  // W7: se cierra al enviar
      clearAc();
      mOpen.value = false;                    // W28b
      if (input.value) input.value.style.height = 'auto';
      try {
        await sendMedia(store.activeChatId, a.file, null, src, body,
          null, null, { spoiler: spo });
        if (spo && !draft.value.trim()) spoilNext.value = false;
      } catch (err) {
        /* la burbuja queda con su reintento; el interruptor se suelta
           para que el próximo adjunto no salga spoiler sin querer (W29g) */
        spoilNext.value = false;
      }
    };

    /* Una imagen/video sola abre la ficha (W23: el texto va en el
       compositor); el resto se manda de una. También entra por Ctrl+V
       y por arrastrar y soltar. */
    const pickFiles = function (files) {
      if (!files || !files.length || !store.activeChatId) return;
      for (let i = 0; i < files.length; i++) {
        if (!files[i].size) {
          /* W29a: un archivo vacío no se adjunta ni se envía. */
          toast(t('El archivo está vacío'), 'err');
          return;
        }
        if (files[i].size > 15 * 1024 * 1024) {
          toast(t('Máximo 15 MB por archivo'), 'err');
          return;
        }
      }
      if (files.length === 1 && /^(image|video)\//.test(files[0].type || '')) {
        cancelAtt();
        const f = files[0];
        att.value = {
          file: f,
          thumb: (/^image\//.test(f.type || '') && window.URL && URL.createObjectURL)
            ? URL.createObjectURL(f) : '',
        };
        /* W23: el foco queda en el compositor: Enter envía ya mismo */
        Vue.nextTick(function () {
          if (input.value) input.value.focus();
        });
        return;
      }
      const src = replyTo.value;
      const spo = spoilNext.value;   // W29d
      replyTo.value = null;
      stick.value = true;
      for (let j = 0; j < files.length; j++) {
        sendMedia(store.activeChatId, files[j], null, src, null, null, null,
          { spoiler: spo }).catch(function () {});
      }
      if (spo && !draft.value.trim()) spoilNext.value = false;
    };

    /* Ctrl+V: pegar una imagen (o lo que traiga el portapapeles como archivo) */
    const onPasteEv = function (e) {
      const cd = e.clipboardData;
      if (!cd || !cd.items) return;
      const files = [];
      for (let i = 0; i < cd.items.length; i++) {
        if (cd.items[i].kind === 'file') {
          const f = cd.items[i].getAsFile();
          if (f) files.push(f);
        }
      }
      if (files.length) { e.preventDefault(); pickFiles(files); }
    };

    /* Arrastrar y soltar archivos sobre la conversación */
    const dropping = Vue.ref(false);

    const onDragOver = function (e) {
      const dt = e.dataTransfer;
      if (!dt || !dt.types) return;
      for (let i = 0; i < dt.types.length; i++) {
        if (dt.types[i] === 'Files') {
          e.preventDefault();
          dropping.value = true;
          return;
        }
      }
    };

    const onDragLeave = function (e) {
      const cur = e.currentTarget;
      if (!e.relatedTarget || !cur || !cur.contains || !cur.contains(e.relatedTarget)) {
        dropping.value = false;
      }
    };

    const onDropEv = function (e) {
      const dt = e.dataTransfer;
      if (!dt || !dt.files || !dt.files.length) return;
      e.preventDefault();
      dropping.value = false;
      pickFiles(Array.prototype.slice.call(dt.files));
    };

    /* W11: cancelar/reintentar la subida desde la burbuja */
    const onUpCancel = function (row) {
      cancelUpload(store.activeChatId, row.client_msg_id);
    };
    const onUpRetry = function (row) {
      retryUpload(store.activeChatId, row.client_msg_id);
    };

    /* ---------- ciclo de vida ---------- */

    /* W38: la fase "Cargando vista previas…" precarga las fotos de la
       lista (avatares + la última imagen de cada chat + perfiles);
       las ondas de audio ya vienen con el último mensaje. Acotado: 40
       imágenes y tope de 3 s (la app no se queda esperando red lenta). */
    const warmPreviews = function () {
      const urls = [];
      const seen = {};
      const push = function (u) {
        if (u && !seen[u] && urls.length < 40) { seen[u] = 1; urls.push(u); }
      };
      const list = store.chats || [];
      for (let i = 0; i < list.length; i++) {
        const c = list[i];
        push(c.type === 'dm' ? (c.title && c.title.avatar_url) : c.avatar_url);
        const lm = c.last_message;
        if (lm && lm.media && (lm.media.mime || '').indexOf('image/') === 0) {
          push(lm.media.url);
        }
      }
      const ppl = store.people || {};
      const groups = [ppl.friends, ppl.sent, ppl.received];
      for (let g = 0; g < groups.length; g++) {
        const arr = groups[g] || [];
        for (let i = 0; i < arr.length; i++) push(arr[i] && arr[i].avatar_url);
      }
      const loads = urls.map(function (u) {
        return new Promise(function (res) {
          const im = new Image();
          im.onload = im.onerror = function () { res(); };
          im.src = mediaUrl(u);
        });
      });
      return Promise.race([
        Promise.all(loads),
        new Promise(function (r) { setTimeout(r, 3000); }),
      ]);
    };

    /* W27h: arranque de la interfaz — la pantalla de carga (W38) muestra
       cada fase real: chats ("Cargando los mensajes…"), gente/bloques
       ("Cargando usuarios…"), fotos de la lista ("Cargando vista
       previas…") y, si la URL pide un chat, sus mensajes: la app se
       revela completa de una vez. */
    const bootAll = async function () {
      try {
        store.bootPhase = 'chats';
        await loadChats();
        resolvePendingChat();   // por si la lista ya existía (reentrada)
        store.bootPhase = 'people';
        await Promise.all([loadPeople(), loadBlocks()]);
        store.bootPhase = 'previews';
        await warmPreviews();
        store.bootPhase = 'ready';
        if (store.activeChatId && !store.loaded[store.activeChatId]) {
          await openChat(store.activeChatId, true);
        }
      } finally {
        store.booting = false;
      }
    };

    Vue.onMounted(function () {
      startWS();
      bootAll();       // W27h: chats + gente + mensajes del deep link
      initInfoPanel();                            // W7: info por defecto si hay lugar
      /* W55: en el APK pedimos una vez el permiso de avisos de Android.
         Si el usuario lo niega, Ajustes → Chat permite reintentarlo. */
      try {
        const an = window.FoxinixAndroid;
        if (an && typeof an.requestPermission === 'function' &&
            an.permission() === 'prompt' &&
            localStorage.getItem('fm.nativeNotifAsked') !== '1') {
          localStorage.setItem('fm.nativeNotifAsked', '1');
          setTimeout(function () {
            try { an.requestPermission(); } catch (e) {}
          }, 1500);
        }
      } catch (e) {}
      document.addEventListener('click', onDocClick);
      window.addEventListener('keydown', onEsc);
      /* W54d: teclado de Android (resize del WebView o viewport visual) */
      window.addEventListener('resize', onKeyboardViewport);
      if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', onKeyboardViewport);
      }
      /* W11: pegar (Ctrl+V) + arrastrar y soltar archivos */
      document.addEventListener('paste', onPasteEv);
      const root = rootEl.value;
      if (root) {
        root.addEventListener('dragover', onDragOver);
        root.addEventListener('dragleave', onDragLeave);
        root.addEventListener('drop', onDropEv);
      }
      if (store.activeChatId) {
        Vue.nextTick(function () { scrollBottom(); });
      }
    });

    Vue.onUnmounted(function () {
      if (rec.value === 'on') stopRec(false);
      clearRec();
      stopWS();
      window.removeEventListener('resize', onPickResize);   // W29g
      window.removeEventListener('resize', onKeyboardViewport);
      if (window.visualViewport) {
        window.visualViewport.removeEventListener('resize', onKeyboardViewport);
      }
      document.removeEventListener('click', onDocClick);
      window.removeEventListener('keydown', onEsc);
      document.removeEventListener('paste', onPasteEv);
      const root = rootEl.value;
      if (root) {
        root.removeEventListener('dragover', onDragOver);
        root.removeEventListener('dragleave', onDragLeave);
        root.removeEventListener('drop', onDropEv);
      }
      cancelAtt();                                 // W11: suelta la miniatura
      store.activeChatId = 0;
      store.search = '';
      store.newChatOpen = false;
      store.newChatMode = 'dm';
      /* W6: ningún panel/ajuste sobrevive a la pantalla */
      store.profile = null;
      store.settingsOpen = false;
      store.settingsTab = 'apariencia';
      store.meProfileOpen = false;
      store.confirmBox = null;
      /* W7 */
      store.infoOpen = false;
      store.info = null;
      store.ctx = null;
      store.reactFor = 0;
      /* W8 */
      store.pwOpen = false;
      store.emOpen = false;
      store.editFor = 0;
      store.editDraft = '';
      closeLb();
    });

    const startNewChat = function () {
      store.newChatMode = 'dm';
      store.newChatOpen = true;
    };

    /* "+" del header del grupo: agregar miembros al grupo activo. */
    const openAddMember = function () {
      store.newChatMode = 'add';
      store.newChatOpen = true;
    };

    const wsLabel = Vue.computed(function () {
      return store.ws === 'connecting' ? t('Conectando…') : t('Sin conexión');
    });

    /* ---------- W6: panel de usuario, perfil, ajustes ---------- */

    const myStatusLine = Vue.computed(function () {
      /* W36d: sin conexión (WS caído) el pie muestra "Desconectado",
         sin importar el estado de perfil guardado. */
      if (store.ws !== 'on') return t('Desconectado');
      const u = store.user;
      if (!u) return '';
      if (u.status_text) return u.status_text;
      if (u.status_preset) return presetLabel(u.status_preset);
      return '@' + u.username;
    });

    const openSettings = function (tab) {
      /* W8: sin pestaña fija, abre en la última vista (default: la primera). */
      if (tab) store.settingsTab = tab;
      store.settingsOpen = true;
    };

    /* Perfil de otro usuario: openProfile() es de nivel módulo (lo usan
       también la cabecera, el menú contextual y el panel de info). */

    /* ---------- W7: info del chat, menús contextuales, emojis ---------- */

    /* W29g: UN solo panel de emojis con 3 pestañas (Emojis/Stickers/
       GIFs); pickTab elige el cuerpo y el clamp lo hace el padre. */
    const pickEl = Vue.ref(null);
    const pickTab = Vue.ref('emo');
    const setPickTab = function (id) {
      pickTab.value = id;
      /* W36k: abrir la pestaña GIFs trae los favoritos (una sola vez) */
      if (id === 'gif') ensureGifFavs();
      if (pickEl.value) {
        Vue.nextTick(function () { clampPanel(pickEl.value, true); });
      }
    };
    const onPickResize = function () {
      if (store.emoOpen && pickEl.value) clampPanel(pickEl.value, false);
    };
    window.addEventListener('resize', onPickResize);
    /* W17: el selector de emojis vive en store.emoOpen (compartido). */
    const toggleEmo = function () {
      const on = !store.emoOpen;
      store.ctx = null;          // un solo panel flotante a la vez
      store.reactFor = 0;
      store.emoOpen = on;
      if (on) {
        pickTab.value = 'emo';   // al abrir, muestra los emojis
        clearAc();
        Vue.nextTick(function () { clampPanel(pickEl.value, true); });
      }
    };
    const onSticker = function (ch) {
      store.emoOpen = false;
      sendText(store.activeChatId, ch, null, 'sticker').catch(function () {});
    };
    const onGif = function (name) {
      store.emoOpen = false;
      sendGif(store.activeChatId, name);
    };

    /* W36k: enviar un GIF favorito (los subidos ya viven en el server:
       sólo se referencia su media_id) y quitarlo de la lista. */
    const onGifFav = function (f) {
      store.emoOpen = false;
      if (!f.media_id) { onGif(f.name); return; }
      api('POST', '/api/chats/' + store.activeChatId + '/messages',
        { kind: 'image', body: '', media_id: f.media_id,
          client_msg_id: String(Date.now()) }).catch(function () {
        toast('No se pudo enviar el GIF', 'err');
      });
    };
    const onFavDel = function (f) {
      const body = f.media_id ? { media_id: f.media_id } : { name: f.name };
      api('DELETE', '/api/gifs/favorites', body).then(function () {
        store.gifFavs = store.gifFavs.filter(function (x) {
          return f.media_id ? x.media_id !== f.media_id : x.name !== f.name;
        });
      }).catch(function () { toast('No se pudo quitar el favorito', 'err'); });
    };
    const favGifSrc = function (f) {
      /* los de la biblioteca son estáticos; los subidos llevan firma
         que se refresca en cada listado */
      return f.media_id ? mediaUrl(f.url) : f.url;
    };

    /* W29h: mantener ENVIAR presionado 3 s → el mensaje sale como
       spoiler (con relleno de progreso); si se suelta antes, es el
       clic normal de siempre. */
    const clickSend = function () {
      if (holdFired) { holdFired = false; return; }  // ya disparó el hold
      send();
    };
    const holdUp = function () {
      if (holdTimer) { clearTimeout(holdTimer); holdTimer = 0; }
      holdOn.value = false;
    };
    const holdDown = function (e) {
      if (holdTimer || holdOn.value) return;
      if (e && e.button) return;                    // sólo botón principal
      if (!draft.value.trim() && !att.value) return;
      if (spoilNext.value) return;                  // ya armado por el interruptor
      holdFired = false;
      holdOn.value = true;
      holdTimer = setTimeout(function () {
        holdTimer = 0;
        holdOn.value = false;
        holdFired = true;
        spoilOnce = true;
        toast(t('Enviado como spoiler'));
        send();
      }, 3000);
    };

    /* W17: autocompletado ":fire" → 🔥 en la caja de escritura. Al
       escribir ':' se arma la lista desde los códigos de emoji.js;
       Tab/Enter/flechas eligen y al enviar ":código:" se convierte. */
    const acEl = Vue.ref(null);
    const acList = Vue.ref([]);
    const acIdx = Vue.ref(0);
    const acTok = Vue.ref(null);     // {s, e, word} sobre el borrador

    const clearAc = function () {
      acList.value = [];
      acTok.value = null;
      acIdx.value = 0;
    };
    const updAc = function () {
      mScan();                                   // W28b: también sigue el @
      const el = input.value;
      const cur = draft.value || '';
      let pos = cur.length;
      if (el && typeof el.selectionStart === 'number') pos = el.selectionStart;
      const before = cur.slice(0, pos);
      const m = before.match(/:([A-Za-z0-9_+-]{1,40})$/);
      if (!m) { clearAc(); return; }
      const list = emojiCodesPrefix(m[1].toLowerCase(), 8);
      if (!list.length) { clearAc(); return; }
      acTok.value = { s: pos - m[0].length, e: pos, word: m[1] };
      acList.value = list;
      if (acIdx.value >= list.length) acIdx.value = 0;
    };
    const pickAc = function (i) {
      const tok = acTok.value;
      const it = acList.value[i];
      if (!tok || !it) return;
      const cur = draft.value || '';
      draft.value = cur.slice(0, tok.s) + it.ch + cur.slice(tok.e);
      clearAc();
      Vue.nextTick(function () {
        if (!input.value) return;
        input.value.focus();
        const pos = tok.s + it.ch.length;
        try {
          input.value.selectionStart = pos;
          input.value.selectionEnd = pos;
        } catch (err) { /* sin selección */ }
        onInput({ target: input.value });
      });
    };
    /* W28b: autocompletado de @menciones en grupos (misma idea que el
       de :código: — Tab/Enter eligen, Esc cierra; el popup vive en el
       composer). La lista sale del panel de info del chat. */
    const mOpen = Vue.ref(false);
    const mIdx = Vue.ref(0);
    const mStart = Vue.ref(0);   // índice del '@' en el draft
    const mQ = Vue.ref('');      // letras escritas tras el '@'
    const isGroupChat = Vue.computed(function () {
      const c = activeChat.value;
      return !!(c && c.type === 'group');
    });
    const mList = Vue.computed(function () {
      if (!mOpen.value || !isGroupChat.value) return [];
      const inf = store.info;
      if (!inf || inf.chatId !== store.activeChatId) return [];
      const q = mQ.value.toLowerCase();
      const out = (inf.members || []).filter(function (u) {
        return u.username &&
          (!q || u.username.toLowerCase().indexOf(q) >= 0);
      });
      return out.slice(0, 6);
    });
    const mScan = function () {
      const el = input.value;
      if (!el || !isGroupChat.value) { mOpen.value = false; return; }
      const pos = typeof el.selectionStart === 'number'
        ? el.selectionStart : (el.value || '').length;
      const before = (el.value || '').slice(0, pos);
      const mm = before.match(/(?:^|[\s(])@([A-Za-z0-9_.]*)$/);
      if (!mm) { mOpen.value = false; return; }
      mStart.value = pos - mm[1].length - 1;
      mQ.value = mm[1];
      mIdx.value = 0;
      mOpen.value = true;
    };
    const mPick = function (u) {
      const el = input.value;
      if (!el || !u) return;
      const v = el.value || '';
      const caret = typeof el.selectionStart === 'number'
        ? el.selectionStart : v.length;
      const ins = '@' + u.username + ' ';
      draft.value = v.slice(0, mStart.value) + ins + v.slice(caret);
      mOpen.value = false;
      Vue.nextTick(function () {
        const p = mStart.value + ins.length;
        el.focus();
        try {
          el.selectionStart = p;
          el.selectionEnd = p;
        } catch (err) { /* sin selección */ }
      });
    };

    /* El popup se reclampea al área de mensajes (mismo truco que los
       chips; clampPanel mide la caja real de .msgs). */
    const onAcResize = function () {
      if (!acList.value.length) return;
      Vue.nextTick(function () { clampPanel(acEl.value, false); });
    };
    Vue.watch(acList, onAcResize);

    /* Puntito propio del side-head y del panel de usuario. */
    const myDot = Vue.computed(function () {
      return dotClass(store.user, store.ws === 'on');
    });

    /* Cabecera de la conversación: en directos abre el perfil del
       contacto; en grupos, alterna el panel de info. */
    const headDotClass = Vue.computed(function () {
      const c = activeChat.value;
      const d = dotClass(c && c.type === 'dm' ? c.title : null);
      d.clickable = true;
      return d;
    });
    const headTitle = Vue.computed(function () {
      const c = activeChat.value;
      return c && c.type === 'dm' ? t('Ver perfil') : t('Info del chat');
    });
    const onHeadClick = function () {
      const c = activeChat.value;
      if (!c) return;
      if (c.type === 'dm') openPeerProfile();
      else toggleInfo();
    };

    const toggleInfo = function () {
      store.infoOpen = !store.infoOpen;
      if (store.infoOpen && store.activeChatId) loadMembers(store.activeChatId);
    };

    /* El panel derecho queda abierto por defecto si hay lugar (W7). */
    const initInfoPanel = function () {
      store.infoOpen = window.innerWidth > 1100;
    };

    /* W19: sidebar colapsable (solo escritorio; en móvil manda el
       layout de pantalla completa y el botón queda oculto). */
    const toggleSide = function () { setSideCollapsed(!store.sideCollapsed); };
    const unfoldSide = function () { setSideCollapsed(false); };

    /* W27c: la opción "Personas" vive en el PANEL DE CHATS (sidebar),
       arriba de la lista. En escritorio lleva al centro (y cierra el
       chat si hay uno abierto); en móvil va a pantalla completa. Siempre
       vuelve a la pantalla principal (pestaña Activos). */
    const isNarrow = Vue.ref(window.innerWidth <= 760);
    const onResizeW = function () {
      isNarrow.value = window.innerWidth <= 760;
    };
    window.addEventListener('resize', onResizeW);
    Vue.onUnmounted(function () {
      window.removeEventListener('resize', onResizeW);
    });
    const peopleActive = Vue.computed(function () {
      return isNarrow.value ? !!store.peopleMobile : !store.activeChatId;
    });
    /* W29a: globo con las solicitudes de amistad recibidas (tope 9+). */
    const reqCount = Vue.computed(function () {
      const p = store.people;
      return (p && p.received) ? p.received.length : 0;
    });
    const goPeople = function () {
      store.settingsOpen = false;
      store.peopleTab = 'active';
      if (isNarrow.value) {
        if (store.activeChatId) closeChat();
        store.peopleMobile = true;
      } else if (store.activeChatId) {
        closeChat();
      }
    };
    const closePeople = function () { store.peopleMobile = false; };

    /* W54: navegación móvil. En el teléfono la app usa una barra inferior
       (Chats / Personas / Ajustes) en vez de la fila "Personas" y el panel
       de usuario del sidebar de escritorio. */
    const mobileChats = function () {
      store.settingsOpen = false;
      store.peopleMobile = false;
      if (store.activeChatId) closeChat();
    };

    /* W54: en la cabecera del chat, en pantalla chica, las llamadas y
       "agregar miembros" viven en un menú ⋮ para no aplastar el nombre
       del chat. En escritorio siguen como botones directos. */
    const chatMore = function (e) {
      const c = activeChat.value;
      if (!c) return;
      const items = [];
      if (canCall.value) {
        items.push({
          label: 'Llamar', icon: 'i-phone',
          fn: function () { doCall(false); },
        });
        items.push({
          label: 'Videollamada', icon: 'i-video',
          fn: function () { doCall(true); },
        });
      }
      if (c.type === 'group') {
        items.push({
          label: 'Agregar miembros', icon: 'i-userplus',
          fn: function () { openAddMember(); },
        });
      }
      items.push({
        label: c.pinned ? 'Desfijar chat' : 'Fijar chat',
        icon: c.pinned ? 'i-x' : 'i-pin',
        fn: function () { setPinned(c.id, !c.pinned); },
      });
      items.push({
        label: c.muted ? 'Activar notificaciones' : 'Silenciar notificaciones',
        icon: c.muted ? 'i-bell' : 'i-bell-off',
        fn: function () { setMuted(c.id, !c.muted); },
      });
      openCtx(e, items, null, 'chat-more', ctxChatHead(c));
    };

    /* ---------- W13: buscar dentro del chat ---------- */

    const searchOpen = Vue.ref(false);
    const sQ = Vue.ref('');
    const sResults = Vue.ref([]);
    const sBusy = Vue.ref(false);
    const sErr = Vue.ref('');
    let sTimer = null;

    const toggleSearch = function () {
      searchOpen.value = !searchOpen.value;
      /* W37b: al abrir el modal, el cursor queda listo para escribir */
      if (searchOpen.value) {
        Vue.nextTick(function () {
          const el = document.querySelector('.search-modal input');
          if (el) el.focus();
        });
      }
      if (!searchOpen.value) {
        sQ.value = '';
        sResults.value = [];
        sErr.value = '';
      }
    };

    const runSearch = async function () {
      const q = sQ.value.trim();
      const cid = store.activeChatId;
      if (!q) { sResults.value = []; sErr.value = ''; return; }
      sBusy.value = true;
      sErr.value = '';
      try {
        const r = await api('GET',
          '/api/chats/' + cid + '/search?q=' + encodeURIComponent(q));
        /* respuesta tardía de un chat o búsqueda que ya no aplica */
        if (cid === store.activeChatId && q === sQ.value.trim()) {
          sResults.value = r.messages || [];
        }
      } catch (e) {
        sErr.value = (e && e.detail) || t('No se pudo buscar');
      } finally {
        sBusy.value = false;
      }
    };
    const onSearchInput = function () {
      if (sTimer) clearTimeout(sTimer);
      sTimer = setTimeout(runSearch, 300);
    };
    const sSnippet = function (m) {
      /* W45: defensa extra para servidores viejos que aún devolvían el
         cuerpo del spoiler en la búsqueda. */
      if (m.spoiler) return t('Spoiler');
      const b = (m.body || '').replace(/\s+/g, ' ').trim();
      return b.length > 90 ? b.slice(0, 90) + '…' : b;
    };
    const sTime = function (ts) {
      return fmtTime(new Date(ts * 1000));
    };
    const scrollToMsg = function (id) {
      const root = rootEl.value;
      const attempt = function (tries) {
        const el = root ? root.querySelector('.msg[data-mid="' + id + '"]') : null;
        if (el) {
          try { el.scrollIntoView({ block: 'center' }); } catch (e) { el.scrollIntoView(); }
          el.classList.add('flash');
          setTimeout(function () { el.classList.remove('flash'); }, 1800);
          return;
        }
        if (tries > 0) setTimeout(function () { attempt(tries - 1); }, 250);
      };
      attempt(6);
    };
    /* W22: el salto deja su permalink en la URL (?m=<id>) al final de
       jumpResult; tryJump es el camino inverso (URL → scroll) para
       deep links y para el botón atrás. */
    let lastJump = 0;
    const jumpResult = async function (m) {
      const cid = store.activeChatId;
      const arr = store.msgs[cid];
      let found = false;
      if (arr) {
        for (let i = 0; i < arr.length; i++) {
          if (arr[i].id === m.id) { found = true; break; }
        }
      }
      if (!found) {
        /* no está cargado: traer una ventana alrededor del resultado */
        try {
          const r = await api('GET', '/api/chats/' + cid +
            '/messages?before_seq=' + (m.seq + 1) + '&limit=50');
          mergeMessages(cid, r.messages || []);
        } catch (e) { return; }
      }
      lastJump = m.id;
      store.jumpMsg = m.id;
      store.infoOpen = false;   // el panel de info cede el lugar
      await Vue.nextTick();
      scrollToMsg(m.id);
    };
    /* W22: saltar a un mensaje por id (?m= de la URL). Si no está en lo
       cargado, pagina hacia atrás hasta encontrarlo (tope: 15 páginas). */
    const tryJump = async function (id) {
      if (!id) { lastJump = 0; return; }
      const cid = store.activeChatId;
      if (!cid || id === lastJump) return;
      if (!store.loaded[cid]) return;   // aún sin mensajes: lo retoma loaded
      lastJump = id;
      const find = function () {
        const arr = store.msgs[cid] || [];
        for (let i = 0; i < arr.length; i++) if (arr[i].id === id) return arr[i];
        return null;
      };
      let m = find();
      let tries = 0;
      while (!m && store.hasMore[cid] && tries < 15) {
        tries++;
        await loadOlder(cid);
        m = find();
      }
      if (!m) return;
      store.infoOpen = false;   // el panel de info cede el lugar
      await Vue.nextTick();
      scrollToMsg(m.id);
    };

    /* W22: la URL manda — el chat que pide la ruta (deep link o atrás)
       se abre al tener la lista; el ?m= salta cuando los mensajes
       están cargados. */
    Vue.watch(function () { return store.pendingPath; }, function () {
      resolvePendingChat();
    });
    Vue.watch(function () { return store.jumpMsg; }, function (v) {
      tryJump(v);
    });
    Vue.watch(function () { return store.loaded[store.activeChatId]; }, function (v) {
      if (v && store.jumpMsg) tryJump(store.jumpMsg);
    });

    /* ---------- W13: reenviar mensajes ---------- */

    const fwdFor = Vue.ref(null);   // {msg, src} mientras está el modal abierto
    const fwdQ = Vue.ref('');
    const fwdBusy = Vue.ref(false);

    const openForward = function (m) {
      fwdFor.value = { msg: m, src: store.activeChatId };
      fwdQ.value = '';
    };
    const fwdChats = Vue.computed(function () {
      const f = fwdFor.value;
      if (!f) return [];
      const q = fwdQ.value.trim().toLowerCase();
      return store.chats.filter(function (c) {
        if (c.id === f.src) return false;   // el chat origen no es destino
        if (!q) return true;
        return chatTitle(c).toLowerCase().indexOf(q) >= 0;
      });
    });
    const doForward = async function (targetId) {
      const f = fwdFor.value;
      if (!f || fwdBusy.value) return;
      fwdBusy.value = true;
      try {
        await forwardMessage(f.src, f.msg.id, targetId);
        fwdFor.value = null;
      } catch (e) { /* toast ya mostrado en actions */ }
      finally { fwdBusy.value = false; }
    };

    /* Menús contextuales: openCtx y chatMenu ahora son de módulo (los
       usan también el panel de info y la ventana de perfil). */
    /* W28a: enlace directo a un mensaje — la URL del chat + ?m=<id>
       (el salto a mensajes ya existía con store.jumpMsg). */
    const msgLink = function (m) {
      const chat = activeChat.value;
      if (!chat || !m) return '';
      let path;
      if (chat.type === 'dm' && chat.title && chat.title.id) {
        path = '/app/user/' + chat.title.id;
      } else {
        path = '/app/group/' + chat.id;
      }
      return location.origin + path + '?m=' + m.id;
    };

    /* W28a: doble clic en un mensaje = reacciona con tu emoji reciente
       (o 👍 si aún no usas ninguno). No cuenta sobre imagen/video/
       enlace: ahí el clic ya hace zoom o descarga. */
    const quickReact = function (ev, r) {
      const t = ev && ev.target;
      if (t && t.closest && t.closest('img, video, a')) return;
      const m = r && r.ref;
      if (!m || m.kind === 'system') return;
      const rec = emojiRecent();
      toggleReaction(store.activeChatId, m.id, rec.length ? rec[0] : '👍');
    };

    /* W28f: "Visto por" — carga la lista de lectores de un mensaje mío
       en un grupo y la abre en el modal ReadsBox. */
    const openReads = function (chatId, msgId) {
      store.readsBox = {
        chatId: chatId, msgId: msgId,
        rows: null, total: 0, loading: true, error: '',
      };
      api('GET', '/api/chats/' + chatId + '/messages/' + msgId + '/reads')
        .then(function (r) {
          if (store.readsBox && store.readsBox.msgId === msgId) {
            store.readsBox.rows = r.reads || [];
            store.readsBox.total = r.total || 0;
            store.readsBox.loading = false;
          }
        })
        .catch(function (e) {
          if (store.readsBox && store.readsBox.msgId === msgId) {
            store.readsBox.loading = false;
            store.readsBox.error = (e && e.detail) || 'No se pudo cargar';
          }
        });
    };

    const msgMenu = function (e, r) {
      const m = r && r.ref;
      if (!m || m.kind === 'system') return;
      const items = [
        { label: 'Responder', icon: 'i-reply', fn: function () { startReply(m); } },
        { label: 'Reaccionar', icon: 'i-smile', fn: function () { store.reactFor = m.id; } },
      ];
      /* W37b: copiar el texto DESCIFRADO (nunca el marcador E2E) */
      const cpTxt = (m._plain != null ? m._plain : m.body) || '';
      if (cpTxt) {
        items.push({
          label: 'Copiar texto', icon: 'i-copy',
          fn: function () { copyText(cpTxt); },
        });
      }
      /* W28a: enlace directo al mensaje */
      items.push({
        label: 'Copiar enlace al mensaje', icon: 'i-link',
        fn: function () { copyText(msgLink(m)); toast('Enlace copiado'); },
      });
      /* W28c: fijar el mensaje en la info del chat */
      items.push(m.pinned
        ? { label: 'Desfijar mensaje', icon: 'i-pin-off',
            fn: function () { togglePin(store.activeChatId, m.id, false); } }
        : { label: 'Fijar mensaje', icon: 'i-pin',
            fn: function () { togglePin(store.activeChatId, m.id, true); } });
      /* W13: reenviar a otro chat (menos los mensajes del sistema) */
      items.push({
        label: 'Reenviar…', icon: 'i-forward',
        fn: function () { openForward(m); },
      });
      /* W8: editar y eliminar sólo lo tuyo */
      if (r.mine) {
        /* W28f: quién leyó tu mensaje — solo en grupos */
        const cNow = activeChat.value;
        if (cNow && cNow.type === 'group') {
          items.push({
            label: 'Visto por', icon: 'i-eye',
            fn: function () { openReads(store.activeChatId, m.id); },
          });
        }
        if (m.kind === 'text' && !m.media) {
          items.push({
            label: 'Editar', icon: 'i-pencil',
            fn: function () {
              /* W32: texto descifrado al editar (nunca el marcador). */
              store.editFor = m.id;
              store.editDraft = (m._plain != null ? m._plain : m.body) || '';
            },
          });
        }
        items.push({
          label: 'Eliminar', icon: 'i-trash', danger: true,
          fn: function () { askDeleteMessage(store.activeChatId, m); },
        });
      }
      /* W36g: en grupos, los owner/admin también pueden eliminar
         mensajes de otros miembros (el server revalida el rol). */
      else {
        const cAdm = activeChat.value;
        if (cAdm && cAdm.type === 'group' &&
            (cAdm.my_role === 'owner' || cAdm.my_role === 'admin')) {
          items.push({
            label: 'Eliminar mensaje', icon: 'i-trash', danger: true,
            fn: function () { askDeleteMessage(store.activeChatId, m); },
          });
        }
      }
      /* W17: ancla a la burbuja (tanto clic derecho como el ⋯ hover).
         W36i: el mismo ⋯ alterna abrir/cerrar. */
      const tgt = e && e.target;
      const bubble = tgt && tgt.closest ? tgt.closest('.bubble') : null;
      openCtx(e, items, bubble, 'msg:' + m.id);
    };
    const runCtx = function (it) {
      store.ctx = null;
      if (it && it.fn) it.fn();
    };

    /* Clic en cualquier lado: cierra menú, selector de emojis del
       composer y chips de reacción (W17: los tres son "paneles
       flotantes" y solo puede haber uno abierto). El autocompletado
       :código: solo se cierra si el clic fue fuera del composer. */
    const onDocClick = function (e) {
      store.ctx = null;
      store.emoOpen = false;
      store.reactFor = 0;
      const tgt = e && e.target;
      if (!tgt || !tgt.closest || !tgt.closest('.comp-row')) clearAc();
    };

    /* Emojis en la caja de escritura (W7): inserta en la posición del
       cursor y devuelve el foco al textarea. */
    const insertEmoji = function (ch) {
      const el = input.value;
      const cur = draft.value;
      let s = cur.length;
      let t = cur.length;
      if (el && typeof el.selectionStart === 'number') {
        s = el.selectionStart;
        t = el.selectionEnd;
      }
      draft.value = cur.slice(0, s) + ch + cur.slice(t);
      Vue.nextTick(function () {
        if (!input.value) return;
        input.value.focus();
        const pos = s + ch.length;
        try {
          input.value.selectionStart = pos;
          input.value.selectionEnd = pos;
        } catch (err) { /* sin selección: se queda al final */ }
        onInput({ target: input.value });
      });
    };

    const openPeerProfile = function () {
      const c = activeChat.value;
      if (c && c.type === 'dm' && c.title && c.title.username) {
        openProfile(c.title.username);
      }
    };

    /* ---------- W8: vista previa de imágenes con zoom ---------- */
    /* W29l: el estado vive en el store para que el visor también se
       abra desde el modal "Archivos y medios" de la info. */
    const lb = Vue.computed(function () { return store.lb; });
    const lbScale = Vue.ref(1);
    const lbTx = Vue.ref(0);
    const lbTy = Vue.ref(0);
    const lbDragging = Vue.ref(false);
    let lbMoveOff = null;            // apaga el arrastre al cerrar

    const lbReset = function () {
      lbScale.value = 1;
      lbTx.value = 0;
      lbTy.value = 0;
    };
    const openLb = function (url) {
      store.lb = { url: url };
      lbReset();
    };
    const closeLb = function () {
      if (lbMoveOff) { lbMoveOff(); lbMoveOff = null; }
      store.lb = null;
    };
    /* W29l: si el visor lo abre el modal de la info, el zoom parte en 1x */
    Vue.watch(lb, function (v) { if (v) lbReset(); });
    const lbStyle = Vue.computed(function () {
      return {
        transform: 'translate(' + lbTx.value + 'px,' + lbTy.value + 'px)' +
          ' scale(' + lbScale.value + ')',
        cursor: lbDragging.value ? 'grabbing' : (lbScale.value > 1 ? 'grab' : 'zoom-in'),
      };
    });
    let lbMoved = false;            // W22: hubo arrastre → el clic NO zoom
    /* W54c: al ampliar, la imagen puede recorrer la pantalla pero nunca
       se pierde fuera de ella. El visor queda entre los controles. */
    const lbClamp = function () {
      if (lbScale.value <= 1) { lbTx.value = 0; lbTy.value = 0; return; }
      const img = document.querySelector('.lightbox .lb-img');
      if (!img) return;
      const rect = img.getBoundingClientRect();
      const baseW = rect.width / lbScale.value;
      const baseH = rect.height / lbScale.value;
      const maxX = Math.max(0, (baseW * lbScale.value - window.innerWidth) / 2 + 10);
      const maxY = Math.max(0, (baseH * lbScale.value - window.innerHeight) / 2 + 10);
      lbTx.value = Math.max(-maxX, Math.min(maxX, lbTx.value));
      lbTy.value = Math.max(-maxY, Math.min(maxY, lbTy.value));
    };
    const lbZoom = function () {
      /* clic sobre la imagen: alterna ajustado ↔ ampliado (2.5x).
         W22: si el clic cierra un arrastre no alterna (antes soltar el
         drag hacía zoom-out sin querer). */
      if (lbMoved) { lbMoved = false; return; }
      if (lbScale.value > 1) lbReset();
      else { lbScale.value = 2.5; lbClamp(); }
    };
    const lbWheel = function (e) {
      /* rueda/trackpad: zoom continuo entre 1x y 5x */
      const d = e.deltaY < 0 ? 0.25 : -0.25;
      lbScale.value = Math.max(1, Math.min(5, lbScale.value + d));
      if (lbScale.value === 1) lbReset();
      else lbClamp();
    };
    const lbDown = function (e) {
      /* arrastrar para recorrer la imagen ampliada */
      if (lbScale.value <= 1) return;
      e.preventDefault();
      const px = e.clientX, py = e.clientY;   // W22: umbral de arrastre
      lbMoved = false;
      const sx = e.clientX - lbTx.value;
      const sy = e.clientY - lbTy.value;
      lbDragging.value = true;
      const move = function (ev) {
        if (Math.abs(ev.clientX - px) > 4 || Math.abs(ev.clientY - py) > 4) {
          lbMoved = true;
        }
        lbTx.value = ev.clientX - sx;
        lbTy.value = ev.clientY - sy;
        lbClamp();
      };
      const up = function () {
        lbDragging.value = false;
        document.removeEventListener('mousemove', move);
        document.removeEventListener('mouseup', up);
        lbMoveOff = null;
      };
      document.addEventListener('mousemove', move);
      document.addEventListener('mouseup', up);
      lbMoveOff = up;
    };

    /* W54c: en el teléfono se amplía con dos dedos y se arrastra con
       uno; así el visor funciona como una galería táctil. */
    let lbTouches = null;
    const lbTouchStart = function (e) {
      const t = e.touches;
      if (t.length === 2) {
        const dx = t[0].clientX - t[1].clientX;
        const dy = t[0].clientY - t[1].clientY;
        lbTouches = {
          mode: 'pinch',
          dist: Math.max(1, Math.sqrt(dx * dx + dy * dy)),
          scale: lbScale.value,
          tx: lbTx.value, ty: lbTy.value,
          mx: (t[0].clientX + t[1].clientX) / 2,
          my: (t[0].clientY + t[1].clientY) / 2,
        };
      } else if (t.length === 1 && lbScale.value > 1) {
        lbTouches = {
          mode: 'pan',
          x: t[0].clientX, y: t[0].clientY,
          tx: lbTx.value, ty: lbTy.value,
        };
      } else {
        lbTouches = null;
      }
    };
    const lbTouchMove = function (e) {
      if (!lbTouches) return;
      const t = e.touches;
      if (lbTouches.mode === 'pinch' && t.length >= 2) {
        const dx = t[0].clientX - t[1].clientX;
        const dy = t[0].clientY - t[1].clientY;
        const dist = Math.max(1, Math.sqrt(dx * dx + dy * dy));
        const mx = (t[0].clientX + t[1].clientX) / 2;
        const my = (t[0].clientY + t[1].clientY) / 2;
        lbScale.value = Math.max(1, Math.min(5, lbTouches.scale * dist / lbTouches.dist));
        lbTx.value = lbTouches.tx + mx - lbTouches.mx;
        lbTy.value = lbTouches.ty + my - lbTouches.my;
        if (lbScale.value === 1) { lbTx.value = 0; lbTy.value = 0; }
        else lbClamp();
        lbMoved = true;
        if (e.cancelable) e.preventDefault();
      } else if (lbTouches.mode === 'pan' && t.length === 1) {
        lbTx.value = lbTouches.tx + t[0].clientX - lbTouches.x;
        lbTy.value = lbTouches.ty + t[0].clientY - lbTouches.y;
        lbClamp();
        lbMoved = true;
        if (e.cancelable) e.preventDefault();
      }
    };
    const lbTouchEnd = function (e) {
      const t = e.touches;
      if (!t.length) { lbTouches = null; return; }
      if (t.length === 1 && lbScale.value > 1) {
        lbTouches = {
          mode: 'pan',
          x: t[0].clientX, y: t[0].clientY,
          tx: lbTx.value, ty: lbTy.value,
        };
      } else {
        lbTouches = null;
      }
    };

    /* Guardar la edición en línea de un mensaje propio (W8). */
    const onSaveEdit = function (m, text) {
      editMessage(store.activeChatId, m.id, text).catch(function (err) {
        toast(err.message || 'No se pudo editar el mensaje', 'err');
      });
    };

    /* Enter / Shift+Enter / Ctrl+Enter según la preferencia del usuario.
       W17: con el autocompletado ':código:' abierto, Enter/Tab eligen
       el emoji (y ↑ ↓ recorren la lista) antes de enviar. */
    const onComposerKey = function (e) {
      if (mOpen.value && mList.value.length) { // W28b: popup de @menciones
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          mIdx.value = (mIdx.value + 1) % mList.value.length;
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          mIdx.value = (mIdx.value + mList.value.length - 1) % mList.value.length;
          return;
        }
        if (e.key === 'Tab' ||
            (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.shiftKey)) {
          e.preventDefault();
          mPick(mList.value[mIdx.value]);
          return;
        }
        if (e.key === 'Escape') { mOpen.value = false; return; }
      }
      if (acList.value.length) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          acIdx.value = (acIdx.value + 1) % acList.value.length;
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          acIdx.value = (acIdx.value + acList.value.length - 1) % acList.value.length;
          return;
        }
        if (e.key === 'Tab' ||
            (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.shiftKey)) {
          e.preventDefault();
          pickAc(acIdx.value);
          return;
        }
        if (e.key === 'Escape') { clearAc(); return; }
      }
      if (e.key !== 'Enter') return;
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        send();
        return;
      }
      if (e.shiftKey) return;            // salto de línea
      if (store.prefs.enter) {           // encendido: Enter envía
        e.preventDefault();
        send();
      }
      // apagado: Enter hace salto de línea; envía el botón o Ctrl+Enter
    };

    /* Esc cierra de arriba hacia abajo lo que esté encima (atajo documentado). */
    const onEsc = function (e) {
      if (e.key !== 'Escape') return;
      /* W18: el aviso anti-spam solo sale con su botón. */
      if (store.spamUntil > Date.now()) return;
      if (store.confirmBox) {
        if (!store.confirmBox.busy) store.confirmBox = null;
        return;
      }
      if (lb.value) { closeLb(); return; }                      // W8
      if (store.ctx) { store.ctx = null; return; }              // W7
      if (acList.value.length) { clearAc(); return; }           // W17
      if (store.emoOpen) { store.emoOpen = false; return; }     // W7/W29g
      if (fwdFor.value) { fwdFor.value = null; return; }        // W13
      if (searchOpen.value) { toggleSearch(); return; }         // W13
      if (store.sasOpen) { store.sasOpen = false; return; }     // W39
      if (store.meProfileOpen) { store.meProfileOpen = false; return; }
      if (store.pwOpen) { store.pwOpen = false; return; }       // W8
      if (store.emOpen) { store.emOpen = false; return; }       // W8
      if (store.settingsOpen) { store.settingsOpen = false; return; }
      if (store.wallPanelOpen) { store.wallPanelOpen = false; return; }  // W21c
      if (store.newChatOpen) { store.newChatOpen = false; return; }
      if (store.profile) { store.profile = null; return; }
      if (store.reactFor) { store.reactFor = 0; return; }       // W7
      if (store.editFor) { store.editFor = 0; store.editDraft = ''; return; }  // W8
      if (store.pinsModal) { store.pinsModal = false; return; }  // W29l
      if (store.galModal) { store.galModal = false; return; }    // W29l
      if (store.infoOpen) { store.infoOpen = false; return; }   // W7
      if (att.value) { cancelAtt(); return; }                   // W11
      if (replyTo.value) { replyTo.value = null; }
    };

    /* ---------- W28h: llamadas 1:1 ---------- */

    const canCall = Vue.computed(function () {
      const c = activeChat.value;
      if (!c || c.type !== 'dm' || store.call) return false;
      const peer = c.title;   // en un DM, title ES el brief del peer
      return !!(peer && peer.id) && (store.blocks || []).indexOf(peer.id) < 0;
    });
    const doCall = function (video) {
      const c = activeChat.value;
      if (c && c.type === 'dm') startCall(c, !!video);
    };

    return {
      store,
      scroller, input, fileInput, draft,
      rootEl,
      canCall, doCall,   /* W28h */
      /* W13 */
      searchOpen, sQ, sResults, sBusy, sErr,
      toggleSearch, onSearchInput, sSnippet, sTime, jumpResult,
      fwdFor, fwdQ, fwdBusy, fwdChats, doForward,
      filteredChats, listEmpty, activeChat, rows,
      chatLoading,   /* W27h */
      quickReact, msgLink,   /* W28a */
      mList, mIdx, mPick,    /* W28b: @menciones */
      typingActive, typingLabel, typingAvs, chatTyping,   /* W29c */
      peerOn, statusLine,
      avatarOf, initialsOf, previewText, listTime, titleOf: chatTitle,
      onScroll, send, onInput, onAttach, onImgLoad,
      keepComposerVisible,   /* W54d: teclado de Android */
      stick, scrollBottom,   /* W44: botón "ir hacia abajo" */
      replyTo, replySender, replyPreview, startReply, cancelReply, onReact,
      e2ePendBar,   /* W30d: aviso de cifrado pendiente */
      sasCode,      /* W39: modal del código de verificación */
      spoilNext,   /* W29d: spoiler del próximo mensaje */
      rec, recTime, startRec, stopRec, recWave, recBar,
      open: openChat, close: closeChat,
      toggleTheme, logout, startNewChat, openAddMember, mediaUrl, wsLabel,
      /* W6 */
      myStatusLine, openSettings, openProfile, openPeerProfile,
      onComposerKey, askLogout,
      /* W7 */
      myDot, headDotClass, headTitle, onHeadClick, toggleInfo,
      chatMenu, msgMenu, runCtx, dotClass,
      /* W27 */
      menuKey,
      emoOpen: Vue.computed(function () { return store.emoOpen; }),
      toggleEmo, insertEmoji,
      /* W29g: panel unificado con 3 pestañas (Emojis/Stickers/GIFs) */
      pickEl, pickTab, setPickTab, onSticker, onGif,
      /* W36a: los stickers se pintan con Twemoji del sitio */
      emoFile, emoSrc,
      /* W36k */
      onGifFav, onFavDel, favGifSrc, isLibGifFav, toggleLibGif,
      stkList: STICKERS, gifList: GIF_LIST,
      /* W29h: enviar manteniendo presionado 3 s = spoiler */
      holdOn, holdDown, holdUp, clickSend,
      /* W17: autocompletado :código: */
      acEl, acList, acIdx, pickAc, updAc,
      /* W8 */
      lb, lbStyle, openLb, closeLb, lbZoom, lbWheel, lbDown,
      lbTouchStart, lbTouchMove, lbTouchEnd,   /* W54c: pinza y arrastre */
      lbScale,   // W22: la ayuda (v-if) se va cuando hay zoom
      onSaveEdit,
      /* W11 */
      att, attName, attType, attSize, cancelAtt, sendAtt, dropping, onUpCancel, onUpRetry,
      /* W19: sidebar colapsable */
      toggleSide, unfoldSide,
      /* W27c: "Personas" en el panel de chats (sidebar) */
      goPeople, closePeople, peopleActive, reqCount,
      /* W54: barra inferior y menú ⋮ de la cabecera en móvil */
      mobileChats, chatMore,
    };
  },
  template:
    '<div class="app-shell" ref="rootEl" :class="{ \'show-chat\': !!store.activeChatId, \'show-people\': !!store.peopleMobile }">' +

      /* W20: el panel de fondo (si está abierto) ocupa el sitio del
         sidebar en desktop; en celular CSS lo convierte en hoja inferior */
      '<aside class="sidebar" v-if="!store.wallPanelOpen">' +
        '<header class="side-head">' +
          '<img class="side-logo side-logo-word" src="/static/logo.svg" alt="Foxinix" />' +
          '<img class="side-logo-mark" src="/static/icon.svg" alt="" />' +
          '<span class="side-title">{{ t(\'Chats\') }}</span>' +
          '<span class="ws-dot" v-if="store.ws !== \'on\'" :title="wsLabel"></span>' +
          '<button class="icon-btn side-new" type="button" :title="t(\'Nuevo chat\')" @click="startNewChat">' +
            '<svg class="ic"><use href="#i-plus"></use></svg>' +
          '</button>' +
          /* W54: perfil a mano en móvil (el panel de usuario de abajo se
             oculta para dejarle el lugar a la barra inferior). */
          '<button class="icon-btn mobile-me" type="button" :title="t(\'Tu perfil\')" ' +
            '@click="store.meProfileOpen = true">' +
            '<span class="avatar av30">' +
              '<img v-if="store.user && store.user.avatar_url" :src="mediaUrl(store.user.avatar_url)" alt="">' +
              '<span v-else>{{ store.user ? (store.user.display_name || store.user.username).charAt(0).toUpperCase() : \'?\' }}</span>' +
            '</span>' +
          '</button>' +
          /* W19: contraer el sidebar (el hamburger del chat lo devuelve).
             Va DESPUÉS del ＋: los tests (y el ojo) dan por sentado que el
             primer .icon-btn del header es "Nuevo chat". */
          '<button class="icon-btn side-fold" type="button" :title="t(\'Contraer menú\')" ' +
            '@click="toggleSide">' +
            '<svg class="ic"><use href="#i-fold"></use></svg>' +
          '</button>' +
        '</header>' +
        '<div class="side-search">' +
          '<div class="search-pill">' +
            '<svg class="ic ic-sm"><use href="#i-search"></use></svg>' +
            '<input v-model="store.search" :placeholder="t(\'Buscar chats y grupos\')" :aria-label="t(\'Buscar chats y grupos\')">' +
          '</div>' +
        '</div>' +
        /* W27c: opción "Personas" en el panel de chats, arriba de todos
           los usuarios: vuelve a la pantalla principal (centro en
           escritorio; a pantalla completa en móvil) */
        '<button class="side-people" type="button" :class="{ on: peopleActive }" ' +
          ':title="t(\'Personas\')" @click="goPeople">' +
          '<svg class="ic ic-sm"><use href="#i-users"></use></svg>' +
          '<span>{{ t(\'Personas\') }}</span>' +
          /* W29a: globo rojo con las solicitudes recibidas (tope 9+) */
          '<i class="side-badge" v-if="reqCount > 0">' +
            '{{ reqCount > 9 ? \'9+\' : reqCount }}</i>' +
        '</button>' +
        '<div class="chat-list">' +
          '<button class="chat-item" type="button" v-for="c in filteredChats" :key="c.id" ' +
            ':data-chat-id="c.id" ' +
            ':class="{ active: c.id === store.activeChatId }" @click="open(c.id)" ' +
            '@contextmenu.prevent="chatMenu($event, c)">' +
            '<span class="av-wrap" :class="dotClass(c.type === \'dm\' ? c.title : null)">' +
              '<span class="avatar">' +
                '<img v-if="avatarOf(c)" :src="avatarOf(c)" alt="" loading="lazy">' +
                '<span v-else>{{ initialsOf(c) }}</span>' +
              '</span>' +
            '</span>' +
            '<span class="ci-main">' +
              '<span class="ci-top"><span class="ci-name">{{ titleOf(c) }}</span>' +
              /* W13: fijado / silenciado */
              '<span class="ci-icons" v-if="c.pinned || c.muted">' +
                '<svg class="ic ic-sm" v-if="c.pinned" :title="t(\'Fijado\')"><use href="#i-pin"></use></svg>' +
                '<svg class="ic ic-sm" v-if="c.muted" :title="t(\'Silenciado\')"><use href="#i-bell-off"></use></svg>' +
              '</span>' +
              '<span class="ci-time">{{ listTime(c) }}</span></span>' +
              '<span class="ci-bot">' +
                /* W29c: pelotita de "escribiendo…" en la lista de chats */
                '<span class="ci-typing" v-if="chatTyping(c)" ' +
                  ':title="t(\'escribiendo…\')"><i></i><i></i><i></i></span>' +
                '<span class="ci-prev">{{ previewText(c) }}</span>' +
              /* W28b: contador aparte para los mensajes que me citan */
              '<span class="badge mention" v-if="c.unread_mentions">{{ c.unread_mentions > 99 ? \'99+\' : c.unread_mentions }}</span>' +
              '<span class="badge" :class="{ muted: c.muted }" v-if="c.unread">{{ c.unread > 99 ? \'99+\' : c.unread }}</span></span>' +
            '</span>' +
            /* W27: ⋮ administrar el chat (mismo menú del clic derecho) */
            '<span class="ci-menu" role="button" tabindex="0" :title="t(\'Administrar\')" ' +
              '@click.stop="chatMenu($event, c)" ' +
              '@keydown.enter.stop.prevent="menuKey($event, c)">' +
              '<svg class="ic ic-sm"><use href="#i-dots"></use></svg>' +
            '</span>' +
          '</button>' +
          '<div class="list-empty" v-if="listEmpty">' +
            '<template v-if="store.chats.length">{{ t(\'Sin resultados para “{n}”\', { n: store.search }) }}</template>' +
            '<template v-else>{{ t(\'Aún no tienes chats.\') }}<br>{{ t(\'Crea uno con el botón ＋.\') }}</template>' +
          '</div>' +
        '</div>' +
        /* panel de usuario (W6/W8): perfil abajo a la izquierda; la
           configuración vive SOLO en el engranaje (Ajustes). */
        '<div class="user-panel">' +
          '<button class="up-main" type="button" :title="t(\'Tu perfil\')" @click="store.meProfileOpen = true">' +
            '<span class="av-wrap" :class="myDot">' +
              '<span class="avatar av36">' +
                '<img v-if="store.user && store.user.avatar_url" :src="mediaUrl(store.user.avatar_url)" alt="">' +
                '<span v-else>{{ store.user ? (store.user.display_name || store.user.username).charAt(0).toUpperCase() : \'?\' }}</span>' +
              '</span>' +
            '</span>' +
            '<span class="up-col">' +
              '<span class="up-name">{{ store.user ? (store.user.display_name || store.user.username) : \'\' }}</span>' +
              '<span class="up-status">{{ myStatusLine }}</span>' +
            '</span>' +
          '</button>' +
          '<button class="icon-btn" type="button" :title="t(\'Ajustes\')" @click="openSettings()">' +
            '<svg class="ic"><use href="#i-gear"></use></svg>' +
          '</button>' +
        '</div>' +
      '</aside>' +
      '<wall-panel v-if="store.wallPanelOpen"></wall-panel>' +

      /* W21c: con el panel de fondo abierto, el centro muestra la
         vista previa a tamaño real (el chat vuelve al cerrar) */
      '<wall-preview v-if="store.wallPanelOpen"></wall-preview>' +
      '<main class="chat-pane" v-else-if="activeChat">' +
        '<header class="chat-head">' +
          /* W19: si el sidebar está contraído, el hamburger lo devuelve */
          '<button class="icon-btn side-open" type="button" :title="t(\'Mostrar chats\')" ' +
            '@click="unfoldSide">' +
            '<svg class="ic"><use href="#i-unfold"></use></svg>' +
          '</button>' +
          '<button class="icon-btn back" type="button" :title="t(\'Volver\')" @click="close">' +
            '<svg class="ic"><use href="#i-back"></use></svg>' +
          '</button>' +
          '<span class="av-wrap" :class="headDotClass" :title="headTitle" @click="onHeadClick">' +
            '<span class="avatar av36">' +
              '<img v-if="avatarOf(activeChat)" :src="avatarOf(activeChat)" alt="">' +
              '<span v-else>{{ initialsOf(activeChat) }}</span>' +
            '</span>' +
          '</span>' +
          '<span class="ch-col clickable" :title="headTitle" @click="onHeadClick">' +
            '<span class="ch-name">{{ titleOf(activeChat) }}</span>' +
            '<span class="ch-status" :class="{ typing: typingActive }">{{ statusLine }}</span>' +
          '</span>' +
          '<span class="ws-pill" v-if="store.ws !== \'on\'">{{ wsLabel }}</span>' +
          /* W13: buscar dentro del chat */
          '<button class="icon-btn" :class="{ on: searchOpen }" type="button" ' +
            ':title="t(\'Buscar en el chat\')" @click="toggleSearch">' +
            '<svg class="ic"><use href="#i-search"></use></svg>' +
          '</button>' +
          /* W28h: llamadas 1:1 (solo DM; si ya hay una, el .callbox manda) */
          '<button class="icon-btn call-action" v-if="canCall" type="button" ' +
            ':title="t(\'Llamar\')" @click="doCall(false)">' +
            '<svg class="ic"><use href="#i-phone"></use></svg>' +
          '</button>' +
          '<button class="icon-btn call-action" v-if="canCall" type="button" ' +
            ':title="t(\'Videollamada\')" @click="doCall(true)">' +
            '<svg class="ic"><use href="#i-video"></use></svg>' +
          '</button>' +
          /* W34b: "Agregar miembros" ocupa el primer slot de la derecha
             y la info del chat/usuario queda en el último (donde antes
             estaba el +). W36f: el icono lleva "+" (añadir personas). */
          '<button class="icon-btn add-member-action" v-if="activeChat.type === \'group\'" type="button" ' +
            ':title="t(\'Agregar miembros\')" @click="openAddMember">' +
            '<svg class="ic"><use href="#i-userplus"></use></svg>' +
          '</button>' +
          /* W54: en móvil estas acciones se juntan en un menú ⋮ para
             que el nombre del chat tenga espacio. */
          '<button class="icon-btn chat-more" type="button" ' +
            ':title="t(\'Más acciones\')" @click.stop="chatMore($event)">' +
            '<svg class="ic"><use href="#i-dots"></use></svg>' +
          '</button>' +
          /* W7: botón del panel derecho (info del chat / miembros) */
          '<button class="icon-btn" :class="{ on: store.infoOpen }" type="button" ' +
            ':title="store.infoOpen ? t(\'Ocultar info del chat\') : t(activeChat.type === \'dm\' ? \'Info del usuario\' : \'Info del chat\')" @click="toggleInfo">' +
            '<svg class="ic"><use href="#i-info"></use></svg>' +
          '</button>' +
        '</header>' +

        '<div class="msgs" ref="scroller" @scroll.passive="onScroll">' +
          /* W27h: "Cargando…" mientras se piden los mensajes del chat.
             W38: el spinner es la animación de cubitos. */
          '<div class="msgs-load" v-if="chatLoading">' +
            '<span class="cubes"><span class="cube"></span><span class="cube"></span></span>' +
            '<span>{{ t(\'Cargando…\') }}</span>' +
          '</div>' +
          '<div class="load-older" v-if="store.loadingOlder">{{ t(\'Cargando anteriores…\') }}</div>' +
          /* W39: la key es estable entre el pendiente y su ack (el
             id temporal NEGATIVO cambiaba por el del server → Vue
             recreaba el nodo y la animación de entrada se veía como
             "se borra y se reenvía"). Sin client_msg_id (mensajes de
             sistema) se usa el id. */
          '<template v-for="r in rows" :key="r.ref.client_msg_id || r.ref.id">' +
            '<div v-if="r.day" class="day-pill">{{ r.day }}</div>' +
            '<message-row :row="r" :data-mid="r.ref.id" @dblclick="quickReact($event, r)" ' +
              '@imgload="onImgLoad" @reply="startReply" ' +
              '@react="onReact" @openprofile="openProfile" ' +
              '@zoom="openLb" @saveedit="onSaveEdit" ' +
              '@upcancel="onUpCancel" @upretry="onUpRetry" ' +
              '@menu="msgMenu($event.ev, $event.row)" ' +
              '@contextmenu.prevent="msgMenu($event, r)"></message-row>' +
          '</template>' +
          '<transition name="typ">' +
          '<div class="msg theirs tight typ-row" v-if="typingActive" key="typing">' +
            '<span class="typ-avs" v-if="typingAvs.length">' +
              '<img v-for="(a, i) in typingAvs" :key="i" :src="a" alt="" loading="lazy">' +
            '</span>' +
            /* columna vacía: las burbujas del grupo quedan alineadas */
            '<span class="msg-av" v-else-if="activeChat && activeChat.type === \'group\'"></span>' +
            '<div class="bubble dots typing-line"><i></i><i></i><i></i>' +
              '<span class="typ-txt">{{ typingLabel }}</span></div>' +
          '</div>' +
          '</transition>' +
        '</div>' +

        /* W44: botón "ir hacia abajo" — aparece solo cuando el chat no
           está pegado al final (stick=false); el clic salta al final
           (scrollBottom) y onScroll lo esconde al llegar. */
        '<button class="jump-bottom" type="button" v-if="!stick" ' +
          ':title="t(\'Ir hacia abajo\')" @click="scrollBottom">' +
          '<svg class="ic"><use href="#i-chevron-down"></use></svg>' +
        '</button>' +

        '<footer class="composer">' +
          '<div class="reply-bar" v-if="replyTo">' +
            '<svg class="ic ic-sm rb-ic"><use href="#i-reply"></use></svg>' +
            '<span class="rb-col">' +
              '<b>{{ replySender }}</b>' +
              '<span>{{ replyPreview }}</span>' +
            '</span>' +
            '<button class="icon-btn" type="button" :title="t(\'Cancelar respuesta\')" @click="cancelReply">' +
              '<svg class="ic ic-sm"><use href="#i-x"></use></svg>' +
            '</button>' +
          '</div>' +
          /* W30d: aviso de cifrado pendiente (el par aún no publica) */
          '<div class="e2e-pend-bar" v-if="e2ePendBar">' +
            '<svg class="ic ic-sm"><use href="#i-info"></use></svg>' +
            '<span>{{ e2ePendBar }}</span>' +
          '</div>' +
          /* W23: ficha del archivo (nombre + tipo/tamaño); el texto del
             mensaje se escribe en el compositor de abajo */
          '<div class="cap-strip" v-if="att">' +
            '<img v-if="att.thumb" class="cs-thumb" :src="att.thumb" alt="">' +
            '<svg v-else class="ic cs-ic"><use href="#i-file"></use></svg>' +
            '<span class="cs-col">' +
              '<span class="cs-name">{{ attName }}</span>' +
              '<span class="cs-meta">' +
                '<span class="cs-type">{{ attType }}</span>' +
                '<span class="cs-size">{{ attSize }}</span>' +
              '</span>' +
            '</span>' +
            '<button class="icon-btn" type="button" :title="t(\'Quitar\')" @click="cancelAtt">' +
              '<svg class="ic ic-sm"><use href="#i-x"></use></svg>' +
            '</button>' +
          '</div>' +
          '<div class="comp-row" v-if="rec === \'off\'">' +
            '<label class="icon-btn" :title="t(\'Adjuntar archivo\')">' +
              '<svg class="ic"><use href="#i-clip"></use></svg>' +
              '<input type="file" hidden ref="fileInput" ' +
                'accept="image/*,video/*,.pdf,.txt,.zip,.doc,.docx,.xls,.xlsx" @change="onAttach">' +
            '</label>' +
            '<textarea class="composer-input" ref="input" rows="1" v-model="draft" ' +
              ':placeholder="t(\'Mensaje\')" @input="onInput" @click="updAc" ' +
              '@focus="keepComposerVisible" ' +
              '@keydown="onComposerKey" @keydown.esc="cancelReply"></textarea>' +
            /* W7: selector de emojis para escribir en el mensaje */
            '<button class="icon-btn comp-emo" :class="{ on: emoOpen }" type="button" ' +
              ':title="t(\'Emojis\')" @click.stop="toggleEmo">' +
              '<svg class="ic"><use href="#i-smile"></use></svg>' +
            '</button>' +
            /* W29d/g: "Mensaje Spoiler: On/Off" — SOLO con adjunto */
            '<button class="icon-btn comp-spoil" v-if="att" :class="{ on: spoilNext }" type="button" ' +
              ':title="t(\'Mensaje Spoiler\') + \': \' + (spoilNext ? \'On\' : \'Off\')" ' +
              '@click="spoilNext = !spoilNext">' +
              '<svg class="ic"><use href="#i-eye-off"></use></svg>' +
            '</button>' +
            '<button class="icon-btn comp-mic" v-if="!draft.trim() && !att" type="button" ' +
              ':title="t(\'Nota de voz\')" @click="startRec">' +
              '<svg class="ic"><use href="#i-mic"></use></svg>' +
            '</button>' +
            /* W29h: mantener 3 s → se envía como spoiler (relleno) */
            '<button class="send-btn" type="button" :class="{ holding: holdOn }" ' +
              ':title="t(\'Enviar\')" :disabled="!draft.trim() && !att" ' +
              '@click="clickSend" @pointerdown="holdDown" @pointerup="holdUp" ' +
              '@pointerleave="holdUp" @pointercancel="holdUp">' +
              '<span class="send-fill" aria-hidden="true"></span>' +
              '<svg class="ic"><use href="#i-send"></use></svg>' +
            '</button>' +
            /* W29g: un panel con 3 pestañas: Emojis / Stickers / GIFs.
               W36j: tamaño fijo (las 3 pestañas miden lo mismo) y sin
               animación de apertura: un "pasar página" al entrar y al
               cambiar de pestaña. W36k: pestaña GIFs con Favoritos. */
            '<div class="st-panel" ref="pickEl" v-if="emoOpen" @click.stop>' +
              '<div class="ep-tabs">' +
                '<button class="ep-tab" :class="{ on: pickTab === \'emo\' }" ' +
                  'type="button" @click="setPickTab(\'emo\')">{{ t(\'Emojis\') }}</button>' +
                '<button class="ep-tab" :class="{ on: pickTab === \'st\' }" ' +
                  'type="button" @click="setPickTab(\'st\')">{{ t(\'Stickers\') }}</button>' +
                '<button class="ep-tab" :class="{ on: pickTab === \'gif\' }" ' +
                  'type="button" @click="setPickTab(\'gif\')">{{ t(\'GIFs\') }}</button>' +
              '</div>' +
              '<transition name="pgflip" mode="out-in">' +
              '<emoji-picker v-if="pickTab === \'emo\'" key="emo" :embed="true" ' +
                '@pick="insertEmoji">' +
              '</emoji-picker>' +
              /* W36a: stickers con los emojis del sitio (Twemoji), no
                 los nativos del sistema */
              '<div class="st-grid" v-else-if="pickTab === \'st\'" key="st">' +
                '<button class="st-e" type="button" v-for="s in stkList" :key="s" ' +
                  '@click="onSticker(s)" :title="s">' +
                  '<img v-if="emoFile(s)" class="emo" :src="emoSrc(s)" :alt="s">' +
                  '<span v-else>{{ s }}</span></button>' +
              '</div>' +
              '<div class="st-body" v-else-if="pickTab === \'gif\'" key="gif">' +
                '<div class="st-sec" v-if="store.gifFavs.length">{{ t(\'Favoritos\') }}</div>' +
                '<div class="st-grid" v-if="store.gifFavs.length">' +
                  '<span class="st-g-wrap" v-for="f in store.gifFavs" ' +
                    ':key="f.media_id ? \'m\' + f.media_id : \'n\' + f.name">' +
                    '<button class="st-g" type="button" @click="onGifFav(f)" ' +
                      ':title="t(\'Enviar\')">' +
                      '<img :src="favGifSrc(f)" alt="" loading="lazy"></button>' +
                    '<button class="st-fav on" type="button" ' +
                      ':title="t(\'Quitar de favoritos\')" @click.stop="onFavDel(f)">' +
                      '<svg class="ic ic-sm"><use href="#i-star-fill"></use></svg></button>' +
                  '</span>' +
                '</div>' +
                '<div class="st-sec">{{ t(\'Biblioteca\') }}</div>' +
                '<div class="st-grid">' +
                  '<span class="st-g-wrap" v-for="g in gifList" :key="g">' +
                    '<button class="st-g" type="button" ' +
                      '@click="onGif(g)" :title="g">' +
                      '<img :src="\'/static/gifs/\' + g" alt="" loading="lazy">' +
                    '</button>' +
                    '<button class="st-fav" :class="{ on: isLibGifFav(g) }" ' +
                      'type="button" ' +
                      ':title="isLibGifFav(g) ? t(\'Quitar de favoritos\') : t(\'Agregar a favoritos\')" ' +
                      '@click.stop="toggleLibGif(g)">' +
                      '<svg class="ic ic-sm"><use :href="isLibGifFav(g) ? \'#i-star-fill\' : \'#i-star\'"></use></svg>' +
                    '</button>' +
                  '</span>' +
                '</div>' +
              '</div>' +
              '</transition>' +
            '</div>' +
            /* W17: autocompletado ":fire" → 🔥 (Tab/Enter/clic eligen) */
            '<div class="emo-ac" ref="acEl" v-if="acList.length" @click.stop>' +
              '<button class="emo-ac-row" :class="{ on: i === acIdx }" type="button" ' +
                'v-for="(m, i) in acList" :key="m.code" @click="pickAc(i)">' +
                '<b><img v-if="emoFile(m.ch)" class="emo" :src="emoSrc(m.ch)" ' +
                  ':alt="m.ch"><span v-else>{{ m.ch }}</span></b><i>:{{ m.code }}:</i>' +
              '</button>' +
            '</div>' +
            /* W28b: @menciones — flota igual que el de :código: */
            '<div class="m-mention" v-if="mList.length">' +
              '<button class="mm-row" type="button" v-for="(mu, i) in mList" ' +
                ':key="mu.id" :class="{ on: i === mIdx }" @click="mPick(mu)">' +
                '<span class="mm-at">@</span>' +
                '<b>{{ mu.username }}</b>' +
                '<span class="mm-disp" v-if="mu.display_name && mu.display_name !== mu.username">{{ mu.display_name }}</span>' +
              '</button>' +
            '</div>' +
          '</div>' +
          '<div class="comp-row rec-bar" v-else :aria-label="t(\'Grabando nota de voz…\')">' +
            '<span class="rec-dot"></span>' +
            '<span class="rec-time">{{ recTime }}</span>' +
            '<span class="rec-wave" :class="{ live: recWave.length }" aria-hidden="true">' +
              '<i v-for="i in 22" :key="i" :style="{ transform: \'scaleY(\' + recBar(i - 1) + \')\' }"></i>' +
            '</span>' +
            '<span class="rec-hint">{{ t(\'Grabando nota de voz…\') }}</span>' +
            '<button class="icon-btn" type="button" :title="t(\'Cancelar\')" @click="stopRec(false)">' +
              '<svg class="ic"><use href="#i-x"></use></svg>' +
            '</button>' +
            '<button class="send-btn rec-send" type="button" :title="t(\'Enviar nota de voz\')" @click="stopRec(true)">' +
              '<svg class="ic"><use href="#i-send"></use></svg>' +
            '</button>' +
          '</div>' +
        '</footer>' +
      '</main>' +

      /* W27: sin chat abierto, el centro muestra Personas (Activos +
         Solicitudes); la lista de chats vive siempre en el sidebar */
      '<main class="chat-pane people-pane" v-else>' +
        /* W54: título de pantalla en móvil (en escritorio Personas vive
           en el centro y no necesita app bar propia). */
        '<header class="mobile-page-head"><img class="mobile-page-logo" ' +
          'src="/static/icon.svg" alt=""><b>{{ t(\'Personas\') }}</b></header>' +
        /* W19: sin chat abierto también se puede devolver el sidebar */
        '<button class="icon-btn side-open" type="button" :title="t(\'Mostrar chats\')" ' +
          '@click="unfoldSide">' +
          '<svg class="ic"><use href="#i-unfold"></use></svg>' +
        '</button>' +
        /* W27b: en móvil (pantalla completa) el botón atrás vuelve a la
           lista de chats; en escritorio lo oculta el CSS (.back) */
        '<button class="icon-btn back ppl-back-btn" type="button" :title="t(\'Chats\')" ' +
          '@click="closePeople">' +
          '<svg class="ic"><use href="#i-back"></use></svg>' +
        '</button>' +
        '<people-panel></people-panel>' +
      '</main>' +

      /* W54: barra inferior estilo app. Solo con la lista o Personas a
         la vista: dentro de una conversación manda el chat a pantalla
         completa (se vuelve con la flecha). */
      '<nav class="mobile-tabs" v-if="!store.activeChatId && !store.wallPanelOpen && ' +
        '!store.meProfileOpen && !store.newChatOpen && !store.profile" ' +
        ':aria-label="t(\'Navegación principal\')">' +
        '<button class="mt-btn" type="button" :class="{ on: !store.peopleMobile && !store.settingsOpen }" ' +
          '@click="mobileChats">' +
          '<svg class="ic"><use href="#i-chat"></use></svg>' +
          '<span class="mt-label">{{ t(\'Chats\') }}</span>' +
        '</button>' +
        '<button class="mt-btn" type="button" :class="{ on: store.peopleMobile && !store.settingsOpen }" ' +
          '@click="goPeople">' +
          '<span class="mt-ic-wrap">' +
            '<svg class="ic"><use href="#i-users"></use></svg>' +
            '<i class="mt-badge" v-if="reqCount > 0">{{ reqCount > 9 ? \'9+\' : reqCount }}</i>' +
          '</span>' +
          '<span class="mt-label">{{ t(\'Personas\') }}</span>' +
        '</button>' +
        '<button class="mt-btn" type="button" :class="{ on: store.settingsOpen }" ' +
          '@click="openSettings()">' +
          '<svg class="ic"><use href="#i-gear"></use></svg>' +
          '<span class="mt-label">{{ t(\'Ajustes\') }}</span>' +
        '</button>' +
      '</nav>' +

      /* W37c: todos los modales animan apertura Y cierre (fade de la
         velada + scale del cuadro). */
      '<transition name="veil">' +
      '<new-chat-modal v-if="store.newChatOpen"></new-chat-modal>' +
      '</transition>' +
      '<transition name="veil">' +
      '<settings-modal v-if="store.settingsOpen"></settings-modal>' +
      '</transition>' +
      '<transition name="veil">' +
      '<me-profile-modal v-if="store.meProfileOpen"></me-profile-modal>' +
      '</transition>' +
      '<transition name="veil">' +
      '<me-profile-edit-modal v-if="store.meEditOpen"></me-profile-edit-modal>' +
      '</transition>' +
      '<transition name="veil">' +
      '<confirm-box v-if="store.confirmBox"></confirm-box>' +
      '</transition>' +
      /* W28f: lista de lectores de un mensaje propio en un grupo */
      '<transition name="veil">' +
      '<reads-box v-if="store.readsBox"></reads-box>' +
      '</transition>' +
      /* W28h: panel de llamada (entrante o en curso) */
      '<call-box v-if="store.call"></call-box>' +
      /* W18: aviso anti-spam (pantalla completa; solo el botón la cierra) */
      '<spam-box v-if="store.spamUntil > 0"></spam-box>' +
      /* W13: modal de reenvío (elegir chat destino) */
      '<transition name="veil">' +
      '<div class="modal-veil" v-if="fwdFor" @click.self="fwdFor = null">' +
        '<div class="modal fwd" role="dialog" :aria-label="t(\'Reenviar mensaje\')">' +
          '<header>{{ t(\'Reenviar mensaje\') }}' +
            '<button class="icon-btn" type="button" :title="t(\'Cerrar\')" @click="fwdFor = null">' +
              '<svg class="ic"><use href="#i-x"></use></svg>' +
            '</button>' +
          '</header>' +
          '<div class="m-search">' +
            '<svg class="ic ic-sm"><use href="#i-search"></use></svg>' +
            '<input v-model="fwdQ" :placeholder="t(\'Buscar en la lista…\')" ' +
              ':aria-label="t(\'Buscar en la lista…\')">' +
          '</div>' +
          '<div class="results fwd-list">' +
            '<button class="res-item" type="button" v-for="c in fwdChats" :key="c.id" ' +
              ':disabled="fwdBusy" @click="doForward(c.id)">' +
              '<span class="avatar av36">' +
                '<img v-if="avatarOf(c)" :src="avatarOf(c)" alt="" loading="lazy">' +
                '<span v-else>{{ initialsOf(c) }}</span>' +
              '</span>' +
              '<span class="ri-col"><span class="ri-name">{{ titleOf(c) }}</span>' +
              '<span class="ri-user">{{ c.type === \'group\' ? t(\'Grupo\') : t(\'Chat\') }}</span></span>' +
            '</button>' +
            '<div class="list-empty" v-if="!fwdChats.length">{{ t(\'Sin resultados.\') }}</div>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '</transition>' +
      '<chat-info-panel></chat-info-panel>' +
      /* W13: buscar dentro del chat. W37b: ahora es un MODAL (no un
         panel lateral que empujaba el chat). W37c: anima apertura y
         cierre como el resto. */
      '<transition name="veil">' +
      '<div class="modal-veil" v-if="searchOpen && activeChat" @click.self="toggleSearch">' +
        '<div class="modal search-modal" :aria-label="t(\'Buscar en el chat\')">' +
        '<header>' +
          '<b>{{ t(\'Buscar en el chat\') }}</b>' +
          '<button class="icon-btn" type="button" :title="t(\'Cerrar\')" @click="toggleSearch">' +
            '<svg class="ic"><use href="#i-x"></use></svg>' +
          '</button>' +
        '</header>' +
        '<div class="sp-body">' +
          '<div class="search-pill">' +
            '<svg class="ic ic-sm"><use href="#i-search"></use></svg>' +
            '<input v-model="sQ" :placeholder="t(\'Buscar mensajes\')" ' +
              ':aria-label="t(\'Buscar mensajes\')" @input="onSearchInput">' +
          '</div>' +
          '<div class="sp-res" role="button" tabindex="0" v-for="m in sResults" :key="m.id" ' +
            '@click="jumpResult(m)" @keydown.enter="jumpResult(m)">' +
            '<span class="spr-top">' +
              '<b>{{ m.sender ? (m.sender.display_name || m.sender.username) : \'\' }}</b>' +
              '<span class="spr-time">{{ sTime(m.created_at) }}</span>' +
            '</span>' +
            '<span class="spr-text">{{ sSnippet(m) }}</span>' +
          '</div>' +
          '<div class="sp-empty" v-if="sErr">{{ sErr }}</div>' +
          '<div class="sp-empty" v-else-if="sBusy">{{ t(\'Buscando…\') }}</div>' +
          '<div class="sp-empty" v-else-if="!sQ.trim()">' +
            '{{ t(\'Escribe para buscar en los mensajes de este chat.\') }}</div>' +
          '<div class="sp-empty" v-else-if="!sResults.length">{{ t(\'Sin resultados.\') }}</div>' +
        '</div>' +
        '</div>' +
      '</div>' +
      '</transition>' +
      /* W39: el código de verificación E2E en un MODAL centrado (antes
         era un toast que se perdía en la esquina). Icono de llave,
         los 6 números bien grandes y una pista para compararlo. */
      '<transition name="veil">' +
      '<div class="modal-veil" v-if="store.sasOpen" @click.self="store.sasOpen = false">' +
        '<div class="modal sas-modal" role="dialog" ' +
          ':aria-label="t(\'Código de verificación\')">' +
        '<header>' +
          '<b>{{ t(\'Código de verificación\') }}</b>' +
          '<button class="icon-btn" type="button" :title="t(\'Cerrar\')" ' +
            '@click="store.sasOpen = false">' +
            '<svg class="ic"><use href="#i-x"></use></svg>' +
          '</button>' +
        '</header>' +
        '<div class="sas-body">' +
          '<svg class="ic sas-ic"><use href="#i-key"></use></svg>' +
          '<div class="sas-code">{{ sasCode }}</div>' +
          '<div class="sas-hint">' +
            '{{ t(\'Compara este código con tu contacto. Si coincide, ' +
              'nadie intercepta la conversación.\') }}' +
          '</div>' +
        '</div>' +
        '</div>' +
      '</div>' +
      '</transition>' +
      '<profile-panel></profile-panel>' +
      /* W11: soltar archivos sobre el chat */
      '<div class="drop-hint" v-if="dropping">' +
        '<span>{{ t(\'Suelta los archivos para enviarlos\') }}</span>' +
      '</div>' +
      /* W8: vista previa de imágenes con zoom (clic = 2.5x, rueda, arrastre) */
      '<div class="lightbox" v-if="lb" :class="{ \'lb-zoomed\': lbScale > 1 }" @click.self="closeLb">' +
        '<button class="icon-btn lb-close" type="button" :title="t(\'Cerrar (Esc)\')" @click="closeLb">' +
          '<svg class="ic"><use href="#i-x"></use></svg>' +
        '</button>' +
        '<a class="icon-btn lb-dl" :href="lb.url" download :title="t(\'Descargar\')">' +
          '<svg class="ic"><use href="#i-download"></use></svg>' +
        '</a>' +
        '<img class="lb-img" :src="lb.url" :style="lbStyle" ' +
          '@click="lbZoom" @wheel.prevent="lbWheel" @mousedown.prevent="lbDown" ' +
          '@touchstart="lbTouchStart" @touchmove.prevent="lbTouchMove" ' +
          '@touchend="lbTouchEnd" @touchcancel="lbTouchEnd">' +
        /* W22: la ayuda lleva su píldora de fondo y desaparece al
           hacer zoom (con la imagen ampliada solo estorba). */
        '<span class="lb-hint" v-if="lbScale <= 1"><span class="lb-pill">' +
          '{{ t(\'Click o rueda para ampliar · arrastra para mover\') }}</span></span>' +
      '</div>' +
      /* W7: menú contextual (fixed; la posición sale del evento.
         W17: con ancla a la burbuja no tapa el mensaje.
         W37b: cada ítem puede traer su icono (it.icon → #symbol).
         W37b: en móvil el MISMO menú es un bottom sheet abajo. */
      '<div class="ctx-backdrop" v-if="store.ctx && store.ctx.sheet" ' +
        '@click.stop="store.ctx = null"></div>' +
      '<div class="ctx-menu" :class="{ \'ctx-sheet\': store.ctx.sheet }" ' +
        'v-if="store.ctx" @click.stop ' +
        ':style="store.ctx.sheet ? {} : ' +
          '{ left: store.ctx.x + \'px\', top: store.ctx.y + \'px\' }">' +
        '<div class="ctx-head" v-if="store.ctx.sheet && store.ctx.head">' +
          '<span class="avatar av36">' +
            '<img v-if="store.ctx.head.avatar" :src="store.ctx.head.avatar" alt="">' +
            '<span v-else>{{ store.ctx.head.ini }}</span>' +
          '</span>' +
          '<span class="ctx-head-col">' +
            '<b>{{ store.ctx.head.name }}</b>' +
            '<small v-if="store.ctx.head.sub">{{ store.ctx.head.sub }}</small>' +
          '</span>' +
        '</div>' +
        '<button class="ctx-item" :class="{ danger: it.danger }" type="button" ' +
          'v-for="(it, i) in store.ctx.items" :key="i" @click="runCtx(it)">' +
          '<svg class="ic ic-sm ctx-ic" v-if="it.icon"><use :href="\'#\' + it.icon"></use></svg>' +
          '<span>{{ t(it.label) }}</span></button>' +
      '</div>' +
      /* W27h: pantalla de arranque — cubre la app hasta que chats,
         gente (perfiles), vistas previas y mensajes iniciales están
         listos y la interfaz se revela completa. W38: ahora muestra
         la pantalla compartida (icono, cifrado, barra y fase). */
      '<div class="app-boot" v-if="store.booting">' +
        '<boot-screen></boot-screen>' +
      '</div>' +
    '</div>',
};
