"""日志解析核心包：各游戏脚本运行日志的解析与汇总。

迁移自原 `scripts/collect_log.py`：核心解析逻辑（Parser 类、辅助函数、
`parse_log` / `parse_logs`）现置于本包，`scripts/collect_log.py` 仅作 CLI 入口薄壳。
本包不依赖项目其余运行时模块（除 `src.config.subscript.get_script_name`），
保持独立可测试。

为兼容下游 `import src.log as collect_log` 后按 `collect_log._xxx` 访问内部符号，
以下私有符号一并显式再导出（列入 `__all__` 以声明再导出意图）。
"""

from .monitor import (
    _LOG_TAIL_LINES,
    _PARSERS,
    BaseLogParser,
    BGILogParser,
    M7ALogParser,
    OkEfLogParser,
    OkNteLogParser,
    OkWwLogParser,
    ScriptLogStatus,
    ZZZLogParser,
    _build_summary_report,
    _cell_width,
    _format_diagnostic_sections,
    _get_root_dir,
    _pad_row,
    _prepare_action_lists,
    _resolve_exited,
    get_log_dir,
    get_script_name,
    log_info,
    logger,
    parse_log,
    parse_logs,
    status_cn,
)

__all__ = [
    "BaseLogParser",
    "BGILogParser",
    "M7ALogParser",
    "OkEfLogParser",
    "OkNteLogParser",
    "OkWwLogParser",
    "ScriptLogStatus",
    "ZZZLogParser",
    "_LOG_TAIL_LINES",
    "_PARSERS",
    "_build_summary_report",
    "_cell_width",
    "_format_diagnostic_sections",
    "_get_root_dir",
    "_pad_row",
    "_prepare_action_lists",
    "_resolve_exited",
    "get_log_dir",
    "get_script_name",
    "log_info",
    "logger",
    "parse_log",
    "parse_logs",
    "status_cn",
]
