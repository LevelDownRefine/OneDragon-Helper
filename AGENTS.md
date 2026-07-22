# AGENTS.md

面向 AI 代理（与贡献者）的 OneDragon-Helper 项目指南。改代码、跑测试、新增游戏适配前先读这份文件。

## 1. 项目简介

OneDragon-Helper 是**多游戏自动化脚本调度器 + PySide6 GUI 启动器**：GUI 选脚本/副本/超时 → 生成 `OneDragon-ScriptChainer` 配置 → 调用各游戏脚本 exe 运行；附带日志解析汇总成功/失败。

## 2. 技术栈与依赖

- **Python 3.11+**；GUI 用 **PySide6 + QFluentWidgets**（实际为原生控件 + 手写样式）
- 依赖：`uv sync`（pyproject.toml）；Lint/Format：`ruff`（line-length 88，double quote）
- 子项目 `OneDragon-ScriptChainer/`（第三方游戏脚本，**勿改**）
- CI：`.github/workflows/ci.yml` 用 `uv`，**不走 env.bat**

## 3. 目录结构

```
src/gui_launcher.py        # 唯一 GUI 入口（MainWindow/ScriptItem/SingleScriptConfigDialog/ScriptChainRunner）
src/utils.py                # 路径工具（get_root_dir 等，lru_cache）
src/config/
  set_config.py             # 副本配置适配器：外观接口 + ScriptConfig 类层级（设计见 set_config.md）
  subscript.py              # config 读写基础设施（_CONFIG_REL_PATHS / _TEMPLATE_PATHS / load/save/template）
  dungeon_config.py         # dungeon_list.yml 解析（一级/二级副本）
  init_config.py            # config_workflow / need_config_workflow / copy_python_scripts
  bgi.py                    # copy_BGI_User（整体复制，dirs_exist_ok=True）
src/log/collect_log.py      # 各游戏 *LogParser + parse_logs() 汇总
src/python_script/          # python 脚本（mute/shutdown/unmute 等，由 ScriptChainer 调用）
config/                     # config.example.yml / config.yml / dungeon_list.yml / weekly_timeouts.yml / gui_state.json / 各 init 模板 / BGI_User
tests/  assets/  OneDragon-ScriptChainer/  pyproject.toml  launcher.bat  run_tests.bat  env.bat  uv.lock
```

## 4. 核心架构

- **GUI**（`gui_launcher.py`）：`MainWindow` 列出 `ScriptItem`（副本下拉 + 开关 + ⚙配置按钮）；`SingleScriptConfigDialog(QDialog)` 配脚本路径与每周超时；运行 → `_generate_config("88")` 生成 `OneDragon-ScriptChainer/config/script_chain/88.yml` → `ScriptChainRunner(QThread)` 后台调 `script_chainer.win_exe.launcher --chain 88`。
- **副本配置适配器**（`set_config.py`）：外观接口 `set_config()` + `ScriptConfig` 类层级，各游戏一个子类，封装 config 读写差异。**详细设计与各脚本适配状态见 [`src/config/set_config.md`](src/config/set_config.md)。**
- **配置读写**（`subscript.py`）：`_CONFIG_REL_PATHS`（脚本 config 相对路径）+ `_TEMPLATE_PATHS`（init 模板，在 `config/` 下）；`load_config/save_config/load_template` 按扩展名支持 JSON/YAML；`_get_script_root_dir` 取 `script_path` 父目录并 `replace('\\','/')`。
- **副本列表**（`dungeon_config.py`）：解析 `dungeon_list.yml` 结构化格式 → `(options, seq_map, show_seq)`；`get_display_name` 反查显示名；`restore_sequence_type` 恢复序列类型（解决 YAML 读 int/str 问题）。
- **初始化**（`init_config.py`）：`config_workflow()` 复制 BGI 用户配置 + python 脚本 + 从模板生成 `config.yml`。
- **日志**（`log/collect_log.py`）：每游戏一个 `*LogParser`，`parse_logs()` 汇总今日结果。

## 5. 编码约定（强偏好，违反即打回）

1. **严格 `assert`** 表达「不该发生」的编程错误（缺字段/类型不符/路径不存在/未适配副本）。可恢复情况（如用户没选副本）才用 `return False`/跳过。
2. **字典访问不用 `.get()`**：先 `assert key in dict` 再直接 `dict[key]`。
3. **不静默吞异常**：except 用 `warnings.warn`，不 `pass` 空过。
4. **命名简洁一致、显式明确**（如 `self.display_name` 优于 `self.name`）；不保留向后兼容别名。
5. **多实体共享/注册模式优先 OOP 类层级**，而非 `function + dict`。
6. **重构只在有明确收益时做**，反对 scope-creep；只实现被要求的功能。
7. **坚决反对绕过依赖/CI 的 workaround**（禁 `skipUnless`、`os.name=='nt'` 等）；CI 用 uv 而非 env.bat 代理。
8. **代码稳定性优先**：能加强约束就加强（如 `_is_aligned` 严格要求 `plan_list` 顺序一致）。
9. 新增/修改功能后**必须补测试并跑全套**。
10. GUI 持久化：`gui_state.json` 只存 `dungeon`/`sequence`，**`enabled` 不持久化**（从 config.yml 取）。

## 6. 测试

> ⚠️ **前置步骤：激活环境（必须）**。所有命令都必须在已激活的项目 venv 中运行，否则 `import` 找不到依赖、测试/工具不可用。激活方式（二选一）：
> - bash / git bash：`source .venv/Scripts/activate`
> - cmd：`call env.bat`（同时设置代理 `127.0.0.1:7890`）
>
> 未激活环境是最常见的「本地能跑、CI 挂」或 `ImportError` 根因——**改代码、跑测试、跑 lint 前务必先激活**。

- 本地（在已激活 venv 中）：`cd <root> && export PYTHONPATH=src && python -m unittest discover -s tests -p "test*.py"`（Windows cmd 用 `set PYTHONPATH=src`）。`python -m` 把根目录加入 `sys.path`（`from src.config import ...` 可用），`PYTHONPATH=src` 让 `import gui_launcher` 可用——**两种 import 风格并存**，必须在根目录且带 `PYTHONPATH=src` 跑。
- 测试文件：配置适配器（`test_set_config.py` / `test_set_config_subclasses.py`）、`test_dungeon_config.py`、`test_gui_launcher.py`（开头设 `QT_QPA_PLATFORM=offscreen`）、`test_init_config.py` / `test_bgi.py` / `test_log_monitor.py` / `test_utils.py`。
- 隔离原则：文件 I/O 一律 mock；不依赖真实 config 文件或游戏脚本路径。

## 7. 常见任务

- **启动 GUI**：`launcher.bat`（提权+加载环境），或 `python -m src.gui_launcher`。
- **首次初始化**：删 `config/config.yml` 后启动即触发 `config_workflow()`。
- **日志汇总**：`python -m src.log.collect_log`。
- **加依赖**：改 `pyproject.toml` → `uv sync`（同步 `uv.lock`）。
- **风格检查**（先激活 venv，见 §6 前置步骤）：`ruff check src tests`。只检查 `src/` 与 `tests/`，**不要**对 `OneDragon-ScriptChainer/` 跑（第三方，勿改）。自动修复安全项：`ruff check src tests --fix`；剩余需人工判断的项再逐个处理。
- **新增游戏适配**：见 `src/config/set_config.md`「如何新增一个游戏适配」。

## 8. 环境（Windows）

- **改代码 / 跑测试 / 跑 lint 前必须先激活环境**（详见 §6 前置步骤）。
- `env.bat`：激活根 `.venv\Scripts\activate.bat` + 代理 `127.0.0.1:7890`；`launcher.bat`/`run_tests.bat` 先 call 它。
- `renew.bat`：注释占位，未启用。
- `OneDragon-ScriptChainer/` 有独立 `.venv` 与大量 `.pyc`，**勿改动内部代码、勿提交 `.pyc`**。
