"""针对打包产物 OneDragon-Helper.exe 的「运行前关闭残留进程」集成测试（模拟真实情景）。

与 tests/test_schedule.py（ProcessSim 用 mock psutil 测 close_running_scripts）互补：
本文件**真实启动打包 exe**，用唯一命名的真实 OS 进程（odh_stub_game.exe / odh_stub_body.exe）
模拟残留游戏与脚本真身，验证冻结后的 exe 真的能按 game_process_name / script_process_name
杀掉真实进程——这是 mock 永远证明不了的。

安全设计（避免误拉起游戏 / 误触 UAC / 误杀）：
- 只造唯一命名的真实进程（odh_stub_game.exe / odh_stub_body.exe），绝不碰任何真实游戏 / 真实脚本。
- 链运行只拉起一个退出 0 的 .cmd stub，不启动任何外部程序。
- 临时改写 exe 捆绑的 config.yml（仅替换为一条 stub 脚本条目），测试结束后恢复原状。
- exe manifest 标了 uac_admin=True；非管理员环境下调用会弹 UAC 卡死，故整文件 skip
  （CI 的 windows runner 默认管理员，可真跑）。
"""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from src.utils_yaml import dump_yaml
from tests.exe import project_root

PROJECT_ROOT = str(project_root())

_CANDIDATES = [
    os.environ.get("ODH_GUI_EXE"),
    os.path.join(
        PROJECT_ROOT, "deploy", "dist", "OneDragon-Helper", "OneDragon-Helper.exe"
    ),
    os.path.join(
        PROJECT_ROOT, "deploy", "dist_opt", "OneDragon-Helper", "OneDragon-Helper.exe"
    ),
    os.path.join(
        PROJECT_ROOT, "deploy", "dist_new", "OneDragon-Helper", "OneDragon-Helper.exe"
    ),
]
GUI_EXE = next((p for p in _CANDIDATES if p and os.path.isfile(p)), None)
EXE_CONFIG = (
    os.path.join(os.path.dirname(GUI_EXE), "config", "config.yml") if GUI_EXE else None
)


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _kill_process_tree(pid: int) -> None:
    """结束整个进程树（含子进程）。

    windowed exe 跑 --schedule-run now 时拉起独立 Runner 子进程且自身不一定退出；
    仅 terminate 父 exe 会留下孤儿 Runner 占用资源、污染后续用例，故必须用
    taskkill /T 结束整棵树。本测试仅在 Windows 运行（CAN_RUN_EXE 已限定），
    非 Windows 直接返回。
    """
    if sys.platform != "win32":
        return
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


CAN_RUN_EXE = sys.platform == "win32" and GUI_EXE is not None and _is_admin()
_SKIP_REASON = "需要 Windows + 管理员权限 + 存在的 GUI exe 才能真实测试打包产物" + (
    f"（未找到 exe，候选: {_CANDIDATES}）" if GUI_EXE is None else ""
)

_GAME_NAME = "odh_stub_game.exe"
_BODY_NAME = "odh_stub_body.exe"
_CMD_STUB = "@exit /b 0\n"


@unittest.skipUnless(CAN_RUN_EXE, _SKIP_REASON)
class TestExeCloseRunning(unittest.TestCase):
    """真实启动 exe，用真实进程验证「运行前关闭残留」确实杀掉了真实 OS 进程。"""

    def _spawn_stub(self, workdir: str, name: str) -> subprocess.Popen:
        """造一个常驻的真实进程 <name>（按名可被 exe 的 close 命中）。

        用 System32\\cmd.exe 复制并重命名为 <name> 后跑一个长驻命令，
        而非复制 sys.executable（venv 的 python.exe）：后者缺 pyvenv.cfg /
        侧旁 DLL，在临时目录中复制后会立即退出（返回码 106 "No pyvenv.cfg
        file"），导致 game.poll() 从一开始就是非 None、被误判为「已被杀」，
        负路径用例随之假失败。cmd.exe 自包含，必为常驻进程，按名匹配稳定。
        """
        stub = os.path.join(workdir, name)
        cmd_exe = os.path.join(os.environ["SYSTEMROOT"], "System32", "cmd.exe")
        shutil.copy(cmd_exe, stub)
        flags = (
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        # ping -n 600 约驻留 600s，足够覆盖正负路径的等待窗口。
        return subprocess.Popen(
            [stub, "/c", "ping -n 600 127.0.0.1 > nul"],
            creationflags=flags,
        )

    def _write_stub_config(self, workdir: str, *, body_name: str | None = None) -> str:
        """把 exe 捆绑的 config.yml 仅替换为一条 stub 脚本条目，返回原内容以便恢复。

        body_name 非 None 时写入 script_process_name（指向真实存在的脚本真身进程），
        用于验证「真身」也按名被 close 命中；为 None 则留空，只验游戏进程。

        用项目统一的 ruamel dump_yaml 写回（不依赖 PyYAML），与 exe 自己的
        load_yaml（ruamel）格式一致。
        """
        assert EXE_CONFIG is not None
        with open(EXE_CONFIG, encoding="utf-8") as f:
            original = f.read()
        # 只留一条 stub：close_running_scripts 扫全量 script_list 会命中其 game_process_name；
        # 链运行（--enable 缺省=all）只跑这条，拉起退出 0 的 .cmd，不碰任何真实程序。
        data = {
            "script_list": [
                {
                    "display_name": "odh_stub_script",
                    "script_path": os.path.join(workdir, "odh_stub_script.cmd"),
                    "script_process_name": body_name if body_name else [],
                    "game_process_name": _GAME_NAME,
                    # 关掉「脚本跑完后由 Runner 主动杀游戏/真身」的默认行为：
                    # kill_game_after_done / kill_script_after_done 默认均为 True，
                    # 会让链在 .cmd 退出后按 game_process_name 把 odh_stub_game.exe
                    # 杀掉，使负路径用例（不带 --close-running 仍期望游戏存活）被误判失败。
                    # 设为 False 后，杀进程的唯一起因只剩 close_running_scripts，
                    # 从而精确隔离被测功能。
                    "kill_game_after_done": False,
                    "kill_script_after_done": False,
                }
            ]
        }
        dump_yaml(EXE_CONFIG, data)
        return original

    def _run_once(self, *, close_running: bool, with_body: bool) -> tuple[bool, bool]:
        """真实启动 exe 跑一次即时调度（--schedule-run now）。

        不依赖 exe 退出：exe 整条链路（pre_run→链运行→post_run）可能因链运行/
        关机/邮件等不立即退出，但 close 在 pre_run 已执行。故以「游戏/真身 stub
        进程是否已被杀」为唯一判据。

        - close_running=True：最多等 30s 让 close 把 game（及 body）进程按名杀掉。
        - close_running=False：等待 8s 让 pre_run 运行（close 不生效），再判定存活。

        Returns:
            (game_killed, body_killed)：close 后两进程是否已被杀（True=已死）。
            with_body=False 时 body_killed 恒为 False。
        finally 会杀掉仍在运行的 exe 与残留 stub，并恢复原始 config。
        """
        workdir = tempfile.mkdtemp(prefix="odh_close_")
        with open(
            os.path.join(workdir, "odh_stub_script.cmd"), "w", encoding="utf-8"
        ) as f:
            f.write(_CMD_STUB)
        game = self._spawn_stub(workdir, _GAME_NAME)
        body = self._spawn_stub(workdir, _BODY_NAME) if with_body else None
        exe = None
        original = None
        try:
            original = self._write_stub_config(
                workdir, body_name=_BODY_NAME if with_body else None
            )
            cmd = [GUI_EXE, "--schedule-run", "now"]
            if close_running:
                cmd.append("--close-running")
            # windowed exe 经 _emit_cli 写文件，不捕获 stdout 以免管道死锁；
            # 不依赖 exe 退出码（链路可能挂起）。
            exe = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if close_running:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if game.poll() is not None and (
                        body is None or body.poll() is not None
                    ):
                        break
                    time.sleep(0.5)
            else:
                # 负路径：给 pre_run 足够时间运行（close 不生效），再判定存活。
                time.sleep(8)
            game_killed = game.poll() is not None
            body_killed = body.poll() is not None if body is not None else False
            return (game_killed, body_killed)
        finally:
            # 杀掉仍运行的 exe 整棵进程树（含其拉起的 Runner 子进程）：windowed exe
            # 跑 --schedule-run now 不一定退出，仅 kill 父 exe 会留下孤儿 Runner；
            # 用 /T 结束整棵树避免进程泄漏污染后续用例。stub 已关 kill_game_after_done，
            # 链运行本身不再杀游戏，本步仅做清理。
            if exe is not None and exe.poll() is None:
                _kill_process_tree(exe.pid)
            if original is not None:
                with open(EXE_CONFIG, "w", encoding="utf-8") as f:
                    f.write(original)
            for proc in (game, body):
                if proc is not None and proc.poll() is None:
                    proc.kill()

    def test_exe_close_running_kills_real_process(self):
        """--close-running 应让真实 exe 按 game_process_name 杀掉真实残留进程。"""
        game_killed, _ = self._run_once(close_running=True, with_body=False)
        self.assertTrue(game_killed, "close-running 未杀掉真实 odh_stub_game.exe 进程")

    def test_exe_without_close_running_spares_real_process(self):
        """不带 --close-running 时，真实 exe 不应杀掉残留进程。"""
        game_killed, _ = self._run_once(close_running=False, with_body=False)
        self.assertFalse(
            game_killed, "未启用 close-running 却杀掉了真实 odh_stub_game.exe 进程"
        )

    def test_exe_close_running_kills_body_and_game(self):
        """--close-running 应让真实 exe 同时按 script_process_name 杀掉脚本真身、
        按 game_process_name 杀掉游戏两个真实进程（对应 ProcessSim 的
        test_run_kills_each_body_and_game 在真实二进制层面的重验）。"""
        game_killed, body_killed = self._run_once(close_running=True, with_body=True)
        self.assertTrue(
            body_killed, "close-running 未杀掉真实 odh_stub_body.exe 脚本真身进程"
        )
        self.assertTrue(
            game_killed, "close-running 未杀掉真实 odh_stub_game.exe 游戏进程"
        )


if __name__ == "__main__":
    unittest.main()
