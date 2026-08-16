# src/gui — GUI 包

新 GUI 主窗口 + 单脚本配置弹窗（2026-08-16 由 src/launcher_proto 迁入，
2026-08-17 更名 main_window.py；旧 GUI 的 runner / widgets 已删，
弹窗样式/工具已并入 dialogs.py）。

## 文件与依赖

| 模块 | 职责 | 项目内依赖 |
|------|------|-----------|
| `main_window` | 主窗口 LauncherWindow（正式入口） | task_card / widgets / icons / theme / dialogs / config / service |
| `task_card` | TaskCardPanel 任务卡（副本/周常调度） | theme / widgets / config / service / utils_weekly |
| `widgets` | RailContainer / Toggle / GameIcon 自绘控件 | theme / icons |
| `icons` | glyph 绘制 + 脚本 exe 图标获取 | theme / config.subscript / utils |
| `theme` | 设计稿常量（颜色/尺寸/字体/链接） | （无，纯样式层） |
| `dialogs` | SingleScriptConfigDialog 弹窗 + 确认回调 | config / service（自包含样式与工具） |

依赖单向：`main_window` 是入口，各模块不反向引用主窗口；`theme` 被各模块引用但不依赖业务模块。

## 主窗口（`main_window.py`）

`LauncherWindow`：1280x720 frameless 启动器式界面——左侧脚本栏（图标 + ⊞ 控制
模式 + 启动全部）、HERO 背景区、任务卡（日常副本/周常周几起）、启动胶囊 +
悬浮图标条（主页/启动游戏/文件夹/B站/GitHub/壁纸）。运行直接
`subprocess.Popen` 开独立控制台窗口跑链。

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
