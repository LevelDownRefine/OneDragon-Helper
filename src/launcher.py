"""启动器入口：GUI 启动。

GUI 各部分在 src/gui 包中：state（状态持久化）、runner（后台运行）、
widgets（自定义控件）、dialogs（弹窗）、main_window（主窗口）。
"""
import os
import sys

from PySide6.QtWidgets import QApplication

from src.config.bgi import copy_BGI_User
from src.config.subscript import generate_config_from_example
from src.gui.main_window import MainWindow
from src.utils import get_config_yml_path_under_root
from src.utils_logger import setup_logging


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 复制 BetterGI 用户配置
    copy_BGI_User()
    # 从模板生成 config.yml（如果不存在），相对 script_path 解析为绝对路径
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        generate_config_from_example()


def main():
    setup_logging()
    if need_config_workflow():
        config_workflow()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
