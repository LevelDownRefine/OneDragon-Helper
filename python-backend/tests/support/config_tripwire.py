"""测试进程的生成配置绊线：源码测试读取真实生成配置时立即失败。

仓库约定（见 python-backend/tests/__init__.py 说明）：源码测试对生成物
（config.yml / schedule.yml / weekly.yml 等，运行时由模板生成，不进版本库）
零依赖——各读盘测试自建临时文件或 mock 路径。此类违规在本地（生成配置存在）
静默通过、只在 CI 挂，故在测试进程装审计钩子让违规当场失败。

经 sys.addaudithook 拦截 open 事件，覆盖任意 import 绑定形式的读盘。
子进程（headless e2e 等）不加载测试包，不受绊线影响；经 tests.gui.helpers
起的 QML 子进程会随包导入装上绊线，其配置 I/O 由 make_bridge 统一隔离。
豁免名单见 _EXEMPT_MARKERS。
"""

import os
import sys
from pathlib import Path

_installed = False

# .gitignore 中「运行时生成、不进版本库」的 config/ 顶层文件。
_GUARDED_NAMES = {
    "config.yml",
    "schedule.yml",
    "weekly.yml",
    "notify_mail.yml",
    "wallpaper.json",
}
_GUARDED_TOP_DIRS = {"script_chain"}


# 调用栈文件名包含下列标记时豁免：本地安全测试按设计读取真实 config.yml；
# test_cli_client 把既有 yml 拷贝进临时项目做隔离装配（行为不依赖其内容）。
_EXEMPT_MARKERS = ("test_local_config_paths", "test_cli_client")


def _exempt_by_stack() -> bool:
    frame = sys._getframe()
    while frame is not None:
        filename = frame.f_code.co_filename
        if any(marker in filename for marker in _EXEMPT_MARKERS):
            return True
        frame = frame.f_back
    return False


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    config_dir = Path(__file__).resolve().parents[3] / "config"
    config_prefix = str(config_dir).replace("\\", "/") + "/"

    def _hook(event, args):
        if event != "open":
            return
        raw = args[0]
        if not isinstance(raw, str):
            try:
                raw = os.fspath(raw)
            except TypeError:
                return
        norm = raw.replace("\\", "/") if isinstance(raw, str) else ""
        if not norm.startswith(config_prefix):
            return
        rest = norm[len(config_prefix) :]
        top = rest.split("/", 1)[0]
        if rest not in _GUARDED_NAMES and top not in _GUARDED_TOP_DIRS:
            return
        if _exempt_by_stack():
            return
        raise AssertionError(
            f"测试读取了真实生成配置: {raw}\n"
            "源码测试对生成配置零依赖（见 python-backend/tests/__init__.py 说明）："
            "请在测试内自建临时文件或 mock 路径；"
            "如属本地安全测试 test_local_config_paths.py 的预期读取则无需处理。"
        )

    sys.addaudithook(_hook)
