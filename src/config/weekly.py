"""一条周常的落点：由 ``weekly_task_list.yml`` 一条声明解析出的读写规则。

与日常同构——**一条周常一个对象**（一个脚本可有多条，如崩铁的货币战争 / 历战余响 /
模拟宇宙），声明里用 ``class`` 标机制类（``WEEKLY_CLASSES`` 查表）、``config`` 标读写的
主文件；对象由 ``ScriptConfig`` 在构造期经 :func:`build_weeklies` 装配并持有，故初始化
时机与日常一致。

周几起（``weekly.yml`` 的 ``weekly_start`` 段）是**条目级**的：每条周常各有一个起始日；
取值 ``DISABLED_START_DAY``（= 0）表示**不启用**——每次运行都把开关写成关闭，与「未设置」
（条目缺席、不动开关）不同。

三类入口按真相归属分开：

- ``prepare_start_day``：运行期唯一写入口，按「今天是否到起始日」折算后写开关；
- ``set_start_day``：编辑期字面落盘，仅需要字面字段 / 额外开关的周常覆写；
- ``set_task`` / ``read_task``：副本选型（当前无周常声明 ``options``，机制保留待用）。

落点形态随周常而异（Additional Tasks 列表增删、布尔字段、``_group.yml`` 的 app 条目、
TaskQueue 公式），各由子类覆写；基类只兜底 assert。
"""

import logging

from src.config.task_config import get_physical_name, get_value_map, load_weekly_map
from src.utils.utils_dict import get_field, safe_update
from src.utils.utils_sub_config import load_script_config, save_script_config
from src.utils.utils_weekly import DISABLED_START_DAY, is_weekly_start_reached

logger = logging.getLogger(__name__)


# ============================================================
# 基类
# ============================================================


class Weekly:
    """单条周常：名称、由声明解析出的落点，以及它那部分的读写规则。

    Attributes:
        script_name: 所属脚本标识名。
        script_display_name: 所属脚本的展示名（日志与报错用）。
        display_name: 周常展示名，来自声明；界面行名与匹配键。
        physical_name: 周常物理名，按落点形态各取所需（列表元素值 / app_id / 段名）。
        key: 原生字段名，来自声明（列表字段 / 开关字段 / 起始日字段）。
    """

    def __init__(
        self, script_name: str, declaration: dict, script_display_name: str
    ) -> None:
        """解析一条周常声明。

        Args:
            script_name: 所属脚本标识名。
            declaration: ``weekly_task_list.yml`` 里该周常的声明节点；
                ``class``（机制类）与 ``config``（读写主文件）已由读取层校验，
                ``key``（原生字段名）可选，路径相对脚本根目录。
            script_display_name: 所属脚本的展示名（日志与报错用）。
        """
        self.script_name = script_name
        self.script_display_name = script_display_name
        self.display_name: str = declaration["display_name"]
        self.physical_name: str | int = get_physical_name(declaration)
        self._config_rel_path: str = declaration["config"]
        self._key: str = declaration.get("key", "")
        self._enable_key: str = declaration.get("enable_key", "")
        """启用开关的原生字段名；落点本身不是布尔开关时才需要声明（如历战余响）。"""
        self._task_values: dict[str, str | int] = get_value_map(declaration)
        """该周常的「展示名 → 物理值」映射（副本选型用）；声明走资源来源时为空。"""

    def _load_config(self, *, allow_missing: bool = False) -> dict | None:
        """读周常所在的 config 文件（缺失与损坏语义见 ``load_script_config``）。

        Args:
            allow_missing: True 时读取失败返回 None（读路径）；
                False 时失败即报错（写路径，默认）。

        Returns:
            解析后的 config dict；仅 allow_missing=True 且读取失败时为 None。
        """
        return load_script_config(
            self.script_name,
            self.script_display_name,
            self._config_rel_path,
            allow_missing=allow_missing,
        )

    def _save_config(self, config: dict) -> None:
        """保存周常所在的 config 文件并回读校验落盘一致。

        Args:
            config: 待保存的 dict。

        Raises:
            AssertionError: config 非 dict 或保存后回读不一致。
        """
        save_script_config(
            self.script_name, self.script_display_name, self._config_rel_path, config
        )

    def _check_start_day(self, start_day: int) -> None:
        """校验周常起始日，供各子类写入口首行调用。

        Args:
            start_day: 周几以后启用（1~7，1=周一）；``DISABLED_START_DAY`` 表示不启用。

        Raises:
            AssertionError: start_day 既不是 DISABLED_START_DAY 也不在 1~7。
        """
        assert start_day == DISABLED_START_DAY or 1 <= start_day <= 7, (
            f"[weekly][{self.display_name}] 非法周常起始日: {start_day}"
            "（应为 0（不启用）或 1~7）"
        )

    def prepare_start_day(self, start_day: int) -> None:
        """按周几起写本周常的开关（运行期入口），由各子类按自身 config 结构覆写。

        开关形态随周常而异（列表增删、布尔开关、语义反相、app 条目、队列公式），
        基类无通用落点，故只兜底 assert。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 子类未覆写本方法（无周常落点）。
        """
        assert False, (  # noqa: B011  # 故意：未覆写即不该走到周常写入
            f"[weekly][{self.display_name}] 未支持周常配置"
        )

    def set_start_day(self, start_day: int) -> None:
        """编辑期落盘周几起的字面起始日，由有字面字段的周常覆写。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 子类未覆写本方法（该周常无「周几起」字面字段）。
        """
        assert False, (  # noqa: B011  # 故意：无字面字段的周常不该走到本入口
            f"[weekly][{self.display_name}] 该周常无「周几起」字面字段"
        )

    def set_task(self, task_name: str) -> None:
        """写本周常当前选中的副本名，由有副本选型的周常覆写。

        Args:
            task_name: 选中的副本名。

        Raises:
            AssertionError: 子类未覆写本方法（该周常无副本选型）。
        """
        assert False, (  # noqa: B011  # 故意：无副本选型的周常不该走到本入口
            f"[weekly][{self.display_name}] 该周常无「选副本」概念"
        )

    def read_task(self) -> str | None:
        """反读本周常当前选中的副本名。

        Returns:
            当前选中的副本名；基类无副本真相恒为 None。
        """
        return None


# ============================================================
# 各周常子类
# ============================================================


# ---- 鸣潮 Wuthering Waves：幻梦游园 ----
class WutheringWavesWeekly(Weekly):
    """鸣潮：周常在 Additional Tasks 列表里按任务名增删。"""

    def prepare_start_day(self, start_day: int) -> None:
        """按周几起增删 Additional Tasks 里的周常任务名。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 起始日越界，或缺少 Additional Tasks 列表字段。
        """
        self._check_start_day(start_day)
        enabled = is_weekly_start_reached(start_day)
        config = self._load_config()
        tasks = get_field(config, self._key, self.display_name, list)
        contains = self.physical_name in tasks
        if enabled == contains:
            logger.info(
                f"[weekly][{self.display_name}] 周常状态无变化（enabled={enabled}）"
            )
            return
        if enabled:
            tasks.append(self.physical_name)
        else:
            tasks.remove(self.physical_name)
        logger.info(
            f"[weekly][{self.display_name}] {'启用' if enabled else '停用'}周常"
        )
        self._save_config(config)


# ---- 终末地 Arknights: Endfield：卖出物资 ----
class EndfieldWeekly(Weekly):
    """终末地：周常是语义反相的布尔字段（只买不卖=true → 不卖出 → 周常关）。"""

    def prepare_start_day(self, start_day: int) -> None:
        """按周几起写「只买不卖」开关（语义反相）。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 起始日越界。
        """
        self._check_start_day(start_day)
        enabled = is_weekly_start_reached(start_day)
        config = self._load_config()
        # 反相：enabled=True（卖出）→ 只买不卖=false
        safe_update(config, self._key, not enabled, self.display_name)
        self._save_config(config)


# ---- 绝区零 Zenless Zone Zero：迷失之地 ----
class ZenlessZoneZeroWeekly(Weekly):
    """绝区零：周常在 _group.yml 的 app_list 里，是某条 app 条目的 enabled。"""

    def prepare_start_day(self, start_day: int) -> None:
        """按周几起写 app_list 里该 app 条目的 enabled。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 起始日越界，或 app_list 缺少该 app 条目。
        """
        self._check_start_day(start_day)
        enabled = is_weekly_start_reached(start_day)
        config = self._load_config()
        app_list = get_field(config, "app_list", self.display_name, list)
        target = next(
            (app for app in app_list if app["app_id"] == self.physical_name),
            None,
        )
        assert target is not None, (
            f"[weekly][{self.display_name}] app_list 缺少 {self.physical_name}"
        )
        safe_update(target, "enabled", enabled, self.display_name)
        self._save_config(config)


# ---- 通用：按周几起折算写布尔开关（崩铁的货币战争 / 模拟宇宙）----
class SwitchWeekly(Weekly):
    """开关型周常：游戏侧只有一个布尔开关，按周几起折算后写 ``key``。

    适用于 M7A 里没有自身「周几起」门控、只给一个开关的功能（货币战争 / 模拟宇宙）——
    由本工具在运行期按「今天是否已到起始日」决定该开关的取值。
    """

    def prepare_start_day(self, start_day: int) -> None:
        """按周几起写布尔开关（今天已到起始日、且非「不启用」才为 True）。

        Args:
            start_day: 周几以后启用（1~7，1=周一）；``DISABLED_START_DAY`` 表示不启用。

        Raises:
            AssertionError: 起始日越界。
        """
        self._check_start_day(start_day)
        config = self._load_config()
        safe_update(
            config,
            self._key,
            is_weekly_start_reached(start_day),
            self.display_name,
        )
        self._save_config(config)


# ---- 崩铁 Honkai: Star Rail：历战余响 ----
class EchoOfWarWeekly(Weekly):
    """崩铁·历战余响：任务型周本，周几起写字面字段交 M7A 自身门控。

    M7A 另有一个总开关（声明 ``enable_key``），故「不启用」写它、不动字面起始日——
    保留用户原选择，便于再启用。
    """

    def prepare_start_day(self, start_day: int) -> None:
        """按周几起写总开关与字面起始日，由 M7A 自身按该日门控。

        Args:
            start_day: 周几以后启用（1~7，1=周一）；``DISABLED_START_DAY`` 表示不启用。

        Raises:
            AssertionError: 起始日越界，或未声明 enable_key。
        """
        self._check_start_day(start_day)
        config = self._load_config()
        self._apply_start_day(config, start_day)
        self._save_config(config)

    def set_start_day(self, start_day: int) -> None:
        """编辑期落盘总开关与字面起始日，无需等链运行。

        Args:
            start_day: 周几以后启用（1~7，1=周一）；``DISABLED_START_DAY`` 表示不启用。

        Raises:
            AssertionError: 起始日越界，或游戏原生 config 读不出来（文件缺失/损坏）。
        """
        self._check_start_day(start_day)
        # 前置条件：游戏原生 config 路径有效（游戏已安装、script_path 正确），由 GUI 侧
        # 调用前保证；本方法假设该前置成立，不做存在性兜底盘——写路径必须按 load_script_config
        # 的契约报错，否则会把读不出来的 config 当成空 dict 整份覆盖成单字段存根。
        config = self._load_config()
        self._apply_start_day(config, start_day)
        self._save_config(config)

    def _apply_start_day(self, config: dict, start_day: int) -> None:
        """把「周几起 / 不启用」写进 config（两个入口共用）。

        字段本身在真实 M7A 配置里都存在；首次使用（或配置被清）时允许新增。

        Args:
            config: 待修改的 config dict（就地改）。
            start_day: 周几起；``DISABLED_START_DAY`` 表示不启用。

        Raises:
            AssertionError: 未声明 enable_key（声明错误）。
        """
        assert self._enable_key, (
            f"[weekly][{self.display_name}] 未声明 enable_key，无法表达启用/不启用"
        )
        enabled = start_day != DISABLED_START_DAY
        safe_update(
            config,
            self._enable_key,
            enabled,
            self.display_name,
            assert_key_exists=False,
        )
        if enabled:
            safe_update(
                config,
                self._key,
                start_day,
                self.display_name,
                assert_key_exists=False,
            )


# ---- 明日方舟 Arknights（粥）：理智药剂 ----
class ArknightsWeekly(Weekly):
    """粥：周常是「理智药剂临期窗口」，按周几起换算成天数写进所有战斗任务。"""

    def _task_queue(self, config: dict) -> list[dict]:
        """取 MAA 默认配置中的原生任务队列。

        Args:
            config: MAA 的 gui.new.json dict。

        Returns:
            原生任务队列列表。

        Raises:
            AssertionError: 缺少 Configurations/Default/TaskQueue 结构。
        """
        configurations = get_field(
            config, "Configurations", self.display_name, dict, "weekly"
        )
        profile = get_field(
            configurations, "Default", self.display_name, dict, "weekly"
        )
        return get_field(profile, "TaskQueue", self.display_name, list, "weekly")

    def prepare_start_day(self, start_day: int) -> None:
        """按周几起写临期窗口并开启临期药；不启用则只关临期药。

        与其它周常的二值开关不同，本方法按公式直接写入窗口（不按「今天是否到起始日」
        门控）：周几起 = 7 - MedicineExpireDays + 1 ⇒ 窗口 = 8 - 周几起。
        ``DISABLED_START_DAY`` 时只关临期药开关，窗口值保留（便于再启用）。

        Args:
            start_day: 周几起（1~7，1=周一）；``DISABLED_START_DAY`` 表示不启用。
        """
        self._check_start_day(start_day)
        config = self._load_config()
        task_queue = self._task_queue(config)
        if start_day == DISABLED_START_DAY:
            changed = self._write_medicine_switch(task_queue, False)
        else:
            changed = self._write_expire_window(task_queue, 8 - start_day)
            changed |= self._write_medicine_switch(task_queue, True)
        self._log_and_save(config, changed, "理智药剂配置")

    def set_start_day(self, start_day: int) -> None:
        """编辑期只落盘临期窗口（= 8 - 周几起）；不启用时只关临期药开关。

        Args:
            start_day: 周几起（1~7，1=周一）；``DISABLED_START_DAY`` 表示不启用。

        Raises:
            AssertionError: 起始日越界，或游戏原生 config 读不出来（文件缺失/损坏）。
        """
        self._check_start_day(start_day)
        # 前置条件：游戏原生 config 已存在（游戏已安装、script_path 正确），由 GUI 侧
        # 调用前保证；缺失即前置不成立，直接断言失败，不做存在性兜底盘。
        config = self._load_config()
        task_queue = self._task_queue(config)
        if start_day == DISABLED_START_DAY:
            changed = self._write_medicine_switch(task_queue, False)
        else:
            changed = self._write_expire_window(task_queue, 8 - start_day)
        self._log_and_save(config, changed, "理智药剂过期窗口")

    def _log_and_save(self, config: dict, changed: bool, what: str) -> None:
        """按本次是否有实际修改记日志，有改动才落盘。

        Args:
            config: 已就地修改的 config dict。
            changed: 本次是否有字段被修改。
            what: 日志里的改动对象名。
        """
        if not changed:
            logger.info(f"[weekly][{self.display_name}] {what}无需更新")
            return
        logger.info(f"[weekly][{self.display_name}] {what}已更新")
        self._save_config(config)

    def _write_expire_window(self, task_queue: list[dict], expire_days: int) -> bool:
        """把临期窗口天数写进所有战斗任务，返回是否有实际修改。

        Args:
            task_queue: 原生任务队列。
            expire_days: 临期窗口天数（= 8 - 周几起）。

        Returns:
            是否真的有字段被修改。
        """
        return self._write_fight_tasks(task_queue, "MedicineExpireDays", expire_days)

    def _write_medicine_switch(self, task_queue: list[dict], enabled: bool) -> bool:
        """开关所有战斗任务的临期药，返回是否有实际修改。

        Args:
            task_queue: 原生任务队列。
            enabled: 临期药开关取值。

        Returns:
            是否真的有字段被修改。
        """
        return self._write_fight_tasks(task_queue, "UseExpiringMedicine", enabled)

    def _write_fight_tasks(self, task_queue: list[dict], field: str, value) -> bool:
        """把某字段写进队列里所有战斗任务，返回是否有实际修改。

        Args:
            task_queue: 原生任务队列。
            field: 原生字段名。
            value: 待写入的值。

        Returns:
            是否真的有字段被修改。
        """
        changed = False
        for task in task_queue:
            if task["$type"] != "FightTask":
                continue
            changed |= safe_update(
                task, field, value, self.display_name, assert_key_exists=False
            )
        return changed


WEEKLY_CLASSES: dict[str, type[Weekly]] = {
    cls.__name__: cls
    for cls in (
        WutheringWavesWeekly,
        EndfieldWeekly,
        ZenlessZoneZeroWeekly,
        SwitchWeekly,
        EchoOfWarWeekly,
        ArknightsWeekly,
    )
}
"""声明 ``class`` 字段可引用的机制类注册表（键 = 类名）。"""


# ============================================================
# 装配与适配器接口
# ============================================================

_BUILT: dict[str, list[Weekly]] = {}
"""已装配的周常对象（按脚本标识）；由 ``ScriptConfig`` 构造期装配，模块级入口取用。"""


def build_weeklies(script_name: str, script_display_name: str) -> list[Weekly]:
    """装配某脚本的全部周常（幂等）：按声明逐条建对象。

    由 ``ScriptConfig.__init__`` 在构造期调用，与日常装配同一时机。

    Args:
        script_name: 脚本标识名。
        script_display_name: 脚本展示名（日志与报错用）。

    Returns:
        该脚本的周常对象列表（顺序与声明一致）；无周常声明的脚本返回空列表。

    Raises:
        AssertionError: 声明里的机制类未注册，或同脚本内周常物理名重复。
    """
    if script_name in _BUILT:
        return _BUILT[script_name]
    declarations = load_weekly_map()
    weeklies: list[Weekly] = []
    seen: set[str | int] = set()
    for declaration in declarations.get(script_name, []):
        class_name = declaration["class"]
        assert class_name in WEEKLY_CLASSES, (
            f"[weekly][{script_display_name}] 未知的周常机制类: {class_name!r}"
        )
        weekly = WEEKLY_CLASSES[class_name](
            script_name, declaration, script_display_name
        )
        assert weekly.physical_name not in seen, (
            f"{script_name} 的周常物理名重复: {weekly.physical_name}"
        )
        seen.add(weekly.physical_name)
        weeklies.append(weekly)
    _BUILT[script_name] = weeklies
    return weeklies


def weeklies_of(script_name: str) -> list[Weekly]:
    """取某脚本的周常对象（未装配则就地装配，展示名回落脚本标识）。

    Args:
        script_name: 脚本标识名。

    Returns:
        该脚本的周常对象列表；无周常声明时为空列表。
    """
    if script_name not in _BUILT:
        build_weeklies(script_name, script_name)
    return _BUILT[script_name]


def weekly_names(script_name: str) -> list[str]:
    """取某脚本的周常展示名列表（顺序与声明一致），供调用方遍历。

    Args:
        script_name: 脚本标识名。

    Returns:
        周常展示名列表。
    """
    return [weekly.display_name for weekly in weeklies_of(script_name)]


def _weekly_named(script_name: str, weekly_name: str) -> Weekly | None:
    """按展示名取该脚本的一条周常；未适配或无此周常返回 None。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常展示名。

    Returns:
        对应的周常对象；不存在时返回 None。
    """
    for weekly in weeklies_of(script_name):
        if weekly.display_name == weekly_name:
            return weekly
    return None


def supports_weekly(script_name: str) -> bool:
    """查询脚本是否支持周常（供 GUI 控制周常行可选性）。

    只看声明：该脚本在 ``weekly_task_list.yml`` 里有无周常条目。

    Args:
        script_name: 脚本标识名。

    Returns:
        该脚本是否有周常声明。
    """
    return bool(load_weekly_map().get(script_name))


def prepare_weekly_start_days(script_name: str, start_days: dict[str, int]) -> None:
    """运行期入口：按各周常的起始日写该脚本的周本开关。

    未适配周常的脚本优雅跳过；``start_days`` 未列出的周常不动。

    Args:
        script_name: 脚本标识名。
        start_days: {周常展示名: 起始日（1~7）}。
    """
    for weekly in weeklies_of(script_name):
        if weekly.display_name in start_days:
            weekly.prepare_start_day(start_days[weekly.display_name])


def set_weekly_start_day(script_name: str, weekly_name: str, start_day: int) -> None:
    """编辑期入口：把某条周常的起始日写进它的游戏侧字面起始日字段。

    与 ``prepare_start_day`` 的分工：本方法只在编辑期落盘「字面起始日」（崩铁历战余响的
    ``echo_of_war_start_day_of_week`` / 粥的 MedicineExpireDays），值由该日直接算出、
    不依赖当天星期；按「今天是否已到起始日」折算的二值开关仍只在运行期由
    ``prepare_start_day`` 写。

    未适配周常、无此周常、或该周常没有字面起始日字段（未覆写 ``set_start_day``）时
    优雅跳过。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常展示名（如「历战余响」）。
        start_day: 周几以后启用（1~7，1=周一）。
    """
    weekly = _weekly_named(script_name, weekly_name)
    if weekly is None or type(weekly).set_start_day is Weekly.set_start_day:
        return
    weekly.set_start_day(start_day)


def set_weekly_task(script_name: str, weekly_name: str, task_name: str) -> None:
    """编辑期入口：写某条周常当前选中的副本名。

    未适配周常或该周常无副本选型（未覆写 ``set_task``）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常展示名（如「历战余响」）。
        task_name: 选中的副本名。
    """
    weekly = _weekly_named(script_name, weekly_name)
    if weekly is None or type(weekly).set_task is Weekly.set_task:
        return
    weekly.set_task(task_name)


def get_weekly_task(script_name: str, weekly_name: str) -> str | None:
    """读某条周常当前选中的副本名（反读子脚本 config）。

    未适配周常或无此周常时返回 None。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常展示名（如「历战余响」）。

    Returns:
        当前选中的副本名；无真相/未设置返回 None。
    """
    weekly = _weekly_named(script_name, weekly_name)
    if weekly is None:
        return None
    return weekly.read_task()
