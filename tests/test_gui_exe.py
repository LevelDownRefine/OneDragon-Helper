"""针对打包产物 OneDragon-Helper.exe 的集成测试（专门测 GUI exe）。

与 tests/test_gui_*.py（PySide6 控件 mock 的源码层测试）互补：
本文件**真正启动打包出来的 GUI exe**，验证它的 CLI 出口能被正确路由并产生可观测结果。

关键约束（决定测试怎么写）：
- exe 的 manifest 标了 uac_admin=True。非管理员环境下调用会弹 UAC 卡死，因此：
  * 非 Windows / exe 不存在 / 非管理员，整文件 skip（不报错、不卡）。
  * 可用环境变量 ODH_GUI_EXE 指定任意构建产物路径。
- GUI exe 是 console=False（windowed），stdout/stderr 被重定向丢弃，subprocess 捕获不到输出。
  因此 CLI 出口（--help/--version/--selftest）的结果会**同时写文件**，测试改读这些文件产物验证。

注意：需要在「管理员终端」下运行才能真实验证 exe；CI / 普通终端下自动 skip。
"""

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import unittest

from src.config.yaml_rt import load_yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli_file(kind: str) -> str:
    """CLI 出口结果文件（与 src/cli.py 的 _emit_cli / _run_selftest 对应）。"""
    if kind == "selftest":
        return os.path.join(tempfile.gettempdir(), "odh_gui_selftest.json")
    return os.path.join(tempfile.gettempdir(), f"odh_gui_{kind}.txt")


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


@unittest.skipUnless(CAN_RUN_EXE, _SKIP_REASON)
class TestGuiExe(unittest.TestCase):
    """真实启动 OneDragon-Helper.exe 的集成测试。"""

    def _run_exe(self, *args, timeout: int = 120):
        return subprocess.run(
            [GUI_EXE, *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def test_exe_help(self):
        """--help 应退出 0，并把用法写文件（windowed 下 stdout 不可见）。"""
        result = self._run_exe("--help")
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        path = _cli_file("help")
        self.assertTrue(os.path.isfile(path), f"--help 未生成文件: {path}")
        with open(path, encoding="utf-8") as f:
            self.assertIn("OneDragon", f.read())

    def test_exe_version(self):
        """--version 应退出 0，并把版本号写文件。"""
        result = self._run_exe("--version")
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        path = _cli_file("version")
        self.assertTrue(os.path.isfile(path), f"--version 未生成文件: {path}")
        with open(path, encoding="utf-8") as f:
            self.assertTrue(f.read().strip(), "--version 文件为空")

    def test_exe_selftest(self):
        """--selftest 应无头校验 ChainService 并写 JSON 结果（status=ok、关键检查通过）。"""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            out = fh.name
        result = self._run_exe("--selftest", "--out", out)
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        self.assertTrue(os.path.isfile(out), f"--selftest 未生成 JSON: {out}")
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("status"), "ok", msg=data)
        checks = data.get("checks", {})
        self.assertTrue(checks.get("service_ready"), msg=checks)
        self.assertIn("script_count", checks, msg=checks)
        self.assertTrue(checks.get("config_loaded"), msg=checks)

    def test_exe_generate_chain(self):
        """--generate-chain 应退出 0，并把脚本链配置写到 --out 指定的路径。"""
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        result = self._run_exe("--generate-chain", "--out", out)
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        self.assertTrue(os.path.isfile(out), f"--generate-chain 未产出 yml: {out}")
        with open(out, encoding="utf-8") as f:
            data = load_yaml(f)
        self.assertIn("script_list", data, msg=data)
        self.assertIsInstance(data["script_list"], list, msg=data)

    def test_exe_run_chain_missing(self):
        """--run-chain 指向不存在的配置文件时，应退出码 1 且不真正拉起 Runner。"""
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as fh:
            missing = fh.name
        os.unlink(missing)
        result = self._run_exe("--run-chain", missing)
        self.assertEqual(result.returncode, 1, msg=result.stderr[:500])

    def test_exe_list_scripts(self):
        """--list-scripts 应退出 0，JSON 含脚本列表（可断言数量与内容）。"""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            out = fh.name
        result = self._run_exe("--list-scripts", "--out", out)
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        self.assertTrue(os.path.isfile(out), f"--list-scripts 未生成 JSON: {out}")
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("scripts", data, msg=data)
        self.assertIsInstance(data["scripts"], list, msg=data)
        self.assertGreaterEqual(data["script_count"], 1, msg=data)

    def test_exe_get_script(self):
        """--get-script 应退出 0，JSON 含目标脚本条目。"""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            out = fh.name
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh2:
            list_out = fh2.name
        result = self._run_exe("--list-scripts", "--out", list_out)
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        with open(list_out, encoding="utf-8") as f:
            names = json.load(f)["scripts"]
        result = self._run_exe("--get-script", names[0], "--out", out)
        self.assertEqual(result.returncode, 0, msg=result.stderr[:500])
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["status"], "ok", msg=data)
        self.assertEqual(data["script"]["display_name"], names[0])

    def test_exe_check_config(self):
        """--check-config 应退出 0/1 且 JSON 结构完整（invalid 元素可断言）。"""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            out = fh.name
        result = self._run_exe("--check-config", "--out", out)
        self.assertIn(result.returncode, (0, 1), msg=result.stderr[:500])
        self.assertTrue(os.path.isfile(out), f"--check-config 未生成 JSON: {out}")
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("status", data, msg=data)
        self.assertIn("script_count", data, msg=data)
        self.assertIn("invalid", data, msg=data)
        # status 与退出码一致：invalid 非空 → 1，空 → 0
        if data["invalid"]:
            self.assertEqual(result.returncode, 1)
        else:
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
