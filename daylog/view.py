"""dl view — a single, nicely-formatted HTML report (stats + AI insights)
opened in the default browser.

Built for the desktop widget's "expand" button: cramming multi-paragraph AI
insights into a 300px-wide Übersicht widget reads badly (text overflow, no
real typography, awkward wrapping) — this generates the same content as a
proper page instead, styled to match the widget's own dark aesthetic. Fine
to run by hand too (`dl view`, `dl view --week`).
"""

from __future__ import annotations

import html as html_module
import re
import webbrowser
from datetime import date
from pathlib import Path
from typing import Optional

from daylog.config import STATE_DIR, ensure_dirs
from daylog.models import Entry

VIEW_PATH = STATE_DIR / "view.html"

# Kept in sync with widget/daylog.widget/index.jsx.template's CATEGORY_COLORS
# by hand — small, stable, low-churn enough that a shared source of truth
# isn't worth the cross-language plumbing.
CATEGORY_COLORS = {
    "coding": "#7dd3fc",
    "meeting": "#fca5a5",
    "discussion": "#fcd34d",
    "review": "#c4b5fd",
    "firefighting": "#fb7185",
    "learning": "#86efac",
    "admin": "#94a3b8",
    "other": "#a1a1aa",
}


def _fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m}m" if h else f"{m}m"


def _md_lite_to_html(text: str) -> str:
    """Minimal, dependency-free markdown -> HTML for the shapes our own AI
    prompts actually produce (bold, inline code, bullet lists, paragraphs,
    **Label**-style section headers) — not a general markdown parser. Raw
    text is HTML-escaped first; the markdown syntax characters (`**`,
    backticks) survive escaping untouched, so converting them to tags
    afterward is safe and can't be used to inject arbitrary HTML from the
    model's output.
    """
    if not text or not text.strip():
        return '<p class="empty">(nothing to show)</p>'

    def _inline(s: str) -> str:
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        return s

    lines = text.splitlines()
    out: list[str] = []
    in_list = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        escaped = html_module.escape(stripped)

        if stripped.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(html_module.escape(stripped[2:]))}</li>")
            continue

        if in_list:
            out.append("</ul>")
            in_list = False

        # A line that's *only* a bold span (our prompts' "**Label**" section
        # headers) renders as a heading instead of a bolded paragraph.
        only_bold = re.fullmatch(r"\*\*(.+?)\*\*:?", stripped)
        if only_bold:
            out.append(f"<h3>{html_module.escape(only_bold.group(1))}</h3>")
            continue

        out.append(f"<p>{_inline(escaped)}</p>")

    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _stats_bars_html(category_min: dict) -> str:
    if not category_min:
        return '<p class="empty">nothing logged</p>'
    max_min = max(category_min.values()) or 1
    rows = []
    for cat, minutes in sorted(category_min.items(), key=lambda kv: -kv[1]):
        pct = max(6, round(minutes / max_min * 100))
        color = CATEGORY_COLORS.get(cat, "#a1a1aa")
        rows.append(
            '<div class="bar-row">'
            f'<div class="bar-label">{html_module.escape(cat)}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color};"></div></div>'
            f'<div class="bar-value">{_fmt_duration(minutes)}</div>'
            "</div>"
        )
    return "\n".join(rows)


def _daily_breakdown_html(week_entries: dict[date, list[Entry]]) -> str:
    """Per-day category trend (coding/meeting/discussion/review/... by day
    of the week), not just a single aggregated week total — the thing a
    prose insights paragraph can gesture at ("Fri/Sat were deep-work days")
    but can't show precisely."""
    if not any(week_entries.values()):
        return '<p class="empty">nothing logged this week</p>'

    rows = []
    for day in sorted(week_entries):
        entries = week_entries[day]
        cat_min: dict[str, int] = {}
        for e in entries:
            cat_min[e.category] = cat_min.get(e.category, 0) + e.duration_min
        total = sum(cat_min.values())
        label = day.strftime("%a %m-%d")

        if not cat_min:
            rows.append(
                '<div class="day-row">'
                f'<div class="day-label">{label}</div>'
                '<div class="day-stack"></div>'
                '<div class="day-total" style="opacity:0.35;">—</div>'
                "</div>"
            )
            continue

        segments = "".join(
            f'<div class="day-seg" style="width:{(minutes / total * 100):.1f}%;background:{CATEGORY_COLORS.get(cat, "#a1a1aa")};" '
            f'title="{html_module.escape(cat)}: {_fmt_duration(minutes)}"></div>'
            for cat, minutes in sorted(cat_min.items(), key=lambda kv: -kv[1])
        )
        rows.append(
            '<div class="day-row">'
            f'<div class="day-label">{label}</div>'
            f'<div class="day-stack">{segments}</div>'
            f'<div class="day-total">{_fmt_duration(total)}</div>'
            "</div>"
        )

    legend = "".join(
        f'<span class="legend-item"><span class="legend-dot" style="background:{color};"></span>{cat}</span>'
        for cat, color in CATEGORY_COLORS.items()
    )
    return f'<div class="day-grid">{"".join(rows)}</div><div class="legend">{legend}</div>'


def _top_items_html(top_items: list[tuple[str, int]]) -> str:
    """Ranked list of tickets/projects by time spent this week — concrete
    numbers, not a narrative gesture at "where the week went"."""
    if not top_items:
        return '<p class="empty">nothing logged</p>'
    max_min = top_items[0][1] or 1
    rows = []
    for key, minutes in top_items:
        pct = max(6, round(minutes / max_min * 100))
        rows.append(
            '<div class="bar-row">'
            f'<div class="bar-label" style="width:170px;text-transform:none;"><code>{html_module.escape(key)}</code></div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:#7dd3fc;"></div></div>'
            f'<div class="bar-value">{_fmt_duration(minutes)}</div>'
            "</div>"
        )
    return "\n".join(rows)


def _weekday_bars_html(by_weekday: dict, color: str, ordered_days: Optional[list] = None) -> str:
    """Shared renderer for both meeting-load-by-weekday (dict keyed by
    weekday label, e.g. analytics.WEEKDAYS order) and focus-block-by-day
    (dict keyed by date) — same one-bar-per-row shape either way."""
    if not by_weekday or not any(by_weekday.values()):
        return '<p class="empty">nothing logged</p>'
    keys = ordered_days if ordered_days is not None else sorted(by_weekday)
    max_min = max(by_weekday.values()) or 1
    rows = []
    for key in keys:
        minutes = by_weekday.get(key, 0)
        label = key.strftime("%a %m-%d") if isinstance(key, date) else str(key)
        pct = max(4, round(minutes / max_min * 100)) if minutes else 0
        rows.append(
            '<div class="day-row">'
            f'<div class="day-label">{html_module.escape(label)}</div>'
            f'<div class="day-stack"><div class="day-seg" style="width:{pct}%;background:{color};"></div></div>'
            f'<div class="day-total">{_fmt_duration(minutes) if minutes else "—"}</div>'
            "</div>"
        )
    return f'<div class="day-grid">{"".join(rows)}</div>'


def _jira_completion_html(week_entries: dict[date, list[Entry]]) -> str:
    """Which Jira tickets touched this week were actually closed out
    (tagged `jira-status:done` by backfill.import_jira_events when a
    captured transition reads as a completion) vs. merely touched. Only
    covers Jira-linked, transition-tagged work — daylog tracks time, not
    ticket status, so this is deliberately scoped to what's actually known
    rather than guessing at completion for untagged entries."""
    from daylog.backfill import DONE_STATUS_TAG

    all_entries = [e for entries in week_entries.values() for e in entries]
    by_ticket: dict[str, list[Entry]] = {}
    for e in all_entries:
        if e.jira:
            by_ticket.setdefault(e.jira, []).append(e)

    if not by_ticket:
        return '<p class="empty">no Jira-linked entries this week</p>'

    done: list[tuple[str, int]] = []
    open_tickets: list[tuple[str, int]] = []
    for key, entries in sorted(by_ticket.items()):
        total = sum(e.duration_min for e in entries)
        is_done = any(DONE_STATUS_TAG in (e.tags or []) for e in entries)
        (done if is_done else open_tickets).append((key, total))

    def _list(items: list[tuple[str, int]]) -> str:
        return "".join(f"<li><code>{html_module.escape(k)}</code> — {_fmt_duration(m)}</li>" for k, m in items)

    parts = []
    if done:
        parts.append(f'<h4 class="subheading">Closed this week</h4><ul>{_list(done)}</ul>')
    else:
        parts.append(
            '<p class="empty">Nothing marked closed this week — only tickets whose Jira sync captured a '
            "Done/Closed/Resolved-style transition show up here.</p>"
        )
    if open_tickets:
        parts.append(f'<h4 class="subheading">Touched, still open</h4><ul>{_list(open_tickets)}</ul>')
    return "\n".join(parts)


def _render_page(
    title: str,
    subtitle: str,
    stats_html: str,
    insights_html: Optional[str] = None,
    daily_html: Optional[str] = None,
    top_items_html: Optional[str] = None,
    meeting_load_html: Optional[str] = None,
    focus_blocks_html: Optional[str] = None,
    completion_html: Optional[str] = None,
) -> str:
    daily_section = f'<h2 class="section">Day by day</h2>\n{daily_html}' if daily_html else ""
    top_items_section = f'<h2 class="section">Where your time went</h2>\n{top_items_html}' if top_items_html else ""
    meeting_load_section = (
        f'<h2 class="section">Meeting load by weekday</h2>\n{meeting_load_html}' if meeting_load_html else ""
    )
    focus_blocks_section = (
        f'<h2 class="section">Longest focus block per day</h2>\n{focus_blocks_html}' if focus_blocks_html else ""
    )
    completion_section = f'<h2 class="section">Jira completion</h2>\n{completion_html}' if completion_html else ""
    insights_section = f'<h2 class="section">Insights</h2>\n{insights_html}' if insights_html else ""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{html_module.escape(title)}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 56px 64px 80px;
    max-width: 720px;
    margin: 0 auto;
    background: #131022;
    color: rgba(255,255,255,0.92);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
    line-height: 1.65;
  }}
  h1 {{ font-size: 30px; font-weight: 600; margin: 0 0 4px; }}
  .subtitle {{ font-size: 13px; opacity: 0.5; letter-spacing: 0.5px; }}
  h2.section {{
    font-size: 12px; text-transform: uppercase; letter-spacing: 1.8px;
    opacity: 0.5; margin-top: 44px; margin-bottom: 16px; font-weight: 600;
  }}
  h3 {{ font-size: 15px; margin-top: 26px; margin-bottom: 8px; opacity: 0.85; font-weight: 600; }}
  p {{ margin: 8px 0; font-size: 14.5px; }}
  p.empty {{ opacity: 0.45; font-style: italic; }}
  ul {{ padding-left: 22px; margin: 8px 0; }}
  li {{ margin: 7px 0; font-size: 14.5px; }}
  code {{ background: rgba(255,255,255,0.08); padding: 1px 6px; border-radius: 4px; font-size: 0.9em; }}
  .bar-row {{ display: flex; align-items: center; gap: 12px; margin: 8px 0; }}
  .bar-label {{ width: 110px; font-size: 13px; opacity: 0.75; text-transform: capitalize; flex-shrink: 0; }}
  .bar-track {{ flex: 1; height: 9px; border-radius: 5px; background: rgba(255,255,255,0.08); overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 5px; }}
  .bar-value {{ width: 54px; font-size: 12.5px; opacity: 0.6; text-align: right; flex-shrink: 0; }}
  .subheading {{ font-size: 12px; opacity: 0.75; margin: 18px 0 6px; font-weight: 600; }}
  .day-grid {{ display: flex; flex-direction: column; gap: 9px; margin-top: 4px; }}
  .day-row {{ display: flex; align-items: center; gap: 12px; }}
  .day-label {{ width: 68px; font-size: 12.5px; opacity: 0.7; flex-shrink: 0; }}
  .day-stack {{ flex: 1; height: 14px; border-radius: 4px; background: rgba(255,255,255,0.06); overflow: hidden; display: flex; }}
  .day-seg {{ height: 100%; }}
  .day-total {{ width: 54px; font-size: 12.5px; opacity: 0.6; text-align: right; flex-shrink: 0; }}
  .legend {{ margin-top: 14px; display: flex; flex-wrap: wrap; gap: 14px; }}
  .legend-item {{ font-size: 11.5px; opacity: 0.6; display: flex; align-items: center; gap: 5px; text-transform: capitalize; }}
  .legend-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
</style>
</head>
<body>
  <h1>{html_module.escape(title)}</h1>
  <div class="subtitle">{html_module.escape(subtitle)}</div>
  <h2 class="section">Stats</h2>
  {stats_html}
  {daily_section}
  {top_items_section}
  {meeting_load_section}
  {focus_blocks_section}
  {completion_section}
  {insights_section}
</body>
</html>
"""


def run_view(cfg: dict, week: bool = False, open_browser: bool = True) -> Path:
    ensure_dirs()
    today = date.today()

    daily_html = None
    top_items_html = None
    meeting_load_html = None
    focus_blocks_html = None
    completion_html = None
    insights_html = None  # week view has no Insights section at all (see below)

    if week:
        from daylog.analytics import WEEKDAYS, compute_stats, load_week, week_bounds

        monday, sunday = week_bounds(today, 0)
        week_entries = load_week(monday)
        stats = compute_stats(week_entries, cfg)
        title = f"Week of {monday.isoformat()}"
        subtitle = f"{monday.strftime('%b %-d')} – {sunday.strftime('%b %-d')} · {_fmt_duration(stats['total_captured_min'])} captured"
        stats_html = _stats_bars_html(stats["category_min"])
        daily_html = _daily_breakdown_html(week_entries)
        top_items_html = _top_items_html(stats["top_items"])
        meeting_load_html = _weekday_bars_html(
            stats["meeting_by_weekday"], CATEGORY_COLORS["meeting"], ordered_days=WEEKDAYS
        )
        focus_blocks_html = _weekday_bars_html(stats["focus_by_day"], CATEGORY_COLORS["coding"])
        completion_html = _jira_completion_html(week_entries)
        # No AI insights for the week view: daylog-review.md's pattern-
        # spotting prose ("meeting-heavy vs deep-work days") wasn't useful
        # in practice, and the concrete sections above (day-by-day trend,
        # top items, meeting load, focus blocks, Jira completion) already
        # cover the same ground with real numbers instead of narrative.
    else:
        from daylog import store
        from daylog.summary import compute_day_stats, generate_summary

        entries = store.read_entries(today)
        stats = compute_day_stats(entries)
        title = today.strftime("%A, %B %-d")
        subtitle = f"{_fmt_duration(stats['total_min'])} captured today"
        stats_html = _stats_bars_html(stats["by_category"])
        # The day view's Insights section reuses daylog-standup.md (the same
        # prompt `dl standup --ai` uses) via generate_summary, not the
        # weekly-review prompt -- that's genuinely useful content (a
        # readable, human-sounding recap), unlike the week view's prose.
        insights_text = generate_summary(today, cfg, ai=True)
        insights_html = _md_lite_to_html(insights_text or "")

    page = _render_page(
        title,
        subtitle,
        stats_html,
        insights_html,
        daily_html=daily_html,
        top_items_html=top_items_html,
        meeting_load_html=meeting_load_html,
        focus_blocks_html=focus_blocks_html,
        completion_html=completion_html,
    )
    VIEW_PATH.write_text(page)

    if open_browser:
        webbrowser.open(VIEW_PATH.as_uri())

    return VIEW_PATH
