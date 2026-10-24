"""Foxinix server — FastAPI + WebSockets + SQLite."""
from __future__ import annotations

import asyncio
import logging
import os
import time

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import cleanup, config, db
from .realtime import hub
from .routers import auth as auth_router
from .routers import assets, chats, gifs, links, media, people, users, ws

logging.basicConfig(
    level=getattr(logging, os.environ.get("FOXMSG_LOG", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="Foxinix server",
    version="0.1.0",
    docs_url=None,          # W14: sin swagger expuesto (menos superficie)
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # cliente desktop; la auth es por Bearer (sin cookies)
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def reject_big_bodies(request, call_next):
    """Rechaza bodies gigantes ANTES de que FastAPI los lea a memoria.

    - /api/media: tope de subida (MAX_MEDIA_BYTES).
    - El resto (JSON): tope chico de 64 KB — ningún endpoint legítimo
      necesita más y frena buffers de cientos de MB por request.
    """
    if request.method in ("POST", "PUT", "PATCH"):
        cl = request.headers.get("content-length")
        # W37f (auditoría): un body CHUNKED no trae content-length y
        # esquivaba todos los topes. Los clientes legítimos (fetch/XHR/
        # urllib) siempre mandan el largo — se rechaza con 411.
        if request.headers.get("transfer-encoding"):
            from fastapi.responses import JSONResponse

            return JSONResponse(
                status_code=411,
                content={"detail": "Falta la longitud del cuerpo"},
            )
        if cl and cl.isdigit():
            # W45c: la foto de grupo viaja como multipart a
            # /api/chats/{id}/avatar. Antes caía en el límite JSON de 64 KB
            # y una foto normal (cientos de KB) devolvía 413 aunque el
            # endpoint acepta MAX_MEDIA_BYTES.
            path = request.url.path
            is_media = (
                path == "/api/media"
                or (path.startswith("/api/chats/") and path.endswith("/avatar"))
            )
            # margen para el boundary/multipart: el endpoint vuelve a medir
            # los bytes reales del archivo y aplica MAX_MEDIA_BYTES exacto.
            limit = (config.MAX_MEDIA_BYTES + 512 * 1024) if is_media else 64 * 1024
            if int(cl) > limit:
                from fastapi.responses import JSONResponse

                if limit > 1024 * 1024:
                    detail = f"El archivo supera los {limit // (1024 * 1024)} MB"
                else:
                    detail = "Cuerpo de la petición demasiado grande"
                return JSONResponse(status_code=413, content={"detail": detail})
    return await call_next(request)


# W14: cabeceras de seguridad en TODA respuesta.
# Nota: 'unsafe-eval' en script-src es necesario porque el build global de
# Vue compila los templates en runtime (new Function). Se MANTIENE sin
# 'unsafe-inline': los scripts inline siguen bloqueados (el vector XSS
# principal) y el resto del CSP endurece el resto de recursos.
_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline';"
    # W45f: las tarjetas de enlace muestran portadas externas; sin https:
    # el navegador las bloqueaba y la tarjeta quedaba sin imagen.
    " img-src 'self' data: blob: https:; media-src 'self' blob:;"
    # blob: en connect-src: resolveDur (notas de voz viejas, W13) hace fetch
    # del src; W15 sirve el audio como blob, y sin blob: el CSP lo bloqueaba.
    " connect-src 'self' ws: wss: blob:; worker-src 'self' blob:;"
    " font-src 'self'; manifest-src 'self'; object-src 'none';"
    " frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Estáticos: revalidación por ETag (304 barato) + endurecimiento.

    La CSP es estricta ('self', sin inline scripts): el único <script>
    inline que existía (tema pre-paint) vive ahora en /static/js/boot.js.
    """
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Permissions-Policy"] = (
        "camera=(self), geolocation=(), payment=(), usb=(), microphone=(self)"
    )
    resp.headers["Content-Security-Policy"] = _CSP
    resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    return resp


app.include_router(auth_router.router)
app.include_router(users.router)
app.include_router(chats.router)
app.include_router(people.router)
app.include_router(media.router)
app.include_router(media.pub)
app.include_router(links.router)   # W35c: vista previa de enlaces
app.include_router(gifs.router)    # W36k: favoritos de GIFs
app.include_router(assets.router)  # W61: biblioteca de GIFs/stickers subidos
app.include_router(ws.router)

# ------------------------------------------------ frontend web (estáticos)
# Por defecto: server/web junto a app/ (local: <repo>/server/web,
# remoto: /home/FoxOrange/chat-server/web). FOXMSG_WEB_DIR lo sobreescribe.
WEB_DIR = Path(
    os.environ.get("FOXMSG_WEB_DIR")
    or Path(__file__).resolve().parents[1] / "web"
)
INDEX_HTML = WEB_DIR / "index.html"

if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="web")


@app.get("/")
def index() -> FileResponse:
    """SPA: el shell de la app web (rutas por hash, sin catch-all)."""
    if not INDEX_HTML.is_file():
        return Response(status_code=404, media_type="text/plain", content="web no desplegado")
    return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def service_worker() -> FileResponse:
    """El SW va en la raíz para que su scope sea '/' (shell offline + caché)."""
    if not (WEB_DIR / "sw.js").is_file():
        return Response(status_code=404, media_type="text/plain", content="web no desplegado")
    return FileResponse(
        WEB_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest")
def webmanifest() -> FileResponse:
    if not (WEB_DIR / "manifest.webmanifest").is_file():
        return Response(status_code=404, media_type="text/plain", content="web no desplegado")
    return FileResponse(
        WEB_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/favicon.ico")
def favicon() -> Response:
    """Evita el 404 ruidoso: el ícono real lo declara index.html."""
    return Response(status_code=204)

_started_at = int(time.time())


@app.on_event("startup")
async def _startup() -> None:
    db.init_db()
    hub.bind_loop()
    asyncio.create_task(cleanup.cleanup_loop())


@app.get("/api/health")
def health() -> dict:
    # W37f (auditoría): no se publica el nº de usuarios ni la cuota —
    # health sólo sirve a "¿está vivo y qué versión corre?".
    return {
        "ok": True,
        "version": app.version,
        "uptime": int(time.time()) - _started_at,
    }


# ATENCIÓN: el catch-all de la SPA va AL FINAL — Starlette compara las
# rutas en orden de registro y esto no debe tapar /api/* ni /static/*.
@app.get("/{full_path:path}")
def spa(full_path: str):
    """W22: rutas reales de la SPA (/app/user/5, /login…, sin #).

    Cualquier GET que no sea API/media/estático sirve el shell y el router
    de cliente resuelve. Los API desconocidos siguen siendo 404 JSON."""
    # W45: FastAPI ya no expone Swagger/OpenAPI (docs_url=None), pero el
    # catch-all de la SPA los convertía en un 200 con el shell. Un 404 real
    # evita que /docs y /openapi.json parezcan endpoints válidos.
    if full_path in ("docs", "redoc", "openapi.json") or full_path.startswith(
        ("docs/", "redoc/", "api/", "media/", "static/")
    ):
        return JSONResponse({"detail": "No encontrado"}, status_code=404)
    if not INDEX_HTML.is_file():
        return Response(status_code=404, media_type="text/plain", content="web no desplegado")
    return FileResponse(INDEX_HTML, headers={"Cache-Control": "no-cache"})
