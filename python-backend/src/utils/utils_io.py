"""JSON/YAML 文件读写；按内容缓存解码结果，不解释业务字段。"""

import io
import json
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Literal

from ruamel.yaml import YAML

FileFormat = Literal["json", "yaml"]

YAML_INSTANCE = YAML(typ="rt")
YAML_INSTANCE.preserve_quotes = True
YAML_INSTANCE.width = 4096


@lru_cache(maxsize=16)
def _parse_yaml(content: str):
    """按文本内容缓存 YAML 解码结果，副本由调用方生成。"""
    return YAML_INSTANCE.load(content)


@lru_cache(maxsize=16)
def _parse_json(content: str):
    """按文本内容缓存 JSON 解码结果，副本由调用方生成。"""
    return json.loads(content)


def parse_data(content: str, file_format: FileFormat, cached: bool = False):
    """解码 JSON/YAML 文本，不校验业务结构。

    Args:
        content: 已解码的文本。
        file_format: 文本格式。
        cached: 是否按内容复用解码结果；缓存结果返回独立副本。

    Returns:
        解码后的数据，保留 YAML 注释、引号及键序。
    """
    assert file_format in ("json", "yaml"), f"未知文件格式: {file_format}"
    if cached:
        parse = _parse_json if file_format == "json" else _parse_yaml
        return deepcopy(parse(content))
    return json.loads(content) if file_format == "json" else YAML_INSTANCE.load(content)


def load_data(
    path: str | Path,
    file_format: FileFormat,
    cached: bool = False,
    encoding: str = "utf-8",
):
    """读取 JSON/YAML 文件；每次读盘，缓存仅避免重复解码。

    Args:
        path: 文件路径。
        file_format: 文件格式，由调用方显式指定。
        cached: 是否按内容缓存解码结果，默认不缓存。
        encoding: 文本编码，含 BOM 的外部资源可使用 utf-8-sig。

    Returns:
        解码后的独立数据；缺失和损坏文件的异常交由调用方处理。

    Raises:
        OSError: 文件无法读取。
    """
    assert file_format in ("json", "yaml"), f"未知文件格式: {file_format}"
    with open(path, encoding=encoding) as stream:
        content = stream.read()
    return parse_data(content, file_format=file_format, cached=cached)


def dump_data_str(data: dict | list, file_format: FileFormat, indent: int = 4) -> str:
    """编码配置数据，保留 YAML 注释与引号。

    Args:
        data: 配置字典或列表。
        file_format: 目标格式。
        indent: JSON 缩进空格数。

    Returns:
        编码后的文本。
    """
    assert isinstance(data, (dict, list)), "待保存配置必须为 dict/list"
    assert file_format in ("json", "yaml"), f"未知文件格式: {file_format}"
    if file_format == "json":
        return json.dumps(data, ensure_ascii=False, indent=indent)
    stream = io.StringIO()
    YAML_INSTANCE.dump(data, stream)
    return stream.getvalue()


def save_data(
    path: str | Path,
    data: dict | list,
    file_format: FileFormat,
    indent: int = 4,
    encoding: str = "utf-8",
) -> None:
    """先完整编码，再写临时文件并原子替换目标。

    Args:
        path: 目标文件路径，父目录由调用方准备。
        data: 配置字典或列表。
        file_format: 文件格式，由调用方显式指定。
        indent: JSON 缩进空格数。
        encoding: 写入编码。

    Raises:
        OSError: 临时文件写入或目标替换失败。
    """
    text = dump_data_str(data, file_format=file_format, indent=indent)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding=encoding) as stream:
        stream.write(text)
    os.replace(temporary, path)
