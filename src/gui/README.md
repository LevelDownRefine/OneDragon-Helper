# src/gui — GUI 包

PySide6 GUI：脚本列表、增删/重排/配置、生成脚本链配置并运行。

## 文件与依赖

| 模块 | 项目内依赖 |
|------|-----------|
| `main_window` | widgets / dialogs / runner / config.dungeon_config / service.chain_service / service.script_service / src.utils |
| `widgets` | dialogs / icons / runner / utils / config.dungeon_config / config.subscript |
| `dialogs` | utils / src.utils / service.script_service |
| `icons` | src.utils |
| `utils` | src.utils |
| `runner` | src.utils |

依赖单向：`main_window` 是唯一入口，其余模块不反向引用主窗口。

## 写盘架构（单一路径）

**config.yml 写入权统一归 ChainService。** MainWindow / SingleScriptConfigDialog 均不直接写盘。

| 操作 | GUI 触发 | 写盘路径 |
|------|----------|---------|
| 编辑脚本字段 | 弹窗 `save_data` → 存 `pending_changes` → `_on_script_config_saved` | `ChainService.update_script`（内部处理 config + weekly） |
| 增删脚本 | `_add_script` / `_delete_script` | `ChainService.add_script` / `remove_script`（内部处理 config + weekly） |
| 重排 | 拖拽 | `ChainService.save_config` |
| 运行 | 点「运行」 | `ChainService.generate_chain` → `chain_gen` |

`SingleScriptConfigDialog.save_data()` **不再写盘**，仅收集表单数据存入 `self.pending_changes`。ScriptItem `accept` 后将 `pending_changes` 传给 `MainWindow._on_script_config_saved`，后者委托 `ChainService.update_script()` 原子完成 config + weekly 落盘，再重新 `load_config()` 同步内存与卡片。

## 运行流程

点「运行」→ `_generate_config("88")` → `ChainService.generate_chain` → `chain_gen.generate_chain_config` 生成 `config/script_chain/88.yml`（仅含启用的脚本）→ `ScriptChainRunner(QThread)` 以**单个 runner 子进程**运行整条链。

命令：开发态 `python -m src.runner.launcher --chain <path>`（注入 `PYTHONPATH=src/runner`）；frozen 态用同目录 `OneDragon-Helper-Runner.exe`。链内每条脚本的 `block` 字段决定阻塞/非阻塞（缺字段视为阻塞），详见 [`src/runner/README.md`](../runner/README.md)。

## UI 状态持久化

`gui_state.json` 只存 `dungeon`/`sequence`（用户选了哪个副本）。`enabled`（开关）是纯内存态，重启恢复全开。经由 `ChainService.load_ui_state` / `save_ui_state` 读写。
