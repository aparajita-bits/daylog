import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, timedelta


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.store as store_module
    import daylog.github_sync as github_sync_module

    importlib.reload(config_module)
    importlib.reload(store_module)
    importlib.reload(github_sync_module)
    return config_module, store_module, github_sync_module


def test_sync_prs_idempotent_and_needs_review(tmp_path, monkeypatch):
    config_module, store_module, github_sync_module = _reload(tmp_path, monkeypatch)

    fake_prs = [
        {
            "number": 86,
            "title": "List api startup cache",
            "url": "https://github.com/example/repo/pull/86",
            "repository": {"nameWithOwner": "example/repo"},
        }
    ]
    monkeypatch.setattr(github_sync_module, "fetch_reviewed_prs", lambda day, timeout_sec=20: fake_prs)
    monkeypatch.setattr(github_sync_module, "fetch_authored_prs", lambda day, timeout_sec=20: [])
    monkeypatch.setattr(github_sync_module, "fetch_review_comments", lambda day, timeout_sec=20: [])

    day = date.today()
    cfg = config_module.DEFAULT_CONFIG

    first_run = github_sync_module.sync_prs(day, cfg)
    assert len(first_run) == 1
    assert first_run[0].category == "review"
    assert first_run[0].source == "github"
    assert first_run[0].needs_review is True
    assert first_run[0].event_uid == "https://github.com/example/repo/pull/86#reviewed"
    assert "#86" in first_run[0].title
    assert "example/repo" in first_run[0].title

    second_run = github_sync_module.sync_prs(day, cfg)
    assert second_run == []  # idempotent: keyed on {pr_url}#{action}


def test_sync_prs_disabled_via_config(tmp_path, monkeypatch):
    config_module, store_module, github_sync_module = _reload(tmp_path, monkeypatch)

    called = []
    monkeypatch.setattr(
        github_sync_module,
        "fetch_reviewed_prs",
        lambda day, timeout_sec=20: called.append(1) or [],
    )

    cfg = {**config_module.DEFAULT_CONFIG, "github_sync": {"enabled": False}}
    result = github_sync_module.sync_prs(date.today(), cfg)
    assert result == []
    assert called == []  # short-circuited before even calling any fetcher


def test_sync_prs_same_pr_authored_and_reviewed_produces_two_entries(tmp_path, monkeypatch):
    config_module, store_module, github_sync_module = _reload(tmp_path, monkeypatch)

    same_pr = {
        "number": 42,
        "title": "Add retry logic",
        "url": "https://github.com/example/repo/pull/42",
        "repository": {"nameWithOwner": "example/repo"},
    }
    monkeypatch.setattr(github_sync_module, "fetch_authored_prs", lambda day, timeout_sec=20: [same_pr])
    monkeypatch.setattr(github_sync_module, "fetch_reviewed_prs", lambda day, timeout_sec=20: [same_pr])
    monkeypatch.setattr(github_sync_module, "fetch_review_comments", lambda day, timeout_sec=20: [same_pr])

    cfg = config_module.DEFAULT_CONFIG
    entries = github_sync_module.sync_prs(date.today(), cfg)

    assert len(entries) == 3  # opened, reviewed, and commented are distinct facts
    uids = {e.event_uid for e in entries}
    assert uids == {
        "https://github.com/example/repo/pull/42#authored",
        "https://github.com/example/repo/pull/42#reviewed",
        "https://github.com/example/repo/pull/42#commented",
    }
    titles = {e.title.split(":")[0] for e in entries}
    assert titles == {"Opened PR #42", "Reviewed PR #42", "Commented on PR #42"}

    # Re-running doesn't duplicate any of the three.
    second_run = github_sync_module.sync_prs(date.today(), cfg)
    assert second_run == []


def test_fetch_review_comments_normalizes_issues_search_shape(tmp_path, monkeypatch):
    config_module, store_module, github_sync_module = _reload(tmp_path, monkeypatch)

    fake_stdout = (
        '[{"number": 7, "title": "Fix flaky test", '
        '"html_url": "https://github.com/example/repo/pull/7", '
        '"repository_url": "https://api.github.com/repos/example/repo"}]'
    )

    class FakeResult:
        returncode = 0
        stdout = fake_stdout

    monkeypatch.setattr(github_sync_module, "_gh_available", lambda: True)
    monkeypatch.setattr(github_sync_module.subprocess, "run", lambda *a, **k: FakeResult())

    results = github_sync_module.fetch_review_comments(date.today())
    assert results == [
        {
            "number": 7,
            "title": "Fix flaky test",
            "url": "https://github.com/example/repo/pull/7",
            "repository": {"nameWithOwner": "example/repo"},
        }
    ]


def test_sync_prs_backfill_lands_entries_on_their_real_updated_date(tmp_path, monkeypatch):
    config_module, store_module, github_sync_module = _reload(tmp_path, monkeypatch)

    three_days_ago = date.today() - timedelta(days=3)
    fake_pr = {
        "number": 55,
        "title": "Old fix",
        "url": "https://github.com/example/repo/pull/55",
        "repository": {"nameWithOwner": "example/repo"},
        "updatedAt": f"{three_days_ago.isoformat()}T10:00:00Z",
    }
    monkeypatch.setattr(github_sync_module, "fetch_authored_prs", lambda day, timeout_sec=20: [fake_pr])
    monkeypatch.setattr(github_sync_module, "fetch_reviewed_prs", lambda day, timeout_sec=20: [])
    monkeypatch.setattr(github_sync_module, "fetch_review_comments", lambda day, timeout_sec=20: [])

    cfg = config_module.DEFAULT_CONFIG
    entries = github_sync_module.sync_prs(three_days_ago, cfg)

    assert len(entries) == 1
    assert entries[0].ts.date() == three_days_ago
    # Lands in that day's own store file, not today's.
    assert store_module.read_entries(three_days_ago)[0].event_uid == entries[0].event_uid
    assert store_module.read_entries(date.today()) == []


def test_sync_prs_backfill_dedup_scans_whole_range(tmp_path, monkeypatch):
    config_module, store_module, github_sync_module = _reload(tmp_path, monkeypatch)
    from daylog.models import Entry
    from datetime import datetime

    two_days_ago = date.today() - timedelta(days=2)
    # Simulate an entry already imported for a day in the middle of the
    # range being backfilled.
    store_module.append_entry(
        Entry(
            ts=datetime.combine(two_days_ago, datetime.min.time()).astimezone(),
            duration_min=30,
            category="coding",
            source="github",
            title="Opened PR #99: already imported",
            event_uid="https://github.com/example/repo/pull/99#authored",
        ),
        day=two_days_ago,
    )

    fake_pr = {
        "number": 99,
        "title": "already imported",
        "url": "https://github.com/example/repo/pull/99",
        "repository": {"nameWithOwner": "example/repo"},
        "updatedAt": f"{two_days_ago.isoformat()}T10:00:00Z",
    }
    monkeypatch.setattr(github_sync_module, "fetch_authored_prs", lambda day, timeout_sec=20: [fake_pr])
    monkeypatch.setattr(github_sync_module, "fetch_reviewed_prs", lambda day, timeout_sec=20: [])
    monkeypatch.setattr(github_sync_module, "fetch_review_comments", lambda day, timeout_sec=20: [])

    three_days_ago = date.today() - timedelta(days=3)
    cfg = config_module.DEFAULT_CONFIG
    entries = github_sync_module.sync_prs(three_days_ago, cfg)
    assert entries == []  # already-imported entry found via the range-wide dedup scan


def test_fetchers_return_empty_when_gh_missing(tmp_path, monkeypatch):
    config_module, store_module, github_sync_module = _reload(tmp_path, monkeypatch)

    monkeypatch.setattr(github_sync_module, "_gh_available", lambda: False)

    day = date.today()
    assert github_sync_module.fetch_authored_prs(day) == []
    assert github_sync_module.fetch_reviewed_prs(day) == []
    assert github_sync_module.fetch_review_comments(day) == []
