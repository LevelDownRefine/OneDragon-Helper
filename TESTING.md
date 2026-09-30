# TESTING.md — 测试与开发工作流

铁律：改代码前先激活 venv，改完必须跑测试 + ruff。

## 0. 前置：激活环境

```bash
source .venv/Scripts/activate    # bash / git bash
call env.bat                     # cmd，同时设置代理 127.0.0.1:7890
```

未激活环境是最常见的本地能跑、CI 挂或 ImportError 根因。

## 1. 跑测试

```bash
cd <root>
python -m unittest discover -s python-backend/tests -t python-backend -p "test*.py"
python -m unittest discover -s python-gui/tests -t python-gui -p "test*.py"
```

`uv sync` 会把两个 workspace 包以可编辑方式安装，源码与测试不再拼接 `PYTHONPATH`。测试按被测模块和职责归档；GUI 测试开头设 `QT_QPA_PLATFORM=offscreen` 无头跑 PySide6。文件 I/O 使用 mock 或独立临时目录，不读写真实 config 或游戏脚本路径；临时资源用上下文管理器或 `addCleanup` 回收。新增或修改功能后必须补测试并跑全套再交付。

`-t` 将各 Python 子项目作为测试包顶层；两个测试集须分开运行，避免它们同名的 `tests` 包互相遮蔽。子目录须保留 `__init__.py`，否则 unittest 不会递归发现其中的用例。

| 目录 | 归属 |
|---|---|
| `python-gui/tests/gui/` | 控件、控制器、QML、窗口及 GUI 共享夹具 |
| `rust-gui/tests/` | Rust 窗口、同名控制器/弹窗、原生能力与 CLI 通信；由 Cargo 运行 |
| `python-backend/tests/config/` | 配置适配器、声明、日常、周常及 golden 验证 |
| `python-backend/tests/service/` | 配置服务、链生成、调度和运行编排 |
| `python-backend/tests/update/` | 更新包协议、下载服务、运行锁、安装回滚 |
| `python-backend/tests/utils/` | 通用工具、文件读写、路径与系统操作 |
| `python-backend/tests/log/` | 日志解析与邮件通知 |
| `python-backend/tests/tools/` | 选项同步脚本的离线测试 |
| `python-backend/tests/support/` | 跨模块测试辅助代码及其自身测试 |
| `python-backend/tests/exe/` | 后端、Runner、更新器和 Rust 发布产物集成测试 |
| `python-gui/tests/exe/` | Python GUI 发布产物集成测试 |
| `python-backend/tests/fixtures/`、`python-backend/tests/golden/` | 静态夹具与 golden 基线 |

只跑某一 GUI 模块时也指定 Python GUI 项目根，例如：

```bash
python -m unittest discover -s python-gui/tests/gui -t python-gui -p "test*.py"
```

- 参数不同但契约相同的场景用具名 `subTest` 合并，每个场景保留独立输入和完整断言；不同失败原因或不同层次的集成测试单独保留。
- 共享夹具放非 `test_*.py` 模块，不从另一个测试文件导入。`python-gui/tests/gui/helpers.py` 提供 `get_app()` 和 `make_bridge()`；使用 Qt 图像或窗口前显式创建应用，不依赖导入副作用。
- 缓存测试使用隔离的注册表并恢复原状态；需要已初始化对象时，在用例中明确构造。golden 使用独立适配器和固定种子，不受其它测试是否预热缓存影响。
- 合并或迁移测试后，除全量检查外，受影响文件须能独立运行，例如 `python -m unittest tests.config.test_golden_daily`。只检查“未抛异常”或“结果非空”不足以验证具体行为，应断言结果、调用对象或持久化内容。

runner 子模块测试由 OneDragonRunner 仓库自己的 CI 执行，主仓 CI 只运行主仓测试。

日常 golden 覆盖全部声明菜单选择的保存路径、字段差异及反读，正常测试只读基线。确认行为变更后显式更新，并审查 `python-backend/tests/golden/daily_baseline.json` 的差异：

```bash
PYTHONPATH=python-backend:python-backend/src python -m tests.config.test_golden_daily --update
```

完整测试清单及本轮发现见 [测试审查记录](docs/test-audit.md)。

平台分工：源码全量测试只在本地/CI ubuntu 跑；Windows 下**只跑打包产物集成测试**（python-backend/tests/exe/test_*_exe.py，由 .github/workflows/build-exe.yml 打包后覆盖），非打包测试不在 Windows 重复跑。

`deploy/build.bat` 经 `tools/release_package.py test` 复制发布目录到临时目录再运行
exe 测试，使用 `ODH_PACKAGE_DIR`、`ODH_GUI_EXE`、`ODH_RUNNER_EXE` 指定测试副本。
发布目录不生成用户配置、日志或缓存。打包测试覆盖缺少用户 YAML 时的首启生成、
再次启动保留修改，以及 `--version` 与构建元数据一致；测试前后和 ZIP 归档前均检查发布文件清单。
测试后尝试清理临时副本，清理失败仅警告并给出残留路径；构建结果取决于 EXE 测试结果与发布包校验。

`python-backend/tests/update/` 覆盖更新包边界、下载校验与取消、程序文件替换、故障回滚和中断恢复；
`python-backend/tests/exe/test_update_exe.py` 使用临时安装副本真正启动更新器，
验证升级后的 EXE 可启动、运行中的 Runner 阻止更新、Windows 文件占用时回滚、
启动闸门先于用户配置初始化，以及独立恢复入口。所有用户文件断言均使用临时夹具。
升级夹具从被测包继承 Qt/Rust 类型，因此同一组真实 EXE 测试可验证两种发布布局。

`python-gui/tests/gui/test_update_dialog.py` 用真实 Qt 事件循环和替代服务验证显式检查、
工作线程、下载进度、取消/关闭、错误重试及安装就绪后退出；网络和安装操作均隔离。

独立无 Qt 后端由 `deploy/OneDragon-Helper-CLI.spec` 构建：

```text
python -m PyInstaller --noconfirm --workpath deploy/build/rust-cli --distpath deploy/dist/rust-cli deploy/OneDragon-Helper-CLI.spec
python -m unittest discover -s python-backend/tests -t python-backend -p test_headless_exe.py -v
```

`ODH_CLI_EXE` 可指定已有 CLI 构建。测试在临时目录复制 EXE/运行库，使用空白配置模板，
覆盖异目录启动、首启生成/再次保留、更新闸门、单进程 stdio 与 EOF 释放运行锁，
并直接检查冻结模块不包含 Qt/GUI。后端继承父进程权限，无自身 UAC 提示；这些只读/临时
配置测试不需要管理员。CI 的独立 Windows job 实际执行，Ubuntu 源码全量跳过这六项。
另覆盖原 `--selftest/--get-script` 输出文件和退出码；Rust 主程序的同类参数转交此后端。
这一构建是 Rust 发布包的后端组件，尚未包括完整 GUI/Runner/Updater 和发布资源。

完整 Rust 包通过 `python tools/build_rust.py --test` 在 Windows 管理员环境验证；
`build-exe.yml` 的独立 job 同时执行 Windows Rust 测试、CLI/GUI/Runner/Updater 的
真实 EXE 测试。`test_rust_package_exe.py` 直接读取最终 PE 验证 GUI 图标/UAC、CLI
继承权限、PE 校验和，以及全部 Python EXE 无 Qt/QML；这些只读检查不要求管理员。
另检查 Rust 主程序的 CRT 导入符号均由同目录运行库提供，避免依赖开发机预装的 VC 运行库。
包内 GUI 权限与原版一致，普通终端不要直接跑需要启动 GUI/Runner/Updater 的集成测试。
绘制专项区分前端：Qt 仍验证完整 QML 的 D3D11/WARP 首帧；Rust 在临时空脚本夹具中
调用随包的 `--capture` 诊断，检查主窗口及关机确认窗的实际截图尺寸和颜色，
分别使用自动选卡和强制 WARP；截图后取消关机，仅运行独立窗口，不调用系统关机。
两种渲染测试都以当前权限运行，
不启动脚本，也不把 Qt 的 QML 文件要求施加到 Rust 包。

Rust 双进程升级用真实主 EXE 的原 CLI `--dump-config --out` 写命名管道，暂缓读取以
保持主程序与 CLI 存活。独立更新器收到双方 PID/创建时间，写 ready 后必须保持旧文件；
读取输出让两者自然退出，才完成替换，且保留临时用户文件。这里覆盖进程交接与安装，
不声称点击了更新窗；窗口状态和 ready 回执由 Rust/无 Qt 会话测试验证。管道夹具的
锁保持与 EOF 已由独立 CLI EXE 在非管理员环境实际验证，不给产品增加测试命令。

`tools/measure_gui_startup.py` 对 Qt/Rust 的干净完整包做暖启动对比，首个可回读任务画面
才计时成功。测量工具测试覆盖标记前退出、缺少任务数据和非零退出，实际 15 轮交替测量
见 `docs/rust-feasibility/assessment.md`；它不是常规 CI 的性能阈值测试。
计时原始样本写到忽略目录 `.cache/gui-startup.json`，不提交本机报告。

Rust 源码位于 `rust-gui/src`，单元与集成测试都已映射到 `rust-gui/tests`：

```bash
cargo fmt --manifest-path rust-gui/Cargo.toml --check
cargo clippy --manifest-path rust-gui/Cargo.toml --locked --all-features --all-targets -- -D warnings
cargo test --manifest-path rust-gui/Cargo.toml --locked --all-features
```

## 2. 风格检查 ruff

```bash
ruff check python-backend python-gui tools runner
ruff format .
```

`check` 与 CI 一致，含 tools/；`format .` 全仓格式化（含 runner/，也是我们的代码）。

## 3. 加依赖

改任一 Python 子项目的 pyproject.toml → 在仓库根运行 uv sync 同步 uv.lock。

## 4. 调试

先看日志再下结论：主程序日志在 logs/onedragon_helper.log，每日 00:00 轮转，保留 14 天。运行器子进程有独立日志系统 .log/。子脚本日志目录见 config/script_resources.yml 的 logs 声明。日志汇总：uv run --directory python-backend python -m src.log。

## 5. Windows 全链路真实模拟（手动）

```bash
PYTHONPATH=python-backend:python-backend/src python -m tests.sim_schedule_win
```

在 %TEMP% 沙箱内以真实进程走完 schedule_run 全编排（定时等待→清场→生成链→runner 子进程→日志解析→重跑→post_run），假脚本/假游戏由脚本内 PyInstaller 现场打包（进程名唯一不误杀），16 项断言逐项核验；不进 CI，不触碰真实 config。
