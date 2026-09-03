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
import unittest

from src.utils_yaml import dump_yaml
from tests.exe import project_root

PROJECT_ROOT = str(project_root())

_CANDIDATES = [
    os.environ.get("ODH_GUI_EXE"),
    os.path.join(PROJECT_ROOT, "deploy", "dist", "OneDragon-Helper", "OneDragon-Helper.exe"),
    os.path.join(PROJECT_ROOT, "deploy", "dist_opt", "OneDragon-Helper", "OneDragon-Helper.exe"),
    os.path.join(PROJECT_ROOT, "deploy", "dist_new", "OneDragon-Helper", "OneDragon-Helper.exe"),
]
GUI_EXE = next((p for p in _CANDIDATES if p and os.path.isfile(p)), None)
EXE_CONFIG = (
    os.path.join(os.path.dirname(GUI_EXE), "config", "config.yml")
    if GUI_EXE
    else None
)


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


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
        """造一个常驻的真实进程 <name>（按名可被 exe 的 close 命中）。"""
        stub = os.path.join(workdir, name)
        shutil.copy(sys.executable, stub)
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        return subprocess.Popen(
            [stub, "-c", "import time; time.sleep(600)"],
            creationflags=flags,
        )

    def _spawn_game_stub(self, workdir: str) -> subprocess.Popen:
        return self._spawn_stub(workdir, _GAME_NAME)

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
                }
            ]
        }
        dump_yaml(EXE_CONFIG, data)
        return original

    def _run_schedule(self, *, close_running: bool) -> tuple[subprocess.Popen, int | None]:
        """启动 exe 跑一次即时调度（--schedule-run now），返回 (game进程, exe退出码)。

        退出码为 None 表示 exe 超时（链运行卡住）；此时 close 已在 pre_run 完成，
        游戏进程应已被杀，调用方仍可按游戏存活与否断言。
        """
        workdir = tempfile.mkdtemp(prefix="odh_close_")
        with open(os.path.join(workdir, "odh_stub_script.cmd"), "w", encoding="utf-8") as f:
            f.write(_CMD_STUB)
        original = None
        game = None
        try:
            original = self._write_stub_config(workdir)
            game = self._spawn_game_stub(workdir)
            cmd = [GUI_EXE, "--schedule-run", "now"]
            if close_running:
                cmd.append("--close-running")
            try:
                result = subprocess.run(
                    cmd,
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
                code = result.returncode
            except subprocess.TimeoutExpired as exc:
                if exc.process is not None:
                    exc.process.kill()
                code = None
            return game, code
        finally:
            if game is not None and game.poll() is None:
                game.kill()
            if original is not None:
                with open(EXE_CONFIG, "w", encoding="utf-8") as f:
                    f.write(original)

    def _run_schedule_with_body(self, *, close_running: bool) -> tuple[
        subprocess.Popen, subprocess.Popen, int | None
    ]:
        """启动 exe 跑即时调度，同时造真实「脚本真身 + 游戏」两个进程，验两者均被杀。

        与 _run_schedule 的区别：config 条目的 script_process_name 指向真实存在的
        odh_stub_body.exe 进程（而非空），故 close 应同时命中「真身」与「游戏」两条匹配。
        """
        workdir = tempfile.mkdtemp(prefix="odh_close_")
        with open(os.path.join(workdir, "odh_stub_script.cmd"), "w", encoding="utf-8") as f:
            f.write(_CMD_STUB)
        original = None
        game = None
        body = None
        try:
            original = self._write_stub_config(workdir, body_name=_BODY_NAME)
            game = self._spawn_stub(workdir, _GAME_NAME)
            body = self._spawn_stub(workdir, _BODY_NAME)
            cmd = [GUI_EXE, "--schedule-run", "now"]
            if close_running:
                cmd.append("--close-running")
            try:
                result = subprocess.run(
                    cmd,
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
                code = result.returncode
            except subprocess.TimeoutExpired as exc:
                if exc.process is not None:
                    exc.process.kill()
                code = None
            return game, body, code
        finally:
            for proc in (game, body):
                if proc is not None and proc.poll() is None:
                    proc.kill()
            if original is not None:
                with open(EXE_CONFIG, "w", encoding="utf-8") as f:
                    f.write(original)

    def test_exe_close_running_kills_real_process(self):
        """--close-running 应让真实 exe 按 game_process_name 杀掉真实残留进程。"""
        game, _code = self._run_schedule(close_running=True)
        self.assertIsNotNone(
            game.poll(), "close-running 未杀掉真实 odh_stub_game.exe 进程"
        )

    def test_exe_without_close_running_spares_real_process(self):
        """不带 --close-running 时，真实 exe 不应杀掉残留进程。"""
        game, _code = self._run_schedule(close_running=False)
        self.assertIsNone(
            game.poll(), "未启用 close-running 却杀掉了真实 odh_stub_game.exe 进程"
        )

    def test_exe_close_running_kills_body_and_game(self):
        """--close-running 应让真实 exe 同时按 script_process_name 杀掉脚本真身、
        按 game_process_name 杀掉游戏两个真实进程（对应 ProcessSim 的
        test_run_kills_each_body_and_game 在真实二进制层面的重验）。"""
        game, body, _code = self._run_schedule_with_body(close_running=True)
        self.assertIsNotNone(
            body.poll(), "close-running 未杀掉真实 odh_stub_body.exe 脚本真身进程"
        )
        self.assertIsNotNone(
            game.poll(), "close-running 未杀掉真实 odh_stub_game.exe 游戏进程"
        )


if __name__ == "__main__":
    unittest.main()
