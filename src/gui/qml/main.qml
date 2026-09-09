import QtQuick
import QtQuick.Window
import OneDragonHelper 1.0
import "Theme.js" as Theme

// OneDragon-Helper 主场景：frameless 1280x720 启动器。
// 背景三层（视频 / 图片 / 渐变）由 Bridge.backgroundMode 切换；
// UI 层（左侧栏 / 启动胶囊 / 悬浮条 / toast）叠加其上，场景图同管线合成，
// 视频作为场景图节点不会像 QVideoWidget 那样盖住 UI。
Window {
    id: root
    width: 1280
    height: 720
    flags: Qt.FramelessWindowHint | Qt.Window
    color: Theme.canvas
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
    // sourceSize 约束解码尺寸：按显示区实际像素（含高分屏 DPR）解码，
    // 避免大图整体上传为 GPU 纹理触发 GL_MAX_TEXTURE_SIZE 降采样而发糊；
    // mipmap 提升缩小渲染质量。图片小于 sourceSize 时按原生尺寸加载，不会反向放大。
    // source 末尾追加 #v<版本号>：换壁纸时缓存路径不变，靠版本号改变 source 身份，
    // 强制 Image 重新读盘（QML 按 source 字符串缓存，否则不重载）。
    Image {
        id: bgImage
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        mipmap: true
        sourceSize.width: root.width * Screen.devicePixelRatio
        sourceSize.height: root.height * Screen.devicePixelRatio
        visible: Bridge.backgroundMode === "image"
        source: Bridge.backgroundMode === "image"
               ? Bridge.backgroundUrl + "#v" + Bridge.backgroundVersion
               : ""
    }

    // 渐变兜底（游戏主色 → 深色 + 中央水印字）
    Rectangle {
        id: bgGradient
        anchors.fill: parent
        visible: Bridge.backgroundMode === "gradient"
        gradient: Gradient {
            GradientStop { position: 0.0; color: Bridge.gradientColor }
            GradientStop { position: 1.0; color: Theme.canvas }
        }
        Text {
            anchors.centerIn: parent
            text: Bridge.gradientChar
            color: Qt.rgba(1, 1, 1, 0.06)
            font.pixelSize: 320
            font.weight: Font.Bold
        }
    }

    // 壁纸边缘压暗，保证浅色背景上的控件也有稳定对比度。
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#1F0B1220" }
            GradientStop { position: 0.48; color: "#000B1220" }
            GradientStop { position: 1; color: "#4D0B1220" }
        }
    }

    // ═══════════════ UI 层 ═══════════════
    // 空白区域拖动窗口（背景之上、UI 之下）：系统原生拖动（DWM 接管，最流畅）
    MouseArea {
        anchors.fill: parent
        z: 1
        onPressed: Bridge.startWindowMove()
    }

    // 左侧栏：图标列表与底部操作共用背景。
    Rectangle {
        x: 0
        y: 0
        width: 80
        height: root.height
        z: 10
        color: "#E6101929"
        Rectangle {
            x: 79
            width: 1
            height: parent.height
            color: Theme.border
            opacity: 0.55
        }
    }

    // 左侧脚本图标列表（可滚动；点击切换/启停；拖拽重排）
    // 命中区拓宽到整条背景宽(0~80)：在左侧栏内任意位置（含原两侧空隙
    // x:0~12 / x:68~80）拖动都能滚动列表，不再穿透到 z:1 全窗层触发整窗移动。
    // 图标格(iconBox)56 宽居中，负责图标重排；图标格之外的列表区负责滚动。
    ListView {
        id: gameList
        objectName: "gameList"
        x: 0
        y: 20
        width: 80
        height: sidebarBottom.y - y - 8
        z: 15
        model: Bridge.gameModel
        spacing: 8
        // 拖拽删除状态：dragActive 控制删除区显隐，overDelete 标记图标是否悬停删除区
        property bool dragActive: false
        property bool overDelete: false
        clip: true
        // DragAndOvershootBounds：保留滚动到边界时的过头回弹 + fling 惯性
        // （StopAtBounds 会禁掉过冲，使列表拖到顶/底立即停死，无惯性感）。
        boundsBehavior: Flickable.DragAndOvershootBounds
        delegate: Rectangle {
            id: iconBox
            width: 80
            height: 56
            color: "transparent"
            Rectangle {
                x: 3; anchors.verticalCenter: parent.verticalCenter
                width: 3; height: 24; radius: 2
                color: Theme.accent
                visible: index === Bridge.currentIndex
            }
            // 内部图标容器 56 宽居中：图标、边框、拖拽命中区都在这，
            // 两侧各 12px 留给 ListView Flickable 做列表滚动。
            Rectangle {
                id: iconInner
                objectName: "scriptIcon" + index
                anchors.horizontalCenter: parent.horizontalCenter
                width: 56
                height: 56
                radius: 16
                color: index === Bridge.currentIndex ? Theme.accentSoft
                       : (iconMouseArea.containsMouse ? Theme.control : "transparent")
                border.width: 1
                border.color: index === Bridge.currentIndex ? Theme.accent : "transparent"
                Behavior on color { ColorAnimation { duration: 140 } }

                // exe 图标（image://scripticon/<script_name>：按游戏身份解析，
                // 重排后行 index 不变也能取到正确图标）
                Image {
                    anchors.centerIn: parent
                    width: 40
                    height: 40
                    source: "image://scripticon/" + model.scriptName
                    fillMode: Image.PreserveAspectFit
                    // 脚本路径变更/创建后需即时刷新：禁用 QML 按 URL 的图标缓存，
                    // 让 delegate 重建时（reload 触发 beginResetModel）重新向
                    // provider 请求，否则同名 URL 直接走缓存、图标不更新。
                    cache: false
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
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
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
                        gameList.dragActive = false
                        gameList.overDelete = false
                    }
                    // onPositionChanged（事件参数）比 onMouseYChanged（属性）可靠：
                    // 属性更新有丢帧/延迟，导致拖拽判定时好时坏。
                    onPositionChanged: (mouse) => {
                        // 开启 hover 后，未按下的移动也会触发本事件。
                        if (!pressed) return
                        if (!dragging && Math.abs(mouse.y - pressY) > 12) {
                            dragging = true
                            parent.z = 100  // 拖拽中浮起
                            gameList.dragActive = true  // 显示删除区
                        }
                        if (dragging) {
                            // 用稳定坐标系求真实位移：局部 mouse.y 会随 box 移动而翻转，
                            // 直接用会陷入「移动 box ↔ 局部 y 反向」的反馈抖动（每两次才动一下）。
                            var cur = iconMouseArea.mapToItem(gameList.contentItem, mouse.x, mouse.y).y
                            parent.y = origY + (cur - pressCursorY)  // 视觉精确跟随
                            // 检测图标中心是否落入删除区：直接映射到 deleteZone 本地坐标系，
                            // 判断本地坐标是否落在其 [0,0]~[width,height] 边界内。
                            // 注意 mapToItem 第一参数必须是 QQuickItem（Item），
                            // 不能传 Window（root 是 Window 而非 Item），故直接用 deleteZone。
                            var c = iconInner.mapToItem(deleteZone, iconInner.width / 2, iconInner.height / 2)
                            gameList.overDelete = (c.x >= 0 && c.x <= deleteZone.width
                                                  && c.y >= 0 && c.y <= deleteZone.height)
                        }
                    }
                    onReleased: (mouse) => {
                        // 用稳定坐标系的总位移估算目标 index（item 高 56 + spacing 8）
                        var cur = iconMouseArea.mapToItem(gameList.contentItem, mouse.x, mouse.y).y
                        var dy = cur - pressCursorY
                        // 拖到删除区：触发删除（Python 侧弹二次确认后再落盘），不再走重排
                        if (dragging && gameList.overDelete) {
                            gameList.dragActive = false
                            gameList.overDelete = false
                            // 先复位图标视觉位置（拖拽中改过 parent=iconInner 的 y/z），
                            // 取消删除时图标才回原位；确认删除由 model 重载兜底复位。
                            parent.y = origY
                            parent.z = 0
                            Bridge.deleteScript(index)
                            return
                        }
                        parent.y = origY  // 复位（model.move 后 ListView 重排）
                        parent.z = 0
                        gameList.dragActive = false
                        gameList.overDelete = false
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
    }

    // 拖拽删除区：拖拽图标时覆盖底部固定区显示，图标中心落入即删除（红色高亮反馈）。
    // 平时隐藏；拖拽时整条底部变删除区（覆盖底部按钮，
    // 非意外重合），列表区完全留给重排，避免删除区盖住列表底干扰末位重排。
    Rectangle {
        id: deleteZone
        x: 0
        y: sidebarBottom.y
        width: 80
        height: sidebarBottom.height
        z: 18
        radius: 6
        color: gameList.overDelete ? "#E74C3C" : "#922B21"
        visible: gameList.dragActive
        Column {
            anchors.centerIn: parent
            spacing: 4
            Image {
                anchors.horizontalCenter: parent.horizontalCenter
                source: "image://uiicon/trash"
                width: 36
                height: 36
                fillMode: Image.PreserveAspectFit
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "拖到此处删除"
                color: "#FFFFFF"
                font.pixelSize: 11
            }
        }
    }

    // 左侧底部只保留控制模式与启动全部。
    Rectangle {
        id: sidebarBottom
        x: 0
        y: root.height - height
        width: 80
        height: 120
        z: 16
        color: "transparent"
        Rectangle {
            x: 12; y: 0; width: 56; height: 1
            color: Theme.divider
        }
        Rectangle {
            id: controlModeButton
            objectName: "controlModeButton"
            x: 16; y: 8; width: 48; height: 48; radius: 14
            color: modeMouse.containsMouse ? Theme.hover
                   : (Bridge.controlMode ? Theme.accentSoft : Theme.control)
            border.width: 1
            border.color: Bridge.controlMode ? Theme.accent : Theme.border
            Behavior on color { ColorAnimation { duration: 120 } }
            Image {
                anchors.centerIn: parent
                width: 32; height: 32
                source: "image://uiicon/grid"
                opacity: Bridge.controlMode ? 1 : 0.7
            }
            MouseArea {
                id: modeMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: Bridge.toggleMode()
            }
        }
        // 黄色圆形按钮搭配深色播放图标，突出批量启动入口。
        Rectangle {
            objectName: "launchAllButton"
            x: 16; y: 64; width: 48; height: 48; radius: width / 2
            color: launchAllBtn.pressed ? Theme.batchPressed
                   : (launchAllBtn.containsMouse ? Theme.batchHover : Theme.batch)
            Behavior on color { ColorAnimation { duration: 120 } }
            Image {
                anchors.centerIn: parent
                anchors.horizontalCenterOffset: 1
                width: 32; height: 32
                source: "image://uiicon/play_all"
                scale: launchAllBtn.pressed ? 0.92 : 1
                Behavior on scale { NumberAnimation { duration: 80 } }
            }
            Rectangle {
                objectName: "launchAllHint"
                anchors.left: parent.right; anchors.leftMargin: 28
                anchors.verticalCenter: parent.verticalCenter
                width: launchAllHintText.implicitWidth + 24; height: 32; radius: 8
                color: Theme.control
                border.width: 1
                border.color: Theme.border
                opacity: launchAllBtn.containsMouse ? 1 : 0
                visible: opacity > 0
                Behavior on opacity { NumberAnimation { duration: 140 } }
                Text {
                    id: launchAllHintText
                    anchors.centerIn: parent
                    text: "启动全部"
                    color: Theme.text
                    font.pixelSize: 12
                }
            }
            MouseArea {
                id: launchAllBtn
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: Bridge.launchAll()
            }
        }
    }

    // 菜单展开时将提示移到上方，避免遮住操作按钮。
    Rectangle {
        objectName: "controlModeHint"
        x: controlBubble.x
        y: controlBubble.visible ? controlBubble.y - height - 8
           : sidebarBottom.y + controlModeButton.y + (controlModeButton.height - height) / 2
        width: controlModeHintText.implicitWidth + 24; height: 32; radius: 8
        z: 37
        color: Theme.control
        border.width: 1
        border.color: Theme.border
        opacity: modeMouse.containsMouse && !gameList.dragActive ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 140 } }
        Text {
            id: controlModeHintText
            objectName: "controlModeHintText"
            anchors.centerIn: parent
            text: Bridge.controlMode ? "退出控制模式" : "控制模式"
            color: Theme.text
            font.pixelSize: 12
        }
    }

    // 气泡不遮挡左侧脚本列表，控制模式下仍可逐项切换启停。
    MouseArea {
        x: 80; y: 0; width: root.width - 80; height: root.height
        z: 35
        visible: controlBubble.visible
        onClicked: Bridge.toggleMode()
    }
    Rectangle {
        id: controlBubble
        objectName: "controlBubble"
        x: 92
        y: sidebarBottom.y + controlModeButton.y + (controlModeButton.height - height) / 2
        width: 156; height: 60; radius: 16
        z: 36
        visible: Bridge.controlMode && !gameList.dragActive
        color: Theme.panel
        border.width: 1
        border.color: Theme.border
        transformOrigin: Item.Left
        scale: visible ? 1 : 0.94
        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        Rectangle {
            x: -5; anchors.verticalCenter: parent.verticalCenter
            width: 12; height: 12; rotation: 45; radius: 2
            color: Theme.panel
            z: -1
        }
        // 气泡内空隙也属于菜单，不能穿透到关闭层。
        MouseArea { anchors.fill: parent }
        Row {
            anchors.centerIn: parent
            spacing: 8
            Repeater {
                model: [
                    { name: "selectAllButton", label: "全", act: () => Bridge.selectAll() },
                    { name: "deselectAllButton", label: "清", act: () => Bridge.deselectAll() },
                    { name: "addScriptButton", label: "＋", act: () => {
                        Bridge.toggleMode()
                        Bridge.addScript()
                    } },
                ]
                Rectangle {
                    objectName: modelData.name
                    width: 36; height: 36; radius: 10
                    color: actionMouse.containsMouse ? Theme.hover : Theme.control
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        anchors.centerIn: parent
                        text: modelData.label
                        color: Theme.text
                        font.pixelSize: index === 2 ? 23 : 14
                    }
                    MouseArea {
                        id: actionMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: modelData.act()
                    }
                }
            }
        }
    }
    Shortcut {
        sequence: "Escape"
        enabled: controlBubble.visible
        onActivated: Bridge.toggleMode()
    }

    // 窗口控制（右上：配置 / 最小化 / 关闭）——独立组件，Loader 加载。
    Loader {
        x: 1136; y: 16; width: 128; height: 44; z: 30
        source: "window.qml"
    }

    // 右下主操作：启动当前脚本，右侧入口编辑该脚本配置。
    Loader {
        x: 960; y: 636; width: 236; height: 60; z: 20
        source: "launch.qml"
    }

    // 右侧悬浮图标条（主页/启动游戏/文件夹/日志/脚本配置/B站/GitHub/壁纸）——图标用 image://uiicon 矢量绘制
    Rectangle {
        x: 1212
        y: 88
        width: 52
        height: 396
        z: 20
        radius: 18
        color: Theme.panel
        border.width: 1
        border.color: Theme.border
        Repeater {
            model: [
                { icon: "home", label: "项目主页", act: () => Bridge.openHome() },
                { icon: "game", label: "启动游戏", act: () => Bridge.launchGame() },
                { icon: "folder", label: "脚本目录", act: () => Bridge.openScriptFolder() },
                { icon: "log", label: "运行日志", act: () => Bridge.openLogFolder() },
                { icon: "configfile", label: "脚本配置文件", act: () => Bridge.openScriptConfig() },
                { icon: "bili", label: "哔哩哔哩", act: () => Bridge.openBilibili() },
                { icon: "github", label: "GitHub", act: () => Bridge.openGithub() },
                { icon: "wallpaper", label: "更换壁纸", act: () => Bridge.openWallpaper() },
            ]
            Rectangle {
                x: 8
                y: 12 + index * 48
                width: 36
                height: 36
                radius: 10
                color: iconMouse.containsMouse ? Theme.hover : "transparent"
                Behavior on color { ColorAnimation { duration: 140 } }
                Image {
                    anchors.centerIn: parent
                    width: 26
                    height: 26
                    source: "image://uiicon/" + modelData.icon
                    fillMode: Image.PreserveAspectFit
                }
                Rectangle {
                    anchors.right: parent.left
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    width: hintText.implicitWidth + 24
                    height: 32
                    radius: 8
                    color: Theme.control
                    border.width: 1
                    border.color: Theme.border
                    opacity: iconMouse.containsMouse ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 140 } }
                    Text {
                        id: hintText
                        anchors.centerIn: parent
                        text: modelData.label
                        color: Theme.text
                        font.pixelSize: 12
                    }
                }
                MouseArea {
                    id: iconMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: modelData.act()
                }
            }
        }
    }

    // toast 浮层（Bridge.toastRequested 信号 → 显示 3 秒）
    Rectangle {
        id: toast
        objectName: "toast"
        visible: false
        z: 50
        y: root.height - height - 24
        x: (root.width - width) / 2
        width: Math.min(toastText.implicitWidth + 40, root.width - 240)
        height: Math.max(44, toastText.contentHeight + 24)
        radius: 12
        color: Theme.panel
        border.width: 1
        border.color: Theme.border
        Text {
            id: toastText
            objectName: "toastText"
            anchors.centerIn: parent
            width: parent.width - 40
            wrapMode: Text.Wrap
            color: Theme.text
            font.pixelSize: 13
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
