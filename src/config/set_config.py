"""
副本配置适配器（外观模式）
对外提供统一的 set_config 接口，内部封装各自动化脚本的 config 读写逻辑。

每个脚本的 config 格式、路径、字段名都不同，
各脚本子类单独适配，上层无需关心差异。
"""

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
    """
    安全更新单个字段，返回是否修改。
    检查类型一致性，用 type() 严格比较，避免 bool/int 混淆。

    Args:
        config: 配置字典
        key: 要更新的键
        value: 新值
        display_name: 脚本显示名称，用于日志
        assert_key_exists: 是否 assert key 存在；为 False 时允许添加新 key，此时会记录 warning 日志
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
    """取必填字段，缺字段或类型错误（指定 type 时）均 assert 暴露；context 标注所属操作。"""
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
    """内部标识：script_path basename 去后缀（如 ok-ww / BetterGI），全链路适配 key
    （_CONFIGS 注册表索引，外部代码不直接访问）"""
    display_name: str = ""
    """GUI 展示名（如 鸣潮），仅用于展示/日志"""
    _task_key: str = ""
    """config 中副本类型对应的字段名，设了即启用 _update_task"""
    _task_map: dict[str, Any] = {}
    """副本中文名 → config 值的映射，空 dict 表示直接用 dungeon_name"""

    _game_path_keys: tuple[str, ...] = ()
    """游戏 exe 路径在游戏配置（_game_config_rel_path 指向的文件）中的嵌套键路径。

    空元组表示该脚本未适配「打开游戏」。各子类按需声明，如 ``("pc_full_path",)``。
    """

    _config_rel_path: str = ""
    """config 文件相对脚本根目录的路径（必填，子类必须声明）。"""

    _game_config_rel_path: str = ""
    """游戏路径配置文件相对脚本根目录的路径（声明了 ``_game_path_keys`` 则必填）。"""

    _template_rel_path: str = ""
    """模板文件相对 config/ 目录的路径（走模板初始化的子类必须声明）。"""

    bg_img: str = ""
    """启动器背景图相对脚本根目录的路径（如 assets/ui/static_background.webp）。

    空字符串表示未配置，GUI 走渐变占位背景。由 GUI 通过 ``get_game_bg_img``
    只读获取，不实例化子类。
    """

    bilibili: str = ""
    """游戏官方 B 站空间 UID（如 1955897084，不含域名前缀）。

    空字符串表示未配置，GUI 走通用占位链接。由 GUI 通过 ``get_game_bilibili``
    只读获取（基类拼接完整 https://space.bilibili.com/<uid>），不实例化子类。
    """

    github: str = ""
    """游戏对应脚本项目的 GitHub repo 路径（如 ok-oldking/ok-wuthering-waves，不含域名前缀）。

    空字符串表示未配置，GUI 走通用占位链接。由 GUI 通过 ``get_game_github``
    只读获取（基类拼接完整 https://github.com/<repo>），不实例化子类。
    """

    homepage: str = ""
    """游戏官方主页链接（官网首页，区别于脚本项目 GitHub）。

    空字符串表示未配置，GUI 走通用占位链接。由 GUI 通过 ``get_game_homepage``
    只读获取，不实例化子类。
    """

    _weekly_task_name: str = ""
    """周常任务在脚本配置中的标识名（非空即表示该脚本支持周常「周几以后开始执行」）。

    各脚本含义不同（如崩铁 config 字段名 currencywars_enable、鸣潮 Additional
    Tasks 列表任务名 Check Weekly Garden、绝区零 _group.yml 的 app_id lost_void），
    但统一用本字段非空判定是否支持周常。GUI 通过 ``supports_weekly`` 只读查询，
    不实例化子类。
    """

    _weekly_config_rel_path: str = ""
    """周常配置文件相对脚本根目录的路径（如 ``config/01/one_dragon/_group.yml``）。

    空字符串表示周常配置与 ``_config_rel_path`` 同一文件（声明了 ``_weekly_task_name``
    的子类按需声明；缺省复用主 config 文件）。
    """

    confirm_before_save: Callable[[str], bool] | None = None
    """保存前确认回调（由 GUI 注入，参数为 display_name，返回 True 才落盘）。

    None 表示未注入（CLI/测试等无 GUI 环境），此时直接保存保持原行为。
    """

    enabled: bool = True
    """本次实例是否可操作 config。默认 True（每次新建实例即重置）。

    用户在 ``_confirm_save`` 中拒绝（回调返回 False）后置为 False，
    此时该实例「什么都不做」：``_save`` 统一检查该标记，使本次运行中后续
    ``set_dungeon`` 等写入一并失效，避免「刚拒绝更新、另一入口又改写同一
    config」的矛盾行为。
    """

    def _load(self, rel_path: str | None = None) -> dict:
        rel_path = rel_path or self._config_rel_path
        config = load_config(self._script_name, rel_path)
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        return config

    def _save(self, config: dict, rel_path: str | None = None) -> None:
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
        """保存后重新读取，确认落盘内容与预期一致（校验写盘确实生效）。"""
        reloaded = self._load(rel_path)
        assert reloaded == expected, (
            f"[set_config][{self.display_name}] 配置保存后校验失败："
            f"重新读取的内容与预期不一致"
        )

    def _load_weekly(self) -> dict:
        """加载周常配置文件（``_weekly_config_rel_path``，缺省复用主 config）。"""
        config = load_config(
            self._script_name, self._weekly_config_rel_path or self._config_rel_path
        )
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] 周常 config 必须是 dict"
        )
        return config

    def _save_weekly(self, config: dict) -> None:
        """保存周常配置文件并校验落盘（同主 config 的保存后校验语义）。"""
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
        """加载模板文件（相对 config/ 目录），支持 JSON 和 YAML 格式"""
        assert self._template_rel_path, (
            f"[set_config][{self.display_name}] 未声明 _template_rel_path"
        )
        return load_template(self._script_name, self._template_rel_path)

    def _update_task(self, config: dict, dungeon_name: str) -> bool:
        """
        更新副本类型字段。返回是否修改。
        子类设 _task_key 即启用，_task_map 为空时直接赋 dungeon_name。
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
        """更新序列字段。返回是否修改。默认不启用。"""
        assert sequence is None, (
            f"[set_config][{self.display_name}] 不支持 sequence 参数"
        )
        return False

    def _confirm_save(self) -> bool:
        """保存前询问用户确认；未注入回调时默认放行（保持 CLI/测试行为不变）。

        注意必须经 ``type(self).confirm_before_save`` 取类属性：若用 ``self.confirm_before_save``
        访问，普通函数会被描述符绑定成实例方法（多传 self），导致
        ``confirm_config_update(self, display_name)`` 的 TypeError。

        用户拒绝（回调返回 False）时置 ``enabled = False``，使本次实例后续所有
        ``_save`` 调用（含 ``set_dungeon``）一并失效。
        """
        callback = type(self).confirm_before_save
        if callback is None:
            return True
        accepted = callback(self.display_name)
        if not accepted:
            self.enabled = False
        return accepted

    def _init_config(self) -> None:
        """
        通用的 config 初始化逻辑：加载 config 和 template，检查对齐，合并更新。
        子类重写 _is_aligned 以实现特殊比较逻辑。

        先确认再改内存/落盘：用户拒绝或限时超时（enabled=False）→ 不添加字段、
        不落盘、不打「已更新」日志（未确认前不产生任何修改与更新日志）。
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
        """
        默认对齐检查：递归比较模板中的所有 key。
        对于 dict 递归检查，对于 list 按索引逐一比较，其余直接比较值。
        子类重写以实现特殊比较逻辑。
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
        """
        设置副本。默认流程：_update_task → _update_sequence → save。
        子类直接覆盖 set_dungeon 则完全自定义（如粥）。

        用户已拒绝（enabled=False）时直接短路：本实例「什么都不做」，
        连 _load/_update_task 等也不执行，仅记日志。
        """
        if not self.enabled:
            logger.info(
                f"[set_dungeon][{self.display_name}] 用户拒绝更新，跳过副本设置"
            )
            return
        config = self._load()
        changed = self._update_task(config, dungeon_name) or self._update_sequence(
            config, dungeon_name, sequence
        )
        if changed:
            logger.info(f"[set_dungeon][{self.display_name}] config 已更新")
            self._save(config)
        else:
            logger.info(f"[set_dungeon][{self.display_name}] config 无需更新")

    def set_weekly(self, start_day: int) -> None:
        """设置周常起始日（周几以后开始执行），今天周几 >= 起始日则启用周常。

        周常开关（enabled）是 GUI 内存态，不参与本方法；无论开关如何，
        都按 start_day 判断写入脚本配置（与日常副本选择落盘不受日常开关
        影响的模型一致）。子类声明 _weekly_task_name 并实现 _write_weekly(enabled)。

        用户已拒绝（enabled=False）时直接短路（同 ``set_dungeon``）。

        Args:
            start_day: 周常起始日（1=周一 ~ 7=周日）。
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
        """写周常开关到脚本配置（子类实现）。默认不支持，未声明 _weekly_task_name 的子类
        调用本方法属编程错误，直接 assert 暴露。

        仅由 ``set_weekly`` 内部调用，enabled 为「今天周几 >= 起始日」的判断结果；
        GUI 周常开关（enabled 内存态）不直写本方法。

        Args:
            enabled: True 表示启用周常，False 表示停用周常。
        """
        assert False, f"[set_config][{self.display_name}] 未支持周常配置"  # noqa: B011  # 故意：未适配脚本不应走到周常写入

    @classmethod
    def get_game_exe_path(cls, script_name: str) -> str | None:
        """
        读取脚本配置中的游戏可执行文件路径（类方法，不实例化，无写盘副作用）。

        - 未适配（``_game_path_keys`` 为空）→ None
        - 游戏配置缺失 / 字段缺失 / 值为空 → None
        - 成功 → 游戏 exe 路径字符串（可能是 .lnk 快捷方式）

        Args:
            script_name: 脚本唯一标识（exe 为进程名、python/bat 为 display_name），
                用于读对应脚本的游戏配置。
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
        """
        读取脚本配置中的启动器背景图绝对路径（类方法，不实例化）。

        背景图相对脚本根目录（script_path 父目录）声明，本方法完成
        相对 → 绝对解析并校验文件存在。以下情况返回空字符串（GUI 走渐变占位）：
        - 未声明（``bg_img`` 为空）
        - 脚本根目录取不到（config.yml 无此脚本 / script_path 为空）
        - 背景图文件不存在

        注意：个别子类覆盖本方法时会先尝试下载远程背景图（网络操作，
        见子类 docstring），此时并非纯只读。

        Args:
            script_name: 脚本唯一标识（exe 为进程名、python/bat 为 display_name）。
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
        """
        读取游戏官方 B 站空间链接（类方法，不实例化，无副作用）。

        子类 ``bilibili`` 只存 UID（如 ``1955897084``），本方法拼接完整
        ``https://space.bilibili.com/<uid>``。未声明（``bilibili`` 为空）→
        返回空字符串，GUI 走通用占位链接。

        Args:
            script_name: 脚本唯一标识（exe 为进程名、python/bat 为 display_name）。
        """
        return f"https://space.bilibili.com/{cls.bilibili}" if cls.bilibili else ""

    @classmethod
    def get_game_github(cls, script_name: str) -> str:
        """
        读取脚本项目的 GitHub 主页链接（类方法，不实例化，无副作用）。

        子类 ``github`` 只存 repo 路径（如 ``ok-oldking/ok-wuthering-waves``），
        本方法拼接完整 ``https://github.com/<repo>``。未声明（``github`` 为空）→
        返回空字符串，GUI 走通用占位链接。

        Args:
            script_name: 脚本唯一标识（exe 为进程名、python/bat 为 display_name）。
        """
        return f"https://github.com/{cls.github}" if cls.github else ""

    @classmethod
    def get_game_homepage(cls, script_name: str) -> str:
        """
        读取游戏官方主页链接（类方法，不实例化，无副作用）。

        未声明（``homepage`` 为空）→ 返回空字符串，GUI 走通用占位链接。

        Args:
            script_name: 脚本唯一标识（exe 为进程名、python/bat 为 display_name）。
        """
        return cls.homepage


# ============================================================
# 注册表
# ============================================================

# 由 register() 装饰器显式填充（必须在子类定义前初始化）。
_CONFIGS: dict[str, type[ScriptConfig]] = {}


def register(cls: type[ScriptConfig]) -> type[ScriptConfig]:
    """显式注册 ScriptConfig 子类到 ``_CONFIGS``（装饰器）。

    子类声明 ``_script_name`` 与路径类属性后加 ``@register`` 即完成登记。
    路径/周常声明不完整属编程错误，import 时立即 assert 暴露，
    避免新增脚本漏配后静默缺功能：
    - 缺 ``_config_rel_path``、或声明了 ``_game_path_keys`` 却缺 ``_game_config_rel_path``
    - 声明了 ``_weekly_task_name``（支持周常）却未实现 ``_write_weekly``
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
    bilibili = "1955897084"
    github = "ok-oldking/ok-wuthering-waves"
    homepage = "https://mc.kurogames.com/"
    _weekly_task_name = "Check Weekly Garden"
    """周常（每周花园）在 Additional Tasks 列表中的任务名。"""

    def __init__(self):
        self.display_name = "鸣潮"
        self._task_key = "Which to Farm"
        self._task_map = {
            "凝素领域": "Forgery Challenge",
            "模拟领域": "Simulation Challenge",
            "无音区": "Tacet Suppression",
        }

    def _write_weekly(self, enabled: bool) -> None:
        """鸣潮周常开关：控制 Additional Tasks 列表中「Check Weekly Garden」的增删。

        启用 → 任务名加入 ``Additional Tasks to Run After Daily Task`` 列表；
        停用 → 从列表中移除。列表本身缺失属配置错误，assert 暴露。
        """
        config = self._load()
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
        self.display_name = "原神"
        self._task_key = "DomainName"
        self._init_config()

    @classmethod
    def get_game_bg_img(cls, script_name: str) -> str:
        """原神背景：项目 assets/banner.jpg（无则从官方仓库下载）。

        原始图 = 项目根 assets/banner.jpg（官方仓库 banner，与 exe 内嵌
        主界面横幅同一张，2538x1157 超宽，由 GUI cover 裁剪显示）。
        assets 无原始图 → 从 jsDelivr 官方仓库下载；下载失败 → 空（渐变占位）。
        仅在脚本已注册（_CONFIGS 含 BetterGI，模块级接口已兜底）时被调用。

        Args:
            script_name: 脚本唯一标识（exe 为进程名、python/bat 为 display_name）。
        """
        assets_file = resolve_script_path("assets/banner.jpg")
        if not os.path.isfile(assets_file):
            if not _download_file(cls.banner_url, assets_file):
                return ""
        return assets_file

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """设置原神副本：副本按「目录 → 副本」两级组织，实际写入的是二级副本名。

        dungeon_list.yml 中一级为类型目录，二级才是具体副本名。
        DomainName 字段存副本名；无二级时（兼容旧单层配置）回退写一级名。
        """
        target = sequence if sequence is not None else dungeon_name
        super().set_dungeon(target)


# ---- 终末地 Arknights: Endfield ----
@register
class EndfieldConfig(ScriptConfig):
    _script_name = "ok-ef"
    _config_rel_path = "data/apps/ok-ef/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ef/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)
    bilibili = "1265652806"
    github = "AliceJump/ok-end-field"
    homepage = "https://endfield.hypergryph.com/"

    def __init__(self):
        self.display_name = "终末地"
        self._task_key = "体力本"
        self._init_config()

    def _init_config(self):
        # TODO: 确认包含了绳索等配置
        pass

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None) -> None:
        """设置终末地副本：副本按「类型 → 副本」两级组织（假一级目录），实际写入的是二级副本名。

        dungeon_list.yml 中一级为类型目录，二级才是具体副本名。
        体力本 字段存副本名；无二级时（兼容旧单层配置）回退写一级名。
        """
        target = sequence if sequence is not None else dungeon_name
        super().set_dungeon(target)


# ---- 绝区零 Zenless Zone Zero ----
@register
class ZenlessZoneZeroConfig(ScriptConfig):
    _script_name = "OneDragon-Launcher"
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
    """周常（遗失的虚空）在 _group.yml app_list 中的 app_id。"""

    def __init__(self):
        self.display_name = "绝区零"
        self._init_config()

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None):
        logger.info(f"[set_config][{self.display_name}] zzz无需适配")

    def _write_weekly(self, enabled: bool) -> None:
        """绝区零周常开关：控制 _group.yml 中 lost_void 应用的 enabled。

        在 app_list 中按 ``_weekly_task_name`` 定位条目并更新 enabled；
        条目缺失属配置错误，assert 暴露。
        """
        config = self._load_weekly()
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
    _config_rel_path = "config.yaml"
    _game_config_rel_path = "config.yaml"
    _template_rel_path = "M7A一条龙.yml"
    _game_path_keys = ("game_path",)
    bg_img = "assets/app/images/bg37.jpg"
    bilibili = "1340190821"
    github = "moesnow/March7thAssistant"
    homepage = "https://sr.mihoyo.com/"
    _weekly_task_name = "currencywars_enable"
    """周常（货币战争）在 config.yaml 中的开关字段名。"""

    def __init__(self):
        self.display_name = "崩铁"
        self._task_key = "instance_type"
        self._init_config()

    def _write_weekly(self, enabled: bool) -> None:
        """崩铁周常开关：控制 config.yaml 的 currencywars_enable 字段。"""
        config = self._load()
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
    bilibili = "3546636978489848"
    github = "BnanZ0/ok-nte"
    homepage = "https://yh.wanmei.com/"
    _daily_section = "daily_anomaly"
    """日常任务配置顶层子对象名（由 _bind_section 按副本切换）。"""
    _exclusive_routine_items = ("daily_anomaly", "daily_anomaly_hunter")
    """互斥的两个日常 routine item id（DailyRoutineTask.json）。"""

    _launcher_rel_path = "NTELauncher.exe"
    """异环启动器文件名（相对游戏安装根目录，非游戏本体）。"""

    def __init__(self):
        self.display_name = "异环"
        # 动态字段由 _bind_section 绑定

    @classmethod
    def get_game_exe_path(cls, script_name: str) -> str | None:
        """异环重写：从游戏本体路径向上查找启动器，找不到返回 None。"""
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
        """取日常任务配置子对象；缺段或类型错误均 assert 暴露。"""
        return get_field(
            config, self._daily_section, self.display_name, dict, "daily_section"
        )

    def _update_task(self, config: dict, dungeon_name: str) -> bool:
        """写任务类型字段（值=中文副本名）；追猎目标无此字段，跳过。"""
        if dungeon_name == "追猎目标":
            return False
        return safe_update(
            self._daily_section_dict(config),
            self._task_key,
            dungeon_name,
            self.display_name,
        )

    def _update_sequence(self, config, dungeon_name, sequence) -> bool:
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
        """按所选副本切换日常配置段与字段映射。"""
        if dungeon_name == "追猎目标":
            self._daily_section = "daily_anomaly_hunter"
            self._seq_key_map = {"追猎目标": "追猎目标"}
        else:
            self._daily_section = "daily_anomaly"
            self._seq_key_map = {
                "异能升级材料": "异能材料序号",
                "空幕": "空幕序号",
                "弧盘突破材料": "弧盘材料序号",
            }
            self._task_key = "任务类型"

    def _update_routine_exclusion(self, routine: dict) -> bool:
        """追猎目标与异象界域互斥：启用所选、停用另一，返回是否修改。"""
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
        """动态绑定段与字段后委托基类写配置，再切换第二份文件的互斥启用状态。"""
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
        self.display_name = "粥"
        self._init_task_map()
        self._init_config()

    def _init_task_map(self):
        """
        self._task_map = {
            "剿灭":   {"index": 1, "stage": "Annihilation"},
            "红票":   {"index": 2, "stage": "AP-5"},
            "经验":   {"index": 3, "stage": "LS-6"},
            "龙门币": {"index": 4, "stage": "CE-6"},
            "活动土": {"index": 5, "stage": None},
            "土":     {"index": 6, "stage": "1-7"},
        }
        """
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
        """
        粥的副本设置逻辑：禁用所有副本 → 启用剿灭任务（周常） → 启用选定副本 → 启用刷土清理剩余体力。
        只有状态变化时返回 True。
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
            logger.info(
                f"[set_config][{self.display_name}] task_config[{idx}] {task_config[idx]}"
            )
            changed |= safe_update(
                task_config[idx],
                "IsEnable",
                should_enable,
                f"{self.display_name}[TaskQueue[{idx}]]",
            )

        return changed


# ============================================================
# 注册表
# ============================================================
# 见基类上方定义：由 register() 装饰器显式填充，
# 新增脚本只需声明子类（_script_name + 路径类属性）并加 @register。


# ============================================================
# 外观接口
# ============================================================


def set_config(
    script_name: str,
    dungeon_name: str | None = None,
    sequence: str | int | None = None,
    weekly_start: int | None = None,
) -> None:
    """
    外观接口：为指定脚本设置副本、刷取序列与周常起始日

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）
        dungeon_name: 副本名称（来自 dungeon_list.yml），None 或 "未选择" 时跳过副本
        sequence: 刷取序列（字符串或整数），None 表示无序列
        weekly_start: 周常起始日（1=周一 ~ 7=周日），None 表示不处理周常。
            无论 GUI 周常开关（enabled，纯内存 UI 态）如何，都按
            「今天周几 >= 起始日」判断启用/停用写入脚本配置——与日常副本
            选择落盘不受日常开关影响的模型一致。
    """
    # 未选择副本且未指定周常时，不做更改
    if (not dungeon_name or dungeon_name == "未选择") and weekly_start is None:
        return

    # 自定义脚本（用户在 GUI 中新增）没有副本适配，不在注册表中，直接跳过。
    # 这类脚本本就没有副本选项，正常不会带 dungeon_name 走到这里；即便带了也优雅跳过。
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
    """
    外观接口：按脚本唯一标识取脚本 config 绝对路径（供 GUI「打开配置文件」用）。

    未适配脚本 → AssertionError（消息与 subscript 原语义一致，供上层捕获提示）。
    路径（``_config_rel_path``）由对应子类声明，本函数只做分发。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    assert script_name in _CONFIGS, f"[set_config] 未适配脚本: {script_name}"
    return _get_config_path_impl(script_name, _CONFIGS[script_name]._config_rel_path)


def get_game_exe_path(script_name: str) -> str | None:
    """
    外观接口：读取指定脚本对应的游戏可执行文件路径（供 GUI「打开游戏」用）。

    只读查询，不实例化子类（避免 __init__ 触发的 _init_config 写盘副作用）。
    未适配 / 游戏配置缺失 / 字段缺失 / 值为空时返回 None，GUI 据此隐藏菜单项。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    if script_name not in _CONFIGS:
        return None
    return _CONFIGS[script_name].get_game_exe_path(script_name)


def get_game_bg_img(script_name: str) -> str:
    """
    外观接口：读取指定脚本对应的启动器背景图绝对路径（供 GUI 渲染背景用）。

    不实例化子类。未适配 / 未声明 / 根目录取不到 / 文件不存在
    → 返回空字符串，GUI 据此走渐变占位背景。
    注意：个别脚本（原神）首次调用时会尝试下载远程背景图（网络操作，
    见 GenshinConfig.get_game_bg_img），并非纯只读。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_bg_img(script_name)


def get_game_bilibili(script_name: str) -> str:
    """
    外观接口：读取指定脚本对应的游戏官方 B 站空间链接（供 GUI 打开 B 站用）。

    只读查询，不实例化子类。未适配 / 未声明 → 返回空字符串，GUI 走通用占位链接。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_bilibili(script_name)


def get_game_github(script_name: str) -> str:
    """
    外观接口：读取指定脚本项目的 GitHub 主页链接（供 GUI 打开 GitHub 用）。

    只读查询，不实例化子类。未适配 / 未声明 → 返回空字符串，GUI 走通用占位链接。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_github(script_name)


def get_game_homepage(script_name: str) -> str:
    """
    外观接口：读取指定脚本对应的游戏官方主页链接（供 GUI 打开官网用）。

    只读查询，不实例化子类。未适配 / 未声明 → 返回空字符串，GUI 走通用占位链接。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    if script_name not in _CONFIGS:
        return ""
    return _CONFIGS[script_name].get_game_homepage(script_name)


def is_adapted(script_name: str) -> bool:
    """
    外观接口：查询脚本是否已注册副本配置适配（供 GUI 决定是否显示任务卡）。

    只读查询，不实例化子类。未适配（不在 _CONFIGS 注册表）→ False。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    return script_name in _CONFIGS


def supports_weekly(script_name: str) -> bool:
    """
    外观接口：查询脚本是否支持周常（周几以后开始执行）配置（供 GUI 控制周常行可选性）。

    只读查询，不实例化子类。未适配 / 未声明 ``_weekly_task_name`` → False，
    GUI 据此保持周常行「未支持」禁用态。

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）。
    """
    if script_name not in _CONFIGS:
        return False
    return bool(_CONFIGS[script_name]._weekly_task_name)
