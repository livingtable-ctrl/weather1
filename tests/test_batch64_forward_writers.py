"""Batch-64: the four forward-only data writers.

Every item here is a WRITE-ONLY observation added alongside existing
behaviour — nothing in this batch may change a trading decision. Several of
these tests exist specifically to prove that, not just to prove the new data
lands: test_forecast_cycle_is_not_touched_by_the_new_field and
test_get_cached_book_shape_is_unchanged are regression guards on live paths
(order dedup / LivePositionStore, and reprice-chase respectively), not
coverage of new code.

The data these writers collect cannot be backfilled, which is why the batch
runs first; the tests correspondingly care a lot about a writer silently
no-opping (see the dedup and positive-control tests below).
"""

import json
import queue
import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

import kalshi_ws
import tracker
import weather_markets as wm

# ══════════════════════════════════════════════════════════════════════════
# Item 1 — the real model-run initialisation time
# ══════════════════════════════════════════════════════════════════════════


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_run_init_cache():
    """get_model_run_init memoises per dataset; a leaked entry would make a
    later test read the previous test's mock (or a real network result)."""
    wm._model_run_init_cache.clear()
    yield
    wm._model_run_init_cache.clear()


def test_run_init_is_the_products_timestamp_not_the_wall_clock():
    """The whole point of item 1: the recorded value must come from the
    fetched product, not from `now`.

    order_executor._current_forecast_cycle() computes
    `12 if now.hour >= 12 else 0`, so at 13:00 UTC it says "12z". This mock's
    run initialisation time is deliberately the PREVIOUS DAY's 18z — a value
    the wall clock can never produce at 13:00 — so a naive implementation
    that quietly fell back to a clock-derived cycle cannot pass this test.
    That disagreement is real and not hypothetical: verified live 2026-08-25,
    ecmwf_aifs025_ensemble was on the previous day's 18z run while two other
    blend models were on 00z.
    """
    product_run = datetime(2026, 8, 24, 18, 0, tzinfo=UTC)
    wall_clock = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    assert product_run.strftime("%H") != wall_clock.strftime("%H"), (
        "the fixture is only meaningful while the two disagree"
    )

    with patch.object(
        wm,
        "_om_request",
        return_value=_FakeResp(
            {"last_run_initialisation_time": int(product_run.timestamp())}
        ),
    ):
        got = wm.get_model_run_init("ecmwf_aifs025_ensemble")

    assert got == product_run.isoformat()
    # And explicitly NOT the wall-clock answer for the same moment.
    assert not got.startswith(wall_clock.date().isoformat()), (
        "run init must not be derived from the current date"
    )
    assert "T18:00" in got


def test_run_init_is_cached_and_not_refetched_within_the_ttl():
    calls = []

    def _fake(method, url, **kw):
        calls.append(url)
        return _FakeResp({"last_run_initialisation_time": 1787594400})

    with patch.object(wm, "_om_request", side_effect=_fake):
        first = wm.get_model_run_init("icon_seamless")
        second = wm.get_model_run_init("icon_seamless")

    assert first == second
    assert len(calls) == 1, f"expected one request, got {calls}"
    # Positive control: the one request that DID happen went to the mapped
    # dataset, not to the bot's alias (which 500s on that endpoint).
    assert "dwd_icon_eps" in calls[0]
    assert "icon_seamless" not in calls[0]


def test_run_init_failure_is_negatively_cached_and_returns_none():
    """A failing endpoint must not be retried on every market in a scan, and
    must never be papered over with a wall-clock guess."""
    calls = []

    def _boom(method, url, **kw):
        calls.append(url)
        raise RuntimeError("endpoint down")

    with patch.object(wm, "_om_request", side_effect=_boom):
        assert wm.get_model_run_init("gfs_seamless") is None
        assert wm.get_model_run_init("gfs_seamless") is None

    assert len(calls) == 1, "a known failure must be cached, not re-requested"


def test_unmapped_model_returns_none_without_any_request():
    """ukmo_global_ensemble_20km has no meta.json dataset; None is the honest
    answer and must cost no network call.

    Recording stub, not a raise-only stub — see
    test_observed_run_inits_never_touch_the_network for why the raise alone
    proves nothing here (get_model_run_init swallows every Exception).
    """
    calls = []

    def _record(method, url, **kw):
        calls.append(url)
        raise RuntimeError(f"blocked: {url}")

    with patch.object(wm, "_om_request", side_effect=_record):
        assert wm.get_model_run_init("ukmo_global_ensemble_20km") is None
        assert wm.get_model_run_init("not_a_model_at_all") is None

    assert calls == [], f"an unmapped model must cost no request: {calls}"

    # Positive control: a MAPPED model does reach the stub, proving the empty
    # list above is the mapping guard and not a stub that was never wired in.
    with patch.object(wm, "_om_request", side_effect=_record):
        wm.get_model_run_init("icon_seamless")
    assert len(calls) == 1 and "dwd_icon_eps" in calls[0], calls


@pytest.mark.parametrize("bad", [True, False, None, "not-a-number", {}, []])
def test_malformed_run_init_payload_yields_none(bad):
    """A bool is an int subclass — True would otherwise become
    1970-01-01T00:00:01 and read as a real (absurdly old) run."""
    with patch.object(
        wm, "_om_request", return_value=_FakeResp({"last_run_initialisation_time": bad})
    ):
        assert wm.get_model_run_init("nbm") is None


def test_observed_run_inits_never_touch_the_network():
    """The property this function exists for.

    analyze_trade() runs per market across a thread pool, and this repo has
    already been bitten by network calls hiding inside it — see
    test_weather_markets.py's
    test_analyze_trade_makes_no_real_nws_mos_or_climate_indices_calls. Item 1
    must not add a fourth.

    The stub RECORDS and then raises; the assertion is on the recording, not
    on the return value. An opus review mutation-proved the first draft of
    this test vacuous: it asserted only `== {}` against a raise-only stub,
    but get_model_run_init wraps its request in `except Exception` — which
    catches AssertionError — so a mutant that called the network per model
    still returned {} and still passed. This is the identical trap
    test_weather_markets.py:1801-1806 already documents ("A raise-on-call-only
    stub falsely passed even with a mock removed... Recording is what
    survives that resilience").
    """
    calls = []

    def _record(method, url, **kw):
        calls.append(url)
        raise RuntimeError(f"blocked: {url}")

    with patch.object(wm, "_om_request", side_effect=_record):
        out = wm.observed_model_run_inits(["icon_seamless", "gfs_seamless"])

    assert calls == [], f"observed_model_run_inits reached the network: {calls}"
    assert out == {}


def test_observed_run_inits_read_what_the_fetch_saw():
    with patch.object(wm, "_model_run_init_observed", {"icon_seamless": "OBSERVED"}):
        with patch.object(wm, "_om_request", side_effect=AssertionError("network!")):
            out = wm.observed_model_run_inits(
                ["icon_seamless", "gfs_seamless", "ukmo_global_ensemble_20km"]
            )
    assert out == {"icon_seamless": "OBSERVED"}, out


def test_observed_run_inits_fall_back_to_an_unexpired_cache_entry():
    """Second memory-only source: a value already fetched this process."""
    with patch.object(
        wm,
        "_om_request",
        return_value=_FakeResp({"last_run_initialisation_time": 1787594400}),
    ):
        wm.get_model_run_init("icon_seamless")  # warms the cache

    with patch.object(wm, "_om_request", side_effect=AssertionError("network!")):
        out = wm.observed_model_run_inits(["icon_seamless", "gfs_seamless"])

    assert list(out) == ["icon_seamless"], out
    assert out["icon_seamless"].startswith("2026-")


def test_persist_member_values_records_the_observed_run_init():
    """The bridge between the two: the fetch path is what populates the store
    that the (network-free) analyze_trade path later reads."""
    with patch.object(wm, "_model_run_init_observed", {}) as store:
        with patch.object(tracker, "log_ensemble_members", return_value=True):
            with patch.object(wm, "get_model_run_init", return_value="RUN-X"):
                wm._persist_member_values(
                    "NYC", "icon_seamless", "2026-08-26", "max", [70.0]
                )
        assert store == {"icon_seamless": "RUN-X"}

    # Negative control: an unresolvable run init records nothing rather than
    # storing a None that would later read as an observation.
    with patch.object(wm, "_model_run_init_observed", {}) as store:
        with patch.object(tracker, "log_ensemble_members", return_value=True):
            with patch.object(wm, "get_model_run_init", return_value=None):
                wm._persist_member_values(
                    "NYC", "icon_seamless", "2026-08-26", "max", [70.0]
                )
        assert store == {}


def test_forecast_cycle_is_not_touched_by_the_new_field():
    """Regression guard on a LIVE path, not coverage of new code.

    order_executor._current_forecast_cycle() is the dedup key for live order
    placement (_poll_pending_orders) and the LivePositionStore key. Item 1
    adds a field beside it and must not repurpose or replace it.
    """
    import order_executor

    fixed = datetime(2026, 8, 25, 13, 5, tzinfo=UTC)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC, f"expected UTC, got {tz!r}"
            return fixed

    with patch.object(order_executor, "datetime", _FixedDatetime):
        assert order_executor._current_forecast_cycle() == "2026-08-25_12z"

    tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B70",
        city="NYC",
        market_date=None,
        analysis={
            "condition": {"type": "above", "threshold": 70, "var": "max"},
            "forecast_prob": 0.6,
            "market_prob": 0.5,
            "edge": 0.1,
        },
        forecast_cycle="2026-08-25_12z",
        forecast_run_inits={"ecmwf_aifs025_ensemble": "2026-08-24T18:00:00+00:00"},
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        cycle, inits = con.execute(
            "SELECT forecast_cycle, forecast_run_inits FROM predictions"
        ).fetchone()

    assert cycle == "2026-08-25_12z", "forecast_cycle must survive verbatim"
    assert json.loads(inits) == {"ecmwf_aifs025_ensemble": "2026-08-24T18:00:00+00:00"}
    assert cycle != inits, "the two fields carry genuinely different facts"


# ══════════════════════════════════════════════════════════════════════════
# Item 2 — per-member ensemble values
# ══════════════════════════════════════════════════════════════════════════


def _emv_rows():
    with sqlite3.connect(tracker.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM ensemble_member_values")]


def test_member_values_round_trip_with_run_init():
    members = [70.1, 71.25, 69.8, 72.0]
    assert tracker.log_ensemble_members(
        city="NYC",
        model="icon_seamless",
        target_date_str="2026-08-26",
        members=members,
        var="max",
        cycle="2026-08-25_06z",
        run_init="2026-08-25T06:00:00+00:00",
    )

    (row,) = _emv_rows()
    assert json.loads(row["values_json"]) == members
    assert row["n_members"] == 4
    assert row["run_init"] == "2026-08-25T06:00:00+00:00"
    assert row["cycle"] == "2026-08-25_06z"
    assert row["var"] == "max"


def test_member_values_dedup_keeps_the_first_write_of_a_cycle():
    """The ensemble cache is cycle-aligned and cron runs one-shot, so the
    same forecast is re-presented across scans. The row that survives must be
    the first — its run_init was the one actually observed at fetch time."""
    key = dict(
        city="NYC",
        model="gfs_seamless",
        target_date_str="2026-08-26",
        var="max",
        cycle="2026-08-25_06z",
    )
    assert tracker.log_ensemble_members(members=[1.0, 2.0], run_init="A", **key) is True
    assert tracker.log_ensemble_members(members=[9.9], run_init="B", **key) is False

    (row,) = _emv_rows()
    assert json.loads(row["values_json"]) == [1.0, 2.0]
    assert row["run_init"] == "A"


def test_member_values_differ_by_cycle_and_by_model():
    """Positive control for the dedup test above: the unique index must be
    narrow enough that a genuinely different forecast still gets its own row,
    otherwise 'dedup works' would be indistinguishable from 'the writer
    silently drops almost everything'."""
    base = dict(city="NYC", target_date_str="2026-08-26", var="max", members=[1.0])
    assert tracker.log_ensemble_members(model="icon_seamless", cycle="c1", **base)
    assert tracker.log_ensemble_members(model="icon_seamless", cycle="c2", **base)
    assert tracker.log_ensemble_members(model="gfs_seamless", cycle="c1", **base)
    assert tracker.log_ensemble_members(
        city="BOS",
        model="icon_seamless",
        cycle="c1",
        target_date_str="2026-08-26",
        var="max",
        members=[1.0],
    )
    assert len(_emv_rows()) == 4


def test_empty_member_list_writes_nothing():
    assert (
        tracker.log_ensemble_members("NYC", "icon_seamless", "2026-08-26", []) is False
    )
    assert _emv_rows() == []


def test_member_writer_never_raises_into_the_fetch_path():
    """A forecast fetch must not be able to fail because a log-only writer
    did. Paired with a positive control that the failing call was reached."""
    with patch.object(tracker, "_conn", side_effect=RuntimeError("db gone")):
        assert (
            tracker.log_ensemble_members("NYC", "icon_seamless", "2026-08-26", [1.0])
            is False
        )
    # Positive control: with _conn working again the identical call succeeds,
    # proving the False above came from the induced failure and not from the
    # arguments being rejected before any write was attempted.
    assert tracker.log_ensemble_members("NYC", "icon_seamless", "2026-08-26", [1.0])


def test_persist_member_values_buffers_raw_values_and_flush_writes_them():
    """_persist_member_values must forward the members untouched — no bias
    correction, no weight replication — and must BUFFER rather than write.

    The buffering is not incidental. The per-row writer opens its own SQLite
    connection, measured at ~67 ms on this project's storage, and
    batch_prewarm_ensemble reaches this function of order 300 times per scan.
    Writing per row added ~20 s to every scan and, because a deduped no-op
    costs the same as an insert, it was paid on every subsequent scan too.
    """
    with patch.object(wm, "_member_values_pending", []) as pending:
        with patch.object(wm, "get_model_run_init", return_value="RUN"):
            wm._persist_member_values(
                "NYC", "icon_seamless", "2026-08-26", "max", [70.0, 71.0]
            )
        assert len(pending) == 1
        row = pending[0]
        assert row["members"] == [70.0, 71.0], "raw members, untransformed"
        assert row["run_init"] == "RUN"
        assert row["city"] == "NYC" and row["model"] == "icon_seamless"
        assert row["var"] == "max"

        # The flush is what actually reaches the DB.
        assert wm.flush_member_values() == 1
        assert pending == [], "flush must drain the buffer"

    (stored,) = _emv_rows()
    assert json.loads(stored["values_json"]) == [70.0, 71.0]
    assert stored["run_init"] == "RUN"


def test_persist_member_values_never_raises_into_the_fetch_path():
    with patch.object(wm, "get_model_run_init", side_effect=RuntimeError("boom")):
        wm._persist_member_values("NYC", "icon_seamless", "2026-08-26", "max", [1.0])
    # Positive control: the same call with a working dependency does buffer,
    # so the no-crash above is not just an argument rejection.
    with patch.object(wm, "_member_values_pending", []) as pending:
        with patch.object(wm, "get_model_run_init", return_value=None):
            wm._persist_member_values(
                "NYC", "icon_seamless", "2026-08-26", "max", [1.0]
            )
        assert len(pending) == 1


def test_flush_is_a_noop_when_nothing_is_pending():
    with patch.object(wm, "_member_values_pending", []):
        assert wm.flush_member_values() == 0
    assert _emv_rows() == []


def test_flush_failure_does_not_raise_and_drops_the_batch_cleanly():
    with patch.object(wm, "_member_values_pending", []) as pending:
        with patch.object(wm, "get_model_run_init", return_value="RUN"):
            wm._persist_member_values(
                "NYC", "icon_seamless", "2026-08-26", "max", [1.0]
            )
        with patch.object(
            tracker, "log_ensemble_members_bulk", side_effect=RuntimeError("db gone")
        ):
            assert wm.flush_member_values() == 0
        assert pending == [], "a failed flush must not leave the buffer wedged"


def test_bulk_writer_dedups_and_skips_empty_member_sets():
    rows = [
        {
            "city": "NYC",
            "model": "icon_seamless",
            "target_date_str": "2026-08-26",
            "members": [1.0, 2.0],
            "var": "max",
            "cycle": "c1",
            "run_init": "A",
        },
        # Same natural key — must dedup against the first.
        {
            "city": "NYC",
            "model": "icon_seamless",
            "target_date_str": "2026-08-26",
            "members": [9.9],
            "var": "max",
            "cycle": "c1",
            "run_init": "B",
        },
        # Genuinely different — positive control that dedup isn't eating everything.
        {
            "city": "BOS",
            "model": "icon_seamless",
            "target_date_str": "2026-08-26",
            "members": [3.0],
            "var": "max",
            "cycle": "c1",
            "run_init": "A",
        },
        # Empty member set — skipped.
        {
            "city": "LAX",
            "model": "icon_seamless",
            "target_date_str": "2026-08-26",
            "members": [],
            "var": "max",
            "cycle": "c1",
            "run_init": "A",
        },
    ]
    assert tracker.log_ensemble_members_bulk(rows) == 2
    stored = {(r["city"], json.loads(r["values_json"])[0]) for r in _emv_rows()}
    assert stored == {("NYC", 1.0), ("BOS", 3.0)}, stored
    assert tracker.log_ensemble_members_bulk([]) == 0


@pytest.mark.parametrize(
    "hour,expected",
    [
        (0, "2026-08-24_18z"),
        (1, "2026-08-24_18z"),
        (2, "2026-08-25_00z"),
        (7, "2026-08-25_00z"),
        (8, "2026-08-25_06z"),
        (13, "2026-08-25_06z"),
        (14, "2026-08-25_12z"),
        (19, "2026-08-25_12z"),
        (20, "2026-08-25_18z"),
        (23, "2026-08-25_18z"),
    ],
)
def test_ensemble_cycle_tag_buckets_on_availability_boundaries(hour, expected):
    """Buckets on 02/08/14/20 UTC — the same availability boundaries
    _ttl_until_next_cycle() uses to expire the data these members come from,
    so one member set is stored per model per city per window. Deliberately
    four windows, not the two that a 00z/12z wall-clock split would give."""
    got = wm._ensemble_cycle_tag(datetime(2026, 8, 25, hour, 30, tzinfo=UTC))
    assert got == expected


def test_ensemble_cycle_tag_gives_four_distinct_windows_per_day():
    tags = {
        wm._ensemble_cycle_tag(datetime(2026, 8, 25, h, 0, tzinfo=UTC))
        for h in range(2, 24)
    }
    assert len(tags) == 4, tags


# ══════════════════════════════════════════════════════════════════════════
# Item 3 — blend exclusion reasons
# ══════════════════════════════════════════════════════════════════════════


def test_blend_exclusions_round_trip():
    tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B70",
        city="NYC",
        market_date=None,
        analysis={
            "condition": {"type": "above", "threshold": 70, "var": "max"},
            "forecast_prob": 0.6,
            "market_prob": 0.5,
            "edge": 0.1,
        },
        blend_sources={"ensemble": 0.7, "climatology": 0.3},
        blend_exclusions={"nws": "unavailable", "ensemble_cdf": "zero_weight"},
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        srcs, excl = con.execute(
            "SELECT blend_sources, blend_exclusions FROM predictions"
        ).fetchone()

    assert json.loads(excl) == {"nws": "unavailable", "ensemble_cdf": "zero_weight"}
    # The two are complements: a source cannot be both blended and excluded.
    assert not (set(json.loads(srcs)) & set(json.loads(excl)))


def test_empty_exclusions_stored_as_empty_json_not_null():
    """An empty dict means "nothing was excluded" — a real, informative fact.
    NULL means "this row has no answer", which is what a pre-migration row
    and a caller that never passed the field both look like.

    An earlier draft used truthiness (`if blend_exclusions`) and wrote NULL
    for `{}`, collapsing those three cases together — the exact ambiguity
    this column exists to remove, reintroduced at the row level. Matches
    blend_sources/signal_values, which both use `is not None`.
    """
    _base = {
        "condition": {"type": "above", "threshold": 70, "var": "max"},
        "forecast_prob": 0.6,
        "market_prob": 0.5,
        "edge": 0.1,
    }
    tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B70",
        city="NYC",
        market_date=None,
        analysis=_base,
        blend_exclusions={},
        forecast_run_inits={},
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        excl, inits = con.execute(
            "SELECT blend_exclusions, forecast_run_inits FROM predictions"
        ).fetchone()
    assert excl == "{}", excl
    assert inits == "{}", inits

    # Positive control on the other side: a caller that passes nothing at all
    # still stores NULL, so the two cases stay distinguishable.
    tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B71", city="NYC", market_date=None, analysis=_base
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        (excl2,) = con.execute(
            "SELECT blend_exclusions FROM predictions WHERE ticker=?",
            ("KXHIGHNY-26AUG26-B71",),
        ).fetchone()
    assert excl2 is None


def test_a_later_write_without_the_fields_does_not_wipe_them():
    """These columns are forward-only, so a plain UPSERT overwrite loses data
    permanently. weather_markets' retirement-probation path calls
    log_prediction with no blend kwargs against an existing (ticker, date),
    which NULLed a real trade's run inits — hence COALESCE.
    """
    _base = {
        "condition": {"type": "above", "threshold": 70, "var": "max"},
        "forecast_prob": 0.6,
        "market_prob": 0.5,
        "edge": 0.1,
    }
    tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B70",
        city="NYC",
        market_date=None,
        analysis=_base,
        forecast_run_inits={"icon_seamless": "2026-08-25T00:00:00+00:00"},
        blend_exclusions={"nws": "unavailable"},
    )
    # A probation/shadow-style write: same key, none of the new fields.
    tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B70",
        city="NYC",
        market_date=None,
        analysis=_base,
        is_shadow=True,
        is_probation=True,
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        inits, excl = con.execute(
            "SELECT forecast_run_inits, blend_exclusions FROM predictions"
        ).fetchone()
    assert json.loads(inits) == {"icon_seamless": "2026-08-25T00:00:00+00:00"}
    assert json.loads(excl) == {"nws": "unavailable"}

    # Positive control: a later write that DOES carry a value still wins, so
    # COALESCE has not frozen the column at its first value.
    tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B70",
        city="NYC",
        market_date=None,
        analysis=_base,
        forecast_run_inits={"gfs_seamless": "2026-08-25T06:00:00+00:00"},
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        (inits2,) = con.execute("SELECT forecast_run_inits FROM predictions").fetchone()
    assert json.loads(inits2) == {"gfs_seamless": "2026-08-25T06:00:00+00:00"}


def test_dedup_still_applies_when_var_and_cycle_are_absent():
    """SQLite treats NULLs as DISTINCT in a UNIQUE index, so a NULL var or
    cycle would silently switch idx_emv_dedup off and let duplicates
    accumulate. The writers coerce both key columns to ""."""
    for _ in range(3):
        tracker.log_ensemble_members("NYC", "icon_seamless", "2026-08-26", [1.0, 2.0])
    assert len(_emv_rows()) == 1, "a NULL key part must not defeat the dedup index"
    # Positive control: a genuinely different key still gets its own row.
    tracker.log_ensemble_members("BOS", "icon_seamless", "2026-08-26", [1.0])
    assert len(_emv_rows()) == 2


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — order-book depth
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(kalshi_ws, "_CACHE_PATH", tmp_path / "orderbook_cache.json")
    monkeypatch.setattr(kalshi_ws, "_orderbook", {})
    monkeypatch.setattr(kalshi_ws, "_depth_books", {})
    monkeypatch.setattr(kalshi_ws, "_depth_last_persist", {})
    monkeypatch.setattr(kalshi_ws, "_depth_seq_by_sid", {})
    monkeypatch.setattr(kalshi_ws, "_depth_sid_tickers", {})
    # A fresh queue per test, and no writer thread: these tests assert on
    # what was ENQUEUED, which is deterministic, rather than racing a
    # background drain. test_the_writer_thread_actually_drains_to_the_db
    # below covers the thread itself.
    monkeypatch.setattr(kalshi_ws, "_depth_write_queue", queue.Queue(maxsize=512))
    monkeypatch.setattr(kalshi_ws, "_ensure_depth_writer", lambda: None)
    # Persistence off by default; the tests that want it re-enable it.
    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "0")
    monkeypatch.setenv("KALSHI_ENV", "demo")
    return kalshi_ws


def _now():
    return datetime.now(UTC).isoformat()


def _snapshot(ticker="KXT-A", yes=None, no=None, seq=1, ts=None):
    return {
        "type": "orderbook_snapshot",
        "ticker": ticker,
        "yes_levels": yes if yes is not None else [[0.55, 100], [0.54, 200]],
        "no_levels": no if no is not None else [[0.42, 50]],
        "best_yes_bid": 0.55,
        "best_no_bid": 0.42,
        "seq": seq,
        "ts": ts or _now(),
    }


def _delta(price, delta, side="yes", ticker="KXT-A", seq=2, ts=None):
    return {
        "type": "orderbook_delta",
        "ticker": ticker,
        "seq": seq,
        "ts": ts or _now(),
        "delta": {
            "market_ticker": ticker,
            "price": price,
            "delta": delta,
            "side": side,
        },
    }


def test_parse_message_carries_the_sequence_number(ws):
    parsed = kalshi_ws.parse_message(
        {
            "type": "orderbook_delta",
            "seq": 77,
            "msg": {"market_ticker": "KXT-A", "price": 0.5, "delta": 3, "side": "yes"},
        }
    )
    assert parsed["seq"] == 77
    snap = kalshi_ws.parse_message(
        {
            "type": "orderbook_snapshot",
            "seq": 1,
            "msg": {"market_ticker": "KXT-A", "yes": [["0.55", 10]], "no": []},
        }
    )
    assert snap["seq"] == 1
    # Absent seq must be None, not a crash or a fabricated 0.
    assert (
        kalshi_ws.parse_message(
            {"type": "orderbook_delta", "msg": {"market_ticker": "KXT-A"}}
        )["seq"]
        is None
    )


def test_depth_is_built_from_snapshot_and_sorted_best_first(ws):
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.54, 200], [0.55, 100]]))
    depth = ws.get_cached_depth("KXT-A")
    assert depth["yes"] == [[0.55, 100], [0.54, 200]], "both sides are bids: high first"
    assert depth["no"] == [[0.42, 50]]
    assert depth["seq"] == 1


def test_deltas_are_signed_changes_not_absolute_quantities(ws):
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[]))
    ws.update_orderbook_cache("KXT-A", _delta(0.55, 25, seq=2))
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 125]], (
        "delta 25 on a resting 100 must total 125, not replace it with 25"
    )
    ws.update_orderbook_cache("KXT-A", _delta(0.55, -25, seq=3))
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 100]]


def test_a_level_reaching_zero_is_evicted_from_the_book(ws):
    """Asserts the INTERNAL book, not the rendered depth.

    Mutation-testing this caught a vacuous first draft: _map_to_levels already
    filters `q > 0`, so an assertion on get_cached_depth() passes whether the
    exhausted level is evicted or left sitting at zero. The eviction is real
    and load-bearing anyway — without it a long-lived WS session accumulates
    an entry for every price level ever touched on every subscribed ticker,
    which is a slow leak, not a display quirk. So assert the thing that
    actually differs.
    """
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100], [0.54, 10]], no=[]))
    assert 0.54 in ws._depth_books["KXT-A"]["yes"], "positive control: level existed"

    ws.update_orderbook_cache("KXT-A", _delta(0.54, -10, seq=2))

    assert 0.54 not in ws._depth_books["KXT-A"]["yes"], (
        "an exhausted level must be evicted, not retained at qty 0"
    )
    assert ws._depth_books["KXT-A"]["yes"] == {0.55: 100}
    # And the rendered view has no zero-qty holes for a depth walk.
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 100]]


def test_a_new_price_level_can_be_created_by_a_delta(ws):
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[]))
    ws.update_orderbook_cache("KXT-A", _delta(0.53, 40, seq=2))
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 100], [0.53, 40]]


def test_sequence_gap_invalidates_the_book_and_a_snapshot_revives_it(ws):
    """Absence-assertion (get_cached_depth() is None) paired with positive
    controls on BOTH sides: the book was genuinely valid before the gap, and
    genuinely rebuildable after. Without them this would pass just as well if
    depth were never built at all."""
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[], seq=1))
    # Positive control 1 — there was a real book to lose.
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 100]]

    ws.update_orderbook_cache("KXT-A", _delta(0.55, -100, seq=99))
    assert ws.get_cached_depth("KXT-A") is None, "a gap must invalidate the book"

    # A delta arriving after the gap must not silently revive it either.
    ws.update_orderbook_cache("KXT-A", _delta(0.55, 5, seq=100))
    assert ws.get_cached_depth("KXT-A") is None

    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.60, 10]], no=[], seq=200))
    # Positive control 2 — the None above was invalidation, not permanent death.
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.60, 10]]


def test_in_sequence_deltas_do_not_invalidate(ws):
    """Positive control for the gap test: consecutive seqs must survive, or
    'gap detection works' could just mean 'every delta invalidates'."""
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[], seq=5))
    for i, seq in enumerate((6, 7, 8), start=1):
        ws.update_orderbook_cache("KXT-A", _delta(0.55, 1, seq=seq))
        assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 100 + i]]


def test_delta_before_any_snapshot_is_ignored(ws):
    ws.update_orderbook_cache("KXT-A", _delta(0.55, 10, seq=1))
    assert ws.get_cached_depth("KXT-A") is None
    # Positive control: the very same delta applies once a snapshot exists.
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[], seq=1))
    ws.update_orderbook_cache("KXT-A", _delta(0.55, 10, seq=2))
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 110]]


def test_stale_depth_is_withheld(ws):
    old = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    ws.update_orderbook_cache("KXT-A", _snapshot(ts=old))
    assert ws.get_cached_depth("KXT-A") is None
    # Positive control: an identical book with a fresh ts IS served.
    ws.update_orderbook_cache("KXT-A", _snapshot(ts=_now(), seq=1))
    assert ws.get_cached_depth("KXT-A") is not None


def test_an_unapplicable_delta_invalidates_rather_than_leaving_a_drifted_book(ws):
    """A delta we received but could not apply means the book changed and we
    failed to track it. Serving it on would be serving a drifted book, which
    the whole `valid` mechanism exists to prevent — so each of these must
    invalidate, and a fresh snapshot must bring the book back."""
    seq = 0
    for bad in (
        {"side": "maybe", "price_dollars": "0.55", "delta_fp": "5.00"},
        {"side": "yes", "price_dollars": None, "delta_fp": "5.00"},
        {"side": "yes", "price_dollars": "0.55", "delta_fp": "nope"},
        {"side": "yes", "price_dollars": "0.55"},
        {"side": "yes", "price_dollars": True, "delta_fp": "5.00"},
        {"side": "yes", "price_dollars": "0.55", "delta_fp": True},
        "not-a-dict",
    ):
        seq += 1
        ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[], seq=seq))
        # Positive control, every iteration: there was a real book to lose.
        assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 100]], bad

        seq += 1
        msg = _delta(0, 0, seq=seq)
        msg["delta"] = bad
        ws.update_orderbook_cache("KXT-A", msg)
        assert ws.get_cached_depth("KXT-A") is None, bad

    # And a well-formed delta at the next seq applies normally, proving the
    # rejections above are about the payloads and not about deltas at large.
    seq += 1
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[], seq=seq))
    ws.update_orderbook_cache("KXT-A", _delta(0.55, 25, seq=seq + 1))
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 125]]


def test_a_price_outside_zero_to_one_invalidates_rather_than_fabricating_depth(ws):
    """Kalshi prices are dollars in (0, 1). A cents-scaled price would key
    alongside the dollar-scaled ones and sort ABOVE every real level, so
    get_cached_depth()[...][0] would report a fabricated best bid. Refusing
    the book is the safe direction."""
    ws.update_orderbook_cache("KXT-A", _snapshot(yes=[[0.55, 100]], no=[], seq=1))
    assert ws.get_cached_depth("KXT-A") is not None, "positive control"

    ws.update_orderbook_cache("KXT-A", _delta(64, 30, seq=2))
    assert ws.get_cached_depth("KXT-A") is None, (
        "an out-of-scale price must invalidate, not create a phantom level"
    )


def test_snapshot_does_not_clobber_mid_price(ws):
    """Pre-existing bug fixed inline: the snapshot branch fell through to a
    wholesale `_orderbook[ticker] = data`, and a snapshot carries no
    mid_price — so every (re)subscribe blanked the value
    get_cached_mid_price() feeds to order_executor's flash-crash breaker."""
    ts = _now()
    ws.update_orderbook_cache(
        "KXT-A",
        {
            "type": "ticker",
            "ticker": "KXT-A",
            "yes_bid": 0.54,
            "yes_ask": 0.56,
            "mid_price": 0.55,
            "last_price": 0.55,
            "ts": ts,
        },
    )
    assert ws.get_cached_mid_price("KXT-A") == 0.55

    ws.update_orderbook_cache("KXT-A", _snapshot(ts=_now()))

    assert ws.get_cached_mid_price("KXT-A") == 0.55, "snapshot wiped mid_price"
    assert ws._orderbook["KXT-A"]["ts"] == ts, (
        "a snapshot doesn't refresh mid_price, so it must not refresh its ts "
        "either — same reasoning as the delta branch"
    )
    # Positive control: the snapshot's own fields did land.
    assert ws._orderbook["KXT-A"]["yes_levels"] == [[0.55, 100], [0.54, 200]]


def test_get_cached_book_shape_is_unchanged(ws):
    """get_cached_book's contract: exactly three keys, top-of-book only.

    Framing note (opus review): this is NOT a "the reprice path is unmoved"
    guard. With the snapshot-merge fix reverted, get_cached_book returns None
    here and the test fails — so it asserts the NEW behaviour. The reprice
    path genuinely does see something different after a snapshot now (it used
    to see None and fall back to a REST get_market() call), and that change
    is deliberate; see the module docstring and the batch notes. What this
    test does guard is that the SHAPE never grew a depth field, which is what
    would actually move a caller's behaviour.
    """
    ws.update_orderbook_cache(
        "KXT-A",
        {
            "type": "ticker",
            "ticker": "KXT-A",
            "yes_bid": 0.54,
            "yes_ask": 0.56,
            "mid_price": 0.55,
            "last_price": 0.55,
            "ts": _now(),
        },
    )
    ws.update_orderbook_cache("KXT-A", _snapshot())
    book = ws.get_cached_book("KXT-A")
    assert set(book) == {"yes_bid", "yes_ask", "mid_price"}
    assert book == {"yes_bid": 0.54, "yes_ask": 0.56, "mid_price": 0.55}


def test_delta_still_records_last_delta_unchanged(ws):
    """The existing last_delta contract (asserted by test_kalshi_ws.py) must
    survive the depth work."""
    ws.update_orderbook_cache("KXT-A", _snapshot(seq=1))
    msg = _delta(0.55, 5, seq=2)
    ws.update_orderbook_cache("KXT-A", msg)
    assert ws._orderbook["KXT-A"]["last_delta"] == msg["delta"]


def _queued(ws):
    out = []
    while True:
        try:
            out.append(ws._depth_write_queue.get_nowait())
        except queue.Empty:
            return out


def test_depth_snapshots_are_throttled_per_ticker(ws, monkeypatch):
    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "3600")

    ws.update_orderbook_cache("KXT-A", _snapshot(seq=1))
    for seq in (2, 3, 4):
        ws.update_orderbook_cache("KXT-A", _delta(0.55, 1, seq=seq))

    writes = _queued(ws)
    assert len(writes) == 1, f"expected one throttled write, got {len(writes)}"
    assert writes[0]["ticker"] == "KXT-A"
    assert writes[0]["env"] == "demo"
    assert writes[0]["yes_levels"] == [[0.55, 100], [0.54, 200]]
    assert writes[0]["no_levels"] == [[0.42, 50]]

    # Positive control: a DIFFERENT ticker is throttled independently.
    ws.update_orderbook_cache("KXT-B", _snapshot(ticker="KXT-B", seq=5))
    writes2 = _queued(ws)
    assert len(writes2) == 1 and writes2[0]["ticker"] == "KXT-B"


def test_depth_persistence_can_be_disabled(ws, monkeypatch):
    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "0")
    ws.update_orderbook_cache("KXT-A", _snapshot(seq=1))
    assert _queued(ws) == []
    # Positive control: with the throttle re-enabled the identical message
    # DOES enqueue, proving the empty list above is the setting and not a
    # message that never reached the persist path.
    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "3600")
    ws.update_orderbook_cache("KXT-A", _snapshot(seq=2))
    assert len(_queued(ws)) == 1


def test_the_writer_thread_actually_drains_to_the_db(ws, monkeypatch):
    """The queue hand-off exists so SQLite stays off the WS event loop — but
    a queue nothing drains is a writer that silently collects nothing, which
    is the failure this whole batch exists to prevent.

    Starts _depth_writer_loop directly rather than going through
    _ensure_depth_writer: the `ws` fixture stubs that out, and re-reading it
    off the module just recovers the stub.
    """
    import threading
    import time as _time

    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "3600")
    threading.Thread(
        target=kalshi_ws._depth_writer_loop, name="depth-writer-test", daemon=True
    ).start()

    ws.update_orderbook_cache("KXT-A", _snapshot(seq=1))

    deadline = _time.monotonic() + 10
    rows = []
    while _time.monotonic() < deadline:
        with sqlite3.connect(tracker.DB_PATH) as con:
            rows = con.execute(
                "SELECT ticker, yes_json, env FROM orderbook_depth_snapshots"
            ).fetchall()
        if rows:
            break
        _time.sleep(0.05)

    assert len(rows) == 1, f"writer thread never drained the queue: {rows}"
    assert rows[0][0] == "KXT-A"
    assert json.loads(rows[0][1]) == [[0.55, 100], [0.54, 200]]
    assert rows[0][2] == "demo"

    # Stop this test's writer so it doesn't sit on the queue afterwards.
    ws._depth_write_queue.put(None)


def test_a_full_queue_drops_the_snapshot_instead_of_blocking_the_feed(ws, monkeypatch):
    """Losing a depth snapshot is tolerable; blocking the WS event loop is
    not. put_nowait must never raise out of update_orderbook_cache."""
    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "3600")
    monkeypatch.setattr(kalshi_ws, "_depth_write_queue", queue.Queue(maxsize=1))
    ws._depth_write_queue.put_nowait({"filler": True})

    ws.update_orderbook_cache("KXT-A", _snapshot(seq=1))  # must not raise
    assert ws._depth_write_queue.qsize() == 1, "the new snapshot was dropped"

    # Positive control: with room in the queue the identical message lands.
    monkeypatch.setattr(kalshi_ws, "_depth_write_queue", queue.Queue(maxsize=4))
    monkeypatch.setattr(kalshi_ws, "_depth_last_persist", {})
    ws.update_orderbook_cache("KXT-A", _snapshot(seq=2))
    assert ws._depth_write_queue.qsize() == 1


def test_prune_depth_books_drops_only_unlisted_tickers(ws):
    for t in ("KXT-A", "KXT-B", "KXT-C"):
        ws.update_orderbook_cache(t, _snapshot(ticker=t, seq=1))
        assert ws.get_cached_depth(t) is not None, t

    assert ws.prune_depth_books(keep={"KXT-B"}) == 2
    assert ws.get_cached_depth("KXT-A") is None
    assert ws.get_cached_depth("KXT-C") is None
    # Positive control: the kept ticker survives untouched.
    assert ws.get_cached_depth("KXT-B") is not None
    assert "KXT-A" not in ws._depth_last_persist


def test_invalid_snapshot_interval_falls_back_to_60(ws, monkeypatch):
    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "banana")
    assert kalshi_ws._depth_snapshot_interval() == 60.0


def test_a_failing_depth_write_never_breaks_the_feed(ws, monkeypatch):
    monkeypatch.setenv("DEPTH_SNAPSHOT_INTERVAL_SECS", "3600")
    monkeypatch.setattr(
        tracker,
        "log_orderbook_depth",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    ws.update_orderbook_cache("KXT-A", _snapshot(seq=1))
    # Positive control: the message was still fully processed — the in-memory
    # book exists even though its persistence blew up.
    assert ws.get_cached_depth("KXT-A")["yes"] == [[0.55, 100], [0.54, 200]]


def test_orderbook_depth_row_round_trips():
    assert tracker.log_orderbook_depth(
        "KXT-A",
        [[0.55, 100], [0.54, 20]],
        [[0.42, 5]],
        env="demo",
        snapshot_at="2026-08-25T06:00:00+00:00",
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        con.row_factory = sqlite3.Row
        (row,) = [
            dict(r) for r in con.execute("SELECT * FROM orderbook_depth_snapshots")
        ]
    assert json.loads(row["yes_json"]) == [[0.55, 100], [0.54, 20]]
    assert json.loads(row["no_json"]) == [[0.42, 5]]
    assert row["env"] == "demo"
    assert row["snapshot_at"] == "2026-08-25T06:00:00+00:00"


def test_orderbook_depth_writer_never_raises():
    with patch.object(tracker, "_conn", side_effect=RuntimeError("db gone")):
        assert tracker.log_orderbook_depth("KXT-A", [[0.5, 1]], []) is False
    # Positive control.
    assert tracker.log_orderbook_depth("KXT-A", [[0.5, 1]], []) is True


# ══════════════════════════════════════════════════════════════════════════
# Schema
# ══════════════════════════════════════════════════════════════════════════


def test_schema_version_matches_migration_count():
    assert tracker._SCHEMA_VERSION == len(tracker._MIGRATIONS)


def test_migration_chain_applies_to_an_empty_database(tmp_path, monkeypatch):
    """Coordination requirement: batch 72 also appends to _MIGRATIONS, so
    whoever lands second re-numbers and re-proves the chain from scratch."""
    fresh = tmp_path / "fresh.db"
    monkeypatch.setattr(tracker, "DB_PATH", fresh)
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()

    with sqlite3.connect(fresh) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == (
            tracker._SCHEMA_VERSION
        )
        tables = {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"ensemble_member_values", "orderbook_depth_snapshots"} <= tables
        cols = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
        assert {"forecast_run_inits", "blend_exclusions", "forecast_cycle"} <= cols


# ══════════════════════════════════════════════════════════════════════════
# End-to-end: analyze_trade -> _prediction_kwargs_from_analysis -> the DB
# ══════════════════════════════════════════════════════════════════════════
#
# The batch file's own warning is that "a forward-only writer that silently
# no-ops costs exactly what this batch exists to prevent". Every test above
# exercises one link in the chain; these two prove the whole chain, because a
# writer that is correct in isolation but never reached collects nothing.


def test_analyze_trade_surfaces_the_new_fields(monkeypatch):
    from tests.test_weather_markets import (
        _analyze_trade_base_mocks,
        _analyze_trade_enriched_fixture,
    )

    _analyze_trade_base_mocks(monkeypatch, wm)
    # No network, and no quarantine file read: the run inits must come from
    # what a fetch observed this process.
    monkeypatch.setattr(wm, "get_quarantined_members", lambda: set())
    monkeypatch.setattr(
        wm, "_model_run_init_observed", {"icon_seamless": "2026-08-25T00:00:00+00:00"}
    )
    monkeypatch.setattr(
        wm,
        "_om_request",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("net!")),
    )

    result = wm.analyze_trade(_analyze_trade_enriched_fixture())

    assert result is not None
    assert "forecast_run_inits" in result, "item 1 never reached the result dict"
    assert result["forecast_run_inits"] == {
        "icon_seamless": "2026-08-25T00:00:00+00:00"
    }
    assert "blend_exclusions" in result, "item 3 never reached the result dict"
    assert isinstance(result["blend_exclusions"], dict)
    # nws_prob is mocked to None by the base mocks, so "nws" must be recorded
    # as an exclusion — a concrete positive control that the map is really
    # populated rather than just present and empty.
    assert result["blend_exclusions"].get("nws") == "unavailable", result[
        "blend_exclusions"
    ]
    # And the complement invariant holds against the real blend_sources.
    assert not (set(result["blend_sources"]) & set(result["blend_exclusions"])), (
        "a source cannot be both blended and excluded"
    )


def test_prediction_kwargs_carry_the_new_fields_into_the_db():
    """order_executor._prediction_kwargs_from_analysis is the bridge every
    real logging path goes through (it is also imported by main.py)."""
    import order_executor

    analysis = {
        "condition": {"type": "above", "threshold": 70, "var": "max"},
        "forecast_prob": 0.61,
        "market_prob": 0.5,
        "edge": 0.11,
        "blend_sources": {"ensemble": 1.0},
        "blend_exclusions": {"nws": "unavailable", "ensemble": "circuit_open"},
        "forecast_run_inits": {"icon_seamless": "2026-08-25T00:00:00+00:00"},
    }
    kwargs = order_executor._prediction_kwargs_from_analysis(analysis)

    assert kwargs["forecast_run_inits"] == analysis["forecast_run_inits"]
    assert kwargs["blend_exclusions"] == analysis["blend_exclusions"]
    # forecast_cycle is still produced independently and is NOT the run init.
    assert kwargs["forecast_cycle"].endswith("z")
    assert kwargs["forecast_cycle"] != kwargs["forecast_run_inits"]

    assert tracker.log_prediction(
        ticker="KXHIGHNY-26AUG26-B70",
        city="NYC",
        market_date=None,
        analysis=analysis,
        **{
            k: v
            for k, v in kwargs.items()
            if k
            in (
                "forecast_cycle",
                "blend_sources",
                "forecast_run_inits",
                "blend_exclusions",
            )
        },
    )
    with sqlite3.connect(tracker.DB_PATH) as con:
        inits, excl = con.execute(
            "SELECT forecast_run_inits, blend_exclusions FROM predictions"
        ).fetchone()
    assert json.loads(inits) == analysis["forecast_run_inits"]
    assert json.loads(excl) == analysis["blend_exclusions"]


# ══════════════════════════════════════════════════════════════════════════
# Item 4 — raw Kalshi envelopes through the REAL parse_message
# ══════════════════════════════════════════════════════════════════════════
#
# Every depth test above starts from a hand-built *parsed* dict, which is
# exactly how two HIGH defects survived the first round: parse_message was
# reading `yes`/`no` and the delta handler was reading `price`/`delta`, none
# of which appear in Kalshi's published AsyncAPI schema. The real field names
# are yes_dollars_fp/no_dollars_fp and price_dollars/delta_fp, and the
# payloads below are copied from that spec's own examples. This round trip is
# the guard against the whole class.


def _raw_snapshot(ticker="KXT-A", sid=2, seq=2):
    return {
        "type": "orderbook_snapshot",
        "sid": sid,
        "seq": seq,
        "msg": {
            "market_ticker": ticker,
            "market_id": "9b0f6b43-5b68-4f9f-9f02-9a2d1b8ac1a1",
            "yes_dollars_fp": [["0.0800", "300.00"], ["0.2200", "333.00"]],
            "no_dollars_fp": [["0.5400", "20.00"], ["0.5600", "146.00"]],
        },
    }


def _raw_delta(ticker="KXT-A", sid=2, seq=3, price="0.2200", delta="-33.00"):
    return {
        "type": "orderbook_delta",
        "sid": sid,
        "seq": seq,
        "msg": {
            "market_ticker": ticker,
            "market_id": "9b0f6b43-5b68-4f9f-9f02-9a2d1b8ac1a1",
            "price_dollars": price,
            "delta_fp": delta,
            "side": "yes",
            "ts": "2022-11-22T20:44:01Z",
            "ts_ms": 1669149841000,
        },
    }


def test_raw_kalshi_envelopes_build_a_real_depth_book(ws):
    """The end-to-end round trip: raw envelope -> parse_message ->
    update_orderbook_cache -> get_cached_depth."""
    parsed = kalshi_ws.parse_message(_raw_snapshot())
    assert parsed is not None and parsed["type"] == "orderbook_snapshot"
    assert parsed["yes_levels"] == [["0.0800", "300.00"], ["0.2200", "333.00"]], (
        "parse_message must read yes_dollars_fp — the bare `yes` key is not "
        "in Kalshi's schema and yielded an empty snapshot"
    )
    assert parsed["seq"] == 2 and parsed["sid"] == 2
    ws.update_orderbook_cache(parsed["ticker"], parsed)

    depth = ws.get_cached_depth("KXT-A")
    assert depth is not None, "a real snapshot must produce a usable book"
    assert depth["yes"] == [[0.22, 333], [0.08, 300]], depth
    assert depth["no"] == [[0.56, 146], [0.54, 20]], depth

    # Now a real delta: remove 33 contracts at 0.2200.
    parsed_d = kalshi_ws.parse_message(_raw_delta())
    assert parsed_d["seq"] == 3 and parsed_d["sid"] == 2
    ws.update_orderbook_cache(parsed_d["ticker"], parsed_d)

    depth = ws.get_cached_depth("KXT-A")
    assert depth is not None, "the delta must apply, not invalidate the book"
    assert depth["yes"] == [[0.22, 300], [0.08, 300]], (
        "delta_fp is a SIGNED change to the resting quantity: 333 - 33 = 300"
    )


def test_an_all_empty_snapshot_does_not_produce_a_confidently_valid_book(ws):
    """The failure mode behind the wrong-field-name bug: an empty book marked
    valid, which later deltas then build up from nothing — every removal a
    no-op, every addition a phantom level, with no gap warning."""
    empty = dict(_raw_snapshot())
    empty["msg"] = {"market_ticker": "KXT-A", "yes_dollars_fp": [], "no_dollars_fp": []}
    parsed = kalshi_ws.parse_message(empty)
    ws.update_orderbook_cache("KXT-A", parsed)
    assert ws.get_cached_depth("KXT-A") is None

    # Positive control: the same envelope WITH levels does produce a book.
    ws.update_orderbook_cache("KXT-A", kalshi_ws.parse_message(_raw_snapshot(seq=9)))
    assert ws.get_cached_depth("KXT-A") is not None


def test_seq_is_tracked_per_subscription_not_per_ticker(ws):
    """cron.py subscribes every scanned ticker under ONE subscribe message,
    so a single sid spans hundreds of markets and each ticker's own seq jumps
    by ~N between its messages. A per-ticker contiguity check would invalidate
    every book on its first delta and never recover."""
    for i, t in enumerate(("KXT-A", "KXT-B", "KXT-C"), start=1):
        ws.update_orderbook_cache(
            t, kalshi_ws.parse_message(_raw_snapshot(ticker=t, sid=7, seq=i))
        )
    for t in ("KXT-A", "KXT-B", "KXT-C"):
        assert ws.get_cached_depth(t) is not None, t

    # Interleaved deltas on one shared counter — contiguous per sid, but each
    # ticker's own seq jumps by 3.
    for i, t in enumerate(("KXT-A", "KXT-B", "KXT-C"), start=4):
        ws.update_orderbook_cache(
            t, kalshi_ws.parse_message(_raw_delta(ticker=t, sid=7, seq=i))
        )

    for t in ("KXT-A", "KXT-B", "KXT-C"):
        depth = ws.get_cached_depth(t)
        assert depth is not None, f"{t} was invalidated by a per-ticker seq check"
        assert depth["yes"] == [[0.22, 300], [0.08, 300]], t


def test_a_real_gap_invalidates_every_book_on_that_subscription(ws):
    """The lost message could have belonged to any market on the sid, and we
    cannot tell which — so all of them are suspect."""
    for i, t in enumerate(("KXT-A", "KXT-B"), start=1):
        ws.update_orderbook_cache(
            t, kalshi_ws.parse_message(_raw_snapshot(ticker=t, sid=7, seq=i))
        )
    assert ws.get_cached_depth("KXT-A") is not None  # positive control
    assert ws.get_cached_depth("KXT-B") is not None

    # seq jumps 2 -> 50 on the shared counter.
    ws.update_orderbook_cache(
        "KXT-A", kalshi_ws.parse_message(_raw_delta(ticker="KXT-A", sid=7, seq=50))
    )
    assert ws.get_cached_depth("KXT-A") is None
    assert ws.get_cached_depth("KXT-B") is None, (
        "a gap on the subscription must invalidate every book under it, not "
        "only the ticker whose message happened to carry the gap"
    )


def test_hourly_fetches_are_not_persisted_as_member_values(monkeypatch):
    """ensemble_member_values' dedup key has no hour component.

    If the `hour is None` guard in get_ensemble_temps were removed, an hourly
    member set would insert FIRST for (city, model, target_date, var, cycle)
    and INSERT OR IGNORE would then permanently block the daily set for that
    whole window — silently poisoning A15's daily rank histogram with hourly
    data, undetectable after the fact.
    """
    monkeypatch.setattr(wm, "_ensemble_cache", type(wm._ensemble_cache)(ttl_secs=1))
    monkeypatch.setattr(wm, "_fetch_model_ensemble", lambda *a, **kw: [70.0, 71.0])
    monkeypatch.setattr(wm, "_save_ensemble_disk_entry", lambda *a, **kw: None)
    monkeypatch.setattr(wm, "get_quarantined_members", lambda: set())
    monkeypatch.setattr(wm, "_model_weights", lambda *a, **kw: {})
    monkeypatch.setattr(wm, "_model_bias", lambda *a, **kw: {})

    from datetime import date as _date

    with patch.object(wm, "_member_values_pending", []) as pending:
        with patch.object(wm, "get_model_run_init", return_value="RUN"):
            wm.get_ensemble_temps("NYC", _date(2026, 8, 26), hour=14, var="max")
        assert pending == [], "an hourly fetch must not buffer member values"

        # Positive control: the identical call with hour=None DOES buffer,
        # proving the empty list above is the guard and not a mock that
        # stopped the code short of the writer.
        with patch.object(wm, "get_model_run_init", return_value="RUN"):
            wm.get_ensemble_temps("NYC", _date(2026, 8, 26), hour=None, var="max")
        assert len(pending) > 0, "the daily path must still buffer"
        assert all(r["members"] == [70.0, 71.0] for r in pending)


def test_migrations_upgrade_an_existing_older_database(tmp_path, monkeypatch):
    """The empty-DB test alone would still pass if someone moved the new
    columns into the base CREATE TABLE and deleted the ALTERs — which would
    break every existing production database. This exercises the real
    upgrade path.

    Pinned at 61, the version this batch branched from, deliberately: batch-69
    landed four migrations (62-65) while this one was in flight, so batch-64's
    own six were re-numbered to 66-71 on rebase. Starting from 61 exercises
    BOTH batches' migrations in order, which is the case a real production DB
    that missed both will actually take.
    """
    _PRE = 61
    old = tmp_path / "old.db"
    monkeypatch.setattr(tracker, "DB_PATH", old)
    monkeypatch.setattr(tracker, "_db_initialized", False)

    # Build a DB at the pre-batch-64 state: base schema + the first 61
    # migrations, cursor pinned at 61.
    monkeypatch.setattr(tracker, "_MIGRATIONS", tracker._MIGRATIONS[:_PRE])
    monkeypatch.setattr(tracker, "_SCHEMA_VERSION", _PRE)
    tracker.init_db()
    with sqlite3.connect(old) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == _PRE
        cols = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
        assert "forecast_run_inits" not in cols, "fixture must start without it"

    # Now upgrade with the real list.
    monkeypatch.undo()
    monkeypatch.setattr(tracker, "DB_PATH", old)
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()

    with sqlite3.connect(old) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == (
            tracker._SCHEMA_VERSION
        )
        cols = {r[1] for r in con.execute("PRAGMA table_info(predictions)")}
        assert {"forecast_run_inits", "blend_exclusions"} <= cols
        tables = {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"ensemble_member_values", "orderbook_depth_snapshots"} <= tables


def test_metar_locked_analysis_still_produces_blend_exclusions(monkeypatch):
    """Regression guard for the UnboundLocalError.

    blend_exclusions was initialised inside `if not metar_locked:`, so the
    METAR-locked path never assigned it and the result dict's read raised.
    analyze_trade's callers swallow the exception, so every METAR-locked
    market — the whole `between` bracket family, which requires lock-in —
    was silently skipped and no trade placed where one previously would have
    been. A write-only observation must never be able to do that.
    """
    from tests.test_weather_markets import (
        _analyze_trade_base_mocks,
        _analyze_trade_enriched_fixture,
    )

    _analyze_trade_base_mocks(monkeypatch, wm)
    monkeypatch.setattr(wm, "get_quarantined_members", lambda: set())
    monkeypatch.setattr(wm, "_metar_lock_in", lambda *a, **kw: (True, 0.93, {}))

    result = wm.analyze_trade(_analyze_trade_enriched_fixture())

    assert result is not None, "METAR-locked analysis must not raise/skip"
    assert result["blend_exclusions"] == {}, (
        "METAR lock-in bypasses the multi-source blend entirely, so there is "
        "no exclusion decision to record — but the key must still exist"
    )
    # Positive control that lock-in really engaged, or the assertion above
    # would be about the ordinary path.
    assert result.get("metar_locked") is True


def test_an_open_ensemble_circuit_is_recorded_as_circuit_open(monkeypatch):
    """'the ensemble was missing' and 'the ensemble was suppressed because
    its breaker was open' are very different facts for A3. Before this they
    were the same _log line and nothing else."""
    from tests.test_weather_markets import (
        _analyze_trade_base_mocks,
        _analyze_trade_enriched_fixture,
    )

    _analyze_trade_base_mocks(monkeypatch, wm)
    monkeypatch.setattr(wm, "get_quarantined_members", lambda: set())
    monkeypatch.setattr(wm, "_ensemble_circuit_is_open", lambda: True)

    result = wm.analyze_trade(_analyze_trade_enriched_fixture())
    assert result is not None
    assert result["blend_exclusions"].get("ensemble") == "circuit_open", result[
        "blend_exclusions"
    ]

    # Control run: breaker CLOSED but the ensemble genuinely absent must read
    # "unavailable", or "circuit_open" would be indistinguishable from the
    # default and the branch would be untested.
    monkeypatch.setattr(wm, "_ensemble_circuit_is_open", lambda: False)
    monkeypatch.setattr(wm, "get_ensemble_temps", lambda *a, **kw: [])
    result2 = wm.analyze_trade(_analyze_trade_enriched_fixture())
    if result2 is not None and "ensemble" in result2["blend_exclusions"]:
        assert result2["blend_exclusions"]["ensemble"] == "unavailable", result2[
            "blend_exclusions"
        ]
