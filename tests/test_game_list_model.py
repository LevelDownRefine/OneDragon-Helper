"""测试 GameListModel（QML ListView 的 QAbstractListModel）。"""

import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.gui.game_list_model import GameListModel

_app = QApplication.instance() or QApplication([])


def _games():
    return [
        {"display_name": "甲", "script_name": "a", "char": "甲", "color": "#111111"},
        {"display_name": "乙", "script_name": "b", "char": "乙", "color": "#222222"},
        {"display_name": "丙", "script_name": "c", "char": "丙", "color": "#333333"},
    ]


class TestGameListModel(unittest.TestCase):
    def test_rowcount_and_data(self):
        m = GameListModel(_games())
        self.assertEqual(m.rowCount(), 3)
        idx = m.index(0, 0)
        self.assertEqual(m.data(idx, m.DisplayNameRole), "甲")
        self.assertEqual(m.data(idx, m.CharRole), "甲")
        self.assertEqual(m.data(idx, m.ColorRole), "#111111")
        self.assertIsNone(m.data(m.index(9, 0), m.DisplayNameRole))

    def test_rolenames_are_bytes(self):
        m = GameListModel(_games())
        roles = m.roleNames()
        self.assertEqual(roles[m.DisplayNameRole], b"displayName")
        self.assertEqual(roles[m.CharRole], b"char")
        self.assertEqual(roles[m.ScriptNameRole], b"scriptName")

    def test_script_name_role(self):
        m = GameListModel(_games())
        self.assertEqual(m.data(m.index(0, 0), m.ScriptNameRole), "a")
        self.assertEqual(m.data(m.index(2, 0), m.ScriptNameRole), "c")

    def test_set_games_resets(self):
        m = GameListModel(_games())
        spy = MagicMock()
        m.modelReset.connect(spy)
        m.set_games([_games()[0]])
        spy.assert_called_once()
        self.assertEqual(m.rowCount(), 1)
        self.assertEqual(m.data(m.index(0, 0), m.DisplayNameRole), "甲")

    def test_move_reorders_and_emits_rows_moved(self):
        m = GameListModel(_games())
        spy = MagicMock()
        m.rowsMoved.connect(spy)
        m.move(0, 2)
        spy.assert_called_once()
        self.assertEqual(
            [m.data(m.index(r, 0), m.DisplayNameRole) for r in range(3)],
            ["乙", "丙", "甲"],
        )
        # 同位置 move 不触发
        spy.reset_mock()
        m.move(1, 1)
        spy.assert_not_called()

    def test_move_forward_and_backward(self):
        m = GameListModel(_games())
        m.move(0, 1)  # 甲 -> 第 1
        self.assertEqual(
            [m.data(m.index(r, 0), m.DisplayNameRole) for r in range(3)],
            ["乙", "甲", "丙"],
        )
        m.move(2, 0)  # 丙 -> 第 0
        self.assertEqual(
            [m.data(m.index(r, 0), m.DisplayNameRole) for r in range(3)],
            ["丙", "乙", "甲"],
        )

    def test_append_and_pop(self):
        m = GameListModel(_games())
        m.append(
            {"display_name": "丁", "script_name": "d", "char": "丁", "color": "#444444"}
        )
        self.assertEqual(m.rowCount(), 4)
        self.assertEqual(m.data(m.index(3, 0), m.DisplayNameRole), "丁")
        popped = m.pop(0)
        self.assertEqual(popped["display_name"], "甲")
        self.assertEqual(m.rowCount(), 3)
        self.assertEqual(m.data(m.index(0, 0), m.DisplayNameRole), "乙")


if __name__ == "__main__":
    unittest.main()
