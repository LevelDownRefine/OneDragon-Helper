"""统一 YAML 读写（ruamel.yaml 往返模式）。

集中使用 ruamel.yaml 取代 PyYAML：保留注释 / 键序 / 原引号，且按 YAML 1.2
解析，避免 PyYAML 1.1 把 ``04:00`` 这类时间误判为六十进制数（→ ``240.0``）
污染落盘。

返回的容器是 ruamel 的 ``CommentedMap`` / ``CommentedSeq``，二者分别是
``dict`` / ``list`` 的子类，因此既有 ``.get()`` / 下标 / 迭代 / ``in`` 等
dict-like 操作照常可用（``isinstance(x, dict)`` 也成立）。
"""

from __future__ import annotations

from io import StringIO
from typing import Any

from ruamel.yaml import YAML

# 往返实例：typ="rt" 保留全部格式信息（注释 / 原引号 / 缩进 / 键序）。
_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
_yaml.width = 4096  # 防止长行（长注释 / 列表）被折行破坏原排版


def load_yaml(source: Any) -> Any:
    """从文件路径或已打开的文本文件对象加载 YAML。

    Args:
        source: 文件路径（str）或已打开的文本文件对象。

    Returns:
        ruamel ``CommentedMap`` / ``CommentedSeq``（分别为 ``dict`` / ``list`` 子类）；
        空文件返回 ``None``。
    """
    if isinstance(source, str):
        with open(source, encoding="utf-8") as f:
            return _yaml.load(f)
    return _yaml.load(source)


def load_yaml_text(text: str) -> Any:
    """从字符串加载 YAML。"""
    return _yaml.load(text)


def dump_yaml(data: Any, target: Any) -> None:
    """将 data 写入文件路径或已打开的文本文件对象（"w" 模式）。

    Args:
        data: 待序列化的 dict / list（或 ruamel 容器）。
        target: 文件路径（str）或已打开的文本文件对象。
    """
    if isinstance(target, str):
        with open(target, "w", encoding="utf-8") as f:
            _yaml.dump(data, f)
    else:
        _yaml.dump(data, target)


def dump_yaml_text(data: Any) -> str:
    """将 data 序列化为 YAML 字符串。"""
    buf = StringIO()
    _yaml.dump(data, buf)
    return buf.getvalue()
