import asyncio
import binascii
import zlib
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from PIL import Image, ImageDraw, ImageFont

from bleak import BleakClient, BleakScanner

# ---- Display targets ----
TARGETS = {
    "579": {"w": 272, "h": 792, "device_name": "JON_EINK_579"},
    # later: add 4.2", e.g. 400x300
    # "42": {"w": 400, "h": 300, "device_name": "JON_EINK_42"},
}

# ---- BLE UUIDs ----
SVC_UUID  = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001"
CTRL_UUID = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001"
DATA_UUID = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001"
PROG_UUID = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001"

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@dataclass
class SignState:
    status: str = "IN OFFICE"
    back_at: str = ""
    note: str = "Knock if it's urgent."

STATE = SignState()

def render_1bpp(w: int, h: int, state: SignState) -> Image.Image:
    # 1-bit image: 0=black, 255=white in Pillow mode "1" can be finicky for drawing,
    # so draw in "L" then threshold.
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)

    # Fonts: use basic default if you don't want to ship fonts yet
    # For nicer results, add a TTF in server/assets and load it.
    font_big = ImageFont.load_default()
    font_med = ImageFont.load_default()
    font_sm  = ImageFont.load_default()

    # Layout tuned for tall portrait (272x792)
    margin = 10
    y = 20

    d.text((margin, y), state.status.upper(), fill=0, font=font_big)
    y += 60

    if state.back_at.strip():
        d.text((margin, y), f"BACK: {state.back_at.strip()}", fill=0, font=font_med)
        y += 40

    if state.note.strip():
        d.text((margin, h - 40), state.note.strip(), fill=0, font=font_sm)

    # threshold to 1-bit
    bw = img.point(lambda p: 0 if p < 128 else 255, mode="1")
    return bw

def pack_1bpp_rowmajor(img_1bit: Image.Image) -> bytes:
    """
    Pack pixels left-to-right, top-to-bottom, 1 bit per pixel.
    Bit order per byte: MSB is leftmost pixel in the group of 8.
    White=1, Black=0 typical for many e-paper libs, but confirm in firmware and invert if needed.
    """
    img = img_1bit.convert("1")
    w, h = img.size
    pixels = img.load()

    out = bytearray()
    for y in range(h):
        byte = 0
        bit = 7
        for x in range(w):
            is_white = 1 if pixels[x, y] else 0  # Pillow "1": 255->True, 0->False
            if is_white:
                byte |= (1 << bit)
            bit -= 1
            if bit < 0:
                out.append(byte)
                byte = 0
                bit = 7
        if bit != 7:  # pad remaining bits
            out.append(byte)
    return bytes(out)

async def ble_push(target_key: str, payload: bytes, w: int, h: int):
    dev_name = TARGETS[target_key]["device_name"]

    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name == dev_name)
    )
    if device is None:
        raise RuntimeError(f"BLE device not found: {dev_name}")

    crc = zlib.crc32(payload) & 0xFFFFFFFF
    begin = f"BEGIN {w} {h} {len(payload)} {crc:08x}\n".encode()

    ack_offset = 0
    ack_event = asyncio.Event()

    def on_prog(_, data: bytearray):
        nonlocal ack_offset
        msg = data.decode(errors="ignore").strip()
        if msg.startswith("ACK "):
            try:
                ack_offset = int(msg.split()[1])
                ack_event.set()
            except Exception:
                pass

    async with BleakClient(device) as client:
        await client.start_notify(PROG_UUID, on_prog)

        await client.write_gatt_char(CTRL_UUID, begin, response=True)

        # Conservative chunking for cross-platform stability.
        # You can tune this after it works.
        chunk_size = 180
        step_ack = 2048

        sent = 0
        while sent < len(payload):
            chunk = payload[sent:sent+chunk_size]
            # Use response=False for speed, but rely on ACK pacing.
            await client.write_gatt_char(DATA_UUID, chunk, response=False)
            sent += len(chunk)

            if sent - ack_offset >= step_ack:
                ack_event.clear()
                try:
                    await asyncio.wait_for(ack_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    # fall back to slower mode if needed
                    await client.write_gatt_char(DATA_UUID, b"", response=True)

        await client.write_gatt_char(CTRL_UUID, b"END\n", response=True)
        await asyncio.sleep(0.25)
        await client.stop_notify(PROG_UUID)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "state": STATE})

@app.post("/update", response_class=HTMLResponse)
async def update(
    request: Request,
    status: str = Form(...),
    back_at: str = Form(""),
    note: str = Form(""),
    target: str = Form("579"),
):
    STATE.status = status
    STATE.back_at = back_at
    STATE.note = note

    w = TARGETS[target]["w"]
    h = TARGETS[target]["h"]
    img = render_1bpp(w, h, STATE)

    # push to device
    payload = pack_1bpp_rowmajor(img)
    await ble_push(target, payload, w, h)

    return templates.TemplateResponse("index.html", {"request": request, "state": STATE})

@app.get("/preview.png")
async def preview():
    w = TARGETS["579"]["w"]
    h = TARGETS["579"]["h"]
    img = render_1bpp(w, h, STATE).convert("L")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")
