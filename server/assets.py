from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageOps

BUILTIN_ICON_NAMES = ["meeting", "class", "office", "lunch", "away", "phone", "travel"]


def list_builtin_icons(icons_dir: Path) -> list[str]:
    names = set(BUILTIN_ICON_NAMES)
    if icons_dir.exists():
        for path in icons_dir.glob("*.png"):
            names.add(path.stem)
    return sorted(names)


def _draw_builtin(name: str, size: int = 128) -> Image.Image:
    img = Image.new("L", (size, size), 255)
    d = ImageDraw.Draw(img)
    c = 0
    if name == "meeting":
        d.rectangle((8, 16, size - 8, size - 32), outline=c, width=6)
        d.line((size * 0.2, size * 0.78, size * 0.8, size * 0.78), fill=c, width=8)
        d.ellipse((24, 32, 50, 58), outline=c, width=5)
        d.ellipse((size - 50, 32, size - 24, 58), outline=c, width=5)
    elif name == "class":
        d.rectangle((12, 18, size - 12, size - 38), outline=c, width=6)
        d.line((24, size - 26, size - 24, size - 26), fill=c, width=8)
        d.polygon([(size / 2, 38), (size / 2 - 18, 56), (size / 2 + 18, 56)], outline=c)
    elif name == "office":
        d.rectangle((18, 24, size - 18, size - 20), outline=c, width=6)
        d.rectangle((size / 2 - 14, size - 58, size / 2 + 14, size - 20), outline=c, width=5)
    elif name == "lunch":
        d.arc((20, 20, size - 20, size - 20), 20, 340, fill=c, width=7)
        d.line((size * 0.32, 18, size * 0.32, size - 18), fill=c, width=6)
        d.line((size * 0.66, 18, size * 0.66, size - 18), fill=c, width=6)
    elif name == "away":
        d.ellipse((16, 16, size - 16, size - 16), outline=c, width=7)
        d.line((size / 2, size / 2, size / 2, 34), fill=c, width=7)
        d.line((size / 2, size / 2, size - 36, size / 2), fill=c, width=7)
    elif name == "phone":
        d.rounded_rectangle((28, 10, size - 28, size - 10), radius=12, outline=c, width=6)
        d.rectangle((42, 22, size - 42, size - 30), outline=c, width=3)
        d.ellipse((size / 2 - 5, size - 24, size / 2 + 5, size - 14), fill=c)
    elif name == "travel":
        d.rectangle((22, 32, size - 22, size - 20), outline=c, width=6)
        d.arc((36, 12, size - 36, 52), 180, 360, fill=c, width=6)
    else:
        d.rectangle((16, 16, size - 16, size - 16), outline=c, width=6)
    return img


def resolve_icon(ref: str, uploads_dir: Path, icons_dir: Path) -> Image.Image | None:
    if not ref:
        return None
    if ref.startswith("builtin:"):
        name = ref.split(":", 1)[1]
        png_path = icons_dir / f"{name}.png"
        if png_path.exists():
            return Image.open(png_path)
        return _draw_builtin(name)
    if ref.startswith("upload:"):
        filename = ref.split(":", 1)[1]
        path = uploads_dir / filename
        if path.exists():
            return Image.open(path)
    return None


def fit_image_to_box(image: Image.Image, box_width: int, box_height: int, dither: bool = True, invert: bool = False) -> Image.Image:
    img = ImageOps.exif_transpose(image.convert("L"))
    img.thumbnail((box_width, box_height), Image.Resampling.LANCZOS)
    if invert:
        img = ImageOps.invert(img)
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    bw = img.convert("1", dither=mode)
    canvas = Image.new("1", (box_width, box_height), 1)
    x = (box_width - bw.width) // 2
    y = (box_height - bw.height) // 2
    canvas.paste(bw, (x, y))
    return canvas
