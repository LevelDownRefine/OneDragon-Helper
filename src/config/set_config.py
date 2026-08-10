"""
副本配置适配器（外观模式）
对外提供统一的 set_config 接口，内部封装各自动化脚本的 config 读写逻辑。

每个脚本的 config 格式、路径、字段名都不同，
各脚本子类单独适配，上层无需关心差异。
"""

import logging
from collections.abc import Callable
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

    def _load(self) -> dict:
        config = load_config(self._script_name, self._config_rel_path)
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        return config

    def _save(self, config: dict) -> None:
        assert isinstance(config, dict), (
            f"[set_config][{self.display_name}] config 必须是 dict"
        )
        if not self.enabled:
            logger.info(f"[set_config][{self.display_name}] 用户拒绝更新，跳过保存")
            return
        save_config(self._script_name, self._config_rel_path, config)
        self._verify_saved(config)

    def _verify_saved(self, expected: dict) -> None:
        """保存后重新读取，确认落盘内容与预期一致（校验写盘确实生效）。"""
        reloaded = self._load()
        assert reloaded == expected, (
            f"[set_config][{self.display_name}] 配置保存后校验失败："
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
            assert dungeon_name in self._task_map, (
                f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
            )
            task = self._task_map[dungeon_name]
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
        """
        config = self._load()
        template = self._load_template()

        if self._is_aligned(config, template):
            logger.info(f"[init_config][{self.display_name}] config 已对齐，无需更新")
            return

        for key, val in template.items():
            safe_update(config, key, val, self.display_name, assert_key_exists=False)
        if self._confirm_save():
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


# ============================================================
# 注册表
# ============================================================

# 由 register() 装饰器显式填充（必须在子类定义前初始化）。
_CONFIGS: dict[str, type[ScriptConfig]] = {}


def register(cls: type[ScriptConfig]) -> type[ScriptConfig]:
    """显式注册 ScriptConfig 子类到 ``_CONFIGS``（装饰器）。

    子类声明 ``_script_name`` 与路径类属性后加 ``@register`` 即完成登记。
    路径声明不完整（缺 ``_config_rel_path``、或声明了 ``_game_path_keys`` 却缺
    ``_game_config_rel_path``）属编程错误，import 时立即 assert 暴露，
    避免新增脚本漏配路径后静默缺功能。
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

    def __init__(self):
        self.display_name = "鸣潮"
        self._task_key = "Which to Farm"
        self._task_map = {
            "凝素领域": "Forgery Challenge",
            "模拟领域": "Simulation Challenge",
            "无音区": "Tacet Suppression",
        }

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

    def __init__(self):
        self.display_name = "原神"
        self._task_key = "DomainName"
        self._init_config()


# ---- 终末地 Arknights: Endfield ----
@register
class EndfieldConfig(ScriptConfig):
    _script_name = "ok-ef"
    _config_rel_path = "data/apps/ok-ef/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-ef/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)

    def __init__(self):
        self.display_name = "终末地"
        self._task_key = "体力本"
        self._init_config()

    def _init_config(self):
        # TODO: 确认包含了绳索等配置
        pass


# ---- 绝区零 Zenless Zone Zero ----
@register
class ZenlessZoneZeroConfig(ScriptConfig):
    _script_name = "OneDragon-Launcher"
    _config_rel_path = "config/01/one_dragon/charge_plan.yml"
    _game_config_rel_path = "config/01/game_account.yml"
    _template_rel_path = "ZZZ一条龙.yml"
    _game_path_keys = ("game_path",)

    def __init__(self):
        self.display_name = "绝区零"
        self._init_config()

    def set_dungeon(self, dungeon_name: str, sequence: str | int | None = None):
        logger.info(f"[set_config][{self.display_name}] zzz无需适配")


# ---- 崩铁 Honkai: Star Rail ----
@register
class StarRailConfig(ScriptConfig):
    _script_name = "March7th-Assistant"
    _config_rel_path = "config.yaml"
    _game_config_rel_path = "config.yaml"
    _template_rel_path = "M7A一条龙.yml"
    _game_path_keys = ("game_path",)

    def __init__(self):
        self.display_name = "崩铁"
        self._task_key = "instance_type"
        self._init_config()


# ---- 异环 Neverness to Everness (NTE) ----
@register
class NTEConfig(ScriptConfig):
    _script_name = "ok-nte"
    _config_rel_path = "data/apps/ok-nte/working/configs/DailyTask.json"
    _game_config_rel_path = "data/apps/ok-nte/working/configs/devices.json"
    _game_path_keys = ("pc_full_path",)

    def __init__(self):
        self.display_name = "异环"
        self._task_key = "任务类型"
        self._seq_key_map = {
            "异能升级材料": "异能材料序号",
            "空幕": "空幕序号",
            "弧盘突破材料": "弧盘材料序号",
        }

    def _update_sequence(
        self, config: dict, dungeon_name: str, sequence: str | int | None
    ) -> bool:
        assert sequence is not None, f"[set_config][{self.display_name}] 序列不能为空"
        assert dungeon_name in self._seq_key_map, (
            f"[set_config][{self.display_name}] 未适配的副本: {dungeon_name}"
        )
        key = self._seq_key_map[dungeon_name]
        return safe_update(config, key, sequence, self.display_name)


# ---- 明日方舟 Arknights（粥）----
@register
class ArknightsConfig(ScriptConfig):
    _script_name = "MAA"
    _config_rel_path = "config/gui.new.json"
    _game_config_rel_path = "config/gui.new.json"
    _template_rel_path = "MAA一条龙.json"
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
) -> None:
    """
    外观接口：为指定脚本设置副本和刷取序列

    Args:
        script_name: 脚本唯一标识（exe 为进程名如 ok-ww / BetterGI，
            python/bat 为 display_name）
        dungeon_name: 副本名称（来自 dungeon_list.yml），None 或 "未选择" 时跳过
        sequence: 刷取序列（字符串或整数），None 表示无序列
    """
    # 未选择副本时，不做更改
    if not dungeon_name or dungeon_name == "未选择":
        return

    # 自定义脚本（用户在 GUI 中新增）没有副本适配，不在注册表中，直接跳过。
    # 这类脚本本就没有副本选项，正常不会带 dungeon_name 走到这里；即便带了也优雅跳过。
    if script_name not in _CONFIGS:
        logger.info(f"[set_config] 进程 {script_name} 无副本适配（自定义脚本），跳过")
        return

    cfg_cls = _CONFIGS[script_name]
    cfg_cls().set_dungeon(dungeon_name, sequence)


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
