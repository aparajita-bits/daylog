#!/usr/bin/env python3
"""Claude Code SessionStart/Stop/SessionEnd hook -> daylog auto-capture.

Installed into ~/.claude/settings.json by hooks/install_hooks.py. Must never
block or slow down Claude Code: every failure is caught, logged, and the
script always exits 0.

Invoked as:
    python3 claude_session.py session-start       (stdin: hook JSON payload)
    python3 claude_session.py user-prompt-submit  (stdin: hook JSON payload)
    python3 claude_session.py stop                (stdin: hook JSON payload)
    python3 claude_session.py session-end         (stdin: hook JSON payload)

Design note: `Stop` fires once per turn (every time Claude finishes
responding), not once per session -- `SessionEnd` is the once-per-session
event. A session can also be kept open indefinitely (across days) without
ever hitting SessionEnd. So capture can't wait for either "the session
ended" or "the whole session's duration at once" -- instead every `stop`
incrementally flushes elapsed time into the state file and upserts today's
(or spanned days') daylog entry, splitting at local midnight. `session-end`
just runs one final flush and cleans up the marker.

Two flush points per turn, treated differently:
  - `user-prompt-submit` -> the gap since the *previous* Stop is "waiting on
    the user" (reading, thinking, typing). Idle-filtered: a gap over
    IDLE_CUTOFF_MIN is assumed to be a real break (lunch, overnight) and
    discarded rather than counted as work.
  - `stop` -> the gap since the *matching* UserPromptSubmit is Claude
    actively responding (which can legitimately run long with extensive
    tool calls) and is always counted in full, no matter how long.
This mirrors backfill.py's inter-message idle-cutoff logic, just applied at
turn granularity instead of message granularity (Stop hooks don't have
per-message timestamps to work with without re-parsing the transcript on
every turn).
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, datetime, time, timedelta
from pathlib import Path

# Make the sibling `daylog` package importable regardless of which python3 ran this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DAYLOG_HOME = Path(os.environ.get("DAYLOG_HOME", "~/.daylog")).expanduser()
STATE_DIR = DAYLOG_HOME / "state"
ERROR_LOG = DAYLOG_HOME / "hook-errors.log"

# A gap between two consecutive Stop events longer than this means the user
# stepped away (lunch, overnight, laptop closed) rather than actively
# working -- that gap doesn't count as active time. Mirrors
# daylog/backfill.py's IDLE_CUTOFF_MIN so live capture and backfill agree.
IDLE_CUTOFF_MIN = 15


def _log_error(context: str, exc: BaseException) -> None:
    try:
        DAYLOG_HOME.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG, "a") as f:
            f.write(f"{datetime.now().isoformat()} [{context}] {exc!r}\n")
            f.write(traceback.format_exc() + "\n")
    except Exception:
        pass  # even error logging must never crash the hook


def _load_threshold_and_ignores() -> tuple[int, list[str]]:
    try:
        from daylog.config import load_config

        cfg = load_config()
        cc = cfg.get("claude_capture", {})
        return int(cc.get("threshold_min", 10)), list(cc.get("ignore_dirs", []))
    except Exception:
        return 10, []


def _session_summary(transcript_path: str) -> str:
    """Best-effort one-line summary for the title. Prefers Claude Code's own
    AI-generated session title (clean, human-written) over the raw first user
    message, which is often a pasted error blob, screenshot path, or otherwise
    not standup-readable. Falls back to the first message with whitespace
    collapsed if no ai-title record exists yet. Called at most once per
    session (cached in state["title"]) since transcripts can be multi-MB.
    """
    first_prompt = ""
    ai_title = None
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not first_prompt and (rec.get("type") == "user" or rec.get("role") == "user"):
                    message = rec.get("message", rec)
                    content = message.get("content")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        text = " ".join(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    else:
                        text = ""
                    first_prompt = text.strip()
                if rec.get("type") == "ai-title" and rec.get("aiTitle"):
                    ai_title = rec["aiTitle"]
    except Exception:
        pass

    if ai_title:
        return ai_title
    return " ".join(first_prompt.split())


def handle_session_start(payload: dict) -> None:
    """Claude Code fires SessionStart again on `--resume`/`--continue` with
    the *same* session_id, not just on a brand-new session. A blind overwrite
    here would wipe day_minutes/entry_ids for a session already accumulating
    time, forking a second disconnected entry on the next flush while
    orphaning the first at whatever duration it last had. So: merge-preserve
    whatever's already on disk for this session_id, only resetting the
    in-progress segment clock (the gap during the resume itself -- laptop
    closed, time between sessions -- must not be counted as active work,
    same idle philosophy as _flush's IDLE_CUTOFF_MIN)."""
    session_id = payload.get("session_id") or "unknown"
    cwd = payload.get("cwd") or str(Path.cwd())
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = STATE_DIR / f"{session_id}.json"
    now = datetime.now().astimezone().isoformat()

    existing = None
    if state_path.exists():
        try:
            with open(state_path) as f:
                existing = json.load(f)
        except Exception:
            existing = None  # corrupt file -- fall through to fresh state

    if existing and existing.get("session_id") == session_id:
        existing["cwd"] = cwd
        existing["project"] = Path(cwd).name or existing.get("project", "unknown-project")
        existing["segment_start"] = now
        existing["transcript_path"] = payload.get("transcript_path") or existing.get("transcript_path")
        state = existing
    else:
        state = {
            "session_id": session_id,
            "cwd": cwd,
            "project": Path(cwd).name or "unknown-project",
            "start_ts": now,
            "segment_start": now,
            "transcript_path": payload.get("transcript_path"),
            "title": None,
            "day_minutes": {},
            "day_start": {},
            "entry_ids": {},
        }

    with open(state_path, "w") as f:
        json.dump(state, f)


def _split_into_day_chunks(start: datetime, end: datetime) -> list[tuple[date, datetime, datetime]]:
    """Split [start, end) into per-calendar-day pieces so a segment that
    crosses local midnight gets attributed to each day it actually touched."""
    chunks = []
    cur = start
    while cur.date() < end.date():
        next_midnight = datetime.combine(cur.date() + timedelta(days=1), time.min, tzinfo=cur.tzinfo)
        chunks.append((cur.date(), cur, next_midnight))
        cur = next_midnight
    chunks.append((cur.date(), cur, end))
    return chunks


def _flush(
    state: dict, now: datetime, threshold_min: int, ignore_dirs: list[str], idle_sensitive: bool
) -> None:
    """Account for elapsed time since state['segment_start'], upserting a
    coding entry per day touched. Always advances segment_start to `now`,
    even when the gap is discarded as idle -- an idle gap should reset the
    clock, not be retried on the next flush.

    `idle_sensitive=True` (called from user-prompt-submit, i.e. the gap since
    Claude last finished responding) discards gaps over IDLE_CUTOFF_MIN as a
    real break. `idle_sensitive=False` (called from stop, i.e. the gap since
    the user's prompt landed) counts the full gap regardless of length --
    Claude actually working can legitimately take a while.
    """
    segment_start = datetime.fromisoformat(state["segment_start"])
    if now <= segment_start:
        return

    gap_min = (now - segment_start).total_seconds() / 60
    cwd = state.get("cwd", "")
    if (idle_sensitive and gap_min > IDLE_CUTOFF_MIN) or any(
        ignored and ignored in cwd for ignored in ignore_dirs
    ):
        state["segment_start"] = now.isoformat()
        return

    from daylog.models import Entry
    from daylog.store import append_entry, update_entry

    day_minutes = state.setdefault("day_minutes", {})
    day_start = state.setdefault("day_start", {})
    entry_ids = state.setdefault("entry_ids", {})

    for day, chunk_start, chunk_end in _split_into_day_chunks(segment_start, now):
        minutes = (chunk_end - chunk_start).total_seconds() / 60
        if minutes <= 0:
            continue
        key = day.isoformat()
        day_minutes[key] = day_minutes.get(key, 0.0) + minutes
        day_start.setdefault(key, chunk_start.isoformat())
        total = day_minutes[key]

        entry_id = entry_ids.get(key)
        if entry_id:
            update_entry(entry_id, day, duration_min=round(total))
            continue
        if total < threshold_min:
            continue

        if state.get("title") is None:
            transcript_path = state.get("transcript_path")
            state["title"] = _session_summary(transcript_path) if transcript_path else ""

        summary = state["title"]
        title = f"Claude Code: {state.get('project', 'unknown-project')}"
        if summary:
            title += f" — {summary[:80]}"

        entry = Entry(
            ts=datetime.fromisoformat(day_start[key]),
            duration_min=round(total),
            category="coding",
            source="claude-code",
            title=title,
            tags=[f"session:{state['session_id']}", state.get("project", "unknown-project")],
        )
        append_entry(entry, day=day)
        entry_ids[key] = entry.id

    state["segment_start"] = now.isoformat()


def handle_user_prompt_submit(payload: dict) -> None:
    session_id = payload.get("session_id") or "unknown"
    state_path = STATE_DIR / f"{session_id}.json"
    if not state_path.exists():
        return  # no matching SessionStart marker, nothing to flush from

    with open(state_path) as f:
        state = json.load(f)

    threshold_min, ignore_dirs = _load_threshold_and_ignores()
    _flush(state, datetime.now().astimezone(), threshold_min, ignore_dirs, idle_sensitive=True)

    with open(state_path, "w") as f:
        json.dump(state, f)


def handle_stop(payload: dict) -> None:
    session_id = payload.get("session_id") or "unknown"
    state_path = STATE_DIR / f"{session_id}.json"
    if not state_path.exists():
        return  # no matching SessionStart marker, nothing to flush from

    with open(state_path) as f:
        state = json.load(f)

    threshold_min, ignore_dirs = _load_threshold_and_ignores()
    _flush(state, datetime.now().astimezone(), threshold_min, ignore_dirs, idle_sensitive=False)

    with open(state_path, "w") as f:
        json.dump(state, f)


def handle_session_end(payload: dict) -> None:
    session_id = payload.get("session_id") or "unknown"
    state_path = STATE_DIR / f"{session_id}.json"
    if not state_path.exists():
        return

    with open(state_path) as f:
        state = json.load(f)

    threshold_min, ignore_dirs = _load_threshold_and_ignores()
    _flush(state, datetime.now().astimezone(), threshold_min, ignore_dirs, idle_sensitive=False)

    try:
        state_path.unlink()
    except Exception:
        pass


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as exc:
        _log_error("stdin-parse", exc)
        payload = {}

    try:
        if event == "session-start":
            handle_session_start(payload)
        elif event == "user-prompt-submit":
            handle_user_prompt_submit(payload)
        elif event == "stop":
            handle_stop(payload)
        elif event == "session-end":
            handle_session_end(payload)
    except Exception as exc:
        _log_error(event or "unknown-event", exc)


if __name__ == "__main__":
    main()
    sys.exit(0)
