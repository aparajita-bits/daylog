"""Keyword -> category inference and shorthand parsing for fast entry."""

from __future__ import annotations

import re
from typing import Optional

KEYWORD_CATEGORY = {
    "meeting": "meeting",
    "mtg": "meeting",
    "sync": "meeting",
    "standup": "meeting",
    "discussed": "discussion",
    "discussion": "discussion",
    "chat": "discussion",
    "fixed": "coding",
    "implemented": "coding",
    "built": "coding",
    "coded": "coding",
    "debugging": "coding",
    "reviewed": "review",
    "review": "review",
    "pr": "review",
    "incident": "firefighting",
    "firefighting": "firefighting",
    "outage": "firefighting",
    "oncall": "firefighting",
    "learning": "learning",
    "reading": "learning",
    "course": "learning",
    "admin": "admin",
    "email": "admin",
    "expenses": "admin",
}

# e.g. "45m", "1h", "1h30m", "90"
_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?$|^(\d+)$")

JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def infer_category(text: str, categories: list[str], default: Optional[str] = None) -> Optional[str]:
    lowered = text.lower()
    for word, category in KEYWORD_CATEGORY.items():
        if category in categories and re.search(rf"\b{re.escape(word)}\b", lowered):
            return category
    return default


def extract_jira_key(text: str) -> Optional[str]:
    match = JIRA_KEY_RE.search(text)
    return match.group(1) if match else None


def parse_duration_token(token: str) -> Optional[int]:
    """Parse '45', '45m', '1h', '1h30m' -> minutes."""
    token = token.strip().lower()
    match = _DURATION_RE.match(token)
    if not match or not any(match.groups()):
        return None
    hours, minutes, bare = match.groups()
    if bare is not None:
        return int(bare)
    total = 0
    if hours:
        total += int(hours) * 60
    if minutes:
        total += int(minutes)
    return total or None


def parse_shorthand(text: str, categories: list[str], default_duration: int) -> dict:
    """Parse free text like 'mtg design review 45m' or 'AXON-1234 fixed pruning bug'
    into {title, category, duration_min, jira}. Used by `dl log`, `dl fill`, `dl quicklog`.
    """
    words = text.strip().split()
    duration_min = default_duration
    remaining = []
    for w in words:
        # Require an explicit unit suffix (45m, 1h30m) — a bare number like "15"
        # is ambiguous with natural language ("since 15 minutes") and shouldn't
        # be silently swallowed as a duration.
        if w[-1] not in "hm":
            remaining.append(w)
            continue
        parsed = parse_duration_token(w.rstrip("."))
        if parsed is not None:
            duration_min = parsed
            continue
        remaining.append(w)
    title = " ".join(remaining).strip()
    jira = extract_jira_key(title)
    category = infer_category(title, categories, default=None)
    return {
        "title": title or text.strip(),
        "duration_min": duration_min,
        "category": category,
        "jira": jira,
    }
