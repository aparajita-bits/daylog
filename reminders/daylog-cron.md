# Linux alternative: cron instead of launchd

`launchd` is macOS-only. On Linux, use cron to get the same two scheduled runs.

```bash
crontab -e
```

Add:

```cron
# daylog: calendar sweep at 17:45, gap-fill reminder at 18:00
45 17 * * 1-5 /usr/bin/env dl calendar-sync >> ~/.daylog/state/calsync.log 2>&1
0  18 * * 1-5 /usr/bin/env dl fill --notify >> ~/.daylog/state/remind.log 2>&1

# optional: morning brief, polled every 15 min (same idempotent no-op logic
# as the launchd version — safe to poll this often). Needs
# morning_brief.enabled: true and morning_brief.delivery: email (Notes.app
# delivery is macOS-only) in ~/.daylog/config.yaml.
*/15 * * * * /usr/bin/env dl morning-brief >> ~/.daylog/state/morningbrief.log 2>&1
```

Notes:

- `dl fill --notify` uses `osascript` for notifications on macOS. On Linux, swap
  `daylog/gapfill.py::send_notification` to shell out to `notify-send` instead
  (guarded by `sys.platform`), or just rely on the log file.
- Calendar sync's default `eventkit` backend is macOS-only (Calendar.app via
  JXA) — on Linux, set `calendar_sync.backend: outlook` in `~/.daylog/config.yaml`
  if your meetings are in Microsoft 365, or drop the `calendar-sync` cron line
  entirely and rely on manual entries.
- `1-5` restricts the schedule to weekdays; drop it if you work weekends.
- Run `crontab -l` to confirm the entries, and check `~/.daylog/state/*.log` if
  a scheduled run doesn't seem to have fired.
