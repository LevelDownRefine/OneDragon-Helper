# src/gui — GUI 包

新 GUI 主窗口 + 单脚本配置弹窗（2026-08-16 由 src/launcher_proto 迁入，
2026-08-17 更名 main_window.py；旧 GUI 的 runner / widgets 已删，
弹窗样式/工具已并入 dialogs.py）。

**架构边界**：`src/gui/` 只放**只跟图形界面有关**的东西（QML / 控制器 / 弹窗）。
业务逻辑、config 读写、脚本链生成与运行一律不在此层——分别归
`set_config`（适配器）、`runner`（运行器）、`service`（外观层，整合并支撑 CLI）。
GUI 不写盘，写盘统一经 `service`。详见 [`../AGENTS.md`](../AGENTS.md) 第 4 节。

## 文件与依赖

| 模块 | 职责 | 项目内依赖 |
|------|------|-----------|
| `main_window` (QmlBridge) | QML 门面单例：组合各控制器 + 委托 property/slot + 编排 | controllers/* / icons / service |
| `controllers/game_list` | 脚本列表 / 选中 / 增删 / 配置弹窗 / 图标提供器 | config / icons |
| `controllers/background` | 背景（视频/图片/渐变）/ 壁纸 / 背景路径解析 | config / subscript |
| `controllers/task_card` | 日常副本 / 周常周几（数据 + 选择持久化） | config / service / utils_weekly |
| `controllers/launch` | 启动胶囊（启动当前 / 启动全部） | game_list / task_card / service |
| `controllers/links` | 悬浮条（主页/B站/GitHub/目录/设置/启动游戏） | config / subscript / utils |
| `controllers/window` | 窗口控制（最小化/关闭/拖动） | （无） |
| `icons` | 脚本 exe 图标 + QML 矢量图标提供器 | config.subscript |
| `dialogs` | 单脚本配置弹窗 + 确认回调 | config / service（自包含） |

依赖单向：`main_window` 组合各控制器，控制器间经构造注入依赖；`QmlBridge` 是 QML 唯一门面（见 launcher.py 注册）。`src/gui/qml/` 下组件经 `Loader` 相对路径加载，文件名与 `controllers/` 同名（单文件不套子目录）。

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

## 添加功能配方（架构约定）

QML 仅经 `Bridge.<slot>()` 与 Python 交互，`QmlBridge`(main_window.py) 是二者间
唯一桥。新增一个功能按以下三步，逻辑归位于所属控制器，门面只做薄委托：

1. **逻辑**：加到所属 `controllers/` 控制器（新能力无固定归属时，按"屏幕区域"
   就近放；跨区域则新建一个独立控制器）。门面不放业务/UI 逻辑。
2. **暴露**：在 `main_window.py` 的 `QmlBridge` 加一行 `@Slot` 委托
   （`def xxx(self, ...): self.<controller>.xxx(...)`）。
3. **界面**：在对应 `src/gui/qml/<name>.qml` 组件里加 `Rectangle`/`MouseArea`，
   调用 `Bridge.xxx(...)`；复用的旧能力只改 QML，无需碰 Python。

示例：右上角加「截图」按钮 → `window.py` 加 `@Slot def screenshot()` →
`QmlBridge.screenshot` 一行委托 → `qml/window.qml` 加按钮。
