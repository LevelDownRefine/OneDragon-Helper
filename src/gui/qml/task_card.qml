import QtQuick
import OneDragonHelper 1.0
import "Theme.js" as Theme
import "Layout.js" as Layout

// 任务调度卡（日常副本 / 周常）：复刻旧 src/gui/task_card.py 的视觉与行为契约。
// 数据经 Bridge 暴露：taskTitle / taskAdapted / weeklySupported / dailyItems / weeklyItems；
// 下拉数据经 dailyOptions(dailyName) / weeklyOptions(weeklyName)；
// 副本写回经 selectDaily(dailyName, taskName, sequence) / selectWeekly；
// 日常开关（仅声明了开关的脚本，如异环）经 setDailyEnabled(dailyName, enabled)。
// task/sequence 持久化到子脚本 config；周几起（weekly_start）持久化到 weekly.yml。
//
// 周常行有两块 chip：左侧「周几起」（条目级，每条周常各一个，见 weeklyStartButton）、
// 右侧副本（仅需选副本的周常有）；两块合计宽 = 日常行单个 chip 宽，使两行控件区右边界
// 对齐。无副本选型的周常只有「周几起」一块，此时它独占整宽（与日常 chip 等宽对齐）。
//
// 布局从旧版固定坐标起步（标题 y=18 / 分隔线 y=56 / 日常 y=68），日常区与周常区都按
// 「每行 Layout.taskRowHeight、行数由数据决定」顺次下推（周常区上沿 = 日常区底部），
// 卡片高度随之增长；显隐仍只用 visible 切显隐，不逐个写死行 y。
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
    // 周常行把 chip 区对半分给「周几起 + 副本」，两块合计宽 = 日常单个 chip 宽（右边界对齐）；
    // 无需选副本的周常没有右块，「周几起」独占整宽，故这两个位置只用于有副本的行。
    readonly property int weeklyCopyX: chipX + Layout.weeklyStartChipWidth + Layout.chipGap
    readonly property int weeklyCopyW: Layout.chipWidth
                                        - Layout.weeklyStartChipWidth - Layout.chipGap
    // 周常区上沿 = 日常区底部：任务行自带上下留白，区块外沿直接相接即为统一的行间距。
    readonly property int weeklyTop: dailyArea.y + dailyArea.height
    // 行区自标题行下方开始（rowsTop）；内容高度与视口高度：行数少时视口 = 内容高度
    // （卡片自适应，与旧版观感一致）；行数多时（如原神 9 个日常）视口封顶到窗口底并滚动。
    readonly property int rowsTop: 68
    readonly property int rowsContentH: (weeklyArea.visible
                                         ? weeklyArea.y + weeklyArea.height
                                         : dailyArea.y + dailyArea.height)
                                         + Layout.cardBottomPad
    readonly property int rowsViewportH: Layout.windowHeight - Layout.taskCardY
                                         - Layout.cardBottomPad
    readonly property int rowsHeight: Math.min(rowsContentH, rowsViewportH)
    // 高度随适配态：未适配 84（仅标题）；适配时为行区视口高度（已含卡片底部留白）。
    height: Bridge.taskAdapted ? rowsHeight : 84

    // 下拉和点击遮罩共用窗口边界，由画布尺寸与卡片位置推导。
    readonly property int winTopInCard: -Layout.taskCardY
    readonly property int winBottomInCard: Layout.windowHeight - Layout.taskCardY

    // 下拉定位：优先在锚点下方展开；下方装不下且上方更宽裕时上翻（对齐系统菜单）。
    // 高度封顶到所选方向的实际余量，使 Flickable 视口 == 可见区域，内容超出即可滚动。
    // 不封顶会出事：弹窗底部越过窗口边界后，超出部分既不可见、又因内容未溢出视口
    // 而无法滚动到 —— 周常 9 个副本只显示 3 个就是这么来的（日常因内容恰好溢出
    // 视口能滚动，才掩盖了同一个问题）。
    //
    // anchorTop / anchorBottom 为锚点行在滚动内容坐标系里的上下边，desiredH 为内容理想高度。
    // 行区在 rowsFlick 里：先把锚点折成卡片坐标，再按窗口余量决定向下还是向上展开。
    // 返回 {y, h}：弹窗应放置的 y 与最终高度。
    function placePopup(anchorTop, anchorBottom, desiredH) {
        var top = anchorTop - rowsFlick.contentY
        var bottom = anchorBottom - rowsFlick.contentY
        var below = cardRoot.winBottomInCard - bottom
                    - Layout.popupAnchorGap - Layout.popupEdgeMargin
        var above = top - cardRoot.winTopInCard
                    - Layout.popupAnchorGap - Layout.popupEdgeMargin
        if (desiredH <= below || below >= above) {
            return { "y": bottom + Layout.popupAnchorGap,
                     "h": Math.min(desiredH, below) }
        }
        var h = Math.min(desiredH, above)
        return { "y": top - Layout.popupAnchorGap - h, "h": h }
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

    // ── 行区滚动视口：只覆盖标题行下方，故滚动内容不会滑进标题行 ──
    // 子项挂在 rowsContent 里（内容坐标 = 卡片坐标 - rowsTop），因此行区各区块仍按
    // 卡片坐标声明、弹窗锚点也只需减 contentY（rowsTop 在两端抵消）。
    Flickable {
        id: rowsFlick
        objectName: "rowsFlick"
        x: 0; y: cardRoot.rowsTop
        width: cardRoot.width
        height: cardRoot.rowsHeight - cardRoot.rowsTop
        contentWidth: width
        contentHeight: Math.max(0, cardRoot.rowsContentH - cardRoot.rowsTop)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Item {
            id: rowsContent
            y: -cardRoot.rowsTop
            width: cardRoot.width
        }
    }

    // ── 日常区（y=68 起，每个日常一行：标签为日常展示名，chip 为该日常已选副本）──
    // 行内尺寸、图标、文字、chip 的 x/y 与周常行严格对齐，保证两区视觉统一。
    Item {
        id: dailyArea
        objectName: "dailyArea"
        parent: rowsContent
        x: 20; y: 68; width: 440
        visible: Bridge.taskAdapted
        readonly property int rowH: Layout.taskRowHeight
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
                        objectName: index === 0 ? "dailyButton"
                                                : "dailyButton" + index
                        x: cardRoot.chipX; y: 10
                        width: Layout.chipWidth
                        height: 36; radius: 10
                        color: dailyMouse.containsMouse ? Theme.hover : Theme.control
                        border.width: 1
                        border.color: dailyPopup.visible && dailyPopup.dailyName === modelData.name
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
                            rotation: dailyPopup.visible && dailyPopup.dailyName === modelData.name ? 180 : 0
                            opacity: 0.7
                        }
                        MouseArea {
                            id: dailyMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                // 纯开关日常（switch_only）没有副本可选项，chip 仍要弹窗
                                // —— 菜单只列「启用 / 不启用」两项。
                                if (Bridge.dailyOptions(modelData.name).length === 0
                                        && !modelData.switch_only) {
                                    Bridge.toastRequested("暂无副本选项")
                                    return
                                }
                                var sameRow = dailyPopup.visible
                                              && dailyPopup.dailyName === modelData.name
                                dailyPopup.dailyName = modelData.name
                                dailyPopup.canDisable = modelData.can_disable
                                dailyPopup.switchOnly = modelData.switch_only
                                dailyPopup.anchorTop = dailyArea.y + index * dailyArea.rowH
                                dailyPopup.anchorBottom = dailyPopup.anchorTop + dailyArea.rowH
                                weeklyPopup.visible = false
                                weeklyStartPopup.visible = false
                                // 同一行再点=收起；换一行=就地换菜单（visible 不变，须手动重取）
                                if (sameRow) {
                                    dailyPopup.visible = false
                                } else if (dailyPopup.visible) {
                                    dailyPopup.openMenu()
                                } else {
                                    dailyPopup.visible = true
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
        parent: rowsContent
        x: 20; y: cardRoot.weeklyTop; width: 440
        visible: Bridge.taskAdapted && Bridge.weeklySupported
        property bool supported: Bridge.weeklySupported
        // 高度由数据模型长度推导：Column 无 count 属性（那是 Repeater 的），
        // 用 Bridge.weeklyItems.length 才可靠；每项固定 rowH（与日常行共用同一行高），
        // 底部留白不在本区高度里，由卡片统一加。
        readonly property int rowH: Layout.taskRowHeight
        height: Bridge.weeklyItems.length * rowH

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
                    // 「周几起」chip：每条周常各一个（条目级起始日）。右侧有副本 chip 时
                    // 让出半个 chip 宽；无副本选型时独占整宽，与日常行的 chip 完全对齐。
                    Rectangle {
                        id: wkStartChip
                        objectName: "weeklyStartButton" + index
                        x: cardRoot.chipX; y: 10
                        width: hasTask ? Layout.weeklyStartChipWidth : Layout.chipWidth
                        height: 36; radius: 10
                        color: weeklyStartMouse.containsMouse ? Theme.hover : Theme.control
                        border.width: 1
                        border.color: weeklyStartPopup.visible && weeklyStartPopup.weeklyName === modelData.name
                                      ? Theme.accent : Theme.border
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Text {
                            anchors.fill: parent
                            leftPadding: 12; rightPadding: 32
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: modelData.start_label
                            color: modelData.start_set ? Theme.accent : Theme.muted
                            font.pixelSize: 12
                        }
                        Image {
                            anchors.right: parent.right; anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            width: 20; height: 20
                            source: "image://uiicon/chevron_down"
                            rotation: weeklyStartPopup.visible && weeklyStartPopup.weeklyName === modelData.name ? 180 : 0
                            opacity: 0.7
                        }
                        MouseArea {
                            id: weeklyStartMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                var rowTop = weeklyArea.y + index * weeklyArea.rowH
                                weeklyStartPopup.weeklyName = modelData.name
                                weeklyStartPopup.anchorTop = rowTop
                                weeklyStartPopup.anchorBottom = rowTop + weeklyArea.rowH
                                weeklyStartPopup.visible = !weeklyStartPopup.visible
                                dailyPopup.visible = false
                                weeklyPopup.visible = false
                            }
                        }
                    }
                    Rectangle {
                        id: wkChip
                        objectName: "weeklyTaskButton" + index
                        x: cardRoot.weeklyCopyX; y: 10
                        width: cardRoot.weeklyCopyW
                        height: 36; radius: 10
                        visible: hasTask
                        color: weeklyMouse.containsMouse ? Theme.hover : Theme.control
                        border.width: 1
                        border.color: weeklyPopup.visible && weeklyPopup.weeklyName === modelData.name
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
                            rotation: weeklyPopup.visible && weeklyPopup.weeklyName === modelData.name ? 180 : 0
                            opacity: 0.7
                        }
                        MouseArea {
                            id: weeklyMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            enabled: weeklyArea.supported
                            onClicked: {
                                weeklyPopup.weeklyName = modelData.name
                                var rowTop = weeklyArea.y + index * weeklyArea.rowH
                                weeklyPopup.anchorTop = rowTop
                                weeklyPopup.anchorBottom = rowTop + weeklyArea.rowH
                                weeklyPopup.visible = !weeklyPopup.visible
                                dailyPopup.visible = false
                                weeklyStartPopup.visible = false
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 日常副本下拉（多级级联：一级副本 → 二级选项，对齐旧 QMenu 子菜单）──
    // 左列一级副本、右列二级选项，两列各自独立 Flickable 滚动（互不挤压、
    // 长列表都能滑到底），分别解决「二级目录显示不全」与「滚动到头也漏项」。
    // 宽度/高度在 openMenu() 中按下拉内容一次性算定（仅 1 个 TextMetrics，
    // 避免每行测量导致的 hover 重布局抖动 → 卡顿）。
    // 每个日常一个弹窗实例：dailyName 标记当前是哪个日常，选项在 openMenu 时取定。
    Item {
        id: dailyPopup
        objectName: "dailyPopup"
        z: 100
        visible: false
        x: dailyArea.x + cardRoot.chipX
        y: dailyPopup.popupY
        // 宽度随一级列 +（出现二级列时）；高度封顶避免出屏，超出由各列 Flickable 独立滚动
        width: dailyPopup.rightW > 0
               ? (dailyPopup.leftW + 4 + dailyPopup.rightW + 8)
               : (dailyPopup.leftW + 8)
        height: dailyPopup.popupHeight

        property string dailyName: ""
        property bool canDisable: false
        // 纯开关日常：菜单只列「启用 / 不启用」，不列副本
        property bool switchOnly: false
        property var options: []
        property int leftW: 200
        property int rightW: 0
        property int anchorTop: dailyArea.y
        property int anchorBottom: dailyArea.y + dailyArea.rowH
        property int popupY: anchorBottom + Layout.popupAnchorGap
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
            options = Bridge.dailyOptions(dailyPopup.dailyName)
            var maxW = 60
            for (var i = 0; i < options.length; i++) {
                measTm.text = options[i].display_name
                if (measTm.width > maxW) maxW = measTm.width
            }
            if (canDisable) {
                measTm.text = "不启用"
                if (measTm.width > maxW) maxW = measTm.width
            }
            leftW = Math.min(maxW + 28, 240)
            var rows = options.length + (canDisable ? 1 : 0) + (switchOnly ? 1 : 0)
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
                if (options[i].display_name === selName) {
                    if (options[i].options !== undefined) {
                        selSequences = options[i].options.values
                    }
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
                width: dailyPopup.leftW
                height: dailyPopup.viewportH
                contentWidth: leftCol.width
                contentHeight: leftCol.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: leftCol
                    width: dailyPopup.leftW
                    spacing: 2
                    Repeater {
                        model: dailyPopup.options
                        Rectangle {
                            // 该选项是否带二级子选项（声明词汇：options.values 递归）
                            property bool hasSub:
                                modelData.options !== undefined
                                && modelData.options.values.length > 0
                            width: dailyPopup.leftW
                            height: 30
                            radius: 6
                            color: (optMouse.containsMouse || dailyPopup.selName === modelData.display_name)
                                   ? Theme.accentSoft : "transparent"
                            Text {
                                anchors.fill: parent; leftPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.display_name
                                color: Theme.text; font.pixelSize: 13
                            }
                            Image {
                                anchors.right: parent.right; anchors.rightMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                width: 16; height: 16
                                source: "image://uiicon/chevron_down"
                                rotation: -90
                                opacity: 0.7
                                visible: hasSub
                            }
                            MouseArea {
                                id: optMouse; anchors.fill: parent; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onEntered: {
                                    dailyPopup.selName = hasSub ? modelData.display_name : ""
                                }
                                onClicked: {
                                    if (hasSub) {
                                        dailyPopup.selName = modelData.display_name
                                    } else {
                                        Bridge.selectDaily(
                                            dailyPopup.dailyName, modelData.display_name, null)
                                        dailyPopup.visible = false
                                    }
                                }
                            }
                        }
                    }
                    // 纯开关日常：给出「启用」，与下面的「不启用」构成开关两态
                    Rectangle {
                        width: dailyPopup.leftW
                        height: 30; radius: 6
                        visible: dailyPopup.switchOnly && dailyPopup.canDisable
                        color: enableMouse.containsMouse ? Theme.accentSoft : "transparent"
                        Text {
                            anchors.fill: parent; leftPadding: 10
                            verticalAlignment: Text.AlignVCenter
                            text: "启用"
                            color: Theme.text; font.pixelSize: 13
                        }
                        MouseArea {
                            id: enableMouse; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                Bridge.setDailyEnabled(dailyPopup.dailyName, true)
                                dailyPopup.visible = false
                            }
                        }
                    }
                    // 该日常可停用时，一级列末尾追加「不启用」（点即生效，无需二级）
                    Rectangle {
                        width: dailyPopup.leftW
                        height: 30; radius: 6
                        visible: dailyPopup.canDisable
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
                                Bridge.setDailyEnabled(dailyPopup.dailyName, false)
                                dailyPopup.visible = false
                            }
                        }
                    }
                }
            }
            // 右列：二级选项（独立滚动；仅当选中带子项的副本时出现）
            Flickable {
                id: rightFlick
                visible: dailyPopup.rightW > 0
                width: dailyPopup.rightW
                height: dailyPopup.viewportH
                contentWidth: seqCol.width
                contentHeight: seqCol.height
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: seqCol
                    width: dailyPopup.rightW
                    spacing: 2
                    Repeater {
                        model: dailyPopup.selSequences
                        Rectangle {
                            width: dailyPopup.rightW
                            height: 30
                            radius: 6
                            color: seqMouse.containsMouse ? Theme.accentSoft : "transparent"
                            Text {
                                anchors.fill: parent; leftPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.display_name
                                color: Theme.text; font.pixelSize: 13
                            }
                            MouseArea {
                                id: seqMouse; anchors.fill: parent; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    Bridge.selectDaily(
                                        dailyPopup.dailyName,
                                        dailyPopup.selName, modelData.physical_name)
                                    dailyPopup.visible = false
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 周常副本下拉（单级：副本名列表，来自 Bridge.weeklyOptions）──
    // 锚点从整个周常区底部改为被点击的具体子项行，弹出位置与点击行对齐。
    Item {
        id: weeklyPopup
        objectName: "weeklyPopup"
        z: 100
        visible: false
        // 挂在副本 chip 下方：副本 chip 是行内最右控件，故下拉右对齐到它（= 日常 chip 的
        // 右边界），宽度随内容伸缩时也始终留在卡片内。chipX 是区内容坐标，须补 weeklyArea.x。
        x: weeklyArea.x + cardRoot.weeklyCopyX + cardRoot.weeklyCopyW - width
        y: weeklyPopup.popupY
        width: instW + 8
        height: popupHeight
        property string weeklyName: ""
        property int instW: 200
        property int anchorTop: weeklyArea.y
        property int anchorBottom: weeklyArea.y + weeklyArea.height
        property int popupY: anchorBottom + Layout.popupAnchorGap
        property int popupHeight: 360
        property int viewportH: height - 8

        Rectangle {
            anchors.fill: parent; radius: 10
            color: Theme.control; border.width: 1; border.color: Theme.border
        }
        TextMetrics { id: instTm; font.pixelSize: 13 }
        function openMenu() {
            var opts = Bridge.weeklyOptions(weeklyPopup.weeklyName)
            var maxW = 60
            for (var i = 0; i < opts.length; i++) {
                instTm.text = opts[i].display_name
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
            width: weeklyPopup.instW
            height: weeklyPopup.viewportH
            contentWidth: instCol.width
            contentHeight: instCol.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: instCol
                width: weeklyPopup.instW
                spacing: 2
                Repeater {
                    model: weeklyPopup.visible
                          ? Bridge.weeklyOptions(weeklyPopup.weeklyName)
                          : []
                    Rectangle {
                        width: weeklyPopup.instW
                        height: 30; radius: 6
                        color: instMouse.containsMouse ? Theme.accentSoft : "transparent"
                        Text {
                            anchors.fill: parent; leftPadding: 10
                            verticalAlignment: Text.AlignVCenter
                            text: modelData.display_name
                            color: Theme.text; font.pixelSize: 13
                        }
                        MouseArea {
                            id: instMouse; anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                Bridge.selectWeekly(
                                    weeklyPopup.weeklyName, modelData.display_name)
                                weeklyPopup.visible = false
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 「周几起」下拉（单级：周一~周日；选中写 weekly.yml 的 weekly_start 段）──
    // 每条周常各一份起始日（条目级），锚点取被点击的具体行。
    Item {
        id: weeklyStartPopup
        objectName: "weeklyStartPopup"
        z: 100
        visible: false
        x: weeklyArea.x + cardRoot.chipX
        y: weeklyStartPopup.popupY
        width: Layout.weeklyStartChipWidth + 8
        height: popupHeight
        property string weeklyName: ""
        property int anchorTop: weeklyArea.y
        property int anchorBottom: weeklyArea.y + weeklyArea.rowH
        property int popupY: anchorBottom + Layout.popupAnchorGap
        // 上限按候选数给足（不启用 + 周一~周日共 8 项 = 264），窗口放不下时由 placePopup 收窄
        property int popupHeight: 272
        property int viewportH: height - 8

        Rectangle {
            anchors.fill: parent; radius: 10
            color: Theme.control; border.width: 1; border.color: Theme.border
        }
        function openMenu() {
            var opts = Bridge.weeklyStartOptions()
            var geom = cardRoot.placePopup(anchorTop, anchorBottom,
                Math.min(opts.length * 32 + 8, 272))
            popupY = geom.y
            popupHeight = geom.h
        }
        onVisibleChanged: { if (visible) openMenu() }
        Flickable {
            width: weeklyStartPopup.width
            height: weeklyStartPopup.viewportH
            contentWidth: dayCol.width
            contentHeight: dayCol.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: dayCol
                width: weeklyStartPopup.width
                spacing: 2
                Repeater {
                    model: weeklyStartPopup.visible ? Bridge.weeklyStartOptions() : []
                    Rectangle {
                        width: weeklyStartPopup.width
                        height: 30; radius: 6
                        color: dayMouse.containsMouse ? Theme.accentSoft : "transparent"
                        Text {
                            anchors.fill: parent; leftPadding: 10
                            verticalAlignment: Text.AlignVCenter
                            text: modelData.label
                            color: Theme.text; font.pixelSize: 13
                        }
                        MouseArea {
                            id: dayMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                Bridge.selectWeeklyStart(
                                    weeklyStartPopup.weeklyName, modelData.value)
                                weeklyStartPopup.visible = false
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 点击空白处关闭下拉（对齐旧 QMenu：弹窗外任意点击即关闭）──
    // 全窗透明捕获层，仅当任一弹窗打开时激活；位于弹窗(z:100)之下、卡片内容(z:0)之上，
    // 故「弹窗内」点击由弹窗自身处理、「弹窗外」点击被本层拦截并关闭全部弹窗。
    MouseArea {
        id: popupCatcher
        objectName: "popupCatcher"
        x: -Layout.taskCardX
        y: cardRoot.winTopInCard
        width: Layout.windowWidth
        height: cardRoot.winBottomInCard - cardRoot.winTopInCard
        z: 99
        visible: dailyPopup.visible || weeklyPopup.visible || weeklyStartPopup.visible
        enabled: dailyPopup.visible || weeklyPopup.visible || weeklyStartPopup.visible
        onClicked: {
            dailyPopup.visible = false
            weeklyPopup.visible = false
            weeklyStartPopup.visible = false
        }
    }
}
