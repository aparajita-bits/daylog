"""Generates a fixture week of JSONL data for manual/automated analytics testing."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from daylog.models import Entry
from daylog import store


def build_fake_week(monday):
    def dt(day_offset, hour, minute=0):
        return (monday + timedelta(days=day_offset)).replace(hour=hour, minute=minute, tzinfo=datetime.now().astimezone().tzinfo)

    entries_by_day = {
        0: [  # Monday: 2h coding, 1h meeting
            Entry(ts=dt(0, 9), duration_min=120, category="coding", source="manual", title="AXON-1 work", jira="AXON-1"),
            Entry(ts=dt(0, 11), duration_min=60, category="meeting", source="manual", title="standup"),
        ],
        1: [  # Tuesday: 3h coding, 30m review
            Entry(ts=dt(1, 9), duration_min=180, category="coding", source="manual", title="AXON-1 work", jira="AXON-1"),
            Entry(ts=dt(1, 13), duration_min=30, category="review", source="manual", title="PR review"),
        ],
        2: [  # Wednesday: meeting-heavy
            Entry(ts=dt(2, 9), duration_min=60, category="meeting", source="manual", title="planning"),
            Entry(ts=dt(2, 10), duration_min=60, category="meeting", source="manual", title="1:1"),
            Entry(ts=dt(2, 11), duration_min=60, category="meeting", source="manual", title="design review"),
        ],
        3: [  # Thursday: 4h focused coding block
            Entry(ts=dt(3, 9), duration_min=240, category="coding", source="manual", title="AXON-2 work", jira="AXON-2"),
        ],
        4: [  # Friday: firefighting
            Entry(ts=dt(4, 9), duration_min=90, category="firefighting", source="manual", title="prod incident"),
        ],
    }
    for offset, entries in entries_by_day.items():
        day = (monday + timedelta(days=offset)).date()
        store.write_entries(day, entries)
    return entries_by_day
