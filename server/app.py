from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from assets import list_builtin_icons
from ble_client import BleSignClient
from config import Settings, load_settings
from presets import PresetInput, PresetStore, SignState, StateInput, state_from_dict, state_to_dict
from render import image_to_png_bytes, render_framebuffer

settings: Settings = load_settings()
app = FastAPI(title="Statsign Server", version=settings.app_version)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
ble = BleSignClient(settings)
push_lock = asyncio.Lock()
preset_store = PresetStore(settings.presets_file)

settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.builtins_dir.mkdir(parents=True, exist_ok=True)
if settings.uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")

state = SignState()
last_push_at: str | None = None
last_error: str | None = None


def _write_atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_state() -> None:
    global state
    if not settings.state_file.exists():
        return
    try:
        saved = json.loads(settings.state_file.read_text(encoding="utf-8"))
        state = state_from_dict(saved)
    except Exception:
        pass


def _save_state() -> None:
    _write_atomic_json(settings.state_file, state_to_dict(state))


def _upload_files() -> list[str]:
    files = []
    for path in settings.uploads_dir.glob("*"):
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            files.append(path.name)
    return sorted(files)


_load_state()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "state": state_to_dict(state),
            "device_name": settings.ble_device_name,
            "builtin_icons": list_builtin_icons(settings.builtins_dir),
            "uploads": _upload_files(),
        },
    )


@app.get("/presets", response_class=HTMLResponse)
async def presets_page(request: Request):
    return templates.TemplateResponse("presets.html", {"request": request, "warning": "MVP: no authentication enabled."})


@app.get("/preview.png")
async def preview_png():
    img, _ = render_framebuffer(
        state,
        settings.display_width,
        settings.display_height,
        settings.ttf_path,
        uploads_dir=settings.uploads_dir,
        icons_dir=settings.builtins_dir,
    )
    return Response(content=image_to_png_bytes(img), media_type="image/png")


@app.get("/api/health")
async def health():
    return {
        "version": settings.app_version,
        "device_name": settings.ble_device_name,
        "last_push_timestamp": last_push_at,
        "last_error": last_error,
    }


@app.get("/api/state")
async def get_state():
    return {"ok": True, "state": state_to_dict(state)}


@app.post("/api/state")
async def set_state(payload: StateInput):
    global state
    state = state_from_dict(payload.model_dump())
    _save_state()
    return {"ok": True, "state": state_to_dict(state)}


@app.get("/api/presets")
async def list_presets():
    return {"ok": True, "presets": preset_store.list()}


@app.post("/api/presets")
async def create_preset(payload: PresetInput):
    try:
        record = preset_store.create(payload)
        return {"ok": True, "preset": record}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.put("/api/presets/{preset_id}")
async def update_preset(preset_id: str, payload: PresetInput):
    try:
        record = preset_store.update(preset_id, payload)
        return {"ok": True, "preset": record}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Preset not found") from exc


@app.delete("/api/presets/{preset_id}")
async def delete_preset(preset_id: str):
    try:
        preset_store.delete(preset_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Preset not found") from exc


@app.post("/api/presets/{preset_id}/apply")
async def apply_preset(preset_id: str):
    global state
    try:
        preset = preset_store.get(preset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Preset not found") from exc
    state = state_from_dict(preset)
    _save_state()
    return {"ok": True, "state": state_to_dict(state)}


@app.post("/api/upload")
async def upload_image(request: Request):
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext_map = {"image/png": ".png", "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/bmp": ".bmp", "image/webp": ".webp"}
    if content_type not in ext_map:
        raise HTTPException(status_code=400, detail="Set Content-Type to image/png, image/jpeg, image/bmp, or image/webp")

    original_name = request.headers.get("x-filename", "upload")
    ext = Path(original_name).suffix.lower() or ext_map[content_type]
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        ext = ext_map[content_type]

    safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", Path(original_name).stem).strip("-") or "upload"
    out_name = f"{safe_stem}-{uuid4().hex[:8]}{ext}"
    out_path = settings.uploads_dir / out_name
    content = await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="Empty upload body")
    out_path.write_bytes(content)
    ref = f"upload:{out_name}"
    return {"ok": True, "filename": out_name, "icon": ref, "image": ref, "url": f"/uploads/{out_name}"}



@app.post("/api/push")
async def push_state():
    global last_push_at, last_error
    async with push_lock:
        img, framebuffer = render_framebuffer(
            state,
            settings.display_width,
            settings.display_height,
            settings.ttf_path,
            uploads_dir=settings.uploads_dir,
            icons_dir=settings.builtins_dir,
        )
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
