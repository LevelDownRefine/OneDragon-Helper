"""DungeonService：副本配置服务（无 Qt 依赖）。

管理两个「副本维度」的持久化配置：
- dungeon_list.yml：日常副本/序列配置映射
- weekly_list.yml：每个脚本支持的周常副本清单

设计为纯数据读写层，不含 config.yml 查询或其他脚本级逻辑。
调用方（GUI / CLI）负责按需使用。

内部标识统一用**脚本唯一标识 script_name**（exe 脚本为进程名、脚本文件为
display_name），display_name 仅用于展示。
"""

import logging
import os

from src.config.dungeon_config import load_dungeon_map
from src.config.set_config import get_dungeon_lists
from src.utils import get_weekly_list_yml_path_under_root
from src.utils_yaml import load_yaml

logger = logging.getLogger(__name__)


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


class DungeonService:
    """副本配置服务：dungeon_list.yml + weekly_list.yml 读取。

    脚本内部标识为**脚本唯一标识**（get_script_name）：exe 脚本用进程名，
    python/bat 等脚本文件用 display_name。所有方法入参均为此标识。
    """

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

    def get_weekly_map(self, script_name: str) -> list:
        """返回某脚本支持的周常副本清单（weekly_list.yml）。

        每项：{"name", "dungeons"?}。dungeons 存在且有内容即有可选副本。文件缺失或该
        脚本无声明时返回空列表。

        声明项若带 ``dungeons_source`` 标记，则副本清单取自游戏脚本自身配置（运行期
        读取，见 ``set_config.get_dungeon_lists``），不再手写维护；读不到时降级
        为 ``dungeons: []``（该周常无需/无法选副本）。

        Args:
            script_name: 脚本唯一标识。

        Returns:
            周常副本列表；无声明时为空列表。
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
