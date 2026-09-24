"""脚本原生任务的开关：由 ``task_switch_list.yml`` 的声明选实现类与读写规则。

三种形态只描述同一件事 —— 「配置里哪些项是任务行、开关值落在哪个字典的哪个键上」，
即 ``_tasks``；枚举、白名单过滤与写回因此在基类里各只有一处，按行名（显示名）反查：

- ``task_pattern``：正则白名单形态，键名匹配该正则的顶层项即任务行，行名取第一个捕获组、
  值本身即开关（如 ok-ef 的 ``⭐`` 任务项）；值不是 bool 的项带子选项，不作开关。
- ``tasks_key`` + ``enabled_key``：双表形态，任务定义 ``{id: 任务名}`` 与任务启用
  ``{id: 开关}`` 两张键一致的表（如 BetterGI 的一条龙配置）。
- ``list_key`` + ``id_key`` + ``enabled_key``：应用列表形态，``{list_key: [{id_key: 标识,
  enabled_key: 开关}]}``（如绝区零的应用组、异环的计划任务）。

``names`` 三种形态共用：给了它就是白名单（只列出的行标识出现、行名取映射值）。脚本侧
改名或增删任务都会自动跟上。声明格式与校验只在本模块。
"""

import logging
import re
from copy import deepcopy
from functools import cache, lru_cache
from pathlib import Path, PureWindowsPath
from typing import NamedTuple

from src.utils import get_task_switch_list_yml_path_under_root
from src.utils.utils_sub_config import load_script_config, save_script_config
from src.utils.utils_yaml import load_yaml_str

logger = logging.getLogger(__name__)


class _NativeTask(NamedTuple):
    """脚本自带的（原生）一个任务：开关落在哪个字典的哪个键上，以及行标识与默认行名。

    ``ident`` 是各形态的原始标识（配置键名 / 任务 id / 应用标识），``names`` 白名单按它
    匹配；``name`` 是未给 ``names`` 时界面显示的名字。
    """

    ident: str
    name: str
    container: dict
    field: str


class TaskSwitch:
    """某脚本的原生任务开关基类。

    子类只实现 ``_tasks``（把配置归约成 ``_NativeTask``）与 ``from_declaration``；读取、
    白名单与写回都在基类。

    Args:
        script_name: 脚本标识名（与 config.yml 一致）。
        display_name: 脚本展示名（日志用）。
        config_rel_path: 该脚本的原生配置文件（相对脚本安装目录）。
        names: ``{行标识: 展示名}``；给了它即白名单（只列出的行才出现，行名取映射值），
            空 dict 表示全部行照原样（行名由各形态给）。
    """

    def __init__(
        self,
        script_name: str,
        display_name: str,
        config_rel_path: str,
        names: dict,
    ) -> None:
        self.script_name = script_name
        self.display_name = display_name
        self._config_rel_path = config_rel_path
        self._names = names

    def read(self) -> list[dict]:
        """枚举该脚本的原生任务与开关态。

        Returns:
            ``[{name, enabled}, ...]``，顺序与配置里的任务一致；配置或任务表缺失、某项
            无开关记录时按无该行处理。

        Raises:
            AssertionError: 开关值非 bool（声明与脚本实际不符）。
        """
        _, rows = self._resolve()
        result: list[dict] = []
        for name, task in rows:
            value = task.container.get(task.field)
            if value is None:
                logger.warning(
                    f"[task_switch][{self.display_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            assert isinstance(value, bool), (
                f"[task_switch][{self.display_name}] 任务 {name!r} 的开关必须为 bool: "
                f"{value!r}"
            )
            result.append({"name": name, "enabled": value})
        return result

    def write(self, states: dict[str, bool]) -> int:
        """按行名（任务名）写开关。

        Args:
            states: ``{任务名: 目标开关态}``。

        Returns:
            实际变更并落盘的项数；取值与现状一致的不计入，全无变更时不落盘。
        """
        if not states:
            return 0
        config, rows = self._resolve()
        if config is None:
            return 0
        changed = 0
        for name, value in states.items():
            task = self._task_of(rows, name)
            if task is None:
                logger.warning(
                    f"[task_switch][{self.display_name}] 未找到唯一的任务 {name!r}，跳过"
                )
                continue
            current = task.container.get(task.field)
            if current is None:
                logger.warning(
                    f"[task_switch][{self.display_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            if current == value:
                continue
            task.container[task.field] = value
            changed += 1
        if changed:
            save_script_config(
                self.script_name, self.display_name, self._config_rel_path, config
            )
        return changed

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        """把配置归约成原生任务行；声明与脚本实际不符（缺表、结构不对）时返回 None。

        Raises:
            NotImplementedError: 由子类实现。
        """
        raise NotImplementedError

    def _resolve(self) -> tuple[dict | None, list[tuple[str, _NativeTask]]]:
        """读原生配置并归约成 ``[(行名, _NativeTask)]``。

        配置或任务表缺失（脚本未安装、声明与实际不符）时 config 为 None、行表为空，
        读写两侧都按「无此特性」处理。

        ``names`` 给了就是白名单：只保留其中列出的行标识，行名取映射值。
        """
        config = self._load()
        if config is None:
            return None, []
        tasks = self._tasks(config)
        if tasks is None:
            return None, []
        rows: list[tuple[str, _NativeTask]] = []
        for task in tasks:
            if self._names and task.ident not in self._names:
                continue
            rows.append((self._names.get(task.ident, task.name), task))
        return config, rows

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

    @staticmethod
    def _task_of(rows: list[tuple[str, _NativeTask]], name: str) -> _NativeTask | None:
        """按行名反查任务；同名撞车（多个命中）返回 None，不猜目标。"""
        matches = [task for row_name, task in rows if row_name == name]
        return matches[0] if len(matches) == 1 else None


class PatternTaskSwitch(TaskSwitch):
    """正则白名单形态：键名匹配正则的顶层项即任务行，值本身即开关。

    Args:
        script_name: 脚本标识名。
        display_name: 脚本展示名（日志用）。
        config_rel_path: 原生配置文件（相对脚本安装目录）。
        pattern: 白名单正则，第一个捕获组即行标识；值不是 bool 的项不作开关。
        names: ``{捕获组: 展示名}``。
    """

    def __init__(
        self,
        script_name: str,
        display_name: str,
        config_rel_path: str,
        pattern: str,
        names: dict,
    ) -> None:
        super().__init__(script_name, display_name, config_rel_path, names)
        self._pattern = re.compile(pattern)

    @classmethod
    def from_declaration(
        cls, script_name: str, declaration: dict
    ) -> "PatternTaskSwitch":
        """取声明里的 config、task_pattern 与可选的 names。"""
        return cls(
            script_name,
            script_name,
            declaration["config"],
            declaration["task_pattern"],
            declaration.get("names", {}),
        )

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        tasks: list[_NativeTask] = []
        for key, value in config.items():
            match = self._pattern.fullmatch(key)
            if match is not None and isinstance(value, bool):
                tasks.append(_NativeTask(match.group(1), match.group(1), config, key))
        return tasks


class KeyPairTaskSwitch(TaskSwitch):
    """双表形态：任务定义 ``{id: 任务名}`` 与任务启用 ``{id: 开关}``，两张表键一致。

    行标识即任务 id，默认行名取定义表里的任务名。

    Args:
        script_name: 脚本标识名。
        display_name: 脚本展示名（日志用）。
        config_rel_path: 原生配置文件（相对脚本安装目录）。
        tasks_key: 任务定义表所在的顶层键。
        enabled_key: 任务启用表所在的顶层键。
        names: ``{任务 id: 展示名}``。
    """

    def __init__(
        self,
        script_name: str,
        display_name: str,
        config_rel_path: str,
        tasks_key: str,
        enabled_key: str,
        names: dict,
    ) -> None:
        super().__init__(script_name, display_name, config_rel_path, names)
        self._tasks_key = tasks_key
        self._enabled_key = enabled_key

    @classmethod
    def from_declaration(
        cls, script_name: str, declaration: dict
    ) -> "KeyPairTaskSwitch":
        """取声明里的 config、两张表的键与可选的 names。"""
        return cls(
            script_name,
            script_name,
            declaration["config"],
            declaration["tasks_key"],
            declaration["enabled_key"],
            declaration.get("names", {}),
        )

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        if self._tasks_key not in config or self._enabled_key not in config:
            logger.warning(
                f"[task_switch][{self.display_name}] 配置缺少任务表 "
                f"{self._tasks_key}/{self._enabled_key}，按无开关处理"
            )
            return None
        definitions = config[self._tasks_key]
        enabled = config[self._enabled_key]
        assert isinstance(definitions, dict) and isinstance(enabled, dict), (
            f"[task_switch][{self.display_name}] 任务表必须为字典"
        )
        tasks: list[_NativeTask] = []
        for task_id, name in definitions.items():
            assert isinstance(name, str) and name, (
                f"[task_switch][{self.display_name}] 任务名必须为非空字符串: {name!r}"
            )
            tasks.append(_NativeTask(task_id, name, enabled, task_id))
        return tasks


class AppListTaskSwitch(TaskSwitch):
    """应用列表形态：``{list_key: [{id_key: 标识, enabled_key: 开关}]}``。

    行标识即应用标识，默认行名与它相同。

    Args:
        script_name: 脚本标识名。
        display_name: 脚本展示名（日志用）。
        config_rel_path: 原生配置文件（相对脚本安装目录）。
        list_key: 列表所在的顶层键。
        id_key: 列表项里应用标识的键。
        enabled_key: 列表项里开关的键。
        names: ``{应用标识: 展示名}``。
    """

    def __init__(
        self,
        script_name: str,
        display_name: str,
        config_rel_path: str,
        list_key: str,
        id_key: str,
        enabled_key: str,
        names: dict,
    ) -> None:
        super().__init__(script_name, display_name, config_rel_path, names)
        self._list_key = list_key
        self._id_key = id_key
        self._enabled_key = enabled_key

    @classmethod
    def from_declaration(
        cls, script_name: str, declaration: dict
    ) -> "AppListTaskSwitch":
        """取声明里的列表三键与可选的 names。"""
        return cls(
            script_name,
            script_name,
            declaration["config"],
            declaration["list_key"],
            declaration["id_key"],
            declaration["enabled_key"],
            declaration.get("names", {}),
        )

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        if self._list_key not in config:
            logger.warning(
                f"[task_switch][{self.display_name}] 配置缺少应用列表 "
                f"{self._list_key}，按无开关处理"
            )
            return None
        items = config[self._list_key]
        assert isinstance(items, list), (
            f"[task_switch][{self.display_name}] 应用列表必须为列表"
        )
        tasks: list[_NativeTask] = []
        for item in items:
            assert isinstance(item, dict), (
                f"[task_switch][{self.display_name}] 应用列表项必须为字典"
            )
            assert self._id_key in item, (
                f"[task_switch][{self.display_name}] 应用列表项缺少 {self._id_key}"
            )
            app_id = item[self._id_key]
            assert isinstance(app_id, str) and app_id, (
                f"[task_switch][{self.display_name}] 应用标识必须为非空字符串: {app_id!r}"
            )
            tasks.append(_NativeTask(app_id, app_id, item, self._enabled_key))
        return tasks


#: 各形态共有的可选字段：names（白名单 + 展示名）
_OPTIONAL_FIELDS = frozenset({"names"})

#: 声明形态 → (必需字段, 可选字段, 实现类)；各形态字段集互不重叠
_FORMS: tuple[tuple[frozenset, frozenset, type[TaskSwitch]], ...] = (
    (frozenset({"config", "task_pattern"}), _OPTIONAL_FIELDS, PatternTaskSwitch),
    (
        frozenset({"config", "tasks_key", "enabled_key"}),
        _OPTIONAL_FIELDS,
        KeyPairTaskSwitch,
    ),
    (
        frozenset({"config", "list_key", "id_key", "enabled_key"}),
        _OPTIONAL_FIELDS,
        AppListTaskSwitch,
    ),
)


def _form_of(declaration: dict) -> type[TaskSwitch] | None:
    """匹配声明所属形态：必需字段齐且无多余字段；不属于任何形态时返回 None。"""
    fields = frozenset(declaration)
    for required, optional, cls in _FORMS:
        if required <= fields and fields <= (required | optional):
            return cls
    return None


def _single_group_pattern(text: str) -> bool:
    """正则可编译且恰好一个捕获组（行名取自它）。"""
    try:
        pattern = re.compile(text)
    except re.error:
        return False
    return pattern.groups == 1


def _validate_declaration(script_name: str, declaration) -> None:
    """声明节点须匹配某一形态，字段全为非空字符串，config 为脚本内相对路径。

    Raises:
        AssertionError: 字段缺失、多写、形态混用、取值非法，或正则不可用（编译失败／
            捕获组数不为 1，行名无从取）。
    """
    assert isinstance(declaration, dict), f"{script_name} 的任务开关声明必须为字典"
    assert _form_of(declaration) is not None, (
        f"{script_name} 的任务开关声明字段必须为 "
        + " 或 ".join(
            str(sorted(required)) + (f" + 可选 {sorted(optional)}" if optional else "")
            for required, optional, _ in _FORMS
        )
    )
    for field in sorted(declaration):
        if field in _OPTIONAL_FIELDS:
            continue
        value = declaration[field]
        assert isinstance(value, str) and value.strip(), (
            f"{script_name}/task_switch/{field} 必须为非空字符串"
        )
    path = PureWindowsPath(declaration["config"])
    assert not path.anchor and ".." not in path.parts, (
        f"{script_name}/task_switch/config 必须为脚本内相对路径"
    )
    if "task_pattern" in declaration:
        assert _single_group_pattern(declaration["task_pattern"]), (
            f"{script_name}/task_switch/task_pattern 必须是可编译且恰好一个捕获组的正则"
        )
    if "names" in declaration:
        names = declaration["names"]
        assert isinstance(names, dict), f"{script_name}/task_switch/names 必须为字典"
        for ident, name in names.items():
            assert isinstance(ident, str) and ident.strip(), (
                f"{script_name}/task_switch/names 的键必须为非空字符串"
            )
            assert isinstance(name, str) and name.strip(), (
                f"{script_name}/task_switch/names 的值必须为非空字符串"
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
    declaration = declarations[script_name]
    cls = _form_of(declaration)
    assert cls is not None, f"[task_switch] {script_name} 的声明形态未校验通过"
    return cls.from_declaration(script_name, declaration)
