# -*- coding: utf-8 -*-
"""生成 icon.ico（蓝底白书），供 PyInstaller 打包时当 exe 图标。

运行：python make_icon.py
依赖：pillow
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).with_name("icon.ico")


def build(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=int(size * 0.22),
                        fill=(37, 99, 235, 255))
    m = size // 8
    d.rectangle([m + 2, m + 3, size // 2 - 2, size - m - 3], fill=(255, 255, 255, 240))
    d.rectangle([size // 2 + 1, m + 3, size - m - 3, size - m - 3], fill=(226, 238, 255, 240))
    d.rectangle([size // 2 - 2, m + 2, size // 2 + 1, size - m - 2], fill=(30, 64, 175, 255))
    return img


def main() -> None:
    build(256).save(OUT, format="ICO",
                    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("已生成图标：%s" % OUT)


if __name__ == "__main__":
    main()
