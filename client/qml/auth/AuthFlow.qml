import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."   // singleton Theme (qmldir del directorio raíz)

// Flujo de autenticación: Login <-> Registro -> Perfil
Item {
    id: flow

    // subvista: "login" | "register" | "profile"
    property string sub: "login"
    // true entre que se pulsa "Crear cuenta" y el servidor confirma el registro
    property bool registering: false

    function doLogin() {
        if (loginId.text.length > 0 && loginPw.text.length > 0) {
            bridge.login(loginId.text, loginPw.text)
        }
    }

    Rectangle { anchors.fill: parent; color: Theme.bg }

    // -------------------------------------------------- puente con bridge
    Connections {
        target: bridge
        function onVerificationRequired(masked, resendAfter) {
            if (registering) {
                registering = false
                // el servidor confirmó el registro: pasar al paso de perfil
                flow.sub = "profile"
            }
        }
        function onToast(msg, type) {
            if (registering && type === "error") {
                registering = false
                // se queda en register para reintentar
            }
        }
    }

    // ---------------------------------------------- layout split
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // -------- panel izquierdo decorativo (solo pantallas anchas)
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: 1
            visible: parent.width > 760
            color: Theme.accent

            Column {
                anchors.centerIn: parent
                spacing: 18
                width: parent.width * 0.7

                Label {
                    text: "🦊"
                    font.pixelSize: 72
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                Label {
                    text: "FoxMsg"
                    font.pixelSize: 40
                    font.bold: true
                    color: "white"
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                Label {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    text: "Tu centro de mensajería propio.\nRápido, privado y en tu servidor."
                    font.pixelSize: 17
                    color: "#e0ffffff"
                }
            }
        }

        // -------- formulario
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 460
            Layout.maximumWidth: 520
            Layout.minimumWidth: 340
            color: Theme.dark ? "#0f1a1f" : "#ffffff"

            StackLayout {
                anchors.fill: parent
                anchors.margins: 40
                currentIndex: sub === "login" ? 0 : (sub === "register" ? 1 : 2)

                // =================================================== LOGIN
                ColumnLayout {
                    spacing: 14
                    Layout.alignment: Qt.AlignVCenter

                    Label { text: "Ingresá a FoxMsg"; font.pixelSize: Theme.fsBig
                            font.bold: true; color: Theme.textPri
                            Layout.bottomMargin: 10 }

                    Label { text: "Usuario o correo"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }

                    TextField {
                        id: loginId
                        Layout.fillWidth: true
                        placeholderText: "ana o ana@mail.com"
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        background: Rectangle {
                            radius: Theme.radius
                            color: Theme.panelAlt
                            border.color: loginId.activeFocus ? Theme.accent : Theme.border
                            border.width: loginId.activeFocus ? 2 : 1
                        }
                        onAccepted: loginPw.forceActiveFocus()
                    }

                    Label { text: "Contraseña"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }

                    TextField {
                        id: loginPw
                        Layout.fillWidth: true
                        placeholderText: "••••••••"
                        echoMode: TextInput.Password
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        background: Rectangle {
                            radius: Theme.radius
                            color: Theme.panelAlt
                            border.color: loginPw.activeFocus ? Theme.accent : Theme.border
                            border.width: loginPw.activeFocus ? 2 : 1
                        }
                        onAccepted: if (text.length) doLogin()
                    }

                    Label {
                        id: loginError
                        visible: text.length > 0
                        text: ""
                        color: Theme.danger
                        font.pixelSize: Theme.fsSmall
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                    }

                    Button {
                        id: loginBtn
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                        text: "Ingresar"
                        enabled: loginId.text.length > 0 && loginPw.text.length > 0
                        font.pixelSize: Theme.fsBody
                        contentItem: Text {
                            text: loginBtn.text
                            font: loginBtn.font
                            color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: Theme.radius
                            color: loginBtn.enabled ? Theme.accent : Theme.border
                        }
                        onClicked: doLogin()
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 4
                        Item { Layout.fillWidth: true }
                        LinkLabel { text: "¿Olvidaste tu contraseña?"
                                    onClicked: forgotDialog.open() }
                        Item { Layout.fillWidth: true }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 18
                        Item { Layout.fillWidth: true }
                        Label { text: "¿No tenés cuenta?"; color: Theme.textSec
                                font.pixelSize: Theme.fsBody }
                        LinkLabel { text: "Creala" ; onClicked: flow.sub = "register" }
                        Item { Layout.fillWidth: true }
                    }
                }

                // =================================================== REGISTRO
                ColumnLayout {
                    spacing: 12
                    Layout.alignment: Qt.AlignVCenter

                    RowLayout {
                        Layout.fillWidth: true
                        LinkLabel { text: "← Volver"; onClicked: flow.sub = "login" }
                        Item { Layout.fillWidth: true }
                    }

                    Label { text: "Creá tu cuenta"; font.pixelSize: Theme.fsBig
                            font.bold: true; color: Theme.textPri }

                    Label { text: "Correo electrónico"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }
                    TextField {
                        id: regEmail
                        Layout.fillWidth: true
                        placeholderText: "tu@mail.com"
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: regEmail.activeFocus ? Theme.accent : Theme.border
                            border.width: regEmail.activeFocus ? 2 : 1
                        }
                    }

                    Label { text: "Usuario"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }
                    TextField {
                        id: regUser
                        Layout.fillWidth: true
                        placeholderText: "3-20 caracteres: letras, números, _ y ."
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        validator: RegularExpressionValidator {
                            regularExpression: /^[a-z0-9][a-z0-9_.]{2,19}$/
                        }
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: regUser.activeFocus ? Theme.accent : Theme.border
                            border.width: regUser.activeFocus ? 2 : 1
                        }
                    }

                    Label { text: "Contraseña"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }
                    TextField {
                        id: regPw
                        Layout.fillWidth: true
                        placeholderText: "Mínimo 8 caracteres"
                        echoMode: TextInput.Password
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: regPw.activeFocus ? Theme.accent : Theme.border
                            border.width: regPw.activeFocus ? 2 : 1
                        }
                        onTextChanged: strengthBar.value = strength(text)
                        function strength(p) {
                            if (p.length < 8) return 0
                            var s = 1
                            if (/[A-Z]/.test(p) && /[a-z]/.test(p)) s++
                            if (/[0-9]/.test(p)) s++
                            if (/[^A-Za-z0-9]/.test(p) && p.length >= 12) s++
                            return s
                        }
                    }

                    // barra de fortaleza
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Repeater {
                            model: 4
                            delegate: Rectangle {
                                Layout.fillWidth: true; height: 4; radius: 2
                                color: index < regPw.strength(regPw.text)
                                       ? (regPw.strength(regPw.text) <= 1 ? Theme.danger
                                          : regPw.strength(regPw.text) === 2 ? "#f5b942"
                                          : Theme.accent)
                                       : Theme.border
                            }
                        }
                    }

                    Label { text: "Confirmar contraseña"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }
                    TextField {
                        id: regPw2
                        Layout.fillWidth: true
                        placeholderText: "Repetí la contraseña"
                        echoMode: TextInput.Password
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: regPw2.activeFocus
                                          ? (regPw2.text && regPw2.text !== regPw.text
                                             ? Theme.danger : Theme.accent)
                                          : Theme.border
                            border.width: regPw2.activeFocus ? 2 : 1
                        }
                    }
                    Label {
                        visible: regPw2.text.length > 0 && regPw2.text !== regPw.text
                        text: "Las contraseñas no coinciden"
                        color: Theme.danger; font.pixelSize: Theme.fsSmall
                    }

                    Button {
                        id: regBtn
                        Layout.fillWidth: true
                        Layout.topMargin: 6
                        text: "Crear cuenta"
                        enabled: regEmail.text.length > 3
                                 && regUser.acceptableInput
                                 && regPw.text.length >= 8
                                 && regPw2.text === regPw.text
                        contentItem: Text {
                            text: regBtn.text; font: regBtn.font; color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: Theme.radius
                            color: regBtn.enabled ? Theme.accent : Theme.border
                        }
                        onClicked: {
                            flow.registering = true
                            bridge.register(regEmail.text, regUser.text, regPw.text)
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: "Al crear la cuenta te enviamos un código de verificación a tu correo."
                        color: Theme.textSec; font.pixelSize: Theme.fsSmall
                    }
                }

                // =================================================== PERFIL (paso 2)
                ColumnLayout {
                    spacing: 12
                    Layout.alignment: Qt.AlignVCenter

                    Label { text: "Tu perfil"; font.pixelSize: Theme.fsBig
                            font.bold: true; color: Theme.textPri }
                    Label { text: "Opcional: podés completarlo después."
                            color: Theme.textSec; font.pixelSize: Theme.fsSmall
                            Layout.bottomMargin: 6 }

                    // avatar picker
                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.bottomMargin: 8
                        spacing: 14
                        Rectangle {
                            id: avatarPreview
                            width: 84; height: 84; radius: 42
                            color: Theme.panelAlt
                            border.color: Theme.border; border.width: 1
                            property url src: ""
                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 2
                                radius: 40
                                clip: true
                                color: "transparent"
                                Image {
                                    anchors.fill: parent
                                    source: avatarPreview.src
                                    fillMode: Image.PreserveAspectCrop
                                    visible: status === Image.Ready
                                    sourceSize: Qt.size(168, 168)
                                }
                            }
                            Label {
                                anchors.centerIn: parent
                                text: avatarPreview.src ? "" : "📷"
                                font.pixelSize: 26
                                visible: !avatarPreview.src
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: fileDialog.open()
                            }
                        }
                        ColumnLayout {
                            spacing: 6
                            LinkLabel { text: "Elegir foto"
                                        onClicked: fileDialog.open() }
                            LinkLabel { text: "Quitar"
                                        visible: avatarPreview.src !== ""
                                        onClicked: avatarPreview.src = "" }
                            Label { text: "Clic para cambiar"; color: Theme.textSec
                                    font.pixelSize: Theme.fsSmall }
                        }
                    }

                    Label { text: "Nombre para mostrar"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }
                    TextField {
                        id: profName
                        Layout.fillWidth: true
                        placeholderText: "Si lo dejás vacío, se usa tu usuario"
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: profName.activeFocus ? Theme.accent : Theme.border
                            border.width: profName.activeFocus ? 2 : 1
                        }
                    }

                    Label { text: "Descripción (opcional)"; color: Theme.textSec
                            font.pixelSize: Theme.fsSmall }
                    TextArea {
                        id: profBio
                        Layout.fillWidth: true
                        Layout.preferredHeight: 80
                        placeholderText: "Contá algo sobre vos…"
                        wrapMode: TextEdit.Wrap
                        color: Theme.textPri
                        font.pixelSize: Theme.fsBody
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.panelAlt
                            border.color: profBio.activeFocus ? Theme.accent : Theme.border
                            border.width: profBio.activeFocus ? 2 : 1
                        }
                    }
                    Label {
                        visible: profBio.text.length > 150
                        text: "Máximo 150 caracteres"
                        color: Theme.danger; font.pixelSize: Theme.fsSmall
                    }

                    Button {
                        id: profBtn
                        Layout.fillWidth: true
                        Layout.topMargin: 8
                        text: "Continuar"
                        enabled: profBio.text.length <= 150
                        contentItem: Text {
                            text: profBtn.text; font: profBtn.font; color: "white"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            radius: Theme.radius; color: Theme.accent
                        }
                        onClicked: {
                            bridge.setup_profile(profName.text, profBio.text,
                                                 avatarPreview.src.toString())
                        }
                    }
                    LinkLabel {
                        Layout.alignment: Qt.AlignHCenter
                        text: "Omitir por ahora"
                        onClicked: bridge.show_verify()
                    }
                }
            }
        }
    }

    // -------------------------------------------------- diálogo "olvidé mi contraseña"
    Popup {
        id: forgotDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(420, parent.width - 40)
        padding: 24
        background: Rectangle {
            radius: Theme.radiusBig; color: Theme.panel
            border.color: Theme.border
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 12

            Label { text: "Recuperar contraseña"; font.pixelSize: Theme.fsTitle
                    font.bold: true; color: Theme.textPri }
            Label { text: "Ingresá tu usuario o correo y te mandamos un código."
                    color: Theme.textSec; font.pixelSize: Theme.fsSmall
                    wrapMode: Text.WordWrap; Layout.fillWidth: true }

            TextField {
                id: forgotId
                Layout.fillWidth: true
                placeholderText: "Usuario o correo"
                color: Theme.textPri
                background: Rectangle {
                    radius: Theme.radius; color: Theme.panelAlt
                    border.color: Theme.border
                }
            }
            TextField {
                id: forgotPw
                Layout.fillWidth: true
                placeholderText: "Nueva contraseña (mín. 8)"
                echoMode: TextInput.Password
                color: Theme.textPri
                background: Rectangle {
                    radius: Theme.radius; color: Theme.panelAlt
                    border.color: Theme.border
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                LinkLabel { text: "Cancelar"; onClicked: forgotDialog.close() }
                Button {
                    text: "Enviar código"
                    enabled: forgotId.text.length > 0 && forgotPw.text.length >= 8
                    contentItem: Text {
                        text: parent.text; font: parent.font; color: "white"
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        radius: Theme.radius; color: Theme.accent
                    }
                    onClicked: {
                        bridge.forgot(forgotId.text, forgotPw.text)
                        forgotDialog.close()
                    }
                }
            }
        }
    }

    // selector de archivos (avatar)
    FileDialog {
        id: fileDialog
        title: "Elegí tu foto de perfil"
        nameFilters: ["Imágenes (*.png *.jpg *.jpeg *.webp *.gif)"]
        onAccepted: {
            avatarPreview.src = selectedFile
            if (flow.sub === "profile") {
                // si ya está en la app, aplicar directo
                bridge.set_avatar(selectedFile.toString().replace("file://", ""))
            }
        }
    }

    // Helper: link clicable
    component LinkLabel: Label {
        signal clicked()
        font.pixelSize: Theme.fsBody
        font.underline: true
        color: Theme.accent
        textFormat: Text.PlainText
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.clicked()
        }
    }
}
