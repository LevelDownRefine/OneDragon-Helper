"""config dict 的字段级工具：类型安全的写入与必填读取。

从 ``set_config.py`` 搬出来，好让配置规则层（``daily.Daily``）也能用而不与它循环导入。
日志前缀随之为模块名（``[safe_update]`` / ``[get_field]``），消息正文不变。
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _scalar_kind(value: Any) -> type:
    """归一化标量类型，用于类型一致性比较。

    ruamel.yaml 往返会把带引号字符串读成 ``str`` 的子类
    （如 ``DoubleQuotedScalarString``）、保留字读成对应子类。直接 ``type()``
    比较会误判为「类型不一致」。这里按真实语义归类，同时保留 ``bool`` 与
    ``int`` 的区分（``bool`` 是 ``int`` 的子类，但语义不同，必须分别对待）。

    Args:
        value: 待归类的标量值。

    Returns:
        归一化后的类型（bool / int / float / str 或原 type）。
    """
    if isinstance(value, bool):
        return bool
    if isinstance(value, int):
        return int
    if isinstance(value, float):
        return float
    if isinstance(value, str):
        return str
    # ruamel 容器是原生 list/dict 的子类（CommentedSeq/CommentedMap），
    # 归一为 list/dict，避免与下游传入的原生容器比较时被判「类型不一致」。
    if isinstance(value, list):
        return list
    if isinstance(value, dict):
        return dict
    return type(value)


def safe_update(
    config: dict,
    key: str,
    value: Any,
    display_name: str = "",
    assert_key_exists: bool = True,
) -> bool:
    """安全更新单字段，返回是否发生实际修改。

    Args:
        config: 待修改的 config dict。
        key: 目标字段名。
        value: 目标值，类型须与现字段语义一致（按 _scalar_kind 归一化比较，
            容忍 ruamel 的 str/bool 子类，同时避免 bool/int 混淆）。
        display_name: 日志与报错用的脚本展示名。
        assert_key_exists: True 时缺字段直接 assert；False 时缺字段则新增。

    Returns:
        字段值是否发生了改变。

    Raises:
        AssertionError: 缺字段（assert_key_exists=True）或新旧类型不一致。
    """
    if assert_key_exists:
        assert key in config, f"[safe_update][{display_name}] config 中缺少字段: {key}"
    elif key not in config:
        logger.warning(
            f"[safe_update][{display_name}] 添加新字段 config['{key}'] = {value}"
        )
        config[key] = value
        return True

    assert _scalar_kind(config[key]) is _scalar_kind(value), (
        f"[safe_update][{display_name}] 类型不一致: key={key}, "
        f"config={_scalar_kind(config[key]).__name__}, "
        f"value={_scalar_kind(value).__name__}"
    )

    if config[key] == value:
        return False

    config[key] = value
    logger.info(f"[safe_update][{display_name}] 更新 config['{key}'] 为 {value}")
    return True


def get_field(
    config: dict,
    key: str,
    display_name: str,
    type: type | None = None,
    context: str = "",
):
    """取必填字段，缺字段或类型不符时 assert 暴露。

    Args:
        config: 待读取的 dict。
        key: 字段名。
        display_name: 日志与报错用的脚本展示名。
        type: 期望类型；非 None 时做 isinstance 校验。
        context: 报错上下文标签（如所属操作名），用于定位。

    Returns:
        config[key] 的值。

    Raises:
        AssertionError: 缺字段，或指定 type 后类型不符。
    """
    prefix = f"[get_field][{display_name}]"
    if context:
        prefix += f"[{context}]"
    assert key in config, f"{prefix} 缺少 {key} 字段"
    value = config[key]
    if type is not None:
        assert isinstance(value, type), f"{prefix} {key} 必须是 {type.__name__}"
    return value
