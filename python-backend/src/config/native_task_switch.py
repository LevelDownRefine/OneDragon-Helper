"""脚本原生任务的开关：由 ``task_switch_list.yml`` 的声明选实现类与读写规则。

一个脚本可以声明一条或多条「段」（同一脚本的开关常散在同一个文件的不同键上），每段只
描述同一件事 —— 「配置里哪些项是任务行、开关值落在哪里」，即 ``_tasks``；枚举、``names``
过滤与写回因此各只有一处，按行名（显示名）反查：

- ``task_pattern``：正则白名单形态，键名匹配该正则的顶层项即任务行，行名取第一个捕获组、
  值本身即开关（如 ok-ef 的执行外部命令）；值不是 bool 的项带子选项，不作开关。
- ``tasks_key`` + ``enabled_key``：双表形态，任务定义 ``{id: 任务名}`` 与任务启用
  ``{id: 开关}`` 两张键一致的表（如 BetterGI 的一条龙配置）。
- ``list_key`` + ``id_key`` + ``enabled_key``：应用列表形态，``{list_key: [{id_key: 标识,
  enabled_key: 开关}]}``（如绝区零的应用组、异环的计划任务）。
- ``list_key`` + ``names``：多选形态，``{list_key: [已选中的标识]}`` —— **在列表里即在跑**
  （如 ok-ef 的日常任务、ok-ww 的附加任务）。候选项只存在于脚本源码，故 ``names``
  必填、即全部候选。

``names`` 各形态共用：给了它就是白名单（只列出的行标识出现、行名取映射值），也可写成
``[标识]`` 列表（行名即标识）。多段声明的段写在 ``segments`` 下，节点级的 ``config`` 作为
各段默认。声明格式与校验只在本模块。
"""

import difflib
import logging
import re
from functools import cache
from pathlib import Path, PureWindowsPath
from typing import NamedTuple

from src.utils import get_task_switch_list_yml_path_under_root
from src.utils.utils_io import load_data
from src.utils.utils_sub_config import load_script_config, save_script_config

logger = logging.getLogger(__name__)

#: 任务名定位失败的原因；直接进日志与调用方诊断，不二次翻译。
_REASON_UNKNOWN = "未找到该任务"
_REASON_AMBIGUOUS = "同名任务不唯一"
_REASON_NO_SLOT = "任务无开关记录"
_REASON_NO_CONFIG = "原生配置缺失或脚本未安装"
#: 脚本压根没在 task_switch_list.yml 里声明任务开关（与「声明了但读不到」不同）。
REASON_NO_SWITCH = "脚本未声明任务开关"


class SwitchWriteResult(NamedTuple):
    """一次开关写入的结果；失败是可预期结果，不是异常。

    任务名对不上属外部输入问题（模型、命令行写错名字），按项目约定用返回值表达。
    调用方据此告诉用户「没改成，因为…，可选的是…」。

    Attributes:
        changed: 实际变更并落盘的项数。
        reasons: ``{任务名: 原因}``；空表示全部写入成功。
        candidates: 当前可写的全部行名，供调用方给出候选。
    """

    changed: int
    reasons: dict[str, str]
    candidates: list[str]

    @property
    def ok(self) -> bool:
        """是否全部写入成功。"""
        return not self.reasons

    def describe(self, script_name: str) -> str:
        """人可读的一行结论；成功与失败共用「{脚本}：{动作}{对象}」句式。"""
        if self.ok:
            return f"{script_name}：已更新 {self.changed} 项任务开关"
        detail = "；".join(
            f"{name}（{reason}）" for name, reason in self.reasons.items()
        )
        near = _nearest(self.reasons, self.candidates)
        hint = f"；是否为：{'、'.join(near)}" if near else ""
        return (
            f"{script_name}：未写入任务开关（{detail}）{hint}"
            f"；当前可用任务：{'、'.join(self.candidates) or '（无）'}"
        )


#: 提示「是否为某个候选」的相似度门槛。中文任务名每个字的信息量大，0.5 已经能
#: 覆盖单字差异（如「模拟宇宙」与「模拟领域」），再低会把无关名字也凑成建议。
_NEAR_HINT_RATIO = 0.5

#: 最多提示几个候选：超过三个就不再是「纠错」，而是把清单倒给用户。
_NEAR_HINT_LIMIT = 3


def _nearest(reasons: dict[str, str], candidates: list[str]) -> list[str]:
    """为每个写错的任务名挑一个最接近的候选，按相似度取前几个。

    仅用于提示文案，不参与任何写入决策；调用方在展示期按需计算，结果不必缓存。
    """
    if not candidates:
        return []
    scored: list[tuple[float, str]] = []
    for name in reasons:
        # 相似度只需对每个候选算一次：max 取到的就是最高分。
        ratios = [
            (difflib.SequenceMatcher(None, name, item).ratio(), item)
            for item in candidates
        ]
        ratio, best = max(ratios)
        if ratio >= _NEAR_HINT_RATIO:
            scored.append((ratio, best))
    scored.sort(reverse=True)
    return [name for _, name in scored[:_NEAR_HINT_LIMIT]]


#: ``(原生配置, 行表)``：一次读盘的产物，供预检与写入共用，避免重复读同一文件。
_Resolved = tuple[dict | None, list[tuple[str, "_NativeTask"]]]


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
                    f"[native_task_switch][{self.script_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            assert isinstance(value, bool), (
                f"[native_task_switch][{self.script_name}] 任务 {name!r} 的开关必须为 bool: "
                f"{value!r}"
            )
            result.append({"name": name, "enabled": value})
        return result

    def write(
        self, states: dict[str, bool], resolved: "_Snapshot | None" = None
    ) -> int:
        """按行名（任务名）写开关。

        Args:
            states: ``{任务名: 目标开关态}``。
            resolved: 已解析快照；省略时自行读盘。批量写入方传入同一份快照可避免
                逐段重复读同一文件。

        Returns:
            实际变更并落盘的项数；取值与现状一致的不计入，全无变更时不落盘。
        """
        if not states:
            return 0
        snapshot = resolved
        if snapshot is None:
            config, rows = self._resolve()
            owner = None
        else:
            config, rows = snapshot.config_of(self), snapshot.rows_of(self)
            owner = snapshot
        if config is None:
            return 0
        changed = 0
        for name, value in states.items():
            task, reason = self._lookup(rows, name)
            if reason:
                logger.warning(
                    f"[native_task_switch][{self.script_name}] 任务 {name!r} 无法定位"
                    f"（{reason}），跳过"
                )
                continue
            assert task is not None
            current = task.slot.get()
            if current is None:
                logger.warning(
                    f"[native_task_switch][{self.script_name}] 任务 {name!r} 无开关记录，跳过"
                )
                continue
            if current == value:
                continue
            task.slot.set(value)
            changed += 1
        if changed:
            if owner is None:
                save_script_config(
                    self.script_name, self.script_name, self._config_rel_path, config
                )
            else:
                owner.mark_dirty(self)
        return changed

    def unresolved(
        self, states: dict[str, bool], resolved: "_Snapshot | None" = None
    ) -> dict[str, str]:
        """预检任务名能否写入：``{任务名: 原因}``，空表示全部可写。

        只读不写。``apply`` 用它把「名字对不上」变成返回值，而不是像 :meth:`write`
        那样跳过并返回偏小的变更数——那会让调用方误以为已经改成功。

        Args:
            states: ``{任务名: 目标开关态}``。
            resolved: 已解析快照；省略时自行读盘。

        Returns:
            定位失败的任务名及其原因。
        """
        if not states:
            return {}
        if resolved is None:
            config, rows = self._resolve()
        else:
            config, rows = resolved.config_of(self), resolved.rows_of(self)
        if config is None:
            return dict.fromkeys(states, _REASON_NO_CONFIG)
        result: dict[str, str] = {}
        for name in states:
            task, reason = self._lookup(rows, name)
            if reason:
                result[name] = reason
                continue
            assert task is not None
            if task.slot.get() is None:
                result[name] = _REASON_NO_SLOT
        return result

    def _tasks(self, config: dict) -> list[_NativeTask] | None:
        """把配置归约成任务行；声明与脚本实际不符（缺表、结构不对）时返回 None。

        Raises:
            NotImplementedError: 由子类实现。
        """
        raise NotImplementedError

    def _resolve(
        self, cache: dict[str, dict] | None = None
    ) -> tuple[dict | None, list[tuple[str, _NativeTask]]]:
        """读原生配置并归约成 ``[(行名, _NativeTask)]``。

        配置或任务表缺失（脚本未安装、声明与实际不符）时 config 为 None、行表为空，
        读写两侧都按「无此特性」处理。

        Args:
            cache: 本次调用共享的 ``{配置文件相对路径: 已读配置}``。同一文件被多条
                声明段引用时（如 ok-ef / ok-ww），各段必须看到**同一个 dict**，
                否则后写的段会用自己那份旧副本覆盖先写的段。

        ``names`` 给了就是白名单：只保留其中列出的行标识，行名取映射值。
        """
        if cache is not None and self._config_rel_path in cache:
            config = cache[self._config_rel_path]
        else:
            config = self._load()
            if cache is not None and config is not None:
                cache[self._config_rel_path] = config
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
    def _lookup(
        rows: list[tuple[str, _NativeTask]], name: str
    ) -> tuple[_NativeTask | None, str]:
        """按行名反查任务，返回 ``(任务, 失败原因)``；成功时原因为空串。

        找不到与同名撞车是两种不同的错误，调用方要能分别说明，故不合并成 ``None``。
        """
        matches = [task for row_name, task in rows if row_name == name]
        if not matches:
            return None, _REASON_UNKNOWN
        if len(matches) > 1:
            return None, _REASON_AMBIGUOUS
        return matches[0], ""


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
                f"[native_task_switch][{self.script_name}] 配置缺少任务表 "
                f"{self._tasks_key}/{self._enabled_key}，按无开关处理"
            )
            return None
        definitions = config[self._tasks_key]
        enabled = config[self._enabled_key]
        assert isinstance(definitions, dict) and isinstance(enabled, dict), (
            f"[native_task_switch][{self.script_name}] 任务表必须为字典"
        )
        tasks: list[_NativeTask] = []
        for task_id, name in definitions.items():
            assert isinstance(name, str) and name, (
                f"[native_task_switch][{self.script_name}] 任务名必须为非空字符串: {name!r}"
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
                f"[native_task_switch][{self.script_name}] 配置缺少应用列表 "
                f"{self._list_key}，按无开关处理"
            )
            return None
        items = config[self._list_key]
        assert isinstance(items, list), (
            f"[native_task_switch][{self.script_name}] 应用列表必须为列表"
        )
        tasks: list[_NativeTask] = []
        for item in items:
            assert isinstance(item, dict), (
                f"[native_task_switch][{self.script_name}] 应用列表项必须为字典"
            )
            assert self._id_key in item, (
                f"[native_task_switch][{self.script_name}] 应用列表项缺少 {self._id_key}"
            )
            app_id = item[self._id_key]
            assert isinstance(app_id, str) and app_id, (
                f"[native_task_switch][{self.script_name}] 应用标识必须为非空字符串: {app_id!r}"
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
                f"[native_task_switch][{self.script_name}] 配置缺少多选列表 "
                f"{self._list_key}，按无开关处理"
            )
            return None
        items = config[self._list_key]
        assert isinstance(items, list) and all(
            isinstance(item, str) for item in items
        ), f"[native_task_switch][{self.script_name}] 多选列表必须为字符串列表"
        return [
            _NativeTask(ident, ident, _MemberSlot(items, ident))
            for ident in self._names
        ]


class _Snapshot:
    """一次调用内的解析结果：各段行表 + 按文件共享的配置缓存。

    多个段经常指向同一个原生文件（ok-ef / ok-ww）。它们必须改写**同一份** dict，
    否则各段写各自的副本、后保存的会覆盖先保存的。故这里按相对路径持缓存，
    并记录哪些文件真的被改过，结束时每文件只落盘一次。
    """

    def __init__(self, resolved: dict["_Segment", _Resolved]) -> None:
        self.resolved = resolved
        self._dirty: dict[str, dict] = {}

    def config_of(self, segment: "_Segment") -> dict | None:
        """该段对应的原生配置（各段共享同一份 dict）。"""
        return self.resolved[segment][0]

    def rows_of(self, segment: "_Segment") -> list[tuple[str, "_NativeTask"]]:
        """该段归约出的行表。"""
        return self.resolved[segment][1]

    def mark_dirty(self, segment: "_Segment") -> None:
        """记下该段的文件需要落盘。"""
        config = self.config_of(segment)
        if config is not None:
            self._dirty[segment._config_rel_path] = config

    def save(self, script_name: str) -> None:
        """把每个被改过的文件各保存一次。"""
        for rel_path, config in self._dirty.items():
            save_script_config(script_name, script_name, rel_path, config)
        self._dirty.clear()


class NativeTaskSwitch:
    """某脚本的原生任务开关：由一条或多条声明段聚合而成。

    读取按声明顺序拼接；写回先按行名定位到行所在的段，再交给该段（同名行以先声明的段为准）。

    Args:
        script_name: 脚本标识名（与 config.yml 一致）。
        declarations: 声明段列表，每段由 ``_form_of`` 选实现类。
    """

    def __init__(self, script_name: str, declarations: list[dict]) -> None:
        self.script_name = script_name
        self._segments: list[_Segment] = []
        for declaration in declarations:
            cls = _form_of(declaration)
            assert cls is not None, (
                f"[native_task_switch] {script_name} 的声明形态未校验通过"
            )
            self._segments.append(cls.from_declaration(script_name, declaration))

    def read(self) -> list[dict]:
        """枚举该脚本的原生任务与开关态（按声明段顺序拼接）。

        Returns:
            ``[{name, enabled}, ...]``。
        """
        return [row for segment in self._segments for row in segment.read()]

    def check(self, states: dict[str, bool]) -> dict[str, str]:
        """预检任务名：``{任务名: 原因}``，空表示全部能写。

        只读不写。同一行名出现在多段时以先声明的段为准（与 :meth:`write` 一致），
        故先在整表上解析归属，再交给该段做段内定位。
        """
        if not states:
            return {}
        return self._check(self._snapshot(), states)

    def write(self, states: dict[str, bool]) -> int:
        """按行名（任务名）写开关，分发到行所在的段。

        定位失败的行**跳过并记日志**，不阻断其余行。

        保留本方法供 ``script_service.update`` 的全量表单保存使用：那里一次提交整张
        开关表，个别行无法定位时静默跳过是既有契约。需要「全成或全不成」的调用方用
        :meth:`apply`。

        Args:
            states: ``{任务名: 目标开关态}``。

        Returns:
            实际变更并落盘的项数；取值与现状一致的不计入，全无变更时不落盘。
        """
        if not states:
            return 0
        snapshot = self._snapshot()
        changed = self._write(snapshot, states, skip_unknown=True)
        snapshot.save(self.script_name)
        return changed

    def apply(self, states: dict[str, bool]) -> SwitchWriteResult:
        """先预检再写：任一行名定位失败就整批不写，并说明原因。

        与 :meth:`write` 的区别只在失败语义：这个不静默跳过、也不抛异常，而是
        把「哪几项对不上、可选的有什么」作为返回值交给调用方。

        整次调用只读盘一次（每段一次），预检与写入共用同一份快照。

        Args:
            states: ``{任务名: 目标开关态}``。

        Returns:
            ``changed`` 为实际变更项数；``reasons`` 非空表示整批未写。
        """
        if not states:
            return SwitchWriteResult(0, {}, [])
        snapshot = self._snapshot()
        candidates = [
            name for segment in self._segments for name, _t in snapshot.rows_of(segment)
        ]
        failed = self._check(snapshot, states)
        if failed:
            return SwitchWriteResult(0, failed, candidates)
        changed = self._write(snapshot, states, skip_unknown=False)
        snapshot.save(self.script_name)
        return SwitchWriteResult(changed, {}, candidates)

    def names(self) -> list[str]:
        """当前可写的任务行名（按声明段顺序）。"""
        return [row["name"] for row in self.read()]

    def _snapshot(self) -> "_Snapshot":
        """每个文件读一次原生配置，供本次调用的预检与写入共用。

        同一文件被多条段引用时共享同一份 dict——各段各自读一份会让后写的段覆盖
        先写的段。
        """
        cache: dict[str, dict] = {}
        return _Snapshot(
            {segment: segment._resolve(cache) for segment in self._segments}
        )

    def _check(self, snapshot: "_Snapshot", states: dict[str, bool]) -> dict[str, str]:
        """按快照预检；行名归属取自归约后的行表而非 :meth:`read`。

        后者会跳过没有开关记录的行，用它会把这些行误报成「任务不存在」，
        而不是更准确的「任务无开关记录」。
        """
        owners: dict[str, _Segment] = {}
        configured = False
        for segment in self._segments:
            config = snapshot.config_of(segment)
            if config is not None:
                configured = True
            for name, _task in snapshot.rows_of(segment):
                owners.setdefault(name, segment)
        if not configured:
            return dict.fromkeys(states, _REASON_NO_CONFIG)
        result: dict[str, str] = {}
        batches: dict[_Segment, dict[str, bool]] = {}
        for name, value in states.items():
            segment = owners.get(name)
            if segment is None:
                result[name] = _REASON_UNKNOWN
                continue
            batches.setdefault(segment, {})[name] = value
        for segment, batch in batches.items():
            result.update(segment.unresolved(batch, snapshot))
        return result

    def _write(
        self,
        snapshot: "_Snapshot",
        states: dict[str, bool],
        *,
        skip_unknown: bool,
    ) -> int:
        """按快照写入。

        Args:
            snapshot: 本次调用的解析快照。
            states: ``{任务名: 目标开关态}``。
            skip_unknown: 定位失败的行是否只记日志跳过。``False`` 表示调用方已经
                预检过，未知行属编程错误（预检与写入之间配置被改动），用断言暴露。
        """
        owners: dict[str, _Segment] = {}
        for segment in self._segments:
            for name, _task in snapshot.rows_of(segment):
                owners.setdefault(name, segment)
        batches: dict[_Segment, dict[str, bool]] = {}
        for name, value in states.items():
            segment = owners.get(name)
            if segment is None:
                if not skip_unknown:
                    raise AssertionError(
                        f"[native_task_switch][{self.script_name}] 预检后任务 "
                        f"{name!r} 不存在，配置可能已被改动"
                    )
                logger.warning(
                    f"[native_task_switch][{self.script_name}] 未找到任务 {name!r}，跳过"
                )
                continue
            batches.setdefault(segment, {})[name] = value
        return sum(segment.write(batch, snapshot) for segment, batch in batches.items())


#: 声明段共有：可选字段 names（白名单 / 展示名 / 多选候选项）
_OPTIONAL_FIELDS = frozenset({"names"})

#: 声明段形态 → (必需字段, 可选字段, 实现类)；各形态字段集互不重叠
_FORMS: tuple[tuple[frozenset, frozenset, type[_Segment]], ...] = (
    (frozenset({"config", "task_pattern"}), _OPTIONAL_FIELDS, PatternSegment),
    (
        frozenset({"config", "tasks_key", "enabled_key"}),
        _OPTIONAL_FIELDS,
        KeyPairSegment,
    ),
    (
        frozenset({"config", "list_key", "id_key", "enabled_key"}),
        _OPTIONAL_FIELDS,
        AppListSegment,
    ),
    (
        frozenset({"config", "list_key", "names"}),
        frozenset(),
        MultiSelectSegment,
    ),
)


def _form_of(declaration: dict) -> type[_Segment] | None:
    """匹配声明段所属形态：必需字段齐且无多余字段；不属于任何形态时返回 None。"""
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


def _validate_segment(script_name: str, segment: dict) -> None:
    """单段声明须匹配某一形态，字段全为非空字符串，config 为脚本内相对路径。

    Raises:
        AssertionError: 字段缺失、多写、形态混用、取值非法，或正则不可用（编译失败／
            捕获组数不为 1，行名无从取）。
    """
    assert _form_of(segment) is not None, (
        f"{script_name} 的任务开关声明字段必须为 "
        + " 或 ".join(
            str(sorted(required)) + (f" + 可选 {sorted(optional)}" if optional else "")
            for required, optional, _ in _FORMS
        )
    )
    for field in sorted(segment):
        if field in _OPTIONAL_FIELDS:
            continue
        value = segment[field]
        assert isinstance(value, str) and value.strip(), (
            f"{script_name}/native_task_switch/{field} 必须为非空字符串"
        )
    path = PureWindowsPath(segment["config"])
    assert not path.anchor and ".." not in path.parts, (
        f"{script_name}/native_task_switch/config 必须为脚本内相对路径"
    )
    if "task_pattern" in segment:
        assert _single_group_pattern(segment["task_pattern"]), (
            f"{script_name}/native_task_switch/task_pattern 必须是可编译且恰好一个捕获组的正则"
        )
    if "names" in segment:
        _validate_names(script_name, segment["names"])


def _validate_names(script_name: str, names) -> None:
    """``names`` 为 ``{标识: 展示名}`` 或 ``[标识]``（后者行名即标识），键与值都须非空。

    Raises:
        AssertionError: 既非字典也非列表，或其中某项不是非空字符串。
    """
    assert isinstance(names, (dict, list)), (
        f"{script_name}/native_task_switch/names 必须为字典（标识: 展示名）或列表（标识）"
    )
    pairs = (
        list(names.items())
        if isinstance(names, dict)
        else [(ident, ident) for ident in names]
    )
    for ident, name in pairs:
        assert isinstance(ident, str) and ident.strip(), (
            f"{script_name}/native_task_switch/names 的标识必须为非空字符串"
        )
        assert isinstance(name, str) and name.strip(), (
            f"{script_name}/native_task_switch/names 的展示名必须为非空字符串"
        )


def _with_dict_names(segment: dict) -> dict:
    """``names`` 写成 ``[标识]`` 时补成 ``{标识: 标识}``（行名即标识）。"""
    names = segment.get("names")
    if isinstance(names, list):
        return {**segment, "names": {ident: ident for ident in names}}
    return segment


def _normalized_segments(script_name: str, node) -> list[dict]:
    """把声明节点校验并归一化成段列表。

    单段直接写在节点上；多段写在 ``segments`` 下，节点级的 ``config`` 作为各段默认（同一
    脚本的开关常散在同一个文件的不同键上，路径因此只写一次）。``names`` 统一成
    ``{标识: 展示名}``。

    Returns:
        段列表，每段一种形态。

    Raises:
        AssertionError: 节点非字典、``segments`` 非非空列表、节点级多写字段，或某段非法。
    """
    assert isinstance(node, dict), f"{script_name} 的任务开关声明必须为字典"
    node = {key: value for key, value in node.items() if key != "options"}
    if "segments" not in node:
        _validate_segment(script_name, node)
        return [_with_dict_names(node)]

    defaults = {key: value for key, value in node.items() if key != "segments"}
    assert set(defaults) <= {"config"}, (
        f"{script_name}/native_task_switch 多段声明的节点级只能给 config（作为各段默认）"
    )
    segments = node["segments"]
    assert isinstance(segments, list) and segments, (
        f"{script_name}/native_task_switch/segments 必须为非空列表"
    )
    result: list[dict] = []
    for segment in segments:
        assert isinstance(segment, dict), (
            f"{script_name}/native_task_switch/segments 的每一项必须为字典"
        )
        merged = {**defaults, **segment}
        _validate_segment(script_name, merged)
        result.append(_with_dict_names(merged))
    return result


def load_native_task_switch_map() -> dict[str, list[dict]]:
    """取得各脚本的任务开关声明段（``{脚本标识: [段, ...]}``）。

    Returns:
        段列表的独立副本；每段的 ``names`` 已归一化为 ``{标识: 展示名}``。

    Raises:
        AssertionError: 声明文件缺失、内容非字典或某条声明非法。
    """
    path = get_task_switch_list_yml_path_under_root()
    file = Path(path)
    assert file.is_file(), f"任务开关声明缺失: {path}"
    return _parse_declarations(load_data(path, cached=True, file_format="yaml"))


def _parse_declarations(data: dict) -> dict[str, list[dict]]:
    """校验已读取的数据，不读文件或缓存业务结构。"""
    assert isinstance(data, dict), "任务开关声明必须是字典"
    return {
        script_name: _normalized_segments(script_name, node)
        for script_name, node in data.items()
    }


@cache
def native_task_switch_of(script_name: str) -> NativeTaskSwitch | None:
    """取某脚本的任务开关。

    Args:
        script_name: 脚本标识名。

    Returns:
        该脚本的开关对象；声明文件里没有该脚本时为 None。
    """
    declarations = load_native_task_switch_map()
    if script_name not in declarations:
        return None
    return NativeTaskSwitch(script_name, declarations[script_name])
