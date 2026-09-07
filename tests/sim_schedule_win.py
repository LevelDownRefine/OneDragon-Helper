"""Windows 下 schedule 全链路真实模拟（手动诊断脚本，不进 CI、不被 discover 收集）。

用法:
    PYTHONPATH=src python -m tests.sim_schedule_win

在 %TEMP%/odh_e2e_<pid> 搭建沙箱：进程内把 get_root_dir 补丁指向沙箱后，
用真实代码与真实子进程走完 ``schedule_run`` 全编排——

    定时等待 → 清场（杀残留假游戏）→ 写脚本 config → 生成链 →
    真实 runner 子进程（CREATE_NEW_CONSOLE，含游戏启动/收尾）→
    日志解析 → 重跑轮 → post_run（邮件关机静音均不触发）

模拟对象（全部 PyInstaller 实体进程，进程名唯一不误杀）：
- ok-ww.exe：external 脚本（runner 会按 game_path 先启动游戏再跑它），
  自写含成功标记的 ok-script.log 后退出，模拟「今日已完成」；
- ok-nte.py：python 脚本（runner 进程内 exec），首跑写不含成功标记的日志并
  exit(1)，重跑才写标记，模拟「首跑失败、重跑成功」；
- FakeGame.exe：onedir 自跑心跳 exe。一个实例由 pre_run 清场杀掉（昨晚残留），
  一个由 runner 按 game_path 启动、kill_game_after_done 收尾（本轮游戏）。

安全：全程不关机、不动静音、不发邮件；清场/收尾只匹配 FakeGame.exe 与
沙箱路径 cmdline，绝不触碰真实进程。
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

# ── ① 必须最先执行：get_root_dir 指向沙箱，之后 import 其余 src.* ──────────
REAL_ROOT = Path(__file__).resolve().parents[1]
SANDBOX = Path(tempfile.gettempdir()) / f"odh_e2e_{os.getpid()}"

import src.utils as _u  # noqa: E402

_u.get_root_dir = lambda: str(SANDBOX)
# runner 子进程以沙箱为 cwd 起进程：src.runner.launcher 从仓库根导入，而 launcher
# 内部的 import script_chainer 需要 <仓库根>/src/runner 在 sys.path。build_script_command
# 会把 get_root_dir()/src/runner（沙箱下不存在）拼到 PYTHONPATH 前列，无害，但真实
# runner 目录必须由这里提供。
os.environ["PYTHONPATH"] = (
    str(REAL_ROOT / "src" / "runner")
    + os.pathsep
    + str(REAL_ROOT)
    + os.pathsep
    + os.environ.get("PYTHONPATH", "")
)

import psutil  # noqa: E402

from src.service import chain_service  # noqa: E402
from src.utils.utils_logger import setup_logging  # noqa: E402
from src.utils.utils_sub_config import default_script_entry  # noqa: E402

GAME_NAME = "FakeGame.exe"
GAME_DIR = SANDBOX / "fake_game"
GAME_EXE = GAME_DIR / "FakeGame" / GAME_NAME  # onedir 产物：单进程，无双进程对
HEARTBEAT = GAME_DIR / "heartbeat.txt"
WW_DIR = SANDBOX / "fake_ww"
WW_LOG_DIR = WW_DIR / "data" / "apps" / "ok-ww" / "working" / "logs"
NTE_DIR = SANDBOX / "fake_nte"
NTE_LOG_DIR = NTE_DIR / "data" / "apps" / "ok-nte" / "working" / "logs"
FRAMEWORK_LOG = SANDBOX / "logs" / "onedragon_helper.log"

# 假游戏本体：自跑心跳循环（onedir 打包，启动即写心跳，无需参数即可常驻）
GAME_MAIN_SOURCE = """\
import os
import pathlib
import time

hb = pathlib.Path(r"{HEARTBEAT}")
with hb.open("a") as f:
    f.write("start pid=%d t=%f\\n" % (os.getpid(), time.time()))
while True:
    with hb.open("a") as f:
        f.write("beat pid=%d t=%f\\n" % (os.getpid(), time.time()))
    time.sleep(2)
"""

# 假日常脚本 ok-ww.exe：按真实日志规则伪造「今日已完成」，写完即退（external）
WW_MAIN_SOURCE = """\
import pathlib
import time

log = pathlib.Path(r"{WW_LOG_DIR}")
log.mkdir(parents=True, exist_ok=True)
(log / "ok-script.log").write_text(
    "info_set current_stamina 145\\n"
    "current daily progress 180\\n",
    encoding="utf-8",
)
pathlib.Path(r"{WW_DIR}").joinpath("ran.txt").write_text("1")
time.sleep(2)
"""

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(
        f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  — {detail}" if detail else "")
    )


def _pyinstaller(name: str, main_py: Path, onedir: bool, distpath: Path) -> None:
    args = [sys.executable, "-m", "PyInstaller", "--noupx", "--console"]
    if not onedir:
        args.append("--onefile")
    args += [
        "--distpath",
        str(distpath),
        "--workpath",
        str(SANDBOX / "_pyi" / name),
        "--specpath",
        str(SANDBOX / "_pyi"),
        "--name",
        name,
        str(main_py),
    ]
    subprocess.run(args, check=True, capture_output=True)


def build_sandbox() -> None:
    (SANDBOX / "config").mkdir(parents=True)
    (SANDBOX / "config" / "script_chain").mkdir()
    GAME_DIR.mkdir(parents=True)
    WW_DIR.mkdir(parents=True)
    NTE_DIR.mkdir(parents=True)
    NTE_LOG_DIR.mkdir(parents=True)

    # 日志分析关键词：从真实仓库复制（假脚本按真实规则伪造日志）
    shutil.copy(
        REAL_ROOT / "config" / "log_analysis.yml",
        SANDBOX / "config" / "log_analysis.yml",
    )

    game_main = GAME_DIR / "game_main.py"
    game_main.write_text(GAME_MAIN_SOURCE.replace("{HEARTBEAT}", str(HEARTBEAT)))
    _pyinstaller("FakeGame", game_main, onedir=True, distpath=GAME_DIR)

    ww_main = WW_DIR / "ok-ww.py"
    ww_main.write_text(
        WW_MAIN_SOURCE.replace("{WW_LOG_DIR}", str(WW_LOG_DIR)).replace(
            "{WW_DIR}", str(WW_DIR)
        )
    )
    _pyinstaller("ok-ww", ww_main, onedir=False, distpath=WW_DIR)

    # 假日常脚本 ok-nte：首跑无成功标记 + ERROR 行（FAILED/重跑候选）；重跑才写成功标记
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

    # config.yml：ok-ww 为 external（runner 先启动 FakeGame 再跑它、收尾杀游戏）；
    # ok-nte 为 python（进程内 exec，首跑失败触发重跑轮）。
    from src.utils.utils_yaml import dump_yaml

    ww = default_script_entry(
        display_name="ok-ww",
        script_type="external",
        script_path=str(WW_DIR / "ok-ww.exe"),
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
    dump_yaml(SANDBOX / "config" / "config.yml", {"script_list": [ww, nte]})
    dump_yaml(
        SANDBOX / "config" / "schedule.yml",
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
        SANDBOX / "config" / "weekly.yml",
        {
            "weekly_start": {},
            "weekly_timeouts": {"ok-ww": [3600] * 7, "ok-nte": [3600] * 7},
        },
    )


def spawn_leftover_game():
    """起一个「昨晚残留」的假游戏（自跑 exe 常驻），返回 Popen 供事后验证被清场杀掉。"""
    return subprocess.Popen(
        [str(GAME_EXE)],
        cwd=str(GAME_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def alive_named(name: str) -> list:
    return [
        p
        for p in psutil.process_iter(["name"])
        if (p.info["name"] or "").lower() == name.lower()
    ]


def read_framework_log() -> str:
    return (
        FRAMEWORK_LOG.read_text(encoding="utf-8", errors="replace")
        if FRAMEWORK_LOG.exists()
        else ""
    )


def main() -> int:
    # 看门狗：180s 未结束即全栈转储并退出（定位挂起，不静默吊死）
    import faulthandler

    faulthandler.dump_traceback_later(180, exit=True)

    print(f"沙箱: {SANDBOX}")
    build_sandbox()
    setup_logging()

    enabled = {"ok-ww", "ok-nte"}
    now = datetime.now()
    if now.minute <= 57:
        target_dt = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        target = target_dt.strftime("%H:%M")
        expected_wait = (target_dt - now).total_seconds()
        mode = f"定时（等 {expected_wait:.0f}s，目标 {target}）"
    else:
        target = "now"
        expected_wait = 0.0
        mode = "即时（now，临近午夜跳过定时等待避免跨天）"
    print(f"运行模式: {mode}")

    leftover = spawn_leftover_game()
    time.sleep(3)  # 留足解压/启动时间，确保残留实例也写下心跳
    print(f"残留假游戏已起 pid={leftover.pid}")

    t0 = time.time()
    try:
        chain_service.schedule_run(
            enabled,
            target,
            chain_name="today",
            mute=False,
            shutdown_delay=None,
            close_running=True,
        )
    finally:
        elapsed = time.time() - t0
        # 安全网：清掉一切残留假游戏
        for p in alive_named(GAME_NAME):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                p.kill()

    print(f"\nschedule_run 返回，耗时 {elapsed:.0f}s，逐项核验：")

    # 1. 定时等待真实发生
    log_text = read_framework_log()
    if target != "now":
        check(
            "定时等待：日志含『定时运行已设置，将等待至』",
            "定时运行已设置，将等待至" in log_text,
        )
        check(
            f"定时等待：真实等待 ≥ 预期 {expected_wait:.0f}s",
            elapsed >= max(expected_wait - 2, 0),
            f"耗时 {elapsed:.0f}s",
        )
    else:
        check("定时等待：临近午夜按计划跳过", True)

    # 2. pre_run 清场杀掉残留假游戏
    check(
        "清场：残留 FakeGame 已被 pre_run 终止",
        leftover.poll() is not None,
        f"returncode={leftover.poll()}",
    )
    check("清场：日志含『已关闭残留进程』", "已关闭残留进程" in log_text)

    # 3. 链生成（today + rerun 两份）与重跑决策
    check("生成链 today.yml", (SANDBOX / "config/script_chain/today.yml").exists())
    check("重跑链 rerun.yml", (SANDBOX / "config/script_chain/rerun.yml").exists())
    check(
        "日志含『重跑 1 个脚本: ['ok-nte']』",
        "重跑 1 个脚本" in log_text and "'ok-nte'" in log_text,
    )

    # 4. 假脚本真的跑了：ok-ww external 一次；ok-nte 首跑失败 + 重跑成功
    check("ok-ww 已运行", (WW_DIR / "ran.txt").exists())
    check(
        "ok-ww 日志含成功标记",
        "current daily progress 180"
        in (WW_LOG_DIR / "ok-script.log").read_text(encoding="utf-8"),
    )
    check(
        "ok-nte 重跑后日志含成功标记",
        "info_set failed []"
        in (NTE_LOG_DIR / "ok-script.log").read_text(encoding="utf-8"),
    )

    # 5. 游戏生命周期：残留 + runner 启动共 2 个实例都真实活过，最终全部收尾
    check("游戏收尾：结束时无 FakeGame 进程存活", not alive_named(GAME_NAME))
    heartbeats = set()
    if HEARTBEAT.exists():
        for line in HEARTBEAT.read_text(encoding="utf-8").splitlines():
            if line.startswith("start ") and "pid=" in line:
                heartbeats.add(line.split("pid=")[1].split()[0])
    check(
        "游戏生命周期：心跳含 2 个实例（残留 + runner 启动）",
        len(heartbeats) >= 2,
        f"实际心跳实例: {sorted(heartbeats)}",
    )

    # 6. 安全边界：无关机 / 无静音 / 无邮件
    check("安全：全程未触发关机", "关机" not in log_text)
    check("安全：未触碰系统静音（mute=False）", "静音" not in log_text)
    check("安全：未发送邮件（notify=False）", "发送" not in log_text)

    # 7. 进程收尾
    check("收尾：无 FakeGame 残留进程", not alive_named(GAME_NAME))

    failed = [r for r in results if not r[1]]
    print(
        f"\n{'=' * 56}\n结果: {len(results) - len(failed)}/{len(results)} 通过；沙箱保留供检查: {SANDBOX}"
    )
    for name, _ok, detail in failed:
        print(f"  FAIL {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    code = 0
    try:
        code = main()
    finally:
        # 双保险清理（正常路径 runner/清场已杀）
        for p in alive_named(GAME_NAME):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                p.kill()
    sys.exit(code)
