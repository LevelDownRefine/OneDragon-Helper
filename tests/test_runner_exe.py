"""针对打包产物 OneDragon-Helper-Runner.exe 的集成测试（专门测 exe）。

与 src/runner/tests/test_launcher.py（纯 Python 层 mock/import 测试）互补：
本文件**真正启动打包出来的 exe**，验证它能被拉起、参数能被正确路由、能执行脚本。

安全设计（避免误拉起游戏 / 误触 UAC）：
- 只用已有的 ``--script <stub.py>`` 与 ``--help`` 路径；``--script`` 单文件模式不加载
  脚本链配置、不启动任何游戏。不引入新的 exe CLI 参数。
- exe 的 manifest 标了 uac_admin=True。非管理员环境下调用会弹 UAC 卡死，因此：
  * 非 Windows / exe 不存在 / 非管理员，整文件 skip（不报错、不卡）。
  * 可用环境变量 ODH_RUNNER_EXE 指定任意构建产物路径。

注意：需要在「管理员终端」下运行才能真实验证 exe；CI / 普通终端下自动 skip。
"""

import contextlib
import ctypes
import os
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CANDIDATES = [
    os.environ.get("ODH_RUNNER_EXE"),
    os.path.join(PROJECT_ROOT, "deploy", "dist_opt", "OneDragon-Helper-Runner.exe"),
    os.path.join(PROJECT_ROOT, "deploy", "dist", "OneDragon-Helper-Runner.exe"),
    os.path.join(PROJECT_ROOT, "deploy", "dist_new", "OneDragon-Helper-Runner.exe"),
    os.path.join(
        PROJECT_ROOT,
        "deploy",
        "dist_opt",
        "OneDragon-Helper",
        "OneDragon-Helper-Runner.exe",
    ),
]
RUNNER_EXE = next((p for p in _CANDIDATES if p and os.path.isfile(p)), None)


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


CAN_RUN_EXE = sys.platform == "win32" and RUNNER_EXE is not None and _is_admin()
_SKIP_REASON = "需要 Windows + 管理员权限 + 存在的 Runner exe 才能真实测试打包产物" + (
    f"（未找到 exe，候选: {_CANDIDATES}）" if RUNNER_EXE is None else ""
)


@unittest.skipUnless(CAN_RUN_EXE, _SKIP_REASON)
class TestRunnerExe(unittest.TestCase):
    """真实启动 OneDragon-Helper-Runner.exe 的集成测试。"""

    def _run_exe(self, *args, timeout: int = 120):
        return subprocess.run(
            [RUNNER_EXE, *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            # 与 test_gui_exe 同源：exe 的 stderr 可能含 GBK 中文，text=True(utf-8) 解码
            # 会失败使 result.stderr 变 None 并可能死锁。统一 errors='replace' 解码。
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

    def test_exe_help_reports_usage(self):
        """--help 应打印用法（含 --chain）并以退出码 0 结束。"""
        result = self._run_exe("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("chain", result.stdout.lower())

    def test_exe_runs_single_script(self):
        """--script 单文件模式：exe 应成功 exec 一个无害 .py 并以退出码 0 结束。"""
        marker = "ODH_RUNNER_EXE_SELFTEST_OK"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(f'print("{marker}")\n')
            stub = fh.name
        try:
            result = self._run_exe("--script", stub)
        finally:
            with contextlib.suppress(OSError):
                os.remove(stub)
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        self.assertIn(marker, result.stdout)


if __name__ == "__main__":
    unittest.main()
