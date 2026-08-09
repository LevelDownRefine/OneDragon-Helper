"""ChainService：脚本链核心服务（GUI / CLI 唯一 facade）。

承载「真实实现」：config.yml 完整读写（含单脚本字段更新）、UI 状态持久化
（gui_state.json）、脚本链生成、合法性校验、runner 命令构造。

weekly_timeouts 同步由内部 ScriptService 处理，调用方不感知。GUI（MainWindow）
与 CLI（launcher.py）都作为薄适配器依赖本服务。

本模块不承载 UI 渲染/弹窗逻辑，无 Qt 依赖。
"""

import json
import logging
import os

import yaml

from src.config.dungeon_config import load_dungeon_map
from src.service.chain_gen import generate_chain_config as _generate_chain_config
from src.service.script_service import ScriptService
from src.utils import (
    get_config_yml_path_under_root,
    get_root_dir,
    require_config_yml_path,
    safe_path_join,
)
from src.utils_runner import (
    build_chain_command as _build_chain_command,
)
from src.utils_runner import (
    collect_invalid_script_messages,
)
from src.utils_runner import (
    run_chain_command as _run_chain_command,
)

logger = logging.getLogger(__name__)

_STATE_FILE = safe_path_join(get_root_dir(), "config", "gui_state.json")


class ChainService:
    """脚本链核心服务：config.yml 读写、链生成、校验、运行命令构造，
    内部集成 ScriptService 处理 weekly_timeouts 同步。"""

    def __init__(self, script_service=None):
        """初始化 ChainService。

        Args:
            script_service: 可注入的 ScriptService；None 时自建默认实例。
        """
        self._script_service = script_service or ScriptService()

    # ---------- 配置读写 ----------

    def load_config(self) -> dict:
        """读取 config.yml（断言存在），返回完整 script_list 配置。

        结果从外部 YAML 载入——入口处一次性校验每个条目含 display_name，
        ``script_list`` 内部数据此后可安全用直接访问。
        """
        config_path = require_config_yml_path()
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict) and "script_list" in data, (
            "[service] config.yml 缺少 script_list 字段"
        )
        for s in data["script_list"]:
            assert "display_name" in s, (
                f"[service] script_list 条目缺少 display_name: {s}"
            )
        return data

    def dungeon_map(self) -> dict:
        """读取 dungeon_list.yml 的副本/序列配置映射。

        Returns:
            脚本名 → 副本配置的映射（文件缺失时返回空 dict）。
        """
        return load_dungeon_map()

    def save_config(self, data: dict) -> None:
        """写回 config.yml（生成目标，不要求已存在）。

        Args:
            data: 完整 script_list 配置字典。
        """
        assert isinstance(data, dict) and "script_list" in data, (
            "[service] 待保存的 config 缺少 script_list 字段"
        )
        config_path = get_config_yml_path_under_root()
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    def add_script(self, script_data: dict) -> None:
        """向 config.yml 的 script_list 追加一个脚本条目，并自动创建 weekly 默认条目。

        display_name 不得与已有条目重复（数据完整性约束）。

        Args:
            script_data: 完整脚本条目 dict（含 display_name / script_path 等）。
        """
        assert "display_name" in script_data, "[service] script_data 缺少 display_name"
        config = self.load_config()
        scripts = config.setdefault("script_list", [])
        display_name = script_data["display_name"]
        assert all(s["display_name"] != display_name for s in scripts), (
            f"[service] 脚本名称已存在: {display_name}"
        )
        scripts.append(script_data)
        self.save_config(config)
        self._script_service.ensure_weekly_entry(display_name)

    def remove_script(self, display_name: str) -> None:
        """从 config.yml 的 script_list 移除指定脚本条目，并自动清理 weekly 孤儿。

        Args:
            display_name: 要移除的脚本 display_name。
        """
        config = self.load_config()
        scripts = config.setdefault("script_list", [])
        target = next(
            (s for s in scripts if s["display_name"] == display_name), None
        )
        assert target is not None, f"[service] 找不到脚本: {display_name}"
        scripts.remove(target)
        self.save_config(config)
        self._script_service.delete_weekly(display_name)

    def update_script(
        self,
        old_display_name: str,
        new_display_name: str,
        config_patch: dict,
        weekly_timeouts: list[int | None],
    ) -> None:
        """更新单个脚本条目字段并同步 weekly_timeouts。

        自动处理改名（含 weekly 迁移）与 kill_game_after_done 自洽
        （未设置 game_process_name 时强制 False）。

        Args:
            old_display_name: 原 display_name（用于定位条目）。
            new_display_name: 新 display_name（可与 old_display_name 相同表示不改名）。
            config_patch: 要写入条目顶层字段的映射（如 script_path/check_done）。
            weekly_timeouts: 7 格超时输入值，空输入为 None（落盘前转默认超时）。
        """
        assert new_display_name, "[service] 脚本名称不能为空"
        config = self.load_config()
        target = None
        for script in config.setdefault("script_list", []):
            if script["display_name"] == old_display_name:
                target = script
                break
        assert target is not None, f"[service] 找不到脚本: {old_display_name}"

        renamed = new_display_name != old_display_name
        if renamed:
            assert all(
                s["display_name"] != new_display_name for s in config["script_list"]
            ), f"[service] 脚本名称已存在: {new_display_name}"

        for key, value in config_patch.items():
            target[key] = value
        target["display_name"] = new_display_name

        # 配置自洽：未设置游戏进程名时「运行后关闭游戏」强制 False
        if not target.get("game_process_name", ""):
            target["kill_game_after_done"] = False

        self.save_config(config)

        if renamed:
            self._script_service.rename_weekly_in_timeouts(
                old_display_name, new_display_name
            )
        self._script_service.save_weekly(new_display_name, weekly_timeouts)

    def load_ui_state(self) -> dict:
        """读取 gui_state.json（UI 状态：副本/序列选择）。

        Returns:
            状态字典；文件不存在时返回空 dict。
        """
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_ui_state(self, state: dict) -> None:
        """保存 UI 状态。

        Args:
            state: 要写入 gui_state.json 的状态字典。
        """
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    # ---------- 链生成与校验 ----------

    def generate_chain(
        self,
        all_config_data: dict,
        enabled_names: set[str],
        chain_name: str = "88",
        ui_state: dict | None = None,
        out_path: str | None = None,
    ) -> str:
        """生成 ScriptChainer 配置文件（仅含启用脚本）。

        weekly_timeouts 通过 ScriptService 加载后传入 chain_gen，不再由
        chain_gen 直接读取磁盘文件。

        Args:
            all_config_data: config.yml 完整数据（含 script_list）。
            enabled_names: 要纳入链的脚本 display_name 集合。
            chain_name: 链配置文件名（不含扩展名）。
            ui_state: gui_state.json 的 UI 状态（副本/序列选择）。
            out_path: 输出路径；None 时默认 config/script_chain/<chain_name>.yml。

        Returns:
            输出文件路径。
        """
        weekly_timeouts = self._script_service.load_all_weekly()
        return _generate_chain_config(
            all_config_data,
            enabled_names,
            chain_name,
            ui_state,
            out_path,
            weekly_timeouts=weekly_timeouts,
        )

    def collect_invalid_scripts(self, script_list: list[dict]) -> list[tuple[str, str]]:
        """收集脚本列表中配置不合法的条目。

        Args:
            script_list: 脚本配置条目列表。

        Returns:
            [(display_name, invalid_message), ...]，仅含不合法项。
        """
        return collect_invalid_script_messages(script_list)

    # ---------- runner 命令 ----------

    def build_chain_command(
        self, chain_config_path: str, extra_args: list[str] | None = None
    ) -> tuple[list[str], str, dict | None]:
        """构造脚本链启动命令，返回 ``(命令列表, cwd, env)``。"""
        return _build_chain_command(chain_config_path, extra_args)

    def run_chain_command(
        self,
        chain_config_path: str,
        block: bool = True,
        extra_args: list[str] | None = None,
    ) -> int:
        """运行一条脚本链，返回退出码。"""
        return _run_chain_command(chain_config_path, block, extra_args)
