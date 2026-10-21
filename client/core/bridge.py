"""Bridge: lógica de la app expuesta a QML (slots + señales)."""
from __future__ import annotations

import base64
import logging
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from . import api as api_mod
from . import cache
from . import session as session_mod
from .api import Api, ApiError
from .models import ChatsModel, MessagesModel
from .ws import ws_client

session = session_mod.session   # instancia de Session (no el módulo)

log = logging.getLogger("foxmsg.client.bridge")
api: Api = api_mod.api


class Worker(QRunnable):
    """Ejecuta `fn` en el pool y emite `done/error` en el hilo principal."""

    class _Signals(QObject):
        done = Signal(object)
        error = Signal(str, object)   # mensaje, detail (ApiError|None)

    def __init__(self, fn: Callable[[], Any], on_done=None, on_error=None) -> None:
        super().__init__()
        self.fn = fn
        self.sig = self._Signals()
        if on_done:
            self.sig.done.connect(on_done)
        if on_error:
            self.sig.error.connect(on_error)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.fn()
        except ApiError as exc:
            self.sig.error.emit(exc.message, exc)
            return
        except Exception as exc:  # noqa: BLE001
            log.exception("worker falló")
            self.sig.error.emit(str(exc), None)
            return
        self.sig.done.emit(result)


class Bridge(QObject):
    # ------------------------------------------------------------ señales
    toast = Signal(str, str)                # mensaje, tipo (info|error|ok)
    busyChanged = Signal(bool)
    authStateChanged = Signal()             # refrescar si hay sesión
    verificationRequired = Signal(str, int)  # email_enmascarado, resend_after
    chatsUpdated = Signal()
    messagesReset = Signal()
    messagesAppended = Signal()
    wsStatusChanged = Signal(str)
    presenceChanged = Signal(int, bool)     # user_id, online
    typingChanged = Signal(int, str)        # chat_id, username ('' = paró)
    chatReadChanged = Signal(int, int)      # chat_id, seq
    openChatRequested = Signal(int)
    navigate = Signal(str)                  # 'auth' | 'verify' | 'app'
    avatarChanged = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.chats = ChatsModel(self)
        self.messages = MessagesModel(self)
        self.current_chat_id: int = 0
        self._pool = QThreadPool.globalInstance()
        self._typing_timers: dict[int, int] = {}

        ws_client.on_event = self._on_ws_event
        ws_client.on_status = lambda s: self.wsStatusChanged.emit(s)

    # ------------------------------------------------------------ helpers

    def _run(self, fn, on_done, on_error=None) -> None:
        self.busyChanged.emit(True)

        def _done(res):
            self.busyChanged.emit(False)
            if on_done:
                on_done(res)

        def _err(msg, detail):
            self.busyChanged.emit(False)
            if on_error:
                on_error(msg, detail)
            else:
                self.toast.emit(msg, "error")

        self._pool.start(Worker(fn, _done, _err))

    @property
    def me_id(self) -> int | None:
        u = session.user
        return u["id"] if u else None

    # ================================================================
    # Auth
    # ================================================================

    @Slot(str, str, str)
    def register(self, email: str, username: str, password: str) -> None:
        def fn():
            return api.post("/api/auth/register", {
                "email": email.strip(), "username": username.strip(),
                "password": password,
            })

        def done(res):
            self._adopt_auth(res)
            # NO navegamos a verify todavía: el cliente muestra el paso de perfil
            # (AuthFlow cambia a sub="profile"); verificationRequired guarda el email.
            self.verificationRequired.emit(
                res["verification"]["email_masked"],
                res["verification"].get("resend_after", 60),
            )
            self.toast.emit(f"Te enviamos un código a {res['verification']['email_masked']}", "ok")

        self._run(fn, done)

    @Slot(str, str)
    def login(self, identifier: str, password: str) -> None:
        def fn():
            return api.post("/api/auth/login", {
                "identifier": identifier.strip(), "password": password,
            })

        def done(res):
            self._adopt_auth(res)
            if res.get("verification", {}).get("required"):
                self.verificationRequired.emit(
                    res["verification"]["email_masked"],
                    res["verification"].get("resend_after", 0),
                )
                self.navigate.emit("verify")
            else:
                self.toast.emit(f"¡Hola, {res['user']['display_name']}!", "ok")
                self._enter_app()

        self._run(fn, done)

    @Slot(str)
    def verify(self, code: str) -> None:
        def fn():
            return api.post("/api/auth/verify", {"code": code.strip()})

        def done(res):
            if res.get("verified"):
                self._adopt_auth(res, keep_verification=False)
                self.toast.emit("¡Correo verificado!", "ok")
                self._enter_app()

        self._run(fn, done)

    @Slot()
    def show_verify(self) -> None:
        """Navega a la pantalla de verificación (sin reenviar código)."""
        u = session.user or {}
        self.verificationRequired.emit(u.get("email_masked", ""), 0)
        self.navigate.emit("verify")

    @Slot()
    def resend_code(self) -> None:
        def fn():
            return api.post("/api/auth/resend", {"purpose": "verify"})

        def done(_res):
            self.verificationRequired.emit(
                session.user.get("email_masked", "") if session.user else "",
                60,
            )
            self.toast.emit("Código reenviado", "ok")

        self._run(fn, done)

    @Slot(str, str, str)
    def setup_profile(self, display_name: str, bio: str, avatar_path: str) -> None:
        """Paso 2 del registro: perfil (antes de verificar)."""

        def fn():
            body: dict[str, Any] = {}
            if display_name.strip():
                body["display_name"] = display_name.strip()
            if bio.strip():
                body["bio"] = bio.strip()
            avatar_id = None
            if avatar_path:
                p = Path(avatar_path)
                if p.is_file():
                    mime = mimetypes.guess_type(p.name)[0] or "image/png"
                    up = api.upload("/api/media", p.name, p.read_bytes(), mime)
                    avatar_id = up["id"]
            if avatar_id is not None:
                body["avatar_media_id"] = avatar_id
            if body:
                api.put("/api/auth/profile", body)
            return True

        def done(_res):
            self.toast.emit("Perfil guardado", "ok")
            self.avatarChanged.emit("")
            self.navigate.emit("verify")

        self._run(fn, done)

    @Slot(str, str)
    def forgot(self, identifier: str, new_password: str) -> None:
        """flujo 'olvidé mi contraseña': pide código y resetea."""
        def fn():
            return api.post("/api/auth/forgot", {"identifier": identifier.strip()})

        def done(_res):
            self.toast.emit("Si existe el usuario, te enviamos un código", "info")
            self._pending_reset = (identifier.strip(), new_password)
            self.navigate.emit("verify")

        self._run(fn, done)

    @Slot(str)
    def reset_password(self, code: str) -> None:
        ident, new_pw = getattr(self, "_pending_reset", ("", ""))

        def fn():
            return api.post("/api/auth/reset", {
                "identifier": ident, "code": code.strip(), "password": new_pw,
            })

        def done(res):
            self._adopt_auth(res, keep_verification=False)
            self.toast.emit("Contraseña actualizada", "ok")
            self._enter_app()

        self._run(fn, done)

    @Slot()
    def logout(self) -> None:
        ws_client.stop()
        api.set_tokens(None, None)
        session.clear()
        cache.clear_all()
        self.chats.set_chats([])
        self.messages.set_messages([])
        self.navigate.emit("auth")

    def _adopt_auth(self, res: dict, keep_verification: bool = True) -> None:
        tokens = res.get("tokens") or {}
        api.set_tokens(tokens.get("access"), tokens.get("refresh"))
        if res.get("user"):
            user = dict(res["user"])
            if keep_verification and res.get("verification"):
                user["email_masked"] = res["verification"].get("email_masked", "")
            session.set_auth(tokens, user, api.server_label())
        elif tokens:
            session.data.setdefault("tokens", {})
            session.data["tokens"] = tokens
            session.save()
        self.authStateChanged.emit()

    def _enter_app(self) -> None:
        """Tras sesión válida: cargar chats y abrir WS."""
        self.navigate.emit("app")
        self.messages.set_me(self.me_id or -1)
        self.refresh_chats()
        ws_client.start(api.ws_url)

    # ================================================================
    # Arranque con sesión guardada
    # ================================================================

    @Slot(result=bool)
    def restore_session(self) -> bool:
        if not session.tokens:
            return False
        api.set_tokens(session.tokens.get("access"), session.tokens.get("refresh"))
        if session.server:
            for name, url in api_mod.config.SERVERS:
                if name == session.server:
                    api.base = url
        # validar en background
        self._run(lambda: api.get("/api/users/me"),
                  lambda res: self._enter_app(),
                  lambda msg, detail: self._session_invalid(msg))
        return True

    def _session_invalid(self, msg: str) -> None:
        session.clear()
        api.set_tokens(None, None)
        self.navigate.emit("auth")

    # ================================================================
    # Chats
    # ================================================================

    @Slot()
    def refresh_chats(self) -> None:
        def fn():
            return api.get("/api/chats")

        def done(res):
            chats = res.get("chats", [])
            for c in chats:
                cache.upsert_chat(c)
            self.chats.set_chats(chats)
            self.chatsUpdated.emit()

        # si falla, usar caché local
        self._run(fn, done, lambda msg, d: self._chats_from_cache())

    def _chats_from_cache(self) -> None:
        chats = cache.cached_chats()
        if chats:
            self.chats.set_chats(chats)
            self.chatsUpdated.emit()
            self.toast.emit("Sin conexión: mostrando caché local", "info")

    @Slot(str)
    def open_dm(self, username: str) -> None:
        def fn():
            return api.post("/api/chats/dm", {"username": username})

        def done(res):
            chat = res["chat"]
            cache.upsert_chat(chat)
            self.chats.upsert(chat)
            self.chatsUpdated.emit()
            self.open_chat(chat["id"])

        self._run(fn, done)

    @Slot(str, str)
    def create_group(self, title: str, members_csv: str) -> None:
        members = [m.strip() for m in members_csv.split(",") if m.strip()]

        def fn():
            return api.post("/api/chats/group", {"title": title, "members": members})

        def done(res):
            cache.upsert_chat(res["chat"])
            self.chats.upsert(res["chat"])
            self.chatsUpdated.emit()
            self.open_chat(res["chat"]["id"])

        self._run(fn, done)

    @Slot(int)
    def open_chat(self, chat_id: int) -> None:
        self.current_chat_id = chat_id
        cached = cache.cached_messages(chat_id, limit=100)
        if cached:
            self.messages.set_messages(cached)
            self.messages.set_read_seq(max((m.get("seq") or 0) for m in cached))
            self.messagesReset.emit()

        last = cache.last_seq(chat_id)

        def fn():
            return api.get(f"/api/chats/{chat_id}/messages",
                           params={"before_seq": last} if last else None)

        def done(res):
            msgs = res.get("messages", [])
            if msgs:
                cache.upsert_messages(msgs)
                merged = {m["id"]: m for m in msgs}
                for m in self.messages._items:
                    if m.get("id"):
                        merged[m["id"]] = m
                ordered = sorted(merged.values(), key=lambda m: m.get("seq") or 0)
                self.messages.set_messages(ordered)
                self.messages.set_read_seq(
                    max((m.get("seq") or 0) for m in ordered if m.get("seq"))
                )
                self.messagesReset.emit()
            elif not cached:
                self.messages.set_messages([])
                self.messagesReset.emit()
            self._send_seen(chat_id, self.messages.max_seq())
            self.openChatRequested.emit(chat_id)

        self._run(fn, done, lambda m, d: self.openChatRequested.emit(chat_id))

    # ================================================================
    # Mensajes
    # ================================================================

    @Slot(str)
    def send_text(self, body: str) -> None:
        self._send(kind="text", body=body.strip())

    @Slot(str, str, str)
    def send_file(self, path: str, kind: str, caption: str = "") -> None:
        """kind: image | file | voice"""
        self._send(kind=kind, body=caption, file_path=path)

    def _send(self, kind: str, body: str = "", file_path: str = "") -> None:
        chat_id = self.current_chat_id
        if not chat_id or (kind == "text" and not body):
            return
        client_msg_id = uuid.uuid4().hex
        pending: dict[str, Any] = {
            "id": None,
            "seq": 10**9,
            "chat_id": chat_id,
            "kind": kind,
            "body": body,
            "media": None,
            "reply_to": None,
            "client_msg_id": client_msg_id,
            "created_at": int(time.time()),
            "sender": session.user,
            "reactions": [],
            "_pending": True,
        }

        def fn():
            media_id = None
            if file_path:
                p = Path(file_path)
                mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                if kind == "image" and not mime.startswith("image/"):
                    mime = "image/png"
                up = api.upload("/api/media", p.name, p.read_bytes(), mime)
                media_id = up["id"]
            payload: dict[str, Any] = {
                "kind": kind, "body": body, "client_msg_id": client_msg_id,
            }
            if media_id is not None:
                payload["media_id"] = media_id
            return api.post(f"/api/chats/{chat_id}/messages", payload)

        def done(res):
            msg = res["message"]
            cache.upsert_messages([msg])
            self.messages.replace_local(client_msg_id, msg)
            self.messagesAppended.emit()
            self._bump_chat_preview(chat_id, msg)
            # forzar "entregado" local: el estado de lectura llega por WS
            self.messages.bump_read(self.messages.max_seq() - 1)

        def err(msg, detail):
            self.messages.mark_failed(client_msg_id)
            self.messagesAppended.emit()
            self.toast.emit(f"No se pudo enviar: {msg}", "error")

        self.messages.append_local(pending)
        self.messagesAppended.emit()
        self._run(fn, done, err)

    @Slot(str)
    def retry_send(self, client_msg_id: str) -> None:
        """Reenvía un mensaje fallido (mismo client_msg_id = idempotente)."""
        target = next(
            (m for m in self.messages._items
             if m.get("client_msg_id") == client_msg_id), None,
        )
        if not target:
            return
        for m in self.messages._items:
            if m.get("client_msg_id") == client_msg_id:
                m.pop("_failed", None)
        self.messages.refresh_states()

        chat_id = target["chat_id"]

        def fn():
            payload = {
                "kind": target["kind"], "body": target.get("body") or "",
                "client_msg_id": client_msg_id,
            }
            media = target.get("media")
            if media:
                payload["media_id"] = media["id"]
            return api.post(f"/api/chats/{chat_id}/messages", payload)

        def done(res):
            self.messages.replace_local(client_msg_id, res["message"])
            self.messagesAppended.emit()

        def err(msg, _d):
            self.messages.mark_failed(client_msg_id)
            self.messagesAppended.emit()
            self.toast.emit(f"No se pudo reenviar: {msg}", "error")

        self._run(fn, done, err)

    @Slot(str)
    def send_typing(self, chat_id_and_dummy: str = "") -> None:
        if self.current_chat_id:
            ws_client.send({"type": "typing_detail", "chat_id": self.current_chat_id})
            # fallback REST (el server acepta POST /typing)
            import threading
            cid = self.current_chat_id
            threading.Thread(
                target=lambda: self._safe_typing(cid), daemon=True
            ).start()

    def _safe_typing(self, chat_id: int) -> None:
        try:
            api.post(f"/api/chats/{chat_id}/typing")
        except Exception:
            pass

    @Slot(int)
    def mark_read(self, chat_id: int) -> None:
        seq = self.messages.max_seq() if chat_id == self.current_chat_id else 0
        if not seq:
            return
        self._send_seen(chat_id, seq)
        self.chats.patch(chat_id, unread=0)
        self.chatsUpdated.emit()

    def _send_seen(self, chat_id: int, seq: int) -> None:
        if not seq:
            return
        ws_client.send({"type": "seen", "chat_id": chat_id, "seq": seq})
        import threading
        threading.Thread(
            target=lambda: self._safe_read(chat_id, seq), daemon=True
        ).start()

    def _safe_read(self, chat_id: int, seq: int) -> None:
        try:
            api.post(f"/api/chats/{chat_id}/read", {"seq": seq})
        except Exception:
            pass

    @Slot(str)
    def react(self, spec: str) -> None:
        """spec: '<msg_id>:<emoji>'"""
        try:
            mid_s, emoji = spec.split(":", 1)
            mid = int(mid_s)
        except ValueError:
            return
        chat_id = self.current_chat_id
        import threading
        threading.Thread(
            target=lambda: self._safe_react(chat_id, mid, emoji), daemon=True
        ).start()

    def _safe_react(self, chat_id: int, msg_id: int, emoji: str) -> None:
        try:
            api.post(f"/api/chats/{chat_id}/reactions/{msg_id}", {"emoji": emoji})
        except Exception:
            pass

    @Slot(str)
    def copy_text(self, text: str) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.toast.emit("Copiado al portapapeles", "ok")

    def _bump_chat_preview(self, chat_id: int, msg: dict) -> None:
        chat = self.chats.get(chat_id)
        if chat:
            updated = dict(chat)
            updated["last_message"] = msg
            self.chats.upsert(updated)
            self.chats.move_to_top(chat_id)
            cache.upsert_chat(updated)
            self.chatsUpdated.emit()

    # ================================================================
    # Perfil
    # ================================================================

    @Slot(str, str, str)
    def update_profile(self, display_name: str, bio: str, status_text: str) -> None:
        def fn():
            body: dict[str, Any] = {}
            body["display_name"] = display_name.strip() or None
            if bio.strip() != (session.user or {}).get("bio", ""):
                body["bio"] = bio.strip()
            if status_text.strip() != (session.user or {}).get("status_text", ""):
                body["status_text"] = status_text.strip()
            return api.put("/api/auth/profile", body)

        def done(res):
            session.update_user(res["user"])
            self.authStateChanged.emit()
            self.toast.emit("Perfil actualizado", "ok")

        self._run(fn, done)

    @Slot(str)
    def set_avatar(self, path: str) -> None:
        def fn():
            p = Path(path)
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
            up = api.upload("/api/media", p.name, p.read_bytes(), mime)
            return api.put("/api/auth/profile", {"avatar_media_id": up["id"]})

        def done(res):
            session.update_user(res["user"])
            self.authStateChanged.emit()
            self.avatarChanged.emit(res["user"].get("avatar_url") or "")
            self.toast.emit("Foto de perfil actualizada", "ok")

        self._run(fn, done)

    @Slot(result=str)
    def my_avatar_url(self) -> str:
        url = (session.user or {}).get("avatar_url")
        return api.media_url(url) if url else ""

    # ================================================================
    # WS
    # ================================================================

    def _on_ws_event(self, evt: dict[str, Any]) -> None:
        """Se ejecuta en el hilo del WS → emitir señales Qt (seguro)."""
        etype = evt.get("type")
        if etype == "message":
            msg = evt.get("message") or {}
            chat_id = msg.get("chat_id")
            cache.upsert_messages([msg])
            if chat_id == self.current_chat_id:
                self.messages.append(msg)
                self.messagesAppended.emit()
                self._send_seen(chat_id, msg.get("seq") or 0)
            self._bump_chat_preview(chat_id, msg)
            chat = self.chats.get(chat_id)
            if chat_id != self.current_chat_id and chat:
                self.chats.patch(chat_id, unread=int(chat.get("unread") or 0) + 1)
                self.chatsUpdated.emit()
        elif etype == "typing":
            self.typingChanged.emit(evt.get("chat_id", 0), evt.get("username", ""))
        elif etype == "read":
            if evt.get("chat_id") == self.current_chat_id:
                self.messages.bump_read(evt.get("seq") or 0)
                self.messagesAppended.emit()
            self.chatReadChanged.emit(evt.get("chat_id", 0), evt.get("seq") or 0)
        elif etype == "presence":
            self.presenceChanged.emit(evt.get("user_id", 0), bool(evt.get("online")))
        elif etype == "chat_created":
            self.refresh_chats()
        elif etype in ("reaction", "reaction_removed"):
            if evt.get("chat_id") == self.current_chat_id:
                self._patch_reaction(evt)
        elif etype == "members_changed":
            if evt.get("chat_id") == self.current_chat_id:
                self.open_chat(self.current_chat_id)

    def _patch_reaction(self, evt: dict) -> None:
        mid, uid = evt.get("message_id"), evt.get("user_id")
        for i, m in enumerate(self.messages._items):
            if m.get("id") == mid:
                reactions = list(m.get("reactions") or [])
                if evt["type"] == "reaction":
                    reactions = [r for r in reactions if r.get("user_id") != uid]
                    reactions.append({"user_id": uid, "emoji": evt.get("emoji")})
                else:
                    reactions = [r for r in reactions if r.get("user_id") != uid]
                m["reactions"] = reactions
                from PySide6.QtCore import QModelIndex
                idx = self.messages.index(i, 0)
                self.messages.dataChanged.emit(idx, idx, [self.messages.Roles["reactions"]])
                return

    # ================================================================
    # Search / utils
    # ================================================================

    # --------------------------------------------------------------- extra
    searchResults = Signal(list)

    @Slot(str)
    def search_contacts(self, q: str) -> None:
        def fn():
            return api.get("/api/users/search", params={"q": q})

        def done(res):
            self.searchResults.emit(res.get("results", []))

        self._run(fn, done)

    @Slot(result=str)
    def server_label(self) -> str:
        return api.server_label()

    @Slot(result=str)
    def me_username(self) -> str:
        return (session.user or {}).get("username", "")

    @Slot(result=str)
    def me_display(self) -> str:
        u = session.user or {}
        return u.get("display_name") or u.get("username", "")
