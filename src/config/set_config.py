"""副本配置适配器：统一 set_config 适配接口，按各脚本格式封装 config 读写。"""

import logging
import os
from typing import Any

from src.config.subscript import (
    get_config_path as _get_config_path_impl,
)
from src.config.subscript import (
    load_config,
    load_game_config,
    load_template,
    save_config,
)
from src.utils_weekly import is_weekly_start_reached

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
    _task_key: str = ""
    """config 中副本类型字段名，设了即启用 _update_task。"""
    _task_map: dict[str, Any] = {}
    """副本中文名 → config 值；空 dict 表示直接用 dungeon_name。"""

    _game_path_keys: tuple[str, ...] = ()
    """游戏 exe 路径在游戏配置中的嵌套键路径；空元组表示未适配「打开游戏」。"""

    _config_rel_path: str = ""
    """config 文件相对脚本根目录路径。"""

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

    _enabled: bool = True
    """实例是否可操作 config；拒绝保存后置 False 使后续写入一并失效。"""

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
        if not self._enabled:
            logger.info(f"[set_config][{self.display_name}] 用户拒绝更新，跳过保存")
            return
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
        if not self._enabled:
            logger.info(f"[set_config][{self.display_name}] 用户拒绝更新，跳过保存")
            return
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

    def _update_task(
        self, config: dict, dungeon_name: str, sequence: str | int | None = None
    ) -> bool:
        """写入副本类型字段（及二级序列），返回是否修改。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名；_task_map 为空时直接作为字段值。
            sequence: 二级序列值；基类默认必须为 None。

        Returns:
            字段是否发生实际修改。

        Raises:
            AssertionError: 子类未声明 _task_key，或 dungeon_name 不在 _task_map，
                或基类收到非 None 的 sequence。
        """
        assert sequence is None, (
            f"[set_config][{self.display_name}] 不支持 sequence 参数"
        )
        assert self._task_key, f"[set_config][{self.display_name}] 子类必须设 _task_key"
        if self._task_map:
            task = get_field(
                self._task_map, dungeon_name, self.display_name, context="update_task"
            )
        else:
            task = dungeon_name
        return safe_update(config, self._task_key, task, self.display_name)

    def _read_dungeon(self) -> tuple[str | None, str | int | None]:
        """反读当前日常副本中文名与二级序列（经 _task_key + _task_map 反转）。

        返回 ``(副本中文名, 序列值)`` 二元组：基类仅处理标准存储结构下的副本反转，
        无二级序列通道时序列恒为 None。子类若有非标准存储结构（如 NTE 多 section）
        或二级序列，应覆写本方法并在内部调用 ``super()._read_dungeon()`` 复用标准反转，
        再补上自身逻辑后返回 ``(dungeon, sequence)``；若子类无标准存储结构
        （无 ``_task_key`` / 非 ``_task_key`` + ``_task_map``），可完全自行实现而不调 super。

        仅「脚本未安装」与「用户未选择」的副本部分返回 None；config 损坏或字段值未知
        属异常，直接 assert 暴露，不静默回退（否则会被 gui_state 兜底掩盖）。

        Returns:
            ``(副本中文名, 序列值)``；无 _task_key（无适应）/ 脚本未安装 / 未选择时
            副本部分为 None，序列部分恒为 None。
        """
        if not self._task_key:
            return None, None  # 无副本真相（如 ZZZ/崩铁日常）
        config = self._load(allow_missing=True)
        if config is None:
            return None, None  # 脚本未安装/未配置
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        raw = config.get(self._task_key)
        if raw is None:
            return None, None  # 未选择副本
        if self._task_map:
            inv = {v: k for k, v in self._task_map.items()}
            assert raw in inv, f"[set_config][{self.display_name}] 未知副本值: {raw!r}"
            return inv[raw], None
        return raw, None

    def _read_weekly_dungeon(self, weekly_name: str) -> str | None:
        """反读某周常当前选中的副本名（与 set_weekly_dungeon 对称）。

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

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """设置副本：更新任务类型与序列后落盘。

        enabled=False 时短路（用户拒绝更新）。

        Args:
            dungeon_name: 副本中文名。
            sequence: 序列值；不传则仅设置任务类型。
        """
        if not self._enabled:
            logger.info(
                f"[set_dungeon][{self.display_name}] 用户拒绝更新，跳过副本设置"
            )
            return
        config = self._load()
        changed = self._update_task(config, dungeon_name, sequence)
        if changed:
            logger.info(f"[set_dungeon][{self.display_name}] config 已更新")
            self._save(config)
        else:
            logger.info(f"[set_dungeon][{self.display_name}] config 无需更新")

    def set_weekly(self, start_day: int) -> None:
        """设置周常起始日并写入开关。

        enabled=False 时短路。周常开关为 GUI 内存态，不直写 config。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。

        Raises:
            AssertionError: 未适配周常，或 start_day 不在 1~7。
        """
        if not self._enabled:
            logger.info(f"[set_weekly][{self.display_name}] 用户拒绝更新，跳过周常设置")
            return
        assert self._weekly_task_name, (
            f"[set_config][{self.display_name}] 未支持周常配置"
        )
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )
        self._write_weekly(is_weekly_start_reached(start_day))

    def _write_weekly(self, enabled: bool) -> None:
        """写入周常开关。基类默认不支持（未适配子类不应走到此处）。

        Args:
            enabled: 是否启用周常。

        Raises:
            AssertionError: 基类默认调用（未适配周常的脚本）。
        """
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
    def get_dungeon_lists(cls, task_name: str, source: str) -> list[str] | None:
        """读取某任务（周常/日常）的可选副本名清单（类方法，无需实例化）。

        Args:
            task_name: 任务名（周常/日常均可，如「历战余响」）。
            source: 来源标记，即 weekly_list.yml 的 ``dungeons_source``。

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
        AssertionError: 缺少 _script_name/_config_rel_path 显式声明，或声明了
            _game_path_keys/_weekly_task_name 但未补全对应声明/实现。
    """
    for attr in ("_script_name", "_config_rel_path"):
        assert attr in cls.__dict__, f"[set_config][{cls.__name__}] 必须声明 {attr}"
    if cls._game_path_keys:
        assert "_game_config_rel_path" in cls.__dict__, (
            f"[set_config][{cls.__name__}] 声明了 _game_path_keys 必须声明 "
            f"_game_config_rel_path"
        )
    if cls._weekly_task_name:
        assert cls._write_weekly is not ScriptConfig._write_weekly or (
            cls.set_weekly is not ScriptConfig.set_weekly
        ), (
            f"[set_config][{cls.__name__}] 声明了 _weekly_task_name 必须实现 "
            f"_write_weekly 或覆写 set_weekly（周常写入的落点）"
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
    _config_rel_path = "data/apps/ok-ww/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ww/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "鸣潮"
    _task_key = "Which to Farm"
    _task_map = {
        "凝素领域": "Forgery Challenge",
        "模拟领域": "Simulation Challenge",
        "无音区": "Tacet Suppression",
    }
    _sequence_map = {
        "模拟领域": {
            "key": "Material Selection",
            "values": {
                "共鸣者经验": "Resonator EXP",
                "武器经验": "Weapon EXP",
                "贝币": "Shell Credit",
            },
        },
        "无音区": {"key": "Which Tacet Suppression to Farm", "values": None},
        "凝素领域": {"key": "Which Forgery Challenge to Farm", "values": None},
    }
    _weekly_task_name = "Check Weekly Garden"

    def _write_weekly(self, enabled: bool) -> None:
        """控制「Check Weekly Garden」在 Additional Tasks 中的增删。

        Args:
            enabled: True 追加任务，False 移除任务。

        Raises:
            AssertionError: 缺少 Additional Tasks 列表字段。
        """
        config = self._load()
        # 周常（乐园）在 Additional Tasks 列表中任务名 _weekly_task_name。
        tasks = get_field(
            config, "Additional Tasks to Run After Daily Task", self.display_name, list
        )
        contains = self._weekly_task_name in tasks
        if enabled == contains:
            logger.info(
                f"[set_weekly][{self.display_name}] 周常状态无变化（enabled={enabled}）"
            )
            return
        if enabled:
            tasks.append(self._weekly_task_name)
        else:
            tasks.remove(self._weekly_task_name)
        logger.info(
            f"[set_weekly][{self.display_name}] {'启用' if enabled else '停用'}周常"
        )
        self._save(config)

    def _update_task(
        self, config: dict, dungeon_name: str, sequence: str | int | None = None
    ) -> bool:
        """写入副本类型字段与二级序列字段，返回是否修改（与 _read_dungeon 对称）。

        先经基类标准副本写入（复用 ``_task_key`` + ``_task_map`` 反转），再按当前副本
        从 ``_sequence_map`` 写入二级序列字段。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名（决定映射键与取值方式）。
            sequence: 序列值；无二级映射时直接作为字段值。

        Returns:
            字段是否发生实际修改。

        Raises:
            AssertionError: 未适配的副本或序列。
        """
        changed = super()._update_task(config, dungeon_name, None)
        assert sequence is not None, (
            f"[set_dungeon][{self.display_name}] sequence 不能为空"
        )
        assert dungeon_name in self._sequence_map, (
            f"[set_dungeon][{self.display_name}] 未适配的副本: {dungeon_name}"
        )
        cfg = self._sequence_map[dungeon_name]

        if cfg["values"] is not None:
            assert sequence in cfg["values"], (
                f"[set_dungeon][{self.display_name}] 未适配的序列: {sequence}"
            )
            target = cfg["values"][sequence]
        else:
            target = sequence

        changed |= safe_update(
            config, cfg["key"], target, self.display_name, assert_key_exists=False
        )
        return changed

    def _read_dungeon(self) -> tuple[str | None, str | int | None]:
        """反读当前日常副本与二级序列值（与 set_dungeon / _update_task 对称）。

        先经基类标准反转得到副本名，再按当前副本从 ``_sequence_map`` 读回原始序列值
        （``values`` 映射反转回中文）。

        Returns:
            ``(副本中文名, 序列值)``；无序列通道/未设置时序列为 None。
        """
        dungeon, _ = super()._read_dungeon()
        if dungeon is None or dungeon not in self._sequence_map:
            return dungeon, None
        cfg = self._sequence_map[dungeon]
        config = self._load(allow_missing=True)
        if config is None:
            return dungeon, None  # 脚本未安装/未配置
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        raw = config.get(cfg["key"])
        if raw is None:
            return dungeon, None  # 未选择序号
        if cfg["values"] is not None:
            inv = {v: k for k, v in cfg["values"].items()}
            assert raw in inv, f"[set_config][{self.display_name}] 未知序列值: {raw!r}"
            return dungeon, inv[raw]
        return dungeon, raw


# ---- 原神 Genshin Impact ----
@register
class GenshinConfig(ScriptConfig):
    _script_name = "BetterGI"
    display_name = "原神"
    _task_key = "DomainName"
    _config_rel_path = "User/OneDragon/默认配置.json"
    _game_config_rel_path = "User/config.json"
    _template_rel_path = "BGI一条龙.json"
    _game_path_keys = ("genshinStartConfig", "installPath")

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """原神副本两级组织：有二级时写入二级副本名，否则回退一级。

        Args:
            dungeon_name: 一级副本名。
            sequence: 二级副本名；None 时回退一级。
        """
        target = sequence if sequence is not None else dungeon_name
        super().set_dungeon(target)

    @classmethod
    def get_dungeon_lists(cls, task_name: str, source: str) -> list[str]:
        """读 BetterGI 的 tp.json，取某秘境分类（周常/日常）的副本名清单。

        Args:
            task_name: 秘境分类（yml 中的中文名，如「圣遗物」）。
            source: tp.json 相对脚本根目录的路径。

        Returns:
            副本名列表（即 tp.json 的 ``name`` 字段）；文件缺失/空时返回 ``[]``。
        """
        # tp.json 按地图场景分组、秘境类别用英文 type；与 dungeon_list.yml 的中文
        # 分类名（圣遗物/武器/天赋）不同，故在此维护「中文分类 → tp.json type」映射。
        # type 含义：BlessDomain=圣遗物本，ForgeryDomain=武器本，MasteryDomain=天赋本。
        tp_domain_type_by_category = {
            "圣遗物": "BlessDomain",
            "武器": "ForgeryDomain",
            "天赋": "MasteryDomain",
        }
        data = load_game_config(cls._script_name, source)
        if not data:
            return []
        assert isinstance(data, dict), (
            f"[set_config][{cls.display_name}] 副本名应为 dict"
        )
        tp_type = tp_domain_type_by_category.get(task_name)
        assert tp_type is not None, (
            f"[set_config][{cls.display_name}] 未适配的秘境分类: {task_name!r}"
        )
        names: list[str] = []
        for scene in data.get("data", []):
            if not isinstance(scene, dict):
                continue
            for pt in scene.get("points", []):
                if isinstance(pt, dict) and pt.get("type") == tp_type:
                    name = pt.get("name")
                    if name:
                        names.append(name)
        return names


# ---- 终末地 Arknights: Endfield ----
@register
class EndfieldConfig(ScriptConfig):
    _script_name = "ok-ef"
    display_name = "终末地"
    _task_key = "体力本"
    _template_rel_path = "okef一条龙.json"
    _config_rel_path = "data/apps/ok-ef/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ef/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    _weekly_task_name = "只买不卖"
    """周常（卖出物资）在 DailyTask.json 中的开关键；true=只买不卖=不卖=周常关。"""

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """终末地副本两级组织：有二级时写入二级副本名，否则回退一级。

        Args:
            dungeon_name: 一级副本名。
            sequence: 二级副本名；None 时回退一级。
        """
        target = sequence if sequence is not None else dungeon_name
        super().set_dungeon(target)

    def _write_weekly(self, enabled: bool) -> None:
        """控制 DailyTask.json 的「只买不卖」周常开关（语义反相）。

        游戏约定：只买不卖=true → 不卖出 → 周常（卖出物资）关闭；
        故 enabled 需反相写入。

        Args:
            enabled: 是否启用周常（卖出物资）。
        """
        config = self._load()
        # 反相：enabled=True（卖出）→ 只买不卖=false
        safe_update(config, self._weekly_task_name, not enabled, self.display_name)
        self._save(config)

    @classmethod
    def get_dungeon_lists(cls, task_name: str, source: str) -> list[str]:
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
        stages = data.get("stages_dict")
        assert isinstance(stages, dict), (
            f"[set_config][{cls.display_name}] world_map.json 缺少 stages_dict: {source}"
        )
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
    _config_rel_path = "config/01/one_dragon/charge_plan.yml"
    _game_config_rel_path = "config/01/game_account.yml"
    _template_rel_path = "ZZZ一条龙.yml"
    _weekly_config_rel_path = "config/01/one_dragon/_group.yml"
    _game_path_keys = ("game_path",)
    background = "assets/ui/static_background.webp"
    _weekly_task_name = "lost_void"

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None):
        logger.info(f"[set_config][{self.display_name}] zzz无需适配")

    def _write_weekly(self, enabled: bool) -> None:
        """控制 _group.yml 中 lost_void 的 enabled 开关。

        Args:
            enabled: 是否启用周常。

        Raises:
            AssertionError: app_list 缺少 lost_void 条目。
        """
        config = self._load_weekly()
        # 周常（迷失之地）在 _group.yml app_list 中的 app_id。
        app_list = get_field(config, "app_list", self.display_name, list)
        target = next(
            (app for app in app_list if app.get("app_id") == self._weekly_task_name),
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
    _script_name = "March7th-Assistant"
    display_name = "崩铁"
    _config_rel_path = "config.yaml"
    _game_config_rel_path = "config.yaml"
    _template_rel_path = "M7A一条龙.yml"
    _game_path_keys = ("game_path",)
    background = "assets/app/images/bg37.jpg"
    _weekly_task_name = "currencywars_enable"

    @classmethod
    def get_dungeon_lists(cls, task_name: str, source: str) -> list[str]:
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

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None):
        logger.info(f"[set_config][{self.display_name}] M7A无需适配")

    def set_weekly(self, start_day: int) -> None:
        """崩铁周常：周几起对所有周本生效。

        - 货币战争（开关型）：M7A 无自身周几起门控，由 launcher 按周几起落盘
          currencywars_enable。
        - 历战余响（dungeon 型）：把周几起写入 M7A 的 echo_of_war_start_day_of_week，
          由 M7A 自身按该日门控；副本选型 instance_names 正交，不在这里改动。

        Args:
            start_day: 周几以后启用（1~7，1=周一）。
        """
        if not self._enabled:
            logger.info(f"[set_weekly][{self.display_name}] 用户拒绝更新，跳过周常设置")
            return
        assert self._weekly_task_name, (
            f"[set_config][{self.display_name}] 未支持周常配置"
        )
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )
        config = self._load()
        # 货币战争：今天是否已到起始日
        safe_update(
            config,
            self._weekly_task_name,
            is_weekly_start_reached(start_day),
            self.display_name,
        )
        # 历战余响：周几起交给 M7A 自身门控，与副本选型 instance_names 正交
        config["echo_of_war_start_day_of_week"] = start_day
        self._save(config)

    def set_weekly_start_day(self, start_day: int) -> None:
        """编辑期落盘周几起字面起始日到 echo_of_war_start_day_of_week。

        与 set_weekly 不同：本方法不写 currencywars_enable（开关型周本需运行期按
        「今天是否已到起始日」计算二进制开关），只写 dungeon 型周本（历战余响）的字面
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
        config["echo_of_war_start_day_of_week"] = start_day
        self._save(config)

    def set_weekly_dungeon(self, weekly_name: str, dungeon_name: str) -> None:
        """写入某周常当前选中的副本名到 config.yaml 的 instance_names。

        副本名清单的展示与下拉选项由 OneDragon-Helper 的 weekly_list.yml 声明
        （dungeons 字段）负责，本方法只承担把用户所选写回 M7A 游戏配置的本分。

        Args:
            weekly_name: 周常名（如「历战余响」）；即 instance_names 的键。
            dungeon_name: 选中的副本名（来自 weekly_list.yml 声明）。
        """
        config = self._load()
        # instance_names 是 M7A 约定键名（{周常名: 副本名} 的 dict），保持不动；
        # 缺字段则新建。
        instance_names = config.get("instance_names")
        if not isinstance(instance_names, dict):
            instance_names = {}
            config["instance_names"] = instance_names
        instance_names[weekly_name] = dungeon_name
        self._save(config)

    def _read_weekly_dungeon(self, weekly_name: str) -> str | None:
        """反读某周常当前选中的副本名（与 set_weekly_dungeon 对称）。

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
        instance_names = config.get("instance_names")
        if instance_names is None:
            return None  # 未配置周常副本
        assert isinstance(instance_names, dict), (
            f"[set_config][{self.display_name}] instance_names 必须是 dict"
        )
        return instance_names.get(weekly_name)  # 可能为 None（未选周常副本）


# ---- 异环 Neverness to Everness (NTE) ----
@register
class NTEConfig(ScriptConfig):
    _script_name = "ok-nte"
    _config_rel_path = "data/apps/ok-nte/working/configs/DailyRoutineTaskConfigs.json"
    _routine_config_rel_path = "data/apps/ok-nte/working/configs/DailyRoutineTask.json"
    _game_config_rel_path = "data/apps/ok-nte/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "异环"
    _exclusive_routine_items = ("daily_anomaly", "daily_anomaly_hunter")
    """互斥的两个日常 routine item id（DailyRoutineTask.json）。"""
    _anomaly_seq_key_map = {
        "异能升级材料": "异能材料序号",
        "空幕": "空幕序号",
        "弧盘突破材料": "弧盘材料序号",
        "经验与甲硬币": "具体奖励目标",
    }

    # 日常两种互斥模式：键 = 互斥 routine item id = DailyRoutineTaskConfigs.json 段名。
    _mode_specs = {
        "daily_anomaly": {
            "task_field": "任务类型",  # 副本中文名存此字段；追猎模式为 None
            "seq_fields": _anomaly_seq_key_map,  # 副本 → 序号字段
        },
        "daily_anomaly_hunter": {
            "task_field": None,
            "seq_fields": {"追猎目标": "追猎目标"},  # 副本名即 boss 名
        },
    }

    # 副本中文名 → 所属模式 id（写路径按 dungeon 反查模式，避免可变实例状态）。
    _dungeon_to_mode = {
        **dict.fromkeys(_anomaly_seq_key_map, "daily_anomaly"),
        "追猎目标": "daily_anomaly_hunter",
    }
    """副本中文名 → 日常模式 id（即 _mode_specs 的键）。"""

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

    def _daily_section_dict(self, config: dict, section: str) -> dict:
        """取指定日常任务配置段子对象（config 文件）。

        Args:
            config: 顶层 config dict。
            section: 段名（即模式 id，如 daily_anomaly / daily_anomaly_hunter）。

        Returns:
            日常任务配置子 dict。

        Raises:
            AssertionError: 缺段或类型非 dict。
        """
        return get_field(config, section, self.display_name, dict, "daily_section")

    def _update_task(
        self, config: dict, dungeon_name: str, sequence: str | int | None = None
    ) -> bool:
        """写入副本类型字段与序号字段，返回是否修改（与 _read_dungeon 对称）。

        由 dungeon 经 ``_dungeon_to_mode`` 反查日常模式（异象界域 / 追猎目标），
        再按 ``_mode_specs`` 声明的字段映射写入；不依赖可变实例状态。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名。
            sequence: 序号值。

        Returns:
            是否发生实际修改。

        Raises:
            AssertionError: 未适配的副本，序列为空，或副本无对应序号键。
        """
        assert dungeon_name in self._dungeon_to_mode, (
            f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        )
        mode_id = self._dungeon_to_mode[dungeon_name]
        mode = self._mode_specs[mode_id]
        section_dict = self._daily_section_dict(config, mode_id)
        task_field = mode["task_field"]
        if task_field is not None:
            dungeon_changed = safe_update(
                section_dict,
                task_field,
                dungeon_name,
                self.display_name,
                assert_key_exists=False,
            )
        else:
            dungeon_changed = False
        assert sequence is not None, f"[set_config][{self.display_name}] 序列不能为空"
        key = get_field(
            mode["seq_fields"], dungeon_name, self.display_name, context="update_task"
        )
        seq_changed = safe_update(
            section_dict, key, sequence, self.display_name, assert_key_exists=False
        )
        return dungeon_changed or seq_changed

    def _update_routine_exclusion(self, routine: dict, mode_id: str) -> bool:
        """互斥切换追猎目标与异象界域的 Routine Item 启用状态。

        Args:
            routine: DailyRoutineTask.json 的 dict。
            mode_id: 当前所选日常模式 id（_mode_specs 的键）。

        Returns:
            启用状态是否发生实际修改。

        Raises:
            AssertionError: Routine Items 缺少当前所选玩法段。
        """
        items = get_field(routine, "Routine Items", self.display_name, list)
        ids = {item["id"] for item in items}
        assert mode_id in ids, (
            f"[set_config][{self.display_name}] Routine Items 缺少 {mode_id}（无法启用所选玩法）"
        )
        changed = False
        for item in items:
            task_id = item["id"]
            if task_id not in self._exclusive_routine_items:
                continue
            changed |= safe_update(
                item, "enabled", task_id == mode_id, self.display_name
            )
        return changed

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """委托基类写配置（按 _dungeon_to_mode 反查模式），再切换第二份文件的互斥启用状态。

        Args:
            dungeon_name: 副本中文名。
            sequence: 序列值。
        """
        mode_id = self._dungeon_to_mode[dungeon_name]
        super().set_dungeon(dungeon_name, sequence)
        if self._enabled:
            routine = self._load(self._routine_config_rel_path)
            if self._update_routine_exclusion(routine, mode_id):
                self._save(routine, self._routine_config_rel_path)

    def _read_dungeon(self) -> tuple[str | None, str | int | None]:
        """反读当前日常副本与二级序号（与 set_dungeon / _update_task 对称）。

        当前玩法由 DailyRoutineTask.json 的 Routine Items 启用状态判定，经 ``_mode_specs``
        查表解析当前模式（异象界域 / 追猎目标）。追猎目标无任务类型通道，set_dungeon
        不写 daily_anomaly.任务类型（陈旧值），故必须优先用启用状态，不能直接读 任务类型。

        两种模式数据落点不同（NTE 既有结构）：追猎目标 boss 存于 routine 文件
        DailyRoutineTask.json 的 daily_anomaly_hunter 段；异象界域副本名+序号存于
        config 文件 DailyRoutineTaskConfigs.json 的 daily_anomaly 段。故按模式 id 分流读取。

        NTE 无标准存储结构（不依赖 _task_key + _task_map 反转），完全自行实现。
        脚本未安装（routine 缺失）返回 (None, None)；routine/config 损坏属异常，assert 暴露。

        Returns:
            (副本中文名, 序号值)；无启用玩法/未安装/未选择返回 (None, None)。
        """
        routine = self._load(self._routine_config_rel_path, allow_missing=True)
        if routine is None:
            return None, None  # 脚本未安装/未配置
        assert isinstance(routine, dict), (
            f"[set_config][{self.display_name}] DailyRoutineTask.json 必须是 dict"
        )
        enabled = {
            item.get("id")
            for item in routine.get("Routine Items", [])
            if isinstance(item, dict) and item.get("enabled")
        }
        # 追猎目标优先（与既有解析顺序一致）；互斥场景下仅一个 enabled。
        mode_id = next(
            (
                mid
                for mid in ("daily_anomaly_hunter", "daily_anomaly")
                if mid in enabled
            ),
            None,
        )
        if mode_id is None:
            return None, None  # 无启用玩法 → 未选择副本
        if mode_id == "daily_anomaly_hunter":
            # 追猎目标：boss 名存于 routine 文件 daily_anomaly_hunter 段。
            # 该段/字段可能尚未落盘（用户在 NTE 自身 UI 启用追猎但未选 boss，
            # 不经本工具 set_dungeon 写入）：段或字段缺失按「已识别模式、未选 boss」
            # 处理为 None，而非断言——与读路径「容忍未配置」一致；结构性损坏（段
            # 类型非 dict）已在下方 isinstance 断言覆盖。
            section = routine.get("daily_anomaly_hunter", {})
            assert isinstance(section, dict), (
                f"[set_config][{self.display_name}] daily_anomaly_hunter 段必须是 dict"
            )
            boss = section.get("追猎目标")
            return "追猎目标", boss if boss not in (None, "") else None
        # 异象界域：副本名+序号存于 config 文件 daily_anomaly 段。
        config = self._load(allow_missing=True)
        if config is None:
            return None, None  # 脚本未安装/未配置
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] DailyTask config.yaml 必须是 dict"
        )
        # daily_anomaly 段缺失按「未选副本」处理（读路径容忍未配置；段类型非 dict
        # 的结构性损坏由下方 isinstance 断言覆盖，字段级缺失不视为损坏）。
        section = config.get("daily_anomaly", {})
        assert isinstance(section, dict), (
            f"[set_config][{self.display_name}] daily_anomaly 段必须是 dict"
        )
        dungeon = section.get("任务类型")  # 段缺失时为 None（未选副本）
        if dungeon in (None, ""):  # 值为空串同样视为未选具体副本
            return None, None
        key = self._anomaly_seq_key_map.get(dungeon)
        sequence = section.get(key) if key else None
        return dungeon, sequence


# ---- 明日方舟 Arknights（粥）----
@register
class ArknightsConfig(ScriptConfig):
    _script_name = "MAA"
    display_name = "粥"
    _config_rel_path = "config/gui.new.json"
    _game_config_rel_path = "config/gui.new.json"
    _game_path_keys = (
        "Configurations",
        "Default",
        "Gui",
        "StartUpSettings",
        "EmulatorPath",
    )
    _weekly_task_name = "理智药剂"
    # 关卡代码 → 中文名。基于 StagePlan[0] 识别任务，不再依赖 TaskQueue 顺序。
    # 只维护这5个关卡，其余 FightTask 不动。
    _task_map = {
        "Annihilation": "剿灭",
        "AP-5": "红票",
        "LS-6": "经验",
        "CE-6": "龙门币",
        "1-7": "土",
    }

    def _update_task(
        self, config: dict, dungeon_name: str, sequence: str | int | None = None
    ) -> bool:
        """粥副本设置：基于 StagePlan[0] 识别任务，启用剿灭/土/选定副本。

        只处理 _task_map 中的5个关卡，其余 FightTask 不动。

        Args:
            config: 目标 config dict。
            dungeon_name: 选定副本中文名。

        Returns:
            是否有任意任务项状态发生变化。

        Raises:
            AssertionError: 未适配的副本，或 StagePlan 格式不匹配。
        """
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        # 反查：中文名 → 关卡代码
        stage_by_name = {name: stage for stage, name in self._task_map.items()}
        assert dungeon_name in stage_by_name, (
            f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        )

        fixed_names = {"剿灭", "土"}
        changed = False
        for task in task_config:
            if task.get("$type") != "FightTask":
                continue
            stage_plan = task.get("StagePlan")
            if not isinstance(stage_plan, list) or len(stage_plan) != 1:
                continue
            stage = stage_plan[0]
            if stage not in self._task_map:
                continue  # 未维护的关卡，不动
            name = self._task_map[stage]

            should_enable = name in fixed_names or name == dungeon_name
            changed |= safe_update(
                task,
                "IsEnable",
                should_enable,
                f"{self.display_name}[{name}]",
            )

        return changed

    def _read_dungeon(self) -> tuple[str | None, str | int | None]:
        """反读当前日常副本（与 _update_task 对称）。

        遍历 TaskQueue，除固定启用的剿灭/土外，
        被勾选 IsEnable 的那一项即当前副本。
        特殊：若所有维护关卡都未启用，但有 StagePlan=["1-7"] 的任务，则读为「土」。

        Returns:
            (副本中文名, None)；未设置返回 (None, None)。
        """
        config = self._load(allow_missing=True)
        if config is None:
            return None, None  # 脚本未安装/未配置
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        fixed_names = {"剿灭", "土"}
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
            if stage not in self._task_map:
                continue
            name = self._task_map[stage]
            if name in fixed_names:
                continue
            if task.get("IsEnable"):
                return name, None
        # 所有维护关卡都未启用，但有1-7 → 读为土
        if has_1_7:
            return "土", None
        return None, None

    def set_weekly(self, start_day: int) -> None:
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
        if not self._enabled:
            logger.info(f"[set_weekly][{self.display_name}] 用户拒绝更新，跳过周常设置")
            return
        assert self._weekly_task_name, (
            f"[set_config][{self.display_name}] 未支持周常配置"
        )
        assert 1 <= start_day <= 7, (
            f"[set_config][{self.display_name}] 非法周常起始日: {start_day}（应为 1~7）"
        )
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
        if changed:
            logger.info(f"[set_weekly][{self.display_name}] 理智药剂配置已更新")
            self._save(config)
        else:
            logger.info(f"[set_weekly][{self.display_name}] 理智药剂配置无需更新")

    def set_weekly_start_day(self, start_day: int) -> None:
        """编辑期落盘周几起字面起始日到 MedicineExpireDays。

        与 set_weekly 不同：本方法只写 MedicineExpireDays（由周几起推算：
        MedicineExpireDays = 8 - 周几起），不写 UseExpiringMedicine（是否吃药的
        开关依赖各 FightTask 的启用状态，需运行期按当日副本选型经 set_weekly 计算）。
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
    dungeon_name: str | None = None,
    sequence: str | int | None = None,
    weekly_start: int | None = None,
) -> None:
    """适配器接口：设置副本 / 序列 / 周常起始日。

    未选副本且无周常，或脚本未适配（自定义脚本）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        dungeon_name: 副本中文名；None 或「未选择」表示不设置副本。
        sequence: 序列值；仅部分脚本支持。
        weekly_start: 周常起始日（1~7）；None 表示不设置周常。
    """
    if (not dungeon_name or dungeon_name == "未选择") and weekly_start is None:
        return

    # 自定义脚本（不在注册表）跳过
    if script_name not in _CONFIGS:
        logger.info(f"[set_config] 进程 {script_name} 无副本适配（自定义脚本），跳过")
        return

    cfg_cls = _CONFIGS[script_name]
    cfg = cfg_cls()
    if dungeon_name and dungeon_name != "未选择":
        cfg.set_dungeon(dungeon_name, sequence)
    if weekly_start is not None:
        cfg.set_weekly(weekly_start)


def get_dungeon_lists(
    script_name: str, task_name: str, source: str
) -> list[str] | None:
    """适配器接口：副本清单源在游戏脚本自身配置里，从中读某任务的可选副本名清单，委托给对应脚本的 config 类。

    「从哪读、怎么解析」的知识归各 ``ScriptConfig`` 子类，本函数只做分发。

    Args:
        script_name: 脚本唯一标识（如 ``March7th-Assistant``）。
        task_name: 任务名（周常/日常均可，如「历战余响」）。
        source: 来源标记，即 weekly_list.yml 的 ``dungeons_source``。

    Returns:
        副本名列表（含「无」等占位）；不可用时返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name].get_dungeon_lists(task_name, source)


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


def set_weekly_dungeon(script_name: str, weekly_name: str, dungeon_name: str) -> None:
    """适配器接口：写某周常当前选中的副本名到脚本自身 config。

    未适配或该脚本无「周常选副本」概念（子类未实现）时优雅跳过。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常名（如「历战余响」）。
        dungeon_name: 选中的副本名。
    """
    if script_name not in _CONFIGS:
        return
    cfg_cls = _CONFIGS[script_name]
    if not hasattr(cfg_cls, "set_weekly_dungeon"):
        return
    cfg = cfg_cls()
    cfg.set_weekly_dungeon(weekly_name, dungeon_name)


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


def get_dungeon(script_name: str) -> str | None:
    """读当前日常副本中文名（反读子脚本 config）。

    无真相（如绝区零/崩铁日常无副本适配）或字段未设置时返回 None。

    Args:
        script_name: 脚本标识名。

    Returns:
        当前副本中文名；无真相/未设置返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name]()._read_dungeon()[0]


def get_sequence(script_name: str) -> str | int | None:
    """读当前二级序列值（反读子脚本 config）。

    无二级序列通道（如原神/终末地序列即副本名、绝区零/崩铁日常无适配）时返回 None。

    Args:
        script_name: 脚本标识名。

    Returns:
        当前序列值；无通道/未设置返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name]()._read_dungeon()[1]


def get_weekly_dungeon(script_name: str, weekly_name: str) -> str | None:
    """读某周常当前选中的副本名（反读子脚本 config）。

    未适配周常副本（无 set_weekly_dungeon）或字段未设置时返回 None。

    Args:
        script_name: 脚本标识名。
        weekly_name: 周常名（如「历战余响」）。

    Returns:
        当前选中的副本名；无真相/未设置返回 None。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name]()._read_weekly_dungeon(weekly_name)
