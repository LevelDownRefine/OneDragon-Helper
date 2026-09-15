import QtQuick
import QtMultimedia
import OneDragonHelper 1.0

// 视频背景组件：由 main.qml 的 Loader 按文件路径懒加载。
// QtMultimedia 依赖隔离在本文件——MediaPlayer 类型注册在部分环境/进程下
// 不稳定，若在本文件内失效，仅视频层不可用（main.qml 本体不受影响）。
Item {
    id: videoBg
    anchors.fill: parent
    property url backgroundUrl
    property int backgroundVersion
    property bool frameReady: false

    MediaPlayer {
        id: player
        objectName: "wallpaperPlayer"
        videoOutput: output
        source: videoBg.backgroundUrl
        loops: MediaPlayer.Infinite
        onErrorOccurred: (error, errorString) => {
            if (Bridge.backgroundMode === "video"
                    && Bridge.backgroundVersion === videoBg.backgroundVersion)
                Bridge.videoError(errorString)
        }
    }

    VideoOutput {
        id: output
        objectName: "wallpaperVideoOutput"
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    Connections {
        target: output.videoSink
        enabled: !videoBg.frameReady
        function onVideoFrameChanged() {
            videoBg.frameReady = Bridge.videoFrameReady(
                output.videoSink, videoBg.backgroundVersion)
        }
    }

    // 源就绪 500ms 后再 play，避开窗口显示阶段（避免启动即解码卡 UI）
    Timer {
        id: startTimer
        objectName: "wallpaperStartTimer"
        interval: 500
        repeat: false
        running: true
        onTriggered: player.play()
    }
}
