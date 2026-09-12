"""配置界面的每日计划编辑；持久化和系统任务操作统一经 service。"""

import logging

from PySide6.QtCore import QObject, Slot
from ruamel.yaml.error import YAMLError

from src.gui.daily_plan_dialog import DailyPlanDialog
from src.service.daily_plan import DailyPlanOptions

logger = logging.getLogger(__name__)


class DailyPlanController(QObject):
    def __init__(self, app_service, toast, parent=None):
        super().__init__(parent)
        self._app_service = app_service
        self._toast = toast
        self.plan = DailyPlanOptions()

    @Slot()
    def refresh(self):
        """读取保存后的计划，兼容旧计划并供配置界面回显开关。"""
        try:
            self.plan = self._app_service.load_daily_plan()
        except (OSError, YAMLError) as exc:
            logger.error("读取每日计划失败：%s: %s", type(exc).__name__, exc)
            return

    @Slot()
    def edit(self):
        try:
            plan = self._app_service.load_daily_plan()
            scripts = self._app_service.list_daily_plan_scripts()
        except (OSError, YAMLError) as exc:
            logger.error("读取每日计划失败：%s: %s", type(exc).__name__, exc)
            self._toast(f"读取每日计划失败：{exc}")
            return
        dialog = DailyPlanDialog(plan, scripts)

        def save():
            try:
                self._app_service.apply_daily_plan(dialog.daily_plan)
            except (OSError, ValueError, YAMLError) as exc:
                logger.error("保存每日计划失败：%s: %s", type(exc).__name__, exc)
                dialog.show_error(f"保存失败：{exc}")
                return
            dialog.accept()
            self.refresh()
            self._toast("每日计划已保存")

        dialog.saveRequested.connect(save)
        dialog.exec()
