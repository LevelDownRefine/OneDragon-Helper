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
    RunOptions,
    _dump_run_options,
    _parse_run_options,
    is_valid_target_time,
    load_schedule,
    save_schedule,
)
from src.utils import get_root_dir
from src.utils.utils_config import load_config
from src.utils.utils_sub_config import get_script_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyPlanOptions:
    enabled: bool = False
    target_time: str = "04:10"
    run_options: RunOptions = RunOptions()

    def __post_init__(self):
        assert type(self.enabled) is bool
        assert is_valid_target_time(self.target_time)
        assert isinstance(self.run_options, RunOptions)


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
        """系统任务是否已与计划一致。"""
        if not options.enabled:
            return not self.exists
        return self.exists and self.enabled and self.target_time == options.target_time


def load_daily_plan(schedule: dict | None = None) -> DailyPlanOptions:
    """读取每日计划；未设置时默认关闭，非法值关闭并记诊断。

    每日计划对所有脚本生效，配置只记录启用状态、触发时间与独立运行选项，无脚本名单。
    旧 ``daily_run.script_names`` 残留忽略不读；``run_options`` 缺省为空白 RunOptions。
    """
    data = load_schedule() if schedule is None else schedule
    block = data.get("daily_run", None)
    if block is None:
        return DailyPlanOptions()
    if isinstance(block, dict):
        enabled = block.get("enabled", False)
        target = block.get("target_time", "04:10")
        if type(enabled) is bool and is_valid_target_time(target):
            run_options = (
                _parse_run_options(block["run_options"])
                if isinstance(block.get("run_options"), dict)
                else RunOptions()
            )
            return DailyPlanOptions(enabled, target, run_options)
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
    task = WindowsDailyTask()
    synced = not task.read().matches(options)
    if synced:
        task.sync(options)
    data["daily_run"] = {
        "enabled": options.enabled,
        "target_time": options.target_time,
        "run_options": _dump_run_options(options.run_options),
    }
    # 授权码（仅本次填写时）：注册进系统凭据管理器，避免明文落盘 schedule.yml。
    auth = options.run_options.auth_code
    if auth:
        try:
            from src.log.notify_mail import register_credentials

            register_credentials(options.run_options.email, auth)
        except Exception as exc:  # noqa: BLE001  # 凭据为最佳努力：失败记日志，不阻塞落盘
            logger.error(
                "[daily] 授权码写入系统凭据管理器失败(%s)：%s",
                type(exc).__name__,
                exc,
            )
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


def run_daily_plan() -> None:
    """按计划运行全部脚本，运行选项使用每日计划独立的 RunOptions。"""
    plan = load_daily_plan()
    if not plan.enabled:
        logger.info("[daily] 每日计划已关闭，跳过此次触发")
        return
    config = load_config()
    assert "script_list" in config
    scripts = {get_script_name(s) for s in config["script_list"]}
    if not scripts:
        logger.info("[daily] 没有可运行的脚本，跳过此次触发")
        return
    opts = plan.run_options
    # 邮件通知配置独立构造；notify 未启用或邮箱缺失则不发。
    smtp_config = None
    if opts.notify_enabled and opts.email:
        try:
            smtp_port = int(opts.smtp_port) if opts.smtp_port else None
        except ValueError:
            logger.warning("[daily] smtp_port 非法(%r)，邮件配置跳过", opts.smtp_port)
            smtp_port = None
        smtp_config = {
            "enabled": True,
            "email": opts.email,
            "smtp_host": opts.smtp_host,
            "smtp_port": smtp_port,
        }
    # 计划任务用独立链文件，避免与手动运行的 today.yml 互相覆盖。
    chain_service.schedule_run(
        scripts,
        "now",
        chain_name="plan",
        mute=opts.mute_enabled,
        unmute=opts.unmute_enabled,
        shutdown_delay=(
            opts.shutdown_delay
            if opts.shutdown_enabled and opts.shutdown_delay > 0
            else None
        ),
        close_running=opts.close_running_enabled,
        rerun_enabled=opts.rerun_enabled,
        smtp_config=smtp_config,
    )
