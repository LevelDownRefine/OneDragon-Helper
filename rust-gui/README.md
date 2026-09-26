# Rust 任务卡原型

分支 `codex/rust-gui-prototype`，基于 `codex/rust-feasibility` 的 `1e039b7`。
Rust 负责窗口、列表、任务卡和进程通信；现有 Python `src.headless` 负责全部配置业务。
首版选用 [egui / eframe 0.36.2](https://docs.rs/eframe/0.36.2/eframe/)，使用 Glow 渲染器，
用于验证 Rust GUI + Python CLI 的边界和操作体验，尚未决定最终界面框架。

## 直接体验

需要 Rust 1.95+、Windows MSVC 构建工具、项目 Python 环境。先激活项目虚拟环境。
从仓库根目录运行：

```powershell
# 首次会构建 release 程序；使用独立临时配置，关闭窗口后清理。
python tools/run_rust_gui.py --demo

# 后续直接运行已有构建。
python tools/run_rust_gui.py --demo --no-build

# 使用当前仓库真实配置：修改任务卡会写入外部脚本配置。
python tools/run_rust_gui.py --no-build
```

演示包含鸣潮和崩铁：选择鸣潮 → 日常改为“凝素领域 · 梦州-迅刀” → 切到崩铁
更改培养目标 → 切回鸣潮确认保存；周常可切换“周几起”和“不启用”。
演示使用真正的 Python CLI 与适配器，仅源代码、静态声明和生成的假脚本配置被复制到
临时目录；不复制主配置、邮件配置或真实脚本目录。关闭再开演示会重置数据。

也可直接运行 EXE，并显式指定 Python 和项目位置：

```powershell
cargo build --release --locked --manifest-path rust-gui/Cargo.toml
.\rust-gui\target\release\onedragon-rust-gui.exe --project-root . --python .\.venv\Scripts\python.exe
```

默认 Python 选择顺序为已激活的 `VIRTUAL_ENV`、项目 `.venv`、PATH 的 `python`。
中文字体从 Windows 微软雅黑读取；其他系统可用 `--font` 指定本机字体文件。
字体不嵌入 EXE。当前以 Windows 为验证平台，Linux/macOS 窗口兼容性尚未验证。

## 当前范围

- 脚本列表、日常两级菜单、日常启用开关、周常选项和起始日；菜单来自 CLI。
- 一个常驻 `serve --stdio` 子进程；UTF-8 JSONL，不开端口，不拼接 shell 命令。
- 请求在工作线程处理，等待时显示状态并禁用编辑/切换；返回后以真实反读状态更新。
  子选项保留 JSON 的整数、布尔、字符串类型；未设置与不启用分别呈现。
- 超时、坏响应或子进程退出会清空任务卡；手动刷新重连，不自动重放写操作。
  部分写入失败时自动反读，保留失败提示；诊断区显示 PID 和有界 stderr 尾部。
- 正常退出关闭 stdin，等待 300 ms，必要时终止并回收自己启动的 CLI。强制杀死 GUI
  的进程树托管尚未实现。Python 会话仍持有现有更新租约。
- 界面不直接读写游戏配置，也没有修改 `ScriptConfig` 初始化实现；已有 TODO 保留。

启动脚本、计划、脚本增删/路径配置、设置、备份、更新、壁纸和完整原 GUI 还未迁移。
这些功能继续通过原版助手使用。此原型不启动外部脚本，不是发布包替代品。

## 体积和启动指标

release 使用 `opt-level=s`、thin LTO、单 codegen unit、strip；依赖锁定在 `Cargo.lock`。
前端不链接 Qt/PySide，不启动 WebView。实际运行仍需要 Python CLI 的解释器、依赖、
源代码和模板；Windows 系统字体与图形驱动也属于外部运行条件。

2026-09-27 本机 Rust 1.97.1 / Windows x64 MSVC 的普通 release EXE 为
**6,979,584 字节（6.65625 MiB）**，不含开发用 `capture` 功能、Python 后端或系统依赖。

不能把这个仅支持任务卡的 EXE 与 152.17 MiB 的完整原版包直接做同功能比较，也不能把
前端大小称为整个助手的安装大小。当前未构建独立 Python CLI 分发包。

调试日志提供 `first UI callback` 和 `first task ready` 两个进程内耗时；前者是首次
UI 回调，不能冒充显示器首帧或包括进程创建的冷启动时间。原报告的源码 offscreen
首帧与此窗口指标条件不同，暂不据此报告加速百分比。

## 验证

```powershell
cargo fmt --manifest-path rust-gui/Cargo.toml --check
cargo clippy --manifest-path rust-gui/Cargo.toml --locked --all-features --all-targets -- -D warnings
$env:ODH_TEST_PYTHON = (Get-Command python).Source
cargo test --manifest-path rust-gui/Cargo.toml --locked --all-features

# 运行真实窗口、待任务卡加载完成后截图，并正常关闭/回收 CLI。
python tools/run_rust_gui.py --demo --capture rust-gui-preview.png
```

Rust 集成测试使用临时目录与实际 Python CLI，并阻止导入 Qt/GUI；覆盖整数/布尔写入、
外部修改反读、周常开关、同一 PID 复用、错误后继续请求、UTF-8、stderr 大量输出、
超时、坏响应和退出释放更新租约。演示目录生成另有 Python 单元测试。
Python 全套测试仍按 `TESTING.md` 在 Ubuntu 运行。

本次本地验证：Rust 8 项通过；Ubuntu Python 1098 项中 1064 项通过、34 项按原有规则
跳过（63.457 秒）；Ruff、rustfmt 和严格 Clippy 通过。已运行 Windows 实际窗口并检查
中文显示与任务卡截图。CI 增加 Rust 检查和真实 Python CLI 集成测试。
