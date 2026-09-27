# -*- mode: python ; coding: utf-8 -*-
"""Rust GUI 的独立 Python 后端；onedir，不携带 Qt 或外部脚本环境。"""

import _hashlib
import _ssl
import logging
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.depend.bindepend import get_imports

assert sys.platform == "win32", "此发布配置仅支持 Windows"
root = Path(SPECPATH).parent
base_bin = Path(sys.base_prefix) / "Library/bin"
binaries = [
    (str(base_bin / name), ".")
    for name in ("ffi-8.dll", "liblzma.dll", "libbz2.dll", "libexpat.dll")
    if (base_bin / name).is_file()
]
# 按扩展的真实导入表收集 DLL；部分 Python 构建已静态链接 OpenSSL。
ssl_dir = Path(_ssl.__file__).resolve().parent
ssl_names = {
    name
    for module in (_ssl, _hashlib)
    for name, _resolved in get_imports(module.__file__)
    if name.lower().startswith(("libssl", "libcrypto", "ssleay", "libeay"))
}
logging.getLogger(__name__).info("OpenSSL DLL imports: %s", sorted(ssl_names))
for name in sorted(ssl_names):
    candidates = [
        folder / name
        for folder in (ssl_dir, ssl_dir.parent, ssl_dir.parent / "Library/bin")
    ]
    found = next((path for path in candidates if path.is_file()), None)
    assert found is not None, f"构建环境缺少 OpenSSL: {name}"
    binaries.append((str(found), "."))

a = Analysis(
    [str(root / "src/headless_entry.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=[],
    hiddenimports=collect_submodules("keyring"),
    runtime_hooks=[str(root / "deploy/runtime_hook_utf8.py")],
    excludes=["PySide6", "shiboken6", "src.gui", "src.launcher", "tkinter"],
)
assert not any(
    name.startswith(("PySide6", "shiboken6", "src.gui", "src.launcher"))
    for name, *_rest in a.pure
), "CLI 意外包含 GUI 模块"
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OneDragon-Helper-CLI",
    console=True,
    upx=False,
    icon=[str(root / "assets/ds.ico")],
)
coll = COLLECT(exe, a.binaries, a.datas, name="OneDragon-Helper", upx=False)
