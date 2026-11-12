from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# How much a fact from each source is trusted when scoring answers.
SOURCE_QUALITY = {
    "pr_review": 1.0,
    "terminal": 0.9,
    "ide": 0.8,
    "runbook": 0.8,
    "chat": 0.6,
    "llm_chat": 0.5,
    "browser": 0.4,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Event:
    source: str
    content: str
    ts: str = field(default_factory=now_iso)
    meta: dict = field(default_factory=dict)

    @property
    def time(self) -> datetime:
        return datetime.fromisoformat(self.ts)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        if not isinstance(d.get("source"), str) or not isinstance(d.get("content"), str):
            raise ValueError("event needs string 'source' and 'content'")
        ts = d.get("ts") or now_iso()
        datetime.fromisoformat(ts)  # reject malformed timestamps early
        meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
        return cls(d["source"], d["content"][:20_000], ts, meta)
