#!/usr/bin/env python3
"""Captura pantallas de la UI en render offscreen (para revisar visualmente).

Uso: QT_QPA_PLATFORM=offscreen python3 tests/screenshot.py [login|chat]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication
# Importar QtQuick ANTES de cargar el QML: PySide6 decide el tipo del wrapper
# al crear el objeto, y sin esto la raíz se envuelve como QWindow (sin
# grabWindow). Con la importación previa queda como QQuickWindow.
from PySide6.QtQuick import QQuickWindow  # noqa: F401
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QUrl, QTimer

ARGS = sys.argv[1:]
sys.argv = ["screenshot"]
app = QGuiApplication(sys.argv)

from core.bridge import Bridge  # noqa: E402

bridge = Bridge()
eng = QQmlApplicationEngine()
ctx = eng.rootContext()
ctx.setContextProperty("bridge", bridge)
ctx.setContextProperty("chatsModel", bridge.chats)
ctx.setContextProperty("messagesModel", bridge.messages)
eng.load(QUrl.fromLocalFile(str(Path(__file__).parent.parent / "qml" / "Main.qml")))
roots = eng.rootObjects()
if not roots:
    print("no se cargó el QML")
    sys.exit(1)
win = roots[0]

OUT = Path("/tmp/opencode")
OUT.mkdir(parents=True, exist_ok=True)
mode = ARGS[0] if ARGS else "login"

if mode == "chat":
    # poblar el modelo con datos de ejemplo para revisar la vista de chat
    now = int(time.time())
    bridge.chats.set_chats([
        {"id": 1, "type": "dm",
         "title": {"id": 2, "username": "bruno", "display_name": "Bruno Díaz",
                   "online": True, "last_seen": now},
         "avatar_url": None, "member_count": 2,
         "last_message": {"seq": 5, "kind": "text", "body": "¡dale, nos vemos!",
                          "sender": {"id": 2, "username": "bruno"},
                          "created_at": now - 120},
         "unread": 2, "my_role": "member"},
        {"id": 2, "type": "group",
         "title": {"display_name": "Equipo Fox"},
         "avatar_url": None, "member_count": 4,
         "last_message": {"seq": 12, "kind": "text", "body": "subí el build",
                          "sender": {"id": 3, "username": "ana"}, "created_at": now - 3600},
         "unread": 0, "my_role": "owner"},
        {"id": 3, "type": "dm",
         "title": {"id": 4, "username": "marta", "display_name": "Marta",
                   "online": False, "last_seen": now - 7200},
         "avatar_url": None, "member_count": 2,
         "last_message": {"seq": 2, "kind": "image", "body": "",
                          "sender": {"id": 4, "username": "marta"},
                          "created_at": now - 86400},
         "unread": 0, "my_role": "member"},
    ])
    me = {"id": 1, "username": "ana", "display_name": "Ana Pérez",
          "avatar_url": None, "bio": "Hola!", "status_text": ""}
    bridge.messages.set_me(1)
    bridge.messages.set_messages([
        {"id": 1, "seq": 1, "chat_id": 1, "kind": "text",
         "body": "¡hola! ¿cómo estás?", "media": None, "reply_to": None,
         "client_msg_id": "a1", "created_at": now - 600,
         "sender": {"id": 2, "username": "bruno", "display_name": "Bruno Díaz",
                    "avatar_url": None},
         "reactions": []},
        {"id": 2, "seq": 2, "chat_id": 1, "kind": "text",
         "body": "bien! trabajando en FoxMsg 🦊", "media": None, "reply_to": None,
         "client_msg_id": "a2", "created_at": now - 540,
         "sender": {"id": 1, "username": "ana", "display_name": "Ana Pérez",
                    "avatar_url": None},
         "reactions": [{"user_id": 2, "emoji": "👍"}]},
        {"id": 3, "seq": 3, "chat_id": 1, "kind": "text",
         "body": "queda genial el tema oscuro", "media": None, "reply_to": None,
         "client_msg_id": "a3", "created_at": now - 300,
         "sender": {"id": 2, "username": "bruno", "display_name": "Bruno Díaz",
                    "avatar_url": None},
         "reactions": []},
        {"id": 4, "seq": 4, "chat_id": 1, "kind": "text",
         "body": "sí! y las burbujas con los checks ✓✓", "media": None,
         "reply_to": {"id": 3, "seq": 3, "body": "queda genial el tema oscuro",
                      "sender": "Bruno Díaz"},
         "client_msg_id": "a4", "created_at": now - 240,
         "sender": {"id": 1, "username": "ana", "display_name": "Ana Pérez",
                    "avatar_url": None},
         "reactions": []},
        {"id": 5, "seq": 5, "chat_id": 1, "kind": "text",
         "body": "¡dale, nos vemos!", "media": None, "reply_to": None,
         "client_msg_id": "a5", "created_at": now - 120,
         "sender": {"id": 2, "username": "bruno", "display_name": "Bruno Díaz",
                    "avatar_url": None},
         "reactions": []},
    ])
    bridge.messages.set_read_seq(3)
    # navegar a la app
    win.setProperty("view", "app")
    QTimer.singleShot(100, lambda: bridge.open_chat(1))


def grab():
    img = win.grabWindow()
    path = OUT / f"shot-{mode}.png"
    ok = img.save(str(path))
    print("guardado:", ok, path, f"{img.width()}x{img.height()}")
    app.quit()


QTimer.singleShot(1200 if mode == "chat" else 500, grab)
QTimer.singleShot(8000, app.quit)
app.exec()
