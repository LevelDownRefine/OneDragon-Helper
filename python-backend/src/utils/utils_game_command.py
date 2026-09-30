"""游戏启动命令解析与旧配置转换。"""

import re
import subprocess


def parse_game_command(command: str) -> tuple[str, str]:
    """拆出可执行文件与原始参数；含空格的路径须用双引号。"""
    if not isinstance(command, str) or "\0" in command:
        raise ValueError("游戏启动命令无效")
    if not command.strip():
        return "", ""
    match = re.fullmatch(r'\s*(?:"([^"\r\n]+)"|([^\s"]+))(?:\s+(.*))?\s*', command)
    if match is None:
        raise ValueError("游戏启动命令格式无效，含空格的路径须用双引号")
    return match[1] or match[2], (match[3] or "").strip()


def game_command_of(script: dict) -> str:
    """新字段优先；旧游戏路径和参数仅在未迁移时转换。"""
    if "game_command" in script:
        return script["game_command"]
    path = ""
    arguments = ""
    if "game_path" in script:
        path = script["game_path"]
    if "game_arguments" in script:
        arguments = script["game_arguments"]
    if not path:
        return ""
    return subprocess.list2cmdline([path]) + (" " + arguments if arguments else "")
