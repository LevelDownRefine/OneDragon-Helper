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

# 测试会在包内额外写盘的位置：链 yml 与两级日志目录。setUp 快照、teardown
# 精确回滚（旧文件截回原大小、新文件删除、新建目录清空后移除），保证
# build-exe 上传的 dist 产物不含测试痕迹。
_CHAIN_DIR = _CONFIG_DIR / "script_chain" if _CONFIG_DIR else None
_CHAIN_FILES = ("today.yml", "rerun.yml")
_LOG_DIRS = ("logs", ".log")

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
    # mute 观测（test_mute_real）：测试前的系统静音状态，tearDown 兜底还原用户原态
    # （原静音则测完仍静音，不因本轮 --unmute 永久改其音量）。读不到为 None。
    initial_mute: bool | None = None

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

        # 包内 config 生成物与链文件：备份 → 写入本测试的假配置。build-exe 跑完
        # 本测试后会上传 dist 产物，测试写盘必须全部还原，避免测试痕迹进 artifact。
        cls._config_backup = cls._backup_files(_CONFIG_DIR, _GENERATED)
        cls._chain_backup = cls._backup_files(_CHAIN_DIR, _CHAIN_FILES)
        cls._snapshot_logs()

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
                "daily_run": {"enabled": False, "target_time": "04:10"},
                "mute": {"enabled": False},
                "unmute": {"enabled": False},
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
        # 记录测试前静音状态：本轮 --mute/--unmute 会改系统静音，tearDown 按此还原
        # 用户原态（原静音则测完仍静音，不无端强制恢复非静音）。
        cls.initial_mute = cls._read_mute_now()
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
                    "--mute",
                    "--unmute",
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
        # 兜底：无论断言成败都还原测试前的静音状态（--unmute 正常则已是非静音，
        # 幂等；用户本为静音则改回静音）。读不到原始态则跳过（非 Windows/无端点，
        # 此时 mute 本身也不生效）。
        if cls.initial_mute is not None:
            with contextlib.suppress(Exception):
                from src.utils.utils_mute import set_system_mute

                set_system_mute(cls.initial_mute)
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower() == GAME_NAME.lower():
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    p.kill()
        # 恢复包内 config 生成物与链文件（原缺失则删除，还 dist 一个干净状态）
        cls._restore_files(_CONFIG_DIR, cls._config_backup)
        cls._restore_files(_CHAIN_DIR, cls._chain_backup)
        cls._restore_logs()
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    @classmethod
    def _read_mute_now(cls) -> bool | None:
        """读取当前系统静音状态；无默认音频端点等不可读时返回 None。"""
        try:
            from ctypes import POINTER, cast

            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            device = AudioUtilities.GetSpeakers()
            volume = cast(
                device.Activate(IAudioEndpointVolume._iid_, 0, None),
                POINTER(IAudioEndpointVolume),
            )
            return bool(volume.GetMute())
        except Exception:
            return None

    # ── 工具 ─────────────────────────────────────────────────────────
    @classmethod
    def _backup_files(
        cls, dir_: Path, names: tuple[str, ...]
    ) -> dict[str, bytes | None]:
        """备份一组文件原内容（原缺失记 None，供 _restore_files 回滚）。"""
        return {
            name: (dir_ / name).read_bytes() if (dir_ / name).exists() else None
            for name in names
        }

    @classmethod
    def _restore_files(cls, dir_: Path, backup: dict[str, bytes | None]) -> None:
        """按备份回滚：原缺失删之，原存在写回。"""
        for name, content in backup.items():
            path = dir_ / name
            if content is None:
                with contextlib.suppress(OSError):
                    path.unlink()
            else:
                path.write_bytes(content)

    @classmethod
    def _snapshot_logs(cls) -> None:
        """快照日志文件原大小，并记录本轮缺失的目录（teardown 精确回滚）。"""
        cls._log_snapshot: dict[str, int] = {}  # 文件路径 -> 原大小
        cls._created_dirs: list[Path] = []  # 本轮测试新建的目录（清空后移除）
        for path in (_CHAIN_DIR, *(Path(PACKAGE_DIR) / d for d in _LOG_DIRS)):
            if not path.is_dir():
                cls._created_dirs.append(path)
                continue
            if path.name in _LOG_DIRS:
                for f in path.iterdir():
                    if f.is_file():
                        cls._log_snapshot[str(f)] = f.stat().st_size

    @classmethod
    def _restore_logs(cls) -> None:
        """日志回滚：旧文件截回快照大小（抹掉本轮追加），快照外的新文件
        （含午夜轮转备份、framework 日志）删除；本轮新建目录已清空则移除。"""
        for d in _LOG_DIRS:
            base = Path(PACKAGE_DIR) / d
            if not base.is_dir():
                continue
            for f in base.iterdir():
                if not f.is_file():
                    continue
                if str(f) in cls._log_snapshot:
                    with open(f, "r+b") as fh:
                        fh.truncate(cls._log_snapshot[str(f)])
                else:
                    with contextlib.suppress(OSError):
                        f.unlink()
        for path in cls._created_dirs:
            with contextlib.suppress(OSError):
                path.rmdir()

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
        """安全边界：全程无关机、无邮件（静音/恢复本轮刻意开启，见 test_mute_real）。"""
        self.assertNotIn("关机", self.fw_tail)
        self.assertNotIn("发送", self.fw_tail)

    def test_mute_real(self):
        """--mute/--unmute 真实生效：exe 收到参数后系统静音、运行结束恢复，日志留痕。

        mute_on/mute_off 调 pycaw 成功才打 ``[mute] 已静音`` / ``[mute] 已恢复声音``，
        断言这两条即证明静音真实执行。读不到静音状态则跳过（无默认音频端点，
        环境限制而非产品缺陷）。tearDownClass 依 initial_mute 还原测试前状态：
        用户本为静音则测完仍静音，不被本轮 --unmute 永久改其音量。
        """
        if self.initial_mute is None:
            self.skipTest("本机读不到系统静音状态（无默认音频端点）")
        self.assertIn("[mute] 已静音", self.fw_tail)
        self.assertIn("[mute] 已恢复声音", self.fw_tail)


if __name__ == "__main__":
    unittest.main()
