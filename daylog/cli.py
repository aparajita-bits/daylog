"""daylog CLI — `dl`. Logging must take under 5 seconds."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from daylog import gapfill, store
from daylog.config import CONFIG_PATH, load_config
from daylog.infer import extract_jira_key, infer_category, parse_shorthand
from daylog.models import Entry

app = typer.Typer(add_completion=False, help="daylog — where did your day actually go.")
console = Console()


def _parse_date(value: Optional[str]) -> date:
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


@app.command()
def log(
    text: str = typer.Argument(..., help="What you were doing"),
    duration: Optional[int] = typer.Option(None, "-d", "--duration", help="Minutes"),
    category: Optional[str] = typer.Option(None, "-c", "--category"),
    jira: Optional[str] = typer.Option(None, "--jira"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated"),
):
    """Log a manual entry. `dl log "discussed webhook retries with Priya" -d 30 -c discussion`"""
    cfg = load_config()
    categories = cfg["categories"]
    resolved_category = category or infer_category(text, categories, default="other")
    resolved_duration = duration or store.suggested_duration_min(date.today(), cfg)
    resolved_jira = jira or extract_jira_key(text)
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    entry = Entry(
        ts=datetime.now().astimezone(),
        duration_min=resolved_duration,
        category=resolved_category,
        source="manual",
        title=text,
        tags=tag_list,
        jira=resolved_jira,
    )
    store.append_entry(entry)
    console.print(f"[green]logged[/green] {entry.title} ({resolved_duration}m, {resolved_category})")


@app.command()
def jira(
    ticket: str = typer.Argument(..., help="Ticket key, e.g. AXON-1234"),
    duration: Optional[int] = typer.Option(None, "-d", "--duration"),
    text: Optional[str] = typer.Option(None, "-m", "--message"),
):
    """Shortcut: log coding time against a ticket. `dl jira AXON-1234 -d 60`"""
    cfg = load_config()
    resolved_duration = duration or store.suggested_duration_min(date.today(), cfg)
    title = text or f"Worked on {ticket}"
    entry = Entry(
        ts=datetime.now().astimezone(),
        duration_min=resolved_duration,
        category="coding",
        source="jira",
        title=title,
        tags=[],
        jira=ticket,
    )
    store.append_entry(entry)
    console.print(f"[green]logged[/green] {title} ({resolved_duration}m, {ticket})")


@app.command(name="calendar-sync")
def calendar_sync_cmd(
    from_date: Optional[str] = typer.Option(None, "--from"),
    to_date: Optional[str] = typer.Option(None, "--to"),
):
    """Pull today's (or --from/--to date range's) calendar events and log completed meetings."""
    from daylog.calendar_sync import calendar_sync, calendar_sync_range

    cfg = load_config()
    if from_date or to_date:
        start = _parse_date(from_date)
        end = _parse_date(to_date) if to_date else start
        results = calendar_sync_range(start, end, cfg)
        total_new = sum(len(v) for v in results.values())
        console.print(f"[green]calendar sync[/green]: {total_new} new entries across {len(results)} day(s)")
    else:
        new_entries = calendar_sync(date.today(), cfg)
        console.print(f"[green]calendar sync[/green]: {len(new_entries)} new entries")


@app.command(name="github-sync")
def github_sync_cmd(
    since: Optional[str] = typer.Option(
        None, "--since", help="Backfill PRs updated on/after this date (YYYY-MM-DD), instead of just today"
    ),
):
    """Pull GitHub PRs — authored, reviewed, and commented on (via `gh` CLI) — and log them.
    Each is logged under the day it actually happened, so `--since` backfills
    a whole range in one call, not just a single day."""
    from daylog.github_sync import sync_prs

    cfg = load_config()
    day = _parse_date(since) if since else date.today()
    new_entries = sync_prs(day, cfg)
    console.print(f"[green]github sync[/green]: {len(new_entries)} new entries")


@app.command()
def checkpoint(date_str: Optional[str] = typer.Option(None, "--date")):
    """End-of-workday pull: calendar (eventkit, automatic) + GitHub PRs opened/
    reviewed/commented (automatic) + Jira, and Outlook if that backend is
    configured, via headless Claude/MCP (unattended) — then regenerates the
    AI summary. Runs as part of the 17:45 launchd sweep in place of a bare
    calendar-sync."""
    from daylog.checkpoint import run_checkpoint

    d = _parse_date(date_str)
    cfg = load_config()
    result = run_checkpoint(d, cfg)
    if not result.get("enabled", True):
        console.print("[dim]checkpoint disabled in config[/dim]")
        return
    outlook_part = f" outlook_ran={result['outlook_ran']}" if "outlook_ran" in result else ""
    console.print(
        f"[green]checkpoint[/green]: calendar={result['calendar']} github={result['github']}"
        f"{outlook_part} jira_ran={result['jira_ran']}"
    )


@app.command(name="morning-brief")
def morning_brief_cmd():
    """Yesterday's AI standup, delivered to Notes (or email) — meant to be
    polled every ~15 min by a launchd job so it goes out shortly after you
    next open/wake your laptop, not at a fixed clock time. Safe to run by
    hand any time too — idempotent, no-ops if already sent today or if it's
    before `morning_brief.earliest_hour`."""
    from daylog.morning_brief import run_morning_brief

    cfg = load_config()
    result = run_morning_brief(cfg)
    if not result.get("enabled", True):
        console.print("[dim]morning-brief disabled in config[/dim]")
        return
    if result.get("sent"):
        console.print(f"[green]morning brief[/green] sent via {result['delivery']}")
    else:
        console.print(f"[dim]morning brief: {result.get('reason', 'not sent')}[/dim]")


@app.command()
def quicklog(
    text: str = typer.Argument(..., help="Free text, e.g. 'mtg design review 45m' or 'AXON-1234 fixed bug 90m'"),
    at: Optional[str] = typer.Option(
        None, "--at", help="HH:MM to backdate the entry to instead of now — e.g. filling a detected gap"
    ),
    duration: Optional[int] = typer.Option(
        None, "-d", "--duration", help="Override the parsed/guessed duration (minutes)"
    ),
):
    """Fastest possible entry point — built for macOS Shortcuts/Spotlight, not typing in a terminal.

    Parses duration, category, and jira key out of one free-text string so a single
    text field is enough. See shortcuts/README.md for wiring this up to a keyboard
    shortcut or Spotlight search. `--at`/`-d` let a caller (e.g. the desktop widget)
    backdate a gap-fill entry into a specific slot instead of "now".
    """
    cfg = load_config()
    # `-d`/`--duration` is the *fallback* default fed into parse_shorthand,
    # not a hard override -- an explicit duration token in the text itself
    # (e.g. "worked on X 30m") must still win. parsed["duration_min"]
    # already encodes that precedence correctly; do not re-apply `duration`
    # on top of it (that used to silently discard any duration the user
    # actually typed whenever the widget's gap-fill flow passed `-d`).
    default_duration = duration or store.suggested_duration_min(date.today(), cfg)
    parsed = parse_shorthand(text, cfg["categories"], default_duration)
    category = parsed["category"] or infer_category(parsed["title"], cfg["categories"], default="other")
    if at:
        h, m = map(int, at.split(":"))
        ts = datetime.now().astimezone().replace(hour=h, minute=m, second=0, microsecond=0)
    else:
        ts = datetime.now().astimezone()
    entry = Entry(
        ts=ts,
        duration_min=parsed["duration_min"],
        category=category,
        source="manual",
        title=parsed["title"],
        jira=parsed["jira"],
    )
    store.append_entry(entry)
    suffix = f" at {at}" if at else ""
    console.print(f"logged: {entry.title} ({entry.duration_min}m, {category}){suffix}")


@app.command()
def fill(
    notify: bool = typer.Option(False, "--notify", help="Send a summary notification instead of the interactive fill"),
    date_str: Optional[str] = typer.Option(None, "--date"),
):
    """Interactive gap-filler — what the 6 PM reminder opens."""
    from daylog.calendar_sync import lazy_sync_if_needed

    d = _parse_date(date_str)
    cfg = load_config()
    lazy_sync_if_needed(d, cfg)

    if notify:
        gapfill.send_fill_notification(d, cfg)
        return

    gapfill.interactive_fill(d, cfg)

    from daylog.summary import generate_summary

    generate_summary(d, cfg, ai=True)
    gapfill.send_notification("daylog", "Your day summary is ready.")


@app.command()
def summary(
    ai: bool = typer.Option(False, "--ai", help="Claude-polished version (falls back to template if unavailable)"),
    date_str: Optional[str] = typer.Option(None, "--date"),
):
    """Day summary — template version, or --ai for Claude-polished output."""
    from daylog.summary import generate_summary

    d = _parse_date(date_str)
    cfg = load_config()
    text = generate_summary(d, cfg, ai=ai)
    console.print(text)


@app.command()
def day(
    date_str: Optional[str] = typer.Option(None, "--date"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output, e.g. for the desktop widget"),
):
    """Show today's timeline + total captured vs gaps."""
    d = _parse_date(date_str)
    entries = store.read_entries(d)

    if json_output:
        import json as json_module

        from daylog.gapfill import _parse_hhmm, capture_summary, compute_gaps

        cfg = load_config()
        working_start = _parse_hhmm(cfg["working_hours"]["start"])
        working_end = _parse_hhmm(cfg["working_hours"]["end"])
        gaps = compute_gaps(entries, d, working_start, working_end, cfg["gapfill"]["min_gap_min"])
        gap_summary = capture_summary(entries, d, cfg)

        category_min: dict[str, int] = {}
        for e in entries:
            category_min[e.category] = category_min.get(e.category, 0) + e.duration_min
        payload = {
            "date": d.isoformat(),
            "total_captured_min": sum(e.duration_min for e in entries),
            "category_min": category_min,
            "unaccounted_min": gap_summary["unaccounted_min"],
            "gaps": [
                {
                    "start": start.strftime("%H:%M"),
                    "end": end.strftime("%H:%M"),
                    "span_min": int((end - start).total_seconds() // 60),
                }
                for start, end in gaps
            ],
            "entries": [
                {
                    "id": e.id,
                    "time": e.ts.strftime("%H:%M"),
                    "duration_min": e.duration_min,
                    "category": e.category,
                    "title": e.title,
                    "jira": e.jira,
                    "needs_review": e.needs_review,
                }
                for e in entries
            ],
        }
        print(json_module.dumps(payload))
        return

    if not entries:
        console.print(f"[dim]No entries for {d.isoformat()}[/dim]")
        return

    table = Table(title=f"daylog — {d.isoformat()}")
    table.add_column("Time")
    table.add_column("Dur")
    table.add_column("Category")
    table.add_column("Title")
    table.add_column("Jira")

    total = 0
    for e in entries:
        marker = "~" if e.needs_review else ""
        table.add_row(
            e.ts.strftime("%H:%M"),
            f"{e.duration_min}m{marker}",
            e.category,
            e.title,
            e.jira or "",
        )
        total += e.duration_min

    console.print(table)
    console.print(f"[bold]Total captured:[/bold] {total // 60}h{total % 60}m")


@app.command()
def standup(
    ai: bool = typer.Option(
        False, "--ai", help="AI-polished standup via headless Claude (falls back to the template on failure)"
    ),
):
    """Yesterday + today summary, copy-paste ready."""
    from daylog.summary import generate_standup

    cfg = load_config()
    console.print(generate_standup(cfg, ai=ai))


def _bar(pct: float, width: int = 24) -> str:
    filled = round(width * min(pct, 100) / 100)
    return "█" * filled + "░" * (width - filled)


def _fmt_h(minutes: int) -> str:
    return f"{minutes / 60:.1f}h"


def _render_week(stats: dict, title: str) -> None:
    console.print(f"[bold]{title}[/bold]")
    console.print(
        f"Captured {_fmt_h(stats['total_captured_min'])} / "
        f"{_fmt_h(stats['scheduled_min'])} scheduled "
        f"([bold]{stats['capture_rate']:.0f}%[/bold] capture rate)"
    )
    console.print()

    console.print("[bold]Category breakdown[/bold]")
    total = stats["total_captured_min"] or 1
    for category, minutes in sorted(stats["category_min"].items(), key=lambda kv: kv[1], reverse=True):
        pct = minutes / total * 100
        console.print(f"  {category:<14} {_bar(pct)} {pct:4.0f}%  {_fmt_h(minutes)}")
    console.print()

    console.print("[bold]Top 5 work items[/bold]")
    for key, minutes in stats["top_items"]:
        console.print(f"  {key:<20} {_fmt_h(minutes)}")
    console.print()

    console.print("[bold]Longest focus block per day[/bold]")
    for d, minutes in sorted(stats["focus_by_day"].items()):
        console.print(f"  {d.strftime('%a %m-%d')}   {_fmt_h(minutes)}")
    console.print()

    console.print("[bold]Meeting load by weekday[/bold]")
    for wd, minutes in stats["meeting_by_weekday"].items():
        console.print(f"  {wd}   {_fmt_h(minutes)}")

    if stats["backfilled"]:
        console.print()
        console.print("[yellow]Note: this week contains backfilled data — capture rate not comparable to live-tracked weeks.[/yellow]")


@app.command()
def week(
    prev: bool = typer.Option(False, "--prev", help="Show last week instead of this week"),
    compare: bool = typer.Option(False, "--compare", help="This week vs last week deltas"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output, e.g. for the desktop widget"),
):
    """This week's analytics with bar charts."""
    from daylog.analytics import compare_stats, compute_stats, load_week, stats_to_json_dict, week_bounds

    cfg = load_config()
    today = date.today()

    if json_output:
        import json as json_module

        offset = -1 if prev else 0
        monday, sunday = week_bounds(today, offset)
        stats = compute_stats(load_week(monday), cfg)
        payload = {
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            **stats_to_json_dict(stats),
        }
        print(json_module.dumps(payload))
        return

    if compare:
        this_monday, _ = week_bounds(today, 0)
        prev_monday, _ = week_bounds(today, -1)
        this_stats = compute_stats(load_week(this_monday), cfg)
        prev_stats = compute_stats(load_week(prev_monday), cfg)
        deltas = compare_stats(this_stats, prev_stats)

        console.print("[bold]This week vs last week[/bold]")
        console.print(
            f"Total: {_fmt_h(this_stats['total_captured_min'])} "
            f"({'+' if deltas['total_delta_min'] >= 0 else ''}{_fmt_h(deltas['total_delta_min'])})"
        )
        console.print(
            f"Capture rate: {this_stats['capture_rate']:.0f}% "
            f"({'+' if deltas['capture_rate_delta'] >= 0 else ''}{deltas['capture_rate_delta']:.0f}pp)"
        )
        console.print()
        console.print("[bold]Category deltas[/bold]")
        for category, delta in sorted(deltas["category_deltas"].items(), key=lambda kv: -abs(kv[1])):
            sign = "+" if delta >= 0 else ""
            console.print(f"  {category:<14} {sign}{_fmt_h(delta)}")
        return

    offset = -1 if prev else 0
    monday, sunday = week_bounds(today, offset)
    stats = compute_stats(load_week(monday), cfg)
    _render_week(stats, f"Week of {monday.isoformat()} – {sunday.isoformat()}")


@app.command()
def review(
    prev: bool = typer.Option(False, "--prev", help="Review last week instead of this week"),
    ai: bool = typer.Option(False, "--ai", help="Generate qualitative insights via headless Claude"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output, e.g. for the desktop widget"),
):
    """Weekly qualitative insights (patterns, not totals — see `dl week` for those)."""
    from daylog.analytics import week_bounds
    from daylog.review import generate_weekly_insights

    cfg = load_config()
    today = date.today()
    offset = -1 if prev else 0
    monday, _ = week_bounds(today, offset)

    insights = generate_weekly_insights(cfg, monday) if ai else None

    if json_output:
        import json as json_module
        from datetime import datetime as _datetime

        if insights is not None:
            payload = {"insights": insights, "generated_at": _datetime.now().astimezone().isoformat()}
        elif not ai:
            payload = {"insights": None, "error": "pass --ai to generate insights"}
        else:
            payload = {"insights": None, "error": "AI insights unavailable (disabled, no `claude` CLI, or the call failed/timed out)"}
        print(json_module.dumps(payload))
        return

    if insights is not None:
        console.print(insights)
    elif ai:
        console.print("[dim]AI insights unavailable — falling back to `dl week` for the numbers.[/dim]")
    else:
        console.print("[dim]Pass --ai for qualitative insights, or run `dl week` for the numbers.[/dim]")


@app.command()
def view(
    week: bool = typer.Option(False, "--week", help="This week instead of today"),
    no_open: bool = typer.Option(False, "--no-open", help="Write the HTML file without opening a browser"),
):
    """Nicely-formatted HTML report opened in your default browser: category
    stats plus AI insights (today), or with --week a day-by-day category
    trend (discussion/coding/review/etc. per weekday), where your time went
    (top tickets/projects), meeting load by weekday, longest focus block per
    day, and Jira completion (tickets closed vs. only touched this week) —
    no AI section for --week, since the pattern-spotting prose wasn't
    useful and the sections above already cover the same ground with real
    numbers. Built for the widget's expand button — cramming multi-
    paragraph text into a 300px-wide widget reads badly — but fine to run
    by hand any time."""
    from daylog.view import run_view

    cfg = load_config()
    path = run_view(cfg, week=week, open_browser=not no_open)
    console.print(f"[green]view[/green] written to {path}")


@app.command()
def edit(
    entry_id: str = typer.Argument(...),
    duration: Optional[int] = typer.Option(None, "-d", "--duration"),
    category: Optional[str] = typer.Option(None, "-c", "--category"),
    title: Optional[str] = typer.Option(None, "-t", "--title"),
    date_str: Optional[str] = typer.Option(None, "--date", help="Narrow search to this date"),
):
    """Fix a duration/category/title, e.g. `dl edit a1b2c3d4 -d 90`."""
    d = _parse_date(date_str) if date_str else None
    found = store.find_entry(entry_id, d)
    if not found:
        console.print(f"[red]No entry found with id {entry_id}[/red]")
        raise typer.Exit(1)
    entry, entry_day = found
    fields = {}
    if duration is not None:
        fields["duration_min"] = duration
    if category is not None:
        fields["category"] = category
    if title is not None:
        fields["title"] = title
    fields["needs_review"] = False
    store.update_entry(entry_id, entry_day, **fields)
    console.print(f"[green]updated[/green] {entry_id}")


@app.command()
def config():
    """Open the config file in $EDITOR."""
    load_config()  # ensure it exists
    editor = subprocess.os.environ.get("EDITOR", "vi")
    console.print(f"Opening {CONFIG_PATH} with {editor}")
    subprocess.run([editor, str(CONFIG_PATH)])


@app.command(name="backfill-claude")
def backfill_claude_cmd(
    days: int = typer.Option(7, "--days"),
    ai: bool = typer.Option(
        False, "--ai", help="Use headless Claude to summarize sessions with no ai-title (adds latency/cost)"
    ),
):
    """Walk ~/.claude/projects/ session history and log significant past sessions."""
    from daylog.backfill import backfill_claude_sessions

    cfg = load_config()
    new_entries = backfill_claude_sessions(days, cfg, ai=ai)
    console.print(f"[green]claude session backfill[/green]: {len(new_entries)} entries")


@app.command(name="import-events")
def import_events(
    source: str = typer.Option("jira", "--source"),
    file: Optional[str] = typer.Option(None, "--file", help="JSON file path, or omit to read stdin"),
):
    """Import raw events (from a Claude Code MCP command, e.g. Jira backfill) as daylog entries.

    Applies the rules in Python — default duration, needs_review flag, idempotency —
    the LLM only supplies the raw facts (ticket key + timestamp) via MCP.
    """
    import json as json_module
    from pathlib import Path as PathType

    raw_text = PathType(file).read_text() if file else sys.stdin.read()
    try:
        events = json_module.loads(raw_text)
    except json_module.JSONDecodeError as exc:
        console.print(f"[red]invalid JSON: {exc}[/red]")
        raise typer.Exit(1)

    if source == "jira":
        from daylog.backfill import import_jira_events

        new_entries = import_jira_events(events)
    elif source == "outlook":
        from daylog.backfill import import_outlook_events

        new_entries = import_outlook_events(events, load_config())
    elif source == "confluence":
        from daylog.backfill import import_confluence_events

        new_entries = import_confluence_events(events)
    else:
        console.print(f"[red]unknown source: {source}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]imported[/green] {len(new_entries)} entries")


@app.command()
def backfill(
    days: int = typer.Option(7, "--days"),
    ai: bool = typer.Option(
        False, "--ai", help="Use headless Claude to summarize Claude Code sessions with no ai-title"
    ),
):
    """One-time recovery: calendar + Claude sessions + GitHub PRs (automatic),
    Jira + Outlook (semi-automated, need your MCP connectors)."""
    from daylog.backfill import backfill_calendar, backfill_claude_sessions
    from daylog.github_sync import sync_prs

    cfg = load_config()
    today = date.today()
    start = today - timedelta(days=days - 1)

    console.print(f"[bold]Backfilling {start.isoformat()} to {today.isoformat()}[/bold]")

    if cfg["calendar_sync"].get("backend", "eventkit") == "eventkit":
        cal_results = backfill_calendar(start, today, cfg)
        cal_total = sum(len(v) for v in cal_results.values())
        console.print(f"calendar: {cal_total} entries")
    else:
        console.print(
            "[yellow]calendar backend is 'outlook' — that needs your Microsoft 365 MCP "
            "connector, run /daylog-backfill-outlook inside a Claude Code session in this "
            f"repo to pull the last {days} days of Outlook events.[/yellow]"
        )

    claude_entries = backfill_claude_sessions(days, cfg, ai=ai)
    console.print(f"claude sessions: {len(claude_entries)} entries")

    github_entries = sync_prs(start, cfg)
    console.print(f"github: {len(github_entries)} entries")

    console.print(
        "[yellow]Jira backfill needs your Atlassian MCP connector — run "
        "/daylog-backfill-jira inside a Claude Code session in this repo "
        "to pull recent ticket activity.[/yellow]"
    )

    if typer.confirm("Run interactive fill for each backfilled day?", default=False):
        d = start
        while d <= today:
            gapfill.interactive_fill(d, cfg)
            d += timedelta(days=1)

    console.print()
    week(prev=False, compare=False)


if __name__ == "__main__":
    app()
