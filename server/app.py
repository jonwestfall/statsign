from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ble_client import BleSignClient
from config import Settings, load_settings
from render import SignState, image_to_png_bytes, render_framebuffer

settings: Settings = load_settings()
app = FastAPI(title="Statsign Server", version=settings.app_version)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
ble = BleSignClient(settings)
push_lock = asyncio.Lock()


class StateInput(BaseModel):
    status: str
    message: str = ""
    location: str = ""


state = SignState()
last_push_at: str | None = None
last_error: str | None = None


def _load_state() -> None:
    if not settings.state_file.exists():
        return
    try:
        saved = json.loads(settings.state_file.read_text(encoding="utf-8"))
        state.status = saved.get("status", state.status)
        state.message = saved.get("message", state.message)
        state.location = saved.get("location", state.location)
    except Exception:
        pass


def _save_state() -> None:
    settings.state_file.parent.mkdir(parents=True, exist_ok=True)
    settings.state_file.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


_load_state()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "state": state,
            "device_name": settings.ble_device_name,
        },
    )


@app.get("/preview.png")
async def preview_png():
    img, _ = render_framebuffer(state, settings.display_width, settings.display_height, settings.ttf_path)
    return Response(content=image_to_png_bytes(img), media_type="image/png")


@app.get("/api/health")
async def health():
    return {
        "version": settings.app_version,
        "device_name": settings.ble_device_name,
        "last_push_timestamp": last_push_at,
        "last_error": last_error,
    }


@app.post("/api/state")
async def set_state(payload: StateInput):
    state.status = payload.status
    state.message = payload.message
    state.location = payload.location
    _save_state()
    return {"ok": True, "state": asdict(state)}


@app.post("/api/push")
async def push_state():
    global last_push_at, last_error
    async with push_lock:
        img, framebuffer = render_framebuffer(state, settings.display_width, settings.display_height, settings.ttf_path)
        _ = img
        result = await ble.push_framebuffer(framebuffer, settings.display_width, settings.display_height)
        if result.success:
            last_push_at = datetime.now().isoformat(timespec="seconds")
            last_error = None
            return JSONResponse({"ok": True, "logs": result.logs, "bytes": len(framebuffer)})

        last_error = result.error
        return JSONResponse({"ok": False, "error": result.error, "logs": result.logs}, status_code=500)


@app.post("/api/clear")
async def clear_sign():
    async with push_lock:
        result = await ble.send_control("CLEAR")
        if result.success:
            return {"ok": True, "logs": result.logs}
        raise HTTPException(status_code=500, detail={"error": result.error, "logs": result.logs})


@app.post("/api/demo")
async def demo_sign():
    async with push_lock:
        result = await ble.send_control("DEMO")
        if result.success:
            return {"ok": True, "logs": result.logs}
        raise HTTPException(status_code=500, detail={"error": result.error, "logs": result.logs})
