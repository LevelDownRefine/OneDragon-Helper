"""AppService：组合根（composition root），GUI/CLI 唯一服务入口。

持有平级 peer 并薄委托，使各 peer 互不越界——链编排归 :mod:`src.service.chain_service` 模块函数（生成/运行/调度/校验），本类只组合它。

peer：
- 脚本管理（增删改、排序与跨配置编排）：归 :mod:`src.service.script_service` 模块函数
- 助手配置读写、条目查询与路径解析：归 :mod:`src.utils.utils_config` 模块函数
- 副本与周常声明读取（daily_task_list.yml / weekly_task_list.yml）：归 :mod:`src.config.daily_config` 模块函数
- 链编排（生成/运行/调度/校验）：归 :mod:`src.service.chain_service` 模块函数
- schedule.yml 读写：归 :mod:`src.service.schedule` 的模块函数（与调度编排同处一模一样）
- 周常运行期参数（weekly.yml 的 weekly_start 段 / weekly.yml 的 weekly_timeouts 段）：归 :mod:`src.utils.utils_weekly` 模块函数
- 游戏侧 config 适配器（副本/周几起写脚本自身 config）：归 :mod:`src.config.set_config` 模块函数
- 自定义壁纸表（config/wallpaper.json）：归 :mod:`src.utils.utils_wallpaper` 模块函数
- 配置备份与恢复（各子脚本 config 打包为 ZIP / 按目录原样回写）：归 :mod:`src.service.backup_service` 模块函数
- 助手手动更新（检查 / 下载 / 安装交接）：归 :class:`src.update.service.UpdateService`

GUI（MainWindow）与 CLI（各子命令）都只实例化本类，控制器经构造注入持有它；
Python GUI 直接调用本类；CLI 在传输边界转换数据，两者共用业务实现。
"""

import logging
from dataclasses import asdict

import src.link as link
import src.service.backup_service as backup_service
import src.service.chain_service as chain_service
import src.service.daily_plan as daily_plan
import src.service.script_service as script_service
import src.service.task_service as task_service
from src.config.daily_config import get_daily_map, get_weekly_map
from src.config.set_config import (
    ensure_config,
    get_registered_script_names,
    set_config,
    set_daily_enabled,
    set_weekly_start_day,
    set_weekly_task,
    weekly_names,
)
from src.config.task_switch import task_switch_of
from src.service import launch_service, wallpaper_service
from src.service.background_job import BackgroundJob, InvalidBackgroundJob
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
from src.service.script_service import InvalidScript, ScriptEdit
from src.service.update_session import UpdateSession
from src.update.service import UpdateService
from src.utils.utils_config import (
    config_file_path,
    get_script,
    load_config,
    save_config,
)
from src.utils.utils_runner import (
    build_chain_command,
    collect_invalid_script_messages,
    run_chain_command,
)
from src.utils.utils_sub_config import get_script_name
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

    def __init__(self, *, frontend: str = "qt"):
        """装配各 peer；GUI/CLI 入口选择对应发行版的更新服务。"""
        self._updates = UpdateService(frontend=frontend)
        self.background = BackgroundJob()
        self._update_session = UpdateSession(self._updates, self.background)

    def close(self) -> None:
        self.background.close()

    def start_backup(self) -> dict:
        return self.background.start("backup", self.create_backup)

    def start_restore(self, zip_path: str, confirmed: bool) -> dict:
        if (
            confirmed is not True
            or not isinstance(zip_path, str)
            or not zip_path.strip()
        ):
            raise InvalidBackgroundJob("请选择 ZIP 并确认覆盖当前脚本配置")
        return self.background.start("restore", lambda: self.restore_backup(zip_path))

    def poll_job(self, job_id: str) -> dict:
        return self.background.poll(job_id)

    def cancel_job(self, job_id: str) -> bool:
        return self.background.cancel(job_id)

    def update_view(self) -> dict:
        return self._update_session.view()

    def start_update_check(self) -> dict:
        return self._update_session.check()

    def start_update_download(self) -> dict:
        return self._update_session.download()

    def start_update_install(self) -> dict:
        return self._update_session.install()

    def app_snapshot(self) -> dict:
        """CLI 首屏脚本列表。"""
        return task_service.app_snapshot()

    def add_script(self, file_path: str) -> dict:
        """将脚本文件加入助手列表，不运行或复制文件。"""
        return script_service.add(file_path)

    def remove_script(self, script_name: str) -> None:
        """从助手列表移除脚本，不删除脚本文件。"""
        return script_service.remove(script_name)

    def reorder_scripts(self, script_names: list[str]) -> None:
        return script_service.reorder(script_names)

    def script_view(self, script_name: str) -> dict:
        """CLI 任务卡及物化选项。"""
        return task_service.script_view(script_name)

    def resolve_script_target(self, script_name: str, target: str) -> dict:
        """取得脚本工具栏的外部打开目标。"""
        return link.resolve_script_target(script_name, target)

    def game_icon_path(self, script_name: str) -> dict:
        return link.game_icon_path(script_name)

    def wallpaper_view(self, script_name: str) -> dict:
        return wallpaper_service.wallpaper_view(script_name)

    def set_wallpaper(self, script_name: str, file_path: str | None) -> None:
        return wallpaper_service.set_wallpaper(script_name, file_path)

    def save_wallpaper_cache(
        self, script_name: str, token: str, jpeg_base64: str
    ) -> bool:
        return wallpaper_service.save_wallpaper_cache(script_name, token, jpeg_base64)

    def resolve_launch_target(self, script_name: str, target: str) -> dict:
        return launch_service.resolve_launch_target(script_name, target)

    def run_view(self, script_names: list[str]) -> dict:
        """汇总本次所选脚本、配置问题和已存运行选项。"""
        scripts = chain_service.selected_scripts(script_names)
        return {
            "script_names": [get_script_name(script) for script in scripts],
            "invalid": [
                {"name": name, "reason": reason}
                for name, reason in self.collect_invalid_scripts(scripts)
            ],
            "options": asdict(self.load_run_options()),
        }

    def settings_view(self) -> dict:
        """从同一份配置汇总启动、每日计划开关和运行选项。"""
        schedule = load_schedule()
        return {
            "startup": asdict(load_startup_options(schedule)),
            "daily_enabled": daily_plan.load_daily_plan(schedule).enabled,
            "run_options": asdict(load_run_options(schedule)),
        }

    def saved_run(self, script_names: list[str]) -> RunOptions:
        """自动启动校验名单并读取上次选项，不保存或运行。"""
        chain_service.selected_scripts(script_names)
        return self.load_run_options()

    def prepare_run(
        self, script_names: list[str], options: RunOptions, confirm_invalid: bool
    ) -> RunOptions:
        """确认配置问题后保存选项，反读不含授权码的运行配置。"""
        assert isinstance(options, RunOptions)
        assert type(confirm_invalid) is bool
        scripts = chain_service.selected_scripts(script_names)
        if self.collect_invalid_scripts(scripts) and not confirm_invalid:
            raise chain_service.InvalidRunRequest(
                "请先确认配置不合法的脚本将在运行时跳过"
            )
        self.apply_run_options(options)
        return self.load_run_options()

    def run_batch(self, script_names: list[str], options: RunOptions) -> None:
        return chain_service.run_batch(script_names, options)

    def script_edit_view(self, script_name: str) -> dict:
        """读取脚本配置表单；不提交编辑或强制初始化。"""
        script = self.get_script(script_name)
        if script is None:
            raise InvalidScript("脚本已不存在，请刷新列表")
        return {
            "script_name": script_name,
            "script": script,
            "weekly_timeouts": self.weekly_inputs(script_name),
            "switches": self.get_script_switches(script_name),
        }

    def select_daily(
        self,
        script_name: str,
        daily_name: str | None = None,
        task_name: str | None = None,
        sequence: str | int | None = None,
    ) -> None:
        """CLI 日常选择，直接转发原 GUI 接口。"""
        return self.set_script_daily_task(
            script_name,
            daily_display_name=daily_name,
            task_name=task_name,
            sequence=sequence,
        )

    def check_update(self):
        """用户手动检查新版。"""
        return self._updates.check_update()

    def enable_daily(self, script_name: str, daily_name: str, enabled: bool) -> None:
        """CLI 日常开关，直接转发原 GUI 接口。"""
        return self.set_script_daily_enabled(script_name, daily_name, enabled)

    def select_weekly(self, script_name: str, weekly_name: str, task_name: str) -> None:
        """CLI 周常选择，直接转发原 GUI 接口。"""
        return self.set_script_weekly_task(script_name, weekly_name, task_name)

    def start_weekly(self, script_name: str, weekly_name: str, start_day: int) -> None:
        """CLI 周常起始日，直接转发原 GUI 接口。"""
        return self.set_weekly_start_for(script_name, weekly_name, start_day)

    def get_update_info(self):
        """读取本地版本与上次安装结果，不联网。"""
        return self._updates.get_update_info()

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

    def get_daily_map(self, script_name: str) -> dict:
        """物化指定脚本的日常菜单。"""
        return get_daily_map(script_name)

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
    # 文件读写归 utils_config；脚本条目修改归 script_service。
    def load_config(self) -> dict:
        return load_config()

    def save_config(self, data: dict) -> None:
        return save_config(data)

    def validate_script_edit(self, edit: ScriptEdit) -> ScriptEdit:
        """表单提交前校验；不写盘，允许 GUI 保留输入继续编辑。"""
        return script_service.validate_edit(edit)

    def update_script(self, edit: ScriptEdit) -> str:
        """应用一次完整脚本编辑，返回保存后的标识。"""
        return script_service.update(edit)

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

    def daily_plan_view(
        self, *, task: daily_plan.WindowsDailyTask | None = None
    ) -> dict:
        return daily_plan.daily_plan_view(task=task)

    def apply_daily_plan(
        self,
        options: daily_plan.DailyPlanOptions,
        *,
        task: daily_plan.WindowsDailyTask | None = None,
    ) -> None:
        return daily_plan.apply_daily_plan(options, task=task)

    def read_daily_task_state(self) -> daily_plan.DailyTaskState:
        return daily_plan.read_daily_task_state()

    def run_daily_plan(self) -> None:
        return daily_plan.run_daily_plan()

    def collect_invalid_scripts(self, script_list: list) -> list:
        return collect_invalid_script_messages(script_list)

    # ── 游戏侧 config 适配器（src.config.set_config 模块函数）─────────────
    # 副本写入各脚本自身 config；周几起由任务卡按条实时保存。
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
