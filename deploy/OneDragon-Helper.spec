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
hiddenimports = []
hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('pynput')

# --- 数据文件 ---
# qfluentwidgets 的 QSS、图片等资源（由 PyInstaller 放入 _internal/）
datas = collect_data_files('qfluentwidgets')

# --- 可安全排除的模块（实测 GUI 运行时走不到）---
# numpy: 仅 qfluentwidgets.acrylic_label 以 try/except ImportError 懒加载，
#        本 GUI 不使用 AcrylicLabel，缺失时回退 QPixmap，安全排除（省 ~42M）。
# QtQml/QtQuick: GUI 已迁移到 QML（launcher.py 用 QQmlApplicationEngine 加载
#        src/gui/qml/main.qml，game_list.py / icons.py 用 QQuickImageProvider），
#        必须保留，不可排除，否则冻结后启动即 ModuleNotFoundError。
# QtMultimedia: background.qml 用 import QtMultimedia 实现视频壁纸（仅 video 模式加载
#        background.qml），必须保留，不可排除，否则视频壁纸运行时 QML import 失败。
#        代价是打入 FFmpeg 的 av*.dll（约 +30M）。
#        PySide6.QtMultimediaWidgets 未被使用（QML 视频用 QtMultimedia QML 类型而非
#        QVideoWidget），可安全排除。
# pynput 跨平台后端: Windows 仅用 win32，其余后端永不加载。
# 其余为标准库未使用模块。
excludes = [
    'numpy',
    'PySide6.QtMultimediaWidgets',
    'pynput.keyboard._darwin', 'pynput.keyboard._xorg',
    'pynput.mouse._darwin', 'pynput.mouse._xorg',
    'pynput._util.darwin', 'pynput._util.xorg', 'pynput._util.xorg_keys',
    'pynput.keyboard._uinput', 'pynput.mouse._uinput',
    'tkinter', 'unittest', 'doctest', 'pydoc', 'lib2to3',
    'curses', 'ensurepip', 'distutils', 'venv', 'idlelib',
    'turtledemo', 'test', 'pty', 'tty', 'wsgiref',
    # WebEngine（Chromium 内核，~149M）从未被本项目使用，纯属 PyInstaller 默认收集。
    # 排除 Python 模块名 + 下方手动过滤 Qt DLL 双保险。若未来引入 QWebEngineView 需移除此处。
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineQuick',
    'PySide6.QtWebEngineQuickDelegatesQml',
    # 以下为本项目从未使用的 Qt 模块（PyInstaller 默认 collect_submodules 全量收集，
    # 代码不 import，QFluentWidgets 也不依赖）。分批排除，每批需重打包并跑 test_gui_exe 验证。
    # 若未来引入对应功能需移除此处并同步清除下方 a.binaries/a.datas 过滤关键词。
    'PySide6.QtPdf', 'PySide6.QtPdfQuick',
    'PySide6.Qt3DCore', 'PySide6.Qt3DExtras', 'PySide6.Qt3DRender',
    'PySide6.Qt3DAnimation', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic',
    'PySide6.Qt3DQuick', 'PySide6.Qt3DQuickExtras', 'PySide6.Qt3DQuickInput',
    'PySide6.Qt3DQuickRender', 'PySide6.Qt3DQuickScene2D',
    'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
    'PySide6.QtLocation',
    'PySide6.QtQuick3D', 'PySide6.QtQuick3DRuntimeRender',
    'PySide6.QtQuick3DXr', 'PySide6.QtQuick3DParticles', 'PySide6.QtQuick3DUtils',
]

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
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# --- 排除未使用的 Qt 二进制（双保险）---
# PyInstaller 会扫描整个 Qt 安装目录并收集所有 Qt DLL（不依赖 Python import），
# 仅靠上方 excludes 模块名不足以剔除这些从未使用的模块。本项目 GUI（QFluentWidgets +
# QML）用不到以下模块，在此手动过滤 a.binaries / a.datas 中路径含这些关键词的条目。
# 若未来引入对应功能需移除此处并同步清除上方 excludes 模块名。分批排除，每批需重打包
# 并跑 test_gui_exe 验证 GUI 仍可启动。
_UNUSED_QT_KEYWORDS = (
    'WebEngine',                 # Chromium 内核（~149M）
    'Qt6Pdf', 'QtPdf',           # PDF，无引用
    'Qt63D', 'Qt3D',             # 3D 渲染
    'Qt6Quick3D', 'QtQuick3D',   # 3D 渲染 (Quick)
    'Qt6Charts', 'QtCharts',     # 图表
    'Qt6DataVisualization', 'QtDataVisualization',  # 图表
    'Qt6Graphs', 'QtGraphs',     # 图表
    'Qt6Location', 'QtLocation', # 定位
)
for _attr in ('binaries', 'datas'):
    _seq = getattr(a, _attr)
    _filtered = [x for x in _seq if not any(k in x[0] for k in _UNUSED_QT_KEYWORDS)]
    setattr(a, _attr, _filtered)

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
    icon=['../assets/ds.ico'],
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
