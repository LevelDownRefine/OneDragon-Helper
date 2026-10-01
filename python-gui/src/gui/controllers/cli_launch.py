"""运行确认与保存经 CLI；独立控制台的启动及 stdin 交付在后台完成。"""

import logging
import os
import subprocess
from dataclasses import asdict
from threading import Thread

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QMessageBox

from gui.controllers.cli_links import valid_command
from gui.controllers.cli_settings import parse_run_options
from gui.dialogs import show_warning, styled_msg_box
from gui.run_confirm_dialog import RunConfirmDialog

logger = logging.getLogger(__name__)


class RunStarter(QObject):
    started = Signal()
    failed = Signal(str)

    def start(self, target):
        """stdin 交付成功才报告启动；后续运行与 GUI 生命周期独立。"""

        def launch():
            child = None
            try:
                child = subprocess.Popen(
                    [target["program"], *target["args"]],
                    cwd=target["cwd"],
                    env={**os.environ, **target["env"]},
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                    if os.name == "nt"
                    else 0,
                    start_new_session=os.name != "nt",
                )
                assert child.stdin is not None
                with child.stdin:
                    child.stdin.write(target["input"].encode("utf-8"))
                self.started.emit()
            except (OSError, ValueError) as exc:
                logger.exception("交付运行配置失败")
                self.failed.emit(f"启动或传递运行配置失败：{exc}；请核对控制台后再操作")
            if child is not None:
                child.wait()

        Thread(target=launch, daemon=True, name="odh-run-start").start()


class CliLaunchController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, session, toast, parent=None):
        super().__init__(parent)
        self._game_list, self._session, self._toast = game_list, session, toast
        self.active = False
        self._starter = RunStarter(self)
        self._starter.started.connect(self._started)
        self._starter.failed.connect(self._failed_start)

    @Slot()
    def launchAll(self, confirm=True):
        if self.active or self._session.busy:
            self._toast("已有操作进行中，请稍候")
            return
        names = [
            game["script_name"]
            for game, enabled in zip(
                self._game_list.games, self._game_list.enabled, strict=True
            )
            if enabled
        ]
        if not names:
            self._toast("没有勾选手动运行的脚本")
            return
        self.active = True
        if not confirm:
            self._session.call(
                "run.saved", {"script_names": names}, self._target, self._failure
            )
            return

        def loaded(view):
            validate_run_view(view, names)
            if view["invalid"]:
                text = "\n".join(
                    f"· {row['name']}：{row['reason']}" for row in view["invalid"]
                )
                box = styled_msg_box(
                    None,
                    QMessageBox.Warning,
                    "脚本配置不合法",
                    f"以下脚本运行时会被跳过：\n{text}\n\n是否仍然运行？",
                )
                box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                box.setDefaultButton(QMessageBox.No)
                if box.exec() != QMessageBox.Yes:
                    self.active = False
                    return
            options = parse_run_options(view["options"])
            saving = False

            def submit(dialog):
                nonlocal saving
                if saving:
                    return
                if (
                    dialog.run_options.shutdown_enabled
                    and not view["shutdown_supported"]
                ):
                    show_warning(dialog, "此环境不支持自动关机，请取消该选项")
                    return
                if not self._session.hold():
                    show_warning(
                        dialog, "已有后台操作，或会话已失效，请关闭表单并重新读取"
                    )
                    return
                saving = True
                dialog.set_pending(True)

                def rejected(failure):
                    nonlocal saving
                    saving = False
                    dialog.set_pending(False)
                    self._session.release()
                    if dialog.isVisible():
                        show_warning(dialog, failure.message)
                    else:
                        self._failure(failure)

                def saved(target):
                    self._session.release()
                    validate_run_target(target)
                    dialog.set_pending(False)
                    dialog.accept()
                    self._target(target)

                self._session.call(
                    "run.prepare",
                    {
                        "script_names": names,
                        "options": asdict(dialog.run_options),
                        "confirm_invalid": bool(view["invalid"]),
                    },
                    saved,
                    rejected,
                )

            dialog = RunConfirmDialog(len(names), options, submit=submit)
            if dialog.exec() != QDialog.Accepted:
                self.active = False

        self._session.call("run.view", {"script_names": names}, loaded, self._failure)

    def _target(self, target):
        validate_run_target(target)
        self._starter.start(target)

    def _failure(self, failure):
        self.active = False
        self._toast(failure.message)

    def _started(self):
        self.active = False
        self._toast("手动运行：已在独立控制台启动，关闭控制台即取消")

    def _failed_start(self, message):
        self.active = False
        self._toast(message)


def validate_run_target(target):
    if (
        not isinstance(target, dict)
        or "kind" not in target
        or target["kind"] != "command"
        or not valid_command(target)
        or "console" not in target
        or target["console"] is not True
        or "input" not in target
        or not isinstance(target["input"], str)
    ):
        raise ValueError("运行命令无效")


def validate_run_view(view, names):
    if (
        not isinstance(view, dict)
        or not all(
            key in view
            for key in ("script_names", "invalid", "options", "shutdown_supported")
        )
        or not isinstance(view["script_names"], list)
        or not all(isinstance(name, str) for name in view["script_names"])
        or len(view["script_names"]) != len(names)
        or set(view["script_names"]) != set(names)
        or type(view["shutdown_supported"]) is not bool
        or not isinstance(view["invalid"], list)
    ):
        raise ValueError("运行确认数据无效")
    if not all(
        isinstance(row, dict)
        and all(key in row and isinstance(row[key], str) for key in ("name", "reason"))
        for row in view["invalid"]
    ):
        raise ValueError("配置校验信息无效")
    parse_run_options(view["options"])
