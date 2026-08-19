import QtQuick
import QtQuick.Window
import OneDragonHelper 1.0

// OneDragon-Helper 主场景：frameless 1280x720 启动器。
// 背景三层（视频 / 图片 / 渐变）由 Bridge.backgroundMode 切换；
// UI 层（左侧栏 / 启动胶囊 / 悬浮条 / toast）叠加其上，场景图同管线合成，
// 视频作为场景图节点不会像 QVideoWidget 那样盖住 UI。
Window {
    id: root
    width: 1280
    height: 720
    flags: Qt.FramelessWindowHint | Qt.Window
    color: "#0A0E1A"
    visible: true
    title: "OneDragon-Helper · 游戏自动化调度器"

    // ═══════════════ 背景层（最底）═══════════════
    // 视频背景：Loader 按文件路径懒加载 VideoBackground.qml。
    // main.qml 本体不引用 QtMultimedia 类型——MediaPlayer 类型注册在部分
    // 环境/进程下不稳定（Type unavailable），隔离到子组件后 main.qml 解析
    // 完全稳定；视频层失败只影响背景视频，UI 不受影响。
    Loader {
        id: videoBgLoader
        anchors.fill: parent
        visible: status === Loader.Ready
        source: Bridge.backgroundMode === "video" ? "background.qml" : ""
    }

    // 图片背景（cover 裁剪）
    Image {
        id: bgImage
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        visible: Bridge.backgroundMode === "image"
        source: Bridge.backgroundMode === "image" ? Bridge.backgroundUrl : ""
    }

    // 渐变兜底（游戏主色 → 深色 + 中央水印字）
    Rectangle {
        id: bgGradient
        anchors.fill: parent
        visible: Bridge.backgroundMode === "gradient"
        gradient: Gradient {
            GradientStop { position: 0.0; color: Bridge.gradientColor }
            GradientStop { position: 1.0; color: "#0A0E1A" }
        }
        Text {
            anchors.centerIn: parent
            text: Bridge.gradientChar
            color: Qt.rgba(1, 1, 1, 0.06)
            font.pixelSize: 320
            font.weight: Font.Bold
        }
    }

    // ═══════════════ UI 层 ═══════════════
    // 空白区域拖动窗口（背景之上、UI 之下）：系统原生拖动（DWM 接管，最流畅）
    MouseArea {
        anchors.fill: parent
        z: 1
        onPressed: Bridge.startWindowMove()
    }

    // 左侧栏背景（80 宽半透明底 + 右边框）
    Rectangle {
        x: 0
        y: 0
        width: 80
        height: root.height
        z: 10
        color: "#070A14"
        opacity: 0.72
        Rectangle {
            x: 79
            width: 1
            height: parent.height
            color: "#0F1524"
            opacity: 0.8
        }
    }

    // 控制模式按钮行（全选/清空/添加，仅 ⊞ 控制模式显示）
    Row {
        x: 6
        y: 8
        spacing: 6
        z: 16
        visible: Bridge.controlMode
        Repeater {
            model: [
                { label: "全", act: () => Bridge.selectAll() },
                { label: "清", act: () => Bridge.deselectAll() },
                { label: "＋", act: () => Bridge.addScript() },
            ]
            Rectangle {
                width: 20
                height: 20
                radius: 6
                color: btnMouse.containsMouse ? "#2B3A52" : "#1F2937"
                Text {
                    anchors.centerIn: parent
                    text: modelData.label
                    color: "#FFFFFF"
                    font.pixelSize: 12
                }
                MouseArea {
                    id: btnMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: modelData.act()
                }
            }
        }
    }

    // 左侧脚本图标列表（可滚动；点击切换/启停；拖拽重排）
    ListView {
        id: gameList
        x: 12
        y: Bridge.controlMode ? 34 : 12
        width: 56
        height: root.height - (Bridge.controlMode ? 120 : 90)
        z: 15
        model: Bridge.gameModel
        spacing: 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        delegate: Rectangle {
            id: iconBox
            width: 56
            height: 56
            radius: 16
            color: "transparent"
            border.width: index === Bridge.currentIndex ? 3 : 0
            border.color: "#FFFFFF"

            // exe 图标（image://scripticon/<script_name>：按游戏身份解析，
            // 重排后行 index 不变也能取到正确图标）
            Image {
                anchors.centerIn: parent
                width: 48
                height: 48
                source: "image://scripticon/" + model.scriptName
                fillMode: Image.PreserveAspectFit
            }

            // 停用灰盖：未启用的脚本图标整体压暗（覆盖在图标之上，对齐旧 GUI
            // paintEvent 的 fillRect(4,4,48,48,黑150/255≈0.59) 变灰表现，无 ✕ 角标；
            // 两种模式都显示）。必须声明在 Image 之后，使其位于图标上层才能压暗，
            // 否则会被图标盖住、只露成"背后黑块"而非变灰。
            Rectangle {
                anchors.centerIn: parent
                width: 48
                height: 48
                radius: 10
                color: "#000000"
                opacity: Bridge.enabledStates[index] ? 0 : 0.58
            }

            MouseArea {
                id: iconMouseArea
                anchors.fill: parent
                // preventStealing：不让 Flickable(列表滚动) 抢走拖动事件，
                // 否则 onMouseYChanged 不触发、拖拽永远走 selectGame。
                preventStealing: true
                property real pressY: 0         // 局部 y，仅用于阈值判定
                property real origY: 0          // 按下时 box.y（contentItem 坐标）
                property real pressCursorY: 0   // 按下时光标在 contentItem 坐标系的 y（稳定参照）
                property bool dragging: false
                onPressed: (mouse) => {
                    pressY = mouse.y
                    origY = parent.y
                    // 光标在 ListView contentItem 坐标系中的位置（不随 box 移动而变）
                    pressCursorY = iconMouseArea.mapToItem(gameList.contentItem, mouse.x, mouse.y).y
                    dragging = false
                }
                // onPositionChanged（事件参数）比 onMouseYChanged（属性）可靠：
                // 属性更新有丢帧/延迟，导致拖拽判定时好时坏。
                onPositionChanged: (mouse) => {
                    if (!dragging && Math.abs(mouse.y - pressY) > 12) {
                        dragging = true
                        parent.z = 100  // 拖拽中浮起
                    }
                    if (dragging) {
                        // 用稳定坐标系求真实位移：局部 mouse.y 会随 box 移动而翻转，
                        // 直接用会陷入「移动 box ↔ 局部 y 反向」的反馈抖动（每两次才动一下）。
                        var cur = iconMouseArea.mapToItem(gameList.contentItem, mouse.x, mouse.y).y
                        parent.y = origY + (cur - pressCursorY)  // 视觉精确跟随
                    }
                }
                onReleased: (mouse) => {
                    // 用稳定坐标系的总位移估算目标 index（item 高 56 + spacing 8）
                    var cur = iconMouseArea.mapToItem(gameList.contentItem, mouse.x, mouse.y).y
                    var dy = cur - pressCursorY
                    parent.y = origY  // 复位（model.move 后 ListView 重排）
                    parent.z = 0
                    if (dragging) {
                        var target = index + Math.round(dy / 64)
                        target = Math.max(0, Math.min(Bridge.games.length - 1, target))
                        if (target !== index) {
                            Bridge.reorderGames(index, target)
                        }
                    } else {
                        Bridge.selectGame(index)
                    }
                }
            }
        }
    }

    // 左侧底部固定区（⊞ 模式切换 + 启动全部）
    Rectangle {
        x: 0
        y: root.height - 70
        width: 80
        height: 70
        z: 16
        color: "#070A14"
        opacity: 0.85
        // ⊞ 模式切换
        Rectangle {
            x: 10
            y: 6
            width: 60
            height: 28
            radius: 6
            color: modeBtn.containsMouse ? "#2B3A52" : "#1A2233"
            Text {
                anchors.centerIn: parent
                text: Bridge.controlMode ? "⊞ 控制模式" : "⊞ 浏览模式"
                color: "#FFFFFF"
                font.pixelSize: 11
            }
            MouseArea {
                id: modeBtn
                anchors.fill: parent
                hoverEnabled: true
                onClicked: Bridge.toggleMode()
            }
        }
        // 启动全部（黄色）
        Rectangle {
            x: 10
            y: 36
            width: 60
            height: 26
            radius: 6
            color: launchAllBtn.containsMouse ? "#FFD95C" : "#F5C542"
            Text {
                anchors.centerIn: parent
                text: "▶ 启动全部"
                color: "#1A1A1A"
                font.pixelSize: 10
            }
            MouseArea {
                id: launchAllBtn
                anchors.fill: parent
                hoverEnabled: true
                onClicked: Bridge.launchAll()
            }
        }
    }

    // 窗口控制（右上：最小化 / 设置 / 关闭）——独立组件，Loader 加载。
    Loader {
        x: 1164; y: 8; width: 116; height: 36; z: 30
        source: "window.qml"
    }

    // 右下启动胶囊（蓝色大按钮，点击启动当前脚本）——独立组件，Loader 加载。
    Loader {
        x: 960; y: 636; width: 216; height: 64; z: 20
        source: "launch.qml"
    }

    // 右侧悬浮图标条（主页/启动游戏/文件夹/B站/GitHub/壁纸）——图标用 image://uiicon 矢量绘制
    Item {
        x: 1220
        y: 80
        width: 60
        height: 300
        z: 20
        Repeater {
            model: [
                { icon: "home", act: () => Bridge.openHome() },
                { icon: "game", act: () => Bridge.launchGame() },
                { icon: "folder", act: () => Bridge.openScriptFolder() },
                { icon: "bili", act: () => Bridge.openBilibili() },
                { icon: "github", act: () => Bridge.openGithub() },
                { icon: "wallpaper", act: () => Bridge.openWallpaper() },
            ]
            Rectangle {
                x: 12
                y: 22 + index * 48
                width: 36
                height: 36
                radius: 12
                color: iconMouse.containsMouse ? "#2B3A52" : "#1F2937"
                Image {
                    anchors.centerIn: parent
                    width: 22
                    height: 22
                    source: "image://uiicon/" + modelData.icon
                    fillMode: Image.PreserveAspectFit
                }
                MouseArea {
                    id: iconMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: modelData.act()
                }
            }
        }
    }

    // toast 浮层（Bridge.toastRequested 信号 → 显示 3 秒）
    Rectangle {
        id: toast
        visible: false
        z: 50
        y: root.height - 40
        x: (root.width - width) / 2
        width: toastText.paintedWidth + 36
        height: 40
        radius: 12
        color: Qt.rgba(10 / 255, 16 / 255, 32 / 255, 0.92)
        Text {
            id: toastText
            anchors.centerIn: parent
            color: "#FFFFFF"
            font.pixelSize: 14
        }
    }
    Timer {
        id: toastTimer
        interval: 3000
        onTriggered: toast.visible = false
    }

    // 任务调度卡（日常副本 / 周常周几）：Loader 按路径懒加载，复用视频层同样的
    // "独立 .qml + Loader source" 稳定模式（不把类型 import 进 main.qml 本体）。
    Loader {
        id: taskCardLoader
        x: 128
        y: 392
        z: 20  // 高于拖拽层，避免开关/副本按钮首次点击被抢（双击感）
        source: "task_card.qml"
    }

    // toast / 添加脚本 / 重排信号连接（不用 Connections 组件，避免单例 target 解析的潜在问题）
    Component.onCompleted: {
        Bridge.toastRequested.connect(function(text) {
            toastText.text = text
            toast.visible = true
            toastTimer.restart()
        })
        Bridge.gameAdded.connect(function() {
            gameList.positionViewAtEnd()
        })
        // 重排/增删由 GameListModel 的 beginMoveRows/beginResetModel 信号精确驱动
        // （Python 侧 reorderGames 里 move + set_games 兜底 reset）。
    }
}
