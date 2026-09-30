import QtQuick
import OneDragonHelper 1.0
import "Theme.js" as Theme

// 窗口控制组；保留纯图标入口。
Rectangle {
    anchors.fill: parent
    radius: 14
    color: Theme.panel
    border.width: 1
    border.color: Theme.border

    Repeater {
        model: [
            { icon: "settings", act: () => Bridge.openConfig() },
            { icon: "min", act: () => Bridge.minimize() },
            { icon: "close", act: () => Bridge.closeWindow() },
        ]
        Rectangle {
            objectName: index === 0 ? "configButton" : "windowButton" + index
            x: 6 + index * 40; y: 6; width: 36; height: 32; radius: 9
            color: buttonMouse.containsMouse
                   ? (index === 2 ? Theme.danger : Theme.hover) : "transparent"
            Behavior on color { ColorAnimation { duration: 120 } }
            Image {
                anchors.centerIn: parent; width: 28; height: 28
                source: "image://uiicon/" + modelData.icon
                fillMode: Image.PreserveAspectFit
            }
            MouseArea {
                id: buttonMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: modelData.act()
            }
        }
    }
}
