"""GUI 包：QML 启动器 + 单脚本配置弹窗。

- qml_bridge: QML 业务桥接单例（脚本列表 / 背景 / 任务卡 / 链接 / 窗口控制）
- game_list_model / icons / theme: 列表模型 / 图标 / 设计常量
- dialogs: SingleScriptConfigDialog / confirm_config_update / inject_config_confirm
  （自包含：弹窗样式与工具封在文件内部）

正式入口 launcher.bat → python -m src.launcher（QML GUI）。
"""
