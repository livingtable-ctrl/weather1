"""Tests for per-market flash crash circuit breaker."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFlashCrashCB:
    def setup_method(self):
        # Isolation of circuit_breaker._FLASH_CRASH_HISTORY_PATH/
        # _FLASH_CRASH_COOLDOWN_PATH (and the flash_crash_cb singleton's
        # in-memory state) is handled by the autouse isolate_flash_crash_cb_state
        # fixture in conftest.py -- verified empirically that it takes effect
        # before setup_method runs, so FlashCrashCB() built here picks up the
        # redirected paths with no per-file isolation code needed.
        from circuit_breaker import FlashCrashCB

        self.cb = FlashCrashCB(
            threshold_pct=0.20, window_seconds=300, cooldown_seconds=600
        )

    def test_no_crash_on_first_observation(self):
        assert self.cb.check("TICKER-A", 0.50) is False

    def test_no_crash_on_small_move(self):
        self.cb.check("TICKER-A", 0.50)
        assert self.cb.check("TICKER-A", 0.55) is False

    def test_crash_on_large_move(self):
        self.cb.check("TICKER-A", 0.60)
        assert self.cb.check("TICKER-A", 0.45) is True  # -25%

    def test_cooldown_prevents_trading(self):
        self.cb.check("TICKER-B", 0.60)
        self.cb.check("TICKER-B", 0.40)  # -33% → crash
        assert self.cb.is_in_cooldown("TICKER-B") is True

    def test_different_tickers_independent(self):
        self.cb.check("TICKER-C", 0.80)
        self.cb.check("TICKER-C", 0.40)
        assert self.cb.is_in_cooldown("TICKER-C") is True
        assert self.cb.is_in_cooldown("TICKER-D") is False

    def test_no_cooldown_on_clean_ticker(self):
        assert self.cb.is_in_cooldown("BRAND-NEW") is False

    def test_cooldown_expires(self):
        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=1, cooldown_seconds=1)
        cb.check("TICKER-E", 0.80)
        cb.check("TICKER-E", 0.40)
        assert cb.is_in_cooldown("TICKER-E") is True
        time.sleep(1.1)
        assert cb.is_in_cooldown("TICKER-E") is False

    def test_upward_spike_also_triggers(self):
        self.cb.check("TICKER-F", 0.30)
        assert self.cb.check("TICKER-F", 0.70) is True  # +133%


class TestFlashCrashCBHistoryPersistence:
    """Proves the actual point of persisting _history to disk: two SEPARATE
    FlashCrashCB instances sharing the same disk path (simulating two
    separate process invocations, e.g. two `python main.py cron` runs close
    together) must be able to detect a crash across that boundary -- before
    this fix, _history was in-memory only, so a fresh instance/process could
    never see a prior instance's observations and detection was impossible.
    Every other test in this file uses one long-lived `self.cb`, which would
    still pass even if _save_history()/_load_history() were silently
    reverted -- this is the one test that would actually catch that."""

    def test_second_instance_on_same_path_detects_crash_from_first(self):
        from circuit_breaker import FlashCrashCB

        # Both instances share the same (test-isolated) disk path via the
        # autouse fixture's redirected circuit_breaker._FLASH_CRASH_HISTORY_PATH.
        first = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert first.check("TICKER-CROSS", 0.60) is False

        second = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert second.check("TICKER-CROSS", 0.45) is True  # -25%, seen via disk

    def test_second_instance_does_not_false_positive_on_small_move(self):
        from circuit_breaker import FlashCrashCB

        first = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert first.check("TICKER-CROSS-2", 0.60) is False

        second = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert second.check("TICKER-CROSS-2", 0.62) is False  # +3%, no crash


class TestFlashCrashCBHistorySaveThrottle:
    """2026-07-12: check() now fires on every live WS tick (kalshi_ws.py's
    update_orderbook_cache), not just once per scan cycle -- persisting the
    full history JSON on every single call while holding self._lock would let
    disk I/O throttle real-time crash detection for the main scan thread.
    _save_history() is now rate-limited to once per _HISTORY_SAVE_INTERVAL_SECS;
    in-memory comparison (what check()'s return value actually depends on) is
    never throttled."""

    def test_rapid_successive_calls_skip_disk_save_but_still_detect_crash(
        self, monkeypatch
    ):
        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        save_calls = []
        monkeypatch.setattr(cb, "_save_history", lambda: save_calls.append(1) or None)

        cb.check("TICKER-THROTTLE", 0.60)  # first call always saves (0.0 baseline)
        assert len(save_calls) == 1

        # Several rapid calls within the throttle window must not save again...
        cb.check("TICKER-THROTTLE", 0.59)
        cb.check("TICKER-THROTTLE", 0.58)
        assert len(save_calls) == 1

        # ...but in-memory crash detection is completely unaffected by the throttle.
        assert cb.check("TICKER-THROTTLE", 0.40) is True  # -33% from 0.60

    def test_save_resumes_once_interval_elapses(self, monkeypatch):
        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        save_calls = []
        monkeypatch.setattr(cb, "_save_history", lambda: save_calls.append(1) or None)

        cb.check("TICKER-THROTTLE-2", 0.60)
        assert len(save_calls) == 1

        cb._last_history_save -= cb._HISTORY_SAVE_INTERVAL_SECS + 1
        cb.check("TICKER-THROTTLE-2", 0.59)
        assert len(save_calls) == 2


class TestFlashCrashCBAbsoluteFloor:
    """The breaker requires a move to clear BOTH a relative threshold and an
    absolute floor. A purely relative threshold is meaningless on a penny
    book: replaying data/.flash_crash_history.json from the 2026-09-07 cron
    run (313 tickers) through check()'s own arithmetic, 18 tickers tripped and
    15 of them had moved 4 cents or less (7 of those a cent or less) -- one of
    them 41 times, on a mid oscillating between 0.005 and 0.01. The 18 is a
    count under the OLD purely-relative rule, before _COMPARE_EPSILON existed;
    with the epsilon it is 19, the extra one being a 0.5c move the floor
    rejects anyway.

    Each guard gets its OWN test here. They produce the same observable
    (check() returns False), so a single test covering "doesn't trip" would
    exercise only whichever guard its scenario happens to hit and leave the
    other one silently uncovered."""

    def _cb(self):
        from circuit_breaker import FlashCrashCB

        return FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )

    def test_big_relative_move_below_the_absolute_floor_does_not_trip(self):
        """Guard 2 (the absolute floor), isolated: the relative threshold is
        cleared four times over and the trip must still be refused."""
        cb = self._cb()
        cb.check("PENNY", 0.025)
        # 0.025 -> 0.005 is -80%, four times past threshold_pct, but 2 cents.
        assert cb.check("PENNY", 0.005) is False
        assert cb.is_in_cooldown("PENNY") is False

        # POSITIVE CONTROL: the identical -80% move on a book big enough to
        # clear the floor DOES trip, proving the refusal above came from the
        # floor and not from the scenario failing to reach the branch at all.
        cb.check("RICH", 0.50)
        assert cb.check("RICH", 0.10) is True
        assert cb.is_in_cooldown("RICH") is True

    def test_big_absolute_move_below_the_relative_threshold_does_not_trip(self):
        """Guard 1 (the pre-existing relative threshold), isolated: the floor
        is cleared twice over and the trip must still be refused. Without this
        test, mutating `move / oldest_price < self.threshold_pct` away would
        leave the suite green."""
        cb = self._cb()
        cb.check("EXPENSIVE", 0.90)
        # 0.90 -> 0.80 is 10 cents (2x the floor) but only -11.1%.
        assert cb.check("EXPENSIVE", 0.80) is False
        assert cb.is_in_cooldown("EXPENSIVE") is False

        # POSITIVE CONTROL: same ticker, still comfortably past the floor,
        # now also past the relative threshold -- so the branch is reachable.
        # (This is 0.90 -> 0.65 = 25c, not a magnitude match for the 10c case
        # above; oldest_price stays 0.90 because history is [0.90, 0.80, 0.65].)
        assert cb.check("EXPENSIVE", 0.65) is True
        assert cb.is_in_cooldown("EXPENSIVE") is True

    def test_move_exactly_at_the_floor_trips(self):
        """0.10 -> 0.05 is exactly 0.05 in IEEE 754 (no representation error),
        pinning the boundary as inclusive."""
        cb = self._cb()
        cb.check("BOUNDARY", 0.10)
        assert cb.check("BOUNDARY", 0.05) is True

    def test_exact_five_cent_move_that_floats_just_under_the_floor_trips(self):
        """The float-representation regression on the FLOOR. abs(0.15 - 0.10)
        evaluates to 0.04999999999999999, so a mathematically-exact 5-cent
        move compares as BELOW a 0.05 floor. The -33% relative move clears the
        threshold comfortably, so only the floor's epsilon is under test."""
        cb = self._cb()
        assert abs(0.15 - 0.10) < 0.05, "premise: this really is a float below 0.05"
        cb.check("FLOATY", 0.15)
        assert cb.check("FLOATY", 0.10) is True

    def test_exact_twenty_percent_move_that_floats_just_under_it_trips(self):
        """The same regression on the RELATIVE threshold, which is pre-existing
        rather than introduced here: (0.50 - 0.40) / 0.50 is
        0.19999999999999996, so a textbook 20% crash was silently refused by a
        breaker documenting a 20% threshold. The 10-cent move clears the
        absolute floor twice over, so only the threshold's epsilon is under
        test."""
        cb = self._cb()
        assert (0.50 - 0.40) / 0.50 < 0.20, "premise: this really is a float below 0.20"
        cb.check("FLOATY-REL", 0.50)
        assert cb.check("FLOATY-REL", 0.40) is True

    def test_just_below_the_floor_does_not_trip(self):
        """4.4 cents at -22%: past the relative threshold, under the floor.
        The epsilon must not be wide enough to admit this."""
        cb = self._cb()
        cb.check("NEARLY", 0.20)
        assert cb.check("NEARLY", 0.156) is False
        assert cb.is_in_cooldown("NEARLY") is False

    @pytest.mark.parametrize(
        "ticker,first,second,should_trip",
        [
            # Real (ticker, oldest, extreme) pairs read out of the 2026-09-07
            # .flash_crash_history.json. The three that should trip are the
            # three whose absolute move a human would call a crash.
            #
            # DELIBERATELY REDUNDANT, and kept as a REGRESSION CORPUS rather
            # than as guard coverage: all five no-trip cases are refused by the
            # same guard (the absolute floor), so one mutation kills all five
            # and they prove nothing the two dedicated single-guard tests above
            # do not already prove. What they do carry is the actual incident --
            # if someone later loosens the rule, this is the record of which
            # real markets it would let back through. KXRAINMIAM is the only
            # one near BOTH bounds at once (5.5c / +22.9%).
            ("KXTEMPNYCH-26SEP0715-T76.99", 0.63, 0.905, True),  # 27.5c, +43.7%
            ("KXTEMPMIAH-26SEP0715-T87.99", 0.245, 0.15, True),  # 9.5c, -38.8%
            ("KXRAINMIAM-26SEP-12", 0.24, 0.295, True),  # 5.5c, +22.9%
            ("KXTEMPLAXH-26SEP0715-T83.99", 0.075, 0.035, False),  # 4.0c, -53.3%
            ("KXHIGHTDAL-26SEP07-B103.5", 0.03, 0.06, False),  # 3.0c, +100%
            ("KXHIGHLAX-26SEP07-B80.5", 0.025, 0.005, False),  # 2.0c, -80%
            ("KXHIGHTOKC-26SEP07-T104", 0.015, 0.025, False),  # 1.0c, +66.7%
            ("KXRAIN-26SEP07-DAL", 0.01, 0.005, False),  # 0.5c, -50%
        ],
    )
    def test_replays_the_2026_09_07_incident(self, ticker, first, second, should_trip):
        cb = self._cb()
        cb.check(ticker, first)
        assert cb.check(ticker, second) is should_trip
        assert cb.is_in_cooldown(ticker) is should_trip


class TestFlashCrashCBCooldownReArm:
    """While a ticker is already cooling, a further crash-sized move must
    extend protection without re-logging or re-writing disk on every tick.
    Before this, one ticker produced ~50 WARNING lines and ~50 atomic writes
    in ~110 seconds (backlog.txt, 2026-08-30), burying the rest of the cycle."""

    def _armed(self):
        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )
        cb.check("COOLING", 0.60)
        assert cb.check("COOLING", 0.30) is True  # arms it
        return cb

    def test_rearm_extends_the_deadline_without_relogging(self, caplog):
        import logging

        cb = self._armed()
        # Pull the deadline in to just-about-to-expire so a genuine extension
        # is observable as a forward jump rather than a sub-millisecond delta.
        cb._cooldowns["COOLING"] = time.time() + 1.0
        before = cb._cooldowns["COOLING"]

        # _armed() itself emitted the arming WARNING, and caplog accumulates
        # across the whole test -- without this the assertion below would be
        # reading that record, not the re-arm's.
        caplog.clear()

        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            result = cb.check("COOLING", 0.28)

        # VALUE FIRST: the deadline actually moved, and moved by roughly a
        # full cooldown -- asserting the log count first would short-circuit
        # this claim under mutation.
        after = cb._cooldowns["COOLING"]
        assert after > before
        assert after - time.time() > 500
        assert result is False  # edge semantics: it did not ARM, it extended
        assert cb.is_in_cooldown("COOLING") is True

        # Assert on LEVEL, not on a message substring. The first version of
        # this test filtered for "FLASH CRASH CB", which the re-arm branch
        # never emits -- its message is "FlashCrashCB: ... still crashing",
        # and "FLASH CRASH CB" in "FlashCrashCB: ..." is False. The list was
        # therefore empty for a reason unrelated to the log level under test,
        # and mutating the re-arm's _log.debug back to _log.warning (i.e.
        # literally reinstating the spam this change exists to remove) left
        # the whole suite green.
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        # POSITIVE CONTROL for that absence: the branch really did run, and
        # really did log -- at DEBUG. Without this the assertion above is
        # satisfied just as well by check() never reaching the branch.
        assert [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "still crashing" in r.getMessage()
        ]

    def test_first_trip_does_log_a_warning(self, caplog):
        """POSITIVE CONTROL for the absence assertion above: the WARNING this
        suppresses is genuinely emitted on the arming edge, so its absence
        during a re-arm means suppression, not a scenario that never reached
        the log call."""
        import logging

        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )
        with caplog.at_level(logging.WARNING, logger="circuit_breaker"):
            cb.check("FIRST", 0.60)
            assert cb.check("FIRST", 0.30) is True

        assert [r for r in caplog.records if "FLASH CRASH CB" in r.getMessage()]

    def test_rearm_never_shortens_an_existing_deadline(self):
        """max(), not assignment. A plain `self._cooldowns[t] = now + cooldown`
        passes every other test in this class but pulls a longer deadline
        BACKWARDS, which is the one direction a circuit breaker must never
        move on its own."""
        cb = self._armed()
        far_future = time.time() + 10_000
        cb._cooldowns["COOLING"] = far_future

        cb.check("COOLING", 0.28)

        assert cb._cooldowns["COOLING"] == far_future

    def test_rearm_disk_writes_are_throttled(self, monkeypatch):
        cb = self._armed()
        save_calls = []
        monkeypatch.setattr(cb, "_save_cooldowns", lambda: save_calls.append(1) or None)

        # A burst of re-triggering ticks inside the throttle window.
        for price in (0.29, 0.28, 0.27, 0.26):
            cb.check("COOLING", price)
        assert save_calls == []

        # ...and the throttle releases once the interval has elapsed.
        cb._last_cooldown_save -= cb._COOLDOWN_SAVE_INTERVAL_SECS + 1
        cb.check("COOLING", 0.25)
        assert len(save_calls) == 1


class TestFlashCrashCBSurvivorGaps:
    """Tests added after an independent review re-ran the mutation set and
    found FIVE survivors the original six mutations missed. Each test here
    exists to kill exactly one of them; the mutation it kills is named in the
    docstring so a later reader can re-run it."""

    def test_production_default_min_abs_move_is_pinned(self):
        """Kills: constructor default min_abs_move 0.05 -> 0.0.

        Every other test in this file passes min_abs_move explicitly, but the
        object production actually gates on is the module-level singleton
        `flash_crash_cb = FlashCrashCB()`, which takes the DEFAULT. Nothing
        noticed when the default was mutated to 0.0 -- the value that restores
        the exact penny-book behaviour this change exists to remove."""
        from circuit_breaker import FlashCrashCB

        assert FlashCrashCB().min_abs_move == 0.05

        # Behavioural half: the default really does refuse a penny-book move,
        # driven through a default-constructed instance rather than asserted
        # on the attribute alone.
        cb = FlashCrashCB()
        cb.check("DEFAULTED", 0.025)
        assert cb.check("DEFAULTED", 0.005) is False

    def test_negative_min_abs_move_is_refused_at_construction(self):
        from circuit_breaker import FlashCrashCB

        with pytest.raises(ValueError, match="min_abs_move"):
            FlashCrashCB(min_abs_move=-0.01)

    def test_epsilon_stays_orders_of_magnitude_below_the_tick_grid(self):
        """Kills: _COMPARE_EPSILON widened into the real quoting grid.

        test_just_below_the_floor_does_not_trip only bites once the epsilon
        exceeds ~0.006, leaving the whole band from 1e-9 to 0.005 unpinned --
        while the production comment's safety argument rests on the epsilon
        being ~1e6 times smaller than the smallest real gap. Pin THAT claim,
        not a weaker one: an earlier version asserted < 1e-6, which is only 3
        orders below the grid gap and would admit an epsilon 100x looser than
        the comment documents."""
        from circuit_breaker import FlashCrashCB

        # The two real margins, measured on the half-cent grid Kalshi mids
        # land on: 0.005 below the absolute bound, 0.00102 below the relative
        # one (at oldest=0.98 -> 0.785). Require five clear orders under the
        # tighter of the two, so the "orders of magnitude" claim is real.
        smallest_relative_gap = 0.00102
        assert FlashCrashCB._COMPARE_EPSILON * 1e5 < smallest_relative_gap

    def test_expired_cooldown_then_new_crash_arms_and_logs_again(self, caplog):
        """Kills: `already_cooling = ticker in self._cooldowns`.

        An expired entry survives in _cooldowns until the next
        _save_cooldowns() prunes it, so a membership test would route a
        genuinely NEW crash on a previously-cooled ticker into the silent
        DEBUG branch and return False -- the operator's only WARNING for that
        crash would disappear. It must be a TIME comparison. The pre-existing
        test_cooldown_expires only checks that is_in_cooldown flips to False;
        it never re-crashes the ticker."""
        import logging

        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=1,
            min_abs_move=0.05,
        )
        cb.check("EXPIRING", 0.60)
        assert cb.check("EXPIRING", 0.30) is True  # arms
        time.sleep(1.1)
        assert cb.is_in_cooldown("EXPIRING") is False
        # POSITIVE CONTROL: the stale entry is still in the dict, which is
        # precisely why a membership test would be wrong here.
        assert "EXPIRING" in cb._cooldowns

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            result = cb.check("EXPIRING", 0.15)

        assert result is True  # armed afresh, not silently extended
        assert cb.is_in_cooldown("EXPIRING") is True
        assert [r for r in caplog.records if "FLASH CRASH CB" in r.getMessage()]

    def test_armed_cooldown_survives_into_a_second_instance(
        self, tmp_path, monkeypatch
    ):
        """Kills: deleting the arming path's unthrottled _save_cooldowns().

        The class docstring's R14 rationale -- cooldowns are persisted so
        restarts don't lose active protection -- had no test at all, and the
        bot runs as a one-shot `python main.py cron`, so the cross-process
        case is the normal case rather than an edge one. Mirrors the existing
        TestFlashCrashCBHistoryPersistence shape for _history."""
        import circuit_breaker
        from circuit_breaker import FlashCrashCB

        # Both instances share one isolated path. The autouse conftest fixture
        # already points _FLASH_CRASH_COOLDOWN_PATH at exactly this file, so
        # this rebind is a no-op today -- it is written with monkeypatch (not
        # a raw module-global assignment) purely so that it stays undone at
        # teardown if the fixture's filename ever diverges from this one.
        cd_path = tmp_path / ".flash_crash_cooldowns.json"
        monkeypatch.setattr(circuit_breaker, "_FLASH_CRASH_COOLDOWN_PATH", cd_path)

        first = FlashCrashCB(
            threshold_pct=0.20, window_seconds=300, cooldown_seconds=600
        )
        first.check("PERSISTED", 0.60)
        assert first.check("PERSISTED", 0.30) is True
        assert cd_path.exists(), "arming must write the cooldown through to disk"

        second = FlashCrashCB(
            threshold_pct=0.20, window_seconds=300, cooldown_seconds=600
        )
        assert second.is_in_cooldown("PERSISTED") is True
        # POSITIVE CONTROL: the second instance is not simply saying True to
        # everything -- an unrelated ticker is still clean.
        assert second.is_in_cooldown("NEVER-CRASHED") is False

    def test_zero_first_observation_cannot_divide_by_zero(self):
        """Kills: deleting `if oldest_price <= 0: return False`.

        Nothing in the suite fed a zero first observation, so a future
        refactor that reordered the new `move = abs(...)` / floor checks above
        that guard would raise ZeroDivisionError inside check() -- on the
        kalshi_ws background thread. Not hypothetical: this change's own
        docstring argues a 0.005 mid means an empty bid side."""
        cb = self._cb()
        cb.check("ZEROED", 0.0)
        assert cb.check("ZEROED", 0.10) is False  # must not raise
        assert cb.is_in_cooldown("ZEROED") is False

    def _cb(self):
        from circuit_breaker import FlashCrashCB

        return FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )

    def test_non_finite_price_does_not_arm_a_cooldown(self):
        """The guards are written as inverted early-returns, and every
        comparison against NaN is False -- so without an explicit finiteness
        check a NaN price falls through BOTH of them into the arming path and
        logs a 'nan% move'. The pre-refactor single positive `if` evaluated
        False and armed nothing, so the refactor had silently reversed this."""
        cb = self._cb()
        cb.check("NANNY", 0.50)
        assert cb.check("NANNY", float("nan")) is False
        assert cb.is_in_cooldown("NANNY") is False

        cb.check("INFY", 0.50)
        assert cb.check("INFY", float("inf")) is False
        assert cb.is_in_cooldown("INFY") is False

        # POSITIVE CONTROL: a finite crash on the same tickers still arms, so
        # the refusals above are the finiteness guard and not a dead scenario.
        assert cb.check("NANNY", 0.20) is True


class TestFlashCrashCBEscalationLogging:
    """A materially bigger move during an active cooldown is a different event
    from a repeat tick. Demoting every re-arm to DEBUG lost information the
    operator previously had -- and DEBUG reaches only the per-pid debug file,
    since both the console and the main log handler sit at INFO."""

    def _armed(self):
        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )
        cb.check("ESC", 0.60)
        assert cb.check("ESC", 0.48) is True  # arms on a 12c move
        return cb

    def test_materially_larger_move_re_warns(self, caplog):
        import logging

        cb = self._armed()
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            # 0.60 -> 0.05 is 55c, far past 1.5x the 12c that armed it.
            assert cb.check("ESC", 0.05) is False

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "an escalating crash must reach the operator"
        assert "STILL FALLING" in warnings[0].getMessage()

    def test_ordinary_retick_stays_quiet(self, caplog):
        """POSITIVE CONTROL for the test above: the escalation path must not
        fire on jitter inside an already-reported crash, or the change has
        simply reinstated the spam it removed."""
        import logging

        cb = self._armed()
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            # 13c vs the 12c that armed it -- bigger, but not 1.5x bigger.
            assert cb.check("ESC", 0.47) is False

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        assert [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "still crashing" in r.getMessage()
        ]

    def test_escalation_re_baselines_so_it_fires_once_per_step(self, caplog):
        """After an escalation warns, the new (larger) move becomes the
        baseline -- otherwise every subsequent tick of a deep crash re-warns
        against the original small arming move and the spam returns."""
        import logging

        cb = self._armed()
        cb.check("ESC", 0.05)  # escalates, re-baselines to 55c
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            assert cb.check("ESC", 0.04) is False  # 56c: bigger, not 1.5x

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


class TestFlashCrashCBConcurrency:
    """Both feeds -- the kalshi_ws background thread and the main scan thread
    -- call check() on the same singleton, and this change added a new
    read-then-write of _cooldowns/_armed_move/_last_cooldown_save inside the
    lock. The suite had no threaded coverage at all.

    SCOPE, stated honestly: this is a DEADLOCK detector, not a race detector.
    It reliably catches lock re-entry (the failure mode that actually threatens
    this class, since self._lock is a plain Lock and check() would self-
    deadlock if it ever called is_in_cooldown() from inside the hold). It does
    NOT observe data races -- deleting `with self._lock:` from check() outright
    leaves it green. Pinning that would need deterministic interleaving, which
    is a bigger harness than this change warrants."""

    def test_concurrent_check_and_is_in_cooldown_do_not_deadlock(self):
        import threading

        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )
        errors: list[BaseException] = []
        done = threading.Event()

        def hammer_check():
            try:
                for i in range(200):
                    cb.check(f"T{i % 5}", 0.60 if i % 2 else 0.20)
            except BaseException as exc:  # noqa: BLE001 - recorded, re-raised below
                errors.append(exc)
            finally:
                done.set()

        def hammer_read():
            try:
                while not done.is_set():
                    cb.is_in_cooldown("T0")
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        # daemon=True so a re-entry regression FAILS the test instead of
        # hanging the pytest process forever: done.set() lives in
        # hammer_check's finally, which never runs if it deadlocks, so a
        # non-daemon hammer_read would block interpreter exit at join.
        t1 = threading.Thread(target=hammer_check, daemon=True)
        t2 = threading.Thread(target=hammer_read, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not t1.is_alive(), "check() thread hung -- probable lock re-entry"
        assert not t2.is_alive(), "is_in_cooldown() thread hung"
        assert errors == []
        # POSITIVE CONTROL: the run actually did work, so the absence of
        # hangs/errors above is not the absence of a scenario.
        assert cb._cooldowns, "the hammer loop should have armed at least one ticker"


class TestFlashCrashCBNonFiniteInputs:
    """Round-2 review found the round-1 finiteness fix was itself a FAIL-OPEN:
    the guard sat below the history append, so one non-finite observation was
    recorded (and persisted), and then blinded the breaker on that ticker for
    a whole window_seconds -- silently, with no log line. A real 0.60 -> 0.05
    collapse armed nothing. These tests pin the ORDERING, not just the guard."""

    def _cb(self):
        from circuit_breaker import FlashCrashCB

        return FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_price_is_rejected_before_it_is_recorded(self, bad):
        """The ordering is the whole point: asserting only that check() returns
        False would pass with the guard in the old (broken) position too."""
        cb = self._cb()
        cb.check("POISON", 0.60)
        assert cb.check("POISON", bad) is False

        # THE ACTUAL CLAIM: it never entered the history at all.
        assert [p for _ts, p in cb._history["POISON"]] == [0.60]

        # ...so the breaker still works on the very next tick. Under the old
        # ordering this armed nothing for a full window.
        assert cb.check("POISON", 0.05) is True
        assert cb.is_in_cooldown("POISON") is True

    def test_inf_passes_both_live_feed_gates(self):
        """Pins the premise behind the guard above. An earlier comment claimed
        non-finite prices were unreachable from the live feeds; that reasoned
        only about NaN. Both feeds gate on `mid > 0`, and inf > 0 is True."""
        assert (float("inf") > 0) is True
        assert bool(float("inf")) is True
        # ...whereas these two really are filtered by the same gates.
        assert (float("nan") > 0) is False
        assert (float("-inf") > 0) is False

    def test_non_finite_oldest_price_does_not_arm(self):
        """The half the round-1 test missed: a NaN arriving as OLDEST_PRICE,
        which the production comment itself calls the realistic seed (a
        corrupted .flash_crash_history.json read back by _load_history's bare
        float()). Seeded directly, because check() now refuses to create it."""
        cb = self._cb()
        now = time.time()
        cb._history["OLDNAN"] = [(now - 10, float("nan")), (now - 5, 0.60)]
        assert cb.check("OLDNAN", 0.05) is False
        assert cb.is_in_cooldown("OLDNAN") is False

        # POSITIVE CONTROL: the identical shape with a finite oldest price
        # DOES arm, so the refusal above is the guard and not the fixture.
        cb._history["OLDOK"] = [(now - 10, 0.60), (now - 5, 0.60)]
        assert cb.check("OLDOK", 0.05) is True

    def test_non_finite_history_entry_on_disk_is_discarded_on_load(
        self, tmp_path, monkeypatch
    ):
        import json

        import circuit_breaker
        from circuit_breaker import FlashCrashCB

        path = tmp_path / ".flash_crash_history.json"
        now = time.time()
        path.write_text(
            json.dumps({"DISK": [[now - 10, float("nan")], [now - 5, 0.60]]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(circuit_breaker, "_FLASH_CRASH_HISTORY_PATH", path)

        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert [p for _ts, p in cb._history.get("DISK", [])] == [0.60]

    def test_infinite_cooldown_on_disk_is_discarded_on_load(
        self, tmp_path, monkeypatch
    ):
        """A bare Infinity token satisfies `exp > now` forever, so one corrupt
        entry blocked a ticker permanently across every restart -- and the save
        path re-persisted it, since inf > now is True there too."""
        import json

        import circuit_breaker
        from circuit_breaker import FlashCrashCB

        path = tmp_path / ".flash_crash_cooldowns.json"
        path.write_text(
            json.dumps({"STUCK": float("inf"), "REAL": time.time() + 600}),
            encoding="utf-8",
        )
        monkeypatch.setattr(circuit_breaker, "_FLASH_CRASH_COOLDOWN_PATH", path)

        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        assert cb.is_in_cooldown("STUCK") is False
        # POSITIVE CONTROL: a legitimate deadline in the same file survives.
        assert cb.is_in_cooldown("REAL") is True

    def test_non_finite_cooldown_is_not_persisted(self, tmp_path, monkeypatch):
        import json

        import circuit_breaker
        from circuit_breaker import FlashCrashCB

        path = tmp_path / ".flash_crash_cooldowns.json"
        monkeypatch.setattr(circuit_breaker, "_FLASH_CRASH_COOLDOWN_PATH", path)

        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=300)
        cb._cooldowns["STUCK"] = float("inf")
        cb._cooldowns["REAL"] = time.time() + 600
        cb._save_cooldowns()

        written = json.loads(path.read_text(encoding="utf-8"))
        assert "STUCK" not in written
        assert "REAL" in written


class TestFlashCrashCBConstructorValidation:
    """The round-1 validation rejected the one value that cannot hurt (a
    negative floor is a no-op) and accepted all three that can. inf in
    particular is a total silent fail-open: `move < inf` is always True, so
    the breaker never trips at all."""

    @pytest.mark.parametrize("bad", [0.0, -0.01, float("nan"), float("inf")])
    def test_dangerous_min_abs_move_values_are_refused(self, bad):
        from circuit_breaker import FlashCrashCB

        with pytest.raises(ValueError, match="min_abs_move"):
            FlashCrashCB(min_abs_move=bad)

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_dangerous_threshold_pct_values_are_refused(self, bad):
        from circuit_breaker import FlashCrashCB

        with pytest.raises(ValueError, match="threshold_pct"):
            FlashCrashCB(threshold_pct=bad)

    def test_the_production_defaults_construct(self):
        """POSITIVE CONTROL: the validation must not be so tight that the
        singleton's own defaults raise."""
        from circuit_breaker import FlashCrashCB

        cb = FlashCrashCB()
        assert cb.min_abs_move == 0.05
        assert cb.threshold_pct == 0.20


class TestFlashCrashCBArmedMoveLifecycle:
    def _cb(self, cooldown_seconds=600):
        from circuit_breaker import FlashCrashCB

        return FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=cooldown_seconds,
            min_abs_move=0.05,
        )

    def test_expired_entries_are_pruned_when_another_ticker_arms(self):
        """_armed_move is bounded by ACTIVE cooldowns, not by every ticker that
        has ever crashed. Pruned on the arming path only, which is rare."""
        cb = self._cb(cooldown_seconds=1)
        cb.check("GONE", 0.60)
        assert cb.check("GONE", 0.30) is True
        assert "GONE" in cb._armed_move

        time.sleep(1.1)  # only ever oversleeps, so this cannot flake short
        assert cb.is_in_cooldown("GONE") is False

        cb.check("FRESH", 0.60)
        assert cb.check("FRESH", 0.30) is True

        assert "GONE" not in cb._armed_move  # the expired entry was dropped
        assert "FRESH" in cb._armed_move  # ...and the live one was not

    def test_no_spurious_escalation_after_a_restart(
        self, tmp_path, monkeypatch, caplog
    ):
        """A second process restores _cooldowns from disk but NOT _armed_move
        (it is deliberately unpersisted). The first re-arm must fall through to
        DEBUG rather than warning against a baseline of 0.0 -- otherwise the
        cross-process case, which is the bot's normal one-shot cron case,
        re-emits exactly the spam this change removed."""
        import logging

        import circuit_breaker
        from circuit_breaker import FlashCrashCB

        path = tmp_path / ".flash_crash_cooldowns.json"
        monkeypatch.setattr(circuit_breaker, "_FLASH_CRASH_COOLDOWN_PATH", path)

        first = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )
        first.check("RESTART", 0.60)
        assert first.check("RESTART", 0.48) is True

        second = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
            min_abs_move=0.05,
        )
        assert second.is_in_cooldown("RESTART") is True
        assert second._armed_move == {}  # the premise: no baseline survived

        second.check("RESTART", 0.60)
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            assert second.check("RESTART", 0.05) is False

        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        # POSITIVE CONTROL: the re-arm branch really did run.
        assert [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "still crashing" in r.getMessage()
        ]

    def test_escalation_factor_magnitude_is_pinned_from_both_sides(self, caplog):
        """Pins _ESCALATION_FACTOR's magnitude, which nothing else does: a
        review mutation setting it to 1.0 was caught only from below.

        Deliberately NOT a test of the exact 1.5x boundary. That boundary is
        not representable: arming on 0.60 -> 0.45 gives 0.14999999999999997,
        so 1.5x is 0.22499999999999995, and a move a human would call "exactly
        1.5x" lands on whichever side float noise puts it. Since the
        comparison is log-only and has no behavioural consequence, the
        boundary is left fuzzy on purpose and 1.4x / 1.6x are tested instead.

        Note the arming move must clear BOTH bounds -- 0.60 -> 0.50 is 10c but
        only 16.7%, so it never arms at all."""
        import logging

        cb = self._cb()
        cb.check("FACTOR", 0.60)
        assert cb.check("FACTOR", 0.45) is True  # arms on 15c / -25%
        assert cb._armed_move["FACTOR"] == pytest.approx(0.15)

        # 1.4x the arming move: below the factor, must stay quiet.
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            assert cb.check("FACTOR", 0.39) is False  # 21c
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        assert [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and "still crashing" in r.getMessage()
        ]

        # 1.6x: above the factor, must warn. Same ticker, same arming
        # baseline (still 15c, since the quiet branch does not re-baseline),
        # so this isolates the factor rather than the scenario.
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="circuit_breaker"):
            assert cb.check("FACTOR", 0.36) is False  # 24c
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings and "STILL FALLING" in warnings[0].getMessage()
