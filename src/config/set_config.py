"""副本配置适配器（外观模式）：统一 set_config 接口，按各脚本格式封装 config 读写。"""

import logging
import os
from collections.abc import Callable
from typing import Any

from src.config.subscript import (
    _get_script_root_dir_soft,
    load_config,
    load_game_config,
    load_template,
    resolve_script_path,
    save_config,
)
from src.config.subscript import (
    download_file as _download_file,
)
from src.config.subscript import (
    get_config_path as _get_config_path_impl,
)
from src.utils_weekly import is_weekly_start_reached

logger = logging.getLogger(__name__)


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
        value: 目标值，类型须与现字段严格一致（type() 比较，避免 bool/int 混淆）。
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

    assert type(config[key]) is type(value), (
        f"[set_config][{display_name}] 类型不一致: key={key}, "
        f"config={type(config[key]).__name__}, value={type(value).__name__}"
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

    bg_img: str = ""
    """启动器背景图相对脚本根目录路径；空字符串走渐变占位。"""

    bilibili: str = ""
    """官方 B 站 UID；空字符串走通用占位。"""

    github: str = ""
    """脚本 GitHub repo 路径（不含域名）；空字符串走通用占位。"""

    homepage: str = ""
    """官方主页链接；空字符串走通用占位。"""

    _weekly_task_name: str = ""
    """周常任务标识名（非空即支持周常）；各脚本含义不同。"""

    _weekly_config_rel_path: str = ""
    """周常配置文件路径；空字符串复用主 config。"""

    confirm_before_save: Callable[[str], bool] | None = None
    """保存前确认回调（GUI 注入，返回 False 则不落盘）。"""

    enabled: bool = True
    """实例是否可操作 config；拒绝保存后置 False 使后续写入一并失效。"""

    def _load(self, rel_path: str | None = None) -> dict:
        """读取脚本 config 并校验为 dict。

        Args:
            rel_path: 相对脚本根目录的路径；缺省用 _config_rel_path。

        Returns:
            解析后的 config dict。

        Raises:
            AssertionError: 解析结果非 dict。
        """
        rel_path = rel_path or self._config_rel_path
        config = load_config(self._script_name, rel_path)
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
        if not self.enabled:
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
        if not self.enabled:
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

    def _update_task(self, config: dict, dungeon_name: str) -> bool:
        """写入副本类型字段，返回是否修改。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名；_task_map 为空时直接作为字段值。

        Returns:
            字段是否发生实际修改。

        Raises:
            AssertionError: 子类未声明 _task_key，或 dungeon_name 不在 _task_map。
        """
        assert self._task_key, f"[set_config][{self.display_name}] 子类必须设 _task_key"
        if self._task_map:
            task = get_field(
                self._task_map, dungeon_name, self.display_name, context="update_task"
            )
        else:
            task = dungeon_name
        return safe_update(config, self._task_key, task, self.display_name)

    def _update_sequence(
        self, config: dict, dungeon_name: str, sequence: str | int | None
    ) -> bool:
        """写入序列字段，返回是否修改。基类默认不启用。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名。
            sequence: 序列值；基类默认必须为 None。

        Returns:
            字段是否发生实际修改。

        Raises:
            AssertionError: 子类未适配却传入 sequence。
        """
        assert sequence is None, (
            f"[set_config][{self.display_name}] 不支持 sequence 参数"
        )
        return False

    def _confirm_save(self) -> bool:
        """保存前确认，返回是否允许落盘。

        未注入回调默认放行；拒绝后置 enabled=False 使后续写入一并失效。

        Returns:
            用户是否接受保存。
        """
        callback = type(self).confirm_before_save
        if callback is None:
            return True
        accepted = callback(self.display_name)
        if not accepted:
            self.enabled = False
        return accepted

    def _init_config(self) -> None:
        """对齐检查并合并模板字段到 config。

        已对齐或未确认（enabled=False）时不动 config。
        """
        config = self._load()
        template = self._load_template()

        if self._is_aligned(config, template):
            logger.info(f"[init_config][{self.display_name}] config 已对齐，无需更新")
            return

        if not self._confirm_save():
            logger.info(f"[init_config][{self.display_name}] 用户拒绝更新，跳过")
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
        if not self.enabled:
            logger.info(
                f"[set_dungeon][{self.display_name}] 用户拒绝更新，跳过副本设置"
            )
            return
        config = self._load()
        task_changed = self._update_task(config, dungeon_name)
        seq_changed = self._update_sequence(config, dungeon_name, sequence)
        changed = task_changed or seq_changed
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
        if not self.enabled:
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
    def get_game_bg_img(cls, script_name: str) -> str:
        """读取背景图绝对路径（类方法，无需实例化）。

        Args:
            script_name: 脚本标识名。

        Returns:
            背景图绝对路径；未声明或文件缺失时返回空字符串（渐变占位）。
        """
        if not cls.bg_img:
            return ""
        script_root = _get_script_root_dir_soft(script_name)
        if not script_root:
            return ""
        bg_path = os.path.join(script_root, cls.bg_img)
        if not os.path.isfile(bg_path):
            return ""
        return bg_path

    @classmethod
    def get_game_bilibili(cls, script_name: str) -> str:
        """读 B 站空间链接（子类存 UID，本方法拼 URL）；未声明 → 空字符串。"""
        return f"https://space.bilibili.com/{cls.bilibili}" if cls.bilibili else ""

    @classmethod
    def get_game_github(cls, script_name: str) -> str:
        """读 GitHub 链接（子类存 repo 路径，本方法拼 URL）；未声明 → 空字符串。"""
        return f"https://github.com/{cls.github}" if cls.github else ""

    @classmethod
    def get_game_homepage(cls, script_name: str) -> str:
        """读官方主页链接；未声明 → 空字符串。"""
        return cls.homepage


# ============================================================
# 注册表
# ============================================================

# 由 register() 装饰器显式填充（必须在子类定义前初始化）。
_CONFIGS: dict[str, type[ScriptConfig]] = {}


def register(cls: type[ScriptConfig]) -> type[ScriptConfig]:
    """注册子类到 _CONFIGS，并校验必要声明。

    Args:
        cls: 待注册的 ScriptConfig 子类。

    Returns:
        原样返回 cls（便于装饰器使用）。

    Raises:
        AssertionError: 缺少 _script_name/_config_rel_path，或声明了
            _game_path_keys/_weekly_task_name 但未补全对应声明/实现。
    """
    assert cls._script_name, f"[set_config][{cls.__name__}] 必须声明 _script_name"
    assert cls._config_rel_path, (
        f"[set_config][{cls.__name__}] 必须声明 _config_rel_path"
    )
    if cls._game_path_keys:
        assert cls._game_config_rel_path, (
            f"[set_config][{cls.__name__}] 声明了 _game_path_keys 必须声明 "
            f"_game_config_rel_path"
        )
    if cls._weekly_task_name:
        assert cls._write_weekly is not ScriptConfig._write_weekly, (
            f"[set_config][{cls.__name__}] 声明了 _weekly_task_name 必须实现 "
            f"_write_weekly"
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
    bilibili = "1955897084"
    github = "ok-oldking/ok-wuthering-waves"
    homepage = "https://mc.kurogames.com/"
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

    def _update_sequence(
        self, config: dict, dungeon_name: str, sequence: str | int | None
    ) -> bool:
        """按副本映射写入二级序列字段，返回是否修改。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名（决定映射键与取值方式）。
            sequence: 序列值；无二级映射时直接作为字段值。

        Returns:
            字段是否发生实际修改。

        Raises:
            AssertionError: 未适配的副本或序列。
        """
        assert sequence is not None, (
            f"[set_dungeon][{self.display_name}] sequence 不能为空"
        )

        sequence_map = {
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

        assert dungeon_name in sequence_map, (
            f"[set_dungeon][{self.display_name}] 未适配的副本: {dungeon_name}"
        )
        cfg = sequence_map[dungeon_name]

        if cfg["values"] is not None:
            assert sequence in cfg["values"], (
                f"[set_dungeon][{self.display_name}] 未适配的序列: {sequence}"
            )
            target = cfg["values"][sequence]
        else:
            target = sequence

        return safe_update(config, cfg["key"], target, self.display_name)


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
    bilibili = "401742377"
    github = "babalae/better-genshin-impact"
    homepage = "https://ys.mihoyo.com/"
    banner_url = (
        "https://cdn.jsdelivr.net/gh/babalae/better-genshin-impact@0.63.0/"
        "BetterGenshinImpact/Resources/Images/banner.jpg"
    )
    """BetterGI 官方仓库 banner（与 BetterGI.exe 内嵌主界面横幅同一张）。"""

    def __init__(self):
        self._init_config()

    @classmethod
    def get_game_bg_img(cls, script_name: str) -> str:
        """读取原神背景图：优先项目 assets/banner.jpg，缺失则从官方仓库下载。

        Args:
            script_name: 脚本标识名。

        Returns:
            背景图绝对路径；下载失败返回空字符串（渐变占位）。
        """
        assets_file = resolve_script_path("assets/banner.jpg")
        if not os.path.isfile(assets_file):
            if not _download_file(cls.banner_url, assets_file):
                return ""
        return assets_file

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """原神副本两级组织：有二级时写入二级副本名，否则回退一级。

        Args:
            dungeon_name: 一级副本名。
            sequence: 二级副本名；None 时回退一级。
        """
        target = sequence if sequence is not None else dungeon_name
        super().set_dungeon(target)


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
    bilibili = "1265652806"
    github = "AliceJump/ok-end-field"
    homepage = "https://endfield.hypergryph.com/"

    def __init__(self):
        self._init_config()

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """终末地副本两级组织：有二级时写入二级副本名，否则回退一级。

        Args:
            dungeon_name: 一级副本名。
            sequence: 二级副本名；None 时回退一级。
        """
        target = sequence if sequence is not None else dungeon_name
        super().set_dungeon(target)


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
    bg_img = "assets/ui/static_background.webp"
    bilibili = "1636034895"
    github = "DoctorReid/ZenlessZoneZero-OneDragon"
    homepage = "https://zzz.mihoyo.com/"
    _weekly_task_name = "lost_void"

    def __init__(self):
        self._init_config()

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
    _task_key = "instance_type"
    _config_rel_path = "config.yaml"
    _game_config_rel_path = "config.yaml"
    _template_rel_path = "M7A一条龙.yml"
    _game_path_keys = ("game_path",)
    bg_img = "assets/app/images/bg37.jpg"
    bilibili = "1340190821"
    github = "moesnow/March7thAssistant"
    homepage = "https://sr.mihoyo.com/"
    _weekly_task_name = "currencywars_enable"

    def __init__(self):
        self._init_config()

    def _write_weekly(self, enabled: bool) -> None:
        """控制 config.yaml 的 currencywars_enable 周常开关。

        Args:
            enabled: 是否启用周常。
        """
        config = self._load()
        # 周常（货币战争）在 config.yaml 中的开关_weekly_task_name。
        safe_update(config, self._weekly_task_name, enabled, self.display_name)
        self._save(config)


# ---- 异环 Neverness to Everness (NTE) ----
@register
class NTEConfig(ScriptConfig):
    _script_name = "ok-nte"
    _config_rel_path = "data/apps/ok-nte/working/configs/DailyRoutineTaskConfigs.json"
    _routine_config_rel_path = "data/apps/ok-nte/working/configs/DailyRoutineTask.json"
    _game_config_rel_path = "data/apps/ok-nte/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    display_name = "异环"
    bilibili = "3546636978489848"
    github = "BnanZ0/ok-nte"
    homepage = "https://yh.wanmei.com/"
    _exclusive_routine_items = ("daily_anomaly", "daily_anomaly_hunter")
    """互斥的两个日常 routine item id（DailyRoutineTask.json）。"""

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

    def _daily_section_dict(self, config: dict) -> dict:
        """取当前绑定的日常任务配置子对象。

        Args:
            config: 顶层 config dict。

        Returns:
            日常任务配置子 dict。

        Raises:
            AssertionError: 缺段或类型非 dict。
        """
        return get_field(
            config, self._daily_section, self.display_name, dict, "daily_section"
        )

    def _update_task(self, config: dict, dungeon_name: str) -> bool:
        """写入任务类型字段（值=中文副本名）。

        追猎目标无任务类型通道，直接跳过。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名。

        Returns:
            是否发生实际修改。

        Raises:
            AssertionError: 段/通道绑定不一致（如追猎目标却设了任务类型）。
        """
        if dungeon_name == "追猎目标":
            assert not self._task_key, (
                f"[set_config][{self.display_name}] 追猎目标不应绑定任务类型通道"
            )
            return False
        assert self._task_key, (
            f"[set_config][{self.display_name}] 异象界域必须绑定任务类型通道"
        )
        return safe_update(
            self._daily_section_dict(config),
            self._task_key,
            dungeon_name,
            self.display_name,
        )

    def _update_sequence(self, config, dungeon_name, sequence) -> bool:
        """按副本映射写入序号字段，返回是否修改。

        Args:
            config: 目标 config dict。
            dungeon_name: 副本中文名（决定 _seq_key_map 的键）。
            sequence: 序号值。

        Returns:
            字段是否发生实际修改。

        Raises:
            AssertionError: sequence 为空或副本无对应序号键。
        """
        assert sequence is not None, f"[set_config][{self.display_name}] 序列不能为空"
        key = get_field(
            self._seq_key_map,
            dungeon_name,
            self.display_name,
            context="update_sequence",
        )
        return safe_update(
            self._daily_section_dict(config), key, sequence, self.display_name
        )

    def _bind_section(self, dungeon_name: str) -> None:
        """按所选副本切换日常配置段与字段映射。

        追猎目标绑定 daily_anomaly_hunter 且仅走序列通道；
        其余副本绑定 daily_anomaly 并启用任务类型通道。

        Args:
            dungeon_name: 副本中文名。
        """
        if dungeon_name == "追猎目标":
            self._daily_section = "daily_anomaly_hunter"
            self._seq_key_map = {"追猎目标": "追猎目标"}
            self._task_key = None  # 追猎目标走序列通道，无任务类型字段
        else:
            self._daily_section = "daily_anomaly"
            self._seq_key_map = {
                "异能升级材料": "异能材料序号",
                "空幕": "空幕序号",
                "弧盘突破材料": "弧盘材料序号",
            }
            self._task_key = "任务类型"

    def _update_routine_exclusion(self, routine: dict) -> bool:
        """互斥切换追猎目标与异象界域的 Routine Item 启用状态。

        Args:
            routine: DailyRoutineTask.json 的 dict。

        Returns:
            启用状态是否发生实际修改。

        Raises:
            AssertionError: Routine Items 缺少当前所选玩法段。
        """
        items = get_field(routine, "Routine Items", self.display_name, list)
        ids = {item["id"] for item in items}
        assert self._daily_section in ids, (
            f"[set_config][{self.display_name}] Routine Items 缺少 {self._daily_section}（无法启用所选玩法）"
        )
        changed = False
        for item in items:
            task_id = item["id"]
            if task_id not in self._exclusive_routine_items:
                continue
            changed |= safe_update(
                item, "enabled", task_id == self._daily_section, self.display_name
            )
        return changed

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """绑定段与字段后委托基类写配置，再切换第二份文件的互斥启用状态。

        Args:
            dungeon_name: 副本中文名。
            sequence: 序列值。
        """
        self._bind_section(dungeon_name)
        super().set_dungeon(dungeon_name, sequence)
        if self.enabled:
            routine = self._load(self._routine_config_rel_path)
            if self._update_routine_exclusion(routine):
                self._save(routine, self._routine_config_rel_path)


# ---- 明日方舟 Arknights（粥）----
@register
class ArknightsConfig(ScriptConfig):
    _script_name = "MAA"
    display_name = "粥"
    _config_rel_path = "config/gui.new.json"
    _game_config_rel_path = "config/gui.new.json"
    _template_rel_path = "MAA一条龙.json"
    bilibili = "161775300"
    github = "MaaAssistantArknights/MaaAssistantArknights"
    homepage = "https://ak.hypergryph.com/"
    _game_path_keys = (
        "Configurations",
        "Default",
        "Gui",
        "StartUpSettings",
        "EmulatorPath",
    )

    def __init__(self):
        self._init_task_map()
        self._init_config()

    def _init_task_map(self):
        """从模板 TaskQueue 提取 FightTask，构建 副本名 → {index, stage} 映射。"""
        template = self._load_template()
        task_config = template["Configurations"]["Default"]["TaskQueue"]
        self._task_map = {}
        for index, task in enumerate(task_config):
            if task.get("$type") == "FightTask":
                name = task.get("Name", "")
                if name:
                    stage = (
                        None
                        if "StagePlan" not in task or len(task["StagePlan"]) == 0
                        else task["StagePlan"][0]
                    )
                    self._task_map[name] = {"index": index, "stage": stage}

    def _update_task(self, config: dict, dungeon_name: str) -> bool:
        """粥副本设置：禁用全部后启用剿灭/土/活动土/选定副本。

        Args:
            config: 目标 config dict。
            dungeon_name: 选定副本中文名。

        Returns:
            是否有任意任务项状态发生变化。

        Raises:
            AssertionError: 未适配的副本，或 TaskQueue 索引/名称/关卡不匹配。
        """
        task_config = config["Configurations"]["Default"]["TaskQueue"]
        assert dungeon_name in self._task_map, (
            f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        )

        changed = False
        for name, info in self._task_map.items():
            idx = info["index"]
            assert task_config[idx]["Name"] == name, (
                f"[set_config][{self.display_name}] TaskQueue[{idx}] Name 不匹配: 期望 {name}, 实际 {task_config[idx]['Name']}"
            )
            stage = info["stage"]
            if stage is not None:
                assert task_config[idx]["StagePlan"] == [stage], (
                    f"[set_config][{self.display_name}] TaskQueue[{idx}] StagePlan 不匹配: 期望 {[stage]}, 实际 {task_config[idx]['StagePlan']}"
                )

            should_enable = name in ["剿灭", "土", "活动土", dungeon_name]
            changed |= safe_update(
                task_config[idx],
                "IsEnable",
                should_enable,
                f"{self.display_name}[TaskQueue[{idx}]]",
            )

        return changed


# ============================================================
# 外观接口
# ============================================================


def set_config(
    script_name: str,
    dungeon_name: str | None = None,
    sequence: str | int | None = None,
    weekly_start: int | None = None,
) -> None:
    """外观接口：设置副本 / 序列 / 周常起始日。

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


def get_game_bg_img(script_name: str) -> str:
    """读背景图绝对路径（供 GUI 渲染）；未适配/缺失 → 空字符串。原神首次调用会下载。"""
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_bg_img(script_name)


def get_game_bilibili(script_name: str) -> str:
    """读 B 站链接（供 GUI 打开）；未适配/未声明 → 空字符串。"""
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_bilibili(script_name)


def get_game_github(script_name: str) -> str:
    """读 GitHub 链接（供 GUI 打开）；未适配/未声明 → 空字符串。"""
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_github(script_name)


def get_game_homepage(script_name: str) -> str:
    """读官网链接（供 GUI 打开）；未适配/未声明 → 空字符串。"""
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_homepage(script_name)


def is_adapted(script_name: str) -> bool:
    """查询脚本是否已注册副本适配（供 GUI 决定是否显示任务卡）。"""
    return script_name in _CONFIGS


def supports_weekly(script_name: str) -> bool:
    """查询脚本是否支持周常（供 GUI 控制周常行可选性）。"""
    if script_name not in _CONFIGS:
        return False
    return bool(_CONFIGS[script_name]._weekly_task_name)
