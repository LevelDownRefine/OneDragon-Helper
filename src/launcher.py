"""启动器入口：GUI 启动。

GUI 各部分在 src/gui 包中：state（状态持久化）、runner（后台运行）、
widgets（自定义控件）、dialogs（弹窗）、main_window（主窗口）。
无头 CLI 出口见 :mod:`src.cli`。
"""

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.cli import build_parser, run_cli
from src.config.subscript import generate_config_from_example
from src.gui.dialogs import inject_config_confirm
from src.gui.main_window import MainWindow
from src.service.chain_service import ChainService
from src.service.script_service import ScriptService
from src.utils import get_config_yml_path_under_root, get_path_under_root
from src.utils_logger import setup_logging


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 首次运行时从模板生成 config.yml（相对 script_path 解析为绝对路径）
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        generate_config_from_example()


def _set_app_window_icon(app):
    """把 assets/Chtholly.ico 设为应用窗口图标（标题栏/任务栏）。

    在 dev 与冻结（PyInstaller）两种模式下都能定位：dev 时 assets/ 在项目根，
    冻结时 build.bat 已把 assets/ 拷到 exe 同级目录，get_path_under_root 据此解析。
    图标缺失时静默跳过，不影响启动。
    """
    icon_path = get_path_under_root("assets", "Chtholly.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


def main():
    # 首次运行时，拷贝配置模板到用户目录
    if need_config_workflow():
        config_workflow()

    args = build_parser().parse_args()
    # 提前配置日志：CLI 出口（如 run_chain_command）也依赖 logger，
    # windowed exe 下 logs/onedragon_helper.log 是主要观测渠道。幂等，GUI 路径复用。
    setup_logging()

    # 非 GUI 的 CLI 出口：解析后即退出，不进入事件循环。
    exit_code = run_cli(args)
    if exit_code is not None:
        sys.exit(exit_code)

    # GUI 主路径
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _set_app_window_icon(app)
    inject_config_confirm()
    window = MainWindow(
        service=ChainService(),
        script_service=ScriptService(),
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
