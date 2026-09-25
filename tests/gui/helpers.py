"""GUI 测试共享夹具；导入时不创建应用或读取配置。"""

import os
from copy import deepcopy
from unittest.mock import MagicMock, patch

_app = None

_SCRIPTS = [
    {
        "display_name": "鸣潮",
        "script_path": "scripts/ok-ww/ok-ww.exe",
        "script_type": "external",
    },
    {
        "display_name": "测试脚本",
        "script_path": "scripts/t.py",
        "script_type": "python",
    },
]


def get_app():
    """按需创建并持有无头应用，供窗口与图像测试显式调用。"""
    global _app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    return _app


def make_bridge():
    """构造隔离配置 I/O 的桥接对象，每次使用独立的脚本条目。"""
    get_app()
    from src.gui.main_window import QmlBridge
    from src.service.app_service import AppService
    from src.service.daily_plan import DailyPlanOptions

    with (
        patch(
            "src.utils.utils_sub_config._load_config_yml",
            return_value={"script_list": []},
        ),
        patch.object(
            AppService, "load_config", return_value={"script_list": deepcopy(_SCRIPTS)}
        ),
        patch("src.service.daily_plan.load_schedule", return_value={}),
    ):
        b = QmlBridge()
    b.app_service.load_config = MagicMock(
        return_value={"script_list": deepcopy(_SCRIPTS)}
    )
    # 构造后的重排、添加和计划操作同样隔离 I/O。
    b.app_service.load_daily_plan = MagicMock(return_value=DailyPlanOptions())
    b.app_service.save_config = MagicMock()
    return b
