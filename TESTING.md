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
cd <root> && export PYTHONPATH=src && python -m unittest discover -s tests -p "test*.py"
```

python -m 把根目录加入 sys.path，PYTHONPATH=src 让 import launcher 可用；两种 import 风格并存，必须在根目录且带 PYTHONPATH=src 跑。测试按被测模块和职责归档；GUI 测试开头设 QT_QPA_PLATFORM=offscreen 无头跑 PySide6。文件 I/O 使用 mock 或独立临时目录，不读写真实 config 或游戏脚本路径；临时资源用上下文管理器或 addCleanup 回收。新增/修改功能后必须补测试并跑全套再交付。

- 参数不同但契约相同的场景用具名 `subTest` 合并，每个场景保留独立输入和完整断言；不同失败原因或不同层次的集成测试单独保留。
- 共享夹具放非 `test_*.py` 模块，不从另一个测试文件导入。`tests/gui_helpers.py` 提供 `get_app()` 和 `make_bridge()`；使用 Qt 图像或窗口前显式创建应用，不依赖导入副作用。
- 缓存测试使用隔离的注册表并恢复原状态；需要已初始化对象时，在用例中明确构造。golden 使用独立适配器和固定种子，不受其它测试是否预热缓存影响。
- 合并或迁移测试后，除全量检查外，受影响文件须能独立运行，例如 `PYTHONPATH=src python -m unittest tests.test_golden_daily`。只检查“未抛异常”或“结果非空”不足以验证具体行为，应断言结果、调用对象或持久化内容。

runner 子模块测试由 OneDragonRunner 仓库自己的 CI 执行，主仓 CI 只运行主仓测试。

日常 golden 覆盖全部声明菜单选择的保存路径、字段差异及反读，正常测试只读基线。确认行为变更后显式更新，并审查 `tests/golden/daily_baseline.json` 的差异：

```bash
PYTHONPATH=src python -m tests.test_golden_daily --update
```

完整测试清单及本轮发现见 [测试审查记录](docs/test-audit.md)。

平台分工：源码全量测试只在本地/CI ubuntu 跑；Windows 下**只跑打包产物集成测试**（tests/exe/test_*_exe.py，由 .github/workflows/build-exe.yml 打包后覆盖），非打包测试不在 Windows 重复跑。

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
