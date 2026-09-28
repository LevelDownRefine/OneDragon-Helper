# 视频测试夹具

`wallpaper.mp4` 是 FFmpeg `testsrc2`/`sine` 生成的 96×64、10 fps、0.6 秒 H.264/AAC 文件，
没有用户媒体或第三方画面。测试覆盖 RGB 颜色、时间戳、音轨关闭、循环和文件释放。
FFmpeg 仅用于生成此提交的静态夹具，不是构建或运行依赖：

```text
ffmpeg -f lavfi -i testsrc2=size=96x64:rate=10:duration=0.6 -f lavfi -i sine=frequency=1000:sample_rate=44100:duration=0.6 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest -movflags +faststart wallpaper.mp4
ffmpeg -f lavfi -i color=red:size=2400x80:rate=1:duration=1 -c:v libx264 -pix_fmt yuv420p -an wallpaper-wide.mp4
ffmpeg -display_rotation:v:0 90 -i wallpaper.mp4 -c copy wallpaper-rotated.mp4
```

宽幅/旋转变体分别验证解码阶段缩放至最长边 1920，以及容器方向元数据。
