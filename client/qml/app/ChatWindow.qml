import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import QtQuick.Dialogs
import ".."   // singleton Theme (qmldir del directorio raíz)

// Ventana principal: panel de chats | conversación | panel lateral
Item {
    id: win

    property int activeChatId: 0
    property string activeTitle: ""
    property string activeSubtitle: ""
    property string activeAvatar: ""
    property bool sidePanel: false
    property int sidePanelWidth: 0

    // índice del chat abierto en chatsModel
    function chatIndex(id) {
        for (var i = 0; i < chatsModel.rowCount(); i++) {
            if (chatsModel.data(chatsModel.index(i, 0), chatsModel.Roles.chatId) === id)
                return i
        }
        return -1
    }

    function openChat(id, title, subtitle, avatar) {
        activeChatId = id
        activeTitle = title
        activeSubtitle = subtitle
        activeAvatar = avatar
        bridge.open_chat(id)
        msgInput.forceActiveFocus()
    }

    Connections {
        target: bridge
        function onOpenChatRequested(id) {
            // abrir el chat en la UI (bridge.open_chat puede venir de un
            // diálogo nuevo o de otra vista sin pasar por openChat)
            activeChatId = id
            // refrescar cabecera con los datos del modelo
            var i = win.chatIndex(id)
            if (i >= 0) {
                var idx = chatsModel.index(i, 0)
                activeTitle = chatsModel.data(idx, chatsModel.Roles.title) || activeTitle
                activeAvatar = chatsModel.data(idx, chatsModel.Roles.avatarUrl) || ""
            }
            bridge.mark_read(id)
            scrollToEnd()
        }
        function onMessagesReset() { scrollToEnd() }
        function onMessagesAppended() { scrollToEnd() }
        function onChatsUpdated() {
            // si el chat activo cambió de título/estado, refrescar cabecera
            if (activeChatId > 0) {
                var i = chatIndex(activeChatId)
                if (i >= 0) {
                    var idx = chatsModel.index(i, 0)
                    activeTitle = chatsModel.data(idx, chatsModel.Roles.title) || activeTitle
                    activeAvatar = chatsModel.data(idx, chatsModel.Roles.avatarUrl) || activeAvatar
                }
            }
        }
    }

    function scrollToEnd() {
        if (msgList.count > 0)
            positionViewAtIndex(msgList.count - 1, ListView.End)
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ================================================ PANEL DE CHATS
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: Theme.sidebarW
            Layout.minimumWidth: 280
            Layout.maximumWidth: 420
            color: Theme.sidebar

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // --- cabecera del panel
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 62
                    color: Theme.header

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 10

                        Rectangle {
                            width: 40; height: 40; radius: 20
                            color: Theme.accent
                            Label {
                                anchors.centerIn: parent
                                text: "🦊"
                                font.pixelSize: 20
                            }
                        }
                        Label {
                            text: "FoxMsg"
                            font.pixelSize: Theme.fsTitle
                            font.bold: true
                            color: Theme.textPri
                            Layout.fillWidth: true
                        }
                        // nuevo chat
                        Rectangle {
                            width: 34; height: 34; radius: 17
                            color: mouseNew.containsMouse ? Theme.border : "transparent"
                            Label { anchors.centerIn: parent; text: "✏️"; font.pixelSize: 16 }
                            MouseArea {
                                id: mouseNew
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: newChatDialog.open()
                            }
                        }
                        // menú (perfil/ajustes/salir)
                        Rectangle {
                            width: 34; height: 34; radius: 17
                            color: mouseMenu.containsMouse ? Theme.border : "transparent"
                            Label { anchors.centerIn: parent; text: "⋮"; font.pixelSize: 18
                                    color: Theme.textPri }
                            MouseArea {
                                id: mouseMenu
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: menuPopup.open()
                            }
                            Menu {
                                id: menuPopup
                                y: parent.height
                                MenuItem {
                                    text: "Mi perfil"
                                    onTriggered: profileDialog.open()
                                }
                                MenuItem {
                                    text: bridge.server_label() === "tailscale"
                                          ? "🌐 Conectado por Tailscale"
                                          : "🌐 " + bridge.server_label()
                                    enabled: false
                                }
                                MenuSeparator {}
                                MenuItem {
                                    text: "Cerrar sesión"
                                    onTriggered: bridge.logout()
                                }
                            }
                        }
                    }
                }

                // --- buscador
                Rectangle {
                    Layout.fillWidth: true
                    Layout.margins: 8
                    Layout.preferredHeight: 40
                    radius: Theme.radius
                    color: Theme.panelAlt

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 6
                        Label { text: "🔍"; font.pixelSize: 14; opacity: 0.7 }
                        TextField {
                            id: searchField
                            Layout.fillWidth: true
                            placeholderText: "Buscar chats…"
                            background: Item {}
                            color: Theme.textPri
                            font.pixelSize: Theme.fsBody
                        }
                        Label {
                            visible: searchField.text.length > 0
                            text: "✕"
                            color: Theme.textSec
                            MouseArea {
                                anchors.fill: parent
                                onClicked: searchField.text = ""
                            }
                        }
                    }
                }

                // --- lista
                ListView {
                    id: chatList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: chatsModel

                    displaced: Transition {
                        NumberAnimation { properties: "x,y"; duration: 150; easing.type: Easing.OutQuad }
                    }

                    delegate: Rectangle {
                        id: chatRow
                        property bool active: win.activeChatId === model.chatId
                        property bool matched: {
                            if (!searchField.text) return true
                            var q = searchField.text.toLowerCase()
                            return (model.title || "").toLowerCase().indexOf(q) >= 0
                                   || (model.username || "").toLowerCase().indexOf(q) >= 0
                                   || (model.lastBody || "").toLowerCase().indexOf(q) >= 0
                        }
                        visible: matched
                        height: matched ? 72 : 0
                        width: chatList.width
                        color: active ? Theme.accent
                             : (hoverArea.containsMouse ? Theme.panelAlt : "transparent")

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 10

                            // avatar
                            Rectangle {
                                width: 52; height: 52; radius: 26
                                color: Theme.border
                                clip: true
                                Image {
                                    anchors.fill: parent
                                    source: model.avatarUrl || ""
                                    fillMode: Image.PreserveAspectCrop
                                    visible: status === Image.Ready
                                    sourceSize: Qt.size(104, 104)
                                }
                                Label {
                                    anchors.centerIn: parent
                                    visible: !model.avatarUrl
                                    text: model.isGroup ? "👥"
                                         : (model.title || "?").charAt(0).toUpperCase()
                                    font.pixelSize: 22
                                    font.bold: true
                                    color: Theme.textPri
                                }
                                // indicador online (solo DM)
                                Rectangle {
                                    visible: !model.isGroup && model.online
                                    width: 13; height: 13; radius: 7
                                    color: "#25d366"
                                    border.color: active ? Theme.accent : Theme.sidebar
                                    border.width: 2
                                    anchors.right: parent.right
                                    anchors.bottom: parent.bottom
                                }
                            }

                            // textos
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                RowLayout {
                                    Layout.fillWidth: true
                                    Label {
                                        Layout.fillWidth: true
                                        text: model.title || "(sin nombre)"
                                        font.pixelSize: Theme.fsBody
                                        font.bold: true
                                        elide: Text.ElideRight
                                        color: active ? "white" : Theme.textPri
                                    }
                                    Label {
                                        text: model.lastTime ? Theme.timeStr(model.lastTime) : ""
                                        font.pixelSize: Theme.fsSmall
                                        color: active ? "#e0ffffff" : Theme.textSec
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6
                                    Label {
                                        Layout.fillWidth: true
                                        text: (model.senderName && !model.isGroup
                                               && model.senderName === bridge.me_username()
                                               ? "Tú: " : "")
                                              + (model.lastBody || "Sin mensajes")
                                        font.pixelSize: Theme.fsSmall
                                        elide: Text.ElideRight
                                        color: active ? "#e0ffffff" : Theme.textSec
                                    }
                                    // badge de no leídos
                                    Rectangle {
                                        visible: model.unread > 0
                                        width: Math.max(22, unreadLabel.implicitWidth + 10)
                                        height: 20; radius: 10
                                        color: active ? "white" : Theme.unreadBadge
                                        Label {
                                            id: unreadLabel
                                            anchors.centerIn: parent
                                            text: model.unread > 99 ? "99+" : model.unread
                                            font.pixelSize: 11
                                            font.bold: true
                                            color: active ? Theme.accent : "white"
                                        }
                                    }
                                }
                            }
                        }

                        MouseArea {
                            id: hoverArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: win.openChat(
                                model.chatId, model.title, "", model.avatarUrl)
                        }
                    }

                    // estado vacío
                    Label {
                        visible: chatList.count === 0
                        anchors.centerIn: parent
                        text: "No hay chats todavía.\nTocá ✏️ para buscar un contacto."
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.textSec
                        font.pixelSize: Theme.fsBody
                    }
                }
            }
        }

        // separador
        Rectangle { Layout.fillHeight: true; width: 1; color: Theme.border }

        // ================================================ CONVERSACIÓN
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.bg

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // --- cabecera de conversación
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 62
                    color: Theme.header
                    visible: win.activeChatId > 0

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 10

                        Rectangle {
                            width: 40; height: 40; radius: 20
                            color: Theme.border
                            clip: true
                            Image {
                                anchors.fill: parent
                                source: win.activeAvatar
                                fillMode: Image.PreserveAspectCrop
                                visible: status === Image.Ready
                                sourceSize: Qt.size(80, 80)
                            }
                            Label {
                                anchors.centerIn: parent
                                visible: win.activeAvatar === ""
                                text: (win.activeTitle || "?").charAt(0).toUpperCase()
                                font.bold: true
                                color: Theme.textPri
                            }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 0
                            Label {
                                text: win.activeTitle || "Conversación"
                                font.pixelSize: Theme.fsTitle
                                font.bold: true
                                color: Theme.textPri
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            // subtítulo: "escribiendo…" o miembros
                            Label {
                                id: subtitleLabel
                                text: ""
                                font.pixelSize: Theme.fsSmall
                                color: Theme.accent
                                visible: text.length > 0
                            }
                        }
                        // botón panel lateral
                        Label {
                            text: "ⓘ"
                            font.pixelSize: 18
                            color: Theme.textSec
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    win.sidePanel = !win.sidePanel
                                    sideAnim.target = win
                                    sideAnim.property = "sidePanelWidth"
                                    sideAnim.to = win.sidePanel ? 300 : 0
                                    sideAnim.start()
                                }
                            }
                        }
                    }

                    NumberAnimation {
                        id: sideAnim
                        duration: 200
                        easing.type: Easing.OutQuad
                    }

                    Connections {
                        target: bridge
                        function onTypingChanged(chatId, username) {
                            if (chatId === win.activeChatId && username) {
                                subtitleLabel.text = username + " está escribiendo…"
                                typingReset.restart()
                            }
                        }
                        function onPresenceChanged(userId, online) { /* refrescar cabecera */ }
                    }
                    Timer {
                        id: typingReset
                        interval: 3000
                        onTriggered: subtitleLabel.text = ""
                    }
                }

                // --- zona de mensajes
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Theme.bg

                    ListView {
                        id: msgList
                        anchors.fill: parent
                        anchors.margins: 8
                        clip: true
                        spacing: 3
                        model: messagesModel
                        verticalLayoutDirection: ListView.TopToBottom

                        // separadores de fecha + burbujas
                        delegate: Item {
                            id: msgWrap
                            width: msgList.width
                            // col ya incluye dayLabel cuando está visible
                            // (Column omite los hijos invisibles)
                            height: col.height

                            property bool showDay: {
                                if (model.index === 0) return true
                                var prev = messagesModel.data(messagesModel.index(model.index - 1, 0),
                                                              messagesModel.Roles.dayKey)
                                return prev !== model.dayKey
                            }

                            Column {
                                id: col
                                width: parent.width
                                spacing: 0

                                Label {
                                    id: dayLabel
                                    visible: msgWrap.showDay
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: Theme.dayStr(model.time)
                                    font.pixelSize: 11
                                    font.bold: true
                                    color: Theme.textSec
                                    background: Rectangle {
                                        radius: 8; color: Theme.panelAlt
                                        implicitWidth: dayLabel.implicitWidth + 16
                                        implicitHeight: dayLabel.implicitHeight + 6
                                    }
                                    topPadding: 3; bottomPadding: 3
                                    leftPadding: 8; rightPadding: 8
                                }

                                // mensaje del sistema: centrado y opaco
                                Label {
                                    visible: model.isSystem
                                    width: parent.width
                                    horizontalAlignment: Text.AlignHCenter
                                    text: model.body
                                    font.pixelSize: Theme.fsSmall
                                    color: Theme.textSec
                                    wrapMode: Text.WordWrap
                                    topPadding: 6; bottomPadding: 6
                                    leftPadding: 40; rightPadding: 40
                                }

                                // burbuja normal
                                RowLayout {
                                    visible: !model.isSystem
                                    width: parent.width
                                    spacing: 8
                                    Item {
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: 1
                                        height: bubble.implicitHeight
                                        visible: model.mine
                                    }

                                    Rectangle {
                                        id: bubble
                                        property int maxW: msgList.width * 0.68
                                        // Ancho natural del contenido. El `implicitWidth`
                                        // de un Text con wrap es su ancho SIN envolver, es
                                        // decir no depende del ancho resuelto → sin bucle
                                        // de binding (antes colapsaba la burbuja a 10 px).
                                        property int contentW: Math.max(
                                            txt.implicitWidth,
                                            replyBox.visible ? replyTxt.implicitWidth + 30 : 0,
                                            imgBox.visible ? 280 : 0,
                                            fileBox.visible ? 230 : 0,
                                            70)   // hora + checks
                                        implicitWidth: Math.min(contentW + 22, maxW)
                                        implicitHeight: bubbleCol.implicitHeight + 12
                                        radius: 12
                                        color: model.mine ? Theme.bubbleMine : Theme.bubbleTheirs

                                        // esquinas asimétricas (estilo WhatsApp)
                                        Rectangle {
                                            anchors.left: model.mine ? undefined : parent.left
                                            anchors.right: model.mine ? parent.right : undefined
                                            anchors.bottom: parent.bottom
                                            width: 12; height: 12
                                            color: parent.color
                                            Rectangle {
                                                width: 12; height: 12
                                                anchors.right: parent.right
                                                anchors.bottom: parent.bottom
                                                color: model.mine ? Theme.bg : Theme.bg
                                                radius: 12
                                                Rectangle {
                                                    width: 6; height: 6
                                                    anchors.left: parent.left
                                                    anchors.top: parent.top
                                                    color: model.mine ? Theme.bubbleMine
                                                         : Theme.bubbleTheirs
                                                }
                                            }
                                        }

                                        Column {
                                            id: bubbleCol
                                            x: 11
                                            y: 6
                                            width: bubble.implicitWidth - 22
                                            spacing: 3

                                            // respuesta citada
                                            Rectangle {
                                                id: replyBox
                                                visible: model.replyBody !== ""
                                                width: parent.width
                                                height: replyCol.implicitHeight + 8
                                                radius: 6
                                                color: Qt.rgba(0, 0, 0, 0.18)
                                                Rectangle {
                                                    width: 3; height: parent.height
                                                    color: Theme.accent
                                                    radius: 2
                                                }
                                                    Column {
                                                        id: replyCol
                                                        anchors.left: parent.left
                                                        anchors.leftMargin: 10
                                                        anchors.right: parent.right
                                                        anchors.rightMargin: 6
                                                        anchors.verticalCenter: parent.verticalCenter
                                                        spacing: 1
                                                        Label {
                                                            text: model.replySender
                                                            font.pixelSize: Theme.fsSmall
                                                            font.bold: true
                                                            color: Theme.accent
                                                        }
                                                        Label {
                                                            id: replyTxt
                                                            width: parent.width
                                                            text: model.replyBody
                                                        font.pixelSize: Theme.fsSmall
                                                        color: Theme.textSec
                                                        elide: Text.ElideRight
                                                        maximumLineCount: 2
                                                    }
                                                }
                                            }

                                            // imagen
                                            Rectangle {
                                                id: imgBox
                                                visible: model.kind === "image" && model.mediaUrl !== ""
                                                width: Math.min(parent.width, 280)
                                                height: 190
                                                radius: 8
                                                color: Qt.rgba(0,0,0,0.2)
                                                clip: true
                                                Image {
                                                    anchors.fill: parent
                                                    source: model.mediaUrl
                                                    fillMode: Image.PreserveAspectCrop
                                                    sourceSize.width: 560
                                                    asynchronous: true
                                                }
                                                MouseArea {
                                                    anchors.fill: parent
                                                    cursorShape: Qt.PointingHandCursor
                                                    onClicked: Qt.openUrlExternally(model.mediaUrl)
                                                }
                                            }

                                            // archivo / nota de voz (tarjeta)
                                            Rectangle {
                                                id: fileBox
                                                visible: model.kind === "file" || model.kind === "voice"
                                                width: parent.width
                                                height: fileRow.implicitHeight + 12
                                                radius: 8
                                                color: Qt.rgba(0,0,0,0.15)
                                                RowLayout {
                                                    id: fileRow
                                                    anchors.fill: parent
                                                    anchors.margins: 6
                                                    spacing: 8
                                                    Label {
                                                        text: model.kind === "voice" ? "🎙" : "📄"
                                                        font.pixelSize: 22
                                                    }
                                                    ColumnLayout {
                                                        Layout.fillWidth: true
                                                        spacing: 0
                                                        Label {
                                                            Layout.fillWidth: true
                                                            text: model.kind === "voice"
                                                                  ? "Nota de voz"
                                                                  : (model.mediaName || "Archivo")
                                                            font.pixelSize: Theme.fsSmall
                                                            font.bold: true
                                                            elide: Text.ElideRight
                                                            color: Theme.textPri
                                                        }
                                                        Label {
                                                            text: model.mediaSize
                                                                  ? Theme.humanSize(model.mediaSize) : ""
                                                            font.pixelSize: 11
                                                            color: Theme.textSec
                                                        }
                                                    }
                                                    Label {
                                                        text: "⬇"
                                                        font.pixelSize: 16
                                                        color: Theme.accent
                                                        MouseArea {
                                                            anchors.fill: parent
                                                            onClicked:
                                                                Qt.openUrlExternally(model.mediaUrl)
                                                        }
                                                    }
                                                }
                                            }

                                            // texto
                                            Label {
                                                id: txt
                                                visible: model.body !== ""
                                                width: parent.width
                                                text: model.body
                                                font.pixelSize: Theme.fsBody
                                                color: Theme.textPri
                                                wrapMode: Text.Wrap
                                                textFormat: Text.StyledText
                                            }

                                            // pie: hora + checks
                                            RowLayout {
                                                width: parent.width
                                                spacing: 4
                                                Item { Layout.fillWidth: true }
                                                Label {
                                                    visible: model.reactions !== ""
                                                    text: model.reactions
                                                    font.pixelSize: 14
                                                }
                                                Label {
                                                    text: Theme.timeStr(model.time)
                                                    font.pixelSize: 10
                                                    color: model.mine
                                                          ? Qt.rgba(1,1,1,0.6) : Theme.textSec
                                                }
                                                // checks de estado
                                                Label {
                                                    visible: model.mine
                                                    text: model.state === "read" ? "✓✓"
                                                        : model.state === "failed" ? "⚠"
                                                        : "✓"
                                                    font.pixelSize: 12
                                                    font.bold: true
                                                    color: model.state === "read"
                                                           ? "#53bdeb"
                                                           : model.state === "failed"
                                                             ? Theme.danger
                                                             : Qt.rgba(1,1,1,0.6)
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        enabled: model.state === "failed"
                                                        cursorShape: Qt.PointingHandCursor
                                                        onClicked: bridge.retry_send(model.clientMsgId)
                                                    }
                                                }
                                            }
                                        }

                                        // menú al hover (responder/copiar/react)
                                        Rectangle {
                                            visible: hoverMsg.containsMouse && !model.isSystem
                                            anchors.right: model.mine ? parent.left : undefined
                                            anchors.left: model.mine ? undefined : parent.right
                                            anchors.verticalCenter: parent.verticalCenter
                                            width: 84; height: 30
                                            radius: 8
                                            color: Theme.panel
                                            border.color: Theme.border
                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.margins: 4
                                                spacing: 6
                                                Label { text: "↩"; font.pixelSize: 13
                                                        MouseArea { anchors.fill: parent
                                                            onClicked: {
                                                                // responder: precargar (simplificado)
                                                                msgInput.forceActiveFocus()
                                                            } } }
                                                Label { text: "📋"; font.pixelSize: 13
                                                        MouseArea { anchors.fill: parent
                                                            onClicked:
                                                                bridge.copy_text(model.body) } }
                                                Label { text: "👍"; font.pixelSize: 13
                                                        MouseArea { anchors.fill: parent
                                                            onClicked:
                                                                bridge.react(model.msgId + ":👍") } }
                                                Label { text: "❤️"; font.pixelSize: 13
                                                        MouseArea { anchors.fill: parent
                                                            onClicked:
                                                                bridge.react(model.msgId + ":❤️") } }
                                            }
                                        }
                                        MouseArea {
                                            id: hoverMsg
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            acceptedButtons: Qt.RightButton | Qt.LeftButton
                                            onClicked: (mouse) => {
                                                if (mouse.button === Qt.RightButton)
                                                    ctxMenu.popup()
                                            }
                                        }
                                        Menu {
                                            id: ctxMenu
                                            MenuItem {
                                                text: "Copiar mensaje"
                                                onTriggered: bridge.copy_text(model.body)
                                            }
                                            MenuItem {
                                                text: "Responder"
                                                onTriggered: msgInput.forceActiveFocus()
                                            }
                                            MenuItem {
                                                text: "Reaccionar 👍"
                                                onTriggered:
                                                    bridge.react(model.msgId + ":👍")
                                            }
                                        }
                                    }

                                    Item {
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: 1
                                        height: bubble.implicitHeight
                                        visible: !model.mine
                                    }
                                }
                            }
                        }

                        // indicador "mensajes nuevos" al scrollear arriba
                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }
                    }

                    // estado vacío de conversación
                    Label {
                        visible: win.activeChatId === 0
                        anchors.centerIn: parent
                        text: "🦊\nElegí un chat o empezá uno nuevo"
                        horizontalAlignment: Text.AlignHCenter
                        color: Theme.textSec
                        font.pixelSize: Theme.fsTitle
                        opacity: 0.7
                    }
                }

                // --- barra de escritura
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: win.activeChatId > 0 ? 74 : 0
                    visible: win.activeChatId > 0
                    color: Theme.panel

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 10
                        anchors.rightMargin: 10
                        spacing: 8

                        // adjuntar
                        Rectangle {
                            width: 38; height: 38; radius: 19
                            color: hoverAttach.containsMouse ? Theme.panelAlt : "transparent"
                            Label { anchors.centerIn: parent; text: "📎"; font.pixelSize: 18 }
                            MouseArea {
                                id: hoverAttach
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: attachMenu.open()
                            }
                            Menu {
                                id: attachMenu
                                MenuItem {
                                    text: "📷 Foto o imagen"
                                    onTriggered: {
                                        attachDialog.nameFilters =
                                            ["Imágenes (*.png *.jpg *.jpeg *.webp *.gif)"]
                                        attachDialog.selectedKind = "image"
                                        attachDialog.open()
                                    }
                                }
                                MenuItem {
                                    text: "📎 Archivo"
                                    onTriggered: {
                                        attachDialog.nameFilters = ["Todos los archivos (*)"]
                                        attachDialog.selectedKind = "file"
                                        attachDialog.open()
                                    }
                                }
                            }
                        }

                        // campo de texto (contenedor redondeado)
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.min(inputCol.implicitHeight + 16, 130)
                            radius: Theme.radiusBig
                            color: Theme.panelAlt
                            border.color: msgInput.activeFocus ? Theme.accent : "transparent"
                            border.width: 1

                            Column {
                                id: inputCol
                                anchors.fill: parent
                                anchors.margins: 8
                                spacing: 4

                                // preview de adjunto
                                RowLayout {
                                    visible: pendingFile !== ""
                                    spacing: 8
                                    Label { text: "📎"; font.pixelSize: 16 }
                                    Label {
                                        Layout.fillWidth: true
                                        text: pendingFileName
                                        elide: Text.ElideRight
                                        font.pixelSize: Theme.fsSmall
                                        color: Theme.textPri
                                    }
                                    Label {
                                        text: "✕"
                                        color: Theme.textSec
                                        MouseArea {
                                            anchors.fill: parent
                                            onClicked: {
                                                pendingFile = ""
                                                pendingFileName = ""
                                            }
                                        }
                                    }
                                }

                                TextArea {
                                    id: msgInput
                                    width: parent.width
                                    Layout.fillWidth: true
                                    height: Math.min(contentHeight, 96)
                                    placeholderText: "Escribe un mensaje…"
                                    wrapMode: TextEdit.Wrap
                                    color: Theme.textPri
                                    font.pixelSize: Theme.fsBody
                                    background: Item {}
                                    property string pendingFile: ""
                                    property string pendingFileName: ""

                                    Keys.onReturnPressed: (event) => {
                                        if (!(event.modifiers & Qt.ShiftModifier)) {
                                            event.accepted = true
                                            sendCurrent()
                                        }
                                    }
                                }
                            }
                        }

                        // enviar / micrófono
                        Rectangle {
                            width: 44; height: 44; radius: 22
                            color: canSend ? Theme.accent
                                 : (hoverSend.containsMouse ? Theme.border : Theme.panelAlt)
                            property bool canSend: msgInput.text.trim().length > 0
                                                   || pendingFile !== ""
                            Label {
                                anchors.centerIn: parent
                                text: parent.canSend ? "➤" : "🎤"
                                font.pixelSize: 18
                                color: parent.canSend ? "white" : Theme.textSec
                            }
                            MouseArea {
                                id: hoverSend
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: sendCurrent()
                            }
                        }
                    }
                }
            }
        }
    }

    // estado pendiente de adjunto (en el scope de la ventana)
    property string pendingFile: ""
    property string pendingFileName: ""

    function sendCurrent() {
        if (pendingFile !== "") {
            bridge.send_file(pendingFile, pendingAttachKind, msgInput.text.trim())
            pendingFile = ""
            pendingFileName = ""
        } else if (msgInput.text.trim().length > 0) {
            bridge.send_text(msgInput.text)
        }
        msgInput.text = ""
        msgInput.forceActiveFocus()
    }
    property string pendingAttachKind: "file"

    FileDialog {
        id: attachDialog
        property string selectedKind: "file"
        title: "Elegí un archivo"
        onAccepted: {
            pendingFile = selectedFile.toString().replace("file://", "")
            pendingFileName = fileName || pendingFile.split("/").pop()
            pendingAttachKind = selectedKind
        }
    }

    // ================================================ diálogo nuevo chat
    Popup {
        id: newChatDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(440, parent.width - 40)
        height: Math.min(460, parent.height - 40)
        padding: 0
        background: Rectangle {
            radius: Theme.radiusBig
            color: Theme.panel
            border.color: Theme.border
        }

        onOpened: {
            searchContact.text = ""
            resultsModel.clear()
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "Nuevo chat"
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                    color: Theme.textPri
                    Layout.fillWidth: true
                }
                Label {
                    text: "✕"
                    font.pixelSize: 16
                    color: Theme.textSec
                    MouseArea {
                        anchors.fill: parent
                        onClicked: newChatDialog.close()
                    }
                }
            }

            // pestañas: contacto | grupo
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Rectangle {
                    Layout.fillWidth: true; height: 34; radius: 8
                    color: tabs.currentIndex === 0 ? Theme.accent : Theme.panelAlt
                    Label {
                        anchors.centerIn: parent
                        text: "Contacto"
                        color: tabs.currentIndex === 0 ? "white" : Theme.textSec
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: tabs.currentIndex = 0
                    }
                }
                Rectangle {
                    Layout.fillWidth: true; height: 34; radius: 8
                    color: tabs.currentIndex === 1 ? Theme.accent : Theme.panelAlt
                    Label {
                        anchors.centerIn: parent
                        text: "Grupo nuevo"
                        color: tabs.currentIndex === 1 ? "white" : Theme.textSec
                    }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: tabs.currentIndex = 1
                    }
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: tabs.currentIndex

                // ---------------- buscar contacto
                ColumnLayout {
                    spacing: 8
                    TextField {
                        id: searchContact
                        Layout.fillWidth: true
                        placeholderText: "Buscar por usuario o nombre…"
                        color: Theme.textPri
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: Theme.border
                        }
                        onTextChanged: {
                            debounce.stop()
                            debounce.start()
                        }
                    }
                    Timer {
                        id: debounce
                        interval: 300
                        onTriggered: bridge.search_contacts(searchContact.text)
                    }

                    ListView {
                        id: resultsList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: ListModel { id: resultsModel }

                        delegate: Rectangle {
                            width: resultsList.width
                            height: visible ? 56 : 0
                            visible: true
                            radius: 8
                            color: hoverRes.containsMouse ? Theme.panelAlt : "transparent"

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 6
                                spacing: 10
                                Rectangle {
                                    width: 40; height: 40; radius: 20
                                    color: Theme.border
                                    Label {
                                        anchors.centerIn: parent
                                        text: (model.name || "?").charAt(0).toUpperCase()
                                        font.bold: true
                                        color: Theme.textPri
                                    }
                                }
                                ColumnLayout {
                                    spacing: 0
                                    Label {
                                        text: model.name
                                        font.bold: true
                                        color: Theme.textPri
                                        font.pixelSize: Theme.fsBody
                                    }
                                    Label {
                                        text: "@" + model.username
                                        color: Theme.textSec
                                        font.pixelSize: Theme.fsSmall
                                    }
                                }
                            }
                            MouseArea {
                                id: hoverRes
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    bridge.open_dm(model.username)
                                    newChatDialog.close()
                                }
                            }
                        }

                        Label {
                            visible: resultsList.count === 0 && searchContact.text.length >= 2
                            anchors.centerIn: parent
                            text: "Sin resultados"
                            color: Theme.textSec
                        }
                    }
                }

                // ---------------- crear grupo
                ColumnLayout {
                    spacing: 10
                    TextField {
                        id: groupTitle
                        Layout.fillWidth: true
                        placeholderText: "Nombre del grupo"
                        color: Theme.textPri
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: Theme.border
                        }
                    }
                    TextField {
                        id: groupMembers
                        Layout.fillWidth: true
                        placeholderText: "Miembros (separados por coma): ana, bruno"
                        color: Theme.textPri
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: Theme.border
                        }
                    }
                    Button {
                        Layout.fillWidth: true
                        text: "Crear grupo"
                        enabled: groupTitle.text.length > 0
                                 && groupMembers.text.length > 0
                        contentItem: Text {
                            text: parent.text; font: parent.font; color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: Theme.radius
                            color: parent.enabled ? Theme.accent : Theme.border
                        }
                        onClicked: {
                            bridge.create_group(groupTitle.text, groupMembers.text)
                            newChatDialog.close()
                            groupTitle.text = ""
                            groupMembers.text = ""
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: "Todos los usuarios deben tener la cuenta verificada."
                        color: Theme.textSec
                        font.pixelSize: Theme.fsSmall
                    }
                }
            }
        }
    }

    QtObject {
        id: tabs
        property int currentIndex: 0
    }

    // ================================================ diálogo de perfil
    Popup {
        id: profileDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(420, parent.width - 40)
        padding: 20
        background: Rectangle {
            radius: Theme.radiusBig; color: Theme.panel
            border.color: Theme.border
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: "Mi perfil"
                    font.pixelSize: Theme.fsTitle
                    font.bold: true
                    color: Theme.textPri
                    Layout.fillWidth: true
                }
                Label {
                    text: "✕"
                    color: Theme.textSec
                    MouseArea {
                        anchors.fill: parent
                        onClicked: profileDialog.close()
                    }
                }
            }

            RowLayout {
                spacing: 12
                Layout.alignment: Qt.AlignHCenter
                Rectangle {
                    width: 72; height: 72; radius: 36
                    color: Theme.border
                    clip: true
                    Image {
                        anchors.fill: parent
                        source: bridge.my_avatar_url()
                        fillMode: Image.PreserveAspectCrop
                        visible: status === Image.Ready
                    }
                    Label {
                        anchors.centerIn: parent
                        text: "📷"
                        font.pixelSize: 24
                        visible: bridge.my_avatar_url() === ""
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: avatarDlg.open()
                    }
                }
                ColumnLayout {
                    spacing: 2
                    Label {
                        text: "@" + bridge.me_username()
                        font.pixelSize: Theme.fsSmall
                        color: Theme.textSec
                    }
                    Label {
                        text: "Clic en el avatar para cambiarlo"
                        font.pixelSize: Theme.fsSmall
                        color: Theme.textSec
                        opacity: 0.7
                    }
                }
            }

            Label { text: "Nombre para mostrar"; color: Theme.textSec
                    font.pixelSize: Theme.fsSmall }
            TextField {
                id: pName
                Layout.fillWidth: true
                text: bridge.me_display()
                color: Theme.textPri
                background: Rectangle {
                    radius: Theme.radius; color: Theme.panelAlt
                    border.color: Theme.border
                }
            }

            Label { text: "Descripción"; color: Theme.textSec
                    font.pixelSize: Theme.fsSmall }
            TextArea {
                id: pBio
                Layout.fillWidth: true
                Layout.preferredHeight: 70
                wrapMode: TextEdit.Wrap
                color: Theme.textPri
                background: Rectangle {
                    radius: Theme.radius; color: Theme.panelAlt
                    border.color: Theme.border
                }
            }

            Label { text: "Estado (estilo WhatsApp)"; color: Theme.textSec
                    font.pixelSize: Theme.fsSmall }
            TextField {
                id: pStatus
                Layout.fillWidth: true
                placeholderText: "Disponible…"
                color: Theme.textPri
                background: Rectangle {
                    radius: Theme.radius; color: Theme.panelAlt
                    border.color: Theme.border
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Label {
                    text: "Cancelar"
                    color: Theme.textSec
                    font.underline: true
                    MouseArea {
                        anchors.fill: parent
                        onClicked: profileDialog.close()
                    }
                }
                Button {
                    text: "Guardar"
                    contentItem: Text {
                        text: parent.text; font: parent.font; color: "white"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: Theme.radius; color: Theme.accent
                    }
                    onClicked: {
                        bridge.update_profile(pName.text, pBio.text, pStatus.text)
                        profileDialog.close()
                    }
                }
            }
        }

        FileDialog {
            id: avatarDlg
            nameFilters: ["Imágenes (*.png *.jpg *.jpeg *.webp *.gif)"]
            onAccepted: bridge.set_avatar(selectedFile.toString().replace("file://", ""))
        }
    }
}
