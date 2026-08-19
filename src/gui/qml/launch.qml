import QtQuick
import OneDragonHelper 1.0

// 启动胶囊（▶ 启动脚本 + ≡ 配置），由 main.qml 的 Loader 加载。
Rectangle {
    anchors.fill: parent
    radius: 32
    color: launchCapsule.containsMouse ? "#35A2F5" : "#2196F3"

    // 左 ▶ 圆
    Rectangle {
        x: 4; y: 4; width: 56; height: 56; radius: 28
        color: "#0F2A4D"
        Text { anchors.centerIn: parent; text: "▶"; color: "#FFFFFF"; font.pixelSize: 30 }
    }
    // 中间文字
    Text {
        x: 60; y: 0; width: 96; height: 64
        text: "启动脚本"; color: "#FFFFFF"
        font.pixelSize: 18; font.weight: Font.Bold
        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
    }
    MouseArea {
        id: launchCapsule; anchors.fill: parent; hoverEnabled: true
        onClicked: Bridge.launchScript()
    }
    // 右侧 ≡ 配置圆（点击打开当前脚本配置弹窗）
    Rectangle {
        x: 156; y: 4; width: 56; height: 56; radius: 28
        color: cfgBtn.containsMouse ? "#0F3A6B" : "#0F2A4D"
        Text { anchors.centerIn: parent; text: "≡"; color: "#FFFFFF"; font.pixelSize: 30 }
        MouseArea {
            id: cfgBtn; anchors.fill: parent; hoverEnabled: true
            onClicked: Bridge.configCurrent()
        }
    }
}
