"""Flat, whole-file JSON store for notes/action items — undated and
persistent, unlike Entry's per-day JSONL log (see daylog/store.py)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from daylog.config import NOTES_PATH, ensure_dirs
from daylog.models import Note


def _load() -> list[Note]:
    if not NOTES_PATH.exists():
        return []
    try:
        raw = json.loads(NOTES_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    return [Note.from_dict(d) for d in raw]


def _save(notes: list[Note]) -> None:
    ensure_dirs()
    NOTES_PATH.write_text(json.dumps([n.to_dict() for n in notes]))


def add_note(text: str) -> Note:
    notes = _load()
    note = Note(text=text)
    notes.append(note)
    _save(notes)
    return note


def list_notes(include_done: bool = False) -> list[Note]:
    notes = _load()
    if not include_done:
        notes = [n for n in notes if not n.done]
    return sorted(notes, key=lambda n: n.created_at)


def mark_done(note_id: str) -> Optional[Note]:
    notes = _load()
    found = None
    for n in notes:
        if n.id == note_id:
            n.done = True
            n.done_at = datetime.now().astimezone()
            found = n
            break
    if found is not None:
        _save(notes)
    return found
