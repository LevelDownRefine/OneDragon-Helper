"""log 测试共享夹具：构造 monitor.parse_logs 的返回结构与 entries。"""

from src.log.monitor import ScriptLogStatus


def make_result(*, notify=("demo",), entries=()) -> dict:
    """构造最小 parse_logs 产物。

    Args:
        notify: 报错脚本列表；传空元组表示「本次全成功」，用于验证仍发汇总邮件。
        entries: 各脚本解析结果（含 display_name / result），供表格与诊断段消费。

    Returns:
        最小 result dict（含 report / entries / notify / rerun）。
    """
    return {
        "report": "脚本运行状况汇总报告",
        "entries": list(entries),
        "notify": list(notify),
        "rerun": [],
    }


def make_entry(name: str, status: str, *, errors=(), stamina=None) -> dict:
    """构造一条脚本解析结果，字段与 monitor.parse_logs 的 entries 一致。

    Args:
        name: 展示名。
        status: ScriptLogStatus 状态值。
        errors: 报错行列表。
        stamina: 剩余体力；None 表示日志无体力。

    Returns:
        单个 entry dict。
    """
    return {
        "display_name": name,
        "result": {
            "status": status,
            "stamina": stamina,
            "daily_done": status == ScriptLogStatus.SUCCESS,
            "errors": list(errors),
            "log_content": "",
            "log_path": None,
        },
    }
