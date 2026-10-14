# Rust GUI

基于 egui/eframe 的 Windows 界面，与 Qt 前端共用 Python 后端。前端负责绘制、交互、媒体解码和系统打开动作；配置读写、任务适配、备份、计划及更新经无 Qt CLI 调用 AppService。

## 启动与构建

在仓库根目录初始化子模块并执行 `uv sync --frozen`，另需 Rust 1.95+ 和 MSVC 工具链。

```powershell
.launcher-rust.bat
.launcher-rust.bat --demo
.launcher-rust.bat --no-build
```

默认连接当前检出的 Python 后端，操作会写入真实配置。`--demo` 使用临时数据；`--no-build` 复用已有二进制。也可运行 `python tools/run_rust_gui.py`，其余参数见 `--help`。

完整 Windows 安装包：

```powershell
.deploy\build-rust.bat
```

输出 `deploy/dist/rust/OneDragon-Helper-Rust.zip`，包含 GUI、CLI、Runner、Updater 和资源。解压到独立安装目录使用；构建目录不应用作日常安装。构建选项、发布流程见 [工具指南](../tools/README.md)，检查命令见 [测试指南](../docs/TESTING.md)。

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `src/main_window.rs`、`src/controllers/`、`src/dialogs/` | 窗口、交互状态与业务入口 |
| `src/backend.rs`、`src/model.rs` | CLI 会话、请求响应与展示数据 |
| `src/runtime.rs` | 独立运行进程及生命周期 |
| 渲染与 Windows 平台模块 | 背景、图标、媒体和系统集成 |

任务卡、脚本配置、运行、设置、计划、备份恢复和更新均通过 [CLI 协议](../docs/rust-feasibility/headless-cli.md) 完成。前端不读取外部脚本配置，也不复制后端适配规则。

- 一个 GUI 复用一个 JSON-RPC stdio 子进程，业务请求不阻塞绘制线程。
- 写入成功后另行刷新；刷新或连接失败不自动重放写请求。切换脚本后丢弃迟到响应。
- 手动勾选只存内存，重启全选；每日计划对所有脚本生效。
- 拖入文件只添加脚本，显式运行时才启动。运行链使用独立进程，关闭 GUI 不终止已交付的运行。
- 关闭窗口时关闭 CLI stdin，等待 300 ms 后终止仍存活的 CLI 子进程；不保证终止其进程树。

## 图形与媒体

Windows 使用 wgpu Direct3D 12 + FXC，支持硬件设备和系统 WARP 软件设备；设置 `ODH_FORCE_SOFTWARE_RENDERING=1` 可强制 WARP 诊断。其他平台使用 Glow。Windows 默认加载微软雅黑，其他环境可通过 `--font` 指定中文字体。

视频背景由 Windows Media Foundation 解码，静音循环播放；解码线程只保留最新帧，最长边限制为 1920。Rust 上传帧到 GPU 绘制，Python 负责缓存写盘。运行时不依赖 FFmpeg，格式支持取决于系统解码器。

源码截图诊断：

```powershell
python tools/run_rust_gui.py --demo --capture rust-gui-preview.png
```

截图模式等待任务卡绘制后退出，并跳过自动运行。完整包也支持 `--capture`。

## 开发参考

- [CLI 协议与生命周期](../docs/rust-feasibility/headless-cli.md)
- [测试与 Windows EXE 验证](../docs/TESTING.md)
- [测试夹具生成](tests/fixtures/README.md)
- [2026-09-28 体积与启动测量](../docs/rust-feasibility/assessment.md)：历史样本，不代表当前版本指标。
