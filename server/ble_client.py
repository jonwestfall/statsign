from __future__ import annotations

import asyncio
import zlib
from dataclasses import dataclass, field

from bleak import BleakClient, BleakScanner

from config import Settings


@dataclass(slots=True)
class BleResult:
    success: bool
    logs: list[str] = field(default_factory=list)
    error: str | None = None


class BleSignClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def _find_device(self):
        return await BleakScanner.find_device_by_filter(
            lambda d, ad: d.name == self.settings.ble_device_name,
            timeout=self.settings.ble_scan_timeout_s,
        )

    async def send_control(self, command: str) -> BleResult:
        logs: list[str] = [f"Scanning for {self.settings.ble_device_name}..."]
        device = await self._find_device()
        if not device:
            return BleResult(success=False, logs=logs, error="BLE device not found")

        done_event = asyncio.Event()

        def on_prog(_: int, data: bytearray):
            msg = data.decode(errors="ignore").strip()
            if msg:
                logs.append(msg)
                print(f"[PROG] {msg}")
            if msg in {"DONE", "OK"}:
                done_event.set()

        try:
            async with BleakClient(device, timeout=self.settings.ble_connect_timeout_s) as client:
                await client.start_notify(self.settings.ble_prog_uuid, on_prog)
                await client.write_gatt_char(
                    self.settings.ble_ctrl_uuid,
                    f"{command}\n".encode("ascii"),
                    response=True,
                )
                try:
                    await asyncio.wait_for(done_event.wait(), timeout=4.0)
                except asyncio.TimeoutError:
                    logs.append("No DONE/OK received; command write completed")
                await client.stop_notify(self.settings.ble_prog_uuid)
                return BleResult(success=True, logs=logs)
        except Exception as exc:
            return BleResult(success=False, logs=logs, error=str(exc))

    async def push_framebuffer(self, payload: bytes, width: int, height: int) -> BleResult:
        logs: list[str] = [f"Scanning for {self.settings.ble_device_name}..."]
        device = await self._find_device()
        if not device:
            return BleResult(success=False, logs=logs, error="BLE device not found")

        expected = (width * height) // 8
        if len(payload) != expected:
            return BleResult(success=False, logs=logs, error=f"Invalid payload length {len(payload)}; expected {expected}")

        crc = zlib.crc32(payload) & 0xFFFFFFFF
        begin = f"BEGIN {width} {height} {len(payload)} {crc:08x}\n".encode("ascii")

        ack_offset = 0
        ack_event = asyncio.Event()
        done_event = asyncio.Event()
        crc_ok = None

        def on_prog(_: int, data: bytearray):
            nonlocal ack_offset, crc_ok
            msg = data.decode(errors="ignore").strip()
            if not msg:
                return
            logs.append(msg)
            print(f"[PROG] {msg}")
            if msg.startswith("ACK "):
                try:
                    ack_offset = int(msg.split()[1])
                    ack_event.set()
                except Exception:
                    pass
            elif msg.startswith("CRCOK"):
                crc_ok = True
            elif msg.startswith("CRCFAIL"):
                crc_ok = False
                done_event.set()
            elif msg == "DONE":
                done_event.set()

        try:
            async with BleakClient(device, timeout=self.settings.ble_connect_timeout_s) as client:
                await client.start_notify(self.settings.ble_prog_uuid, on_prog)
                await client.write_gatt_char(self.settings.ble_ctrl_uuid, begin, response=True)

                sent = 0
                while sent < len(payload):
                    chunk = payload[sent : sent + self.settings.ble_chunk_size]
                    await client.write_gatt_char(
                        self.settings.ble_data_uuid,
                        chunk,
                        response=self.settings.ble_write_response,
                    )
                    sent += len(chunk)

                    if self.settings.ble_yield_every_chunks > 0 and (
                        (sent // self.settings.ble_chunk_size) % self.settings.ble_yield_every_chunks == 0
                    ):
                        await asyncio.sleep(0)

                    if self.settings.ble_ack_every > 0 and (sent - ack_offset) >= self.settings.ble_ack_every:
                        ack_event.clear()
                        try:
                            await asyncio.wait_for(ack_event.wait(), timeout=self.settings.ble_ack_timeout_s)
                        except asyncio.TimeoutError:
                            await client.write_gatt_char(self.settings.ble_data_uuid, b"", response=True)

                await client.write_gatt_char(self.settings.ble_ctrl_uuid, b"END\n", response=True)
                await asyncio.wait_for(done_event.wait(), timeout=self.settings.ble_push_done_timeout_s)
                await client.stop_notify(self.settings.ble_prog_uuid)

                if crc_ok is False:
                    return BleResult(success=False, logs=logs, error="Device reported CRCFAIL")
                return BleResult(success=True, logs=logs)
        except Exception as exc:
            return BleResult(success=False, logs=logs, error=str(exc))
