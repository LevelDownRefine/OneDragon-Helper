"""定时/即时运行编排：ScheduledRun 持有 pre_run / 核心编排 / post_run。

``ScheduledRun`` 是一个带生命周期的对象，而非纯函数：它在独立控制台进程
（由 ``utils_runner.spawn_schedule_run`` 以 ``CREATE_NEW_CONSOLE`` 起）中运行，
故前置阻塞等待（``time.sleep``）无害；关闭该控制台即取消。

编排固定为：pre_run → （等待到点）→ 生成脚本链并运行 → 可选重跑轮 → post_run。
pre_run / post_run 为可扩展的 step 列表（Callable 序列），初始化时组装。
"""

import logging
import time
from collections.abc import Callable, Sequence
from datetime import datetime

from src.config.subscript import get_script_name
from src.log.monitor import parse_logs
from src.log.notify_mail import send_mail
from src.service.chain_service import _resolve_mail_config
from src.utils_mute import mute_off, mute_on
from src.utils_shutdown import shutdown_sys
from src.utils_weekly import next_target_datetime

logger = logging.getLogger(__name__)


def build_pre_run_pipeline(
    *, target_time: str, mute: bool = False
) -> list[Callable[[], None]]:
    """运行前 step：定时计划（等待到目标时刻，即时运行为空）+ 可选静音。

    与 ``build_post_run_pipeline`` 同形——均产出 ``list[Callable]``，由 ``_run_steps``
    统一执行。仅 step 内容不同：此处为定时等待（+静音），post_run 为恢复/分析/邮件/关机。
    """
    steps: list[Callable[[], None]] = []
    if mute:
        steps.append(mute_on)
    if not target_time or target_time == "now":
        return steps

    def _wait() -> None:
        target_dt = next_target_datetime(target_time)
        wait_seconds = (target_dt - datetime.now()).total_seconds()
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    steps.append(_wait)
    return steps


def build_post_run_pipeline(
    *,
    shutdown_delay: int | None,
    smtp_config: dict | None = None,
    mute: bool = False,
) -> list[Callable[[], None]]:
    """按序构建运行后动作：日志分析(最终态) → 邮件 → 关机(末位)。

    重跑已移出本 pipeline，作为运行主环节由 ``ChainService._rerun_round`` 在链运行
    结束后、本 pipeline 触发前完成；此处只需对最终态做日志分析供邮件汇总，并在末位关机。

    Args:
        shutdown_delay: 关机延迟秒数；None/0 表示不关机。
        smtp_config: SMTP 配置；None 表示不发邮件（默认关闭）。

    Returns:
        后置步骤列表（可能仅含关机或为空）。各步骤经共享闭包 ``shared`` 传递日志分析结果。
    """
    shared: dict = {}

    def _analyze() -> None:
        shared["result"] = parse_logs(do_log=False)

    steps: list[Callable[[], None]] = [_analyze]

    def _do_mail() -> None:
        result = shared.get("result")
        if not result or smtp_config is None:
            return
        send_mail(result, smtp_config=smtp_config)

    steps.append(_do_mail)

    if mute:
        # 运行后恢复声音：须在关机之前（关机后恢复无意义）。
        steps.append(mute_off)

    if shutdown_delay:
        steps.append(lambda: shutdown_sys(shutdown_delay))

    return steps


class ScheduledRun:
    """一次调度运行：拥有 pre_run / 核心编排 / post_run 的完整生命周期。

    Args:
        service: 提供 ``load_config`` / ``run_chain_once`` 的 ChainService 实例。
        enabled_keys: 纳入链的脚本唯一标识集合；None 表示全部脚本。
        target_time: 目标时刻 ``"HH:MM"``（24 小时制，须合法，调用方已校验）；
            传 ``"now"`` 表示即时运行（跳过等待，直接点火）。
        chain_name: 链配置文件名（不含扩展名，默认 today）。
        mute: 是否运行中静音（由 pre_run 静音、post_run 恢复，主仓直接操作系统音频）。
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
        shutdown_delay: int | None = None,
    ) -> None:
        self.service = service
        self.enabled_keys = enabled_keys
        self.target_time = target_time
        self.chain_name = chain_name
        self.shutdown_delay = shutdown_delay

        # pre_run / post_run：均为 step 列表（同形），分别经工厂组装、由 _run_steps 执行。
        # 仅所处位置不同（run 前 / 后），机制完全一致。
        self.pre_run: list[Callable[[], None]] = build_pre_run_pipeline(
            target_time=target_time,
            mute=mute,
        )

        # post_run：日志分析最终态 → 邮件 → 恢复声音 → 关机（末位），由 build_post_run_pipeline 产出。
        all_config = service.load_config()
        mail_config = _resolve_mail_config(all_config)
        self.post_run: list[Callable[[], None]] = build_post_run_pipeline(
            shutdown_delay=shutdown_delay,
            smtp_config=mail_config,
            mute=mute,
        )

    def run(self) -> None:
        """执行完整编排：pre_run → 生成并运行 → 重跑 → post_run。"""
        self._run_steps(self.pre_run)
        self._run_core()
        self._run_steps(self.post_run)

    def _run_core(self) -> None:
        """生成脚本链并运行，随后按需重跑失败脚本（先于 post_run）。"""
        all_config = self.service.load_config()
        known = {get_script_name(s) for s in all_config["script_list"]}
        assert known, "[chain] config 无脚本，无法生成链"
        keys = self.enabled_keys if self.enabled_keys is not None else set(known)
        # 第一次跑：复用 run_chain_once 原子（生成+运行），与 ``_rerun_round`` 内的
        # 重跑路径完全一致（均阻塞），仅脚本集合（全部启用 vs 失败子集）与链名不同。
        self.service.run_chain_once(keys, chain_name=self.chain_name)
        # 重跑轮：链跑完后解析日志、对失败脚本二次运行（先于 post_run）。
        # 受 config.rerun.enabled 控制（契约键，缺失即 assert 崩，不降级）。
        assert "rerun" in all_config, "[chain] config 缺 rerun 块"
        rerun_cfg = all_config["rerun"]
        assert "enabled" in rerun_cfg, "[chain] config.rerun 缺 enabled 键"
        if rerun_cfg["enabled"]:
            self.service._rerun_round(all_config=all_config)

    @staticmethod
    def _run_steps(steps: Sequence[Callable[[], None]]) -> None:
        """按序执行 step 列表；单步失败不影响后续步骤，均记日志。"""
        for step in steps:
            try:
                step()
            except Exception:
                logger.exception("[chain] 运行步骤执行失败")
