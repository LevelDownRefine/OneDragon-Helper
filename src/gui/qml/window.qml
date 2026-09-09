import QtQuick
import OneDragonHelper 1.0

// 窗口控制栏（恢复 / 备份 / 最小化 / 关闭），由 main.qml 的 Loader 加载。
Item {
    anchors.fill: parent

    // 恢复配置（选一个备份 zip 还原；已设置的游戏路径保留现值）
    Rectangle {
        x: 0; y: 0; width: 36; height: 36; radius: 12
        color: restoreBtnMouse.containsMouse ? "#2B3A52" : "#1F2937"
        Image {
            anchors.centerIn: parent; width: 22; height: 22
            source: "image://uiicon/restore"; fillMode: Image.PreserveAspectFit
        }
        MouseArea {
            id: restoreBtnMouse; anchors.fill: parent; hoverEnabled: true
            onClicked: Bridge.restoreConfig()
        }
    }
    // 备份配置（一键打包自身与子脚本 config）
    Rectangle {
        x: 40; y: 0; width: 36; height: 36; radius: 12
        color: backupBtnMouse.containsMouse ? "#2B3A52" : "#1F2937"
        Image {
            anchors.centerIn: parent; width: 22; height: 22
            source: "image://uiicon/backup"; fillMode: Image.PreserveAspectFit
        }
        MouseArea {
            id: backupBtnMouse; anchors.fill: parent; hoverEnabled: true
            onClicked: Bridge.backupConfig()
        }
    }
    // 最小化
    Rectangle {
        x: 80; y: 0; width: 36; height: 36; radius: 12
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
        x: 120; y: 0; width: 36; height: 36; radius: 12
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
