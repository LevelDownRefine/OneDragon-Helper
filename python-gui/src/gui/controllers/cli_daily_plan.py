"""每日计划的读取和系统任务注册使用同一 CLI 入口。"""

from dataclasses import asdict

from PySide6.QtCore import QObject, Signal

from gui.controllers.cli_settings import parse_run_options
from gui.daily_plan_dialog import DailyPlanDialog
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
        if self._opening or self._session.busy:
            return
        self._opening = True

        def failed(failure):
            self._opening = False
            self._toast(failure.message)

        def loaded(view):
            self._opening = False
            plan, state = parse_plan_view(view)
            self.plan = plan
            dialog = DailyPlanDialog(plan, state)
            if view["state_error"]:
                dialog.state_label.setText(
                    f"系统任务：读取失败（{view['state_error']}）"
                )
            if not view["supported"]:
                dialog.show_error("此环境无法启用每日计划；可保存停用设置")
            saving = False

            def save():
                nonlocal saving
                if saving:
                    return
                if not self._session.hold():
                    dialog.show_error(
                        "已有后台操作，或会话已失效，请关闭表单并重新读取"
                    )
                    return
                saving = True
                dialog.set_pending(True)
                options = dialog.daily_plan
                if (
                    options.run_options.shutdown_enabled
                    and not view["shutdown_supported"]
                ):
                    saving = False
                    dialog.set_pending(False)
                    self._session.release()
                    dialog.show_error("此环境不支持自动关机，请取消该选项")
                    return
                if options.enabled and not view["supported"]:
                    saving = False
                    dialog.set_pending(False)
                    self._session.release()
                    dialog.show_error("此环境无法启用每日计划")
                    return

                def rejected(failure):
                    nonlocal saving
                    saving = False
                    dialog.set_pending(False)
                    self._session.release()
                    if dialog.isVisible():
                        dialog.show_error(failure.message)
                    else:
                        self._toast(failure.message)

                def saved(value):
                    self._session.release()
                    if value is not None:
                        raise ValueError("每日计划保存响应无效")
                    self.plan = options
                    dialog.set_pending(False)
                    dialog.accept()
                    self.changed.emit()
                    self._toast("每日计划已保存")

                self._session.call(
                    "plan.save", {"plan": asdict(options)}, saved, rejected
                )

            dialog.saveRequested.connect(save)
            dialog.exec()

        self._session.call("plan.view", {}, loaded, failed)


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
        or set(plan) != {"enabled", "target_time", "run_options"}
        or type(plan["enabled"]) is not bool
        or not isinstance(plan["target_time"], str)
        or not is_valid_target_time(plan["target_time"])
    ):
        raise ValueError("每日计划字段无效")
    options = DailyPlanOptions(
        plan["enabled"], plan["target_time"], parse_run_options(plan["run_options"])
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
