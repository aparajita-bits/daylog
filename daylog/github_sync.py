"""GitHub PR sync: pulls PRs authored, reviewed, and commented on since a
given date via the `gh` CLI (no MCP needed — `gh` is a plain, already-
authenticated CLI) and logs each as its own entry, on the day it actually
happened. Runs automatically as part of `dl checkpoint` (today only); pass
an earlier date via `dl github-sync --since` to backfill.

Authored/reviewed/commented are tracked as separate facts even for the same
PR — opening a PR, reviewing someone else's, and leaving a comment are
different pieces of work with different durations — so a PR touched in more
than one of those ways the same day can legitimately produce more than one
entry. Each action type is deduped independently via a suffixed event_uid
(`{pr_url}#authored` / `#reviewed` / `#commented`), so re-running sync never
duplicates any one of them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import date, datetime, timedelta
from typing import Optional

from daylog import store
from daylog.models import Entry


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def fetch_reviewed_prs(day: date, timeout_sec: int = 20) -> list[dict]:
    """Best-effort: PRs the authenticated `gh` user reviewed on/after `day`.
    Returns [] on any failure (gh missing, not authenticated, network error,
    timeout) rather than raising — this must never block the checkpoint flow.

    Uses `--updated >=day`, i.e. "since the start of today" — correct for the
    same-day checkpoint use case this is built for, not a general date-range
    query (a PR updated yesterday and again today would still show up).
    """
    if not _gh_available():
        return []
    try:
        result = subprocess.run(
            [
                "gh",
                "search",
                "prs",
                "--reviewed-by",
                "@me",
                "--updated",
                f">={day.isoformat()}",
                "--json",
                "repository,title,url,updatedAt,number",
                "--limit",
                "50",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def fetch_authored_prs(day: date, timeout_sec: int = 20) -> list[dict]:
    """Best-effort: PRs the authenticated `gh` user opened on/after `day`.
    Same failure/return-shape contract as fetch_reviewed_prs."""
    if not _gh_available():
        return []
    try:
        result = subprocess.run(
            [
                "gh",
                "search",
                "prs",
                "--author",
                "@me",
                "--updated",
                f">={day.isoformat()}",
                "--json",
                "repository,title,url,updatedAt,number",
                "--limit",
                "50",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return []


def fetch_review_comments(day: date, timeout_sec: int = 20) -> list[dict]:
    """Best-effort: PRs the authenticated `gh` user left a comment on (as
    opposed to a formal review) on/after `day`. `gh search prs` has no
    "commented" filter, so this goes through `gh api`'s issue/PR search
    instead, which supports a `commenter:` qualifier — GitHub's search API
    doesn't guarantee a clean separation between "review comment" and
    "general PR conversation comment", so this may occasionally overlap with
    fetch_reviewed_prs for the same PR on the same day; that's fine, they're
    deduped independently by action-suffixed event_uid regardless. Same
    failure/return-shape contract as fetch_reviewed_prs."""
    if not _gh_available():
        return []
    query = f"commenter:@me type:pr updated:>={day.isoformat()}"
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "search/issues",
                "-f",
                f"q={query}",
                "--jq",
                ".items",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        items = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    # Normalize the issues-search shape (repository_url, html_url, number,
    # title) to the same repository/title/url/number shape the two `gh
    # search prs`-backed fetchers already return, so sync_prs can treat all
    # three uniformly.
    normalized = []
    for item in items:
        repo_url = item.get("repository_url", "")
        name_with_owner = "/".join(repo_url.rstrip("/").split("/")[-2:]) if repo_url else ""
        normalized.append(
            {
                "number": item.get("number"),
                "title": item.get("title", ""),
                "url": item.get("html_url"),
                "repository": {"nameWithOwner": name_with_owner},
            }
        )
    return normalized


def _make_entry(pr: dict, action: str, verb: str, category: str, duration_min: int) -> Optional[Entry]:
    url = pr.get("url")
    if not url:
        return None
    repo = (pr.get("repository") or {}).get("nameWithOwner", "")
    number = pr.get("number")
    title = f"{verb} PR #{number}: {pr.get('title', '')}" + (f" ({repo})" if repo else "")

    # Land the entry on the day the PR was actually touched (its real
    # updatedAt), not "now" -- matters for backfill: `sync_prs` can be
    # called with a `day` far in the past (see `dl github-sync --since`),
    # and `gh search`'s `--updated >=day` returns everything from `day`
    # through today, spanning many different actual days.
    ts = datetime.now().astimezone()
    updated_raw = pr.get("updatedAt")
    if updated_raw:
        try:
            ts = datetime.fromisoformat(updated_raw.replace("Z", "+00:00")).astimezone()
        except ValueError:
            pass

    return Entry(
        ts=ts,
        duration_min=duration_min,
        category=category,
        source="github",
        title=title,
        event_uid=f"{url}#{action}",
        needs_review=True,  # duration is a guess — GitHub doesn't report time spent
    )


def sync_prs(day: date, cfg: dict) -> list[Entry]:
    """Pulls PRs authored, reviewed, and commented on since `day` and logs
    each under the day it actually happened (see _make_entry). `day` can be
    today (the normal checkpoint use) or a date in the past — `gh search`'s
    `--updated >=day` is open-ended, so a single call with an older `day`
    naturally backfills everything since then across however many days that
    spans (see `dl github-sync --since`)."""
    gh_cfg = cfg.get("github_sync", {})
    if not gh_cfg.get("enabled", True):
        return []

    timeout_sec = gh_cfg.get("timeout_sec", 20)
    today = date.today()
    existing_uids: set[str] = set()
    d = day
    while d <= today:
        existing_uids.update(e.event_uid for e in store.read_entries(d) if e.event_uid)
        d += timedelta(days=1)

    buckets = [
        (
            fetch_authored_prs(day, timeout_sec=timeout_sec),
            "authored",
            "Opened",
            "coding",
            gh_cfg.get("authored_duration_min", 30),
        ),
        (
            fetch_reviewed_prs(day, timeout_sec=timeout_sec),
            "reviewed",
            "Reviewed",
            "review",
            gh_cfg.get("review_duration_min", 20),
        ),
        (
            fetch_review_comments(day, timeout_sec=timeout_sec),
            "commented",
            "Commented on",
            "review",
            gh_cfg.get("comment_duration_min", 10),
        ),
    ]

    new_entries = []
    for prs, action, verb, category, duration_min in buckets:
        for pr in prs:
            entry = _make_entry(pr, action, verb, category, duration_min)
            if entry is None or entry.event_uid in existing_uids:
                continue  # idempotent: keyed on {pr_url}#{action}, re-running never duplicates
            store.append_entry(entry, day=entry.ts.date())
            new_entries.append(entry)
            existing_uids.add(entry.event_uid)

    return new_entries
