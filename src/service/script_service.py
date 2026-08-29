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

from src.config.dungeon_config import load_dungeon_map
from src.config.set_config import get_config_path, get_dungeon_lists
from src.config.subscript import (
    _is_exe_script,
    default_script_entry,
    get_script_name,
    resolve_script_path,
)
from src.utils import (
    get_weekly_list_yml_path_under_root,
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


def _load_weekly_defs() -> dict:
    """读取 weekly_list.yml（周常声明配置，进 git，必存在）。

    结构：{script_name: [{"name", "dungeons"?}, ...]}。dungeons 存在且有内容即
    表示该周常需选副本（不再用 needs_instance 布尔字段）。周常起始日（周几起）
    另存于 weekly_start.yml，不在本文件。
    """
    weekly_list_path = get_weekly_list_yml_path_under_root()
    assert os.path.exists(weekly_list_path), (
        f"[service] 周常声明配置缺失: {weekly_list_path}"
    )
    data = load_yaml(weekly_list_path)
    # 空文件或内容非 dict 都是声明配置损坏，直接暴露而非静默当成「无声明」。
    assert isinstance(data, dict), (
        f"[service] 周常声明配置应为 dict（空文件或格式错误）: {weekly_list_path}"
    )
    return data


class ScriptService:
    """单脚本配置服务：config.yml 只读查询。

    脚本内部标识为**脚本唯一标识**（get_script_name）：exe 脚本用进程名，
    python/bat 等脚本文件用 display_name。所有方法入参均为此标识。
    """

    def get_weekly_defs(self, script_name: str) -> list:
        """返回某脚本支持的周常声明清单（weekly_list.yml）。

        每项：{"name", "dungeons"?}。dungeons 存在且有内容即有可选副本。文件缺失或该
        脚本无声明时返回空列表。

        声明项若带 ``dungeons_source`` 标记，则副本清单取自游戏脚本自身配置（运行期
        读取，见 ``set_config.get_dungeon_lists``），不再手写维护；读不到时降级
        为 ``dungeons: []``（该周常无需/无法选副本）。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            周常声明列表；无声明时为空列表。
        """
        defs_map = _load_weekly_defs()
        if script_name not in defs_map:
            return []
        defs = list(defs_map[script_name])
        for d in defs:
            source = d.get("dungeons_source")
            if source:
                # 副本清单来自外部（如 M7A 的 instance_names.json），运行时读取，
                # 不再手动维护；读不到则降级为无可选副本（has_dungeon=False）。
                names = get_dungeon_lists(script_name, d["name"], source)
                d["dungeons"] = names if names is not None else []
        return defs

    def get_dungeon_map(self) -> dict:
        """返回日常副本/序列配置映射（dungeon_list.yml）。

        声明项若带 ``dungeons_source`` 标记，其二级序列（副本名清单）取自游戏脚本
        自身配置（运行期读取，见 ``get_dungeon_lists``），不再手写维护；读不到时
        降级为 ``sequences: []``（该副本无需/无法选二级）。

        Returns:
            脚本唯一标识 → 副本配置的映射（文件缺失时返回空 dict）。
        """
        data = load_dungeon_map()
        for script_name, cfg in data.items():
            if not isinstance(cfg, dict):
                continue
            for d in cfg.get("dungeons", []):
                if not isinstance(d, dict):
                    continue
                source = d.get("dungeons_source")
                if source:
                    # 二级序列来自外部（如 ok-ef 的 world_map.json），运行期读取，
                    # 不手动维护；读不到则降级为无可选序列（show_seq=False）。
                    names = get_dungeon_lists(script_name, d["name"], source)
                    d["sequences"] = (
                        [{"display": n, "value": n} for n in names] if names else []
                    )
        return data

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
