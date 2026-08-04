"""源码级 CLI 单测（offscreen，CI / 普通终端均可真跑）。

与 tests/test_gui_exe.py（必须 Windows + 管理员 + 已打包 exe 才跑，CI 全 skip）互补：
本文件直接调 ``launcher.main()`` 并 patch ``sys.argv``，验证各 CLI 出口的退出码与
文件产物，无需打包、无需管理员，CI 也能覆盖。

关键约定：
- CLI 出口都通过 ``sys.exit`` 返回，故用 ``assertRaises(SystemExit)`` 捕获退出码。
- --help/--version/--generate-chain/--run-chain 的结果经 ``_emit_cli`` 写临时文件，
  测试读这些文件验证实质行为（与 windowed exe 的可观测方式一致）。
- --generate-chain 会经 ``generate_chain_config`` 调 ``set_config``，可能回写真实脚本
  配置（依赖游戏 exe 存在）。源码测试里 patch 掉 ``src.gui.chain.set_config``，
  避免副作用、并使其不依赖本机是否装有游戏。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# 必须在导入 PySide6 / launcher 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml

from src import launcher
from src.gui import chain as gui_chain

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cli_file(kind: str) -> str:
    """CLI 出口结果文件（与 src/launcher.py 的 _emit_cli 对应）。"""
    return os.path.join(tempfile.gettempdir(), f"odh_gui_{kind}.txt")


def _run_main(argv, expect_exit=None):
    """patch sys.argv 后调 launcher.main()，返回退出码。

    main() 的 CLI 出口都用 sys.exit 退出，故捕获 SystemExit 取退出码。
    正常 CLI 出口会走到 sys.exit；若意外落到 GUI 主路径（不退出），返回 0。
    """
    with patch.object(sys, "argv", ["launcher.py", *argv]):
        try:
            launcher.main()
        except SystemExit as exc:
            code = exc.code
        else:  # pragma: no cover - main() 的正常 CLI 出口必走 sys.exit
            code = 0
    if expect_exit is not None:
        assert code == expect_exit, f"期望退出码 {expect_exit}，实际 {code}"
    return code


def _read_cli_file(kind: str) -> str:
    path = _cli_file(kind)
    assert os.path.isfile(path), f"{kind} 未生成文件: {path}"
    with open(path, encoding="utf-8") as f:
        return f.read()


def _known_script_names():
    # 确保 config.yml 存在：复用 launcher 自身的首次运行逻辑（与 main() 一致，
    # 即「若 need_config_workflow 则 config_workflow」），不手动复制文件。
    # 随后直接读取 --generate-chain 实际使用的同一份 config.yml，保证期望集合与
    # 产出集合同源（本地真实 config 可能含 example 没有的脚本，如 MAS）。
    if launcher.need_config_workflow():
        launcher.config_workflow()
    config_path = launcher.get_config_yml_path_under_root()
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [s["display_name"] for s in data.get("script_list", [])]


class TestCliHelpVersion(unittest.TestCase):
    """--help / --version 出口：退出 0 且结果写文件。"""

    def test_help_exit_zero_and_writes_file(self):
        code = _run_main(["--help"], expect_exit=0)
        self.assertEqual(code, 0)
        text = _read_cli_file("help")
        self.assertIn("OneDragon", text)

    def test_version_exit_zero_and_writes_file(self):
        code = _run_main(["--version"], expect_exit=0)
        self.assertEqual(code, 0)
        text = _read_cli_file("version").strip()
        self.assertTrue(text, "--version 文件为空")
        self.assertEqual(text, launcher._get_version())


class TestCliSelftest(unittest.TestCase):
    """--selftest 出口：无头构造 MainWindow，退出 0 且 JSON 标记 OK。"""

    def test_selftest_ok(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            out = fh.name
        try:
            code = _run_main(["--selftest", "--out", out], expect_exit=0)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(out), f"--selftest 未生成 JSON: {out}")
            with open(out, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data.get("status"), "ok", msg=data)
            checks = data.get("checks", {})
            self.assertTrue(checks.get("mainwindow_created"), msg=checks)
            self.assertIn("script_count", checks, msg=checks)
            self.assertIn("config_loaded", checks, msg=checks)
        finally:
            if os.path.exists(out):
                os.remove(out)


class TestCliGenerateChain(unittest.TestCase):
    """--generate-chain 出口：产出仅含启用脚本的 yml；缺名时报错退出 1。"""

    def setUp(self):
        self._names = _known_script_names()
        self.assertTrue(self._names, "config.yml 不应为空脚本列表")

    def test_generate_chain_default_all_enabled(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            with patch.object(gui_chain, "set_config"):
                code = _run_main(["--generate-chain", "--out", out], expect_exit=0)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(out), f"--generate-chain 未产出 yml: {out}")
            with open(out, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertIn("script_list", data, msg=data)
            produced = [s["display_name"] for s in data["script_list"]]
            self.assertEqual(set(produced), set(self._names), msg=produced)
            # _emit_cli 也应写了结果文件
            self.assertIn("已生成脚本链配置", _read_cli_file("generate_chain"))
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_enable_subset(self):
        target = self._names[0]
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            with patch.object(gui_chain, "set_config"):
                code = _run_main(
                    ["--generate-chain", "--enable", target, "--out", out],
                    expect_exit=0,
                )
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            produced = [s["display_name"] for s in data["script_list"]]
            self.assertEqual(produced, [target], msg=produced)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_unknown_name_exits_one(self):
        bogus = "此脚本一定不存在_XYZ"
        assert bogus not in self._names
        with patch.object(gui_chain, "set_config"):
            code = _run_main(["--generate-chain", "--enable", bogus], expect_exit=1)
        self.assertEqual(code, 1)
        self.assertIn("未知的脚本名", _read_cli_file("generate_chain"))


class TestCliRunChain(unittest.TestCase):
    """--run-chain 出口：配置文件不存在时退出 1 且不真正拉起 Runner。"""

    def test_run_chain_missing_config_exits_one(self):
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as fh:
            missing = fh.name
        os.unlink(missing)  # 故意不创建
        with patch("src.gui.runner.run_chain_command") as mock_run:
            code = _run_main(["--run-chain", missing], expect_exit=1)
        self.assertEqual(code, 1)
        mock_run.assert_not_called()  # 缺文件时不该真正启动 Runner
        self.assertIn("脚本链配置不存在", _read_cli_file("run_chain"))


if __name__ == "__main__":
    unittest.main()
