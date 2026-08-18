import QtQuick
import OneDragonHelper 1.0

// 任务调度卡（日常副本 / 周常周几）：复刻旧 src/gui/task_card.py 的视觉与行为契约。
// 数据经 Bridge 暴露：taskTitle / taskAdapted / weeklySupported / dailyDungeonText /
// weeklyStartLabel / masterOn / dailyOn / weeklyOn / dungeonOptions；
// 写回经 selectDungeon / selectWeekly / toggleMaster / toggleWeekly
// （dungeon/sequence/weekly_start 持久化到 gui_state.json；开关内存态）。
//
// 布局严格按旧版固定坐标（标题 y=18 / 分隔线 y=56 / 日常 y=68 / 周常 y=134），
// 只用 visible 切显隐、绝不动态改行 y —— 旧版 _set_task_rows_visible 就是这么做的，
// 因此日常/周常行不可能错位。
//
// 显隐规则（对齐旧 _set_task_rows_visible / _refresh_weekly_chip）：
// - taskAdapted 为假 → 仅显示标题，隐藏分隔线/两行（卡片收缩）。
// - 周常行：weeklySupported 为真才亮蓝可点；否则整行置灰、chip 写「未支持」、开关禁用。
//
// 下拉用纯 QML 自绘（不引 QtQuick.Controls 的 Menu 组件类型）：项目早期在
// 自定义 .qml 组件类型解析上有非确定失败（Type unavailable），自绘更稳。
Item {
    id: cardRoot
    width: 480
    // 高度随适配态：适配 210（两行）/ 未适配 84（仅标题）
    height: Bridge.taskAdapted ? 210 : 84

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
            Text { anchors.centerIn: parent; text: "▶"; color: "#1A1A1A"; font.pixelSize: 16 }
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

    // ── 日常行（固定 y=68，对齐旧 _task_row 坐标）──
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
            x: 58; y: 15; width: 60; height: 26
            text: "日常"; color: "#FFFFFF"; font.pixelSize: 15; font.weight: Font.DemiBold
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
                        weeklyPopup.visible = false
                    }
                }
            }
        }
        // 日常开关（镜像总开关；点击即切总开关，对齐旧 daily_toggle 不独立接线）
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

    // ── 周常行（固定 y=134；不支持时整行置灰，对齐旧 _refresh_weekly_chip）──
    Item {
        id: weeklyRow
        x: 20; y: 134; width: 440; height: 56
        visible: Bridge.taskAdapted
        property bool supported: Bridge.weeklySupported
        Rectangle {
            x: 12; y: 10; width: 36; height: 36; radius: 10
            color: weeklyRow.supported ? "#1A3A7A" : "#2A3040"
            Text {
                anchors.centerIn: parent; text: "📅"
                color: weeklyRow.supported ? "#7DA8FF" : "#4A5568"; font.pixelSize: 16
            }
        }
        Text {
            x: 58; y: 15; width: 60; height: 26
            text: "周常"
            color: weeklyRow.supported ? "#7DA8FF" : "#4A5568"
            font.pixelSize: 15; font.weight: Font.DemiBold
        }
        Rectangle {
            id: weeklyChip
            x: 130; y: 15; width: 120; height: 26; radius: 13
            color: weeklyRow.supported ? "#0F1A2E" : "#1A2028"
            border.width: 1
            border.color: weeklyRow.supported ? "#33517A" : "#2A3850"
            Text {
                anchors.centerIn: parent
                text: weeklyRow.supported ? Bridge.weeklyStartLabel : "未支持"
                color: weeklyRow.supported ? "#7DA8FF" : "#4A5568"; font.pixelSize: 11
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                enabled: weeklyRow.supported
                onClicked: {
                    weeklyPopup.visible = !weeklyPopup.visible
                    dungeonPopup.visible = false
                }
            }
        }
        // 周常开关（内存态，由 toggleMaster / selectWeekly 置位；不支持时禁用置灰）
        Item {
            id: weeklyToggle
            x: 388; y: 17; width: 40; height: 22
            property bool on: Bridge.weeklyOn
            Rectangle {
                anchors.fill: parent; radius: 11
                color: !weeklyRow.supported ? "#2A3040"
                     : (weeklyToggle.on ? "#2196F3" : "#2A3850")
            }
            Rectangle {
                x: weeklyToggle.on ? 20 : 2; y: 2; width: 18; height: 18; radius: 9
                color: "#FFFFFF"
                Behavior on x { NumberAnimation { duration: 120 } }
            }
            MouseArea {
                anchors.fill: parent
                enabled: weeklyRow.supported
                onClicked: Bridge.toggleWeekly(!weeklyToggle.on)
            }
        }
    }

    // ── 日常副本下拉（多级级联：一级副本 → 二级序列，对齐旧 QMenu 子菜单）──
    // 左列列一级副本；带二级项的行 hover 即在右列展开序列（仿原生子菜单弹出），
    // 既支持「副本→序列」两级，也兼容纯一级副本（点击即选）。
    //
    // 宽度按内容自适应（仿旧 QMenu 自动按最长项撑开，不再截断长副本名），
    // 内容过高则 Flickable 内部滚动（仿旧 QMenu 超长滚动）。
    Item {
        id: dungeonPopup
        z: 100
        visible: false
        x: dailyChip.x
        y: dailyRow.y + 56 + 4
        // 宽高随内容：宽 = 左列 +（右列出现时）+ 内边距，封顶 440 避免出屏；
        // 高 = 内容高度封顶 380，超出由 Flickable 滚动。
        property int contentW: dungeonList.implicitWidth
                               + (seqList.visible ? popupRow.spacing + seqList.implicitWidth : 0)
        width: Math.min(contentW + 8, 440)
        height: Math.min(popupRow.implicitHeight, 380) + 8

        Rectangle {
            anchors.fill: parent; radius: 10
            color: "#0F1A2E"; border.width: 1; border.color: "#33517A"
        }
        Flickable {
            id: popupFlick
            x: 4; y: 4
            width: parent.width - 8
            height: parent.height - 8
            contentWidth: popupRow.implicitWidth
            contentHeight: popupRow.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Row {
                id: popupRow
                spacing: 4
                // 左列：一级副本（宽随最长项自适应；TextMetrics 量字宽）
                Column {
                    id: dungeonList
                    spacing: 2
                    Repeater {
                        model: dungeonPopup.visible ? Bridge.dungeonOptions : []
                        Rectangle {
                            property int padL: 10
                            property int padR: 18
                            TextMetrics { id: optTm; font.pixelSize: 13; text: modelData.name }
                            implicitWidth: optTm.width + padL + padR
                            width: implicitWidth
                            implicitHeight: 30
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
                            // 有二级序列的副本标注 ▸，提示有子菜单
                            Text {
                                anchors.right: parent.right; rightPadding: 6
                                anchors.verticalCenter: parent.verticalCenter
                                text: "▸"; color: "#7DA8FF"; font.pixelSize: 12
                                visible: modelData.sequences.length > 0
                            }
                            MouseArea {
                                id: optMouse; anchors.fill: parent; hoverEnabled: true
                                onEntered: {
                                    // 进入带子项副本 → 展开右列；进入叶子副本 → 收起右列
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
                // 右列：二级序列（仅当选中带子项的一级副本时出现）
                Column {
                    id: seqList
                    spacing: 2
                    visible: dungeonPopup.selName !== "" && dungeonPopup.selSequences.length > 0
                    Repeater {
                        model: dungeonPopup.selSequences
                        Rectangle {
                            TextMetrics { id: seqTm; font.pixelSize: 13; text: modelData.label }
                            implicitWidth: seqTm.width + 20
                            width: implicitWidth
                            implicitHeight: 30
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

        property string selName: ""
        property var selSequences: []
        onSelNameChanged: {
            selSequences = []
            for (var i = 0; i < Bridge.dungeonOptions.length; i++) {
                if (Bridge.dungeonOptions[i].name === selName) {
                    selSequences = Bridge.dungeonOptions[i].sequences
                    break
                }
            }
        }
        onVisibleChanged: {
            if (!visible) {
                selName = ""
                selSequences = []
            }
        }
    }

    // ── 周常周几下拉 ──
    Item {
        id: weeklyPopup
        z: 100
        visible: false
        x: weeklyChip.x
        y: weeklyRow.y + 56 + 4
        width: 160
        property int todayDay: (new Date().getDay() + 6) % 7 + 1  // 周一=1..周日=7
        height: weeklyList.height + 8

        Rectangle { anchors.fill: parent; radius: 10; color: "#0F1A2E"; border.width: 1; border.color: "#33517A" }
        Column {
            id: weeklyList
            x: 4; y: 4; width: parent.width - 8; spacing: 2
            Repeater {
                model: weeklyPopup.visible ? [1, 2, 3, 4, 5, 6, 7] : []
                Rectangle {
                    width: weeklyList.width; height: 30; radius: 6
                    color: wMouse.containsMouse ? "#1A3A7A" : "transparent"
                    Text {
                        anchors.fill: parent; leftPadding: 10
                        verticalAlignment: Text.AlignVCenter
                        text: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][modelData - 1]
                              + (modelData === weeklyPopup.todayDay ? "（今天）" : "")
                        color: "#FFFFFF"; font.pixelSize: 13
                    }
                    MouseArea {
                        id: wMouse; anchors.fill: parent; hoverEnabled: true
                        onClicked: { Bridge.selectWeekly(modelData); weeklyPopup.visible = false }
                    }
                }
            }
        }

    // ── 点击空白处关闭下拉（对齐旧 QMenu：弹窗外任意点击即关闭）──
    // 全窗透明捕获层，仅当任一弹窗打开时激活；位于弹窗(z:100)之下、卡片内容(z:0)之上，
    // 故「弹窗内」点击由弹窗自身处理，「弹窗外」点击被本层拦截并关闭两个弹窗。
    MouseArea {
        id: popupCatcher
        x: -128; y: -392; width: 1280; height: 720
        z: 99
        visible: dungeonPopup.visible || weeklyPopup.visible
        enabled: dungeonPopup.visible || weeklyPopup.visible
        onClicked: {
            dungeonPopup.visible = false
            weeklyPopup.visible = false
        }
    }
}
