"""针对打包产物的 schedule 集成测试（真实 exe + 真实子进程 + 假脚本/假游戏）。

与 tests/sim_schedule_win.py（dev 模式、get_root_dir 补丁到沙箱）互补：
本文件在**打包产物所在目录就地运行**（frozen 后 get_root_dir = exe 目录），
真实走 ``OneDragon-Helper.exe --schedule-run`` → Runner exe → 假脚本/假游戏。
分两轮，共用一套夹具：

- 第一轮「掐断」（``--name cut``，ok-ww 带 game_path）：定时等待 → 清场（杀残留假游戏）→
  生成链 → Runner 启动游戏后固定等待就绪 60s。**跑到「游戏已被拉起」即掐断**，
  判据 = 「Runner 拉起了与残留进程 **pid 不同**的 FakeGame，且观察期内仍存活」——
  mock 证不了的「冻结版真的拉起了真实 OS 进程」由此覆盖，且不必付那 60s。
- 第二轮「整链」（``--name tail``，ok-ww 的 game_path 留空）：假游戏**由测试自己挂着**
  （不被清场），Runner 不介入启动，故无 60s 等待，可以完整跑到底——脚本真跑（写 ok-script.log
  → 日志解析）、重跑轮、``kill_game_after_done`` 按名关真实进程、post_run 的 unmute 都在这一轮。
- 第三轮「daily」（``--run-daily``，schedule.yml 的 daily_run.enabled=true）：每日计划独立
  run_options 的 rerun=false 生效——顶层 rerun 块恒为 true 作对照，ok-nte 走到第 3 次尝试
  仍失败且框架日志无重跑，即证明重跑决策读的是 daily_run.run_options 而非顶层块。

模拟对象（进程名唯一，绝不误杀真实进程）：
- ok-ww.cmd：external 脚本（.cmd 由 Runner 经 CreateProcess 直接拉起，实测可跑），
  写含成功标记的 ok-script.log 后退出；配了 game_path 才会触发游戏启动；
- ok-nte.py：python 脚本，首跑 exit(1) 不写成功标记、重跑才写，验证重跑轮；
- FakeGame.exe：System32 cmd.exe 副本（无参数启动即驻留控制台，当「挂着的游戏」）。

windowed exe 捕获不到 stdout，全部证据走文件产物：
- <exe目录>/logs/onedragon_helper.log（框架日志：等待/清场/重跑决策/静音）；
- <exe目录>/.log/script_chainer_runner.log（Runner 日志，frozen 专属：启动游戏/关闭游戏
  ——dev 模式不落盘，正是本测试必须打包跑的原因之一）。

关键约束与 test_gui_exe 同源：exe manifest 标 uac_admin，非 Windows / exe 不存在 /
非管理员整文件 skip；复用 test_gui_exe 的 exe 探测与管理员判断。
"""

import contextlib
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from src.utils.utils_sub_config import default_script_entry
from src.utils.utils_yaml import dump_yaml
from tests.exe import project_root
from tests.exe.test_close_running_exe import _kill_process_tree
from tests.exe.test_gui_exe import _SKIP_REASON, CAN_RUN_EXE, GUI_EXE

PROJECT_ROOT = str(project_root())
PACKAGE_DIR = os.path.dirname(GUI_EXE) if GUI_EXE else None

WORK_DIR = Path(tempfile.gettempdir()) / f"odh_exe_e2e_{os.getpid()}"
GAME_NAME = "FakeGame.exe"
GAME_EXE = WORK_DIR / GAME_NAME
WW_DIR = WORK_DIR / "fake_ww"
WW_CMD = WW_DIR / "ok-ww.cmd"
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
_CHAIN_FILES = ("cut.yml", "tail.yml", "rerun.yml", "plan.yml")
_LOG_DIRS = ("logs", ".log")

_TARGET_LEAD_SECONDS = (
    8  # 掐断轮目标时刻 = 当前 + 该秒数（覆盖 exe 冷启到 pre_run 的耗时）
)
_LAUNCH_DEADLINE = (
    120  # 掐断轮：等新假游戏出现（目标等待 + 清场 + 生成链 + Runner 冷启）
)
_GAME_OBSERVE_SECONDS = 3  # 出现后再观察其存活的秒数（仍存活即认为启动成功，随即掐断）
_TAIL_TIMEOUT = (
    180  # 整链轮 / daily 轮：两条链 + 日志解析 + post_run（无 60s 就绪等待）
)


def _fake_game_pids() -> set[int]:
    """当前存活的假游戏进程 pid 集合（按名匹配，名字唯一不误伤真实进程）。"""
    return {
        p.pid
        for p in psutil.process_iter(["name"])
        if (p.info["name"] or "").lower() == GAME_NAME.lower()
    }


def _write_okww_cmd() -> Path:
    """写假日常脚本 ok-ww.cmd（external），按 log_analysis.yml 规则伪造「今日已完成」。

    只用 ASCII（cmd 按 OEM 代码页读脚本，中文会乱码）；日志行照抄真实脚本的成功标记，
    使 ok-ww 不落入重跑名单（重跑轮只该圈中 ok-nte）。
    """
    log_file = WW_LOG_DIR / "ok-script.log"
    ran_file = WW_DIR / "ran.txt"
    lines = [
        "@echo off",
        f'mkdir "{WW_LOG_DIR}" 2>nul',
        f'(echo info_set current_stamina 145& echo current daily progress 180) > "{log_file}"',
        f'> "{ran_file}" echo 1',
        "ping -n 2 127.0.0.1 >nul",
    ]
    WW_CMD.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\r\n")
    return WW_CMD


@unittest.skipUnless(CAN_RUN_EXE, _SKIP_REASON)
class TestScheduleExeE2E(unittest.TestCase):
    """真实启动 OneDragon-Helper.exe --schedule-run 的集成测试。

    setUpClass 顺序跑两轮（掐断 / 整链），两条链的全部断言各共享对应那一轮的运行，
    避免每条用例都付一份链路成本；tearDownClass 恢复包内 config 生成物并清理进程。
    """

    # 掐断轮：框架/Runner 日志增量、耗时、观察到的游戏进程
    cut_fw = ""
    cut_runner = ""
    cut_elapsed = 0.0
    game_pid: int | None = None
    game_alive = False
    # 整链轮：框架/Runner 日志增量
    tail_fw = ""
    tail_runner = ""
    # mute 观测（test_mute_on_real / test_unmute_real）：测试前的系统静音状态，
    # tearDown 兜底还原用户原态。读不到为 None。
    initial_mute: bool | None = None

    @classmethod
    def setUpClass(cls):
        import faulthandler

        faulthandler.dump_traceback_later(
            _LAUNCH_DEADLINE + 2 * _TAIL_TIMEOUT + 60, exit=True
        )

        cls.work = WORK_DIR
        cls.work.mkdir(parents=True)
        WW_DIR.mkdir(parents=True)
        NTE_DIR.mkdir(parents=True)
        NTE_LOG_DIR.mkdir(parents=True)
        WW_LOG_DIR.mkdir(parents=True)

        # 假游戏：cmd.exe 副本（按名清理安全）。常驻方式见 _spawn_fake_game——
        # 不可无参数启动 cmd 副本（无控制台/stdin 环境下会立即读 EOF 退出）。
        shutil.copy(r"C:\Windows\System32\cmd.exe", GAME_EXE)

        # 假日常脚本：ok-ww.cmd（external，写含成功标记的日志）+ ok-nte.py
        # （python，按 .attempt 计数奇跑失败/偶跑成功；ok-script.log 只留最新一轮状态，
        # 跨轮证据走追加式 history.txt，供重跑轮与 daily 轮的断言互不覆盖）
        _write_okww_cmd()
        cls.nte_script = NTE_DIR / "ok-nte.py"
        cls.nte_script.write_text(
            "import pathlib, sys\n"
            f"root = pathlib.Path(r'{NTE_DIR}')\n"
            "attempt = root / '.attempt'\n"
            "n = int(attempt.read_text() or '0') + 1 if attempt.exists() else 1\n"
            "attempt.write_text(str(n))\n"
            f"log = pathlib.Path(r'{NTE_LOG_DIR}')\n"
            "log.mkdir(parents=True, exist_ok=True)\n"
            "with (root / 'history.txt').open('a', encoding='utf-8') as hist:\n"
            "    if n % 2:\n"
            "        (log / 'ok-script.log').write_text(\n"
            "            'info_set 当前体力 132\\nERROR connect timed out\\n',\n"
            "            encoding='utf-8')\n"
            "        hist.write(f'{n}:fail\\n')\n"
            "        sys.exit(1)\n"
            "    (log / 'ok-script.log').write_text(\n"
            "        'info_set 当前体力 132\\ninfo_set failed []\\n', encoding='utf-8')\n"
            "    hist.write(f'{n}:ok\\n')\n",
            encoding="utf-8",
        )

        # 包内 config 生成物与链文件：备份 → 写入本测试的假配置。build-exe 跑完
        # 本测试后会上传 dist 产物，测试写盘必须全部还原，避免测试痕迹进 artifact。
        cls._config_backup = cls._backup_files(_CONFIG_DIR, _GENERATED)
        cls._chain_backup = cls._backup_files(_CHAIN_DIR, _CHAIN_FILES)
        cls._snapshot_logs()
        cls._write_schedule_yml()

        # 日志偏移：只取后续增量（午夜轮转时文件变小，整份即增量）
        cls._offsets = cls._log_offsets()

        # 掐断轮的目标时刻：用带秒的「当前 + _TARGET_LEAD_SECONDS」，等固定几秒即可，
        # 不必像 HH:MM 那样只能等下一个整分钟（后者在 1~60s 间浮动，是 CI 时长抖动的主源）。
        # 跨午夜时同名时刻要等到明天，宁可即时运行（此时不再断言定时等待，见 test_timed_wait_real）。
        now = datetime.now()
        target_dt = now + timedelta(seconds=_TARGET_LEAD_SECONDS)
        if target_dt.date() == now.date():
            target = target_dt.strftime("%H:%M:%S")
            cls.expected_wait = _TARGET_LEAD_SECONDS
        else:
            target = "now"
            cls.expected_wait = 0.0

        # 记录测试前静音状态：两轮分别 --mute / --unmute，tearDown 按此还原用户原态
        # （原静音则测完仍静音，不无端强制恢复非静音）。
        cls.initial_mute = cls._read_mute_now()

        # 第一轮「掐断」：带 game_path，残留假游戏留给 pre_run 清场杀，跑到 Runner
        # 拉起新游戏即掐断（不等那固定 60s 的就绪等待）。
        cls._write_config(with_game=True)
        cls.leftover = cls._spawn_fake_game()
        time.sleep(1)  # 等 ping 拉起，确保进程已常驻
        cls.cut_elapsed, cls.cut_fw, cls.cut_runner = cls._run_cut(target)

        # 第二轮「整链」：game_path 留空 → Runner 不介入启动、没有 60s 等待，可跑到底；
        # 假游戏由测试自己挂着，链尾由 ok-ww 的 kill_game_after_done 按名关掉。
        cls._offsets2 = cls._log_offsets()
        cls._write_config(with_game=False)
        cls.tail_game = cls._spawn_fake_game()
        time.sleep(1)
        cls.tail_fw, cls.tail_runner = cls._run_tail()

        # 第三轮「daily」：--run-daily 走 daily_run.run_options（rerun=false），
        # 与顶层 rerun=true 形成对照；此时无残留假游戏（整链轮已按名关掉）。
        cls._offsets3 = cls._log_offsets()
        cls._write_schedule_yml(daily_enabled=True)
        cls.daily_fw = cls._run_daily()

    @classmethod
    def tearDownClass(cls):
        # 兜底：无论断言成败都还原测试前的静音状态（掐断轮静音后由整链轮的 post_run
        # 恢复，中途失败则靠这里；用户本为静音则改回静音）。读不到原始态则跳过
        # （非 Windows/无端点，此时 mute 本身也不生效）。
        if cls.initial_mute is not None:
            with contextlib.suppress(Exception):
                from src.utils.utils_mute import set_system_mute

                set_system_mute(cls.initial_mute)
        cls._kill_fake_games()
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
    def _write_schedule_yml(cls, *, daily_enabled: bool = False) -> None:
        """写 schedule.yml / weekly.yml（关机与邮件全程关闭）。

        顶层 rerun 恒为 true 作对照：``--run-daily`` 若误读顶层而非
        daily_run.run_options，daily 轮首跑失败的 ok-nte 会触发重跑（断言据此区分）。
        """
        daily_run: dict = {"enabled": daily_enabled, "target_time": "04:10"}
        if daily_enabled:
            daily_run["run_options"] = {
                "shutdown": {"after_run": False, "delay_seconds": 0},
                "mute": {"enabled": False},
                "unmute": {"enabled": False},
                "close_running": {"enabled": True},
                "rerun": {"enabled": False},
                "notify": {"enabled": False, "email": ""},
            }
        dump_yaml(
            _CONFIG_DIR / "schedule.yml",
            {
                "shutdown": {"after_run": False, "delay_seconds": 0},
                "daily_run": daily_run,
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

    @classmethod
    def _write_config(cls, *, with_game: bool) -> None:
        """写包内 config.yml；with_game 决定 ok-ww 是否带 game_path。

        两轮共用 ok-ww.cmd / ok-nte.py 与 game_process_name（整链轮留着给
        kill_game_after_done 按名收尾）；只有 game_path 会引出启动 + 60s 就绪等待。
        """
        ww = default_script_entry(
            display_name="ok-ww", script_type="external", script_path=str(WW_CMD)
        )
        ww.update(
            {
                "game_path": str(GAME_EXE) if with_game else "",
                "game_process_name": GAME_NAME,
                "kill_game_after_done": True,
                "check_done": "script_closed",
            }
        )
        nte = default_script_entry(
            display_name="ok-nte", script_type="python", script_path=str(cls.nte_script)
        )
        dump_yaml(_CONFIG_DIR / "config.yml", {"script_list": [ww, nte]})

    @classmethod
    def _spawn_fake_game(cls) -> subprocess.Popen:
        """挂一个常驻假游戏：掐断轮留给 pre_run 清场，整链轮留给链尾按名关掉。

        不可无参数启动 cmd 副本——无控制台/stdin 环境下 cmd 会立即读 EOF 退出，
        故用 ping -n 600 稳定常驻（与 test_close_running_exe._spawn_stub 同策略）。
        """
        return subprocess.Popen(
            [str(GAME_EXE), "/c", "ping -n 600 127.0.0.1 > nul"],
            cwd=str(WORK_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def _log_offsets(cls) -> dict[str, int]:
        """当前两级日志文件大小（作为「本轮增量」的起点）。"""
        return {
            p: (Path(p).stat().st_size if Path(p).exists() else 0)
            for p in cls._log_paths()
        }

    @classmethod
    def _run_cut(cls, target: str) -> tuple[float, str, str]:
        """跑掐断轮，返回 (耗时, 框架日志增量, Runner 日志增量)。"""
        t0 = time.time()
        exe = None
        try:
            # 不可用 subprocess.run 等退出：Runner 启动游戏后固定等就绪 60s，我们只到
            # 「游戏已拉起并被观察到」就掐断，故用 Popen 自行控时。
            exe = subprocess.Popen(
                [
                    GUI_EXE,
                    "--schedule-run",
                    target,
                    "--name",
                    "cut",
                    "--enable",
                    "ok-ww,ok-nte",
                    "--close-running",
                    "--mute",
                ],
                cwd=PACKAGE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cls.game_pid, cls.game_alive = cls._await_game_launch(exe)
        finally:
            elapsed = time.time() - t0
            fw, runner = cls._read_tails(cls._offsets)
            # 掐断 exe 整棵树（含其拉起的 Runner 与 shell 子进程），再清残留假游戏
            if exe is not None and exe.poll() is None:
                _kill_process_tree(exe.pid)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    exe.wait(timeout=10)
            cls._kill_fake_games()
        return elapsed, fw, runner

    @classmethod
    def _run_tail(cls) -> tuple[str, str]:
        """跑整链轮（脚本真跑 → 重跑轮 → post_run），返回两日志增量。"""
        subprocess.run(
            [
                GUI_EXE,
                "--schedule-run",
                "now",
                "--name",
                "tail",
                "--enable",
                "ok-ww,ok-nte",
                "--unmute",
            ],
            cwd=PACKAGE_DIR,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TAIL_TIMEOUT,
        )
        return cls._read_tails(cls._offsets2)

    @classmethod
    def _run_daily(cls) -> str:
        """跑 daily 轮（``--run-daily``，运行选项取 daily_run.run_options），返回框架日志增量。"""
        subprocess.run(
            [GUI_EXE, "--run-daily"],
            cwd=PACKAGE_DIR,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TAIL_TIMEOUT,
        )
        return cls._read_tails(cls._offsets3)[0]

    @classmethod
    def _await_game_launch(cls, exe: subprocess.Popen) -> tuple[int | None, bool]:
        """等 Runner 拉起「新的」假游戏进程，再观察数秒确认其仍存活。

        以「出现与残留进程 pid 不同的 FakeGame 进程」为启动判据：不依赖日志落盘
        （Runner 日志随时可写），且天然把 pre_run 清场与 Runner 的启动区分开——
        残留进程被清场杀掉后才可能出现新 pid，否则 Runner 会走「已在运行 跳过启动」。

        Args:
            exe: 已在运行的 GUI exe 进程句柄。

        Returns:
            (pid, alive)：新游戏进程 pid（超时或 exe 提前退出为 None），以及观察期
            结束时该进程是否仍存活（存活即认为启动成功）。
        """
        deadline = time.monotonic() + _LAUNCH_DEADLINE
        while time.monotonic() < deadline:
            others = _fake_game_pids() - {cls.leftover.pid}
            if others:
                pid = min(others)
                time.sleep(_GAME_OBSERVE_SECONDS)
                return pid, psutil.pid_exists(pid)
            if exe.poll() is not None:
                break
            time.sleep(0.2)
        return None, False

    @classmethod
    def _kill_fake_games(cls) -> None:
        """清掉一切残留假游戏（按名匹配，断言前置零，避免污染后续用例）。"""
        for pid in _fake_game_pids():
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                psutil.Process(pid).kill()

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
    def _read_tails(cls, offsets: dict[str, int]) -> tuple[str, str]:
        """读两级日志相对 offsets 的增量（午夜轮转时文件变小，整份即增量）。"""
        tails = {}
        for key, path in cls._log_paths().items():
            offset = offsets.get(key, 0)
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
            self.assertIn("定时运行已设置，将等待至", self.cut_fw)
            self.assertGreaterEqual(self.cut_elapsed, max(self.expected_wait - 2, 0))
        else:
            self.assertNotIn("定时运行已设置", self.cut_fw)

    def test_close_running_killed_leftover(self):
        """pre_run 清场：残留假游戏被终止，框架日志留痕。"""
        self.assertIsNotNone(self.leftover.poll())
        self.assertIn("已关闭残留进程", self.cut_fw)
        self.assertIn(GAME_NAME, self.cut_fw)

    def test_chains_generated(self):
        """三份链 yml 落盘：掐断轮的 cut 主链 + 整链轮的 tail 主链与 rerun 重跑链。"""
        for name in _CHAIN_FILES:
            self.assertTrue(
                (Path(PACKAGE_DIR) / "config" / "script_chain" / name).exists(), name
            )

    def test_game_launched_real(self):
        """Runner（冻结版）按 game_path 真实拉起真实 OS 进程，观察期内仍存活。

        只用「新 FakeGame pid 出现且存活」判启动成功，不等它跑完 60s 就绪等待。
        """
        self.assertIsNotNone(self.game_pid, "未观察到 Runner 拉起的 FakeGame.exe 进程")
        self.assertTrue(self.game_alive, "假游戏进程在观察期内已退出")
        # Runner 日志（frozen 落盘）：游戏被启动（dev 模式不落盘，故必须打包跑）
        self.assertIn("启动游戏", self.cut_runner)
        self.assertIn(GAME_NAME, self.cut_runner)

    def test_okww_ran_and_game_closed(self):
        """整链轮：ok-ww 真实执行（写成功日志），链尾按名关掉挂着的真实游戏进程。

        整链轮 game_path 留空（Runner 不启动游戏，故无 60s 等待），游戏由测试自己挂着，
        收尾走 ok-ww 的 kill_game_after_done —— 关的是真实 OS 进程。
        """
        self.assertTrue((WW_DIR / "ran.txt").exists(), "假 ok-ww 未执行")
        content = (WW_LOG_DIR / "ok-script.log").read_text(encoding="utf-8")
        self.assertIn("current daily progress 180", content)
        self.assertIn("尝试关闭游戏进程", self.tail_runner)
        self.assertIn(GAME_NAME, self.tail_runner)
        self.assertIsNotNone(self.tail_game.poll(), "链尾未关闭挂着的假游戏进程")

    def test_rerun_decision(self):
        """重跑轮只圈中首跑失败的 ok-nte（ok-ww 日志含成功标记，不进重跑名单）。"""
        self.assertIn("重跑 1 个脚本", self.tail_fw)
        self.assertIn("'ok-nte'", self.tail_fw)

    def test_oknte_failed_then_rerun_success(self):
        """ok-nte 首跑失败进重跑，重跑后成功（tail 轮 history：1 失败 → 2 成功）。"""
        history = (NTE_DIR / "history.txt").read_text(encoding="utf-8")
        self.assertIn("1:fail", history)
        self.assertIn("2:ok", history)

    def test_daily_run_uses_plan_run_options(self):
        """daily 轮重跑决策读 daily_run.run_options（rerun=false），顶层 rerun=true 不参与。

        history 恰为三轮：tail 轮 1 失败 + 重跑 2 成功、daily 轮 3 失败且无第 4 次——
        若误读顶层 rerun 块，daily 轮会多跑一轮（出现 4:ok）。用文件证据而非框架日志
        增量：同一产物日志被多轮运行共享，偏移对账不可靠。
        """
        self.assertEqual((NTE_DIR / ".attempt").read_text(), "3")
        self.assertEqual(
            (NTE_DIR / "history.txt").read_text(encoding="utf-8"),
            "1:fail\n2:ok\n3:fail\n",
        )

    def test_no_game_leftover(self):
        """收尾干净：无 FakeGame 进程存活。"""
        self.assertEqual(_fake_game_pids(), set())

    def test_safety_boundaries(self):
        """安全边界：三轮全程无关机、无邮件（静音/恢复刻意开启，见 mute 两条）。"""
        for tail in (self.cut_fw, self.tail_fw, self.daily_fw):
            self.assertNotIn("关机", tail)
            self.assertNotIn("发送", tail)

    def test_mute_on_real(self):
        """掐断轮 --mute 真实生效：exe 收到参数后系统静音，日志留痕。

        mute_on 调 pycaw 成功才打 ``[mute] 已静音``，断言它即证明静音真实执行。
        读不到静音状态则跳过（无默认音频端点，环境限制而非产品缺陷）。
        """
        if self.initial_mute is None:
            self.skipTest("本机读不到系统静音状态（无默认音频端点）")
        self.assertIn("[mute] 已静音", self.cut_fw)

    def test_unmute_real(self):
        """整链轮 --unmute 真实生效：post_run 收到参数后恢复声音，日志留痕。

        与 test_mute_on_real 隔一轮：掐断轮静音后不会自己恢复，由本轮的 post_run
        恢复；tearDownClass 再依 initial_mute 兜底还原（用户本为静音则改回静音）。
        """
        if self.initial_mute is None:
            self.skipTest("本机读不到系统静音状态（无默认音频端点）")
        self.assertIn("[mute] 已恢复声音", self.tail_fw)


if __name__ == "__main__":
    unittest.main()
