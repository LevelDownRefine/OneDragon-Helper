"""ScriptService：单脚本配置服务（无 Qt 依赖）。

承载「单脚本」视角的真实实现：从 config.yml 读写单个脚本条目，并同步
weekly_timeouts.yml。对应 GUI 的 ScriptItem 卡片与配置弹窗（SingleScriptConfigDialog）；
GUI 只做表单收集/弹窗，持久化逻辑在此收编，便于无头测试与 CLI 复用。

链编排（脚本列表/生成/运行）见 :mod:`src.service.chain_service`。
"""

import logging
import os

import yaml

from src.config.subscript import DEFAULT_RUN_TIMEOUT, default_script_entry
from src.utils import (
    get_config_yml_path_under_root,
    get_weekly_timeouts_yml_path_under_root,
    require_config_yml_path,
)

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    """读取 config.yml（断言存在）。"""
    config_path = require_config_yml_path()
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _dump_config(config: dict) -> None:
    """写回 config.yml。"""
    config_path = get_config_yml_path_under_root()
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)


def _load_weekly() -> dict:
    """读取 weekly_timeouts.yml（不存在时返回空 dict）。"""
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    if not os.path.exists(weekly_path):
        return {}
    with open(weekly_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _dump_weekly(weekly_map: dict) -> None:
    """写回 weekly_timeouts.yml。"""
    weekly_path = get_weekly_timeouts_yml_path_under_root()
    with open(weekly_path, "w", encoding="utf-8") as f:
        yaml.dump(weekly_map, f, allow_unicode=True, sort_keys=False)


def _resolve_weekly_timeouts(timeouts: list[int | None]) -> list[int]:
    """把弹窗输入的超时列表规范化：None（空输入）转默认超时，并 clamp 不低于 10。

    Args:
        timeouts: 7 格输入值，空输入为 None。

    Returns:
        规范化后的 7 格超时值列表。
    """
    return [DEFAULT_RUN_TIMEOUT if v is None else max(v, 10) for v in timeouts]


class ScriptService:
    """单脚本配置服务：config.yml 单条目读写 + weekly_timeouts 同步。"""

    def get_script(self, display_name: str) -> dict | None:
        """按 display_name 读取单个脚本条目。

        Args:
            display_name: 脚本 display_name。

        Returns:
            脚本条目 dict；不存在时返回 None。
        """
        config = _load_config()
        for script in config.get("script_list", []):
            if script.get("display_name") == display_name:
                return script
        return None

    def update_script(
        self,
        old_name: str,
        new_name: str,
        patch: dict,
        weekly_timeouts: list[int] | None = None,
    ) -> None:
        """更新单个脚本条目（支持改名）并同步 weekly_timeouts。

        Args:
            old_name: 原 display_name（用于定位条目）。
            new_name: 新 display_name（可与 old_name 相同表示不改名）。
            patch: 要写入条目顶层字段的映射（如 script_path/check_done）。
            weekly_timeouts: 新的 7 格超时列表（元素为 None 表示空输入，
                落盘前转默认超时并 clamp ≥10）；None 表示不改 weekly_timeouts。
                改名时旧的超时配置会迁移到新名。
        """
        assert new_name, "[service] 脚本名称不能为空"
        config = _load_config()
        target = None
        for script in config.get("script_list", []):
            if script.get("display_name") == old_name:
                target = script
                break
        assert target is not None, f"[service] 找不到脚本: {old_name}"

        for key, value in patch.items():
            target[key] = value
        target["display_name"] = new_name

        renamed = new_name != old_name
        if weekly_timeouts is not None or renamed:
            weekly = _load_weekly()
            if renamed:
                old_val = weekly.pop(old_name, None)
                if old_val is not None:
                    weekly[new_name] = old_val
            if weekly_timeouts is not None:
                weekly[new_name] = _resolve_weekly_timeouts(weekly_timeouts)
            _dump_weekly(weekly)

        _dump_config(config)

    def ensure_weekly_entry(self, display_name: str) -> None:
        """为该脚本在 weekly_timeouts.yml 创建 7 格默认条目（已存在则跳过）。

        Args:
            display_name: 脚本 display_name。
        """
        weekly = _load_weekly()
        if display_name in weekly:
            return
        weekly[display_name] = [DEFAULT_RUN_TIMEOUT] * 7
        _dump_weekly(weekly)

    def weekly_inputs(self, display_name: str) -> list[int]:
        """返回配置弹窗 7 个超时输入框的初始值。

        Args:
            display_name: 脚本 display_name。

        Returns:
            长度为 7 的超时值列表（无条目/不足 7 格时用默认超时补齐）。
        """
        weekly_map = _load_weekly()
        entry = weekly_map.get(display_name)
        timeouts = list(entry) if entry else [DEFAULT_RUN_TIMEOUT] * 7
        if len(timeouts) < 7:
            timeouts.extend([DEFAULT_RUN_TIMEOUT] * (7 - len(timeouts)))
        return timeouts[:7]

    def check_weekly(self) -> dict:
        """校验 weekly_timeouts.yml 与 config 脚本条目的一致性。

        Returns:
            {"status": "ok"|"inconsistent", "missing_or_short": [...], "orphans": [...]}。
            weekly_timeouts 中不是 7 格条目的脚本进 missing_or_short；
            config 已删除的孤儿 key 进 orphans。
        """
        config = _load_config()
        config_names = [s["display_name"] for s in config.get("script_list", [])]
        weekly = _load_weekly()

        missing = [name for name in config_names if len(weekly.get(name) or []) != 7]
        orphans = [name for name in weekly if name not in config_names]

        return {
            "status": "ok" if not missing and not orphans else "inconsistent",
            "missing_or_short": missing,
            "orphans": orphans,
        }

    def build_script_entry(self, file_path: str, existing_names: set[str]) -> dict:
        """按文件路径构造脚本条目：去重命名 + 类型推断 + 默认字段补全。

        Args:
            file_path: 选中的脚本文件路径（已规范化）。
            existing_names: 已有脚本 display_name 集合，用于去重命名。

        Returns:
            完整的 script_list 条目 dict（display_name 不与 existing_names 重复）。
        """
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        display_name = base_name
        suffix = 1
        while display_name in existing_names:
            display_name = f"{base_name}_{suffix}"
            suffix += 1

        script_type = "python" if file_path.lower().endswith(".py") else "external"
        return default_script_entry(
            display_name=display_name,
            script_type=script_type,
            script_path=file_path,
        )
