"""测试 GUI 卡片点击图标启动脚本(_open_script) 的 python 分支命令构造。

python 脚本的启动命令统一由 ``src.utils_runner.build_script_command(["--script", ...])``
构造（其内部已含 frozen / 非 frozen 判断），``_open_script`` 只负责拿 cmd list 去 spawn。
此测试验证 ``_open_script`` 正确委派给 ``build_script_command``，不重复 frozen 逻辑
（frozen 行为由 ``test_gui_runner.py`` 的 ``TestBuildScriptInvocationFrozen`` 覆盖）。
"""

import unittest
from types import SimpleNamespace
from unittest import mock


class _FakeItem:
    """最小替身：只提供 _open_script 读取的两个属性。"""

    def __init__(self, script_type, script_path):
        self.script_type = script_type
        self.script_path = script_path


def _make_obj(script_path):
    item = _FakeItem("python", script_path)
    from src.gui.widgets import ScriptItem

    return SimpleNamespace(
        script_type=item.script_type,
        script_path=item.script_path,
        _open_script=ScriptItem._open_script.__get__(item),
    )


class TestOpenPythonScriptDelegatesToBuildRunnerInvocation(unittest.TestCase):
    """_open_script 的 python 分支应把命令构造委派给 build_script_command。"""

    def test_delegates_command_tobuild_script_command(self):
        script_path = "D:/scripts/foo.py"
        fake_cmd = ["FAKE_CMD", "--script", script_path]
        obj = _make_obj(script_path)
        with (
            mock.patch(
                "src.gui.widgets.build_script_command",
                return_value=(fake_cmd, "FAKE_CWD", None),
            ) as bsc,
            mock.patch("src.gui.widgets.os.path.isfile", return_value=True),
            mock.patch("src.gui.widgets.subprocess.Popen") as popen,
        ):
            obj._open_script()
        bsc.assert_called_once_with(["--script", script_path])
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0], fake_cmd)
        self.assertEqual(kwargs["cwd"], "FAKE_CWD")
        self.assertIsNone(kwargs["env"])

    def test_missing_file_shows_warning_no_launch(self):
        obj = _make_obj("D:/nope/missing.py")
        with (
            mock.patch("src.gui.widgets.build_script_command") as bsc,
            mock.patch("src.gui.widgets.os.path.isfile", return_value=False),
            mock.patch("src.gui.widgets.subprocess.Popen") as popen,
            mock.patch("src.gui.widgets._styled_msg_box") as msg,
        ):
            obj._open_script()
        bsc.assert_not_called()
        popen.assert_not_called()
        msg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
