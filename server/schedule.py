from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "America/Chicago"


def get_timezone(name: str | None, fallback: str = DEFAULT_TZ) -> ZoneInfo:
    """Return a ZoneInfo, falling back to UTC if tzdata is unavailable."""
    candidates = [name, fallback, "UTC"]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            continue
    return ZoneInfo("UTC")


class RecurrenceInput(BaseModel):
    freq: Literal["daily", "weekly", "monthly"]
    interval: int = Field(default=1, ge=1, le=365)
    byweekday: list[int] = Field(default_factory=list)
    byhour: int | None = Field(default=None, ge=0, le=23)
    byminute: int | None = Field(default=None, ge=0, le=59)
    until: str | None = None


class ScheduleItemInput(BaseModel):
    enabled: bool = True
    name: str
    type: Literal["one_time", "recurring", "timed_override", "sequence"]
    timezone: str = DEFAULT_TZ
    priority: int = 0
    start_at: str
    end_at: str | None = None
    recurrence: RecurrenceInput | None = None
    payload: dict[str, Any]
    notes: str | None = None


class ScheduleItem(ScheduleItemInput):
    id: str


@dataclass(slots=True)
class ActiveDecision:
    item: ScheduleItem | None
    payload: dict[str, Any] | None
    start_time: datetime | None
    end_time: datetime | None


class ScheduleStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_atomic({"items": [], "last_applied_item_id": None, "last_applied_at": None})

    def read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("items", [])
                raw.setdefault("last_applied_item_id", None)
                raw.setdefault("last_applied_at", None)
                return raw
        except Exception:
            pass
        return {"items": [], "last_applied_item_id": None, "last_applied_at": None}

    def list_items(self) -> list[ScheduleItem]:
        return [ScheduleItem(**item) for item in self.read().get("items", [])]

    def create(self, payload: ScheduleItemInput) -> ScheduleItem:
        data = self.read()
        item = ScheduleItem(id=uuid4().hex[:12], **payload.model_dump())
        data["items"].append(item.model_dump())
        self._write_atomic(data)
        return item

    def update(self, item_id: str, payload: ScheduleItemInput) -> ScheduleItem:
        data = self.read()
        for idx, item in enumerate(data["items"]):
            if item.get("id") == item_id:
                updated = ScheduleItem(id=item_id, **payload.model_dump())
                data["items"][idx] = updated.model_dump()
                self._write_atomic(data)
                return updated
        raise KeyError(item_id)

    def delete(self, item_id: str) -> None:
        data = self.read()
        filtered = [item for item in data["items"] if item.get("id") != item_id]
        if len(filtered) == len(data["items"]):
            raise KeyError(item_id)
        data["items"] = filtered
        self._write_atomic(data)

    def set_enabled(self, item_id: str, enabled: bool) -> ScheduleItem:
        data = self.read()
        for item in data["items"]:
            if item.get("id") == item_id:
                item["enabled"] = enabled
                self._write_atomic(data)
                return ScheduleItem(**item)
        raise KeyError(item_id)

    def mark_last_applied(self, item_id: str | None, at: datetime) -> None:
        data = self.read()
        data["last_applied_item_id"] = item_id
        data["last_applied_at"] = at.isoformat()
        self._write_atomic(data)

    def _write_atomic(self, payload: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def parse_dt(value: str, timezone: str = DEFAULT_TZ) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_timezone(timezone))
    return dt


def _normalize_now(now: datetime | None, timezone: str) -> datetime:
    if now is None:
        return datetime.now(get_timezone(timezone))
    if now.tzinfo is None:
        return now.replace(tzinfo=get_timezone(timezone))
    return now


def _duration(item: ScheduleItem) -> timedelta | None:
    if not item.end_at:
        return None
    return parse_dt(item.end_at, item.timezone) - parse_dt(item.start_at, item.timezone)


def _with_time(base: datetime, rec: RecurrenceInput | None, start: datetime) -> datetime:
    hour = rec.byhour if rec and rec.byhour is not None else start.hour
    minute = rec.byminute if rec and rec.byminute is not None else start.minute
    return base.replace(hour=hour, minute=minute, second=start.second, microsecond=0)


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return dt.replace(year=year, month=month, day=day)


def _iter_occurrences(item: ScheduleItem, horizon_end: datetime, limit: int = 2000) -> list[datetime]:
    if not item.recurrence:
        return []
    rec = item.recurrence
    start = parse_dt(item.start_at, item.timezone)
    until = parse_dt(rec.until, item.timezone) if rec.until else None
    out: list[datetime] = []

    if rec.freq == "daily":
        cursor = start
        while cursor <= horizon_end and len(out) < limit:
            occ = _with_time(cursor, rec, start)
            if occ >= start and (not until or occ <= until):
                out.append(occ)
            cursor += timedelta(days=rec.interval)
    elif rec.freq == "weekly":
        weekdays = rec.byweekday or [start.weekday()]
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        week0 = start - timedelta(days=start.weekday())
        while day <= horizon_end and len(out) < limit:
            weeks = (day - week0).days // 7
            if weeks >= 0 and weeks % rec.interval == 0 and day.weekday() in weekdays:
                occ = _with_time(day, rec, start)
                if occ >= start and (not until or occ <= until):
                    out.append(occ)
            day += timedelta(days=1)
    else:
        cursor = start
        while cursor <= horizon_end and len(out) < limit:
            occ = _with_time(cursor, rec, start)
            if occ >= start and (not until or occ <= until):
                out.append(occ)
            cursor = _add_months(cursor, rec.interval)

    return sorted(out)


def _recurring_window(item: ScheduleItem, now: datetime) -> tuple[datetime, datetime | None] | None:
    start = parse_dt(item.start_at, item.timezone)
    occs = _iter_occurrences(item, now + timedelta(days=400))
    past = [o for o in occs if o <= now]
    if not past:
        return None
    current = past[-1]
    dur = _duration(item)
    if dur:
        end = current + dur
        if now >= end:
            return None
        return current, end
    idx = occs.index(current)
    end = occs[idx + 1] if idx + 1 < len(occs) else None
    if end and now >= end:
        return None
    return current, end


def _sequence_window(item: ScheduleItem) -> tuple[datetime, datetime] | None:
    start = parse_dt(item.start_at, item.timezone)
    end = parse_dt(item.end_at, item.timezone) if item.end_at else None
    if not end:
        return None
    return start, end


def _item_window(item: ScheduleItem, now: datetime) -> tuple[datetime, datetime | None, dict[str, Any] | None] | None:
    tz_now = now.astimezone(get_timezone(item.timezone))
    if item.type in {"one_time", "timed_override"}:
        start = parse_dt(item.start_at, item.timezone)
        end = parse_dt(item.end_at, item.timezone) if item.end_at else None
        if tz_now < start or (end and tz_now >= end):
            return None
        return start, end, item.payload

    if item.type == "sequence":
        window = _sequence_window(item)
        if not window:
            return None
        start, end = window
        if tz_now < start or tz_now >= end:
            return None
        first_minutes = int(item.payload.get("first_minutes", 0))
        split = start + timedelta(minutes=first_minutes)
        if first_minutes > 0 and tz_now < split:
            return start, split, item.payload.get("first")
        return (split if first_minutes > 0 else start), end, item.payload.get("second")

    if item.type == "recurring":
        window = _recurring_window(item, tz_now)
        if not window:
            return None
        start, end = window
        return start, end, item.payload
    return None


def get_active_item(items: list[ScheduleItem], now: datetime | None = None, default_tz: str = DEFAULT_TZ) -> ActiveDecision:
    ref = _normalize_now(now, default_tz)
    candidates: list[tuple[ScheduleItem, datetime, datetime | None, dict[str, Any]]] = []
    for item in items:
        if not item.enabled:
            continue
        window = _item_window(item, ref)
        if window is None:
            continue
        start, end, payload = window
        if payload is None:
            continue
        candidates.append((item, start, end, payload))

    if not candidates:
        return ActiveDecision(item=None, payload=None, start_time=None, end_time=None)

    def sort_key(entry: tuple[ScheduleItem, datetime, datetime | None, dict[str, Any]]):
        item, start, _, _ = entry
        override_boost = 1 if item.type == "timed_override" else 0
        return (override_boost, item.priority, start, item.id)

    winner = sorted(candidates, key=sort_key, reverse=True)[0]
    item, start, end, payload = winner
    return ActiveDecision(item=item, payload=payload, start_time=start, end_time=end)


def _next_start(item: ScheduleItem, now: datetime) -> datetime | None:
    tz_now = now.astimezone(get_timezone(item.timezone))
    if item.type in {"one_time", "timed_override", "sequence"}:
        start = parse_dt(item.start_at, item.timezone)
        return start if start > tz_now else None
    if item.type == "recurring":
        occs = _iter_occurrences(item, tz_now + timedelta(days=400))
        for occ in occs:
            if occ > tz_now:
                return occ
    return None


def get_next_change_time(items: list[ScheduleItem], now: datetime | None = None, default_tz: str = DEFAULT_TZ) -> datetime | None:
    ref = _normalize_now(now, default_tz)
    active = get_active_item(items, ref, default_tz)
    future: list[datetime] = []
    if active.end_time:
        future.append(active.end_time.astimezone(ref.tzinfo))
    for item in items:
        if not item.enabled:
            continue
        start = _next_start(item, ref)
        if start:
            future.append(start.astimezone(ref.tzinfo))
    if not future:
        return None
    return min(future)
