# -*- mode: python -*-
"""Runner exe 启动早期强制 UTF-8 标准流（PyInstaller 运行时 hook）。

冻结后运行在英文 locale(cp1252) 的 Windows 上时，Runner 经 colorama 往 stdout 打印中文
会抛 ``'charmap' codec can't encode characters`` 使进程崩溃（GitHub Windows runner 即此场景）。
此 hook 在 main 导入 colorama 之前把 ``sys.stdout``/``sys.stderr`` 强制为 UTF-8（errors=replace），
与 ``src/launcher.py`` 的 ``_force_utf8_stdio`` 同源修复。

注意：build.bat 以 deploy/ 为 CWD 调 pyinstaller，故相对路径不带 deploy/ 前缀。
"""

import contextlib
import sys

for _stream in (sys.stdout, sys.stderr):
    if _stream is None:
        continue
    with contextlib.suppress(AttributeError, ValueError, OSError):
        _stream.reconfigure(encoding="utf-8", errors="replace")
