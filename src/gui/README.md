# src/gui — GUI 包

PySide6 GUI：脚本列表、增删/重排/配置、生成脚本链配置并运行。

## 文件与依赖

| 模块 | 项目内依赖 |
|------|-----------|
| `main_window` | widgets / dialogs / controls / chain / utils / runner / config.dungeon_config / src.utils |
| `widgets` | dialogs / controls / icons / runner / utils / config.dungeon_config / config.subscript |
| `dialogs` | controls / utils / src.utils |
| `controls` | 仅 PySide6 |
| `icons` | src.utils |
| `chain` | utils / config.dungeon_config / config.set_config / src.utils |
| `utils` | src.utils |
| `runner` | src.utils |

依赖单向：`main_window` 是唯一入口，其余模块不反向引用主窗口。

## 内存/磁盘同步不变量（强约束）

`MainWindow.all_config_data` 是 `config.yml` 的内存副本。三条写盘路径：

| 路径 | 触发 | 是否更新内存 |
|------|------|-------------|
| `_generate_config`（运行） | 点「运行」 | ✅ 基于内存写 |
| `_save_script_order`（重排/增删） | 拖拽/添加/删除 | ✅ 基于内存写 |
| `SingleScriptConfigDialog.save_data`（配置弹窗） | 弹窗保存 | ❌ 直接改磁盘 |

弹窗 `accept` 后，`ScriptItem` 必须通过 `config_saved_callback` → `MainWindow._on_script_config_saved` 重新从磁盘加载 `all_config_data` 并同步对应卡片的 `script_path`。

**违反此约束会导致「保存路径失效」**：内存仍是旧路径，下一次运行/重排把旧路径覆盖回磁盘。

## 运行流程

点「运行」→ `_generate_config("88")` → `chain.py` 的 `generate_chain_config` 生成 `config/script_chain/88.yml`（仅含启用的脚本）→ `ScriptChainRunner(QThread)` 以**单个 runner 子进程**运行整条链。

命令：开发态 `python -m src.runner.launcher --chain <path>`（注入 `PYTHONPATH=src/runner`）；frozen 态用同目录 `OneDragon-Helper-Runner.exe`。链内每条脚本的 `block` 字段决定阻塞/非阻塞（缺字段视为阻塞），详见 [`src/runner/README.md`](../runner/README.md)。

## UI 状态持久化

`gui_state.json` 只存 `dungeon`/`sequence`（用户选了哪个副本）。`enabled`（开关）是纯内存态，重启恢复全开。详见 `utils.py` 的 `load_ui_state` / `save_ui_state`。
