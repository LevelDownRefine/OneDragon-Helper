"""脚本原生任务的开关：由 ``task_switch_list.yml`` 的声明选实现类与读写规则。

一个脚本可以声明一条或多条「段」（同一脚本的开关常散在同一个文件的不同键上），每段只
描述同一件事 —— 「配置里哪些项是任务行、开关值落在哪里」，即 ``_tasks``；枚举、``names``
过滤与写回因此各只有一处，按行名（显示名）反查：

- ``task_pattern``：正则白名单形态，键名匹配该正则的顶层项即任务行，行名取第一个捕获组、
  值本身即开关（如 ok-ef 的 ``⭐`` 任务项）；值不是 bool 的项带子选项，不作开关。
- ``tasks_key`` + ``enabled_key``：双表形态，任务定义 ``{id: 任务名}`` 与任务启用
  ``{id: 开关}`` 两张键一致的表（如 BetterGI 的一条龙配置）。
- ``list_key`` + ``id_key`` + ``enabled_key``：应用列表形态，``{list_key: [{id_key: 标识,
  enabled_key: 开关}]}``（如绝区零的应用组、异环的计划任务）。
- ``list_key`` + ``names``：多选形态，``{list_key: [已选中的标识]}`` —— **在列表里即在跑**
  （如 ok-ww 的附加任务）。候选项只存在于脚本源码，配置里只有已选中的，故 ``names``
  必填、即全部候选。

``names`` 各形态共用：给了它就是白名单（只列出的行标识出现、行名取映射值），也可写成
``[标识]`` 列表（行名即标识）。多段声明的段写在 ``segments`` 下，节点级的 ``config`` 作为
各段默认。声明格式与校验集中于 task_parser，本模块负责机制装配及原生配置读写。
"""

import logging
import re
from functools import cache
from pathlib import Path
from typing import NamedTuple

from src.config.task_parser import parse_task_switch_map, switch_form
from src.utils import get_task_switch_list_yml_path_under_root
from src.utils.utils_io import load_data
from src.utils.utils_sub_config import load_script_config, save_script_config

logger = logging.getLogger(__name__)


class _DictSlot(NamedTuple):
    """开关落在 ``container[field]`` 上（正则 / 双表 / 应用列表三种形态）。"""

    container: dict
    field: str

    def get(self) -> bool | None:
        """取开关值；该键无记录时返回 None。"""
        return self.container.get(self.field)

    def set(self, value: bool) -> None:
        self.container[self.field] = value


class _MemberSlot(NamedTuple):
    """开关即「``item`` 在不在 ``items`` 里」（多选形态）。"""

    items: list
    item: str

    def get(self) -> bool:
        return self.item in self.items

    def set(self, value: bool) -> None:
        if value and self.item not in self.items:
            self.items.append(self.item)
        elif not value and self.item in self.items:
            self.items.remove(self.item)


class _NativeTask(NamedTuple):
    """脚本自带的（原生）一个任务：行标识、默认行名，以及开关值的落点。

    ``ident`` 是各形态的原始标识（配置键名 / 任务 id / 应用标识 / 列表成员本身），
    ``names`` 白名单按它匹配；``name`` 是未给 ``names`` 时界面显示的名字。
    """

    ident: str
    name: str
    slot: _DictSlot | _MemberSlot


class _Segment:
    """一条声明段：一种形态，把该段配置归约成 ``_NativeTask``。

    子类只实现 ``_tasks`` 与 ``from_declaration``；读取、``names`` 过滤与写回都在基类。

    Args:
        script_name: 脚本标识名（与 config.yml 一致）。
        config_rel_path: 该段对应的原生配置文件（相对脚本安装目录）。
        names: ``{行标识: 展示名}``；给了它即白名单（只列出的行才出现，行名取映射值），
            空 dict 表示全部行照原样（行名由各形态给）。
    """

    def __init__(self, script_name: str, config_rel_path: str, names: dict) -> None:
        self.script_name = script_name
        self._config_rel_path = config_rel_path
        self._names = names

    def read(self) -> list[dict]:
        """枚举该段的任务与开关态。

        Returns:
            ``[{name, enabled}, ...]``，顺序与配置里的任务一致；配置或任务表缺失、某项
            无开关记录时按无该行处理。

        Raises:
            AssertionError: 开关值非 bool（声明与脚本实际不符）。
        """
        _, rows = self._resolve()
        result: list[dict] = []
        for name, task in rows:
            value = task.slot.get()
            if value is None:
                logger.warning(
                    f"[task_switch][{self.script_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            assert isinstance(value, bool), (
                f"[task_switch][{self.script_name}] 任务 {name!r} 的开关必须为 bool: "
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
                    f"[task_switch][{self.script_name}] 未找到唯一的任务 {name!r}，跳过"
                )
                continue
            current = task.slot.get()
            if current is None:
                logger.warning(
                    f"[task_switch][{self.script_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            if current == value:
                continue
            task.slot.set(value)
            changed += 1
        if changed:
            save_script_config(
                self.script_name, self.script_name, self._config_rel_path, config
            )
        return changed

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        """把配置归约成任务行；声明与脚本实际不符（缺表、结构不对）时返回 None。

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
            self.script_name,
            self._config_rel_path,
            allow_missing=True,
        )

    @staticmethod
    def _task_of(rows: list[tuple[str, _NativeTask]], name: str) -> _NativeTask | None:
        """按行名反查任务；同名撞车（多个命中）返回 None，不猜目标。"""
        matches = [task for row_name, task in rows if row_name == name]
        return matches[0] if len(matches) == 1 else None


class PatternSegment(_Segment):
    """正则白名单形态：键名匹配正则的顶层项即任务行，值本身即开关。

    Args:
        script_name: 脚本标识名。
        config_rel_path: 原生配置文件（相对脚本安装目录）。
        pattern: 白名单正则，第一个捕获组即行标识；值不是 bool 的项不作开关。
        names: ``{捕获组: 展示名}``。
    """

    def __init__(
        self,
        script_name: str,
        config_rel_path: str,
        pattern: str,
        names: dict,
    ) -> None:
        super().__init__(script_name, config_rel_path, names)
        self._pattern = re.compile(pattern)

    @classmethod
    def from_declaration(cls, script_name: str, declaration: dict) -> "PatternSegment":
        """取声明里的 config、task_pattern 与可选的 names。"""
        return cls(
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
                tasks.append(
                    _NativeTask(match.group(1), match.group(1), _DictSlot(config, key))
                )
        return tasks


class KeyPairSegment(_Segment):
    """双表形态：任务定义 ``{id: 任务名}`` 与任务启用 ``{id: 开关}``，两张表键一致。

    行标识即任务 id，默认行名取定义表里的任务名。

    Args:
        script_name: 脚本标识名。
        config_rel_path: 原生配置文件（相对脚本安装目录）。
        tasks_key: 任务定义表所在的顶层键。
        enabled_key: 任务启用表所在的顶层键。
        names: ``{任务 id: 展示名}``。
    """

    def __init__(
        self,
        script_name: str,
        config_rel_path: str,
        tasks_key: str,
        enabled_key: str,
        names: dict,
    ) -> None:
        super().__init__(script_name, config_rel_path, names)
        self._tasks_key = tasks_key
        self._enabled_key = enabled_key

    @classmethod
    def from_declaration(cls, script_name: str, declaration: dict) -> "KeyPairSegment":
        """取声明里的 config、两张表的键与可选的 names。"""
        return cls(
            script_name,
            declaration["config"],
            declaration["tasks_key"],
            declaration["enabled_key"],
            declaration.get("names", {}),
        )

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        if self._tasks_key not in config or self._enabled_key not in config:
            logger.warning(
                f"[task_switch][{self.script_name}] 配置缺少任务表 "
                f"{self._tasks_key}/{self._enabled_key}，按无开关处理"
            )
            return None
        definitions = config[self._tasks_key]
        enabled = config[self._enabled_key]
        assert isinstance(definitions, dict) and isinstance(enabled, dict), (
            f"[task_switch][{self.script_name}] 任务表必须为字典"
        )
        tasks: list[_NativeTask] = []
        for task_id, name in definitions.items():
            assert isinstance(name, str) and name, (
                f"[task_switch][{self.script_name}] 任务名必须为非空字符串: {name!r}"
            )
            tasks.append(_NativeTask(task_id, name, _DictSlot(enabled, task_id)))
        return tasks


class AppListSegment(_Segment):
    """应用列表形态：``{list_key: [{id_key: 标识, enabled_key: 开关}]}``。

    行标识即应用标识，默认行名与它相同。

    Args:
        script_name: 脚本标识名。
        config_rel_path: 原生配置文件（相对脚本安装目录）。
        list_key: 列表所在的顶层键。
        id_key: 列表项里应用标识的键。
        enabled_key: 列表项里开关的键。
        names: ``{应用标识: 展示名}``。
    """

    def __init__(
        self,
        script_name: str,
        config_rel_path: str,
        list_key: str,
        id_key: str,
        enabled_key: str,
        names: dict,
    ) -> None:
        super().__init__(script_name, config_rel_path, names)
        self._list_key = list_key
        self._id_key = id_key
        self._enabled_key = enabled_key

    @classmethod
    def from_declaration(cls, script_name: str, declaration: dict) -> "AppListSegment":
        """取声明里的列表三键与可选的 names。"""
        return cls(
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
                f"[task_switch][{self.script_name}] 配置缺少应用列表 "
                f"{self._list_key}，按无开关处理"
            )
            return None
        items = config[self._list_key]
        assert isinstance(items, list), (
            f"[task_switch][{self.script_name}] 应用列表必须为列表"
        )
        tasks: list[_NativeTask] = []
        for item in items:
            assert isinstance(item, dict), (
                f"[task_switch][{self.script_name}] 应用列表项必须为字典"
            )
            assert self._id_key in item, (
                f"[task_switch][{self.script_name}] 应用列表项缺少 {self._id_key}"
            )
            app_id = item[self._id_key]
            assert isinstance(app_id, str) and app_id, (
                f"[task_switch][{self.script_name}] 应用标识必须为非空字符串: {app_id!r}"
            )
            tasks.append(
                _NativeTask(app_id, app_id, _DictSlot(item, self._enabled_key))
            )
        return tasks


class MultiSelectSegment(_Segment):
    """多选形态：``{list_key: [已选中的标识]}``，在列表里即在跑。

    候选项只存在于脚本源码（配置里只有已选中的），故行集合取自 ``names`` —— 没列出的
    标识既不出行也无从勾选，声明必须列全。

    Args:
        script_name: 脚本标识名。
        config_rel_path: 原生配置文件（相对脚本安装目录）。
        list_key: 字符串列表所在的顶层键。
        names: ``{列表成员: 展示名}``，即全部候选项。
    """

    def __init__(
        self,
        script_name: str,
        config_rel_path: str,
        list_key: str,
        names: dict,
    ) -> None:
        super().__init__(script_name, config_rel_path, names)
        self._list_key = list_key

    @classmethod
    def from_declaration(
        cls, script_name: str, declaration: dict
    ) -> "MultiSelectSegment":
        """取声明里的 config、list_key 与 names（候选项集合）。"""
        return cls(
            script_name,
            declaration["config"],
            declaration["list_key"],
            declaration["names"],
        )

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        if self._list_key not in config:
            logger.warning(
                f"[task_switch][{self.script_name}] 配置缺少多选列表 "
                f"{self._list_key}，按无开关处理"
            )
            return None
        items = config[self._list_key]
        assert isinstance(items, list) and all(
            isinstance(item, str) for item in items
        ), f"[task_switch][{self.script_name}] 多选列表必须为字符串列表"
        return [
            _NativeTask(ident, ident, _MemberSlot(items, ident))
            for ident in self._names
        ]


_SEGMENT_CLASSES = {
    "pattern": PatternSegment,
    "key_pair": KeyPairSegment,
    "app_list": AppListSegment,
    "multi_select": MultiSelectSegment,
}


class TaskSwitch:
    """某脚本的原生任务开关：由一条或多条声明段聚合而成。

    读取按声明顺序拼接；写回先按行名定位到行所在的段，再交给该段（同名行以先声明的段为准）。

    Args:
        script_name: 脚本标识名（与 config.yml 一致）。
        declarations: 声明段列表，每段由 ``switch_form`` 选实现类。
    """

    def __init__(self, script_name: str, declarations: list[dict]) -> None:
        self.script_name = script_name
        self._segments: list[_Segment] = []
        for declaration in declarations:
            form = switch_form(declaration)
            assert form in _SEGMENT_CLASSES, (
                f"[task_switch] {script_name} 的声明形态未校验通过"
            )
            cls = _SEGMENT_CLASSES[form]
            self._segments.append(cls.from_declaration(script_name, declaration))

    def read(self) -> list[dict]:
        """枚举该脚本的原生任务与开关态（按声明段顺序拼接）。

        Returns:
            ``[{name, enabled}, ...]``。
        """
        return [row for segment in self._segments for row in segment.read()]

    def write(self, states: dict[str, bool]) -> int:
        """按行名（任务名）写开关，分发到行所在的段。

        Args:
            states: ``{任务名: 目标开关态}``。

        Returns:
            实际变更并落盘的项数；取值与现状一致的不计入，全无变更时不落盘。
        """
        if not states:
            return 0
        owners: dict[str, _Segment] = {}
        for segment in self._segments:
            for row in segment.read():
                owners.setdefault(row["name"], segment)
        batches: dict[_Segment, dict[str, bool]] = {}
        for name, value in states.items():
            segment = owners.get(name)
            if segment is None:
                logger.warning(
                    f"[task_switch][{self.script_name}] 未找到任务 {name!r}，跳过"
                )
                continue
            batches.setdefault(segment, {})[name] = value
        return sum(segment.write(batch) for segment, batch in batches.items())


def load_task_switch_map() -> dict[str, list[dict]]:
    """取得各脚本的任务开关声明段（``{脚本标识: [段, ...]}``）。

    Returns:
        段列表的独立副本；每段的 ``names`` 已归一化为 ``{标识: 展示名}``。

    Raises:
        AssertionError: 声明文件缺失、内容非字典或某条声明非法。
    """
    path = get_task_switch_list_yml_path_under_root()
    file = Path(path)
    assert file.is_file(), f"任务开关声明缺失: {path}"
    return parse_task_switch_map(load_data(path, cached=True, file_format="yaml"))


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
    return TaskSwitch(script_name, declarations[script_name])
