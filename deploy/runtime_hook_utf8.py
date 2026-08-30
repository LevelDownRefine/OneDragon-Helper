# -*- mode: python ; coding: utf-8 -*-
"""Runner exe 启动早期强制 UTF-8 标准流（PyInstaller 运行时 hook）。

冻结后运行在英文 locale(cp1252) 的 Windows 上时，
``script_chainer/win_exe/script_runner.py`` 经 colorama 往 stdout 打印中文会抛
``'charmap' codec can't encode characters`` 使进程崩溃（GitHub Windows runner 即此场景）。
此 hook 在 main 导入 colorama 之前把 ``sys.stdout``/``sys.stderr`` 强制为 UTF-8，
与 ``src/launcher.py`` 的 ``_force_utf8_stdio`` 同源修复。
"""

import sys

for _stream in (sys.stdout, sys.stderr):
    if _stream is None:
        continue
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
