import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// HiveMind bar widget. Talks to hivemind-daemon over its Unix socket with the
// same newline-delimited JSON protocol the GTK window uses: `hello` for a
// snapshot, then live events. Approvals are answered with `approve`.
Panel {
  id: root
  moduleName: "gogema.hivemind"
  ipcTarget: "gogema.hivemind"

  readonly property string socketPath: Quickshell.env("XDG_RUNTIME_DIR") + "/hivemind.sock"
  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace("file://", "")
  readonly property string venvDaemon: Quickshell.env("HOME") + "/.local/share/hivemind/venv/bin/hivemind-daemon"

  property bool connected: false
  property bool installed: true
  property bool installing: false
  property bool installFailed: false
  property string installLog: ""
  property var agents: []
  property var statuses: ({})
  property var approvals: []
  property int nextId: 1

  readonly property int working: Object.keys(root.statuses).filter(k => root.statuses[k] === "working").length
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color glyphColor: root.beeStatus === "waiting" ? root.yellow
    : (root.beeStatus === "thinking" || root.beeStatus === "tool") ? Color.accent : root.dim

  // Same sequences as hivemind/ui/bee_frames.py. The bar shows the most important state:
  // waiting > working (tool beats thinking) > idle; it sleeps only when every agent sleeps.
  readonly property int sleepAfter: 300
  property int tick: 0
  property real now: Date.now() / 1000
  property var activities: ({})
  property var lastActive: ({})
  readonly property bool allAsleep: root.agents.length > 0 && root.agents.every(
    a => (root.statuses[a.id] || "idle") === "idle" && root.now - (root.lastActive[a.id] || 0) >= root.sleepAfter)
  readonly property string beeStatus: !root.connected ? "offline"
    : root.approvals.length > 0 ? "waiting"
    : root.working > 0 ? (Object.values(root.activities).indexOf("tool") !== -1 ? "tool" : "thinking")
    : root.allAsleep ? "sleeping" : "idle"
  readonly property var frame: {
    const rep = (f, n, o) => Array(n).fill([f, o === undefined ? 1.0 : o])
    const bob = rep("up", 6).concat(rep("low", 6))
    const seqs = {
      "idle": bob.concat(bob, [["down", 1.0], ["up", 1.0], ["down", 1.0], ["up", 1.0]]),
      "thinking": rep("think-up", 3).concat(rep("think-down", 3)),
      "tool": [["up", 1.0], ["down", 1.0]],
      "waiting": rep("wait", 4).concat(rep("wait", 4, 0.35)),
      "sleeping": rep("sleep-1", 8).concat(rep("sleep-2", 8))
    }
    const seq = seqs[root.beeStatus] || [["up", 1.0]]
    return seq[root.tick % seq.length]
  }
  readonly property string iconsDir: root.pluginDir + "/hivemind/ui/icons/"

  // Yellow is not one of the shell's colour roles, so read it from the theme ourselves and
  // re-read whenever the accent changes (that is what a theme switch does).
  property color yellow: Color.urgent
  FileView {
    id: themeColors
    path: Color.currentThemePath + "/colors.toml"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      const m = text().match(/^\s*yellow\s*=\s*["']?(#[0-9A-Fa-f]{6})/m)
      root.yellow = m ? m[1] : Color.urgent
    }
  }
  Connections {
    target: Color
    function onAccentChanged() { themeColors.reload() }
  }

  Timer {
    interval: 125
    running: root.connected
    repeat: true
    onTriggered: {
      root.tick = (root.tick + 1) % 1000
      if (root.tick % 8 === 0) root.now = Date.now() / 1000  // once a second, for falling asleep
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function send(method, params) {
    if (!root.connected) return
    sock.write(JSON.stringify({ id: root.nextId++, method: method, params: params || {} }) + "\n")
    sock.flush()
  }

  function nameOf(id) {
    const a = root.agents.find(x => x.id === id)
    return a ? a.name : "?"
  }

  function handle(line) {
    let msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (msg.result && msg.result.agents !== undefined && msg.result.statuses !== undefined) {
      root.agents = msg.result.agents
      root.statuses = msg.result.statuses
      root.approvals = msg.result.approvals || []
      root.activities = msg.result.activities || ({})
      root.lastActive = msg.result.last_active || ({})
      return
    }
    const ev = msg.event
    if (!ev) return
    if (ev.type === "agents") root.agents = ev.agents
    else if (ev.type === "status") {
      const s = Object.assign({}, root.statuses); s[ev.agent] = ev.status; root.statuses = s
    }
    else if (ev.type === "activity") {
      const a = Object.assign({}, root.activities)
      if (ev.activity) a[ev.agent] = ev.activity; else delete a[ev.agent]
      root.activities = a
      if (ev.last_active) { const l = Object.assign({}, root.lastActive); l[ev.agent] = ev.last_active; root.lastActive = l }
    }
    else if (ev.type === "approval") root.approvals = root.approvals.concat([ev.approval])
    else if (ev.type === "approval_resolved") root.approvals = root.approvals.filter(a => a.id !== ev.id)
  }

  function install() {
    if (root.installing) return
    root.installing = true
    root.installFailed = false
    root.installLog = ""
    installProcess.command = ["bash", root.pluginDir + "/install.sh"]
    installProcess.running = true
  }

  Socket {
    id: sock
    path: root.socketPath
    connected: true
    parser: SplitParser { onRead: data => root.handle(data) }
    onConnectionStateChanged: {
      root.connected = sock.connected
      if (sock.connected) root.send("hello", { role: "panel" })
      else { root.approvals = []; root.statuses = ({}) }
    }
  }

  // Reconnect every 3 s while the daemon is down or restarting.
  Timer {
    interval: 3000
    running: !root.connected
    repeat: true
    onTriggered: {
      if (!root.installing) probe.running = true
      sock.connected = false
      sock.connected = true
    }
  }

  Process {
    id: probe
    command: ["test", "-x", root.venvDaemon]
    onExited: function(exitCode) { root.installed = exitCode === 0 }
  }

  Process {
    id: installProcess
    running: false
    command: []
    stdout: SplitParser { onRead: data => root.installLog = (root.installLog + data + "\n").slice(-2000) }
    stderr: SplitParser { onRead: data => root.installLog = (root.installLog + data + "\n").slice(-2000) }
    onExited: function(exitCode) {
      root.installing = false
      root.installFailed = exitCode !== 0
      probe.running = true
    }
  }

  Process { id: openProcess; command: ["hivemind"] }

  Component.onCompleted: probe.running = true

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Item {
        implicitWidth: Style.space(22)
        implicitHeight: Style.space(22)
        // Same SVGs as the window; tinted with the shell colours like the tray tints symbolic icons.
        Image {
          id: beeImage
          anchors.fill: parent
          fillMode: Image.PreserveAspectFit
          sourceSize.width: Math.round(width * Screen.devicePixelRatio)
          sourceSize.height: Math.round(height * Screen.devicePixelRatio)
          source: "file://" + root.iconsDir + "hivemind-bee-" + root.frame[0] + "-symbolic.svg"
          visible: false
          layer.enabled: true
        }
        MultiEffect {
          anchors.fill: beeImage
          source: beeImage
          colorization: 1.0
          colorizationColor: root.glyphColor
          opacity: root.frame[1]
        }
        // Daemon unreachable: strike the bee through.
        Rectangle {
          visible: !root.connected
          anchors.centerIn: parent
          width: parent.width * 1.2
          height: Math.max(1, Math.round(Style.space(1.5)))
          rotation: -35
          color: root.dim
        }
        Text {
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          visible: root.connected && (root.approvals.length > 0 || root.working > 0)
          text: root.approvals.length > 0 ? "!" : String(root.working)
          color: root.glyphColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) openProcess.startDetached()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(560))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: flick.width
          spacing: Style.spacing.md

          // --- not installed -------------------------------------------------
          Column {
            width: parent.width
            spacing: Style.spacing.md
            visible: root.installing || root.installFailed || (!root.connected && !root.installed)

            Text {
              width: parent.width
              wrapMode: Text.Wrap
              text: "HiveMind aún no está instalada. Se instala en tu usuario: una app, un servicio y sin permisos de root."
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
            Button {
              text: root.installing ? "Instalando…" : root.installFailed ? "Reintentar instalación" : "Instalar HiveMind"
              foreground: root.foreground
              fontFamily: root.fontFamily
              bordered: true
              onClicked: root.install()
            }
            Text {
              width: parent.width
              visible: root.installLog.length > 0
              wrapMode: Text.WrapAnywhere
              text: root.installLog
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          // --- installed but daemon down ------------------------------------
          Text {
            width: parent.width
            visible: !root.connected && root.installed
            wrapMode: Text.Wrap
            text: "El daemon de HiveMind no responde. Reintentando…"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          // --- approvals -----------------------------------------------------
          PanelSectionHeader {
            visible: root.connected && root.approvals.length > 0
            text: "APROBACIONES"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Repeater {
            model: root.connected ? root.approvals : []
            delegate: Column {
              required property var modelData
              width: column.width
              spacing: Style.spacing.xs
              Text {
                width: parent.width
                elide: Text.ElideRight
                text: root.nameOf(modelData.agent_id) + " quiere usar " + modelData.tool
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
              }
              Text {
                width: parent.width
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 3
                elide: Text.ElideRight
                text: modelData.input.command || modelData.input.file_path || JSON.stringify(modelData.input)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
              Row {
                spacing: Style.spacing.sm
                Button { text: "Permitir"; foreground: root.foreground; fontFamily: root.fontFamily; bordered: true
                         onClicked: root.send("approve", { approval: modelData.id, decision: "allow" }) }
                Button { text: "Denegar"; foreground: root.foreground; fontFamily: root.fontFamily; bordered: true
                         onClicked: root.send("approve", { approval: modelData.id, decision: "deny" }) }
                Button { text: "Siempre"; foreground: root.foreground; fontFamily: root.fontFamily
                         tooltipText: "Guardará: " + (modelData.rule || modelData.tool)
                         onClicked: root.send("approve", { approval: modelData.id, decision: "always" }) }
              }
            }
          }

          // --- agents --------------------------------------------------------
          PanelSectionHeader {
            visible: root.connected
            text: "AGENTES"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }
          Repeater {
            model: root.connected ? root.agents : []
            delegate: Row {
              required property var modelData
              spacing: Style.spacing.sm
              Text {
                text: "●"
                color: ({ working: Color.accent, waiting: root.yellow, error: Color.urgent })[root.statuses[modelData.id]] || root.dim
                font.pixelSize: Style.font.caption
              }
              Text {
                text: modelData.name + "  ·  " + ({ idle: "inactivo", queued: "en cola", working: "trabajando",
                      waiting: "esperando aprobación", error: "error" })[root.statuses[modelData.id] || "idle"]
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }
            }
          }

          Button {
            visible: root.connected || root.installed
            text: "Abrir HiveMind"
            foreground: root.foreground
            fontFamily: root.fontFamily
            bordered: true
            onClicked: { openProcess.startDetached(); root.close() }
          }
        }
      }
    }
  }
}
