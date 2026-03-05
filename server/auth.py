from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class AuthTokenRecord:
    id: str
    name: str
    prefix: str
    token_hash: str
    created_at: str
    last_used_at: str | None = None


class AuthTokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: list[AuthTokenRecord] = []
        self.load()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def load(self) -> None:
        if not self.path.exists():
            self._records = []
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            rows = payload.get("tokens", []) if isinstance(payload, dict) else []
            self._records = [AuthTokenRecord(**row) for row in rows]
        except Exception:
            self._records = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = {"tokens": [asdict(record) for record in self._records]}
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def create(self, name: str) -> tuple[AuthTokenRecord, str]:
        raw = f"stsgn_{secrets.token_urlsafe(32)}"
        token_id = secrets.token_hex(8)
        now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        record = AuthTokenRecord(
            id=token_id,
            name=name.strip() or "API token",
            prefix=raw[:12],
            token_hash=self._hash_token(raw),
            created_at=now,
        )
        self._records.append(record)
        self.save()
        return record, raw

    def list(self) -> list[dict]:
        return [
            {
                "id": record.id,
                "name": record.name,
                "prefix": record.prefix,
                "created_at": record.created_at,
                "last_used_at": record.last_used_at,
            }
            for record in self._records
        ]

    def delete(self, token_id: str) -> bool:
        idx = next((i for i, record in enumerate(self._records) if record.id == token_id), -1)
        if idx < 0:
            return False
        self._records.pop(idx)
        self.save()
        return True

    def verify(self, token: str) -> bool:
        incoming_hash = self._hash_token(token)
        now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        dirty = False
        matched = False
        for record in self._records:
            if hmac.compare_digest(record.token_hash, incoming_hash):
                record.last_used_at = now
                dirty = True
                matched = True
                break
        if dirty:
            self.save()
        return matched
