import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Effects
import QtQuick.Dialogs
import "auth"
import "app"

ApplicationWindow {
    id: root
    width: 1180
    height: 760
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    title: "FoxMsg"
    color: Theme.bg

    // ícono de ventana (zorro simple generado)
    Component.onCompleted: {
        var c = Qt.createQmlObject('import QtQuick; Canvas {visible:false; width:64; height:64; onPaint:{'
            + 'var g=getContext("2d"); g.fillStyle="#00a884"; g.fillRect(0,0,64,64);'
            + 'g.fillStyle="#ffffff"; g.font="bold 40px sans-serif"; g.textAlign="center";'
            + 'g.fillText("🦊",32,46);}}', root)
        c.requestPaint()
        root.flags = Qt.Window
    }

    // estado: "auth" | "verify" | "app"
    property string view: "auth"
    property bool pendingVerification: false
    property string pendingEmail: ""


    Connections {
        target: bridge
        function onNavigate(v) { root.view = v }
        function onVerificationRequired(masked, resendAfter) {
            root.pendingVerification = true
            root.pendingEmail = masked
        }
        function onToast(msg, type) { toast.show(msg, type) }
    }

    StackLayout {
        anchors.fill: parent
        currentIndex: view === "auth" ? 0 : (view === "verify" ? 1 : 2)

        // 1) Auth: login/registro/perfil
        AuthFlow {
            id: authFlow
        }

        // 2) Verificación de correo
        VerifyPage {
            emailMasked: root.pendingEmail
        }

        // 3) App principal
        ChatWindow {
            id: chatWin
        }
    }

    // -------------------------------------------------- toast flotante
    Rectangle {
        id: toast
        property string kind: "info"
        function show(msg, type) {
            kind = type || "info"
            label.text = msg
            appear.start()
        }
        z: 1000
        anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height - 90
        width: Math.min(implicitWidth + 40, parent.width - 40)
        height: visible ? 46 : 0
        radius: 23
        color: kind === "error" ? Theme.danger
             : kind === "ok" ? Theme.accent : Theme.panelAlt
        visible: opacity > 0.01
        opacity: 0

        Behavior on opacity { NumberAnimation { duration: 180 } }

        Label {
            id: label
            anchors.centerIn: parent
            color: "white"
            font.pixelSize: Theme.fsBody
        }

        Timer {
            id: hideTimer
            interval: 3200
            onTriggered: fadeOut.start()
        }
        SequentialAnimation {
            id: appear
            NumberAnimation { target: toast; property: "opacity"; to: 1; duration: 180 }
            ScriptAction { script: hideTimer.restart() }
        }
        NumberAnimation {
            id: fadeOut
            target: toast; property: "opacity"; to: 0; duration: 250
        }
    }

    // -------------------------------------------------- indicador global de carga
    Rectangle {
        visible: busyIndicator.visible
        anchors.fill: parent
        color: "#60000000"
        z: 999
        MouseArea { anchors.fill: parent }   // bloquear input mientras carga

        Rectangle {
            id: busyIndicator
            visible: false
            anchors.centerIn: parent
            width: 64; height: 64; radius: 32
            color: Theme.panel
            property alias visible_: busyIndicator.visible

            Rectangle {
                id: spinner
                anchors.centerIn: parent
                width: 34; height: 34; radius: 17
                color: "transparent"
                border.width: 4
                border.color: Theme.accent
                opacity: 0.9
                Component.onCompleted: rot.start()
                RotationAnimation on rotation {
                    id: rot
                    from: 0; to: 360; loops: Animation.Infinite; duration: 850
                }
                // arco: recorte con rectángulo
                Rectangle {
                    anchors.right: parent.right
                    width: parent.width / 2 + 2
                    height: parent.height + 8
                    color: Theme.panel
                    visible: busyIndicator.visible
                }
            }
        }
        // visibilidad enganchada a bridge.busyChanged
        Connections {
            target: bridge
            function onBusyChanged(b) { busyIndicator.visible = b }
        }
    }
}
