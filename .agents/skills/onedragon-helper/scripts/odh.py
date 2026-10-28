# /// script
# requires-python = ">=3.11"
# dependencies = ["ruamel.yaml>=0.18"]
# ///
"""Inspect an installation with the latest OneDragon-Helper backend source."""

import argparse
import importlib
import json
import logging
import sys
from pathlib import Path

from log_tools import list_log_files, read_log
from ruamel.yaml.error import YAMLError
from source_cache import default_cache, ensure_source, source_info

logger = logging.getLogger(__name__)


def object_field(data: dict, key: str, expected: type):
    if key not in data or not isinstance(data[key], expected):
        raise ValueError(f"Missing or invalid field: {key}")
    return data[key]


class Backend:
    """Bind one installation before importing backend consumers, once per process.

    Upstream has no public root override. Only its root provider is replaced in
    memory; all declarations, path semantics and parsers remain upstream-owned.
    """

    def __init__(self, source: Path, install: Path):
        if any(name == "src" or name.startswith("src.") for name in sys.modules):
            raise RuntimeError("Backend already imported; use a fresh odh.py process")
        self.source = source.resolve()
        self.install = install.resolve()
        self.package = self.source / "python-backend" / "src"
        if not (self.package / "utils" / "__init__.py").is_file():
            raise FileNotFoundError(f"Backend source not found: {self.source}")
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(self.package.parent))
        utils = self.module("src.utils")
        utils.get_root_dir = lambda: str(self.install)
        self.io = self.module("src.utils.utils_io")
        self.paths = self.module("src.utils.utils_sub_config")

    def module(self, name: str):
        module = importlib.import_module(name)
        # src is a namespace package: another ordinary src package can take priority.
        for loaded_name, loaded in tuple(sys.modules.items()):
            if loaded_name.startswith("src."):
                filename = getattr(loaded, "__file__", None)
                if filename is None or not Path(filename).resolve().is_relative_to(
                    self.package
                ):
                    raise ImportError(
                        f"Backend module loaded outside source: {loaded_name}"
                    )
        return module

    def mapping(self, path: Path) -> dict:
        data = self.io.load_data(path, file_format="yaml", encoding="utf-8-sig")
        if not isinstance(data, dict):
            raise ValueError(f"Expected mapping in {path}")
        return data

    def list_scripts(self) -> list[dict]:
        scripts = object_field(
            self.mapping(self.install / "config" / "config.yml"), "script_list", list
        )
        result = []
        names = set()
        for script in scripts:
            if not isinstance(script, dict):
                raise ValueError("Invalid script entry")
            path = object_field(script, "script_path", str)
            display = object_field(script, "display_name", str)
            name = self.paths.get_script_name(script)
            if not name or name in names:
                raise ValueError(f"Empty or duplicate script id: {name!r}")
            names.add(name)
            result.append(
                {"script_name": name, "display_name": display, "script_path": path}
            )
        return result

    def select(self, names: list[str]) -> list[dict]:
        available = self.list_scripts()
        selected = []
        for name in dict.fromkeys(names):
            matches = [
                s for s in available if object_field(s, "script_name", str) == name
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Expected one script with id {name!r}; use list first"
                )
            selected.append(matches[0])
        return selected

    def log_info(self, script: dict) -> dict:
        parsers = object_field(
            self.mapping(self.install / "config" / "log_analysis.yml"), "parsers", dict
        )
        name = object_field(script, "script_name", str)
        # Custom scripts need not have a log declaration.
        rules = parsers.get(name, {})
        if not isinstance(rules, dict):
            raise ValueError(f"Invalid log declaration for {name}")
        patterns = {}
        for kind, analysis in (("realtime", False), ("analysis", True)):
            path = self.paths.resolve_log_path(script, analysis=analysis)
            patterns[kind] = str(path) if path is not None else None
        return {"log_patterns": patterns, "log_rules": rules}

    def inspect(self, names: list[str]) -> list[dict]:
        resources = self.module("src.config.script_resources").load_resource_manifest(
            str(self.install / "config" / "script_resources.yml")
        )
        entries = []
        for script in self.select(names):
            raw = object_field(script, "script_path", str)
            location = (
                Path(self.paths.resolve_script_path(raw).replace("\\", "/"))
                if raw
                else None
            )
            name = object_field(script, "script_name", str)
            repository = {"url": None, "source": "unknown"}
            if name in resources:
                links = object_field(resources[name], "links", dict)
                repository = {
                    "url": object_field(links, "github", str),
                    "source": str(self.install / "config" / "script_resources.yml"),
                }
            entries.append(
                {
                    **script,
                    "executable_path": str(location) if location is not None else None,
                    "script_directory": str(location.parent)
                    if location is not None
                    else None,
                    "executable_exists": location.is_file() if location else False,
                    "directory_exists": location.parent.is_dir() if location else False,
                    "repository": repository,
                    **self.log_info(script),
                }
            )
        return entries

    def analyze(self, names: list[str]) -> list[dict]:
        monitor = self.module("src.log.monitor")
        # Upstream exposes parse_log but keeps its parser registry private.
        supported = {parser.script_name for parser in monitor._PARSERS}
        entries = []
        for script in self.select(names):
            info = self.log_info(script)
            name = object_field(script, "script_name", str)
            patterns = object_field(info, "log_patterns", dict)
            assert "analysis" in patterns
            path = patterns["analysis"]
            entry = {"script_name": name, "analysis_pattern": path, "result": None}
            if name not in supported:
                entry["reason"] = "unsupported_parser"
            elif path is None:
                entry["reason"] = "analysis_log_not_configured"
            else:
                entry["result"] = monitor.parse_log(name, path)
                rules = object_field(info, "log_rules", dict)
                # Upstream treats absent completion markers as done to avoid reruns.
                entry["daily_completion_checkable"] = bool(
                    rules.get("daily_success_marker", [])
                )
            entries.append(entry)
        return entries


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--install", type=Path, help="完整助手安装目录")
    root.add_argument("--source", type=Path, help="已有助手源码根目录；省略时用缓存")
    sub = root.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="下载或更新默认分支最新源码")
    setup.add_argument("--cache", type=Path, default=default_cache())
    sub.add_parser("list", help="列出已配置脚本")
    for command, help_text in (
        ("inspect", "查询目录、仓库和日志规则"),
        ("analyze", "调用后端解析器分析当日日志"),
    ):
        command_parser = sub.add_parser(command, help=help_text)
        command_parser.add_argument("--script", action="append", required=True)
    logs = sub.add_parser("logs", help="列出日志文件")
    logs.add_argument("--script")
    logs.add_argument(
        "--kind",
        choices=("all", "realtime", "analysis", "helper", "runner"),
        default="all",
    )
    logs.add_argument("--limit", type=int, default=10)
    read = sub.add_parser("read-log", help="读取带行号的原文或搜索上下文")
    read.add_argument("--path", type=Path, required=True)
    read.add_argument("--start-line", type=int, default=1)
    read.add_argument("--lines", type=int, default=200)
    read.add_argument("--find")
    read.add_argument("--context", type=int, default=3)
    read.add_argument("--max-matches", type=int, default=20)
    read.add_argument("--encoding", default="auto")
    return root


def execute(args: argparse.Namespace) -> dict:
    if args.command == "setup":
        if args.source is not None:
            raise ValueError("setup uses --cache; --source is for existing source")
        return {"source": ensure_source(args.cache, refresh=True)}
    if args.command == "read-log":
        return read_log(
            args.path,
            start_line=args.start_line,
            lines=args.lines,
            find=args.find,
            context=args.context,
            max_matches=args.max_matches,
            encoding=args.encoding,
        )
    if args.install is None:
        raise ValueError("--install is required for this command")
    install = args.install.resolve()
    if not install.is_dir():
        raise NotADirectoryError(f"Installation directory not found: {install}")
    patterns = {
        "helper": str(install / "logs" / "onedragon_helper*.log*"),
        "runner": str(install / ".log" / "*.log*"),
    }
    if args.command == "logs" and args.kind in ("helper", "runner"):
        return list_log_files({args.kind: patterns[args.kind]}, limit=args.limit)
    source = (
        source_info(args.source)
        if args.source is not None
        else ensure_source(default_cache())
    )
    backend = Backend(Path(object_field(source, "path", str)), install)
    version_path = install / "version.json"
    version = (
        backend.io.load_data(version_path, file_format="json", encoding="utf-8-sig")
        if version_path.is_file()
        else None
    )
    context = {
        "installation": str(install),
        "helper_version": version,
        "source": source,
    }
    if args.command == "list":
        return {**context, "scripts": backend.list_scripts()}
    if args.command == "inspect":
        return {**context, "scripts": backend.inspect(args.script)}
    if args.command == "analyze":
        return {
            **context,
            "scope": "运行日从本地时间 04:00 起；结果不代表本轮运行，需核对原日志",
            "scripts": backend.analyze(args.script),
        }
    if args.script is None:
        raise ValueError("--script is required for realtime/analysis/all logs")
    info = backend.log_info(backend.select([args.script])[0])
    patterns.update(object_field(info, "log_patterns", dict))
    if args.kind != "all":
        assert args.kind in patterns
        patterns = {args.kind: patterns[args.kind]}
    return {
        **context,
        "script_name": args.script,
        **list_log_files(patterns, limit=args.limit),
    }


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    args = parser().parse_args()
    try:
        result = execute(args)
    except (
        OSError,
        ValueError,
        ImportError,
        RuntimeError,
        AssertionError,
        YAMLError,
    ) as error:
        # Backend assertions validate declarations; surface incompatibility as an error.
        logger.error("%s: %s", type(error).__name__, error)
        json.dump(
            {"error": str(error), "type": type(error).__name__},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
