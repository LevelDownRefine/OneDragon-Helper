"""Measure main source startup with isolated config and a real first-frame signal."""

import argparse
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

logger = logging.getLogger(__name__)


def child(args):
    sys.path.insert(0, str(args.checkout))
    sys.argv = ["rust-feasibility-probe", "--after-update"]
    started = time.perf_counter()
    marks = {"process_to_probe_ms": (started - args.parent_started) * 1000}
    import src.utils

    src.utils.get_root_dir = lambda: str(args.fixture)
    from PySide6 import QtQml
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    qt_loaded = time.perf_counter()
    marks["qt_import_ms"] = (qt_loaded - started) * 1000
    original_engine = QtQml.QQmlApplicationEngine
    seen_frame = False

    class ProbeEngine(original_engine):
        def __init__(self):
            super().__init__()
            self.objectCreated.connect(self.capture_window)

        def capture_window(self, window, _url):
            assert window is not None, "QML root failed to load"
            marks["root_created_ms"] = (time.perf_counter() - started) * 1000
            window.frameSwapped.connect(self.frame)
            QTimer.singleShot(15000, QApplication.instance().quit)

        def frame(self):
            nonlocal seen_frame
            if seen_frame:
                return
            seen_frame = True
            now = time.perf_counter()
            marks["source_first_frame_ms"] = (now - started) * 1000
            marks["process_first_frame_ms"] = (now - args.parent_started) * 1000
            marks["main_to_frame_ms"] = (now - imported) * 1000
            QTimer.singleShot(0, QApplication.instance().quit)

    QtQml.QQmlApplicationEngine = ProbeEngine
    from src import launcher

    imported = time.perf_counter()
    marks["launcher_extra_import_ms"] = (imported - qt_loaded) * 1000
    # Never delete the user's global QML cache.
    launcher._clear_qml_cache = lambda: None
    try:
        launcher.main()
    except SystemExit as exc:
        assert exc.code == 0, exc.code
    assert seen_frame, "No frameSwapped signal"
    args.output.write_text(json.dumps(marks), encoding="utf-8")


def parent(args):
    import PySide6

    samples = []
    workspace = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="gui-probe-", dir=workspace) as directory:
        fixture = Path(directory)
        for relative in ("config", "assets", "src/gui/qml"):
            source = args.checkout / relative
            # Only the fresh main worktree's tracked defaults are copied.
            shutil.copytree(source, fixture / relative)
        shutil.copyfile(args.checkout / "pyproject.toml", fixture / "pyproject.toml")
        (fixture / "config/config.yml").write_text(
            "script_list: []\n", encoding="utf-8"
        )
        (fixture / "tmp").mkdir()
        env = {
            **os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONIOENCODING": "utf-8",
            "TEMP": str(fixture / "tmp"),
            "TMP": str(fixture / "tmp"),
        }
        for run in range(args.runs + 1):
            output = fixture / "result.json"
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--child",
                "--checkout",
                str(args.checkout),
                "--fixture",
                str(fixture),
                "--output",
                str(output),
                "--parent-started",
                str(time.perf_counter()),
            ]
            completed = subprocess.run(
                command,
                cwd=fixture,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            (workspace / "startup-child.log").write_text(
                completed.stdout + completed.stderr, encoding="utf-8"
            )
            assert completed.returncode == 0, completed.stderr
            record = json.loads(output.read_text(encoding="utf-8"))
            if run:
                samples.append(record)
            logger.info("Round %d/%d: %s", run, args.runs, record)
    assert samples
    summary = {}
    for key in samples[0]:
        values = []
        for sample in samples:
            assert key in sample
            values.append(sample[key])
        summary[key] = {
            "median_ms": statistics.median(values),
            "min_ms": min(values),
            "max_ms": max(values),
        }
    result = {
        "python": sys.version,
        "pyside6": PySide6.__version__,
        "platform": platform.platform(),
        "runs": args.runs,
        "warmup_runs_excluded": 1,
        "scenario": "source, empty script list, offscreen, --after-update, warm OS cache",
        "samples": samples,
        "summary": summary,
    }
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent-started", type=float, default=0)
    parser.add_argument("--runs", type=int, default=15)
    options = parser.parse_args()
    (child if options.child else parent)(options)
