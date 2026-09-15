"""副本配置适配器：统一 set_config 适配接口，按各脚本格式封装 config 读写。"""

import logging
import os

from src.config.daily import (
    AnomalyHunterDaily,
    Daily,
    MaaDaily,
    NoopDaily,
    SegmentedDaily,
)
from src.config.task_config import (
    get_daily_configs,
    get_physical_name,
    get_value_map,
    get_weekly_config,
)
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
from src.utils.utils_weekly import is_weekly_start_reached

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

    _config_rel_path: str = ""
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

    _weekly_task_name: str = ""
    """周常任务标识名（非空即支持周常）；各脚本含义不同。"""

    _weekly_config_rel_path: str = ""
    """周常配置文件路径；空字符串复用主 config。"""

    _routine_config_rel_path: str = ""
    """日常开关所在文件（如异环的 DailyRoutineTask.json）；空字符串表示该脚本无日常开关。"""

    _dailies_data: list[Daily] | None = None
    """该脚本的日常对象缓存（首次访问 ``_dailies`` 时由声明构造）。"""

    def _load(
        self, rel_path: str | None = None, *, allow_missing: bool = False
    ) -> dict | None:
        """读取脚本 config 并校验为 dict。

        写路径（初始化/落盘校验）要求 config 必须存在且为 dict，任何读取失败都抛出；
        读路径（反读日常/周本副本）容忍外部状态，一律返回 None，其中：

        - 脚本未安装（config.yml 中无此脚本）与 config 文件缺失属正常状态，静默跳过；
        - 文件存在但解析器报错（JSON/YAML 语法错误）不当作「无内容」，留痕后仍返回 None。

        Args:
            rel_path: 相对脚本根目录的路径；缺省用 _config_rel_path。
            allow_missing: True 时读取失败返回 None（读路径）；
                False 时失败即报错（写路径，默认）。

        Returns:
            解析后的 config dict；仅 allow_missing=True 且读取失败时为 None。

        Raises:
            AssertionError: allow_missing=False 且文件不存在、内容损坏或解析结果非 dict。
        """
        rel_path = rel_path or self._config_rel_path
        try:
            config = load_config(self._script_name, rel_path)
        except AssertionError:
            # 未安装 / 文件缺失由 load_config 以断言表达，读路径按「未设置」处理。
            if not allow_missing:
                raise
            return None
        except Exception:  # noqa: BLE001  # 文件存在但内容损坏
            if not allow_missing:
                raise
            logger.warning(
                f"[set_config][{self.display_name}] config 损坏，"
                f"按未设置处理: {rel_path}",
                exc_info=True,
            )
            return None
        if not isinstance(config, dict):
            if allow_missing:
                return None
            assert isinstance(config, dict), (
                f"[set_config][{self.display_name}] config 必须是 dict"
            )
        return config

    def _save(self, config: dict, rel_path: str | None = None) -> None:
        """保存 config 并回读校验落盘一致。

        enabled=False 时跳过（用户拒绝更新）。

        Args:
            config: 待保存的 dict。
            rel_path: 相对脚本根目录的路径；缺省用 _config_rel_path。

        Raises:
            AssertionError: config 非 dict 或保存后回读不一致。
        """
        rel_path = rel_path or self._config_rel_path
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        save_config(self._script_name, rel_path, config)
        self._verify_saved(config, rel_path)

    def _verify_saved(self, expected: dict, rel_path: str | None = None) -> None:
        """保存后回读校验落盘与预期一致。

        Args:
            expected: 期望落盘的 config dict。
            rel_path: 相对脚本根目录的路径；缺省用 _config_rel_path。

        Raises:
            AssertionError: 重新读取的内容与预期不一致。
        """
        reloaded = self._load(rel_path)
        assert reloaded == expected, (
            f"[set_config][{self.display_name}] 配置保存后校验失败："
            f"重新读取的内容与预期不一致"
        )

    def _load_weekly(self) -> dict:
        """加载周常配置文件（缺省复用主 config）。

        Returns:
            解析后的 config dict。

        Raises:
            AssertionError: 解析结果非 dict。
        """
        config = load_config(
            self._script_name, self._weekly_config_rel_path or self._config_rel_path
        )
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] 周常 config 必须是 dict"
        )
        return config

    def _save_weekly(self, config: dict) -> None:
        """保存周常配置并回读校验落盘一致。

        enabled=False 时跳过（用户拒绝更新）。

        Args:
            config: 待保存的 dict。

        Raises:
            AssertionError: config 非 dict 或保存后回读不一致。
        """
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] 周常 config 必须是 dict"
        )
        save_config(
            self._script_name,
            self._weekly_config_rel_path or self._config_rel_path,
            config,
        )
        reloaded = self._load_weekly()
        assert reloaded == config, (
            f"[set_config][{self.display_name}] 周常配置保存后校验失败："
            f"重新读取的内容与预期不一致"
        )

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

    def _build_dailies(self) -> list[Daily]:
        """由各脚本子类手动实例化自己的日常（一个日常一个实例、类写在明处）。

        Returns:
            该脚本的日常列表；单日常脚本长度为 1。
        """
        raise NotImplementedError(
            f"[set_config][{self.display_name}] 未实现 _build_dailies"
        )

    @property
    def _dailies(self) -> list[Daily]:
        """该脚本的全部日常（懒加载，见 ``_build_dailies``）。"""
        if self._dailies_data is None:
            dailies = self._build_dailies()
            seen: set[str] = set()
            for daily in dailies:
                assert daily.physical_name not in seen, (
                    f"{self._script_name} 的日常物理名重复: {daily.physical_name}"
                )
                seen.add(daily.physical_name)
            self._dailies_data = dailies
        return self._dailies_data

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

    def _read_weekly_task(self, weekly_name: str) -> str | None:
        """反读某周常当前选中的副本名（与 set_weekly_task 对称）。

        基类默认无周常副本真相，返回 None；有周常副本的子类（如崩铁）应覆写。

        Args:
            weekly_name: 周常名（如「历战余响」）。

        Returns:
            当前选中的副本名；无真相/未设置返回 None。
        """
        return None

    def _init_config(self) -> None:
        """对齐检查并把模板 config 同步到用户 config。

        仅对有模板（声明 ``_template_rel_path``）的脚本生效；无模板脚本或脚本尚未
        安装/未配置（config 缺失）时直接返回，不触碰 config。已对齐时不动 config。
        """
        if not self._template_rel_path:
            return
        config = self._load(allow_missing=True)
        if config is None:
            return  # 脚本未安装/未配置，待首次写入时由 set_* 创建
        template = self._load_template()

        if self._is_aligned(config, template):
            logger.info(f"[init_config][{self.display_name}] config 已对齐，无需更新")
            return

        for key, val in template.items():
            safe_update(config, key, val, self.display_name, assert_key_exists=False)
        self._save(config)
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
        if not self._routine_config_rel_path:
            return  # 无日常开关文件：选择即启用
        daily.set_enabled(enabled)

    def _check_weekly_start(self, start_day: int) -> None:
        """校验周常起始日，供各子类的 prepare_weekly_start_day 首行调用。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常，或 start_day 不在 1~7。
        """
        assert self._weekly_task_name, (
            f"[set_config][{self.display_name}] 未支持周常配置"
        )
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )

    def prepare_weekly_start_day(self, start_day: int) -> None:
        """设置周常起始日并写入周常开关，由各子类按自身 config 结构覆写。

        周常开关的形态随脚本而异（Additional Tasks 列表增删、布尔开关、语义反相、
        _group.yml 的 app 条目），基类无通用落点，故只兜底 assert。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常（未声明 _weekly_task_name）。
        """
        self._check_weekly_start(start_day)
        assert False, f"[set_config][{self.display_name}] 未支持周常配置"  # noqa: B011  # 故意：未适配脚本不应走到周常写入

    @classmethod
    def get_game_exe_path(cls, script_name: str) -> str | None:
        """读取游戏 exe 路径（类方法，无需实例化）。

        Args:
            script_name: 脚本标识名。

        Returns:
            exe 绝对路径；未适配、缺失或为空时返回 None。
        """
        if not cls._game_path_keys:
            return None
        game_config = load_game_config(script_name, cls._game_config_rel_path)
        if game_config is None:
            return None
        node = game_config
        for key in cls._game_path_keys:
            if not isinstance(node, dict) or key not in node:
                logger.warning(
                    f"[get_game_exe_path][{script_name}] 配置缺少字段: "
                    f"{cls._game_path_keys}"
                )
                return None
            node = node[key]
        if not isinstance(node, str) or not node:
            logger.warning(
                f"[get_game_exe_path][{script_name}] 游戏路径字段非字符串或为空"
            )
            return None
        return node

    @classmethod
    def get_task_lists(cls, task_name: str, source: str) -> list[str] | None:
        """读取某任务（周常/日常）的可选副本名清单（类方法，无需实例化）。

        Args:
            task_name: 任务名（周常/日常均可，如「历战余响」）。
            source: options.source.path 声明的脚本内相对路径。

        Returns:
            副本名列表（含「无」等占位）；未适配或源不可达时返回 None。
        """
        logger.warning(
            f"[set_config][{cls.display_name}] 未适配副本清单读取: source={source!r}"
        )
        # 基类默认未适配副本清单读取，返回 None 由调用方降级为「该任务无可选副本」。
        return None


# ============================================================
# 注册表
# ============================================================

# 由 register() 装饰器显式填充（必须在子类定义前初始化）。
_CONFIGS: dict[str, type[ScriptConfig]] = {}


def register(cls: type[ScriptConfig]) -> type[ScriptConfig]:
    """注册子类到 _CONFIGS，并校验必要声明。

    必填属性须由子类在 ``cls.__dict__`` 中显式声明（而非继承基类默认值）；
    声明了条件属性（_game_path_keys / _weekly_task_name）必须补全对应依赖。

    Args:
        cls: 待注册的 ScriptConfig 子类。

    Returns:
        原样返回 cls（便于装饰器使用）。

    Raises:
        AssertionError: 缺少 _script_name/_config_rel_path/_backup_paths 显式声明，
            或声明了 _game_path_keys/_weekly_task_name 但未补全对应声明/实现。
    """
    for attr in ("_script_name", "_config_rel_path", "_backup_paths"):
        assert attr in cls.__dict__, f"[set_config][{cls.__name__}] 必须声明 {attr}"
    if cls._game_path_keys:
        assert "_game_config_rel_path" in cls.__dict__, (
            f"[set_config][{cls.__name__}] 声明了 _game_path_keys 必须声明 "
            f"_game_config_rel_path"
        )
    if cls._weekly_task_name:
        assert (
            cls.prepare_weekly_start_day is not ScriptConfig.prepare_weekly_start_day
        ), (
            f"[set_config][{cls.__name__}] 声明了 _weekly_task_name 必须覆写 "
            f"prepare_weekly_start_day（周常开关的落点）"
        )
    _CONFIGS[cls._script_name] = cls
    return cls


# ============================================================
# 各脚本子类
# ============================================================


# ---- 鸣潮 Wuthering Waves ----
@register
class WutheringWavesConfig(ScriptConfig):
    _script_name = "ok-ww"

    def _build_dailies(self) -> list[Daily]:
        """按声明实例化本脚本的日常（标准两层）。"""
        (declaration,) = get_daily_configs(self._script_name)
        return [Daily(self._script_name, declaration, self)]

    _backup_paths = ("data/apps/ok-ww/working/configs",)
    _config_rel_path = "data/apps/ok-ww/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ww/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "鸣潮"
    _weekly_config = get_weekly_config(_script_name, "幻梦游园")
    _weekly_task_name = get_physical_name(_weekly_config)

    def prepare_weekly_start_day(self, start_day: int) -> None:
        """控制「Check Weekly Garden」在 Additional Tasks 中的增删。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常、起始日越界，或缺少 Additional Tasks 列表字段。
        """
        self._check_weekly_start(start_day)
        enabled = is_weekly_start_reached(start_day)
        config = self._load()
        # 周常（乐园）在 Additional Tasks 列表中任务名 _weekly_task_name。
        tasks = get_field(config, self._weekly_config["key"], self.display_name, list)
        contains = self._weekly_task_name in tasks
        if enabled == contains:
            logger.info(
                f"[prepare_weekly_start_day][{self.display_name}] 周常状态无变化（enabled={enabled}）"
            )
            return
        if enabled:
            tasks.append(self._weekly_task_name)
        else:
            tasks.remove(self._weekly_task_name)
        logger.info(
            f"[prepare_weekly_start_day][{self.display_name}] {'启用' if enabled else '停用'}周常"
        )
        self._save(config)


# ---- 原神 Genshin Impact ----
@register
class GenshinConfig(ScriptConfig):
    _script_name = "BetterGI"
    display_name = "原神"

    def _build_dailies(self) -> list[Daily]:
        """按声明实例化本脚本的日常（两层共用一级字段）。"""
        (declaration,) = get_daily_configs(self._script_name)
        return [Daily(self._script_name, declaration, self)]

    _backup_paths = ("User",)
    _config_rel_path = "User/OneDragon/默认配置.json"
    _game_config_rel_path = "User/config.json"
    _template_rel_path = "BGI一条龙.json"
    _game_path_keys = ("genshinStartConfig", "installPath")

    @classmethod
    def get_task_lists(cls, task_name: str, source: str) -> list[str]:
        """读 BetterGI 的 tp.json，取某秘境分类（周常/日常）的副本名清单。

        Args:
            task_name: source.category 中的原生秘境分类（如 BlessDomain）。
            source: tp.json 相对脚本根目录的路径。

        Returns:
            副本名列表（即 tp.json 的 ``name`` 字段）；文件缺失/空时返回 ``[]``。
        """
        data = load_game_config(cls._script_name, source)
        if not data:
            return []
        assert isinstance(data, dict), (
            f"[set_config][{cls.display_name}] 副本名应为 dict"
        )
        names: list[str] = []
        for scene in data.get("data", []):
            if not isinstance(scene, dict):
                continue
            for pt in scene.get("points", []):
                if isinstance(pt, dict) and pt.get("type", "") == task_name:
                    name = pt.get("name", "")
                    if name:
                        names.append(name)
        return names


# ---- 终末地 Arknights: Endfield ----
@register
class EndfieldConfig(ScriptConfig):
    _script_name = "ok-ef"
    display_name = "终末地"

    def _build_dailies(self) -> list[Daily]:
        """按声明实例化本脚本的日常（两层共用一级字段）。"""
        (declaration,) = get_daily_configs(self._script_name)
        return [Daily(self._script_name, declaration, self)]

    _template_rel_path = "okef一条龙.json"
    _backup_paths = ("data/apps/ok-ef/working/configs",)
    _config_rel_path = "data/apps/ok-ef/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ef/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    _weekly_task_name = get_weekly_config(_script_name, "卖出物资")["key"]
    """周常（卖出物资）在 DailyTask.json 中的开关键；true=只买不卖=不卖=周常关。"""

    def prepare_weekly_start_day(self, start_day: int) -> None:
        """控制 DailyTask.json 的「只买不卖」周常开关（语义反相）。

        游戏约定：只买不卖=true → 不卖出 → 周常（卖出物资）关闭；
        故按起始日算出的 enabled 需反相写入。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常，或起始日越界。
        """
        self._check_weekly_start(start_day)
        enabled = is_weekly_start_reached(start_day)
        config = self._load()
        # 反相：enabled=True（卖出）→ 只买不卖=false
        safe_update(config, self._weekly_task_name, not enabled, self.display_name)
        self._save(config)

    @classmethod
    def get_task_lists(cls, task_name: str, source: str) -> list[str]:
        """读取体力本的可选副本名清单。

        Args:
            task_name: 日常类别名（即 stages_dict 的键，如「能量淤积点」）。
            source: world_map.json 相对脚本根目录的路径。

        Returns:
            副本名列表；未安装/缺失/空文件时返回 []。
        """
        data = load_game_config(cls._script_name, source)
        if not data:
            return []
        assert isinstance(data, dict), (
            f"[set_config][{cls.display_name}] world_map.json 顶层应为 dict: {source}"
        )
        stages = get_field(data, "stages_dict", cls.display_name, dict, "world_map")
        assert task_name in stages, (
            f"[set_config][{cls.display_name}] 未知日常类别: {task_name!r} (source={source})"
        )
        entry = stages[task_name]
        assert isinstance(entry, list), (
            f"[set_config][{cls.display_name}] stages_dict[{task_name!r}] 应为 list: {source}"
        )
        return list(entry)


# ---- 绝区零 Zenless Zone Zero ----
@register
class ZenlessZoneZeroConfig(ScriptConfig):
    _script_name = "OneDragon-Launcher"
    display_name = "绝区零"
    _backup_paths = ("config",)
    _config_rel_path = "config/01/one_dragon/charge_plan.yml"
    _game_config_rel_path = "config/01/game_account.yml"
    _template_rel_path = "ZZZ一条龙.yml"
    _weekly_config_rel_path = "config/01/one_dragon/_group.yml"
    _game_path_keys = ("game_path",)
    background = "assets/ui/static_background.webp"
    _weekly_task_name = get_physical_name(get_weekly_config(_script_name, "迷失之地"))

    def _build_dailies(self) -> list[Daily]:
        """按声明实例化本脚本的日常（上游自适配，无需落盘）。"""
        (declaration,) = get_daily_configs(self._script_name)
        return [NoopDaily(self._script_name, declaration, self)]

    def prepare_weekly_start_day(self, start_day: int) -> None:
        """控制 _group.yml 中 lost_void 的 enabled 开关。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常、起始日越界，或 app_list 缺少 lost_void 条目。
        """
        self._check_weekly_start(start_day)
        enabled = is_weekly_start_reached(start_day)
        config = self._load_weekly()
        # 周常（迷失之地）在 _group.yml app_list 中的 app_id。
        app_list = get_field(config, "app_list", self.display_name, list)
        target = next(
            (app for app in app_list if app["app_id"] == self._weekly_task_name),
            None,
        )
        assert target is not None, (
            f"[set_config][{self.display_name}] app_list 缺少 {self._weekly_task_name}"
        )
        safe_update(target, "enabled", enabled, self.display_name)
        self._save_weekly(config)


# ---- 崩铁 Honkai: Star Rail ----
@register
class StarRailConfig(ScriptConfig):
    _script_name = "March7th-Launcher"
    display_name = "崩铁"
    _backup_paths = ("config.yaml",)
    _config_rel_path = "config.yaml"
    _game_config_rel_path = "config.yaml"
    _template_rel_path = "M7A一条龙.yml"
    _game_path_keys = ("game_path",)
    background = "assets/app/images/bg37.jpg"
    _weekly_task_name = get_weekly_config(_script_name, "货币战争")["key"]
    _echo_config = get_weekly_config(_script_name, "历战余响")

    def _build_dailies(self) -> list[Daily]:
        """按声明实例化本脚本的日常（上游自适配，无需落盘）。"""
        (declaration,) = get_daily_configs(self._script_name)
        return [NoopDaily(self._script_name, declaration, self)]

    @classmethod
    def get_task_lists(cls, task_name: str, source: str) -> list[str]:
        """读取某任务（周常/日常）的可选副本名清单。

        Args:
            task_name: 任务名（即文件中的键，如「历战余响」）。
            source: 副本清单文件相对脚本根目录的路径。

        Returns:
            副本名列表（含「无」等占位）；data 为空（未安装/缺失/空文件）时返回空列表。
        """
        data = load_game_config(cls._script_name, source)
        if not data:
            return []
        assert isinstance(data, dict), (
            f"[set_config][{cls.display_name}] 副本清单 {source} 非 dict: {type(data)}"
        )
        assert task_name in data, (
            f"[set_config][{cls.display_name}] 副本清单 {source} 缺任务 {task_name!r}"
        )
        entry = data[task_name]
        assert isinstance(entry, dict), (
            f"[set_config][{cls.display_name}] 任务 {task_name!r} 条目非 dict: {type(entry)}"
        )
        return list(entry.keys())

    def prepare_weekly_start_day(self, start_day: int) -> None:
        """崩铁周常：周几起对所有周本生效。

        - 货币战争（开关型）：M7A 无自身周几起门控，由 launcher 按周几起落盘
          currencywars_enable。
        - 历战余响（任务型）：把周几起写入 M7A 的 echo_of_war_start_day_of_week，
          由 M7A 自身按该日门控；副本选型 instance_names 正交，不在这里改动。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。
        """
        self._check_weekly_start(start_day)
        config = self._load()
        # 货币战争：今天是否已到起始日
        safe_update(
            config,
            self._weekly_task_name,
            is_weekly_start_reached(start_day),
            self.display_name,
        )
        # 历战余响：周几起交给 M7A 自身门控，与副本选型 instance_names 正交
        safe_update(config, self._echo_config["key"], start_day, self.display_name)
        self._save(config)

    def set_weekly_start_day(self, start_day: int) -> None:
        """编辑期落盘周几起字面起始日到 echo_of_war_start_day_of_week。

        与 prepare_weekly_start_day 不同：本方法不写 currencywars_enable（开关型周本需运行期按
        「今天是否已到起始日」计算二进制开关），只写 任务型周本（历战余响）的字面
        起始日，由 M7A 自身按该日门控。编辑期改周几起即应落盘此值，无需等待链运行。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。
        """
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )
        # 前置条件：游戏原生 config 路径有效（游戏已安装、script_path 正确），由 GUI 侧
        # 调用前保证；本方法假设该前置成立，不做存在性兜底盘。
        config = self._load(allow_missing=True) or {}
        # 空 config 时字段可能尚不存在（本方法容忍 config 缺失），故允许新增。
        safe_update(
            config,
            self._echo_config["key"],
            start_day,
            self.display_name,
            assert_key_exists=False,
        )
        self._save(config)

    def set_weekly_task(self, weekly_name: str, task_name: str) -> None:
        """写入某周常当前选中的副本名到 config.yaml 的 instance_names。

        副本名清单的展示与下拉选项由 OneDragon-Helper 的 weekly_task_list.yml 声明
        （tasks 字段）负责，本方法只承担把用户所选写回 M7A 游戏配置的本分。

        Args:
            weekly_name: 周常名（如「历战余响」）；即 instance_names 的键。
            task_name: 选中的副本名（来自 weekly_task_list.yml 声明）。
        """
        config = self._load()
        # instance_names 是 M7A 约定键名（{周常名: 副本名} 的 dict）；仅首次使用时新建，
        # 已存在则由 get_field 校验类型——与 _read_weekly_task 对称，不静默抹掉损坏值。
        if "instance_names" not in config:
            safe_update(
                config,
                "instance_names",
                {},
                self.display_name,
                assert_key_exists=False,
            )
        instance_names = get_field(config, "instance_names", self.display_name, dict)
        task = get_weekly_config(self._script_name, weekly_name)
        values = get_value_map(task)
        if values:
            assert task_name in values, f"未知周常副本: {task_name!r}"
            task_name = values[task_name]
        instance_names[get_physical_name(task)] = task_name
        self._save(config)

    def _read_weekly_task(self, weekly_name: str) -> str | None:
        """反读某周常当前选中的副本名（与 set_weekly_task 对称）。

        Args:
            weekly_name: 周常名（如「历战余响」）；即 instance_names 的键。

        Returns:
            当前选中的副本名；未设置/无 instance_names 返回 None。
        """
        config = self._load(allow_missing=True)
        if config is None:
            return None  # 脚本未安装/未配置
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        if "instance_names" not in config:
            return None  # 未配置周常副本
        instance_names = config["instance_names"]
        assert isinstance(instance_names, dict), (
            f"[set_config][{self.display_name}] instance_names 必须是 dict"
        )
        task = get_weekly_config(self._script_name, weekly_name)
        # 未选周常副本时返回 None。
        value = instance_names.get(get_physical_name(task), None)
        names = {value: name for name, value in get_value_map(task).items()}
        # 未维护别名的上游副本直接显示原生值。
        return names.get(value, value)


# ---- 异环 Neverness to Everness (NTE) ----
@register
class NTEConfig(ScriptConfig):
    _script_name = "ok-nte"
    _backup_paths = ("data/apps/ok-nte/working/configs",)
    _config_rel_path = "data/apps/ok-nte/working/configs/DailyRoutineTaskConfigs.json"
    _routine_config_rel_path = "data/apps/ok-nte/working/configs/DailyRoutineTask.json"
    _game_config_rel_path = "data/apps/ok-nte/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "异环"

    _launcher_rel_path = "NTELauncher.exe"
    """异环启动器文件名（相对游戏安装根目录，非游戏本体）。"""

    def _build_dailies(self) -> list[Daily]:
        """按声明实例化异环的两个日常（各一段、开关独立）。"""
        by_name = {d["display_name"]: d for d in get_daily_configs(self._script_name)}
        return [
            SegmentedDaily(self._script_name, by_name["异象界域"], self),
            AnomalyHunterDaily(self._script_name, by_name["追猎目标"], self),
        ]

    @classmethod
    def get_game_exe_path(cls, script_name: str) -> str | None:
        """重写：从游戏本体路径向上查找异环启动器。

        Args:
            script_name: 脚本标识名。

        Returns:
            启动器绝对路径；本体缺失或找不到启动器时返回 None。
        """
        game_exe = super().get_game_exe_path(script_name)
        if not game_exe:
            return None
        directory = os.path.dirname(game_exe)
        while True:
            candidate = os.path.join(directory, cls._launcher_rel_path)
            if os.path.isfile(candidate):
                return candidate
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent
        logger.warning(
            f"[get_game_exe_path][{script_name}] 未找到启动器 {cls._launcher_rel_path}"
        )
        return None


# ---- 明日方舟 Arknights（粥）----
@register
class ArknightsConfig(ScriptConfig):
    _script_name = "MAA"
    display_name = "粥"
    _backup_paths = ("config",)
    _config_rel_path = "config/gui.new.json"
    _game_config_rel_path = "config/gui.new.json"
    _game_path_keys = (
        "Configurations",
        "Default",
        "Gui",
        "StartUpSettings",
        "EmulatorPath",
    )
    _weekly_task_name = get_physical_name(get_weekly_config(_script_name, "理智药剂"))

    def _build_dailies(self) -> list[Daily]:
        """按声明实例化本脚本的日常（TaskQueue 机制）。"""
        (declaration,) = get_daily_configs(self._script_name)
        return [MaaDaily(self._script_name, declaration, self)]

    def prepare_weekly_start_day(self, start_day: int) -> None:
        """周常「理智药剂」：按周几起写过期理智药使用窗口，并随副本启停同步开关。

        与基类二值开关不同，本方法每次调用都直接写入（不按「今天是否到起始日」门控）：
        - 开启的 FightTask 设 UseExpiringMedicine=true，其余设 false；
        - 剿灭不吃理智药：即便开启也强制 UseExpiringMedicine=false（照常运行，只是不吃药）；
        - MedicineExpireDays 由周几起推算：周几起 = 7 - MedicineExpireDays + 1
          ⇒ MedicineExpireDays = 8 - 周几起（周几起∈1~7，1=周一）。

        Args:
            start_day: 周几起（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常，或 start_day 不在 1~7。
        """
        self._check_weekly_start(start_day)
        config = self._load()
        task_queue = get_field(
            get_field(
                get_field(config, "Configurations", self.display_name, dict, "weekly"),
                "Default",
                self.display_name,
                dict,
                "weekly",
            ),
            "TaskQueue",
            self.display_name,
            list,
            "weekly",
        )
        # 周几起 = 7 - MedicineExpireDays + 1  ⇒  MedicineExpireDays = 8 - 周几起
        expire_days = 8 - start_day
        changed = False
        for task in task_queue:
            if task["$type"] != "FightTask":
                continue
            enabled = bool(task["IsEnable"])
            # 剿灭不吃理智药：开启但仍强制 false
            use_medicine = enabled and task["Name"] != "剿灭"
            changed |= safe_update(
                task,
                "UseExpiringMedicine",
                use_medicine,
                self.display_name,
                assert_key_exists=False,
            )
            changed |= safe_update(
                task,
                "MedicineExpireDays",
                expire_days,
                self.display_name,
                assert_key_exists=False,
            )
        if changed:
            logger.info(
                f"[prepare_weekly_start_day][{self.display_name}] 理智药剂配置已更新"
            )
            self._save(config)
        else:
            logger.info(
                f"[prepare_weekly_start_day][{self.display_name}] 理智药剂配置无需更新"
            )

    def set_weekly_start_day(self, start_day: int) -> None:
        """编辑期落盘周几起字面起始日到 MedicineExpireDays。

        与 prepare_weekly_start_day 不同：本方法只写 MedicineExpireDays（由周几起推算：
        MedicineExpireDays = 8 - 周几起），不写 UseExpiringMedicine（是否吃药的
        开关依赖各 FightTask 的启用状态，需运行期按当日副本选型经 prepare_weekly_start_day 计算）。
        编辑期改周几起即应落盘此值，无需等待链运行。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。
        """
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )
        # 前置条件：游戏原生 config 已存在（游戏已安装、script_path 正确），由 GUI 侧调用前
        # 保证；缺失即前置不成立，直接断言失败，不做存在性兜底盘。
        config = self._load()
        task_queue = get_field(
            get_field(
                get_field(config, "Configurations", self.display_name, dict, "weekly"),
                "Default",
                self.display_name,
                dict,
                "weekly",
            ),
            "TaskQueue",
            self.display_name,
            list,
            "weekly",
        )
        expire_days = 8 - start_day
        changed = False
        for task in task_queue:
            if task["$type"] != "FightTask":
                continue
            changed |= safe_update(
                task,
                "MedicineExpireDays",
                expire_days,
                self.display_name,
                assert_key_exists=False,
            )
        if changed:
            logger.info(
                f"[set_weekly_start_day][{self.display_name}] 理智药剂过期窗口已更新"
            )
            self._save(config)
        else:
            logger.info(
                f"[set_weekly_start_day][{self.display_name}] 理智药剂过期窗口无需更新"
            )


# ============================================================
# 适配器接口
# ============================================================


def init_config(script_name: str) -> None:
    """对齐脚本 config 与模板，补全缺失字段。

    仅对声明了 ``_template_rel_path`` 的脚本生效；无模板或脚本未安装/未配置时为空操作。

    Args:
        script_name: 脚本标识名。
    """
    if script_name not in _CONFIGS:
        return
    _CONFIGS[script_name]()._init_config()


def init_config_all() -> None:
    """对齐所有已注册脚本的 config 与模板（启动时调用）。"""
    for script_name in _CONFIGS:
        init_config(script_name)


def set_config(
    script_name: str,
    daily_display_name: str | None = None,
    task_name: str | None = None,
    sequence: str | int | None = None,
    weekly_start: int | None = None,
) -> None:
    """适配器接口：设置副本 / 序列 / 周常起始日。

    未选副本且无周常，或脚本未适配（自定义脚本）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        daily_display_name: 副本所属日常展示名（界面逐行渲染时即该行行名）；
            单日常脚本也要给，分段脚本（多日常）据此选段。
        task_name: 一级项展示名（副本站位）；None 或「未选择」表示不设置副本。
        sequence: 二级项值；仅部分脚本支持。
        weekly_start: 周常起始日（1~7）；None 表示不设置周常。
    """
    if (not task_name or task_name == "未选择") and weekly_start is None:
        return

    # 自定义脚本（不在注册表）跳过
    if script_name not in _CONFIGS:
        logger.info(f"[set_config] 进程 {script_name} 无副本适配（自定义脚本），跳过")
        return

    cfg_cls = _CONFIGS[script_name]
    cfg = cfg_cls()
    if task_name and task_name != "未选择":
        cfg.set_daily_task(daily_display_name, task_name, sequence)
    if weekly_start is not None:
        cfg.prepare_weekly_start_day(weekly_start)


def get_task_lists(script_name: str, task_name: str, source: str) -> list[str] | None:
    """适配器接口：副本清单源在游戏脚本自身配置里，从中读某任务的可选副本名清单，委托给对应脚本的 config 类。

    「从哪读、怎么解析」的知识归各 ``ScriptConfig`` 子类，本函数只做分发。

    Args:
        script_name: 脚本唯一标识（如 ``March7th-Launcher``）。
        task_name: 任务名（周常/日常均可，如「历战余响」）。
        source: options.source.path 声明的脚本内相对路径。

    Returns:
        副本名列表（含「无」等占位）；不可用时返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name].get_task_lists(task_name, source)


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
    return _get_config_path_impl(script_name, _CONFIGS[script_name]._config_rel_path)


def get_game_path_keys(script_name: str, rel: str) -> tuple[str, ...]:
    """查询该文件的游戏路径字段；复用打开游戏的声明，其他文件返回空元组。"""
    if script_name not in _CONFIGS:
        return ()
    assert script_name in _CONFIGS
    cls = _CONFIGS[script_name]
    if rel.casefold() != cls._game_config_rel_path.casefold():
        return ()
    return cls._game_path_keys


def iter_backup_paths() -> dict[str, tuple[str, ...]]:
    """遍历各已适配脚本的备份范围（相对脚本根目录，元素可为目录或文件）。

    「该脚本的配置面在哪」的知识归适配层，本函数只做汇总；展开（目录递归 /
    单文件收录）由备份层处理。

    Returns:
        {脚本唯一标识: (备份路径, ...)}。
    """
    return {
        script_name: cfg_cls._backup_paths for script_name, cfg_cls in _CONFIGS.items()
    }


def get_game_exe_path(script_name: str) -> str | None:
    """读游戏 exe 路径（供 GUI 打开）；未适配/缺失 → None。"""
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name].get_game_exe_path(script_name)


def is_adapted(script_name: str) -> bool:
    """查询脚本是否已注册副本适配（供 GUI 决定是否显示任务卡）。"""
    return script_name in _CONFIGS


def supports_weekly(script_name: str) -> bool:
    """查询脚本是否支持周常（供 GUI 控制周常行可选性）。"""
    if script_name not in _CONFIGS:
        return False
    return bool(_CONFIGS[script_name]._weekly_task_name)


def get_background_rel_path(script_name: str) -> str:
    """读脚本默认背景图相对路径（相对脚本根目录，供 GUI 背景控制器）。

    Args:
        script_name: 脚本标识名。

    Returns:
        背景图相对路径；未适配或未声明背景图时返回空字符串。
    """
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].background


def set_weekly_task(script_name: str, weekly_name: str, task_name: str) -> None:
    """适配器接口：写某周常当前选中的副本名到脚本自身 config。

    未适配或该脚本无「周常选副本」概念（子类未实现）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常名（如「历战余响」）。
        task_name: 选中的副本名。
    """
    if script_name not in _CONFIGS:
        return
    cfg_cls = _CONFIGS[script_name]
    if not hasattr(cfg_cls, "set_weekly_task"):
        return
    cfg = cfg_cls()
    cfg.set_weekly_task(weekly_name, task_name)


def set_weekly_start_day(script_name: str, start_day: int) -> None:
    """适配器接口：编辑期落盘周几起字面起始日到脚本自身 config。

    未适配或该脚本无「周几起」概念（子类未实现）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        start_day: 周几以后启用（1~7，1=周一）。
    """
    if script_name not in _CONFIGS:
        return
    cfg_cls = _CONFIGS[script_name]
    if not hasattr(cfg_cls, "set_weekly_start_day"):
        return
    cfg = cfg_cls()
    cfg.set_weekly_start_day(start_day)


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


def get_weekly_task(script_name: str, weekly_name: str) -> str | None:
    """读某周常当前选中的副本名（反读子脚本 config）。

    未适配周常副本（无 set_weekly_task）或字段未设置时返回 None。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常名（如「历战余响」）。

    Returns:
        当前选中的副本名；无真相/未设置返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name]()._read_weekly_task(weekly_name)


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
