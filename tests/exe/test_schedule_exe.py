"""针对打包产物的 schedule 全链路集成测试（真实 exe + 真实子进程 + 假脚本/假游戏）。

与 tests/sim_schedule_win.py（dev 模式、get_root_dir 补丁到沙箱）互补：
本文件在**打包产物所在目录就地运行**（frozen 后 get_root_dir = exe 目录），
真实走 ``OneDragon-Helper.exe --schedule-run`` → Runner exe → 假脚本/假游戏：

    定时等待 → 清场（杀残留假游戏）→ 写脚本 config → 生成链 →
    Runner exe 子进程（含游戏启动/收尾）→ 日志解析 → 重跑轮 → post_run

模拟对象（进程名唯一，绝不误杀真实进程）：
- ok-ww.exe：PyInstaller onefile 的 external 脚本，自写含成功标记的 ok-script.log
  后退出；runner 会按 game_path 先启动假游戏再跑它，kill_game_after_done 收尾；
- ok-nte.py：python 脚本（Runner exe 进程内 exec），首跑 exit(1) 不写成功标记，
  重跑才写，验证重跑轮；
- FakeGame.exe：System32 cmd.exe 副本（无参数启动即驻留控制台，当「挂着的游戏」）。

windowed exe 捕获不到 stdout，全部证据走文件产物：
- <exe目录>/logs/onedragon_helper.log（框架日志：等待/清场/重跑决策）；
- <exe目录>/.log/script_chainer_runner.log（Runner 日志，frozen 专属：
  启动游戏/关闭游戏——dev 模式不落盘，正是本测试必须打包跑的原因之一）。

关键约束与 test_gui_exe 同源：exe manifest 标 uac_admin，非 Windows / exe 不存在 /
非管理员整文件 skip；复用 test_gui_exe 的 exe 探测与管理员判断。
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from src.utils.utils_sub_config import default_script_entry
from src.utils.utils_yaml import dump_yaml
from tests.exe import project_root
from tests.exe.test_gui_exe import _SKIP_REASON, CAN_RUN_EXE, GUI_EXE

PROJECT_ROOT = str(project_root())
PACKAGE_DIR = os.path.dirname(GUI_EXE) if GUI_EXE else None

WORK_DIR = Path(tempfile.gettempdir()) / f"odh_exe_e2e_{os.getpid()}"
GAME_NAME = "FakeGame.exe"
GAME_EXE = WORK_DIR / GAME_NAME
WW_DIR = WORK_DIR / "fake_ww"
WW_LOG_DIR = WW_DIR / "data" / "apps" / "ok-ww" / "working" / "logs"
NTE_DIR = WORK_DIR / "fake_nte"
NTE_LOG_DIR = NTE_DIR / "data" / "apps" / "ok-nte" / "working" / "logs"

# 三个生成物在包内 config/ 下的路径（frozen 后 get_root_dir = exe 目录）
_CONFIG_DIR = Path(PACKAGE_DIR) / "config" if PACKAGE_DIR else None
_GENERATED = ("config.yml", "schedule.yml", "weekly.yml")

_RUN_TIMEOUT = 420  # 定时等待(≤60s) + 两条链 + 日志解析，含冷启动余量


def _pyinstaller_okww(main_py: Path) -> Path:
    """把假日常脚本打成 ok-ww.exe（onefile，无参数自足运行）。"""
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noupx",
        "--console",
        "--onefile",
        "--distpath",
        str(WW_DIR),
        "--workpath",
        str(WORK_DIR / "_pyi" / "ok-ww"),
        "--specpath",
        str(WORK_DIR / "_pyi"),
        "--name",
        "ok-ww",
        str(main_py),
    ]
    subprocess.run(args, check=True, capture_output=True, timeout=180)
    return WW_DIR / "ok-ww.exe"


@unittest.skipUnless(CAN_RUN_EXE, _SKIP_REASON)
class TestScheduleExeE2E(unittest.TestCase):
    """真实启动 OneDragon-Helper.exe --schedule-run 的全链路集成测试。

    setUpClass 一次性跑完整个 schedule（多条断言共享一次运行，避免每条用例
    都付 2-4 分钟的链路成本）；tearDownClass 恢复包内 config 生成物并清理进程。
    """

    fw_tail = ""
    runner_tail = ""
    elapsed = 0.0
    leftover_poll = None

    @classmethod
    def setUpClass(cls):
        import faulthandler

        faulthandler.dump_traceback_later(_RUN_TIMEOUT + 120, exit=True)

        cls.work = WORK_DIR
        cls.work.mkdir(parents=True)
        (WW_DIR).mkdir(parents=True)
        (NTE_DIR).mkdir(parents=True)
        (NTE_LOG_DIR).mkdir(parents=True)
        (WW_LOG_DIR).mkdir(parents=True)

        # 假游戏：cmd.exe 副本（按名清理安全）。常驻方式见下方 leftover 启动——
        # 不可无参数启动 cmd 副本（无控制台/stdin 环境下会立即退出，见下文注释）。
        shutil.copy(r"C:\Windows\System32\cmd.exe", GAME_EXE)

        # 假日常脚本 ok-ww.exe：按真实 log_analysis.yml 规则伪造「今日已完成」
        ww_main = WW_DIR / "ok-ww.py"
        ww_main.write_text(
            "import pathlib\n"
            "import time\n"
            f"log = pathlib.Path(r'{WW_LOG_DIR}')\n"
            "log.mkdir(parents=True, exist_ok=True)\n"
            "(log / 'ok-script.log').write_text(\n"
            "    'info_set current_stamina 145\\n'\n"
            "    'current daily progress 180\\n', encoding='utf-8')\n"
            f"pathlib.Path(r'{WW_DIR}').joinpath('ran.txt').write_text('1')\n"
            "time.sleep(2)\n",
            encoding="utf-8",
        )
        ww_exe = _pyinstaller_okww(ww_main)

        # 假日常脚本 ok-nte：首跑无成功标记 + ERROR 行（FAILED/重跑候选）；重跑才写标记
        (NTE_DIR / "ok-nte.py").write_text(
            "import pathlib, sys\n"
            f"root = pathlib.Path(r'{NTE_DIR}')\n"
            "attempt = root / '.attempt'\n"
            "first = not attempt.exists()\n"
            "attempt.write_text('x')\n"
            f"log = pathlib.Path(r'{NTE_LOG_DIR}')\n"
            "log.mkdir(parents=True, exist_ok=True)\n"
            "if first:\n"
            "    (log / 'ok-script.log').write_text(\n"
            "        'info_set 当前体力 132\\nERROR connect timed out\\n', encoding='utf-8')\n"
            "    sys.exit(1)\n"
            "(log / 'ok-script.log').write_text(\n"
            "    'info_set 当前体力 132\\ninfo_set failed []\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )

        # 包内 config 生成物：备份 → 写入本测试的假配置
        cls._config_backup = {}
        for name in _GENERATED:
            path = _CONFIG_DIR / name
            cls._config_backup[name] = path.read_bytes() if path.exists() else None

        ww = default_script_entry(
            display_name="ok-ww",
            script_type="external",
            script_path=str(ww_exe),
        )
        ww.update(
            {
                "game_path": str(GAME_EXE),
                "game_process_name": GAME_NAME,
                "kill_game_after_done": True,
                "check_done": "script_closed",
            }
        )
        nte = default_script_entry(
            display_name="ok-nte",
            script_type="python",
            script_path=str(NTE_DIR / "ok-nte.py"),
        )
        dump_yaml(_CONFIG_DIR / "config.yml", {"script_list": [ww, nte]})
        dump_yaml(
            _CONFIG_DIR / "schedule.yml",
            {
                "shutdown": {"after_run": False, "delay_seconds": 0},
                "timed_run": {"enabled": False, "target_time": ""},
                "mute": {"enabled": False},
                "rerun": {"enabled": True},
                "notify": {"enabled": False, "email": ""},
                "close_running": {"enabled": True},
            },
        )
        dump_yaml(
            _CONFIG_DIR / "weekly.yml",
            {
                "weekly_start": {},
                "weekly_timeouts": {"ok-ww": [3600] * 7, "ok-nte": [3600] * 7},
            },
        )

        # 日志偏移：只取本轮增量（午夜轮转时文件变小，整份即增量）
        cls._offsets = {
            p: (Path(p).stat().st_size if Path(p).exists() else 0)
            for p in cls._log_paths()
        }

        # 残留假游戏（「之前打开的」），留给 pre_run 清场杀。
        # 注意：不可无参数启动 cmd 副本——无控制台/stdin 环境下 cmd 会立即读 EOF
        # 退出，pre_run 清场时它已不在，日志就不会出现 FakeGame.exe（CI 即如此失败）。
        # 用 ping -n 600 让其稳定常驻，与 test_close_running_exe._spawn_stub 同策略。
        cls.leftover = subprocess.Popen(
            [str(GAME_EXE), "/c", "ping -n 600 127.0.0.1 > nul"],
            cwd=str(WORK_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1)  # 等 ping 拉起，确保进程已常驻

        now = datetime.now()
        if now.minute <= 57:
            target_dt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            target = target_dt.strftime("%H:%M")
            cls.expected_wait = (target_dt - now).total_seconds()
        else:
            target = "now"
            cls.expected_wait = 0.0

        t0 = time.time()
        try:
            subprocess.run(
                [
                    GUI_EXE,
                    "--schedule-run",
                    target,
                    "--name",
                    "today",
                    "--enable",
                    "ok-ww,ok-nte",
                    "--close-running",
                ],
                cwd=PACKAGE_DIR,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=_RUN_TIMEOUT,
            )
        finally:
            cls.elapsed = time.time() - t0
            cls.fw_tail, cls.runner_tail = cls._read_tails()
            # 安全网：清掉一切残留假游戏（断言前置零，避免污染后续用例）
            for p in psutil.process_iter(["name"]):
                if (p.info["name"] or "").lower() == GAME_NAME.lower():
                    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                        p.kill()

    @classmethod
    def tearDownClass(cls):
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower() == GAME_NAME.lower():
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    p.kill()
        # 恢复包内 config 生成物（原缺失则删除，还 dist 一个干净状态）
        for name, backup in cls._config_backup.items():
            path = _CONFIG_DIR / name
            if backup is None:
                with contextlib.suppress(OSError):
                    path.unlink()
            else:
                path.write_bytes(backup)
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    # ── 工具 ─────────────────────────────────────────────────────────
    @classmethod
    def _log_paths(cls) -> dict[str, str]:
        return {
            "fw": os.path.join(PACKAGE_DIR, "logs", "onedragon_helper.log"),
            "runner": os.path.join(PACKAGE_DIR, ".log", "script_chainer_runner.log"),
        }

    @classmethod
    def _read_tails(cls) -> tuple[str, str]:
        tails = {}
        for key, path in cls._log_paths().items():
            offset = cls._offsets.get(key, 0)
            p = Path(path)
            if not p.exists():
                tails[key] = ""
                continue
            with open(p, encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() <= offset:  # 午夜轮转截断重建：整份即本轮增量
                    f.seek(0)
                    tails[key] = f.read()
                else:
                    f.seek(offset)
                    tails[key] = f.read()
        return tails["fw"], tails["runner"]

    # ── 断言 ─────────────────────────────────────────────────────────
    def test_timed_wait_real(self):
        """定时模式真实等待到目标时刻；临近午夜则按计划即时运行。"""
        if self.expected_wait > 0:
            self.assertIn("定时运行已设置，将等待至", self.fw_tail)
            self.assertGreaterEqual(self.elapsed, max(self.expected_wait - 2, 0))
        else:
            self.assertNotIn("定时运行已设置", self.fw_tail)

    def test_close_running_killed_leftover(self):
        """pre_run 清场：残留假游戏被终止，框架日志留痕。"""
        self.assertIsNotNone(self.leftover.poll())
        self.assertIn("已关闭残留进程", self.fw_tail)
        self.assertIn("FakeGame.exe", self.fw_tail)

    def test_chains_generated(self):
        """两条链都生成：today 主链 + rerun 重跑链。"""
        for name in ("today.yml", "rerun.yml"):
            self.assertTrue(
                (Path(PACKAGE_DIR) / "config" / "script_chain" / name).exists(), name
            )

    def test_rerun_decision(self):
        """重跑轮只圈中首跑失败的 ok-nte。"""
        self.assertIn("重跑 1 个脚本", self.fw_tail)
        self.assertIn("'ok-nte'", self.fw_tail)

    def test_okww_ran_with_game(self):
        """ok-ww（external + game_path）被 Runner 真实执行且写了成功日志。"""
        self.assertTrue((WW_DIR / "ran.txt").exists())
        content = (WW_LOG_DIR / "ok-script.log").read_text(encoding="utf-8")
        self.assertIn("current daily progress 180", content)
        # Runner 日志（frozen 落盘）：游戏被启动又被按名关闭
        self.assertIn("启动游戏", self.runner_tail)
        self.assertIn("尝试关闭游戏进程", self.runner_tail)
        self.assertIn("FakeGame.exe", self.runner_tail)

    def test_oknte_failed_then_rerun_success(self):
        """ok-nte 首跑失败进重跑，重跑后日志含成功标记。"""
        content = (NTE_LOG_DIR / "ok-script.log").read_text(encoding="utf-8")
        self.assertIn("info_set failed []", content)
        self.assertTrue((NTE_DIR / ".attempt").exists())

    def test_no_game_leftover(self):
        """收尾干净：无 FakeGame 进程存活。"""
        alive = [
            p
            for p in psutil.process_iter(["name"])
            if (p.info["name"] or "").lower() == GAME_NAME.lower()
        ]
        self.assertEqual(alive, [])

    def test_safety_boundaries(self):
        """安全边界：全程无关机、无静音、无邮件。"""
        self.assertNotIn("关机", self.fw_tail)
        self.assertNotIn("静音", self.fw_tail)
        self.assertNotIn("发送", self.fw_tail)


if __name__ == "__main__":
    unittest.main()
