# Contributing to daylog

daylog is deliberately small: a Python CLI, some JSONL files, and a couple of
launchd agents. Keep contributions in that spirit — no database, no server,
no telemetry.

## Setup

```bash
git clone <this repo>
cd daylog
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Running tests

```bash
.venv/bin/pytest tests/
```

Analytics and backfill logic are tested against fixture data (see
`tests/fixtures/`), not live macOS integrations — those (calendar sync,
launchd, Shortcuts) are inherently hard to unit test and are meant to be
verified by hand against your own machine.

Set `DAYLOG_HOME` to point at a scratch directory when testing manually, so
you don't touch your real `~/.daylog`:

```bash
export DAYLOG_HOME=/tmp/daylog-scratch
.venv/bin/dl log "testing" -d 15
.venv/bin/dl day
```

## Design principles (please read before sending a PR)

- **Logging must take under 5 seconds.** If a change adds friction to `dl log`
  or the quick-entry interface, it needs a very good reason.
- **Local-first, no telemetry.** Nothing calls home. Anything that talks to
  an external service (Jira via MCP, headless Claude) is explicit,
  config-gated, and has a working fallback.
- **No persistent daemon.** Calendar sync and reminders are scheduled sweeps
  (launchd/cron), not a background process. See the "Later" section of the
  build plan for the deliberately-deferred `dl daemon` idea.
- **Config-driven, not hardcoded.** Categories, thresholds, working hours,
  ignore lists — all live in `~/.daylog/config.yaml`. No personal defaults in
  the source.
- **Fail silent, log loud.** Hooks and background sweeps must never block or
  crash the thing that triggered them (Claude Code, launchd). Errors go to
  `~/.daylog/hook-errors.log` or `~/.daylog/backfill-errors.log`, not stderr
  of the calling process.

## Filing issues

Bug reports and feature requests are welcome. For bugs, include your
`~/.daylog/config.yaml` (redacted of anything you'd rather not share) and the
relevant lines from `~/.daylog/hook-errors.log` or `backfill-errors.log` if
applicable.
