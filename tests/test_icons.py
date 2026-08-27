import os
import tempfile
import unittest
from unittest.mock import patch

from src.gui.icons import _EXE_ICON_CACHE, _exe_icon


class _StubIcon:
    """替代真实 QIcon，仅满足 _exe_icon 的非空判定，避免无头环境依赖平台图标提供器。"""

    def isNull(self) -> bool:  # noqa: N802  # 对齐 QIcon.isNull 命名
        return False


class TestExeIconCache(unittest.TestCase):
    """_exe_icon 仅缓存成功结果，缺失/失败不缓存，以容忍 exe 后续就位。

    旧实现用 @lru_cache 会把 ``path → None`` 永久缓存：脚本创建时 exe 尚未
    就位、首次取不到，之后 exe 出现仍取不到，需重启进程才刷新。
    """

    def setUp(self):
        _EXE_ICON_CACHE.clear()

    def test_missing_returns_none_and_not_cached(self):
        """文件缺失时返回 None，且不写入缓存（否则会永久记住失败态）。"""
        missing = os.path.join(tempfile.mkdtemp(), "nope.exe")
        self.assertIsNone(_exe_icon(missing))
        self.assertNotIn(missing, _EXE_ICON_CACHE)

    def test_existing_file_returns_icon_and_cached(self):
        """存在的文件应取到图标并写入缓存。"""
        fd, path = tempfile.mkstemp(suffix=".exe")
        os.close(fd)
        try:
            with patch("src.gui.icons._ICON_PROVIDER") as mock_provider:
                mock_provider.icon.return_value = _StubIcon()
                icon = _exe_icon(path)
            self.assertIsNotNone(icon)
            self.assertIn(path, _EXE_ICON_CACHE)
        finally:
            os.remove(path)

    def test_missing_then_file_appears_is_refetched(self):
        """缺失后 exe 才就位：再次请求应能取到（不因首次缺失而缓存失败）。"""
        path = os.path.join(tempfile.mkdtemp(), "later.exe")
        self.assertIsNone(_exe_icon(path))
        self.assertNotIn(path, _EXE_ICON_CACHE)
        with open(path, "w") as f:
            f.write("")
        try:
            with patch("src.gui.icons._ICON_PROVIDER") as mock_provider:
                mock_provider.icon.return_value = _StubIcon()
                self.assertIsNotNone(_exe_icon(path))
        finally:
            os.remove(path)
