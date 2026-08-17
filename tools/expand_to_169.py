"""将图片扩充（留边）为 16:9 比例，保持原图完整、居中放置。

用法:
    python tools/expand_to_169.py assets/ds.jpg
    python tools/expand_to_169.py assets/ds.jpg -o out.jpg --bg white
"""

from __future__ import annotations

import argparse

from PIL import Image

TARGET_RATIO = 16 / 9


def expand_to_169(src_path: str, dst_path: str, bg: str) -> tuple[int, int]:
    """把 src_path 扩充为 16:9 并保存到 dst_path, 返回输出尺寸。

    Args:
        src_path: 源图片路径。
        dst_path: 输出图片路径。
        bg: 留边背景色, 支持颜色名或 "r,g,b"。

    Returns:
        输出图片的 (width, height)。
    """
    bg_rgb = _parse_color(bg)
    img = Image.open(src_path).convert("RGB")
    src_w, src_h = img.size

    if src_w / src_h >= TARGET_RATIO:
        out_w = src_w
        out_h = round(src_w / TARGET_RATIO)
    else:
        out_h = src_h
        out_w = round(src_h * TARGET_RATIO)

    canvas = Image.new("RGB", (out_w, out_h), bg_rgb)
    offset = ((out_w - src_w) // 2, (out_h - src_h) // 2)
    canvas.paste(img, offset)
    canvas.save(dst_path)
    return canvas.size


def _parse_color(bg: str) -> tuple[int, int, int]:
    """解析背景色: 支持 "r,g,b" 或 PIL 颜色名。"""
    parts = bg.split(",")
    assert len(parts) in (1, 3), f"无效背景色: {bg}"
    if len(parts) == 3:
        return tuple(int(p.strip()) for p in parts)  # type: ignore[return-value]
    return bg  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser(description="将图片扩充为 16:9 (留边居中)")
    parser.add_argument("src", help="源图片路径")
    parser.add_argument(
        "-o", "--output", default=None, help="输出路径 (默认 <源名>_16x9.jpg)"
    )
    parser.add_argument(
        "--bg",
        default="white",
        help='留边背景色, 如 black/white/"255,255,255" (默认 white)',
    )
    args = parser.parse_args()

    dst = args.output or _default_output(args.src)
    size = expand_to_169(args.src, dst, args.bg)
    print(f"已保存: {dst} ({size[0]}x{size[1]})")


def _default_output(src: str) -> str:
    dot = src.rfind(".")
    if dot == -1:
        return src + "_16x9.jpg"
    return src[:dot] + "_16x9" + src[dot:]


if __name__ == "__main__":
    main()
