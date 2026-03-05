from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
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
from render import image_to_png_bytes, render_framebuffer, render_sign_image
from schedule import (
    DEFAULT_TZ,
    ScheduleItemInput,
    ScheduleStore,
    get_active_item,
    get_next_change_time,
    get_timezone,
)

settings: Settings = load_settings()
app = FastAPI(title="Statsign Server", version=settings.app_version)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
ble = BleSignClient(settings)
push_lock = asyncio.Lock()
preset_store = PresetStore(settings.presets_file)
schedule_store = ScheduleStore(settings.schedule_file)

settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.builtins_dir.mkdir(parents=True, exist_ok=True)
if settings.uploads_dir.exists():
    app.mount("/uploads", StaticFiles(directory=str(settings.uploads_dir)), name="uploads")

state = SignState()
last_push_at: str | None = None
last_error: str | None = None
scheduler_backoff_until: datetime | None = None
current_applied_signature: str | None = None


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


def _resolve_payload_state(payload: dict) -> SignState:
    if "preset_id" in payload:
        return state_from_dict(preset_store.get(payload["preset_id"]))
    if "state" in payload:
        return state_from_dict(payload["state"])
    if "image_ref" in payload:
        return SignState(layout="designer", image=payload["image_ref"], icon=payload["image_ref"])
    raise HTTPException(status_code=400, detail="payload must include preset_id, state, or image_ref")


async def _apply_state_and_push(new_state: SignState, item_id: str | None, reason: str) -> dict:
    global state, last_push_at, last_error, current_applied_signature
    async with push_lock:
        img, framebuffer = render_framebuffer(
            new_state,
            settings.display_width,
            settings.display_height,
            settings.ttf_path,
            uploads_dir=settings.uploads_dir,
            icons_dir=settings.builtins_dir,
        )
        _ = img
        result = await ble.push_framebuffer(framebuffer, settings.display_width, settings.display_height)
        if not result.success:
            last_error = result.error
            raise RuntimeError(result.error or "BLE push failed")

        state = new_state
        _save_state()
        last_push_at = datetime.now(tz=get_timezone(settings.default_timezone)).isoformat(timespec="seconds")
        last_error = None
        signature = f"{item_id or 'manual'}:{json.dumps(state_to_dict(new_state), sort_keys=True)}"
        current_applied_signature = signature
        schedule_store.mark_last_applied(item_id, datetime.now(tz=get_timezone(settings.default_timezone)))
        return {"ok": True, "logs": result.logs, "bytes": len(framebuffer), "reason": reason}


async def _scheduler_loop() -> None:
    global scheduler_backoff_until
    tz = get_timezone(settings.default_timezone)
    while True:
        now = datetime.now(tz=tz)
        if scheduler_backoff_until and now < scheduler_backoff_until:
            await asyncio.sleep(5)
            continue

        items = schedule_store.list_items()
        decision = get_active_item(items, now=now, default_tz=settings.default_timezone)
        if decision.item and decision.payload:
            try:
                desired_state = _resolve_payload_state(decision.payload)
                signature = f"{decision.item.id}:{json.dumps(state_to_dict(desired_state), sort_keys=True)}"
                if signature != current_applied_signature:
                    await _apply_state_and_push(desired_state, decision.item.id, "scheduler")
            except Exception:
                scheduler_backoff_until = now + timedelta(seconds=60)

        nxt = get_next_change_time(items, now=now, default_tz=settings.default_timezone)
        sleep_s = 30
        if nxt:
            delta = (nxt.astimezone(tz) - datetime.now(tz=tz)).total_seconds()
            sleep_s = max(2, min(30, int(delta)))
        await asyncio.sleep(sleep_s)


@app.on_event("startup")
async def startup_scheduler() -> None:
    asyncio.create_task(_scheduler_loop())


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


@app.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request):
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "presets": preset_store.list(),
            "uploads": _upload_files(),
            "builtin_icons": list_builtin_icons(settings.builtins_dir),
            "default_timezone": settings.default_timezone or DEFAULT_TZ,
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


@app.get("/api/render-test")
async def render_test(headline_size: int = 86, message_size: int = 42):
    probe = state_from_dict(state_to_dict(state))
    probe.style.headline_size = headline_size
    probe.style.message_size = message_size
    img = render_sign_image(probe, settings.display_width, settings.display_height, settings.ttf_path, settings.uploads_dir, settings.builtins_dir)
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
    global state, current_applied_signature
    state = state_from_dict(payload.model_dump())
    _save_state()
    current_applied_signature = None
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
    try:
        return JSONResponse(await _apply_state_and_push(state, None, "manual"))
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


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


@app.get("/api/schedule")
async def list_schedule():
    return {"ok": True, "items": [item.model_dump() for item in schedule_store.list_items()]}


@app.post("/api/schedule")
async def create_schedule(payload: ScheduleItemInput):
    item = schedule_store.create(payload)
    return {"ok": True, "item": item.model_dump()}


@app.put("/api/schedule/{item_id}")
async def update_schedule(item_id: str, payload: ScheduleItemInput):
    try:
        item = schedule_store.update(item_id, payload)
        return {"ok": True, "item": item.model_dump()}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule item not found") from exc


@app.delete("/api/schedule/{item_id}")
async def delete_schedule(item_id: str):
    try:
        schedule_store.delete(item_id)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule item not found") from exc


@app.post("/api/schedule/{item_id}/enable")
async def enable_schedule(item_id: str):
    try:
        item = schedule_store.set_enabled(item_id, True)
        return {"ok": True, "item": item.model_dump()}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule item not found") from exc


@app.post("/api/schedule/{item_id}/disable")
async def disable_schedule(item_id: str):
    try:
        item = schedule_store.set_enabled(item_id, False)
        return {"ok": True, "item": item.model_dump()}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule item not found") from exc


@app.get("/api/schedule/active")
async def schedule_active():
    now = datetime.now(tz=get_timezone(settings.default_timezone))
    items = schedule_store.list_items()
    active = get_active_item(items, now=now, default_tz=settings.default_timezone)
    nxt = get_next_change_time(items, now=now, default_tz=settings.default_timezone)
    return {
        "ok": True,
        "active": active.item.model_dump() if active.item else None,
        "active_payload": active.payload,
        "active_start": active.start_time.isoformat() if active.start_time else None,
        "active_end": active.end_time.isoformat() if active.end_time else None,
        "next_change_time": nxt.isoformat() if nxt else None,
    }


@app.post("/api/schedule/run-now")
async def schedule_run_now(payload: dict):
    minutes = int(payload.get("minutes", 10))
    timezone = payload.get("timezone") or settings.default_timezone
    now = datetime.now(tz=get_timezone(timezone, settings.default_timezone))
    end = now + timedelta(minutes=minutes)
    priority = int(payload.get("priority", 1000))
    item = schedule_store.create(
        ScheduleItemInput(
            enabled=True,
            name=payload.get("name") or f"Run now {now.isoformat(timespec='minutes')}",
            type="timed_override",
            timezone=timezone,
            priority=priority,
            start_at=now.isoformat(),
            end_at=end.isoformat(),
            recurrence=None,
            payload=payload.get("payload") or {},
            notes=payload.get("notes"),
        )
    )
    revert_mode = str(payload.get("revert_mode") or "schedule")
    revert_item = None
    if revert_mode in {"previous", "preset"}:
        revert_payload: dict | None = None
        if revert_mode == "previous":
            # Last known displayed state prior to the override.
            revert_payload = {"state": state_to_dict(state)}
        elif revert_mode == "preset":
            revert_preset_id = payload.get("revert_preset_id")
            if not revert_preset_id:
                raise HTTPException(status_code=400, detail="revert_preset_id is required when revert_mode='preset'")
            try:
                _ = preset_store.get(revert_preset_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="Revert preset not found") from exc
            revert_payload = {"preset_id": revert_preset_id}

        revert_item = schedule_store.create(
            ScheduleItemInput(
                enabled=True,
                name=f"Revert for {item.id}",
                type="one_time",
                timezone=timezone,
                priority=int(payload.get("revert_priority", max(0, priority - 1))),
                start_at=end.isoformat(),
                end_at=None,
                recurrence=None,
                payload=revert_payload or {},
                notes=f"Auto-created revert target ({revert_mode})",
            )
        )

    return {
        "ok": True,
        "item": item.model_dump(),
        "revert_item": revert_item.model_dump() if revert_item else None,
        "revert_mode": revert_mode,
    }
