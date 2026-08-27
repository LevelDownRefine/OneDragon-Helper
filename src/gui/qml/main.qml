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

    // 左侧脚本图标列表（可滚动；点击切换/启停；拖拽重排）
    // 命中区拓宽到整条背景宽(0~80)：在左侧栏内任意位置（含原两侧空隙
    // x:0~12 / x:68~80）拖动都能滚动列表，不再穿透到 z:1 全窗层触发整窗移动。
    // 图标格(iconBox)56 宽居中，负责图标重排；图标格之外的列表区负责滚动。
    ListView {
        id: gameList
        x: 0
        y: 12
        width: 80
        height: root.height - 112
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
            // 内部图标容器 56 宽居中：图标、边框、拖拽命中区都在这，
            // 两侧各 12px 留给 ListView Flickable 做列表滚动。
            Rectangle {
                id: iconInner
                anchors.horizontalCenter: parent.horizontalCenter
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
    // 平时隐藏，底部 4 按钮正常可见；拖拽时整条底部变删除区（设计性覆盖底部按钮，
    // 非意外重合），列表区完全留给重排，避免删除区盖住列表底干扰末位重排。
    Rectangle {
        id: deleteZone
        x: 0
        y: root.height - 100
        width: 80
        height: 100
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

    // 左侧底部固定区（全/清 + ⊞/＋ + 启动全部）
    // 半透明策略：底部区本身不画独立背景（color:transparent），直接复用其背后
    // 左侧栏背景条(0.72)的半透明——这样整条左侧栏（含底部）是统一的 0.72 半透明，
    // 不会再出现「底部叠一层更实的同色块」导致局部更不透明的问题。
    // 紧凑布局：按钮 30×30，行距收紧，整条高度 100。
    Rectangle {
        x: 0
        y: root.height - 100
        width: 80
        height: 100
        z: 16
        color: "transparent"
        // 上排：全 / 清（居中）
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 6
            spacing: 6
            Repeater {
                model: [
                    { label: "全", act: () => Bridge.selectAll() },
                    { label: "清", act: () => Bridge.deselectAll() },
                ]
                Rectangle {
                    width: 30
                    height: 30
                    radius: 6
                    color: btnMouseTop.containsMouse ? "#2B3A52" : "#1F2937"
                    Text {
                        anchors.centerIn: parent
                        text: modelData.label
                        color: "#FFFFFF"
                        font.pixelSize: 13
                    }
                    MouseArea {
                        id: btnMouseTop
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: modelData.act()
                    }
                }
            }
        }
        // 下排：⊞ / ＋（居中）
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 38
            spacing: 6
            Repeater {
                model: [
                    { label: "⊞", act: () => Bridge.toggleMode() },
                    { label: "＋", act: () => Bridge.addScript() },
                ]
                Rectangle {
                    width: 30
                    height: 30
                    radius: 6
                    color: btnMouseBot.containsMouse ? "#2B3A52" : "#1F2937"
                    Text {
                        anchors.centerIn: parent
                        text: modelData.label
                        color: "#FFFFFF"
                        font.pixelSize: 27
                    }
                    MouseArea {
                        id: btnMouseBot
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: modelData.act()
                    }
                }
            }
        }
        // 启动全部（黄色）
        Rectangle {
            x: 8
            y: 72
            width: 64
            height: 26
            radius: 6
            color: launchAllBtn.containsMouse ? "#FFD95C" : "#F5C542"
            Text {
                anchors.centerIn: parent
                text: "▶ 启动全部"
                color: "#1A1A1A"
                font.pixelSize: 12
            }
            MouseArea {
                id: launchAllBtn
                anchors.fill: parent
                hoverEnabled: true
                onClicked: Bridge.launchAll()
            }
        }
    }

    // 窗口控制（右上：最小化 / 关闭）——独立组件，Loader 加载。
    Loader {
        x: 1164; y: 8; width: 116; height: 36; z: 30
        source: "window.qml"
    }

    // 右下启动胶囊（蓝色大按钮，点击启动当前脚本）——独立组件，Loader 加载。
    Loader {
        x: 960; y: 636; width: 216; height: 64; z: 20
        source: "launch.qml"
    }

    // 右侧悬浮图标条（主页/启动游戏/文件夹/日志/脚本配置/B站/GitHub/壁纸）——图标用 image://uiicon 矢量绘制
    Item {
        x: 1220
        y: 80
        width: 60
        height: 348
        z: 20
        Repeater {
            model: [
                { icon: "home", act: () => Bridge.openHome() },
                { icon: "game", act: () => Bridge.launchGame() },
                { icon: "folder", act: () => Bridge.openScriptFolder() },
                { icon: "log", act: () => Bridge.openLogFolder() },
                { icon: "configfile", act: () => Bridge.openScriptConfig() },
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
