"""Tests for consistency.record_shadow_observations()/get_shadow_observation_report()
-- backlog.txt "RAIN ARBITRAGE-CHECK SHADOW SIGNAL HAS NO GRADUATION DECISION
YET". No existing test to mirror directly; written from scratch against the
same RAIN_ARB_SHADOW_PATH/paths.py state-file convention test_series_drift.py
already established for check_series_drift().
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import consistency
from consistency import (
    Violation,
    get_shadow_observation_report,
    record_shadow_observations,
)


def _shadow(buy="KXRAINDENM-26JUL-1", sell="KXRAINDENM-26JUL-3", edge=0.05):
    return Violation(
        buy_ticker=buy,
        sell_ticker=sell,
        buy_prob=0.30,
        sell_prob=0.30 + edge,
        guaranteed_edge=edge,
        description="test shadow violation",
        is_shadow=True,
    )


def _real(buy="KXHIGHNY-26JUL17-T70", sell="KXHIGHNY-26JUL17-T65", edge=0.05):
    return Violation(
        buy_ticker=buy,
        sell_ticker=sell,
        buy_prob=0.30,
        sell_prob=0.30 + edge,
        guaranteed_edge=edge,
        description="test real violation",
        is_shadow=False,
    )


def test_first_call_creates_state_file(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([])

    assert path.exists()
    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 1
    assert state["cycles_with_violation"] == 0
    assert state["pairs"] == {}


def test_cycles_observed_increments_even_with_no_violations(tmp_path, monkeypatch):
    """cycles_observed is the denominator for a future violation-rate calc --
    it must count every cycle checked, not just cycles with a hit."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([])
    record_shadow_observations([])
    record_shadow_observations([])

    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 3
    assert state["cycles_with_violation"] == 0


def test_real_non_shadow_violations_are_filtered_out(tmp_path, monkeypatch):
    """A caller passing find_violations()'s raw (mixed) return value must
    never let a real temperature violation pollute the rain-only history --
    mutation-tested by removing the is_shadow filter and confirming this
    fails."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_real()])

    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 1
    assert state["cycles_with_violation"] == 0
    assert state["pairs"] == {}


def test_shadow_violation_recorded_and_cycles_with_violation_increments(
    tmp_path, monkeypatch
):
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow(edge=0.07)])

    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 1
    assert state["cycles_with_violation"] == 1
    key = "KXRAINDENM-26JUL-1|KXRAINDENM-26JUL-3"
    assert key in state["pairs"]
    entry = state["pairs"][key]
    assert entry["times_seen"] == 1
    assert entry["max_edge"] == 0.07
    assert entry["buy_ticker"] == "KXRAINDENM-26JUL-1"
    assert entry["sell_ticker"] == "KXRAINDENM-26JUL-3"


def test_repeated_pair_increments_times_seen_and_tracks_max_edge(tmp_path, monkeypatch):
    """A persistent violation is re-detected every cycle it lasts -- this
    must accumulate onto ONE pair entry, not create a new row each time."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow(edge=0.03)])
    record_shadow_observations([_shadow(edge=0.09)])  # edge widened this cycle
    record_shadow_observations([_shadow(edge=0.05)])  # narrowed again

    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 3
    assert state["cycles_with_violation"] == 3
    key = "KXRAINDENM-26JUL-1|KXRAINDENM-26JUL-3"
    entry = state["pairs"][key]
    assert entry["times_seen"] == 3
    # max_edge must track the highest edge ever seen, not the most recent.
    assert entry["max_edge"] == 0.09


def test_distinct_pairs_get_distinct_entries(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations(
        [_shadow(buy="A", sell="B", edge=0.02), _shadow(buy="C", sell="D", edge=0.04)]
    )

    state = json.loads(path.read_text())
    assert len(state["pairs"]) == 2
    assert state["cycles_with_violation"] == 1  # one cycle, two pairs in it


def test_corrupt_existing_state_falls_back_to_fresh_state(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow()])

    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 1
    assert state["cycles_with_violation"] == 1


def test_write_failure_never_raises(tmp_path, monkeypatch):
    """Entirely observational -- a persistence bug must never propagate out
    and threaten the caller's own trading-critical flow (mutation-tested by
    removing the try/except and confirming this raises)."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    def _boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(consistency.safe_io, "atomic_write_json", _boom)

    record_shadow_observations([_shadow()])  # must not raise


def test_report_returns_none_when_no_file(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    assert get_shadow_observation_report() is None


def test_report_returns_none_on_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    assert get_shadow_observation_report() is None


def test_report_computes_violation_rate_and_sorts_top_pairs(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    # 4 cycles: pair A|B seen 3x, pair C|D seen 1x.
    record_shadow_observations([_shadow(buy="A", sell="B", edge=0.02)])
    record_shadow_observations([_shadow(buy="A", sell="B", edge=0.02)])
    record_shadow_observations(
        [_shadow(buy="A", sell="B", edge=0.02), _shadow(buy="C", sell="D", edge=0.10)]
    )
    record_shadow_observations([])  # a clean cycle, no violation

    report = get_shadow_observation_report()
    assert report is not None
    assert report["cycles_observed"] == 4
    assert report["cycles_with_violation"] == 3
    assert report["violation_rate"] == 3 / 4
    assert report["distinct_pairs"] == 2
    # Most-observed pair must sort first.
    assert report["top_pairs"][0]["buy_ticker"] == "A"
    assert report["top_pairs"][0]["times_seen"] == 3
    assert report["top_pairs"][1]["buy_ticker"] == "C"
    assert report["top_pairs"][1]["times_seen"] == 1


# ── opus-review findings (M1/M2/M3/L2/L4/L9) ────────────────────────────────


def test_first_seen_preserved_across_repeated_sightings(tmp_path, monkeypatch):
    """A mutation that reset first_seen on every sighting (destroying "how
    long has this pair been misbehaving") would pass every other test in
    this file -- none of them asserted on first_seen/last_seen directly."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow()])
    first_state = json.loads(path.read_text())
    key = "KXRAINDENM-26JUL-1|KXRAINDENM-26JUL-3"
    original_first_seen = first_state["pairs"][key]["first_seen"]

    record_shadow_observations([_shadow()])
    record_shadow_observations([_shadow()])
    final_state = json.loads(path.read_text())
    entry = final_state["pairs"][key]

    assert entry["first_seen"] == original_first_seen
    assert entry["times_seen"] == 3


def test_last_seen_updates_to_most_recent_sighting(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow()])
    first_last_seen = json.loads(path.read_text())["pairs"][
        "KXRAINDENM-26JUL-1|KXRAINDENM-26JUL-3"
    ]["last_seen"]

    # Force a real timestamp change without sleeping the test.
    import consistency as _c

    class _Later(_c.datetime):
        @classmethod
        def now(cls, tz=None):
            return super().now(tz).replace(year=2099)

    monkeypatch.setattr(_c, "datetime", _Later)
    record_shadow_observations([_shadow()])

    entry = json.loads(path.read_text())["pairs"][
        "KXRAINDENM-26JUL-1|KXRAINDENM-26JUL-3"
    ]
    assert entry["last_seen"] != first_last_seen
    assert entry["last_seen"].startswith("2099")
    # first_seen must NOT jump to the later timestamp too.
    assert not entry["first_seen"].startswith("2099")


def test_description_tracks_the_max_edge_sighting_not_the_latest(tmp_path, monkeypatch):
    """description must stay consistent with max_edge (the sighting that
    SET the max), not silently drift to whichever sighting happened most
    recently -- an operator reading the raw JSON otherwise sees an edge
    number next to an unrelated description."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    big = _shadow(edge=0.09)
    big.description = "the big one"
    small = _shadow(edge=0.01)
    small.description = "a small one"

    record_shadow_observations([big])
    record_shadow_observations([small])  # smaller edge -- must not overwrite

    entry = json.loads(path.read_text())["pairs"][
        "KXRAINDENM-26JUL-1|KXRAINDENM-26JUL-3"
    ]
    assert entry["max_edge"] == 0.09
    assert entry["description"] == "the big one"


def test_corrupt_typed_existing_state_self_heals_instead_of_stalling_forever(
    tmp_path, monkeypatch
):
    """A parseable-but-wrong-typed existing file (e.g. cycles_observed
    stored as a string) must take the SAME 'log and start fresh' path as an
    unparseable file -- not raise past the fallback and silently repeat the
    same failure every cycle forever."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    path.write_text(json.dumps({"cycles_observed": "not-a-number", "pairs": {}}))
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow()])  # must not raise, must not stall

    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 1
    assert state["cycles_with_violation"] == 1


def test_corrupt_pairs_shape_self_heals(tmp_path, monkeypatch):
    """Same as above, for a 'pairs' field that parses but isn't a JSON
    object (e.g. a list)."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    path.write_text(json.dumps({"cycles_observed": 5, "pairs": ["not", "a", "dict"]}))
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow()])

    state = json.loads(path.read_text())
    assert state["cycles_observed"] == 1  # fresh state, not 6
    assert len(state["pairs"]) == 1


def test_non_dict_falsy_pair_entry_is_replaced_not_crashed_on(tmp_path, monkeypatch):
    """A stored pair value that's falsy AND not a dict (e.g. JSON `0` from
    some future corruption) must be replaced with a fresh entry, not passed
    through unmodified -- `entry is None` alone would let a non-None falsy
    value through untouched and crash on the next line's `entry.get(...)`.
    The isinstance(entry, dict) check is what actually distinguishes this
    from the original `pairs.get(key) or {...}` shape: both handle a
    falsy-and-not-a-dict value, but a bare `is None` check does not."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    key = "KXRAINDENM-26JUL-1|KXRAINDENM-26JUL-3"
    path.write_text(json.dumps({"cycles_observed": 3, "pairs": {key: 0}}))
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    record_shadow_observations([_shadow()])  # must not raise

    state = json.loads(path.read_text())
    entry = state["pairs"][key]
    assert entry["times_seen"] == 1
    assert entry["buy_ticker"] == "KXRAINDENM-26JUL-1"


def test_write_uses_emergency_copy_false(tmp_path, monkeypatch):
    """This is a purely observational log, not irreplaceable trading state
    -- must not trip cron.py's check_emergency_copies() operator alert on a
    transient write failure the way trading-critical state correctly does."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    calls = []
    monkeypatch.setattr(
        consistency.safe_io,
        "atomic_write_json",
        lambda *a, **kw: calls.append(kw),
    )

    record_shadow_observations([_shadow()])

    assert calls == [{"emergency_copy": False}]


def test_record_failure_logs_at_warning_not_debug(tmp_path, monkeypatch, caplog):
    """A permanently-broken recorder must be operator-visible -- DEBUG-level
    logging (the original level) would let months of silent failure pass
    with zero trace."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)
    monkeypatch.setattr(
        consistency.safe_io,
        "atomic_write_json",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")),
    )

    with caplog.at_level(logging.WARNING, logger="consistency"):
        record_shadow_observations([_shadow()])

    assert any(
        r.levelno == logging.WARNING
        and "record_shadow_observations failed" in r.message
        for r in caplog.records
    )


def test_report_returns_none_when_json_root_is_not_a_dict(tmp_path, monkeypatch):
    path = tmp_path / "rain_arb_shadow_observations.json"
    path.write_text(json.dumps(["not", "a", "dict"]))
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    assert get_shadow_observation_report() is None


def test_report_returns_none_on_malformed_pairs_shape(tmp_path, monkeypatch):
    """pairs stored as a list (not a dict of entries) -- must degrade to
    None, never raise, since this is display-path-only (`py main.py
    consistency`, including the interactive menu)."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    path.write_text(
        json.dumps({"cycles_observed": 3, "cycles_with_violation": 1, "pairs": [1, 2]})
    )
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    assert get_shadow_observation_report() is None


def test_report_returns_none_when_a_pair_entry_is_not_a_dict(tmp_path, monkeypatch):
    """`pairs` itself is a real dict (passes the isinstance(pairs, dict)
    guard) but one VALUE inside it isn't a dict -- this only surfaces once
    sorted()'s key lambda calls `.get` on it, past every guard specific to
    the top-level shape. Proves the function's own outer try/except (not
    just the two isinstance checks) is load-bearing."""
    path = tmp_path / "rain_arb_shadow_observations.json"
    path.write_text(
        json.dumps(
            {
                "cycles_observed": 3,
                "cycles_with_violation": 1,
                "pairs": {"A|B": "not-a-dict-entry"},
            }
        )
    )
    monkeypatch.setattr(consistency, "RAIN_ARB_SHADOW_PATH", path)

    assert get_shadow_observation_report() is None
