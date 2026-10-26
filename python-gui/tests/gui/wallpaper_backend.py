"""测试端壁纸 RPC 服务器；真实后端 I/O 仅落在用例临时目录。"""

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.service.app_service import AppService


class WallpaperBackend:
    def __init__(self, directory):
        self.root = Path(directory)
        self.service = AppService()
        self._stack = ExitStack()

    def __enter__(self):
        self._stack.enter_context(
            patch(
                "src.utils.utils_wallpaper.get_wallpaper_json_path_under_root",
                return_value=str(self.root / "wallpaper.json"),
            )
        )
        self._stack.enter_context(
            patch(
                "src.utils.utils_wallpaper.get_script",
                return_value={"display_name": "测试"},
            )
        )
        self._stack.enter_context(
            patch("src.utils.utils_wallpaper.get_background_rel_path", return_value="")
        )
        return self

    def __exit__(self, *args):
        return self._stack.__exit__(*args)

    def set(self, name, path):
        self.service.set_wallpaper(name, str(path))

    def view(self, name):
        return self.service.wallpaper_view(name)

    def handle(self, method, params):
        methods = {
            "wallpaper.current": self.service.wallpaper_view,
            "wallpaper.view": self.service.wallpaper_view,
            "wallpaper.set": self.service.set_wallpaper,
            "wallpaper.cache": self.service.save_wallpaper_cache,
        }
        assert method in methods
        return methods[method](**params)

    def responses(self):
        return {
            method: lambda params, method=method: self.handle(method, params)
            for method in (
                "wallpaper.current",
                "wallpaper.view",
                "wallpaper.set",
                "wallpaper.cache",
            )
        }
