"""CLI 出口：无头命令行子命令（不进入 GUI 事件循环）。

提供 --help / --version / --selftest / --generate-chain / --run-chain /
--schedule-run / --check-config / --list-scripts / --get-script / --dump-config /
--check-weekly 等出口，
供打包产物集成测试与排障使用。windowed exe 的 stdout/stderr 被丢弃，
因此 --help/--version 等结果会**同时写文件**（见 _emit_cli / _emit_json）。

GUI 主路径见 :mod:`src.launcher`，本模块不依赖 Qt。
"""

import argparse
import json
import logging
import os
import tempfile
import tomllib
import warnings

from src.config.set_config import supports_weekly
from src.service.app_service import AppService
from src.utils_config import get_script
from src.utils_shutdown import shutdown_sys
from src.utils_sub_config import get_script_name

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器（对齐 Runner 的 argparse 风格）。

    GUI 主程序本质是窗口应用，但提供「不进入 GUI 事件循环」的 CLI 出口，
    便于打包产物的集成测试与排障。windowed exe 的 stdout/stderr 被丢弃，
    因此结果会**同时写文件**（见 _emit_cli / _emit_json）。
    """
    parser = argparse.ArgumentParser(
        prog="OneDragon-Helper",
        description="OneDragon-Helper",
        add_help=False,
    )
    parser.add_argument(
        "--help", action="store_true", help="显示用法并退出（结果同时写文件）"
    )
    parser.add_argument(
        "--version", action="store_true", help="显示版本并退出（结果同时写文件）"
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--selftest",
        action="store_true",
        help="无头自检：校验 AppService 配置/脚本列表，结果写 JSON 后退出",
    )
    action.add_argument(
        "--check-config",
        action="store_true",
        help="校验 config.yml 全部脚本合法性，结果写 JSON 后退出（0=全部合法）",
    )
    action.add_argument(
        "--list-scripts",
        action="store_true",
        help="列出所有脚本唯一标识，结果写文件后退出",
    )
    action.add_argument(
        "--get-script",
        metavar="SCRIPT_KEY",
        help="查询单个脚本条目（按唯一标识），结果写 JSON 后退出",
    )
    action.add_argument(
        "--dump-config",
        action="store_true",
        help="导出完整 config.yml（JSON），结果写文件后退出",
    )
    action.add_argument(
        "--check-weekly",
        action="store_true",
        help="校验 weekly_timeouts.yml 与 config 脚本一致性，结果写 JSON 后退出",
    )
    action.add_argument(
        "--generate-chain",
        action="store_true",
        help="生成脚本链配置（仅含启用的脚本）并退出，结果写文件后退出",
    )
    action.add_argument(
        "--run-chain",
        metavar="PATH",
        help="运行指定路径的脚本链配置并退出（透传 --shutdown 等参数给 Runner）",
    )
    action.add_argument(
        "--schedule-run",
        metavar="HH:MM",
        help="等待到目标时刻再生成并运行脚本链（独立进程，关闭控制台即取消；"
        "配合 --enable 指定脚本、--shutdown 指定关机延迟）。传 'now' 表示即时运行（不等待）",
    )
    parser.add_argument(
        "--enable",
        type=str,
        default="all",
        help="纳入链的脚本标识白名单（逗号分隔）；默认 all（全部脚本）。"
        "也可显式写 all 表示全部。未知标识会报错退出。",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        default=None,
        help="配合 --generate-chain，逗号分隔的脚本标识黑名单（从启用集合中剔除）",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="today",
        help="配合 --generate-chain，脚本链文件名（不含扩展名，默认 today）",
    )
    parser.add_argument(
        "--shutdown",
        type=int,
        default=None,
        help="配合 --run-chain，运行结束后多少秒关机（由主仓库编排，链运行结束后触发）",
    )
    parser.add_argument(
        "--no-block",
        action="store_true",
        help="配合 --run-chain，即起即返（后台非阻塞运行整条链）",
    )
    parser.add_argument(
        "--mute",
        action="store_true",
        help="运行期间静音（透传 --mute 给 Runner）",
    )
    parser.add_argument(
        "--close-running",
        action="store_true",
        help="运行前关闭残留的脚本/游戏进程（透传 --close-running 给 Runner）",
    )
    parser.add_argument(
        "--weekly-start",
        type=str,
        default=None,
        help="配合 --generate-chain，覆盖周常起始日（周几起 1=周一~7=周日），"
        "格式 '脚本标识=1~7'（逗号分隔多个）；今天周几 >= 起始日才执行周常",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="结果 JSON 路径或链配置输出路径"
        "（默认 %%TEMP%%/odh_gui_<出口>.json 或 config/script_chain/<name>.yml）",
    )
    return parser


def _emit_cli(kind: str, text: str) -> None:
    """把 CLI 输出同时打印（dev 可见）与写文件（windowed exe 可观测）。

    Args:
        kind: 出口名，用于默认输出文件名 odh_gui_<kind>.txt。
        text: 要写出的文本。

    写文件失败时告警（windowed exe 下文件是唯一可观测渠道，不能静默丢弃）。
    """
    print(text)
    path = os.path.join(tempfile.gettempdir(), f"odh_gui_{kind}.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError as exc:
        warnings.warn(f"[cli] 无法写入 {path}: {exc}", RuntimeWarning, stacklevel=2)


def _emit_json(kind: str, data: dict, out_path: str | None = None) -> None:
    """把结构化结果同时打印（JSON 单行）与写文件（windowed exe 可观测/测试可断言）。

    Args:
        kind: 出口名，用于默认输出文件名 odh_gui_<kind>.json。
        data: 要输出的 JSON 可序列化 dict。
        out_path: 指定输出路径；None 时用默认 %TEMP%/odh_gui_<kind>.json。

    写文件失败时告警（windowed exe 下文件是唯一可观测渠道，不能静默丢弃）。
    """
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)
    out = out_path or os.path.join(tempfile.gettempdir(), f"odh_gui_{kind}.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError as exc:
        warnings.warn(f"[cli] 无法写入 {out}: {exc}", RuntimeWarning, stacklevel=2)


def get_version() -> str:
    """读取 pyproject.toml 的 [project] version。

    Returns:
        版本字符串；pyproject.toml 缺失时返回 "unknown" 并告警
        （打包产物不含源码树属正常场景）。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pyproject_path = os.path.join(root, "pyproject.toml")
    if not os.path.exists(pyproject_path):
        warnings.warn(
            f"[cli] 找不到 pyproject.toml: {pyproject_path}",
            RuntimeWarning,
            stacklevel=2,
        )
        return "unknown"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    assert "project" in data, "[cli] pyproject.toml 缺少 [project] 段"
    assert "version" in data["project"], "[cli] pyproject.toml 缺少 project.version"
    return str(data["project"]["version"])


def _run_selftest(out_path: str | None) -> int:
    """无头自检：经 AppService 校验关键依赖/配置/脚本列表。

    结果写入 JSON（默认 %TEMP%/odh_gui_selftest.json），返回退出码 0=OK / 1=失败。
    供打包产物集成测试 test_gui_exe.py 读取验证实质行为。
    """
    result: dict = {"status": "fail", "checks": {}}
    try:
        app_service = AppService()
        data = app_service.load_config()
        result["checks"]["service_ready"] = True
        result["checks"]["script_count"] = len(data["script_list"])
        result["checks"]["config_loaded"] = True
        result["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - 自检需捕获一切以产出失败结果
        result["status"] = "fail"
        result["error"] = str(exc)

    _emit_json("selftest", result, out_path)
    return 0 if result["status"] == "ok" else 1


def _run_check_config(out_path: str | None) -> int:
    """CLI: 校验 config.yml 全部脚本合法性。

    返回退出码 0=全部合法 / 1=存在不合法项。
    """
    try:
        app_service = AppService()
        all_config_data = app_service.load_config()
        invalid = app_service.collect_invalid_scripts(all_config_data["script_list"])
        result = {
            "status": "ok" if not invalid else "invalid",
            "script_count": len(all_config_data["script_list"]),
            "invalid": [{"name": n, "message": m} for n, m in invalid],
        }
        _emit_json("check_config", result, out_path)
        return 0 if not invalid else 1
    except Exception as exc:  # noqa: BLE001 - CLI 需捕获一切以产出失败结果
        _emit_json("check_config", {"status": "fail", "error": str(exc)}, out_path)
        return 1


def _run_list_scripts(out_path: str | None) -> int:
    """CLI: 列出所有脚本唯一标识（exe 用进程名，脚本文件用 display_name）。"""
    app_service = AppService()
    all_config_data = app_service.load_config()
    names = [get_script_name(s) for s in all_config_data["script_list"]]
    result = {"script_count": len(names), "scripts": names}
    _emit_json("list_scripts", result, out_path)
    return 0


def _run_get_script(script_name: str, out_path: str | None) -> int:
    """CLI: 查询单个脚本条目（按唯一标识，JSON）。

    返回退出码 0=找到 / 1=不存在。
    """
    script = get_script(script_name)
    if script is None:
        _emit_json(
            "get_script",
            {"status": "not_found", "script_name": script_name},
            out_path,
        )
        return 1
    _emit_json("get_script", {"status": "ok", "script": script}, out_path)
    return 0


def _run_dump_config(out_path: str | None) -> int:
    """CLI: 导出完整 config.yml（JSON）。"""
    app_service = AppService()
    all_config_data = app_service.load_config()
    _emit_json("dump_config", all_config_data, out_path)
    return 0


def _run_check_weekly(out_path: str | None) -> int:
    """CLI: 校验 weekly_timeouts.yml 与 config 脚本一致性。

    检查项：
    - config 中每脚本在 weekly_timeouts 是否有 7 格条目（缺/不足 7 格视为不一致）；
    - weekly_timeouts 中是否存在 config 已不存在的孤儿条目。

    返回退出码 0=一致 / 1=存在不一致。
    """
    result = AppService().check_weekly()
    _emit_json("check_weekly", result, out_path)
    assert "status" in result, "[cli] check_weekly 结果缺少 status"
    return 0 if result["status"] == "ok" else 1


def _parse_overrides(raw: str | None) -> dict[str, str]:
    """解析 '脚本名=值,脚本名=值' 格式的命令行覆盖参数。

    Args:
        raw: 原始字符串（None 或空 → 空 dict）。

    Returns:
        脚本名 → 值的映射。

    Raises:
        ValueError: 条目缺少 '=' 或值为空。
    """
    if not raw:
        return {}
    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"覆盖参数格式错误（缺少 '='）: {entry}")
        name, _, value = entry.partition("=")
        name, value = name.strip(), value.strip()
        if not name or not value:
            raise ValueError(f"覆盖参数格式错误（脚本名或值为空）: {entry}")
        result[name] = value
    return result


def _resolve_enable_keys(
    raw: str | None, known: set[str]
) -> tuple[set[str], str | None]:
    """把 --enable 解析为脚本标识集合（--generate-chain / --schedule-run 共用）。

    - None 或 "all"（大小写不敏感，兼容默认） → 全部已知脚本 set(known)；
    - 否则按逗号拆分成白名单；含不在 known 的标识时返回 ("", 错误信息)。

    这样「全部」由显式 all / 缺省 表达，绝不用 None 隐式代表全部；
    内层 run_chain_once / parse_logs 的 None=跳过 语义不被本层覆盖。
    """
    value = (raw or "all").strip().lower()
    if value == "all":
        return set(known), None
    enabled = {n.strip() for n in (raw or "").split(",") if n.strip()}
    unknown = enabled - known
    if unknown:
        return set(), f"未知的脚本标识: {sorted(unknown)}"
    return enabled, None


def _run_generate_chain(args) -> int:
    """CLI: 生成脚本链配置。返回退出码 0=成功 / 1=失败。"""
    app_service = AppService()
    all_config_data = app_service.load_config()

    known = {get_script_name(s) for s in all_config_data["script_list"]}
    enabled_keys, err = _resolve_enable_keys(args.enable, known)
    if err:
        _emit_cli("generate_chain", err)
        return 1

    if args.exclude:
        excluded = {n.strip() for n in args.exclude.split(",") if n.strip()}
        unknown = excluded - known
        if unknown:
            _emit_cli("generate_chain", f"未知的脚本标识: {sorted(unknown)}")
            return 1
        enabled_keys -= excluded

    # 命令行覆盖：--weekly-start 持久化到 weekly_start.yml
    # （周几跑是长期配置，同 GUI 改周几起语义）。
    # 校验失败（未知脚本/未支持周常/非整数/越界）在写盘前拦截并返回 1。
    try:
        weekly_overrides = _parse_overrides(args.weekly_start)
    except ValueError as exc:
        _emit_cli("generate_chain", str(exc))
        return 1
    for script_name in weekly_overrides:
        if script_name not in known:
            _emit_cli(
                "generate_chain", f"--weekly-start 中未知的脚本标识: {script_name}"
            )
            return 1
        if not supports_weekly(script_name):
            _emit_cli(
                "generate_chain",
                f"--weekly-start 中 {script_name} 未支持周常（不设周几起）",
            )
            return 1
        try:
            start_day = int(weekly_overrides[script_name])
        except ValueError:
            _emit_cli(
                "generate_chain",
                f"--weekly-start 中 {script_name} 的值不是整数: "
                f"{weekly_overrides[script_name]}",
            )
            return 1
        if not 1 <= start_day <= 7:
            _emit_cli(
                "generate_chain",
                f"--weekly-start 中 {script_name} 的值越界: {start_day}（应为 1~7）",
            )
            return 1
        # 仅做持久化（周几跑是长期配置），不实时写子脚本 config
        app_service.set_weekly_start(script_name, start_day)

    out = args.out
    if out:
        out = os.path.abspath(out)
    out = app_service.generate_chain(
        all_config_data, enabled_keys, args.name, out_path=out
    )
    _emit_cli("generate_chain", f"已生成脚本链配置: {out}")
    return 0


def _run_run_chain(args) -> int:
    """CLI: 运行脚本链配置。返回 Runner 退出码。"""
    chain_path = os.path.abspath(args.run_chain)
    if not os.path.exists(chain_path):
        _emit_cli("run_chain", f"脚本链配置不存在: {chain_path}")
        return 1

    extra_args = []
    app_service = AppService()
    command, cwd, _env = app_service.build_chain_command(chain_path, extra_args)
    _emit_cli("run_chain", f"运行: {cwd} {' '.join(command)}")
    code = app_service.run_chain_command(
        chain_path, block=not args.no_block, extra_args=extra_args
    )
    if args.no_block:
        _emit_cli("run_chain", f"脚本链已后台启动，启动状态码: {code}")
    else:
        _emit_cli("run_chain", f"脚本链退出码: {code}")
    # 关机由主仓库编排：等链运行结束（block 模式已等待）后再触发确认关机，
    # 不再透传 runner 的 --shutdown（会抢在重跑前关机）。非阻塞模式不触发关机。
    if args.shutdown is not None and not args.no_block:
        shutdown_sys(args.shutdown)
    return code


def _run_scheduled(args) -> int:
    """CLI 出口：调度运行入口，真实实现见 ``chain_service.schedule_run``。

    本函数在独立控制台进程中运行（由 ``utils_runner.spawn_schedule_run`` 以
    ``CREATE_NEW_CONSOLE`` 起），故等待阻塞无害；关闭该控制台即取消。链在点火时
    才生成（按当天星期）。
    """
    app_service = AppService()
    all_config_data = app_service.load_config()
    known = {get_script_name(s) for s in all_config_data["script_list"]}
    enabled_keys, err = _resolve_enable_keys(args.enable, known)
    if err:
        _emit_cli("schedule_run", err)
        return 1
    app_service.schedule_run(
        enabled_keys,
        args.schedule_run,
        chain_name=args.name or "today",
        mute=args.mute,
        shutdown_delay=args.shutdown,
        close_running=args.close_running,
    )
    return 0


def run_cli(args) -> int | None:
    """分发 CLI 出口：返回退出码（None 表示应进入 GUI 主路径）。

    Args:
        args: argparse 解析结果。

    Returns:
        退出码；None 表示无 CLI 出口命中，调用方应继续 GUI 主路径。
    """
    if args.help:
        _emit_cli("help", build_parser().format_help().strip())
        return 0
    if args.version:
        _emit_cli("version", get_version())
        return 0
    if args.selftest:
        return _run_selftest(args.out)
    if args.check_config:
        return _run_check_config(args.out)
    if args.list_scripts:
        return _run_list_scripts(args.out)
    if args.get_script is not None:
        return _run_get_script(args.get_script, args.out)
    if args.dump_config:
        return _run_dump_config(args.out)
    if args.check_weekly:
        return _run_check_weekly(args.out)
    if args.generate_chain:
        return _run_generate_chain(args)
    if args.run_chain is not None:
        return _run_run_chain(args)
    if args.schedule_run is not None:
        return _run_scheduled(args)
    return None
