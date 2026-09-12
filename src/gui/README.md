# src/gui — GUI 包

图形界面层：主窗口 + 单脚本配置弹窗。只放与图形界面有关的东西，即 QML / 控制器 / 弹窗，不承载业务逻辑、config 读写、链生成与运行——分别归 set_config、runner、service。GUI 不写盘，写盘统一经 service。详见 AGENTS.md 第 4 节。

## 文件与依赖

| 模块 | 职责 | 项目内依赖 |
|------|------|-----------|
| main_window，QmlBridge | QML 门面单例：组合各控制器 + 委托 property/slot | controllers/* / icons / service |
| controllers/game_list | 脚本列表 / 选中 / 增删 / 配置弹窗 / 图标提供器 | config / icons |
| controllers/background | 背景视频/图片/渐变、壁纸、背景路径解析 | config / subscript |
| controllers/task_card | 日常副本 / 周常周几，数据 + 选择持久化 | config / service / utils_weekly |
| controllers/launch | 启动胶囊，启动当前 / 启动全部 | game_list / task_card / service |
| controllers/links | 悬浮条：主页/B站/GitHub/目录/设置/启动游戏 | config / utils_sub_config / utils |
| controllers/backup | 配置操作分发、备份 / 恢复与结果提示 | config_dialog / service |
| controllers/daily_plan | 配置界面的每日计划编辑 | daily_plan_dialog / service |
| controllers/window | 窗口控制：最小化/关闭/拖动 | 无 |
| icons | 脚本 exe 图标 + QML 矢量图标提供器 | utils_sub_config |
| dialogs | 单脚本配置弹窗 + 确认回调 | config / service |
| file_drop | Windows 整窗文件拖入，兼容管理员窗口 | 无 |
| config_dialog | 右上角配置入口与自动启动设置 | dialogs / icons |
| daily_plan_dialog | 每日计划的时间、脚本名单与启用开关 | dialogs / service |
| qml/Theme.js | 主窗口、按钮、任务卡与下拉菜单的共享配色 | 无 |

依赖单向：main_window 组合各控制器，控制器间构造注入；QmlBridge 是 QML 唯一门面。qml/ 组件经 Loader 相对路径加载，文件名与 controllers/ 同名。

## 主窗口 main_window.py

`QmlBridge`：QML 中央控制器单例，经 `qmlRegisterSingletonInstance` 注册为 QML 的 `Bridge`，组合各职责控制器并编排跨控制器流程（选脚本 → 刷背景 + 任务卡）。窗口几何与布局在 `qml/main.qml`，运行直接 subprocess.Popen 开独立控制台窗口跑链。

主窗口使用蓝灰配色与半透明面板；颜色统一取 `qml/Theme.js`，原生弹窗对应色板在 `dialogs.py`。图标通过 `UiIconProvider` 绘制，避免依赖符号字体；右侧工具栏悬停显示用途，长 toast 自动换行。保持纯 QtQuick，不增加控件或效果库依赖。

「启动游戏」悬停时，经 `set_config.get_game_exe_path` 读取当前游戏 exe，在内存中生成图标提示；路径或图标缺失时显示「启动游戏」。切换脚本和再次悬停时刷新，不写图标缓存文件。

左下控制模式按钮开启时，在右侧气泡显示「全 / 清 / ＋」，左侧脚本仍可逐项选择是否参加手动运行；再次点击模式按钮、Esc 或点击右侧内容区退出控制模式。添加脚本前先收起气泡，拖拽期间暂时隐藏气泡。

从资源管理器将 `.exe` / `.bat` / `.py` 文件或快捷方式拖到主窗口任意位置即可添加，支持多个文件，复用「＋」的命名、默认配置和保存流程。快捷方式由 service 读取目标路径与原始启动参数；失效、指向其他类型或指定不同工作目录的快捷方式拒绝添加并说明原因（运行器固定以目标所在目录启动）。同名 exe 提示已存在。批量添加结束后统一显示成功、重复和失败数量，保留未完成文件的名称与原因。仅记录启动信息，不移动或运行文件。Windows 先撤销 Qt 的 OLE 拖放注册，再统一使用 WM_DROPFILES，避免管理员窗口先被 OLE 拒绝；其他平台由整窗 QML DropArea 接收。两条入口均经 Bridge.dropScripts。

## 弹窗 dialogs.py

- SingleScriptConfigDialog：单脚本配置弹窗，保存后经 pending_changes 返回，写盘委托 AppService.update_script（内部转 src.utils.utils_config.update_script）。
- ConfigDialog：右上角图标入口，自动启动设置点击「保存」才写入；取消、关闭和 Esc 不写入。每日计划、运行选项和备份/恢复独立打开，保留当前表单。每日计划启用时不再触发打开窗口的自动启动。
- DailyPlanDialog：时间、参加的脚本、启用开关放在同一表单，保存后经 DailyPlanController 调 AppService；失败保留输入，取消不写入。仅从「配置 → 每日计划」进入，主界面不显示计划卡片或快捷按钮。在表单中取消勾选启用开关并保存即可暂停，时间与脚本继续保留；手动勾选不修改计划。
- RunConfirmDialog：手动启动前确认，或在「运行选项」中仅保存配置。每日时间独立管理，手动「启动全部」始终立即运行。
- 表单、启动/关机倒计时及消息框共用半透明背景（与 QML Theme.panel 一致），文字和控件保持清晰；系统文件选择框沿用系统外观。

## 写盘路径

config.yml 写入权统一归 src.utils.utils_config（经 AppService 委托），GUI 弹窗不直接写盘：

| 操作 | GUI 触发 | 写盘路径 |
|------|----------|---------|
| 编辑脚本字段 | 弹窗 save_data → pending_changes | AppService.update_script（src.utils.utils_config） |
| 增删脚本 | _add_script / _on_delete_script | AppService.add_script / remove_script（src.utils.utils_config） |
| 重排 | 拖拽 | AppService.save_config（src.utils.utils_config） |
| 自动启动 | 配置弹窗保存 | AppService.apply_startup_options → schedule.yml 的 startup 块 |
| 每日计划 | 计划弹窗保存 / 暂停 / 恢复 | AppService.apply_daily_plan → Windows 任务计划 + schedule.yml 的 daily_run 块 |
| 脚本勾选 | 控制模式 / 全选 / 清空 | AppService.set_script_enabled → config.yml 脚本条目的 enabled |
| 运行 | 启动全部 | AppService 链生成 → chain_gen（src.service.chain_service.generate_chain） |

## UI 状态持久化

日常副本/序列的真源是子脚本 config（编辑期实时落盘，无 UI 状态文件）；set_daily_task 为
no-op 的脚本（绝区零/崩铁，上游自身已支持）不提供选择，chip 直接呈现 daily_task_list.yml
声明的唯一选项。手动脚本 enabled 保存到 config.yml，重启按脚本身份回显；缺省启用。每日计划的脚本名单独立保存到 schedule.yml 的 daily_run.script_names，触发时使用最新副本和运行选项。

## 添加功能配方

QML 仅经 Bridge.<slot>() 与 Python 交互，QmlBridge 是唯一桥。新增功能三步，逻辑归所属控制器，门面只做薄委托：

1. 逻辑：加到所属 controllers/ 控制器；无固定归属按屏幕区域就近放，跨区域则新建独立控制器。
2. 暴露：在 QmlBridge 加一行 @Slot 委托。
3. 界面：在对应 qml/<name>.qml 加 Rectangle/MouseArea，调用 Bridge.xxx()。

示例：右上角加截图按钮 → window.py 加 @Slot def screenshot → QmlBridge.screenshot 一行委托 → qml/window.qml 加按钮。
