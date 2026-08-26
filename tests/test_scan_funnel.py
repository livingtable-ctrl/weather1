"""Tests for the A12 scanner funnel -- weather_markets' declared gate order,
its bounded closest-miss retention, tracker.get_scan_activity(), and the
/api/scanner-funnel endpoint that joins them.

The gate-coverage test is the structural one: it re-derives the set of
_count_gate() literals in weather_markets.py from its AST and asserts
SCAN_GATES covers exactly that set, so a gate added without a ScanGate entry
fails here rather than silently dropping out of the funnel.

DB isolation comes from conftest.py's autouse `isolate_tracker_db` fixture;
SCAN_FUNNEL_PATH is redirected by `isolate_cron_generated_files`.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import tracker
import weather_markets as wm


@pytest.fixture(autouse=True)
def _clean_gate_state():
    """Every test starts from an empty scan and leaves one behind.

    reset_gate_counts() is the production entry point for this, so using it
    here also keeps the tests honest about what a real scan boundary does.

    `_unknown_gates_warned` is deliberately process-global in production (warn
    once per process, not once per rejected market) and reset_gate_counts()
    does NOT clear it. Two tests here use the same unknown gate name, so
    without an explicit clear whichever ran first would permanently suppress
    the warning for the other -- order-dependent state under the repo's
    default random test ordering.
    """
    wm.reset_gate_counts()
    wm._unknown_gates_warned.clear()
    yield
    wm.reset_gate_counts()
    wm._unknown_gates_warned.clear()


class TestDeclaredGateOrder:
    def test_scan_gates_covers_exactly_the_count_gate_call_sites(self):
        """Re-derived from the AST, not from a hand-maintained list.

        A gate added to analyze_trade() without a ScanGate entry would still be
        counted, but could not be placed in the funnel -- and a ScanGate entry
        for a gate that no longer exists would draw a row that can never fill.
        """
        src = Path(wm.__file__).read_text(encoding="utf-8")
        emitted = set()
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_count_gate"
            ):
                assert isinstance(node.args[0], ast.Constant), (
                    "_count_gate's name must be a literal so this scan can see it"
                )
                emitted.add(node.args[0].value)

        declared = [g.name for g in wm.SCAN_GATES]

        assert emitted, "positive control: the scan found no call sites at all"
        assert len(declared) == len(set(declared)), "duplicate ScanGate name"
        assert set(declared) - emitted == set(), "declared but never emitted"
        assert emitted - set(declared) == set(), "emitted but not declared"

    def test_declared_order_matches_first_occurrence_order_in_the_source(self):
        """Set equality is not enough: the ORDER is the feature. Someone adding
        a gate mid-pipeline and appending its ScanGate entry at the end of the
        tuple -- the natural thing to do -- would pass every other test here
        while making `last_gate` wrong forever.

        TWO gates are excluded by name, and only two:

          hourly_thin_ensemble / degenerate_ens -- emitted inside
            _analyze_hourly_trade, a helper DEFINED earlier in the file than
            analyze_trade but CALLED from partway down it. First-occurrence
            line order sorts them to the very front, so they are declared
            where the dispatch happens instead.

        The daily_* pair is deliberately NOT excluded: it is emitted from the
        non-hourly branch at source lines that DO fall in declared order, so
        excluding it would drop real coverage of its position for no reason.
        The remaining 34 are pinned to source order exactly.
        """
        src = Path(wm.__file__).read_text(encoding="utf-8")
        first_line: dict[str, int] = {}
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_count_gate"
                and isinstance(node.args[0], ast.Constant)
            ):
                name = node.args[0].value
                first_line[name] = min(first_line.get(name, node.lineno), node.lineno)

        DUAL_BRANCH = {"hourly_thin_ensemble", "degenerate_ens"}
        by_source = [
            n for n in sorted(first_line, key=first_line.get) if n not in DUAL_BRANCH
        ]
        declared = [g.name for g in wm.SCAN_GATES if g.name not in DUAL_BRANCH]

        # Positive control: the scan found real line numbers, not an empty map.
        assert len(by_source) == 34
        assert declared == by_source

    def test_every_gate_has_a_non_empty_label_and_a_known_stage(self):
        for gate in wm.SCAN_GATES:
            assert gate.label.strip(), gate.name
            # A typo'd stage would create a phantom funnel section on the
            # panel; the vocabulary is closed.
            assert gate.stage in wm.SCAN_GATE_STAGES, (gate.name, gate.stage)
            # The label is for humans -- it must not just echo the key.
            assert gate.label != gate.name, gate.name

    def test_counts_come_back_in_declared_order_not_first_hit_order(self):
        """The bug this whole item exists for: a plain dict's key order is the
        order each gate first fired, so a late gate that fired first sorts
        first. Firing extreme_price (declared late) before past_date (declared
        early) must still yield past_date first.
        """
        wm._count_gate("extreme_price")
        wm._count_gate("past_date")
        wm._count_gate("no_city")

        keys = list(wm.get_gate_counts())

        assert keys == ["no_city", "past_date", "extreme_price"]
        # Positive control that the premise is real: insertion order genuinely
        # is the other way round.
        assert list(wm._gate_counts) == ["extreme_price", "past_date", "no_city"]

    def test_an_unknown_gate_is_counted_and_sorts_after_every_declared_gate(self):
        wm._count_gate("past_date")
        wm._count_gate("brand_new_gate")

        counts = wm.get_gate_counts()
        funnel = wm.get_scan_funnel()

        assert counts == {"past_date": 1, "brand_new_gate": 1}
        assert list(counts) == ["past_date", "brand_new_gate"]
        assert funnel["unknown_gates"] == {"brand_new_gate": 1}
        assert [g["name"] for g in funnel["gates"]] == ["past_date"]

    def test_an_unknown_gate_warns_exactly_once_per_process(self, caplog):
        """Once per process, not once per rejected market: this fires inside
        analyze_trade, which runs across 8 workers over ~590 markets.
        """
        with caplog.at_level("WARNING", logger="weather_markets"):
            for _ in range(5):
                wm._count_gate("brand_new_gate")

        warnings = [r for r in caplog.records if "brand_new_gate" in r.getMessage()]
        assert len(warnings) == 1
        assert "SCAN_GATES" in warnings[0].getMessage()
        # Positive control: all five rejections were still counted, so the
        # single warning is deduplication rather than four dropped calls.
        assert wm.get_gate_counts()["brand_new_gate"] == 5

    def test_a_declared_gate_never_warns(self, caplog):
        """Positive control for the test above: the warning path is not simply
        unreachable."""
        with caplog.at_level("WARNING", logger="weather_markets"):
            wm._count_gate("past_date")

        assert [r for r in caplog.records if "SCAN_GATES" in r.getMessage()] == []
        assert wm.get_gate_counts()["past_date"] == 1

    def test_last_gate_is_the_deepest_declared_gate_that_fired(self):
        wm._count_gate("extreme_price")
        wm._count_gate("no_city")
        wm._count_gate("past_date")

        last = wm.get_scan_funnel()["last_gate"]

        assert last["name"] == "extreme_price"
        assert last["label"] == wm._GATE_BY_NAME["extreme_price"].label
        assert last["order"] == wm._GATE_ORDER["extreme_price"]

    def test_last_gate_is_none_when_only_unknown_gates_fired(self):
        """An unknown gate has no declared position, so calling it "last" would
        be a guess. It must appear in unknown_gates instead.
        """
        wm._count_gate("brand_new_gate")

        funnel = wm.get_scan_funnel()

        assert funnel["last_gate"] is None
        # Positive control: the rejection was recorded, not dropped.
        assert funnel["total_rejected"] == 1
        assert funnel["unknown_gates"] == {"brand_new_gate": 1}

    def test_last_gate_is_none_when_nothing_was_rejected(self):
        funnel = wm.get_scan_funnel()

        assert funnel["last_gate"] is None
        assert funnel["gates"] == []
        assert funnel["total_rejected"] == 0


class TestNearMissRetention:
    def test_a_numeric_gate_records_the_margin_it_missed_by(self):
        """miss_frac is |value - threshold| / |threshold|: a 12-day horizon
        against a 10-day cap misses by 2/10 = 0.2.
        """
        wm._count_gate("days_out", ticker="KX-A", value=12, threshold=10, unit="days")

        (miss,) = wm.get_scan_funnel()["near_misses"]

        assert miss["gate"] == "days_out"
        assert miss["ticker"] == "KX-A"
        assert miss["value"] == 12
        assert miss["threshold"] == 10
        assert miss["unit"] == "days"
        assert miss["miss_frac"] == pytest.approx(0.2)

    def test_extreme_price_ranks_both_sides_of_the_band_on_one_scale(self):
        """miss_frac divides by the threshold, so reporting the raw ask against
        MIN_MARKET_PRICE on the low side and 1 - MIN_MARKET_PRICE on the high
        side divided by 0.05 and 0.95 -- a factor of 19. An ask of 0.99 (4c
        past the bar) then scored a SMALLER miss_frac than 0.045 (0.5c from
        it), and every high-side rejection was structurally capped at
        0.05/0.95 = 0.0526, so the list filled with 0.95-0.99 markets ranked
        backwards. Distance to the nearest edge of the band is symmetric.
        """
        # The production CALL SITE is asserted from source, not re-implemented
        # here: a test that computes min(ask, 1 - ask) itself would pass no
        # matter what analyze_trade actually passes, which is the whole bug.
        tree = ast.parse(Path(wm.__file__).read_text(encoding="utf-8"))
        call = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_count_gate"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "extreme_price"
        )
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        # value must be min(_yes_ask, 1 - _yes_ask) -- symmetric about the band
        assert isinstance(kwargs["value"], ast.Call)
        assert getattr(kwargs["value"].func, "id", None) == "min"
        # ...and threshold must be the BARE constant, not a side-dependent
        # conditional, or the two halves divide by 0.05 and 0.95 again.
        assert isinstance(kwargs["threshold"], ast.Name)
        assert kwargs["threshold"].id == "MIN_MARKET_PRICE"

        bar = wm.MIN_MARKET_PRICE

        def _record(ticker, ask):
            # Mirrors the asserted call site above.
            wm._count_gate(
                "extreme_price",
                ticker=ticker,
                value=min(ask, 1 - ask),
                threshold=bar,
                unit="dist to price band",
            )

        # Mirror-image asks must score IDENTICAL miss_frac.
        _record("LOW", 0.045)
        _record("HIGH", 1 - 0.045)
        by_ticker = {m["ticker"]: m for m in wm.get_scan_funnel()["near_misses"]}
        assert by_ticker["LOW"]["miss_frac"] == by_ticker["HIGH"]["miss_frac"]

        # ...and a market further past the bar must score WORSE, not better.
        wm.reset_gate_counts()
        _record("NEAR", 0.045)  # 0.5c from the bar
        _record("FAR", 0.99)  # 4c past it
        ranked = [m["ticker"] for m in wm.get_scan_funnel()["near_misses"]]
        assert ranked == ["NEAR", "FAR"]

    def test_a_categorical_gate_contributes_a_count_but_no_near_miss(self):
        wm._count_gate("no_city")

        funnel = wm.get_scan_funnel()

        assert funnel["near_misses"] == []
        # Positive control paired with the empty-list assertion: the gate WAS
        # reached, so the absence is "no margin to report", not "never ran".
        assert funnel["total_rejected"] == 1
        assert [g["name"] for g in funnel["gates"]] == ["no_city"]

    def test_retention_is_bounded_per_gate_and_keeps_the_closest(self):
        """Fifty rejections from ONE gate, two slots for it. The two closest
        must survive and its bucket must never grow past the cap in between.
        """
        per_gate = wm.SCAN_NEAR_MISS_PER_GATE
        # miss_frac = i/100 for i in 1..50, so the closest are i = 1..per_gate.
        for i in range(1, 51):
            wm._count_gate(
                "spread",
                ticker=f"KX-{i}",
                value=100 + i,
                threshold=100,
                unit="frac of mid",
            )
            # <= per_gate, not per_gate + 1: the trim runs inside the same
            # locked block as the append, so the cap holds on every
            # observable state. The looser bound would pass a trim that
            # kept one extra entry forever.
            assert len(wm._gate_near_misses["spread"]) <= per_gate

        misses = wm.get_scan_funnel()["near_misses"]

        assert len(misses) == per_gate
        assert [m["ticker"] for m in misses] == [
            f"KX-{i}" for i in range(1, per_gate + 1)
        ]
        # Positive control: every one of the fifty was still counted.
        assert wm.get_gate_counts()["spread"] == 50

    def test_a_loud_gate_cannot_evict_a_quiet_gate_s_only_candidate(self):
        """The reason retention is per-gate. extreme_price fires 184x and
        spread 127x in a real scan; a global-only top-K would fill every slot
        with near-identical rows from whichever gate fires most and drop the
        single model_spread candidate that actually tells an operator
        something new.
        """
        # 50 spread rejections, all closer than the one model_spread row.
        for i in range(1, 51):
            wm._count_gate(
                "spread", ticker=f"LOUD-{i}", value=100.001 * i, threshold=100 * i
            )
        wm._count_gate(
            "model_spread", ticker="QUIET", value=8.1, threshold=8.0, unit="\u00b0F"
        )

        misses = wm.get_scan_funnel()["near_misses"]

        # The quiet gate survives despite being the WORST miss in the set...
        assert "QUIET" in [m["ticker"] for m in misses]
        # ...and the loud gate is held to its per-gate cap.
        assert sum(1 for m in misses if m["gate"] == "spread") == (
            wm.SCAN_NEAR_MISS_PER_GATE
        )
        assert len(misses) <= wm.SCAN_NEAR_MISS_LIMIT

    def test_near_miss_order_is_deterministic_on_ties(self):
        """Equal miss_frac across gates must not depend on which pool worker
        recorded first, or the panel reshuffles between identical scans.
        """
        for gate, ticker in (
            ("spread", "B"),
            ("model_spread", "A"),
            ("min_volume", "C"),
        ):
            wm._count_gate(gate, ticker=ticker, value=2.0, threshold=1.0)

        first = [(m["gate"], m["ticker"]) for m in wm.get_scan_funnel()["near_misses"]]

        wm.reset_gate_counts()
        for gate, ticker in (
            ("min_volume", "C"),
            ("spread", "B"),
            ("model_spread", "A"),
        ):
            wm._count_gate(gate, ticker=ticker, value=2.0, threshold=1.0)

        second = [(m["gate"], m["ticker"]) for m in wm.get_scan_funnel()["near_misses"]]

        assert first == second
        # Positive control: all three really are tied, so the ordering above is
        # the tiebreak's doing rather than miss_frac's.
        assert len({m["miss_frac"] for m in wm.get_scan_funnel()["near_misses"]}) == 1

    def test_within_gate_ties_are_broken_deterministically_too(self):
        """The per-gate trim in _count_gate is a SEPARATE sort from the global
        one in get_scan_funnel, and it is where arrival order across 8 pool
        workers would otherwise decide which tied candidate survives. Three
        different gates with one entry each never reach that trim, so this
        needs ties inside ONE gate, over the per-gate cap.
        """
        tied = ["D", "A", "C", "B"]
        assert len(tied) > wm.SCAN_NEAR_MISS_PER_GATE  # the trim must fire

        for ticker in tied:
            wm._count_gate("spread", ticker=ticker, value=2.0, threshold=1.0)
        first = [m["ticker"] for m in wm.get_scan_funnel()["near_misses"]]

        wm.reset_gate_counts()
        for ticker in reversed(tied):
            wm._count_gate("spread", ticker=ticker, value=2.0, threshold=1.0)
        second = [m["ticker"] for m in wm.get_scan_funnel()["near_misses"]]

        # Positive control: the trim really did discard some, and every
        # survivor really is tied on miss_frac.
        assert len(first) == wm.SCAN_NEAR_MISS_PER_GATE
        assert len({m["miss_frac"] for m in wm.get_scan_funnel()["near_misses"]}) == 1
        # Insertion order must not decide the survivors.
        assert first == second == sorted(tied)[: wm.SCAN_NEAR_MISS_PER_GATE]

    def test_a_ticker_key_present_but_none_still_yields_a_usable_ticker(self):
        """`.get("ticker", "?")` applies its default only when the KEY IS
        ABSENT -- a key present with value None returns None, and
        _near_miss_entry drops any record whose ticker is None, silently losing
        a margin every other gate would have reported.
        """
        # The behaviour that makes it matter.
        assert (
            wm._near_miss_entry("spread", None, value=2.0, threshold=1.0, unit="")
            is None
        )
        # Positive control: an identical call WITH a ticker does produce one.
        assert (
            wm._near_miss_entry("spread", "KX", value=2.0, threshold=1.0, unit="")
            is not None
        )

        # ...and analyze_trade's own binding must use the `or` form, asserted
        # from source because reaching it otherwise means driving a full
        # analyze_trade call.
        src = Path(wm.__file__).read_text(encoding="utf-8")
        assert 'enriched.get("ticker") or "?"' in src
        assert '_tkr = enriched.get("ticker", "?")' not in src

    def test_a_zero_threshold_yields_a_count_only(self):
        """There is no fraction to take of zero, and reporting a raw difference
        beside other gates' fractions would rank two different quantities in
        one column.
        """
        wm._count_gate("model_mkt_gap", ticker="KX-Z", value=5, threshold=0)

        funnel = wm.get_scan_funnel()

        assert funnel["near_misses"] == []
        assert funnel["total_rejected"] == 1  # positive control

    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_values_never_reach_the_payload(self, bad):
        """jsonify() emits bare Infinity/NaN, which JSON.parse rejects -- one
        poisoned row would kill the whole panel rather than one cell.
        """
        wm._count_gate("spread", ticker="KX-BAD", value=bad, threshold=0.3)
        wm._count_gate("spread", ticker="KX-OK", value=0.4, threshold=0.3)

        funnel = wm.get_scan_funnel()

        assert [m["ticker"] for m in funnel["near_misses"]] == ["KX-OK"]
        json.dumps(funnel, allow_nan=False)

    def test_a_non_numeric_value_is_ignored_rather_than_raising(self):
        wm._count_gate("spread", ticker="KX-STR", value="wide", threshold=0.3)

        funnel = wm.get_scan_funnel()

        assert funnel["near_misses"] == []
        assert funnel["total_rejected"] == 1  # positive control

    def test_a_quotient_that_overflows_to_infinity_is_dropped(self):
        """Both operands finite is not enough: float division overflows to inf
        rather than raising, and safe_io.atomic_write_json leaves allow_nan at
        its True default, so an inf would be written to disk as a bare
        `Infinity` and stay there until the next scan.
        """
        # Positive control on the premise: this really does overflow.
        assert abs(1e308 - 1.0) / abs(1e-300) == float("inf")

        wm._count_gate("spread", ticker="OVERFLOW", value=1e308, threshold=1e-300)
        wm._count_gate("spread", ticker="FINE", value=2.0, threshold=1.0)

        funnel = wm.get_scan_funnel()

        assert [m["ticker"] for m in funnel["near_misses"]] == ["FINE"]
        assert funnel["total_rejected"] == 2  # both still counted
        json.dumps(funnel, allow_nan=False)

    def test_reset_clears_counts_and_near_misses_together(self):
        wm._count_gate("spread", ticker="KX-A", value=0.4, threshold=0.3)
        assert wm.get_scan_funnel()["near_misses"]  # positive control

        wm.reset_gate_counts()
        funnel = wm.get_scan_funnel()

        assert funnel["near_misses"] == []
        assert funnel["gates"] == []
        assert funnel["total_rejected"] == 0
        assert funnel["scan_started_at"] is not None


class TestSnapshotWrite:
    def test_snapshot_writes_the_funnel(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", tmp_path / "scan_funnel.json")
        wm._count_gate("past_date")
        wm._count_gate("days_out", ticker="KX-A", value=12, threshold=10, unit="days")

        assert wm.snapshot_scan_funnel() is True

        written = json.loads((tmp_path / "scan_funnel.json").read_text("utf-8"))
        assert [g["name"] for g in written["gates"]] == ["past_date", "days_out"]
        assert written["last_gate"]["name"] == "days_out"
        assert written["near_misses"][0]["ticker"] == "KX-A"
        assert written["snapshot_at"]
        # Timestamps must carry an offset: a naive "2026-08-25T06:36:00" is
        # parsed as LOCAL time by JavaScript's Date, shifting the panel's clock
        # by the viewer's UTC offset.
        assert datetime.fromisoformat(written["snapshot_at"]).tzinfo is not None
        assert datetime.fromisoformat(written["scan_started_at"]).tzinfo is not None
        # No temp file left behind by the atomic write.
        assert list(tmp_path.glob("*.tmp")) == []

    def test_snapshot_never_raises_when_the_write_fails(self, tmp_path, monkeypatch):
        """A dashboard artifact must not be able to fail a scan.

        The failure is injected at safe_io rather than by pointing at a missing
        directory: atomic_write_json creates its parents, so a nonexistent path
        succeeds and would make this test pass vacuously.
        """
        monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", tmp_path / "f.json")
        wm._count_gate("past_date")

        calls: list = []

        def _boom(*a, **kw):
            calls.append((a, kw))
            raise OSError("disk full")

        monkeypatch.setattr(wm._safe_io, "atomic_write_json", _boom)

        assert wm.snapshot_scan_funnel() is False
        # The write really was attempted -- a raising double inside a function
        # that swallows exceptions proves nothing on its own.
        assert len(calls) == 1
        # ...and the in-memory funnel is intact, so the False came from the
        # write and not from an empty scan.
        assert wm.get_scan_funnel()["total_rejected"] == 1

    def test_snapshot_opts_out_of_the_emergency_copy(self, tmp_path, monkeypatch):
        """Two write options this artifact must not take the default on.

        emergency_copy: the default lands a file in
        <project_root>/data/.emergency/ -- the MAIN CLONE's data dir even from
        a worktree -- and cron.py's check_emergency_copies() then re-alerts the
        operator every cycle until it is deleted by hand. This artifact is
        fully re-derivable by the next scan, so it must not pay that cost.

        retries: the default is 3 attempts with a 1s sleep between them, and
        this call runs on the scan path before placement.
        """
        monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", tmp_path / "f.json")
        wm._count_gate("past_date")

        seen: list = []

        def _record(data, path, **kw):
            seen.append(kw)
            path.write_text(json.dumps(data), encoding="utf-8")

        monkeypatch.setattr(wm._safe_io, "atomic_write_json", _record)

        assert wm.snapshot_scan_funnel() is True
        # retries=1 as well: safe_io sleeps 1s between attempts, and this call
        # sits on the scan path ahead of placement, so 3 attempts would cost
        # ~5s there. One attempt caps it at the replace deadline.
        assert seen == [{"retries": 1, "emergency_copy": False}]

    def test_a_partial_scan_is_labelled_as_such(self, tmp_path, monkeypatch):
        """run_trade_cycle swallows both a TimeoutError and a general exception
        from its analysis pool and carries on, so a funnel covering 120 of 590
        markets would otherwise be indistinguishable from a full one -- an
        operator would read a truncated gate distribution as a change in the
        market universe.
        """
        monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", tmp_path / "scan_funnel.json")
        wm._count_gate("past_date")

        assert wm.snapshot_scan_funnel(complete=False) is True
        written = json.loads((tmp_path / "scan_funnel.json").read_text("utf-8"))
        assert written["complete"] is False

        # Positive control: the same call defaults to a complete scan, so the
        # False above came from the argument and not from a constant.
        assert wm.snapshot_scan_funnel() is True
        assert (
            json.loads((tmp_path / "scan_funnel.json").read_text("utf-8"))["complete"]
            is True
        )

    def test_the_kill_switch_break_leaves_the_scan_incomplete(self):
        """The mid-scan kill-switch check BREAKS out of the analysis loop. A
        plain `_scan_completed = True` after the loop would then stamp
        complete=True on a scan abandoned at market 120 of 590 -- exactly the
        claim the flag exists to prevent.

        Asserted structurally: the assignment must live in the loop's `else`
        clause, which Python runs ONLY when the loop was not broken out of.
        """
        tree = ast.parse(
            (Path(wm.__file__).parent / "trade_cycle.py").read_text(encoding="utf-8")
        )
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "run_trade_cycle"
        )
        loops = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.For)
            and any(isinstance(b, ast.Break) for b in ast.walk(n))
        ]

        # Positive control: the loop this guards really does contain a break,
        # so the for/else below is load-bearing rather than decorative.
        assert loops, "expected an analysis loop containing a break"

        setters = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", None) == "_scan_completed"
            and isinstance(n.value, ast.Constant)
            and n.value.value is True
        ]
        assert len(setters) == 1

        in_orelse = any(
            setter is stmt
            for loop in loops
            for stmt in loop.orelse
            for setter in setters
        )
        assert in_orelse, (
            "_scan_completed = True must sit in the analysis loop's `else` "
            "clause; anywhere else and a kill-switch break marks a truncated "
            "scan complete"
        )

    def test_no_early_return_can_skip_the_snapshot(self):
        """The invariant this test exists for was a real regression.

        The call was briefly moved AFTER the placement loop, to keep a
        worst-case ~5s atomic write off the path between the scan finishing
        and orders being submitted. That put it behind run_trade_cycle's
        kill-switch `return None`, so a mid-scan kill switch left the panel
        showing the PREVIOUS scan's funnel at exactly the moment an operator
        was asking what had just happened. The latency is handled inside
        snapshot_scan_funnel() with retries=1 instead.

        Asserted structurally rather than by exercising the kill-switch path:
        any FUTURE early return added between the scan loop and the snapshot
        re-breaks this, and only a structural check catches that.
        """
        tree = ast.parse(
            (Path(wm.__file__).parent / "trade_cycle.py").read_text(encoding="utf-8")
        )
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "run_trade_cycle"
        )
        # Returns belonging to nested helpers are not run_trade_cycle's own.
        nested = {
            id(x)
            for f in ast.walk(fn)
            if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef) and f is not fn
            for x in ast.walk(f)
        }
        flag_init = next(
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", None) == "_scan_completed"
            and isinstance(n.value, ast.Constant)
            and n.value.value is False
        )
        snapshot = next(
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "snapshot_scan_funnel"
        )
        returns = [
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Return) and id(n) not in nested
        ]

        # Positive control: run_trade_cycle really does contain early returns,
        # so an empty "between" set below is a real ordering property and not
        # an artefact of finding no returns at all.
        assert returns, "expected run_trade_cycle to have return statements"
        assert any(r > snapshot.lineno for r in returns), (
            "expected at least one return AFTER the snapshot -- if none exist, "
            "this test can no longer detect the regression it guards"
        )

        between = [r for r in returns if flag_init.lineno < r < snapshot.lineno]
        assert between == [], (
            f"return(s) at line(s) {between} sit between _scan_completed's "
            f"initialisation (line {flag_init.lineno}) and "
            f"snapshot_scan_funnel() (line {snapshot.lineno}) -- those paths "
            f"would skip the snapshot and serve a stale funnel"
        )

    def test_the_read_helpers_do_not_write_anything(self, tmp_path, monkeypatch):
        """get_gate_counts()/reset_gate_counts() are called from ~50 tests and
        from main.py, and paths.py resolves data/ to the main clone even from a
        worktree -- a write hidden in either would land in production data/.
        """
        target = tmp_path / "scan_funnel.json"
        monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", target)

        wm._count_gate("past_date")
        wm.get_gate_counts()
        wm.get_scan_funnel()
        wm.reset_gate_counts()

        assert not target.exists()
        # Positive control: the same path IS written by the explicit snapshot.
        wm._count_gate("past_date")
        wm.snapshot_scan_funnel()
        assert target.exists()

    def test_run_trade_cycle_is_the_only_scan_time_snapshot_call_site(self):
        """The hook must stay a single explicit call. If a second one appears,
        the "one write per scan" claim in snapshot_scan_funnel()'s docstring is
        no longer true.

        Counted as AST Call nodes, not as a substring: documenting the call in
        a comment or docstring in the same file is a perfectly reasonable thing
        to do and must not fail this guard.
        """
        src = Path(wm.__file__).parent / "trade_cycle.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))

        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "snapshot_scan_funnel"
        ]

        assert len(calls) == 1
        # ...and it passes the loop's own completion VARIABLE, not a literal.
        # Asserting only the keyword's name would let `complete=True` through,
        # which is precisely the claim a crashed scan must not make.
        (kw,) = calls[0].keywords
        assert kw.arg == "complete"
        assert isinstance(kw.value, ast.Name), ast.dump(kw.value)
        assert kw.value.id == "_scan_completed"


class TestScanActivity:
    def _insert_attempt(self, ticker: str, when: str) -> None:
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO analysis_attempts (ticker, city, condition, "
                "target_date, analyzed_at, forecast_prob, market_prob, days_out) "
                "VALUES (?, 'nyc', 'above', '2026-01-06', ?, 0.5, 0.5, 1)",
                (ticker, when),
            )

    def _insert_prediction(self, ticker: str, when: str) -> None:
        with tracker._conn() as con:
            con.execute(
                "INSERT INTO predictions (ticker, city, market_date, our_prob, "
                "days_out, predicted_at, predicted_date) VALUES "
                "(?, 'nyc', '2026-01-06', 0.5, 1, ?, ?)",
                (ticker, when, when[:10]),
            )

    def test_the_three_day_states_are_distinguished(self):
        """ "analysed, no signals" is an edge/threshold story; "no output" is
        ambiguous between an outage and a fully-gated day and must not be
        labelled as either.

        Dates are derived from the returned days_series rather than recomputed
        from datetime.now(): the function takes its own clock reading, so a UTC
        midnight crossing between the two would put the expected key outside
        the window and raise KeyError.
        """
        now = datetime.now(UTC)

        def stamp(days_ago: int) -> str:
            return (now - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")

        self._insert_attempt("A1", stamp(0))
        self._insert_prediction("P1", stamp(0))
        self._insert_attempt("A2", stamp(1))  # reached analysis, no prediction
        # day 2: nothing at all

        out = tracker.get_scan_activity(3)
        series = out["days_series"]

        assert out["days"] == 3
        assert len(series) == 3
        # days_series is ordered oldest -> newest, so index -1 is "today".
        assert series[-1]["state"] == "signals"
        assert series[-1]["signals"] == 1
        assert series[-2]["state"] == "analysed, no signals"
        assert series[-2]["reached_analysis"] == 1
        assert series[-2]["signals"] == 0
        assert series[-3]["state"] == "no output"
        assert out["signal_days"] == 1
        assert out["analysed_no_signal_days"] == 1
        assert out["no_output_days"] == 1

    def test_no_output_is_not_reported_as_an_outage(self):
        """The H1 trap: `analysis_attempts` only gets a row for a market that
        survived EVERY gate, so a day where the scanner ran fine and gated all
        590 markets produces zero rows in both tables. Calling that "no scan"
        would turn a routine modelling day into a phantom outage -- the exact
        inversion this function exists to prevent.

        batch-78 gave the function a third table (`scan_runs`) that CAN name
        an outage, so the vocabulary now exists -- but it stays unused while
        that table is empty, which is the state here.
        """
        out = tracker.get_scan_activity(3)

        states = {d["state"] for d in out["days_series"]}
        assert states == {"no output"}
        # The verdict must not claim to know a cause it cannot observe.
        assert "no scan" not in states
        assert out["no_scan_days"] == 0
        assert out["scan_coverage_from"] is None
        assert out["no_output_days"] == 3

    def test_every_day_in_the_window_is_present_including_empty_ones(self):
        out = tracker.get_scan_activity(30)

        assert len(out["days_series"]) == 30
        assert out["days_series"][0]["date"] == out["start_date"]
        assert out["days_series"][-1]["date"] == out["end_date"]
        assert out["no_output_days"] == 30
        assert out["signal_days"] == 0
        assert out["analysed_no_signal_days"] == 0

    def test_rows_outside_the_window_are_not_counted(self):
        now = datetime.now(UTC)
        inside = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        outside = (now - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
        self._insert_prediction("IN", inside)
        self._insert_prediction("OUT", outside)

        out = tracker.get_scan_activity(30)

        assert out["total_signals"] == 1
        # Positive control: widening the window picks the older row back up, so
        # the count above is the window's doing and not a failed insert.
        assert tracker.get_scan_activity(60)["total_signals"] == 2

    def test_totals_and_the_series_agree(self):
        now = datetime.now(UTC)
        for i in range(3):
            when = (now - timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S")
            self._insert_attempt(f"A{i}", when)
            self._insert_prediction(f"P{i}", when)

        out = tracker.get_scan_activity(30)

        assert out["total_signals"] == sum(d["signals"] for d in out["days_series"])
        assert out["total_reached_analysis"] == sum(
            d["reached_analysis"] for d in out["days_series"]
        )
        assert out["total_signals"] == 3

    def test_reached_analysis_is_not_assumed_to_be_a_superset_of_signals(self):
        """`analysis_attempts` upserts on (ticker, target_date), so re-analysing
        a market later moves its row's analyzed_at forward instead of adding
        one -- on live data reached_analysis < signals on 4 of the last 32
        days. A panel must not draw the two as one funnel, and this function
        must not silently repair the inversion.
        """
        when = (datetime.now(UTC)).strftime("%Y-%m-%d %H:%M:%S")
        self._insert_prediction("P1", when)
        self._insert_prediction("P2", when)
        # No attempt rows at all for the same day.

        out = tracker.get_scan_activity(1)
        today = out["days_series"][-1]

        assert today["signals"] == 2
        assert today["reached_analysis"] == 0
        # Reported honestly rather than clamped, and the day still reads as a
        # signal day because a prediction is the stronger evidence.
        assert today["state"] == "signals"

    def test_a_zero_or_negative_window_collapses_to_a_single_day(self):
        for arg in (0, -5):
            out = tracker.get_scan_activity(arg)
            assert out["days"] == 1
            assert len(out["days_series"]) == 1
            assert out["start_date"] == out["end_date"]

    # ── batch-78 item 1: scan_runs splits the old "no output" bucket ──────
    def _insert_scan(self, when: str, *, reached: int = 0) -> None:
        tracker.log_scan_run(
            when,
            finished_at=when,
            markets_fetched=590,
            markets_scanned=590,
            reached_analysis=reached,
            scan_completed=True,
            mode="cron",
        )

    def test_a_fully_gated_day_is_now_named_rather_than_left_ambiguous(self):
        """The distinguishing case the whole table exists for. Neither
        `analysis_attempts` nor `predictions` gets a row when every market is
        gated out, so before batch-78 this day and a dead cron job were the
        same observation. A scan_runs row separates them.
        """
        now = datetime.now(UTC)
        self._insert_scan(now.isoformat())

        out = tracker.get_scan_activity(1)
        today = out["days_series"][-1]

        assert today["state"] == "scanned, nothing survived"
        assert today["scans"] == 1
        assert today["reached_analysis"] == 0
        assert today["signals"] == 0
        assert out["scanned_no_survivors_days"] == 1
        assert out["no_output_days"] == 0
        assert out["no_scan_days"] == 0
        assert out["total_scans"] == 1

    def test_a_missing_day_inside_the_covered_era_reads_as_a_real_outage(self):
        """A silent day BETWEEN two scanned days is a genuine outage.

        The gap day must not be today: cron writes the row when a cycle ENDS
        and the first of four lands at 02:15 UTC, so today is legitimately
        empty for the first couple of hours of every healthy day (see
        test_today_is_never_called_an_outage). The outage verdict therefore
        only applies to days that are already over.
        """
        now = datetime.now(UTC)
        self._insert_scan((now - timedelta(days=2)).isoformat())
        self._insert_scan(now.isoformat())

        out = tracker.get_scan_activity(3)
        two_ago, one_ago, today = out["days_series"]

        assert two_ago["state"] == "scanned, nothing survived"
        assert one_ago["state"] == "no scan"
        assert today["state"] == "scanned, nothing survived"
        assert out["no_scan_days"] == 1
        # Positive control: the outage verdict is the ABSENCE of a row for
        # that day, so prove the day is inside the window and inside the
        # covered era -- otherwise this would also pass if the day had simply
        # fallen out of the series.
        assert out["scan_coverage_from"] == two_ago["date"]
        assert one_ago["date"] > out["scan_coverage_from"]
        assert one_ago["date"] < out["end_date"]

    def test_today_is_never_called_an_outage(self):
        """Opus review (reviewer A #1), and a real bug an earlier version of
        this very test class enshrined.

        cron writes the scan_runs row when a cycle ENDS, and the four cycles
        land at 02:15/08:15/14:15/20:15 UTC. Between 00:00 and ~02:20 UTC
        today has no row on a perfectly healthy day. Labelling that "no scan"
        would fire a false outage alarm every single night -- the same
        inversion the coverage floor prevents at the other end of the window.
        """
        now = datetime.now(UTC)
        self._insert_scan((now - timedelta(days=1)).isoformat())

        out = tracker.get_scan_activity(2)
        yesterday, today = out["days_series"]

        assert today["date"] == out["end_date"]
        assert today["state"] == "today, no scan yet"
        assert out["today_no_scan_yet_days"] == 1
        assert out["no_scan_days"] == 0, "today's verdict is not settled yet"
        # Positive control: today IS inside the covered era, so the label is
        # the today-exemption doing its job and not the coverage floor
        # already excusing the day for a different reason.
        assert out["scan_coverage_from"] == yesterday["date"]
        assert today["date"] > out["scan_coverage_from"]

    def test_today_stays_no_output_before_coverage_begins(self):
        """The today-exemption must not fire outside the covered era. With
        scan_runs empty there is nothing to be "not yet" about, and the
        honest label is still the pre-batch-78 one.
        """
        out = tracker.get_scan_activity(3)

        assert {d["state"] for d in out["days_series"]} == {"no output"}
        assert out["today_no_scan_yet_days"] == 0
        assert out["no_output_days"] == 3
        assert out["scan_coverage_from"] is None

    def test_a_future_dated_row_never_becomes_the_reported_coverage_start(self):
        """Opus review (reviewer A #2), narrowed to what the bound actually
        does. A clock-skewed or hand-inserted future row must not be reported
        as `scan_coverage_from` -- a caller rendering "scan recording began
        <date>" would print a date that has not happened.

        Asserted on the RETURNED VALUE, not on day states, and deliberately
        so: a future floor leaves every window day uncovered, which is the
        same state outcome as no floor at all, so a state-only assertion here
        would pass with the bound removed. An earlier version of this test
        made exactly that mistake -- it seeded a future row AND a present one,
        so MIN() picked the present one regardless and the bound was never
        exercised.
        """
        now = datetime.now(UTC)
        self._insert_scan((now + timedelta(days=400)).isoformat())

        out = tracker.get_scan_activity(5)

        assert out["scan_coverage_from"] is None
        # Positive control: the row really was written, so the None above is
        # the bound excluding it rather than an insert that silently failed.
        with tracker._conn() as con:
            assert con.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0] == 1
        # And with the row inside the window instead, the floor IS set --
        # proving the bound is date-sensitive and not a blanket None.
        self._insert_scan(now.isoformat())
        out2 = tracker.get_scan_activity(5)
        assert out2["scan_coverage_from"] == out2["end_date"]

    def test_a_back_dated_row_is_a_documented_limitation_not_a_guard(self):
        """The other half of reviewer A #2, pinned as accepted behaviour so a
        future reader does not mistake the `<= today` bound for protection
        against it. A row back-dated inside the plausible range IS taken as
        real coverage, and every silent day after it reads as an outage.
        There is no cheap bound that separates that from genuine coverage;
        the mitigation is that cron is the only writer and log_scan_run
        rejects a non-ISO stamp.
        """
        now = datetime.now(UTC)
        self._insert_scan((now - timedelta(days=4)).isoformat())

        out = tracker.get_scan_activity(5)

        assert out["scan_coverage_from"] == out["days_series"][0]["date"]
        # Days 2-4 of the window are outages; today is exempt as always.
        assert out["no_scan_days"] == 3
        assert out["today_no_scan_yet_days"] == 1
        assert out["no_output_days"] == 0

    def test_days_before_the_first_scan_row_are_never_called_an_outage(self):
        """The coverage floor. `scan_runs` is forward-only and starts empty,
        so every day before its first row has no scan record for a reason
        that says nothing about whether a scan ran. Labelling those "no scan"
        would manufacture an outage history that never happened -- strictly
        worse than the ambiguity it replaced.
        """
        now = datetime.now(UTC)
        self._insert_scan(now.isoformat())

        out = tracker.get_scan_activity(5)
        series = out["days_series"]

        assert series[-1]["state"] == "scanned, nothing survived"
        # The four days before the table's first row keep the honest label.
        assert [d["state"] for d in series[:-1]] == ["no output"] * 4
        assert out["no_output_days"] == 4
        assert out["no_scan_days"] == 0
        assert out["scan_coverage_from"] == series[-1]["date"]

    def test_the_floor_is_read_from_the_whole_table_not_just_the_window(self):
        """A window that begins AFTER the first scan row must still treat its
        own days as covered. Scoping the MIN() to the window would make
        coverage_from equal the window's own first scan day, re-arming the
        false-outage bug for every earlier-but-covered day in a short window.
        """
        now = datetime.now(UTC)
        self._insert_scan((now - timedelta(days=20)).isoformat())
        self._insert_scan(now.isoformat())

        out = tracker.get_scan_activity(3)
        series = out["days_series"]

        # The 20-day-old row is outside this 3-day window entirely...
        assert out["total_scans"] == 1
        # ...but it still sets the floor, so the two silent days inside the
        # window are diagnosable outages rather than unknowns.
        assert out["scan_coverage_from"] < series[0]["date"]
        assert [d["state"] for d in series[:-1]] == ["no scan"] * 2
        assert out["no_scan_days"] == 2
        assert out["no_output_days"] == 0

    def test_a_scan_that_reached_analysis_still_reads_as_an_analysis_day(self):
        """scan_runs must not outrank the stronger evidence. A day with
        analysis_attempts rows keeps its existing label; the scan count is
        additive information, not a replacement verdict.
        """
        now = datetime.now(UTC)
        when = now.strftime("%Y-%m-%d %H:%M:%S")
        self._insert_attempt("A1", when)
        self._insert_scan(now.isoformat(), reached=1)

        out = tracker.get_scan_activity(1)
        today = out["days_series"][-1]

        assert today["state"] == "analysed, no signals"
        assert today["scans"] == 1
        assert out["scanned_no_survivors_days"] == 0
        assert out["analysed_no_signal_days"] == 1

    def test_the_four_day_states_partition_the_window(self):
        """No day may be counted twice or dropped: the four state counters
        must sum to the window length for any mix of inputs.
        """
        now = datetime.now(UTC)
        self._insert_scan((now - timedelta(days=3)).isoformat())  # gated day
        self._insert_scan(now.isoformat(), reached=1)
        self._insert_attempt("A1", now.strftime("%Y-%m-%d %H:%M:%S"))
        self._insert_prediction(
            "P1",
            (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        )

        out = tracker.get_scan_activity(6)

        total = (
            out["signal_days"]
            + out["analysed_no_signal_days"]
            + out["scanned_no_survivors_days"]
            + out["cron_ran_no_scan_days"]
            + out["today_no_scan_yet_days"]
            + out["no_scan_days"]
            + out["no_output_days"]
        )
        assert total == out["days"] == 6
        # Every label the state chain can emit must have a counter above, or
        # this sum silently stops being a partition the moment a new state is
        # added. Derived from the series rather than hardcoded.
        assert len({d["state"] for d in out["days_series"]}) >= 3
        # Positive control: the mix really is mixed, so the sum above is a
        # partition and not four zeros plus one full bucket.
        assert out["signal_days"] == 1
        assert out["analysed_no_signal_days"] == 1
        assert out["scanned_no_survivors_days"] == 1


class TestScannerFunnelEndpoint:
    @pytest.fixture
    def client(self, monkeypatch):
        import utils
        from web_app import _build_app

        monkeypatch.setattr(utils, "DASHBOARD_PASSWORD", "")
        with patch("main.KALSHI_ENV", "demo"):
            app = _build_app(object())
            app.config["TESTING"] = True
            with app.test_client() as c:
                yield c

    def test_pipeline_lists_every_gate_even_with_no_scan_on_disk(self, client):
        """A funnel needs the gates that did NOT fire as much as the ones that
        did -- otherwise the chart has no denominator.
        """
        resp = client.get("/api/scanner-funnel")

        assert resp.status_code == 200
        body = resp.get_json()
        assert [g["name"] for g in body["pipeline"]] == [g.name for g in wm.SCAN_GATES]
        assert all(g["count"] == 0 for g in body["pipeline"])
        assert body["last_gate"] is None
        assert body["near_misses"] == []
        assert body["scan_started_at"] is None

    def test_counts_from_the_snapshot_land_on_the_declared_pipeline(
        self, client, tmp_path, monkeypatch
    ):
        import web_app

        target = tmp_path / "scan_funnel.json"
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)
        monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", target)
        wm.reset_gate_counts()
        for _ in range(3):
            wm._count_gate("past_date")
        wm._count_gate("spread", ticker="KX-A", value=0.4, threshold=0.3)
        wm.snapshot_scan_funnel()

        body = client.get("/api/scanner-funnel").get_json()
        by_name = {g["name"]: g for g in body["pipeline"]}

        assert by_name["past_date"]["count"] == 3
        assert by_name["spread"]["count"] == 1
        assert by_name["no_city"]["count"] == 0
        assert body["last_gate"]["name"] == "spread"
        assert body["total_rejected"] == 4
        assert body["near_misses"][0]["ticker"] == "KX-A"
        assert body["near_miss_limit"] == wm.SCAN_NEAR_MISS_LIMIT

    def test_a_corrupt_snapshot_degrades_to_no_scan_rather_than_500(
        self, client, tmp_path, monkeypatch
    ):
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text("[not, a, dict", encoding="utf-8")
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        resp = client.get("/api/scanner-funnel")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["total_rejected"] == 0
        # Positive control: the static half of the payload is still complete.
        assert len(body["pipeline"]) == len(wm.SCAN_GATES)

    def test_a_json_array_snapshot_degrades_to_no_scan(
        self, client, tmp_path, monkeypatch
    ):
        """Valid JSON of the wrong shape must not reach .get() on a list."""
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        resp = client.get("/api/scanner-funnel")

        assert resp.status_code == 200
        assert resp.get_json()["total_rejected"] == 0

    def test_a_snapshot_holding_a_bare_json_constant_degrades_to_no_scan(
        self, client, tmp_path, monkeypatch
    ):
        """Python's json module ACCEPTS bare Infinity/NaN by default; jsonify
        would then re-emit them, and JSON.parse rejects them -- one
        hand-edited value would kill the whole panel rather than one cell.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text(
            '{"total_rejected": 3, "near_misses": [{"miss_frac": Infinity}]}',
            encoding="utf-8",
        )
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        resp = client.get("/api/scanner-funnel")

        assert resp.status_code == 200
        assert resp.get_json()["total_rejected"] == 0
        # Positive control: the identical file WITHOUT the bare constant is
        # read through, so the rejection above is the guard's doing and not a
        # path that never reads the file at all.
        target.write_text(
            '{"total_rejected": 3, "near_misses": [{"miss_frac": 0.5}]}',
            encoding="utf-8",
        )
        assert client.get("/api/scanner-funnel").get_json()["total_rejected"] == 3

    def test_sources_never_consume_a_half_open_recovery_probe(self, client):
        """is_open() is a mutator that spends the breaker's one HALF-OPEN
        probe. A dashboard poll must never spend a probe the fetch path needs,
        so the endpoint reads seconds_open() instead.
        """
        calls = []
        breaker = wm.CIRCUIT_BREAKERS[0].breaker
        original = type(breaker).is_open

        def _tripwire(self):
            calls.append(self.name)
            return original(self)

        with patch.object(type(breaker), "is_open", _tripwire):
            body = client.get("/api/scanner-funnel").get_json()

        assert calls == []
        # Positive control: the endpoint really did report on every breaker, so
        # the empty call list is not an unreached code path.
        assert set(body["sources"]) == {r.name for r in wm.CIRCUIT_BREAKERS}
        assert all(set(v) == {"state", "open_for_s"} for v in body["sources"].values())

    def test_activity_block_is_the_thirty_day_baseline(self, client):
        body = client.get("/api/scanner-funnel").get_json()

        assert body["activity"]["days"] == 30
        assert len(body["activity"]["days_series"]) == 30

    def test_the_payload_carries_no_bare_json_constants(
        self, client, tmp_path, monkeypatch
    ):
        """A real snapshot with real numeric near-misses is written first: run
        against an ABSENT snapshot this asserts nothing, because near_misses is
        [] and the payload has no numeric content to sanitise.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)
        monkeypatch.setattr(wm, "SCAN_FUNNEL_PATH", target)
        wm.reset_gate_counts()
        wm._count_gate("spread", ticker="KX-A", value=0.4, threshold=0.3)
        wm._count_gate("min_volume", ticker="KX-B", value=90, threshold=100)
        wm.snapshot_scan_funnel()

        resp = client.get("/api/scanner-funnel")
        body = resp.get_json()

        # Positive control on the premise: there IS numeric content to poison.
        assert len(body["near_misses"]) == 2
        assert all(isinstance(m["miss_frac"], float) for m in body["near_misses"])

        def _reject(name):
            raise AssertionError(f"payload contained bare JSON constant {name!r}")

        json.loads(resp.get_data(as_text=True), parse_constant=_reject)
        # ...and the same parser DOES reject a poisoned document.
        with pytest.raises(AssertionError):
            json.loads('{"x": Infinity}', parse_constant=_reject)

    def test_a_wrong_typed_count_degrades_instead_of_500ing(
        self, client, tmp_path, monkeypatch
    ):
        """The isinstance(dict) guard only covers the TOP level. A hand-edited
        or older-schema snapshot with a string count, or a `gates` that is not
        a list, must not take the whole panel down.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        for payload in (
            '{"gates": [{"name": "spread", "count": "three"}]}',
            '{"gates": 7}',
            '{"gates": [{"name": "spread", "count": 2}], "total_rejected": "many"}',
            '{"unknown_gates": ["not", "a", "dict"], "near_misses": "nope"}',
            '{"last_gate": "not a dict"}',
            # An UNHASHABLE name raises TypeError from the dict comprehension
            # itself, before any value guard can run.
            '{"gates": [{"name": [], "count": 1}]}',
            '{"gates": [{"name": {"a": 1}, "count": 1}]}',
            # int(float("inf")) raises OverflowError, which is neither
            # TypeError nor ValueError.
            '{"total_rejected": 1e400}',
            '{"gates": [{"name": "spread", "count": 1e400}]}',
        ):
            target.write_text(payload, encoding="utf-8")
            resp = client.get("/api/scanner-funnel")
            assert resp.status_code == 200, payload
            body = resp.get_json()
            # The static half of the response survives every one of them.
            assert len(body["pipeline"]) == len(wm.SCAN_GATES), payload
            assert isinstance(body["total_rejected"], int), payload
            assert isinstance(body["near_misses"], list), payload
            assert isinstance(body["unknown_gates"], dict), payload

        # Positive control: a well-formed snapshot of the same shape IS read
        # through, so the survivals above are the guards' doing.
        target.write_text(
            '{"gates": [{"name": "spread", "count": 2}], "total_rejected": 2}',
            encoding="utf-8",
        )
        body = client.get("/api/scanner-funnel").get_json()
        assert body["total_rejected"] == 2
        assert next(g for g in body["pipeline"] if g["name"] == "spread")["count"] == 2

    def test_an_ordinary_json_number_cannot_smuggle_infinity_into_the_payload(
        self, client, tmp_path, monkeypatch
    ):
        """parse_constant only intercepts the bare TOKENS Infinity/NaN. `1e400`
        is a syntactically ordinary JSON number that json.load parses to
        float("inf") without ever consulting it, so guarding only the read was
        one-legged -- jsonify would then re-emit a bare `Infinity`, which
        JSON.parse rejects, killing the whole panel.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text(
            '{"total_rejected": 2, "near_misses":'
            ' [{"gate": "spread", "ticker": "KX-A", "miss_frac": 1e400},'
            '  {"gate": "spread", "ticker": "KX-B", "miss_frac": 0.5}]}',
            encoding="utf-8",
        )
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        resp = client.get("/api/scanner-funnel")
        raw = resp.get_data(as_text=True)

        assert resp.status_code == 200
        # Positive control on the premise: Python really does parse 1e400 to
        # infinity, so this file genuinely carried one.
        assert json.loads('{"x": 1e400}')["x"] == float("inf")
        # The bare constant must not survive into the wire format...
        assert "Infinity" not in raw
        assert "NaN" not in raw

        def _reject(name):
            raise AssertionError(f"bare JSON constant {name!r} in payload")

        json.loads(raw, parse_constant=_reject)
        # ...and the clean sibling entry is still served, so sanitisation
        # nulled one value rather than dropping the whole block.
        body = resp.get_json()
        assert [m["ticker"] for m in body["near_misses"]] == ["KX-A", "KX-B"]
        assert body["near_misses"][0]["miss_frac"] is None
        assert body["near_misses"][1]["miss_frac"] == 0.5

    def test_a_gate_renamed_since_the_scan_still_appears(
        self, client, tmp_path, monkeypatch
    ):
        """A gate known at WRITE time but renamed since is in snapshot["gates"],
        is NOT in snapshot["unknown_gates"], and is not in the live SCAN_GATES.
        Without reconciliation it vanishes from `pipeline` while still counting
        toward `total_rejected`, and the two disagree on screen with nothing to
        explain the gap.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text(
            '{"gates": [{"name": "spread", "count": 2},'
            ' {"name": "gate_from_a_past_life", "count": 3}],'
            ' "total_rejected": 5}',
            encoding="utf-8",
        )
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        body = client.get("/api/scanner-funnel").get_json()

        assert body["unknown_gates"] == {"gate_from_a_past_life": 3}
        # Positive control: the still-live gate landed on the pipeline as
        # normal, so the retired one is not simply being swept into the same
        # bucket as everything else.
        assert next(g for g in body["pipeline"] if g["name"] == "spread")["count"] == 2
        # Everything now reconciles: pipeline + unknown == total_rejected.
        assert (
            sum(g["count"] for g in body["pipeline"])
            + sum(body["unknown_gates"].values())
            == body["total_rejected"]
        )

    def test_a_gate_is_never_listed_in_both_pipeline_and_unknown_gates(
        self, client, tmp_path, monkeypatch
    ):
        """A gate emitted by _count_gate before its ScanGate entry existed
        lands in the snapshot's own unknown_gates. Once the entry is added the
        gate is on the live pipeline too, and listing it in both places
        double-counts it against total_rejected -- breaking the reconciliation
        invariant the renamed-gate test asserts.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text(
            '{"gates": [{"name": "spread", "count": 2}],'
            ' "unknown_gates": {"spread": 4, "gone_for_good": "3"},'
            ' "total_rejected": 5}',
            encoding="utf-8",
        )
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        body = client.get("/api/scanner-funnel").get_json()

        # `spread` is known now, so it belongs on the pipeline and nowhere else
        assert next(g for g in body["pipeline"] if g["name"] == "spread")["count"] == 2
        assert "spread" not in body["unknown_gates"]
        # ...and a genuinely unknown name is kept, with its value coerced like
        # every other count rather than forwarded as the raw string.
        assert body["unknown_gates"] == {"gone_for_good": 3}

    def test_staleness_is_computed_server_side(self, client, tmp_path, monkeypatch):
        """If cron dies the panel would otherwise serve a week-old funnel that
        looks exactly like a fresh one, and a frontend cannot compute the age
        safely from the timestamp alone.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        fresh = datetime.now(UTC).isoformat()
        target.write_text(json.dumps({"snapshot_at": fresh}), encoding="utf-8")
        body = client.get("/api/scanner-funnel").get_json()
        assert body["stale"] is False
        assert body["snapshot_age_secs"] < 5

        old = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        target.write_text(json.dumps({"snapshot_at": old}), encoding="utf-8")
        body = client.get("/api/scanner-funnel").get_json()
        assert body["stale"] is True
        assert body["snapshot_age_secs"] > body["stale_after_secs"]

        # An unparseable or missing timestamp must report "unknown", never a
        # confident False that would read as fresh.
        target.write_text('{"snapshot_at": "not a date"}', encoding="utf-8")
        body = client.get("/api/scanner-funnel").get_json()
        assert body["stale"] is None
        assert body["snapshot_age_secs"] is None

    def test_last_gate_position_is_re_derived_from_the_live_gate_list(
        self, client, tmp_path, monkeypatch
    ):
        """The snapshot's last_gate.order was computed against whatever
        SCAN_GATES looked like at WRITE time. Insert one gate mid-pipeline and
        every older snapshot's order is off by one, so a frontend matching it
        against pipeline[].order highlights the wrong bar.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text(
            '{"last_gate": {"name": "spread", "label": "stale label",'
            ' "stage": "stale stage", "order": 999}}',
            encoding="utf-8",
        )
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        body = client.get("/api/scanner-funnel").get_json()
        live = next(g for g in body["pipeline"] if g["name"] == "spread")

        assert body["last_gate"]["order"] == live["order"] != 999
        assert body["last_gate"]["label"] == live["label"] != "stale label"
        assert body["last_gate"]["stage"] == live["stage"]
        assert body["last_gate"]["retired"] is False

        # A name that no longer exists keeps its identity but is flagged,
        # rather than silently pointing at whichever gate now sits at its old
        # index.
        target.write_text(
            '{"last_gate": {"name": "gate_from_a_past_life", "order": 3}}',
            encoding="utf-8",
        )
        body = client.get("/api/scanner-funnel").get_json()
        assert body["last_gate"]["name"] == "gate_from_a_past_life"
        assert body["last_gate"]["retired"] is True
        assert body["last_gate"]["order"] is None

    def test_a_pre_batch65_snapshot_does_not_claim_completeness(
        self, client, tmp_path, monkeypatch
    ):
        """`complete` is absent from any snapshot written before it existed.
        Defaulting it to True would assert completeness for a file that never
        made the claim -- the exact failure the field exists to prevent.
        """
        import web_app

        target = tmp_path / "scan_funnel.json"
        target.write_text('{"total_rejected": 4}', encoding="utf-8")
        monkeypatch.setattr(web_app, "SCAN_FUNNEL_PATH", target)

        assert client.get("/api/scanner-funnel").get_json()["complete"] is None

        # Positive control: a snapshot that DOES make the claim is forwarded.
        target.write_text('{"total_rejected": 4, "complete": false}', encoding="utf-8")
        assert client.get("/api/scanner-funnel").get_json()["complete"] is False

    def test_a_failing_activity_query_returns_500_not_a_partial_payload(self, client):
        """Sibling endpoints in this file return 500 for a total failure; a 200
        with half a payload would pass a response.ok check in the frontend.
        """
        with patch("tracker.get_scan_activity", side_effect=RuntimeError("boom")):
            resp = client.get("/api/scanner-funnel")

        assert resp.status_code == 500
        assert "boom" in resp.get_json()["error"]
