"""ScriptService：单脚本配置服务（无 Qt 依赖）。

承载「单脚本」视角的实现：从 config.yml 读取单个脚本条目，
build_script_entry 构建脚本配置项，config_file_path 解析配置文件路径。

内部标识统一用**脚本唯一标识 script_name**（exe 脚本为进程名、脚本文件为
display_name），display_name 仅用于展示。config.yml 的写入权统一归
ChainService；本 Service 仅做只读查询。对应 GUI 的 ScriptItem 卡片与配置
弹窗（SingleScriptConfigDialog）。

weekly_timeouts / weekly_start 管理见 :mod:`src.service.weekly_service`。
链编排（脚本列表/生成/运行）见 :mod:`src.service.chain_service`。
"""

import logging
import os

from src.config.set_config import get_config_path
from src.config.subscript import (
    _is_exe_script,
    default_script_entry,
    get_script_name,
    resolve_script_path,
)
from src.utils import (
    require_config_yml_path,
)
from src.utils_yaml import load_yaml

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    """读取 config.yml（断言存在），校验每个条目含 display_name 与 script_path。"""
    config_path = require_config_yml_path()
    data = load_yaml(config_path)
    for s in data.get("script_list", []):
        assert "display_name" in s, f"[service] script_list 条目缺少 display_name: {s}"
        assert "script_path" in s, f"[service] script_list 条目缺少 script_path: {s}"
    return data


class ScriptService:
    """单脚本配置服务：config.yml 只读查询。

    脚本内部标识为**脚本唯一标识**（get_script_name）：exe 脚本用进程名，
    python/bat 等脚本文件用 display_name。所有方法入参均为此标识。
    """

    def get_script(self, script_name: str) -> dict | None:
        """按脚本唯一标识读取单个脚本条目。

        Args:
            script_name: 脚本唯一标识（exe 用进程名，脚本文件用 display_name）。

        Returns:
            脚本条目 dict；不存在时返回 None。
        """
        config = _load_config()
        for script in config.get("script_list", []):
            if get_script_name(script) == script_name:
                return script
        return None

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
        if _is_exe_script(script_path):
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
