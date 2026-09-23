"""脚本原生任务的开关：由 ``task_switch_list.yml`` 声明解析出的枚举与读写规则。

声明给出该脚本的原生配置文件与其两张表（任务定义 ``{id: 任务名}`` 与任务启用
``{id: 开关}``，键一致）。本模块把两表合成为配置弹窗可用的行（行名即任务名），并按行名
反查 id 写回开关，故脚本侧改名或增删任务都会自动跟上。声明格式与校验只在本模块。
"""

import logging
from copy import deepcopy
from functools import cache, lru_cache
from pathlib import Path, PureWindowsPath

from src.utils import get_task_switch_list_yml_path_under_root
from src.utils.utils_sub_config import load_script_config, save_script_config
from src.utils.utils_yaml import load_yaml_str

logger = logging.getLogger(__name__)

_DECLARATION_FIELDS = {"config", "tasks_key", "enabled_key"}


class TaskSwitch:
    """某脚本的原生任务开关。

    Args:
        script_name: 脚本标识名（与 config.yml 一致）。
        declaration: 该脚本在 ``task_switch_list.yml`` 里的声明节点。
        display_name: 脚本展示名（日志用）。
    """

    def __init__(self, script_name: str, declaration: dict, display_name: str) -> None:
        self.script_name = script_name
        self.display_name = display_name
        self._config_rel_path = declaration["config"]
        self._tasks_key = declaration["tasks_key"]
        self._enabled_key = declaration["enabled_key"]

    def read(self) -> list[dict]:
        """枚举该脚本的原生任务与开关态。

        Returns:
            ``[{name, enabled}, ...]``，顺序与配置里的任务定义一致；配置或任务表缺失、
            某项无开关记录时按无该行处理。

        Raises:
            AssertionError: 任务名非字符串，或开关值非 bool（声明与脚本实际不符）。
        """
        config = self._load()
        if config is None:
            return []
        tables = self._tables(config)
        if tables is None:
            return []
        tasks, enabled = tables
        rows: list[dict] = []
        for task_id, name in tasks.items():
            assert isinstance(name, str) and name, (
                f"[task_switch][{self.display_name}] 任务名必须为非空字符串: {name!r}"
            )
            if task_id not in enabled:
                logger.warning(
                    f"[task_switch][{self.display_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            value = enabled[task_id]
            assert isinstance(value, bool), (
                f"[task_switch][{self.display_name}] 任务 {name!r} 的开关必须为 bool: "
                f"{value!r}"
            )
            rows.append({"name": name, "enabled": value})
        return rows

    def write(self, states: dict[str, bool]) -> int:
        """按行名（任务名）写开关。

        Args:
            states: ``{任务名: 目标开关态}``。

        Returns:
            实际变更并落盘的项数；取值与现状一致的不计入，全无变更时不落盘。

        Raises:
            AssertionError: 任务表非字典（声明与脚本实际不符）。
        """
        if not states:
            return 0
        config = self._load()
        if config is None:
            return 0
        tables = self._tables(config)
        if tables is None:
            return 0
        tasks, enabled = tables
        changed = 0
        for name, value in states.items():
            task_id = self._task_id_of(tasks, name)
            if task_id is None:
                logger.warning(
                    f"[task_switch][{self.display_name}] 未找到唯一的任务 {name!r}，跳过"
                )
                continue
            if task_id not in enabled:
                logger.warning(
                    f"[task_switch][{self.display_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            if enabled[task_id] == value:
                continue
            enabled[task_id] = value
            changed += 1
        if changed:
            save_script_config(
                self.script_name, self.display_name, self._config_rel_path, config
            )
        return changed

    def _load(self) -> dict | None:
        """读原生配置；缺失（脚本未安装/未配置）或内容损坏返回 None。

        读写两侧都按 None 处理：开关不作为保存的前置条件，安装目录变动时配置弹窗
        保存不应因此报错。
        """
        return load_script_config(
            self.script_name,
            self.display_name,
            self._config_rel_path,
            allow_missing=True,
        )

    def _tables(self, config: dict) -> tuple[dict, dict] | None:
        """取任务定义表与启用表；缺任一表返回 None（声明与脚本版本不匹配）。"""
        if self._tasks_key not in config or self._enabled_key not in config:
            logger.warning(
                f"[task_switch][{self.display_name}] 配置缺少任务表 "
                f"{self._tasks_key}/{self._enabled_key}，按无开关处理"
            )
            return None
        tasks = config[self._tasks_key]
        enabled = config[self._enabled_key]
        assert isinstance(tasks, dict) and isinstance(enabled, dict), (
            f"[task_switch][{self.display_name}] 任务表必须为字典"
        )
        return tasks, enabled

    @staticmethod
    def _task_id_of(tasks: dict, name: str) -> str | None:
        """按任务名反查 id；同名撞车（多个命中）返回 None，不猜目标。"""
        matches = [task_id for task_id, task_name in tasks.items() if task_name == name]
        return matches[0] if len(matches) == 1 else None


def _validate_declaration(script_name: str, declaration) -> None:
    """声明节点必须是三个非空字符串字段，且 config 为脚本内相对路径。

    Raises:
        AssertionError: 字段缺失、多写或取值非法。
    """
    assert isinstance(declaration, dict), f"{script_name} 的任务开关声明必须为字典"
    assert set(declaration) == _DECLARATION_FIELDS, (
        f"{script_name} 的任务开关声明字段必须为 {sorted(_DECLARATION_FIELDS)}"
    )
    for field in sorted(_DECLARATION_FIELDS):
        value = declaration[field]
        assert isinstance(value, str) and value.strip(), (
            f"{script_name}/task_switch/{field} 必须为非空字符串"
        )
    path = PureWindowsPath(declaration["config"])
    assert not path.anchor and ".." not in path.parts, (
        f"{script_name}/task_switch/config 必须为脚本内相对路径"
    )


def load_task_switch_map() -> dict[str, dict]:
    """取得任务开关声明（``{脚本标识: 声明节点}``）。

    Returns:
        声明字典的独立副本。

    Raises:
        AssertionError: 声明文件缺失、内容非字典或某条声明非法。
    """
    path = get_task_switch_list_yml_path_under_root()
    file = Path(path)
    assert file.is_file(), f"任务开关声明缺失: {path}"
    return deepcopy(_parse_declarations(file.read_text(encoding="utf-8")))


@lru_cache(maxsize=2)
def _parse_declarations(content: str) -> dict[str, dict]:
    """以内容为缓存键，避免同大小、同时间戳的文件替换读到旧声明。"""
    data = load_yaml_str(content)
    assert isinstance(data, dict), "任务开关声明必须是字典"
    for script_name, declaration in data.items():
        _validate_declaration(script_name, declaration)
    return data


@cache
def task_switch_of(script_name: str) -> TaskSwitch | None:
    """取某脚本的任务开关。

    Args:
        script_name: 脚本标识名。

    Returns:
        该脚本的开关对象；声明文件里没有该脚本时为 None。
    """
    declarations = load_task_switch_map()
    if script_name not in declarations:
        return None
    return TaskSwitch(script_name, declarations[script_name], script_name)
