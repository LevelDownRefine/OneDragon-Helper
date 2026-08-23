"""集中 YAML 读写（ruamel 单一引擎）。

统一全项目的 YAML 读写，避免散落各处的 PyYAML 残留。用 ruamel 而非 PyYAML：
PyYAML 1.1 把 ``04:10`` 这类时间字面量误当六十进制数解析成 ``250.0``，污染后续读取
与落盘；ruamel 按 YAML 1.2 解析并保持 ``"04:10"`` 为字符串，同时 ``preserve_quotes``
保留原引号、``width`` 防止长行折行破坏原排版。

设计原则（与项目「克制兜底」约定一致）：
- ``load_yaml`` 面向**必需**文件：缺失 / 空 / 非 dict 一律 ``assert`` 暴露，不静默兜底。
- ``load_yaml_optional`` 面向**可选**文件：缺失返回 ``{}``；但空 / 非 dict 仍 ``assert``，
  不把损坏文件静默当成「无内容」。
- ``dump_yaml`` 写回：接受原生 ``dict`` / ``list``（来自 load 返回值或上游构造）。
"""

import os

from ruamel.yaml import YAML

# 游戏 config 往返读写实例：保留注释 / 键序 / 原引号，并按 YAML 1.2 解析。
YAML_INSTANCE = YAML(typ="rt")
YAML_INSTANCE.preserve_quotes = True
YAML_INSTANCE.width = 4096  # 防止长行（长注释 / 列表）被折行破坏原排版

_yaml = YAML_INSTANCE  # 内部简写


def load_yaml(path: str) -> dict:
    """读取**必需** YAML 文件为 dict（ruamel，YAML 1.2 语义）。

    缺失 / 空 / 非 dict 一律 ``assert`` 暴露，不静默兜底——配置文件损坏属编程错误，
    应快速失败而非带病运行。

    Args:
        path: YAML 文件路径（必须存在且为合法 dict）。

    Returns:
        解析后的 dict（ruamel CommentedMap，可当原生 dict 用）。
    """
    assert os.path.exists(path), f"[yaml] 配置文件缺失: {path}"
    with open(path, encoding="utf-8") as f:
        data = _yaml.load(f)
    assert data is not None, f"[yaml] 配置文件为空: {path}"
    assert isinstance(data, dict), f"[yaml] 文件内容应为 dict: {path}"
    return data


def load_yaml_optional(path: str) -> dict:
    """读取**可选** YAML 文件为 dict（ruamel，YAML 1.2 语义）。

    与 ``load_yaml`` 的区别：文件缺失时返回 ``{}``（调用方按「无此可选配置」处理）。
    但文件存在却为空 / 非 dict 仍 ``assert``——损坏的可选文件不是「无内容」。

    Args:
        path: 可选 YAML 文件路径。

    Returns:
        解析后的 dict；文件缺失时为 ``{}``。
    """
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = _yaml.load(f)
    assert data is not None, f"[yaml] 可选配置文件为空: {path}"
    assert isinstance(data, dict), f"[yaml] 文件内容应为 dict: {path}"
    return data


def dump_yaml(path: str, data: dict | list) -> None:
    """将 dict / list 写回 YAML 文件（ruamel，保留注释/键序/引号，不重排键）。

    Args:
        path: 目标 YAML 文件路径。
        data: 待写入的 dict 或 list。
    """
    assert isinstance(data, (dict, list)), f"[yaml] 待写入内容应为 dict/list: {path}"
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(data, f)
