"""运行前/后各 step 的具体动作（pre_run / post_run 的「做什么」）。

每个函数做一件事、参数全部显式传入（不依赖闭包捕获），由 ``schedule`` 的
``build_pre_run_pipeline`` / ``build_post_run_pipeline`` 组装成 step 序列并决定顺序。

步骤间的数据流（如日志分析结果 → 邮件）属组装关注点，留在 pipeline 内；本模块只提供
动作本身，故各函数均返回结果或就地完成，不持有跨步骤状态。
"""

import logging
import time
from datetime import datetime

from src.config.set_config import set_config
from src.log.monitor import parse_logs
from src.log.notify_mail import send_mail
from src.service.chain_gen import resolve_weekly_start
from src.utils.utils_runner import (
    ProcessTarget,
    collect_process_targets,
    kill_processes,
)
from src.utils.utils_weekly import next_target_datetime

logger = logging.getLogger(__name__)


def wait_until_target(target_time: str) -> None:
    """阻塞等待到目标时刻；等待前先打日志，避免等待期静默。

    Args:
        target_time: 目标时刻 ``"HH:MM"``（调用方已确保非 ``"now"``）。
    """
    target_dt = next_target_datetime(target_time)
    wait_seconds = (target_dt - datetime.now()).total_seconds()
    if wait_seconds > 0:
        logger.info(
            "[chain] 定时运行已设置，将等待至 %s 再运行（剩余约 %.0f 秒）",
            target_dt.strftime("%Y-%m-%d %H:%M"),
            wait_seconds,
        )
        time.sleep(wait_seconds)
    logger.info("[chain] 已到达目标时刻 %s，开始运行", target_time)


def close_running_scripts(scripts: list[dict]) -> None:
    """关闭各脚本残留的脚本进程、启动器真身与对应游戏进程（优雅终止 + 子进程树）。

    传入 config 的全量脚本（不按本次启用集合过滤）：残留多为「昨天跑、今天不跑」的
    脚本遗留，按启用集合过滤恰好抓不住这类。

    日志只报**实际被终止的进程**，不报归属脚本名——多个脚本常共用同一解释器进程名
    （如 ok 系列同为 pythonw.exe），按脚本归类必然张冠李戴。

    全部脚本的匹配条件**汇总后一次扫描**：逐脚本各扫一遍是 N 遍全系统遍历
    （8 个脚本实测 17s，``cmdline()`` 约 5.9ms/进程是唯一瓶颈），合并后固定一次。

    Args:
        scripts: 脚本配置 dict 列表；无匹配条件的脚本不产生条件。
    """
    targets: list[ProcessTarget] = []
    for script in scripts:
        targets += collect_process_targets(script)
    if not targets:
        return
    killed = kill_processes(targets)
    if killed:
        logger.info("[chain] 已关闭残留进程 %d 个：%s", len(killed), "、".join(killed))


def apply_subscript_config(
    enabled_keys: set[str], weekly_start_map: dict | None
) -> None:
    """把 weekly_start（按当天星期算出的周本开关）写回各子脚本 config。

    Args:
        enabled_keys: 纳入链的脚本唯一标识集合。
        weekly_start_map: weekly.yml 的 weekly_start 段 全量映射（{脚本标识: 1~7}）；None 按空处理。
    """
    for name in enabled_keys:
        weekly_start = resolve_weekly_start(weekly_start_map or {}, name)
        set_config(name, weekly_start=weekly_start)


def analyze_logs(
    enabled_keys: set[str] | None,
) -> dict[str, list[str] | str]:
    """解析启用脚本的日志，返回汇总结果（供邮件使用）。

    Args:
        enabled_keys: 本次启用的脚本标识集合（即 ``parse_logs`` 的候选列表）。

    Returns:
        日志汇总结果，结构同 ``src.log.monitor.parse_logs``。
    """
    # 候选集即启用脚本：只解析这些，邮件汇总自然只含其中的失败/报错项。
    return parse_logs(do_log=False, candidate_script_names=enabled_keys)


def send_summary_mail(
    result: dict[str, list[str] | str] | None, smtp_config: dict | None
) -> None:
    """按日志汇总结果发送邮件；无结果或无 SMTP 配置时静默跳过。

    Args:
        result: ``analyze_logs`` 的汇总结果；为空则不发。
        smtp_config: SMTP 配置；None 表示不发送。
    """
    if not result or smtp_config is None:
        return
    try:
        send_mail(result, smtp_config=smtp_config)
    except Exception as exc:  # noqa: BLE001  # 邮件为最佳努力通知，失败须记日志而非中断后续步骤（如关机）
        logger.error("[mail] 运行汇总邮件发送失败：%s", exc, exc_info=True)
