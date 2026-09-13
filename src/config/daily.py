"""一个日常：由 daily_task_list.yml 声明解析出的选项落点，以及它那部分的读写规则。

``Daily`` 只出规则、不碰盘：声明怎么变成落点（一级字段、二级字段、静态二级枚举）、
某次选择往某段写什么（``write``）、某段该怎么反读（``read``）、开关文件里哪一条是
本日常的（``read_enabled`` / ``set_enabled``）。方法签名一律是「吃 dict 吐 dict/值」，
不认识 ``ScriptConfig``——文件 I/O 归它（唯一碰盘的一层）：读盘后把数据段交给日常，
再按返回值决定要不要落盘。

声明表达不了的由子类覆写：日常数据在自己那段、开关在第二份文件里（``SegmentedDaily``
提供共同实现，该脚本每个日常各一个子类）、粥的 TaskQueue（``write`` / ``read``）、
绝区零/崩铁的不适配（``no_op``）。
"""

import logging
from typing import Any

from src.config.task_config import (
    get_options,
    get_physical_name,
    get_value_map,
)
from src.utils.utils_dict import get_field, safe_update

logger = logging.getLogger(__name__)


class Daily:
    """单个日常：名称、由声明解析出的落点，以及它那部分的读写规则。

    Attributes:
        script_name: 所属脚本标识名（报错定位用）。
        name: 日常展示名（界面行名，也是调用方使用的标识）。
        physical_name: 日常物理名（子脚本 config 的段名 / routine item id）。
        options: 该日常的一级项声明（菜单数据来源）；单层日常即该日常自身。
        task_field: 一级项写入的原生字段；单层日常（无一级字段）为 None。
        task_map: 一级项展示名 → 一级物理值。
        option_fields: 一级项展示名 → 二级项写入的原生字段。
        no_op: 是否无需本工具写 config（上游自身已支持副本选择）。
        enable_on_select: 选副本后是否顺带启用本日常的开关。
    """

    no_op: bool = False
    """无需本工具写 config 的日常：副本选择完全由上游脚本自己管（绝区零/崩铁）。"""

    enable_on_select: bool = False
    """选副本后顺带启用本日常：选了就是想跑它（分段脚本的语义）。"""

    def __init__(self, script_name: str, declaration: dict) -> None:
        """解析一条日常声明。

        Args:
            script_name: 所属脚本标识名（报错定位用）。
            declaration: ``daily_task_list.yml`` 里该日常的声明节点。

        Raises:
            AssertionError: 未声明选项、选项混用单层与两层，或（两层且顶层无 key 时）
                各一级项的二级 key 不唯一。
        """
        self.script_name = script_name
        self.name: str = declaration["display_name"]
        self.physical_name: str = get_physical_name(declaration)
        options = get_options(declaration)
        assert options, f"{script_name}/{self.physical_name} 必须声明选项"
        layered = ["options" in option for option in options]
        assert all(layered) or not any(layered), (
            f"{script_name}/{self.physical_name} 的选项不能混用单层与两层"
        )
        if all(layered):
            self._parse_layered(declaration, options)
        else:
            self._parse_flat(declaration, options)
        # 两级写同一字段（如原神/终末地的 DomainName / 体力本）：字段里存的是
        # 「二级优先、否则一级」的最终副本名，读时不做一级映射。
        self._single_field = self.task_field is not None and all(
            field == self.task_field for field in self.option_fields.values()
        )

    def _parse_layered(self, declaration: dict, options: list[dict]) -> None:
        """解析两层日常（各一级项自带 ``options``）。

        Args:
            declaration: 日常声明节点。
            options: 一级项声明列表。
        """
        keys = {option["options"]["key"] for option in options}
        group = declaration["options"]
        if "key" in group:
            self.task_field: str | None = group["key"]
        else:
            assert len(keys) == 1, (
                f"{self.script_name}/{self.physical_name} 未声明顶层 key 时"
                "各选项的二级 key 必须唯一"
            )
            self.task_field = keys.pop()
        self.task_map: dict[str, Any] = get_value_map(declaration)
        self.option_fields: dict[str, str] = {
            option["display_name"]: option["options"]["key"] for option in options
        }
        self.options: list[dict] = options
        static = all("values" in option["options"] for option in options)
        self._sequence_values: dict[str, dict[str, Any]] = (
            {option["display_name"]: get_value_map(option) for option in options}
            if static
            else {}
        )
        self._sequence_required = static

    def _parse_flat(self, declaration: dict, options: list[dict]) -> None:
        """解析单层日常（各一级项都是叶子）。

        组内有 ``key`` 时选择结果直接写它、整组自身即唯一一级项（如追猎目标）；
        组内无 ``key`` 时该日常无落点，values 仍作一级项（如绝区零/崩铁）。

        Args:
            declaration: 日常声明节点。
            options: 一级项声明列表。
        """
        group = declaration["options"]
        self.task_field = None
        self.task_map = {}
        self.option_fields = {self.name: group["key"]} if "key" in group else {}
        self.options = [declaration] if self.option_fields else options
        static = "values" in group
        self._sequence_values = (
            {self.name: get_value_map(declaration)} if static else {}
        )
        self._sequence_required = static

    def fields(
        self, task_name: str, sequence: str | int | None = None
    ) -> dict[str, Any]:
        """该次选择要写入的 {字段: 值}。

        两级落在同一字段时（一级值先写、二级值后写）二级覆盖一级，只留一个键。

        Args:
            task_name: 一级项展示名。
            sequence: 二级项值（物理值；静态枚举的二级也接受展示名）；无二级时省略。

        Returns:
            {字段: 值}；单层日常只有二级那一个键。

        Raises:
            AssertionError: 该日常无选项落点、一级项未声明、二级必填却缺失，
                或静态枚举的二级取值不在声明里。
        """
        assert self.option_fields, (
            f"[daily][{self.name}] 无选项落点，不能作为副本选择写入"
        )
        assert task_name in self.option_fields, (
            f"[daily][{self.name}] 未声明的一级项: {task_name}"
        )
        values: dict[str, Any] = {}
        if self.task_field is not None:
            values[self.task_field] = self.task_map[task_name]
        if sequence is None:
            assert not self._sequence_required, (
                f"[daily][{self.name}] {task_name} 缺少二级选项"
            )
        else:
            # 静态枚举的二级可直接传展示名，菜单给的是物理值；由脚本资源展开的
            # 二级声明层拿不到取值，不校验。
            sequence_values = self._sequence_values.get(task_name, {})
            if sequence_values:
                sequence = sequence_values.get(sequence, sequence)
                assert sequence in sequence_values.values(), (
                    f"[daily][{self.name}] 未适配的二级值: {sequence!r}"
                )
            values[self.option_fields[task_name]] = sequence
        return values

    def write(
        self,
        section: dict,
        task_name: str,
        sequence: str | int | None,
        display_name: str,
    ) -> bool:
        """把该次选择写进数据段（只改内存），返回是否有改动。

        默认实现按 ``fields`` 写平面字段；结构化改写（粥的 TaskQueue）覆写本方法。

        Args:
            section: 该日常的数据段（由 ``section`` 给出）。
            task_name: 一级项展示名（副本名）。
            sequence: 二级项值；无二级时为 None。
            display_name: 脚本展示名（字段写入的日志用）。

        Returns:
            是否有实际修改。

        Raises:
            AssertionError: 无选项落点、一级项未声明、二级必填却缺失，
                或静态枚举的二级取值不在声明里。
        """
        changed = False
        for key, value in self.fields(task_name, sequence).items():
            changed |= safe_update(
                section, key, value, display_name, assert_key_exists=False
            )
        return changed

    def read(self, section: dict) -> tuple[str | None, str | int | None]:
        """从数据段反读该日常已选的 (一级项展示名, 二级值)。

        Args:
            section: 该日常的数据段（由 ``section`` 给出）。

        Returns:
            (一级项展示名, 二级值)；无落点 / 未选择 / 字段为空时 (None, None)，
            单层日常的副本名即日常名。

        Raises:
            AssertionError: 字段里的副本值不在声明里（config 损坏或版本不符）。
        """
        if not self.option_fields:
            return None, None  # 无落点（如绝区零/崩铁日常）：无副本真相
        if self.task_field is None:
            # 单层日常：唯一一级项即日常自身，选择结果直接落 option_fields 的字段。
            key = self.option_fields[self.name]
            if key not in section:
                return self.name, None
            return self.name, section[key] or None
        raw = section.get(self.task_field)
        if raw is None or raw == "":
            return None, None
        if self._single_field:
            return raw, None  # 字段里存的就是最终副本名（二级优先），不做一级映射
        names = {value: name for name, value in self.task_map.items()}
        assert raw in names, f"[daily][{self.name}] 未知副本值: {raw!r}"
        task = names[raw]
        seq_field = self.option_fields[task]
        if seq_field not in section:
            return task, None
        return task, section[seq_field]

    def read_enabled(self, routine: dict | None) -> bool | None:
        """反读该日常是否启用；无日常开关文件的脚本返回 None。

        Args:
            routine: 开关文件的 dict；该脚本无开关文件或文件缺失时为 None。

        Returns:
            是否启用；无开关文件返回 None（界面据此不提供「不启用」）。
        """
        return None

    def set_enabled(self, routine: dict, enabled: bool) -> bool:
        """置该日常的启用状态（只改内存）；无日常开关文件的脚本不支持。

        Args:
            routine: 开关文件的 dict（本实现忽略）。
            enabled: 目标启用状态（本实现忽略）。

        Raises:
            AssertionError: 该脚本未支持停用日常。
        """
        # 未适配脚本不该走到开关写入；显式 raise 而非 assert False，避免 B011 例外。
        raise AssertionError(f"[daily][{self.name}] 未支持停用日常")

    def section(self, config: dict) -> dict:
        """该日常在 config 里的数据段；基类为整份 config。

        Args:
            config: 顶层 config dict。

        Returns:
            该日常的数据段；分段脚本覆写本方法取段。
        """
        return config

    def section_exists(self, config: dict) -> bool:
        """该日常在 config 里是否已落盘；基类恒为 True。

        Args:
            config: 顶层 config dict。

        Returns:
            是否已落盘；分段脚本覆写本方法判段是否存在。
        """
        return True


class NoopDaily(Daily):
    """无需本工具适配副本的日常（绝区零/崩铁：上游自身已支持）：副本选择不落盘。"""

    no_op = True


class SegmentedDaily(Daily):
    """数据在自己那段、开关在第二份文件里的日常（异环的两个日常）。

    段名与 Routine Items 的 id 都取本日常声明的物理名；选完副本顺带启用自己那条，
    另一个日常的开关不动（是否只跑一个由游戏侧决定）。
    """

    enable_on_select = True

    def read_enabled(self, routine: dict | None) -> bool | None:
        """反读本日常的 Routine Item 是否启用；开关文件缺失（无真相）返回 None。

        Args:
            routine: DailyRoutineTask.json 的 dict；文件缺失时为 None。

        Returns:
            是否启用；开关文件缺失返回 None。

        Raises:
            AssertionError: Routine Items 缺少或重复本日常的物理名。
        """
        if routine is None:
            return None  # 开关文件缺失：无真相，不谎报「已停用」
        return bool(self._routine_item(routine)["enabled"])

    def set_enabled(self, routine: dict, enabled: bool) -> bool:
        """置本日常的 Routine Item 启用状态（只改内存），另一个日常不动。

        Args:
            routine: DailyRoutineTask.json 的 dict。
            enabled: 目标启用状态。

        Returns:
            是否有实际修改（无变化即不落盘）。

        Raises:
            AssertionError: Routine Items 缺少或重复本日常的物理名。
        """
        return safe_update(self._routine_item(routine), "enabled", enabled, self.name)

    def _routine_item(self, routine: dict) -> dict:
        """取 Routine Items 里本日常的 item。

        Args:
            routine: DailyRoutineTask.json 的 dict。

        Returns:
            本日常的 Routine Item dict。

        Raises:
            AssertionError: Routine Items 缺少或重复本日常的物理名。
        """
        items = get_field(routine, "Routine Items", self.name, list)
        target = [item for item in items if item["id"] == self.physical_name]
        assert len(target) == 1, (
            f"[daily][{self.name}] Routine Items 缺少或重复 {self.physical_name}"
        )
        return target[0]

    def section(self, config: dict) -> dict:
        """取本日常自己的段（段名 = 本日常物理名）。

        Args:
            config: 顶层 config dict。

        Returns:
            本日常的段；段缺失返回空 dict（按未落盘处理）。

        Raises:
            AssertionError: 段存在但类型非 dict（损坏）。
        """
        section = config.get(self.physical_name)
        assert section is None or isinstance(section, dict), (
            f"[daily][{self.name}] {self.physical_name} 段必须是 dict"
        )
        return section if section is not None else {}

    def section_exists(self, config: dict) -> bool:
        """本日常的段是否已落盘。

        Args:
            config: 顶层 config dict。

        Returns:
            段是否存在。
        """
        return self.physical_name in config


class AnomalyDaily(SegmentedDaily):
    """异环的异象界域日常（段名与开关 id 取本日常声明的物理名）。"""


class AnomalyHunterDaily(SegmentedDaily):
    """异环的追猎目标日常（段名与开关 id 取本日常声明的物理名）。"""


class MaaDaily(Daily):
    """粥的日常：副本以 MAA 的 TaskQueue / StagePlan 表达。

    关卡代码 → 中文名由声明推导（另加固定的剿灭），基于 ``StagePlan[0]`` 识别任务，
    不依赖 TaskQueue 顺序；只维护映射内的关卡，其余 FightTask 不动。
    """

    _fixed_stages = ("Annihilation", "1-7")
    """固定启用的关卡代码：剿灭恒启用；``1-7`` 是「土」的落点。"""

    def __init__(self, script_name: str, declaration: dict) -> None:
        """解析粥日常：额外建「关卡代码 ↔ 中文名」映射。

        Args:
            script_name: 所属脚本标识名。
            declaration: 该日常的声明节点。
        """
        super().__init__(script_name, declaration)
        self._name_by_stage: dict[str, str] = {
            "Annihilation": "剿灭",
            **{
                get_physical_name(option): option["display_name"]
                for option in get_options(declaration)
            },
        }
        self._stage_by_name: dict[str, str] = {
            name: stage for stage, name in self._name_by_stage.items()
        }

    def write(
        self,
        section: dict,
        task_name: str,
        sequence: str | int | None,
        display_name: str,
    ) -> bool:
        """启用剿灭/土/选定副本：改 TaskQueue 各项的 ``IsEnable``（只改内存）。

        队列里完全没有目标关卡时借一个槽位改写其 StagePlan（只改 StagePlan）。

        Args:
            section: MAA config dict。
            task_name: 选定副本中文名。
            sequence: 粥无二级序列，恒为 None。
            display_name: 脚本展示名（字段写入的日志用）。

        Returns:
            是否有实际修改。

        Raises:
            AssertionError: 未适配的副本（不在关卡映射里）。
        """
        assert task_name in self._stage_by_name, (
            f"[daily][{self.name}] 未适配的副本: {task_name}"
        )
        target_stage = self._stage_by_name[task_name]
        task_queue = self._task_queue(section)

        changed = False
        matched_target = False
        for task in task_queue:
            if task["$type"] != "FightTask":
                continue
            stage_plan = task["StagePlan"]
            if not isinstance(stage_plan, list) or len(stage_plan) != 1:
                continue
            stage = stage_plan[0]
            if stage not in self._name_by_stage:
                continue  # 未维护的关卡，不动
            if stage == target_stage:
                matched_target = True
            name = self._name_by_stage[stage]
            should_enable = stage in self._fixed_stages or name == task_name
            changed |= safe_update(
                task,
                "IsEnable",
                should_enable,
                f"{display_name}[{name}]",
            )

        # 目标关卡缺失时借槽改写 StagePlan，优先借副本列表内已启用的槽（剿灭除外），
        # 其次才借未追踪占位槽。
        if not matched_target:
            changed |= self._borrow_slot(task_queue, target_stage, display_name)
        return changed

    def read(self, section: dict) -> tuple[str | None, str | int | None]:
        """反读当前副本与二级序列。

        遍历 TaskQueue，除固定启用的剿灭/土外，被勾选 ``IsEnable`` 的那一项即当前
        副本；特殊：维护关卡都未启用但有 ``StagePlan=["1-7"]`` 的任务时读为「土」。

        Args:
            section: MAA config dict。

        Returns:
            (副本中文名, 序列值)；未设置返回 (None, None)。
        """
        has_1_7 = False
        for task in self._task_queue(section):
            if task["$type"] != "FightTask":
                continue
            stage_plan = task["StagePlan"]
            if not isinstance(stage_plan, list) or len(stage_plan) != 1:
                continue
            stage = stage_plan[0]
            if stage == "1-7":
                has_1_7 = True
            if stage not in self._name_by_stage or stage in self._fixed_stages:
                continue
            if task["IsEnable"]:
                return self._name_by_stage[stage], None
        if has_1_7:
            return self._name_by_stage["1-7"], None
        return None, None

    def _borrow_slot(
        self, task_queue: list, target_stage: str, display_name: str
    ) -> bool:
        """借一个已启用槽位改写 StagePlan（只改 StagePlan，不动 IsEnable）。

        Args:
            task_queue: MAA config 的 TaskQueue 列表。
            target_stage: 目标关卡代码。
            display_name: 日志用脚本展示名。

        Returns:
            是否发生实际修改。
        """
        candidates = [
            task
            for task in task_queue
            if task["$type"] == "FightTask"
            and task["IsEnable"]
            and isinstance(task["StagePlan"], list)
            and len(task["StagePlan"]) == 1
            and task["StagePlan"][0] != "Annihilation"
        ]
        borrow = next(
            (
                task
                for task in candidates
                if task["StagePlan"][0] in self._name_by_stage
            ),
            None,
        ) or next(iter(candidates), None)
        if borrow is None:
            return False
        borrowed = borrow.get("Name", display_name)
        return safe_update(
            borrow, "StagePlan", [target_stage], f"{display_name}[borrow:{borrowed}]"
        )

    @staticmethod
    def _task_queue(section: dict) -> list:
        """取 MAA config 的 TaskQueue。

        Args:
            section: MAA config dict。

        Returns:
            TaskQueue 列表。
        """
        return section["Configurations"]["Default"]["TaskQueue"]
