/* W29f: cifrado de extremo a extremo (chats directos).
   ECDH P-256 → HKDF-SHA-256 (manual, con HMAC de WebCrypto) → clave
   AES-GCM-256 por pareja de usuarios. La privada vive SOLO en
   IndexedDB del navegador; el server ve clave pública, IV y blob
   cifrado — jamás el texto en claro.

   HKDF manual (no usa importKey 'HKDF' para no depender del soporte
   exacto de cada versión de Firefox):
     PRK  = HMAC-SHA256(salt, ikm)
     T1   = HMAC-SHA256(PRK, info || 0x01)   → 32 B = clave AES
   info = "foxinix-e2e-v1|<uidMin>|<uidMax>" (misma para ambos lados). */
import { api } from './api.js';
import { store } from './store.js';

const enc = new TextEncoder();
const dec = new TextDecoder();
const SALT = enc.encode('foxinix-e2e-v1-salt');
const INFO_PFX = 'foxinix-e2e-v1|';

function writeLs(key, val) {
  try { localStorage.setItem(key, val); } catch (e) {}
}

/* -------------------------------------------------- base64 <-> bytes */

export function b64(u8) {
  let s = '';
  for (let i = 0; i < u8.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

export function unb64(s) {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/* -------------------------------------------------- IndexedDB (privada) */

const DB_NAME = 'foxinix-e2e';

function openDb() {
  return new Promise(function (res, rej) {
    /* W30a: v2 añade 'chats' (claves de chat ya derivadas) */
    const rq = indexedDB.open(DB_NAME, 2);
    rq.onupgradeneeded = function () {
      if (!rq.result.objectStoreNames.contains('keys')) {
        rq.result.createObjectStore('keys', { keyPath: 'uid' });
      }
      if (!rq.result.objectStoreNames.contains('chats')) {
        rq.result.createObjectStore('chats', { keyPath: 'cid' });
      }
    };
    rq.onsuccess = function () { res(rq.result); };
    rq.onerror = function () { rej(rq.error); };
  });
}

async function idbGet(uid) {
  try {
    const dbh = await openDb();
    return await new Promise(function (res, rej) {
      const tx = dbh.transaction('keys', 'readonly');
      const rq = tx.objectStore('keys').get(uid);
      rq.onsuccess = function () { res(rq.result || null); };
      rq.onerror = function () { rej(rq.error); };
    });
  } catch (e) {
    return null;
  }
}

async function idbPut(rec) {
  const dbh = await openDb();
  return new Promise(function (res, rej) {
    const tx = dbh.transaction('keys', 'readwrite');
    tx.objectStore('keys').put(rec);
    tx.oncomplete = function () { res(true); };
    tx.onerror = function () { rej(tx.error); };
  });
}

/* W30a: caché local de la clave de chat YA derivada (raw AES-GCM).
   Evita el RTT a /e2e-key en cada recarga: el historial se descifra
   antes de pintarse y el marcador del server nunca se ve. */
async function idbChatGet(cid) {
  try {
    const dbh = await openDb();
    return await new Promise(function (res, rej) {
      const tx = dbh.transaction('chats', 'readonly');
      const rq = tx.objectStore('chats').get(cid);
      rq.onsuccess = function () { res(rq.result || null); };
      rq.onerror = function () { rej(rq.error); };
    });
  } catch (e) {
    return null;
  }
}

async function idbChatPut(rec) {
  try {
    const dbh = await openDb();
    return await new Promise(function (res, rej) {
      const tx = dbh.transaction('chats', 'readwrite');
      tx.objectStore('chats').put(rec);
      tx.oncomplete = function () { res(true); };
      tx.onerror = function () { rej(tx.error); };
    });
  } catch (e) {
    return false;
  }
}

async function idbChatDel(cid) {
  try {
    const dbh = await openDb();
    await new Promise(function (res, rej) {
      const tx = dbh.transaction('chats', 'readwrite');
      tx.objectStore('chats').delete(cid);
      tx.oncomplete = function () { res(true); };
      tx.onerror = function () { rej(tx.error); };
    });
  } catch (e) { /* sin caché: no hay nada que borrar */ }
}

/* -------------------------------------------------- par ECDH propio */

async function importPriv(jwk) {
  return crypto.subtle.importKey(
    'jwk', jwk, { name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']
  );
}

async function generatePair(uid) {
  const kp = await crypto.subtle.generateKey(
    { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']
  );
  let raw = new Uint8Array(await crypto.subtle.exportKey('raw', kp.publicKey));
  if (raw.length !== 65 || raw[0] !== 4) {
    /* Algunos navegadores sólo exportan SPKI: el punto P-256 son los
       últimos 65 bytes (cabecera fija de29 B). */
    const spki = new Uint8Array(await crypto.subtle.exportKey('spki', kp.publicKey));
    raw = spki.subarray(spki.length - 65);
  }
  const jwk = await crypto.subtle.exportKey('jwk', kp.privateKey);
  await idbPut({ uid: uid, pub: b64(raw), jwk: jwk });
  return b64(raw);
}

/* Mi clave pública (la crea la primera vez que se necesita). */
export async function ensureMyKey(uid) {
  const have = await idbGet(uid);
  if (have && have.pub) return have.pub;
  return generatePair(uid);
}

async function myPrivateKey(uid) {
  const rec = await idbGet(uid);
  if (!rec || !rec.jwk) return null;
  return importPriv(rec.jwk);
}

/* -------------------------------------------------- derivación */

function hkdf(ikm, infoStr) {
  const info = enc.encode(infoStr);
  return crypto.subtle.importKey(
    'raw', SALT, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  ).then(function (saltKey) {
    return crypto.subtle.sign('HMAC', saltKey, ikm);
  }).then(function (prkB) {
    const t1 = new Uint8Array(info.length + 1);
    t1.set(info);
    t1[info.length] = 1;
    return crypto.subtle.importKey(
      'raw', prkB, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
    ).then(function (prkKey) {
      return crypto.subtle.sign('HMAC', prkKey, t1);
    });
  });
}

function infoFor(uidA, uidB) {
  const lo = Math.min(uidA, uidB);
  const hi = Math.max(uidA, uidB);
  return INFO_PFX + lo + '|' + hi;
}

/* Clave AES-GCM de la pareja: devuelve {key (CryptoKey), raw (Uint8Array)} */
async function deriveWith(myUid, peerUid, peerPubB64) {
  const priv = await myPrivateKey(myUid);
  if (!priv) throw new Error('Sin clave propia');
  const pub = await crypto.subtle.importKey(
    'raw', unb64(peerPubB64),
    { name: 'ECDH', namedCurve: 'P-256' }, false, []
  );
  const ikm = new Uint8Array(
    await crypto.subtle.deriveBits({ name: 'ECDH', public: pub }, priv, 256)
  );
  const raw = new Uint8Array(await hkdf(ikm, infoFor(myUid, peerUid)));
  const key = await crypto.subtle.importKey(
    'raw', raw, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']
  );
  return { key: key, raw: raw };
}

/* -------------------------------------------------- claves por chat */

const chatKeys = {};      // chatId → {key, raw} | {none: true}
const chatKeyWait = {};   // chatId → Promise (dedupe)

function peerOfChat(chatId) {
  const c = (store.chats || []).find(function (x) { return x.id === chatId; });
  if (!c || c.type !== 'dm' || !c.title) return null;
  return c.title;
}

/* Red: busca la clave pública del par y deriva (W30a: un solo sitio). */
async function fetchChatKey(chatId, me, peer) {
  await ensureMyKey(me.id);
  const r = await api('GET', '/api/users/' +
    encodeURIComponent(peer.username) + '/e2e-key');
  if (!r || !r.public_key) return { none: true };
  const out = await deriveWith(me.id, peer.id, r.public_key);
  chatKeys[chatId] = out;
  store.e2eSas[chatId] = sasOf(out.raw);
  idbChatPut({ cid: chatId, me: me.id, peerUid: peer.id,
               raw: b64(out.raw), peerPub: r.public_key });
  return out;
}

/* W30a: revalida EN SEGUNDO PLANO la clave pública del par contra la
   caché local; si cambió (el par rotó su clave), se rederiva y se
   reintenta descifrar todo. Así la clave local nunca queda vieja. */
function revalidateChatKey(chatId, me, peer, knownPub) {
  api('GET', '/api/users/' + encodeURIComponent(peer.username) + '/e2e-key')
    .then(async function (r) {
      const pub = r && r.public_key;
      if (!pub || pub === knownPub) return;
      const out = await deriveWith(me.id, peer.id, pub);
      if (!chatKeys[chatId] || !chatKeys[chatId]._cached) return;
      chatKeys[chatId] = out;
      store.e2eSas[chatId] = sasOf(out.raw);
      idbChatPut({ cid: chatId, me: me.id, peerUid: peer.id,
                   raw: b64(out.raw), peerPub: pub });
      retryDecrypt(store.msgs[chatId]);
    })
    .catch(function () {});
}

export async function chatKey(chatId) {
  if (chatKeys[chatId]) return chatKeys[chatId];
  if (chatKeyWait[chatId]) return chatKeyWait[chatId];
  const p = (async function () {
    const me = store.user;
    const peer = peerOfChat(chatId);
    if (!me || !peer || !peer.id) return { none: true };
    /* W30a: clave derivada en IndexedDB → se usa YA (AES local, sin
       RTT): la recarga no vuelve a preguntar y los mensajes se ven
       descifrados desde el primer pintado. */
    const cached = await idbChatGet(chatId);
    if (cached && cached.raw && cached.peerPub &&
        cached.me === me.id && cached.peerUid === peer.id) {
      try {
        const raw = unb64(cached.raw);
        const key = await crypto.subtle.importKey(
          'raw', raw, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
        const out = { key: key, raw: raw, _cached: true };
        chatKeys[chatId] = out;
        store.e2eSas[chatId] = sasOf(raw);
        revalidateChatKey(chatId, me, peer, cached.peerPub);
        return out;
      } catch (e) { /* caché ilegible: se cae a la red */ }
    }
    return await fetchChatKey(chatId, me, peer);
  })();
  chatKeyWait[chatId] = p;
  try {
    const out = await p;
    /* Los "sin clave" NO se retienen: si la lista de chats o la clave
       del contacto llegan después, el siguiente intento reconsulta. */
    if (!out || out.none) delete chatKeyWait[chatId];
    return out;
  } catch (e) {
    delete chatKeyWait[chatId];
    throw e;
  }
}

/* W30a: ¿la clave ya está en memoria? → el entrante por WS se
   descifra ANTES de insertar (la burbuja nunca muestra el marcador). */
export function chatKeyReady(chatId) {
  const k = chatKeys[chatId];
  return !!(k && !k.none);
}

/* W30a: descarta la clave local (el blob no abrió: el par rotó la
   clave) y fuerza una consulta nueva a la red. */
function invalidateChatKey(chatId) {
  delete chatKeys[chatId];
  delete chatKeyWait[chatId];
  return idbChatDel(chatId).then(function () { return true; });
}

/* -------------------------------------------------- W31d: reintentos */

/* "Hasta que den los dos": si un blob no abre o el par aún no publicó
   su clave, se reintenta con backoff creciente (1s → 30s, tope de 12
   intentos ≈ 5 min). Cada intento descarta la clave local, reconsulta
   la pública del par, rederiva y vuelve a descifrar todo el chat; si
   el par ya publicó, los dos quedan con la misma clave y los mensajes
   se ven en claro. Se cancela solo si el chat ya no existe. */
const rekeyTimers = {};   // chatId → timeout pendiente
const rekeyTry = {};      // chatId → intentos agotados

function scheduleRekey(chatId) {
  if (rekeyTimers[chatId]) return;              // ya hay uno en vuelo
  const n = (rekeyTry[chatId] || 0) + 1;
  rekeyTry[chatId] = n;
  if (n > 12) { delete rekeyTry[chatId]; return; }   // basta (y al reabrir se reanuda)
  const delays = [1000, 2000, 4000, 8000, 15000, 30000];
  const d = delays[Math.min(n - 1, delays.length - 1)];
  rekeyTimers[chatId] = setTimeout(function () {
    delete rekeyTimers[chatId];
    let alive = false;
    const chats = store.chats || [];
    for (let i = 0; i < chats.length; i++) {
      if (chats[i].id === chatId) { alive = true; break; }
    }
    if (!alive) { delete rekeyTry[chatId]; return; }
    invalidateChatKey(chatId)
      .then(function () { return chatKey(chatId); })
      .then(function (ck) {
        if (!ck || ck.none) { scheduleRekey(chatId); return; }
        delete rekeyTry[chatId];
        retryDecrypt(store.msgs[chatId]);
      })
      .catch(function () { scheduleRekey(chatId); });
  }, d);
}

/* Huella numérica de verificación: 6 dígitos (p. ej. "8 2 0 7 0 2"),
   derivados de la clave compartida. Informativa en el panel; la
   verificación la resuelve la propia app (W31d), el usuario no tiene
   que comparar nada. */
export function sasOf(raw) {
  let out = '';
  for (let i = 0; i < 6; i++) out += (i ? ' ' : '') + (raw[i] % 10);
  return out;
}

/* -------------------------------------------------- cifrar / descifrar */

export async function encryptText(key, text) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: iv }, key, enc.encode(text)
    )
  );
  return { iv: b64(iv), ct: b64(ct) };
}

export async function decryptText(key, ivB64, ctB64) {
  const out = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: unb64(ivB64) }, key, unb64(ctB64)
  );
  return dec.decode(new Uint8Array(out));
}

/* Descifra un mensaje en el lugar (m._plain). Fallas silenciosas:
   se muestra el marcador "[Mensaje cifrado]" que puso el server. */
export async function decryptInto(m) {
  if (!m || !m.e2e || m._plain != null || m._e2eTried) return;
  m._e2eTried = true;
  let ck = null;
  try {
    ck = await chatKey(m.chat_id);
    if (!ck || ck.none) {
      /* Sin clave (el par aún no publicó): se limpia la marca y se
         programa el reintento — W31d: se sigue intentando hasta que
         él publique (o el chat desaparezca). */
      delete m._e2eTried;
      scheduleRekey(m.chat_id);
      return;
    }
    m._plain = await decryptText(ck.key, m.e2e.iv, m.e2e.ct);
    delete rekeyTry[m.chat_id];   // W31d: ya dieron los dos
  } catch (e) {
    delete m._e2eTried;
    if (ck && ck._cached && !m._e2eReFetched) {
      /* W30a: la clave de la caché local no abre el blob (p. ej. el
         par rotó su clave): se descarta y se reintenta YA con la de
         red; si esa tampoco da, cae al reintento con backoff. */
      m._e2eReFetched = true;
      return invalidateChatKey(m.chat_id).then(function () {
        return decryptInto(m);
      });
    }
    /* W31d: la clave no abre el blob (desincronización): reintento
       con backoff hasta que dé — o, en el peor caso, queda el
       marcador tras agotar los intentos. */
    scheduleRekey(m.chat_id);
  }
}

/* Fuerza un reintentar de descifrado (p. ej. al activar el cifrado). */
export function retryDecrypt(msgs) {
  if (!msgs) return;
  for (let i = 0; i < msgs.length; i++) {
    const m = msgs[i];
    if (m && m.e2e) {
      delete m._e2eTried;
      decryptInto(m);
    }
  }
}

/* -------------------------------------------------- estado por chat */

function lsKey() {
  return 'fm.e2e.' + ((store.user && store.user.id) || 0);
}

function e2eSaveState() {
  writeLs(lsKey(), JSON.stringify(store.e2e || {}));
}

export function e2eOn(chatId) {
  return !!(store.e2e && store.e2e[chatId]);
}

export function e2eSet(chatId, on) {
  if (on) store.e2e[chatId] = 1;
  else delete store.e2e[chatId];
  e2eSaveState();
}

/* ¿Este chat viaja cifrado ahora? */
export function isEncrypting(chatId) {
  return e2eOn(chatId);
}

/* -------------------------------------------------- activación */

/* W30d: MI clave pública SIEMPRE publicada (como WhatsApp sube sus
   prekeys al registrar). Se guarda la huella de lo último publicado en
   localStorage para no re-enviar la MISMA clave en cada arranque. */
export async function ensurePublishedKey() {
  const me = store.user;
  if (!me) return false;
  try {
    const pub = await ensureMyKey(me.id);
    let last = null;
    try { last = localStorage.getItem('fm.e2e.pub'); } catch (e) {}
    if (last === pub) return true;   // ya publicada antes
    await api('PUT', '/api/users/me/e2e-key', { public_key: pub });
    try { localStorage.setItem('fm.e2e.pub', pub); } catch (e) {}
    return true;
  } catch (e) {
    return false;
  }
}

/* Activa el cifrado en un DM: publica MI clave (si no existe), pide
   la del par y deriva. Lanza Error con mensaje listo para toast. */
/* W30d/W31c: auto-activación al ABRIR un DM — el cifrado SIEMPRE
   intenta encenderse (ya no hay switch ni opt-out). Si el par ya
   publicó su clave se activa solo; si AÚN no, queda "pendiente"
   (aviso en el panel y sobre la conversación) y se reactiva al
   reabrir — o con los reintentos de fondo (W31d) — cuando publique.
   Devuelve 'on' | 'pend' | 'skip'. Comparte la misma petición de
   clave (chatKey) que el descifrado del historial. */
export async function maybeAutoActivate(chat) {
  if (!chat || chat.type !== 'dm' || !chat.title) return 'skip';
  const id = chat.id;
  if (store.e2e && store.e2e[id]) return 'skip';        // ya activo
  const me = store.user;
  if (!me) return 'skip';
  try {
    await ensurePublishedKey();          // para que el par pueda cifrarme
    const ck = await chatKey(id);        // 1 petición (compartida con el historial)
    if (ck && !ck.none) {
      if (store.e2ePend) delete store.e2ePend[id];
      e2eSet(id, true);
      retryDecrypt(store.msgs[id]);
      return 'on';
    }
    if (!store.e2ePend) store.e2ePend = {};
    store.e2ePend[id] = 1;   // W31c: aviso en TODOS los DMs sin clave
    return 'pend';
  } catch (e) {
    return 'skip';
  }
}
