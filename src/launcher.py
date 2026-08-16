"""启动器入口：GUI 启动。

GUI 主窗口在 src/gui（LauncherWindow）；单脚本配置弹窗在 src/gui/dialogs.py。
无头 CLI 出口见 :mod:`src.cli`（本模块的 --generate-chain / --run-chain 等命令行参数）。
"""

import logging
import os
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from src.cli import build_parser, run_cli
from src.config.subscript import generate_config_from_example
from src.gui.dialogs import inject_config_confirm
from src.gui.main_window import LauncherWindow
from src.gui.theme import FONT_FAMILY
from src.utils import get_config_yml_path_under_root, get_path_under_root
from src.utils_logger import setup_logging

logger = logging.getLogger(__name__)

# 启动耗时打点基准（模块导入完成后、main() 入口处归零）
_STARTUP_T0 = time.perf_counter()


def _log_startup(stage: str) -> None:
    """记录启动阶段耗时：相对 main() 入口的毫秒数（供启动性能分析）。"""
    elapsed_ms = (time.perf_counter() - _STARTUP_T0) * 1000
    logger.info("[startup] %-30s %8.1f ms", stage, elapsed_ms)


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 首次运行时从模板生成 config.yml（相对 script_path 解析为绝对路径）
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        generate_config_from_example()


def _set_app_window_icon(app):
    """把 assets/ds.ico 设为应用窗口图标（标题栏/任务栏）。

    在 dev 与冻结（PyInstaller）两种模式下都能定位：dev 时 assets/ 在项目根，
    冻结时 build.bat 已把 assets/ 拷到 exe 同级目录，get_path_under_root 据此解析。
    图标缺失时静默跳过，不影响启动。
    """
    icon_path = get_path_under_root("assets", "ds.ico")
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
    # 模块导入耗时（_STARTUP_T0 之前）由 python -X importtime 观测；
    # 此处起记录 main() 内各阶段耗时。
    _log_startup("main() 初始化（config_workflow/parse_args/setup_logging）")

    # 非 GUI 的 CLI 出口：解析后即退出，不进入事件循环。
    exit_code = run_cli(args)
    if exit_code is not None:
        sys.exit(exit_code)
    _log_startup("run_cli")

    # GUI 主路径
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # 新 GUI 的 QSS 只设 font-size 未设 font-family，需显式设置应用默认字体
    # （与 main_window.main() 一致），否则中文字符会 fallback 到宋体
    app.setFont(QFont(FONT_FAMILY))
    _set_app_window_icon(app)
    _log_startup("QApplication + setStyle + icon")

    inject_config_confirm()
    _log_startup("inject_config_confirm")

    window = LauncherWindow()
    _log_startup("LauncherWindow 构造")

    window.show()
    _log_startup("window.show()")

    # 仅用于启动耗时自动测量：设置 ODH_AUTOQUIT_MS 后，show 完定时退出事件循环。
    # 正常运行（未设置该环境变量）时不影响任何行为。
    autoquit_ms = os.environ.get("ODH_AUTOQUIT_MS")
    if autoquit_ms:
        QTimer.singleShot(int(autoquit_ms), app.quit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
