import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Vomee 1.0

ApplicationWindow {
    id: win
    visible: true
    width: 1360
    height: 860
    title: "mSense OS"
    color: "#f5f5f7"

    // ── palette (macOS light) ────────────────────────────────────
    readonly property color cardBg:   "#ffffff"
    readonly property color cardLine:  "#e5e5ea"
    readonly property color textMain:  "#1d1d1f"
    readonly property color textSub:   "#6e6e73"
    readonly property color accent:    "#0a84ff"
    readonly property color good:      "#34c759"
    readonly property color danger:    "#ff3b30"
    readonly property int   radius:    14

    component Card: Rectangle {
        color: win.cardBg
        radius: win.radius
        border.color: win.cardLine
        border.width: 1
    }

    // A display panel: the dark viewport FILLS the whole card; the title
    // is overlaid in the corner. Extra children (e.g. a HUD) draw on top.
    component DisplayCard: Rectangle {
        property string title: ""
        property alias view: fv
        radius: win.radius
        color: "#0b0b0c"
        border.color: win.cardLine
        border.width: 1
        clip: true
        FrameView { id: fv; anchors.fill: parent; anchors.margins: 1 }
        Text {
            text: parent.title
            anchors.left: parent.left; anchors.top: parent.top
            anchors.leftMargin: 14; anchors.topMargin: 12
            color: "#e8e8ed"
            font.pixelSize: 11; font.weight: Font.DemiBold; font.letterSpacing: 1.2
        }
    }

    // ── live frame channels ───────────────────────────────────────
    Connections {
        target: backend
        function onCameraFrameReady(img) { cameraCard.view.setImage(img) }
        function onRdFrameReady(img)     { rdCard.view.setImage(img) }
        function onRaFrameReady(img)     { raCard.view.setImage(img) }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 16

        // ── top bar: brand + status + merged controls ────────────
        Card {
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 16
                spacing: 14

                Rectangle { width: 10; height: 10; radius: 5; color: backend.recording ? win.danger : win.good }
                Text { text: "mSense OS"; color: win.textMain; font.pixelSize: 18; font.weight: Font.Bold }
                Text {
                    text: backend.statusText
                    color: backend.recording ? win.danger : win.textSub
                    font.pixelSize: 13; font.weight: Font.DemiBold
                }
                Text {
                    text: backend.elapsedText
                    visible: backend.recording
                    color: win.textMain; font.family: "Menlo"; font.pixelSize: 13
                }

                Item { Layout.fillWidth: true }   // spacer

                // ── merged controls ──
                Text { text: "Skeleton"; color: win.textSub; font.pixelSize: 13 }
                Switch {
                    checked: backend.skeletonEnabled
                    onToggled: backend.setSkeleton(checked)
                }
                ComboBox {
                    Layout.preferredWidth: 130
                    model: POSE_BACKEND_LABELS
                    currentIndex: POSE_BACKENDS.indexOf(DEFAULT_BACKEND)
                    onActivated: backend.setPoseBackend(POSE_BACKENDS[currentIndex])
                }
                ComboBox {
                    Layout.preferredWidth: 150
                    model: KEYPOINT_GROUP_LABELS
                    currentIndex: KEYPOINT_GROUPS.indexOf(DEFAULT_GROUP)
                    onActivated: backend.setKeypointGroup(KEYPOINT_GROUPS[currentIndex])
                }
                ComboBox {
                    Layout.preferredWidth: 120
                    model: ["Preview", "Recording"]
                    enabled: !backend.recording
                    onActivated: backend.setMode(currentText)
                }
                Button {
                    Layout.preferredWidth: 130
                    text: "Start Recording"
                    enabled: !backend.recording
                    onClicked: backend.start()
                    background: Rectangle { radius: 9; color: parent.enabled ? win.accent : "#d7d7db" }
                    contentItem: Text {
                        text: parent.text; color: "white"
                        font.pixelSize: 13; font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                }
                Button {
                    Layout.preferredWidth: 84
                    text: "Stop"
                    enabled: backend.recording
                    onClicked: backend.stop()
                    background: Rectangle { radius: 9; color: parent.enabled ? win.danger : "#f0f0f3" }
                    contentItem: Text {
                        text: parent.text; color: parent.enabled ? "white" : win.textSub
                        font.pixelSize: 13; font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        // ── main: camera (left) | RD over RA (right) ─────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            // camera fills the left; video aspect-fits on its dark canvas
            DisplayCard {
                id: cameraCard
                objectName: "cameraCard"
                title: backend.skeletonEnabled ? "CAMERA · SKELETON" : "CAMERA"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumWidth: 360

                // live telemetry HUD, bottom-left over the dark canvas
                Rectangle {
                    anchors.left: parent.left; anchors.bottom: parent.bottom
                    anchors.margins: 14
                    radius: 9
                    color: "#b3000000"
                    width: hud.implicitWidth + 24
                    height: hud.implicitHeight + 14
                    Row {
                        id: hud
                        anchors.centerIn: parent
                        spacing: 16
                        Text { text: backend.poseText;  color: "#e8e8ed"; font.pixelSize: 12 }
                        Text { text: backend.fpsText;   color: "#e8e8ed"; font.pixelSize: 12 }
                        Text { text: backend.syncText;  color: "#e8e8ed"; font.pixelSize: 12 }
                        Text { text: backend.frameText; color: "#e8e8ed"; font.pixelSize: 12 }
                    }
                }
            }

            // heatmaps stacked on the right; width tracks height so each is square
            ColumnLayout {
                objectName: "heatCol"
                Layout.fillWidth: false
                Layout.fillHeight: true
                Layout.preferredWidth: (height - 16) / 2   // square = half the column height
                Layout.minimumWidth: 220
                Layout.maximumWidth: 560
                spacing: 16

                DisplayCard {
                    id: rdCard
                    title: "RANGE-DOPPLER"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
                DisplayCard {
                    id: raCard
                    title: "RANGE-AZIMUTH"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                }
            }
        }
    }
}
