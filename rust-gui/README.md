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

Windows 可双击根目录 `launcher-rust.bat`，使用当前配置构建并启动。
启动器优先使用已激活环境，其次查找仓库及上级目录中的 `.venv`（兼容 worktree），
最后使用 PATH 中的 Python；失败保留窗口和错误信息。
在终端运行 `launcher-rust.bat --demo` 可使用临时演示配置，
加 `--no-build` 可跳过构建；其余参数转交给下面的 Python 入口。

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
- 右下齿轮打开单脚本配置：名称、路径/文件选择、运行类型/参数/完成检测、关闭行为、
  游戏进程/路径、七日超时和原生任务开关。保存经 CLI 调用原有 service 流程，
  仅路径或标识变化时初始化。取消不写入；部分失败或断连保留草稿、要求重新读取，
  不自动重放保存。原生文件选择当前支持 Windows，其他系统可粘贴路径。
- 左下方格切换手动选择，气泡支持全选、清空、添加脚本/快捷方式；勾选只保存在内存，
  不影响每日计划，重启恢复全选。图标拖到另一图标可重排；拖到左下“删除”区弹出确认，
  只移除助手条目和每周设置，保留脚本文件，且至少保留一个脚本。
  添加前校验文件，复用 Python 快捷方式解析；添加不会运行脚本，过期排序会被拒绝并刷新。

- 右下按钮可启动当前脚本，右侧游戏按钮可启动游戏；Python 脚本走现有 Runner CLI，
  external 脚本/游戏走系统关联。路径缺失和启动失败有提示，Python 子进程异常退出会提示查看日志。
  GUI 退出会释放后端，但保留已启动脚本；单独启动沿用原版语义，不应用批量运行参数和前后动作。

- 左下启动按钮确认运行手动勾选的脚本，显示无效配置提示，支持运行前关闭残留进程/静音、
  失败重跑、邮件通知与恢复声音。取消不保存、不启动；部分失败保留草稿，要求重新读取。
  确认后保存选项，通过独立无 Qt Python 进程调度，stdin 传参数、不在命令行暴露凭据。
  运行控制台和日志沿用原编排；GUI 关闭后继续运行。自动关机已接独立 Rust 倒计时，
  整个链及重跑、邮件、恢复声音结束后才出现；关闭主窗口也可弹出。取消/Esc/关窗不关机，
  入口失效、初始化失败或异常退出按取消处理；延迟 0 保留原语义（不触发）。

- 右上齿轮接通全局配置和独立运行选项保存，取消不写入。嵌套保存运行选项保留尚未提交的
  启动设置草稿；部分失败需要重新读取。自动启动在任务卡就绪后显示倒计时，只尝试一次；
  取消/Esc/关窗不启动，确认后读取上次运行选项、不再弹手动确认或重新保存。
  每日计划开启时、`--after-update` 重启、演示及截图模式跳过自动启动。

每日计划编辑、备份、更新、
壁纸切换与视频还未迁移。占位入口在悬停时提示，
点击后显示说明；这些操作继续通过原版助手使用。脚本图标目前统一使用静态默认图标，
尚未提取各 EXE 的图标。此原型仍需源码和 Python 环境，不是发布包替代品。

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

脚本配置批次验证：Rust 20 项通过；Ubuntu Python 1165 项（1131 通过、34 项原有跳过，78.353 秒）。
覆盖完整表单预校验、保存顺序/旧快照、改名落盘、取消、断连与部分失败不重放。
Windows 实际窗口的配置弹窗已截图检查；`launcher-rust.bat --help` 验证参数透传与中文输出。
开发用 capture 构建可加 `--capture-editor` 截取配置弹窗，截图会等待界面淡入完成。

列表批次验证：Rust 23 项；Ubuntu Python 1171 项（1137 通过、34 项原有跳过）。
覆盖无 Qt 添加/排序/删除、拒绝过期排序/重复 EXE/最后一个脚本、保留文件与清理每周设置，
以及真实指针拖拽、手动勾选不发业务请求、取消不保存；Windows 实际截图检查控制气泡。
开发用 capture 构建可加 `--capture-list` 展开手动选择菜单。

单独启动批次验证：Rust 26 项；Ubuntu Python 1175 项（1141 通过、34 项原有跳过，86.766 秒）。
检查无 Qt 目标解析、Runner 命令/环境差量、中文及特殊字符参数，使用临时假脚本验证
进程启动和 GUI 释放后继续执行。BAT 完整构建/启动/截图通过；未启动真实游戏或用户脚本。

批量运行批次验证：Rust 30 项；Ubuntu Python 1183 项（1149 通过、34 项原有跳过，90.343 秒）。
覆盖选择范围、完整选项验证、无效脚本确认、保存失败不启动、独立无 Qt worker 与运行锁，
以及参数经 stdin 到达子进程并关闭管道。Windows 新控制台输出绑定用隔离调度回调验证；
实际确认窗截图已检查。未运行真实任务、发送邮件或执行系统前后动作。
开发用 capture 构建可加 `--capture-run` 截取批量确认窗。

关机确认批次：独立 Rust 入口不要求项目目录或 Python 后端；中文字体缺失也按失败取消。
Windows 实际 EXE 已验证倒计时返回确认码、无效参数失败，以及截图模式关闭返回取消码；
Rust 窗口本身不执行关机命令。Python 适配器和无 Qt worker 测试使用模拟进程，未执行真实关机。

本批 Rust 32 项通过；Ubuntu Python 1186 项（1152 通过、34 项原有跳过，97.476 秒），
Ruff、rustfmt、严格 Clippy（含非 capture 构建）通过。

全局设置批次覆盖无 Qt 保存/反读、自动启动只读原配置、不在服务进程启动任务，
以及嵌套表单草稿、Esc 取消、每日计划抑制与启动查询失败不重试。Windows 实际设置窗已截图检查。
开发用 capture 构建可加 `--capture-settings`；此模式不会自动运行任务。

本批 Rust 35 项通过；Ubuntu Python 1189 项（1155 通过、34 项原有跳过，95.511 秒），
Ruff、rustfmt、严格 Clippy 通过。
