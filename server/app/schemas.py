"""Esquemas Pydantic para request bodies."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.]{2,19}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterIn(BaseModel):
    email: str
    username: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v) or len(v) > 254:
            raise ValueError("correo inválido")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("usuario: 3-20 caracteres, letras/números/punto/guion bajo, empieza alfanumérico")
        return v

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("la contraseña debe tener al menos 8 caracteres")
        if len(v) > 200:
            raise ValueError("contraseña demasiado larga")
        return v


class LoginIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)  # usuario o correo
    password: str = Field(min_length=1, max_length=200)


class VerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def _digits(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError("el código debe tener 6 dígitos")
        return v


class ResendIn(BaseModel):
    purpose: str = "verify"  # 'verify' | 'reset'


class ForgotIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)


class ResetIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=254)
    code: str = Field(min_length=6, max_length=6)
    password: str = Field(min_length=8, max_length=200)


class RefreshIn(BaseModel):
    refresh: str


class LogoutIn(BaseModel):
    # W30e: el refresh normal vive en la cookie HttpOnly; el body es el
    # respaldo para sesiones legadas (localStorage, sin cookie).
    refresh: str = ""


class ProfileIn(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=50)
    bio: Optional[str] = Field(default=None, max_length=150)
    status_text: Optional[str] = Field(default=None, max_length=80)
    status_preset: Optional[str] = None  # '' | online | busy | dnd | invisible (W6)
    avatar_media_id: Optional[int] = None  # null = quitar avatar

    @field_validator("status_preset")
    @classmethod
    def _preset(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if v not in ("", "online", "busy", "dnd", "invisible"):
            raise ValueError("estado inválido")
        return v

    @field_validator("display_name")
    @classmethod
    def _dn(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        # '' es válido: permite vaciar el nombre (se muestra el usuario).
        v = v.strip()
        if len(v) > 50:
            raise ValueError("máximo 50 caracteres")
        return v

    @field_validator("bio", "status_text")
    @classmethod
    def _txt(cls, v: Optional[str]) -> Optional[str]:
        # '' es válido: permite vaciar bio/estado (None = no tocar el campo).
        return v.strip() if v is not None else None


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class EmailChangeIn(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v) or len(v) > 254:
            raise ValueError("correo inválido")
        return v


class DeleteAccountIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    username: str = Field(min_length=1, max_length=30)
