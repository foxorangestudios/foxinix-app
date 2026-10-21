"""Contraseñas (scrypt de la stdlib) y JWT (PyJWT)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

import jwt

from . import config

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, dk_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
        )
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def hash_code(code: str) -> str:
    return hashlib.sha256(f"{config.SECRET}:{code}".encode()).hexdigest()


def verify_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_code(code), code_hash)


def new_code() -> str:
    """Código de 6 dígitos (no secuencial)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _issue(user_id: int, scope: str, ttl: int, token_version: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "scope": scope,
        "tv": token_version,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, config.SECRET, algorithm="HS256")


def issue_access(user_id: int, verified: bool, token_version: int) -> str:
    return _issue(user_id, "full" if verified else "pending", config.ACCESS_TTL, token_version)


def issue_refresh(user_id: int, verified: bool, token_version: int) -> str:
    return _issue(
        user_id,
        ("full" if verified else "pending") + ":refresh",
        config.REFRESH_TTL,
        token_version,
    )


def decode(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, config.SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# ------------------------------------------------- firmas de media (W11)

def _media_sig(slug: str, exp: int) -> str:
    return hmac.new(
        config.SECRET.encode(), f"{slug}.{exp}".encode(), hashlib.sha256
    ).hexdigest()[:32]


def sign_media(slug: str, ttl: int) -> tuple[int, str]:
    """Firma corta (exp, sig) para una URL de media con caducidad."""
    exp = int(time.time()) + ttl
    return exp, _media_sig(slug, exp)


def verify_media_sig(slug: str, exp: Any, sig: Any) -> bool:
    """True si la firma es válida y no venció."""
    if not slug or not exp or not sig:
        return False
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(_media_sig(slug, exp), str(sig))
