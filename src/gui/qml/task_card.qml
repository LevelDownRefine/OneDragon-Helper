import QtQuick
import OneDragonHelper 1.0
import "Theme.js" as Theme

// 日常/周常行由 Bridge 提供，选择经 service 写回脚本配置。
// 日常与周常共享滚动区域，菜单以被点击的行定位。
Item {
    id: cardRoot
    objectName: "cardRoot"
    width: 480
    // 副本/周常 chip 水平位置：在标签（58+64）右侧剩余空间内居中，
    // 使选项卡片在横向空白块内左右留白一致。
    readonly property int chipX: 181
    height: Bridge.taskAdapted ? taskRows.y + taskRows.height + (weeklyArea.visible ? 16 : 4) : 84

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

    // 写回会刷新模型并销毁菜单项，后续操作放在稳定的卡片作用域。
    function chooseDaily(optionName, sequence) {
        var dailyName = dailyTaskPopup.dailyName
        dailyTaskPopup.visible = false
        if (dailyTaskPopup.taskType === "weekly")
            Bridge.selectWeeklyTaskOption(dailyName, optionName, sequence)
        else
            Bridge.selectDailyTask(dailyName, optionName, sequence)
    }

    function disableTask() {
        var taskName = dailyTaskPopup.dailyName
        dailyTaskPopup.visible = false
        Bridge.setTaskEnabled(taskName, false)
    }

    function chooseWeekly(optionName) {
        var weeklyName = weeklyTaskPopup.weeklyName
        weeklyTaskPopup.visible = false
        Bridge.selectWeeklyTaskOption(weeklyName, optionName)
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

    Flickable {
        id: taskRows
        objectName: "taskRows"
        x: 0; y: 68; width: parent.width
        height: Math.min(contentHeight, cardRoot.winBottomInCard - y - 16)
        contentHeight: dailyArea.height + (weeklyArea.visible ? weeklyArea.height : 0)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        visible: Bridge.taskAdapted
        onContentYChanged: {
            dailyTaskPopup.visible = false
            weeklyTaskPopup.visible = false
        }
        Column {
            id: dailyArea
            x: 20; width: 440
            Repeater {
                model: Bridge.dailyItems
                Item {
                    id: dailyRow
                    width: 440; height: 56
                    property string dailyName: modelData.name
                    visible: Bridge.taskAdapted
                    Rectangle {
                        x: 12; y: 10; width: 36; height: 36; radius: 10
                        color: Theme.accentSoft
                        Text { anchors.centerIn: parent; text: "日"; color: Theme.accent; font.pixelSize: 13; font.weight: Font.DemiBold }
                    }
                    Text {
                        x: 58; y: 15; width: 112; height: 26
                        text: modelData.display_name; elide: Text.ElideRight; color: Theme.text; font.pixelSize: 14; font.weight: Font.DemiBold
                        verticalAlignment: Text.AlignVCenter
                    }
                    Rectangle {
                        id: dailyChip
                        objectName: "dailyTaskButton"
                        x: cardRoot.chipX; y: 10
                        width: 220
                        height: 36; radius: 10
                        color: dailyMouse.containsMouse ? Theme.hover : Theme.control
                        border.width: 1
                        border.color: dailyTaskPopup.visible && dailyTaskPopup.taskType === "daily" && dailyTaskPopup.dailyName === dailyRow.dailyName ? Theme.accent : Theme.border
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Text {
                            anchors.fill: parent
                            leftPadding: 12; rightPadding: 32
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            text: modelData.selection_label
                            color: Theme.accent; font.pixelSize: 12
                        }
                        Image {
                            anchors.right: parent.right; anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            width: 20; height: 20
                            source: "image://uiicon/chevron_down"
                            rotation: dailyTaskPopup.visible && dailyTaskPopup.taskType === "daily" && dailyTaskPopup.dailyName === dailyRow.dailyName ? 180 : 0
                            opacity: 0.7
                        }
                        MouseArea {
                            id: dailyMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (modelData.options.length === 0) {
                                    Bridge.toastRequested("暂无副本选项")
                                } else {
                                    var wasOpen = dailyTaskPopup.visible && dailyTaskPopup.taskType === "daily" && dailyTaskPopup.dailyName === dailyRow.dailyName
                                    dailyTaskPopup.visible = false
                                    weeklyTaskPopup.visible = false
                                    dailyTaskPopup.taskType = "daily"
                                    dailyTaskPopup.dailyName = dailyRow.dailyName
                                    dailyTaskPopup.options = modelData.options
                                    var rowTop = dailyRow.mapToItem(cardRoot, 0, 0).y
                                    dailyTaskPopup.anchorTop = rowTop
                                    dailyTaskPopup.anchorBottom = rowTop + dailyRow.height
                                    dailyTaskPopup.visible = !wasOpen
                                }
                            }
                        }
                    }
                }
            }
        }

        // ── 周常区（跟随日常列表；不支持周常时隐藏）──
        // 颜色与每日任务行共用同一色板（白标题 / 蓝图标底 / 蓝图标字 / 蓝 chip 字）。
        // 仅列出各周常子项（如「货币战争」「历战余响」），父分类标题已去除；
        // 每行尺寸、图标、文字、chip 的 y 都与「每日任务」行严格对齐，保证视觉统一。
        Item {
            id: weeklyArea
            objectName: "weeklyArea"
            x: 20; y: dailyArea.height; width: 440
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
                        property bool hasOptions: modelData.has_options
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
                            text: modelData.display_name
                            elide: Text.ElideRight
                            color: Theme.text
                            font.pixelSize: 14; font.weight: Font.DemiBold
                            verticalAlignment: Text.AlignVCenter
                        }
                        Rectangle {
                            id: wkChip
                            property bool menuOpen: (weeklyTaskPopup.visible && weeklyTaskPopup.weeklyName === modelData.name)
                                                    || (dailyTaskPopup.visible && dailyTaskPopup.taskType === "weekly" && dailyTaskPopup.dailyName === modelData.name)
                            x: cardRoot.chipX; y: 10
                            width: 220
                            height: 36; radius: 10
                            visible: hasOptions
                            color: weeklyMouse.containsMouse ? Theme.hover : Theme.control
                            border.width: 1
                            border.color: wkChip.menuOpen
                                          ? Theme.accent : Theme.border
                            Behavior on color { ColorAnimation { duration: 140 } }
                            Text {
                                anchors.fill: parent
                                leftPadding: 12; rightPadding: 32
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                text: modelData.selection_label
                                color: Theme.accent
                                font.pixelSize: 12
                            }
                            Image {
                                anchors.right: parent.right; anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                width: 20; height: 20
                                source: "image://uiicon/chevron_down"
                                rotation: wkChip.menuOpen ? 180 : 0
                                opacity: 0.7
                            }
                            MouseArea {
                                id: weeklyMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                enabled: weeklyArea.supported
                                onClicked: {
                                    var wasOpen = wkChip.menuOpen
                                    dailyTaskPopup.visible = false
                                    weeklyTaskPopup.visible = false
                                    if (modelData.options.some(function(option) { return option.options.length > 0 || option.action === "disable" })) {
                                        weeklyTaskPopup.visible = false
                                        dailyTaskPopup.taskType = "weekly"
                                        dailyTaskPopup.dailyName = modelData.name
                                        dailyTaskPopup.options = modelData.options
                                        var nestedTop = weeklyArea.mapToItem(cardRoot, 0, index * weeklyArea.rowH).y
                                        dailyTaskPopup.anchorTop = nestedTop
                                        dailyTaskPopup.anchorBottom = nestedTop + weeklyArea.rowH
                                        dailyTaskPopup.visible = !wasOpen
                                        return
                                    }
                                    weeklyTaskPopup.weeklyName = modelData.name
                                    var rowTop = weeklyArea.mapToItem(cardRoot, 0, index * weeklyArea.rowH).y
                                    weeklyTaskPopup.anchorTop = rowTop
                                    weeklyTaskPopup.anchorBottom = rowTop + weeklyArea.rowH
                                    weeklyTaskPopup.visible = !wasOpen
                                    dailyTaskPopup.visible = false
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Component.onCompleted: Bridge.taskStateChanged.connect(function() {
        dailyTaskPopup.visible = false
        weeklyTaskPopup.visible = false
    })

    // ── 日常副本下拉（多级级联：一级副本 → 二级序列，对齐旧 QMenu 子菜单）──
    // 左列一级副本、右列二级序列，两列各自独立 Flickable 滚动（互不挤压、
    // 长列表都能滑到底），分别解决「二级目录显示不全」与「滚动到头也漏项」。
    // 宽度/高度在 openMenu() 中按下拉内容一次性算定（仅 1 个 TextMetrics，
    // 避免每行测量导致的 hover 重布局抖动 → 卡顿）。
    Item {
        id: dailyTaskPopup
        objectName: "dailyTaskPopup"
        z: 100
        visible: false
        x: 20 + cardRoot.chipX
        y: dailyTaskPopup.popupY
        // 宽度随一级列 +（出现二级列时）；高度封顶避免出屏，超出由各列 Flickable 独立滚动
        width: dailyTaskPopup.rightW > 0
               ? (dailyTaskPopup.leftW + 4 + dailyTaskPopup.rightW + 8)
               : (dailyTaskPopup.leftW + 8)
        height: dailyTaskPopup.popupHeight

        property int leftW: 200
        property int rightW: 0
        property int popupY: anchorBottom + 4
        property string dailyName: ""
        property string taskType: "daily"
        property var options: []
        property int anchorTop: 0
        property int anchorBottom: 0
        property int popupHeight: 360
        property int viewportH: height - 8
        property string selName: ""
        property var selOptions: []

        Rectangle {
            anchors.fill: parent; radius: 10
            color: Theme.control; border.width: 1; border.color: Theme.border
        }

        // 单个复用测量器：仅 openMenu 调用一次，避免每行 TextMetrics 的 hover 抖动
        TextMetrics { id: measTm; font.pixelSize: 13 }

        function openMenu() {
            var opts = dailyTaskPopup.options
            var maxW = 60
            for (var i = 0; i < opts.length; i++) {
                measTm.text = opts[i].name
                if (measTm.width > maxW) maxW = measTm.width
            }
            leftW = Math.min(maxW + 28, 240)
            var geom = cardRoot.placePopup(
                anchorTop, anchorBottom,
                Math.min(opts.length * 32 + 8, 360))
            popupY = geom.y
            popupHeight = geom.h
            selName = ""
            selOptions = []
            rightW = 0
        }

        onSelNameChanged: {
            var opts = dailyTaskPopup.options
            selOptions = []
            for (var i = 0; i < opts.length; i++) {
                if (opts[i].name === selName) {
                    selOptions = opts[i].options
                    break
                }
            }
            rightW = (selOptions.length > 0)
                     ? Math.min(200, 424 - leftW)
                     : 0
        }

        onVisibleChanged: {
            if (visible) openMenu()
            else { selName = ""; selOptions = []; rightW = 0 }
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
                        model: dailyTaskPopup.visible ? dailyTaskPopup.options : []
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
                                visible: modelData.options.length > 0
                            }
                            MouseArea {
                                id: optMouse; anchors.fill: parent; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onEntered: {
                                    dailyTaskPopup.selName = modelData.options.length > 0 ? modelData.name : ""
                                }
                                onClicked: {
                                    if (modelData.action === "disable") {
                                        cardRoot.disableTask()
                                    } else if (modelData.options.length > 0) {
                                        dailyTaskPopup.selName = modelData.name
                                    } else {
                                        cardRoot.chooseDaily(modelData.name, null)
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
                        model: dailyTaskPopup.selOptions
                        Rectangle {
                            width: dailyTaskPopup.rightW
                            height: 30
                            radius: 6
                            color: seqMouse.containsMouse ? Theme.accentSoft : "transparent"
                            Text {
                                anchors.fill: parent; leftPadding: 10
                                verticalAlignment: Text.AlignVCenter
                                text: modelData.name
                                color: Theme.text; font.pixelSize: 13
                            }
                            MouseArea {
                                id: seqMouse; anchors.fill: parent; hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    cardRoot.chooseDaily(dailyTaskPopup.selName, modelData.value)
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
                                cardRoot.chooseWeekly(modelData)
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
