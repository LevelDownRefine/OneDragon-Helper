"""AppService：组合根（composition root），GUI/CLI 唯一服务入口。

持有平级 peer 并薄委托，使各 peer 互不越界——ChainService 只是被本类组合的一个链领域 peer，自身只负责链的生成/运行/校验。

peer：
- ScriptService：单脚本配置（config.yml 读写含脚本条目增删改）
- DungeonService：副本与周常声明读取（dungeon_list.yml / weekly_list.yml）
- ChainService：链编排领域服务（生成/运行/调度/校验）
- schedule.yml 读写：归 :mod:`src.service.schedule` 的模块函数（与调度编排同处一模一样）
- 周常运行期参数（weekly_start.yml / weekly_timeouts.yml）：归 :mod:`src.utils_weekly` 模块函数

GUI（MainWindow）与 CLI（各子命令）都只实例化本类，控制器经构造注入持有它；
未来 GUI 同类操作优先经 CLI 完成，本类即两者的共同装配点。
"""

import logging

from src.service.chain_service import ChainService
from src.service.dungeon_service import DungeonService
from src.service.schedule import load_schedule, save_schedule
from src.service.script_service import ScriptService
from src.utils_weekly import (
    check_weekly,
    get_weekly_start,
    get_weekly_start_map,
    set_weekly_start,
    weekly_inputs,
)

logger = logging.getLogger(__name__)


class AppService:
    """组合根：装配平级 service peer 并向外暴露统一接口（GUI/CLI 唯一门面）。"""

    def __init__(
        self,
        script_service=None,
        dungeon_service=None,
        chain_service=None,
    ):
        """装配各 peer。

        Args:
            script_service: 可注入的 ScriptService；None 时自建默认实例。
            dungeon_service: 可注入的 DungeonService；None 时自建默认实例。
            chain_service: 可注入的 ChainService；None 时自建（注入 script_service
                作 collaborator）。
        """
        self._script_service = script_service or ScriptService()
        self._dungeon_service = dungeon_service or DungeonService()
        self._chain_service = chain_service or ChainService(
            script_service=self._script_service
        )

    # ── 副本 / 周常声明（DungeonService）──────────────────────────────
    def get_weekly_map(self, script_name: str) -> list:
        """委托 DungeonService 读取 weekly_list.yml 的周常声明清单。"""
        return self._dungeon_service.get_weekly_map(script_name)

    def get_dungeon_map(self) -> dict:
        """委托 DungeonService 读取 dungeon_list.yml 的副本/序列配置。"""
        return self._dungeon_service.get_dungeon_map()

    # ── 单脚本配置（ScriptService）────────────────────────────────────
    def get_script(self, script_name: str):
        """按脚本唯一标识读取单个脚本条目。"""
        return self._script_service.get_script(script_name)

    def build_script_entry(self, file_path: str, existing_script_names: set) -> dict:
        """按文件路径构造脚本条目（去重命名 + 类型推断 + 默认字段补全）。"""
        return self._script_service.build_script_entry(file_path, existing_script_names)

    def config_file_path(self, script_name: str):
        """返回该脚本「配置文件」的本地路径（用于外部打开）与失败原因。"""
        return self._script_service.config_file_path(script_name)

    # ── 周常运行期参数（src.utils_weekly 模块函数）──
    # weekly_start.yml（周几起）与 weekly_timeouts.yml（每周超时）由 src.utils_weekly
    # 拥有；读写直接调模块函数，不经 ChainService 转发。
    def get_weekly_start(self, script_name: str):
        """返回某脚本的周常起始日（1~7），未设置返回 None。"""
        return get_weekly_start(script_name)

    def weekly_inputs(self, script_name: str) -> list:
        """返回配置弹窗 7 个超时输入框的初始值。"""
        return weekly_inputs(script_name)

    def set_weekly_start(self, script_name: str, start_day) -> None:
        """持久化某脚本的周常起始日（周几起）到 weekly_start.yml。"""
        return set_weekly_start(script_name, start_day)

    def get_weekly_start_map(self) -> dict:
        """读取 weekly_start.yml 全量映射（{脚本标识: 1~7}）。"""
        return get_weekly_start_map()

    def check_weekly(self) -> dict:
        """校验 weekly_timeouts.yml 与 config.yml 脚本条目的一致性。

        Returns:
            一致性结果字典（含 status / missing_or_short / orphans）。
        """
        return check_weekly(self._script_service.load_config())

    # ── 配置读写（ScriptService）──
    # config.yml 读写（含脚本条目增删改）由 ScriptService 拥有；此处仅作薄委托。
    def load_config(self) -> dict:
        return self._script_service.load_config()

    def save_config(self, data: dict) -> None:
        return self._script_service.save_config(data)

    def add_script(self, script_data: dict) -> None:
        return self._script_service.add_script(script_data)

    def remove_script(self, script_name: str) -> None:
        return self._script_service.remove_script(script_name)

    def update_script(
        self,
        old_script_name: str,
        new_display_name: str,
        config_patch: dict,
        weekly_timeouts: list,
    ):
        return self._script_service.update_script(
            old_script_name, new_display_name, config_patch, weekly_timeouts
        )

    # ── schedule.yml（src.service.schedule 模块函数）──
    # schedule.yml 的读写与调度编排同处 src.service.schedule，不挂在任何 peer 实例上；
    # 此处作薄委托，对外接口保持稳定、避免 GUI/CLI 直接依赖该模块。
    def load_schedule(self) -> dict:
        return load_schedule()

    def save_schedule(self, data: dict) -> None:
        return save_schedule(data)

    def collect_invalid_scripts(self, script_list: list) -> list:
        return self._chain_service.collect_invalid_scripts(script_list)

    def generate_chain(
        self,
        all_config_data: dict,
        enabled_keys: set,
        chain_name: str = "today",
        out_path: str | None = None,
    ) -> str:
        return self._chain_service.generate_chain(
            all_config_data, enabled_keys, chain_name, out_path
        )

    def build_chain_command(self, chain_config_path: str, extra_args=None):
        return self._chain_service.build_chain_command(chain_config_path, extra_args)

    def run_chain_command(
        self, chain_config_path: str, block: bool = True, extra_args=None
    ):
        return self._chain_service.run_chain_command(
            chain_config_path, block, extra_args
        )

    def run_chain_once(
        self, enabled_keys: set | None = None, *, chain_name: str = "today"
    ):
        return self._chain_service.run_chain_once(enabled_keys, chain_name=chain_name)

    def schedule_run(
        self,
        enabled_keys,
        target_time: str,
        *,
        chain_name: str = "today",
        mute: bool = False,
        shutdown_delay=None,
        close_running: bool = True,
    ):
        return self._chain_service.schedule_run(
            enabled_keys,
            target_time,
            chain_name=chain_name,
            mute=mute,
            shutdown_delay=shutdown_delay,
            close_running=close_running,
        )
