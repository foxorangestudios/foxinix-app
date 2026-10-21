import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."   // singleton Theme (qmldir del directorio raíz)

// Pantalla de verificación de correo: código de 6 dígitos + reenviar (cooldown 60s)
Item {
    id: verifyPage
    property string emailMasked: ""
    property int resendIn: 0

    Rectangle { anchors.fill: parent; color: Theme.bg }

    Connections {
        target: bridge
        function onVerificationRequired(masked, resendAfter) {
            if (masked) verifyPage.emailMasked = masked
            verifyPage.startCooldown(resendAfter)
        }
    }

    function startCooldown(s) {
        resendIn = Math.max(0, s | 0)
        cooldownTimer.stop()
        if (resendIn > 0) cooldownTimer.start()
    }

    Timer {
        id: cooldownTimer
        interval: 1000
        repeat: true
        onTriggered: {
            if (verifyPage.resendIn > 0) verifyPage.resendIn--
            else stop()
        }
    }

    readonly property var fields: [c0, c1, c2, c3, c4, c5]

    function code() { return c0.text + c1.text + c2.text + c3.text + c4.text + c5.text }
    function tryVerify() { if (code().length === 6) bridge.verify(code()) }
    function clearAll() {
        for (var i = 0; i < fields.length; i++) fields[i].text = ""
        c0.forceActiveFocus()
    }

    Component.onCompleted: c0.forceActiveFocus()

    // avanzar al siguiente / retroceder con backspace
    function advance(i, dir) {
        var n = i + dir
        if (n >= 0 && n < fields.length) fields[n].forceActiveFocus()
    }

    // tras editar el campo i: mover foco y auto-validar
    function afterEdit(i) {
        var f = fields[i]
        if (f.text.length === 1 && i < 5) advance(i, +1)
        if (f.text.length === 0 && i > 0) advance(i, -1)
        if (code().length === 6) tryVerify()
    }

    component CodeField: TextField {
        width: 48; height: 56
        horizontalAlignment: TextInput.AlignHCenter
        verticalAlignment: TextInput.AlignVCenter
        font.pixelSize: 24
        font.bold: true
        color: Theme.textPri
        inputMethodHints: Qt.ImhDigitsOnly
        validator: RegularExpressionValidator { regularExpression: /[0-9]/ }
        onTextEdited: if (text.length > 1) text = text.slice(-1)
        background: Rectangle {
            radius: Theme.radius
            color: Theme.panelAlt
            border.color: parent.activeFocus ? Theme.accent
                         : (parent.text ? Theme.accent : Theme.border)
            border.width: 2
        }
        Keys.onReturnPressed: verifyPage.tryVerify()
        Keys.onEnterPressed: verifyPage.tryVerify()
        Keys.onBackPressed: {
            if (text.length === 0) {
                var idx = verifyPage.fields.indexOf(parent)
                if (idx > 0) {
                    verifyPage.fields[idx].forceActiveFocus()
                    verifyPage.fields[idx].text = ""
                }
            } else {
                text = ""
            }
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 18
        width: Math.min(460, parent.width - 48)

        Label { text: "🦊"; font.pixelSize: 56; Layout.alignment: Qt.AlignHCenter }

        Label {
            text: "Verificá tu correo"
            font.pixelSize: Theme.fsBig; font.bold: true
            color: Theme.textPri
            Layout.alignment: Qt.AlignHCenter
        }
        Label {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Enviamos un código de 6 dígitos a\n<b>"
                  + (verifyPage.emailMasked || "tu correo") + "</b>"
            color: Theme.textSec
            font.pixelSize: Theme.fsBody
        }

        // -------- 6 casilleros
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 8

            CodeField { id: c0; onTextEdited: verifyPage.afterEdit(0) }
            CodeField { id: c1; onTextEdited: verifyPage.afterEdit(1) }
            CodeField { id: c2; onTextEdited: verifyPage.afterEdit(2) }
            CodeField { id: c3; onTextEdited: verifyPage.afterEdit(3) }
            CodeField { id: c4; onTextEdited: verifyPage.afterEdit(4) }
            CodeField { id: c5; onTextEdited: verifyPage.afterEdit(5) }
        }

        Label {
            text: "El código vence en 10 minutos"
            color: Theme.textSec; font.pixelSize: Theme.fsSmall
            Layout.alignment: Qt.AlignHCenter
        }

        // -------- reenviar con cooldown
        Label {
            Layout.alignment: Qt.AlignHCenter
            font.pixelSize: Theme.fsBody
            font.underline: true
            color: verifyPage.resendIn > 0 ? Theme.textSec : Theme.accent
            text: verifyPage.resendIn > 0
                  ? "Reenviar en " + verifyPage.resendIn + "s"
                  : "Reenviar código"
            MouseArea {
                anchors.fill: parent
                enabled: verifyPage.resendIn === 0
                cursorShape: parent.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: {
                    verifyPage.clearAll()
                    bridge.resend_code()
                    verifyPage.startCooldown(60)
                }
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 8
            Item { Layout.fillWidth: true }
            Label {
                text: "Cambiar de cuenta"
                font.pixelSize: Theme.fsBody
                font.underline: true
                color: Theme.accent
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: bridge.logout()
                }
            }
            Item { Layout.fillWidth: true }
        }

        Label {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Tu cuenta se elimina a los 5 días si no verificás."
            color: Theme.textSec
            font.pixelSize: Theme.fsSmall
            opacity: 0.8
        }
    }
}
