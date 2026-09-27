"""从原 GUI 图标源生成 Rust 静态图标；仅开发时需要 Qt。"""

import os
from pathlib import Path


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from src.gui.icons import UiIconProvider, _default_icon, _render_icon

    app = QApplication.instance() or QApplication([])
    provider = UiIconProvider()
    output = Path(__file__).resolve().parents[1] / "rust-gui/assets/icons"
    output.mkdir(parents=True, exist_ok=True)
    names = (
        "home",
        "game",
        "folder",
        "bili",
        "github",
        "wallpaper",
        "settings",
        "min",
        "close",
        "log",
        "configfile",
        "play",
        "play_all",
        "chevron_down",
        "grid",
    )
    for name in names:
        if not provider._render(name).save(str(output / f"{name}.png")):
            raise OSError(f"无法保存图标：{name}")
    if not _render_icon(_default_icon()).save(str(output / "script.png")):
        raise OSError("无法保存默认脚本图标")
    assert app is not None


if __name__ == "__main__":
    main()
