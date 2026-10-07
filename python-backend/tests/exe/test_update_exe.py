"""真实 Windows 更新器：安装、占用、回滚及启动闸门。"""

import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import psutil

from src.update.installer import write_json
from src.update.package import (
    APP_EXE,
    CLI_EXE,
    RUNNER_EXE,
    UPDATER_EXE,
    file_digest,
    load_manifest,
    manifest_frontend,
    write_manifest,
)
from src.update.runtime import FileLease, child_environment
from tests.exe import package_dir
from tests.exe.pipe_output import PipeOutput

CAN_RUN = (
    sys.platform == "win32"
    and bool(ctypes.windll.shell32.IsUserAnAdmin())
    and (package_dir() / UPDATER_EXE).is_file()
)

# 占用测试的目标：新版必须真的改过它，否则更新会跳过替换，锁形同虚设。
LOCKED_FILE = "config/config.example.yml"


@unittest.skipUnless(CAN_RUN, "需要 Windows 管理员环境与完整打包产物")
class TestUpdateExe(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = self.directory / "旧版 安装目录"
        self.new = self.directory / "新版 程序包"
        source = package_dir()
        manifest = load_manifest(source)
        names = list(manifest["files"])
        frontend = manifest_frontend(manifest)
        for root, version, extra in (
            (self.root, "1.0.0", "assets/obsolete.txt"),
            (self.new, "2.0.0", "assets/new.txt"),
        ):
            for name in names:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / name, destination)
            if root == self.new:
                # 两棵树同源，只有元数据不同；给新版造一处真实差异，占用才撞得上替换
                (root / LOCKED_FILE).write_text("program 2.0.0\n", encoding="utf-8")
            metadata = {"version": version}
            if frontend == "rust":
                metadata["frontend"] = frontend
            write_json(root / "version.json", metadata)
            (root / extra).write_text(version, encoding="utf-8")
            write_manifest(root, names + [extra], version, frontend=frontend)
        self.worker = self.directory / UPDATER_EXE
        shutil.copy2(source / UPDATER_EXE, self.worker)
        self.result = self.directory / "result.json"
        self.users = {}
        for name in (
            "config/config.yml",
            "config/schedule.yml",
            "config/weekly.yml",
            "config/wallpaper.json",
            "config/wallpaper_cache/custom.jpg",
            "config/backups/test.zip",
            "config/config.yml.bak",
            "assets/banner.jpg",
            "assets/custom.jpg",
            "logs/test.log",
            ".log/test.log",
        ):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"user: preserved\n")
            self.users[name] = target.read_bytes()
        self.before = load_manifest(self.root, verify=True)

    def run_updater(self, *args):
        process = subprocess.run(
            [
                str(self.worker),
                "--root",
                str(self.root),
                "--result",
                str(self.result),
                *args,
            ],
            cwd=self.directory,
            env=child_environment(),
            timeout=180,
            capture_output=True,
        )
        self.assertTrue(self.result.is_file(), process.stderr)
        result = json.loads(self.result.read_text(encoding="utf-8"))
        self.assertEqual(
            json.loads((self.root / ".update/result.json").read_text(encoding="utf-8")),
            result,
        )
        return process.returncode, result

    def assert_users_unchanged(self):
        self.assertEqual(
            {name: (self.root / name).read_bytes() for name in self.users}, self.users
        )

    def assert_old_restored(self):
        self.assertEqual(load_manifest(self.root, verify=True), self.before)
        self.assertFalse((self.root / "assets/new.txt").exists())
        self.assert_users_unchanged()

    def test_upgrade_real_binaries_and_launch_updated_exe(self):
        code, result = self.run_updater("--package", str(self.new))
        self.assertEqual((code, result["status"]), (0, "installed"), result)
        self.assertEqual(load_manifest(self.root, verify=True)["version"], "2.0.0")
        self.assertFalse((self.root / "assets/obsolete.txt").exists())
        self.assert_users_unchanged()
        launch = subprocess.run(
            [str(self.root / APP_EXE), "--version"],
            cwd=self.directory,
            env=child_environment(),
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(launch.returncode, 0, launch.stderr)
        version = Path(tempfile.gettempdir()) / "odh_gui_version.txt"
        self.assertIn("2.0.0", version.read_text(encoding="utf-8"))
        self.assert_users_unchanged()

    def test_locked_file_rolls_back_after_partial_replacement(self):
        # Windows 普通读句柄禁止替换；触发前已经替换 EXE、删旧资源并写新资源。
        with (self.root / LOCKED_FILE).open("rb"):
            code, result = self.run_updater("--package", str(self.new))
        self.assertEqual((code, result["status"]), (1, "failed"), result)
        self.assert_old_restored()
        journal = json.loads((self.root / ".update/transaction.json").read_text())
        self.assertEqual(journal["phase"], "rolled_back")

    def test_rust_update_waits_for_real_frontend_and_cli_to_exit(self):
        if manifest_frontend(self.before) != "rust":
            self.skipTest("双进程交接只适用于 Rust 发布包，由 build-rust job 真跑")
        content = {"script_list": [], "handoff_probe": "x" * 1024**2}
        config = self.root / "config/config.yml"
        config.write_text(json.dumps(content), encoding="utf-8")
        self.users["config/config.yml"] = config.read_bytes()
        ready = self.directory / "ready.json"
        # 原 CLI 的 --out 可写命名管道；暂不读取让双方自然存活，不加产品测试入口。
        with PipeOutput() as pipe:
            frontend = subprocess.Popen(
                [str(self.root / APP_EXE), "--dump-config", "--out", pipe.name],
                cwd=self.directory,
                env=child_environment(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            updater = None
            children = []
            try:
                pipe.connect()
                gui = psutil.Process(frontend.pid)
                children = gui.children()
                cli = next(
                    child
                    for child in children
                    if Path(child.exe()).resolve() == (self.root / CLI_EXE).resolve()
                )
                self.assertEqual(cli.ppid(), frontend.pid)
                updater = subprocess.Popen(
                    [
                        str(self.worker),
                        "--root",
                        str(self.root),
                        "--package",
                        str(self.new),
                        "--parent-pid",
                        str(cli.pid),
                        "--parent-created",
                        str(cli.create_time()),
                        "--frontend-pid",
                        str(gui.pid),
                        "--frontend-created",
                        str(gui.create_time()),
                        "--ready",
                        str(ready),
                        "--result",
                        str(self.result),
                    ],
                    cwd=self.directory,
                    env=child_environment(),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                deadline = time.monotonic() + 60
                while (
                    not ready.exists()
                    and updater.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.05)
                self.assertTrue(ready.exists(), "更新器未就绪")
                self.assertEqual(json.loads(ready.read_text())["status"], "ready")
                self.assertIsNone(updater.poll())
                self.assertIsNone(frontend.poll())
                self.assertEqual(load_manifest(self.root, verify=True), self.before)
                self.assertEqual(json.loads(pipe.read()), content)
                self.assertEqual(frontend.wait(timeout=30), 0)
                self.assertEqual(updater.wait(timeout=180), 0)
                self.assertEqual(
                    json.loads(self.result.read_text())["status"], "installed"
                )
                self.assertEqual(
                    load_manifest(self.root, verify=True)["version"], "2.0.0"
                )
                self.assert_users_unchanged()
            finally:
                # 仅清理本测试持有的进程，正常成功路径双方自行退出。
                if frontend.poll() is None:
                    children = psutil.Process(frontend.pid).children(recursive=True)
                    for child in children:
                        child.kill()
                    frontend.kill()
                    frontend.wait(timeout=15)
                    psutil.wait_procs(children, timeout=15)
                if updater is not None and updater.poll() is None:
                    updater.kill()
                    updater.wait(timeout=15)

    def test_running_runner_refuses_update_without_killing_task(self):
        marker = self.directory / "runner-ready"
        script = self.directory / "sleep.py"
        script.write_text(
            "import time\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).touch()\ntime.sleep(120)\n",
            encoding="utf-8",
        )
        runner = subprocess.Popen(
            [str(self.root / RUNNER_EXE), "--script", str(script)],
            cwd=self.directory,
            env=child_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 60
            while (
                not marker.exists()
                and time.monotonic() < deadline
                and runner.poll() is None
            ):
                time.sleep(0.1)
            self.assertTrue(marker.exists(), "测试 Runner 未就绪")
            code, result = self.run_updater("--package", str(self.new))
            self.assertEqual((code, result["status"]), (1, "failed"), result)
            self.assertIn("运行中的进程", result["error"])
            self.assertIsNone(runner.poll())
            self.assert_old_restored()
        finally:
            if runner.poll() is None:
                children = psutil.Process(runner.pid).children(recursive=True)
                for child in children:
                    child.kill()
                runner.kill()
                runner.wait(timeout=15)
                psutil.wait_procs(children, timeout=15)

    def test_update_gate_blocks_cli_before_user_config_initialization(self):
        for name in ("config.yml", "schedule.yml", "weekly.yml"):
            (self.root / "config" / name).unlink()
        with FileLease(self.root / ".update/intent.lock"):
            process = subprocess.run(
                [str(self.root / APP_EXE), "--version"],
                cwd=self.directory,
                env=child_environment(),
                capture_output=True,
                timeout=120,
            )
        self.assertEqual(process.returncode, 2, process.stderr)
        self.assertFalse((self.root / "config/config.yml").exists())

    def test_recovery_cli_restores_interrupted_files_idempotently(self):
        # 持久化现场等同于只替换了 version.json 后进程中断。
        identity = "a" * 32
        previous = self.root / ".update" / identity / "previous/version.json"
        previous.parent.mkdir(parents=True)
        shutil.copy2(self.root / "version.json", previous)
        write_json(
            self.root / ".update/transaction.json",
            {
                "phase": "installing",
                "transaction": identity,
                "originals": {"version.json": file_digest(previous)},
            },
        )
        shutil.copy2(self.new / "version.json", self.root / "version.json")
        for _attempt in range(2):
            code, result = self.run_updater("--recover")
            self.assertEqual((code, result["status"]), (0, "recovered"), result)
            self.assert_old_restored()
