# src/gui — 旧 GUI 残留（共享模块）

旧 GUI（main_window / widgets / runner）已被新 GUI `src/launcher_proto` 替代删除。
脚本图标获取（icons.py）也已并入 `src/launcher_proto/icons.py`。本包仅保留
`dialogs`（配置弹窗）与它依赖的 `theme` / `utils`。新 GUI 入口见 `src/launcher_proto`。

## 文件与依赖

| 模块 | 项目内依赖 |
|------|-----------|
| `dialogs` | theme / utils / config.set_config / config.subscript / service.script_service |
| `theme` | （无项目内依赖，纯样式层） |
| `utils` | theme / src.utils |

依赖单向：`dialogs` 被新 GUI 的 `launcher_proto.py` 与 `src/launcher.py` 复用；
`theme` / `utils` 仅被 `dialogs` 依赖。

## 弹窗（`dialogs.py`）

- `SingleScriptConfigDialog`：单脚本配置弹窗（名称/路径/类型/参数/完成检测/
  关闭脚本/关闭游戏/阻塞/游戏进程/每周超时/配置文件/删除脚本），保存后经
  `pending_changes` 返回，写盘由调用方委托 `ChainService.update_script`。
- `confirm_config_update` / `inject_config_confirm`：config 与模板不一致时的
  保存前确认回调（30s 限时，超时按拒绝处理），GUI 入口注入。

## 写盘架构（单一路径）

**config.yml 写入权统一归 ChainService。** GUI 各弹窗不直接写盘：

| 操作 | GUI 触发 | 写盘路径 |
|------|----------|---------|
| 编辑脚本字段 | 弹窗 `save_data` → 存 `pending_changes` | `ChainService.update_script`（内部处理 config + weekly） |
| 增删脚本 | 新 GUI `_add_script` / `_on_delete_script` | `ChainService.add_script` / `remove_script`（内部处理 config + weekly） |
| 重排 | 拖拽 | `ChainService.save_config` |
| 运行 | 点「启动全部」 | `ChainService.generate_chain` → `chain_gen` |

## UI 状态持久化

`gui_state.json` 存 `dungeon`/`sequence`/`weekly_start`。`enabled`（开关）是纯
内存态，重启恢复全开。经由 `ChainService.load_ui_state` / `save_ui_state` 读写。
