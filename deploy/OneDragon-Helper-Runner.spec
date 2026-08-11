# -*- mode: python ; coding: utf-8 -*-
"""OneDragon-Helper Runner（脚本运行器）打包配置。

入口: src/runner/launcher.py (控制台应用，UAC 提权)
模式: onefile，自包含单 exe，由 GUI 主程序同目录调用。
构建: uv run pyinstaller --noconfirm --clean deploy/OneDragon-Helper-Runner.spec

注意: script_chainer 包位于 src/runner/ 下（非标准 src.runner.script_chainer），
      需通过 pathex 将 src/runner/ 加入模块搜索路径。
"""

from PyInstaller.utils.hooks import collect_submodules
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

# --- 隐式导入 ---
hiddenimports = []
hiddenimports += collect_submodules('pynput')
# scripts/mute.py、unmute.py 在运行时才 import pycaw，静态分析抓不到。
# pycaw 仅依赖 comtypes 核心与 comtypes.automation（其源码里为静态 import），
# 由 collect_submodules('pycaw') 顺带收集，无需把 comtypes.test 等一并打包。
hiddenimports += collect_submodules('pycaw')

# --- 可安全排除的模块 ---
# pynput 跨平台后端: Windows 仅用 win32，其余后端永不加载。
# 其余为标准库未使用模块。
# 注意: 不在此排除 numpy —— Runner 在运行时加载用户脚本(scripts/)，
#       若脚本 import numpy 需由本包提供。
excludes = [
    'pynput.keyboard._darwin', 'pynput.keyboard._xorg',
    'pynput.mouse._darwin', 'pynput.mouse._xorg',
    'pynput._util.darwin', 'pynput._util.xorg', 'pynput._util.xorg_keys',
    'pynput.keyboard._uinput', 'pynput.mouse._uinput',
    'tkinter', 'unittest', 'doctest', 'pydoc', 'lib2to3',
    'curses', 'ensurepip', 'distutils', 'venv', 'idlelib',
    'turtledemo', 'test', 'pty', 'tty', 'wsgiref',
]


a = Analysis(
    ['../src/runner/launcher.py'],
    pathex=['../src/runner'],
    binaries=_extra_dlls,
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    icon=['../assets/ds.ico'],
)
