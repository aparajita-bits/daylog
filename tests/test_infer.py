import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from daylog.infer import parse_shorthand


def test_bare_number_in_natural_language_is_not_swallowed_as_duration():
    # Regression: "since 15 minutes" used to silently consume "15" as a
    # 15-minute duration, leaving a garbled "since minutes" title.
    result = parse_shorthand("learning about mcp since 15 minutes", ["learning"], 30)
    assert result["title"] == "learning about mcp since 15 minutes"
    assert result["duration_min"] == 30  # falls back to default, no explicit unit given


def test_explicit_unit_suffix_still_parses():
    result = parse_shorthand("mtg design review 45m", ["meeting"], 30)
    assert result["title"] == "mtg design review"
    assert result["duration_min"] == 45

    result = parse_shorthand("AXON-1234 fixed pruning bug 1h30m", ["coding"], 30)
    assert result["title"] == "AXON-1234 fixed pruning bug"
    assert result["duration_min"] == 90
