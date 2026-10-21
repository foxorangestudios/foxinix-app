"""Bridge QObject: expone lógica y modelos a QML.

Todos los métodos marcados @Slot corren en el hilo principal; las llamadas de
red se ejecutan en hilos con `threading` y vuelven por señales Qt.
"""
from __future__ import annotations

import logging
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    Property,
    QRunnable,
    QThreadPool,
    Qt,
    Signal,
    Slot,
)

from . import api as api_mod
from . import cache, config, session
from .api import Api, ApiError
from .ws import ws_client

log = logging.getLogger("foxmsg.client")

api: Api = api_mod.api


# =====================================================================
# Modelos
# =====================================================================

class ChatsModel(QAbstractListModel):
    """Lista de chats para el panel izquierdo."""

    _ROLES = {
        "chatId": Qt.ItemDataRole.UserRole + 1,
        "title": Qt.ItemDataRole.UserRole + 2,
        "username": Qt.ItemDataRole.UserRole + 3,
        "avatarUrl": Qt.ItemDataRole.UserRole + 4,
        "lastBody": Qt.ItemDataRole.UserRole + 5,
        "lastTime": Qt.ItemDataRole.UserRole + 6,
        "unread": Qt.ItemDataRole.UserRole + 7,
        "chatType": Qt.ItemDataRole.UserRole + 8,
        "online": Qt.ItemDataRole.UserRole + 9,
        "senderName": Qt.ItemDataRole.UserRole + 10,
        "isGroup": Qt.ItemDataRole.UserRole + 11,
        "draft": Qt.ItemDataRole.UserRole + 12,
    }

    # expuesto a QML como `chatsModel.Roles.chatId` (un dict de Python puro
    # no es visible desde QML; Property QVariantMap sí lo es)
    def _roles_qml(self) -> dict[str, int]:
        return dict(self._ROLES)

    Roles = Property("QVariantMap", _roles_qml)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        it = self._items[index.row()]
        role_name = {v: k for k, v in self.Roles.items()}.get(role)
        if role_name is None:
            return None
        if role_name == "chatId":
            return it["id"]
        if role_name == "title":
            return (it.get("title") or {}).get("display_name") or ""
        if role_name == "username":
            return (it.get("title") or {}).get("username") or ""
        if role_name == "avatarUrl":
            url = it.get("avatar_url")
            return api.media_url(url) if url else ""
        if role_name == "lastBody":
            lm = it.get("last_message") or {}
            if lm.get("kind") in ("image", "file", "voice"):
                return {"image": "📷 Foto", "file": "📎 Archivo",
                        "voice": "🎙 Nota de voz"}.get(lm.get("kind"), "")
            return lm.get("body") or ""
        if role_name == "lastTime":
            return (it.get("last_message") or {}).get("created_at") or 0
        if role_name == "senderName":
            s = (it.get("last_message") or {}).get("sender") or {}
            return s.get("username") or ""
        if role_name == "unread":
            return int(it.get("unread") or 0)
        if role_name == "chatType":
            return it.get("type") or "dm"
        if role_name == "isGroup":
            return it.get("type") == "group"
        if role_name == "online":
            t = (it.get("title") or {}).get("last_seen") or 0
            return bool((it.get("title") or {}).get("online")) or (time.time() - t < 300)
        if role_name == "draft":
            return it.get("_draft") or ""
        return None

    def roleNames(self):  # noqa: N802
        return {v: k.encode() for k, v in self.Roles.items()}

    # ------------------------------------------------------------ mutación

    def set_chats(self, chats: list[dict]) -> None:
        self.beginResetModel()
        self._items = chats
        self.endResetModel()

    def upsert(self, chat: dict) -> None:
        for i, it in enumerate(self._items):
            if it["id"] == chat["id"]:
                merged = {**it, **chat}
                self._items[i] = merged
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)
                return
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._items.insert(0, chat)
        self.endInsertRows()

    def patch(self, chat_id: int, **fields: Any) -> None:
        for i, it in enumerate(self._items):
            if it["id"] == chat_id:
                it.update(fields)
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)
                return

    def get(self, chat_id: int) -> dict | None:
        for it in self._items:
            if it["id"] == chat_id:
                return it
        return None

    def move_to_top(self, chat_id: int) -> None:
        for i, it in enumerate(self._items):
            if it["id"] == chat_id:
                if i == 0:
                    return
                self.beginMoveRows(QModelIndex(), i, i, QModelIndex(), 0)
                self._items.insert(0, self._items.pop(i))
                self.endMoveRows()
                return


class MessagesModel(QAbstractListModel):
    """Mensajes de la conversación abierta."""

    _ROLES = {
        "msgId": Qt.ItemDataRole.UserRole + 1,
        "seq": Qt.ItemDataRole.UserRole + 2,
        "mine": Qt.ItemDataRole.UserRole + 3,
        "body": Qt.ItemDataRole.UserRole + 4,
        "kind": Qt.ItemDataRole.UserRole + 5,
        "time": Qt.ItemDataRole.UserRole + 6,
        "senderName": Qt.ItemDataRole.UserRole + 7,
        "senderId": Qt.ItemDataRole.UserRole + 8,
        "avatarUrl": Qt.ItemDataRole.UserRole + 9,
        "state": Qt.ItemDataRole.UserRole + 10,     # sent|delivered|read
        "mediaUrl": Qt.ItemDataRole.UserRole + 11,
        "mediaMime": Qt.ItemDataRole.UserRole + 12,
        "mediaName": Qt.ItemDataRole.UserRole + 13,
        "mediaSize": Qt.ItemDataRole.UserRole + 14,
        "dayKey": Qt.ItemDataRole.UserRole + 15,     # para separadores de fecha
        "isSystem": Qt.ItemDataRole.UserRole + 16,
        "replyBody": Qt.ItemDataRole.UserRole + 17,
        "replySender": Qt.ItemDataRole.UserRole + 18,
        "clientMsgId": Qt.ItemDataRole.UserRole + 19,
        "reactions": Qt.ItemDataRole.UserRole + 20,
        "failed": Qt.ItemDataRole.UserRole + 21,
    }

    # expuesto a QML como `messagesModel.Roles.dayKey`
    def _roles_qml(self) -> dict[str, int]:
        return dict(self._ROLES)

    Roles = Property("QVariantMap", _roles_qml)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._me_id: int | None = None
        self._read_seq: int = 0

    def set_me(self, user_id: int) -> None:
        self._me_id = user_id

    def set_read_seq(self, seq: int) -> None:
        self._read_seq = seq

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role: int) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        m = self._items[index.row()]
        rn = {v: k for k, v in self.Roles.items()}.get(role)
        sender = m.get("sender") or {}
        media = m.get("media") or {}
        reply = m.get("reply_to") or {}
        if rn == "msgId":
            return m.get("id") or 0
        if rn == "seq":
            return m.get("seq") or 0
        if rn == "mine":
            return sender.get("id") == self._me_id
        if rn == "body":
            return m.get("body") or ""
        if rn == "kind":
            return m.get("kind") or "text"
        if rn == "time":
            return m.get("created_at") or 0
        if rn == "senderName":
            return sender.get("display_name") or sender.get("username") or ""
        if rn == "senderId":
            return sender.get("id") or 0
        if rn == "avatarUrl":
            url = sender.get("avatar_url")
            return api.media_url(url) if url else ""
        if rn == "state":
            if sender.get("id") != self._me_id:
                return ""
            if m.get("_failed"):
                return "failed"
            return "read" if (m.get("seq") or 0) <= self._read_seq else "sent"
        if rn == "mediaUrl":
            return api.media_url(media["url"]) if media.get("url") else ""
        if rn == "mediaMime":
            return media.get("mime") or ""
        if rn == "mediaName":
            return media.get("name") or ""
        if rn == "mediaSize":
            return media.get("size") or 0
        if rn == "dayKey":
            return time.strftime("%Y-%m-%d", time.localtime(m.get("created_at") or 0))
        if rn == "isSystem":
            return m.get("kind") == "system"
        if rn == "replyBody":
            return reply.get("body") or ""
        if rn == "replySender":
            return reply.get("sender") or ""
        if rn == "clientMsgId":
            return m.get("client_msg_id") or ""
        if rn == "reactions":
            return ",".join(r.get("emoji", "") for r in (m.get("reactions") or []))
        if rn == "failed":
            return bool(m.get("_failed"))
        return None

    def roleNames(self):  # noqa: N802
        return {v: k.encode() for k, v in self.Roles.items()}

    # ------------------------------------------------------------ mutación

    def set_messages(self, messages: list[dict]) -> None:
        self.beginResetModel()
        self._items = messages
        self.endResetModel()

    def append(self, msg: dict) -> None:
        # evitar duplicados (WS + REST pueden cruzarse)
        mid = msg.get("id")
        if any(m.get("id") == mid for m in self._items):
            return
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items))
        self._items.append(msg)
        self.endInsertRows()

    def append_local(self, msg: dict) -> None:
        """Mensaje optimista (aún sin seq del servidor)."""
        self.beginInsertRows(QModelIndex(), len(self._items), len(self._items))
        self._items.append(msg)
        self.endInsertRows()

    def replace_local(self, client_msg_id: str, server_msg: dict) -> None:
        for i, m in enumerate(self._items):
            if m.get("client_msg_id") == client_msg_id:
                self._items[i] = server_msg
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)
                return

    def mark_failed(self, client_msg_id: str) -> None:
        for i, m in enumerate(self._items):
            if m.get("client_msg_id") == client_msg_id:
                m["_failed"] = True
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)
                return

    def refresh_states(self) -> None:
        if self._items:
            idx0 = self.index(0, 0)
            idx1 = self.index(len(self._items) - 1, 0)
            self.dataChanged.emit(idx0, idx1, [self.Roles["state"]])

    def bump_read(self, seq: int) -> None:
        if seq > self._read_seq:
            self._read_seq = seq
            self.refresh_states()

    def count(self) -> int:
        return len(self._items)

    def max_seq(self) -> int:
        return max((m.get("seq") or 0) for m in self._items) if self._items else 0
