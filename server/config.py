from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    app_version: str = "0.1.0"

    display_width: int = 800
    display_height: int = 272

    ble_device_name: str = "JON_EINK_579"
    ble_service_uuid: str = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001"
    ble_ctrl_uuid: str = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001"
    ble_data_uuid: str = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001"
    ble_prog_uuid: str = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001"

    ble_scan_timeout_s: float = 10.0
    ble_connect_timeout_s: float = 10.0
    ble_push_done_timeout_s: float = 35.0
    ble_ack_timeout_s: float = 6.0
    ble_chunk_size: int = 180
    ble_ack_every: int = 2048
    ble_write_response: bool = False
    ble_yield_every_chunks: int = 8

    ttf_path: str = ""
    state_file: Path = Path("server/data/state.json")


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    default_ttf = root / "server" / "assets" / "RobotoMono.ttf"
    default_state = root / "server" / "data" / "state.json"

    return Settings(
        app_version=os.getenv("STATSIGN_APP_VERSION", "0.1.0"),
        ble_device_name=os.getenv("STATSIGN_DEVICE_NAME", "JON_EINK_579"),
        ble_service_uuid=os.getenv("STATSIGN_SERVICE_UUID", Settings.ble_service_uuid),
        ble_ctrl_uuid=os.getenv("STATSIGN_CTRL_UUID", Settings.ble_ctrl_uuid),
        ble_data_uuid=os.getenv("STATSIGN_DATA_UUID", Settings.ble_data_uuid),
        ble_prog_uuid=os.getenv("STATSIGN_PROG_UUID", Settings.ble_prog_uuid),
        ble_scan_timeout_s=float(os.getenv("STATSIGN_SCAN_TIMEOUT_S", "10")),
        ble_connect_timeout_s=float(os.getenv("STATSIGN_CONNECT_TIMEOUT_S", "10")),
        ble_push_done_timeout_s=float(os.getenv("STATSIGN_PUSH_DONE_TIMEOUT_S", "35")),
        ble_ack_timeout_s=float(os.getenv("STATSIGN_ACK_TIMEOUT_S", "6")),
        ble_chunk_size=int(os.getenv("STATSIGN_CHUNK_SIZE", "180")),
        ble_ack_every=int(os.getenv("STATSIGN_ACK_EVERY", "2048")),
        ble_write_response=_env_bool("STATSIGN_WRITE_RESPONSE", False),
        ble_yield_every_chunks=int(os.getenv("STATSIGN_YIELD_EVERY_CHUNKS", "8")),
        ttf_path=os.getenv("STATSIGN_TTF_PATH", str(default_ttf if default_ttf.exists() else "")),
        state_file=Path(os.getenv("STATSIGN_STATE_FILE", str(default_state))),
    )
