"""启动与运行设置通过共享 CLI 会话查询和提交。"""

from dataclasses import asdict

from gui.config_dialog import ConfigDialog
from gui.controllers.backup import BackupController
from gui.dialogs import show_warning
from gui.run_confirm_dialog import RunConfirmDialog
from src.service.daily_plan import DailyPlanOptions
from src.service.schedule import RunOptions, StartupOptions


def parse_run_options(value):
    defaults = asdict(RunOptions())
    if (
        not isinstance(value, dict)
        or set(value) != set(defaults)
        or any(
            type(value[key]) is not type(default) for key, default in defaults.items()
        )
        or value["shutdown_delay"] < 0
    ):
        raise ValueError("运行选项无效")
    return RunOptions(**value)


def parse_settings(value):
    if (
        not isinstance(value, dict)
        or not all(
            key in value
            for key in ("startup", "daily_enabled", "run_options", "shutdown_supported")
        )
        or type(value["daily_enabled"]) is not bool
        or type(value["shutdown_supported"]) is not bool
    ):
        raise ValueError("设置数据无效")
    startup = value["startup"]
    if (
        not isinstance(startup, dict)
        or set(startup) != {"enabled", "delay_seconds"}
        or type(startup["enabled"]) is not bool
        or type(startup["delay_seconds"]) is not int
        or not 1 <= startup["delay_seconds"] <= 3600
    ):
        raise ValueError("启动选项无效")
    return StartupOptions(**startup), parse_run_options(value["run_options"])


class CliSettingsController(BackupController):
    def __init__(self, app_service, session, toast, parent=None):
        super().__init__(app_service, toast, parent)
        self._session = session
        self._opening = False

    def openConfig(self):
        if self._opening:
            return
        self._opening = True

        def failed(failure):
            self._opening = False
            self._toast(failure.message)

        def loaded(view):
            self._opening = False
            options, _ = parse_settings(view)
            dialog = ConfigDialog(
                startup_options=options,
                daily_plan=DailyPlanOptions(enabled=view["daily_enabled"]),
            )
            actions = {
                "daily": self.daily_plan.edit,
                "backup": self.backupConfig,
                "restore": self.restoreConfig,
                "settings": self.configureRunOptions,
                "update": lambda: self.update.open(dialog),
            }

            def dispatch(action):
                assert action in actions
                actions[action]()
                if action == "daily":
                    self._session.call(
                        "settings.view",
                        {},
                        refresh,
                        lambda failure: dialog.show_error(failure.message),
                    )

            def refresh(view):
                parse_settings(view)
                dialog.set_daily_plan_enabled(view["daily_enabled"])

            saving = False

            def save():
                nonlocal saving
                if saving:
                    return
                saving = True

                def rejected(failure):
                    nonlocal saving
                    saving = False
                    if dialog.isVisible():
                        dialog.show_error(failure.message)
                    else:
                        self._toast(failure.message)

                def saved(result):
                    if result is not None:
                        raise ValueError("保存响应应返回 null")
                    dialog.accept()
                    self._toast("启动设置已保存")

                self._session.call(
                    "settings.startup_save",
                    {"options": asdict(dialog.startup_options)},
                    saved,
                    rejected,
                )

            dialog.actionRequested.connect(dispatch)
            dialog.saveRequested.connect(save)
            dialog.exec()

        self._session.call("settings.view", {}, loaded, failed)

    def configureRunOptions(self):
        def loaded(view):
            _, options = parse_settings(view)
            saving = False

            def submit(dialog):
                nonlocal saving
                if saving:
                    return
                saving = True

                def rejected(failure):
                    nonlocal saving
                    saving = False
                    if dialog.isVisible():
                        show_warning(dialog, failure.message)
                    else:
                        self._toast(failure.message)

                def saved(result):
                    if result is not None:
                        raise ValueError("保存响应应返回 null")
                    dialog.accept()
                    self._toast("运行选项已保存，下次运行生效")

                self._session.call(
                    "settings.run_save",
                    {"options": asdict(dialog.run_options)},
                    saved,
                    rejected,
                )

            dialog = RunConfirmDialog(0, options, settings_only=True, submit=submit)
            dialog.exec()

        self._session.call(
            "settings.view", {}, loaded, lambda failure: self._toast(failure.message)
        )
