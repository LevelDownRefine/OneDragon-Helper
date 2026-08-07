"""Runner 配置校验工具（GUI 侧复刻 runner 的 ScriptConfig.invalid_message）。

校验逻辑对齐 ``src/runner/script_chainer/config/script_config.py`` 的
``ScriptConfig.invalid_message``，但基于 config.yml 的 dict 条目（GUI 侧数据形态），
路径解析复用 ``resolve_script_path``（相对路径按项目根解析）。

注意：本模块与 runner 侧是两份独立实现，**改动校验规则时必须同步 runner 的
``ScriptConfig.invalid_message``**（反之亦然），避免两处规则漂移。

供 GUI 运行前（``MainWindow._run_selected``）校验使用，提前暴露
「脚本配置不合法 跳过运行」类问题，避免脚本链跑完才发现某脚本被
runner 静默跳过（如自动关机未执行）。
"""

import os
import sys
from pathlib import PureWindowsPath

from src.config.subscript import resolve_script_path

_CHECK_DONE_VALUES = {"game_closed", "script_closed", "game_or_script_closed"}


def _normalize_process_name(name: str) -> str:
    """规范化单个进程名，自动补齐 Windows 下的 `.exe` 后缀。

    对齐 runner script_chainer.utils.process_name_utils.normalize_process_name。
    """
    normalized = (name or "").strip()
    if not normalized:
        return ""
    if sys.platform == "win32" and not normalized.lower().endswith(".exe"):
        normalized = f"{normalized}.exe"
    return normalized


def _normalize_process_names(value) -> list[str]:
    """规范化进程名列表（去空白、补 .exe、去重）。

    对齐 runner script_chainer.utils.process_name_utils.normalize_process_names。
    """
    if value is None:
        return []
    raw_items = [value] if isinstance(value, str) else list(value)
    result: list[str] = []
    seen: set[str] = set()
    for raw_name in raw_items:
        name = _normalize_process_name(raw_name)
        if not name:
            continue
        dedupe_key = name.lower() if sys.platform == "win32" else name
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append(name)
    return result


def _process_name_equals(left: str | None, right: str | None) -> bool:
    """判断两个进程名是否相等，Windows 下按不区分大小写处理。

    对齐 runner script_chainer.utils.process_name_utils.process_name_equals。
    """
    if left is None or right is None:
        return left == right
    if sys.platform == "win32":
        return (
            _normalize_process_name(left).lower()
            == _normalize_process_name(right).lower()
        )
    return _normalize_process_name(left) == _normalize_process_name(right)


def script_invalid_message(script: dict) -> str | None:
    """校验单条脚本配置（config.yml 中的 script_list 条目），返回不合法原因或 None。

    与 runner ``ScriptConfig.invalid_message`` 对齐，但基于 dict 条目（GUI 侧数据形态），
    路径解析复用 ``resolve_script_path``（相对路径按项目根解析）。
    返回 ``None`` 表示合法。
    """
    script_type = script.get("script_type", "external")
    script_path = script.get("script_path") or ""

    if script_type == "python":
        if not script_path:
            return "Python 脚本路径为空"
        resolved = resolve_script_path(script_path)
        if not os.path.exists(resolved):
            return f"Python 脚本不存在 {script_path}"
        return None

    if not script_path:
        return "脚本路径为空"
    resolved = resolve_script_path(script_path)
    if not os.path.exists(resolved):
        return f"脚本路径不存在 {script_path}"

    check_done = script.get("check_done", "")
    if check_done not in _CHECK_DONE_VALUES:
        return f"检查完成方式非法 {check_done}"

    game_process_name = _normalize_process_name(script.get("game_process_name", ""))
    if (
        check_done in ("game_or_script_closed", "game_closed")
        or script.get("kill_game_after_done", False)
    ) and not game_process_name:
        return "游戏进程名称为空"

    script_process_names = _normalize_process_names(
        script.get("script_process_name")
    )
    if (
        script.get("launcher_mode", False)
        and (
            check_done in ("game_or_script_closed", "script_closed")
            or script.get("kill_script_after_done", True)
        )
        and not script_process_names
    ):
        return "启动后实际运行的程序为空"

    if script.get("launcher_mode", False) and script_path:
        launch_name = PureWindowsPath(script_path).name
        if any(
            _process_name_equals(item, launch_name) for item in script_process_names
        ):
            return f"启动后实际运行的程序不能包含启动程序本体 {launch_name}"

    run_timeout = script.get("run_timeout_seconds", 3600)
    if not run_timeout or int(run_timeout) <= 0:
        return "运行超时时间必须大于0"

    return None


def collect_invalid_script_messages(script_list: list[dict]) -> list[tuple[str, str]]:
    """遍历脚本列表，返回 ``[(display_name, invalid_message), ...]``（仅不合法项）。

    供 GUI 运行前与 CLI 生成前校验使用；合法脚本不出现在结果里。
    """
    result: list[tuple[str, str]] = []
    for script in script_list:
        message = script_invalid_message(script)
        if message is not None:
            result.append((script.get("display_name") or "(未命名)", message))
    return result
