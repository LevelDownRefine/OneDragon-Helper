# Rust 任务卡原型

分支 `codex/rust-gui-prototype`，已 rebase 到 `main@1573bfc`；main 已包含无 Qt CLI（[#101](https://github.com/LevelDownRefine/OneDragon-Helper/pull/101)）。
分支依赖与后续功能顺序见 [渐进迁移计划](../docs/rust-feasibility/migration-plan.md)。
Rust 负责窗口、列表、任务卡和进程通信；现有 Python `src.headless` 负责全部配置业务。
当前已按原 GUI 对齐主窗口布局与任务卡交互，并接通工具栏资源跳转。
未迁移入口保留并标注“暂不可用”。
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

- 1280×720 逻辑像素的无边框圆角窗口，复用默认壁纸、配色、左侧图标栏、
  左下任务卡、右侧工具栏和底部启动区；支持拖动空白区域、最小化与关闭。
- 脚本切换、日常两级菜单、日常启用开关、周常选项和起始日；菜单来自 CLI。
  鼠标悬停展开子选项，两列可独立滚动，菜单在空间不足时向上展开；日常“不启用”
  恢复到菜单末项，周常“周几起”保留在任务卡内。
- 一个常驻 `serve --stdio` 子进程；UTF-8 JSONL，不开端口，不拼接 shell 命令。
- 请求在工作线程处理，等待时显示状态并禁用编辑/切换；写操作收到 `result:null` 后
  单独请求 `script.view` 回显。刷新失败提示“已保存，但刷新失败”，不会重放写操作。
  子选项保留 JSON 的整数、布尔、字符串类型；未设置与不启用分别呈现。
- 超时、坏响应或子进程退出会清空任务卡；手动刷新重连，不自动重放写操作。
  部分写入失败时自动反读，保留失败提示；点击左上预览标记打开诊断窗口，
  显示 PID 和有界 stderr 尾部。
- 正常退出关闭 stdin，等待 300 ms，必要时终止并回收自己启动的 CLI。强制杀死 GUI
  的进程树托管尚未实现。Python 会话仍持有现有更新租约。
- 界面不直接读写游戏配置；初始化沿用 main 的实现（#104），不在 Rust 重做。
- 工具栏可打开游戏官网、B 站、GitHub、脚本目录、运行日志目录和脚本配置文件。
  Python 解析声明与路径，Rust 在工作线程调用系统关联程序；缺资源和打开失败会提示。
  Windows 使用 `ShellExecuteW`，不经过命令 shell；配置文件打开沿用原版的系统关联行为。

启动脚本/游戏、计划、脚本增删/路径配置、设置弹窗、备份、更新、
壁纸切换与视频还未迁移。启动按钮直接显示“暂不可用”，其余占位入口在悬停时提示，
点击后显示说明；这些操作继续通过原版助手使用。脚本图标目前统一使用静态默认图标，
尚未提取各 EXE 的图标。此原型不启动外部脚本，不是发布包替代品。

尺寸与颜色对应 `src/gui/qml/Layout.js`、`Theme.js`，壁纸直接嵌入 `assets/ds.jpg`。
工具栏 PNG 由原 GUI 的 `UiIconProvider` 导出并提交，修改图标源后运行
`python -m tools.export_rust_icons` 更新；这一步需要 Qt，Rust 界面运行时不需要。
`src/view.rs` 负责布局和输入，`src/skin.rs` 负责样式/资源，`src/app.rs` 负责 CLI 状态。

## 体积和启动指标

release 使用 `opt-level=s`、thin LTO、单 codegen unit、strip；依赖锁定在 `Cargo.lock`。
前端不链接 Qt/PySide，不启动 WebView。实际运行仍需要 Python CLI 的解释器、依赖、
源代码和模板；Windows 系统字体与图形驱动也属于外部运行条件。

2026-09-27 本机 Rust 1.97.1 / Windows x64 MSVC 的普通 release EXE 为
**7,384,064 字节（约 7.042 MiB）**，包含默认壁纸、工具栏图标和图片解码支持，
不含开发用 `capture` 功能、Python 后端或系统依赖。比上一版任务卡原型的
6,979,584 字节增加 395 KiB。

不能把这个仅支持任务卡的 EXE 与完整原版包直接做同功能比较，也不能把
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

Rust 交互测试以真实 egui 指针/滚轮事件验证分级菜单的布尔选择、日常禁用、长列表末项
选择与周常 0 值，以及未迁移入口不产生业务请求；另检查菜单不越出窗口。
集成测试使用临时目录与实际 Python CLI，并阻止导入 Qt/GUI；覆盖整数/布尔写入、
外部修改反读、周常开关、同一 PID 复用、错误后继续请求、UTF-8、stderr 大量输出、
超时、坏响应和退出释放更新租约。演示目录生成另有 Python 单元测试。
Python 全套测试仍按 `TESTING.md` 在 Ubuntu 运行。

2026-09-28 rebase 验证：Rust 13 项通过；Ubuntu Python 1155 项中 1121 项通过、34 项按原有规则
跳过（77.846 秒）；Ruff、rustfmt 和严格 Clippy 通过。已运行 Windows 实际窗口并检查
中文显示与任务卡截图。CI 增加 Rust 检查和真实 Python CLI 集成测试。

当前使用 #101 的扁平任务卡响应：日常 `name/task/sequence/enabled/options`、
周常 `name/task/options/start_day`；请求参数仍为 `daily_name`、`weekly_name`。
不依赖 #102 的 Qt CLI 测试模式，也不包含该模式的 Python 客户端和控制器改动。

导航批次验证：Rust 16 项通过；Ubuntu Python 1161 项（1127 通过、34 项原有跳过，83.196 秒）；
Ruff、rustfmt、Clippy 通过。覆盖六个导航按钮的请求、声明/回退、缺失资源、路径字符和无 Qt CLI 查询。
