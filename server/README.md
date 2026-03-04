# Statsign Server

Local web + BLE controller for the Statsign 5.79" display firmware.

## Features
- Rich sign editor on `/` with large typography, layout selector (`headline`, `split`, `badge`), icon picker, advanced styling options, live preview, and BLE push.
- Preset manager on `/presets` with runtime CRUD backed by `server/data/presets.json`.
- Preview endpoint at `/preview.png` (exact 800x272 1bpp render).
- BLE push pipeline unchanged (`BEGIN` + framebuffer + `END`) plus `CLEAR` and `DEMO` controls.
- State and presets persisted as JSON files with atomic writes.
- Builtin icon refs (`builtin:<name>`) and uploaded image refs (`upload:<filename>`).

## Important MVP warning
> ⚠️ There is **no authentication** on the preset/admin endpoints in this MVP. Only run this server on trusted networks.

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

Open `http://127.0.0.1:8000/`.

## Presets
Presets are stored in `server/data/presets.json` and seeded with defaults if missing:
- In office
- In class
- In meeting
- Back at time
- Out for lunch

Preset API:
- `GET /api/presets`
- `POST /api/presets`
- `PUT /api/presets/{id}`
- `DELETE /api/presets/{id}`
- `POST /api/presets/{id}/apply`

## State model and placeholders
`POST /api/state` accepts the old minimal shape (`status`, `message`, `location`) and the extended shape:
- `status`, `message`, `location`, `return_time`
- `layout`
- `icon`
- `variables` dictionary
- `style` options (`headline_size`, `message_size`, `footer_size`, `padding`, `alignment`, `invert`, `show_border`, `show_updated_timestamp`, `debug_boxes`, `icon_dither`)

Placeholders in `status`/`message` support keys like `{time}`, `{updated}`, `{location}`, `{return_time}`, and custom entries from `variables`.

## Icons and uploads
Builtin icons come from `server/assets/icons/*.png` when present, with programmatic fallbacks for:
`meeting`, `class`, `office`, `lunch`, `away`, `phone`, `travel`.

Upload endpoint:
- `POST /api/upload` with raw image body and headers `Content-Type: image/png|image/jpeg|image/bmp|image/webp` plus optional `X-Filename`
- Saved to `server/data/uploads/`
- Served at `GET /uploads/{filename}`
- Referenced in state/presets as `upload:<filename>`

## Configuration
Environment variables:
- `STATSIGN_DEVICE_NAME`
- `STATSIGN_CHUNK_SIZE`
- `STATSIGN_ACK_EVERY`
- `STATSIGN_WRITE_RESPONSE`
- `STATSIGN_SCAN_TIMEOUT_S`
- `STATSIGN_CONNECT_TIMEOUT_S`
- `STATSIGN_PUSH_DONE_TIMEOUT_S`
- `STATSIGN_ACK_TIMEOUT_S`
- `STATSIGN_TTF_PATH`
- `STATSIGN_STATE_FILE`
- `STATSIGN_PRESETS_FILE`
- `STATSIGN_UPLOADS_DIR`
- `STATSIGN_BUILTIN_ICONS_DIR`

## Troubleshooting
### macOS Bluetooth permissions
1. Open **System Settings → Privacy & Security → Bluetooth**.
2. Ensure your terminal app (Terminal/iTerm/IDE) is allowed.
3. Restart terminal after changing permissions.

### Windows notes
- Use Python 3.11+.
- Make sure Bluetooth is enabled and the ESP32 is advertising.
- If discovery is flaky, increase `STATSIGN_SCAN_TIMEOUT_S`.
