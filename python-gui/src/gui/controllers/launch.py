"""启动 / 运行控制器：启动全部 / 启动当前脚本 / 运行前确认。

「启动全部」与 Rust 前端同一协议：``run.view``（校验与选项回显）→
``run.prepare`` / ``run.saved``（返回独立运行命令，选项经 stdin 交付）→
复用 ``RunStarter`` 以独立控制台 Popen 并写入载荷。GUI 只做确认交互与启动。
"""

import os
import subprocess

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QDialog, QMessageBox

from gui.controllers.cli_launch import RunStarter, validate_run_target
from gui.controllers.cli_settings import parse_run_options
from gui.dialogs import styled_msg_box
from gui.run_confirm_dialog import RunConfirmDialog
from src.service.chain_service import InvalidRunRequest
from src.utils import open_in_explorer


class LaunchController(QObject):
    toastRequested = Signal(str)

    def __init__(self, game_list, task_card, app_service, toast, parent=None):
        super().__init__(parent)
        self._game_list = game_list
        self._task_card = task_card
        self._app_service = app_service
        self._toast = toast
        self._starter = RunStarter(self)
        self._starter.started.connect(self._started)
        self._starter.failed.connect(self._failed_start)

    @Slot()
    def launchAll(self, confirm: bool = True):
        """启动全部：确认后经 run.prepare / run.saved 取运行命令并交付 stdin。

        运行在新控制台进程（``RunStarter`` 以 ``CREATE_NEW_CONSOLE`` 起）中进行，
        ``chain_service.schedule_run`` 处理生成→运行→重跑→邮件/关机。GUI 退出
        不影响运行，关闭控制台即取消。

        Args:
            confirm: 是否弹运行前确认窗（含不合法告警与调度配置回显）。GUI 打开后的
                无人值守启动传 ``False``，直接按上次落盘的选项启动全部。
        """
        enabled_script_names = {
            g["script_name"]
            for g, game_enabled in zip(
                self._game_list.games, self._game_list.enabled, strict=True
            )
            if game_enabled
        }
        if not enabled_script_names:
            self._toast("没有勾选手动运行的脚本")
            return
        try:
            if confirm:
                target = self._confirm_and_prepare(enabled_script_names)
                if target is None:
                    return
            else:
                target = self._app_service.saved_run(sorted(enabled_script_names))
        except InvalidRunRequest as exc:
            # 名单校验失败（脚本已被移除等），刷新列表即可恢复
            self._toast(str(exc))
            return
        validate_run_target(target)
        self._starter.start(target)

    def _confirm_and_prepare(self, enabled_keys: set) -> dict | None:
        """运行前校验并确认；确认后保存选项并返回运行命令（取消返回 None）。"""
        names = sorted(enabled_keys)
        view = self._app_service.run_view(names)
        if view["invalid"]:
            details = "\n".join(
                f"· {row['name']}：{row['reason']}" for row in view["invalid"]
            )
            box = styled_msg_box(
                None,
                QMessageBox.Warning,
                "脚本配置不合法",
                f"以下脚本配置不合法，运行时会被跳过：\n{details}\n\n是否仍然运行？",
            )
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            box.setDefaultButton(QMessageBox.No)
            if box.exec() != QMessageBox.Yes:
                return None

        # 回显 schedule 当前运行选项到确认弹窗（RunOptions 为单一 schema）。
        options = parse_run_options(view["options"])
        dialog = RunConfirmDialog(len(enabled_keys), options)
        if dialog.exec() != QDialog.Accepted:
            return None

        # 勾选项经 prepare_run 整体落盘（schedule.yml + 授权码凭据）并取运行命令。
        res = dialog.run_options
        assert res is not None, "[launch] 弹窗 accept 但 run_options 为 None"
        return self._app_service.prepare_run(
            names, res, confirm_invalid=bool(view["invalid"])
        )

    @Slot()
    def launchScript(self):
        """启动当前选中脚本（直接运行，不走链）。"""
        game = self._game_list.current_game
        if game is None:
            self._toast("尚无脚本")
            return
        target = self._app_service.resolve_launch_target(game["script_name"], "script")
        assert "kind" in target
        if target["kind"] == "unavailable":
            assert "reason" in target
            self._toast(f"{game['display_name']}：{target['reason']}")
            return
        if target["kind"] == "command":
            assert all(key in target for key in ("program", "args", "cwd", "env"))
            # service 只返回覆盖项；继承当前环境，保留 PATH 等运行依赖。
            environment = {**os.environ, **target["env"]} if target["env"] else None
            subprocess.Popen(
                [target["program"], *target["args"]],
                cwd=target["cwd"],
                env=environment,
            )
        else:
            assert target["kind"] == "association" and "path" in target
            open_in_explorer(target["path"])  # noqa: S606 启动脚本本体
        self._toast(f"已启动 {game['display_name']}")

    def _started(self):
        self._toast("手动运行：已在独立控制台启动，关闭控制台即取消")

    def _failed_start(self, message: str):
        self._toast(message)
