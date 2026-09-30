"""副本配置适配器：统一 set_config 适配接口，按各脚本格式封装 config 读写。"""

import logging
import os
from collections.abc import Callable
from copy import deepcopy
from functools import cache

from src.config.daily import Daily, MaaDaily, build_dailies
from src.config.script_resources import ScriptResources, get_script_resources
from src.config.task_config import load_weekly_map
from src.config.weekly import Weekly, build_weeklies
from src.utils.utils_dict import covers, get_field, safe_update
from src.utils.utils_sub_config import (
    get_script_game_path,
    load_config,
    load_game_config,
    load_template,
    save_config,
)
from src.utils.utils_sub_config import (
    get_sub_config_path as _get_config_path_impl,
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

    resources: ScriptResources | None = None
    """静态资源来自 script_resources.yml；基类 None 表示未适配。"""

    def __init__(self) -> None:
        """按声明创建日常与周常对象，并在构造时对齐子脚本 config。

        两者装配同一时机（日常 ``_dailies`` / 周常 ``_weeklies``）；对齐经 ``_init_config``
        收口到构造期。``functools.cache`` 单例保证每进程每脚本仅构造一次，故对齐也仅
        触发一次。CLI/GUI 均经工厂构造，无需分散守卫。
        """
        self._dailies: list[Daily] = build_dailies(self._script_name, self.display_name)
        self._weeklies: list[Weekly] = build_weeklies(
            self._script_name, self.display_name
        )
        # 构造期对齐子脚本 config（懒加载收口点；无模板/未安装脚本为空操作）
        self._init_config()

    def _daily_config_rel_path(self) -> str:
        """脚本 config 文件路径（取首个日常声明的 ``config``）。

        模板对齐与「打开配置」共用它。

        Returns:
            相对脚本根目录的路径。
        """
        return self._dailies[0]._config_rel_path

    def _load_template(self) -> dict:
        """加载模板文件（JSON/YAML）。

        Returns:
            模板 dict。

        Raises:
            AssertionError: 未声明 template 或解析结果非 dict。
        """
        assert self.resources is not None and "template" in self.resources, (
            f"[set_config][{self.display_name}] 未声明 template"
        )
        return load_template(self._script_name, self.resources["template"])

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

        仅对有模板（声明 ``template``）的脚本生效；无模板脚本或脚本尚未
        安装/未配置（config 缺失）时直接返回，不触碰 config。已对齐时不动 config。
        """
        if self.resources is None or "template" not in self.resources:
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

        if covers(config, template):
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

    def _weekly_named(self, weekly_name: str) -> Weekly | None:
        """按展示名取本脚本持有的周常；未知周常返回 None。"""
        for weekly in self._weeklies:
            if weekly.display_name == weekly_name:
                return weekly
        return None

    def prepare_weekly_start_days(self, start_days: dict[str, int]) -> None:
        """运行前按条目写周常开关；未设置的条目保持原样。"""
        for weekly in self._weeklies:
            if weekly.display_name in start_days:
                weekly.prepare_start_day(start_days[weekly.display_name])

    def set_weekly_start_day(self, weekly_name: str, start_day: int) -> None:
        """编辑期同步周常字面起始日；无此能力的条目跳过。"""
        weekly = self._weekly_named(weekly_name)
        if weekly is None or type(weekly).set_start_day is Weekly.set_start_day:
            return
        weekly.set_start_day(start_day)

    def set_weekly_task(self, weekly_name: str, task_name: str) -> None:
        """设置周常副本；无副本选型的条目跳过。"""
        weekly = self._weekly_named(weekly_name)
        if weekly is None or type(weekly).set_task is Weekly.set_task:
            return
        weekly.set_task(task_name)

    def _read_weekly_task(self, weekly_name: str) -> str | None:
        """反读周常副本；未知周常返回 None。"""
        weekly = self._weekly_named(weekly_name)
        if weekly is None:
            return None
        return weekly.read_task()

    def get_game_exe_path(self) -> str | None:
        """读取本脚本配置中的游戏 exe 路径。

        Returns:
            exe 绝对路径；未适配、缺失或为空时返回 None。
        """
        if self.resources is None or "game" not in self.resources:
            return None
        game = self.resources["game"]
        assert "config" in game and "keys" in game
        game_config = load_game_config(self._script_name, game["config"])
        if game_config is None:
            return None
        node = game_config
        for key in game["keys"]:
            if not isinstance(node, dict) or key not in node:
                logger.warning(
                    f"[get_game_exe_path][{self._script_name}] 配置缺少字段: "
                    f"{game['keys']}"
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
    """绑定 YAML 资源声明，注册首次访问时构造、之后复用的机制类。"""
    assert "_script_name" in cls.__dict__ and cls._script_name, (
        f"[set_config][{cls.__name__}] 必须声明 _script_name"
    )
    resources = get_script_resources(cls._script_name)
    assert resources is not None, f"[set_config] 缺少资源声明: {cls._script_name}"
    cls.resources = resources
    _CONFIGS[cls._script_name] = cache(cls)
    return cls


# ============================================================
# 各脚本子类
# ============================================================


# ---- 鸣潮 Wuthering Waves ----
@register
class WutheringWavesConfig(ScriptConfig):
    _script_name = "ok-ww"
    display_name = "鸣潮"


# ---- 原神 Genshin Impact ----
@register
class GenshinConfig(ScriptConfig):
    _script_name = "BetterGI"
    display_name = "原神"


# ---- 终末地 Arknights: Endfield ----
@register
class EndfieldConfig(ScriptConfig):
    _script_name = "ok-ef"
    display_name = "终末地"


# ---- 绝区零 Zenless Zone Zero ----
@register
class ZenlessZoneZeroConfig(ScriptConfig):
    _script_name = "OneDragon-Launcher"
    display_name = "绝区零"


# ---- 崩铁 Honkai: Star Rail ----
@register
class StarRailConfig(ScriptConfig):
    _script_name = "March7th-Launcher"
    display_name = "崩铁"


# ---- 异环 Neverness to Everness (NTE) ----
@register
class NTEConfig(ScriptConfig):
    _script_name = "ok-nte"
    display_name = "异环"

    def get_game_exe_path(self) -> str | None:
        """重写：从游戏本体路径向上查找异环启动器。

        Returns:
            启动器绝对路径；本体缺失或找不到启动器时返回 None。
        """
        assert self.resources is not None and "game" in self.resources
        game = self.resources["game"]
        assert "launcher" in game, "异环必须声明 game.launcher"
        launcher = game["launcher"]
        game_exe = super().get_game_exe_path()
        if not game_exe:
            return None
        directory = os.path.dirname(game_exe)
        while True:
            candidate = os.path.join(directory, launcher)
            if os.path.isfile(candidate):
                return candidate
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        logger.warning(
            f"[get_game_exe_path][{self._script_name}] 未找到启动器 {launcher}"
        )
        return None


# ---- 明日方舟 Arknights（粥）----
@register
class ArknightsConfig(ScriptConfig):
    _script_name = "MAA"
    display_name = "粥"

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
# 适配器接口
# ============================================================


def init_config(script_name: str) -> None:
    """对齐脚本 config 与模板，补全缺失字段（强制重对齐）。

    仅对声明了 ``template`` 的脚本生效；无模板或脚本未安装/未配置时为空操作。
    实例已缓存时不重新构造，但显式再跑一次 ``_init_config``，故用于需强制重对齐的场景
    （新增/修改脚本、备份恢复）。启动预热等幂等场景请用 :func:`ensure_config` 避免重复对齐与日志。

    Args:
        script_name: 脚本标识名。
    """
    if script_name not in _CONFIGS:
        return
    _CONFIGS[script_name]()._init_config()


def ensure_config(script_name: str) -> None:
    """确保脚本 config 已构造并模板对齐（幂等，不强制重对齐）。

    仅经工厂构造单例；``__init__`` 内已收口 ``_init_config``，故每个进程每脚本仅对齐
    一次，无重复日志/重复工作。供启动后预热遍历，与懒加载共用同一工厂出口。
    需强制重对齐（新增/修改脚本、备份恢复）请用 :func:`init_config`。

    Args:
        script_name: 脚本标识名。
    """
    if script_name not in _CONFIGS:
        return
    _CONFIGS[script_name]()


def init_config_all() -> None:
    """对齐所有已注册脚本的 config 与模板（手动全量入口，如备份恢复后）。"""
    for script_name in _CONFIGS:
        init_config(script_name)


def get_registered_script_names() -> list[str]:
    """返回所有已注册（已适配）脚本的标识名，供预热遍历。"""
    return list(_CONFIGS.keys())


def set_config(
    script_name: str,
    daily_display_name: str | None = None,
    task_name: str | None = None,
    sequence: str | int | None = None,
) -> None:
    """适配器接口：设置副本 / 序列。

    未选副本或脚本未适配（自定义脚本）时优雅跳过。周常（周几起 / 周常副本）归
    本模块的周常接口分发给同一 ScriptConfig 持有的 Weekly，不经本函数。

    Args:
        script_name: 脚本标识名。
        daily_display_name: 副本所属日常展示名（界面逐行渲染时即该行行名）；
            单日常脚本也要给，分段脚本（多日常）据此选段。
        task_name: 一级项展示名（副本站位）；None 或「未选择」表示不设置副本。
        sequence: 二级项值；仅部分脚本支持。
    """
    if not task_name or task_name == "未选择":
        return

    # 自定义脚本（不在注册表）跳过
    if script_name not in _CONFIGS:
        logger.info(f"[set_config] 进程 {script_name} 无副本适配（自定义脚本），跳过")
        return

    _CONFIGS[script_name]().set_daily_task(daily_display_name, task_name, sequence)


def get_task_lists(
    script_name: str, daily_display_name: str, source: dict
) -> list[str] | None:
    """适配器接口：复用已注册的 Daily 读取可选副本。

    Args:
        script_name: 脚本唯一标识（如 ``March7th-Launcher``）。
        daily_display_name: 所属日常展示名。
        source: 完整的 options.source 声明，资源定位不依赖任务名称。

    Returns:
        副本名列表（含「无」等占位）；不可用时返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return (
        _CONFIGS[script_name]()
        ._dispatch_daily(daily_display_name)
        .get_task_lists(source)
    )


def get_config_path(script_name: str) -> str:
    """取 config 绝对路径（供 GUI 打开）。

    Args:
        script_name: 脚本标识名。

    Returns:
        config 绝对路径。

    Raises:
        AssertionError: 脚本未适配。
    """
    assert script_name in _CONFIGS, f"[set_config] 未适配脚本: {script_name}"
    return _get_config_path_impl(
        script_name, _CONFIGS[script_name]()._daily_config_rel_path()
    )


def get_game_path_keys(script_name: str, rel: str) -> tuple[str, ...]:
    """查询该文件的游戏路径字段；复用打开游戏的声明，其他文件返回空元组。"""
    if script_name not in _CONFIGS:
        return ()
    assert script_name in _CONFIGS
    cfg = _CONFIGS[script_name]()
    assert cfg.resources is not None
    if "game" not in cfg.resources:
        return ()
    game = cfg.resources["game"]
    assert "config" in game and "keys" in game
    if rel.casefold() != game["config"].casefold():
        return ()
    return tuple(game["keys"])


def iter_backup_paths() -> dict[str, tuple[str, ...]]:
    """遍历各已适配脚本的备份范围（相对脚本根目录，元素可为目录或文件）。

    「该脚本的配置面在哪」的知识归适配层，本函数只做汇总；展开（目录递归 /
    单文件收录）由备份层处理。

    Returns:
        {脚本唯一标识: (备份路径, ...)}。
    """
    paths = {}
    for script_name, factory in _CONFIGS.items():
        resources = factory().resources
        assert resources is not None and "backup_paths" in resources
        paths[script_name] = tuple(resources["backup_paths"])
    return paths


def get_game_exe_path(script_name: str) -> str | None:
    """读游戏 exe 路径（供 GUI 打开游戏、取游戏图标）。

    config.yml 条目里手填的 ``game_path`` 优先 —— 它是用户显式指定的；未填时才回退到脚本
    原生配置里的路径（脚本自管，异环那类可能指向启动器，不自启游戏的 MaaEnd 则没有）。

    Returns:
        exe 绝对路径；两处都没有时返回 None。
    """
    path = get_script_game_path(script_name)
    if path:
        return path
    if script_name in _CONFIGS:
        return _CONFIGS[script_name]().get_game_exe_path()
    return None


def is_adapted(script_name: str) -> bool:
    """查询脚本是否已注册副本适配（供 GUI 决定是否显示任务卡）。"""
    return script_name in _CONFIGS


def get_background_rel_path(script_name: str) -> str:
    """读脚本默认背景图相对路径（相对脚本根目录，供 GUI 背景控制器）。

    Args:
        script_name: 脚本标识名。

    Returns:
        背景图相对路径；未适配或未声明背景图时返回空字符串。
    """
    if script_name not in _CONFIGS:
        return ""
    assert script_name in _CONFIGS
    resources = _CONFIGS[script_name]().resources
    assert resources is not None
    if "background" not in resources:
        return ""
    assert "background" in resources
    return resources["background"]


def get_daily_readback(script_name: str) -> list[dict]:
    """读该脚本全部日常的已选项与开关（反读子脚本 config，界面按日常逐行呈现）。

    日常集合由声明推导，故无需调用方指定日常。未适配脚本返回空列表。

    Args:
        script_name: 脚本标识名。

    Returns:
        [{name, task, sequence, enabled}, ...]；顺序与声明一致。各字段含义见
        ``ScriptConfig._read_daily_tasks``。
    """
    if script_name not in _CONFIGS:
        return []
    return _CONFIGS[script_name]()._read_daily_tasks()


def set_daily_enabled(script_name: str, daily_display_name: str, enabled: bool) -> None:
    """适配器接口：启用/停用某日常（仅声明了日常开关的子类支持）。

    开关只动启用状态、不动副本选择，故日常仍由调用方显式给出。

    Args:
        script_name: 脚本标识名。
        daily_display_name: 日常展示名。
        enabled: 目标启用状态。
    """
    assert script_name in _CONFIGS, f"未适配脚本: {script_name}"
    _CONFIGS[script_name]().set_daily_enabled(daily_display_name, enabled)


def weekly_names(script_name: str) -> list[str]:
    """只读声明中的周常名称，查询与旧配置迁移不触发原生配置初始化。"""
    declarations = load_weekly_map()
    if script_name not in declarations:
        return []
    assert script_name in declarations
    names = []
    for declaration in declarations[script_name]:
        assert "display_name" in declaration
        names.append(declaration["display_name"])
    return names


def supports_weekly(script_name: str) -> bool:
    """查询是否声明了周常，不构造配置适配器。"""
    return bool(weekly_names(script_name))


def prepare_weekly_start_days(script_name: str, start_days: dict[str, int]) -> None:
    """运行期入口：经脚本适配器写入已设置的周常开关（0 表示不启用）。"""
    if script_name not in _CONFIGS:
        return
    assert script_name in _CONFIGS
    _CONFIGS[script_name]().prepare_weekly_start_days(start_days)


def set_weekly_start_day(script_name: str, weekly_name: str, start_day: int) -> None:
    """编辑期入口：经脚本适配器同步该条周常的游戏侧字面起始日。"""
    if script_name not in _CONFIGS:
        return
    assert script_name in _CONFIGS
    _CONFIGS[script_name]().set_weekly_start_day(weekly_name, start_day)


def set_weekly_task(script_name: str, weekly_name: str, task_name: str) -> None:
    """编辑期入口：经脚本适配器写入周常副本。"""
    if script_name not in _CONFIGS:
        return
    assert script_name in _CONFIGS
    _CONFIGS[script_name]().set_weekly_task(weekly_name, task_name)


def get_weekly_task(script_name: str, weekly_name: str) -> str | None:
    """经脚本适配器反读周常副本；未适配脚本返回 None。"""
    if script_name not in _CONFIGS:
        return None
    assert script_name in _CONFIGS
    return _CONFIGS[script_name]()._read_weekly_task(weekly_name)
