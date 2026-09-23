"""AppService：组合根（composition root），GUI/CLI 唯一服务入口。

持有平级 peer 并薄委托，使各 peer 互不越界——链编排归 :mod:`src.service.chain_service` 模块函数（生成/运行/调度/校验），本类只组合它。

peer：
- 单脚本配置（config.yml 读写含脚本条目增删改）：归 :mod:`src.utils.utils_config` 模块函数
- 副本与周常声明读取（daily_task_list.yml / weekly_task_list.yml）：归 :mod:`src.config.daily_config` 模块函数
- 链编排（生成/运行/调度/校验）：归 :mod:`src.service.chain_service` 模块函数
- schedule.yml 读写：归 :mod:`src.service.schedule` 的模块函数（与调度编排同处一模一样）
- 周常运行期参数（weekly.yml 的 weekly_start 段 / weekly.yml 的 weekly_timeouts 段）：归 :mod:`src.utils.utils_weekly` 模块函数
- 游戏侧 config 适配器（副本/周几起写脚本自身 config）：归 :mod:`src.config.set_config` 模块函数
- 自定义壁纸表（config/wallpaper.json）：归 :mod:`src.utils.utils_wallpaper` 模块函数
- 配置备份与恢复（各子脚本 config 打包为 ZIP / 按目录原样回写）：归 :mod:`src.service.backup_service` 模块函数

GUI（MainWindow）与 CLI（各子命令）都只实例化本类，控制器经构造注入持有它；
未来 GUI 同类操作优先经 CLI 完成，本类即两者的共同装配点。
"""

import logging

import src.service.backup_service as backup_service
import src.service.chain_service as chain_service
import src.service.daily_plan as daily_plan
from src.config.daily_config import get_daily_map, get_weekly_map
from src.config.set_config import (
    ensure_config,
    get_registered_script_names,
    set_config,
    set_daily_enabled,
)
from src.config.task_switch import task_switch_of
from src.config.weekly import set_weekly_start_day, set_weekly_task, weekly_names
from src.service.schedule import (
    RunOptions,
    StartupOptions,
    apply_run_options,
    apply_startup_options,
    load_run_options,
    load_schedule,
    load_startup_options,
    save_schedule,
)
from src.service.update_service import UpdateService
from src.utils.utils_config import (
    add_script,
    build_script_entry,
    config_file_path,
    get_script,
    load_config,
    remove_script,
    save_config,
    update_script,
)
from src.utils.utils_runner import (
    build_chain_command,
    collect_invalid_script_messages,
    run_chain_command,
)
from src.utils.utils_wallpaper import (
    load_wallpapers,
    save_video_preview,
    save_wallpapers,
    video_preview_path,
)
from src.utils.utils_weekly import (
    check_weekly,
    get_weekly_start_map,
    set_weekly_start,
    weekly_inputs,
)

logger = logging.getLogger(__name__)


def _weekly_start_entries(script_name: str) -> dict[str, int]:
    """取该脚本的「周常展示名 → 起始日」映射（{周常: 1~7}）。

    值域已由 ``utils_weekly`` 保证：读时迁移并丢弃旧版单值/越界项，写时断言 1~7。

    Args:
        script_name: 脚本标识名。

    Returns:
        该脚本的映射；无条目时为空 dict。
    """
    return get_weekly_start_map().get(script_name) or {}


class AppService:
    """组合根：装配平级 service peer 并向外暴露统一接口（GUI/CLI 唯一门面）。"""

    def __init__(self):
        """装配各 peer。"""
        self._updates = UpdateService()

    def check_update(self):
        """用户手动检查新版。"""
        return self._updates.check_update()

    def prepare_update(self, release, *, progress=None, cancelled=None):
        """下载、校验并准备更新包。"""
        return self._updates.prepare_update(
            release, progress=progress, cancelled=cancelled
        )

    def start_update(self, prepared):
        """等待独立更新器就绪；成功返回后 GUI 应立即退出。"""
        return self._updates.start_update(prepared)

    # ── 配置备份 / 恢复（src.service.backup_service 模块函数）──
    def create_backup(self) -> dict:
        """打包各子脚本配置，返回 ZIP 路径与文件数。"""
        return backup_service.create_backup()

    def restore_backup(self, zip_path: str) -> dict:
        """按当前脚本目录恢复并保留游戏路径，返回恢复文件数和跳过的脚本。"""
        return backup_service.restore_backup(zip_path)

    # ── 副本 / 周常声明（src.config.daily_config 模块函数）────────────
    def get_weekly_map(self, script_name: str) -> list:
        """读取 weekly_task_list.yml 的周常声明清单。"""
        return get_weekly_map(script_name)

    def get_daily_map(self) -> dict:
        """读取 daily_task_list.yml 的副本/序列配置。"""
        return get_daily_map()

    # ── 游戏侧 config 适配器（src.config.set_config 模块函数）────────────
    def get_registered_script_names(self) -> list[str]:
        """已注册（已适配）脚本标识名，供启动后预热遍历。"""
        return get_registered_script_names()

    def warm_config(self, script_name: str) -> None:
        """预热单个脚本 config：构造单例并触发模板对齐（幂等、不强制重对齐）。

        启动后空闲时逐脚本调用，使点选时已在缓存、零等待；对齐在 ``__init__`` 内
        收口，每个进程每脚本仅一次，无重复日志。需强制重对齐请用 ``init_config``。
        """
        ensure_config(script_name)

    # ── 单脚本配置（src.utils.utils_config 模块函数）─────────────────────────
    def get_script(self, script_name: str):
        """按脚本唯一标识读取单个脚本条目。"""
        return get_script(script_name)

    def build_script_entry(self, file_path: str, existing_script_names: set) -> dict:
        """按文件路径构造脚本条目（去重命名 + 类型推断 + 默认字段补全）。"""
        return build_script_entry(file_path, existing_script_names)

    def config_file_path(self, script_name: str):
        """返回该脚本「配置文件」的本地路径（用于外部打开）与失败原因。"""
        return config_file_path(script_name)

    # ── 周常运行期参数（src.utils.utils_weekly 模块函数）──
    # weekly.yml 的 weekly_start 段（周几起）与 weekly.yml 的 weekly_timeouts 段（每周超时）由 src.utils.utils_weekly
    # 拥有；读写直接调模块函数，不经 chain_service 转发。
    def get_weekly_start_for(self, script_name: str, weekly_name: str) -> int | None:
        """读某条周常的起始日（1~7），未设置返回 None。"""
        return _weekly_start_entries(script_name).get(weekly_name)

    def set_weekly_start_for(
        self, script_name: str, weekly_name: str, start_day: int
    ) -> None:
        """写某条周常的起始日（周几起）。

        两处落盘收拢在此：weekly.yml 的 weekly_start 段（意图，同脚本其它周常的取值
        不动）；以及该条周常的游戏侧字面起始日字段（仅覆写 ``set_start_day`` 的周常有，
        如崩铁历战余响 / 粥——这类值无法由当天星期折算，需编辑期即时落盘）。

        Args:
            script_name: 脚本标识名。
            weekly_name: 周常展示名。
            start_day: 周几起（1~7，1=周一）。
        """
        start_days = dict(_weekly_start_entries(script_name))
        start_days[weekly_name] = start_day
        set_weekly_start(script_name, start_days)
        set_weekly_start_day(script_name, weekly_name, start_day)

    def weekly_inputs(self, script_name: str) -> list:
        """返回配置弹窗 7 个超时输入框的初始值。"""
        return weekly_inputs(script_name)

    def set_weekly_start(self, script_name: str, start_day) -> None:
        """持久化某脚本的周常起始日（周几起）到 weekly.yml 的 weekly_start 段。

        start_day 为 None 时清除该脚本条目（对应 CLI ``--weekly-start`` 的「不设置」）；
        否则写给该脚本全部周常（CLI 只给得出脚本级单值，落到每条周常）。
        """
        if start_day is None:
            set_weekly_start(script_name, {})
            return
        set_weekly_start(
            script_name, dict.fromkeys(weekly_names(script_name), start_day)
        )

    def get_weekly_start_map(self) -> dict:
        """读取 weekly.yml 的 weekly_start 段全量映射（{脚本标识: {周常展示名: 1~7}}）。"""
        return get_weekly_start_map()

    def check_weekly(self) -> dict:
        """校验 weekly.yml 的 weekly_timeouts 段 与 config.yml 脚本条目的一致性。

        Returns:
            一致性结果字典（含 status / missing_or_short / orphans）。
        """
        return check_weekly(load_config())

    # ── 配置读写（src.utils.utils_config 模块函数）──
    # config.yml 读写（含脚本条目增删改）归 :mod:`src.utils.utils_config`；此处仅作薄委托。
    def load_config(self) -> dict:
        return load_config()

    def save_config(self, data: dict) -> None:
        return save_config(data)

    def add_script(self, script_data: dict) -> None:
        return add_script(script_data)

    def remove_script(self, script_name: str) -> None:
        return remove_script(script_name)

    def update_script(
        self,
        old_script_name: str,
        new_display_name: str,
        config_patch: dict,
        weekly_timeouts: list,
    ):
        new_script_name = update_script(
            old_script_name,
            new_display_name,
            config_patch,
            weekly_timeouts,
        )
        daily_plan.rename_script(old_script_name, new_script_name)
        return new_script_name

    # ── schedule.yml（src.service.schedule 模块函数）──
    # schedule.yml 的读写与调度编排同处 src.service.schedule，不挂在任何 peer 实例上；
    # 此处作薄委托，对外接口保持稳定、避免 GUI/CLI 直接依赖该模块。
    def load_schedule(self) -> dict:
        return load_schedule()

    def save_schedule(self, data: dict) -> None:
        return save_schedule(data)

    def load_run_options(self) -> RunOptions:
        """读取 schedule.yml 的运行选项（确认窗回显与启动全部直启共用）。"""
        return load_run_options()

    def apply_run_options(self, options: RunOptions) -> None:
        """把运行选项写回 schedule.yml，并注册本次填写的授权码（如有）。"""
        return apply_run_options(options)

    def load_startup_options(self) -> StartupOptions:
        """读取打开 GUI 后的自动启动设置。"""
        return load_startup_options()

    def apply_startup_options(self, options: StartupOptions) -> None:
        """保存自动启动开关与倒计时。"""
        return apply_startup_options(options)

    def load_daily_plan(self) -> daily_plan.DailyPlanOptions:
        return daily_plan.load_daily_plan()

    def apply_daily_plan(self, options: daily_plan.DailyPlanOptions) -> None:
        return daily_plan.apply_daily_plan(options)

    def list_daily_plan_scripts(self) -> list[tuple[str, str]]:
        return daily_plan.list_daily_plan_scripts()

    def read_daily_task_state(self) -> daily_plan.DailyTaskState:
        return daily_plan.read_daily_task_state()

    def run_daily_plan(self) -> None:
        return daily_plan.run_daily_plan()

    def collect_invalid_scripts(self, script_list: list) -> list:
        return collect_invalid_script_messages(script_list)

    # ── 游戏侧 config 适配器（src.config.set_config 模块函数）─────────────
    # 副本写入各脚本**自身**的 config（适配器层）；周几起由 update_script
    # 统一落盘（含游戏侧同步），不经此节入口。
    def set_script_daily_task(
        self,
        script_name: str,
        daily_display_name: str | None = None,
        task_name: str | None = None,
        sequence: str | int | None = None,
    ) -> None:
        """写日常副本/二级序列到脚本自身 config（编辑期实时落盘）。"""
        return set_config(
            script_name,
            daily_display_name=daily_display_name,
            task_name=task_name,
            sequence=sequence,
        )

    def set_script_daily_enabled(
        self, script_name: str, daily_display_name: str, enabled: bool
    ) -> None:
        """启用/停用某日常（写子脚本 config 的日常开关，编辑期实时落盘）。"""
        return set_daily_enabled(script_name, daily_display_name, enabled)

    def set_script_weekly_task(
        self, script_name: str, weekly_name: str, task_name: str
    ) -> None:
        """写某周常当前选中的副本名到脚本自身 config。"""
        return set_weekly_task(script_name, weekly_name, task_name)

    # ── 脚本原生任务开关（src.config.task_switch 模块函数）─────────────
    def get_script_switches(self, script_name: str) -> list:
        """读该脚本原生任务的开关清单（供配置弹窗的「任务开关」区）。

        未声明（该脚本无此特性）或脚本未安装时返回空列表。
        """
        switch = task_switch_of(script_name)
        return [] if switch is None else switch.read()

    def set_script_switches(self, script_name: str, states: dict) -> int:
        """按任务名写该脚本原生任务的开关，返回实际变更项数。"""
        switch = task_switch_of(script_name)
        return 0 if switch is None else switch.write(states)

    # ── 自定义壁纸表（config/wallpaper.json，src.utils.utils_wallpaper）──
    def load_wallpapers(self) -> dict:
        """读取壁纸表（{脚本标识: 壁纸路径}）；缺失/损坏返回空 dict。"""
        return load_wallpapers()

    def save_wallpapers(self, wallpapers: dict) -> None:
        """原子写回壁纸表。"""
        return save_wallpapers(wallpapers)

    def video_preview_path(self, source_path: str) -> str | None:
        """定位当前视频版本的首帧缓存。"""
        return video_preview_path(source_path)

    def save_video_preview(
        self, source_path: str, cache_path: str, data: bytes
    ) -> bool:
        """保存 GUI 编码的首帧，失败不影响播放。"""
        return save_video_preview(source_path, cache_path, data)

    def generate_chain(
        self,
        all_config_data: dict,
        enabled_keys: set,
        chain_name: str = "today",
        out_path: str | None = None,
    ) -> str:
        return chain_service.generate_chain(
            all_config_data, enabled_keys, chain_name, out_path
        )

    def build_chain_command(self, chain_config_path: str, extra_args=None):
        return build_chain_command(chain_config_path, extra_args)

    def run_chain_command(
        self, chain_config_path: str, block: bool = True, extra_args=None
    ):
        return run_chain_command(chain_config_path, block, extra_args)

    def run_chain_once(
        self, enabled_keys: set | None = None, *, chain_name: str = "today"
    ):
        return chain_service.run_chain_once(enabled_keys, chain_name=chain_name)

    def schedule_run(
        self,
        enabled_keys,
        target_time: str,
        *,
        chain_name: str = "today",
        mute: bool = False,
        unmute: bool = False,
        shutdown_delay=None,
        close_running: bool = True,
    ):
        return chain_service.schedule_run(
            enabled_keys,
            target_time,
            chain_name=chain_name,
            mute=mute,
            unmute=unmute,
            shutdown_delay=shutdown_delay,
            close_running=close_running,
        )
