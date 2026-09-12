"""副本配置适配器：统一 set_config 适配接口，按各脚本格式封装 config 读写。"""

import logging
import os
from copy import deepcopy
from typing import Any

from src.config.task_config import (
    get_options,
    get_physical_name,
    get_selection_key,
    has_selection_binding,
    load_daily_map,
    load_weekly_map,
    validate_selection_bindings,
)
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


def _scalar_kind(value: Any) -> type:
    """归一化标量类型，用于类型一致性比较。

    ruamel.yaml 往返会把带引号字符串读成 ``str`` 的子类
    （如 ``DoubleQuotedScalarString``）、保留字读成对应子类。直接 ``type()``
    比较会误判为「类型不一致」。这里按真实语义归类，同时保留 ``bool`` 与
    ``int`` 的区分（``bool`` 是 ``int`` 的子类，但语义不同，必须分别对待）。

    Args:
        value: 待归类的标量值。

    Returns:
        归一化后的类型（bool / int / float / str 或原 type）。
    """
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, str):
        return str
    # ruamel 容器是原生 list/dict 的子类（CommentedSeq/CommentedMap），
    # 归一为 list/dict，避免与下游传入的原生容器比较时被判「类型不一致」。
    if isinstance(value, list):
        return list
    if isinstance(value, dict):
        return dict
    return type(value)


def safe_update(
    config: dict,
    key: str,
    value: Any,
    display_name: str = "",
    assert_key_exists: bool = True,
) -> bool:
    """安全更新单字段，返回是否发生实际修改。

    Args:
        config: 待修改的 config dict。
        key: 目标字段名。
        value: 目标值，类型须与现字段语义一致（按 _scalar_kind 归一化比较，
            容忍 ruamel 的 str/bool 子类，同时避免 bool/int 混淆）。
        display_name: 日志与报错用的脚本展示名。
        assert_key_exists: True 时缺字段直接 assert；False 时缺字段则新增。

    Returns:
        字段值是否发生了改变。

    Raises:
        AssertionError: 缺字段（assert_key_exists=True）或新旧类型不一致。
    """
    if assert_key_exists:
        assert key in config, f"[set_config][{display_name}] config 中缺少字段: {key}"
    elif key not in config:
        logger.warning(
            f"[set_config][{display_name}] 添加新字段 config['{key}'] = {value}"
        )
        config[key] = value
        return True

    assert _scalar_kind(config[key]) is _scalar_kind(value), (
        f"[set_config][{display_name}] 类型不一致: key={key}, "
        f"config={_scalar_kind(config[key]).__name__}, "
        f"value={_scalar_kind(value).__name__}"
    )

    if config[key] == value:
        return False

    config[key] = value
    logger.info(f"[set_config][{display_name}] 更新 config['{key}'] 为 {value}")
    return True


def get_field(
    config: dict,
    key: str,
    display_name: str,
    type: type | None = None,
    context: str = "",
):
    """取必填字段，缺字段或类型不符时 assert 暴露。

    Args:
        config: 待读取的 dict。
        key: 字段名。
        display_name: 日志与报错用的脚本展示名。
        type: 期望类型；非 None 时做 isinstance 校验。
        context: 报错上下文标签（如所属操作名），用于定位。

    Returns:
        config[key] 的值。

    Raises:
        AssertionError: 缺字段，或指定 type 后类型不符。
    """
    prefix = f"[set_config][{display_name}]"
    if context:
        prefix += f"[{context}]"
    assert key in config, f"{prefix} 缺少 {key} 字段"
    value = config[key]
    if type is not None:
        assert isinstance(value, type), f"{prefix} {key} 必须是 {type.__name__}"
    return value


# ============================================================
# 基类
# ============================================================


class ScriptConfig:
    """单个自动化脚本的 config 操作基类"""

    _script_name: str = ""
    """内部标识：script_path basename 去后缀，_CONFIGS 注册表索引。"""
    display_name: str = ""
    """GUI 展示名（如 鸣潮）。"""

    _daily_configs: dict[str, dict] = {}
    """具名日常声明，按有效物理名索引。"""
    _weekly_configs: dict[str, dict] = {}
    """具名周常声明；非空即支持周常。"""

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

    _weekly_config_rel_path: str = ""
    """周常配置文件路径；空字符串复用主 config。"""

    def _load(
        self, rel_path: str | None = None, *, allow_missing: bool = False
    ) -> dict | None:
        """读取脚本 config 并校验为 dict。

        写路径（初始化/落盘校验）要求 config 必须存在且为 dict，缺失即错误；
        读路径（反读日常/周本副本）允许文件缺失或解析失败，此时视为「未设置」返回 None。

        Args:
            rel_path: 相对脚本根目录的路径；缺省用 _config_rel_path。
            allow_missing: True 时文件缺失/解析失败返回 None（读路径）；
                False 时缺失即报错（写路径，默认）。

        Returns:
            解析后的 config dict；仅 allow_missing=True 且读取失败时为 None。

        Raises:
            AssertionError: allow_missing=False 且文件不存在或解析结果非 dict。
        """
        rel_path = rel_path or self._config_rel_path
        try:
            config = load_config(self._script_name, rel_path)
        except Exception:  # noqa: BLE001  # 读路径：缺失/损坏视为未设置
            if allow_missing:
                return None
            raise
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

    def _update_daily_task(
        self,
        config: dict,
        daily_name: str,
        option_name: str,
        sequence: str | int | None = None,
        assert_key_exists: bool = True,
    ) -> bool:
        """写入副本类型字段（及二级序列），返回是否修改。

        Args:
            config: 目标 config dict。
            daily_name: 日常任务标识。
            option_name: 副本展示名；未维护别名时使用原生名称。
            sequence: 二级序列的原生值；只有一级选择时必须为 None。
            assert_key_exists: 是否要求一级字段已存在。

        Returns:
            字段是否发生实际修改。

        Raises:
            AssertionError: 任务或选项未适配，字段缺失或类型不一致。
        """
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        definition = self._daily_configs[daily_name]
        assert isinstance(option_name, str) and option_name, "请选择具体副本"
        validate_selection_bindings(definition)
        key = get_selection_key(definition)
        options = get_options(definition)
        option = next(
            (item for item in options if item["display_name"] == option_name), None
        )
        if option is None:
            assert sequence is None, f"未适配的选项: {option_name}"
            # 纯展示分组或未维护别名的来源允许直接传原生名称。
            if "key" in definition["options"]:
                assert not options or "source" in definition["options"], (
                    f"未适配的副本: {option_name}"
                )
            return safe_update(
                config,
                key,
                option_name,
                self.display_name,
                assert_key_exists and "key" in definition["options"],
            )
        pending = deepcopy(config)
        changed = False
        if "options" in option:
            assert sequence is not None, (
                f"{option_name} 请选择具体副本，sequence 不能为空"
            )
            assert isinstance(sequence, (str, int)) and not isinstance(
                sequence, bool
            ), "序列必须为字符串或整数"
            assert not isinstance(sequence, str) or sequence, "二级选择必须为非空字符串"
            choices = get_options(option)
            assert not choices or any(
                isinstance(get_physical_name(choice), str) == isinstance(sequence, str)
                and get_physical_name(choice) == sequence
                for choice in choices
            ), f"{option_name} 未适配的序列: {sequence}"
            sub_key = get_selection_key(option)
            assert "key" not in definition["options"] or key != sub_key, (
                "两层选择不能写入同一字段"
            )
            changed = safe_update(
                pending, sub_key, sequence, self.display_name, assert_key_exists=False
            )
        else:
            assert sequence is None, f"{option_name} 不支持 sequence 参数"
        if "key" in definition["options"]:
            changed |= safe_update(
                pending,
                key,
                get_physical_name(option),
                self.display_name,
                assert_key_exists,
            )
        if changed:
            config.clear()
            config.update(pending)
        return changed

    def _read_value(self, config: dict, field: str):
        if field not in config:
            return None
        value = config[field]
        assert value is None or (
            isinstance(value, (str, int)) and not isinstance(value, bool)
        ), "副本值必须为字符串或整数"
        return None if value == "" else value

    def _read_daily_config(
        self, config: dict, daily_name: str
    ) -> tuple[str | int | None, str | int | None]:
        """按同一组字段反读展示名和二级原生值，未知值保留类型。"""
        assert isinstance(config, dict), "任务配置必须是 dict"
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        definition = self._daily_configs[daily_name]
        if not has_selection_binding(definition):
            return None, None
        validate_selection_bindings(definition)
        options = get_options(definition)
        value = self._read_value(config, get_selection_key(definition))
        if value is None:
            return None, None
        if "key" in definition["options"]:
            option = next(
                (item for item in options if get_physical_name(item) == value), None
            )
            if option is None:
                return value, None
            if "options" in option:
                return option["display_name"], self._read_value(
                    config, get_selection_key(option)
                )
            return option["display_name"], None
        matches = [
            option
            for option in options
            if any(get_physical_name(child) == value for child in get_options(option))
        ]
        if len(matches) == 1:
            return matches[0]["display_name"], value
        return value, None

    def _read_daily_task(
        self, daily_name: str
    ) -> tuple[str | int | None, str | int | None]:
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        if not has_selection_binding(self._daily_configs[daily_name]):
            return None, None
        config = self._load(allow_missing=True)
        if config is None:
            return None, None
        return self._read_daily_config(config, daily_name)

    def _read_weekly_task(
        self, weekly_name: str
    ) -> tuple[str | int | None, str | int | None]:
        """无周常副本适配时返回空选择；由具体脚本覆写。"""
        return None, None

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
        self, daily_name: str, option_name: str, sequence: str | int | None = None
    ) -> None:
        """设置副本：更新任务类型与序列后落盘。

        Args:
            daily_name: 日常任务标识。
            option_name: 副本中文名。
            sequence: 序列值；不传则仅设置任务类型。
        """
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        config = self._load()
        changed = self._update_daily_task(config, daily_name, option_name, sequence)
        if changed:
            logger.info(f"[set_daily_task][{self.display_name}] config 已更新")
            self._save(config)
        else:
            logger.info(f"[set_daily_task][{self.display_name}] config 无需更新")

    def set_weekly_task(self, weekly_name: str, start_day: int) -> None:
        """更新一个具名周常，保留同脚本的其他任务。"""
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
        self._set_weekly_tasks([weekly_name], start_day)

    def set_weekly_tasks(self, start_day: int) -> None:
        """运行时更新全部周常，统一保存。"""
        self._set_weekly_tasks(list(self._weekly_configs), start_day)

    def _set_weekly_tasks(self, names: list[str], start_day: int) -> None:
        """逐个更新具名周常；同一份配置全部成功后才统一保存。"""
        assert self._weekly_configs, f"[set_config][{self.display_name}] 未支持周常配置"
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )
        config = self._load_weekly() if self._weekly_config_rel_path else self._load()
        pending = deepcopy(config)
        changed = False
        for name in names:
            changed |= self._write_weekly(pending, name, start_day)
        if changed:
            if self._weekly_config_rel_path:
                self._save_weekly(pending)
            else:
                self._save(pending)

    def _write_weekly(self, config: dict, weekly_name: str, start_day: int) -> bool:
        """写入周常开关。基类默认不支持（未适配子类不应走到此处）。"""
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
    def get_task_options(
        cls, source_value: str | int, source_path: str
    ) -> list[str] | None:
        """读取某任务（周常/日常）的可选副本名清单（类方法，无需实例化）。

        Args:
            source_value: 资源内的分类标识或键名；无需别名时与展示名相同。
            source_path: 资源文件相对脚本根目录的路径。

        Returns:
            副本名列表（含「无」等占位）；未适配或源不可达时返回 None。
        """
        logger.warning(
            f"[set_config][{cls.display_name}] 未适配副本清单读取: source_path={source_path!r}"
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
    声明了条件属性（_game_path_keys / _weekly_configs）必须补全对应依赖。

    Args:
        cls: 待注册的 ScriptConfig 子类。

    Returns:
        原样返回 cls（便于装饰器使用）。

    Raises:
        AssertionError: 缺少 _script_name/_config_rel_path/_backup_paths 显式声明，
            或声明了 _game_path_keys/_weekly_configs 但未补全对应声明/实现。
    """
    for attr in ("_script_name", "_config_rel_path", "_backup_paths"):
        assert attr in cls.__dict__, f"[set_config][{cls.__name__}] 必须声明 {attr}"
    if cls._game_path_keys:
        assert "_game_config_rel_path" in cls.__dict__, (
            f"[set_config][{cls.__name__}] 声明了 _game_path_keys 必须声明 "
            f"_game_config_rel_path"
        )
    daily_declarations = load_daily_map()
    assert cls._script_name in daily_declarations, f"缺少日常声明: {cls._script_name}"
    cls._daily_configs = {
        get_physical_name(task): deepcopy(task)
        for task in daily_declarations[cls._script_name]
    }
    weekly_declarations = load_weekly_map()
    # 无周常声明时不支持周常，并覆盖继承的声明。
    cls._weekly_configs = {
        get_physical_name(task): deepcopy(task)
        for task in weekly_declarations.get(cls._script_name, [])
    }
    assert not cls._daily_configs.keys() & cls._weekly_configs.keys(), (
        f"{cls._script_name} 的日常、周常任务物理名重复"
    )
    if cls._weekly_configs:
        assert cls._write_weekly is not ScriptConfig._write_weekly, (
            f"{cls.__name__} 声明了周常必须实现 _write_weekly"
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
    _backup_paths = ("data/apps/ok-ww/working/configs",)
    _config_rel_path = "data/apps/ok-ww/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ww/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "鸣潮"

    def _write_weekly(self, config: dict, weekly_name: str, start_day: int) -> bool:
        """控制「Check Weekly Garden」在 Additional Tasks 中的增删。

        Args:
            config: 目标 config dict。
            weekly_name: 周常任务标识。
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 缺少 Additional Tasks 列表字段。
        """
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
        definition = self._weekly_configs[weekly_name]
        assert "key" in definition, "周常必须声明 key"
        task_name = get_physical_name(definition)
        enabled = is_weekly_start_reached(start_day)
        tasks = get_field(config, definition["key"], self.display_name, list)
        contains = task_name in tasks
        if enabled == contains:
            logger.info(
                f"[set_weekly][{self.display_name}] 周常状态无变化（enabled={enabled}）"
            )
            return False
        if enabled:
            tasks.append(task_name)
        else:
            tasks.remove(task_name)
        logger.info(
            f"[set_weekly][{self.display_name}] {'启用' if enabled else '停用'}周常"
        )
        return True


# ---- 原神 Genshin Impact ----
@register
class GenshinConfig(ScriptConfig):
    _script_name = "BetterGI"
    display_name = "原神"
    _backup_paths = ("User",)
    _config_rel_path = "User/OneDragon/默认配置.json"
    _game_config_rel_path = "User/config.json"
    _template_rel_path = "BGI一条龙.json"
    _game_path_keys = ("genshinStartConfig", "installPath")

    @classmethod
    def get_task_options(cls, source_value: str | int, source_path: str) -> list[str]:
        """读 BetterGI 的 tp.json，取某秘境分类（周常/日常）的副本名清单。

        Args:
            source_value: 资源内的秘境 type，由选项的 value 提供。
            source_path: tp.json 相对脚本根目录的路径。

        Returns:
            副本名列表（即 tp.json 的 ``name`` 字段）；文件缺失/空时返回 ``[]``。
        """
        data = load_game_config(cls._script_name, source_path)
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
                if isinstance(pt, dict) and pt.get("type", "") == source_value:
                    name = pt.get("name")
                    if name:
                        names.append(name)
        return names


# ---- 终末地 Arknights: Endfield ----
@register
class EndfieldConfig(ScriptConfig):
    _script_name = "ok-ef"
    display_name = "终末地"
    _template_rel_path = "okef一条龙.json"
    _backup_paths = ("data/apps/ok-ef/working/configs",)
    _config_rel_path = "data/apps/ok-ef/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ef/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)

    def _write_weekly(self, config: dict, weekly_name: str, start_day: int) -> bool:
        """控制 DailyTask.json 的「只买不卖」周常开关（语义反相）。

        游戏约定：只买不卖=true → 不卖出 → 周常「卖出物资」关闭，
        故 enabled 须反相写入。

        Args:
            config: 目标 config dict。
            weekly_name: 周常任务标识。
            start_day: 周几以后启用（1~7，1=周一）。
        """
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
        definition = self._weekly_configs[weekly_name]
        assert "key" in definition, "周常必须声明 key"
        enabled = is_weekly_start_reached(start_day)
        # 反相：enabled=True（卖出物资）→ 只买不卖=false
        return safe_update(config, definition["key"], not enabled, self.display_name)

    @classmethod
    def get_task_options(cls, source_value: str | int, source_path: str) -> list[str]:
        """读取体力本的可选副本名清单。

        Args:
            source_value: 日常类别名（即 stages_dict 的键，如「能量淤积点」）。
            source_path: world_map.json 相对脚本根目录的路径。

        Returns:
            副本名列表；未安装/缺失/空文件时返回 []。
        """
        data = load_game_config(cls._script_name, source_path)
        if not data:
            return []
        assert isinstance(data, dict), (
            f"[set_config][{cls.display_name}] world_map.json 顶层应为 dict: {source_path}"
        )
        stages = data.get("stages_dict")
        assert isinstance(stages, dict), (
            f"[set_config][{cls.display_name}] world_map.json 缺少 stages_dict: {source_path}"
        )
        assert source_value in stages, (
            f"[set_config][{cls.display_name}] 未知日常类别: {source_value!r} (source_path={source_path})"
        )
        entry = stages[source_value]
        assert isinstance(entry, list), (
            f"[set_config][{cls.display_name}] stages_dict[{source_value!r}] 应为 list: {source_path}"
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

    def set_daily_task(
        self, daily_name: str, option_name: str, sequence: str | int | None = None
    ) -> None:
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        logger.info("[set_config][%s] %s 由脚本自行管理", self.display_name, daily_name)

    def _write_weekly(self, config: dict, weekly_name: str, start_day: int) -> bool:
        """控制 _group.yml 中 lost_void 的 enabled 开关。

        Args:
            config: 目标 config dict。
            weekly_name: 周常任务标识。
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: app_list 缺少 lost_void 条目。
        """
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
        definition = self._weekly_configs[weekly_name]
        task_name = get_physical_name(definition)
        enabled = is_weekly_start_reached(start_day)
        # 周常（迷失之地）是 _group.yml app_list 中的 app_id。
        app_list = get_field(config, "app_list", self.display_name, list)
        target = next(
            (app for app in app_list if "app_id" in app and app["app_id"] == task_name),
            None,
        )
        assert target is not None, (
            f"[set_config][{self.display_name}] app_list 缺少 {task_name}"
        )
        return safe_update(target, "enabled", enabled, self.display_name)


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

    @classmethod
    def get_task_options(cls, source_value: str | int, source_path: str) -> list[str]:
        """读取某任务（周常/日常）的可选副本名清单。

        Args:
            source_value: 任务名（即文件中的键，如「历战余响」）。
            source_path: 副本清单文件相对脚本根目录的路径。

        Returns:
            副本名列表（含「无」等占位）；data 为空（未安装/缺失/空文件）时返回空列表。
        """
        data = load_game_config(cls._script_name, source_path)
        if not data:
            return []
        assert isinstance(data, dict), (
            f"[set_config][{cls.display_name}] 副本清单 {source_path} 非 dict: {type(data)}"
        )
        assert source_value in data, (
            f"[set_config][{cls.display_name}] 副本清单 {source_path} 缺任务 {source_value!r}"
        )
        entry = data[source_value]
        assert isinstance(entry, dict), (
            f"[set_config][{cls.display_name}] 任务 {source_value!r} 条目非 dict: {type(entry)}"
        )
        return list(entry.keys())

    def set_daily_task(
        self, daily_name: str, option_name: str, sequence: str | int | None = None
    ) -> None:
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        logger.info("[set_config][%s] %s 由脚本自行管理", self.display_name, daily_name)

    def _write_weekly(self, config: dict, weekly_name: str, start_day: int) -> bool:
        """设置指定周常的周几起。

        - 货币战争（开关型）：M7A 无自身周几起门控，由 launcher 按周几起落盘
          currencywars_enable。
        - 历战余响（选副本型）：把周几起写入 M7A 的 echo_of_war_start_day_of_week，
          由 M7A 自身按该日门控；副本选型 instance_names 正交，不在这里改动。

        Args:
            config: 目标 config dict。
            weekly_name: 周常任务标识。
            start_day: 周几以后启用（1~7，1=周一）。
        """
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
        definition = self._weekly_configs[weekly_name]
        assert "key" in definition, "周常必须声明 key"
        if weekly_name == "历战余响":
            return safe_update(
                config,
                definition["key"],
                start_day,
                self.display_name,
                assert_key_exists=False,
            )
        return safe_update(
            config,
            definition["key"],
            is_weekly_start_reached(start_day),
            self.display_name,
        )

    def set_weekly_start_day(self, start_day: int) -> None:
        """编辑期落盘周几起字面起始日到 echo_of_war_start_day_of_week。

        与 set_weekly_tasks 不同：本方法不写 currencywars_enable（开关型周本需运行期按
        「今天是否已到起始日」计算二进制开关），只写 可选关卡的周常（历战余响）的字面
        起始日，由 M7A 自身按该日门控。编辑期改周几起即应落盘此值，无需等待链运行。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。
        """
        assert "历战余响" in self._weekly_configs, "未适配历战余响"
        definition = self._weekly_configs["历战余响"]
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )
        # 前置条件：游戏原生 config 路径有效（游戏已安装、script_path 正确），由 GUI 侧
        # 调用前保证；本方法假设该前置成立，不做存在性兜底盘。
        assert "key" in definition, "周常必须声明key"
        config = self._load(allow_missing=True) or {}
        config[definition["key"]] = start_day
        self._save(config)

    def set_weekly_task_option(
        self, weekly_name: str, option_name: str, sequence: str | int | None = None
    ) -> None:
        """当前上游只保存一个原生副本名。"""
        assert weekly_name == "历战余响", "该周常不支持副本选择"
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
        definition = self._weekly_configs[weekly_name]
        options = get_options(definition)
        value = next(
            (
                get_physical_name(option)
                for option in options
                if option["display_name"] == option_name
            ),
            option_name,
        )
        assert sequence is None, "历战余响当前不支持二级选择"
        config = self._load()
        instance_names = config.get("instance_names", {})  # 上游未配置时允许创建。
        assert isinstance(instance_names, dict), "instance_names 必须是 dict"
        instance_names[weekly_name] = value
        config["instance_names"] = instance_names
        self._save(config)

    def _read_weekly_task(
        self, weekly_name: str
    ) -> tuple[str | int | None, str | int | None]:
        if weekly_name != "历战余响":
            return super()._read_weekly_task(weekly_name)
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
        definition = self._weekly_configs[weekly_name]
        config = self._load(allow_missing=True)
        if config is None:
            return None, None
        assert isinstance(config, dict), "任务配置必须是 dict"
        instance_names = config.get("instance_names", {})  # 未配置时没有当前选择。
        assert isinstance(instance_names, dict), "instance_names 必须是 dict"
        value = instance_names.get(weekly_name, None)  # 同一文件可尚未配置此任务。
        if value is None:
            return None, None
        for option in get_options(definition):
            native = get_physical_name(option)
            if isinstance(native, str) == isinstance(value, str) and native == value:
                return option["display_name"], None
        return str(value), None


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

    def _routine_item(self, routine: dict, daily_name: str) -> dict:
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        definition = self._daily_configs[daily_name]
        task_id = get_physical_name(definition)
        assert isinstance(routine, dict), "DailyRoutineTask.json 必须是 dict"
        items = get_field(routine, "Routine Items", self.display_name, list)
        assert all(isinstance(item, dict) and "id" in item for item in items), (
            "Routine Item 缺少 id"
        )
        matches = [item for item in items if item["id"] == task_id]
        assert len(matches) == 1, f"Routine Items 必须唯一包含 {task_id}"
        item = matches[0]
        get_field(item, "enabled", self.display_name, bool)
        return item

    def _update_daily_task(
        self,
        config: dict,
        daily_name: str,
        option_name: str,
        sequence: str | int | None = None,
    ) -> bool:
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        definition = self._daily_configs[daily_name]
        native = get_field(
            config, get_physical_name(definition), self.display_name, dict
        )
        # NTE 在首次配置某种副本时才生成对应字段。
        return super()._update_daily_task(
            native, daily_name, option_name, sequence, assert_key_exists=False
        )

    def _read_task_enabled(self, daily_name: str) -> bool | None:
        routine = self._load(self._routine_config_rel_path, allow_missing=True)
        return (
            None
            if routine is None
            else self._routine_item(routine, daily_name)["enabled"]
        )

    def _set_task_enabled(self, daily_name: str, enabled: bool) -> None:
        routine = deepcopy(self._load(self._routine_config_rel_path))
        if safe_update(
            self._routine_item(routine, daily_name),
            "enabled",
            enabled,
            self.display_name,
        ):
            self._save(routine, self._routine_config_rel_path)

    def set_daily_task(
        self, daily_name: str, option_name: str, sequence: str | int | None = None
    ) -> None:
        routine = deepcopy(self._load(self._routine_config_rel_path))
        changed = safe_update(
            self._routine_item(routine, daily_name), "enabled", True, self.display_name
        )
        super().set_daily_task(daily_name, option_name, sequence)
        if changed:
            self._save(routine, self._routine_config_rel_path)

    def _read_daily_config(
        self, config: dict, daily_name: str
    ) -> tuple[str | int | None, str | int | None]:
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        definition = self._daily_configs[daily_name]
        native = config.get(
            get_physical_name(definition), {}
        )  # 原生任务配置可能尚未生成。
        assert isinstance(native, dict), "NTE 任务配置必须是 dict"
        return super()._read_daily_config(native, daily_name)


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
    # 关卡代码 → 中文名。基于 StagePlan[0] 识别任务，不再依赖 TaskQueue 顺序。
    # 只维护这5个关卡，其余 FightTask 不动。

    def _daily_task_map(self, daily_name: str) -> dict[str, str]:
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        definition = self._daily_configs[daily_name]
        return {
            "Annihilation": "剿灭",
            **{
                get_physical_name(option): option["display_name"]
                for option in get_options(definition)
            },
        }

    def _update_daily_task(
        self,
        config: dict,
        daily_name: str,
        option_name: str,
        sequence: str | int | None = None,
    ) -> bool:
        """粥副本设置：基于 StagePlan[0] 识别任务，启用剿灭/土/选定副本。

        主路径只处理 _task_map 中的5个关卡，其余 FightTask 不动。

        若用户 MAA 配置队列中完全不存在 target_stage，
        则借用一个槽位改写其 StagePlan。

        Args:
            config: 目标 config dict。
            option_name: 选定副本中文名。

        Returns:
            是否有任意任务项状态发生变化。

        Raises:
            AssertionError: 未适配的副本（option_name 不在 _task_map）。
        """
        assert daily_name in self._daily_configs, f"未适配的日常: {daily_name}"
        task_map = self._daily_task_map(daily_name)
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        # 反查：中文名 → 关卡代码
        stage_by_name = {name: stage for stage, name in task_map.items()}
        assert option_name in stage_by_name, (
            f"[set_config][{self.display_name}] 未适配的副本: {option_name}"
        )
        target_stage = stage_by_name[option_name]

        fixed_stages = {"Annihilation", "1-7"}
        changed = False
        matched_target = False
        for task in task_config:
            if task.get("$type") != "FightTask":
                continue
            stage_plan = task.get("StagePlan")
            if not isinstance(stage_plan, list) or len(stage_plan) != 1:
                continue
            stage = stage_plan[0]
            if stage not in task_map:
                continue  # 未维护的关卡，不动
            if stage == target_stage:
                matched_target = True
            name = task_map[stage]

            should_enable = stage in fixed_stages or stage == target_stage
            changed |= safe_update(
                task,
                "IsEnable",
                should_enable,
                f"{self.display_name}[{name}]",
            )

        # fallback（issue #42）：目标关卡缺失时借槽改写 StagePlan，优先借用
        # 副本列表内的启用槽（剿灭除外），其次才借未追踪占位槽。仅改 StagePlan。
        if not matched_target:
            candidates = [
                t
                for t in task_config
                if t.get("$type") == "FightTask"
                and t.get("IsEnable")
                and isinstance(t.get("StagePlan"), list)
                and len(t["StagePlan"]) == 1
                and t["StagePlan"][0] != "Annihilation"
            ]
            borrow = next(
                (t for t in candidates if t["StagePlan"][0] in task_map),
                None,
            ) or next(iter(candidates), None)
            if borrow is not None:
                borrowed = borrow.get("Name", self.display_name)
                changed |= safe_update(
                    borrow,
                    "StagePlan",
                    [target_stage],
                    f"{self.display_name}[borrow:{borrowed}]",
                )

        return changed

    def _read_daily_task(
        self, daily_name: str
    ) -> tuple[str | int | None, str | int | None]:
        """反读当前日常副本（与 _update_daily_task 对称）。

        遍历 TaskQueue，除固定启用的剿灭/土外，
        被勾选 IsEnable 的那一项即当前副本。
        特殊：若所有维护关卡都未启用，但有 StagePlan=["1-7"] 的任务，则读为「土」。

        Returns:
            (副本中文名, None)；未设置返回 (None, None)。
        """
        task_map = self._daily_task_map(daily_name)
        config = self._load(allow_missing=True)
        if config is None:
            return None, None  # 脚本未安装/未配置
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        fixed_stages = {"Annihilation", "1-7"}
        has_1_7 = False
        for task in task_config:
            if task.get("$type") != "FightTask":
                continue
            stage_plan = task.get("StagePlan")
            if not isinstance(stage_plan, list) or len(stage_plan) != 1:
                continue
            stage = stage_plan[0]
            if stage == "1-7":
                has_1_7 = True
            if stage not in task_map:
                continue
            name = task_map[stage]
            if stage in fixed_stages:
                continue
            if task.get("IsEnable"):
                return name, None
        # 所有维护关卡都未启用，但有1-7 → 读为土
        if has_1_7:
            # 未维护别名时直接展示原生关卡代码。
            return task_map.get("1-7", "1-7"), None
        return None, None

    def _write_weekly(self, config: dict, weekly_name: str, start_day: int) -> bool:
        """周常「理智药剂」：按周几起写过期理智药使用窗口，并随副本启停同步开关。

        本方法每次调用都更新（不按「今天是否到起始日」门控）：
        - 开启的 FightTask 设 UseExpiringMedicine=true，其余设 false；
        - 剿灭不吃理智药：即便开启也强制 UseExpiringMedicine=false（照常运行，只是不吃药）；
        - MedicineExpireDays 由周几起推算：周几起 = 7 - MedicineExpireDays + 1
          ⇒ MedicineExpireDays = 8 - 周几起（周几起∈1~7，1=周一）。

        Args:
            config: 目标 config dict。
            weekly_name: 周常任务标识。
            start_day: 周几起（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常或任务队列结构不符合约定。
        """
        assert weekly_name in self._weekly_configs, f"未适配的周常: {weekly_name}"
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
            if task.get("$type") != "FightTask":
                continue
            enabled = bool(task.get("IsEnable", False))
            # 剿灭不吃理智药：开启但仍强制 false
            use_medicine = enabled and task.get("Name") != "剿灭"
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
        return changed

    def set_weekly_start_day(self, start_day: int) -> None:
        """编辑期落盘周几起字面起始日到 MedicineExpireDays。

        与 set_weekly_tasks 不同：本方法只写 MedicineExpireDays（由周几起推算：
        MedicineExpireDays = 8 - 周几起），不写 UseExpiringMedicine（是否吃药的
        开关依赖各 FightTask 的启用状态，需运行期按当日副本选型经 set_weekly_tasks 计算）。
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
            if task.get("$type") != "FightTask":
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
    option_name: str | None = None,
    sequence: str | int | None = None,
    weekly_start: int | None = None,
    daily_name: str | None = None,
    weekly_name: str | None = None,
) -> None:
    """适配器接口：设置副本 / 序列 / 周常起始日。

    未选副本且无周常，或脚本未适配（自定义脚本）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        option_name: 副本中文名；None 或「未选择」表示不设置副本。
        sequence: 序列值；仅部分脚本支持。
        weekly_start: 周常起始日（1~7）；None 表示不设置周常。
        daily_name: 日常名字；设置副本时必填，不能隐式选择第一项。
        weekly_name: 只更新该周常；省略时批量更新脚本的全部周常。
    """
    if (not option_name or option_name == "未选择") and weekly_start is None:
        return

    # 自定义脚本（不在注册表）跳过
    if script_name not in _CONFIGS:
        logger.info(f"[set_config] 进程 {script_name} 无副本适配（自定义脚本），跳过")
        return

    cfg_cls = _CONFIGS[script_name]
    cfg = cfg_cls()
    if option_name and option_name != "未选择":
        assert daily_name, "设置副本必须指定日常名"
        cfg.set_daily_task(daily_name, option_name, sequence)
    if weekly_start is not None:
        if weekly_name is None:
            cfg.set_weekly_tasks(weekly_start)
        else:
            cfg.set_weekly_task(weekly_name, weekly_start)


def get_task_options(
    script_name: str, source_value: str | int, source_path: str
) -> list[str] | None:
    """适配器接口：副本清单源在游戏脚本自身配置里，从中读某任务的可选副本名清单，委托给对应脚本的 config 类。

    「从哪读、怎么解析」的知识归各 ``ScriptConfig`` 子类，本函数只做分发。

    Args:
        script_name: 脚本唯一标识（如 ``March7th-Launcher``）。
        source_value: 资源内的分类标识或键名；无需别名时与展示名相同。
        source_path: 资源文件相对脚本根目录的路径。

    Returns:
        副本名列表（含「无」等占位）；不可用时返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name].get_task_options(source_value, source_path)


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
    return bool(_CONFIGS[script_name]._weekly_configs)


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


def set_weekly_task_option(
    script_name: str,
    weekly_name: str,
    option_name: str,
    sequence: str | int | None = None,
) -> None:
    """适配器接口：写某周常当前选中的副本名到脚本自身 config。

    未适配或该脚本无「周常选副本」概念（子类未实现）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常名（如「历战余响」）。
        option_name: 选中的副本名。
    """
    if script_name not in _CONFIGS:
        return
    cfg_cls = _CONFIGS[script_name]
    if not hasattr(cfg_cls, "set_weekly_task_option"):
        return
    cfg = cfg_cls()
    cfg.set_weekly_task_option(weekly_name, option_name, sequence)


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


def get_daily_task(
    script_name: str, daily_name: str
) -> tuple[str | int | None, str | int | None]:
    """一次反读指定日常的副本与二级序列，未适配时返回空选择。"""
    if script_name not in _CONFIGS:
        return None, None
    return _CONFIGS[script_name]()._read_daily_task(daily_name)


def get_weekly_task(
    script_name: str, weekly_name: str
) -> tuple[str | int | None, str | int | None]:
    """反读指定周常，与日常使用相同选择结构。"""
    if script_name not in _CONFIGS:
        return None, None
    cfg = _CONFIGS[script_name]()
    if not cfg._weekly_configs:
        return None, None
    return cfg._read_weekly_task(weekly_name)


def get_task_enabled(script_name: str, task_name: str) -> bool | None:
    """反读具名任务的原生启用状态。"""
    assert script_name in _CONFIGS, f"未适配的脚本: {script_name}"
    cfg = _CONFIGS[script_name]()
    definitions = {**cfg._daily_configs, **cfg._weekly_configs}
    assert task_name in definitions, f"未适配的任务: {task_name}"
    assert definitions[task_name].get("allow_disable", False), (
        "任务未声明 allow_disable"
    )
    return cfg._read_task_enabled(task_name)


def set_task_enabled(script_name: str, task_name: str, enabled: bool) -> None:
    """只更新一个任务的启用状态，保留其选择。"""
    assert isinstance(enabled, bool), "enabled 必须为 bool"
    assert script_name in _CONFIGS, f"未适配的脚本: {script_name}"
    cfg = _CONFIGS[script_name]()
    definitions = {**cfg._daily_configs, **cfg._weekly_configs}
    assert task_name in definitions, f"未适配的任务: {task_name}"
    assert definitions[task_name].get("allow_disable", False), (
        "任务未声明 allow_disable"
    )
    cfg._set_task_enabled(task_name, enabled)
