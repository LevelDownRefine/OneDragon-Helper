"""一个日常：由 daily_task_list.yml 声明解析出的落点与读写规则。

I/O 由 Daily 自持（``_load_daily_config`` 等，直调 ``utils_sub_config``），完成「读盘 → 改内存 → 有改动才落盘」。
声明形态与读写机制由机制类负责：基类解析标准两层，``Anomaly`` 单层带
``key``，``MaaDaily`` TaskQueue，``NoopDaily`` 无需适配。开关落点亦随声明而异：
基类读主文件的 ``enable_key`` 字段，``Anomaly`` 读 ``routine`` 文件，``BgiDaily``
按 ``enable_task`` 反查任务启用表。
"""

import logging
from copy import deepcopy
from typing import Any

from src.config.maa_activity import read_activity_stages
from src.config.task_config import (
    get_options,
    get_physical_name,
    get_value_map,
)
from src.config.task_source import read_task_source
from src.utils.utils_dict import get_field, safe_update
from src.utils.utils_sub_config import (
    load_config,
    load_game_config,
    load_template,
    save_config,
)

logger = logging.getLogger(__name__)


class Daily:
    """单个日常：名称、由声明解析出的落点，以及它那部分的读写规则。

    Attributes:
        script_name: 所属脚本标识名。
        name: 日常展示名，来自声明，界面行名与匹配键。
        physical_name: 日常物理名，子脚本 config 的段名 / routine item id。
        options: 该日常的一级项声明，菜单数据来源。
        task_field: 一级项写入的原生字段。
        task_map: 一级项展示名 → 一级物理值。
        option_fields: 一级项展示名 → 二级项写入的原生字段。

    读写原语（``_load_daily_config`` / ``_save_daily_config`` / ``_load_routine_config`` /
    ``_save_routine_config``，含保存后回读校验）由 Daily 自持，配置路径由构造注入。
    """

    def __init__(
        self, script_name: str, declaration: dict, script_display_name: str
    ) -> None:
        """解析一条标准两层日常声明。

        Args:
            script_name: 所属脚本标识名。
            declaration: ``daily_task_list.yml`` 里该日常的声明节点；
                ``config``（读写主文件）必填，``routine``（日常开关文件）、
                ``enable_key``（主文件里的开关字段）可选，路径相对脚本根目录。
            script_display_name: 所属脚本的展示名（日志与报错用）。

        Raises:
            AssertionError: 未声明选项、选项是单层形态，或顶层无 ``key`` 时
                各一级项的二级 key 不唯一。
        """
        self.script_name = script_name
        self.script_display_name = script_display_name
        self._config_rel_path: str = declaration["config"]
        self._routine_rel_path: str = declaration.get("routine", "")
        self._enable_key: str = declaration.get("enable_key", "")
        self.display_name: str = declaration["display_name"]
        self.physical_name: str = get_physical_name(declaration)
        self._parse_landing(declaration)

    def get_task_lists(self, source: dict) -> list[str]:
        """读取该日常某组选项的资源；特殊资源格式由机制类覆写。"""
        return read_task_source(self.script_name, source)

    def _read_config(
        self, rel_path: str, *, allow_missing: bool = False
    ) -> dict | None:
        """读脚本 config 文件。

        Args:
            rel_path: 相对脚本根目录的路径。
            allow_missing: True 时读取失败返回 None（读路径）；
                False 时失败即报错（写路径，默认）。

        Returns:
            解析后的 config dict；仅 allow_missing=True 且读取失败时为 None。

        Raises:
            AssertionError: allow_missing=False 且文件不存在、内容损坏或解析结果非 dict。
        """
        try:
            config = load_config(self.script_name, rel_path)
        except AssertionError:
            # 未安装 / 文件缺失由 load_config 以断言表达，读路径按「未设置」处理。
            if not allow_missing:
                raise
            return None
        except Exception:  # noqa: BLE001  # 文件存在但内容损坏
            if not allow_missing:
                raise
            logger.warning(
                f"[daily][{self.script_display_name}] config 损坏，"
                f"按未设置处理: {rel_path}",
                exc_info=True,
            )
            return None
        if not isinstance(config, dict):
            if allow_missing:
                return None
            assert isinstance(config, dict), (
                f"[daily][{self.script_display_name}] config 必须是 dict"
            )
        return config

    def _load_daily_config(self, *, allow_missing: bool = False) -> dict | None:
        """读主 config（副本落点所在文件）。

        Args:
            allow_missing: True 时读取失败返回 None（读路径）；
                False 时失败即报错（写路径，默认）。

        Returns:
            解析后的 config dict；仅 allow_missing=True 且读取失败时为 None。
        """
        return self._read_config(self._config_rel_path, allow_missing=allow_missing)

    def _save_daily_config(self, config: dict) -> None:
        """保存主 config 并回读校验落盘一致。

        Args:
            config: 待保存的 dict。

        Raises:
            AssertionError: config 非 dict 或保存后回读不一致。
        """
        assert isinstance(config, dict), (
            f"[daily][{self.script_display_name}] config 必须是 dict"
        )
        save_config(self.script_name, self._config_rel_path, config)
        reloaded = self._load_daily_config()
        assert reloaded == config, (
            f"[daily][{self.script_display_name}] 配置保存后校验失败："
            "重新读取的内容与预期不一致"
        )

    def _load_routine_config(self, *, allow_missing: bool = True) -> dict | None:
        """读日常开关文件；无日常开关的机制类不使用。

        Args:
            allow_missing: True（默认）时文件缺失返回 None——开关文件的「无真相」。

        Returns:
            解析后的 config dict；allow_missing=True 且读取失败时为 None。
        """
        return self._read_config(self._routine_rel_path, allow_missing=allow_missing)

    def _save_routine_config(self, routine: dict) -> None:
        """保存日常开关文件并回读校验落盘一致。

        Args:
            routine: 待保存的 dict。

        Raises:
            AssertionError: 保存后回读不一致。
        """
        save_config(self.script_name, self._routine_rel_path, routine)
        reloaded = self._load_routine_config(allow_missing=False)
        assert reloaded == routine, (
            f"[daily][{self.script_display_name}] 开关文件保存后校验失败："
            "重新读取的内容与预期不一致"
        )

    def _parse_landing(self, declaration: dict) -> None:
        """解析标准两层落点；其它形态的机制类覆写本方法。

        Args:
            declaration: ``daily_task_list.yml`` 里该日常的声明节点。

        Raises:
            AssertionError: 未声明选项，或顶层无 ``key`` 时各一级项的
                二级 key 不唯一。
        """
        options = get_options(declaration)
        assert options, f"{self.script_name}/{self.physical_name} 必须声明选项"
        layered = ["options" in option for option in options]
        assert all(layered), (
            f"{self.script_name}/{self.physical_name} 的选项是单层形态，"
            "标准两层日常不适用（为该脚本选择匹配的机制类）"
        )
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
        # 两级写同一字段（如原神的 DomainName）时二级覆盖一级，读时不做一级映射。
        self._single_field = all(
            field == self.task_field for field in self.option_fields.values()
        )

    def _fields(
        self, task_name: str, sequence: str | int | None = None
    ) -> dict[str, Any]:
        """该次选择要写入的 {字段: 值}。

        Args:
            task_name: 一级项展示名。
            sequence: 二级项物理值；无二级时省略。

        Returns:
            {字段: 值}；单层日常只有那一个键。

        Raises:
            AssertionError: 无选项落点、一级项未声明、二级必填却缺失，
                或二级取值不在声明里。
        """
        assert self.option_fields, (
            f"[daily][{self.display_name}] 无选项落点，不能作为副本选择写入"
        )
        assert task_name in self.option_fields, (
            f"[daily][{self.display_name}] 未声明的一级项: {task_name}"
        )
        values: dict[str, Any] = {}
        if self.task_field is not None:
            values[self.task_field] = self.task_map[task_name]
        if sequence is None:
            assert not self._sequence_required, (
                f"[daily][{self.display_name}] {task_name} 缺少二级选项"
            )
        else:
            # 静态枚举的二级可传展示名；资源展开的二级不校验。
            sequence_values = self._sequence_values.get(task_name, {})
            if sequence_values:
                sequence = sequence_values.get(sequence, sequence)
                assert sequence in sequence_values.values(), (
                    f"[daily][{self.display_name}] 未适配的二级值: {sequence!r}"
                )
            values[self.option_fields[task_name]] = sequence
        return values

    def update(self, task_name: str, sequence: str | int | None = None) -> bool:
        """设置该日常的副本：读 config → 写数据段 → 有改动才落盘。

        Args:
            task_name: 一级项展示名。
            sequence: 二级项值；无二级时为 None。

        Returns:
            是否有实际修改。

        Raises:
            AssertionError: config 未安装、段未落盘、或落点校验失败
                （``section`` 对缺失段返回游离 dict，直接写会静默丢失，故先断言）。
        """
        data = self._load_daily_config(allow_missing=True)
        assert data is not None, (
            f"[daily][{self.display_name}] config 未安装/未配置，不能写入副本"
        )
        assert self.section_exists(data), (
            f"[daily][{self.display_name}] config 缺少 {self.physical_name} 段"
        )
        changed = False
        for key, value in self._fields(task_name, sequence).items():
            changed |= safe_update(
                self.section(data),
                key,
                value,
                self.script_display_name,
                assert_key_exists=False,
            )
        if changed:
            self._save_daily_config(data)
            logger.info(f"[daily][{self.display_name}] config 已更新")
        else:
            logger.info(f"[daily][{self.display_name}] config 无需更新")
        return changed

    def read(self) -> tuple[str | None, str | int | None]:
        """反读该日常已选的 (一级项展示名, 二级值)。

        Returns:
            (一级项展示名, 二级值)；config 缺失 / 段未落盘 / 无落点 / 未选择时
            (None, None)，单层日常的副本名即日常名。

        Raises:
            AssertionError: 字段里的副本值不在声明里。
        """
        data = self._load_daily_config(allow_missing=True)
        if data is None or not self.section_exists(data):
            return None, None  # 未安装或段未落盘：无真相
        section = self.section(data)
        raw = section.get(self.task_field)
        if raw is None or raw == "":
            return None, None
        if self._single_field:
            return raw, None  # 字段里存的就是最终副本名，不做一级映射
        names = {value: name for name, value in self.task_map.items()}
        assert raw in names, f"[daily][{self.display_name}] 未知副本值: {raw!r}"
        task = names[raw]
        seq_field = self.option_fields[task]
        if seq_field not in section:
            return task, None
        return task, section[seq_field]

    def read_enabled(self) -> bool | None:
        """反读该日常是否启用；无开关落点的脚本返回 None。

        Returns:
            是否启用；未声明 ``enable_key``（无开关落点）时返回 None，
            界面据此不提供「不启用」。

        Raises:
            AssertionError: config 缺少开关字段或该字段不是布尔。
        """
        if not self._enable_key:
            return None
        data = self._load_daily_config(allow_missing=True)
        if data is None:
            return None  # 未安装/未配置：无真相
        return get_field(data, self._enable_key, self.display_name, bool)

    def set_enabled(self, enabled: bool) -> bool:
        """置该日常的启用状态；无开关落点的日常不做事。

        Args:
            enabled: 目标启用状态。

        Returns:
            是否有实际修改；未声明 ``enable_key`` 时恒为 False。

        Raises:
            AssertionError: config 未安装/未配置，或缺少开关字段。
        """
        if not self._enable_key:
            return False
        data = self._load_daily_config()
        if safe_update(data, self._enable_key, enabled, self.display_name):
            self._save_daily_config(data)
            return True
        return False

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


class BgiDaily(Daily):
    """原神的配置读写沿用两层日常，选项按 tp.json 秘境分类读取。

    开关在一条龙配置的任务启用表里，由声明 ``enable_task`` 给的任务名定位：
    id 由 BetterGI 生成，故按名反查而不硬编码。
    """

    _ENABLE_MAP = "TaskEnabledList"
    """一条龙的任务启用表（{任务 id: 是否启用}）。"""

    _TASK_DEFINITIONS = "TaskDefinitions"
    """任务 id → 任务名。"""

    def __init__(
        self, script_name: str, declaration: dict, script_display_name: str
    ) -> None:
        """解析日常声明并记录开关对应的原生任务名。

        Args:
            script_name: 所属脚本标识名。
            declaration: 该日常的声明节点，须声明 ``enable_task``。
            script_display_name: 所属脚本的展示名（日志与报错用）。

        Raises:
            AssertionError: 未声明 ``enable_task``。
        """
        super().__init__(script_name, declaration, script_display_name)
        self._enable_task: str = get_field(
            declaration, "enable_task", self.display_name, str
        )

    def _enabled_id(self, config: dict) -> str:
        """把声明里的任务名反查成任务 id。

        Args:
            config: 一条龙配置 dict。

        Returns:
            该任务在启用表里的 id。

        Raises:
            AssertionError: 缺少任务定义，或同名任务不是唯一一条。
        """
        definitions = get_field(config, self._TASK_DEFINITIONS, self.display_name, dict)
        matches = [
            key for key, name in definitions.items() if name == self._enable_task
        ]
        assert len(matches) == 1, (
            f"[daily][{self.display_name}] 任务定义缺少或重复 {self._enable_task}"
        )
        return matches[0]

    def read_enabled(self) -> bool | None:
        """反读该日常对应的原生任务是否启用。

        Returns:
            是否启用；一条龙配置缺失时返回 None。

        Raises:
            AssertionError: 配置缺少启用表/任务定义，或该任务的值不是布尔。
        """
        config = self._load_daily_config(allow_missing=True)
        if config is None:
            return None  # 未安装/未配置：无真相
        table = get_field(config, self._ENABLE_MAP, self.display_name, dict)
        return get_field(table, self._enabled_id(config), self.display_name, bool)

    def set_enabled(self, enabled: bool) -> bool:
        """置该日常对应的原生任务启用状态。

        Args:
            enabled: 目标启用状态。

        Returns:
            是否有实际修改。

        Raises:
            AssertionError: config 未安装/未配置，或缺少启用表/该任务。
        """
        config = self._load_daily_config()
        table = get_field(config, self._ENABLE_MAP, self.display_name, dict)
        if safe_update(table, self._enabled_id(config), enabled, self.display_name):
            self._save_daily_config(config)
            return True
        return False

    def get_task_lists(self, source: dict) -> list[str]:
        """原神资源：category 筛地图点位，无 category 时走通用键路径读取。"""
        if "category" not in source:
            return super().get_task_lists(source)
        assert source.keys() <= {"path", "category"}, (
            "原神资源来源只支持 path / category"
        )
        path = get_field(source, "path", self.display_name, str)
        category = get_field(source, "category", self.display_name, str)
        data = load_game_config(self.script_name, path)
        if not data:
            return []
        assert isinstance(data, dict), "原神地图资源必须为 dict"
        names = []
        # 地图和点位可没有秘境分类或名称，此时不提供选项。
        scenes = data["data"] if "data" in data else []  # noqa: SIM401
        for scene in scenes:
            if not isinstance(scene, dict) or "points" not in scene:
                continue
            for point in scene["points"]:
                if (
                    isinstance(point, dict)
                    and "type" in point
                    and point["type"] == category
                    and "name" in point
                    and point["name"]
                ):
                    names.append(point["name"])
        return names


class BgiLeyLineDaily(BgiDaily):
    """原神地脉花：一条龙按周几各持一组配置，本工具一次选择写满一周（7 天同值）。

    声明里的字段名用 ``{Day}`` 占位（``LeyLine{Day}Type`` / ``LeyLine{Day}Country``），
    展开为 Monday…Sunday 七个原生字段；反读时 7 天全同才认作已选。
    """

    _DAYS = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    """BetterGI 一条龙地脉花字段的按周几后缀。"""

    def _fields(
        self, task_name: str, sequence: str | int | None = None
    ) -> dict[str, Any]:
        """该次选择要写入的 {字段: 值}：把声明里的 ``{Day}`` 展开成一周 7 份。

        Args:
            task_name: 一级项展示名（花类型）。
            sequence: 二级项值（地区）；不传则只写花类型。

        Returns:
            {字段: 值}；7 个花类型字段，选了地区再追加 7 个地区字段。

        Raises:
            AssertionError: 未声明的一级项、二级必填却缺失，或二级取值不在声明里。
        """
        return {
            self._expand(key, day): value
            for key, value in super()._fields(task_name, sequence).items()
            for day in self._DAYS
        }

    def read(self) -> tuple[str | None, str | int | None]:
        """反读一周统一的选择：7 天的花类型与地区都相同才算已选。

        Returns:
            (一级项展示名, 二级值)；config 缺失、字段缺失或按天各异时
            (None, None)——按天各配的周计划不属于本工具的真相。

        Raises:
            AssertionError: 字段里的花类型不在声明里。
        """
        data = self._load_daily_config(allow_missing=True)
        if data is None:
            return None, None  # 未安装/未配置：无真相
        types = [data.get(self._expand(self.task_field, day), "") for day in self._DAYS]
        if not types[0] or any(value != types[0] for value in types):
            return None, None
        names = {value: name for name, value in self.task_map.items()}
        assert types[0] in names, (
            f"[daily][{self.display_name}] 未知副本值: {types[0]!r}"
        )
        task = names[types[0]]
        countries = [
            data.get(self._expand(self.option_fields[task], day), "")
            for day in self._DAYS
        ]
        if not countries[0] or any(value != countries[0] for value in countries):
            return task, None
        return task, countries[0]

    @staticmethod
    def _expand(field: str, day: str) -> str:
        """把声明里的 ``{Day}`` 占位换成某天。"""
        return field.replace("{Day}", day)


class NoopDaily(Daily):
    """无需适配副本的日常（绝区零/崩铁）：声明无落点，跳过解析，不读不写。"""

    def _parse_landing(self, declaration: dict) -> None:
        """无落点：不解析选项，仅置空通用字段。"""
        self.task_field = None
        self.task_map: dict[str, Any] = {}
        self.option_fields: dict[str, str] = {}

    def read(self) -> tuple[str | None, str | int | None]:
        """无副本真相：不读不解析。

        Returns:
            恒为 (None, None)。
        """
        return None, None

    def update(self, task_name: str, sequence: str | int | None = None) -> bool:
        """无需适配副本选择：不读不写。

        Args:
            task_name: 一级项展示名（本实现忽略）。
            sequence: 二级项值（本实现忽略）。

        Returns:
            恒为 False。
        """
        logger.info(f"[daily][{self.display_name}] 无需适配")
        return False


class Anomaly(Daily):
    """数据在自己那段、开关在第二份文件里的日常（异环的两个日常）。

    段名与 Routine Items 的 id 都取本日常声明的物理名；选完副本顺带启用自己那条，
    另一个日常的开关不动。单层带 ``key`` 的形态由 ``AnomalyHunter`` 解析。
    """

    def read_enabled(self) -> bool | None:
        """反读本日常的 Routine Item 是否启用；开关文件缺失返回 None。

        Returns:
            是否启用；开关文件缺失返回 None。

        Raises:
            AssertionError: Routine Items 缺少或重复本日常的物理名。
        """
        routine = self._load_routine_config()
        if routine is None:
            return None  # 开关文件缺失：无真相
        return bool(self._routine_item(routine)["enabled"])

    def set_enabled(self, enabled: bool) -> bool:
        """置本日常的 Routine Item 启用状态并落盘，另一个日常不动。

        Args:
            enabled: 目标启用状态。

        Returns:
            是否有实际修改（无变化即不落盘）。

        Raises:
            AssertionError: Routine Items 缺少或重复本日常的物理名。
        """
        routine = self._load_routine_config()
        if safe_update(
            self._routine_item(routine), "enabled", enabled, self.display_name
        ):
            self._save_routine_config(routine)
            return True
        return False

    def _routine_item(self, routine: dict) -> dict:
        """取 Routine Items 里本日常的 item。

        Args:
            routine: DailyRoutineTask.json 的 dict。

        Returns:
            本日常的 Routine Item dict。

        Raises:
            AssertionError: Routine Items 缺少或重复本日常的物理名。
        """
        items = get_field(routine, "Routine Items", self.display_name, list)
        target = [item for item in items if item["id"] == self.physical_name]
        assert len(target) == 1, (
            f"[daily][{self.display_name}] Routine Items 缺少或重复 {self.physical_name}"
        )
        return target[0]

    def section(self, config: dict) -> dict:
        """取本日常自己的段，段名即本日常物理名。

        Args:
            config: 顶层 config dict。

        Returns:
            本日常的段；段缺失返回空 dict（按未落盘处理）。

        Raises:
            AssertionError: 段存在但类型非 dict。
        """
        section = config.get(self.physical_name)
        assert section is None or isinstance(section, dict), (
            f"[daily][{self.display_name}] {self.physical_name} 段必须是 dict"
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


class AnomalyHunter(Anomaly):
    """追猎目标：单层带 ``key`` 的分段日常，解析与反读覆写为单层形态。"""

    def _parse_landing(self, declaration: dict) -> None:
        """解析单层带 ``key`` 的声明：整组自身即唯一一级项，展示名用日常名。

        Raises:
            AssertionError: 未声明选项或未声明 ``key``。
        """
        options = get_options(declaration)
        assert options, f"{self.script_name}/{self.physical_name} 必须声明选项"
        group = declaration["options"]
        assert "key" in group, (
            f"{self.script_name}/{self.physical_name} 的单层日常必须声明 key 作为落点"
        )
        self.task_field = None
        self.task_map: dict[str, Any] = {}
        self.option_fields: dict[str, str] = {self.display_name: group["key"]}
        self.options: list[dict] = [declaration]
        self._sequence_values: dict[str, dict[str, Any]] = (
            {self.display_name: get_value_map(declaration)} if "values" in group else {}
        )
        self._sequence_required = "values" in group
        self._single_field = False

    def read(self) -> tuple[str | None, str | int | None]:
        """反读该日常已选的 (日常名, 二级值)。

        Returns:
            (日常名, 二级值)；config 缺失 / 段未落盘 / 未选择时 (None, None)。

        Raises:
            AssertionError: 字段里的副本值不在声明里。
        """
        data = self._load_daily_config(allow_missing=True)
        if data is None or not self.section_exists(data):
            return None, None
        key = self.option_fields[self.display_name]
        if key not in self.section(data):
            return self.display_name, None
        return self.display_name, self.section(data)[key] or None


class MaaDaily(Daily):
    """一个原生 FightTask：名称来自声明，选择和开关保存在 MAA 中。"""

    def __init__(
        self, script_name: str, declaration: dict, script_display_name: str
    ) -> None:
        """解析日常声明并读取固定任务模板，原生配置仍在操作时读写。"""
        super().__init__(script_name, declaration, script_display_name)
        self._template = load_template(self.script_name, "MAA任务.json")
        assert isinstance(self._template, dict)
        assert get_field(self._template, "$type", self.display_name, str) == "FightTask"

    def _parse_landing(self, declaration: dict) -> None:
        """建立声明名称到原生关卡值的双向映射。"""
        self._stage_by_name = get_value_map(declaration)
        assert self._stage_by_name, f"{self.display_name} 未声明关卡"
        self._name_by_stage = {v: k for k, v in self._stage_by_name.items()}

    @staticmethod
    def _task_queue(config: dict) -> list[dict]:
        """取得 MAA 默认配置中的原生任务队列。"""
        configurations = get_field(config, "Configurations", "MAA", dict)
        profile = get_field(configurations, "Default", "MAA", dict)
        return get_field(profile, "TaskQueue", "MAA", list)

    def _find_task(self, queue: list[dict]) -> dict | None:
        """同名同类型取首项；重复项在初始化时清理。"""
        for task in queue:
            if get_field(task, "$type", "MAA", str) != "FightTask":
                continue
            # 原生任务可以没有自定义名称，只有声明所指的同名任务属于本入口。
            if "Name" in task and task["Name"] == self.physical_name:
                return task
        return None

    def _new_task(self, name: str) -> dict:
        """从实例持有的模板创建尚未选关的独立任务。"""
        task = deepcopy(self._template)
        task["Name"] = name
        return task

    @staticmethod
    def _medicine_days(queue: list[dict]) -> int:
        """采用现有任务共同的临期窗口；缺字段按 MAA 默认两天。"""
        days = set()
        for task in queue:
            if get_field(task, "$type", "MAA", str) == "FightTask":
                days.add(
                    get_field(task, "MedicineExpireDays", "MAA", int)
                    if "MedicineExpireDays" in task
                    else 2
                )
        if len(days) == 1:
            return days.pop()
        if len(days) > 1:
            logger.warning("[MAA] 临期窗口不一致，统一为周六起（2 天）")
        return 2

    @staticmethod
    def _set_medicine(queue: list[dict], days: int) -> None:
        """临期药对所有战斗常开，普通药和源石仍由原生配置管理。"""
        for task in queue:
            if get_field(task, "$type", "MAA", str) == "FightTask":
                task.update(UseExpiringMedicine=True, MedicineExpireDays=days)

    @staticmethod
    def _stage(task: dict | None) -> str:
        """仅接受单关卡选择，多关卡计划按未设置显示。"""
        if task is None or "StagePlan" not in task:
            return ""
        plan = get_field(task, "StagePlan", "MAA", list)
        if len(plan) != 1:
            return ""
        assert isinstance(plan[0], str)
        return plan[0]

    @staticmethod
    def _configure_task(task: dict, stage: str, enabled: bool, days: int) -> None:
        """仅接管单关卡、限制开关和临期药，运行交给 MAA。"""
        task.update(
            StagePlan=[stage],
            IsEnable=enabled and bool(stage),
            IsStageManually=True,
            UseOptionalStage=False,
            UseWeeklySchedule=False,
            EnableTimesLimit=False,
            EnableTargetDrop=False,
            UseExpiringMedicine=True,
            MedicineExpireDays=days,
        )

    def _init_task(self, queue: list[dict], days: int) -> dict:
        """补齐缺失入口；未选关和多关卡计划保持停用。"""
        task = self._find_task(queue)
        if task is None:
            task = self._new_task(self.physical_name)
            queue.append(task)
        enabled = get_field(task, "IsEnable", self.display_name) is True
        self._configure_task(task, self._stage(task), enabled, days)
        return task

    def update(self, task_name: str, sequence: str | int | None = None) -> bool:
        """写当前入口的单关卡，并沿用全部战斗共同的临期窗口。"""
        assert sequence is None, f"{self.display_name} 只选择一个关卡"
        stage = task_name
        if self._stage_by_name:
            assert task_name in self._stage_by_name, f"未声明关卡：{task_name}"
            stage = self._stage_by_name[task_name]
        config = self._load_daily_config()
        queue = self._task_queue(config)
        before = deepcopy(queue)
        days = self._medicine_days(queue)
        task = self._find_task(queue)
        if task is None:
            task = self._new_task(self.physical_name)
            queue.append(task)
        self._configure_task(task, stage, True, days)
        self._set_medicine(queue, days)
        if queue == before:
            return False
        self._save_daily_config(config)
        return True

    def read(self) -> tuple[str | None, None]:
        """直接反读原生选择，停用时仍保留所选关卡。"""
        config = self._load_daily_config(allow_missing=True)
        if config is None:
            return None, None
        stage = self._stage(self._find_task(self._task_queue(config)))
        if not stage:
            return None, None
        if stage in self._name_by_stage:
            stage = self._name_by_stage[stage]
        return stage, None

    def read_enabled(self) -> bool:
        """未选关或没有对应任务时返回未启用。"""
        config = self._load_daily_config(allow_missing=True)
        if config is None:
            return False
        task = self._find_task(self._task_queue(config))
        return bool(self._stage(task)) and get_field(task, "IsEnable", "MAA") is True

    def set_enabled(self, enabled: bool) -> bool:
        """只写开关，未选关的入口不能单独启用。"""
        config = self._load_daily_config()
        task = self._find_task(self._task_queue(config))
        if task is None or (enabled and not self._stage(task)):
            return False
        if task["IsEnable"] is enabled:
            return False
        task["IsEnable"] = enabled
        self._save_daily_config(config)
        return True


class MaaActivityDaily(MaaDaily):
    """活动关卡来自 MAA 缓存，仍以固定关卡值保存。"""

    def _parse_landing(self, declaration: dict) -> None:
        """保存活动资源路径，构造对象时不读取原生文件。"""
        options = get_field(declaration, "options", self.display_name, dict)
        source = get_field(options, "source", self.display_name, dict)
        self._activity_path = get_field(source, "path", self.display_name, str)
        self._stage_by_name = {}
        self._name_by_stage = {}

    def get_task_lists(self, source: dict) -> list[str]:
        """使用该日常自己的客户端配置读取活动选项。"""
        assert source.keys() == {"path"}
        return read_activity_stages(
            self.script_name, source["path"], self._config_rel_path
        )

    def _init_task(self, queue: list[dict], days: int) -> dict:
        """初始化时停用过期关卡，保留其固定代码。"""
        task = super()._init_task(queue, days)
        if task["IsEnable"] and self._stage(task) not in self.get_task_lists(
            {"path": self._activity_path}
        ):
            task["IsEnable"] = False
        return task


DAILY_CLASSES: dict[str, type[Daily]] = {
    cls.__name__: cls
    for cls in (
        Daily,
        BgiDaily,
        BgiLeyLineDaily,
        NoopDaily,
        Anomaly,
        AnomalyHunter,
        MaaDaily,
        MaaActivityDaily,
    )
}
"""声明 ``class`` 字段可引用的机制类注册表（键 = 类名）。"""
