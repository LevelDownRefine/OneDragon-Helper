"""GUI 包：QML 启动器 + 单脚本配置弹窗。

- main_window: QmlBridge 门面（脚本列表 / 背景 / 任务卡 / 链接 / 窗口控制）
- controllers: 各职责控制器（独立 QObject 组合，background / game_list / task_card / launch / links / window）
- icons: 图标与图标提供器
- dialogs: SingleScriptConfigDialog / confirm_config_update / inject_config_confirm
  （自包含：弹窗样式与工具封在文件内部）

正式入口 launcher.bat → python -m src.launcher（QML GUI）。
"""
