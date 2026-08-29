"""定时/即时运行编排：ScheduledRun 持有 pre_run / 核心编排 / post_run。

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
from collections.abc import Callable, Sequence

from src.config.subscript import get_script_name
from src.service.chain_service import _resolve_mail_config
from src.service.run_actions import (
    analyze_logs,
    apply_subscript_config,
    close_running_scripts,
    send_summary_mail,
    wait_until_target,
)
from src.utils_mute import mute_off, mute_on
from src.utils_shutdown import shutdown_sys

logger = logging.getLogger(__name__)


def build_pre_run_pipeline(
    *,
    target_time: str,
    enabled_scripts: list[dict] | None = None,
    enabled_keys: set[str] | None = None,
    weekly_start_map: dict | None = None,
    close_running: bool = False,
    mute: bool = False,
) -> list[Callable[[], None]]:
    """运行前 step 列表（单一工厂，与 build_post_run_pipeline 同形）。

    固定顺序：等待到点(+可选静音) → 关闭残留进程 → 写回子脚本 config。各 step 均为
    无参 Callable，由 ``ScheduledRun._run_steps`` 统一顺序执行。
    - 等待+静音置顶：定时运行整段含等待期全程静音，避免等待期噪音；
    - 关闭残留紧贴运行前（等待之后）：等待期内用户可能手动开了脚本/游戏，
      若在最开头就关闭会漏掉等待期新起的进程，须等真正运行前再清场；
      受 ``close_running`` 开关控制（默认关闭）。
    - 写回子脚本 config：关闭之后写，避开残留进程可能持有的文件锁；
      须早于核心运行（游戏/脚本启动时读 config）。

    Args:
        target_time: 目标时刻 ``"HH:MM"``；``"now"`` 表示即时运行（跳过等待）。
        enabled_scripts: 纳入链的脚本配置 dict 列表（已按启用集合过滤），close 步骤用；
            None/空表示不关闭。
        enabled_keys: 纳入链的脚本唯一标识集合，写 config 步骤用；None/空表示不写。
        weekly_start_map: weekly_start.yml 全量映射（{脚本标识: 1~7}），写 config 步骤用。
        close_running: 是否运行前关闭残留进程。
        mute: 是否运行中静音（pre_run 静音、post_run 恢复）。

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
    if close_running and enabled_scripts:
        steps.append(lambda: close_running_scripts(enabled_scripts))

    # 写回子脚本 config：关闭之后写，避开残留进程可能持有的文件锁；
    # 须早于核心运行（游戏/脚本启动时读 config）。
    if enabled_keys:
        steps.append(lambda: apply_subscript_config(enabled_keys, weekly_start_map))

    return steps


def build_post_run_pipeline(
    *,
    shutdown_delay: int | None,
    smtp_config: dict | None = None,
    mute: bool = False,
    enabled_keys: set[str] | None = None,
) -> list[Callable[[], None]]:
    """按序构建运行后动作：日志分析(最终态) → 邮件 → 关机(末位)。

    重跑已移出本 pipeline，作为运行主环节由 ``ChainService._rerun_round`` 在链运行
    结束后、本 pipeline 触发前完成；此处只需对最终态做日志分析供邮件汇总，并在末位关机。

    日志分析结果经共享闭包 ``shared`` 从分析步骤流向邮件步骤——数据流属组装关注点，
    故留在工厂内，动作函数本身（``analyze_logs`` / ``send_summary_mail``）保持无状态。

    Args:
        shutdown_delay: 关机延迟秒数；None/0 表示不关机。
        smtp_config: SMTP 配置；None 表示不发邮件（默认关闭）。
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
        enabled_keys: 纳入链的脚本唯一标识集合；None/空集合表示不纳入任何脚本
            （跳过运行、重跑与邮件）。调用方想全量时显式传入 config 全部脚本集合。
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
        close_running: bool = True,
    ) -> None:
        self.service = service
        self.enabled_keys = enabled_keys
        self.target_time = target_time
        self.chain_name = chain_name
        self.shutdown_delay = shutdown_delay

        # 候选集合 = 启用脚本集合（同一概念）。直接透传，不做 None→集合 的隐式归一化；
        # None/空集合 在下游各函数（run_chain_once / _rerun_round / parse_logs）按「跳过」
        # 语义处理，由调用方显式传入全量集合表达「全部」。
        self.candidate_keys = enabled_keys

        # pre_run / post_run：均为 step 列表（同形），分别经单一工厂组装、由 _run_steps 执行。
        # 仅所处位置不同（run 前 / 后），机制完全一致。
        # pre_run 顺序（由 build_pre_run_pipeline 内部固定）：等待+静音 → 关闭残留 → 写子脚本 config。
        # - 等待+静音置顶：定时运行整段含等待期全程静音，避免等待期噪音；
        # - 关闭残留紧贴运行前（即等待之后）：等待期内用户可能手动开了脚本/游戏，
        #   若在最开头就关闭会漏掉等待期新起的进程，须等真正运行前再清场，受 close_running 开关控制；
        # - 写子脚本 config 在关闭之后：避开残留进程可能持有的文件锁，须早于核心运行。
        # close_running 为真时，先按启用集合解析脚本配置（供 close 步骤用），再整体传入工厂。
        enabled_scripts: list[dict] = []
        if close_running:
            all_scripts = self.service.load_config().get("script_list", [])
            enabled_scripts = [
                s
                for s in all_scripts
                if get_script_name(s) in (self.candidate_keys or set())
            ]
        self.pre_run: list[Callable[[], None]] = build_pre_run_pipeline(
            target_time=target_time,
            enabled_scripts=enabled_scripts,
            enabled_keys=self.candidate_keys,
            weekly_start_map=self.service.get_weekly_start_map(),
            close_running=close_running,
            mute=mute,
        )

        # post_run：日志分析最终态 → 邮件 → 恢复声音 → 关机（末位），由 build_post_run_pipeline 产出。
        # 邮件配置来自 schedule.yml 的 notify 块（已从 config.yml 迁出）。
        schedule = service.load_schedule()
        mail_config = _resolve_mail_config(schedule)
        self.post_run: list[Callable[[], None]] = build_post_run_pipeline(
            shutdown_delay=shutdown_delay,
            smtp_config=mail_config,
            mute=mute,
            enabled_keys=self.candidate_keys,
        )

    def run(self) -> None:
        """执行完整编排：pre_run → 生成并运行 → 重跑 → post_run。"""
        self._run_steps(self.pre_run)
        self._run_core()
        self._run_steps(self.post_run)

    def _run_core(self) -> None:
        """生成脚本链并运行，随后按需重跑失败脚本（先于 post_run）。"""
        all_config = self.service.load_config()
        # 第一次跑：复用 run_chain_once 原子（生成+运行），与 ``_rerun_round`` 内的
        # 重跑路径完全一致（均阻塞），仅脚本集合（全部启用 vs 失败子集）与链名不同。
        # candidate_keys 为 None/空集合时 run_chain_once 按「跳过」语义不运行任何脚本。
        self.service.run_chain_once(self.candidate_keys, chain_name=self.chain_name)
        # 重跑轮：链跑完后解析日志、对失败脚本二次运行（先于 post_run）。
        # 受 schedule.yml 的 rerun.enabled 控制（契约键，缺失即 assert 崩，不降级）。
        schedule = self.service.load_schedule()
        rerun_cfg = schedule.get("rerun")
        assert isinstance(rerun_cfg, dict) and "enabled" in rerun_cfg, (
            "[chain] schedule 缺 rerun.enabled"
        )
        if rerun_cfg["enabled"]:
            self.service._rerun_round(
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
