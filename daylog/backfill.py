"""dl backfill: recover the past N days so analytics work from day one.

Three sub-backfills: calendar (date-range sweep), Claude Code session history
(walks ~/.claude/projects/*/*.jsonl), and Jira (via the `/daylog-backfill-jira`
Claude Code command + `dl import-events` — kept interactive rather than
shelled out headlessly, since it reads live Jira data through the Atlassian
MCP connector and the user should see what it's about to import).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

from daylog import store
from daylog.config import DAYLOG_HOME, ensure_dirs
from daylog.models import Entry

BACKFILL_ERROR_LOG = DAYLOG_HOME / "backfill-errors.log"


def _log_backfill_error(context: str, detail: str) -> None:
    try:
        ensure_dirs()
        with open(BACKFILL_ERROR_LOG, "a") as f:
            f.write(f"{datetime.now().isoformat()} [{context}] {detail}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Calendar backfill
# ---------------------------------------------------------------------------


def backfill_calendar(start: date, end: date, cfg: dict) -> dict[date, list[Entry]]:
    from daylog.calendar_sync import calendar_sync_range

    return calendar_sync_range(start, end, cfg, source_label="backfill-calendar")


# ---------------------------------------------------------------------------
# 2. Claude Code session backfill
# ---------------------------------------------------------------------------


# A gap between two consecutive transcript messages longer than this means the
# session sat idle (laptop closed, came back the next day, etc) rather than
# being continuously worked on — that gap doesn't count as active time.
IDLE_CUTOFF_MIN = 15


def _extract_prompt_text(rec: dict) -> str:
    """Same extraction hooks/claude_session.py uses for the live Stop hook —
    duplicated rather than imported since this module must stay independent
    of the hook script's sys.path hacking.
    """
    message = rec.get("message", rec)
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        text = ""
    return text.strip()


def _collapse_whitespace(text: str) -> str:
    """So a multi-line paste doesn't break `dl day`'s table rendering or
    `dl standup`'s one-line-per-entry format."""
    return " ".join(text.split())


def _ai_summarize_prompt(first_prompt: str) -> str:
    return (
        "Summarize this Claude Code session's opening message in 6-10 words, "
        "as a standup-ready title (e.g. \"Debug API error in payment webhook\"). "
        "Output only the summary — no punctuation at the end, no preamble, no quotes.\n\n"
        f"Message:\n{first_prompt[:2000]}"
    )


def build_session_summary(first_prompt: str, ai_title: Optional[str], use_ai: bool, timeout_sec: int = 20) -> str:
    """Prefer Claude Code's own AI-generated session title (clean, human-written,
    free — no extra API call) over the raw first user message, which is often a
    pasted error blob, screenshot path, or otherwise not standup-readable.

    If `use_ai` and no ai_title exists, falls back to a headless `claude -p`
    call to summarize the raw message. Never raises — any failure there just
    falls back to the collapsed raw text, same as `use_ai=False`.
    """
    if ai_title:
        return ai_title
    if use_ai and first_prompt:
        from daylog.summary import _call_headless_claude

        summarized = _call_headless_claude(_ai_summarize_prompt(first_prompt), timeout_sec)
        if summarized:
            return _collapse_whitespace(summarized)
    return _collapse_whitespace(first_prompt)


def _scan_transcript(path: Path) -> tuple[Optional[str], list[datetime], Optional[str], str, Optional[str]]:
    session_id = None
    cwd = None
    timestamps: list[datetime] = []
    first_prompt = ""
    ai_title = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # malformed line, keep scanning the rest of the file
            session_id = session_id or rec.get("sessionId")
            cwd = cwd or rec.get("cwd")
            if not first_prompt and (rec.get("type") == "user" or rec.get("role") == "user"):
                first_prompt = _extract_prompt_text(rec)
            if rec.get("type") == "ai-title" and rec.get("aiTitle"):
                ai_title = rec["aiTitle"]  # take the latest one seen, in case it's refined mid-session
            ts_raw = rec.get("timestamp")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone()
            except ValueError:
                continue
            timestamps.append(ts)
    return session_id, sorted(timestamps), cwd, first_prompt, ai_title


def _split_into_day_chunks(start: datetime, end: datetime) -> list[tuple[date, datetime, datetime]]:
    """Split [start, end) into per-calendar-day pieces (local tz) so a gap
    that crosses midnight is attributed to each day it actually touched."""
    chunks = []
    cur = start
    while cur.date() < end.date():
        next_midnight = datetime.combine(cur.date() + timedelta(days=1), time.min, tzinfo=cur.tzinfo)
        chunks.append((cur.date(), cur, next_midnight))
        cur = next_midnight
    chunks.append((cur.date(), cur, end))
    return chunks


def _active_minutes_by_day(timestamps: list[datetime]) -> dict[date, float]:
    """Sum of inter-message gaps under IDLE_CUTOFF_MIN, split per calendar
    day -- so a session resumed across several days (or left open overnight)
    attributes each day's own active minutes to that day, rather than
    crediting (or losing) it all on the day the session first started.
    """
    minutes_by_day: dict[date, float] = {}
    for prev, curr in zip(timestamps, timestamps[1:]):
        gap_min = (curr - prev).total_seconds() / 60
        if gap_min > IDLE_CUTOFF_MIN:
            continue
        for day, chunk_start, chunk_end in _split_into_day_chunks(prev, curr):
            minutes_by_day[day] = minutes_by_day.get(day, 0.0) + (chunk_end - chunk_start).total_seconds() / 60
    return minutes_by_day


def walk_claude_sessions(days: int, threshold_min: int, projects_dir: Optional[Path] = None) -> list[dict]:
    """Scan ~/.claude/projects/*/*.jsonl for sessions touched within the last
    `days` days, broken down by calendar day. Malformed/unreadable files are
    skipped and logged, never crash the walk.

    Each returned session dict carries `day_minutes` (date -> active minutes)
    and `day_start` (date -> first timestamp seen that day) so a session
    spanning multiple days produces one row per day, not one lumped row on
    whichever day it happened to start.
    """
    projects_dir = projects_dir or (Path.home() / ".claude" / "projects")
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    sessions = []
    if not projects_dir.exists():
        return sessions

    for transcript_path in sorted(projects_dir.glob("*/*.jsonl")):
        try:
            session_id, timestamps, cwd, first_prompt, ai_title = _scan_transcript(transcript_path)
        except OSError as exc:
            _log_backfill_error(f"claude-session:{transcript_path}", repr(exc))
            continue

        if not timestamps:
            _log_backfill_error(
                f"claude-session:{transcript_path}", "no usable timestamps — skipped as malformed"
            )
            continue

        if timestamps[-1] < cutoff:
            continue  # nothing touched within the requested window at all

        day_minutes = _active_minutes_by_day(timestamps)
        day_minutes = {d: m for d, m in day_minutes.items() if m >= threshold_min and d >= cutoff.date()}
        if not day_minutes:
            continue

        day_start: dict[date, datetime] = {}
        for ts in timestamps:
            day_start.setdefault(ts.date(), ts)

        project = Path(cwd).name if cwd else transcript_path.parent.name.lstrip("-")
        sessions.append(
            {
                "session_id": session_id or transcript_path.stem,
                "project": project or "unknown-project",
                "day_minutes": day_minutes,
                "day_start": day_start,
                "first_prompt": first_prompt,
                "ai_title": ai_title,
            }
        )
    return sessions


def backfill_claude_sessions(
    days: int, cfg: dict, projects_dir: Optional[Path] = None, ai: bool = False
) -> list[Entry]:
    threshold_min = cfg["claude_capture"]["threshold_min"]
    sessions = walk_claude_sessions(days, threshold_min, projects_dir=projects_dir)
    new_entries = []
    for s in sessions:
        summary = None
        title = None
        for day, minutes in s["day_minutes"].items():
            duration_min = round(minutes)
            existing = store.find_entry_by_session(day, s["session_id"])
            if existing:
                if existing.duration_min != duration_min:
                    store.update_entry(existing.id, day, duration_min=duration_min)
                continue  # unchanged, or just topped up -- either way not a "new" entry

            if title is None:
                summary = build_session_summary(s.get("first_prompt", ""), s.get("ai_title"), use_ai=ai)
                title = f"Claude Code: {s['project']}"
                if summary:
                    title += f" — {summary[:80]}"

            entry = Entry(
                ts=s["day_start"][day],
                duration_min=duration_min,
                category="coding",
                source="backfill-claude",
                title=title,
                tags=[f"session:{s['session_id']}", s["project"]],
            )
            store.append_entry(entry, day=day)
            new_entries.append(entry)
    return new_entries


# ---------------------------------------------------------------------------
# 3. Jira backfill — see .claude/commands/daylog-backfill-jira.md
# ---------------------------------------------------------------------------


DONE_STATUS_TAG = "jira-status:done"
_DONE_KEYWORDS = ("done", "closed", "resolved", "complete")


def _is_done_action(action: str | None) -> bool:
    """Best-effort: does this transition's action text read like a
    completion (vs. e.g. "moved to In Review", "reopened")? Deliberately
    keyword-based rather than a fixed enum, since Jira workflow status names
    vary per project/team."""
    if not action:
        return False
    lowered = action.lower()
    return any(kw in lowered for kw in _DONE_KEYWORDS)


def import_jira_events(events: list[dict]) -> list[Entry]:
    """Applied by `dl import-events --source jira`. Python applies the rules
    (default 60m duration, needs_review flag, idempotency, done-status
    tagging) — the LLM only supplies the raw ticket/timestamp/action facts
    via the Atlassian MCP connector.

    Entries whose `action` reads as a completion (transitioned to
    Done/Closed/Resolved) get tagged `jira-status:done`, so `dl view` can
    show which tickets were actually closed out during a period vs. merely
    touched — this only covers Jira-linked work; entries with no ticket or
    no captured transition can't be classified either way.
    """
    new_entries = []
    for ev in events:
        key = ev.get("key")
        if not key:
            continue

        ts_raw = ev.get("transitioned_at") or ev.get("timestamp")
        ts = None
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone()
            except ValueError:
                ts = None
        ts = ts or datetime.now().astimezone()
        day = ts.date()

        dedup_tag = f"jira-backfill:{key}:{day.isoformat()}"
        if any(dedup_tag in e.tags for e in store.read_entries(day)):
            continue  # idempotent: this ticket already backfilled for this day

        action = ev.get("action")
        title = ev.get("summary") or action or f"Worked on {key}"
        tags = [dedup_tag]
        if _is_done_action(action):
            tags.append(DONE_STATUS_TAG)

        entry = Entry(
            ts=ts,
            duration_min=60,
            category="coding",
            source="backfill-jira",
            title=title,
            jira=key,
            tags=tags,
            needs_review=True,
        )
        store.append_entry(entry, day=day)
        new_entries.append(entry)
    return new_entries


# ---------------------------------------------------------------------------
# 4. Outlook calendar backend — see .claude/commands/daylog-outlook-checkpoint.md
# ---------------------------------------------------------------------------


def import_outlook_events(events: list[dict], cfg: dict) -> list[Entry]:
    """Applied by `dl import-events --source outlook`. Unlike Jira/Confluence,
    this doesn't build its own Entry — it groups raw events by the calendar
    day of their start time and hands each day's events straight to
    calendar_sync.sync_day(), reusing the exact same skip/dedup/absorb logic
    the macOS Calendar.app (eventkit) backend already uses. Outlook becomes
    just another `raw_events` producer for that shared pipeline; the only
    difference is where the events come from (Microsoft 365 MCP via a
    headless prompt, instead of the JXA script) and `source_label="outlook"`
    on the resulting entries.
    """
    from daylog.calendar_sync import sync_day

    by_day: dict[date, list[dict]] = {}
    for ev in events:
        start_raw = ev.get("start")
        if not start_raw:
            continue
        try:
            start = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone()
        except ValueError:
            continue
        by_day.setdefault(start.date(), []).append(ev)

    new_entries = []
    for day, day_events in by_day.items():
        new_entries.extend(sync_day(day, day_events, cfg, source_label="outlook"))
    return new_entries


# ---------------------------------------------------------------------------
# 5. Confluence — see .claude/commands/daylog-confluence-checkpoint.md
# ---------------------------------------------------------------------------

_CONFLUENCE_DURATION_MIN = {"edited": 25, "commented": 15}


def import_confluence_events(events: list[dict]) -> list[Entry]:
    """Applied by `dl import-events --source confluence`. Structurally the
    same shape as import_jira_events -- default duration, needs_review flag,
    idempotency via a dedup tag -- the LLM only supplies the raw page/comment
    facts via the Atlassian MCP connector's Confluence tools (this is
    interactive-only for now, not wired into the automated `dl checkpoint`
    sweep — run `/daylog-confluence-checkpoint` by hand).
    """
    new_entries = []
    for ev in events:
        page_id = ev.get("page_id")
        if not page_id:
            continue

        action = ev.get("action") or "edited"
        ts_raw = ev.get("timestamp")
        ts = None
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).astimezone()
            except ValueError:
                ts = None
        ts = ts or datetime.now().astimezone()
        day = ts.date()

        dedup_tag = f"confluence:{page_id}:{action}:{day.isoformat()}"
        if any(dedup_tag in e.tags for e in store.read_entries(day)):
            continue  # idempotent: this page/action already imported for this day

        title = ev.get("title") or f"Confluence page {page_id}"
        verb = "Commented on" if action == "commented" else "Edited"
        space = ev.get("space")
        entry = Entry(
            ts=ts,
            duration_min=_CONFLUENCE_DURATION_MIN.get(action, 20),
            category="discussion",
            source="confluence",
            title=f"{verb} {title}" + (f" ({space})" if space else ""),
            tags=[dedup_tag],
            needs_review=True,
        )
        store.append_entry(entry, day=day)
        new_entries.append(entry)
    return new_entries
