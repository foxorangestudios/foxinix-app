/* Foxinix — W28h: llamadas de voz/video 1:1 (WebRTC).

   El server SOLO relaya la señalización por la WS del chat (oferta,
   respuesta, ICE, colgar); el audio/video viajan P2P entre los dos
   navegadores. Sin SFU ni grupos: 1:1 sobre un DM.

   El estado reactivo vive en store.call (null | {chatId, peer, state,
   video, muted, camOff, startedAt, remote}); RTCPeerConnection y los
   MediaStream quedan FUERA del store (no son datos observables: Vue los
   envolvería en proxies y los métodos nativos se rompen).

   Estados: 'incoming' (suena el tono) → 'connecting' → 'active';
   el que llama empieza en 'outgoing'. Firefox 78: RTCPeerConnection y
   getUserMedia con promesas ✓ (el runner de tests inyecta micrófono y
   cámara falsos vía media.navigator.streams.fake). */
import { store, toast } from './store.js';
import { t } from './i18n.js';
import { ensurePermission } from './permissions.js';

let sendFn = null;          // lo inyecta realtime.js (su send() privado)
let pc = null;
let localStream = null;
let remoteStream = null;
let pendingOffer = null;    // oferta entrante esperando "Contestar"
let ringTimer = null;       // tono de llamada entrante
let callTimer = null;       // sin respuesta / conexión colgada
let iceQueue = [];          // candidatos llegados antes de la remota
let actx = null;
let starting = false;       // getUserMedia en curso (evita doble clic)
let callGen = 0;            // invalida getUserMedia que termina tras colgar
const RING_TIMEOUT = 60000; // 60 s para contestar
const CONNECT_TIMEOUT = 45000; // 45 s para establecer la conexión

export function initCall(send) { sendFn = send; }

/* Los <video> del panel se enganchan a estos streams en cada render. */
export function getLocalStream() { return localStream; }
export function getRemoteStream() { return remoteStream; }

/* ------------------------------------------------- tono (WebAudio) */

function beep(freq, dur) {
  const g = actx.createGain();
  const o = actx.createOscillator();
  const t0 = actx.currentTime;
  o.type = 'sine';
  o.frequency.setValueAtTime(freq, t0);
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(0.12, t0 + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  o.connect(g);
  g.connect(actx.destination);
  o.start(t0);
  o.stop(t0 + dur + 0.05);
}

function stopRing() {
  if (ringTimer) { clearInterval(ringTimer); ringTimer = null; }
}

function stopCallTimer() {
  if (callTimer) { clearTimeout(callTimer); callTimer = null; }
}

/* Sin esto una llamada ignorada o una conexión que nunca completa deja
   cámara/micrófono activos indefinidamente. */
function armCallTimer(ms, reason) {
  stopCallTimer();
  callTimer = setTimeout(function () {
    callTimer = null;
    if (!store.call || store.call.state === 'active') return;
    if (sendFn) sendFn({ type: 'call_hangup', chat_id: store.call.chatId, reason: reason });
    cleanup();
    store.call = null;
    toast(reason === 'timeout' ? t('Sin respuesta') : t('La llamada se cortó'));
  }, ms);
}

function startRing() {
  stopRing();
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    if (!actx) actx = new AC();
    const pair = function () {
      beep(660, 0.35);
      setTimeout(function () { beep(520, 0.35); }, 480);
    };
    pair();
    ringTimer = setInterval(pair, 2400);
  } catch (e) { /* sin audio: solo suena el visual */ }
}

/* ------------------------------------------------------- ciclo base */

function releaseStream(stream) {
  if (!stream) return;
  try {
    const trs = stream.getTracks();
    for (let i = 0; i < trs.length; i++) trs[i].stop();
  } catch (e) {}
}

function cleanup() {
  stopRing();
  stopCallTimer();
  /* Cualquier getUserMedia pendiente queda invalidado: si el usuario
     cuelga/logout mientras el navegador pide permiso, al resolverse no
     puede volver a encender la cámara. */
  callGen++;
  starting = false;
  if (pc) {
    try { pc.close(); } catch (e) {}
    pc = null;
  }
  if (localStream) {
    releaseStream(localStream);
    localStream = null;
  }
  remoteStream = null;
  pendingOffer = null;
  iceQueue = [];
}

function endCall(reason) {
  cleanup();
  store.call = null;
  if (reason === 'busy') toast(t('Ocupado'));
  else if (reason === 'rejected') toast(t('Llamada rechazada'));
  else if (reason === 'failed') toast(t('La llamada falló'));
  else if (reason === 'timeout') toast(t('Sin respuesta'));
}

/* --------------------------------------------------------- peer */

function iceServers() {
  /* Permite añadir TURN sin tocar el código: window.FOXINIX_ICE_SERVERS
     = [{urls:'turn:...', username:'...', credential:'...'}, ...].
     En redes móviles/NAT restrictivas STUN solo no basta. */
  const custom = window.FOXINIX_ICE_SERVERS;
  if (Array.isArray(custom) && custom.length) return custom;
  return [{ urls: 'stun:stun.l.google.com:19302' }];
}

function newPC(chatId, video) {
  const P = window.RTCPeerConnection || window.webkitRTCPeerConnection;
  pc = new P({ iceServers: iceServers() });
  pc.onicecandidate = function (ev) {
    sendFn({
      type: 'call_ice', chat_id: chatId,
      candidate: ev.candidate ? {
        candidate: ev.candidate.candidate,
        sdpMid: ev.candidate.sdpMid,
        sdpMLineIndex: ev.candidate.sdpMLineIndex,
      } : null,
    });
  };
  pc.ontrack = function (ev) {
    /* W60: un solo MediaStream con TODAS las pistas. Antes se guardaba
       ev.streams[0] y, en algunos navegadores, audio y video llegaban
       en flujos distintos: el panel podía quedarse solo con el video y
       no sonaba la llamada de voz. */
    if (!remoteStream) {
      const MS = window.MediaStream || window.webkitMediaStream;
      remoteStream = MS ? new MS() : null;
    }
    if (remoteStream && ev.track) {
      let dup = false;
      const trs = remoteStream.getTracks();
      for (let i = 0; i < trs.length; i++) if (trs[i].id === ev.track.id) dup = true;
      if (!dup) remoteStream.addTrack(ev.track);
    }
    if (store.call) {
      store.call.remote = true;
      if (ev.track && ev.track.kind === 'video') store.call.remoteVideo = true;
    }
  };
  const onState = function () {
    if (!pc || !store.call || store.call.chatId !== chatId) return;
    const cs = pc.connectionState;
    const ics = pc.iceConnectionState;
    if (store.call.state !== 'active' &&
        (cs === 'connected' || ics === 'connected' || ics === 'completed')) {
      store.call.state = 'active';
      store.call.startedAt = Date.now();
      stopCallTimer();
    } else if (cs === 'failed' || ics === 'failed') {
      endCall('failed');
    }
  };
  pc.onconnectionstatechange = onState;
  pc.oniceconnectionstatechange = onState;
}

function flushIce() {
  if (!pc) return;
  for (let i = 0; i < iceQueue.length; i++) {
    try { pc.addIceCandidate(iceQueue[i]); } catch (e) {}
  }
  iceQueue = [];
}

function gotIce(cand) {
  if (!cand) return;
  if (pc && pc.remoteDescription) {
    try { pc.addIceCandidate(cand); } catch (e) {}
  } else {
    iceQueue.push(cand);   // llega antes de la descripción remota
  }
}

/* -------------------------------------------------------- acciones */

/* W60: la cámara NUNCA es obligatoria. Se intenta audio+video; si la
   cámara falta/está denegada, la llamada sigue solo con micrófono (que
   sí es imprescindible y se puede silenciar). */
function acquireMedia(wantVideo) {
  return navigator.mediaDevices.getUserMedia({
    audio: true, video: !!wantVideo,
  }).catch(function (err) {
    if (!wantVideo) throw err;
    return navigator.mediaDevices.getUserMedia({
      audio: true, video: false,
    });
  });
}

export async function startCall(chat, video) {
  if (store.call) { toast(t('Ya hay una llamada en curso')); return; }
  /* W58: si el usuario saltó el permiso al arrancar, se vuelve a pedir
     justo al usar la función; sin permiso no se inicia la llamada. */
  if (!(await ensurePermission('mic'))) {
    toast(t('Permiso de micrófono necesario para llamar'), 'err');
    return;
  }
  if (store.call) { toast(t('Ya hay una llamada en curso')); return; }
  /* en un DM, chat.title ES el brief del peer (chat_brief del server) */
  const peer = chat.title || null;
  let ok = false;
  try {
    ok = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
            (window.RTCPeerConnection || window.webkitRTCPeerConnection));
  } catch (e) { ok = false; }
  if (!ok) { toast(t('No se pudo iniciar la llamada')); return; }
  if (starting) { toast(t('Ya hay una llamada en curso')); return; }
  starting = true;
  const gen = ++callGen;
  acquireMedia(video)
    .then(function (stream) {
      if (gen !== callGen || !store.hasSession) {
        starting = false;
        releaseStream(stream);
        return;
      }
      starting = false;
      localStream = stream;
      const hasCam = stream.getVideoTracks().length > 0;
      store.call = {
        chatId: chat.id, peerId: peer ? peer.id : 0, peer: peer,
        state: 'outgoing',
        /* video = la llamada puede mostrar/recibir video. Si el usuario
           pidió cámara y no la hay, la llamada sigue siendo de voz. */
        video: !!video && hasCam,
        hasCam: hasCam,
        muted: false, camOff: !hasCam,
        remote: false, remoteVideo: false, remoteMuted: false,
        startedAt: 0,
      };
      armCallTimer(CONNECT_TIMEOUT + 15000, 'timeout');
      newPC(chat.id, !!video);
      stream.getTracks().forEach(function (tr) { pc.addTrack(tr, stream); });
      return pc.createOffer();
    })
    .then(function (offer) {
      if (gen !== callGen || !store.call || !pc) return;
      return pc.setLocalDescription(offer);
    })
    .then(function () {
      if (gen !== callGen || !store.call || !pc) return;
      const sent = sendFn({
        type: 'call_offer', chat_id: store.call.chatId,
        video: !!store.call.video, sdp: pc.localDescription.sdp,
      });
      if (!sent) { endCall(null); toast(t('Sin conexión')); }
    })
    .catch(function () {
      if (gen !== callGen) return;
      cleanup();
      store.call = null;
      toast(t('No se pudo iniciar la llamada'));
    });
}

export async function acceptCall() {
  const ev = pendingOffer;
  if (!store.call || store.call.state !== 'incoming' || !ev) return;
  if (!(await ensurePermission('mic'))) {
    toast(t('Permiso de micrófono necesario para llamar'), 'err');
    return;
  }
  if (!store.call || store.call.state !== 'incoming' || !pendingOffer) return;
  if (pendingOffer !== ev || starting) return;
  stopRing();
  stopCallTimer();
  starting = true;
  const gen = ++callGen;
  /* W60: contestar una videollamada sin cámara también es válido: el
     micrófono es obligatorio, la cámara no. */
  acquireMedia(!!ev.video)
    .then(function (stream) {
      if (gen !== callGen || !store.call || store.call.state !== 'incoming'
          || !pendingOffer || pendingOffer !== ev || !store.hasSession) {
        starting = false;
        releaseStream(stream);
        return;
      }
      starting = false;
      localStream = stream;
      const hasCam = stream.getVideoTracks().length > 0;
      store.call.state = 'connecting';
      store.call.hasCam = hasCam;
      store.call.camOff = !hasCam;
      store.call.video = !!(ev.video || hasCam);
      store.call.remote = false;
      store.call.remoteVideo = false;
      armCallTimer(CONNECT_TIMEOUT, 'timeout');
      newPC(ev.chat_id, !!ev.video);
      stream.getTracks().forEach(function (tr) { pc.addTrack(tr, stream); });
      return pc.setRemoteDescription({ type: 'offer', sdp: ev.sdp })
        .then(function () { return pc.createAnswer(); })
        .then(function (ans) { return pc.setLocalDescription(ans); })
        .then(function () {
          if (gen !== callGen || !store.call || !pc) return;
          flushIce();
          const sent = sendFn({
            type: 'call_answer', chat_id: ev.chat_id,
            sdp: pc.localDescription.sdp,
          });
          if (!sent) { endCall(null); toast(t('Sin conexión')); }
        });
    })
    .catch(function () {
      if (gen !== callGen) return;
      cleanup();
      store.call = null;
      toast(t('No se pudo iniciar la llamada'));
    });
}

/* Cierre forzado: logout, pérdida de sesión, desmontaje de la pantalla.
   Avisa best-effort al otro lado y SIEMPRE libera cámara/micrófono. */
export function abortCall(reason) {
  if (store.call && sendFn) {
    try {
      sendFn({
        type: 'call_hangup', chat_id: store.call.chatId,
        reason: reason || 'hangup',
      });
    } catch (e) {}
  }
  cleanup();
  store.call = null;
}

export function rejectCall() {
  if (!store.call || store.call.state !== 'incoming') return;
  sendFn({ type: 'call_hangup', chat_id: store.call.chatId, reason: 'rejected' });
  cleanup();
  store.call = null;
}

export function hangupCall() {
  abortCall('hangup');
}

export function toggleMute() {
  if (!store.call || !localStream) return;
  const m = !store.call.muted;
  const trs = localStream.getAudioTracks();
  for (let i = 0; i < trs.length; i++) trs[i].enabled = !m;
  store.call.muted = m;
}

export function toggleCam() {
  if (!store.call || !localStream) return;
  const off = !store.call.camOff;
  const trs = localStream.getVideoTracks();
  for (let i = 0; i < trs.length; i++) trs[i].enabled = !off;
  store.call.camOff = off;
}

/* ------------------------------------- eventos de la WS (realtime.js) */

export function handleCallEvent(ev) {
  if (ev.type === 'call_error') {
    if (store.call && store.call.chatId === ev.chat_id) {
      cleanup();
      store.call = null;
    }
    toast(ev.detail ? String(ev.detail) : t('El usuario no está disponible'));
    return;
  }

  if (ev.type === 'call_offer') {
    if (store.call) {
      /* ocupado (o llamando a otro): rechazo automático */
      sendFn({ type: 'call_hangup', chat_id: ev.chat_id, reason: 'busy' });
      return;
    }
    if (pendingOffer) return;   // ya hay otra entrante esperando
    pendingOffer = ev;
    store.call = {
      chatId: ev.chat_id,
      peerId: ev.from ? ev.from.id : 0,
      peer: ev.from || null,
      state: 'incoming', video: !!ev.video,
      hasCam: false, muted: false, camOff: true, startedAt: 0,
      remote: false, remoteVideo: false, remoteMuted: false,
    };
    startRing();
    armCallTimer(RING_TIMEOUT, 'missed');
    return;
  }

  if (!store.call || store.call.chatId !== ev.chat_id) return;

  if (ev.type === 'call_answer') {
    if (!pc || !ev.sdp) return;
    pc.setRemoteDescription({ type: 'answer', sdp: ev.sdp })
      .then(function () {
        flushIce();
        if (store.call && store.call.state === 'outgoing') {
          store.call.state = 'connecting';
        }
      })
      .catch(function () { endCall('failed'); });
    return;
  }

  if (ev.type === 'call_ice') {
    gotIce(ev.candidate);
    return;
  }

  if (ev.type === 'call_hangup') {
    const wasIncoming = store.call.state === 'incoming';
    /* el rechazo/ocupado solo interesa al que llamaba; al que rechaza no
       se le molesta con un toast (él ya decidió) */
    endCall(wasIncoming ? null : ev.reason);
  }
}

/* W28h: al recargar o cerrar la pestaña con una llamada abierta, avisar
   al otro lado (best-effort: el WS suele alcanzar a enviarlo antes de
   morir; si no, el peer lo corta con su timeout de conexión). */
window.addEventListener('pagehide', function () {
  if (store.call) abortCall('hangup');
});
