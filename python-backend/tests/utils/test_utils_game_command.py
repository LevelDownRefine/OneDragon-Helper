"""完整游戏启动命令、旧配置转换及字段优先级。"""

import unittest

from src.utils.utils_game_command import game_command_of, parse_game_command


class GameCommandTests(unittest.TestCase):
    def test_parse_preserves_windows_path_and_raw_arguments(self):
        for command, expected in (
            (
                '"D:/Game Folder/game.exe" --profile "中文 空格" --literal "a&b"',
                ("D:/Game Folder/game.exe", '--profile "中文 空格" --literal "a&b"'),
            ),
            (r"C:\Games\game.exe -w", (r"C:\Games\game.exe", "-w")),
            (' "D:/游戏/game.exe" ', ("D:/游戏/game.exe", "")),
            ("", ("", "")),
        ):
            with self.subTest(command=command):
                self.assertEqual(parse_game_command(command), expected)

    def test_malformed_commands_are_recoverable(self):
        for command in ('"unterminated', '"game.exe"tail', "game.exe\0", None):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_game_command(command)

    def test_legacy_conversion_and_explicit_empty_command(self):
        legacy = {
            "game_path": "D:/Game Folder/game.exe",
            "game_arguments": '--profile "中文 空格"',
        }
        command = game_command_of(legacy)
        self.assertEqual(
            parse_game_command(command), (legacy["game_path"], legacy["game_arguments"])
        )
        self.assertEqual(game_command_of({**legacy, "game_command": ""}), "")
