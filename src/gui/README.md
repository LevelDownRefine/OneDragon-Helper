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
| controllers/window | 窗口控制：最小化/关闭/拖动 | 无 |
| icons | 脚本 exe 图标 + QML 矢量图标提供器 | utils_sub_config |
| dialogs | 单脚本配置弹窗 + 确认回调 | config / service |

依赖单向：main_window 组合各控制器，控制器间构造注入；QmlBridge 是 QML 唯一门面。qml/ 组件经 Loader 相对路径加载，文件名与 controllers/ 同名。

## 主窗口 main_window.py

`QmlBridge`：QML 中央控制器单例，经 `qmlRegisterSingletonInstance` 注册为 QML 的 `Bridge`，组合各职责控制器并编排跨控制器流程（选脚本 → 刷背景 + 任务卡）。窗口几何与布局在 `qml/main.qml`，运行直接 subprocess.Popen 开独立控制台窗口跑链。

## 弹窗 dialogs.py

- SingleScriptConfigDialog：单脚本配置弹窗，保存后经 pending_changes 返回，写盘委托 AppService.update_script（内部转 src.utils.utils_config.update_script）。

## 写盘路径

config.yml 写入权统一归 src.utils.utils_config（经 AppService 委托），GUI 弹窗不直接写盘：

| 操作 | GUI 触发 | 写盘路径 |
|------|----------|---------|
| 编辑脚本字段 | 弹窗 save_data → pending_changes | AppService.update_script（src.utils.utils_config） |
| 增删脚本 | _add_script / _on_delete_script | AppService.add_script / remove_script（src.utils.utils_config） |
| 重排 | 拖拽 | AppService.save_config（src.utils.utils_config） |
| 运行 | 启动全部 | AppService 链生成 → chain_gen（src.service.chain_service.generate_chain） |

## UI 状态持久化

日常副本/序列的真源是子脚本 config（编辑期实时落盘，无 UI 状态文件）；set_dungeon 为
no-op 的脚本（绝区零/崩铁，上游自身已支持）不提供选择，chip 直接呈现 dungeon_list.yml
声明的唯一选项。enabled 是纯内存态，重启恢复全开。

## 添加功能配方

QML 仅经 Bridge.<slot>() 与 Python 交互，QmlBridge 是唯一桥。新增功能三步，逻辑归所属控制器，门面只做薄委托：

1. 逻辑：加到所属 controllers/ 控制器；无固定归属按屏幕区域就近放，跨区域则新建独立控制器。
2. 暴露：在 QmlBridge 加一行 @Slot 委托。
3. 界面：在对应 qml/<name>.qml 加 Rectangle/MouseArea，调用 Bridge.xxx()。

示例：右上角加截图按钮 → window.py 加 @Slot def screenshot → QmlBridge.screenshot 一行委托 → qml/window.qml 加按钮。
