#!/usr/bin/env python3
"""FoxMsg — cliente de escritorio (PySide6 + QML)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPixmap
from PySide6.QtQml import QQmlApplicationEngine

from core.bridge import Bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("foxmsg.client")


def main() -> int:
    app = QGuiApplication(sys.argv)
    app.setApplicationName("FoxMsg")
    app.setOrganizationName("FoxOrange")
    app.setDesktopFileName("foxmsg")

    bridge = Bridge()

    engine = QQmlApplicationEngine()
    # mostrar errores de QML en consola
    from PySide6.QtCore import qWarning
    import PySide6.QtQml
    try:
        engine.warnings.connect(
            lambda warns: [qWarning(str(w.toString())) for w in warns]
        )
    except Exception:
        pass
    ctx = engine.rootContext()
    ctx.setContextProperty("bridge", bridge)
    ctx.setContextProperty("chatsModel", bridge.chats)
    ctx.setContextProperty("messagesModel", bridge.messages)

    qml_dir = Path(__file__).parent / "qml"
    engine.load(qml_dir / "Main.qml")
    if not engine.rootObjects():
        log.error("No se pudo cargar QML")
        return 1

    # restaurar sesión si existe (asíncrono: navega por señal)
    bridge.restore_session()

    rc = app.exec()
    from core.ws import ws_client
    ws_client.stop()
    return rc


if __name__ == "__main__":
    sys.exit(main())
