"""AppService：组合根（composition root），GUI/CLI 唯一服务入口。

持有平级 peer 并薄委托，使各 peer 互不越界——链编排归 :mod:`src.service.chain_service` 模块函数（生成/运行/调度/校验），本类只组合它。

peer：
- 单脚本配置（config.yml 读写含脚本条目增删改）：归 :mod:`src.utils.utils_config` 模块函数
- 任务声明：由 :mod:`src.config.task_config` 加载；本模块展开资源并组装任务展示数据
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
from copy import deepcopy

import src.service.backup_service as backup_service
import src.service.chain_service as chain_service
import src.service.daily_plan as daily_plan
from src.config.set_config import (
    get_daily_task,
    get_task_enabled,
    get_task_options,
    get_weekly_task,
    set_config,
    set_task_enabled,
    set_weekly_task_option,
)
from src.config.task_config import (
    get_options,
    get_physical_name,
    has_selection_binding,
    load_daily_map,
    load_weekly_map,
    validate_options,
    validate_selection_depth,
)
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
from src.utils.utils_config import (
    add_script,
    build_script_entry,
    config_file_path,
    get_script,
    load_config,
    remove_script,
    save_config,
    set_script_enabled,
    update_script,
)
from src.utils.utils_runner import (
    build_chain_command,
    collect_invalid_script_messages,
    run_chain_command,
)
from src.utils.utils_wallpaper import load_wallpapers, save_wallpapers
from src.utils.utils_weekly import (
    check_weekly,
    get_weekly_start,
    get_weekly_start_map,
    set_weekly_start,
    weekly_inputs,
)

logger = logging.getLogger(__name__)


def _expand_options(script_name: str, definition: dict) -> dict:
    """各层共用资源展开规则，结果仍保持同样的选项组结构。"""
    assert "options" in definition
    group = deepcopy(definition["options"])
    if "source" in group:
        source = group.pop("source")
        assert "path" in source, "source 必须声明 path"
        # 来源分类默认沿用物理名；资源另有分类规则时单独声明。
        category = source.get("category", get_physical_name(definition))
        names = get_task_options(script_name, category, source["path"])
        assert names is None or (
            isinstance(names, list)
            and all(isinstance(name, str) and name for name in names)
        ), f"{script_name} 的副本来源必须返回名称列表: {source}"
        group["values"] = [{"display_name": name} for name in (names or [])]
        validate_options(group["values"], f"{script_name}/{source}")
    assert "values" in group
    for option in group["values"]:
        if "options" in option:
            option["options"] = _expand_options(script_name, option)
    return group


def get_weekly_map(script_name: str) -> list[dict]:
    """读取指定脚本周常，并展开各层资源。"""
    declarations = load_weekly_map()
    if script_name not in declarations:
        return []
    definitions = deepcopy(declarations[script_name])
    for definition in definitions:
        if "options" in definition:
            definition["options"] = _expand_options(script_name, definition)
    return definitions


def get_daily_map() -> dict[str, list[dict]]:
    """读取日常声明，并按相同规则展开各层资源。"""
    data = deepcopy(load_daily_map())
    for script_name, definitions in data.items():
        for definition in definitions:
            if "options" not in definition:
                continue
            definition["options"] = _expand_options(script_name, definition)
    return data


def build_task_item(
    definition: dict,
    selection: tuple[str | int | None, str | int | None],
    use_first_option: bool = True,
    enabled: bool | None = None,
) -> dict:
    """合并任务声明与当前选择，生成统一的行和菜单数据。"""
    assert "display_name" in definition
    validate_selection_depth(definition)
    option_name, sequence = selection
    menu = []
    options = get_options(definition)
    for option in options:
        assert "display_name" in option
        choices = get_options(option)
        if "options" in option and not choices:
            continue  # 资源缺失时，分类不能退化为可直接写入的副本。
        menu.append(
            {
                "name": option["display_name"],
                "options": [
                    {"name": choice["display_name"], "value": get_physical_name(choice)}
                    for choice in choices
                ],
            }
        )
    # 有原生绑定却没有当前值时不猜选项，避免误显示停用或未选目标。
    has_binding = has_selection_binding(definition)
    # 培养方案/目标等无字段的展示项仍使用首项。
    if use_first_option and not has_binding and option_name is None and menu:
        option_name = menu[0]["name"]
    label = str(option_name) if option_name is not None else "选择副本"
    if sequence is not None:
        for option in options:
            if option["display_name"] != option_name:
                continue
            aliases = {
                get_physical_name(choice): choice["display_name"]
                for choice in get_options(option)
            }
            display = str(sequence)
            if not isinstance(sequence, bool) and sequence in aliases:
                display = aliases[sequence]
            label = (
                f"{option_name} · {display}"
                if "key" in definition["options"]
                else display
            )
            break
    if definition.get("allow_disable", False):  # 无此能力时不提供停用操作。
        menu.insert(0, {"name": "不启用", "options": [], "action": "disable"})
        if enabled is False:
            label = "不启用"
    return {
        "name": get_physical_name(definition),
        "display_name": definition["display_name"],
        "selection_label": label,
        "options": menu,
    }


class AppService:
    """组合根：装配平级 service peer 并向外暴露统一接口（GUI/CLI 唯一门面）。"""

    def __init__(self):
        """装配各 peer。"""

    # ── 配置备份 / 恢复（src.service.backup_service 模块函数）──
    def create_backup(self) -> dict:
        """打包各子脚本配置，返回 ZIP 路径与文件数。"""
        return backup_service.create_backup()

    def restore_backup(self, zip_path: str) -> dict:
        """按当前脚本目录恢复并保留游戏路径，返回恢复文件数和跳过的脚本。"""
        return backup_service.restore_backup(zip_path)

    # ── 任务声明与资源选项 ─────────────────────────────────────────
    def get_weekly_map(self, script_name: str) -> list:
        """读取周常声明并展开本地资源选项。"""
        return get_weekly_map(script_name)

    def get_daily_map(self) -> dict:
        """读取日常声明并展开本地资源选项。"""
        return get_daily_map()

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
    def get_weekly_start(self, script_name: str):
        """返回某脚本的周常起始日（1~7），未设置返回 None。"""
        return get_weekly_start(script_name)

    def weekly_inputs(self, script_name: str) -> list:
        """返回配置弹窗 7 个超时输入框的初始值。"""
        return weekly_inputs(script_name)

    def set_weekly_start(self, script_name: str, start_day) -> None:
        """持久化某脚本的周常起始日（周几起）到 weekly.yml 的 weekly_start 段。"""
        return set_weekly_start(script_name, start_day)

    def get_weekly_start_map(self) -> dict:
        """读取 weekly.yml 的 weekly_start 段 全量映射（{脚本标识: 1~7}）。"""
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

    def set_script_enabled(self, changes: dict[str, bool]) -> None:
        return set_script_enabled(changes)

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
        weekly_start_day: int | None = None,
    ):
        return update_script(
            old_script_name,
            new_display_name,
            config_patch,
            weekly_timeouts,
            weekly_start_day,
        )

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

    def run_daily_plan(self) -> None:
        return daily_plan.run_daily_plan()

    def collect_invalid_scripts(self, script_list: list) -> list:
        return collect_invalid_script_messages(script_list)

    # ── 任务展示与编辑 ─────────────────────────────────────────────
    # 副本写入各脚本**自身**的 config（适配器层）；周几起由 update_script
    # 统一落盘（含游戏侧同步），不经此节入口。
    def get_daily_items(self, script_name: str, daily_defs: list[dict]) -> list[dict]:
        """按声明顺序反读每个日常，返回统一的行和选项数据。"""
        items = []
        for daily in daily_defs:
            assert "display_name" in daily, "日常必须声明 display_name"
            enabled = (
                get_task_enabled(script_name, get_physical_name(daily))
                if daily.get("allow_disable", False)
                else None
            )
            selection = (
                get_daily_task(script_name, get_physical_name(daily))
                if enabled is not False
                else (None, None)
            )
            items.append(build_task_item(daily, selection, enabled=enabled))
        return items

    def get_weekly_items(self, script_name: str) -> list[dict]:
        """周常与日常共用菜单和回显组装。"""
        items = []
        for weekly in self.get_weekly_map(script_name):
            assert "display_name" in weekly
            enabled = (
                get_task_enabled(script_name, get_physical_name(weekly))
                if weekly.get("allow_disable", False)
                else None
            )
            selection = (
                get_weekly_task(script_name, get_physical_name(weekly))
                if get_options(weekly) and enabled is not False
                else (None, None)
            )
            item = build_task_item(
                weekly, selection, use_first_option=False, enabled=enabled
            )
            item["has_options"] = bool(item["options"])
            if not item["has_options"]:
                item["selection_label"] = ""
            items.append(item)
        return items

    def get_weekly_task_options(self, script_name: str, weekly_name: str) -> list[str]:
        """返回指定周常的菜单名称；无选项或未声明时为空。"""
        for weekly in self.get_weekly_map(script_name):
            assert "display_name" in weekly, "周常必须声明 display_name"
            if get_physical_name(weekly) == weekly_name:
                item = build_task_item(weekly, (None, None), use_first_option=False)
                return [
                    option["name"]
                    for option in item["options"]
                    if "action" not in option
                ]
        return []

    def set_task_enabled(self, script_name: str, task_name: str, enabled: bool) -> None:
        """编辑一个具名任务的原生启用状态。"""
        set_task_enabled(script_name, task_name, enabled)

    def set_daily_task(
        self,
        script_name: str,
        daily_name: str,
        option_name: str,
        sequence: str | int | None = None,
    ) -> None:
        """将指定日常的副本/二级序列实时写回脚本自身配置。"""
        set_config(
            script_name,
            option_name=option_name,
            sequence=sequence,
            daily_name=daily_name,
        )

    def set_weekly_task_option(
        self,
        script_name: str,
        weekly_name: str,
        option_name: str,
        sequence: str | int | None = None,
    ) -> None:
        """写某周常当前选中的副本名到脚本自身 config。"""
        return set_weekly_task_option(script_name, weekly_name, option_name, sequence)

    # ── 自定义壁纸表（config/wallpaper.json，src.utils.utils_wallpaper）──
    def load_wallpapers(self) -> dict:
        """读取壁纸表（{脚本标识: 壁纸路径}）；缺失/损坏返回空 dict。"""
        return load_wallpapers()

    def save_wallpapers(self, wallpapers: dict) -> None:
        """原子写回壁纸表。"""
        return save_wallpapers(wallpapers)

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
