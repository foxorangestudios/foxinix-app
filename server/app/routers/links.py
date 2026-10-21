"""W35c: vista previa de enlaces (unfurl de la "portada" de una página).

El cliente pide la metadata de una URL (og:title, descripción, imagen,
favicon) para dibujar la tarjeta bajo un mensaje con enlaces. El
servidor sólo hace GET, sólo acepta http/https, corta cada descarga en
1,5 MB, sigue como mucho 4 redirects (validando el host de cada salto)
y cachea el resultado 7 días en la DB.

Seguridad (SSRF):
  - con FOXMSG_PUBLIC_URL fijada (prod) se bloquean loopback,
    privadas, link-local y redes reservadas; sólo el host propio y los
    hosts públicos pasan.
  - sin PUBLIC_URL (local/tests) se permite loopback para que las
    suites puedan unfurl contra su propio servidor de prueba.
  - W37f: el hostname se RESUELVE (getaddrinfo) y se exige que TODAS
    sus IPs sean globales — cierra el SSRF por dominios que apuntan a
    169.254.169.254/privadas y por notación numérica ("http://2130706433/",
    "http://127.1/"). Residual documentado: TOCTOU/DNS-rebinding entre
    la validación y la conexión de httpx (ventana mínima; mitigación
    completa exigiría conectar por IP con Host fijo)."""
from __future__ import annotations

import html as html_mod
import ipaddress
import re
import socket
import time
import urllib.parse
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import config, db, ratelimit
from ..auth import current_user

router = APIRouter(prefix="/api", tags=["links"])

MAX_BYTES = 1_500_000          # sólo leemos el HTML de la portada
TTL = 7 * 86400                # segundos de caché por URL
_UA = "FoxinixLink/1.0 (+https://chat.foxinix.qzz.io)"

_META_RE = re.compile(r"<meta\s[^>]*>", re.I)
_LINK_RE = re.compile(r"<link\s[^>]*>", re.I)
_ATTR_RE = re.compile(r"([a-zA-Z:_-]+)\s*=\s*([\"'])(.*?)\2", re.S)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


class PrevIn(BaseModel):
    url: str


def _ip_global(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _host_ok(host: str) -> bool:
    """True si se le puede hacer fetch a este host (ver docstring).

    W37f: además del filtro de hosts internos, el hostname se RESUELVE
    y TODAS sus IPs deben ser globales — antes un dominio apuntando a
    169.254.169.254 (o notación numérica como http://2130706433/)
    pasaba sin más y se conectaba a la metadata/loopback."""
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return False
    h = h.strip("[]")
    own = ""
    if config.PUBLIC_URL:
        own = (urllib.parse.urlparse(config.PUBLIC_URL).hostname or "").lower()
    if h == own:
        return True                       # su propio host (inofensivo)
    if not config.PUBLIC_URL and h in ("localhost", "127.0.0.1", "::1"):
        return True                       # local/tests
    if h == "localhost" or h.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        infos = socket.getaddrinfo(h, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False                      # no resuelve → no se prueba
    if not infos:
        return False
    for info in infos:
        if not _ip_global(info[4][0]):
            return False                  # privada/metadata/loopback: corta
    return True


def _attrs(tag: str) -> dict[str, str]:
    return {m.group(1).lower(): html_mod.unescape(m.group(3))
            for m in _ATTR_RE.finditer(tag)}


def _clean(s: str, n: int) -> str:
    return re.sub(r"\s+", " ", s).strip()[:n]


def _abs(base: str, u: str) -> str:
    """URL absoluta sólo si termina en http/https (nada de javascript:)."""
    if not u:
        return ""
    full = urllib.parse.urljoin(base, u)
    if urllib.parse.urlparse(full).scheme not in ("http", "https"):
        return ""
    return full


def _parse_html(body: str, base: str) -> dict[str, str]:
    metas: dict[str, str] = {}
    for m in _META_RE.finditer(body):
        a = _attrs(m.group(0))
        key = (a.get("property") or a.get("name") or "").lower()
        if key.startswith(("og:", "twitter:")) or key == "description":
            if "content" in a and key not in metas:
                metas[key] = a["content"]
    tm = _TITLE_RE.search(body)
    title = (metas.get("og:title") or metas.get("twitter:title")
             or (html_mod.unescape(tm.group(1)) if tm else ""))
    desc = (metas.get("og:description") or metas.get("twitter:description")
            or metas.get("description") or "")
    image = _abs(base, metas.get("og:image") or metas.get("twitter:image") or "")
    icon = ""
    for m in _LINK_RE.finditer(body):
        a = _attrs(m.group(0))
        rel = (a.get("rel") or "").lower()
        if "icon" in rel:
            icon = _abs(base, a.get("href") or "")
            if icon:
                break
    site = metas.get("og:site_name") or ""
    if not site:
        site = urllib.parse.urlparse(base).hostname or ""
    return {"title": _clean(html_mod.unescape(title), 200),
            "desc": _clean(html_mod.unescape(desc), 400),
            "image": image, "icon": icon, "site": _clean(site, 120)}


def _fetch(client: httpx.Client, url: str, depth: int = 0) -> dict[str, Any]:
    try:
        with client.stream("GET", url, follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                nxt = urllib.parse.urljoin(url, r.headers.get("location", ""))
                host = urllib.parse.urlparse(nxt).hostname or ""
                if depth >= 4 or not _host_ok(host):
                    raise HTTPException(400, "Redirección no permitida")
                return _fetch(client, nxt, depth + 1)
            if r.status_code >= 400:
                raise HTTPException(502, "La página respondió con error")
            final = str(r.url)
            ctype = (r.headers.get("content-type") or "").lower()
            if ctype.startswith("image/"):
                return {"type": "image", "url": final}
            cl = r.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > MAX_BYTES:
                raise HTTPException(413, "La página es demasiado grande")
            if "html" not in ctype and "xhtml" not in ctype:
                return {"type": "link", "url": final}
            buf = b""
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    break
    except httpx.HTTPError:
        raise HTTPException(502, "No se pudo leer la página")
    prev = _parse_html(buf.decode("utf-8", "replace"), final)
    prev["type"] = "page"
    prev["url"] = final
    return prev


@router.post("/link-preview")
def link_preview(body: PrevIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    """W35c: "portada" de un enlace (título/descripción/imagen)."""
    u = (body.url or "").strip()[:2000]
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "Sólo se aceptan enlaces http/https")
    if not _host_ok(p.hostname):
        raise HTTPException(400, "Enlace no permitido")
    espera = ratelimit.LINKPREVIEWS.take(user["id"])
    if espera > 0:
        raise HTTPException(429, detail={"retry_after": espera})

    now = time.time()
    row = db.get_db().execute(
        "SELECT * FROM link_previews WHERE url = ?", (u,)).fetchone()
    if row and now - row["fetched_at"] < TTL:
        return {"type": row["type"], "url": row["final_url"],
                "title": row["title"], "desc": row["desc"],
                "image": row["image"], "icon": row["icon"], "site": row["site"]}

    with httpx.Client(timeout=httpx.Timeout(8.0, connect=5.0),
                      follow_redirects=False, trust_env=False,
                      headers={"User-Agent": _UA}) as client:
        prev = _fetch(client, u)

    db.execute(
        "INSERT INTO link_previews (url, final_url, type, title, desc, image,"
        " icon, site, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(url) DO UPDATE SET final_url=excluded.final_url,"
        " type=excluded.type, title=excluded.title, desc=excluded.desc,"
        " image=excluded.image, icon=excluded.icon, site=excluded.site,"
        " fetched_at=excluded.fetched_at",
        (u, prev["url"], prev["type"], prev.get("title", ""),
         prev.get("desc", ""), prev.get("image", ""), prev.get("icon", ""),
         prev.get("site", ""), now))
    return prev
