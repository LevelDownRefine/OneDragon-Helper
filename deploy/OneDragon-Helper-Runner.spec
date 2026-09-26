# -*- mode: python ; coding: utf-8 -*-
"""OneDragon-Helper Runner（脚本运行器）打包配置。

入口: src/runner/launcher.py (控制台应用，UAC 提权)
模式: onefile，自包含单 exe，由 GUI 主程序同目录调用。
构建: uv run pyinstaller --noconfirm --clean deploy/OneDragon-Helper-Runner.spec

注意: script_chainer 包位于 src/runner/ 下（非标准 src.runner.script_chainer），
      需通过 pathex 将 src/runner/ 加入模块搜索路径。
"""

import os
import sys

# --- conda base DLL 补全 ---
# venv 创建自 miniforge3，_ctypes/_lzma/_bz2/pyexpat 等依赖 base 的 Library/bin 下的 DLL，
# PyInstaller 静态分析无法自动发现，需手动加入。
_base_bin = os.path.join(sys.base_prefix, 'Library', 'bin')
_extra_dlls = []
for _dll in ('ffi-8.dll', 'liblzma.dll', 'libbz2.dll', 'libexpat.dll'):
    _p = os.path.join(_base_bin, _dll)
    if os.path.isfile(_p):
        _extra_dlls.append((_p, '.'))

# --- 可安全排除的模块 ---
# Runner 只收集自身依赖；用户 .py 的额外依赖由外部 Python 环境提供。
excludes = [
    'tkinter', 'unittest', 'doctest', 'pydoc', 'lib2to3',
    'curses', 'ensurepip', 'distutils', 'venv', 'idlelib',
    'turtledemo', 'test', 'pty', 'tty', 'wsgiref',
]


a = Analysis(
    ['../src/runner/launcher.py'],
    pathex=['../src/runner'],
    binaries=_extra_dlls,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    # 冻结后运行在英文 locale(cp1252) 的 Windows 上，Runner 经 colorama 往 stdout 打印中文会
    # 抛 'charmap' codec can't encode characters 使进程崩溃（GitHub Windows runner 即此场景）。
    # runtime_hook_utf8.py 在 main 导入 colorama 之前把标准流强制为 UTF-8，是此崩溃的唯一修复点
    # （Runner 入口是 src/runner/launcher.py，并不包含 src/launcher 的代码）。
    # 用 SPECPATH 定位 hook，避免依赖 build.bat 的 CWD。
    runtime_hooks=[os.path.join(SPECPATH, 'runtime_hook_utf8.py')],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OneDragon-Helper-Runner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
)
