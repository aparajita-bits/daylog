Pull today's Outlook/Microsoft 365 calendar events into daylog. This is a
separate step from the main `/daylog-checkpoint` because it needs the
Microsoft 365 MCP connector specifically, and only applies when
`calendar_sync.backend: "outlook"` is set in `~/.daylog/config.yaml` (the
default backend is macOS Calendar.app via a JXA script, which doesn't need
this at all). Used two ways, same as `/daylog-checkpoint`:

- **`/daylog-outlook-checkpoint`, interactive** — you type this yourself.
  MCP tool prompts get answered normally. Recommended way to run this the
  first few times, so you can see exactly what's being queried before
  trusting it unattended.
- **Shelled in headlessly** by `dl checkpoint` (when the Outlook backend is
  enabled and `checkpoint.outlook_skip_permissions: true` is set) — no one
  to answer questions in this mode; proceed with best judgment, skip
  anything that can't be determined confidently rather than guessing.

Steps:

1. Find the user's calendar via the Microsoft 365 MCP connector (whatever
   tool it exposes for listing/reading the authenticated user's calendar —
   check the actual tool names available in this session, don't assume a
   specific one) and query today's events (the current date — local
   timezone).
2. For each event, build one JSON object matching exactly this shape (the
   same shape `dl calendar-sync`'s macOS backend already produces, so it
   flows through the same dedup/skip logic on the Python side):
   ```json
   {
     "uid": "<a stable unique id for this event — the MCP connector's own event id is ideal>",
     "title": "Design review",
     "start": "2026-07-18T14:00:00Z",
     "end": "2026-07-18T14:30:00Z",
     "all_day": false,
     "status": "accepted"
   }
   ```
   - `uid` **must** be stable across runs (the same event queried tomorrow
     must produce the same `uid`) — this is what makes re-running safe
     without duplicating entries. Use whatever persistent event ID the MCP
     connector returns; do not invent one from title+time (titles can repeat,
     times can be edited).
   - `status` should reflect whether the current user accepted/declined/is
     tentative on the event, if the connector exposes that — use `"accepted"`
     if attendance status isn't available rather than guessing at
     `"declined"`.
   - Only use facts returned by the MCP calls — don't guess at event details
     or fabricate timestamps for events the query didn't return. An empty
     result (no events today) is valid — report zero and move on.
3. Collect all event objects into a JSON array and pipe it into (via the
   Bash tool):
   ```
   dl import-events --source outlook
   ```
   Python applies the rules — declined/all-day/short-event skipping, dedup
   against manual entries, idempotency via `uid` — you don't need to check
   for duplicates or filter events yourself; just report what the connector
   actually returned.
4. Print one final plain-text line, e.g. `outlook checkpoint: 3 events
   imported` — this may be the only output a human reads later (from
   `~/.daylog/checkpoint.log`), so make it self-contained.

Note for whoever wires this up: the exact Microsoft 365 MCP tool names and
their response shape for calendar events need to be confirmed against a live
session before trusting this unattended — run it interactively first
(`/daylog-outlook-checkpoint`) and check the entries it produces with `dl day`
before enabling `checkpoint.outlook_skip_permissions`.
