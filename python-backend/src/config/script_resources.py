"""内置资源声明：只描述位置，路径解析与脚本机制仍由 Python 实现。"""

from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Literal, NotRequired, TypedDict, cast
from urllib.parse import urlsplit

from src.utils import get_root_dir
from src.utils.utils_yaml import load_yaml


class GamePath(TypedDict):
    config: str
    keys: list[str]
    launcher: NotRequired[str]


class LogPath(TypedDict):
    root: Literal["script", "temp"]
    path: str


class ScriptResources(TypedDict):
    backup_paths: list[str]
    links: dict[str, str]
    game: NotRequired[GamePath]
    background: NotRequired[str]
    logs: NotRequired[LogPath]


def _fields(value, required: set[str], optional: set[str], context: str) -> None:
    assert isinstance(value, dict), f"{context} 必须为映射"
    assert required <= value.keys(), f"{context} 缺少字段: {required - value.keys()}"
    assert value.keys() <= required | optional, f"{context} 含未知字段"


def _text(value, context: str) -> None:
    assert isinstance(value, str) and value.strip(), f"{context} 必须为非空字符串"


def _relative_path(value, context: str) -> None:
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


def _url(value, context: str) -> None:
    _text(value, context)
    url = urlsplit(value)
    assert (
        url.scheme in {"http", "https"}
        and url.hostname
        and not url.username
        and not url.password
        and not any(char.isspace() for char in value)
    ), f"{context} 必须为完整 HTTP(S) 链接"


def _validate_script(value: dict, name: str) -> None:
    _fields(
        value,
        {"backup_paths", "links"},
        {"game", "background", "logs"},
        name,
    )
    assert "backup_paths" in value and "links" in value
    paths = value["backup_paths"]
    assert isinstance(paths, list) and paths, f"{name}/backup_paths 必须为非空列表"
    for path in paths:
        _relative_path(path, f"{name}/backup_paths")
    assert len({path.casefold() for path in paths}) == len(paths), (
        f"{name}/backup_paths 含重复路径"
    )
    if "game" in value:
        node = value["game"]
        _fields(node, {"config", "keys"}, {"launcher"}, f"{name}/game")
        assert "config" in node and "keys" in node
        keys = node["keys"]
        assert isinstance(keys, list) and keys, f"{name}/game/keys 必须为非空键列表"
        _relative_path(node["config"], f"{name}/game/config")
        for key in keys:
            _text(key, f"{name}/game/keys")
        if "launcher" in node:
            _relative_path(node["launcher"], f"{name}/game/launcher")
    if "logs" in value:
        node = value["logs"]
        _fields(node, {"root", "path"}, set(), f"{name}/logs")
        assert "root" in node and "path" in node
        assert isinstance(node["root"], str) and node["root"] in {"script", "temp"}, (
            f"{name}/logs/root 只支持 script / temp"
        )
        _relative_path(node["path"], f"{name}/logs/path")
    if "background" in value:
        _relative_path(value["background"], f"{name}/background")
    links = value["links"]
    _fields(links, {"homepage", "bilibili", "github"}, set(), f"{name}/links")
    for kind, url in links.items():
        _url(url, f"{name}/links/{kind}")


@lru_cache(maxsize=8)
def load_resource_manifest(path: str) -> dict[str, ScriptResources]:
    """校验并缓存 YAML 字典；调用方只读，更新声明后重启生效。"""
    data = load_yaml(path)
    _fields(data, {"version", "scripts"}, set(), "script_resources")
    assert "version" in data and "scripts" in data
    assert type(data["version"]) is int and data["version"] == 1, "资源声明版本必须为 1"
    scripts = data["scripts"]
    assert isinstance(scripts, dict) and scripts, "scripts 必须为非空映射"
    for name, value in scripts.items():
        _text(name, "script_name")
        _validate_script(value, name)
    return cast(dict[str, ScriptResources], scripts)


def get_script_resources(script_name: str) -> ScriptResources | None:
    """未声明脚本返回 None；声明文件缺失或损坏直接报错，不回退到硬编码。"""
    path = str(Path(get_root_dir()) / "config" / "script_resources.yml")
    resources = load_resource_manifest(path)
    if script_name not in resources:
        return None
    assert script_name in resources
    return resources[script_name]
