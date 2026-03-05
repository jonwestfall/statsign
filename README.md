# Statsign (E-Ink Status Sign)

Statsign has two halves that work together:

1. **Firmware (ESP32 + 5.79" e-ink panel)** advertises a BLE service and accepts framebuffer/control commands.
2. **Server (FastAPI web app)** renders sign content, stores presets/schedules, and pushes the rendered framebuffer to the firmware over BLE.

The web UI is the operator console, and the server API can also be called remotely (CLI/automation) using bearer tokens.

## Architecture: firmware + server flow

- You edit content in the web UI (`/`) or call the API.
- Server stores state/presets/schedules in `server/data/*.json`.
- Server renders a 1-bit framebuffer sized **800x272**.
- BLE client sends:
  - `BEGIN w h len crc`
  - framebuffer chunks over data characteristic
  - `END`
- Firmware validates size + CRC, then refreshes the e-ink display.

Firmware constants (BLE identity + protocol geometry) are defined in `firmware/statsign_579/sign_protocol.h`.【F:firmware/statsign_579/sign_protocol.h†L4-L24】
Transfer/control handling (`BEGIN`, `END`, `CLEAR`, `DEMO`, ACKs) lives in `firmware/statsign_579/ble_sign.cpp`.【F:firmware/statsign_579/ble_sign.cpp†L86-L234】

## Token-based API security

API auth is enabled for all `/api/*` endpoints except `/api/health`.

- Auth header format:
  - `Authorization: Bearer <token>`
- The UI uses a local bootstrap token (stored on disk) for browser requests.
- Remote tokens are generated/revoked from the web UI and persisted in `server/data/auth_tokens.json`.

Server-side token enforcement and token endpoints are implemented in `server/app.py` and `server/auth.py`.【F:server/app.py†L48-L547】【F:server/auth.py†L1-L103】

## Run the server

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://<server-ip>:8000/`.

## Generate a remote API token from Web UI

1. Open `/`.
2. In **Remote API tokens**, enter a label.
3. Click **Generate token**.
4. Copy the token from the one-time display box and store it securely.

That token can be used from curl, scripts, CI, Home Assistant, etc.

---

## API reference

### Health (no token required)
- `GET /api/health`

### State + render/push
- `GET /api/state`
- `POST /api/state`
- `POST /api/push`
- `POST /api/clear`
- `POST /api/demo`
- `GET /preview.png`
- `GET /api/render-test`

### Presets
- `GET /api/presets`
- `POST /api/presets`
- `PUT /api/presets/{preset_id}`
- `DELETE /api/presets/{preset_id}`
- `POST /api/presets/{preset_id}/apply`

### Uploads
- `POST /api/upload` (raw image bytes)
- `GET /uploads/{filename}`

### Scheduler
- `GET /api/schedule`
- `POST /api/schedule`
- `PUT /api/schedule/{item_id}`
- `DELETE /api/schedule/{item_id}`
- `POST /api/schedule/{item_id}/enable`
- `POST /api/schedule/{item_id}/disable`
- `GET /api/schedule/active`
- `POST /api/schedule/run-now`

### Token management
- `GET /api/tokens`
- `POST /api/tokens`
- `DELETE /api/tokens/{token_id}`

---

## curl examples (token-secured)

Set variables:

```bash
BASE_URL="http://127.0.0.1:8000"
TOKEN="stsgn_..."
AUTH_HEADER="Authorization: Bearer ${TOKEN}"
```

### 1) List presets

```bash
curl -s -H "$AUTH_HEADER" "$BASE_URL/api/presets"
```

### 2) Apply a preset then push to display

```bash
curl -s -X POST -H "$AUTH_HEADER" "$BASE_URL/api/presets/in_meeting/apply"
curl -s -X POST -H "$AUTH_HEADER" "$BASE_URL/api/push"
```

### 3) Upload an image and use it as the full-screen designer image

```bash
UPLOAD_JSON=$(curl -s -X POST \
  -H "$AUTH_HEADER" \
  -H "Content-Type: image/png" \
  -H "X-Filename: status.png" \
  --data-binary @./status.png \
  "$BASE_URL/api/upload")

IMAGE_REF=$(python -c 'import json,sys; print(json.load(sys.stdin)["image"])' <<< "$UPLOAD_JSON")

curl -s -X POST "$BASE_URL/api/state" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"layout\":\"designer\",\"status\":\"\",\"message\":\"\",\"location\":\"\",\"return_time\":\"\",\"icon\":\"$IMAGE_REF\",\"image\":\"$IMAGE_REF\",\"variables\":{},\"style\":{\"headline_size\":86,\"message_size\":42,\"footer_size\":20,\"alignment\":\"left\",\"padding\":18,\"invert\":false,\"show_updated_timestamp\":true,\"show_border\":true,\"debug_boxes\":false,\"icon_dither\":true}}"

curl -s -X POST -H "$AUTH_HEADER" "$BASE_URL/api/push"
```

### 4) Create a quick timed override from CLI

```bash
curl -s -X POST "$BASE_URL/api/schedule/run-now" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{"minutes":15,"timezone":"America/Chicago","payload":{"preset_id":"in_meeting"},"revert_mode":"schedule"}'
```

### 5) Generate another remote token from CLI (optional)

```bash
curl -s -X POST "$BASE_URL/api/tokens" \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{"name":"automation-runner"}'
```

## Web UI + token model

- The UI pages (`/`, `/presets`, `/schedule`) include the local bootstrap token and send it automatically in API calls.
- The **Remote API tokens** panel on `/` provides token creation/revocation for external callers.
- Keep the server on trusted networks, and rotate/revoke tokens if leaked.
