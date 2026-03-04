# Statsign Server MVP

Local web + BLE controller for the Statsign 5.79" display firmware.

## Features
- FastAPI web UI at `/` to edit status/message/location and trigger BLE actions.
- Preview endpoint at `/preview.png` (exact 800x272 render).
- BLE push pipeline using `bleak` and firmware protocol (`BEGIN` + data + `END`).
- Control endpoints for `CLEAR` and `DEMO`.
- In-memory state with optional JSON persistence at `server/data/state.json`.

## Setup
```bash
cd server
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1
pip install -e .
```

## Run
Default (loopback only):
```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

LAN/Tailscale mode:
```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

> ⚠️ Security warning: binding to `0.0.0.0` exposes the control API to your LAN/Tailscale peers. Keep this on trusted networks only.

Open `http://127.0.0.1:8000/` (or your LAN/Tailscale IP if bound to `0.0.0.0`).

## Configuration
Set via environment variables:

- `STATSIGN_DEVICE_NAME` (default: `JON_EINK_579`)
- `STATSIGN_CHUNK_SIZE` (default: `180`)
- `STATSIGN_ACK_EVERY` (default: `2048`)
- `STATSIGN_WRITE_RESPONSE` (`0`/`1`, default: `0`)
- `STATSIGN_SCAN_TIMEOUT_S` (default: `10`)
- `STATSIGN_CONNECT_TIMEOUT_S` (default: `10`)
- `STATSIGN_PUSH_DONE_TIMEOUT_S` (default: `35`)
- `STATSIGN_ACK_TIMEOUT_S` (default: `6`)
- `STATSIGN_TTF_PATH` (optional TTF for better typography)
- `STATSIGN_STATE_FILE` (default: `server/data/state.json`)

## API quick reference
- `GET /` UI
- `GET /preview.png` PNG preview of current state
- `GET /api/health` health + last push metadata
- `POST /api/state` body: `{ "status": "In office", "message": "Back at 2:15", "location": "Library" }`
- `POST /api/push` render + BLE push
- `POST /api/clear` send `CLEAR`
- `POST /api/demo` send `DEMO`

## Troubleshooting
### macOS Bluetooth permissions
If scan/connect fails on macOS:
1. Open **System Settings → Privacy & Security → Bluetooth**.
2. Ensure your terminal app (Terminal/iTerm/IDE) is allowed.
3. Restart terminal after changing permissions.

### Windows notes
- Use Python 3.11+.
- Make sure Bluetooth is enabled and the ESP32 is advertising.
- If discovery is flaky, increase `STATSIGN_SCAN_TIMEOUT_S`.
