"""The Entry data model — one line of JSONL per logged block of time."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

SOURCES = (
    "manual",
    "claude-code",
    "jira",
    "gapfill",
    "calendar",
    "backfill-calendar",
    "backfill-claude",
    "backfill-jira",
)


def new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Entry:
    ts: datetime
    duration_min: int
    category: str
    source: str
    title: str
    id: str = field(default_factory=new_id)
    tags: list[str] = field(default_factory=list)
    jira: Optional[str] = None
    needs_review: bool = False
    absorbed: bool = False
    event_uid: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "duration_min": self.duration_min,
            "category": self.category,
            "source": self.source,
            "title": self.title,
            "tags": self.tags,
            "jira": self.jira,
        }
        if self.needs_review:
            d["needs_review"] = True
        if self.absorbed:
            d["absorbed"] = True
        if self.event_uid:
            d["event_uid"] = self.event_uid
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entry":
        return cls(
            id=d.get("id") or new_id(),
            ts=datetime.fromisoformat(d["ts"]),
            duration_min=int(d["duration_min"]),
            category=d["category"],
            source=d["source"],
            title=d["title"],
            tags=list(d.get("tags") or []),
            jira=d.get("jira"),
            needs_review=bool(d.get("needs_review", False)),
            absorbed=bool(d.get("absorbed", False)),
            event_uid=d.get("event_uid"),
        )

    @property
    def end_ts(self) -> datetime:
        from datetime import timedelta

        return self.ts + timedelta(minutes=self.duration_min)


@dataclass
class Note:
    text: str
    id: str = field(default_factory=new_id)
    created_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    done: bool = False
    done_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "done": self.done,
        }
        if self.done_at:
            d["done_at"] = self.done_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Note":
        return cls(
            id=d.get("id") or new_id(),
            text=d["text"],
            created_at=datetime.fromisoformat(d["created_at"]),
            done=bool(d.get("done", False)),
            done_at=datetime.fromisoformat(d["done_at"]) if d.get("done_at") else None,
        )
