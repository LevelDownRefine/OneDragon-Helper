"""脚本配置适配器与 ScriptConfigFacade 统一入口。"""

import logging
import os
from collections.abc import Callable
from copy import deepcopy
from functools import cache

from src.config.daily import DAILY_CLASSES, Daily, MaaDaily
from src.config.task_config import get_daily_configs
from src.config.weekly import build_weeklies
from src.utils.utils_dict import get_field, safe_update
from src.utils.utils_sub_config import (
    get_sub_config_path as _get_config_path_impl,
)
from src.utils.utils_sub_config import (
    load_config,
    load_game_config,
    load_template,
    save_config,
)

logger = logging.getLogger(__name__)


# ============================================================
# 基类
# ============================================================


class ScriptConfig:
    """单个自动化脚本的 config 操作基类"""

    _script_name: str = ""
    """内部标识：script_path basename 去后缀，_CONFIGS 注册表索引。"""
    display_name: str = ""
    """GUI 展示名（如 鸣潮）。"""

    _game_path_keys: tuple[str, ...] = ()
    """游戏 exe 路径在游戏配置中的嵌套键路径；空元组表示未适配「打开游戏」。"""

    """config 文件相对脚本根目录路径。"""

    _backup_paths: tuple[str, ...] = ()
    """备份范围：相对脚本根目录的路径，元素可为目录（整目录打包）或文件。

    与读写路径解耦：读写关心「哪个文件的哪个字段」，备份关心「该脚本的配置面在哪」；
    声明了本属性即表示要备份的配置全在这些路径里。
    """

    _game_config_rel_path: str = ""
    """游戏路径配置文件路径（声明 _game_path_keys 时必填）。"""

    _template_rel_path: str = ""
    """模板文件路径（走模板初始化的子类必填）。"""

    background: str = ""
    """启动器背景图相对脚本根目录路径；空字符串走渐变占位。"""

    def __init__(self) -> None:
        """按声明创建日常与周常对象，并在构造时对齐子脚本 config。

        两者装配同一时机（日常 ``_dailies`` / 周常 ``_weeklies``）；对齐经 ``_init_config``
        收口到构造期。``functools.cache`` 单例保证每进程每脚本仅构造一次，故对齐也仅
        触发一次。CLI/GUI 均经工厂构造，无需分散守卫。
        """
        self._dailies: list[Daily] = []
        seen: set[str] = set()
        for declaration in get_daily_configs(self._script_name):
            class_name = declaration["class"]
            assert class_name in DAILY_CLASSES, (
                f"[set_config][{self.display_name}] 未知的日常机制类: {class_name!r}"
            )
            daily = DAILY_CLASSES[class_name](
                self._script_name, declaration, self.display_name
            )
            assert daily.physical_name not in seen, (
                f"{self._script_name} 的日常物理名重复: {daily.physical_name}"
            )
            seen.add(daily.physical_name)
            self._dailies.append(daily)
        # 构造期装配周常对象（与日常同一时机；无周常声明的脚本得到空列表）
        self._weeklies = build_weeklies(self._script_name, self.display_name)
        # 构造期对齐子脚本 config（懒加载收口点；无模板/未安装脚本为空操作）
        self._init_config()

    def _daily_config_rel_path(self) -> str:
        """脚本 config 文件路径（取首个日常声明的 ``config``）。

        模板对齐与「打开配置」共用该文件——脚本 config 与日常所在文件恰好同份。

        Returns:
            相对脚本根目录的路径。
        """
        return self._dailies[0]._config_rel_path

    def _load_template(self) -> dict:
        """加载模板文件（JSON/YAML）。

        Returns:
            模板 dict。

        Raises:
            AssertionError: 未声明 _template_rel_path 或解析结果非 dict。
        """
        assert self._template_rel_path, (
            f"[set_config][{self.display_name}] 未声明 _template_rel_path"
        )
        return load_template(self._script_name, self._template_rel_path)

    def _dispatch_daily(self, daily_display_name: str) -> Daily:
        """按日常展示名取日常对象。

        Args:
            daily_display_name: 日常展示名（界面行名）。

        Returns:
            对应的日常对象。

        Raises:
            AssertionError: 声明里没有该展示名的日常。
        """
        matches = [
            daily for daily in self._dailies if daily.display_name == daily_display_name
        ]
        assert len(matches) == 1, (
            f"[set_config][{self.display_name}] 未知日常: {daily_display_name}"
        )
        return matches[0]

    def _read_daily_tasks(self) -> list[dict]:
        """反读该脚本全部日常的已选项与开关（界面按日常逐行呈现）。

        日常集合由声明推导，调用方无需指定日常。每项一条记录：

        - ``name``：日常展示名；
        - ``task``：已选一级项展示名；未选择/无真相为 None；
        - ``sequence``：已选二级值；无二级或未选择为 None；
        - ``enabled``：是否启用；该脚本无日常开关文件时为 None。

        Returns:
            [{name, task, sequence, enabled}, ...]，顺序与声明一致。
        """
        records = []
        for daily in self._dailies:
            task, sequence = daily.read()
            records.append(
                {
                    "name": daily.display_name,
                    "task": task,
                    "sequence": sequence,
                    "enabled": daily.read_enabled(),
                }
            )
        return records

    def _init_config(self) -> None:
        """对齐检查并把模板 config 同步到用户 config。

        仅对有模板（声明 ``_template_rel_path``）的脚本生效；无模板脚本或脚本尚未
        安装/未配置（config 缺失）时直接返回，不触碰 config。已对齐时不动 config。
        """
        if not self._template_rel_path:
            return
        rel_path = self._daily_config_rel_path()
        try:
            config = load_config(self._script_name, rel_path)
        except AssertionError:
            return  # 脚本未安装/未配置，待首次写入时由 set_* 创建
        except Exception:  # noqa: BLE001  # 文件存在但内容损坏
            logger.warning(
                f"[init_config][{self.display_name}] config 损坏，跳过对齐: {rel_path}",
                exc_info=True,
            )
            return
        if not isinstance(config, dict):
            return
        template = self._load_template()

        if self._is_aligned(config, template):
            logger.info(f"[init_config][{self.display_name}] config 已对齐，无需更新")
            return

        for key, val in template.items():
            safe_update(config, key, val, self.display_name, assert_key_exists=False)
        save_config(self._script_name, rel_path, config)
        reloaded = load_config(self._script_name, rel_path)
        assert reloaded == config, (
            f"[init_config][{self.display_name}] 配置保存后校验失败："
            "重新读取的内容与预期不一致"
        )
        logger.info(f"[init_config][{self.display_name}] config 已更新")

    def _is_aligned(self, config: dict, template: dict) -> bool:
        """递归比较 config 是否涵盖模板全部结构。

        dict 递归、list 按索引、其余直接比值。

        Args:
            config: 当前 config dict。
            template: 模板 dict。

        Returns:
            config 是否已与模板对齐。
        """

        def _aligned(a, b):
            if isinstance(a, dict) and isinstance(b, dict):
                return all(k in a and _aligned(a[k], b[k]) for k in b)
            if isinstance(a, list) and isinstance(b, list):
                if len(a) < len(b):
                    return False
                return all(_aligned(a[i], b[i]) for i in range(len(b)))
            return a == b

        return all(
            key in config and _aligned(config[key], template[key]) for key in template
        )

    def set_daily_task(
        self,
        daily_display_name: str,
        task_name: str,
        sequence: str | int | None = None,
    ) -> None:
        """设置副本：读盘 → 交给该日常写内存 → 有改动才落盘 → 顺带启用该日常。

        启用经 ``set_daily_enabled``，无日常开关文件的脚本静默跳过。

        Args:
            daily_display_name: 副本所属日常展示名（界面逐行渲染时即该行行名）。
            task_name: 一级项展示名（副本名）。
            sequence: 二级项值；不传则仅写入一级落点。

        Raises:
            AssertionError: 未给出日常展示名，或该日常未知、config 未安装/未配置、
                该日常在 config 里缺少段、无落点、一级项未声明、二级必填却缺失。
        """
        assert daily_display_name, f"[set_config][{self.display_name}] 必须指定日常"
        self._dispatch_daily(daily_display_name).update(task_name, sequence)
        self.set_daily_enabled(daily_display_name, True)

    def set_daily_enabled(self, daily_display_name: str, enabled: bool) -> None:
        """启用/停用某日常：读开关文件 → 交给该日常改内存 → 有改动才落盘。

        该脚本无日常开关文件时不做事（选择即启用，无开关可写）。

        Args:
            daily_display_name: 日常展示名。
            enabled: 目标启用状态。

        Raises:
            AssertionError: 该日常未知，或 Routine Items 缺少或重复该日常的物理名。
        """
        daily = self._dispatch_daily(daily_display_name)
        daily.set_enabled(enabled)  # 无日常开关的机制类不做事（选择即启用）

    def get_game_exe_path(self) -> str | None:
        """读取本脚本配置中的游戏 exe 路径。

        Returns:
            exe 绝对路径；未适配、缺失或为空时返回 None。
        """
        if not self._game_path_keys:
            return None
        game_config = load_game_config(self._script_name, self._game_config_rel_path)
        if game_config is None:
            return None
        node = game_config
        for key in self._game_path_keys:
            if not isinstance(node, dict) or key not in node:
                logger.warning(
                    f"[get_game_exe_path][{self._script_name}] 配置缺少字段: "
                    f"{self._game_path_keys}"
                )
                return None
            node = node[key]
        if not isinstance(node, str) or not node:
            logger.warning(
                f"[get_game_exe_path][{self._script_name}] 游戏路径字段非字符串或为空"
            )
            return None
        return node


# ============================================================
# 注册表
# ============================================================

# 由 register() 装饰器显式填充（必须在子类定义前初始化）。
_CONFIGS: dict[str, Callable[[], ScriptConfig]] = {}


def register(cls: type[ScriptConfig]) -> type[ScriptConfig]:
    """校验必要声明，注册首次访问时构造、之后复用的适配器入口。

    必填属性须由子类在 ``cls.__dict__`` 中显式声明（而非继承基类默认值）；
    声明了条件属性（_game_path_keys）必须补全对应依赖。

    Args:
        cls: 待注册的 ScriptConfig 子类。

    Returns:
        原样返回 cls（便于装饰器使用）。

    Raises:
        AssertionError: 缺少 _script_name/_backup_paths 显式声明，
            或声明了 _game_path_keys 但未补全对应声明/实现。
    """
    for attr in ("_script_name", "_backup_paths"):
        assert attr in cls.__dict__, f"[set_config][{cls.__name__}] 必须声明 {attr}"
    if cls._game_path_keys:
        assert "_game_config_rel_path" in cls.__dict__, (
            f"[set_config][{cls.__name__}] 声明了 _game_path_keys 必须声明 "
            f"_game_config_rel_path"
        )
    _CONFIGS[cls._script_name] = cache(cls)
    return cls


# ============================================================
# 各脚本子类
# ============================================================


# ---- 鸣潮 Wuthering Waves ----
@register
class WutheringWavesConfig(ScriptConfig):
    _script_name = "ok-ww"
    _backup_paths = ("data/apps/ok-ww/working/configs",)
    _game_config_rel_path = "data/apps/ok-ww/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "鸣潮"


# ---- 原神 Genshin Impact ----
@register
class GenshinConfig(ScriptConfig):
    _script_name = "BetterGI"
    display_name = "原神"

    _backup_paths = ("User",)
    _game_config_rel_path = "User/config.json"
    _template_rel_path = "BGI一条龙.json"
    _game_path_keys = ("genshinStartConfig", "installPath")


# ---- 终末地 Arknights: Endfield ----
@register
class EndfieldConfig(ScriptConfig):
    _script_name = "ok-ef"
    display_name = "终末地"

    _template_rel_path = "okef一条龙.json"
    _backup_paths = ("data/apps/ok-ef/working/configs",)
    _game_config_rel_path = "data/apps/ok-ef/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)


# ---- 绝区零 Zenless Zone Zero ----
@register
class ZenlessZoneZeroConfig(ScriptConfig):
    _script_name = "OneDragon-Launcher"
    display_name = "绝区零"
    _backup_paths = ("config",)
    _game_config_rel_path = "config/01/game_account.yml"
    _template_rel_path = "ZZZ一条龙.yml"
    _game_path_keys = ("game_path",)
    background = "assets/ui/static_background.webp"


# ---- 崩铁 Honkai: Star Rail ----
@register
class StarRailConfig(ScriptConfig):
    _script_name = "March7th-Launcher"
    display_name = "崩铁"
    _backup_paths = ("config.yaml",)
    _game_config_rel_path = "config.yaml"
    _template_rel_path = "M7A一条龙.yml"
    _game_path_keys = ("game_path",)
    background = "assets/app/images/bg37.jpg"


# ---- 异环 Neverness to Everness (NTE) ----
@register
class NTEConfig(ScriptConfig):
    _script_name = "ok-nte"
    _backup_paths = ("data/apps/ok-nte/working/configs",)
    _game_config_rel_path = "data/apps/ok-nte/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "异环"

    _launcher_rel_path = "NTELauncher.exe"
    """异环启动器文件名（相对游戏安装根目录，非游戏本体）。"""

    def get_game_exe_path(self) -> str | None:
        """重写：从游戏本体路径向上查找异环启动器。

        Returns:
            启动器绝对路径；本体缺失或找不到启动器时返回 None。
        """
        game_exe = super().get_game_exe_path()
        if not game_exe:
            return None
        directory = os.path.dirname(game_exe)
        while True:
            candidate = os.path.join(directory, self._launcher_rel_path)
            if os.path.isfile(candidate):
                return candidate
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        logger.warning(
            f"[get_game_exe_path][{self._script_name}] 未找到启动器 {self._launcher_rel_path}"
        )
        return None


# ---- 明日方舟 Arknights（粥）----
@register
class ArknightsConfig(ScriptConfig):
    _script_name = "MAA"
    display_name = "粥"
    _backup_paths = ("config",)
    _game_config_rel_path = "config/gui.new.json"
    _game_path_keys = (
        "Configurations",
        "Default",
        "Gui",
        "StartUpSettings",
        "EmulatorPath",
    )

    def _init_config(self) -> None:
        """建立三个独立入口和必刷剿灭，交给 MAA 原生队列执行。"""
        activity, main, remaining = self._dailies
        assert all(isinstance(daily, MaaDaily) for daily in self._dailies)
        config = main._load_daily_config(allow_missing=True)
        if config is None:
            return
        queue = main._task_queue(config)
        before = deepcopy(queue)
        days = main._medicine_days(queue)
        fights = self._init_fight_tasks(queue, days)
        self._order_tasks(queue, fights)
        main._set_medicine(queue, days)
        if queue != before:
            main._save_daily_config(config)

    def _init_fight_tasks(self, queue: list[dict], days: int) -> list[dict]:
        """准备必刷剿灭和三个日常入口，保留各自已有设置。"""
        main = self._dailies[1]
        annihilation = None
        daily_names = {daily.physical_name for daily in self._dailies}
        for task in queue:
            kind = get_field(task, "$type", "MAA", str)
            if kind != "FightTask":
                continue
            if not ("Name" in task and task["Name"] in daily_names) and (
                main._stage(task) == "Annihilation"
                or ("Name" in task and task["Name"] == "剿灭作战")
            ):
                annihilation = task
                break
        if annihilation is None:
            annihilation = main._new_task("剿灭作战")
        main._configure_task(annihilation, "Annihilation", True, days)
        annihilation["IsStageManually"] = False
        selected = [daily._init_task(queue, days) for daily in self._dailies]
        return [annihilation, *selected]

    def _order_tasks(self, queue: list[dict], fights: list[dict]) -> None:
        """唤醒后安排剿灭和活动，库存保持后安排其余日常；清理多余战斗。"""
        others = [task for task in queue if task["$type"] != "FightTask"]
        # 插入点按非战斗队列计算，原生任务的相对顺序保持不变。
        wake = next(
            (i + 1 for i, task in enumerate(others) if task["$type"] == "StartUpTask"),
            0,
        )
        depot = next(
            (
                i + 1
                for i, task in enumerate(others)
                if task["$type"] == "DepotMaintainTask"
            ),
            wake,
        )
        normal = max(wake, depot)
        queue[:] = (
            others[:wake]
            + fights[:2]
            + others[wake:normal]
            + fights[2:]
            + others[normal:]
        )


# ============================================================
# 配置外观
# ============================================================


class ScriptConfigFacade:
    """脚本配置统一入口：查找适配器并委托，文件格式与读写仍由适配器负责。

    统一使用内置注册表，各外观实例共享其中已有的懒加载单例。
    """

    def _find_config(self, script_name: str) -> ScriptConfig | None:
        """按需取得适配器；自定义脚本没有适配器。"""
        if script_name not in _CONFIGS:
            return None
        assert script_name in _CONFIGS
        return _CONFIGS[script_name]()

    def _require_config(self, script_name: str) -> ScriptConfig:
        """要求已适配的操作共用此断言入口。"""
        config = self._find_config(script_name)
        assert config is not None, f"[set_config] 未适配脚本: {script_name}"
        return config

    def init_config(self, script_name: str) -> None:
        """强制重新对齐模板，供新增/修改脚本或恢复配置后调用。"""
        config = self._find_config(script_name)
        if config is not None:
            config._init_config()

    def ensure_config(self, script_name: str) -> None:
        """按需构造并对齐一次，与日常读取共用单例；未知脚本跳过。"""
        self._find_config(script_name)

    def init_config_all(self) -> None:
        """强制对齐全部已注册脚本的配置。"""
        for script_name in _CONFIGS:
            self.init_config(script_name)

    def get_registered_script_names(self) -> list[str]:
        """取已注册脚本标识，供预热遍历；不构造适配器。"""
        return list(_CONFIGS)

    def is_adapted(self, script_name: str) -> bool:
        """判断是否已适配，不构造适配器。"""
        return script_name in _CONFIGS

    def set_daily_task(
        self,
        script_name: str,
        daily_display_name: str | None = None,
        task_name: str | None = None,
        sequence: str | int | None = None,
    ) -> None:
        """设置日常副本/序列；未选择或自定义脚本跳过。

        Args:
            script_name: 脚本标识名。
            daily_display_name: 所属日常展示名，多日常脚本据此选段。
            task_name: 一级选项展示名；None、空串或「未选择」表示不设置。
            sequence: 二级选项值，仅部分脚本支持。
        """
        if not task_name or task_name == "未选择":
            return
        config = self._find_config(script_name)
        if config is None:
            logger.info(
                "[set_config] 进程 %s 无副本适配（自定义脚本），跳过", script_name
            )
            return
        config.set_daily_task(daily_display_name, task_name, sequence)

    def set_daily_enabled(
        self, script_name: str, daily_display_name: str, enabled: bool
    ) -> None:
        """启用/停用指定日常，不改变副本选择；要求脚本已适配。"""
        self._require_config(script_name).set_daily_enabled(daily_display_name, enabled)

    def get_daily_readback(self, script_name: str) -> list[dict]:
        """读取全部日常的已选项与开关，顺序同声明；未知脚本返回空列表。

        Returns:
            [{name, task, sequence, enabled}, ...]，字段见 ScriptConfig._read_daily_tasks。
        """
        config = self._find_config(script_name)
        return config._read_daily_tasks() if config is not None else []

    def get_task_lists(
        self, script_name: str, daily_display_name: str, source: dict
    ) -> list[str] | None:
        """复用 Daily 读取 options.source 声明中的副本资源；不可用时返回 None。"""
        config = self._find_config(script_name)
        if config is None:
            return None
        return config._dispatch_daily(daily_display_name).get_task_lists(source)

    def get_config_path(self, script_name: str) -> str:
        """取配置绝对路径供界面打开；要求脚本已适配。"""
        config = self._require_config(script_name)
        return _get_config_path_impl(script_name, config._daily_config_rel_path())

    def get_game_exe_path(self, script_name: str) -> str | None:
        """读游戏 exe 路径；未适配或缺失时返回 None。"""
        config = self._find_config(script_name)
        return config.get_game_exe_path() if config is not None else None

    def get_background_rel_path(self, script_name: str) -> str:
        """读脚本背景图相对路径；未适配或未声明时返回空字符串。"""
        config = self._find_config(script_name)
        return config.background if config is not None else ""

    def get_game_path_keys(self, script_name: str, rel: str) -> tuple[str, ...]:
        """查询配置文件的游戏路径字段，供恢复备份时保留；其他文件返回空元组。"""
        config = self._find_config(script_name)
        if config is None or rel.casefold() != config._game_config_rel_path.casefold():
            return ()
        return config._game_path_keys

    def iter_backup_paths(self) -> dict[str, tuple[str, ...]]:
        """汇总已适配脚本的备份范围；相对目录/文件的展开由备份层负责。"""
        return {
            script_name: self._require_config(script_name)._backup_paths
            for script_name in _CONFIGS
        }
