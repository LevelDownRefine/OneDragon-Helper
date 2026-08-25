import QtQuick
import OneDragonHelper 1.0

// 任务调度卡（日常副本 / 周常）：复刻旧 src/gui/task_card.py 的视觉与行为契约。
// 数据经 Bridge 暴露：taskTitle / taskAdapted / weeklySupported / dailyDungeonText /
// weeklyItems / dungeonOptions；写回经 selectDungeon / selectWeeklyDungeon / selectWeekly。
// dungeon/sequence 持久化到 gui_state.json；周几起（weekly_start）持久化到 weekly_start.yml。
// 启用控制不在此卡：日常靠控制模式、周常靠周几起（均在别处实现），本卡只做副本选择。
//
// 「周几起」选择已迁至单脚本配置弹窗（≡ 按钮打开），本卡只显示周常名占位。
//
// 布局严格按旧版固定坐标（标题 y=18 / 分隔线 y=56 / 日常 y=68 / 周常 y=134），
// 只用 visible 切显隐、绝不动态改行 y —— 旧版 _set_task_rows_visible 就是这么做的，
// 因此日常/周常行不可能错位。
//
// 显隐规则（对齐旧 _set_task_rows_visible / _refresh_weekly_chip）：
// - taskAdapted 为假 → 仅显示标题，隐藏分隔线/两行（卡片收缩）。
// - 周常区：weeklySupported 为真才显示子项；否则整区隐藏。
//
// 颜色约定：日常行与周常行共用同一套色板（标题白 / 图标底蓝 / 图标字蓝 / chip 文字蓝），
// 保证两行视觉一致。
//
// 下拉用纯 QML 自绘（不引 QtQuick.Controls 的 Menu 组件类型）：项目早期在
// 自定义 .qml 组件类型解析上有非确定失败（Type unavailable），自绘更稳。
Item {
    id: cardRoot
    objectName: "cardRoot"
    width: 480
    // 副本/周常 chip 水平位置：在标签（58+64）右侧剩余空间内居中，
    // 使选项卡片在横向空白块内左右留白一致。
    readonly property int chipX: 181
    // 高度随适配态：未适配 84（仅标题）；适配时标题+分隔线+日常(56)占 128，
    // 再加周常区动态高度 + 卡片底部留白(16)。不支持周常时周常区隐藏，高度缩到 128。
    // 周常区 = 每项(56) * 项数 + 底部留白(16)。
    // 周常区上沿(128)与每日行底(124)对齐其它段间距，纵向节奏统一（文字块间均 34px）。
    height: Bridge.taskAdapted ? (weeklyArea.visible ? (128 + weeklyArea.height + 16) : 128) : 84

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
            x: cardRoot.chipX; y: 15
            width: 200
            height: 26; radius: 13
            color: "#0F1A2E"; border.width: 1; border.color: "#33517A"
            Text {
                anchors.fill: parent
                leftPadding: 12; rightPadding: 12
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                text: Bridge.dailyDungeonText
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
    }

    // ── 周常区（y=134 起；不支持周常时整区隐藏）──
    // 颜色与每日任务行共用同一色板（白标题 / 蓝图标底 / 蓝图标字 / 蓝 chip 字）。
    // 仅列出各周常子项（如「货币战争」「历战余响」），父分类标题已去除；
    // 每行尺寸、图标、文字、chip 的 y 都与「每日任务」行严格对齐，保证视觉统一。
    Item {
        id: weeklyArea
        objectName: "weeklyArea"
        x: 20; y: 128; width: 440
        visible: Bridge.taskAdapted && Bridge.weeklySupported
        property bool supported: Bridge.weeklySupported
        property int rowH: 56
        // 高度由数据模型长度推导：Column 无 count 属性（那是 Repeater 的），
        // 用 Bridge.weeklyItems.length 才可靠；每项固定 rowH。
        height: Bridge.weeklyItems.length * rowH + 16

        // 周常列表：每种一行
        Column {
            id: weeklyItemsCol
            y: 0
            width: parent.width
            spacing: 0
            Repeater {
                model: Bridge.weeklyItems
                Item {
                    width: weeklyArea.width; height: weeklyArea.rowH
                    property bool hasDungeon: modelData.has_dungeon
                    Rectangle {
                        x: 12; y: 10; width: 36; height: 36; radius: 10
                        color: weeklyArea.supported ? "#1A3A7A" : "#2A3040"
                        Text {
                            anchors.centerIn: parent; text: "📅"
                            color: weeklyArea.supported ? "#7DA8FF" : "#4A5568"
                            font.pixelSize: 14
                        }
                    }
                    Text {
                        x: 58; y: 15; width: 64; height: 26
                        text: modelData.name
                        color: weeklyArea.supported ? "#FFFFFF" : "#4A5568"
                        font.pixelSize: 15; font.weight: Font.Bold
                        verticalAlignment: Text.AlignVCenter
                    }
                    Rectangle {
                        id: wkChip
                        x: cardRoot.chipX; y: 15
                        width: 200
                        height: 26; radius: 13
                        visible: hasDungeon
                        color: weeklyArea.supported ? "#0F1A2E" : "#1A2028"
                        border.width: 1
                        border.color: weeklyArea.supported ? "#33517A" : "#2A3850"
                        Text {
                            anchors.fill: parent
                            leftPadding: 12; rightPadding: 12
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
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
                                var rowTop = weeklyArea.y + index * weeklyArea.rowH
                                weeklyDungeonPopup.anchorTop = rowTop
                                weeklyDungeonPopup.anchorBottom = rowTop + weeklyArea.rowH
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
                                color: "#FFFFFF"; font.pixelSize: 13
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
                                    if (modelData.sequences.length > 0) {
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
    // 锚点从整个周常区底部改为被点击的具体子项行，弹出位置与点击行对齐。
    Item {
        id: weeklyDungeonPopup
        objectName: "weeklyDungeonPopup"
        z: 100
        visible: false
        x: cardRoot.chipX
        y: weeklyDungeonPopup.popupY
        width: instW + 8
        height: popupHeight
        property string weeklyName: ""
        property int instW: 200
        property int anchorTop: weeklyArea.y
        property int anchorBottom: weeklyArea.y + weeklyArea.height
        property int popupY: anchorBottom + 4
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
            var geom = cardRoot.placePopup(anchorTop, anchorBottom,
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
