"""Autenticación: registro, perfil, verificación de correo, login, reset.

Flujo definido:
  1. Registro (correo + usuario + contraseña) -> crea cuenta NO verificada
  2. Perfil (nombre opcional, foto, bio opcional)
  3. Código de 6 dígitos al correo: 10 min de validez, reenvío cada 1 min,
     5 intentos fallidos lo invalidan. Verificado -> acceso inmediato.
  4. Sin verificar a los 5 días -> borrado permanente (task en main).
  5. Login con usuario O correo + contraseña.
  6. "Olvidé mi contraseña" -> mismo esquema de código.
"""
from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import config, db, mailer, medialink, security
from ..auth import current_user, pending_user
from ..realtime import hub
from ..schemas import (
    ChangePasswordIn,
    DeleteAccountIn,
    EmailChangeIn,
    ForgotIn,
    LoginIn,
    LogoutIn,
    ProfileIn,
    RefreshIn,
    RegisterIn,
    ResendIn,
    ResetIn,
    UsernameIn,
    VerifyIn,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# W59: el usuario es también el identificador de acceso. Se puede cambiar,
# pero solo una vez cada 12 horas y confirmando la contraseña actual.
USERNAME_COOLDOWN = 12 * 60 * 60

# Rate limit simple en memoria: clave -> (ventana_inicio, contador)
_rate: dict[str, tuple[int, int]] = {}


def _rate_limit(key: str, max_hits: int = config.RATE_MAX) -> None:
    now = int(time.time())
    if len(_rate) > 8192:      # W14: poda defensiva (muchas IPs distintas)
        # W37f (auditoría): _rate.clear() borraba TODOS los contadores —
        # un atacante inundando con claves distintas reiniciaba su propio
        # límite. Ahora sólo se descartan ventanas ya vencidas.
        for k in [k for k, v in _rate.items() if now - v[0] > config.RATE_WINDOW]:
            del _rate[k]
        if len(_rate) > 8192:  # siguen llenas: fuera las más viejas
            for k in sorted(_rate, key=lambda k: _rate[k][0])[:len(_rate) - 8192]:
                del _rate[k]
    start, count = _rate.get(key, (now, 0))
    if now - start > config.RATE_WINDOW:
        start, count = now, 0
    count += 1
    _rate[key] = (start, count)
    if count > max_hits:
        raise HTTPException(429, "Demasiados intentos, inténtalo de nuevo más tarde")


def _client_ip(request: Request) -> str:
    # Detrás de un proxy de confianza, request.client.host es el proxy y
    # todos los usuarios compartirían el mismo cubo de rate limit.
    # FOXMSG_TRUST_PROXY=1 activa X-Forwarded-For (solo el primer salto).
    if config.TRUST_PROXY:
        xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if xff:
            return xff
    return request.client.host if request.client else "?"


def _public_user(u: dict[str, Any]) -> dict[str, Any]:
    avatar = None
    if u.get("avatar_media_id"):
        avatar = medialink.media_url_by_id(u["avatar_media_id"], "profile")
    banner = None
    if u.get("banner_media_id"):
        banner = medialink.media_url_by_id(u["banner_media_id"], "profile")
    return {
        "id": u["id"],
        "username": u["username"],
        "display_name": u["display_name"] or u["username"],
        "bio": u["bio"],
        "email": u["email"],          # solo en respuestas de la propia cuenta
        "status_text": u["status_text"],
        "status_preset": u.get("status_preset", ""),
        "avatar_url": avatar,
        "banner_url": banner,
        "username_changed_at": int(u.get("username_changed_at") or 0),
        "email_verified": bool(u["email_verified"]),
    }


def _peer_user(u: dict[str, Any]) -> dict[str, Any]:
    """Perfil para eventos WS hacia otros usuarios (W37f): SIN email ni
    email_verified — esos campos sólo los ve la propia cuenta."""
    out = _public_user(u)
    out.pop("email", None)
    out.pop("email_verified", None)
    out.pop("username_changed_at", None)
    return out


def _tokens(u: dict[str, Any]) -> dict[str, str]:
    verified = bool(u["email_verified"])
    return {
        "access": security.issue_access(u["id"], verified, u["token_version"]),
        "refresh": security.issue_refresh(u["id"], verified, u["token_version"]),
    }


# W30e: el refresh viaja en una cookie HttpOnly (el access sigue viajando
# en la respuesta, en memoria del cliente). Así un XSS no puede leer el
# refresh de localStorage ni mandarlo a otro lado: la cookie solo la
# manda el navegador a /api/auth/* del mismo origen.
REFRESH_COOKIE = "fm_rt"


def _set_refresh_cookie(
    response: Response, request: Request, refresh: str
) -> None:
    proto = request.headers.get("x-forwarded-proto", "")
    secure = proto.split(",")[0].strip() == "https" or request.url.scheme == "https"
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=config.REFRESH_TTL,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/api/auth",
    )


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}{'*' * max(len(name) - 2, 1)}@{domain}"


def _get_user_by(field: str, value: str) -> dict[str, Any] | None:
    if field not in ("email", "username", "id"):
        raise ValueError("campo inválido")
    return db.one(f"SELECT * FROM users WHERE {field} = ?", (value,))


def _find_identifier(identifier: str) -> dict[str, Any] | None:
    identifier = identifier.strip()
    if "@" in identifier:
        return _get_user_by("email", identifier.lower())
    return _get_user_by("username", identifier.lower())


def _issue_code(user_id: int, purpose: str, to_email: str | None = None) -> dict[str, Any]:
    """Genera código nuevo (invalida anteriores del mismo propósito).
    to_email: destino distinto al correo actual (cambio de correo, W6)."""
    now = int(time.time())
    code = security.new_code()
    with db.tx() as conn:
        conn.execute(
            "DELETE FROM email_codes WHERE user_id = ? AND purpose = ?",
            (user_id, purpose),
        )
        conn.execute(
            "INSERT INTO email_codes (user_id, purpose, code_hash, expires_at, attempts, created_at)"
            " VALUES (?, ?, ?, ?, 0, ?)",
            (user_id, purpose, security.hash_code(code), now + config.CODE_TTL, now),
        )
    user = _get_user_by("id", str(user_id))
    if not to_email:
        to_email = user["email"]
    # W27g: el correo saluda con el usuario ("Hola, [usuario]").
    ok = mailer.send_code(to_email, code, purpose, user["username"])
    if not ok:
        raise HTTPException(502, "No se pudo enviar el correo de verificación")
    return {
        "expires_in": config.CODE_TTL,
        "resend_after": config.CODE_RESEND_COOLDOWN,
        "attempts_left": config.CODE_MAX_ATTEMPTS,
    }


def _check_cooldown(user_id: int, purpose: str) -> int:
    """Devuelve 0 si puede enviar; si no, los segundos restantes."""
    row = db.one(
        "SELECT created_at FROM email_codes WHERE user_id = ? AND purpose = ?"
        " ORDER BY created_at DESC LIMIT 1",
        (user_id, purpose),
    )
    if not row:
        return 0
    elapsed = int(time.time()) - row["created_at"]
    return max(0, config.CODE_RESEND_COOLDOWN - elapsed)


# ---------------------------------------------------------------- registro

def _purge_unverified(conn, u: dict[str, Any]) -> list[tuple[str, int]]:
    """Descarta una cuenta sin verificar (registro abandonado o cancelado al
    recargar). No puede tener chats ni mensajes (scope full), pero sí archivos.
    Devuelve los archivos para borrarlos DESPUÉS del commit: si el registro
    nuevo falla y la transacción hace rollback, la cuenta y su media siguen
    vivas y no deben quedar con filas apuntando a archivos ya borrados."""
    paths = [
        (str(m[0]), int(m[1] or 0))
        for m in conn.execute(
            "SELECT path, size FROM media WHERE owner_id = ?", (u["id"],)
        ).fetchall()
    ]
    conn.execute("DELETE FROM media WHERE owner_id = ?", (u["id"],))
    conn.execute("DELETE FROM users WHERE id = ?", (u["id"],))
    return paths


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response) -> dict[str, Any]:
    _rate_limit(f"reg:{_client_ip(request)}", max_hits=10)

    # Un registro sin verificar no prueba la propiedad de nada: si el correo o
    # el usuario pertenecen a una cuenta pendiente (registro abandonado o
    # cancelado por recarga), se descarta y se crea la nueva con un código
    # recién enviado. Las cuentas verificadas jamás se reemplazan (409).
    old_email = _get_user_by("email", body.email)
    old_name = _get_user_by("username", body.username)
    if old_email and old_email["email_verified"]:
        raise HTTPException(409, "Ese correo ya está registrado")
    if old_name and old_name["email_verified"]:
        raise HTTPException(409, "Ese usuario ya está en uso")
    stale = {
        u["id"]: u
        for u in (old_email, old_name)
        if u and not u["email_verified"]
    }

    now = int(time.time())
    removed_media: list[tuple[str, int]] = []
    try:
        with db.tx() as conn:
            for u in stale.values():
                removed_media.extend(_purge_unverified(conn, u))
            cur = conn.execute(
                "INSERT INTO users (email, username, password_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (body.email, body.username, security.hash_password(body.password), now),
            )
            user_id = cur.lastrowid
    except Exception:
        raise HTTPException(409, "Ese correo o usuario ya está registrado")

    # Recién ahora, con la transacción confirmada, se pueden borrar los
    # archivos de las cuentas descartadas (ver _purge_unverified).
    if removed_media:
        from . import media as media_mod   # perezoso: evita el ciclo
        for rel, size in removed_media:
            try:
                media_mod.remove_media_files(config.MEDIA_DIR / rel)
                media_mod.note_media_size(-size)
            except OSError:
                pass

    info = _issue_code(user_id, "verify")
    user = _get_user_by("id", str(user_id))
    tokens = _tokens(user)
    _set_refresh_cookie(response, request, tokens["refresh"])
    return {
        "user": _public_user(user),
        "tokens": tokens,
        "verification": {
            "required": True,
            "email_masked": _mask_email(user["email"]),
            **info,
        },
    }


# ---------------------------------------------------------------- perfil

@router.put("/profile")
def update_profile(body: ProfileIn, user: dict = Depends(pending_user)) -> dict[str, Any]:
    sets, params = [], []
    if body.display_name is not None:
        sets.append("display_name = ?")
        params.append(body.display_name)
    if body.bio is not None:
        sets.append("bio = ?")
        params.append(body.bio)
    if body.status_text is not None:
        sets.append("status_text = ?")
        params.append(body.status_text)
    old_preset = user.get("status_preset") or ""
    if body.status_preset is not None:
        sets.append("status_preset = ?")
        params.append(body.status_preset)
    if "avatar_media_id" in body.model_fields_set:
        if body.avatar_media_id is None:
            sets.append("avatar_media_id = NULL")  # quitar avatar
        else:
            media = db.one("SELECT * FROM media WHERE id = ?", (body.avatar_media_id,))
            if not media or media["owner_id"] != user["id"]:
                raise HTTPException(400, "Archivo de avatar inválido")
            if not (media["mime"] or "").startswith("image/"):
                raise HTTPException(400, "El avatar debe ser una imagen")
            sets.append("avatar_media_id = ?")
            params.append(body.avatar_media_id)
    if "banner_media_id" in body.model_fields_set:
        if body.banner_media_id is None:
            sets.append("banner_media_id = NULL")  # quitar portada
        else:
            media = db.one("SELECT * FROM media WHERE id = ?", (body.banner_media_id,))
            if not media or media["owner_id"] != user["id"]:
                raise HTTPException(400, "Archivo de portada inválido")
            if not (media["mime"] or "").startswith("image/"):
                raise HTTPException(400, "La portada debe ser una imagen")
            sets.append("banner_media_id = ?")
            params.append(body.banner_media_id)
    if not sets:
        return {"user": _public_user(user)}
    params.append(user["id"])
    old_media = {
        int(x) for x in (user.get("avatar_media_id"), user.get("banner_media_id"))
        if x
    }
    removed: list[tuple[str, int]] = []
    from . import media as media_mod   # perezoso: evita el ciclo
    with db.tx() as conn:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", tuple(params))
        # Si reemplacé avatar/portada, el media anterior deja de estar
        # referenciado por mí. Se borra sólo si nadie más lo usa (p. ej.
        # la misma foto puesta como avatar de un grupo).
        for mid in old_media:
            got = media_mod.drop_media_if_unused(conn, mid)
            if got:
                removed.append(got)
    for rel, size in removed:
        try:
            media_mod.remove_media_files(config.MEDIA_DIR / rel)
            media_mod.note_media_size(-size)
        except OSError:
            pass
    fresh = _get_user_by("id", str(user["id"]))
    # W15: los contactos deben ver al toque el nombre/avatar/estado nuevos
    # (el avatar trae URL nueva → el cliente baja la nueva miniatura).
    hub.emit_to_peers(user["id"], {"type": "profile", "user": _peer_user(fresh)})
    # Presencia "invisible": avisar a los contactos que dejen de verme en línea
    # (y volver a avisar si salgo de invisible estando conectado).
    new_preset = fresh.get("status_preset") or ""
    if new_preset != old_preset:
        if new_preset == "invisible":
            _presence_to_peers(user["id"], False)
        elif old_preset == "invisible" and hub.is_online(user["id"]):
            _presence_to_peers(user["id"], True)
    return {"user": _public_user(fresh)}


@router.put("/username")
def change_username(
    body: UsernameIn, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """W59: cambia el nombre de usuario con contraseña y enfriamiento.

    El usuario es el identificador de acceso y la base de las menciones
    (@usuario). Por eso:
      - se exige la contraseña actual, igual que para el correo;
      - solo se permite un cambio cada 12 horas;
      - no se toca el id ni las claves E2E (los chats siguen intactos).
    """
    _rate_limit(f"uname:{user['id']}", max_hits=10)
    new_name = body.username
    if new_name == user["username"]:
        raise HTTPException(400, "Ese ya es tu usuario actual")
    if not security.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "La contraseña actual no coincide")

    now = int(time.time())
    last = int(user.get("username_changed_at") or 0)
    wait = last + USERNAME_COOLDOWN - now
    if wait > 0:
        hours = wait // 3600
        minutes = (wait % 3600 + 59) // 60
        raise HTTPException(
            429, f"Podrás cambiar tu usuario en {hours} h {minutes} min"
        )

    other = _get_user_by("username", new_name)
    if other and other["id"] != user["id"]:
        raise HTTPException(409, "Ese usuario ya está en uso")
    try:
        db.execute(
            "UPDATE users SET username = ?, username_changed_at = ? WHERE id = ?",
            (new_name, now, user["id"]),
        )
    except Exception:
        # Carrera con otro registro/cambio: el UNIQUE COLLATE NOCASE manda.
        raise HTTPException(409, "Ese usuario ya está en uso")

    fresh = _get_user_by("id", str(user["id"]))
    # Los contactos ven el @nuevo al instante (lista, miembros y perfiles).
    hub.emit_to_peers(user["id"], {"type": "profile", "user": _peer_user(fresh)})
    return {"user": _public_user(fresh)}


def _presence_to_peers(user_id: int, online: bool) -> None:
    rows = db.rows(
        "SELECT DISTINCT cm2.user_id AS uid FROM chat_members cm1"
        " JOIN chat_members cm2 ON cm2.chat_id = cm1.chat_id"
        " WHERE cm1.user_id = ? AND cm2.user_id != ?",
        (user_id, user_id),
    )
    for r in rows:
        hub.emit_to_user(r["uid"], {"type": "presence", "user_id": user_id, "online": online})


# ---------------------------------------------------------------- verificación

@router.post("/verify")
def verify_email(
    body: VerifyIn, request: Request, response: Response,
    user: dict = Depends(pending_user),
) -> dict[str, Any]:
    _rate_limit(f"verify:{user['id']}", max_hits=20)

    if user["email_verified"]:
        tokens = _tokens(user)
        _set_refresh_cookie(response, request, tokens["refresh"])
        return {"verified": True, "tokens": tokens}

    row = db.one(
        "SELECT * FROM email_codes WHERE user_id = ? AND purpose = 'verify'"
        " ORDER BY created_at DESC LIMIT 1",
        (user["id"],),
    )
    now = int(time.time())
    if not row:
        raise HTTPException(400, "No hay código pendiente, solicita uno nuevo")
    if row["expires_at"] < now:
        raise HTTPException(410, "El código expiró, solicita uno nuevo")
    if row["attempts"] >= config.CODE_MAX_ATTEMPTS:
        raise HTTPException(410, "Código invalidado por intentos fallidos")

    if not security.verify_code(body.code, row["code_hash"]):
        db.execute(
            "UPDATE email_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],)
        )
        left = config.CODE_MAX_ATTEMPTS - (row["attempts"] + 1)
        if left <= 0:
            raise HTTPException(410, "Código invalidado por intentos fallidos")
        raise HTTPException(401, f"Código incorrecto, te quedan {left} intentos")

    db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (user["id"],))
    db.execute("DELETE FROM email_codes WHERE user_id = ? AND purpose = 'verify'", (user["id"],))
    fresh = _get_user_by("id", str(user["id"]))
    tokens = _tokens(fresh)
    _set_refresh_cookie(response, request, tokens["refresh"])
    return {"verified": True, "user": _public_user(fresh), "tokens": tokens}


@router.post("/resend")
def resend_code(body: ResendIn, user: dict = Depends(pending_user)) -> dict[str, Any]:
    _rate_limit(f"resend:{user['id']}", max_hits=12)
    purpose = body.purpose if body.purpose in ("verify", "reset") else "verify"
    wait = _check_cooldown(user["id"], purpose)
    if wait:
        raise HTTPException(429, detail={"retry_after": wait, "message": "Espera antes de reenviar"})
    info = _issue_code(user["id"], purpose)
    return {"ok": True, **info}


# ---------------------------------------------------------------- login

@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    ip = _client_ip(request)
    _rate_limit(f"login:{ip}", max_hits=15)
    _rate_limit(f"loginid:{body.identifier.lower()}", max_hits=15)

    user = _find_identifier(body.identifier)
    # Verificación constante de tiempo para usuarios inexistentes
    stored = user["password_hash"] if user else security.hash_password("\x00dummy")
    if not security.verify_password(body.password, stored) or not user:
        raise HTTPException(401, "Usuario o contraseña incorrectos")

    _rate_limit(f"loginok:{user['id']}", max_hits=30)
    tokens = _tokens(user)
    _set_refresh_cookie(response, request, tokens["refresh"])
    out: dict[str, Any] = {"user": _public_user(user), "tokens": tokens}
    if not user["email_verified"]:
        wait = _check_cooldown(user["id"], "verify")
        out["verification"] = {
            "required": True,
            "email_masked": _mask_email(user["email"]),
            "resend_after": wait,
            "resend_ready": wait == 0,
        }
    return out


@router.post("/refresh")
def refresh(
    body: RefreshIn, request: Request, response: Response
) -> dict[str, Any]:
    """W30e: el refresh vive en la cookie HttpOnly; el body se acepta
    todavía (sesiones legadas en localStorage y pruebas lo mandan así).
    Body primero si trae algo; si viene vacío, la cookie."""
    token = body.refresh or request.cookies.get(REFRESH_COOKIE) or ""
    payload = security.decode(token)
    if not payload or not payload.get("scope", "").endswith(":refresh"):
        raise HTTPException(401, "Refresh token inválido")
    user = _get_user_by("id", payload["sub"])
    if not user or user["token_version"] != payload.get("tv"):
        raise HTTPException(401, "Sesión expirada, vuelve a iniciar sesión")
    tokens = _tokens(user)
    _set_refresh_cookie(response, request, tokens["refresh"])   # rotación
    return {"tokens": tokens}


@router.post("/logout")
def logout(
    request: Request, response: Response, body: LogoutIn | None = None
) -> dict[str, Any]:
    """W30e: cierra la sesión del servidor. Borra la cookie del refresh y
    sube token_version, con lo que TODOS los refresh/access emitidos
    quedan invalidados (una cookie robada ya no sirve). Idempotente.
    Lee la cookie primero; el body es respaldo para sesiones legadas."""
    token = request.cookies.get(REFRESH_COOKIE) or (body.refresh if body else "")
    payload = security.decode(token)
    if payload and payload.get("sub"):
        user = _get_user_by("id", payload["sub"])
        if user and user["token_version"] == payload.get("tv"):
            db.execute(
                "UPDATE users SET token_version = token_version + 1 WHERE id = ?",
                (user["id"],),
            )
            # W45g: no dejar la WebSocket viva tras cerrar sesión.
            hub.kick_user(user["id"])
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}


# ---------------------------------------------------------------- reset

@router.post("/forgot")
def forgot(body: ForgotIn, request: Request) -> dict[str, Any]:
    _rate_limit(f"forgot:{_client_ip(request)}", max_hits=10)
    user = _find_identifier(body.identifier)
    if not user:
        # Respuesta idéntica para no revelar existencia de cuentas
        return {"ok": True, "message": "Si existe, se envió un código"}
    wait = _check_cooldown(user["id"], "reset")
    if wait == 0:
        _issue_code(user["id"], "reset")
    return {"ok": True, "message": "Si existe, se envió un código", "retry_after": wait}


@router.post("/reset")
def reset_password(
    body: ResetIn, request: Request, response: Response
) -> dict[str, Any]:
    _rate_limit(f"reset:{_client_ip(request)}", max_hits=10)
    user = _find_identifier(body.identifier)
    if not user:
        raise HTTPException(400, "Solicita primero un código")

    row = db.one(
        "SELECT * FROM email_codes WHERE user_id = ? AND purpose = 'reset'"
        " ORDER BY created_at DESC LIMIT 1",
        (user["id"],),
    )
    now = int(time.time())
    if not row or row["expires_at"] < now:
        raise HTTPException(410, "El código expiró, solicita uno nuevo")
    if row["attempts"] >= config.CODE_MAX_ATTEMPTS:
        raise HTTPException(410, "Código invalidado por intentos fallidos")
    if not security.verify_code(body.code, row["code_hash"]):
        db.execute("UPDATE email_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        raise HTTPException(401, "Código incorrecto")

    with db.tx() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
            (security.hash_password(body.password), user["id"]),
        )
        conn.execute("DELETE FROM email_codes WHERE user_id = ?", (user["id"],))
    hub.kick_user(user["id"])
    fresh = _get_user_by("id", str(user["id"]))
    tokens = _tokens(fresh)
    _set_refresh_cookie(response, request, tokens["refresh"])   # token_version subió
    return {"ok": True, "tokens": tokens}


# ------------------------------------------------- ajustes de cuenta (W6)

@router.post("/password")
def change_password(
    body: ChangePasswordIn, request: Request, response: Response,
    user: dict = Depends(current_user),
) -> dict[str, Any]:
    """Cambio de contraseña estando en sesión: exige la actual y sube
    token_version (invalida las demás sesiones); devuelve tokens nuevos
    para que la sesión actual siga viva."""
    _rate_limit(f"pwchg:{user['id']}", max_hits=10)
    if not security.verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(401, "La contraseña actual no coincide")
    if body.current_password == body.new_password:
        raise HTTPException(400, "La contraseña nueva debe ser distinta")
    with db.tx() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
            (security.hash_password(body.new_password), user["id"]),
        )
    # No cerrar la WS actual en el acto: la respuesta todavía tiene que
    # entregar los tokens nuevos y el cliente debe guardarlos. El chequeo
    # de token_version en ws.py cierra esta conexión en el siguiente ping
    # (25 s), cuando el refresh nuevo ya está aplicado.
    fresh = _get_user_by("id", str(user["id"]))
    tokens = _tokens(fresh)
    _set_refresh_cookie(response, request, tokens["refresh"])   # token_version subió
    return {"ok": True, "user": _public_user(fresh), "tokens": tokens}


@router.post("/email/change")
def email_change(
    body: EmailChangeIn, request: Request, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """Paso 1 del cambio de correo: guarda el pendiente y manda el código
    al correo NUEVO (el viejo sigue activo hasta confirmar)."""
    _rate_limit(f"emchg:{_client_ip(request)}", max_hits=10)
    if body.email == user["email"]:
        raise HTTPException(400, "Ese ya es tu correo actual")
    if _get_user_by("email", body.email):
        raise HTTPException(409, "Ese correo ya está registrado")
    wait = _check_cooldown(user["id"], "emailchange")
    if wait:
        raise HTTPException(429, detail={"retry_after": wait, "message": "Espera antes de pedir otro código"})
    db.execute("UPDATE users SET pending_email = ? WHERE id = ?", (body.email, user["id"]))
    info = _issue_code(user["id"], "emailchange", to_email=body.email)
    return {"ok": True, "email_masked": _mask_email(body.email), **info}


@router.post("/email/change/verify")
def email_change_verify(body: VerifyIn, user: dict = Depends(current_user)) -> dict[str, Any]:
    """Paso 2: el código llega al correo nuevo y recién ahí se reemplaza."""
    _rate_limit(f"emchgv:{user['id']}", max_hits=20)
    row = db.one(
        "SELECT * FROM email_codes WHERE user_id = ? AND purpose = 'emailchange'"
        " ORDER BY created_at DESC LIMIT 1",
        (user["id"],),
    )
    now = int(time.time())
    if not row:
        raise HTTPException(400, "No hay código pendiente, solicita uno nuevo")
    if row["expires_at"] < now:
        raise HTTPException(410, "El código expiró, solicita uno nuevo")
    if row["attempts"] >= config.CODE_MAX_ATTEMPTS:
        raise HTTPException(410, "Código invalidado por intentos fallidos")
    if not security.verify_code(body.code, row["code_hash"]):
        db.execute("UPDATE email_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        left = config.CODE_MAX_ATTEMPTS - (row["attempts"] + 1)
        if left <= 0:
            raise HTTPException(410, "Código invalidado por intentos fallidos")
        raise HTTPException(401, f"Código incorrecto, te quedan {left} intentos")

    fresh0 = _get_user_by("id", str(user["id"]))
    new_email = fresh0.get("pending_email") or ""
    if not new_email:
        raise HTTPException(400, "No hay cambio de correo pendiente")
    other = _get_user_by("email", new_email)
    if other and other["id"] != user["id"]:
        raise HTTPException(409, "Ese correo ya está registrado")
    with db.tx() as conn:
        conn.execute(
            "UPDATE users SET email = ?, pending_email = '' WHERE id = ?",
            (new_email, user["id"]),
        )
        conn.execute(
            "DELETE FROM email_codes WHERE user_id = ? AND purpose = 'emailchange'",
            (user["id"],),
        )
    fresh = _get_user_by("id", str(user["id"]))
    return {"ok": True, "user": _public_user(fresh)}


@router.delete("/account")
def delete_account(
    body: DeleteAccountIn, request: Request, user: dict = Depends(current_user)
) -> dict[str, Any]:
    """Borrado definitivo: exige usuario + contraseña.

    - Mensajes propios: se borran de todos los chats.
    - MD: se eliminan completos para las dos partes.
    - Grupos: se avisa con un mensaje de sistema y se transfiere la
      propiedad si hacía falta.
    - Media: se borra solo si ningún mensaje, perfil, grupo o GIF lo usa.
    """
    _rate_limit(f"delacct:{_client_ip(request)}", max_hits=10)
    if body.username.strip().lower() != user["username"]:
        raise HTTPException(400, "El usuario no coincide")
    if not security.verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Contraseña incorrecta")

    # Import perezoso: chats.py importa este módulo (ciclo si es global).
    from .chats import _next_seq, _transfer_owner, message_out
    from . import media as media_mod   # import perezoso: evita el ciclo

    name = user["display_name"] or user["username"]
    rows = db.rows(
        "SELECT c.id, c.type, cm.role FROM chats c"
        " JOIN chat_members cm ON cm.chat_id = c.id WHERE cm.user_id = ?",
        (user["id"],),
    )
    sys_ids: list[tuple[int, int]] = []
    dm_peers: set[int] = set()
    removed_media: list[tuple[str, int]] = []

    # Una sola transacción: o se borra todo, o nada. Antes se borraban los
    # archivos y la cuenta en pasos sueltos y un fallo dejaba media
    # huérfana o chats con referencias rotas.
    with db.tx() as conn:
        # 1) sus mensajes salen de todos los chats (reacciones caen en
        #    cascada). Recordar sus adjuntos: si el archivo era de otra
        #    cuenta y solo lo usaba este mensaje, queda huérfano.
        msg_media = {
            int(r["media_id"])
            for r in conn.execute(
                "SELECT DISTINCT media_id FROM messages"
                " WHERE sender_id = ? AND media_id IS NOT NULL",
                (user["id"],),
            ).fetchall()
        }
        conn.execute("DELETE FROM messages WHERE sender_id = ?", (user["id"],))

        # 2) DMs: se eliminan para no dejar "Usuario eliminado" en la lista
        #    del otro lado. Grupos: transferir propiedad y avisar.
        for ch in rows:
            if ch["type"] == "dm":
                for cm in conn.execute(
                    "SELECT user_id FROM chat_members WHERE chat_id = ?",
                    (ch["id"],),
                ).fetchall():
                    if cm["user_id"] != user["id"]:
                        dm_peers.add(int(cm["user_id"]))
                conn.execute("DELETE FROM chats WHERE id = ?", (ch["id"],))
                continue

            _transfer_owner(conn, ch["id"], user["id"])
            left = conn.execute(
                "SELECT COUNT(*) AS n FROM chat_members WHERE chat_id = ?",
                (ch["id"],),
            ).fetchone()
            if not left or left["n"] <= 1:
                conn.execute("DELETE FROM chats WHERE id = ?", (ch["id"],))
                continue
            seq = _next_seq(conn, ch["id"])
            cur = conn.execute(
                "INSERT INTO messages (chat_id, seq, sender_id, kind, body, created_at)"
                " VALUES (?, ?, NULL, 'system', ?, ?)",
                (ch["id"], seq, f"La cuenta de {name} fue eliminada",
                 int(time.time())),
            )
            sys_ids.append((int(ch["id"]), int(cur.lastrowid)))

        # 3) media propia: primero recordar ids; después de borrar users
        #    ya no se puede consultar owner_id (ON DELETE SET NULL).
        owned_media = conn.execute(
            "SELECT id, path, size FROM media WHERE owner_id = ?", (user["id"],)
        ).fetchall()

        # 4) la cuenta (cascada: chat_members, email_codes, reactions,
        #    solicitudes y bloqueos)
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))

        # 5) archivos: borrar sólo los que ya nadie referencia (reenvíos,
        #    avatares de grupo o GIFs favoritos de OTROS usuarios).
        owned_ids = set()
        for m in owned_media:
            mid = int(m["id"])
            owned_ids.add(mid)
            if media_mod.media_in_use(conn, mid):
                conn.execute("UPDATE media SET owner_id = NULL WHERE id = ?", (mid,))
            else:
                conn.execute("DELETE FROM media WHERE id = ?", (mid,))
                removed_media.append((m["path"], int(m["size"] or 0)))
        # Adjuntos ajenos que solo usaban los mensajes borrados.
        for mid in msg_media - owned_ids:
            dropped = media_mod.drop_media_if_unused(conn, mid)
            if dropped:
                removed_media.append(dropped)

    hub.kick_user(user["id"])

    # 6) en vivo: los chats abiertos ven el aviso y el cambio de miembros
    for chat_id, msg_id in sys_ids:
        hub.emit_to_chat(chat_id, {"type": "members_changed", "chat_id": chat_id})
        row = db.one("SELECT * FROM messages WHERE id = ?", (msg_id,))
        if row:
            hub.emit_to_chat(chat_id, {"type": "message", "message": message_out(row)})
    for peer in dm_peers:
        hub.emit_to_user(peer, {"type": "chat_updated", "chat_id": 0})

    for rel, size in removed_media:
        try:
            media_mod.remove_media_files(config.MEDIA_DIR / rel)
            media_mod.note_media_size(-size)
        except OSError:
            pass
    return {"ok": True}
