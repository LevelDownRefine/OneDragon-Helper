import QtQuick
import OneDragonHelper 1.0

// 窗口控制栏（配置 / 最小化 / 关闭），由 main.qml 的 Loader 加载。
Item {
    anchors.fill: parent

    // 配置操作入口（备份 / 恢复）
    Rectangle {
        objectName: "configButton"
        x: 0; y: 0; width: 36; height: 36; radius: 12
        color: configBtnMouse.containsMouse ? "#2B3A52" : "#1F2937"
        Image {
            anchors.centerIn: parent; width: 22; height: 22
            source: "image://uiicon/settings"; fillMode: Image.PreserveAspectFit
        }
        MouseArea {
            id: configBtnMouse; anchors.fill: parent; hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: Bridge.openConfig()
        }
    }
    // 最小化
    Rectangle {
        x: 40; y: 0; width: 36; height: 36; radius: 12
        color: minBtnMouse.containsMouse ? "#2B3A52" : "#1F2937"
        Image {
            anchors.centerIn: parent; width: 22; height: 22
            source: "image://uiicon/min"; fillMode: Image.PreserveAspectFit
        }
        MouseArea {
            id: minBtnMouse; anchors.fill: parent; hoverEnabled: true
            onClicked: Bridge.minimize()
        }
    }
    // 关闭
    Rectangle {
        x: 80; y: 0; width: 36; height: 36; radius: 12
        color: closeBtnMouse.containsMouse ? "#2B3A52" : "#1F2937"
        Image {
            anchors.centerIn: parent; width: 22; height: 22
            source: "image://uiicon/close"; fillMode: Image.PreserveAspectFit
        }
        MouseArea {
            id: closeBtnMouse; anchors.fill: parent; hoverEnabled: true
            onClicked: Bridge.closeWindow()
        }
    }
}
