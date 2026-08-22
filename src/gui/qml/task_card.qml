import QtQuick
import OneDragonHelper 1.0

// 任务调度卡（日常副本 / 周常）：复刻旧 src/gui/task_card.py 的视觉与行为契约。
// 数据经 Bridge 暴露：taskTitle / taskAdapted / weeklySupported / dailyDungeonText /
// weeklyItems / masterOn / dailyOn / weeklyOn / dungeonOptions；
// 写回经 selectDungeon / selectWeeklyDungeon / toggleMaster / toggleWeekly
// （dungeon/sequence/weekly_start 持久化到 gui_state.json；开关内存态）。
//
// 「周几起」选择已迁至单脚本配置弹窗（≡ 按钮打开），本卡只显示周常名占位。
//
// 布局严格按旧版固定坐标（标题 y=18 / 分隔线 y=56 / 日常 y=68 / 周常 y=134），
// 只用 visible 切显隐、绝不动态改行 y —— 旧版 _set_task_rows_visible 就是这么做的，
// 因此日常/周常行不可能错位。
//
// 显隐规则（对齐旧 _set_task_rows_visible / _refresh_weekly_chip）：
// - taskAdapted 为假 → 仅显示标题，隐藏分隔线/两行（卡片收缩）。
// - 周常行：weeklySupported 为真才亮蓝可点；否则整行置灰、chip 写「未支持」、开关禁用。
//
// 颜色约定：日常行与周常行共用同一套色板（标题白 / 图标底蓝 / 图标字蓝 / chip 文字蓝），
// 保证两行视觉一致（旧版周常标题用了淡蓝与日常白色不一致，已统一）。
//
// 下拉用纯 QML 自绘（不引 QtQuick.Controls 的 Menu 组件类型）：项目早期在
// 自定义 .qml 组件类型解析上有非确定失败（Type unavailable），自绘更稳。
Item {
    id: cardRoot
    objectName: "cardRoot"
    width: 480
    // 高度随适配态：未适配 84（仅标题）；适配时标题(54)+分隔线+日常(56)+周常区动态高度。
    // 该脚本不支持周常时，周常区整区隐藏，高度直接缩到日常区以下。
    // 周常区含独立头部（36）+ 每项（40）+ 底部留白（16），卡片底部再留 16。
    height: Bridge.taskAdapted ? (weeklyArea.visible ? (134 + weeklyArea.height + 16) : 134) : 84

    // 窗口边界在卡片坐标系中的常量：卡片由 main.qml 的 Loader 固定在 (128, 392)，
    // 窗口固定 1280x720（popupCatcher 用的是同一套常量）。下拉据此判断上下余量。
    readonly property int winTopInCard: -392
    readonly property int winBottomInCard: 328

    // 下拉定位：优先在锚点下方展开；下方装不下且上方更宽裕时上翻（对齐系统菜单）。
    // 高度封顶到所选方向的实际余量，使 Flickable 视口 == 可见区域，内容超出即可滚动。
    // 不封顶会出事：弹窗底部越过窗口边界后，超出部分既不可见、又因内容未溢出视口
    // 而无法滚动到 —— 周常 9 个副本只显示 3 个就是这么来的（日常因内容恰好溢出
    // 视口能滚动，才掩盖了同一个问题）。
    //
    // anchorTop / anchorBottom 为锚点行在卡片坐标系的上下边，desiredH 为内容理想高度。
    // 返回 {y, h}：弹窗应放置的 y 与最终高度。
    function placePopup(anchorTop, anchorBottom, desiredH) {
        var below = cardRoot.winBottomInCard - anchorBottom - 4 - 8
        var above = anchorTop - cardRoot.winTopInCard - 4 - 8
        if (desiredH <= below || below >= above) {
            return { "y": anchorBottom + 4, "h": Math.min(desiredH, below) }
        }
        var h = Math.min(desiredH, above)
        return { "y": anchorTop - 4 - h, "h": h }
    }

    // 玻璃卡背景（半透明；文本为兄弟节点、不受 opacity 影响）
    Rectangle {
        anchors.fill: parent
        radius: 16
        color: Qt.rgba(10 / 255, 16 / 255, 32 / 255, 0.90)
        border.width: 1
        border.color: "#2A3A5C"
    }

    // ── 标题行 ──
    Item {
        id: titleRow
        x: 20; y: 18; width: 440; height: 36
        Rectangle {
            x: 12; y: 0; width: 36; height: 36; radius: 10
            color: "#F4C242"
            Text { anchors.centerIn: parent; text: "▶"; color: "#1A1A1A"; font.pixelSize: 22 }
        }
        Text {
            x: 58; y: 5; width: 260; height: 26
            text: Bridge.taskTitle
            color: "#FFFFFF"; font.pixelSize: 19; font.weight: Font.Bold
        }
        // 总开关（一键同步日常/周本；对齐旧 master_toggle）
        Item {
            id: masterToggle
            x: 388; y: 7; width: 40; height: 22
            property bool on: Bridge.masterOn
            Rectangle {
                anchors.fill: parent; radius: 11
                color: masterToggle.on ? "#2196F3" : "#2A3850"
            }
            Rectangle {
                x: masterToggle.on ? 20 : 2; y: 2; width: 18; height: 18; radius: 9
                color: "#FFFFFF"
                Behavior on x { NumberAnimation { duration: 120 } }
            }
            MouseArea {
                anchors.fill: parent
                onClicked: Bridge.toggleMaster(!masterToggle.on)
            }
        }
    }

    // 分隔线（仅适配时显示）
    Rectangle {
        x: 20; y: 56; width: 440; height: 1
        color: "#2A3850"
        visible: Bridge.taskAdapted
    }

    // ── 每日任务行（固定 y=68，对齐旧 _task_row 坐标）──
    Item {
        id: dailyRow
        x: 20; y: 68; width: 440; height: 56
        visible: Bridge.taskAdapted
        Rectangle {
            x: 12; y: 10; width: 36; height: 36; radius: 10
            color: "#1A3A7A"
            Text { anchors.centerIn: parent; text: "⚡"; color: "#7DA8FF"; font.pixelSize: 16 }
        }
        Text {
            x: 58; y: 15; width: 64; height: 26
            text: "每日任务"; color: "#FFFFFF"; font.pixelSize: 15; font.weight: Font.DemiBold
        }
        Rectangle {
            id: dailyChip
            x: 130; y: 15; width: 120; height: 26; radius: 13
            color: "#0F1A2E"; border.width: 1; border.color: "#33517A"
            Text {
                anchors.centerIn: parent; text: Bridge.dailyDungeonText
                color: "#7DA8FF"; font.pixelSize: 11
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    if (Bridge.dungeonOptions.length === 0) {
                        Bridge.toastRequested("暂无副本选项")
                    } else {
                        dungeonPopup.visible = !dungeonPopup.visible
                    }
                }
            }
        }
        // 每日任务开关（镜像总开关；点击即切总开关，对齐旧 daily_toggle 不独立接线）
        Item {
            id: dailyToggle
            x: 388; y: 17; width: 40; height: 22
            property bool on: Bridge.masterOn
            Rectangle {
                anchors.fill: parent; radius: 11
                color: dailyToggle.on ? "#2196F3" : "#2A3850"
            }
            Rectangle {
                x: dailyToggle.on ? 20 : 2; y: 2; width: 18; height: 18; radius: 9
                color: "#FFFFFF"
                Behavior on x { NumberAnimation { duration: 120 } }
            }
            MouseArea {
                anchors.fill: parent
                onClicked: Bridge.toggleMaster(!dailyToggle.on)
            }
        }
    }

    // ── 周常区（y=134 起；不支持周常时整区隐藏）──
    // 颜色与每日任务行共用同一色板（白标题 / 蓝图标底 / 蓝图标字 / 蓝 chip 字）。
    // 布局改为「头部行 + 周常列表」：头部左侧显示「周常」并放置总开关，
    // 避免原先总开关贴在第一项右侧、看起来只控制第一项的歧义。
    // 每项统一左对齐日常 chip（x=130），保证两行选项在同一垂线上。
    Item {
        id: weeklyArea
        objectName: "weeklyArea"
        x: 20; y: 134; width: 440
        visible: Bridge.taskAdapted && Bridge.weeklySupported
        property bool supported: Bridge.weeklySupported
        property int rowH: 40
        // 高度由数据模型长度推导：Column 无 count 属性（那是 Repeater 的），
        // 用 Bridge.weeklyItems.length 才可靠；每项固定 rowH。
        height: weeklyHeader.height + Bridge.weeklyItems.length * rowH + 16

        // 周常头部：📅 图标 + 「周常」标题 + 总开关
        Item {
            id: weeklyHeader
            x: 0; y: 0; width: parent.width; height: 36
            Rectangle {
                x: 12; y: 5; width: 36; height: 26; radius: 8
                color: weeklyArea.supported ? "#1A3A7A" : "#2A3040"
                Text {
                    anchors.centerIn: parent; text: "📅"
                    color: weeklyArea.supported ? "#7DA8FF" : "#4A5568"
                    font.pixelSize: 14
                }
            }
            Text {
                x: 58; y: 8; width: 64; height: 22
                text: "周常"
                color: weeklyArea.supported ? "#FFFFFF" : "#4A5568"
                font.pixelSize: 15; font.weight: Font.DemiBold
                verticalAlignment: Text.AlignVCenter
            }
            // 周常总开关（内存态，由 toggleMaster / selectWeekly 置位）
            Item {
                id: weeklyToggle
                x: 388; y: 7; width: 40; height: 22
                property bool on: Bridge.weeklyOn
                Rectangle {
                    anchors.fill: parent; radius: 11
                    color: !weeklyArea.supported ? "#2A3040"
                         : (weeklyToggle.on ? "#2196F3" : "#2A3850")
                }
                Rectangle {
                    x: weeklyToggle.on ? 20 : 2; y: 2; width: 18; height: 18; radius: 9
                    color: "#FFFFFF"
                    Behavior on x { NumberAnimation { duration: 120 } }
                }
                MouseArea {
                    anchors.fill: parent
                    enabled: weeklyArea.supported
                    onClicked: Bridge.toggleWeekly(!weeklyToggle.on)
                }
            }
        }

        // 周常列表：每种一行
        Column {
            id: weeklyItemsCol
            y: weeklyHeader.height
            width: parent.width
            spacing: 0
            Repeater {
                model: Bridge.weeklyItems
                Item {
                    width: weeklyArea.width; height: weeklyArea.rowH
                    property bool hasDungeon: modelData.has_dungeon
                    Rectangle {
                        x: 12; y: 7; width: 36; height: 26; radius: 8
                        color: weeklyArea.supported ? "#1A3A7A" : "#2A3040"
                        Text {
                            anchors.centerIn: parent; text: "📅"
                            color: weeklyArea.supported ? "#7DA8FF" : "#4A5568"
                            font.pixelSize: 14
                        }
                    }
                    Text {
                        x: 58; y: 9; width: 64; height: 22
                        text: modelData.name
                        color: weeklyArea.supported ? "#FFFFFF" : "#4A5568"
                        font.pixelSize: 14; font.weight: Font.DemiBold
                        verticalAlignment: Text.AlignVCenter
                    }
                    Rectangle {
                        id: wkChip
                        x: 130; y: 7; width: 120; height: 26; radius: 13
                        visible: hasDungeon
                        color: weeklyArea.supported ? "#0F1A2E" : "#1A2028"
                        border.width: 1
                        border.color: weeklyArea.supported ? "#33517A" : "#2A3850"
                        Text {
                            anchors.centerIn: parent
                            text: modelData.dungeon_label
                            color: weeklyArea.supported ? "#7DA8FF" : "#4A5568"
                            font.pixelSize: 11
                        }
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: weeklyArea.supported
                            onClicked: {
                                weeklyDungeonPopup.weeklyName = modelData.name
                                weeklyDungeonPopup.visible = !weeklyDungeonPopup.visible
                                dungeonPopup.visible = false
                            }
                        }
                    }
                }
            }
        }
    }

    // 「周几起」选择已迁至单脚本配置弹窗（≡ 按钮触发），本卡不再内嵌周几下拉。

    // ── 日常副本下拉（多级级联：一级副本 → 二级序列，对齐旧 QMenu 子菜单）──
    // 左列一级副本、右列二级序列，两列各自独立 Flickable 滚动（互不挤压、
    // 长列表都能滑到底），分别解决「二级目录显示不全」与「滚动到头也漏项」。
    // 宽度/高度在 openMenu() 中按下拉内容一次性算定（仅 1 个 TextMetrics，
    // 避免每行测量导致的 hover 重布局抖动 → 卡顿）。
    Item {
        id: dungeonPopup
        objectName: "dungeonPopup"
        z: 100
        visible: false
        x: dailyChip.x
        y: dungeonPopup.popupY
        // 宽度随一级列 +（出现二级列时）；高度封顶避免出屏，超出由各列 Flickable 独立滚动
        width: dungeonPopup.rightW > 0
               ? (dungeonPopup.leftW + 4 + dungeonPopup.rightW + 8)
               : (dungeonPopup.leftW + 8)
        height: dungeonPopup.popupHeight

        property int leftW: 200
        property int rightW: 0
        property int popupY: dailyRow.y + dailyRow.height + 4
        property int popupHeight: 360
        property int viewportH: height - 8
        property string selName: ""
        property var selSequences: []

        Rectangle {
            anchors.fill: parent; radius: 10
            color: "#0F1A2E"; border.width: 1; border.color: "#33517A"
        }

        // 单个复用测量器：仅 openMenu 调用一次，避免每行 TextMetrics 的 hover 抖动
        TextMetrics { id: measTm; font.pixelSize: 13 }

        function openMenu() {
            var opts = Bridge.dungeonOptions
            var maxW = 60
            for (var i = 0; i < opts.length; i++) {
                measTm.text = opts[i].name
                if (measTm.width > maxW) maxW = measTm.width
            }
            leftW = Math.min(maxW + 28, 240)
            var geom = cardRoot.placePopup(
                dailyRow.y, dailyRow.y + dailyRow.height,
                Math.min(opts.length * 32 + 8, 360))
            popupY = geom.y
            popupHeight = geom.h
            selName = ""
            selSequences = []
            rightW = 0
        }

        onSelNameChanged: {
            var opts = Bridge.dungeonOptions
            selSequences = []
            for (var i = 0; i < opts.length; i++) {
                if (opts[i].name === selName) {
                    selSequences = opts[i].sequences
                    break
                }
            }
            rightW = (selSequences.length > 0)
                     ? Math.min(200, 424 - leftW)
                     : 0
        }

        onVisibleChanged: {
            if (visible) openMenu()
            else { selName = ""; selSequences = []; rightW = 0 }
        }

        Row {
            x: 4; y: 4; spacing: 4
            // 左列：一级副本（独立滚动，必能滑到底）
            Flickable {
                id: leftFlick
                width: dungeonPopup.leftW
                height: dungeonPopup.viewportH
                contentWidth: leftCol.width
                contentHeight: leftCol.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: leftCol
                    width: dungeonPopup.leftW
                    spacing: 2
                    Repeater {
                        model: dungeonPopup.visible ? Bridge.dungeonOptions : []
                        Rectangle {
                            width: dungeonPopup.leftW
                            height: 30
                            radius: 6
                            color: (optMouse.containsMouse || dungeonPopup.selName === modelData.name)
                                   ? "#1A3A7A" : "transparent"
                            Text {
                                anchors.fill: parent; leftPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.name
                                color: modelData.clear ? "#FF9E9E" : "#FFFFFF"; font.pixelSize: 13
                            }
                            Text {
                                anchors.right: parent.right; rightPadding: 6
                                anchors.verticalCenter: parent.verticalCenter
                                text: "▸"; color: "#7DA8FF"; font.pixelSize: 12
                                visible: modelData.sequences.length > 0
                            }
                            MouseArea {
                                id: optMouse; anchors.fill: parent; hoverEnabled: true
                                onEntered: {
                                    dungeonPopup.selName = modelData.sequences.length > 0 ? modelData.name : ""
                                }
                                onClicked: {
                                    if (modelData.clear) {
                                        Bridge.selectDungeon("未选择", null)
                                        dungeonPopup.visible = false
                                    } else if (modelData.sequences.length > 0) {
                                        dungeonPopup.selName = modelData.name
                                    } else {
                                        Bridge.selectDungeon(modelData.name, null)
                                        dungeonPopup.visible = false
                                    }
                                }
                            }
                        }
                    }
                }
            }
            // 右列：二级序列（独立滚动；仅当选中带子项的副本时出现）
            Flickable {
                id: rightFlick
                visible: dungeonPopup.rightW > 0
                width: dungeonPopup.rightW
                height: dungeonPopup.viewportH
                contentWidth: seqCol.width
                contentHeight: seqCol.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: seqCol
                    width: dungeonPopup.rightW
                    spacing: 2
                    Repeater {
                        model: dungeonPopup.selSequences
                        Rectangle {
                            width: dungeonPopup.rightW
                            height: 30
                            radius: 6
                            color: seqMouse.containsMouse ? "#1A3A7A" : "transparent"
                            Text {
                                anchors.fill: parent; leftPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.label
                                color: "#FFFFFF"; font.pixelSize: 13
                            }
                            MouseArea {
                                id: seqMouse; anchors.fill: parent; hoverEnabled: true
                                onClicked: {
                                    Bridge.selectDungeon(dungeonPopup.selName, modelData.value)
                                    dungeonPopup.visible = false
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 周常副本下拉（单级：副本名列表，来自 Bridge.weeklyDungeonOptions）──
    // 复用 dungeonPopup 的测量/封顶滚动模式，宽度按内容一次性算定。
    Item {
        id: weeklyDungeonPopup
        objectName: "weeklyDungeonPopup"
        z: 100
        visible: false
        x: 130
        y: weeklyDungeonPopup.popupY
        width: instW + 8
        height: popupHeight
        property string weeklyName: ""
        property int instW: 200
        property int popupY: weeklyArea.y + weeklyArea.height + 4
        property int popupHeight: 360
        property int viewportH: height - 8

        Rectangle {
            anchors.fill: parent; radius: 10
            color: "#0F1A2E"; border.width: 1; border.color: "#33517A"
        }
        TextMetrics { id: instTm; font.pixelSize: 13 }
        function openMenu() {
            var opts = Bridge.weeklyDungeonOptions(weeklyDungeonPopup.weeklyName)
            var maxW = 60
            for (var i = 0; i < opts.length; i++) {
                instTm.text = opts[i]
                if (instTm.width > maxW) maxW = instTm.width
            }
            instW = Math.min(maxW + 28, 240)
            var geom = cardRoot.placePopup(
                weeklyArea.y, weeklyArea.y + weeklyArea.height,
                Math.min(opts.length * 32 + 8, 360))
            popupY = geom.y
            popupHeight = geom.h
        }
        onVisibleChanged: { if (visible) openMenu() }
        Flickable {
            width: weeklyDungeonPopup.instW
            height: weeklyDungeonPopup.viewportH
            contentWidth: instCol.width
            contentHeight: instCol.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: instCol
                width: weeklyDungeonPopup.instW
                spacing: 2
                Repeater {
                    model: weeklyDungeonPopup.visible
                          ? Bridge.weeklyDungeonOptions(weeklyDungeonPopup.weeklyName)
                          : []
                    Rectangle {
                        width: weeklyDungeonPopup.instW
                        height: 30; radius: 6
                        color: instMouse.containsMouse ? "#1A3A7A" : "transparent"
                        Text {
                            anchors.fill: parent; leftPadding: 10
                            verticalAlignment: Text.AlignVCenter
                            text: modelData
                            color: "#FFFFFF"; font.pixelSize: 13
                        }
                        MouseArea {
                            id: instMouse; anchors.fill: parent; hoverEnabled: true
                            onClicked: {
                                Bridge.selectWeeklyDungeon(
                                    weeklyDungeonPopup.weeklyName, modelData)
                                weeklyDungeonPopup.visible = false
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 点击空白处关闭下拉（对齐旧 QMenu：弹窗外任意点击即关闭）──
    // 全窗透明捕获层，仅当任一弹窗打开时激活；位于弹窗(z:100)之下、卡片内容(z:0)之上，
    // 故「弹窗内」点击由弹窗自身处理、「弹窗外」点击被本层拦截并关闭两个弹窗。
    MouseArea {
        id: popupCatcher
        x: -128
        y: cardRoot.winTopInCard
        width: 1280
        height: cardRoot.winBottomInCard - cardRoot.winTopInCard
        z: 99
        visible: dungeonPopup.visible || weeklyDungeonPopup.visible
        enabled: dungeonPopup.visible || weeklyDungeonPopup.visible
        onClicked: {
            dungeonPopup.visible = false
            weeklyDungeonPopup.visible = false
        }
    }
}
