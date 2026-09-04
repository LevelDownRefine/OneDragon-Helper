"""源码级 CLI 单测（offscreen，CI / 普通终端均可真跑）。

与 tests/exe/test_gui_exe.py（必须 Windows + 管理员 + 已打包 exe 才跑，CI 全 skip）互补：
本文件直接调 ``launcher.main()`` 并 patch ``sys.argv``，验证各 CLI 出口的退出码与
文件产物，无需打包、无需管理员，CI 也能覆盖。

关键约定：
- CLI 出口都通过 ``sys.exit`` 返回，故用 ``assertRaises(SystemExit)`` 捕获退出码。
- --help/--version/--generate-chain/--run-chain 的结果经 ``cli._emit_cli`` 写临时文件，
  测试读这些文件验证实质行为（与 windowed exe 的可观测方式一致）。
- --generate-chain 现仅生成链配置（副本/周常配置已由编辑期实时落盘，周常起始日写盘
  已抽到 ScheduledRun.pre_run），不再调 ``set_config``，不依赖本机是否装有游戏。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# 必须在导入 PySide6 / launcher 之前设置 offscreen 平台插件（CI 无显示器环境）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import cli, launcher
from src.service import chain_gen as service_chain_gen
from src.utils.utils_sub_config import get_script_name
from src.utils.utils_yaml import load_yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setUpModule():
    """确保 config.yml 存在（复用 launcher 首次运行机制，与 _known_script_names 同源）。

    config.yml 被 .gitignore 排除，CI 环境缺失；本模块多数 CLI 出口依赖真实 config，
    故模块加载时先按需生成，避免隐式依赖某个测试先触发（如 _known_script_names）。
    """
    launcher.config_workflow()


def _cli_file(kind: str) -> str:
    """CLI 出口结果文件（与 src/cli.py 的 _emit_cli 对应）。"""
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


def _cli_json(kind: str) -> str:
    """结构化出口（_emit_json）的结果文件 odh_gui_<kind>.json。"""
    return os.path.join(tempfile.gettempdir(), f"odh_gui_{kind}.json")


def _read_cli_json(kind: str) -> dict:
    path = _cli_json(kind)
    assert os.path.isfile(path), f"{kind} 未生成 JSON: {path}"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _known_script_names():
    # 确保 config.yml 存在：复用 launcher 自身的首次运行逻辑（与 main() 一致），
    # 不手动复制文件。config_workflow() 内部已做「缺失才生成」判断。
    # 随后直接读取 --generate-chain 实际使用的同一份 config.yml，保证期望集合与
    # 产出集合同源（本地真实 config 可能含 example 没有的脚本，如 MAS）。
    # 返回脚本唯一标识（exe 用进程名，python/bat 用 display_name）。
    launcher.config_workflow()
    config_path = launcher.get_config_yml_path_under_root()
    data = load_yaml(config_path)
    return [get_script_name(s) for s in data.get("script_list", [])]


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
        self.assertEqual(text, cli.get_version())


class TestCliSelftest(unittest.TestCase):
    """--selftest 出口：无头校验 AppService，退出 0 且 JSON 标记 OK。"""

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
            self.assertTrue(checks.get("service_ready"), msg=checks)
            self.assertIn("script_count", checks, msg=checks)
            self.assertTrue(checks.get("config_loaded"), msg=checks)
        finally:
            if os.path.exists(out):
                os.remove(out)


class TestCliGenerateChain(unittest.TestCase):
    """--generate-chain 出口：产出仅含启用脚本的 yml；缺名时报错退出 1。"""

    def setUp(self):
        self._names = _known_script_names()
        self.assertTrue(self._names, "config.yml 不应为空脚本列表")
        # 固定「当天全部运行」，消除 weekly_timeouts 按星期剔除脚本带来的日期敏感
        # （如 AUTO-MAS 周三配置 0 不运行，会让"应含全部脚本"的断言随机失败）。
        self._resolve_daily = patch.object(
            service_chain_gen, "_resolve_daily_run", return_value=True
        )
        self._resolve_daily.start()
        self.addCleanup(self._resolve_daily.stop)

    def test_generate_chain_default_all_enabled(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            code = _run_main(["--generate-chain", "--out", out], expect_exit=0)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(out), f"--generate-chain 未产出 yml: {out}")
            data = load_yaml(out)
            self.assertIn("script_list", data, msg=data)
            produced = [get_script_name(s) for s in data["script_list"]]
            self.assertEqual(set(produced), set(self._names), msg=produced)
            # _emit_cli 也应写了结果文件
            self.assertIn("已生成脚本链配置", _read_cli_file("generate_chain"))
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_enable_all_is_explicit_all(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            code = _run_main(
                ["--generate-chain", "--enable", "all", "--out", out],
                expect_exit=0,
            )
            self.assertEqual(code, 0)
            data = load_yaml(out)
            produced = [get_script_name(s) for s in data["script_list"]]
            self.assertEqual(set(produced), set(self._names), msg=produced)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_enable_all_is_case_insensitive(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            code = _run_main(
                ["--generate-chain", "--enable", "ALL", "--out", out],
                expect_exit=0,
            )
            self.assertEqual(code, 0)
            data = load_yaml(out)
            produced = [get_script_name(s) for s in data["script_list"]]
            self.assertEqual(set(produced), set(self._names), msg=produced)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_enable_subset(self):
        target = self._names[0]
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            code = _run_main(
                ["--generate-chain", "--enable", target, "--out", out],
                expect_exit=0,
            )
            self.assertEqual(code, 0)
            data = load_yaml(out)
            produced = [get_script_name(s) for s in data["script_list"]]
            self.assertEqual(produced, [target], msg=produced)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_unknown_name_exits_one(self):
        bogus = "此脚本一定不存在_XYZ"
        assert bogus not in self._names
        code = _run_main(["--generate-chain", "--enable", bogus], expect_exit=1)
        self.assertEqual(code, 1)
        self.assertIn("未知的脚本标识", _read_cli_file("generate_chain"))

    def test_generate_chain_exclude_subset(self):
        """--exclude 从全部脚本中剔除指定标识"""
        target = self._names[0]
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            code = _run_main(
                ["--generate-chain", "--exclude", target, "--out", out],
                expect_exit=0,
            )
            self.assertEqual(code, 0)
            data = load_yaml(out)
            produced = [get_script_name(s) for s in data["script_list"]]
            self.assertEqual(set(produced), set(self._names) - {target}, msg=produced)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_exclude_with_enable(self):
        """--enable 白名单后再 --exclude，交集为最终集合"""
        target = self._names[0]
        other = self._names[1]
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            code = _run_main(
                [
                    "--generate-chain",
                    "--enable",
                    f"{target},{other}",
                    "--exclude",
                    target,
                    "--out",
                    out,
                ],
                expect_exit=0,
            )
            self.assertEqual(code, 0)
            data = load_yaml(out)
            produced = [get_script_name(s) for s in data["script_list"]]
            self.assertEqual(produced, [other], msg=produced)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_generate_chain_exclude_unknown_name_exits_one(self):
        """--exclude 含未知标识时报错退出 1"""
        bogus = "此脚本一定不存在_XYZ"
        assert bogus not in self._names
        code = _run_main(["--generate-chain", "--exclude", bogus], expect_exit=1)
        self.assertEqual(code, 1)
        self.assertIn("未知的脚本标识", _read_cli_file("generate_chain"))


class TestParseOverrides(unittest.TestCase):
    """_parse_overrides：解析 '脚本名=值' 格式的覆盖参数。"""

    def test_none_returns_empty(self):
        self.assertEqual(cli._parse_overrides(None), {})

    def test_empty_string_returns_empty(self):
        self.assertEqual(cli._parse_overrides(""), {})

    def test_single_pair(self):
        self.assertEqual(cli._parse_overrides("鸣潮=凝素领域"), {"鸣潮": "凝素领域"})

    def test_multiple_pairs(self):
        result = cli._parse_overrides("鸣潮=凝素领域,崩铁=侵蚀隧洞")
        self.assertEqual(result, {"鸣潮": "凝素领域", "崩铁": "侵蚀隧洞"})

    def test_strips_whitespace(self):
        result = cli._parse_overrides(" 鸣潮 = 凝素领域 , 崩铁 = 侵蚀隧洞 ")
        self.assertEqual(result, {"鸣潮": "凝素领域", "崩铁": "侵蚀隧洞"})

    def test_missing_equals_raises(self):
        with self.assertRaises(ValueError) as ctx:
            cli._parse_overrides("鸣潮凝素领域")
        self.assertIn("缺少 '='", str(ctx.exception))

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            cli._parse_overrides("=凝素领域")

    def test_empty_value_raises(self):
        with self.assertRaises(ValueError):
            cli._parse_overrides("鸣潮=")


class TestCliGenerateChainOverrides(unittest.TestCase):
    """--weekly-start 命令行覆盖的落盘语义。

    - --weekly-start：经 service.set_weekly_start 持久化到 weekly_start.yml
      （周几跑是长期配置），不实时写子脚本 config、不并入任何 UI 状态。
    """

    def setUp(self):
        self._names = _known_script_names()
        self.assertTrue(self._names, "config.yml 不应为空脚本列表")
        self._target = "ok-ww"
        assert self._target in self._names, f"config.yml 缺少 {self._target}"

    def test_weekly_start_persists_via_set_weekly_start(self):
        """--weekly-start 调用 service.set_weekly_start 持久化（周几跑是长期配置），
        不实时写子脚本 config、不并入任何 UI 状态。"""
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as fh:
            out = fh.name
        try:
            with (
                patch.object(cli.AppService, "generate_chain", return_value=out),
                patch.object(cli.AppService, "set_weekly_start") as mock_set,
            ):
                _run_main(
                    [
                        "--generate-chain",
                        "--enable",
                        self._target,
                        "--weekly-start",
                        f"{self._target}=4",
                        "--out",
                        out,
                    ],
                    expect_exit=0,
                )
            mock_set.assert_called_once_with(self._target, 4)
        finally:
            if os.path.exists(out):
                os.remove(out)

    def test_weekly_start_non_int_exits_one(self):
        """--weekly-start 值不是整数 → 退出 1 并报错。"""
        code = _run_main(
            [
                "--generate-chain",
                "--enable",
                self._target,
                "--weekly-start",
                f"{self._target}=abc",
            ],
            expect_exit=1,
        )
        self.assertEqual(code, 1)
        self.assertIn("不是整数", _read_cli_file("generate_chain"))

    def test_weekly_start_out_of_range_exits_one(self):
        """--weekly-start 值越界（0 / 8）→ 退出 1 并报错。"""
        for bad in ("0", "8"):
            with self.subTest(bad=bad):
                code = _run_main(
                    [
                        "--generate-chain",
                        "--enable",
                        self._target,
                        "--weekly-start",
                        f"{self._target}={bad}",
                    ],
                    expect_exit=1,
                )
                self.assertEqual(code, 1)
                self.assertIn("越界", _read_cli_file("generate_chain"))

    def test_unknown_script_in_weekly_start_exits_one(self):
        """--weekly-start 中未知脚本标识 → 退出 1 并报错。"""
        bogus = "此脚本一定不存在_XYZ"
        code = _run_main(
            [
                "--generate-chain",
                "--enable",
                self._target,
                "--weekly-start",
                f"{bogus}=4",
            ],
            expect_exit=1,
        )
        self.assertEqual(code, 1)
        self.assertIn("未知的脚本标识", _read_cli_file("generate_chain"))

    def test_weekly_start_unsupported_script_exits_one(self):
        """--weekly-start 对未支持周常的脚本 → 退出 1 并报错（不崩溃）。"""
        # 找一个不支持周常的已注册脚本（如 ok-ef 终末地）
        from src.config.set_config import _CONFIGS

        unsupported = next(n for n in _CONFIGS if not _CONFIGS[n]._weekly_task_name)
        code = _run_main(
            [
                "--generate-chain",
                "--enable",
                self._target,
                "--weekly-start",
                f"{unsupported}=4",
            ],
            expect_exit=1,
        )
        self.assertEqual(code, 1)
        self.assertIn("未支持周常", _read_cli_file("generate_chain"))


class TestCliRunChain(unittest.TestCase):
    """--run-chain 出口：配置文件不存在时退出 1 且不真正拉起 Runner。"""

    def test_run_chain_missing_config_exits_one(self):
        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as fh:
            missing = fh.name
        os.unlink(missing)  # 故意不创建
        with patch("src.utils.utils_runner.run_chain_command") as mock_run:
            code = _run_main(["--run-chain", missing], expect_exit=1)
        self.assertEqual(code, 1)
        mock_run.assert_not_called()  # 缺文件时不该真正启动 Runner
        self.assertIn("脚本链配置不存在", _read_cli_file("run_chain"))


class TestCliScheduledRun(unittest.TestCase):
    """--schedule-run 出口：解析参数并委托 chain_service.schedule_run。"""

    def _run(self, argv):
        with (
            patch.object(
                cli.AppService,
                "load_config",
                return_value={"script_list": [{"display_name": "demo"}]},
            ),
            patch.object(cli.AppService, "schedule_run") as mock_sched,
        ):
            code = _run_main(argv, expect_exit=0)
        return code, mock_sched

    def test_schedule_run_delegates_with_options(self):
        code, mock_sched = self._run(
            ["--schedule-run", "08:00", "--enable", "demo", "--shutdown", "60"]
        )
        self.assertEqual(code, 0)
        mock_sched.assert_called_once()
        args = mock_sched.call_args
        self.assertEqual(args.args[0], {"demo"})  # enabled_keys 来自 --enable
        self.assertEqual(args.args[1], "08:00")  # target_time
        self.assertEqual(args.kwargs["chain_name"], "today")
        self.assertFalse(args.kwargs["mute"])
        self.assertEqual(args.kwargs["shutdown_delay"], 60)
        self.assertFalse(args.kwargs["close_running"])

    def test_schedule_run_defaults(self):
        code, mock_sched = self._run(["--schedule-run", "08:00"])
        self.assertEqual(code, 0)
        mock_sched.assert_called_once()
        self.assertEqual(
            mock_sched.call_args.args[0], {"demo"}
        )  # 无 --enable → 全部（显式集合，来自 mock config）
        self.assertFalse(mock_sched.call_args.kwargs["mute"])
        self.assertIsNone(mock_sched.call_args.kwargs["shutdown_delay"])
        self.assertFalse(mock_sched.call_args.kwargs["close_running"])

    def test_schedule_run_close_running_flag(self):
        # --close-running 透传为 close_running=True；不传则默认 True。
        code, mock_sched = self._run(
            ["--schedule-run", "08:00", "--enable", "demo", "--close-running"]
        )
        self.assertEqual(code, 0)
        self.assertTrue(mock_sched.call_args.kwargs["close_running"])

    def test_schedule_run_enable_all_is_explicit_all(self):
        code, mock_sched = self._run(["--schedule-run", "08:00", "--enable", "all"])
        self.assertEqual(code, 0)
        mock_sched.assert_called_once()
        self.assertEqual(mock_sched.call_args.args[0], {"demo"})  # --enable all → 全部

    def test_schedule_run_unknown_enable_exits_one(self):
        with (
            patch.object(
                cli.AppService,
                "load_config",
                return_value={"script_list": [{"display_name": "demo"}]},
            ),
            patch.object(cli.AppService, "schedule_run") as mock_sched,
        ):
            code = _run_main(
                ["--schedule-run", "08:00", "--enable", "ghost"], expect_exit=1
            )
        self.assertEqual(code, 1)
        mock_sched.assert_not_called()
        self.assertIn("未知的脚本标识", _read_cli_file("schedule_run"))


class TestCliCheckConfig(unittest.TestCase):
    """--check-config 出口：校验全部脚本合法性，JSON 结果可断言。"""

    def test_check_config_reports_invalid(self):
        """退出码与 invalid 列表一致：invalid 非空 → 1，空 → 0。"""
        code = _run_main(["--check-config"])  # 不预设退出码，按实际内容断言
        data = _read_cli_json("check_config")
        self.assertEqual(data["status"], "invalid" if data["invalid"] else "ok")
        self.assertEqual(code, 1 if data["invalid"] else 0)
        # invalid 元素结构：{name, message}
        self.assertTrue(all({"name", "message"} <= i.keys() for i in data["invalid"]))

    def test_check_config_json_structure(self):
        """JSON 结果字段完整，可被测试断言。"""
        _run_main(["--check-config"])
        data = _read_cli_json("check_config")
        self.assertIn("status", data)
        self.assertIn("script_count", data)
        self.assertIn("invalid", data)


class TestCliListScripts(unittest.TestCase):
    """--list-scripts 出口：列出脚本名，JSON 含完整列表。"""

    def test_list_scripts_matches_config(self):
        """脚本列表与 config.yml 的 script_list 一致。"""
        code = _run_main(["--list-scripts"], expect_exit=0)
        self.assertEqual(code, 0)
        data = _read_cli_json("list_scripts")
        self.assertEqual(data["scripts"], _known_script_names())


class TestCliGetScript(unittest.TestCase):
    """--get-script 出口：查询单个脚本。"""

    def setUp(self):
        self._names = _known_script_names()

    def test_get_existing_script(self):
        """存在的脚本 → status=ok 且返回的正是所查标识的条目。"""
        name = self._names[0]
        code = _run_main(["--get-script", name], expect_exit=0)
        self.assertEqual(code, 0)
        data = _read_cli_json("get_script")
        self.assertEqual(data["status"], "ok")
        # 按脚本唯一标识比较（exe 用进程名、python/bat 用 display_name），
        # 而非 display_name，避免 external 脚本标识与展示名不一致导致的误判。
        self.assertEqual(get_script_name(data["script"]), name)

    def test_get_missing_script_exits_one(self):
        """不存在的脚本 → status=not_found 且退出码 1。"""
        code = _run_main(["--get-script", "不存在脚本_XYZ"], expect_exit=1)
        self.assertEqual(code, 1)
        data = _read_cli_json("get_script")
        self.assertEqual(data["status"], "not_found")


class TestCliDumpConfig(unittest.TestCase):
    """--dump-config 出口：导出完整 config.yml。"""

    def test_dump_config_matches_source(self):
        """导出内容与 config.yml 一致（display_name 列表）。"""
        code = _run_main(["--dump-config"], expect_exit=0)
        self.assertEqual(code, 0)
        data = _read_cli_json("dump_config")
        # 与 config.yml 的 display_name 列表一致（dump 是原始 config.yml 导出）
        config_path = launcher.get_config_yml_path_under_root()
        source = load_yaml(config_path)
        self.assertEqual(
            [s["display_name"] for s in data["script_list"]],
            [s["display_name"] for s in source.get("script_list", [])],
        )


class TestCliCheckWeekly(unittest.TestCase):
    """--check-weekly 出口：校验 weekly 一致性。"""

    def test_check_weekly_ok(self):
        """weekly 与 config 一致 → status=ok 且退出码 0。"""
        code = _run_main(["--check-weekly"], expect_exit=0)
        self.assertEqual(code, 0)
        data = _read_cli_json("check_weekly")
        self.assertEqual(data["status"], "ok", msg=data)


if __name__ == "__main__":
    unittest.main()
