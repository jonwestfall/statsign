from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


@dataclass(slots=True)
class StyleOptions:
    font_family: str = ""
    headline_size: int = 86
    message_size: int = 42
    footer_size: int = 20
    alignment: str = "left"
    padding: int = 18
    invert: bool = False
    show_updated_timestamp: bool = True
    show_border: bool = True
    debug_boxes: bool = False
    icon_dither: bool = True


@dataclass(slots=True)
class SignState:
    status: str = "In office"
    message: str = ""
    location: str = ""
    return_time: str = ""
    layout: str = "headline"
    icon: str = ""
    image: str = ""
    variables: dict[str, str] = field(default_factory=dict)
    style: StyleOptions = field(default_factory=StyleOptions)


def state_to_dict(state: SignState) -> dict[str, Any]:
    payload = asdict(state)
    payload["style"] = asdict(state.style)
    return payload


class StyleInput(BaseModel):
    font_family: str = ""
    headline_size: int = Field(default=86, ge=16, le=220)
    message_size: int = Field(default=42, ge=12, le=180)
    footer_size: int = Field(default=20, ge=8, le=80)
    alignment: str = Field(default="left", pattern="^(left|center|right)$")
    padding: int = Field(default=18, ge=0, le=100)
    invert: bool = False
    show_updated_timestamp: bool = True
    show_border: bool = True
    debug_boxes: bool = False
    icon_dither: bool = True


class StateInput(BaseModel):
    status: str = "In office"
    message: str = ""
    location: str = ""
    return_time: str = ""
    layout: str = Field(default="headline", pattern="^(headline|split|badge|designer)$")
    icon: str = ""
    image: str = ""
    variables: dict[str, str] = Field(default_factory=dict)
    style: StyleInput = Field(default_factory=StyleInput)


class PresetInput(StateInput):
    id: str | None = None
    name: str


DEFAULT_PRESETS: list[dict[str, Any]] = [
    {
        "id": "in-office",
        "name": "In office",
        "status": "In Office",
        "message": "Drop by if the door is open.",
        "layout": "headline",
        "icon": "builtin:office",
    },
    {
        "id": "in-class",
        "name": "In class",
        "status": "Teaching",
        "message": "In class now. Back around {return_time}",
        "return_time": "2:15 PM",
        "layout": "split",
        "icon": "builtin:class",
    },
    {
        "id": "in-meeting",
        "name": "In meeting",
        "status": "In a Meeting",
        "message": "Please send a message and I'll reply after {return_time}",
        "return_time": "11:30 AM",
        "layout": "badge",
        "icon": "builtin:meeting",
    },
    {
        "id": "back-at-time",
        "name": "Back at time",
        "status": "Be Right Back",
        "message": "Back at {return_time}",
        "return_time": "3:00 PM",
        "layout": "split",
        "icon": "builtin:away",
    },
    {
        "id": "out-for-lunch",
        "name": "Out for lunch",
        "status": "Lunch Break",
        "message": "Out for lunch. Back by {return_time}",
        "return_time": "1:00 PM",
        "layout": "headline",
        "icon": "builtin:lunch",
    },
]


class PresetStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_atomic(DEFAULT_PRESETS)

    def list(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return DEFAULT_PRESETS.copy()

    def create(self, payload: PresetInput) -> dict[str, Any]:
        presets = self.list()
        new_id = payload.id or self._generate_id(payload.name, presets)
        if any(p.get("id") == new_id for p in presets):
            raise ValueError(f"Preset with id '{new_id}' already exists")
        record = payload.model_dump()
        record["id"] = new_id
        presets.append(record)
        self._write_atomic(presets)
        return record

    def update(self, preset_id: str, payload: PresetInput) -> dict[str, Any]:
        presets = self.list()
        for idx, preset in enumerate(presets):
            if preset.get("id") == preset_id:
                record = payload.model_dump()
                record["id"] = preset_id
                presets[idx] = record
                self._write_atomic(presets)
                return record
        raise KeyError(preset_id)

    def delete(self, preset_id: str) -> None:
        presets = self.list()
        filtered = [p for p in presets if p.get("id") != preset_id]
        if len(filtered) == len(presets):
            raise KeyError(preset_id)
        self._write_atomic(filtered)

    def get(self, preset_id: str) -> dict[str, Any]:
        for preset in self.list():
            if preset.get("id") == preset_id:
                return preset
        raise KeyError(preset_id)

    def _generate_id(self, name: str, presets: list[dict[str, Any]]) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "preset"
        candidate = slug
        existing = {p.get("id") for p in presets}
        while candidate in existing:
            candidate = f"{slug}-{uuid4().hex[:6]}"
        return candidate

    def _write_atomic(self, payload: list[dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def apply_state_input(payload: StateInput) -> SignState:
    style = StyleOptions(**payload.style.model_dump())
    return SignState(
        status=payload.status,
        message=payload.message,
        location=payload.location,
        return_time=payload.return_time,
        layout=payload.layout,
        icon=payload.icon,
        image=payload.image,
        variables=payload.variables,
        style=style,
    )


def state_from_dict(payload: dict[str, Any]) -> SignState:
    state_input = StateInput(**payload)
    return apply_state_input(state_input)
