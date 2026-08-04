# AGENTS.md

OneDragon-Helper 项目指南

## 1. 项目简介

**多游戏自动化脚本调度器**：GUI 选脚本/副本/超时 → 写各脚本自己的 config → 运行器逐条 subprocess 调外部 exe → 解析日志汇总成功/失败。

## 2. 技术栈与依赖

- **Python 3.11+**；GUI 用 **PySide6**（原生控件 + 手写样式）
- 依赖：`uv sync`（pyproject.toml + uv.lock）；Lint/Format：`ruff`（line-length 88，double quote）
- `src/runner/`：脚本链运行器，**git submodule → OneDragonRunner**（已抽出去独立维护）；
- CI：`.github/workflows/ci.yml`
- 本地开发前必须先激活 venv（`source .venv/Scripts/activate` 或 `call env.bat`）

## 3. 目录结构

```
src/launcher.py            # 入口：parse_args / config_workflow / main
src/utils.py               # 路径工具
src/utils_logger.py        # setup_logging()：控制台 + 文件轮转
src/gui/                   # GUI 包（详见 src/gui/README.md）
  main_window.py / widgets.py / dialogs.py / controls.py
  icons.py / chain.py / utils.py / runner.py
src/config/
  set_config.py             # 副本配置适配器：外观接口 + ScriptConfig 类层级（设计见 set_config.md）
  subscript.py              # config 读写子脚本基础设施（load/save/template）
  dungeon_config.py         # dungeon_list.yml 解析
  bgi.py                    # 暂时未使用
src/runner/                 # 用于运行脚本链；git submodule → OneDragonRunner
python_script/              # 独立脚本，不 import 项目模块
config/                     # 各种配置文件
tests/                      # 测试文件
```

## 4. 核心架构

- **GUI**：`MainWindow` 列出 `ScriptItem`（副本下拉 + 开关 + 配置弹窗）→ 生成脚本链配置 → `ScriptChainRunner(QThread)` 以单个 runner 子进程运行整条链。详见 [`src/gui/README.md`](src/gui/README.md)。
- **副本配置适配器**：外观接口 `set_config()` + `ScriptConfig` 类层级，各游戏一个子类。详见 [`src/config/set_config.md`](src/config/set_config.md)。
- **运行器**：`src/runner/` 逐条执行脚本链，`block` 字段控制阻塞/非阻塞。详见 [`src/runner/README.md`](src/runner/README.md)。
- **初始化**：首次 `config.yml` 缺失时 `config_workflow()`模板生成。
- **日志解析**：由独立脚本`python_script/collect_log.py`解析，并由独立脚本`python_script/rerun.py`重新运行脚本。

## 5. 编码约定（强偏好，违反即打回）

1. **严格 `assert`** 表达「不该发生」的编程错误；可恢复情况才 `return False`/跳过。
2. **字典访问不用 `.get()`**：先 `assert key in dict` 再直接 `dict[key]`。
3. **不静默吞异常**：except 用 `warnings.warn`，不 `pass`。
4. **命名显式明确**（`self.display_name` 优于 `self.name`）；不留兼容别名。
5. **多实体共享/注册优先 OOP 类层级**，而非 `function + dict`。
6. **重构只在有明确收益时做**，反对 scope-creep；1 处调用点不抽函数。
7. **禁止绕过依赖/CI 的 workaround**（`skipUnless`、`os.name` 判断等）。
8. **日志用 `logging` 模块**（`logger = logging.getLogger(__name__)`，入口调 `setup_logging()`），禁止裸 `print`。`collect_log.py` 例外（独立性约束，仅 `basicConfig` 控制台输出）。
9. GUI 持久化：`gui_state.json` 只存 `dungeon`/`sequence`；`enabled` 纯内存态（重启恢复全开）。
10. **不随意修改 `.bak` / 备份文件**，需改动时先征得用户同意。
11. 新增/修改功能后**必须补测试并跑全套**。
12. **避免使用try-except**，仅在必要时捕获异常。尽可能改用if判断。

## 6. 测试与开发工作流

> **前置：先激活 venv**（`source .venv/Scripts/activate` 或 `call env.bat`），否则 ImportError。

完整流程（跑测试 / ruff / 加依赖 / 调试看日志）见 [`TESTING.md`](TESTING.md)。核心命令：

```bash
export PYTHONPATH=src && python -m unittest discover -s tests -p "test*.py"   # 跑测试
ruff check src tests                                                          # 风格检查（含 src/runner/）
```

- **启动 GUI**：`launcher.bat`，或 `python -m src.launcher`。
- **新增游戏适配**：见 `src/config/set_config.md`。
