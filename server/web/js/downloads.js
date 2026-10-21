/* Foxinix — descargas persistentes (W50).

   Los bytes de una descarga explícita se guardan en Cache Storage
   (`foxinix-downloads-v1`) y la ficha (nombre, tamaño, fecha) en
   IndexedDB. Así se pueden volver a guardar o abrir sin bajarlos de
   nuevo, incluso después de recargar la app.

   El caché de medios que usa el service worker es distinto y se poda
   por tamaño; las descargas explícitas NO se podan automáticamente.
   Si el navegador borra el almacenamiento, la ficha se limpia sola al
   abrir la lista y se puede volver a descargar.

   Sin dependencias. FF78: Cache API + IndexedDB + Blob disponibles. */
export const DL_CACHE = 'foxinix-downloads-v1';

const DB_NAME = 'foxinix-downloads';
const DB_VERSION = 1;
const STORE = 'files';
let dbPromise = null;

function hasIDB() {
  return typeof indexedDB !== 'undefined';
}

function dbOpen() {
  if (!hasIDB()) return Promise.reject(new Error('sin IndexedDB'));
  if (dbPromise) return dbPromise;
  dbPromise = new Promise(function (resolve, reject) {
    const rq = indexedDB.open(DB_NAME, DB_VERSION);
    rq.onupgradeneeded = function () {
      const db = rq.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'key' });
      }
    };
    rq.onsuccess = function () { resolve(rq.result); };
    rq.onerror = function () { reject(rq.error); };
  });
  return dbPromise;
}

function idbPut(meta) {
  return dbOpen().then(function (db) {
    return new Promise(function (resolve, reject) {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(meta);
      tx.oncomplete = function () { resolve(meta); };
      tx.onerror = function () { reject(tx.error); };
    });
  });
}

function idbAll() {
  return dbOpen().then(function (db) {
    return new Promise(function (resolve, reject) {
      const tx = db.transaction(STORE, 'readonly');
      const rq = tx.objectStore(STORE).getAll();
      rq.onsuccess = function () { resolve(rq.result || []); };
      rq.onerror = function () { reject(rq.error); };
    });
  });
}

function idbDel(key) {
  return dbOpen().then(function (db) {
    return new Promise(function (resolve, reject) {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete(key);
      tx.oncomplete = function () { resolve(true); };
      tx.onerror = function () { reject(tx.error); };
    });
  });
}

function idbClear() {
  return dbOpen().then(function (db) {
    return new Promise(function (resolve, reject) {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).clear();
      tx.oncomplete = function () { resolve(true); };
      tx.onerror = function () { reject(tx.error); };
    });
  });
}

/* La identidad es la RUTA sin la firma, igual que en mediadl.js. */
export function downloadKey(url) {
  if (!url) return '';
  const s = String(url);
  const i = s.indexOf('?');
  return i < 0 ? s : s.slice(0, i);
}

function cacheOpen() {
  if (typeof caches === 'undefined') return Promise.resolve(null);
  return caches.open(DL_CACHE).catch(function () { return null; });
}

/* Blob -> archivo en disco. La objectURL se revoca al terminar el clic. */
export function saveBlobToDisk(blob, name) {
  if (!blob) return false;
  const obj = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = obj;
  a.download = name || 'archivo';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(function () { URL.revokeObjectURL(obj); }, 1200);
  return true;
}

/* Guarda los bytes + la ficha. Devuelve la ficha o null si no se pudo. */
export async function saveDownload(url, name, blob) {
  if (!url || !blob) return null;
  const key = downloadKey(url);
  if (!key) return null;
  const c = await cacheOpen();
  if (!c) return null;
  const mime = blob.type || 'application/octet-stream';
  try {
    await c.put(key, new Response(blob, {
      headers: {
        'Content-Type': mime,
        'Content-Length': String(blob.size),
      },
    }));
  } catch (e) {
    return null;                       // cuota llena o Cache API bloqueada
  }
  const meta = {
    key: key,
    name: name || 'archivo',
    size: blob.size,
    mime: mime,
    saved_at: Date.now(),
  };
  try { await idbPut(meta); } catch (e) {}
  return meta;
}

/* Busca los bytes por URL o por clave. */
export async function getDownloadBlob(urlOrKey) {
  const key = downloadKey(urlOrKey);
  if (!key) return null;
  const c = await cacheOpen();
  if (!c) return null;
  try {
    const res = await c.match(key);
    return res ? await res.blob() : null;
  } catch (e) {
    return null;
  }
}

export async function hasDownload(urlOrKey) {
  return !!(await getDownloadBlob(urlOrKey));
}

/* Lista las fichas cuya entrada de caché sigue existiendo. */
export async function listDownloads() {
  let list = [];
  try { list = await idbAll(); } catch (e) { return []; }
  const c = await cacheOpen();
  if (!c) return [];
  const out = [];
  for (let i = 0; i < list.length; i++) {
    const item = list[i];
    try {
      const hit = await c.match(item.key);
      if (hit) out.push(item);
      else await idbDel(item.key).catch(function () {});
    } catch (e) {}
  }
  out.sort(function (a, b) { return (b.saved_at || 0) - (a.saved_at || 0); });
  return out;
}

export async function deleteDownload(urlOrKey) {
  const key = downloadKey(urlOrKey);
  if (!key) return false;
  const c = await cacheOpen();
  if (c) { try { await c.delete(key); } catch (e) {} }
  try { await idbDel(key); } catch (e) {}
  return true;
}

export async function clearDownloads() {
  const c = await cacheOpen();
  if (c) {
    try {
      const keys = await c.keys();
      await Promise.all(keys.map(function (k) { return c.delete(k); }));
    } catch (e) {}
  }
  try { await idbClear(); } catch (e) {}
  return true;
}

/* Vuelve a guardar una descarga ya almacenada, sin tocar la red. */
export async function saveDownloadToDisk(key, name) {
  const blob = await getDownloadBlob(key);
  if (!blob) return false;
  return saveBlobToDisk(blob, name);
}

/* Pide al navegador que no borre el almacenamiento si puede. */
export function requestPersistence() {
  try {
    if (navigator.storage && navigator.storage.persist) {
      return navigator.storage.persist().catch(function () { return false; });
    }
  } catch (e) {}
  return Promise.resolve(false);
}
