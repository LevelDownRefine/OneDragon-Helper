"""ScriptService：单脚本配置服务（无 Qt 依赖）。

承载「单脚本」视角的实现：config.yml 的读写（含脚本条目增删改）、
weekly_timeouts.yml 的读写与改名迁移，以及 weekly_start.yml 管理。

内部标识统一用**脚本唯一标识 script_name**（exe 脚本为进程名、脚本文件为
display_name），display_name 仅用于展示。config.yml 的读写权统一归本 Service；
ChainService 仅作运行时委托（其内部 ScheduledRun 经 ``load_config`` 取配置）。
对应 GUI 的 ScriptItem 卡片与配置弹窗（SingleScriptConfigDialog）。

链编排（脚本列表/生成/运行）见 :mod:`src.service.chain_service`。
"""

import logging
import os

from src.config.set_config import get_config_path, init_config
from src.config.subscript import (
    DEFAULT_RUN_TIMEOUT,
    check_script_name_uniqueness,
    default_script_entry,
    get_script_name,
    is_exe_script,
    resolve_script_path,
)
from src.utils import (
    get_config_yml_path_under_root,
    get_weekly_start_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
    require_config_yml_path,
)
from src.utils_yaml import dump_yaml, load_yaml

logger = logging.getLogger(__name__)


def _load_weekly() -> dict:
    """读取 weekly_timeouts.yml（随包发布、必存在）。

    与 _load_weekly_map 同款：assert 存在且为 dict，损坏直接暴露而非静默兜底。
    """
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    assert os.path.exists(weekly_path), f"[service] 周常超时配置缺失: {weekly_path}"
    data = load_yaml(weekly_path)
    assert isinstance(data, dict), (
        f"[service] 周常超时配置应为 dict（空文件或格式错误）: {weekly_path}"
    )
    return data


def _dump_weekly(weekly_map: dict) -> None:
    """写回 weekly_timeouts.yml。"""
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    dump_yaml(weekly_path, weekly_map)


def _load_weekly_start() -> dict:
    """读取 weekly_start.yml（周常起始日持久化配置，进 git，必存在）。

    结构：{script_name: 1~7}。与 _load_weekly / _load_weekly_map 同款：
    assert 存在且为 dict，损坏直接暴露而非静默兜底。
    """
    weekly_start_path = get_weekly_start_yml_path_under_root()
    assert os.path.exists(weekly_start_path), (
        f"[service] 周常起始日配置缺失: {weekly_start_path}"
    )
    data = load_yaml(weekly_start_path)
    assert isinstance(data, dict), (
        f"[service] 周常起始日配置应为 dict（空文件或格式错误）: {weekly_start_path}"
    )
    return data


def _dump_weekly_start(data: dict) -> None:
    """写回 weekly_start.yml（覆盖式，与 _dump_weekly 同款）。"""
    weekly_start_path = get_weekly_start_yml_path_under_root()
    dump_yaml(weekly_start_path, data)


def _resolve_weekly_timeouts(timeouts: list[int | None]) -> list[int]:
    """把弹窗输入的超时列表规范化：None（空输入）转默认超时，低值（<10）原样保留。

    低值不再 clamp，由 chain_gen 在生成链时按「当天 <10 秒不运行」语义跳过脚本。

    Args:
        timeouts: 7 格输入值，空输入为 None。

    Returns:
        规范化后的 7 格超时值列表。
    """
    return [DEFAULT_RUN_TIMEOUT if v is None else v for v in timeouts]


class ScriptService:
    """单脚本配置服务：config.yml 只读查询 + 周常/副本配置管理。

    脚本内部标识为**脚本唯一标识**（get_script_name）：exe 脚本用进程名，
    python/bat 等脚本文件用 display_name。所有方法入参均为此标识。

    副本与周常声明（dungeon_list.yml / weekly_list.yml）的读取由平级
    :class:`DungeonService` 负责（经 :class:`AppService` 组合暴露）；本服务只管
    单脚本配置与周常起始日/超时（weekly_start.yml / weekly_timeouts.yml）。
    """

    def __init__(self) -> None:
        pass

    # ---------- config.yml 读写 ----------

    def load_config(self) -> dict:
        """读取 config.yml（断言存在），返回完整 script_list 配置。

        入口处一次性校验每个条目含 display_name/script_path 且脚本唯一标识唯一，
        script_list 内部数据此后可安全用直接访问。
        """
        config_path = require_config_yml_path()
        data = load_yaml(config_path)
        assert isinstance(data, dict) and "script_list" in data, (
            "[service] config.yml 缺少 script_list 字段"
        )
        for s in data["script_list"]:
            assert "display_name" in s, (
                f"[service] script_list 条目缺少 display_name: {s}"
            )
            assert "script_path" in s, (
                f"[service] script_list 条目缺少 script_path: {s}"
            )
        check_script_name_uniqueness(data)
        return data

    def save_config(self, data: dict) -> None:
        """写回 config.yml（生成目标，不要求已存在）。

        Args:
            data: 完整 script_list 配置字典。
        """
        assert isinstance(data, dict) and "script_list" in data, (
            "[service] 待保存的 config 缺少 script_list 字段"
        )
        config_path = get_config_yml_path_under_root()
        dump_yaml(config_path, data)

    def add_script(self, script_data: dict) -> None:
        """向 config.yml 的 script_list 追加一个脚本条目，并自动创建 weekly 默认条目。

        脚本唯一标识（get_script_name）不得与已有条目重复（数据完整性约束）。

        Args:
            script_data: 完整脚本条目 dict（含 display_name / script_path 等）。
        """
        assert "display_name" in script_data, "[service] script_data 缺少 display_name"
        assert "script_path" in script_data, "[service] script_data 缺少 script_path"
        config = self.load_config()
        scripts = config.setdefault("script_list", [])
        new_script_name = get_script_name(script_data)
        assert all(get_script_name(s) != new_script_name for s in scripts), (
            f"[service] 脚本标识已存在: {new_script_name}"
        )
        scripts.append(script_data)
        self.save_config(config)
        self.ensure_weekly_entry(new_script_name)
        init_config(new_script_name)

    def remove_script(self, script_name: str) -> None:
        """从 config.yml 的 script_list 移除指定脚本条目，并自动清理 weekly 孤儿。

        Args:
            script_name: 要移除的脚本唯一标识。
        """
        config = self.load_config()
        scripts = config.setdefault("script_list", [])
        target = next(
            (s for s in scripts if get_script_name(s) == script_name),
            None,
        )
        assert target is not None, f"[service] 找不到脚本: {script_name}"
        scripts.remove(target)
        self.save_config(config)
        self.delete_weekly(script_name)

    def update_script(
        self,
        old_script_name: str,
        new_display_name: str,
        config_patch: dict,
        weekly_timeouts: list[int | None],
    ) -> str:
        """更新单个脚本条目字段并同步 weekly_timeouts。

        以脚本唯一标识定位条目；自动处理标识变更（含 weekly 迁移）与
        kill_game_after_done 自洽（未设置 game_process_name 时强制 False）。

        Args:
            old_script_name: 原脚本唯一标识（用于定位条目）。
            new_display_name: 新 display_name（展示名，可保留原名）。
            config_patch: 要写入条目顶层字段的映射（如 script_path/check_done）。
            weekly_timeouts: 7 格超时输入值，空输入为 None（落盘前转默认超时）。

        Returns:
            落盘后的脚本唯一标识（标识可能因 script_path/display_name 变更而改变），
            供调用方在落盘后触发依赖新路径的后续动作（如游戏侧周几起同步）。
        """
        assert new_display_name, "[service] 脚本名称不能为空"
        config = self.load_config()
        target = None
        for script in config.setdefault("script_list", []):
            if get_script_name(script) == old_script_name:
                target = script
                break
        assert target is not None, f"[service] 找不到脚本: {old_script_name}"

        for key, value in config_patch.items():
            target[key] = value
        target["display_name"] = new_display_name

        new_script_name = get_script_name(target)
        if new_script_name != old_script_name:
            assert all(
                get_script_name(s) != new_script_name
                for s in config["script_list"]
                if s is not target
            ), f"[service] 脚本标识已存在: {new_script_name}"

        # 配置自洽：未设置游戏进程名时「运行后关闭游戏」强制 False
        if not target.get("game_process_name", ""):
            target["kill_game_after_done"] = False

        self.save_config(config)

        if new_script_name != old_script_name:
            self.rename_weekly_in_timeouts(old_script_name, new_script_name)
        self.save_weekly(new_script_name, weekly_timeouts)
        init_config(new_script_name)
        return new_script_name

    def load_all_weekly(self) -> dict:
        """返回 weekly_timeouts.yml 的完整字典（文件随包发布，必存在）。

        key 为脚本唯一标识。
        """
        return _load_weekly()

    def get_weekly_start(self, script_name: str) -> int | None:
        """返回某脚本的周常起始日（1~7），未设置返回 None。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            周常起始日（1~7），未设置返回 None。
        """
        start_map = _load_weekly_start()
        if script_name not in start_map:
            return None
        start_day = start_map[script_name]
        if start_day is None:
            return None
        assert isinstance(start_day, int), (
            f"[service] {script_name} 非法 weekly_start: {start_day!r}（应为整数 1~7）"
        )
        assert 1 <= start_day <= 7, (
            f"[service] {script_name} 非法 weekly_start: {start_day}（应为 1~7）"
        )
        return start_day

    def get_weekly_start_map(self) -> dict:
        """返回 weekly_start.yml 全量（{脚本标识: 1~7}）。"""
        return _load_weekly_start()

    def set_weekly_start(self, script_name: str, start_day: int | None) -> None:
        """持久化某脚本的周常起始日（周几起）到 weekly_start.yml。

        start_day 为 1~7 时写入；为 None 时移除该脚本条目（对应弹窗「不设置」）。

        Args:
            script_name: 脚本唯一标识。
            start_day: 周常起始日（1~7）；None 表示清除。
        """
        if start_day is not None:
            assert 1 <= start_day <= 7, (
                f"[service] 非法 weekly_start: {start_day}（应为 1~7）"
            )
        data = _load_weekly_start()
        if start_day is None:
            if script_name not in data:
                return
            data.pop(script_name, None)
        else:
            data[script_name] = start_day
        _dump_weekly_start(data)

    def get_script(self, script_name: str) -> dict | None:
        """按脚本唯一标识读取单个脚本条目。

        Args:
            script_name: 脚本唯一标识（exe 用进程名，脚本文件用 display_name）。

        Returns:
            脚本条目 dict；不存在时返回 None。
        """
        config = self.load_config()
        for script in config.get("script_list", []):
            if get_script_name(script) == script_name:
                return script
        return None

    def save_weekly(self, script_name: str, timeouts: list[int | None]) -> None:
        """保存单个脚本的每周超时（空输入转默认超时；低值原样保留表示当天不运行）。

        Args:
            script_name: 脚本唯一标识。
            timeouts: 7 格超时输入值（必须恰好 7 格），空输入为 None。
        """
        assert len(timeouts) == 7, (
            f"[service] weekly 超时必须为 7 格，实际 {len(timeouts)}"
        )
        weekly = _load_weekly()
        weekly[script_name] = _resolve_weekly_timeouts(timeouts)
        _dump_weekly(weekly)

    def rename_weekly_in_timeouts(
        self, old_script_name: str, new_script_name: str
    ) -> None:
        """脚本标识变更时迁移 weekly_timeouts.yml 中的条目。

        旧条目存在则迁移到新名；不存在则无操作。

        Args:
            old_script_name: 原脚本唯一标识。
            new_script_name: 新脚本唯一标识。
        """
        if old_script_name == new_script_name:
            return
        weekly = _load_weekly()
        old_val = weekly.pop(old_script_name, None)
        if old_val is not None:
            weekly[new_script_name] = old_val
            _dump_weekly(weekly)

    def ensure_weekly_entry(self, script_name: str) -> None:
        """为该脚本在 weekly_timeouts.yml 创建 7 格默认条目（已存在则跳过）。

        Args:
            script_name: 脚本唯一标识。
        """
        weekly = _load_weekly()
        if script_name in weekly:
            return
        weekly[script_name] = [DEFAULT_RUN_TIMEOUT] * 7
        _dump_weekly(weekly)

    def weekly_inputs(self, script_name: str) -> list[int]:
        """返回配置弹窗 7 个超时输入框的初始值。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            长度为 7 的超时值列表（无条目/不足 7 格时用默认超时补齐）。
        """
        weekly_map = _load_weekly()
        entry = weekly_map.get(script_name)
        timeouts = list(entry) if entry else [DEFAULT_RUN_TIMEOUT] * 7
        if len(timeouts) < 7:
            timeouts.extend([DEFAULT_RUN_TIMEOUT] * (7 - len(timeouts)))
        return timeouts[:7]

    def check_weekly(self) -> dict:
        """校验 weekly_timeouts.yml 与 config 脚本条目的一致性。

        Returns:
            {"status": "ok"|"inconsistent", "missing_or_short": [...], "orphans": [...]}。
            weekly_timeouts 中不是 7 格条目的脚本标识进 missing_or_short；
            config 已删除的孤儿 key 进 orphans（均为脚本唯一标识）。
        """
        config = self.load_config()
        config_keys = [get_script_name(s) for s in config.get("script_list", [])]
        weekly = _load_weekly()

        missing = [name for name in config_keys if len(weekly.get(name) or []) != 7]
        orphans = [name for name in weekly if name not in config_keys]

        return {
            "status": "ok" if not missing and not orphans else "inconsistent",
            "missing_or_short": missing,
            "orphans": orphans,
        }

    def build_script_entry(
        self, file_path: str, existing_script_names: set[str]
    ) -> dict:
        """按文件路径构造脚本条目：去重命名 + 类型推断 + 默认字段补全。

        新脚本的 display_name 与唯一标识一致（exe 为进程名，脚本文件为 display_name），
        去重基于唯一标识。

        Args:
            file_path: 选中的脚本文件路径（已规范化）。
            existing_script_names: 已有脚本唯一标识集合，用于去重命名。

        Returns:
            完整的 script_list 条目 dict（display_name 不与 existing 重复）。
        """
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        display_name = base_name
        suffix = 1
        while display_name in existing_script_names:
            display_name = f"{base_name}_{suffix}"
            suffix += 1

        script_type = "python" if file_path.lower().endswith(".py") else "external"
        return default_script_entry(
            display_name=display_name,
            script_type=script_type,
            script_path=file_path,
        )

    def delete_weekly(self, script_name: str) -> None:
        """删除脚本时清理 weekly_timeouts.yml 中该脚本的孤儿条目。

        config.yml 的总配置移除由 ChainService.remove_script 负责；此处仅清理
        脚本级配置（weekly 超时条目），使删除行为完整、无残留。

        Args:
            script_name: 要清理 weekly 条目的脚本唯一标识。
        """
        weekly = _load_weekly()
        if script_name in weekly:
            weekly.pop(script_name)
            _dump_weekly(weekly)

    def config_file_path(self, script_name: str) -> tuple[str | None, str | None]:
        """返回该脚本「配置文件」的本地路径（用于外部打开）与失败原因。

        python 脚本返回其 .py 源文件路径；external 脚本返回其内部 config 路径。
        文件不存在或脚本未适配配置文件时返回 (None, error)，error 可直接展示给用户。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            (path, error)：path 为可打开的配置文件路径（str）；error 为非空字符串时
                表示未适配或文件缺失（可直接展示），此时 path 为 None。
        """
        script = self.get_script(script_name)
        if script is None:
            return None, f"找不到脚本: {script_name}"
        script_type = script.get("script_type", "external")
        script_path = script.get("script_path", "")
        if script_type == "python":
            resolved = resolve_script_path(script_path)
            if not resolved or not os.path.isfile(resolved):
                return (
                    None,
                    f"找不到脚本文件：{script_path or '(未设置路径)'}",
                )
            return resolved, None
        if is_exe_script(script_path):
            try:
                config_path = get_config_path(get_script_name(script))
            except AssertionError as e:
                return None, f"该脚本暂未适配配置文件，无法打开：{e}"
            if not os.path.isfile(config_path):
                return None, f"配置文件不存在：{config_path}"
            return config_path, None
        # external 但非 exe（如 bat 等）：无 config 适配，打开其自身
        resolved = resolve_script_path(script_path)
        if not resolved or not os.path.isfile(resolved):
            return None, f"找不到脚本文件：{script_path or '(未设置路径)'}"
        return resolved, None
