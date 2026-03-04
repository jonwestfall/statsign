#!/usr/bin/env python3
"""
push_test.py — macOS BLE push test for Elecrow 5.79" (272x792) e-ink sign.

Requires:
  pip install bleak pillow

Usage:
  python3 push_test.py
"""

import asyncio
import time
import zlib
from dataclasses import dataclass
from typing import Optional

from bleak import BleakClient, BleakScanner
from PIL import Image, ImageDraw, ImageFont

# -----------------------------
# CONFIG — EDIT THESE IF NEEDED
# -----------------------------
DEVICE_NAME = "JON_EINK_579"

SVC_UUID  = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001"
CTRL_UUID = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001"
DATA_UUID = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001"
PROG_UUID = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001"

W = 272
H = 792
FB_LEN = (W * H) // 8

# Conservative values for macOS stability; tune later
CHUNK_SIZE = 180
ACK_EVERY = 2048
ACK_TIMEOUT_S = 6.0
WRITE_WITH_RESPONSE = True


@dataclass
class Progress:
    last_ack: int = 0
    done: bool = False
    crc_ok: bool = False
    ready: bool = False
    last_msg: str = ""


async def _wait_for_ack(progress: Progress, sent: int):
    """Wait until firmware ACKs at least the number of bytes already sent."""
    while progress.last_ack < sent:
        await asyncio.sleep(0.01)

def pack_row_major(img_1bit: Image.Image, msb_left: bool = True, white_is_1: bool = True) -> bytes:
    img = img_1bit.convert("1")
    w, h = img.size
    px = img.load()
    out = bytearray()

    for y in range(h):
        byte = 0
        bit = 7 if msb_left else 0
        step = -1 if msb_left else 1

        for x in range(w):
            is_white = 1 if px[x, y] else 0
            bitval = is_white if white_is_1 else (1 - is_white)
            if bitval:
                byte |= (1 << bit)
            bit += step

            if (msb_left and bit < 0) or ((not msb_left) and bit > 7):
                out.append(byte)
                byte = 0
                bit = 7 if msb_left else 0

        # pad remainder
        if (msb_left and bit != 7) or ((not msb_left) and bit != 0):
            out.append(byte)

    return bytes(out)


def pack_col_major(img_1bit: Image.Image, msb_top: bool = True, white_is_1: bool = True) -> bytes:
    """
    1 byte = 8 vertical pixels in a column. Common for some EPD drivers.
    msb_top: MSB corresponds to the top pixel within the 8-pixel group.
    """
    img = img_1bit.convert("1")
    w, h = img.size
    px = img.load()
    out = bytearray()

    for x in range(w):
        for y0 in range(0, h, 8):
            byte = 0
            for i in range(8):
                y = y0 + i
                if y >= h:
                    break
                is_white = 1 if px[x, y] else 0
                bitval = is_white if white_is_1 else (1 - is_white)
                bit = (7 - i) if msb_top else i
                if bitval:
                    byte |= (1 << bit)
            out.append(byte)

    return bytes(out)
    
def render_calibration_image(w: int, h: int) -> Image.Image:
    """
    Create a 1-bit calibration image:
      - Corner labels TL/TR/BL/BR
      - Vertical stripe pattern
      - Center crosshair
    """
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)

    # Use default font (ship-safe). You can load a TTF later.
    font = ImageFont.load_default()

    # Stripes
    stripe_w = 8
    for x in range(0, w, stripe_w * 2):
        d.rectangle([x, 0, x + stripe_w - 1, h], fill=0)

    # White margin box to make text readable
    margin = 6
    d.rectangle([0, 0, w - 1, h - 1], outline=0, width=2)
    d.rectangle([margin, margin, w - margin - 1, h - margin - 1], outline=0, width=1)

    # Corner labels in white boxes
    def label(x, y, txt):
        pad = 2
        tw, th = d.textbbox((0, 0), txt, font=font)[2:]
        d.rectangle([x, y, x + tw + pad * 2, y + th + pad * 2], fill=255)
        d.text((x + pad, y + pad), txt, fill=0, font=font)

    label(10, 10, "TL")
    label(w - 40, 10, "TR")
    label(10, h - 30, "BL")
    label(w - 40, h - 30, "BR")

    # Crosshair
    cx, cy = w // 2, h // 2
    d.line([(cx - 20, cy), (cx + 20, cy)], fill=0, width=2)
    d.line([(cx, cy - 20), (cx, cy + 20)], fill=0, width=2)
    label(cx - 20, cy - 40, "CENTER")

    # Convert to 1-bit
    bw = img.point(lambda p: 0 if p < 128 else 255, mode="1")
    return bw


def pack_1bpp_msb_left(img_1bit: Image.Image) -> bytes:
    """
    Pack pixels row-major, MSB = leftmost pixel in each 8-pixel group.
    Pillow "1" pixels are True/255 for white, False/0 for black.
    This packer encodes: 1-bit = WHITE, 0-bit = BLACK.

    If your display is inverted, flip bits on either side later.
    """
    img = img_1bit.convert("1")
    w, h = img.size
    px = img.load()

    out = bytearray()
    for y in range(h):
        byte = 0
        bit = 7
        for x in range(w):
            is_white = 1 if px[x, y] else 0
            if is_white:
                byte |= (1 << bit)
            bit -= 1
            if bit < 0:
                out.append(byte)
                byte = 0
                bit = 7
        if bit != 7:
            out.append(byte)
    return bytes(out)


async def find_device_by_name(name: str):
    print(f"Scanning for BLE device named: {name!r} ...")
    dev = await BleakScanner.find_device_by_filter(lambda d, ad: d.name == name, timeout=10.0)
    if not dev:
        raise RuntimeError(f"Device not found: {name!r}. "
                           f"Make sure it's advertising and not already connected.")
    print(f"Found: {dev.name} @ {dev.address}")
    return dev


async def push_frame(payload: bytes):
    if len(payload) != FB_LEN:
        raise ValueError(f"Payload len {len(payload)} != expected {FB_LEN}")

    crc = zlib.crc32(payload) & 0xFFFFFFFF
    begin_cmd = f"BEGIN {W} {H} {len(payload)} {crc:08x}\n".encode("ascii")

    progress = Progress()

    done_event = asyncio.Event()

    def on_prog(_, data: bytearray):
        msg = data.decode(errors="ignore").strip()
        progress.last_msg = msg
        # Print concise progress
        print(f"[PROG] {msg}")

        if msg == "READY":
            progress.ready = True
        elif msg.startswith("ACK "):
            try:
                progress.last_ack = int(msg.split()[1])
            except Exception:
                pass
        elif msg == "CRCOK":
            progress.crc_ok = True
        elif msg == "DONE":
            progress.done = True
            done_event.set()

    dev = await find_device_by_name(DEVICE_NAME)

    async with BleakClient(dev) as client:
        print("Connecting...")
        print("Connected.")

        print("Subscribing to progress notifications...")
        await client.start_notify(PROG_UUID, on_prog)

        print("Sending BEGIN...")
        await client.write_gatt_char(CTRL_UUID, begin_cmd, response=True)

        # If firmware sends READY, wait briefly (optional but nice)
        t0 = time.time()
        while not progress.ready and (time.time() - t0) < 2.0:
            await asyncio.sleep(0.05)

        max_wwr = client.services.get_characteristic(DATA_UUID).max_write_without_response_size
        chunk_size = min(CHUNK_SIZE, max_wwr if max_wwr else CHUNK_SIZE)
        print(
            f"Streaming {len(payload)} bytes "
            f"(chunk={chunk_size}, write_with_response={WRITE_WITH_RESPONSE})..."
        )
        sent = 0
        last_ack_check = 0

        while sent < len(payload):
            chunk = payload[sent:sent + chunk_size]
            await client.write_gatt_char(DATA_UUID, chunk, response=WRITE_WITH_RESPONSE)
            sent += len(chunk)

            # Backpressure: wait for ACK occasionally
            if sent - progress.last_ack >= ACK_EVERY:
                try:
                    await asyncio.wait_for(_wait_for_ack(progress, sent), timeout=ACK_TIMEOUT_S)
                except asyncio.TimeoutError:
                    raise RuntimeError(
                        f"Timed out waiting for ACK near offset {sent}. "
                        f"Last message: {progress.last_msg!r}"
                    )

            # Optional: print basic progress every ~4KB
            if sent - last_ack_check >= 4096:
                print(f"Sent {sent}/{len(payload)} bytes (last ACK {progress.last_ack})")
                last_ack_check = sent

        print("Sending END...")
        await client.write_gatt_char(CTRL_UUID, b"END\n", response=True)

        print("Waiting for DONE...")
        try:
            await asyncio.wait_for(done_event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            raise RuntimeError("Timed out waiting for DONE from device.")

        await client.stop_notify(PROG_UUID)
        print("Done. CRCOK:", progress.crc_ok)


async def main():
    img = render_calibration_image(W, H)
    payload = pack_1bpp_msb_left(img)
    img = render_calibration_image(W, H)

    # Try ONE of these at a time:

    # 1) Current behavior (row-major, MSB-left)
    payload = pack_row_major(img, msb_left=True, white_is_1=True)

    # 2) Row-major, LSB-left
    # payload = pack_row_major(img, msb_left=False, white_is_1=True)

    # 3) Column-major, MSB-top (very common)
    # payload = pack_col_major(img, msb_top=True, white_is_1=True)

    # 4) Column-major, LSB-top
    # payload = pack_col_major(img, msb_top=False, white_is_1=True)

    # If colors inverted, flip white_is_1=False in the call OR XOR the bytes:
    # payload = bytes((b ^ 0xFF) for b in payload)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    print(f"Python CRC32: {crc:08x}")
    # Save a local preview for sanity-checking orientation (optional)
    img.convert("L").save("calibration_preview.png")
    print("Wrote calibration_preview.png")

    # NOTE: If your firmware expects inverted bits, you can flip here:
    # payload = bytes((b ^ 0xFF) for b in payload)

    await push_frame(payload)


if __name__ == "__main__":
    asyncio.run(main())
