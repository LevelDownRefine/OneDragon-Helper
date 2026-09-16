"""日常和周常共用的本地资源键路径读取。"""

from src.utils.utils_dict import get_field
from src.utils.utils_sub_config import load_game_config


def read_task_source(script_name: str, source: dict) -> list[str]:
    """按 path / key 读取选项；列表取值，字典取键，缺失资源返回空列表。"""
    assert source.keys() <= {"path", "key"}, "通用资源来源只支持 path / key"
    path = get_field(source, "path", script_name, str)
    keys = source["key"] if "key" in source else ()  # noqa: SIM401  # 键路径可省略
    assert isinstance(keys, (list, tuple)), "source.key 必须为键路径列表"
    data = load_game_config(script_name, path)
    if data is None or data == {} or data == []:
        return []
    for key in keys:
        assert isinstance(key, str) and key, "source.key 的每层键必须为非空字符串"
        assert isinstance(data, dict), (
            f"[{script_name}] {path} 的 {key!r} 父节点必须为字典"
        )
        data = get_field(data, key, script_name)
    assert isinstance(data, (list, dict)), (
        f"[{script_name}] {path} 的选项必须为列表或字典"
    )
    names = list(data)
    assert all(isinstance(name, str) and name for name in names), (
        f"[{script_name}] {path} 的选项名必须为非空字符串"
    )
    return names
