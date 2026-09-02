"""链编排领域模块：脚本链生成、校验、运行命令构造、调度运行编排。

承载链领域实现：脚本链生成、合法性校验、runner 命令构造、调度运行的编排。
config.yml 的读写由 :mod:`src.utils_config` 拥有，运行时取配置由调用方
（run_chain_once / schedule）直接走 :func:`src.utils_config.load_config`；
schedule.yml 读写归 :mod:`src.service.schedule` 所有——与调度编排
同处该模块。本模块不读取 UI 状态文件；日常副本真源为子脚本 config，set_dungeon
为 no-op 的脚本取 dungeon_list.yml 声明项。
本模块不充当 GUI/CLI 的顶层门面/协调器——该角色由
:class:`src.service.app_service.AppService`（组合根）承担。

weekly 运行期参数（weekly_start.yml / weekly_timeouts.yml）由 :mod:`src.utils_weekly`
模块函数提供，调用方不感知。

本模块不承载 UI 渲染/弹窗逻辑，无 Qt 依赖。
"""

import logging
import os
import subprocess
import sys

from src import utils_config
from src.log.monitor import parse_logs
from src.service.chain_gen import generate_chain_config as _generate_chain_config
from src.service.schedule import ScheduledRun
from src.utils_runner import (
    build_run_chain_command as _build_run_chain_command,
)
from src.utils_sub_config import (
    get_script_name,
)
from src.utils_weekly import (
    load_all_weekly,
)

logger = logging.getLogger(__name__)

# schedule_run 需把「本模块」作为 chain_service facade 传给 ScheduledRun
# （ScheduledRun 仅经其调用 run_chain_once / rerun_round），故传 sys.modules[__name__]。


# ---------- 配置读取 ----------
# config.yml 的读写实现由 :mod:`src.utils_config` 拥有；运行时取配置
# 由 run_chain_once 与 schedule（各自直接 import utils_config）调用
# ``utils_config.load_config``。


# ---------- 链生成与校验 ----------


def generate_chain(
    all_config_data: dict,
    enabled_keys: set[str],
    chain_name: str = "today",
    out_path: str | None = None,
) -> str:
    """生成 ScriptChainer 配置文件（仅含启用脚本）。

    weekly_timeouts 通过 utils_config 加载后传入 chain_gen，不再由
    chain_gen 直接读取磁盘文件。

    Args:
        all_config_data: config.yml 完整数据（含 script_list）。
        enabled_keys: 要纳入链的脚本唯一标识集合。
        chain_name: 链配置文件名（不含扩展名）。
        out_path: 输出路径；None 时默认 config/script_chain/<chain_name>.yml。

    Returns:
        输出文件路径。
    """
    weekly_timeouts = load_all_weekly()
    return _generate_chain_config(
        all_config_data,
        enabled_keys,
        chain_name,
        out_path,
        weekly_timeouts=weekly_timeouts,
    )


# ---------- 周常起始日（weekly_start）----------

# （weekly_start 读取由 schedule 直接经 utils_weekly.get_weekly_start_map 调用，
# 不在此处透传封装。）


def run_chain_once(
    enabled_keys: set[str] | None = None,
    *,
    chain_name: str = "today",
) -> None:
    """生成脚本链并运行（单发原子）：模块级 facade，委托 ``_run_chain_once_impl``。

    阻塞运行；运行后动作（日志分析/重跑/邮件/关机）由调用方（仅 ``schedule_run``）
    在本函数返回后另行编排，本函数不挂任何 post_run。

    Args:
        enabled_keys: 纳入链的脚本唯一标识集合；None/空集合表示不纳入任何脚本
            （跳过运行）。调用方想全量时显式传入 config 全部脚本集合。
        chain_name: 链配置文件名（不含扩展名，默认 today）。

    Returns:
        始终返回 None（纯跑链，运行后动作交由调用方）。
    """
    all_config = utils_config.load_config()
    weekly_timeouts = load_all_weekly()
    _run_chain_once_impl(
        all_config,
        enabled_keys,
        chain_name=chain_name,
        weekly_timeouts=weekly_timeouts,
    )
    return None


def rerun_round(*, all_config: dict, enabled_keys: set[str] | None = None) -> None:
    """主流程重跑轮：链运行结束后解析日志，对未正常退出的脚本二次运行。

    重跑经 ``_run_chain_once_impl`` 阻塞运行失败子集（chain_name="rerun"），属于运行
    主环节而非 post_run，故置于 post_run 之前；后续邮件/关机在重跑结束后才触发。
    config 由调用方传入（避免重复加载）。

    Args:
        enabled_keys: 本次启用的脚本标识集合（作为 ``parse_logs`` 的候选列表），
            只在该候选内挑选「需重跑」的脚本，未启用脚本不进入重跑范围。
            None/空集合表示不纳入任何脚本，直接跳过重跑。
    """
    # None/空集合 = 不干活：跳过重跑轮的日志解析与重跑。
    if not enabled_keys:
        return
    # 候选集即启用脚本：parse_logs 只解析这些，rerun 名单自然只含其中的失败项。
    # 兜底过滤：rerun 名单须落在「config 已知脚本 ∩ 候选集」内，剔除越界/未知项。
    result = parse_logs(do_log=False, candidate_script_names=enabled_keys)
    assert "rerun" in result, "[chain] parse_logs 返回缺 rerun 键"
    known = {get_script_name(s) for s in all_config.get("script_list", [])}
    rerun_list = [s for s in result["rerun"] if s in known]
    rerun_list = [s for s in rerun_list if s in enabled_keys]
    if not rerun_list:
        return
    logger.info("[chain] 重跑 %d 个脚本: %s", len(rerun_list), sorted(rerun_list))
    keys = set(rerun_list)
    # 复用 _run_chain_once_impl（生成+运行原子），阻塞等重跑结束，
    # 使后续邮件/关机基于重跑后的最终态。
    weekly_timeouts = load_all_weekly()
    _run_chain_once_impl(
        all_config,
        keys,
        chain_name="rerun",
        weekly_timeouts=weekly_timeouts,
    )


def schedule_run(
    enabled_keys: set[str] | None,
    target_time: str,
    *,
    chain_name: str = "today",
    mute: bool = False,
    shutdown_delay: int | None = None,
    close_running: bool = True,
) -> None:
    """调度运行：组装 ``ScheduledRun`` 并执行的薄工厂。

    完整编排（等待到点 → 生成并运行 → 可选重跑 → post_run）由
    ``src.service.schedule.ScheduledRun`` 拥有；本函数仅作 facade 入口，
    设计为在独立控制台进程（``utils_runner.spawn_schedule_run`` 以
    ``CREATE_NEW_CONSOLE`` 起）中运行。

    Args:
        enabled_keys: 纳入链的脚本唯一标识集合；None/空集合表示不纳入任何脚本
            （跳过运行）。调用方想全量时显式传入 config 全部脚本集合。
        target_time: 目标时刻 ``"HH:MM"``；``"now"`` 表示即时运行（跳过等待）。
        chain_name: 链配置文件名（不含扩展名，默认 today）。
        mute: 是否运行中静音（由 ScheduledRun 的 pre_run/post_run 执行）。
        shutdown_delay: 关机延迟秒数；None 表示不关机（含 0/未启用）。
        close_running: 是否运行前关闭残留进程（由 ScheduledRun 的 pre_run 执行）。
    """
    ScheduledRun(
        sys.modules[__name__],
        enabled_keys,
        target_time,
        chain_name=chain_name,
        mute=mute,
        shutdown_delay=shutdown_delay,
        close_running=close_running,
    ).run()


def _run_chain_once_impl(
    all_config: dict,
    enabled_keys: set[str] | None,
    *,
    chain_name: str = "today",
    weekly_timeouts: dict | None = None,
) -> None:
    """生成脚本链并运行（单发原子）：不依赖 service 实例的纯函数实现。

    阻塞运行：先生成链，以 ``subprocess.run`` 启动（``CREATE_NEW_CONSOLE`` 起独立
    控制台）并等结束。调用方若需保持响应（如 GUI 主线程），应自行把本调用放进后台线程。
    运行后动作由调用方另行编排，本函数不挂任何 post_run。

    Args:
        all_config: config.yml 完整数据（含 script_list）。
        enabled_keys: 纳入链的脚本唯一标识集合；None/空集合表示不纳入任何脚本
            （跳过运行）。调用方想全量时显式传入 config 全部脚本集合。
        chain_name: 链配置文件名（不含扩展名，默认 today）。

    Returns:
        始终返回 None（纯跑链）。
    """
    # None/空集合 = 不干活：跳过链生成与运行。
    if not enabled_keys:
        return
    known = {get_script_name(s) for s in all_config["script_list"]}
    assert known, "[chain] config 无脚本，无法生成链"
    chain_path = _generate_chain_config(
        all_config,
        enabled_keys,
        chain_name,
        weekly_timeouts=weekly_timeouts,
    )
    command, cwd, env = _build_run_chain_command(chain_path)
    logger.info("[chain] 生成并运行脚本链: %s", chain_path)
    creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    # 始终阻塞：subprocess.run 内部即 Popen+wait，proc 不外传故无需手动 Popen。
    try:
        subprocess.run(command, cwd=cwd, env=env, creationflags=creationflags)
    except Exception:
        logger.exception("[chain] 运行脚本链子进程失败")
    return None
