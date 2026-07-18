#!/usr/bin/env python3
"""Render and install the daylog launchd agents (18:00 gap-fill reminder,
17:45 calendar sweep, and an optional morning-brief poller) into
~/Library/LaunchAgents.

This only writes the plist files by default. Pass --load to also
`launchctl load` them (starts the background schedule immediately) — kept as
a separate, explicit step since it's a persistent change to your system.

Usage:
    python3 install_reminders.py                  # writes plists only
    python3 install_reminders.py --load            # writes + launchctl load
    python3 install_reminders.py --load --morning-brief  # + the morning-brief poller
    python3 install_reminders.py --uninstall       # unload + remove all plists
    python3 install_reminders.py --remind-time 18:00 --calsync-time 17:45
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REMINDERS_DIR = Path(__file__).resolve().parent
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
DAYLOG_HOME = Path(os.environ.get("DAYLOG_HOME", "~/.daylog")).expanduser()

AGENTS = [
    ("com.daylog.remind", "com.daylog.remind.plist.template", "remind_time"),
    ("com.daylog.calsync", "com.daylog.calsync.plist.template", "calsync_time"),
]

# Not in AGENTS (not installed by default) — install() adds it only when
# --morning-brief is passed. `time_key=None` means "no HOUR/MINUTE
# substitution", since this plist polls via StartInterval instead of a
# fixed clock time (see reminders/com.daylog.morningbrief.plist.template).
MORNING_BRIEF_AGENT = ("com.daylog.morningbrief", "com.daylog.morningbrief.plist.template", None)

# All labels that might exist on disk, regardless of how they got there —
# --uninstall cleans up everything, not just what a given install() call
# would have added.
ALL_AGENT_LABELS = [label for label, _, _ in AGENTS] + [MORNING_BRIEF_AGENT[0]]


def _dl_path() -> str:
    path = shutil.which("dl")
    if not path:
        sys.exit("`dl` not found on PATH — install the daylog package first (pip install -e .)")
    return path


def _render(template_path: Path, dl_path: str, hh: str, mm: str) -> str:
    text = template_path.read_text()
    return (
        text.replace("{{DL_PATH}}", dl_path)
        .replace("{{HOUR}}", str(int(hh)))
        .replace("{{MINUTE}}", str(int(mm)))
        .replace("{{DAYLOG_HOME}}", str(DAYLOG_HOME))
    )


def install(remind_time: str, calsync_time: str, load: bool, morning_brief: bool = False) -> None:
    DAYLOG_HOME.joinpath("state").mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    dl_path = _dl_path()
    times = {"remind_time": remind_time, "calsync_time": calsync_time}

    agents = list(AGENTS)
    if morning_brief:
        agents.append(MORNING_BRIEF_AGENT)

    for label, template_name, time_key in agents:
        hh, mm = times[time_key].split(":") if time_key else ("0", "0")
        rendered = _render(REMINDERS_DIR / template_name, dl_path, hh, mm)
        dest = LAUNCH_AGENTS_DIR / f"{label}.plist"
        dest.write_text(rendered)
        print(f"wrote {dest}")
        if load:
            subprocess.run(["launchctl", "unload", str(dest)], check=False, capture_output=True)
            result = subprocess.run(["launchctl", "load", str(dest)], capture_output=True, text=True)
            if result.returncode == 0:
                cadence = f"fires daily at {times[time_key]}" if time_key else "polls every 15 min"
                print(f"loaded {label} ({cadence})")
            else:
                print(f"launchctl load failed for {label}: {result.stderr.strip()}")

    if morning_brief:
        print(
            "  morning-brief defaults to disabled in config.yaml (morning_brief.enabled: false) "
            "until you turn it on — the poller running with it off is a harmless no-op."
        )


def uninstall() -> None:
    for label in ALL_AGENT_LABELS:
        dest = LAUNCH_AGENTS_DIR / f"{label}.plist"
        if dest.exists():
            subprocess.run(["launchctl", "unload", str(dest)], check=False, capture_output=True)
            dest.unlink()
            print(f"removed {dest}")
        else:
            print(f"{dest} not present, skipping")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--remind-time", default="18:00")
    parser.add_argument("--calsync-time", default="17:45")
    parser.add_argument("--load", action="store_true", help="Also launchctl load the agents")
    parser.add_argument(
        "--morning-brief",
        action="store_true",
        help="Also install the morning-brief poller (still off until morning_brief.enabled: true in config.yaml)",
    )
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    if args.uninstall:
        uninstall()
    else:
        install(args.remind_time, args.calsync_time, args.load, morning_brief=args.morning_brief)
