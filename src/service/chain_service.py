"""ChainService：脚本链核心服务。

承载「真实实现」：脚本配置读写、UI 状态持久化（gui_state.json）、脚本链生成、
合法性校验、runner 命令构造。GUI（MainWindow）与 CLI（launcher.py）都作为薄适配器
依赖本服务，便于无头测试与两端行为一致。

本模块不承载 UI 渲染/弹窗逻辑，无 Qt 依赖。
"""

import json
import logging
import os

import yaml

from src.config.dungeon_config import load_dungeon_map
from src.service.chain_gen import generate_chain_config as _generate_chain_config
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
    """脚本链核心服务：配置读写、链生成、校验、运行命令构造。"""

    # ---------- 配置读写 ----------

    def load_config(self) -> dict:
        """读取 config.yml（断言存在），返回完整 script_list 配置。"""
        config_path = require_config_yml_path()
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict) and "script_list" in data, (
            "[service] config.yml 缺少 script_list 字段"
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

        Args:
            all_config_data: config.yml 完整数据（含 script_list）。
            enabled_names: 要纳入链的脚本 display_name 集合。
            chain_name: 链配置文件名（不含扩展名）。
            ui_state: gui_state.json 的 UI 状态（副本/序列选择）。
            out_path: 输出路径；None 时默认 config/script_chain/<chain_name>.yml。

        Returns:
            输出文件路径。
        """
        return _generate_chain_config(
            all_config_data, enabled_names, chain_name, ui_state, out_path
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
