import QtQuick
import QtMultimedia
import OneDragonHelper 1.0

// 视频背景组件：由 main.qml 的 Loader 按文件路径懒加载。
// QtMultimedia 依赖隔离在本文件——MediaPlayer 类型注册在部分环境/进程下
// 不稳定，若在本文件内失效，仅视频层不可用（main.qml 本体不受影响）。
Item {
    id: videoBg
    anchors.fill: parent

    MediaPlayer {
        id: player
        videoOutput: output
        source: Bridge.backgroundMode === "video" ? Bridge.backgroundUrl : ""
        loops: MediaPlayer.Infinite
        onErrorOccurred: (error, errorString) => Bridge.videoError(errorString)
        onSourceChanged: {
            if (source !== "") {
                console.log("[bg] video source set:", source)
                startTimer.restart()
            }
        }
    }

    VideoOutput {
        id: output
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    // 源就绪 500ms 后再 play，避开窗口显示阶段（避免启动即解码卡 UI）
    Timer {
        id: startTimer
        interval: 500
        repeat: false
        onTriggered: {
            console.log("[bg] starting video playback")
            player.play()
        }
    }
}
