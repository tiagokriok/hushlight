import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// One theme-colored circle, macOS-style. Shape distinguishes capture type
// because theme colors can look alike. Hidden when nothing is observed.
// Direct device access is access, never confirmed recording.
//
// One backend process runs per widget instance (one per monitor).
BarWidget {
  id: root
  moduleName: "hushlight.privacy"

  property var snapshot: null

  readonly property string backendPath: decodeURIComponent(
    String(Qt.resolvedUrl("backend/main.py")).replace(/^file:\/\//, ""))

  function stateOf(key) {
    var status = root.snapshot ? root.snapshot[key] : null
    return status && typeof status.state === "string" ? status.state : "unknown"
  }

  readonly property string microphoneState: stateOf("microphone")
  readonly property string cameraState: stateOf("camera")
  readonly property bool microphoneActive: microphoneState === "active"
  readonly property bool cameraActive: cameraState === "active"
  readonly property bool anyActive: microphoneActive || cameraActive

  // ring: microphone only. solid: microphone and camera.
  // Omarchy already shows recording on the top bar, so this plugin only marks
  // microphone and camera access.
  readonly property string mark: {
    if (microphoneActive && cameraActive) return "solid"
    if (microphoneActive) return "ring"
    if (cameraActive) return "camera"
    return "none"
  }

  function validSnapshot(value) {
    if (!value || value.version !== 1) return false
    var validStates = ["active", "unobserved", "unknown"]
    var keys = ["microphone", "camera", "recording"]
    for (var i = 0; i < keys.length; i++) {
      var status = value[keys[i]]
      if (!status || typeof status.state !== "string") return false
      if (validStates.indexOf(status.state) === -1) return false
      if (typeof status.evidence !== "string") return false
      if (!(status.limitations instanceof Array)) return false
    }
    return true
  }

  function handleLine(raw) {
    var text = String(raw)
    if (text.length === 0) return
    var parsed = null
    try {
      parsed = JSON.parse(text)
    } catch (error) {
      resetToUnknown()
      return
    }
    if (!validSnapshot(parsed)) {
      resetToUnknown()
      return
    }
    root.snapshot = parsed
  }

  function resetToUnknown() {
    root.snapshot = null
  }

  function evidenceOf(key) {
    var status = root.snapshot ? root.snapshot[key] : null
    return status && typeof status.evidence === "string" ? status.evidence : ""
  }

  readonly property string tooltipText: {
    var parts = []
    if (microphoneActive) parts.push(evidenceOf("microphone") || "Microphone")
    if (cameraActive) parts.push(evidenceOf("camera") || "Camera")
    return parts.join(" · ")
  }

  property bool tooltipHovered: hoverArea.containsMouse

  readonly property real dot: 12
  implicitWidth: anyActive ? dot + 10 : 0
  implicitHeight: barSize

  function restartBackend() {
    if (!backend.running) backend.running = true
  }

  Process {
    id: backend
    command: ["python3", root.backendPath]
    running: true

    stdout: SplitParser {
      onRead: function(line) { root.handleLine(line) }
    }

    onExited: function(exitCode) {
      root.resetToUnknown()
      restartTimer.start()
    }
  }

  Timer {
    id: restartTimer
    interval: 2000
    repeat: false
    onTriggered: root.restartBackend()
  }

  Item {
    id: markItem
    anchors.centerIn: parent
    width: root.dot
    height: root.dot
    visible: root.anyActive

    Rectangle {
      anchors.fill: parent
      radius: width / 2
      color: root.mark === "solid" || root.mark === "camera" ? Color.bar.active : "transparent"
      border.width: root.mark === "ring" ? 1.5 : 0
      border.color: Color.bar.active
    }

    Rectangle {
      visible: root.mark === "camera"
      anchors.centerIn: parent
      width: 3
      height: 3
      radius: 1.5
      color: Color.bar.background
    }
  }

  MouseArea {
    id: hoverArea
    anchors.fill: parent
    hoverEnabled: true
    acceptedButtons: Qt.NoButton
    cursorShape: Qt.ArrowCursor
    onEntered: if (root.bar && root.tooltipText) root.bar.showTooltip(root, root.tooltipText)
    onExited: if (root.bar) root.bar.hideTooltip(root)
    onVisibleChanged: if (!visible && root.bar) root.bar.hideTooltip(root)
  }

  Accessible.name: "Privacy capture indicator"
  Accessible.description: root.anyActive ? root.tooltipText : "No capture observed on supported paths"
  Accessible.role: Accessible.StaticText
}
