# Rust GUI 预览

总集成分支 `codex/rust-gui-integration`；已同步 main 的脚本管理和资源查询接口。
分支依赖与后续功能顺序见 [渐进迁移计划](../../docs/rust-feasibility/migration-plan.md)。
Rust 负责窗口、列表、任务卡和进程通信；现有 Python `src.headless` 负责全部配置业务。
已接通 Windows 原 GUI 的任务卡、脚本管理、启动、设置、每日计划、备份、壁纸和更新入口。
完整功能边界见下方“当前范围”，同条件发布包对比见[评估报告](../../docs/rust-feasibility/assessment.md)。
支持整窗拖入 `.exe/.bat/.py/.lnk`（每次最多 128 项），逐项调用现有添加接口，
汇总成功、重复、失败与未尝试项；不移动或执行拖入文件。混入不支持的文件时整批拒绝。
弹窗/操作期间忽略新拖入；写入状态不确定时停止余项并刷新，不自动重试。
Windows 撤销 OLE 拖放，按窗口放行 WM_DROPFILES/WM_COPYGLOBALDATA，沿用原版管理员窗口兼容方式。
Windows 左侧提取脚本内嵌图标，失败依次回退 Python 入口图标、内置图标；
悬停“启动游戏”显示 128 逻辑像素的游戏图标（256 像素源），缺失时显示文字。
提取使用 Windows 资源 API，单后台线程、8 项队列、96 项缓存；不调用 Shell 扩展，不执行文件。
刷新列表刷新缓存；移除/重排以路径识别图标，异步旧结果不会覆盖刷新后的图标。
非 Windows 使用内置图标与文字提示。
首版选用 [egui / eframe 0.36.2](https://docs.rs/eframe/0.36.2/eframe/)。Windows 使用
wgpu Direct3D 12，支持系统 WARP 软件渲染；非 Windows 保留 Glow。
主窗口和关机确认窗共用渲染配置，DirectComposition 保留透明圆角；FXC 使用系统组件。
可设 `ODH_FORCE_SOFTWARE_RENDERING=1` 强制 WARP 诊断，不需要额外 DXC/OpenGL 软件 DLL。

## 直接体验

完整 Windows 包可用 `deploy\build-rust.bat` 构建，输出
`deploy/dist/rust/OneDragon-Helper-Rust.zip`。解压到独立目录后双击
`OneDragon-Helper.exe`，无需安装 Python 或 Rust；业务由随附的 CLI 执行。
主程序与原版一样请求管理员权限。构建测试参数和目录保护规则见
[发布工具](../../tools/README.md)。PR 的 Windows 构建任务通过后提供同名 Rust ZIP artifact。

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
cargo build --release --locked --manifest-path src/rust-gui/Cargo.toml
.\src\rust-gui\target\release\onedragon-rust-gui.exe --project-root . --python .\.venv\Scripts\python.exe
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
  仅路径或标识变化时初始化。取消不写入；部分失败或断连保留草稿、要求刷新，
  不自动重放保存。原生文件选择当前支持 Windows，其他系统可粘贴路径。
- 左下方格切换手动选择，气泡支持全选、清空、添加脚本/快捷方式；勾选只保存在内存，
  不影响每日计划，重启恢复全选。图标拖到另一图标可重排；拖到左下“删除”区弹出确认，
  只移除助手条目和每周设置，保留脚本文件，且至少保留一个脚本。
  添加前校验文件，复用 Python 快捷方式解析；添加不会运行脚本，过期排序会被拒绝并刷新。

- 右下按钮可启动当前脚本，右侧游戏按钮可启动游戏；Python 脚本走现有 Runner CLI，
  external 脚本/游戏走系统关联。路径缺失和启动失败有提示，Python 子进程异常退出会提示查看日志。
  GUI 退出会释放后端，但保留已启动脚本；单独启动沿用原版语义，不应用批量运行参数和前后动作。

- 左下启动按钮确认运行手动勾选的脚本，显示无效配置提示，支持运行前关闭残留进程/静音、
  失败重跑、邮件通知与恢复声音。取消不保存、不启动；部分失败保留草稿，要求刷新。
  确认后保存选项，通过独立无 Qt Python 进程调度，stdin 传参数、不在命令行暴露凭据。
  运行控制台和日志沿用原编排；GUI 关闭后继续运行。自动关机已接独立 Rust 倒计时，
  整个链及重跑、邮件、恢复声音结束后才出现；关闭主窗口也可弹出。取消/Esc/关窗不关机，
  入口失效、初始化失败或异常退出按取消处理；延迟 0 保留原语义（不触发）。

- 右上齿轮接通全局配置和独立运行选项保存，取消不写入。嵌套保存运行选项保留尚未提交的
  启动设置草稿；部分失败需要刷新。自动启动在任务卡就绪后显示倒计时，只尝试一次；
  取消/Esc/关窗不启动，确认后读取上次运行选项、不再弹手动确认或重新保存。
  每日计划开启时、`--after-update` 重启、演示及截图模式跳过自动启动。

- 全局配置内可编辑每日计划：时间、开关、独立运行选项与实际系统任务状态。
  对所有脚本生效，暂停保留设置；关闭 GUI 后仍按时执行，需开机并登录，错过不补跑。
  系统任务使用无 Qt `src.headless daily` 入口；保存会检查并修复旧 Qt 入口。
  任务注册成功才写配置，写盘失败恢复原任务 XML；状态读取失败显示未知及错误，不冒充未注册。

- 全局配置内可备份/恢复脚本配置，ZIP 路径可粘贴或用 Windows 文件选择。
  恢复前明确确认覆盖，保留本机游戏路径并生成恢复前 ZIP；结果显示文件数量、跳过脚本和路径。
  长操作在 Python 后台执行，界面轮询短请求，最小化后仍推进；处理中阻止普通关窗和取消。
  失败保留原服务的部分完成与恢复前备份详情，不自动重试；关闭结果窗后刷新任务卡。

- 壁纸按钮可选择 PNG、JPEG、WebP、BMP 或恢复默认；按脚本切换背景，保持比例填满窗口。
  Rust 后台解码并限制内存/尺寸，处理 EXIF 方向，长边超过 1920 的图片生成缩图；
  映射与缓存由 Python service 写盘。旧结果丢弃，损坏缓存回退原图，缺失/损坏原图显示渐变。
  视频可选择 MP4、WebM、MKV、MOV；Windows 系统解码，静音循环，500ms 后开始播放。
  首帧由 CLI 保存为与原版兼容的预览缓存；切换脚本丢弃旧帧，播放失败保留预览/已显示画面并提示。

- 配置中的助手更新可读取本地版本/上次结果、打开发布页面，支持显式检查、版本说明、
  后台下载/校验进度和取消。源码运行沿用原版不支持原位更新的说明；进入弹窗不联网。
  检查与下载只使用 Python 会话保存的对象，取消等待当前网络读取结束，断连不自动重试。
  校验完成后可显式安装并重启；交接中不可取消，收到匹配版本的就绪回执才关闭 GUI/CLI。
  其他任务/窗口、身份不符或超时都会保留当前版本。Rust 使用独立发布包，禁止替换成 Qt 包。
  源码模式仍不可原位安装；完整包的真实双进程更新交接见 `tests/exe/test_update_exe.py`。

开发启动器使用源码和 Python 环境；独立发布包由 `deploy/build-rust.bat` 组装。
原生 EXE 已支持从自身目录识别 Rust `version.json`、`OneDragon-Helper-CLI.exe` 和
`_internal`，直接启动随附后端；不受启动工作目录或已激活 Python 环境影响。
包不完整、类型不符会明确报错，不回退 PATH 中的 Python。Windows 首窗创建前的错误以
原生错误框显示。显式 `--project-root` 保留源码开发模式，`--python` 仅用于源码模式。

尺寸与颜色对应 `src/gui/qml/Layout.js`、`Theme.js`；嵌入 `assets/ds.jpg` 用于初始背景，
加载后使用 CLI 解析的脚本默认/自定义壁纸。
工具栏 PNG 由原 GUI 的 `UiIconProvider` 导出并提交，修改图标源后运行
`python -m tools.export_rust_icons` 更新；这一步需要 Qt，Rust 界面运行时不需要。

## 目录与职责

Rust crate 位于 `src/rust-gui`，源码与 `src/gui` 平级组织；Cargo 显式指定
`main.rs`、`lib.rs`，不再套一层 `src/`。对应原 GUI 的文件按相同职责命名：

| Rust 模块 | 对应 Python GUI | 职责 |
| --- | --- | --- |
| `main_window.rs` | `main_window.py` | 组合窗口、CLI 生命周期、响应分发与跨控制器刷新 |
| `controllers/game_list.rs` | `controllers/game_list.py` | 列表、选中、增删改、排序、拖入和脚本配置事件 |
| `controllers/task_card.rs` | `controllers/task_card.py` | 日常、周常任务卡与选择菜单 |
| `controllers/links.rs` | `controllers/links.py` | 工具栏、资源打开与游戏图标提示 |
| `controllers/launch.rs` | `controllers/launch.py` | 当前/批量启动、运行确认及子进程状态 |
| `controllers/background.rs` | `controllers/background.py` | 背景选择、异步加载、缓存请求与壁纸事件 |
| `controllers/backup.rs` | `controllers/backup.py` | 配置入口、备份恢复及结果处理 |
| `controllers/daily_plan.rs` | `controllers/daily_plan.py` | 每日计划读取、保存与回显 |
| `controllers/update.rs` | `controllers/update.py` | 更新操作事件和异步结果分发 |
| `controllers/window.rs` | `controllers/window.py` | 窗口控制按钮与关闭限制 |
| `dialogs.rs` | `dialogs.py` | 共用弹窗框架、表单控件与单脚本配置 |
| `config_dialog.rs` | `config_dialog.py` | 配置入口和设置草稿 |
| `run_options_editor.rs`、`run_confirm_dialog.rs` | 同名 `.py` | 共用运行选项表单、手动运行确认 |
| `daily_plan_dialog.rs`、`startup_dialog.rs`、`shutdown_dialog.rs`、`update_dialog.rs` | 同名 `.py` | 各自弹窗 |
| `icons.rs`、`file_drop.rs` | 同名 `.py` | 图标资源与缓存、原生文件拖入 |
| `theme.rs` | `qml/Theme.js`、`qml/Layout.js` | 主窗口配色、尺寸与绘制工具 |

egui 没有 QML 层，控制器同时绘制对应区域；`controllers/mod.rs` 保存主画面状态并组合绘制。
控制器通过窗口的统一请求入口调用 CLI，不读写游戏配置。共用弹窗样式在 `dialogs.rs`，
`list_dialog.rs`、`drop_dialog.rs`、`backup_dialog.rs`、`wallpaper_dialog.rs` 只保留各自表单和结果展示。
`backend.rs`、`model.rs`、`runtime.rs`、`rendering.rs`、`file_picker.rs`、`video.rs` 是 Rust 的
协议、启动及平台实现；Python GUI 没有一一对应文件，不为了同名增加转发层。

测试全部位于 `tests/rust-gui`，控制器和 Windows 子模块按源码目录对应；单元测试通过
`#[path]` 作为被测模块的子模块加载，保留私有成员测试，不扩大产品接口。
`backend.rs` 是真实 Python CLI 集成测试，`backend_unit.rs` 验证传输协议；夹具位于 `fixtures/`。

## 体积和启动指标

release 使用 `opt-level=s`、thin LTO、单 codegen unit、strip；依赖锁定在 `Cargo.lock`。
前端不链接 Qt/PySide，不启动 WebView。完整包内含 Python CLI 的解释器、冻结业务模块、
依赖和模板；Windows 系统字体、Direct3D/WARP 与 Media Foundation 属于系统运行条件。
最新完整包与原版的对比见[评估报告](../../docs/rust-feasibility/assessment.md)。以下数字是原型阶段记录。

2026-09-27 本机 Rust 1.97.1 / Windows x64 MSVC 的普通 release EXE 为
**7,384,064 字节（约 7.042 MiB）**，包含默认壁纸、工具栏图标和图片解码支持，
不含开发用 `capture` 功能、Python 后端或系统依赖。比上一版任务卡原型的
6,979,584 字节增加 395 KiB。

不能把这个仅支持任务卡的 EXE 与完整原版包直接做同功能比较，也不能把
前端大小称为整个助手的安装大小；该阶段尚无独立 Python CLI 分发包。

调试日志提供 `first UI callback` 和 `first task ready` 两个进程内耗时；前者是首次
UI 回调，不能冒充显示器首帧或包括进程创建的冷启动时间。原报告的源码 offscreen
首帧与此窗口指标条件不同，暂不据此报告加速百分比。

## 验证

```powershell
cargo fmt --manifest-path src/rust-gui/Cargo.toml --check
cargo clippy --manifest-path src/rust-gui/Cargo.toml --locked --all-features --all-targets -- -D warnings
$env:ODH_TEST_PYTHON = (Get-Command python).Source
cargo test --manifest-path src/rust-gui/Cargo.toml --locked --all-features

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

每日计划批次验证：Rust 36 项；Ubuntu Python 1195 项（1161 通过、34 项原有跳过，92.100 秒）。
Ruff、rustfmt、严格 Clippy 通过。覆盖无 Qt 计划保存/独立执行、全部脚本范围、独立选项、
系统任务入口匹配、XML 回滚、未知状态、暂停与草稿保留。Windows 原生任务查询及界面截图通过；
未注册真实计划，注册/回滚使用模拟 COM。开发用 capture 构建可加 `--capture-plan`。

备份批次用无 Qt 子进程和临时文件验证真实 ZIP 往返、未确认不写盘、恢复前备份，
并验证后台 stdout 不污染协议、并发请求被拒绝、EOF 等待任务期间保持运行租约。
窗口强制结束/系统故障仍可能中断恢复，原服务按文件替换、不承诺整批回滚；应核对备份与日志。
Windows 恢复确认窗截图已检查。开发用 capture 构建可加 `--capture-restore`，只打开表单。

本批 Rust 38 项通过；Ubuntu Python 1199 项（1165 通过、34 项原有跳过，90.755 秒），
Ruff、rustfmt、严格 Clippy 通过。演示/无 Qt 夹具补齐三份静态任务模板，保证全适配器备份扫描。

拖放批次验证：Rust 43 项；Ubuntu Python 1200 项（1166 通过、34 项原有跳过，117.059 秒）。
Ruff、rustfmt、严格 Clippy 通过。真实 Windows 消息窗口验证中文/空格路径、多文件、
忙碌忽略和两种销毁顺序；实际 GUI 在临时目录完成添加与重复提示，结果页截图已检查。
跨权限兼容沿用原版消息过滤方式，尚未手工验证管理员窗口与 Explorer 的鼠标拖拽。
capture 构建可重复传入 `--capture-drop 路径`，会实际添加文件，请仅用于隔离配置。

图标批次验证：Rust 50 项；覆盖真实 Windows 资源提取、透明/半透明像素、缺失文件回退、
缓存上限、刷新期间丢弃旧结果，以及悬停只查询一次、可选查询失败保留任务卡。
Windows 实际窗口的脚本图标与游戏悬停大图已截图检查。capture 构建可加
`--capture-game-icon` 等待预览图就绪后截图（需隔离配置中有可用游戏图标路径）。
Ubuntu Python 1202 项（1168 通过、34 项原有跳过，115.858 秒）；Ruff、rustfmt、严格 Clippy 通过。

图片壁纸批次验证：Rust 57 项；Ubuntu Python 1207 项（1173 通过、34 项原有跳过，119.317 秒）。
覆盖四种图片格式、缩图/缓存回退、源文件不变、缺失/过大图片、旧结果丢弃、Esc 取消，
以及无 Qt 保存/重置、缓存 token 过期和已保存后反读失败不重放。Ruff、rustfmt、严格 Clippy 通过。
缓存通过最大 8 MiB 的请求传输，独立有界写线程保证后端停止读取时仍可超时/关闭；
真实 CLI 测试验证大缓存往返及过期 token 拒绝。capture 构建可加 `--capture-wallpaper`，
等待图片就绪后截取壁纸编辑窗。

视频壁纸批次验证：Rust 64 项通过，包含真实 H.264/AAC 解码、禁用音轨、时间戳、循环、
2400 像素宽视频缩放、方向元数据与颜色、正负行距、坏视频保留预览、退出和切换释放媒体。
Ubuntu Python 1207 项（1173 通过、34 项原有跳过），Ruff、rustfmt、严格 Clippy 通过。
Windows 实窗视频及编辑窗截图已检查，首帧缓存写入且源文件不变；测试媒体均为生成夹具。

平台实现使用 `windows 0.62.2` 的 Media Foundation 绑定，单个解码线程只保留最新待显示帧，
输出最长边 1920，按媒体时间戳播放；没有音频输出设备。正常停止后释放 COM 对象与文件，
若系统解码调用迟迟未返回，界面不等待它，线程返回或进程退出时释放资源。
实际解码能力取决于系统媒体组件与编解码器，Windows N 等缺少媒体组件的系统需安装相应组件；
非 Windows 显示预览与明确不可播放原因。没有附带 FFmpeg/Qt 播放库，也不承诺任意编码均可播放。
原理参考微软 [Source Reader](https://learn.microsoft.com/en-us/windows/win32/medfound/processing-media-data-with-the-source-reader)
与 [高级视频处理](https://learn.microsoft.com/en-us/windows/win32/medfound/mf-source-reader-enable-advanced-video-processing)。

同机、同一 release + capture 配置，本批 EXE 为 8,664,064 字节，图片壁纸基线为
8,614,912 字节，增加 49,152 字节（48 KiB）。这是视频批次对开发截图构建的增量，
不包括 Python 后端和系统媒体组件，也不是完整发布包或与 Qt 的同功能体积比较。

更新检查/下载批次验证：Rust 67 项；Ubuntu Python 1213 项（1179 通过、34 项原有跳过，
312.652 秒）；Ruff、rustfmt、严格 Clippy（含默认构建）通过。覆盖本地只读状态、会话内
发布对象、下载进度、取消/EOF、失败后显式重试、旧任务拒绝、恢复不可取消、Esc 与断连状态。
Windows 实窗源码运行提示已截图检查；`--capture-update` 只打开更新窗，不检查或下载。
网络与下载校验由已有 UpdateService 负责，本批更新流程测试用模拟服务，未更新当前安装。

更新安装交接批次验证：Rust 69 项；Ubuntu Python 1226 项（1192 通过、34 项原有跳过，
411.400 秒），其中更新/锁/无 Qt 会话专项 31 项。Ruff、rustfmt、严格 Clippy 通过。
覆盖 CLI/GUI 路径与创建时间、父子关系、其他任务拒绝、就绪后等待双方、超时不安装，
以及后台安装不可取消、EOF 保持租约、失败保留下载与断连不重放。实际窗口截图用隔离展示
夹具检查“安装并重启”布局，未运行安装器；真实冻结 EXE 双进程升级留给发布批次验证。

独立 CLI 构建验证：Windows 真实 EXE 四项通过，冻结模块检查确认没有 Qt/GUI，
验证直接父子进程关系、异目录启动和运行锁。Ubuntu 全量 1230 项（1192 通过、38 项跳过，
其中新增四项在 Windows 实跑），Ruff 通过。此阶段产物仅含 CLI 与 _internal，
不作为完整 Rust 发布包交付，也不据此推算整体体积或启动加速。

独立前端入口验证：Rust 72 项通过；Ubuntu Python 全量 1230 项（1192 通过、38 项跳过），
Ruff、rustfmt、严格 Clippy 通过。Windows 在临时目录组合真实 Rust EXE/CLI/运行库及生成
配置，从另一个工作目录启动，移除虚拟环境变量并把 PATH 限于 System32，实际窗口与任务卡
已截图验证；程序目录没有 src 源码。未运行外部脚本。UAC、完整发布清单和真实更新安装留给下一批。

原 CLI 参数兼容批次：Rust 主程序在创建窗口前将 `--help/--version/--selftest`、
`--schedule-run` 等交给无 Qt 后端，等待并返回其退出码。结果沿用原 `--out` 或临时目录
文件，直接调用 CLI EXE 也支持这些参数。开发用 `--project-root/--python` 放在业务参数前。
Rust 73 项通过；Ubuntu Python 1235 项（1196 通过、39 项跳过，124.738 秒）；
Windows CLI EXE 五项通过，Ruff、rustfmt、严格 Clippy 通过。临时独立包在无源码和无 Python
PATH 下验证主 EXE 自检、版本、中文输出路径、退出码 1/2，并再次截图检查任务卡。

发布资源批次：`release_package.py prepare --frontend rust` 生成 Rust 类型版本/更新清单，
加入独立 CLI、排除 QML；检查和归档自动识别类型，共用升级夹具保留该类型。
Ubuntu Python 1237 项（1198 通过、39 项跳过，123.989 秒），Ruff 通过；Rust 代码未变。
Windows 临时组装真实四个 EXE 和运行库，127 个发布文件及 ZIP 清单/哈希校验通过。
此步骤未运行带 UAC 的 Runner/Updater，完整构建与管理员 CI 验证继续接入。

完整构建批次：本地生成带管理员 manifest/原图标的 Rust 主程序及独立 CLI、Runner、
Updater、内置资源、ZIP 与校验文件。Windows 七项真实产物检查通过；Ubuntu Python
1242 项（1201 通过、41 项跳过，120.241 秒），Ruff 与 workflow YAML 解析通过。
构建目录保护测试覆盖越界/链接、保留既有用户安装、编译失败不污染其他输出。
本机非管理员，GUI/Runner/Updater 的执行由新增 Windows CI 管理员 job 验证。

双进程 EXE 更新专项使用真实主程序的 `--dump-config --out` 与有界命名管道保持
CLI/主程序存活，验证更新器 ready 后未改旧包、双方自然退出后升级成功且用户文件不变。
窗口点击和 RPC ready 状态仍由既有状态机/无 Qt 会话测试负责。Ubuntu Python 1244 项
（1201 通过、43 项 Windows 专项跳过，138.164 秒），Ruff 通过；本地六项 CLI EXE 测试
通过，包括管道等待期间持有运行锁。管理员双进程测试随本批 Windows CI 执行。
