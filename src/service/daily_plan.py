"""每日计划：Windows 负责触发，运行入口每次读取最新配置。

系统任务里只有触发时间和 ``--run-daily`` 入口，脚本名单与运行选项留在 schedule.yml，
故「每日计划是否生效」有两个来源：yml 是设置意图，系统任务是实际事实。两者会被用户
手动改动而分叉，因此界面回显实际状态（:class:`DailyTaskState`），保存时按回读结果
判断是否要重新注册。
"""

import getpass
import hashlib
import logging
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from ruamel.yaml.error import YAMLError

import src.service.chain_service as chain_service
from src.service.schedule import (
    is_valid_target_time,
    load_run_options,
    load_schedule,
    save_schedule,
)
from src.utils import get_root_dir
from src.utils.utils_config import load_config, script_enabled
from src.utils.utils_sub_config import get_script_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyPlanOptions:
    enabled: bool = False
    target_time: str = "04:10"
    script_names: tuple[str, ...] = ()

    def __post_init__(self):
        assert type(self.enabled) is bool
        assert is_valid_target_time(self.target_time)
        assert isinstance(self.script_names, tuple)
        assert all(isinstance(name, str) and name for name in self.script_names)
        assert len(set(self.script_names)) == len(self.script_names)


@dataclass(frozen=True)
class DailyTaskState:
    """系统任务的实际状态，由 ``WindowsDailyTask.read()`` 回读。

    未注册时三项均为缺省值。``target_time`` 为空串表示触发器时刻读不出来
    （无触发器或格式异常），此时按与设置不一致处理，保存会重新注册。
    """

    exists: bool = False
    enabled: bool = False
    target_time: str = ""

    def matches(self, options: DailyPlanOptions) -> bool:
        """系统任务是否已与计划一致（脚本名单只存在于 schedule.yml，不参与比对）。"""
        if not options.enabled:
            return not self.exists
        return self.exists and self.enabled and self.target_time == options.target_time


def load_daily_plan(schedule: dict | None = None) -> DailyPlanOptions:
    """读取每日计划；未设置时默认关闭，非法值关闭并记诊断。"""
    data = load_schedule() if schedule is None else schedule
    # daily_run 可缺省，缺失时使用默认值。
    block = data.get("daily_run", None)
    if block is None:
        return DailyPlanOptions()
    if isinstance(block, dict):
        enabled = block.get("enabled", False)
        target = block.get("target_time", "04:10")
        if type(enabled) is bool and is_valid_target_time(target):
            if "script_names" not in block:
                # 旧计划只继承一次当前勾选，之后与手动选择独立。
                names = []
                if enabled:
                    config = load_config()
                    assert "script_list" in config
                    names = [
                        get_script_name(script)
                        for script in config["script_list"]
                        if script_enabled(script)
                    ]
                if schedule is None:
                    block["script_names"] = names
                    save_schedule(data)
            else:
                names = block["script_names"]
            if (
                isinstance(names, list)
                and all(isinstance(name, str) and name for name in names)
                and len(set(names)) == len(names)
            ):
                return DailyPlanOptions(enabled, target, tuple(names))
    logger.warning("[daily] 每日计划配置无效，按关闭处理")
    return DailyPlanOptions()


@contextmanager
def _task_service():
    """使用 Windows 自带 COM 接口，不依赖 PowerShell 文本或命令转义。"""
    if sys.platform != "win32":
        raise OSError("每日计划仅支持 Windows")
    import pythoncom
    from win32com.client.dynamic import Dispatch

    initialized = False
    service = None
    try:
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            initialized = True
        except pythoncom.com_error as exc:
            if (
                exc.hresult != -2147417850
            ):  # RPC_E_CHANGED_MODE：使用已有 COM apartment。
                raise
        service = Dispatch("Schedule.Service")
        service.Connect()
        yield service
    except pythoncom.com_error as exc:
        if exc.hresult == -2147024891:  # E_ACCESSDENIED
            raise OSError("权限不足，请以管理员身份打开助手后重新保存每日计划") from exc
        raise OSError(f"Windows 任务计划操作失败：{exc}") from exc
    finally:
        service = None
        if initialized:
            pythoncom.CoUninitialize()


def _trigger_time(task) -> str:
    """取任务首个触发器的 ``HH:MM``；无触发器或格式异常时返回空串。"""
    triggers = task.Definition.Triggers
    if triggers.Count == 0:
        return ""
    match = re.search(r"T(\d{2}:\d{2})", str(triggers.Item(1).StartBoundary))
    return match.group(1) if match else ""


class WindowsDailyTask:
    """按安装目录和用户区分任务；更新同一个任务，关闭时删除。"""

    def __init__(self, root_dir: str | None = None):
        self.root_dir = os.path.abspath(root_dir or get_root_dir())
        identity = os.path.normcase(self.root_dir) + "\0" + getpass.getuser()
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        self.name = f"OneDragon-Helper-Daily-{digest}"

    def read(self) -> DailyTaskState:
        """回读当前安装对应的系统任务；未注册返回缺省状态。"""
        with _task_service() as service:
            folder = None
            try:
                folder = service.GetFolder("\\")
                # GetTasks(1) 与 sync 同源，含隐藏任务，口径一致。
                for task in folder.GetTasks(1):
                    if task.Name == self.name:
                        return DailyTaskState(
                            True, bool(task.Enabled), _trigger_time(task)
                        )
                return DailyTaskState()
            finally:
                # COM 包装对象须先释放，之后才能 CoUninitialize。
                folder = service = None

    def sync(self, options: DailyPlanOptions) -> None:
        """注册每日交互任务，或删除当前安装对应的任务。"""
        with _task_service() as service:
            folder = definition = settings = trigger = action = None
            try:
                folder = service.GetFolder("\\")
                if not options.enabled:
                    # GetTasks(1) 包括隐藏任务，避免把访问错误当作任务不存在。
                    if any(task.Name == self.name for task in folder.GetTasks(1)):
                        folder.DeleteTask(self.name, 0)
                    return

                definition = service.NewTask(0)
                definition.RegistrationInfo.Description = (
                    f"OneDragon-Helper 每日按最新配置运行：{self.root_dir}"
                )
                definition.Principal.LogonType = 3  # 已登录用户的交互会话，不保存密码。
                definition.Principal.RunLevel = 1  # 与游戏自动化所需的管理员权限一致。
                settings = definition.Settings
                settings.Enabled = True
                settings.MultipleInstances = 2  # IgnoreNew，禁止同一系统任务重叠。
                settings.StartWhenAvailable = False  # 错过不在其他时间突然补跑。
                settings.DisallowStartIfOnBatteries = False
                settings.StopIfGoingOnBatteries = False
                settings.ExecutionTimeLimit = "PT0S"  # 由各脚本超时配置控制。
                settings.WakeToRun = False
                trigger = definition.Triggers.Create(2)  # TASK_TRIGGER_DAILY
                hour, minute = map(int, options.target_time.split(":"))
                now = datetime.now()
                start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if start <= now:
                    start += timedelta(days=1)
                trigger.StartBoundary = start.isoformat()
                trigger.DaysInterval = 1
                trigger.Enabled = True
                action = definition.Actions.Create(0)  # TASK_ACTION_EXEC
                action.Path = sys.executable
                args = ["--run-daily"]
                if not getattr(sys, "frozen", False):
                    args = ["-m", "src.launcher", *args]
                action.Arguments = subprocess.list2cmdline(args)
                action.WorkingDirectory = self.root_dir
                folder.RegisterTaskDefinition(self.name, definition, 6, "", "", 3)
            finally:
                # COM 包装对象须先释放，之后才能 CoUninitialize。
                action = trigger = settings = definition = folder = service = None


def apply_daily_plan(options: DailyPlanOptions) -> None:
    """先更新系统任务再保存配置；写盘失败时恢复原计划。

    是否重新注册「回读系统任务后再判断」，而不是只比 yml 里的旧值：用户在任务计划
    程序里删掉或禁用过任务时，再次保存同样的设置也能重新注册。
    """
    assert isinstance(options, DailyPlanOptions)
    data = load_schedule()
    previous = load_daily_plan(data)
    if options.enabled:
        available = {name for name, _label in list_daily_plan_scripts()}
        if not options.script_names:
            raise ValueError("请至少选择一个参加每日计划的脚本")
        missing = set(options.script_names) - available
        if missing:
            raise ValueError(f"脚本已移除，请重新选择：{'、'.join(sorted(missing))}")
    task = WindowsDailyTask()
    synced = not task.read().matches(options)
    if synced:
        task.sync(options)
    data["daily_run"] = {
        "enabled": options.enabled,
        "target_time": options.target_time,
        "script_names": list(options.script_names),
    }
    try:
        save_schedule(data)
    except (OSError, YAMLError):
        try:
            if synced:
                task.sync(previous)
        except OSError:
            logger.exception("[daily] 保存失败后恢复系统任务也失败，请重新设置每日计划")
        raise


def read_daily_task_state() -> DailyTaskState:
    """回读系统任务实际状态供界面回显；读不到时按未注册处理并记诊断。"""
    try:
        return WindowsDailyTask().read()
    except OSError as exc:
        logger.warning("[daily] 读取系统任务状态失败，按未注册处理：%s", exc)
        return DailyTaskState()


def list_daily_plan_scripts() -> list[tuple[str, str]]:
    """返回可选脚本的标识与展示名，不受手动勾选限制。"""
    config = load_config()
    assert "script_list" in config
    choices = []
    for script in config["script_list"]:
        assert "display_name" in script
        choices.append((get_script_name(script), script["display_name"]))
    return choices


def run_daily_plan() -> None:
    """按计划独立保存的脚本名单运行，副本与运行选项读取最新配置。"""
    plan = load_daily_plan()
    if not plan.enabled:
        logger.info("[daily] 每日计划已关闭，跳过此次触发")
        return
    config = load_config()
    assert "script_list" in config
    available = {get_script_name(s) for s in config["script_list"]}
    enabled = set(plan.script_names) & available
    missing = set(plan.script_names) - available
    if missing:
        logger.warning(
            "[daily] 计划中的脚本已移除，跳过：%s", "、".join(sorted(missing))
        )
    if not enabled:
        logger.info("[daily] 计划没有可运行的脚本，跳过此次触发")
        return
    options = load_run_options()
    chain_service.schedule_run(
        enabled,
        "now",
        mute=options.mute_enabled,
        unmute=options.unmute_enabled,
        shutdown_delay=(
            options.shutdown_delay
            if options.shutdown_enabled and options.shutdown_delay > 0
            else None
        ),
        close_running=options.close_running_enabled,
    )
