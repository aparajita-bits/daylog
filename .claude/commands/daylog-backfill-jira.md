Backfill Jira ticket activity into daylog for the last N days (default 7 — check if the user specified a different number).

Steps:

1. Find the user's Jira account: use the Atlassian MCP connector's `atlassianUserInfo` (or `lookupJiraAccountId`) to resolve the current account ID if it isn't already known.
2. Query for issues the user transitioned or logged work on in the last N days. Use `searchJiraIssuesUsingJql` with something like:
   ```
   assignee = currentUser() AND updated >= -Nd ORDER BY updated DESC
   ```
   Also consider issues where the user added a worklog or comment in the window, not just ones assigned to them — use `getJiraIssueRemoteIssueLinks` / worklog fields if useful context, but keep the JQL query itself simple and fast.
3. For each matching issue, build one JSON object:
   ```json
   {
     "key": "AXON-1234",
     "summary": "Fixed partition pruning bug",
     "transitioned_at": "2026-07-08T14:00:00Z",
     "action": "transitioned to Done"
   }
   ```
   Use the issue's `updated` timestamp (or the specific transition/worklog timestamp if you queried it) for `transitioned_at`. Use the issue summary for `summary`.
4. Collect all objects into a JSON array and pipe it into:
   ```
   dl import-events --source jira
   ```
   (via the Bash tool, writing the JSON to stdin — e.g. `echo '<json>' | dl import-events --source jira`, or write it to a temp file and use `--file`).
5. Python (not you) applies the rules: default 60-minute duration, `needs_review: true` flag, and idempotency — re-running this command for a ticket/day already imported is a no-op. You do not need to check for duplicates yourself.
6. Report back to the user how many entries were imported, and remind them the durations are placeholders (`~` marker in `dl day`) editable via `dl edit <entry-id> -d <minutes>`.

Only use facts returned by the MCP calls. Don't guess at ticket content or fabricate timestamps for issues the query didn't return.
