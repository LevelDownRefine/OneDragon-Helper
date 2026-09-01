"""ChainService：链编排领域服务（平级 peer，非协调器）。

承载链领域实现：脚本链生成、合法性校验、runner 命令构造、调度运行的编排。
config.yml 的读写由 :class:`ScriptService` 拥有，本服务仅保留
``load_config`` 委托供运行时取配置；schedule.yml 读写归
:mod:`src.service.schedule` 所有——与调度编排同处本模块。本服务不读取
UI 状态文件；日常副本真源为子脚本 config，set_dungeon 为
no-op 的脚本取 dungeon_list.yml 声明项。本服务
**不再担任** GUI/CLI 的顶层门面/协调器——
该角色由 :class:`AppService`（组合根）承担，本类只是被其组合的一个 peer。

weekly_timeouts 同步委托内部 script_service 处理，调用方不感知。

本模块不承载 UI 渲染/弹窗逻辑，无 Qt 依赖。
"""

import logging
import os
import subprocess

from src.config.subscript import (
    get_script_name,
)
from src.log.monitor import parse_logs
from src.service.chain_gen import generate_chain_config as _generate_chain_config
from src.service.schedule import ScheduledRun
from src.service.script_service import ScriptService
from src.service.weekly_service import WeeklyService
from src.utils_runner import (
    build_chain_command as _build_chain_command,
)
from src.utils_runner import (
    build_run_chain_command as _build_run_chain_command,
)
from src.utils_runner import (
    collect_invalid_script_messages,
)
from src.utils_runner import (
    run_chain_command as _run_chain_command,
)

logger = logging.getLogger(__name__)


class ChainService:
    """链编排领域服务（平级 peer）：链生成、校验、运行命令构造、调度运行编排。

    config.yml 读写由 ScriptService 拥有，本服务仅委托 ``load_config``
    供运行时取配置；weekly_timeouts / weekly_start 由平级 WeeklyService 拥有，本服务
    仅作 collaborator 调用（链生成取超时、调度运行取周几起）。
    """

    def __init__(self, script_service=None, weekly_service=None):
        """初始化 ChainService。

        Args:
            script_service: 可注入的 ScriptService；None 时自建默认实例。
            weekly_service: 可注入的 WeeklyService；None 时自建默认实例。
        """
        self._script_service = script_service or ScriptService()
        self._weekly_service = weekly_service or WeeklyService()

    # ---------- 配置读取（委托 ScriptService）----------
    # config.yml 的读写实现已迁至 ScriptService（见 :class:`ScriptService`）；此处仅保留
    # load_config 委托，供本服务运行时（run_chain_once / ScheduledRun）取配置。

    def load_config(self) -> dict:
        """委托 ScriptService 读取 config.yml（实现见 :class:`ScriptService`）。"""
        return self._script_service.load_config()

    # ---------- 链生成与校验 ----------

    def generate_chain(
        self,
        all_config_data: dict,
        enabled_keys: set[str],
        chain_name: str = "today",
        out_path: str | None = None,
    ) -> str:
        """生成 ScriptChainer 配置文件（仅含启用脚本）。

        weekly_timeouts 通过 ScriptService 加载后传入 chain_gen，不再由
        chain_gen 直接读取磁盘文件。

        Args:
            all_config_data: config.yml 完整数据（含 script_list）。
            enabled_keys: 要纳入链的脚本唯一标识集合。
            chain_name: 链配置文件名（不含扩展名）。
            out_path: 输出路径；None 时默认 config/script_chain/<chain_name>.yml。

        Returns:
            输出文件路径。
        """
        weekly_timeouts = self._weekly_service.load_all_weekly()
        return _generate_chain_config(
            all_config_data,
            enabled_keys,
            chain_name,
            out_path,
            weekly_timeouts=weekly_timeouts,
        )

    # ---------- 周常起始日（weekly_start）----------

    def set_weekly_start(self, script_name: str, start_day: int | None) -> None:
        """持久化某脚本的周常起始日到 weekly_start.yml（None 表示「不设置」）。

        委托平级 WeeklyService，调用方（CLI）不感知底层文件。
        """
        self._weekly_service.set_weekly_start(script_name, start_day)

    def get_weekly_start_map(self) -> dict:
        """读取 weekly_start.yml 全量映射（{脚本标识: 1~7}），供运行前 pre_run 写回子脚本 config。"""
        return self._weekly_service.get_weekly_start_map()

    def collect_invalid_scripts(self, script_list: list[dict]) -> list[tuple[str, str]]:
        """收集脚本列表中配置不合法的条目。

        Args:
            script_list: 脚本配置条目列表。

        Returns:
            [(display_name, invalid_message), ...]，仅含不合法项。
        """
        return collect_invalid_script_messages(script_list)

    # ---------- runner 命令 ----------

    def build_chain_command(
        self, chain_config_path: str, extra_args: list[str] | None = None
    ) -> tuple[list[str], str, dict | None]:
        """构造脚本链启动命令，返回 ``(命令列表, cwd, env)``。"""
        return _build_chain_command(chain_config_path, extra_args)

    def run_chain_command(
        self,
        chain_config_path: str,
        block: bool = True,
        extra_args: list[str] | None = None,
    ) -> int:
        """运行一条脚本链，返回退出码。"""
        return _run_chain_command(chain_config_path, block, extra_args)

    def run_chain_once(
        self,
        enabled_keys: set[str] | None = None,
        *,
        chain_name: str = "today",
    ) -> None:
        """生成脚本链并运行（单发原子）：service 侧 facade，委托 ``_run_chain_once_impl``。

        阻塞运行；运行后动作（日志分析/重跑/邮件/关机）由调用方（仅 ``schedule_run``）
        在本方法返回后另行编排，本方法不挂任何 post_run。

        Args:
            enabled_keys: 纳入链的脚本唯一标识集合；None/空集合表示不纳入任何脚本
                （跳过运行）。调用方想全量时显式传入 config 全部脚本集合。
            chain_name: 链配置文件名（不含扩展名，默认 today）。

        Returns:
            始终返回 None（纯跑链，运行后动作交由调用方）。
        """
        all_config = self.load_config()
        weekly_timeouts = self._weekly_service.load_all_weekly()
        _run_chain_once_impl(
            all_config,
            enabled_keys,
            chain_name=chain_name,
            weekly_timeouts=weekly_timeouts,
        )
        return None

    def _rerun_round(
        self, *, all_config: dict, enabled_keys: set[str] | None = None
    ) -> None:
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
        weekly_timeouts = self._weekly_service.load_all_weekly()
        _run_chain_once_impl(
            all_config,
            keys,
            chain_name="rerun",
            weekly_timeouts=weekly_timeouts,
        )

    def schedule_run(
        self,
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
        ``src.service.schedule.ScheduledRun`` 拥有；本方法仅作 facade 入口，
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
            self,
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
