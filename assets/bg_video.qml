import QtQuick
import QtMultimedia

// OneDragon-Helper 背景视频场景：VideoOutput 全画布 cover 裁剪循环播放。
// 视频作为场景图节点，与上层 UI 同一渲染管线 GPU 合成——不像 QVideoWidget
// 走系统 Overlay（Windows 上必盖住 UI），不会遮挡半透明控件。
Item {
    id: root

    // C++ 侧写入：本地视频的 file:// URL（空串 = 停止）
    property string sourceUrl: ""

    // 媒体错误上报（错误文案），C++ 侧连接后告警并回退渐变
    signal mediaError(string reason)

    MediaPlayer {
        id: player
        source: root.sourceUrl
        videoOutput: videoOutput
        autoPlay: true
        loops: MediaPlayer.Infinite
        onErrorOccurred: (error, errorString) => {
            root.mediaError(errorString || "媒体解码错误")
        }
    }

    VideoOutput {
        id: videoOutput
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }
}
