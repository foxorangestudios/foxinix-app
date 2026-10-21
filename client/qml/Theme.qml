pragma Singleton
import QtQuick

QtObject {
    // ---------- paleta base
    property bool dark: true

    readonly property color bg: dark ? "#0b141a" : "#eae6df"
    readonly property color panel: dark ? "#111b21" : "#ffffff"
    readonly property color panelAlt: dark ? "#202c33" : "#f0f2f5"
    readonly property color sidebar: dark ? "#111b21" : "#f7f5f3"
    readonly property color header: dark ? "#202c33" : "#f0f2f5"
    readonly property color border: dark ? "#2a3942" : "#e4e0da"

    readonly property color textPri: dark ? "#e9edef" : "#111b21"
    readonly property color textSec: dark ? "#8696a0" : "#667781"
    readonly property color textOnAccent: "#ffffff"

    // ---------- acento (personalizable)
    property color accent: "#00a884"          // verde WhatsApp
    readonly property color accentDark: Qt.darker(accent, 1.25)
    readonly property color bubbleMine: dark ? "#005c4b" : accent
    readonly property color bubbleTheirs: dark ? "#202c33" : "#ffffff"
    readonly property color badge: "#25d366"
    readonly property color danger: "#f15c6d"
    readonly property color unreadBadge: accent

    // ---------- tipografía
    readonly property int fsSmall: 12
    readonly property int fsBody: 15
    readonly property int fsTitle: 17
    readonly property int fsBig: 22

    // ---------- métricas
    readonly property int radius: 10
    readonly property int radiusBig: 16
    readonly property int pad: 12
    readonly property int sidebarW: 340

    // ---------- wallpapers de conversación (sutil)
    property string wallpaper: ""

    function timeStr(ts) {
        if (!ts) return ""
        return Qt.formatTime(new Date(ts * 1000), "hh:mm")
    }
    function dayStr(ts) {
        var d = new Date(ts * 1000), now = new Date()
        var yest = new Date(now.getTime() - 86400000)
        if (d.toDateString() === now.toDateString()) return "HOY"
        if (d.toDateString() === yest.toDateString()) return "AYER"
        return Qt.formatDate(d, "d 'de' MMMM")
    }
    function sameDay(a, b) {
        if (!a || !b) return false
        return new Date(a * 1000).toDateString() === new Date(b * 1000).toDateString()
    }
    function humanSize(bytes) {
        if (bytes < 1024) return bytes + " B"
        if (bytes < 1048576) return (bytes / 1024).toFixed(0) + " KB"
        return (bytes / 1048576).toFixed(1) + " MB"
    }
}
