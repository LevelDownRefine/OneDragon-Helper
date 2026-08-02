# -*- mode: python ; coding: utf-8 -*-
"""OneDragon-Helper GUI 主程序打包配置。

入口: src/launcher.py (PySide6 窗口应用)
模式: onedir (COLLECT)，config/assets 放在 exe 同级目录，可写可持久化。
构建: uv run pyinstaller --noconfirm --clean deploy/OneDragon-Helper.spec
"""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files
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

# --- 隐式导入：PySide6 + Fluent Widgets + 其他动态加载的包 ---
hiddenimports = [
    '_cffi_backend',
]
hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('pynput')

# --- 数据文件 ---
# qfluentwidgets 的 QSS、图片等资源（由 PyInstaller 放入 _internal/）
datas = collect_data_files('qfluentwidgets')

# config/ 和 assets/ 不打入 _internal/，由 build.bat 后处理拷贝到 exe 同级目录，
# 保证 get_root_dir() 在冻结模式下能正确找到（可写、持久化）。


a = Analysis(
    ['../src/launcher.py'],
    pathex=['..'],
    binaries=_extra_dlls,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OneDragon-Helper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['../assets/Chtholly.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OneDragon-Helper',
)
