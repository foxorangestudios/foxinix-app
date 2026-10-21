"""Subida y descarga de archivos con cuota global de disco."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import math
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import config, db, medialink, ratelimit, security
from ..auth import current_user, pending_user

router = APIRouter(prefix="/api/media", tags=["media"])

ALLOWED_PREFIXES = ("image/", "video/", "audio/", "application/pdf",
                    "text/", "application/zip", "application/octet-stream")

# W37f (auditoría): contenidos "activos" que NO se suben nunca (el texto
# legítimo es text/plain). Un HTML/JS servido en el mismo origen era el
# vector de XSS almacenado vía <script src="/api/media/N">.
_ACTIVE_MIMES = (
    "text/html", "application/xhtml+xml",
    "text/javascript", "application/javascript",
    "application/ecmascript", "text/ecmascript",
    "text/xml", "application/xml",
)


def _serve_mime(mime: str | None) -> str:
    """MIME seguro para SERVIR: los tipos activos viejos se descargan como
    octet-stream en vez de renderizarse (filas pre-W37f incluidas)."""
    m = (mime or "").split(";")[0].strip().lower()
    return "application/octet-stream" if m in _ACTIVE_MIMES else (mime or "application/octet-stream")

# W8/P0: las imágenes se guardan como WebP, con la orientación EXIF
# aplicada, sin metadatos y con un tope de resolución. Antes se
# recodificaba a calidad 95 y tamaño original EN EL EVENT LOOP: una foto
# de 12 MP bloqueaba el server ~10 s y el archivo quedaba enorme. Ahora
# la codificación corre en un hilo (asyncio.to_thread), baja a 2560 px
# por lado y usa un método de compresión razonable.
try:
    from PIL import Image, ImageOps
    _HAVE_PIL = True
except Exception:  # pragma: no cover - sin Pillow en el entorno
    _HAVE_PIL = False

MAX_IMAGE_SIDE = 2560       # suficiente para pantallas 2K; evita 12 MP
MAX_IMAGE_PIXELS = 40_000_000   # bomba de descompresión: se deja el original
IMAGE_QUALITY = 86
IMAGE_METHOD = 4            # 0-6; 4 comprime bien sin el coste de 6


def _encode_webp(
    data: bytes, max_side: int = MAX_IMAGE_SIDE, quality: int = IMAGE_QUALITY
) -> tuple[bytes, int, int] | None:
    """Recodifica a WebP y devuelve (bytes, ancho, alto).

    Pensada para ejecutarse en un hilo: Pillow decodifica y comprime.
    Devuelve None si Pillow no está o la imagen no se puede leer/decodificar
    de forma segura. La orientación EXIF se aplica antes de medir.
    """
    if not _HAVE_PIL:
        return None
    import io

    try:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_IMAGE_PIXELS:
            return None
        im = ImageOps.exif_transpose(im)
        # GIF animados: conservar la animación en WebP animado. El upload
        # normal excluye GIF (se guarda tal cual), pero dejamos la rama
        # por si otro llamador usa el conversor directamente.
        n_frames = getattr(im, "n_frames", 1)
        if n_frames > 1:
            frames = []
            durations = []
            for i in range(n_frames):
                im.seek(i)
                f = im.convert("RGBA")
                if max_side and max(f.size) > max_side:
                    f.thumbnail((max_side, max_side), Image.LANCZOS)
                frames.append(f)
                durations.append(im.info.get("duration", 100))
            out = io.BytesIO()
            frames[0].save(
                out, "WEBP", save_all=True, append_images=frames[1:],
                duration=durations, loop=im.info.get("loop", 0),
                quality=quality, method=IMAGE_METHOD,
            )
            return out.getvalue(), frames[0].width, frames[0].height
        if im.mode not in ("RGB", "RGBA"):
            has_alpha = "A" in im.getbands() or "transparency" in im.info
            im = im.convert("RGBA" if has_alpha else "RGB")
        if max_side and max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "WEBP", quality=quality, method=IMAGE_METHOD)
        return out.getvalue(), im.width, im.height
    except Exception:
        return None


def _to_webp(data: bytes) -> bytes | None:
    """Compatibilidad: solo los bytes WebP (None si no se pudo convertir)."""
    conv = _encode_webp(data)
    return conv[0] if conv else None


def image_size(data: bytes) -> tuple[int, int] | None:
    """W22: (ancho, alto) de una imagen, si Pillow está y la puede leer."""
    if not _HAVE_PIL:
        return None
    import io

    try:
        im = Image.open(io.BytesIO(data))
        return int(im.width), int(im.height)
    except Exception:
        return None


def video_size_path(path: Path) -> tuple[int, int] | None:
    """W51: (ancho, alto) del primer stream de video, vía ffprobe.

    Tiene en cuenta la rotación de los videos de teléfono (un 320×180 con
    rotate=90 se muestra 180×320). No lee el archivo completo en Python:
    ffprobe abre la ruta directamente, así las filas viejas se rellenan
    una sola vez sin cargar 15 MB en memoria.
    """
    if not shutil.which("ffprobe"):
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height:stream_tags=rotate:stream_side_data=rotation",
                "-of", "json", str(path),
            ],
            capture_output=True, timeout=12, text=True,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        streams = (json.loads(proc.stdout) or {}).get("streams") or []
        if not streams:
            return None
        st = streams[0]
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
        if w < 1 or h < 1:
            return None
        rot = 0.0
        for sd in st.get("side_data_list") or []:
            try:
                rot = float(sd.get("rotation") or 0)
            except (TypeError, ValueError):
                rot = 0.0
        if not rot:
            try:
                rot = float((st.get("tags") or {}).get("rotate") or 0)
            except (TypeError, ValueError):
                rot = 0.0
        if abs(int(rot)) % 180 == 90:
            w, h = h, w
        return w, h
    except Exception:
        return None


def row_dims(row: dict[str, Any]) -> dict[str, Any]:
    """W22/W51: {width, height} de la fila media para el payload del mensaje.

    Las filas antiguas (anteriores a esta columna) se calculan una vez
    sobre el archivo y quedan guardadas (backfill perezoso). Las imágenes
    sin resolución conocida (SVG u originals ilegibles) devuelven {} y el
    chat las muestra sin cuadro reservado ni spinner; los videos usan la
    pista de video real (no la resolución del contenedor)."""
    mime = (row["mime"] or "").lower()
    if row["width"] and row["height"]:
        return {"width": row["width"], "height": row["height"]}
    path = config.MEDIA_DIR / row["path"]
    if mime.startswith("image/"):
        try:
            data = path.read_bytes()
        except OSError:
            return {}
        dims = image_size(data)
    elif mime.startswith("video/"):
        dims = video_size_path(path)
    else:
        return {}
    if not dims:
        return {}
    try:
        db.execute(
            "UPDATE media SET width = ?, height = ? WHERE id = ?",
            (dims[0], dims[1], row["id"]),
        )
    except Exception:  # pragma: no cover - solo el cacheo del backfill
        pass
    return {"width": dims[0], "height": dims[1]}


def _auth_media(token: str | None) -> dict:
    """Acceso a archivos: token por header Authorization o por query ?token=
    (QML Image.source no permite headers custom). Devuelve el usuario
    (W37f: el endpoint legacy valida propiedad/membresía)."""
    if not token:
        raise HTTPException(401, "Falta el token de autorización")
    payload = security.decode(token)
    if not payload or payload.get("scope") not in ("full", "pending"):
        raise HTTPException(401, "Token inválido")
    user = db.one("SELECT * FROM users WHERE id = ?", (payload.get("sub", ""),))
    if not user or user["token_version"] != payload.get("tv"):
        raise HTTPException(401, "Sesión expirada")
    return user


# P2: recorrer 20.000 archivos en cada subida costaba ~270 ms. El tamaño
# se cachea 60 s y las rutas de subida/borrado ajustan el valor sin volver
# a recorrer el árbol. Si el server arranca con archivos viejos, el primer
# escaneo los cuenta.
_QUOTA_TTL = 60.0
_quota_lock = threading.Lock()
_quota_cache: dict[str, float] = {"at": 0.0, "size": 0.0}


def media_dir_size(force: bool = False) -> int:
    now = time.monotonic()
    with _quota_lock:
        at = _quota_cache["at"]
        if not force and at and now - at < _QUOTA_TTL:
            return int(_quota_cache["size"])
    total = 0
    for p in config.MEDIA_DIR.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    with _quota_lock:
        _quota_cache["at"] = now
        _quota_cache["size"] = float(total)
    return total


def note_media_size(delta: int) -> None:
    """Mantiene la caché de cuota al día tras escribir/borrar un archivo.

    Si aún no hubo un escaneo, no inventa un total: el próximo
    media_dir_size() lo calculará completo.
    """
    with _quota_lock:
        if _quota_cache["at"]:
            _quota_cache["size"] = max(0.0, _quota_cache["size"] + delta)
            _quota_cache["at"] = time.monotonic()


# W29e: transcodificación al subir (Mypal78/XP-like no trae codecs
# modernos → <video> sale negro). Vídeo → WebM/VP9+Opus y audio → MP3
# con ffmpeg, sólo si está instalado y el archivo pesa ≤15 MB.
_TRANSCODE_MAX = config.MAX_MEDIA_BYTES
_TRANSCODE_TO = 60   # segundos de tope por archivo


def _transcode(data: bytes, mime: str, ext: str) -> tuple[bytes, str, str] | None:
    """None = no aplica (sin ffmpeg, ya en formato o error: se guarda
    el original tal cual)."""
    if not shutil.which("ffmpeg") or len(data) > _TRANSCODE_MAX:
        return None
    if mime.startswith("video/"):
        # Todos los vídeos salen VP9+Opus (los MediaRecorder de FF78
        # son VP8/Opus y el amigo tampoco los reproduce siempre).
        out_mime, out_ext = "video/webm", ".webm"
        args = [
            "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
            "-crf", "34", "-b:v", "0", "-pix_fmt", "yuv420p",
            "-c:a", "libopus", "-b:a", "64k",
        ]
    elif mime.startswith("audio/"):
        if mime in ("audio/mpeg", "audio/mp3"):
            return None           # MP3 ya es el formato universal
        # W51: las notas de voz se graban como WebM/Opus y algunos
        # navegadores modernos (Safari) no lo reproducen. MP3 es el
        # formato principal más compatible. OJO: en XP/Mypal el MP3 usa
        # WMF (no existe); W53 sirve Ogg Vorbis o WAV PCM bajo demanda.
        out_mime, out_ext = "audio/mpeg", ".mp3"
        args = ["-c:a", "libmp3lame", "-q:a", "5", "-vn"]
    else:
        return None
    fin = fout = None
    try:
        fin = tempfile.NamedTemporaryFile(suffix=ext or None, delete=False)
        fin.write(data)
        fin.close()
        fout = tempfile.NamedTemporaryFile(suffix=out_ext, delete=False)
        fout.close()
        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", fin.name, *args, fout.name],
            capture_output=True, timeout=_TRANSCODE_TO,
        )
        if proc.returncode != 0:
            return None
        out = Path(fout.name).read_bytes()
        if not out or len(out) > config.MAX_MEDIA_BYTES:
            return None
        return out, out_mime, out_ext
    except Exception:
        return None
    finally:
        for p in (fin, fout):
            if p is not None:
                try:
                    os.unlink(p.name)
                except OSError:
                    pass


# W51/W53: formatos de respaldo bajo demanda. No se generan en la subida
# (el WebM/MP3 principal sigue siendo el más liviano); solo cuando un
# cliente avisa que no puede decodificar el original, se crea un sidecar
# junto al archivo y se sirve con ?fmt=mp4 / mp3 / ogg / wav. En XP/Mypal
# el MP3 usa WMF, que no existe; Ogg Vorbis y PCM WAV sí son decodificadores
# internos de Firefox y funcionan sin códecs del sistema.
_compat_lock = threading.Lock()

_COMPAT_FORMATS = ("mp4", "mp3", "ogg", "wav")


def _compat_args(fmt: str) -> list[list[str]] | None:
    """Variantes de ffmpeg para un formato de respaldo, de mejor a peor.

    WAV admite dos muestreos: 16 kHz mono para voces (calidad suficiente)
    y 8 kHz mono si el primero supera el tope de 15 MB.
    """
    if fmt == "mp4":
        # 720p máximo: Mypal 78/XP decodifica H.264 en software y un
        # 1080p puede ahogarlo. Baseline + nivel 3.1 es el perfil más
        # compatible; el filtro conserva la proporción y deja pares.
        return [[
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-profile:v", "baseline", "-level", "3.1",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=w='min(1280,iw)':h='min(720,ih)'"
                   ":force_original_aspect_ratio=decrease,"
                   "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        ]]
    if fmt == "mp3":
        return [["-vn", "-c:a", "libmp3lame", "-q:a", "5"]]
    if fmt == "ogg":
        # Vorbis comprimido: el respaldo habitual para Mypal/XP. No usa
        # WMF y conserva bastante mejor la música que un WAV telefónico.
        return [["-vn", "-c:a", "libvorbis", "-q:a", "4"]]
    if fmt == "wav":
        return [
            ["-vn", "-c:a", "pcm_s16le", "-ac", "1", "-ar", "16000"],
            ["-vn", "-c:a", "pcm_s16le", "-ac", "1", "-ar", "8000"],
        ]
    return None


def _compat_file(path: Path, fmt: str) -> Path | None:
    if fmt not in _COMPAT_FORMATS:
        return None
    out = path.with_name(path.name + ".compat." + fmt)
    if out.is_file() and out.stat().st_size > 0:
        return out
    tmp = path.with_name(path.name + ".compat-tmp." + fmt)
    variants = _compat_args(fmt)
    if not variants:
        return None
    with _compat_lock:
        if out.is_file() and out.stat().st_size > 0:
            return out
        if not shutil.which("ffmpeg"):
            return None
        try:
            for args in variants:
                try:
                    proc = subprocess.run(
                        ["ffmpeg", "-y", "-v", "error", "-i", str(path),
                         *args, str(tmp)],
                        capture_output=True, timeout=120,
                    )
                except Exception:
                    return None
                if (proc.returncode != 0 or not tmp.is_file()
                        or tmp.stat().st_size == 0):
                    return None
                if tmp.stat().st_size > config.MAX_MEDIA_BYTES:
                    try:
                        tmp.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                os.replace(tmp, out)
                note_media_size(out.stat().st_size)
                return out
            return None
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def remove_media_files(path: Path) -> None:
    """Borra el original y sus derivados (.thumb.webp, .compat.*)."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        for extra in path.parent.glob(path.name + ".*"):
            try:
                extra.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


@router.post("", status_code=201)
async def upload(file: UploadFile, user: dict = Depends(pending_user)) -> dict[str, Any]:
    # Nota: pending_user permite subir el avatar antes de verificar el correo.
    # W14: límite de subidas (~12 en ráfaga, 1/5 s sostenido): el disco es caro.
    espera = ratelimit.UPLOADS.take(user["id"])
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": math.ceil(espera)})
    mime = file.content_type or "application/octet-stream"
    if not mime.startswith(ALLOWED_PREFIXES):
        raise HTTPException(415, "Tipo de archivo no permitido")
    # W37f: ni HTML ni JS (ni XML activo) — texto plano sí (text/plain).
    if mime.split(";")[0].strip().lower() in _ACTIVE_MIMES:
        raise HTTPException(415, "Tipo de archivo no permitido")

    # Validar ANTES de leer el body (evita buffer de 50 MB innecesario)
    too_big = f"El archivo supera los {config.MAX_MEDIA_BYTES // (1024*1024)} MB"
    if file.size is not None and file.size > config.MAX_MEDIA_BYTES:
        raise HTTPException(413, too_big)
    cl = file.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > config.MAX_MEDIA_BYTES:
        raise HTTPException(413, too_big)

    data = await file.read()
    if not data:
        raise HTTPException(400, "Archivo vacío")

    # W8/P0: las imágenes se convierten a WebP en un HILO (no en el event
    # loop), con tope de 2560 px. SVG y lo que Pillow no pueda leer quedan
    # como están. W28g: los GIF se guardan tal cual — convertirlos a WebP
    # los dejaría quietos en el primer fotograma.
    conv_mime = mime
    ext = Path(file.filename or "").suffix[:10].lower()
    w = h = None
    if mime.startswith("image/") and mime not in ("image/svg+xml", "image/gif"):
        conv = await asyncio.to_thread(_encode_webp, data)
        if conv is not None:
            data, w, h = conv
            mime = "image/webp"
            ext = ".webp"

    # W29e: vídeo → WebM/VP9+Opus y audio → MP3 (bloqueante pero con
    # tope de 15 MB/60 s; corre en thread para no congelar el loop).
    if mime.startswith(("video/", "audio/")):
        tc = await asyncio.to_thread(_transcode, data, mime, ext)
        if tc is not None:
            data, mime, ext = tc

    if len(data) > config.MAX_MEDIA_BYTES:
        raise HTTPException(413, f"El archivo supera los {config.MAX_MEDIA_BYTES // (1024*1024)} MB")

    used = media_dir_size()
    if used + len(data) > config.MEDIA_QUOTA:
        raise HTTPException(
            507,
            f"Cuota de almacenamiento llena ({config.MEDIA_QUOTA // (1024**2)} MB). "
            "Contacta al administrador.",
        )

    if not ext:
        ext = mimetypes.guess_extension(conv_mime) or ""
    rel = f"{user['id']}/{uuid.uuid4().hex}{ext}"
    dest = config.MEDIA_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    note_media_size(len(data))

    # W51: resolución del video ya transcodificado, para que el chat
    # reserve el marco ANTES de descargar el archivo (igual que las
    # imágenes desde W22). En un hilo: ffprobe no bloquea el event loop.
    if mime.startswith("video/"):
        vd = await asyncio.to_thread(video_size_path, dest)
        if vd:
            w, h = vd

    slug = secrets.token_hex(16)  # W11: nombre aleatorio p/ URL firmada
    # W22: la resolución de la imagen viaja en el mensaje para que el chat
    # reserve el cuadro con el spinner antes de cargar el archivo. Si ya
    # convertimos, _encode_webp nos dio las dimensiones finales.
    if mime.startswith("image/") and (not w or not h):
        dims = await asyncio.to_thread(image_size, data)
        if dims:
            w, h = dims
    media_id = db.execute(
        "INSERT INTO media (owner_id, path, mime, size, name, slug, width, height, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user["id"], rel, mime, len(data), (file.filename or "archivo")[:200],
         slug, w, h, int(time.time())),
    )
    return {
        "id": media_id,
        "url": medialink.signed_url("file", slug, ext),
        "mime": mime,
        "size": len(data),
        "name": file.filename or "archivo",
        "width": w,
        "height": h,
    }


@router.get("/{media_id}")
def download(media_id: int, token: str | None = None) -> FileResponse:
    user = _auth_media(token)
    row = db.one("SELECT * FROM media WHERE id = ?", (media_id,))
    if not row:
        raise HTTPException(404, "Archivo no encontrado")
    # W37f (auditoría): este endpoint legacy servía CUALQUIER archivo a
    # cualquier token autenticado (IDOR). Ahora sólo lo baja el DUEÑO,
    # un MIEMBRO del chat donde se envió, o alguien viendo un chat que
    # lo usa de avatar.
    if row["owner_id"] != user["id"]:
        sent = db.one(
            "SELECT 1 AS x FROM messages"
            " WHERE media_id = ? AND chat_id IN"
            " (SELECT chat_id FROM chat_members WHERE user_id = ?)"
            " LIMIT 1",
            (media_id, user["id"]),
        )
        avatar = db.one(
            "SELECT 1 AS x FROM chats WHERE avatar_media_id = ?"
            " AND id IN (SELECT chat_id FROM chat_members WHERE user_id = ?)"
            " LIMIT 1",
            (media_id, user["id"]),
        )
        if not sent and not avatar:
            raise HTTPException(404, "Archivo no encontrado")
    path = config.MEDIA_DIR / row["path"]
    if not path.is_file():
        raise HTTPException(404, "Archivo no encontrado en disco")
    # W37f: MIME neutralizado + filename SIEMPRE (aunque esté vacío):
    # Starlette responde Content-Disposition: attachment → abrir la URL en
    # una pestaña descarga en vez de ejecutar (los <img>/<video> del
    # cliente ignoran este header).
    return FileResponse(
        path,
        media_type=_serve_mime(row["mime"]),
        filename=row["name"] or "archivo",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/quota/stats")
def quota_stats(user: dict = Depends(current_user)) -> dict[str, Any]:
    used = media_dir_size()
    return {
        "used_bytes": used,
        "quota_bytes": config.MEDIA_QUOTA,
        "percent": round(used * 100 / config.MEDIA_QUOTA, 2),
    }


# --------------------------------------------------------------- W11: URL firmada
# Sin prefijo /api/media y sin token de cuenta: la URL sola (slug aleatorio
# + firma con caducidad) es la credencial. El slug se valida contra la firma
# ANTES de mirar la base, así que no hay enumeración posible.
pub = APIRouter(tags=["media"])


def _ensure_thumb(path: Path) -> Path | None:
    """Miniatura (máx. 480 px) generada UNA vez y cacheada al lado del original.

    W15: los avatares/imágenes se piden con ?thumb=1 para que carguen de
    una (el cliente difumina esta copia chica hasta descargar el original).
    Escritura atómica (tmp + rename) para que dos primeras peticiones
    simultáneas no sirvan un archivo a medias.
    """
    if not _HAVE_PIL:
        return None
    t = path.with_name(path.stem + ".thumb.webp")
    if t.is_file():
        return t
    try:
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
        im.thumbnail((480, 480))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        tmp = path.with_name(path.stem + ".thumb.tmp.webp")
        im.save(tmp, "WEBP", quality=70)
        os.replace(tmp, t)
        try:
            note_media_size(t.stat().st_size)
        except OSError:
            pass
    except Exception:
        return None
    return t if t.is_file() else None


@pub.get("/media/{kind}/{fname}")
def download_signed(kind: str, fname: str, exp: int | None = None,
                    sig: str | None = None, thumb: int = 0,
                    fmt: str | None = None) -> FileResponse:
    """Descarga con firma (?exp=&sig=). kind: 'profile' | 'file'.

    W15: ?thumb=1 sirve una miniatura (si es imagen); si no aplica,
    sigue sirviendo el original.
    W51/W53: ?fmt=mp4|mp3|ogg|wav sirve un derivado compatible para
    navegadores que no decodifican el original (Mypal 78/XP). Ogg y WAV
    evitan los decodificadores WMF que no existen en XP. Se genera una
    sola vez y queda cacheado al lado del original.
    """
    if kind not in ("profile", "file"):
        raise HTTPException(404, "Archivo no encontrado")
    slug = fname.split(".", 1)[0]
    if not security.verify_media_sig(slug, exp, sig):
        raise HTTPException(403, "Enlace de media inválido o caducado")
    row = db.one("SELECT * FROM media WHERE slug = ?", (slug,))
    if not row:
        raise HTTPException(404, "Archivo no encontrado")
    path = config.MEDIA_DIR / row["path"]
    if not path.is_file():
        raise HTTPException(404, "Archivo no encontrado en disco")
    mime = (row["mime"] or "").lower()
    served_mime = row["mime"]
    out_name = row["name"] or "archivo"
    if fmt in _COMPAT_FORMATS:
        if fmt == "mp4" and not mime.startswith("video/"):
            raise HTTPException(404, "Formato no aplicable")
        if fmt in ("mp3", "ogg", "wav") and not mime.startswith(
                ("audio/", "video/")):
            raise HTTPException(404, "Formato no aplicable")
        compat = _compat_file(path, fmt)
        if not compat:
            raise HTTPException(503, "No se pudo preparar el formato compatible")
        path = compat
        served_mime = {
            "mp4": "video/mp4",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "wav": "audio/wav",
        }[fmt]
        out_name = (Path(out_name).stem or "archivo") + "." + fmt
    elif thumb and mime.startswith("image/"):
        t = _ensure_thumb(path)
        if t:
            path = t
    # W37f: igual que el endpoint legacy — MIME neutralizado y filename
    # siempre presente (attachment). Los <img>/<video>/<audio> del
    # cliente ignoran el Content-Disposition.
    return FileResponse(
        path,
        media_type=_serve_mime(served_mime),
        filename=out_name,
        headers={"Cache-Control": "private, max-age=86400"},
    )
