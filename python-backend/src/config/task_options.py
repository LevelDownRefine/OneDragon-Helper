"""已接入任务的附带选项；声明限定字段，原生配置仍是真源。"""

import logging
from copy import deepcopy
from pathlib import Path

from src.config.task_parser import (
    parse_choices,
    parse_enum_names,
    parse_record_names,
    parse_resource_choices,
    parse_task_options,
)
from src.config.task_source import read_task_source
from src.utils import get_root_dir
from src.utils.utils_io import load_data
from src.utils.utils_sub_config import (
    get_script_root_dir,
    get_sub_config_path,
    load_script_config,
    save_script_config,
)

logger = logging.getLogger(__name__)


def load_declarations() -> dict:
    """读取附带选项声明，交由 task_parser 校验。"""
    return parse_task_options(
        load_data(
            str(Path(get_root_dir()) / "config" / "task_switch_list.yml"),
            "yaml",
            cached=True,
        )
    )


class TaskOptions:
    """一个脚本的业务选项；按字段标识写入，不暴露任意文件或键路径。"""

    def __init__(self, script_name: str, groups: list[dict]) -> None:
        self.script_name = script_name
        self.groups = groups

    def _choices(self, field: dict) -> list[dict]:
        if field["type"] == "bool":
            return []
        if "values" in field:
            names = field["values"]
        else:
            source = field["source"]
            path = Path(get_sub_config_path(self.script_name, source["path"]))
            if not path.exists():
                logger.warning("[%s] 任务选项资源缺失：%s", self.script_name, path)
                return []
            if "prefix" in source:
                names = [
                    item.stem.removeprefix(source["prefix"])
                    for item in sorted(path.glob(f"{source['prefix']}*.json"))
                ]
            elif "key" in source:
                names = read_task_source(self.script_name, source)
            elif "enum" in source:
                names = parse_enum_names(path.read_text(encoding="utf-8-sig"), source)
            else:
                records = load_data(
                    path, file_format="json", cached=False, encoding="utf-8-sig"
                )
                names = parse_record_names(records, source)
            return parse_resource_choices(names, source)
        return parse_choices(names)

    @staticmethod
    def _value(config: dict, field: dict):
        node = config
        for key in field["keys"]:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return deepcopy(node)

    def _load(self, group: dict) -> dict | None:
        return load_script_config(
            self.script_name, self.script_name, group["config"], allow_missing=True
        )

    def read(self) -> list[dict]:
        """物化字段与候选项；资源缺失时不提供该选择，读取不创建文件。"""
        if not self.groups:
            return []
        root = get_script_root_dir(self.script_name)
        if root is None or not Path(root).is_dir():
            return []
        rows = []
        for group in self.groups:
            config = self._load(group)
            if config is None:
                continue
            for field in group["fields"]:
                try:
                    choices = self._choices(field)
                except (
                    OSError,
                    UnicodeError,
                    SyntaxError,
                    ValueError,
                ) as exc:
                    logger.warning(
                        "[%s] 任务选项 %s 资源读取失败（%s），跳过",
                        self.script_name,
                        field["id"],
                        type(exc).__name__,
                    )
                    continue
                if field["type"] != "bool" and not choices:
                    continue
                value = self._value(config, field)
                if value is None:
                    continue
                if not self._valid_type(field, value):
                    logger.warning(
                        "[%s] 任务选项 %s 类型不符，跳过", self.script_name, field["id"]
                    )
                    continue
                # 原脚本新增或移除的值仍可回显、原样保留。
                current = [value] if field["type"] == "choice" else value
                if field["type"] != "bool":
                    for item in current:
                        if item not in [choice["physical_name"] for choice in choices]:
                            choices.append(
                                {"display_name": item, "physical_name": item}
                            )
                rows.append(
                    {
                        "id": field["id"],
                        "group": group["display_name"],
                        "tasks": group.get(
                            "tasks", [group["display_name"]]
                        ),  # 兼容旧声明。
                        "display_name": field["display_name"],
                        "type": field["type"],
                        "value": value,
                        "choices": choices,
                    }
                )
        return rows

    @staticmethod
    def _valid_type(field: dict, value) -> bool:
        if field["type"] == "bool":
            return type(value) is bool
        if field["type"] == "choice":
            return isinstance(value, str)
        return (
            isinstance(value, list)
            and all(isinstance(item, str) for item in value)
            and len(value) == len(set(value))
        )

    def prepare(self, values: dict) -> list[tuple[str, dict]]:
        """重新读盘并校验全部修改，任何输入无效时均不写盘。"""
        rows = {row["id"]: row for row in self.read()}
        for ident, value in values.items():
            if ident not in rows:
                raise ValueError(f"任务选项 {ident} 已不可用，请刷新配置")
            row = rows[ident]
            if not self._valid_type(row, value):
                raise ValueError(f"{row['display_name']} 类型无效")
            if row["type"] != "bool":
                choices = {choice["physical_name"] for choice in row["choices"]}
                selected = [value] if row["type"] == "choice" else value
                if any(item not in choices for item in selected):
                    raise ValueError(f"{row['display_name']} 包含未知选项")
            field = next(
                field
                for group in self.groups
                for field in group["fields"]
                if field["id"] == ident
            )
            if "min_items" in field and len(value) < field["min_items"]:
                raise ValueError(
                    f"{row['display_name']} 至少选择 {field['min_items']} 项"
                )
        pending = {}
        for group in self.groups:
            selected = [field for field in group["fields"] if field["id"] in values]
            if not selected:
                continue
            path = group["config"]
            if path not in pending:
                config = self._load(group)
                if config is None:
                    raise ValueError("任务配置已不可用，请刷新配置")
                pending[path] = config
            for field in selected:
                node = pending[path]
                for key in field["keys"][:-1]:
                    if key not in node:
                        node[key] = {}
                    if not isinstance(node[key], dict):
                        raise ValueError(f"{field['display_name']} 配置结构已变化")
                    node = node[key]
                node[field["keys"][-1]] = deepcopy(values[field["id"]])
        return list(pending.items())

    def write_prepared(self, pending: list[tuple[str, dict]]) -> None:
        """保存已校验的修改，保留文件其他字段。"""
        for path, config in pending:
            Path(get_sub_config_path(self.script_name, path)).parent.mkdir(
                parents=True, exist_ok=True
            )
            save_script_config(self.script_name, self.script_name, path, config)


def task_options_of(script_name: str) -> TaskOptions:
    """未声明的脚本没有附带选项。"""
    declarations = load_declarations()
    return TaskOptions(
        script_name,
        declarations.get(script_name, []),  # 未声明的脚本没有选项。
    )
