from __future__ import annotations

import re
import tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Tuple


class ScriptLogStatus:
    SUCCESS = "Success!"
    FAILED = "Failed"
    NO_LOG = "NoLog"


def _read_file(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="gbk") as f:
            return f.read()
    except Exception:
        return ""


def _extract_datetime_from_content(content: str) -> Optional[datetime]:
    patterns = [
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})",
        r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})",
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            try:
                groups = match.groups()
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                hour = int(groups[3]) if len(groups) > 3 else 0
                minute = int(groups[4]) if len(groups) > 4 else 0
                second = int(groups[5]) if len(groups) > 5 else 0
                return datetime(year, month, day, hour, minute, second)
            except ValueError:
                continue
    return None


def _is_valid_log(content: str) -> bool:
    now = datetime.now()
    extracted_dt = _extract_datetime_from_content(content)
    if not extracted_dt:
        return False

    if now.hour >= 4:
        return extracted_dt.date() == now.date()

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if extracted_dt >= today_start:
        return True

    yesterday_4am = (now - timedelta(days=1)).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    return extracted_dt >= yesterday_4am


def _parse_ok_ww(log_content: str) -> str:
    if "Successfully Executed Task" in log_content or "Task completed" in log_content:
        return ScriptLogStatus.SUCCESS
    return ScriptLogStatus.FAILED


def _parse_ok_ef(log_content: str) -> str:
    if "执行状态: 完成" in log_content:
        return ScriptLogStatus.SUCCESS
    return ScriptLogStatus.FAILED


def _parse_m7a(log_content: str) -> str:
    if "游戏终止" in log_content:
        error_count = log_content.count("ERROR")
        if error_count <= 1:
            return ScriptLogStatus.SUCCESS
    return ScriptLogStatus.FAILED


def get_ok_ww_log_path(script_path: str) -> Path:
    ok_ww_dir = Path(script_path).parent
    return ok_ww_dir / "data" / "apps" / "ok-ww" / "working" / "logs" / "ok-script.log"


def get_ok_nte_log_path(script_path: str) -> Path:
    ok_nte_dir = Path(script_path).parent
    return ok_nte_dir / "data" / "apps" / "ok-nte" / "working" / "logs" / "ok-script.log"


def get_ok_ef_latest_log() -> Optional[Path]:
    log_dir = Path(tempfile.gettempdir()) / "ok-ef" / "日常任务"
    if not log_dir.exists():
        return None

    log_files = sorted(log_dir.glob("日常任务_*.txt"), reverse=True)
    for log_file in log_files:
        content = _read_file(log_file)
        if _is_valid_log(content):
            return log_file

    return None


def get_m7a_latest_log(script_path: str) -> Optional[Path]:
    m7a_dir = Path(script_path).parent
    logs_dir = m7a_dir / "logs"
    if not logs_dir.exists():
        return None

    log_files = sorted(logs_dir.glob("*.log"), reverse=True)
    for log_file in log_files:
        content = _read_file(log_file)
        if _is_valid_log(content):
            return log_file

    return None


def parse_log(display_name: str, script_path: str = "") -> dict:
    if display_name in ("ok-ww", "鸣潮"):
        log_path = get_ok_ww_log_path(script_path)
        if not log_path.exists():
            return {"status": ScriptLogStatus.NO_LOG, "log_path": str(log_path)}
        content = _read_file(log_path)
        if not _is_valid_log(content):
            return {"status": ScriptLogStatus.NO_LOG, "log_path": str(log_path)}
        return {
            "status": _parse_ok_ww(content),
            "log_path": str(log_path),
            "log_content": content[-2000:] if len(content) > 2000 else content,
        }

    if display_name in ("ok-nte", "异环"):
        log_path = get_ok_nte_log_path(script_path)
        if not log_path.exists():
            return {"status": ScriptLogStatus.NO_LOG, "log_path": str(log_path)}
        content = _read_file(log_path)
        if not _is_valid_log(content):
            return {"status": ScriptLogStatus.NO_LOG, "log_path": str(log_path)}
        return {
            "status": _parse_ok_ww(content),
            "log_path": str(log_path),
            "log_content": content[-2000:] if len(content) > 2000 else content,
        }

    if display_name in ("ok-ef", "终末地"):
        log_path = get_ok_ef_latest_log()
        if not log_path:
            return {"status": ScriptLogStatus.NO_LOG, "log_path": None}
        content = _read_file(log_path)
        return {
            "status": _parse_ok_ef(content),
            "log_path": str(log_path),
            "log_content": content[-2000:] if len(content) > 2000 else content,
        }

    if display_name in ("M7A", "崩铁"):
        log_path = get_m7a_latest_log(script_path)
        if not log_path:
            return {"status": ScriptLogStatus.NO_LOG, "log_path": None}
        content = _read_file(log_path)
        return {
            "status": _parse_m7a(content),
            "log_path": str(log_path),
            "log_content": content[-2000:] if len(content) > 2000 else content,
        }

    return {"status": "不支持的脚本", "log_path": None}


def main():
    import yaml
    from src.utils import get_root_dir

    config_path = Path(get_root_dir()) / "config" / "config.yml"
    assert config_path.exists(), f"[log_monitor] config.yml 不存在: {config_path}"

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    script_list = config_data.get("script_list", [])
    supported_scripts = ("鸣潮", "终末地", "崩铁", "异环")

    print("=" * 60)
    print("脚本运行状况汇总报告")
    print("=" * 60)

    success_count = 0
    failed_count = 0
    no_log_count = 0
    failed_results = []

    for script in script_list:
        display_name = script.get("display_name", "")
        script_path = script.get("script_path", "")

        if display_name not in supported_scripts:
            continue

        result = parse_log(display_name, script_path)
        status = result["status"]

        if status == ScriptLogStatus.SUCCESS:
            status_icon = "[OK]"
            success_count += 1
        elif status == ScriptLogStatus.FAILED:
            status_icon = "[FAIL]"
            failed_count += 1
            failed_results.append((display_name, result))
        else:
            status_icon = "[NO LOG]"
            no_log_count += 1

        print(f"\n{status_icon} {display_name}")
        print(f"   状态: {status}")
        if result["log_path"]:
            print(f"   日志: {result['log_path']}")

    print("\n" + "=" * 60)
    print(
        f"总计: {success_count + failed_count + no_log_count} 个脚本"
        f" | 成功: {success_count} | 失败: {failed_count} | 无日志: {no_log_count}"
    )

    if failed_results:
        print("\n" + "=" * 60)
        print("失败脚本详情")
        print("=" * 60)

        for display_name, result in failed_results:
            print(f"\n[{display_name}] 日志内容:")
            print("-" * 40)
            if "log_content" in result:
                print(result["log_content"])
            else:
                print("无日志内容")


if __name__ == "__main__":
    main()