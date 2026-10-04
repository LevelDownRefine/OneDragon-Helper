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


def _format(path: str | Path, file_format: FileFormat | None) -> FileFormat:
    """优先采用显式格式，否则按文件扩展名判断。"""
    if file_format is not None:
        assert file_format in ("json", "yaml"), f"未知文件格式: {file_format}"
        return file_format
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in (".yaml", ".yml"):
        return "yaml"
    raise ValueError(f"不支持的配置文件格式: {suffix}")


def parse_data(content: str, *, file_format: FileFormat, cached: bool = False):
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
    *,
    cached: bool = False,
    file_format: FileFormat | None = None,
    encoding: str = "utf-8",
):
    """读取 JSON/YAML 文件；每次读盘，缓存仅避免重复解码。

    Args:
        path: 文件路径。
        cached: 是否按内容缓存解码结果，默认不缓存。
        file_format: 显式格式；省略时按扩展名判断。
        encoding: 文本编码，含 BOM 的外部资源可使用 utf-8-sig。

    Returns:
        解码后的独立数据；缺失和损坏文件的异常交由调用方处理。

    Raises:
        ValueError: 未指定格式且扩展名不受支持。
        OSError: 文件无法读取。
    """
    kind = _format(path, file_format)
    with open(path, encoding=encoding) as stream:
        content = stream.read()
    return parse_data(content, file_format=kind, cached=cached)


def dump_data_str(
    data: dict | list, *, file_format: FileFormat, indent: int = 4
) -> str:
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
    *,
    file_format: FileFormat | None = None,
    indent: int = 4,
    encoding: str = "utf-8",
) -> None:
    """先完整编码，再写临时文件并原子替换目标。

    Args:
        path: 目标文件路径，父目录由调用方准备。
        data: 配置字典或列表。
        file_format: 显式格式；省略时按扩展名判断。
        indent: JSON 缩进空格数。
        encoding: 写入编码。

    Raises:
        ValueError: 未指定格式且扩展名不受支持。
        OSError: 临时文件写入或目标替换失败。
    """
    text = dump_data_str(data, file_format=_format(path, file_format), indent=indent)
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding=encoding) as stream:
        stream.write(text)
    os.replace(temporary, path)


def load_yaml(path: str, *, cached: bool = True) -> dict:
    """读取**必需** YAML 文件为 dict（ruamel，YAML 1.2 语义）。

    缺失 / 空 / 非 dict 一律 ``assert`` 暴露，不静默兜底——配置文件损坏属编程错误，
    应快速失败而非带病运行。

    Args:
        path: YAML 文件路径（必须存在且为合法 dict）。
        cached: 是否复用相同内容的解码结果，默认启用。

    Returns:
        解析后的 dict（ruamel CommentedMap，可当原生 dict 用）。
    """
    assert os.path.exists(path), f"[yaml] 配置文件缺失: {path}"
    data = load_data(path, file_format="yaml", cached=cached)
    assert data is not None, f"[yaml] 配置文件为空: {path}"
    assert isinstance(data, dict), f"[yaml] 文件内容应为 dict: {path}"
    return data


def load_yaml_optional(path: str, *, cached: bool = True) -> dict:
    """读取**可选** YAML 文件为 dict（ruamel，YAML 1.2 语义）。

    与 ``load_yaml`` 的区别：文件缺失时返回 ``{}``（调用方按「无此可选配置」处理）。
    但文件存在却为空 / 非 dict 仍 ``assert``——损坏的可选文件不是「无内容」。

    Args:
        path: 可选 YAML 文件路径。
        cached: 是否复用相同内容的解码结果，默认启用。

    Returns:
        解析后的 dict；文件缺失时为 ``{}``。
    """
    if not os.path.exists(path):
        return {}
    data = load_data(path, file_format="yaml", cached=cached)
    assert data is not None, f"[yaml] 可选配置文件为空: {path}"
    assert isinstance(data, dict), f"[yaml] 文件内容应为 dict: {path}"
    return data


def _dump(path: str, data: dict | list) -> None:
    """rt 引擎写入的公共实现：原子写（tmp + os.replace）。

    写入中断不会留下截断的损坏 YAML——损坏兜底只是最后防线，不应靠它兜主动写入的锅。
    """
    assert isinstance(data, (dict, list)), f"[yaml] 待写入内容应为 dict/list: {path}"
    save_data(path, data, file_format="yaml")


def dump_yaml(path: str, data: dict | list) -> None:
    """将 dict / list 写回 YAML 文件（ruamel，保留注释/键序/引号，不重排键）。

    Args:
        path: 目标 YAML 文件路径。
        data: 待写入的 dict 或 list。
    """
    _dump(path, data)


def dump_yaml_file(path: str, data: dict | list) -> None:
    """将 dict / list 写回 YAML 文件（rt 引擎，纯数据场景用）。

    Args:
        path: 目标 YAML 文件路径。
        data: 待写入的 dict 或 list。
    """
    _dump(path, data)


def load_yaml_str(text: str) -> dict:
    """将 YAML 文本字符串解析为 dict（rt 引擎，用于测试读取 mock 文件内容）。

    Args:
        text: YAML 文本字符串。

    Returns:
        解析后的 dict（ruamel CommentedMap，可当原生 dict 用）。
    """
    return parse_data(text, file_format="yaml")


def dump_yaml_str(data: dict | list) -> str:
    """将 dict / list 序列化为 YAML 字符串（rt 引擎，用于测试构造 mock 文件内容）。

    PyYAML 的 ``yaml.dump(data)`` 直接返回字符串；ruamel 的 ``dump`` 需显式收集
    到流，本函数补齐该差异，使迁移无需逐处改写 stream 处理。

    Args:
        data: 待序列化的 dict 或 list。

    Returns:
        YAML 文本字符串。
    """
    return dump_data_str(data, file_format="yaml")
