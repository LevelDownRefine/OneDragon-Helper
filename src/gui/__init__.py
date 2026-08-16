"""GUI 包：新 GUI 主窗口 + 单脚本配置弹窗（旧 GUI 残留已并入/删除）。

- main_window: 启动器式主窗口（LauncherWindow，2026-08-16 起正式入口）
- task_card / widgets / icons / theme: 任务卡 / 自绘控件 / 图标 / 设计常量
- dialogs: SingleScriptConfigDialog / confirm_config_update / inject_config_confirm
  （自包含：弹窗样式与工具封在文件内部）

正式入口 launcher.bat（python -m src.gui.main_window）与 src/launcher.py 的
GUI 主路径均指向 LauncherWindow。
"""
