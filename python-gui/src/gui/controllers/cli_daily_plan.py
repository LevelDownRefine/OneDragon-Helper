"""每日计划的读取和系统任务注册使用同一 CLI 入口。"""

from dataclasses import asdict

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from gui.controllers.cli_settings import parse_run_options
from gui.daily_plan_dialog import DailyPlanDialog, DailyPlanListDialog
from src.service.daily_plan import DailyPlanOptions, DailyTaskState
from src.service.schedule import is_valid_target_time


class CliDailyPlanController(QObject):
    changed = Signal()

    def __init__(self, session, toast, parent=None):
        super().__init__(parent)
        self._session, self._toast = session, toast
        self.plan = DailyPlanOptions()
        self._opening = False

    def edit(self):
        if self._opening:
            return
        if self._session.busy:
            self._toast("已有后台操作，请稍候")
            return
        self._opening = True

        def failed(failure):
            self._opening = False
            self._toast(failure.message)

        def loaded(view):
            self._opening = False
            listing = DailyPlanListDialog()
            plans = {}
            scripts = []

            def update(value):
                plans.clear()
                plans.update({item["id"]: item for item in value["plans"]})
                scripts[:] = value.get("scripts", [])
                listing.set_plans(value["plans"])

            def refresh():
                self._session.call("plans.list", {}, update, error)

            def error(failure):
                listing.show_error(failure.message)

            def edit_one(plan_id="", copy=False):
                item = plans.get(plan_id)
                if item is None:
                    plan, state = DailyPlanOptions(), DailyTaskState()
                    name = "新计划"
                else:
                    wrapper = {**view, **item}
                    plan, state = parse_plan_view(wrapper)
                    name = item["name"] + (" 副本" if copy else "")
                editor = DailyPlanDialog(
                    plan, state, listing, name=name, scripts=scripts
                )
                if item is not None and item["state_error"]:
                    editor.state_label.setText(
                        f"系统任务：读取失败（{item['state_error']}）"
                    )
                saving = False

                def save():
                    nonlocal saving
                    name_value = editor.name_edit.text().strip()
                    if not name_value:
                        editor.show_error("请输入计划名称")
                        return
                    options = editor.daily_plan
                    if options.enabled and not view["supported"]:
                        editor.show_error("此环境无法启用每日计划")
                        return
                    if (
                        options.run_options.shutdown_enabled
                        and not view["shutdown_supported"]
                    ):
                        editor.show_error("此环境不支持自动关机，请取消该选项")
                        return
                    if saving or not self._session.hold():
                        editor.show_error("已有后台操作，请稍候")
                        return
                    saving = True
                    editor.set_pending(True)

                    def rejected(failure):
                        nonlocal saving
                        saving = False
                        editor.set_pending(False)
                        self._session.release()
                        editor.show_error(failure.message)

                    def saved(_value):
                        self._session.release()
                        editor.set_pending(False)
                        editor.accept()
                        self.changed.emit()
                        refresh()

                    self._session.call(
                        "plans.save",
                        {
                            "id": "" if copy else plan_id,
                            "name": name_value,
                            **asdict(options),
                        },
                        saved,
                        rejected,
                    )

                editor.saveRequested.connect(save)
                editor.exec()

            def delete(plan_id):
                item = plans[plan_id]
                if (
                    QMessageBox.question(
                        listing, "删除计划", f"删除计划“{item['name']}”？"
                    )
                    != QMessageBox.Yes
                ):
                    return

                def deleted(_value):
                    self.changed.emit()
                    refresh()

                self._session.call("plans.delete", {"id": plan_id}, deleted, error)

            listing.addRequested.connect(lambda: edit_one())
            listing.editRequested.connect(edit_one)
            listing.copyRequested.connect(lambda plan_id: edit_one(plan_id, True))
            listing.deleteRequested.connect(delete)
            update(view)
            listing.exec()

        self._session.call("plans.list", {}, loaded, failed)


def parse_plan_view(view):
    if (
        not isinstance(view, dict)
        or not all(
            key in view
            for key in (
                "plan",
                "state",
                "state_error",
                "supported",
                "shutdown_supported",
            )
        )
        or not all(
            type(view[key]) is bool for key in ("supported", "shutdown_supported")
        )
        or (
            view["state_error"] is not None and not isinstance(view["state_error"], str)
        )
    ):
        raise ValueError("每日计划数据无效")
    plan = view["plan"]
    if (
        not isinstance(plan, dict)
        or not {"enabled", "target_time", "run_options"} <= set(plan)
        or not set(plan)
        <= {"enabled", "target_time", "run_options", "selected_scripts"}
        or type(plan["enabled"]) is not bool
        or not isinstance(plan["target_time"], str)
        or not is_valid_target_time(plan["target_time"])
    ):
        raise ValueError("每日计划字段无效")
    selected = plan.get("selected_scripts")
    if selected is not None and (
        not isinstance(selected, list)
        or not all(isinstance(s, str) and s for s in selected)
    ):
        raise ValueError("每日计划脚本选择无效")
    options = DailyPlanOptions(
        plan["enabled"],
        plan["target_time"],
        parse_run_options(plan["run_options"]),
        selected,
    )
    state = view["state"]
    if state is None:
        if not view["state_error"]:
            raise ValueError("系统任务状态缺失")
        return options, DailyTaskState()
    if (
        not isinstance(state, dict)
        or set(state) != {"exists", "enabled", "target_time", "entry_matches"}
        or not all(
            type(state[key]) is bool for key in ("exists", "enabled", "entry_matches")
        )
        or not isinstance(state["target_time"], str)
    ):
        raise ValueError("系统任务状态无效")
    return options, DailyTaskState(**state)
