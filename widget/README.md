# daylog desktop widget

A floating desktop widget showing today's captured hours and category
breakdown — styled to sit alongside macOS's native Calendar/Weather widgets.

This uses [Übersicht](https://tracesof.net/uebersicht/), a free/open-source
app that renders HTML/CSS/JS "widgets" on your desktop background, refreshed
on a timer by shelling out to a command. It's not Apple's native WidgetKit
(that requires Xcode + Swift + code signing — a different kind of project),
but visually it gets close, and it's just a JSX file you can edit freely.

## Setup

`./install.sh` (repo root) prompts to set this up for you — installs
Übersicht via Homebrew (auto-falls-back to `~/Applications` if you don't
have admin rights), then runs `widget/install_widget.sh`. That's the
easiest path; the rest of this section is the manual/by-hand version.

```bash
brew install --cask ubersicht    # if you don't have it
./widget/install_widget.sh        # renders + installs the widget
```

No admin rights on your Mac (managed/corporate machine)? Homebrew's default
install writes to `/Applications`, which needs `sudo`. Install into your own
home directory instead — no admin password needed:

```bash
brew install --cask ubersicht --appdir=~/Applications
```

Then open Übersicht once (⌘Space → "Übersicht") — first launch asks for
Accessibility permission (needed for it to draw on the desktop). The widget
should appear within a few seconds; no restart needed after the first grant.

## What it shows

- Today's date, or "This week" when the Week tab is selected
- A small 🎨 button top-right of the header that **cycles the background
  style**: Dark (original) → Frosted → Glass → Transparent, persisted across
  restarts. The default solid-dark block can clash with macOS's own white/
  frosted native widgets (Calendar, Clock, Weather) sitting nearby — this
  lets you match your setup instead of being stuck with one look.
- A **Day / Week / Notes** tab row: today's numbers, this week's, or your
  pending notes/action items
  - **Day** (default): total time captured today, a bar per category, and —
    if `dl fill` would find anything to fill — a small "N gaps unfilled"
    nudge
  - **Week**: this week's total + capture rate, same category bars, via
    `dl week --json`
  - **Notes**: a count of pending notes/action items, then the list itself
    — freeform text jotted separately from time-tracked entries (e.g.
    "remember to follow up on X from standup"), via `dl notes --json`. Each
    row has a small checkbox that marks it done (`dl note-done <id>`),
    removed from the list immediately without waiting on a refresh. The
    Reload/Report/Standup row below the tabs is hidden while on this tab —
    none of those apply to notes.
- Three small action buttons below the tabs (Day/Week only, see above):
  - **↻ Reload** — re-fetches whatever's currently showing (day or week
    stats), instead of waiting for the 5-minute auto refresh.
  - **⤢ Report** — opens a full, properly-typeset HTML page (`dl view`) in
    your browser for the current period. For the week: stats, a **day-by-day
    category trend**, **where your time went** (top tickets/projects),
    **meeting load by weekday**, **longest focus block per day**, and
    **Jira completion** (tickets closed vs. only touched — see `dl view
    --help`) — all real numbers, no AI narrative (the pattern-spotting prose
    wasn't useful in practice), so this opens near-instantly. For the day,
    it also includes an AI Insights section (same prompt as `dl standup
    --ai`, so it actually reads well) — that one calls the AI fresh each
    time and can take a couple minutes; the button shows "opening…" while
    it works. Deliberately *not* crammed into the 300px widget — an earlier
    version tried rendering AI prose inline in the widget itself and it was
    unreadable; a real page is worth the one extra click.
  - **📋 Standup** — fetches `dl standup --ai` (yesterday + today,
    AI-polished, falls back to the plain template on its own if AI is
    unavailable) and copies it to your clipboard via `pbcopy` (Übersicht's
    webview blocks the browser Clipboard API/`execCommand`, so this shells
    out instead), ready to paste into Teams/Slack/wherever.
- A text input at the bottom — type an entry (e.g. `mtg standup 15m`) and hit
  Enter to log it directly from the widget, no terminal needed. It runs
  `dl quicklog` under the hood, same parsing as the
  [Shortcuts.app flow](../shortcuts/README.md): duration/category/jira all
  inferred from one line. **While viewing Day + Stats with an unfilled gap
  showing**, the same input backdates your entry into that gap's time slot
  (via `dl quicklog --at HH:MM -d N`) instead of logging it at "now" — an
  alternative to running `dl fill` in a terminal for the most recent gap.
  Next to it, a small icon (📝/⏱️) shows and toggles whether Enter adds a
  note (`dl note`) or logs time (`dl quicklog`) — it follows the active tab
  automatically (Notes tab → note mode, Day/Week → log mode), so you don't
  have to remember to flip it by hand; click it to jot a note without
  leaving Day/Week, or vice versa.

The Day/Stats view refreshes every 5 minutes by re-running `dl day --json` —
the same command you can run yourself to see the raw JSON (now includes
`unaccounted_min`/`gaps` alongside the category breakdown):

```bash
dl day --json
```

Week stats are fetched on demand (only when you click the Week tab, not on
every 5-minute refresh, and cached until you hit Reload) — see `dl week
--json` if you want to run it yourself.

Positioned bottom-right by default, to stay clear of macOS's native
Calendar/Weather/Photos widget stack (usually top-left). If it still
overlaps something on your desktop, change the `right`/`bottom` values in
`className` (see Customizing below) — no fixed layout will suit every
desktop.

## Customizing

The rendered widget lives at
`~/Library/Application Support/Übersicht/widgets/daylog.widget/index.jsx`.
Übersicht hot-reloads on save, so you can tweak position (`left`/`top` in
`className`), colors (`CATEGORY_COLORS`), or what's rendered, and see changes
immediately. The source of truth is
[`daylog.widget/index.jsx.template`](daylog.widget/index.jsx.template) in
this repo — edit that if you want the change to survive re-running
`install_widget.sh` (e.g. after moving where `dl` is installed).

## Troubleshooting

**"undefined is not an object (evaluating 'state...')" on load.** Earlier
versions of this widget used Übersicht's `initialState`/`updateState`/
`dispatchAction` reducer API for the log-input field and drag-to-move, and
on at least one real Übersicht install `state` came back `undefined` at
render time — that API didn't wire up as documented. The current widget
deliberately avoids it entirely (plain DOM events + `run()` only), so this
shouldn't recur — but if you see this error after editing the widget
yourself, it's a sign you've reintroduced a dependency on that API.

**A tab looks active but the wrong content is showing.** Fixed: an earlier
version updated the body content on click but never repainted the tab pill
highlighting itself (nothing forces Übersicht to re-run `render()` on a
click, so the pills were stuck showing whichever tab was active at the last
real render pass, e.g. on load). Tab clicks now directly restyle the pills
too (see `tabNodes`/`syncTabStyles` in the template) — if you still see this
after updating, you're likely running a stale rendered copy; re-run
`./widget/install_widget.sh`.

**Header says "This week" while Day is selected (or vice versa).** Same bug
class as above, in a spot the first fix missed: the header date/"This week"
label is plain text driven by `widgetCache.period`, and a tab click doesn't
trigger a React re-render either — it was only repainted on the periodic
5-min refresh. Fixed the same way (`headerLabelDomNode`/`syncHeaderLabel`,
called from `selectTab`) — re-run `./widget/install_widget.sh` if you still
see stale text after updating.

**Dragging doesn't move it.** The drag handler works by walking up from the
date-label DOM node to find the element Übersicht actually positions
(`headerNode.closest('[id^="daylog"]')`, falling back to
`headerNode.parentElement?.parentElement`) — this is a best-effort guess at
Übersicht's internal DOM structure, not a documented API, so it may not hold
on every version. If it doesn't work for you, just edit `right`/`bottom` in
`className` directly (see Customizing above) — 100% reliable, just not
drag-and-drop.

## Removing it

```bash
rm -rf "$HOME/Library/Application Support/Übersicht/widgets/daylog.widget"
```

(Übersicht itself: `brew uninstall --cask ubersicht`, if you don't want it
for anything else.)
