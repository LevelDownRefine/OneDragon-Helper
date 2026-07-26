"""GUI 包：启动器界面按职责拆分的各模块。

- state: gui_state.json 读写与星期计算
- runner: ScriptChainer 命令构造与后台运行线程
- widgets: ToggleSwitch / ScriptItem 等自定义控件
- dialogs: 单脚本配置弹窗 / 添加脚本弹窗
- main_window: 主窗口

入口在 src/launcher.py（python -m src.launcher）。
"""
