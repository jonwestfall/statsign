# Statsign Server

FastAPI + BLE bridge for the Statsign e-ink firmware.

## Security

Token-based authentication is enabled for API endpoints (`/api/*`) except health. Use:

```http
Authorization: Bearer <token>
```

Generate/revoke remote API tokens from the main controller page (`/`).

## Start

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app:app --host 0.0.0.0 --port 8000
```

See the repository root `README.md` for full firmware/server architecture, endpoint documentation, and curl examples.
