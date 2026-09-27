"""内置资源声明：只描述位置，路径解析与脚本机制仍由 Python 实现。"""

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from urllib.parse import urlsplit

from src.utils import get_root_dir
from src.utils.utils_yaml import load_yaml


@dataclass(frozen=True)
class GamePath:
    config: str = ""
    keys: tuple[str, ...] = ()
    launcher: str = ""


@dataclass(frozen=True)
class LogPath:
    root: str
    path: str

    def resolve(self, script_path: str) -> Path:
        """script_path 是调用者已解析的脚本路径；临时目录由当前系统提供。"""
        if self.root == "temp":
            base = Path(tempfile.gettempdir())
        else:
            assert self.root == "script"
            base = Path(script_path.replace("\\", "/")).parent
        return base / self.path


@dataclass(frozen=True)
class ScriptLinks:
    homepage: str = ""
    bilibili: str = ""
    github: str = ""

    def select(self, kind: str) -> str:
        assert kind in {"homepage", "bilibili", "github"}, f"未知链接种类: {kind}"
        return getattr(self, kind)


@dataclass(frozen=True)
class ScriptResources:
    backup_paths: tuple[str, ...] = ()
    game: GamePath = GamePath()
    background: str = ""
    template: str = ""
    logs: LogPath | None = None
    links: ScriptLinks = ScriptLinks()


def _fields(value, required: set[str], optional: set[str], context: str) -> None:
    assert isinstance(value, dict), f"{context} 必须为映射"
    assert required <= value.keys(), f"{context} 缺少字段: {required - value.keys()}"
    assert value.keys() <= required | optional, f"{context} 含未知字段"


def _text(value, context: str) -> str:
    assert isinstance(value, str) and value.strip(), f"{context} 必须为非空字符串"
    return value


def _relative_path(value, context: str) -> str:
    _text(value, context)
    path = PureWindowsPath(value)
    assert (
        not path.anchor
        and ".." not in path.parts
        and value == value.strip()
        and "\\" not in value
        and ":" not in value
        and all(part not in {"", "."} for part in value.split("/"))
    ), f"{context} 必须为使用 / 分隔的根目录内相对路径: {value!r}"
    return value


def _url(value, context: str) -> str:
    _text(value, context)
    url = urlsplit(value)
    assert (
        url.scheme in {"http", "https"}
        and url.hostname
        and not url.username
        and not url.password
        and not any(char.isspace() for char in value)
    ), f"{context} 必须为完整 HTTP(S) 链接"
    return value


def _parse_script(value: dict, name: str) -> ScriptResources:
    _fields(
        value,
        {"backup_paths", "links"},
        {"game", "background", "template", "logs"},
        name,
    )
    assert "backup_paths" in value and "links" in value
    paths = value["backup_paths"]
    assert isinstance(paths, list) and paths, f"{name}/backup_paths 必须为非空列表"
    paths = tuple(_relative_path(path, f"{name}/backup_paths") for path in paths)
    assert len({path.casefold() for path in paths}) == len(paths), (
        f"{name}/backup_paths 含重复路径"
    )
    game = GamePath()
    if "game" in value:
        node = value["game"]
        _fields(node, {"config", "keys"}, {"launcher"}, f"{name}/game")
        assert "config" in node and "keys" in node
        keys = node["keys"]
        assert isinstance(keys, list) and keys, f"{name}/game/keys 必须为非空键列表"
        game = GamePath(
            config=_relative_path(node["config"], f"{name}/game/config"),
            keys=tuple(_text(key, f"{name}/game/keys") for key in keys),
            launcher=(
                _relative_path(node["launcher"], f"{name}/game/launcher")
                if "launcher" in node
                else ""
            ),
        )
    logs = None
    if "logs" in value:
        node = value["logs"]
        _fields(node, {"root", "path"}, set(), f"{name}/logs")
        assert "root" in node and "path" in node
        assert isinstance(node["root"], str) and node["root"] in {"script", "temp"}, (
            f"{name}/logs/root 只支持 script / temp"
        )
        logs = LogPath(node["root"], _relative_path(node["path"], f"{name}/logs/path"))
    links = value["links"]
    _fields(links, {"homepage", "bilibili", "github"}, set(), f"{name}/links")
    return ScriptResources(
        backup_paths=paths,
        game=game,
        background=(
            _relative_path(value["background"], f"{name}/background")
            if "background" in value
            else ""
        ),
        template=(
            _relative_path(value["template"], f"{name}/template")
            if "template" in value
            else ""
        ),
        logs=logs,
        links=ScriptLinks(
            **{kind: _url(url, f"{name}/links/{kind}") for kind, url in links.items()}
        ),
    )


@lru_cache(maxsize=8)
def load_resource_manifest(path: str) -> Mapping[str, ScriptResources]:
    """随程序发布的静态声明；按文件位置缓存，更新声明后重启生效。"""
    data = load_yaml(path)
    _fields(data, {"version", "scripts"}, set(), "script_resources")
    assert "version" in data and "scripts" in data
    assert type(data["version"]) is int and data["version"] == 1, "资源声明版本必须为 1"
    scripts = data["scripts"]
    assert isinstance(scripts, dict) and scripts, "scripts 必须为非空映射"
    return MappingProxyType(
        {
            _text(name, "script_name"): _parse_script(value, name)
            for name, value in scripts.items()
        }
    )


def get_script_resources(script_name: str) -> ScriptResources | None:
    """未声明脚本返回 None；声明文件缺失或损坏直接报错，不回退到硬编码。"""
    path = str(Path(get_root_dir()) / "config" / "script_resources.yml")
    resources = load_resource_manifest(path)
    if script_name not in resources:
        return None
    assert script_name in resources
    return resources[script_name]
