"""游戏 / 脚本链接查询；完整链接统一声明于 script_resources.yml。"""

from src.config.script_resources import get_script_resources


def get_game_link(script_name: str, kind: str) -> str:
    """读取官网 / B 站 / GitHub 链接；未声明脚本返回空字符串。"""
    resources = get_script_resources(script_name)
    if resources is None:
        return ""
    return resources.links.select(kind)
