#!/usr/bin/env python3
"""
push_test.py — Diagnostic BLE push tool for Elecrow ESP32 E-Ink (5.79" 800x272)

Requires:
  pip install bleak pillow

macOS note:
- Make sure Terminal/iTerm has Bluetooth permission in System Settings -> Privacy & Security -> Bluetooth.

Firmware assumptions:
- BLE peripheral advertises with name DEVICE_NAME
- Service + characteristics UUIDs as configured below
- CTRL accepts ASCII:
    BEGIN <w> <h> <len> <crc32hex>
    END
    ABORT
- DATA accepts chunk writes (preferably WRITE_NR)
- PROG notifies strings: READY, ACK <offset>, CRCOK/CRCFAIL, DONE, etc.

Usage examples:
  python3 push_test.py --pattern calib --pack row-msb --invert 0 --rotate 0
  python3 push_test.py --pattern diag --pack col-msb
  python3 push_test.py --pattern checker --pack row-lsb --invert 1
  python3 push_test.py --pattern solid --solid black --pack col-msb --write-response 1
  python3 push_test.py --list-services
"""

import argparse
import asyncio
import time
import zlib
from dataclasses import dataclass
from io import BytesIO
from typing import Optional, Tuple

from bleak import BleakClient, BleakScanner
from PIL import Image, ImageDraw, ImageFont


# -----------------------------
# Defaults / Config
# -----------------------------
DEVICE_NAME = "JON_EINK_579"

SVC_UUID  = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001"
CTRL_UUID = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001"
DATA_UUID = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001"
PROG_UUID = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001"

W_DEFAULT = 800
H_DEFAULT = 272


@dataclass
class Progress:
    ready: bool = False
    done: bool = False
    crc_ok: Optional[bool] = None
    last_ack: int = 0
    last_msg: str = ""


# -----------------------------
# Pattern generators
# -----------------------------
def _font():
    # Default font is fine for diagnosis. Swap for a TTF later if you like.
    return ImageFont.load_default()


def pattern_calib(w: int, h: int) -> Image.Image:
    """Corner labels + center crosshair + stripes + border. Great for orientation."""
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    font = _font()

    # Background stripes (vertical)
    stripe = 10
    for x in range(0, w, stripe * 2):
        d.rectangle([x, 0, x + stripe - 1, h - 1], fill=0)

    # Border
    d.rectangle([0, 0, w - 1, h - 1], outline=0, width=2)

    def label(x, y, txt):
        pad = 2
        bbox = d.textbbox((0, 0), txt, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.rectangle([x, y, x + tw + pad * 2, y + th + pad * 2], fill=255)
        d.text((x + pad, y + pad), txt, fill=0, font=font)

    label(8, 8, "TL")
    label(w - 42, 8, "TR")
    label(8, h - 26, "BL")
    label(w - 42, h - 26, "BR")

    cx, cy = w // 2, h // 2
    d.line([(cx - 30, cy), (cx + 30, cy)], fill=0, width=2)
    d.line([(cx, cy - 30), (cx, cy + 30)], fill=0, width=2)
    label(max(0, cx - 30), max(0, cy - 50), "CENTER")

    return img.point(lambda p: 0 if p < 128 else 255, mode="1")


def pattern_diag(w: int, h: int) -> Image.Image:
    """Diagonal lines + quadrant fills. Reveals row/col packing instantly."""
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    font = _font()

    # diagonals
    d.line([(0, 0), (w - 1, h - 1)], fill=0, width=2)
    d.line([(w - 1, 0), (0, h - 1)], fill=0, width=2)

    # quadrant block
    d.rectangle([0, 0, w // 4, h // 6], fill=0)

    # labels
    d.text((10, 10), "DIAG", fill=0, font=font)
    d.text((10, h - 20), f"{w}x{h}", fill=0, font=font)

    return img.point(lambda p: 0 if p < 128 else 255, mode="1")


def pattern_checker(w: int, h: int, cell: int = 16) -> Image.Image:
    """Checkerboard. Good for bit order and inversion."""
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            if ((x // cell) + (y // cell)) % 2 == 0:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=0)
    return img.point(lambda p: 0 if p < 128 else 255, mode="1")


def pattern_solid(w: int, h: int, color: str) -> Image.Image:
    """All white or all black. Great for verifying polarity/inversion."""
    img = Image.new("1", (w, h), 1)  # 1=white
    if color.lower() == "black":
        img = Image.new("1", (w, h), 0)
    return img


def pattern_noise(w: int, h: int, seed: int = 1) -> Image.Image:
    """Deterministic pseudo-random noise. Good for spotting transfer corruption."""
    # Simple LCG noise without numpy
    img = Image.new("1", (w, h), 1)
    px = img.load()
    x = seed & 0xFFFFFFFF
    for y in range(h):
        for xx in range(w):
            x = (1664525 * x + 1013904223) & 0xFFFFFFFF
            px[xx, y] = 1 if (x & 0x80000000) else 0
    return img


# -----------------------------
# Image transforms
# -----------------------------
def apply_transforms(img: Image.Image, rotate: int, flip_lr: bool, flip_tb: bool) -> Image.Image:
    if rotate:
        img = img.rotate(rotate, expand=False)
    if flip_lr:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_tb:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    return img


# -----------------------------
# Packers
# -----------------------------
def pack_row_major(img_1bit: Image.Image, msb_left: bool = True, white_is_1: bool = True) -> bytes:
    """
    Row-major: 1 byte = 8 horizontal pixels.
    msb_left=True => MSB is leftmost pixel in each byte group.
    white_is_1=True => bit=1 means white (Pillow '1' uses 255/True for white).
    """
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
    Column-major: 1 byte = 8 vertical pixels.
    msb_top=True => MSB is top pixel of each 8-pixel vertical group.
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


def build_payload(img_1bit: Image.Image, pack_mode: str, invert_bytes: bool) -> bytes:
    if pack_mode == "row-msb":
        payload = pack_row_major(img_1bit, msb_left=True, white_is_1=True)
    elif pack_mode == "row-lsb":
        payload = pack_row_major(img_1bit, msb_left=False, white_is_1=True)
    elif pack_mode == "col-msb":
        payload = pack_col_major(img_1bit, msb_top=True, white_is_1=True)
    elif pack_mode == "col-lsb":
        payload = pack_col_major(img_1bit, msb_top=False, white_is_1=True)
    else:
        raise ValueError(f"Unknown pack mode: {pack_mode}")

    if invert_bytes:
        payload = bytes((b ^ 0xFF) for b in payload)

    return payload


# -----------------------------
# BLE helpers
# -----------------------------
async def find_device_by_name(name: str, timeout: float = 10.0):
    print(f"Scanning for BLE device named: {name!r} ...")
    dev = await BleakScanner.find_device_by_filter(lambda d, ad: d.name == name, timeout=timeout)
    if not dev:
        raise RuntimeError(f"Device not found: {name!r}. Ensure it's advertising and not already connected.")
    print(f"Found: {dev.name} @ {dev.address}")
    return dev


async def list_services(client: BleakClient):
    svcs = await client.get_services()
    print("=== Services / Characteristics ===")
    for s in svcs:
        print(f"Service {s.uuid}")
        for c in s.characteristics:
            props = ",".join(c.properties)
            print(f"  Char {c.uuid} props=[{props}]")
    print("=================================")


async def push_over_ble(
    payload: bytes,
    w: int,
    h: int,
    *,
    chunk_size: int,
    ack_every: int,
    ack_timeout_s: float,
    write_response: bool,
    yield_every: int,
    list_svcs: bool,
):
    expected_len = (w * h) // 8
    if len(payload) != expected_len:
        raise ValueError(f"Payload len {len(payload)} != expected {expected_len}")

    crc = zlib.crc32(payload) & 0xFFFFFFFF
    print(f"Python CRC32: {crc:08x}")

    begin_cmd = f"BEGIN {w} {h} {len(payload)} {crc:08x}\n".encode("ascii")

    progress = Progress()
    ack_event = asyncio.Event()
    done_event = asyncio.Event()

    def on_prog(_, data: bytearray):
        msg = data.decode(errors="ignore").strip()
        progress.last_msg = msg
        print(f"[PROG] {msg}")

        if msg == "READY":
            progress.ready = True
        elif msg.startswith("ACK "):
            try:
                progress.last_ack = int(msg.split()[1])
                ack_event.set()
            except Exception:
                pass
        elif msg.startswith("CRCOK"):
            progress.crc_ok = True
        elif msg.startswith("CRCFAIL"):
            progress.crc_ok = False
            # don't hang forever if firmware doesn't send DONE
            done_event.set()
        elif msg == "DONE":
            progress.done = True
            done_event.set()

    dev = await find_device_by_name(DEVICE_NAME)

    async with BleakClient(dev) as client:
        print("Connecting...")
        await client.connect()
        print("Connected.")

        if list_svcs:
            await list_services(client)

        print("Subscribing to progress notifications...")
        await client.start_notify(PROG_UUID, on_prog)

        print("Sending BEGIN...")
        await client.write_gatt_char(CTRL_UUID, begin_cmd, response=True)

        # Wait briefly for READY
        t0 = time.time()
        while not progress.ready and (time.time() - t0) < 2.0:
            await asyncio.sleep(0.05)

        print(f"Streaming {len(payload)} bytes... chunk={chunk_size} "
              f"write_response={int(write_response)} ack_every={ack_every}")

        sent = 0
        last_print = 0

        while sent < len(payload):
            chunk = payload[sent:sent + chunk_size]
            await client.write_gatt_char(DATA_UUID, chunk, response=write_response)
            sent += len(chunk)

            # Yield periodically to keep macOS BLE stack happy
            if yield_every > 0 and (sent // chunk_size) % yield_every == 0:
                await asyncio.sleep(0)

            # App-level backpressure (only useful if firmware sends ACK)
            if ack_every > 0 and (sent - progress.last_ack) >= ack_every:
                ack_event.clear()
                try:
                    await asyncio.wait_for(ack_event.wait(), timeout=ack_timeout_s)
                except asyncio.TimeoutError:
                    # If ACKs stall, force one response write as a nudge
                    await client.write_gatt_char(DATA_UUID, b"", response=True)

            if sent - last_print >= 4096:
                print(f"Sent {sent}/{len(payload)} bytes (last ACK {progress.last_ack})")
                last_print = sent

        print("Sending END...")
        await client.write_gatt_char(CTRL_UUID, b"END\n", response=True)

        print("Waiting for DONE (or CRCFAIL)...")
        await asyncio.wait_for(done_event.wait(), timeout=30.0)

        await client.stop_notify(PROG_UUID)

        if progress.crc_ok is False:
            raise RuntimeError("Device reported CRCFAIL.")

        print("Done. CRCOK:", progress.crc_ok)


# -----------------------------
# Main
# -----------------------------
def build_image(pattern: str, w: int, h: int, solid_color: str, checker_cell: int, noise_seed: int) -> Image.Image:
    if pattern == "calib":
        return pattern_calib(w, h)
    if pattern == "diag":
        return pattern_diag(w, h)
    if pattern == "checker":
        return pattern_checker(w, h, cell=checker_cell)
    if pattern == "solid":
        return pattern_solid(w, h, solid_color)
    if pattern == "noise":
        return pattern_noise(w, h, seed=noise_seed)
    raise ValueError(f"Unknown pattern: {pattern}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=DEVICE_NAME, help="BLE peripheral name")
    ap.add_argument("--w", type=int, default=W_DEFAULT)
    ap.add_argument("--h", type=int, default=H_DEFAULT)

    ap.add_argument("--pattern", default="calib",
                    choices=["calib", "diag", "checker", "solid", "noise"],
                    help="Test pattern to render")
    ap.add_argument("--solid", default="white", choices=["white", "black"], help="Color for --pattern solid")
    ap.add_argument("--checker-cell", type=int, default=16)
    ap.add_argument("--noise-seed", type=int, default=1)

    ap.add_argument("--pack", default="row-msb",
                    choices=["row-msb", "row-lsb", "col-msb", "col-lsb"],
                    help="Framebuffer packing mode")
    ap.add_argument("--invert", type=int, default=0, choices=[0, 1],
                    help="Invert all bytes after packing (quick polarity test)")

    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270],
                    help="Rotate image before packing")
    ap.add_argument("--flip-lr", type=int, default=0, choices=[0, 1])
    ap.add_argument("--flip-tb", type=int, default=0, choices=[0, 1])

    ap.add_argument("--chunk", type=int, default=180, help="BLE DATA chunk size")
    ap.add_argument("--ack-every", type=int, default=2048, help="Wait for app-level ACK every N bytes (0 to disable)")
    ap.add_argument("--ack-timeout", type=float, default=6.0)
    ap.add_argument("--write-response", type=int, default=0, choices=[0, 1],
                    help="Use GATT write-with-response for DATA (slower but reliable)")
    ap.add_argument("--yield-every", type=int, default=8,
                    help="Yield to event loop every N chunks (0 disables)")

    ap.add_argument("--list-services", action="store_true",
                    help="Print discovered services/characteristics after connecting")

    args = ap.parse_args()

    
    img = build_image(args.pattern, args.w, args.h, args.solid, args.checker_cell, args.noise_seed)
    img = apply_transforms(img, args.rotate, bool(args.flip_lr), bool(args.flip_tb))

    # Save preview for sanity
    preview_path = f"preview_{args.pattern}_{args.pack}_inv{args.invert}_r{args.rotate}_lr{args.flip_lr}_tb{args.flip_tb}.png"
    img.convert("L").save(preview_path)
    print(f"Wrote {preview_path}")

    payload = build_payload(img, args.pack, invert_bytes=bool(args.invert))

    await push_over_ble(
        payload,
        args.w, args.h,
        chunk_size=args.chunk,
        ack_every=args.ack_every,
        ack_timeout_s=args.ack_timeout,
        write_response=bool(args.write_response),
        yield_every=args.yield_every,
        list_svcs=args.list_services,
    )


if __name__ == "__main__":
    asyncio.run(main())
