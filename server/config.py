from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_APP_VERSION = "0.1.0"
DEFAULT_DEVICE_NAME = "JON_EINK_579"
DEFAULT_SERVICE_UUID = "6a4e0001-6f44-4f7a-a3b2-2f9b3c1c0001"
DEFAULT_CTRL_UUID = "6a4e0002-6f44-4f7a-a3b2-2f9b3c1c0001"
DEFAULT_DATA_UUID = "6a4e0003-6f44-4f7a-a3b2-2f9b3c1c0001"
DEFAULT_PROG_UUID = "6a4e0004-6f44-4f7a-a3b2-2f9b3c1c0001"


@dataclass(slots=True)
class Settings:
    app_version: str = DEFAULT_APP_VERSION

    display_width: int = 800
    display_height: int = 272

    ble_device_name: str = DEFAULT_DEVICE_NAME
    ble_service_uuid: str = DEFAULT_SERVICE_UUID
    ble_ctrl_uuid: str = DEFAULT_CTRL_UUID
    ble_data_uuid: str = DEFAULT_DATA_UUID
    ble_prog_uuid: str = DEFAULT_PROG_UUID

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
    presets_file: Path = Path("server/data/presets.json")
    uploads_dir: Path = Path("server/data/uploads")
    builtins_dir: Path = Path("server/assets/icons")
    schedule_file: Path = Path("server/data/schedule.json")
    auth_tokens_file: Path = Path("server/data/auth_tokens.json")
    ui_bootstrap_file: Path = Path("server/data/ui_bootstrap_token.txt")
    default_timezone: str = "America/Chicago"


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    root = Path(__file__).resolve().parents[1]
    server_dir = root / "server"
    default_ttf = server_dir / "assets" / "RobotoMono.ttf"
    data_dir = server_dir / "data"

    return Settings(
        app_version=os.getenv("STATSIGN_APP_VERSION", DEFAULT_APP_VERSION),
        ble_device_name=os.getenv("STATSIGN_DEVICE_NAME", DEFAULT_DEVICE_NAME),
        ble_service_uuid=os.getenv("STATSIGN_SERVICE_UUID", DEFAULT_SERVICE_UUID),
        ble_ctrl_uuid=os.getenv("STATSIGN_CTRL_UUID", DEFAULT_CTRL_UUID),
        ble_data_uuid=os.getenv("STATSIGN_DATA_UUID", DEFAULT_DATA_UUID),
        ble_prog_uuid=os.getenv("STATSIGN_PROG_UUID", DEFAULT_PROG_UUID),
        ble_scan_timeout_s=float(os.getenv("STATSIGN_SCAN_TIMEOUT_S", "10")),
        ble_connect_timeout_s=float(os.getenv("STATSIGN_CONNECT_TIMEOUT_S", "10")),
        ble_push_done_timeout_s=float(os.getenv("STATSIGN_PUSH_DONE_TIMEOUT_S", "35")),
        ble_ack_timeout_s=float(os.getenv("STATSIGN_ACK_TIMEOUT_S", "6")),
        ble_chunk_size=int(os.getenv("STATSIGN_CHUNK_SIZE", "180")),
        ble_ack_every=int(os.getenv("STATSIGN_ACK_EVERY", "2048")),
        ble_write_response=_env_bool("STATSIGN_WRITE_RESPONSE", False),
        ble_yield_every_chunks=int(os.getenv("STATSIGN_YIELD_EVERY_CHUNKS", "8")),
        ttf_path=os.getenv("STATSIGN_TTF_PATH", str(default_ttf if default_ttf.exists() else "")),
        state_file=Path(os.getenv("STATSIGN_STATE_FILE", str(data_dir / "state.json"))),
        presets_file=Path(os.getenv("STATSIGN_PRESETS_FILE", str(data_dir / "presets.json"))),
        uploads_dir=Path(os.getenv("STATSIGN_UPLOADS_DIR", str(data_dir / "uploads"))),
        builtins_dir=Path(os.getenv("STATSIGN_BUILTIN_ICONS_DIR", str(server_dir / "assets" / "icons"))),
        schedule_file=Path(os.getenv("STATSIGN_SCHEDULE_FILE", str(data_dir / "schedule.json"))),
        auth_tokens_file=Path(os.getenv("STATSIGN_AUTH_TOKENS_FILE", str(data_dir / "auth_tokens.json"))),
        ui_bootstrap_file=Path(os.getenv("STATSIGN_UI_BOOTSTRAP_FILE", str(data_dir / "ui_bootstrap_token.txt"))),
        default_timezone=os.getenv("STATSIGN_DEFAULT_TIMEZONE", "America/Chicago"),
    )
