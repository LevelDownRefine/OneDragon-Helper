"""配置界面的每日计划编辑；持久化和系统任务操作统一经 service。"""

import logging

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QMessageBox
from ruamel.yaml.error import YAMLError

from gui.daily_plan_dialog import DailyPlanDialog, DailyPlanListDialog
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
        listing = DailyPlanListDialog()
        plans = {}
        scripts = []

        def refresh():
            try:
                view = self._app_service.plans_list()
                plans.clear()
                plans.update({item["id"]: item for item in view["plans"]})
                scripts[:] = view.get("scripts", [])
                listing.set_plans(view["plans"])
            except (OSError, ValueError, YAMLError) as exc:
                listing.show_error(f"读取计划失败：{exc}")

        def edit_one(plan_id="", copy=False):
            item = plans.get(plan_id)
            if item is None:
                from src.service.daily_plan import DailyTaskState

                plan, state = DailyPlanOptions(), DailyTaskState()
                name = "新计划"
            else:
                from gui.controllers.cli_daily_plan import parse_plan_view

                plan, state = parse_plan_view(
                    {
                        **item,
                        "supported": True,
                        "shutdown_supported": True,
                    }
                )
                name = item["name"] + (" 副本" if copy else "")
            editor = DailyPlanDialog(plan, state, listing, name=name, scripts=scripts)

            def save():
                name_value = editor.name_edit.text().strip()
                if not name_value:
                    editor.show_error("请输入计划名称")
                    return
                try:
                    self._app_service.plans_save(
                        "" if copy else plan_id, name_value, editor.daily_plan
                    )
                except (OSError, ValueError, YAMLError) as exc:
                    editor.show_error(f"保存失败：{exc}")
                    return
                editor.accept()
                self.refresh()
                refresh()
                self._toast("计划已保存")

            editor.saveRequested.connect(save)
            editor.exec()

        def delete(plan_id):
            item = plans[plan_id]
            if (
                QMessageBox.question(listing, "删除计划", f"删除计划“{item['name']}”？")
                != QMessageBox.Yes
            ):
                return
            try:
                self._app_service.plans_delete(plan_id)
            except (OSError, ValueError, YAMLError) as exc:
                listing.show_error(f"删除失败：{exc}")
                return
            self.refresh()
            refresh()

        listing.addRequested.connect(lambda: edit_one())
        listing.editRequested.connect(edit_one)
        listing.copyRequested.connect(lambda plan_id: edit_one(plan_id, True))
        listing.deleteRequested.connect(delete)
        refresh()
        listing.exec()
