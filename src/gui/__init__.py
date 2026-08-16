"""GUI 包（旧 GUI 残留：仅保留被新 GUI src/launcher_proto 复用的共享模块）。

- dialogs: 单脚本配置弹窗 / 添加脚本弹窗
- theme: 旧 GUI 设计 token 与 QSS（dialogs 依赖）
- utils: 统一消息框 / 打开文件辅助 / 按钮工厂 / 标题栏同步（dialogs 依赖）

脚本图标获取（get_script_icon）已并入 src/launcher_proto/icons.py（2026-08-16）。

新 GUI 主窗口在 src/launcher_proto；正式入口 launcher.bat（python -m
src.launcher_proto.launcher_proto）与 src/launcher.py 的 GUI 主路径均已指向它。
"""
