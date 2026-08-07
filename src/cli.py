"""CLI 出口：无头命令行子命令（不进入 GUI 事件循环）。

提供 --help / --version / --selftest / --generate-chain / --run-chain /
--check-config / --list-scripts / --get-script / --dump-config / --check-weekly 等出口，
供打包产物集成测试与排障使用。windowed exe 的 stdout/stderr 被丢弃，
因此 --help/--version 等结果会**同时写文件**（见 _emit_cli / _emit_json）。

GUI 主路径见 :mod:`src.launcher`，本模块不依赖 Qt。
"""

import argparse
import json
import os
import tempfile

from src.service.chain_service import ChainService
from src.service.script_service import ScriptService


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器（对齐 Runner 的 argparse 风格）。

    GUI 主程序本质是窗口应用，但提供「不进入 GUI 事件循环」的 CLI 出口，
    便于打包产物的集成测试与排障。windowed exe 的 stdout/stderr 被丢弃，
    因此结果会**同时写文件**（见 _emit_cli / _emit_json）。
    """
    parser = argparse.ArgumentParser(
        prog="OneDragon-Helper",
        description="OneDragon-Helper 脚本启动器（GUI）",
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
        help="无头自检：校验 ChainService 配置/脚本列表，结果写 JSON 后退出",
    )
    action.add_argument(
        "--check-config",
        action="store_true",
        help="校验 config.yml 全部脚本合法性，结果写 JSON 后退出（0=全部合法）",
    )
    action.add_argument(
        "--list-scripts",
        action="store_true",
        help="列出所有脚本 display_name，结果写文件后退出",
    )
    action.add_argument(
        "--get-script",
        metavar="NAME",
        help="查询单个脚本条目，结果写 JSON 后退出",
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
    parser.add_argument(
        "--enable",
        type=str,
        default=None,
        help="配合 --generate-chain，逗号分隔的脚本名白名单（默认：全部脚本）",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="88",
        help="配合 --generate-chain，脚本链文件名（不含扩展名，默认 88）",
    )
    parser.add_argument(
        "--shutdown",
        type=int,
        default=None,
        help="配合 --run-chain，运行结束后多少秒关机（透传给 Runner）",
    )
    parser.add_argument(
        "--no-block",
        action="store_true",
        help="配合 --run-chain，即起即返（后台非阻塞运行整条链）",
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
    """把 CLI 输出同时打印（dev 可见）与写文件（windowed exe 可观测）。"""
    print(text)
    path = os.path.join(tempfile.gettempdir(), f"odh_gui_{kind}.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def _emit_json(kind: str, data: dict, out_path: str | None = None) -> None:
    """把结构化结果同时打印（JSON 单行）与写文件（windowed exe 可观测/测试可断言）。

    Args:
        kind: 出口名，用于默认输出文件名 odh_gui_<kind>.json。
        data: 要输出的 JSON 可序列化 dict。
        out_path: 指定输出路径；None 时用默认 %TEMP%/odh_gui_<kind>.json。
    """
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)
    out = out_path or os.path.join(tempfile.gettempdir(), f"odh_gui_{kind}.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def get_version() -> str:
    """读取 pyproject.toml 的 [project] version。"""
    try:
        import tomllib

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), "rb") as f:
            data = tomllib.load(f)
        return str(data.get("project", {}).get("version", "unknown"))
    except Exception:
        return "unknown"


def _run_selftest(out_path: str | None) -> int:
    """无头自检：校验 ChainService 关键依赖/配置/脚本列表。

    结果写入 JSON（默认 %TEMP%/odh_gui_selftest.json），返回退出码 0=OK / 1=失败。
    供打包产物集成测试 test_gui_exe.py 读取验证实质行为。
    """
    result: dict = {"status": "fail", "checks": {}}
    try:
        service = ChainService()
        data = service.load_config()
        result["checks"]["service_ready"] = True
        result["checks"]["script_count"] = len(data.get("script_list", []))
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
        service = ChainService()
        all_config_data = service.load_config()
        invalid = service.collect_invalid_scripts(
            all_config_data.get("script_list", [])
        )
        result = {
            "status": "ok" if not invalid else "invalid",
            "script_count": len(all_config_data.get("script_list", [])),
            "invalid": [{"name": n, "message": m} for n, m in invalid],
        }
        _emit_json("check_config", result, out_path)
        return 0 if not invalid else 1
    except Exception as exc:  # noqa: BLE001 - CLI 需捕获一切以产出失败结果
        _emit_json("check_config", {"status": "fail", "error": str(exc)}, out_path)
        return 1


def _run_list_scripts(out_path: str | None) -> int:
    """CLI: 列出所有脚本 display_name。"""
    service = ChainService()
    all_config_data = service.load_config()
    names = [s["display_name"] for s in all_config_data.get("script_list", [])]
    result = {"script_count": len(names), "scripts": names}
    _emit_json("list_scripts", result, out_path)
    return 0


def _run_get_script(display_name: str, out_path: str | None) -> int:
    """CLI: 查询单个脚本条目（JSON）。

    返回退出码 0=找到 / 1=不存在。
    """
    script = ScriptService().get_script(display_name)
    if script is None:
        _emit_json(
            "get_script", {"status": "not_found", "name": display_name}, out_path
        )
        return 1
    _emit_json("get_script", {"status": "ok", "script": script}, out_path)
    return 0


def _run_dump_config(out_path: str | None) -> int:
    """CLI: 导出完整 config.yml（JSON）。"""
    service = ChainService()
    all_config_data = service.load_config()
    _emit_json("dump_config", all_config_data, out_path)
    return 0


def _run_check_weekly(out_path: str | None) -> int:
    """CLI: 校验 weekly_timeouts.yml 与 config 脚本一致性。

    检查项：
    - config 中每脚本在 weekly_timeouts 是否有 7 格条目（缺/不足 7 格视为不一致）；
    - weekly_timeouts 中是否存在 config 已不存在的孤儿条目。

    返回退出码 0=一致 / 1=存在不一致。
    """
    result = ScriptService().check_weekly()
    _emit_json("check_weekly", result, out_path)
    return 0 if result.get("status") == "ok" else 1


def _run_generate_chain(args) -> int:
    """CLI: 生成脚本链配置。返回退出码 0=成功 / 1=失败。"""
    service = ChainService()
    all_config_data = service.load_config()

    known = {s["display_name"] for s in all_config_data["script_list"]}
    if args.enable:
        enabled_names = {n.strip() for n in args.enable.split(",") if n.strip()}
        unknown = enabled_names - known
        if unknown:
            _emit_cli("generate_chain", f"未知的脚本名: {sorted(unknown)}")
            return 1
    else:
        enabled_names = set(known)

    ui_state = service.load_ui_state()
    out = args.out
    if out:
        out = os.path.abspath(out)
    out = service.generate_chain(
        all_config_data, enabled_names, args.name, ui_state, out_path=out
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
    if args.shutdown is not None:
        extra_args += ["--shutdown", str(args.shutdown)]

    service = ChainService()
    command, cwd, _env = service.build_chain_command(chain_path, extra_args)
    _emit_cli("run_chain", f"运行: {cwd} {' '.join(command)}")
    code = service.run_chain_command(
        chain_path, block=not args.no_block, extra_args=extra_args
    )
    _emit_cli("run_chain", f"脚本链退出码: {code}")
    return code


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
    if args.get_script:
        return _run_get_script(args.get_script, args.out)
    if args.dump_config:
        return _run_dump_config(args.out)
    if args.check_weekly:
        return _run_check_weekly(args.out)
    if args.generate_chain:
        return _run_generate_chain(args)
    if args.run_chain:
        return _run_run_chain(args)
    return None
