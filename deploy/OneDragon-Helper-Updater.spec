# -*- mode: python ; coding: utf-8 -*-
"""独立 onefile 更新器：无 Qt，不依赖正在替换的 _internal。"""
import os
import sys

base_bin = os.path.join(sys.base_prefix, 'Library', 'bin')
extra_dlls = [
    (os.path.join(base_bin, name), '.')
    for name in ('ffi-8.dll', 'liblzma.dll', 'libbz2.dll', 'libexpat.dll')
    if os.path.isfile(os.path.join(base_bin, name))
]
a = Analysis(
    ['../src/update/__main__.py'],
    pathex=['..'], binaries=extra_dlls, datas=[], hiddenimports=[],
    runtime_hooks=[os.path.join(SPECPATH, 'runtime_hook_utf8.py')],
    excludes=['PySide6', 'numpy', 'cv2', 'tkinter'],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='OneDragon-Helper-Updater',
    console=False, uac_admin=True, upx=True,
)
