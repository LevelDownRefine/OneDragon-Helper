import QtQuick
import OneDragonHelper 1.0
import "Theme.js" as Theme

// 任务调度卡（日常副本 / 周常）：复刻旧 src/gui/task_card.py 的视觉与行为契约。
// 数据经 Bridge 暴露：taskTitle / taskAdapted / weeklySupported / dailyItems / weeklyItems；
// 下拉数据经 dailyTaskOptions(dailyName) / weeklyTaskOptions(weeklyName)；
// 副本写回经 selectDailyTask(dailyName, taskName, sequence) / selectWeeklyTask；
// 日常开关（仅声明了开关的脚本，如异环）经 setDailyEnabled(dailyName, enabled)。
// task/sequence 持久化到子脚本 config；周几起（weekly_start）持久化到 weekly_start.yml。
//
// 「周几起」选择已迁至单脚本配置弹窗（≡ 按钮打开），本卡只显示周常名占位。
//
// 布局从旧版固定坐标起步（标题 y=18 / 分隔线 y=56 / 日常 y=68），日常区与周常区都按
// 「每行 56、行数由数据决定」顺次下推（周常区上沿 = 日常区底部 + 4），卡片高度随之增长；
// 显隐仍只用 visible 切显隐，不逐个写死行 y。
//
// 显隐规则（对齐旧 _set_task_rows_visible / _refresh_weekly_chip）：
// - taskAdapted 为假 → 仅显示标题，隐藏分隔线/两区（卡片收缩）。
// - 周常区：weeklySupported 为真才显示子项；否则整区隐藏。
//
// 颜色约定：日常行与周常行共用同一套色板（标题白 / 图标底蓝 / 图标字蓝 / chip 文字蓝），
// 保证两行视觉一致；被停用的日常 chip 文字降为 muted。
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
    // 周常区上沿 = 日常区底部 + 4（对齐其它段间距，纵向节奏统一）。
    readonly property int weeklyTop: dailyArea.y + dailyArea.height + 4
    // 高度随适配态：未适配 84（仅标题）；适配时为周常区底部 + 卡片底部留白(16)，
    // 不支持周常时收到日常区底部 + 4。
    height: Bridge.taskAdapted
            ? (weeklyArea.visible ? (cardRoot.weeklyTop + weeklyArea.height + 16)
                                  : cardRoot.weeklyTop)
            : 84

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

    // 卡片投影与背景分层，文字保持清晰。
    Rectangle {
        x: 0; y: 5; width: parent.width; height: parent.height
        radius: 20
        color: "#28000000"
    }
    Rectangle {
        anchors.fill: parent
        radius: 20
        color: Theme.panel
        border.width: 1
        border.color: Theme.border
    }

    // ── 标题行 ──
    Item {
        id: titleRow
        x: 20; y: 18; width: 440; height: 36
        Rectangle {
            x: 12; y: 0; width: 36; height: 36; radius: 10
            color: Theme.accentSoft
            Image {
                anchors.centerIn: parent; width: 28; height: 28
                source: "image://uiicon/game"; fillMode: Image.PreserveAspectFit
            }
        }
        Text {
            x: 58; y: 5; width: 286; height: 26
            text: Bridge.taskTitle
            elide: Text.ElideRight
            color: Theme.text; font.pixelSize: 18; font.weight: Font.DemiBold
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: "任务配置"
            color: Theme.muted; font.pixelSize: 11
        }
    }

    // 分隔线（仅适配时显示）
    Rectangle {
        x: 20; y: 56; width: 440; height: 1
        color: Theme.divider
        visible: Bridge.taskAdapted
    }

    // ── 日常区（y=68 起，每个日常一行：标签为日常展示名，chip 为该日常已选副本）──
    // 行内尺寸、图标、文字、chip 的 x/y 与周常行严格对齐，保证两区视觉统一。
    Item {
        id: dailyArea
        objectName: "dailyArea"
        x: 20; y: 68; width: 440
        visible: Bridge.taskAdapted
        property int rowH: 56
        height: Bridge.dailyItems.length * rowH

        Column {
            id: dailyItemsCol
            y: 0
            width: parent.width
            spacing: 0
            Repeater {
                model: Bridge.dailyItems
                Item {
                    width: dailyArea.width; height: dailyArea.rowH
                    Rectangle {
                        x: 12; y: 10; width: 36; height: 36; radius: 10
                        color: Theme.accentSoft
                        Text {
                            anchors.centerIn: parent; text: "日"
                            color: Theme.accent
                            font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                    }
                    Text {
                        x: 58; y: 15; width: 112; height: 26
                        text: modelData.name
                        elide: Text.ElideRight
                        color: Theme.text
                        font.pixelSize: 14; font.weight: Font.DemiBold
                        verticalAlignment: Text.AlignVCenter
                    }
                    Rectangle {
                        id: dailyChip
                        // 首行沿用旧 objectName（单日常脚本的既有契约）；多日常脚本逐行区分。
                        objectName: index === 0 ? "dailyTaskButton"
                                                : "dailyTaskButton" + index
                        x: cardRoot.chipX; y: 10
                        width: 220
                        height: 36; radius: 10
                        color: dailyMouse.containsMouse ? Theme.hover : Theme.control
                        border.width: 1
                        border.color: dailyTaskPopup.visible && dailyTaskPopup.dailyName === modelData.name
                                      ? Theme.accent : Theme.border
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Text {
                            anchors.fill: parent
                            leftPadding: 12; rightPadding: 32
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: modelData.task_label
                            color: modelData.disabled ? Theme.muted : Theme.accent
                            font.pixelSize: 12
                        }
                        Image {
                            anchors.right: parent.right; anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            width: 20; height: 20
                            source: "image://uiicon/chevron_down"
                            rotation: dailyTaskPopup.visible && dailyTaskPopup.dailyName === modelData.name ? 180 : 0
                            opacity: 0.7
                        }
                        MouseArea {
                            id: dailyMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (Bridge.dailyTaskOptions(modelData.name).length === 0) {
                                    Bridge.toastRequested("暂无副本选项")
                                    return
                                }
                                var sameRow = dailyTaskPopup.visible
                                              && dailyTaskPopup.dailyName === modelData.name
                                dailyTaskPopup.dailyName = modelData.name
                                dailyTaskPopup.canDisable = modelData.can_disable
                                dailyTaskPopup.anchorTop = dailyArea.y + index * dailyArea.rowH
                                dailyTaskPopup.anchorBottom = dailyTaskPopup.anchorTop + dailyArea.rowH
                                weeklyTaskPopup.visible = false
                                // 同一行再点=收起；换一行=就地换菜单（visible 不变，须手动重取）
                                if (sameRow) {
                                    dailyTaskPopup.visible = false
                                } else if (dailyTaskPopup.visible) {
                                    dailyTaskPopup.openMenu()
                                } else {
                                    dailyTaskPopup.visible = true
                                }
                            }
                        }
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
        x: 20; y: cardRoot.weeklyTop; width: 440
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
                    property bool hasTask: modelData.has_task
                    Rectangle {
                        x: 12; y: 10; width: 36; height: 36; radius: 10
                        color: Theme.accentSoft
                        Text {
                            anchors.centerIn: parent; text: "周"
                            color: Theme.accent
                            font.pixelSize: 13; font.weight: Font.DemiBold
                        }
                    }
                    Text {
                        x: 58; y: 15; width: 112; height: 26
                        text: modelData.name
                        elide: Text.ElideRight
                        color: Theme.text
                        font.pixelSize: 14; font.weight: Font.DemiBold
                        verticalAlignment: Text.AlignVCenter
                    }
                    Rectangle {
                        id: wkChip
                        x: cardRoot.chipX; y: 10
                        width: 220
                        height: 36; radius: 10
                        visible: hasTask
                        color: weeklyMouse.containsMouse ? Theme.hover : Theme.control
                        border.width: 1
                        border.color: weeklyTaskPopup.visible && weeklyTaskPopup.weeklyName === modelData.name
                                      ? Theme.accent : Theme.border
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Text {
                            anchors.fill: parent
                            leftPadding: 12; rightPadding: 32
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: modelData.task_label
                            color: Theme.accent
                            font.pixelSize: 12
                        }
                        Image {
                            anchors.right: parent.right; anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            width: 20; height: 20
                            source: "image://uiicon/chevron_down"
                            rotation: weeklyTaskPopup.visible && weeklyTaskPopup.weeklyName === modelData.name ? 180 : 0
                            opacity: 0.7
                        }
                        MouseArea {
                            id: weeklyMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            enabled: weeklyArea.supported
                            onClicked: {
                                weeklyTaskPopup.weeklyName = modelData.name
                                var rowTop = weeklyArea.y + index * weeklyArea.rowH
                                weeklyTaskPopup.anchorTop = rowTop
                                weeklyTaskPopup.anchorBottom = rowTop + weeklyArea.rowH
                                weeklyTaskPopup.visible = !weeklyTaskPopup.visible
                                dailyTaskPopup.visible = false
                            }
                        }
                    }
                }
            }
        }
    }

    // 「周几起」选择已迁至单脚本配置弹窗（≡ 按钮触发），本卡不再内嵌周几下拉。

    // ── 日常副本下拉（多级级联：一级副本 → 二级选项，对齐旧 QMenu 子菜单）──
    // 左列一级副本、右列二级选项，两列各自独立 Flickable 滚动（互不挤压、
    // 长列表都能滑到底），分别解决「二级目录显示不全」与「滚动到头也漏项」。
    // 宽度/高度在 openMenu() 中按下拉内容一次性算定（仅 1 个 TextMetrics，
    // 避免每行测量导致的 hover 重布局抖动 → 卡顿）。
    // 每个日常一个弹窗实例：dailyName 标记当前是哪个日常，选项在 openMenu 时取定。
    Item {
        id: dailyTaskPopup
        objectName: "dailyTaskPopup"
        z: 100
        visible: false
        x: dailyArea.x + cardRoot.chipX
        y: dailyTaskPopup.popupY
        // 宽度随一级列 +（出现二级列时）；高度封顶避免出屏，超出由各列 Flickable 独立滚动
        width: dailyTaskPopup.rightW > 0
               ? (dailyTaskPopup.leftW + 4 + dailyTaskPopup.rightW + 8)
               : (dailyTaskPopup.leftW + 8)
        height: dailyTaskPopup.popupHeight

        property string dailyName: ""
        property bool canDisable: false
        property var options: []
        property int leftW: 200
        property int rightW: 0
        property int anchorTop: dailyArea.y
        property int anchorBottom: dailyArea.y + dailyArea.rowH
        property int popupY: anchorBottom + 4
        property int popupHeight: 360
        property int viewportH: height - 8
        property string selName: ""
        property var selSequences: []

        Rectangle {
            anchors.fill: parent; radius: 10
            color: Theme.control; border.width: 1; border.color: Theme.border
        }

        // 单个复用测量器：仅 openMenu 调用一次，避免每行 TextMetrics 的 hover 抖动
        TextMetrics { id: measTm; font.pixelSize: 13 }

        function openMenu() {
            options = Bridge.dailyTaskOptions(dailyTaskPopup.dailyName)
            var maxW = 60
            for (var i = 0; i < options.length; i++) {
                measTm.text = options[i].name
                if (measTm.width > maxW) maxW = measTm.width
            }
            if (canDisable) {
                measTm.text = "不启用"
                if (measTm.width > maxW) maxW = measTm.width
            }
            leftW = Math.min(maxW + 28, 240)
            var rows = options.length + (canDisable ? 1 : 0)
            var geom = cardRoot.placePopup(
                anchorTop, anchorBottom, Math.min(rows * 32 + 8, 360))
            popupY = geom.y
            popupHeight = geom.h
            selName = ""
            selSequences = []
            rightW = 0
        }

        onSelNameChanged: {
            selSequences = []
            for (var i = 0; i < options.length; i++) {
                if (options[i].name === selName) {
                    selSequences = options[i].sequences
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
                width: dailyTaskPopup.leftW
                height: dailyTaskPopup.viewportH
                contentWidth: leftCol.width
                contentHeight: leftCol.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: leftCol
                    width: dailyTaskPopup.leftW
                    spacing: 2
                    Repeater {
                        model: dailyTaskPopup.options
                        Rectangle {
                            width: dailyTaskPopup.leftW
                            height: 30
                            radius: 6
                            color: (optMouse.containsMouse || dailyTaskPopup.selName === modelData.name)
                                   ? Theme.accentSoft : "transparent"
                            Text {
                                anchors.fill: parent; leftPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.name
                                color: Theme.text; font.pixelSize: 13
                            }
                            Image {
                                anchors.right: parent.right; anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                width: 16; height: 16
                                source: "image://uiicon/chevron_down"
                                rotation: -90
                                opacity: 0.7
                                visible: modelData.sequences.length > 0
                            }
                            MouseArea {
                                id: optMouse; anchors.fill: parent; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onEntered: {
                                    dailyTaskPopup.selName = modelData.sequences.length > 0 ? modelData.name : ""
                                }
                                onClicked: {
                                    if (modelData.sequences.length > 0) {
                                        dailyTaskPopup.selName = modelData.name
                                    } else {
                                        Bridge.selectDailyTask(
                                            dailyTaskPopup.dailyName, modelData.name, null)
                                        dailyTaskPopup.visible = false
                                    }
                                }
                            }
                        }
                    }
                    // 该日常可停用时，一级列末尾追加「不启用」（点即生效，无需二级）
                    Rectangle {
                        width: dailyTaskPopup.leftW
                        height: 30; radius: 6
                        visible: dailyTaskPopup.canDisable
                        color: disableMouse.containsMouse ? Theme.accentSoft : "transparent"
                        Text {
                            anchors.fill: parent; leftPadding: 10
                            verticalAlignment: Text.AlignVCenter
                            text: "不启用"
                            color: Theme.muted; font.pixelSize: 13
                        }
                        MouseArea {
                            id: disableMouse; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                Bridge.setDailyEnabled(dailyTaskPopup.dailyName, false)
                                dailyTaskPopup.visible = false
                            }
                        }
                    }
                }
            }
            // 右列：二级选项（独立滚动；仅当选中带子项的副本时出现）
            Flickable {
                id: rightFlick
                visible: dailyTaskPopup.rightW > 0
                width: dailyTaskPopup.rightW
                height: dailyTaskPopup.viewportH
                contentWidth: seqCol.width
                contentHeight: seqCol.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: seqCol
                    width: dailyTaskPopup.rightW
                    spacing: 2
                    Repeater {
                        model: dailyTaskPopup.selSequences
                        Rectangle {
                            width: dailyTaskPopup.rightW
                            height: 30
                            radius: 6
                            color: seqMouse.containsMouse ? Theme.accentSoft : "transparent"
                            Text {
                                anchors.fill: parent; leftPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.label
                                color: Theme.text; font.pixelSize: 13
                            }
                            MouseArea {
                                id: seqMouse; anchors.fill: parent; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    Bridge.selectDailyTask(
                                        dailyTaskPopup.dailyName,
                                        dailyTaskPopup.selName, modelData.value)
                                    dailyTaskPopup.visible = false
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 周常副本下拉（单级：副本名列表，来自 Bridge.weeklyTaskOptions）──
    // 锚点从整个周常区底部改为被点击的具体子项行，弹出位置与点击行对齐。
    Item {
        id: weeklyTaskPopup
        objectName: "weeklyTaskPopup"
        z: 100
        visible: false
        x: weeklyArea.x + cardRoot.chipX
        y: weeklyTaskPopup.popupY
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
            color: Theme.control; border.width: 1; border.color: Theme.border
        }
        TextMetrics { id: instTm; font.pixelSize: 13 }
        function openMenu() {
            var opts = Bridge.weeklyTaskOptions(weeklyTaskPopup.weeklyName)
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
            width: weeklyTaskPopup.instW
            height: weeklyTaskPopup.viewportH
            contentWidth: instCol.width
            contentHeight: instCol.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: instCol
                width: weeklyTaskPopup.instW
                spacing: 2
                Repeater {
                    model: weeklyTaskPopup.visible
                          ? Bridge.weeklyTaskOptions(weeklyTaskPopup.weeklyName)
                          : []
                    Rectangle {
                        width: weeklyTaskPopup.instW
                        height: 30; radius: 6
                        color: instMouse.containsMouse ? Theme.accentSoft : "transparent"
                        Text {
                            anchors.fill: parent; leftPadding: 10
                            verticalAlignment: Text.AlignVCenter
                            text: modelData
                            color: Theme.text; font.pixelSize: 13
                        }
                        MouseArea {
                            id: instMouse; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                Bridge.selectWeeklyTask(
                                    weeklyTaskPopup.weeklyName, modelData)
                                weeklyTaskPopup.visible = false
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
        visible: dailyTaskPopup.visible || weeklyTaskPopup.visible
        enabled: dailyTaskPopup.visible || weeklyTaskPopup.visible
        onClicked: {
            dailyTaskPopup.visible = false
            weeklyTaskPopup.visible = false
        }
    }
}
