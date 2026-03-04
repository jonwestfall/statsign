from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


@dataclass(slots=True)
class SignState:
    status: str = "In office"
    message: str = ""
    location: str = ""


def _load_font(size: int, ttf_path: str) -> ImageFont.ImageFont:
    if ttf_path:
        try:
            return ImageFont.truetype(ttf_path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    if not text.strip():
        return []
    words = text.split()
    lines: list[str] = []
    current = words[0]

    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_sign_image(state: SignState, width: int, height: int, ttf_path: str = "") -> Image.Image:
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(64, ttf_path)
    body_font = _load_font(34, ttf_path)
    small_font = _load_font(20, ttf_path)

    margin = 24
    max_width = width - margin * 2

    status = state.status.strip() or "Status"
    draw.text((margin, margin), status, fill=0, font=title_font)

    y = margin + 86
    message = state.message.strip()
    location = state.location.strip()

    body_text = message
    if location:
        body_text = f"{message} @ {location}" if message else f"Location: {location}"

    for line in _wrap(draw, body_text, body_font, max_width):
        draw.text((margin, y), line, fill=0, font=body_font)
        y += 44

    stamp = datetime.now().strftime("Updated: %H:%M")
    stamp_width = draw.textlength(stamp, font=small_font)
    draw.text((width - margin - stamp_width, height - margin - 24), stamp, fill=0, font=small_font)

    return img.point(lambda p: 0 if p < 128 else 255, mode="1")


def pack_framebuffer_row_major(img_1bit: Image.Image) -> bytes:
    img = img_1bit.convert("1")
    w, h = img.size
    px = img.load()
    out = bytearray()

    for y in range(h):
        current = 0
        bit = 7
        for x in range(w):
            is_white = 1 if px[x, y] else 0
            if is_white:
                current |= (1 << bit)
            bit -= 1
            if bit < 0:
                out.append(current)
                current = 0
                bit = 7
        if bit != 7:
            out.append(current)

    return bytes(out)


def render_framebuffer(state: SignState, width: int, height: int, ttf_path: str = "") -> tuple[Image.Image, bytes]:
    img = render_sign_image(state=state, width=width, height=height, ttf_path=ttf_path)
    payload = pack_framebuffer_row_major(img)
    expected = (width * height) // 8
    if len(payload) != expected:
        raise ValueError(f"Packed framebuffer length {len(payload)} != expected {expected}")
    return img, payload


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.convert("L").save(buf, format="PNG")
    return buf.getvalue()
