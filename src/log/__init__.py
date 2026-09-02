"""日志解析核心包：各游戏脚本运行日志的解析与汇总（parse_log / parse_logs 等）。

迁移自原 `scripts/collect_log.py`；核心解析逻辑（Parser 类、辅助函数、
`parse_log` / `parse_logs`）现置于本包。诊断入口为 `python -m src.log`
（`__main__` 调用 `parse_logs(do_log=True)` 打印当日汇总报告）。
本包不依赖项目其余运行时模块（除 `src.utils_sub_config.get_script_name`），
保持独立可测试。

本包对外暴露的公开符号列入 `__all__`，下游可 `import src.log as collect_log`
后按 `collect_log.xxx` 直接访问。`monitor` 模块内的汇总/排版辅助函数（`_build_summary_report`、
`_cell_width`、`_pad_row`、`_prepare_action_lists`、常量 `_LOG_TAIL_LINES` / `_PARSERS` 等）
保持 `_` 私有，仅供本包与白盒测试使用，不在包级再导出。
"""

from .monitor import (
    BaseLogParser,
    BGILogParser,
    M7ALogParser,
    OkEfLogParser,
    OkNteLogParser,
    OkWwLogParser,
    ScriptLogStatus,
    ZZZLogParser,
    format_diagnostic_sections,
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
    "format_diagnostic_sections",
    "get_log_dir",
    "get_script_name",
    "log_info",
    "logger",
    "parse_log",
    "parse_logs",
    "status_cn",
]
