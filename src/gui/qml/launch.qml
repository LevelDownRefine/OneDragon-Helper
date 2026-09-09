import QtQuick
import OneDragonHelper 1.0
import "Theme.js" as Theme

// 当前脚本主操作与配置入口，共用一个按钮组。
Item {
    anchors.fill: parent
    Rectangle {
        anchors.fill: parent
        radius: 18
        color: launchMouse.containsMouse ? Theme.primaryHover : Theme.primary
        border.width: 1
        border.color: launchMouse.containsMouse ? Theme.accent : Theme.border
        Behavior on color { ColorAnimation { duration: 140 } }
    }
    Item {
        id: launchAction
        objectName: "launchScriptButton"
        width: parent.width - 56; height: parent.height
        Image {
            x: 16; anchors.verticalCenter: parent.verticalCenter
            width: 32; height: 32
            source: "image://uiicon/play"; fillMode: Image.PreserveAspectFit
        }
        Text {
            x: 54; anchors.verticalCenter: parent.verticalCenter
            text: "启动脚本"; color: Theme.text
            font.pixelSize: 17; font.weight: Font.DemiBold
        }
        MouseArea {
            id: launchMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: Bridge.launchScript()
        }
    }
    Rectangle {
        x: launchAction.width; y: 16; width: 1; height: parent.height - 32
        color: Theme.border
    }
    Rectangle {
        objectName: "scriptSettingsButton"
        x: launchAction.width + 6; y: 6
        width: 44; height: parent.height - 12; radius: 12
        color: configMouse.containsMouse ? Theme.primaryHover : "transparent"
        Behavior on color { ColorAnimation { duration: 140 } }
        Image {
            anchors.centerIn: parent; width: 28; height: 28
            source: "image://uiicon/settings"; fillMode: Image.PreserveAspectFit
        }
        MouseArea {
            id: configMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: Bridge.configCurrent()
        }
    }
}
