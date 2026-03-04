from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from assets import fit_image_to_box, resolve_icon
from presets import SignState


def _load_font(size: int, ttf_path: str, font_family: str = "") -> ImageFont.ImageFont:
    # Keep size-responsive behavior even when custom fonts are missing.
    for path in (font_family, ttf_path, "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        if path:
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _line_height(font: ImageFont.ImageFont) -> int:
    box = font.getbbox("Ag")
    return max(1, box[3] - box[1] + 4)


def _wrap_with_ellipsis(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    if not text.strip() or max_lines <= 0:
        return []
    words = text.split()
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if not cur or draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = word
        if len(lines) == max_lines:
            break
    if len(lines) < max_lines and cur:
        lines.append(cur)
    if words and len(" ".join(lines).split()) < len(words):
        last = lines[-1]
        while last and draw.textlength(f"{last}…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = f"{last.rstrip()}…"
    return lines[:max_lines]


def _fit_font(draw: ImageDraw.ImageDraw, text: str, start_size: int, min_size: int, max_width: int, ttf_path: str, font_family: str) -> ImageFont.ImageFont:
    for size in range(start_size, min_size - 1, -2):
        font = _load_font(size, ttf_path, font_family)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _load_font(min_size, ttf_path, font_family)


def _substitute(text: str, state: SignState) -> str:
    values = {
        "time": datetime.now().strftime("%H:%M"),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "location": state.location,
        "return_time": state.return_time,
    }
    values.update(state.variables)
    out = text
    for key, value in values.items():
        out = out.replace(f"{{{key}}}", str(value))
    return out


def _draw_lines(draw: ImageDraw.ImageDraw, lines: Iterable[str], x: int, y: int, font: ImageFont.ImageFont, fill: int, align: str, width: int) -> int:
    line_h = _line_height(font)
    for line in lines:
        tw = draw.textlength(line, font=font)
        dx = x if align == "left" else (x + (width - tw) / 2 if align == "center" else x + width - tw)
        draw.text((dx, y), line, font=font, fill=fill)
        y += line_h
    return y


def render_sign_image(state: SignState, width: int, height: int, ttf_path: str = "", uploads_dir=None, icons_dir=None) -> Image.Image:
    bg = 0 if state.style.invert else 255
    fg = 255 if state.style.invert else 0
    img = Image.new("L", (width, height), bg)
    draw = ImageDraw.Draw(img)

    pad = state.style.padding
    content = (pad, pad, width - pad, height - pad)
    cw = content[2] - content[0]
    ch = content[3] - content[1]

    status = _substitute(state.status.strip() or "Status", state)
    message = _substitute(state.message.strip(), state)
    stamp = datetime.now().strftime("Updated %H:%M")

    # WYSIWYG / full-image layout path.
    if state.layout == "designer":
        base_ref = state.image or state.icon
        if uploads_dir and icons_dir and base_ref:
            source = resolve_icon(base_ref, uploads_dir, icons_dir)
            if source:
                fitted = fit_image_to_box(source, width, height, dither=state.style.icon_dither, invert=state.style.invert)
                img.paste(fitted, (0, 0))
        if state.style.show_border:
            draw.rectangle((1, 1, width - 2, height - 2), outline=fg, width=1)
        return img.point(lambda p: 0 if p < 128 else 255, mode="1")

    if state.layout == "split":
        left_w = int(cw * 0.66)
        right_w = cw - left_w - 8
        lx, ly = content[0], content[1]
        rx, ry = lx + left_w + 8, content[1]

        headline_font = _fit_font(draw, status, state.style.headline_size, 24, left_w, ttf_path, state.style.font_family)
        message_font = _load_font(state.style.message_size, ttf_path, state.style.font_family)
        footer_font = _load_font(state.style.footer_size, ttf_path, state.style.font_family)

        draw.text((lx, ly), status, font=headline_font, fill=fg)
        y = ly + _line_height(headline_font) + 6
        lines = _wrap_with_ellipsis(draw, message, message_font, left_w, max(1, (ch - y + ly - 30) // _line_height(message_font)))
        _draw_lines(draw, lines, lx, y, message_font, fg, state.style.alignment, left_w)

        icon_h = int(ch * 0.55)
        if uploads_dir and icons_dir:
            icon = resolve_icon(state.icon, uploads_dir, icons_dir)
            if icon:
                fitted = fit_image_to_box(icon, right_w, icon_h, dither=state.style.icon_dither, invert=state.style.invert)
                img.paste(fitted, (rx, ry))

        rt_font = _fit_font(draw, state.return_time or "--:--", max(state.style.message_size + 8, 42), 22, right_w, ttf_path, state.style.font_family)
        draw.text((rx, ry + icon_h + 10), "Back at", font=footer_font, fill=fg)
        draw.text((rx, ry + icon_h + 10 + _line_height(footer_font)), state.return_time or "--:--", font=rt_font, fill=fg)

    elif state.layout == "badge":
        banner_h = int(ch * 0.42)
        draw.rectangle((content[0], content[1], content[2], content[1] + banner_h), fill=fg)
        status_font = _fit_font(draw, status, state.style.headline_size, 22, cw - 16, ttf_path, state.style.font_family)
        sw = draw.textlength(status, font=status_font)
        sx = content[0] + (cw - sw) / 2
        sy = content[1] + (banner_h - _line_height(status_font)) / 2
        draw.text((sx, sy), status, font=status_font, fill=bg)

        body_y = content[1] + banner_h + 8
        icon_w = int(cw * 0.25)
        if uploads_dir and icons_dir:
            icon = resolve_icon(state.icon, uploads_dir, icons_dir)
            if icon:
                fitted = fit_image_to_box(icon, icon_w, ch - banner_h - 8, dither=state.style.icon_dither, invert=state.style.invert)
                img.paste(fitted, (content[0], body_y))
        message_font = _load_font(state.style.message_size, ttf_path, state.style.font_family)
        tx = content[0] + icon_w + 10
        tw = cw - icon_w - 10
        lines = _wrap_with_ellipsis(draw, message, message_font, tw, max(1, (ch - banner_h - 8) // _line_height(message_font)))
        _draw_lines(draw, lines, tx, body_y, message_font, fg, "left", tw)

    else:
        headline_font = _fit_font(draw, status, state.style.headline_size, 24, cw, ttf_path, state.style.font_family)
        message_font = _load_font(state.style.message_size, ttf_path, state.style.font_family)
        footer_font = _load_font(state.style.footer_size, ttf_path, state.style.font_family)

        y = content[1]
        y = _draw_lines(draw, [status], content[0], y, headline_font, fg, state.style.alignment, cw) + 4
        max_lines = max(1, (content[3] - y - _line_height(footer_font) - 8) // _line_height(message_font))
        lines = _wrap_with_ellipsis(draw, message, message_font, cw, max_lines)
        _draw_lines(draw, lines, content[0], y, message_font, fg, state.style.alignment, cw)

        if uploads_dir and icons_dir:
            icon = resolve_icon(state.icon, uploads_dir, icons_dir)
            if icon:
                box = int(min(cw * 0.24, ch * 0.5))
                fitted = fit_image_to_box(icon, box, box, dither=state.style.icon_dither, invert=state.style.invert)
                img.paste(fitted, (content[2] - box, content[1]))

        if state.style.show_updated_timestamp:
            draw.text((content[0], content[3] - _line_height(footer_font)), stamp, font=footer_font, fill=fg)

    if state.style.show_border:
        draw.rectangle((1, 1, width - 2, height - 2), outline=fg, width=1)

    if state.style.debug_boxes:
        draw.rectangle(content, outline=fg, width=1)

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


def render_framebuffer(state: SignState, width: int, height: int, ttf_path: str = "", uploads_dir=None, icons_dir=None) -> tuple[Image.Image, bytes]:
    img = render_sign_image(
        state=state,
        width=width,
        height=height,
        ttf_path=ttf_path,
        uploads_dir=uploads_dir,
        icons_dir=icons_dir,
    )
    payload = pack_framebuffer_row_major(img)
    expected = (width * height) // 8
    if len(payload) != expected:
        raise ValueError(f"Packed framebuffer length {len(payload)} != expected {expected}")
    return img, payload


def image_to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.convert("L").save(buf, format="PNG")
    return buf.getvalue()
