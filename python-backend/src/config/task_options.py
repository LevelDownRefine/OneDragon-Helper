"""已接入任务的附带选项；声明限定字段，原生配置仍是真源。"""

import ast
import logging
from copy import deepcopy
from pathlib import Path, PureWindowsPath

from src.config.task_source import read_task_source
from src.utils import get_root_dir
from src.utils.utils_io import load_data, load_yaml
from src.utils.utils_sub_config import (
    get_script_root_dir,
    get_sub_config_path,
    load_script_config,
    save_script_config,
)

logger = logging.getLogger(__name__)


def _relative_path(value: str) -> None:
    assert isinstance(value, str) and value
    path = PureWindowsPath(value)
    assert not path.is_absolute() and not path.drive and ".." not in path.parts


def load_declarations() -> dict:
    """读取并校验静态声明，不读取用户配置。"""
    data = load_yaml(str(Path(get_root_dir()) / "config" / "task_switch_list.yml"))
    data = {name: node["options"] for name, node in data.items() if "options" in node}
    for groups in data.values():
        assert isinstance(groups, list)
        identifiers = set()
        for group in groups:
            assert {"display_name", "config", "fields"} <= group.keys()
            _relative_path(group["config"])
            assert isinstance(group["display_name"], str) and group["display_name"]
            assert isinstance(group["fields"], list) and group["fields"]
            assert isinstance(group["tasks"], list)
            assert all(isinstance(name, str) and name for name in group["tasks"])
            for field in group["fields"]:
                assert {"id", "display_name", "keys", "type"} <= field.keys()
                assert isinstance(field["id"], str) and field["id"]
                assert field["id"] not in identifiers
                identifiers.add(field["id"])
                assert isinstance(field["display_name"], str) and field["display_name"]
                assert field["type"] in ("bool", "choice", "multi")
                assert isinstance(field["keys"], list) and field["keys"]
                assert all(isinstance(key, str) and key for key in field["keys"])
                if field["type"] != "bool":
                    assert ("values" in field) != ("source" in field)
                    if "source" in field:
                        _relative_path(field["source"]["path"])
    return data


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
                # 只读取 AST 中的字符串常量，不导入或执行外部脚本。
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                names = []
                for node in tree.body:
                    if isinstance(node, ast.ClassDef) and node.name == source["enum"]:
                        for item in node.body:
                            if isinstance(item, ast.Assign) and isinstance(
                                item.value, ast.Call
                            ):
                                argument = source["argument"]
                                if len(item.value.args) <= argument:
                                    raise ValueError("枚举构造参数已变化")
                                value = item.value.args[argument]
                                if not isinstance(
                                    value, ast.Constant
                                ) or not isinstance(value.value, str):
                                    raise ValueError("枚举候选名不再是字符串常量")
                                names.append(value.value)
                if not names:
                    raise ValueError("未找到枚举候选项")
            else:
                records = load_data(path, cached=False, encoding="utf-8-sig")
                if not isinstance(records, dict):
                    raise ValueError("候选资源不再是字典")
                assert "field" in source
                names = []
                for record in records.values():
                    if not isinstance(record, dict) or source["field"] not in record:
                        raise ValueError("候选资源字段已变化")
                    names.append(record[source["field"]])
            if not all(isinstance(name, str) and name for name in names):
                raise ValueError("候选资源名称必须是非空字符串")
            if "prepend" in source:
                names = [*source["prepend"], *names]
        assert isinstance(names, list)
        choices = []
        for name in names:
            if isinstance(name, str):
                choices.append({"display_name": name, "physical_name": name})
            else:
                assert (
                    isinstance(name, dict)
                    and {"display_name", "physical_name"} <= name.keys()
                )
                choices.append(dict(name))
        assert all(isinstance(item["physical_name"], str) for item in choices)
        assert len({item["physical_name"] for item in choices}) == len(choices)
        return choices

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
