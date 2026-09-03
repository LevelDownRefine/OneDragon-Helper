# -*- mode: python -*-
"""冻结 exe 启动早期强制 UTF-8 标准流（PyInstaller 运行时 hook）。

GUI exe 与 Runner exe 共用。冻结后运行在英文 locale(cp1252) 的 Windows 上时，CLI 出口
（_emit_cli/_emit_json 的 print、colorama 等）往 stdout 打印中文会抛
``'charmap' codec can't encode characters`` 使进程崩溃（GitHub Windows runner 即此场景，
实测 GUI exe 出现 1 fail + 3 timeout）。此 hook 在 main 导入任何会打印中文的模块之前，
把 ``sys.stdout``/``sys.stderr`` 强制为 UTF-8（errors=replace）。

注意：build.bat 以 deploy/ 为 CWD 调 pyinstaller，但两个 spec 都用 SPECPATH 拼绝对路径引用本文件。
"""

import contextlib
import sys

for _stream in (sys.stdout, sys.stderr):
    if _stream is None:
        continue
    with contextlib.suppress(AttributeError, ValueError, OSError):
        _stream.reconfigure(encoding="utf-8", errors="replace")
