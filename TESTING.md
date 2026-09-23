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
cd <root> && export PYTHONPATH=src && python -m unittest discover -s tests -t . -p "test*.py"
```

python -m 把根目录加入 sys.path，PYTHONPATH=src 让 import launcher 可用；两种 import 风格并存，必须在根目录且带 PYTHONPATH=src 跑。测试按被测模块和职责归档；GUI 测试开头设 QT_QPA_PLATFORM=offscreen 无头跑 PySide6。文件 I/O 使用 mock 或独立临时目录，不读写真实 config 或游戏脚本路径；临时资源用上下文管理器或 addCleanup 回收。新增/修改功能后必须补测试并跑全套再交付。

`-t .` 将项目根作为测试包的顶层，确保按 `tests.gui`、`tests.config` 等完整包名加载，避免 `tests/tools` 遮蔽项目的 `tools`。子目录须保留 `__init__.py`，否则 unittest 不会递归发现其中的用例。

| 目录 | 归属 |
|---|---|
| `tests/gui/` | 控件、控制器、QML、窗口及 GUI 共享夹具 |
| `tests/config/` | 配置适配器、声明、日常、周常及 golden 验证 |
| `tests/service/` | 配置服务、链生成、调度和运行编排 |
| `tests/update/` | 更新包协议、下载服务、运行锁、安装回滚与独立入口 |
| `tests/utils/` | 通用工具、文件读写、路径与系统操作 |
| `tests/log/` | 日志解析与邮件通知 |
| `tests/tools/` | 选项同步脚本的离线测试 |
| `tests/support/` | 跨模块测试辅助代码及其自身测试 |
| `tests/exe/` | Windows 打包产物集成测试 |
| `tests/fixtures/`、`tests/golden/` | 静态夹具与 golden 基线 |

根目录仅保留与 `src` 顶层对应的 CLI、launcher、link 测试及手动模拟入口。只跑某一模块时也指定项目根，例如：

```bash
PYTHONPATH=src python -m unittest discover -s tests/gui -t . -p "test*.py"
```

- 参数不同但契约相同的场景用具名 `subTest` 合并，每个场景保留独立输入和完整断言；不同失败原因或不同层次的集成测试单独保留。
- 共享夹具放非 `test_*.py` 模块，不从另一个测试文件导入。`tests/gui/helpers.py` 提供 `get_app()` 和 `make_bridge()`；使用 Qt 图像或窗口前显式创建应用，不依赖导入副作用。
- 缓存测试使用隔离的注册表并恢复原状态；需要已初始化对象时，在用例中明确构造。golden 使用独立适配器和固定种子，不受其它测试是否预热缓存影响。
- 合并或迁移测试后，除全量检查外，受影响文件须能独立运行，例如 `PYTHONPATH=src python -m unittest tests.config.test_golden_daily`。只检查“未抛异常”或“结果非空”不足以验证具体行为，应断言结果、调用对象或持久化内容。

runner 子模块测试由 OneDragonRunner 仓库自己的 CI 执行，主仓 CI 只运行主仓测试。

日常 golden 覆盖全部声明菜单选择的保存路径、字段差异及反读，正常测试只读基线。确认行为变更后显式更新，并审查 `tests/golden/daily_baseline.json` 的差异：

```bash
PYTHONPATH=src python -m tests.config.test_golden_daily --update
```

完整测试清单及本轮发现见 [测试审查记录](docs/test-audit.md)。

平台分工：源码全量测试只在本地/CI ubuntu 跑；Windows 下**只跑打包产物集成测试**（tests/exe/test_*_exe.py，由 .github/workflows/build-exe.yml 打包后覆盖），非打包测试不在 Windows 重复跑。

`deploy/build.bat` 经 `tools/release_package.py test` 复制发布目录到临时目录再运行
exe 测试，使用 `ODH_PACKAGE_DIR`、`ODH_GUI_EXE`、`ODH_RUNNER_EXE` 指定测试副本。
发布目录不生成用户配置、日志或缓存。打包测试覆盖缺少用户 YAML 时的首启生成、
再次启动保留修改，以及 `--version` 与构建元数据一致；测试前后和 ZIP 归档前均检查发布文件清单。
测试后尝试清理临时副本，清理失败仅警告并给出残留路径；构建结果取决于 EXE 测试结果与发布包校验。

`tests/update/` 覆盖更新包边界、下载校验与取消、程序文件替换、故障回滚和中断恢复，
并以 `python -m src.update` 验证独立入口的安装和失败结果；
`tests/exe/test_update_exe.py` 使用临时安装副本真正启动更新器，
验证升级后的 EXE 可启动、运行中的 Runner 阻止更新、Windows 文件占用时回滚、
启动闸门先于用户配置初始化，以及独立恢复入口。所有用户文件断言均使用临时夹具。

`tests/gui/test_update_dialog.py` 用真实 Qt 事件循环和替代服务验证显式检查、
工作线程、下载进度、取消/关闭、错误重试及安装就绪后退出；网络和安装操作均隔离。

## 2. 风格检查 ruff

```bash
ruff check src tests tools
ruff format .
```

`check` 与 CI 一致，含 tools/；`format .` 全仓格式化（含 src/runner/，也是我们的代码）。

## 3. 加依赖

改 pyproject.toml → uv sync 同步 uv.lock。

## 4. 调试

先看日志再下结论：主程序日志在 logs/onedragon_helper.log，每日 00:00 轮转，保留 14 天。运行器子进程有独立日志系统 .log/。子脚本日志目录见 src/log/monitor 各 Parser 的 _get_log_dir。日志汇总：python -m src.log。

## 5. Windows 全链路真实模拟（手动）

```bash
PYTHONPATH=src python -m tests.sim_schedule_win
```

在 %TEMP% 沙箱内以真实进程走完 schedule_run 全编排（定时等待→清场→生成链→runner 子进程→日志解析→重跑→post_run），假脚本/假游戏由脚本内 PyInstaller 现场打包（进程名唯一不误杀），16 项断言逐项核验；不进 CI，不触碰真实 config。
