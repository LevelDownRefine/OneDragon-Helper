"""在临时安装副本比较首张任务画面回读；不测冷启动或实际显示器呈现。"""

import argparse
import hashlib
import json
import logging
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python-backend"))

from src.update.package import load_manifest, manifest_frontend  # noqa: E402
from src.utils.utils_logger import today  # noqa: E402
from tools.release_package import validate_package  # noqa: E402
from tools.run_rust_gui import prepare_demo  # noqa: E402

logger = logging.getLogger(__name__)


def run_sample(family: str, root: Path, area: Path, iteration: int) -> dict[str, float]:
    """记录任务数据与首张任务画面 GPU 回读；按相同轮询间隔观察。"""
    output = area / f"{family}-{iteration}.log"
    command = [str(root / "OneDragon-Helper.exe"), "--after-update"]
    env = {
        **os.environ,
        "LOCALAPPDATA": str(area / "localappdata"),
        "TEMP": str(area),
        "TMP": str(area),
        "RUST_LOG": "info",
        "RUST_LOG_STYLE": "never",
        "__COMPAT_LAYER": "RunAsInvoker",
        "PATH": str(Path(os.environ["SYSTEMROOT"]) / "System32"),
        "ODH_FORCE_SOFTWARE_RENDERING": "0",
    }
    for key in (
        "VIRTUAL_ENV",
        "PYTHONHOME",
        "PYTHONPATH",
        "QT_QPA_PLATFORM",
        "QSG_RHI_BACKEND",
        "QSG_RHI_PREFER_SOFTWARE_RENDERER",
        "QT_QUICK_BACKEND",
        "QT_PLUGIN_PATH",
    ):
        env.pop(key, None)
    if family == "rust":
        env["ODH_GUI_STARTUP_LOG"] = str(output)
        env["ODH_GUI_MEASURE_STARTUP"] = "1"
        command += ["--capture", str(area / f"rust-{iteration}.png")]
        data_marker = "first task ready"
        frame_marker = "task frame captured"
    else:
        output = root / "logs" / f"onedragon_helper-{today()}.log"
        if output.exists():
            output.unlink()
        data_marker = "[qml] entering event loop"
        frame_marker = "ODH_TASK_FRAME_CAPTURED"
    started = time.perf_counter()
    process = subprocess.Popen(
        command, cwd=area, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    measured = {}
    try:
        while time.perf_counter() - started < 30:
            text = (
                output.read_text(encoding="utf-8", errors="replace")
                if output.exists()
                else ""
            )
            for key, marker in (
                ("task_data_ms", data_marker),
                ("task_frame_ms", frame_marker),
            ):
                if key not in measured and marker in text:
                    measured[key] = (time.perf_counter() - started) * 1000
            if "task_frame_ms" in measured:
                if "task_data_ms" not in measured:
                    raise RuntimeError(f"{family} 日志缺少任务就绪标记: {text}")
                process.wait(timeout=30)
                if process.returncode != 0:
                    raise RuntimeError(
                        f"{family} 截图退出码 {process.returncode}: {text}"
                    )
                return measured
            if process.poll() is not None:
                raise RuntimeError(
                    f"{family} 未到标记即退出 {process.returncode}: {text}"
                )
            time.sleep(0.005)
        raise TimeoutError(f"{family} 启动测量超时: {text}")
    finally:
        if process.poll() is None:
            children = psutil.Process(process.pid).children(recursive=True)
            process.terminate()
            process.wait(timeout=10)
            for child in children:
                if child.is_running():
                    child.kill()
            psutil.wait_procs(children, timeout=10)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-package", type=Path, required=True)
    parser.add_argument("--rust-package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=15)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("冻结 GUI 启动测量仅支持 Windows")
    if args.runs < 1:
        parser.error("--runs 必须为正数")
    project = Path(__file__).resolve().parents[1]
    for family, package in (("qt", args.qt_package), ("rust", args.rust_package)):
        validate_package(project, package)
        if manifest_frontend(load_manifest(package)) != family:
            parser.error(f"{family} 参数指向了其他类型的发布包")
    samples = {"qt": [], "rust": []}
    with tempfile.TemporaryDirectory(prefix="odh-startup-") as temporary:
        area = Path(temporary).resolve()
        demo = area / "demo"
        demo.mkdir()
        prepare_demo(demo)
        roots = {"qt": area / "qt", "rust": area / "rust"}
        for family, source in (("qt", args.qt_package), ("rust", args.rust_package)):
            target = roots[family]
            shutil.copytree(source, target)
            shutil.copytree(demo / "config", target / "config", dirs_exist_ok=True)
            shutil.copytree(demo / "scripts", target / "scripts")
            if family == "qt":
                qml = target / "src/gui/qml/main.qml"
                scene = qml.read_text(encoding="utf-8")
                assert "Window {" in scene
                scene = scene.replace(
                    "Window {",
                    """Window {
    property bool startupProbeRequested: false
    onFrameSwapped: {
        if (!startupProbeRequested) {
            startupProbeRequested = true
            if (!contentItem.grabToImage(function(result) {
                console.info("ODH_TASK_FRAME_CAPTURED")
                Qt.quit()
            })) Qt.exit(2)
        }
    }
""",
                    1,
                )
                qml.write_text(scene, encoding="utf-8")
        for iteration in range(args.runs + 1):
            order = ("qt", "rust") if iteration % 2 == 0 else ("rust", "qt")
            for family in order:
                elapsed = run_sample(family, roots[family], area, iteration)
                if iteration:
                    samples[family].append(elapsed)
                logger.info("%s round %s: %s", family, iteration, elapsed)
    result = {
        "platform": platform.platform(),
        "python": sys.version,
        "processor": platform.processor(),
        "executables_sha256": {
            family: hashlib.sha256(path.read_bytes()).hexdigest()
            for family, path in (
                ("qt", args.qt_package / "OneDragon-Helper.exe"),
                ("rust", args.rust_package / "OneDragon-Helper.exe"),
            )
        },
        "runs": args.runs,
        "excluded_warmup_runs_per_frontend": 1,
        "scenario": "Windows visible GUI, generated two-script fixture, after-update, warm OS cache; temporary RunAsInvoker copies; packaged Rust release+capture with log sink; default adapter selection",
        "markers": {
            "task_data_ms": "Qt entering event loop / Rust first task view received (different stage definitions)",
            "task_frame_ms": "first task frame available in GPU readback callback, before image encoding; Qt grabToImage / egui Screenshot",
        },
        "poll_interval_ms": 5,
        "samples_ms": samples,
        "summary_ms": {
            family: {
                key: {
                    "median": statistics.median(row[key] for row in values),
                    "min": min(row[key] for row in values),
                    "max": max(row[key] for row in values),
                }
                for key in ("task_data_ms", "task_frame_ms")
            }
            for family, values in samples.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("%s", result["summary_ms"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
