"""Qt 测试的异步 CLI 替身；业务数据仅由测试端响应提供。"""

import os
from copy import deepcopy
from pathlib import Path
from weakref import WeakSet

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")

from PySide6.QtCore import QObject, QTimer, Signal

from gui.cli_client import CliFailure

_app = None
_clients = WeakSet()
_SCRIPTS = [
    {
        "display_name": "鸣潮",
        "script_path": "scripts/ok-ww/ok-ww.exe",
        "script_type": "external",
    },
    {
        "display_name": "测试脚本",
        "script_path": "scripts/t.py",
        "script_type": "python",
    },
]


def get_app():
    """按需创建并持有离屏应用。"""
    global _app
    from PySide6.QtWidgets import QApplication

    _app = QApplication.instance() or QApplication([])
    return _app


def drain_events():
    """交付排队的 CLI 响应；夹具编程错误在 Qt 回调外报告。"""
    app = get_app()
    for _ in range(20):
        app.processEvents()
    for client in list(_clients):
        if client.errors:
            raise client.errors.pop(0)


def script_name(script):
    assert "display_name" in script and "script_path" in script
    if "script_name" in script:
        return script["script_name"]
    path = Path(script["script_path"])
    return path.stem if path.suffix.lower() == ".exe" else script["display_name"]


def snapshot(scripts):
    return {
        "default_icon_path": "",
        "scripts": [
            {
                "script_name": script_name(script),
                "display_name": script["display_name"],
                "script_path": script["script_path"],
                "adapted": False,
                "icon_path": None,
                "script_data": deepcopy(script),
            }
            for script in scripts
        ],
    }


def script_view(name, *, adapted=False, dailies=None, weeklies=None):
    return {
        "script_name": name,
        "script": {
            "script_name": name,
            "display_name": name,
            "script_path": "",
            "adapted": adapted,
            "icon_path": None,
        },
        "dailies": [] if dailies is None else deepcopy(dailies),
        "weeklies": [] if weeklies is None else deepcopy(weeklies),
    }


def wallpaper_view(name, *, mode="gradient", source="", token=None, cache=None):
    return {
        "script_name": name,
        "display_name": name,
        "mode": mode,
        "source": source,
        "token": token,
        "cache": cache,
        "custom_path": None,
    }


def settings_view():
    from dataclasses import asdict

    from src.service.schedule import RunOptions, StartupOptions

    return {
        "startup": asdict(StartupOptions()),
        "daily_enabled": False,
        "run_options": asdict(RunOptions()),
        "shutdown_supported": True,
    }


class FakeCliClient(QObject):
    """以真实 CliSession 接收请求，下一轮事件循环交付测试端响应。"""

    succeeded = Signal(int, object)
    failed = Signal(int, object)
    closed = Signal()

    def __init__(self, *, responses=None, scripts=None, handler=None):
        super().__init__()
        self.scripts = deepcopy(_SCRIPTS if scripts is None else scripts)
        self.requests = []
        self.errors = []
        self.usable = True
        self.running = False
        self._protected = False
        self._handler = handler
        self.responses = {
            "app.snapshot": lambda params: snapshot(self.scripts),
            "script.view": lambda params: script_view(params["script_name"]),
            "wallpaper.current": lambda params: wallpaper_view(params["script_name"]),
            "wallpaper.view": lambda params: wallpaper_view(params["script_name"]),
            "script.icon_path": lambda params: {
                "script_name": params["script_name"],
                "path": None,
            },
            "startup.view": lambda params: settings_view(),
            "settings.view": lambda params: settings_view(),
            "script.target": {"kind": "unavailable", "reason": "未配置资源"},
            "script.launch_target": {"kind": "unavailable", "reason": "未配置启动目标"},
            "script.add": self._add,
            "script.remove": self._remove,
            "script.reorder": self._reorder,
            "daily.select": None,
            "daily.enable": None,
            "weekly.select": None,
            "weekly.start": None,
            "wallpaper.set": None,
            "wallpaper.cache": False,
            "startup.save": None,
            "settings.save": None,
        }
        if responses is not None:
            self.responses.update(responses)
        _clients.add(self)

    def _add(self, params):
        assert "file_path" in params
        path = Path(params["file_path"])
        script = {
            "display_name": path.stem,
            "script_path": str(path),
            "script_type": "external",
        }
        self.scripts.append(script)
        return {
            "script_name": script_name(script),
            "display_name": script["display_name"],
        }

    def _remove(self, params):
        assert "script_name" in params
        self.scripts = [
            script
            for script in self.scripts
            if script_name(script) != params["script_name"]
        ]

    def _reorder(self, params):
        assert "script_names" in params
        rows = {script_name(script): script for script in self.scripts}
        assert all(name in rows for name in params["script_names"])
        self.scripts = [rows[name] for name in params["script_names"]]

    def request(self, method, params):
        if not self.usable:
            raise RuntimeError("测试 CLI 已关闭")
        values = {} if params is None else deepcopy(params)
        self.requests.append((method, values))
        request_id = len(self.requests)

        def deliver():
            if not self.usable:
                return
            try:
                if self._handler is not None:
                    result = self._handler(method, values)
                else:
                    assert method in self.responses, f"测试未提供 CLI 响应: {method}"
                    response = self.responses[method]
                    result = (
                        response(values) if callable(response) else deepcopy(response)
                    )
            except (ValueError, OSError) as exc:
                self.failed.emit(request_id, CliFailure(-32002, str(exc)))
                return
            except (AssertionError, KeyError, TypeError) as exc:
                self.errors.append(exc)
                self.failed.emit(request_id, CliFailure("fixture_error", str(exc)))
                return
            if isinstance(result, CliFailure):
                self.failed.emit(request_id, result)
            else:
                self.succeeded.emit(request_id, result)

        QTimer.singleShot(0, deliver)
        return request_id

    def protect(self):
        self._protected = True

    def unprotect(self):
        self._protected = False

    def close(self):
        self.usable = False
        self.closed.emit()


def make_bridge(*, client=None, scripts=None, responses=None):
    """只通过 CLI 响应构造桥接对象，不导入或构造 AppService。"""
    get_app()
    from gui.main_window import QmlBridge

    if client is None:
        client = FakeCliClient(scripts=scripts, responses=responses)
    bridge = QmlBridge(cli_client=client)
    bridge.test_client = client
    drain_events()
    return bridge
