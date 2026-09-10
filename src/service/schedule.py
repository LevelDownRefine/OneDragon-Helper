"""调度运行编排 + schedule.yml 读写：RunOptions schema 与 ScheduledRun 生命周期。

schedule.yml（调度运行参数：shutdown / mute / unmute / rerun /
notify / close_running）的读写归本模块：``load_schedule`` / ``save_schedule``，
其 notify 块经 ``resolve_mail_config`` 解析为 SMTP 配置。六个选项块的
单一 schema 是 :class:`RunOptions`——确认窗回显（``load_run_options``）与
落盘（``apply_run_options``）共用同一类型，GUI 不感知 yml 键名。
``StartupOptions`` 单独管理 startup 块（打开 GUI 后自动启动的开关与秒数），
缺项默认启用 60 秒倒计时，与运行确认窗的 RunOptions 分开读写。

``ScheduledRun`` 是一个带生命周期的对象，而非纯函数：它在独立控制台进程
（由 ``utils_runner.spawn_schedule_run`` 以 ``CREATE_NEW_CONSOLE`` 起）中运行，
故前置阻塞等待（``time.sleep``）无害；关闭该控制台即取消。

编排固定为：pre_run → （等待到点）→ 生成脚本链并运行 → 可选重跑轮 → post_run。
pre_run / post_run 为可扩展的 step 列表（Callable 序列），由本模块的
``build_pre_run_pipeline`` / ``build_post_run_pipeline`` 在初始化时组装：
两个工厂只负责「按什么顺序、在什么条件下跑哪些步骤」，各步骤的具体动作
在 ``src.service.run_actions``。
"""

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import src.utils.utils_config as utils_config
import src.utils.utils_weekly as utils_weekly
from src.log.notify_mail import register_credentials
from src.service.run_actions import (
    analyze_logs,
    apply_subscript_config,
    close_running_scripts,
    send_summary_mail,
    wait_until_target,
)
from src.utils import get_schedule_yml_path_under_root
from src.utils.utils_mute import mute_off, mute_on
from src.utils.utils_shutdown import shutdown_sys
from src.utils.utils_yaml import dump_yaml, load_yaml

logger = logging.getLogger(__name__)

# 定时运行的目标时刻格式：HH:MM（24 小时制）。
_TIME_RE = re.compile(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")


def is_valid_target_time(value: str) -> bool:
    """判断是否为合法目标时刻 ``HH:MM``（24 小时制）。"""
    return isinstance(value, str) and bool(_TIME_RE.match(value))


def load_schedule() -> dict:
    """读取 schedule.yml（缺失时从 schedule.example.yml 生成），返回调度运行参数。

    调度参数（shutdown / mute / unmute / rerun / notify）独立于 config.yml
    存放，避免与脚本链声明（script_list）耦合。
    """
    return load_yaml(get_schedule_yml_path_under_root())


def save_schedule(data: dict) -> None:
    """写回 schedule.yml（生成目标，不要求已存在）。

    Args:
        data: 完整调度运行参数字典（由调用方原地修改后传入）。
    """
    assert isinstance(data, dict), "[schedule] 待保存的 schedule 非 dict"
    dump_yaml(get_schedule_yml_path_under_root(), data)


MAX_STARTUP_DELAY_SECONDS = 3600


@dataclass(frozen=True)
class StartupOptions:
    """打开 GUI 后的自动启动设置；默认保持历史的 60 秒倒计时。"""

    enabled: bool = True
    delay_seconds: int = 60

    def __post_init__(self):
        assert type(self.enabled) is bool
        assert type(self.delay_seconds) is int
        assert 1 <= self.delay_seconds <= MAX_STARTUP_DELAY_SECONDS


def load_startup_options(schedule: dict | None = None) -> StartupOptions:
    """读取启动设置；旧配置缺项沿用默认，非法值关闭自动启动并记诊断。"""
    data = load_schedule() if schedule is None else schedule
    # startup 及其字段对旧配置均为可选，缺失时沿用原有启动行为。
    block = data.get("startup", {})
    if isinstance(block, dict):
        enabled = block.get("enabled", True)
        delay = block.get("delay_seconds", 60)
        if (
            type(enabled) is bool
            and type(delay) is int
            and 1 <= delay <= MAX_STARTUP_DELAY_SECONDS
        ):
            return StartupOptions(enabled, delay)
    logger.warning("[startup] 自动启动设置无效，已关闭自动启动，请在配置弹窗重新设置")
    return StartupOptions(enabled=False)


def apply_startup_options(options: StartupOptions) -> None:
    """保存启动设置，保留其他选项。"""
    assert isinstance(options, StartupOptions)
    data = load_schedule()
    data["startup"] = {
        "enabled": options.enabled,
        "delay_seconds": options.delay_seconds,
    }
    save_schedule(data)


@dataclass(frozen=True)
class RunOptions:
    """调度运行选项的单一 schema：确认窗回显与落盘共用同一类型。

    字段语义：
    - 六个开关对应 schedule.yml 六块（shutdown / mute / unmute /
      close_running / rerun / notify）；块缺失或 ``enabled`` 非 bool 按关闭处理，
      唯 close_running 缺失默认启用（与历史「运行前始终清场」一致）。
    - ``shutdown_delay``：关机延迟秒数；块缺失/非法时为 0。
    - ``email`` / ``smtp_host`` / ``smtp_port`` 空串 = 不覆盖既有值；
      ``auth_code`` 空串 = 不动系统凭据。
    """

    shutdown_enabled: bool = False
    shutdown_delay: int = 0
    mute_enabled: bool = False
    unmute_enabled: bool = False
    close_running_enabled: bool = True
    rerun_enabled: bool = False
    notify_enabled: bool = False
    email: str = ""
    smtp_host: str = ""
    smtp_port: str = ""
    auth_code: str = ""


def _block_enabled(data: dict, key: str, default_enabled: bool) -> bool:
    """读开关块（``{enabled: bool}``）：块缺失按默认，``enabled`` 非 bool 按 False。"""
    block = data.get(key)
    if not isinstance(block, dict):
        return default_enabled
    enabled = block.get("enabled", default_enabled)
    return isinstance(enabled, bool) and enabled


def load_run_options(schedule: dict | None = None) -> RunOptions:
    """从 schedule.yml 数据解析运行选项（确认窗回显与 launchAll 直启共用）。

    Args:
        schedule: schedule.yml 全量数据；None 时自行读取。
    """
    data = load_schedule() if schedule is None else schedule
    shutdown = data.get("shutdown")
    shutdown_delay = 0
    if (
        isinstance(shutdown, dict)
        and isinstance(shutdown.get("delay_seconds"), int)
        and shutdown["delay_seconds"] > 0
    ):
        shutdown_delay = shutdown["delay_seconds"]
    notify = data.get("notify")
    email = smtp_host = smtp_port = ""
    if isinstance(notify, dict):
        email = str(notify.get("email") or "")
        smtp_host = str(notify.get("smtp_host") or "")
        raw_port = notify.get("smtp_port")
        smtp_port = str(raw_port) if raw_port is not None else ""
    return RunOptions(
        shutdown_enabled=isinstance(shutdown, dict)
        and shutdown.get("after_run", False) is True,
        shutdown_delay=shutdown_delay,
        mute_enabled=_block_enabled(data, "mute", False),
        unmute_enabled=_block_enabled(data, "unmute", False),
        close_running_enabled=_block_enabled(data, "close_running", True),
        rerun_enabled=_block_enabled(data, "rerun", False),
        notify_enabled=_block_enabled(data, "notify", False),
        email=email,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
    )


def apply_run_options(options: RunOptions) -> None:
    """把运行选项写回 schedule.yml，并注册本次填写的授权码（如有）。

    Args:
        options: 运行选项（确认窗 accept 的结果或调用方构造）。
    """
    schedule_data = load_schedule()
    schedule_data["shutdown"] = {
        "after_run": bool(options.shutdown_enabled),
        "delay_seconds": int(options.shutdown_delay),
    }
    schedule_data["mute"] = {"enabled": bool(options.mute_enabled)}
    schedule_data["unmute"] = {"enabled": bool(options.unmute_enabled)}
    schedule_data["close_running"] = {"enabled": bool(options.close_running_enabled)}
    schedule_data["rerun"] = {"enabled": bool(options.rerun_enabled)}
    notify = schedule_data.get("notify")
    if not isinstance(notify, dict):
        notify = {}
        schedule_data["notify"] = notify
    notify["enabled"] = bool(options.notify_enabled)
    if options.email:
        notify["email"] = options.email
    if options.smtp_host:
        notify["smtp_host"] = options.smtp_host
    if options.smtp_port:
        try:
            notify["smtp_port"] = int(options.smtp_port)
        except ValueError:
            logger.warning("[schedule] smtp_port 非法(%r)，保留原值", options.smtp_port)
    # 授权码（仅本次填写时）：注册进系统凭据管理器，避免明文落盘 schedule.yml。
    if options.auth_code:
        try:
            register_credentials(options.email, options.auth_code)
        except Exception as exc:  # noqa: BLE001  # 凭据为最佳努力：失败记日志，不阻塞调度参数落盘
            logger.error(
                "[schedule] 授权码写入系统凭据管理器失败(%s)：%s",
                type(exc).__name__,
                exc,
            )
    save_schedule(schedule_data)


def resolve_mail_config(schedule: dict) -> dict | None:
    """从 schedule.yml 数据解析有效邮件配置；未启用或字段缺失返回 None。

    ``notify.enabled`` 非 true、或 email 缺失时返回 None，表示不发邮件
    （默认关闭）。授权码只存于系统凭据管理器，不在此校验（由 send_mail 运行期读取）。

    Args:
        schedule: schedule.yml 全量数据（含 notify 块）。

    Returns:
        有效的 notify 配置字典；不发邮件时返回 None。
    """
    notify = schedule.get("notify")
    if not isinstance(notify, dict) or not notify.get("enabled", False):
        return None
    email = (notify.get("email") or "").strip()
    if not email:
        logger.warning("[schedule] 邮件未启用或 email 缺失，跳过: %s", notify)
        return None
    return notify


def build_pre_run_pipeline(
    *,
    target_time: str,
    scripts: list[dict] | None = None,
    enabled_keys: set[str] | None = None,
    weekly_start_map: dict | None = None,
    close_running: bool = True,
    mute: bool = False,
) -> list[Callable[[], None]]:
    """组装运行前 step 列表（单一工厂，与 build_post_run_pipeline 同形）。

    固定顺序：等待到点(+可选静音) → 关闭残留进程 → 写回子脚本 config；各 step 均为
    无参 Callable，由 ``ScheduledRun._run_steps`` 统一顺序执行。每步的取舍理由见
    对应内联注释。

    Args:
        target_time: 目标时刻 ``"HH:MM"``；``"now"`` 表示即时运行（跳过等待）。
        scripts: config 的脚本配置 dict 列表（全量，不按启用集合过滤），close 步骤用；
            None/空表示不关闭。
        enabled_keys: 纳入链的脚本唯一标识集合，写 config 步骤用；None/空表示不写。
        weekly_start_map: weekly.yml 的 weekly_start 段 全量映射（{脚本标识: 1~7}），写 config 步骤用。
        close_running: 是否运行前关闭残留进程。
        mute: 是否运行前静音（pre_run 静音 step）。

    Returns:
        运行前步骤列表（可能为空）。
    """
    steps: list[Callable[[], None]] = []

    # 等待+静音置顶：定时运行整段含等待期全程静音，避免等待期噪音。
    if mute:
        steps.append(mute_on)
    if target_time and target_time != "now":
        steps.append(lambda: wait_until_target(target_time))

    # 关闭残留：紧贴运行前，清掉等待期可能新起的脚本/游戏进程。
    # 关的是 config 全量脚本。用于关闭用户手动开的脚本/游戏。
    if close_running and scripts:
        steps.append(lambda: close_running_scripts(scripts))

    # 写回子脚本 config：关闭之后写，避开残留进程可能持有的文件锁；
    # 须早于核心运行（游戏/脚本启动时读 config）。
    if enabled_keys:
        steps.append(lambda: apply_subscript_config(enabled_keys, weekly_start_map))

    return steps


def build_post_run_pipeline(
    *,
    shutdown_delay: int | None,
    smtp_config: dict | None = None,
    unmute: bool = False,
    enabled_keys: set[str] | None = None,
) -> list[Callable[[], None]]:
    """按序构建运行后动作：日志分析(最终态) → 邮件 → 开启声音 → 关机(末位)。

    重跑不在此处，由 ``chain_service.rerun_round`` 在链运行结束后、本 pipeline 前完成；
    此处对最终态做日志分析供邮件汇总，并在末位关机。

    Args:
        shutdown_delay: 关机延迟秒数；None/0 表示不关机。
        smtp_config: SMTP 配置；None 表示不发邮件（默认关闭）。
        unmute: 是否运行后开启声音（post_run 恢复 step，与运行前静音相互独立）。
        enabled_keys: 本次启用的脚本标识集合（即 ``parse_logs`` 的候选列表）；
            None/空集合表示不纳入任何脚本，邮件直接跳过（不解析日志）。调用方想全量时
            显式传入 config 全部脚本集合。

    Returns:
        后置步骤列表（可能仅含关机或为空）。
    """
    shared: dict = {}

    def _analyze() -> None:
        shared["result"] = analyze_logs(enabled_keys)

    steps: list[Callable[[], None]] = [_analyze]

    def _do_mail() -> None:
        send_summary_mail(shared.get("result"), smtp_config)

    steps.append(_do_mail)

    if unmute:
        # 运行后开启声音：须在关机之前（关机后开启无意义）。
        steps.append(mute_off)

    if shutdown_delay:
        steps.append(lambda: shutdown_sys(shutdown_delay))

    return steps


class ScheduledRun:
    """一次调度运行：拥有 pre_run / 核心编排 / post_run 的完整生命周期。

    Args:
        service: 提供 ``run_chain_once`` / ``rerun_round`` 的 chain_service 模块对象
            （或等价 facade）；``load_config`` / ``get_weekly_start_map`` 由本模块直接
            import 对应 utils 调用，不经 service。
        enabled_keys: 纳入链的脚本唯一标识集合；None/空集合表示不纳入任何脚本
            （跳过运行、重跑与邮件）。调用方想全量时显式传入 config 全部脚本集合。
        target_time: 目标时刻 ``"HH:MM"``（24 小时制，须合法，调用方已校验）；
            传 ``"now"`` 表示即时运行（跳过等待，直接点火）。
        chain_name: 链配置文件名（不含扩展名，默认 today）。
        mute: 是否运行前静音（由 pre_run 执行，主仓直接操作系统音频）。
        unmute: 是否运行后开启声音（由 post_run 执行，与运行前静音相互独立）。
        shutdown_delay: 关机延迟秒数；None 表示不关机（含 0/未启用）。
    """

    def __init__(
        self,
        service,
        enabled_keys: set[str] | None,
        target_time: str,
        *,
        chain_name: str = "today",
        mute: bool = False,
        unmute: bool = False,
        shutdown_delay: int | None = None,
        close_running: bool = True,
    ) -> None:
        self.service = service
        self.enabled_keys = enabled_keys
        self.target_time = target_time
        self.chain_name = chain_name
        self.shutdown_delay = shutdown_delay

        # 候选集合 = 启用脚本集合（同一概念）。直接透传，不做 None→集合 的隐式归一化；
        # None/空集合 在下游各函数（run_chain_once / rerun_round / parse_logs）按「跳过」
        # 语义处理，由调用方显式传入全量集合表达「全部」。
        self.candidate_keys = enabled_keys

        # pre_run / post_run 均为 step 列表（同形），分别经单一工厂组装、由 _run_steps 执行，
        # 仅所处位置不同（run 前 / 后）。pre_run 顺序与每步取舍见 build_pre_run_pipeline 内联注释。
        # 关残留传全量脚本（非启用集合）：残留多为「昨天跑、今天不跑」的脚本，按启用集过滤抓不到。
        all_scripts = utils_config.load_config().get("script_list", [])
        self.pre_run: list[Callable[[], None]] = build_pre_run_pipeline(
            target_time=target_time,
            scripts=all_scripts,
            enabled_keys=self.candidate_keys,
            weekly_start_map=utils_weekly.get_weekly_start_map(),
            close_running=close_running,
            mute=mute,
        )

        # post_run：日志分析最终态 → 邮件 → 开启声音 → 关机（末位），由 build_post_run_pipeline 产出。
        schedule = load_schedule()
        mail_config = resolve_mail_config(schedule)
        self.post_run: list[Callable[[], None]] = build_post_run_pipeline(
            shutdown_delay=shutdown_delay,
            smtp_config=mail_config,
            unmute=unmute,
            enabled_keys=self.candidate_keys,
        )

    def run(self) -> None:
        """执行完整编排：pre_run → 生成并运行 → 重跑 → post_run。"""
        self._run_steps(self.pre_run)
        self._run_core()
        self._run_steps(self.post_run)

    def _run_core(self) -> None:
        """生成脚本链并运行，随后按需重跑失败脚本（先于 post_run）。"""
        all_config = utils_config.load_config()
        # 首次运行复用 run_chain_once（生成+运行原子）；candidate_keys 为 None/空集合时按「跳过」语义不运行任何脚本。
        self.service.run_chain_once(self.candidate_keys, chain_name=self.chain_name)
        # 重跑轮：链跑完后解析日志、对失败脚本二次运行（先于 post_run）。
        # 受 schedule.yml 的 rerun.enabled 控制（契约键，缺失即 assert 崩，不降级）。
        schedule = load_schedule()
        rerun_cfg = schedule.get("rerun")
        assert isinstance(rerun_cfg, dict) and "enabled" in rerun_cfg, (
            "[chain] schedule 缺 rerun.enabled"
        )
        if rerun_cfg["enabled"]:
            self.service.rerun_round(
                all_config=all_config, enabled_keys=self.candidate_keys
            )

    @staticmethod
    def _run_steps(steps: Sequence[Callable[[], None]]) -> None:
        """按序执行 step 列表；单步失败不影响后续步骤，均记日志。"""
        for step in steps:
            try:
                step()
            except Exception:
                logger.exception("[chain] 运行步骤执行失败")
