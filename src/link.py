"""游戏 / 脚本链接集中管理：官网、B 站、GitHub。

与各脚本 config 适配逻辑（src.config.set_config）解耦——链接不属于副本配置适配职责，
原散落在 set_config 的 ScriptConfig 链接类属性与拼接方法统一迁移至此。沿用 set_config
的基类 + 各脚本子类继承结构：基类 GameLink 声明链接默认空值并提供拼接方法，子类按
_script_name 覆盖链接元数据、经 @register 注册到 _LINKS。

背景图（background）属脚本资源元数据，归 set_config 声明、由背景控制器直接读取，不在此模块。
"""

import logging

logger = logging.getLogger(__name__)


class GameLink:
    """游戏/脚本链接基类；子类按 _script_name 声明链接元数据。"""

    _script_name: str = ""
    _bilibili: str = ""
    """官方 B 站 UID；空字符串走通用占位。"""
    _github: str = ""
    """脚本 GitHub repo 路径（不含域名）；空字符串走通用占位。"""
    _homepage: str = ""
    """官方主页链接；空字符串走通用占位。"""

    @classmethod
    def get_bilibili(cls) -> str:
        """读 B 站空间链接（子类存 UID，本方法拼 URL）；未声明 → 空字符串。"""
        return f"https://space.bilibili.com/{cls._bilibili}" if cls._bilibili else ""

    @classmethod
    def get_github(cls) -> str:
        """读 GitHub 链接（子类存 repo 路径，本方法拼 URL）；未声明 → 空字符串。"""
        return f"https://github.com/{cls._github}" if cls._github else ""

    @classmethod
    def get_homepage(cls) -> str:
        """读官方主页链接；未声明 → 空字符串。"""
        return cls._homepage


_LINKS: dict[str, type[GameLink]] = {}


def register(cls: type[GameLink]) -> type[GameLink]:
    """注册子类到 _LINKS，并校验必要声明。

    Args:
        cls: 待注册的 GameLink 子类。

    Returns:
        原样返回 cls（便于装饰器使用）。

    Raises:
        AssertionError: 缺少 _script_name，或任一链接属性未由子类显式声明。
    """
    assert cls._script_name, f"[link][{cls.__name__}] 必须声明 _script_name"
    for attr in ("_bilibili", "_github", "_homepage"):
        assert attr in cls.__dict__, f"[link][{cls.__name__}] 必须声明 {attr}"
    _LINKS[cls._script_name] = cls
    return cls


@register
class WutheringWavesLink(GameLink):
    _script_name = "ok-ww"
    _bilibili = "1955897084"
    _github = "ok-oldking/ok-wuthering-waves"
    _homepage = "https://mc.kurogames.com/"


@register
class GenshinLink(GameLink):
    _script_name = "BetterGI"
    _bilibili = "401742377"
    _github = "babalae/better-genshin-impact"
    _homepage = "https://ys.mihoyo.com/"


@register
class EndfieldLink(GameLink):
    _script_name = "ok-ef"
    _bilibili = "1265652806"
    _github = "AliceJump/ok-end-field"
    _homepage = "https://endfield.hypergryph.com/"


@register
class ZZZLink(GameLink):
    _script_name = "OneDragon-Launcher"
    _bilibili = "1636034895"
    _github = "DoctorReid/ZenlessZoneZero-OneDragon"
    _homepage = "https://zzz.mihoyo.com/"


@register
class HSRLink(GameLink):
    _script_name = "March7th-Launcher"
    _bilibili = "1340190821"
    _github = "moesnow/March7thAssistant"
    _homepage = "https://sr.mihoyo.com/"


@register
class NTELink(GameLink):
    _script_name = "ok-nte"
    _bilibili = "3546636978489848"
    _github = "BnanZ0/ok-nte"
    _homepage = "https://yh.wanmei.com/"


@register
class MAALink(GameLink):
    _script_name = "MAA"
    _bilibili = "161775300"
    _github = "MaaAssistantArknights/MaaAssistantArknights"
    _homepage = "https://ak.hypergryph.com/"


# 链接种类 → (GameLink 方法名, 是否需传 script_name)
_METHODS: dict[str, tuple[str, bool]] = {
    "bilibili": ("get_bilibili", False),
    "github": ("get_github", False),
    "homepage": ("get_homepage", False),
}


def get_game_link(script_name: str, kind: str) -> str:
    """按 kind 读取某脚本的链接；未注册脚本 → 空字符串。

    Args:
        script_name: 脚本标识名。
        kind: 链接种类，取值见 _METHODS 的键（bilibili/github/homepage）。

    Returns:
        对应链接字符串；未注册/缺失 → 空字符串。
    """
    if script_name not in _LINKS:
        return ""
    method, needs_arg = _METHODS[kind]
    cls = _LINKS[script_name]
    if needs_arg:
        return getattr(cls, method)(script_name)
    return getattr(cls, method)()
