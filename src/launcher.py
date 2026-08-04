"""启动器入口：GUI 启动。

GUI 各部分在 src/gui 包中：state（状态持久化）、runner（后台运行）、
widgets（自定义控件）、dialogs（弹窗）、main_window（主窗口）。
"""

import argparse
import json
import os
import sys
import tempfile

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.config.subscript import generate_config_from_example
from src.gui.main_window import MainWindow
from src.utils import get_config_yml_path_under_root, get_path_under_root
from src.utils_logger import setup_logging


def need_config_workflow() -> bool:
    """判断是否需要先执行 config_workflow（首次运行时 config.yml 不存在）"""
    return not os.path.exists(get_config_yml_path_under_root())


def config_workflow():
    # 从模板生成 config.yml（如果不存在），相对 script_path 解析为绝对路径
    config_path = get_config_yml_path_under_root()
    if not os.path.exists(config_path):
        generate_config_from_example()


def _set_app_window_icon(app):
    """把 assets/Chtholly.ico 设为应用窗口图标（标题栏/任务栏）。

    在 dev 与冻结（PyInstaller）两种模式下都能定位：dev 时 assets/ 在项目根，
    冻结时 build.bat 已把 assets/ 拷到 exe 同级目录，get_path_under_root 据此解析。
    图标缺失时静默跳过，不影响启动。
    """
    icon_path = get_path_under_root("assets", "Chtholly.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


def _build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器（对齐 Runner 的 argparse 风格）。

    GUI 主程序本质是窗口应用，但提供少量「不进入 GUI 事件循环」的 CLI 出口，
    便于打包产物的集成测试与排障。windowed exe 的 stdout/stderr 被丢弃，
    因此 --help/--version/--selftest 的结果会**同时写文件**（见 _emit_cli / _run_selftest）。
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
        help="无头自检：构造 MainWindow 并校验依赖/配置/脚本列表，结果写 JSON 后退出",
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
        help="--selftest 的结果 JSON 路径，或 --generate-chain 的链配置输出路径"
        "（默认 %%TEMP%%/odh_gui_selftest.json 或 config/script_chain/<name>.yml）",
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


def _get_version() -> str:
    """读取 pyproject.toml 的 [project] version。"""
    try:
        import tomllib

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "pyproject.toml"), "rb") as f:
            data = tomllib.load(f)
        return str(data.get("project", {}).get("version", "unknown"))
    except Exception:
        return "unknown"


def _run_selftest(out_path: str | None) -> None:
    """无头自检：构造 MainWindow 并校验关键依赖/配置/脚本列表。

    结果写入 JSON（默认 %TEMP%/odh_gui_selftest.json），退出码 0=OK / 1=失败。
    供打包产物集成测试 test_gui_exe.py 读取验证实质行为。
    """
    result: dict = {"status": "fail", "checks": {}}
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.argv = sys.argv[:1]
        # 复用已存在的 QApplication（如测试进程里其它模块已创建），避免重复实例化报错
        app = QApplication.instance() or QApplication(sys.argv)
        app.setStyle("Fusion")
        _set_app_window_icon(app)
        window = MainWindow()
        result["checks"]["mainwindow_created"] = True
        result["checks"]["script_count"] = len(window.script_items)
        result["checks"]["config_loaded"] = window.all_config_data is not None
        result["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 - 自检需捕获一切以产出失败结果
        result["status"] = "fail"
        result["error"] = str(exc)

    out = out_path or os.path.join(tempfile.gettempdir(), "odh_gui_selftest.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    sys.exit(0 if result["status"] == "ok" else 1)


def _run_generate_chain(args) -> int:
    """CLI: 生成脚本链配置。返回退出码 0=成功 / 1=失败。"""
    import os

    import yaml

    from src.gui.chain import generate_chain_config
    from src.gui.utils import load_ui_state
    from src.utils import require_config_yml_path

    config_path = require_config_yml_path()
    with open(config_path, encoding="utf-8") as f:
        all_config_data = yaml.safe_load(f)
    assert "script_list" in all_config_data, "[cli] config.yml 缺少 script_list 字段"

    known = {s["display_name"] for s in all_config_data["script_list"]}
    if args.enable:
        enabled_names = {n.strip() for n in args.enable.split(",") if n.strip()}
        unknown = enabled_names - known
        if unknown:
            _emit_cli("generate_chain", f"未知的脚本名: {sorted(unknown)}")
            return 1
    else:
        enabled_names = set(known)

    ui_state = load_ui_state()
    out = args.out
    if out:
        out = os.path.abspath(out)
    out = generate_chain_config(
        all_config_data, enabled_names, args.name, ui_state, out_path=out
    )
    _emit_cli("generate_chain", f"已生成脚本链配置: {out}")
    return 0


def _run_run_chain(args) -> int:
    """CLI: 运行脚本链配置。返回 Runner 退出码。"""
    import os

    from src.gui.runner import run_chain_command

    chain_path = os.path.abspath(args.run_chain)
    if not os.path.exists(chain_path):
        _emit_cli("run_chain", f"脚本链配置不存在: {chain_path}")
        return 1

    extra_args = []
    if args.shutdown is not None:
        extra_args += ["--shutdown", str(args.shutdown)]

    code = run_chain_command(chain_path, block=not args.no_block, extra_args=extra_args)
    _emit_cli("run_chain", f"脚本链退出码: {code}")
    return code


def main():
    # 首次运行时，拷贝配置模板到用户目录
    if need_config_workflow():
        config_workflow()

    parser = _build_parser()
    args = parser.parse_args()

    # 非 GUI 的 CLI 出口：解析后即退出，不进入事件循环。
    if args.help:
        _emit_cli("help", parser.format_help().strip())
        sys.exit(0)
    if args.version:
        _emit_cli("version", _get_version())
        sys.exit(0)
    if args.selftest:
        _run_selftest(args.out)
        sys.exit(0)
    if args.generate_chain:
        sys.exit(_run_generate_chain(args))
    if args.run_chain:
        sys.exit(_run_run_chain(args))

    # GUI 主路径
    setup_logging()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _set_app_window_icon(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
