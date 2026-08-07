"""测试 ChainService 的 UI 状态持久化（gui_state.json 读写，原 src/service/state.py）。"""

import json
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

from src.service.chain_service import ChainService


class TestLoadUiState(unittest.TestCase):
    """测试 ChainService.load_ui_state"""

    def test_returns_empty_when_file_not_exists(self):
        """文件不存在时返回空 dict"""
        with patch("src.service.chain_service.os.path.exists", return_value=False):
            result = ChainService().load_ui_state()
        self.assertEqual(result, {})

    def test_loads_valid_json(self):
        """正常 JSON 文件正确读取"""
        data = {"鸣潮": {"dungeon": "朔雷之鳞", "sequence": 2}}
        with (
            patch("src.service.chain_service.os.path.exists", return_value=True),
            patch("builtins.open", mock_open_with_data(data)),
        ):
            result = ChainService().load_ui_state()
        self.assertEqual(result, data)


class TestSaveUiState(unittest.TestCase):
    """测试 ChainService.save_ui_state"""

    def test_writes_json_file(self):
        """正常写入 JSON"""
        captured = {}

        def fake_open(file, mode, encoding=None):
            buf = StringIO()
            captured["buf"] = buf
            captured["mode"] = mode
            m = MagicMock()
            m.__enter__ = MagicMock(return_value=buf)
            m.__exit__ = MagicMock(return_value=False)
            return m

        ui_state = {"鸣潮": {"dungeon": "A", "sequence": 1}}
        with patch("builtins.open", side_effect=fake_open):
            ChainService().save_ui_state(ui_state)

        written = json.loads(captured["buf"].getvalue())
        self.assertEqual(written, ui_state)
        self.assertEqual(captured["mode"], "w")


# ---- helpers ----


def mock_open_with_data(data):
    """返回一个 mock open，读取时返回 JSON 序列化的 data"""
    raw = json.dumps(data, ensure_ascii=False)

    def fake_open(file, mode="r", encoding=None):
        buf = StringIO(raw)
        m = MagicMock()
        m.__enter__ = MagicMock(return_value=buf)
        m.__exit__ = MagicMock(return_value=False)
        return m

    return fake_open


if __name__ == "__main__":
    unittest.main()
