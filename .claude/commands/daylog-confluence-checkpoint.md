Pull today's Confluence activity (pages edited, pages commented on) into
daylog. This is interactive-only for now — not part of the automated
`dl checkpoint` sweep — so run `/daylog-confluence-checkpoint` yourself when
you want it, the same way `/daylog-backfill-jira` is a manual command rather
than a daily automatic one.

Steps:

1. Find the user's Atlassian account via the Atlassian MCP connector's
   `atlassianUserInfo` (or `lookupJiraAccountId`) if it isn't already known —
   Confluence and Jira share the same Atlassian account.
2. **Pages edited today**: use `searchConfluenceUsingCql` with something like:
   ```
   contributor = currentUser() AND lastmodified >= startOfDay() ORDER BY lastmodified DESC
   ```
   For each matching page, build one JSON object:
   ```json
   {
     "page_id": "123456",
     "title": "Payment retry design",
     "space": "ENG",
     "action": "edited",
     "timestamp": "2026-07-18T14:00:00Z"
   }
   ```
   Use the page's `lastmodified` for `timestamp`.
3. **Pages commented on today**: CQL doesn't cleanly filter by comment
   authorship on its own — the exact grammar this Confluence instance
   supports needs to be confirmed live (try something like `type = comment
   AND creator = currentUser() AND created >= startOfDay()` first; if that
   doesn't work, fall back to a CQL query for pages with recent activity and
   check individual pages' comments via `getConfluencePageFooterComments`/
   `getConfluencePageInlineComments` to find ones authored by the current
   user today — more MCP round-trips, but accurate). For each comment found,
   build one JSON object in the same shape as above but with `"action":
   "commented"` and `timestamp` set to the comment's creation time.
4. Only use facts returned by the MCP calls — don't guess at page content or
   fabricate timestamps for pages the query didn't return. An empty result is
   valid — report zero and move on, don't retry with a broader query.
5. Collect all objects (both edited and commented) into a single JSON array
   and pipe it into (via the Bash tool):
   ```
   dl import-events --source confluence
   ```
   Python applies the rules (duration guess, `needs_review: true` flag,
   idempotency via page+action+day) — you don't need to check for
   duplicates yourself.
6. Print one final plain-text line, e.g. `confluence: 2 pages edited, 1
   comment` — this may be the only output a human reads later, so make it
   self-contained.

Note for whoever wires this up: step 3's exact CQL for "comments I authored
today" needs a live probe against this Confluence instance before trusting
it — don't assume the grammar above is correct without checking.
