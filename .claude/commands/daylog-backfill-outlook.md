Backfill Outlook/Microsoft 365 calendar events into daylog for the last N
days (default 7 — check if the user specified a different number or an
explicit start date).

This is the historical/range counterpart to `/daylog-outlook-checkpoint`
(which only pulls today) — use this one for catching up after switching
`calendar_sync.backend` to `"outlook"`, or after a gap in live syncing.

Steps:

1. Find the user's calendar via the Microsoft 365 MCP connector (whatever
   tool it exposes for listing/reading the authenticated user's calendar —
   check the actual tool names available in this session, don't assume a
   specific one) and query events in the requested window (last N days
   through today, local timezone).
2. For each event, build one JSON object matching exactly this shape (the
   same shape `dl calendar-sync`'s macOS backend and
   `/daylog-outlook-checkpoint` already produce, so it flows through the
   same dedup/skip logic on the Python side regardless of which command
   produced it):
   ```json
   {
     "uid": "<a stable unique id for this event — the MCP connector's own event id is ideal>",
     "title": "Design review",
     "start": "2026-07-10T14:00:00Z",
     "end": "2026-07-10T14:30:00Z",
     "all_day": false,
     "status": "accepted"
   }
   ```
   - `uid` **must** be stable across runs (the same event queried again
     tomorrow must produce the same `uid`) — this is what makes re-running
     safe without duplicating entries. Use whatever persistent event ID the
     MCP connector returns; do not invent one from title+time (titles can
     repeat, times can be edited).
   - `status` should reflect whether the current user accepted/declined/is
     tentative on the event, if the connector exposes that — use `"accepted"`
     if attendance status isn't available rather than guessing at
     `"declined"`.
   - Only use facts returned by the MCP calls — don't guess at event details
     or fabricate timestamps for events the query didn't return. A day (or
     the whole window) with no events is valid — report zero and move on.
3. Collect all event objects from every day in the window into a **single**
   JSON array and pipe it into (via the Bash tool):
   ```
   dl import-events --source outlook
   ```
   Python groups events by their own `start` date and applies the rules
   (declined/all-day/short-event skipping, dedup against manual entries,
   idempotency via `uid`) per day — you don't need to split the query by day
   yourself or check for duplicates; one combined array for the whole
   window is fine.
4. Report back to the user how many entries were imported, and remind them
   that entries needing review show a `~` marker in `dl day` (editable via
   `dl edit <entry-id> -d <minutes>`), same as backfilled Jira entries.

Only use facts returned by the MCP calls. Don't guess at event content or
fabricate timestamps for events the query didn't return.

Note for whoever wires this up: the exact Microsoft 365 MCP tool names and
their response shape for calendar events need to be confirmed against a live
session before trusting this at scale — start with a short window (e.g. 2-3
days) and check the entries with `dl day` before running a full backfill.
