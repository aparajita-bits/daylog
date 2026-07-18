Run the full end-of-day checkpoint: calendar sync, GitHub PR activity, Jira
ticket activity, then regenerate today's AI summary. This command is used
two ways:

- **`/daylog-checkpoint`, interactive** — you type this yourself inside a
  real Claude Code session. MCP tool prompts (Atlassian) get answered
  normally, the way any tool permission does in an interactive session — no
  special setup needed. This is the recommended way to run the Jira step if
  you'd rather see what's being queried than trust it running unattended.
- **Shelled in headlessly** by `dl checkpoint` (launchd, 17:45, unattended).
  In that case `dl checkpoint` has *already* run calendar sync and GitHub
  sync directly in Python (steps 1–2 below will just report "nothing new" —
  that's expected, not a bug) before invoking this prompt purely for the
  Jira step, since Jira is the one part that needs MCP. There's no one to
  answer questions in this mode — proceed with your best judgment rather
  than asking for clarification, and if something can't be determined
  confidently, skip it rather than guess.

Steps:

1. Run `dl calendar-sync` (via the Bash tool). Report how many new calendar
   entries it logged.
2. Run `dl github-sync` (via the Bash tool) — pulls PRs you opened, reviewed,
   and commented on today via the already-authenticated `gh` CLI, no MCP
   needed. Report how many new entries it logged.
3. **Jira**: find the user's Jira account via the Atlassian MCP connector's
   `atlassianUserInfo` (or `lookupJiraAccountId`) if it isn't already known,
   then query for issues transitioned, commented on, or worked on **today**
   (not a longer window) with `searchJiraIssuesUsingJql`, e.g.:
   ```
   assignee = currentUser() AND updated >= startOfDay() ORDER BY updated DESC
   ```
   For each matching issue, build one JSON object:
   ```json
   {
     "key": "AXON-1234",
     "summary": "Fixed partition pruning bug",
     "transitioned_at": "2026-07-10T14:00:00Z",
     "action": "transitioned to Done"
   }
   ```
   Use the issue's `updated` timestamp for `transitioned_at`, and the issue
   summary for `summary`. Only use facts returned by the MCP calls — don't
   guess at ticket content or fabricate timestamps for issues the query
   didn't return. An empty result is valid — report zero and move on, don't
   retry with a broader query. Collect all objects into a JSON array and
   pipe it into (via the Bash tool):
   ```
   dl import-events --source jira
   ```
   Python applies the rules (default 60-minute duration, `needs_review: true`
   flag, idempotency) — you don't need to check for duplicates yourself.
4. Run `dl summary --ai` (via the Bash tool) to regenerate today's summary
   now that calendar/GitHub/Jira are all pulled in.
5. Print one final plain-text line summarizing all three sources, e.g.
   `checkpoint: calendar +1, github +2, jira +1` — this may be the only
   output a human reads later (from a log file), so make it self-contained.
