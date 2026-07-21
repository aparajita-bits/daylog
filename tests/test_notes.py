import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reload_notes(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYLOG_HOME", str(tmp_path))
    import importlib
    import daylog.config as config_module
    import daylog.notes as notes_module

    importlib.reload(config_module)
    importlib.reload(notes_module)
    return notes_module


def test_add_note_persists_to_flat_json_file(tmp_path, monkeypatch):
    notes = _reload_notes(tmp_path, monkeypatch)

    n = notes.add_note("follow up on X from standup")

    assert n.text == "follow up on X from standup"
    assert n.done is False
    assert (tmp_path / "notes.json").exists()


def test_list_notes_excludes_done_by_default(tmp_path, monkeypatch):
    notes = _reload_notes(tmp_path, monkeypatch)

    a = notes.add_note("pending one")
    b = notes.add_note("will be done")
    notes.mark_done(b.id)

    pending = notes.list_notes()
    assert [n.id for n in pending] == [a.id]

    everything = notes.list_notes(include_done=True)
    assert {n.id for n in everything} == {a.id, b.id}


def test_mark_done_sets_done_at(tmp_path, monkeypatch):
    notes = _reload_notes(tmp_path, monkeypatch)

    n = notes.add_note("do the thing")
    updated = notes.mark_done(n.id)

    assert updated is not None
    assert updated.done is True
    assert updated.done_at is not None


def test_mark_done_unknown_id_returns_none(tmp_path, monkeypatch):
    notes = _reload_notes(tmp_path, monkeypatch)

    assert notes.mark_done("nonexistent") is None


def test_notes_persist_across_reload(tmp_path, monkeypatch):
    notes = _reload_notes(tmp_path, monkeypatch)
    notes.add_note("first")
    notes.add_note("second")

    notes = _reload_notes(tmp_path, monkeypatch)
    assert [n.text for n in notes.list_notes()] == ["first", "second"]
