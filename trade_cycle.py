"""trade_cycle.py — shared headless trade-cycle engine.

Extracted from cron.py's ``_cmd_cron_body`` and main.py's ``_analyze_once``/
``cmd_watch`` (backlog.txt "THE ONLY LIVE-ORDER PATH IS THE INTERACTIVE WATCH
CLI -- NO HEADLESS TRADE-CYCLE ENGINE"). Owns the canonical recover-pending ->
settle -> scan -> analyze -> decide/place sequence and the gate set that
determines whether/what gets traded, applied identically to both callers so
neither pipeline can end up more permissive than the other.

Out of scope, deliberately, per the entry's resolution: position protection
was a separate design problem from pipeline-hardening parity and was filed
as its own follow-up backlog entry, resolved 2026-08-03 (see backlog.txt's
[POSITION PROTECTION IS STILL TWO SEPARATE MECHANISMS...] entry) -- cron and
watch now run the SAME paper-position checks (paper.check_paper_position_exits
for stop-loss/breakeven, order_executor._check_early_exits for model-flip),
called from cron.py's wrapper and main.py's cmd_watch loop respectively
rather than from this engine. Live-order poll-fills/reprice remains
watch-only -- that's a genuinely different responsibility (watch manages
orders it just placed this cycle) than the now-unified paper checks, not
duplicated strategy. cron-only periodic housekeeping beyond the
scan-relevant ``prewarm`` flag
(weekly retrains, cloud backup, drift detection, etc.), and all interactive
display/UI. Those stay in cron.py's wrapper and main.py's cmd_watch loop.

This module does its own decision-relevant logging (``_log.*``) but issues no
interactive ``print()`` of its own except inside ``_run_batch_prewarm``,
which is cron-only (watch always passes ``prewarm=False``) and is a direct
relocation of cron.py's existing prewarm console output, not new shared
behavior.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

# Real (not TYPE_CHECKING-only) import: kill-switch checks below read
# cron.KILL_SWITCH_PATH via attribute access rather than importing the name
# directly from paths.py, because tests patch cron.KILL_SWITCH_PATH (see
# cron.py's own module docstring: "Tests that need to redirect paths should
# patch cron.LOCK_PATH (not main.LOCK_PATH)") -- a `from paths import
# KILL_SWITCH_PATH` here would copy the reference at this module's import
# time and never see that patch. No circular-import risk: cron.py only
# imports this module lazily, inside _cmd_cron_body's function body, never
# at cron.py's own module top level.
import cron
from utils import (
    CITY_MIN_PROB_EDGE,
    MAX_MARKET_DIVERGENCE_RATIO,
    MED_EDGE,
    MIN_MARKET_PROB_TO_BET_WITH,
    MIN_PROB_EDGE,
    STRONG_EDGE,
    get_paper_min_edge,
    is_trading_paused,
    min_prob_edge_for_days_out,
)

if TYPE_CHECKING:
    from cron import CronContext
    from kalshi_client import KalshiClient

# Same logger name cron.py uses -- existing tests that capture
# logging.getLogger("main") must keep seeing this module's log output too.
_log = logging.getLogger("main")

TIER_STRONG = "strong"
TIER_MED = "med"


@dataclass
class TradeCycleResult:
    """Everything a caller (cron.py's wrapper, main.py's watch loop) needs to
    reconstruct its own console/UI presentation and downstream bookkeeping.
    """

    halted_reason: str | None
    consistency_skip: bool
    markets: list[dict]
    scanned: int  # post-dedup/stale market count
    dedup_removed: int
    stale_skipped: int
    all_results: list[tuple[dict, dict]]  # every (enriched, analysis) analyzed
    no_quote_opps: list[tuple[dict, dict]]  # illiquid, all threshold outcomes
    liquid_opps: list[tuple[dict, dict]]  # liquid, all threshold outcomes
    strong_opps: list[tuple[dict, dict]]  # tier=strong, eligible for placement
    med_opps: list[tuple[dict, dict]]  # tier=med, eligible for placement
    signals_cache_entries: list[dict]
    gate_counts: dict[str, int]
    dbg: dict[str, int]
    pre_settled: list[dict]
    strong_cap: float | None
    placed_strong: int
    placed_med: int
    synced_count: int
    paper_settled: list[dict]
    shadow_logged_count: int


def run_trade_cycle(
    ctx: CronContext,
    client: KalshiClient | None,
    *,
    min_edge: float | None = None,
    live: bool = False,
    live_config: dict | None = None,
    prewarm: bool = False,
    effective_strong_edge: float | None = None,
    require_liquid_for_placement: bool = False,
    external_halted_reason: str | None = None,
    on_markets_fetched: Callable[[list[dict]], None] | None = None,
) -> TradeCycleResult | None:
    """Run one full recover-pending -> settle -> scan -> analyze -> decide/
    place cycle.

    Returns ``None`` only on a hard abort (kill switch active, either at
    cycle start or re-checked immediately before placement) -- matching
    ``_cmd_cron_body``'s historical ``bool(...)`` return contract. Otherwise
    returns a ``TradeCycleResult``, which may itself carry a non-``None``
    ``halted_reason`` for a *soft* halt (manual override / accuracy halt /
    graduation gate not met) -- scan/analyze/settle still ran in that case,
    only placement was skipped.

    ``min_edge``: the CLI ``--edge`` floor override, applied exactly as
    cron.py always applied it -- a floor over ``get_paper_min_edge()``, never
    a ceiling. ``None`` means no explicit override.

    ``effective_strong_edge``: caller-supplied STRONG/MED tier boundary
    (cron.py computes this once per cycle from Brier-drift detection and
    passes it in; watch has no drift-detection mechanism and omits it,
    falling back to the plain ``STRONG_EDGE`` constant).

    ``require_liquid_for_placement``: cron's paper trades don't need real
    market liquidity to fill, so cron passes ``False`` (default) and
    strong_opps/med_opps include every threshold-passing candidate
    regardless of liquidity -- matching cron's pre-extraction behavior
    exactly. Watch's orders can be live, so it passes ``True`` to
    additionally require ``weather_markets.is_liquid()`` before a candidate
    is eligible for strong_opps/med_opps -- matching watch's pre-extraction
    liquid_opps-only auto-trade behavior.

    ``external_halted_reason``: a soft-halt reason the caller already
    determined by its own means before calling this function (cron.py's
    anomaly-detection check and its black-swan-check exception handler both
    set one, entirely outside this engine's own gate list). ORs into the
    same ``halted_reason`` this function accumulates internally from
    ``check_manual_override``/``check_accuracy_halt``/``check_graduation_gate``
    -- mirrors cron.py's pre-extraction ``_cron_halted_reason = _cron_halted_reason
    or (...)`` accumulation exactly, so an externally-detected halt still
    blocks placement here, not just in the caller's own (now-removed) copy
    of the placement gate.

    ``on_markets_fetched``: optional callback invoked with the raw (pre-
    dedup) market list immediately after the fetch, before prewarm/analyze/
    placement run. Both callers use this to subscribe+start their
    WebSocket connection at the same point in the cycle it ran at pre-
    extraction (right after the fetch, before the multi-minute analysis
    pool) -- this engine owns the fetch now, so without this hook a caller
    has no ticker list to subscribe with until after the whole cycle
    (including placement) has already completed, leaving order_executor's
    flash-crash check running on a cold WS cache for the entire cycle. A
    raised exception from this callback propagates like any other
    caller-supplied error -- callers are expected to guard their own WS
    setup internally, matching their pre-extraction try/except shape.
    """
    if cron.KILL_SWITCH_PATH.exists():
        _log.critical(
            "run_trade_cycle: KILL SWITCH ACTIVE — halting immediately. "
            "Remove data/.kill_switch to resume."
        )
        return None

    halted_reason: str | None = external_halted_reason
    if ctx.check_manual_override():
        _log.warning(
            "run_trade_cycle: manual override active — skipping trade placement this run"
        )
        halted_reason = halted_reason or "manual override active"

    _acc_halted, _acc_reason = ctx.check_accuracy_halt()
    if _acc_halted:
        _log.warning(
            "run_trade_cycle: ACCURACY HALT ACTIVE: %s — skipping trade placement "
            "this cycle (settlement/stop-losses still run so the halt can clear)",
            _acc_reason,
        )
        halted_reason = halted_reason or _acc_reason

    try:
        ctx.check_graduation_gate()
    except RuntimeError as _gate_err:
        _log.error(
            "run_trade_cycle: %s — skipping trade placement this cycle", _gate_err
        )
        halted_reason = halted_reason or str(_gate_err)

    # Recover-pending: reconcile any live order left 'pending' by a crash.
    if client is not None:
        try:
            from order_executor import _recover_pending_orders

            _recover_pending_orders(client)
        except Exception as exc:
            _log.warning("run_trade_cycle: _recover_pending_orders failed: %s", exc)

    # Settle (pre-scan) -- before scanning so same-day slot counts reflect
    # current open risk, not yesterday's expired-but-not-yet-settled positions.
    pre_settled: list[dict] = []
    try:
        from paper import auto_settle_paper_trades

        pre_settled = auto_settle_paper_trades(client) or []
    except Exception as exc:
        _log.warning("run_trade_cycle: pre-scan settlement failed: %s", exc)

    # Scan. Wrapped in one broad try/except matching cron.py's pre-extraction
    # "scan loop crashed" catch-all around this entire section (fetch through
    # dedup/market-implied precompute) -- a transient fetch/prewarm failure
    # must degrade to an empty market set, not propagate out of this function
    # and skip settlement/sync_outcomes/shadow-logging/housekeeping for the
    # whole cycle the way an unguarded exception here would.
    markets: list[dict] = []
    deduped_markets: list[dict] = []
    dedup_removed = 0
    stale_skipped = 0
    market_implied_by_event: dict = {}
    consistency_skip = False
    try:
        markets = ctx.get_weather_markets(client)

        # Subscribe/start the caller's WebSocket now, at the same point in
        # the cycle it ran at pre-extraction (right after the fetch, before
        # prewarm/analysis) -- see on_markets_fetched's docstring above.
        if on_markets_fetched is not None:
            on_markets_fetched(markets)

        try:
            from consistency import find_violations

            violations = find_violations(markets)
            if violations:
                _log.warning(
                    "run_trade_cycle: %d consistency violation(s) detected: %s",
                    len(violations),
                    [v.description for v in violations[:5]],
                )
                if len(violations) > 5:
                    consistency_skip = True
                    _log.error(
                        "run_trade_cycle: %d violations exceed threshold (5) — "
                        "skipping auto-trading this cycle",
                        len(violations),
                    )
        except Exception as exc:
            _log.warning(
                "run_trade_cycle: consistency check raised an exception — "
                "skipping auto-trading this cycle: %s",
                exc,
            )
            consistency_skip = True

        if prewarm:
            _run_batch_prewarm(ctx, markets)

        from weather_markets import is_stale as _is_stale_market

        seen_tickers: set[str] = set()
        for m in markets:
            ticker = m.get("ticker", "")
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            # Zero volume/open-interest AND closing within 60 minutes → edge
            # calculations on this market are meaningless (see is_stale's
            # docstring) — skip before spending an enrich+analyze cycle on it.
            if _is_stale_market(m):
                stale_skipped += 1
                continue
            deduped_markets.append(m)
        dedup_removed = len(markets) - stale_skipped - len(deduped_markets)
        if dedup_removed:
            _log.debug(
                "run_trade_cycle: deduped %d duplicate ticker(s) before analysis",
                dedup_removed,
            )
        if stale_skipped:
            _log.debug(
                "run_trade_cycle: skipped %d stale market(s) (no volume, closing within 60min)",
                stale_skipped,
            )

        from weather_markets import compute_market_implied_distributions

        market_implied_by_event = compute_market_implied_distributions(deduped_markets)
    except Exception as _scan_setup_exc:
        _log.error(
            "run_trade_cycle: scan setup (fetch/prewarm/dedup) crashed — "
            "continuing with an empty market set so settlement/sync_outcomes/"
            "housekeeping still run this cycle: %s",
            _scan_setup_exc,
            exc_info=True,
        )

    from weather_markets import (
        get_gate_counts,
        is_liquid,
        reset_gate_counts,
        resolve_market_implied_for_analysis,
    )

    reset_gate_counts()

    eff_strong_edge = (
        effective_strong_edge if effective_strong_edge is not None else STRONG_EDGE
    )

    all_results: list[tuple[dict, dict]] = []
    no_quote_opps: list[tuple[dict, dict]] = []
    liquid_opps: list[tuple[dict, dict]] = []
    strong_opps: list[tuple[dict, dict]] = []
    med_opps: list[tuple[dict, dict]] = []
    signals_cache_entries: list[dict] = []
    dbg: dict[str, int] = {
        "no_analysis": 0,
        "analysis_errors": 0,  # a future raised, distinct from analyze_trade returning falsy
        "same_day": 0,  # informational only — same-day markets are not filtered
        "mkt_prob": 0,
        "divergence": 0,
        "net_edge": 0,
        "prob_edge": 0,
        "passed": 0,
    }

    def _enrich_and_analyze(m: dict) -> tuple[dict, dict, dict | None]:
        enriched = ctx.enrich_with_forecast(m)
        return m, enriched, ctx.analyze_trade(enriched)

    # Per-market analysis timeout: 6 min total for all markets, 8 parallel
    # workers -- matches cron.py's pre-extraction pool sizing exactly (cache-
    # warm analysis is CPU-bound; 8 workers avoids racing on network
    # resources / Windows SSL hangs at higher concurrency). Manual pool (no
    # `with`) so shutdown(wait=False) can be used in the finally block --
    # `with ThreadPoolExecutor` calls shutdown(wait=True) on __exit__, which
    # blocks forever on a hung Windows SSL socket.
    _ANALYSIS_TIMEOUT_S = 360

    try:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import as_completed as _as_completed

        _pool = ThreadPoolExecutor(max_workers=8)
        try:
            _futures = {
                _pool.submit(_enrich_and_analyze, m): m for m in deduped_markets
            }
            try:
                for fut in _as_completed(_futures, timeout=_ANALYSIS_TIMEOUT_S):
                    if cron.KILL_SWITCH_PATH.exists():
                        _log.warning(
                            "run_trade_cycle: kill switch activated mid-scan — stopping analysis"
                        )
                        break
                    try:
                        m, enriched, analysis = fut.result()
                    except Exception as exc:
                        _failed_mkt = _futures.get(fut, {})
                        _log.warning(
                            "run_trade_cycle: analysis failed for %s: %s — skipping ticker",
                            _failed_mkt.get("ticker", "?")
                            if isinstance(_failed_mkt, dict)
                            else "?",
                            exc,
                        )
                        dbg["analysis_errors"] += 1
                        continue
                    if not analysis:
                        dbg["no_analysis"] += 1
                        continue

                    analysis["market_implied"] = resolve_market_implied_for_analysis(
                        market_implied_by_event,
                        enriched.get("_city"),
                        enriched.get("_date"),
                        m.get("ticker", ""),
                    )
                    net_edge = analysis.get("net_edge", analysis.get("edge", 0.0))
                    adjusted_edge = analysis.get("adjusted_edge", net_edge)

                    from weather_markets import _liquidity_edge_scale as _liq_scale

                    liq_edge_scale = _liq_scale(
                        m.get("volume_fp") or m.get("volume") or 0,
                        m.get("open_interest_fp") or m.get("open_interest") or 0,
                    )
                    analysis["liquidity_edge_scale"] = liq_edge_scale
                    analysis["gated_edge"] = adjusted_edge / liq_edge_scale

                    # Recorded here, before the mkt_prob/divergence gates
                    # below, so every market that reached a real analysis
                    # (not just the threshold-eligible ones) lands in the
                    # analysis_attempts audit trail cron.py rebuilds from
                    # this list -- matching cron.py's pre-extraction
                    # _analysis_batch collection point exactly. `analysis`
                    # is the same dict object referenced here and mutated
                    # further below (tier/_passes_threshold/_is_liquid), so
                    # this entry reflects the fully-tagged analysis by the
                    # time the caller reads it.
                    all_results.append((enriched, analysis))

                    # Same-day markets (days_out == 0) are re-enabled.
                    # analyze_trade uses METAR-locked probabilities for
                    # same-day above/below markets, which gives tight CI
                    # width. Between markets at days_out == 0 skip the obs
                    # override in analyze_trade so they fall back to
                    # ensemble and are covered by the between_floor gate.
                    if int(analysis.get("days_out", 1)) == 0:
                        dbg["same_day"] += 1
                        # fall through — do not skip

                    side = analysis.get("recommended_side", "yes")
                    our_p = analysis.get("forecast_prob", 0.5)
                    mkt_p = analysis.get("market_prob", 0.5)
                    if side == "yes":
                        mkt_dir, our_dir = mkt_p, our_p
                    else:
                        mkt_dir, our_dir = 1.0 - mkt_p, 1.0 - our_p
                    if mkt_dir < MIN_MARKET_PROB_TO_BET_WITH:
                        dbg["mkt_prob"] += 1
                        continue
                    if mkt_dir > 0 and our_dir / mkt_dir > MAX_MARKET_DIVERGENCE_RATIO:
                        dbg["divergence"] += 1
                        continue

                    # Track whether this candidate clears both edge gates.
                    # Below-threshold candidates are still recorded
                    # (signals_cache / display) so the dashboard/table can
                    # show them; only candidates that pass are eligible for
                    # auto-trading.
                    passes_threshold = True
                    effective_min_edge = (
                        get_paper_min_edge()
                        if min_edge is None
                        else max(min_edge, get_paper_min_edge())
                    )
                    if abs(adjusted_edge) < effective_min_edge:
                        dbg["net_edge"] += 1
                        passes_threshold = False

                    prob_edge = abs(
                        analysis.get("forecast_prob", 0.5)
                        - analysis.get("market_prob", 0.5)
                    )
                    city_key = enriched.get("_city", "")
                    days_out_val = int(analysis.get("days_out", 1))
                    city_min = CITY_MIN_PROB_EDGE.get(city_key, MIN_PROB_EDGE)
                    days_min = min_prob_edge_for_days_out(days_out_val)
                    min_prob_edge_gate = max(city_min, days_min)
                    if passes_threshold and prob_edge < min_prob_edge_gate:
                        dbg["prob_edge"] += 1
                        passes_threshold = False

                    if passes_threshold:
                        dbg["passed"] += 1

                    analysis["_passes_threshold"] = passes_threshold
                    # Also set under the pre-extraction field name main.py's
                    # other consumers already read with a fail-open
                    # `a.get("_passes_edge", True)` default (e.g. the
                    # portfolio-correlation warning, the arb-exposure
                    # display) -- a caller that filters on the old name
                    # against this engine's output must see the real
                    # threshold outcome, not silently treat every candidate
                    # as passing because the key was simply absent.
                    analysis["_passes_edge"] = passes_threshold
                    analysis["tier"] = None
                    if passes_threshold:
                        if abs(adjusted_edge) >= eff_strong_edge:
                            analysis["tier"] = TIER_STRONG
                        elif abs(adjusted_edge) >= MED_EDGE:
                            analysis["tier"] = TIER_MED

                    liquid = is_liquid(m)
                    analysis["_is_liquid"] = liquid
                    pair = (enriched, analysis)
                    (liquid_opps if liquid else no_quote_opps).append(pair)

                    signal = analysis.get(
                        "net_signal", analysis.get("signal", "")
                    ).strip()
                    time_risk = analysis.get("time_risk", "—")
                    stars = (
                        "★★★"
                        if passes_threshold
                        and "STRONG" in signal
                        and time_risk == "LOW"
                        else "★★"
                        if passes_threshold and "STRONG" in signal
                        else "★"
                        if passes_threshold
                        else ""
                    )
                    from weather_markets import parse_market_price as _pmp

                    tdate = enriched.get("_date")
                    prices = _pmp(m)
                    signals_cache_entries.append(
                        {
                            # Per-market completion time (not one timestamp
                            # for the whole batch) -- cron.py's cron.log
                            # JSONL write reads this per entry, matching the
                            # pre-extraction per-market write's own
                            # per-completion timestamp instead of stamping
                            # every line with a single post-scan time.
                            "ts": datetime.now(UTC).isoformat(),
                            "ticker": m.get("ticker", ""),
                            "city": enriched.get("_city", "—"),
                            "target_date": (
                                tdate
                                if isinstance(tdate, str)
                                else (tdate.isoformat() if tdate else None)
                            ),
                            "side": analysis.get("recommended_side", "—").upper(),
                            "signal": signal,
                            "stars": stars,
                            "edge_pct": round(net_edge * 100, 1),
                            "net_edge": round(net_edge, 6),
                            "yes_bid": prices["yes_bid"],
                            "yes_ask": prices["yes_ask"],
                            "forecast_prob": round(
                                analysis.get("forecast_prob", 0) * 100, 1
                            ),
                            "market_prob": round(
                                analysis.get("market_prob", 0) * 100, 1
                            ),
                            "time_risk": time_risk,
                            "model_consensus": analysis.get("model_consensus", True),
                            "kelly_dollars": 0.0,  # balance unknown here; filled by web
                            "already_held": False,
                            "near_threshold": analysis.get("near_threshold", False),
                            "is_hedge": analysis.get("_is_hedge", False),
                            "passes_threshold": passes_threshold,
                            "days_out": int(analysis.get("days_out", 1)),
                            "model_disagreement_f": analysis.get(
                                "model_disagreement_f"
                            ),
                            "model_disagreement_flag": analysis.get(
                                "model_disagreement_flag", False
                            ),
                            "ensemble_prob": round(
                                analysis.get("ensemble_prob", 0) * 100, 1
                            )
                            if analysis.get("ensemble_prob") is not None
                            else None,
                            "nws_prob": round(analysis.get("nws_prob", 0) * 100, 1)
                            if analysis.get("nws_prob") is not None
                            else None,
                            "clim_prob": round(analysis.get("clim_prob", 0) * 100, 1)
                            if analysis.get("clim_prob") is not None
                            else None,
                            "forecast_temp_f": analysis.get("forecast_temp"),
                        }
                    )

                    if analysis["tier"] and (
                        not require_liquid_for_placement or liquid
                    ):
                        if analysis["tier"] == TIER_STRONG:
                            strong_opps.append(pair)
                        else:
                            med_opps.append(pair)
            except TimeoutError:
                _log.error(
                    "run_trade_cycle: analysis scan timed out after %ds — %d markets processed",
                    _ANALYSIS_TIMEOUT_S,
                    dbg["passed"]
                    + dbg["no_analysis"]
                    + dbg["mkt_prob"]
                    + dbg["divergence"]
                    + dbg["net_edge"]
                    + dbg["prob_edge"],
                )
        finally:
            _pool.shutdown(wait=False)  # never block on a stuck SSL thread
    except TimeoutError:
        _log.error(
            "run_trade_cycle: analysis scan timed out after %ds — %d markets processed so far",
            _ANALYSIS_TIMEOUT_S,
            dbg["passed"]
            + dbg["no_analysis"]
            + dbg["mkt_prob"]
            + dbg["divergence"]
            + dbg["net_edge"]
            + dbg["prob_edge"],
        )
    except Exception as _e:
        _log.error("run_trade_cycle: scan loop crashed: %s", _e, exc_info=True)

    try:
        gate_counts = get_gate_counts()
    except Exception as exc:
        _log.warning("run_trade_cycle: get_gate_counts failed: %s", exc)
        gate_counts = {}

    trading_paused = is_trading_paused()
    strong_cap: float | None = None
    placed_strong = 0
    placed_med = 0
    shadow_logged_count = 0

    if trading_paused or halted_reason:
        if halted_reason:
            _log.warning(
                "run_trade_cycle: trade placement skipped this cycle — %s "
                "(settlement/stop-losses above still ran)",
                halted_reason,
            )
        else:
            _log.warning(
                "run_trade_cycle: TRADING_PAUSED is set — scan/data collection ran, "
                "trade placement skipped"
            )
        shadow_logged_count = ctx.log_shadow_predictions(strong_opps + med_opps) or 0
    elif consistency_skip:
        _log.warning(
            "run_trade_cycle: auto-trading skipped this cycle due to consistency violations"
        )
    else:

        def _kelly_sort_key(opp: tuple) -> float:
            a = opp[1]
            return abs(
                a.get(
                    "ci_adjusted_kelly", a.get("kelly_fraction", a.get("net_edge", 0))
                )
                or 0
            )

        strong_opps.sort(key=_kelly_sort_key, reverse=True)
        med_opps.sort(key=_kelly_sort_key, reverse=True)

        # Final kill switch check — a mid-scan activation breaks the analysis
        # loop but without this check placement would still proceed for
        # already-found signals. Deliberately only checked in this branch
        # (not hoisted above the halted/paused/consistency-skip triage) --
        # matches cron.py's pre-extraction structure exactly. Hoisting it
        # would abort settle/sync_outcomes/shadow-logging too whenever a
        # halt and the kill switch are both active in the same cycle,
        # breaking the invariant (see this function's docstring and the
        # halted_reason branch above) that a soft halt must never stop
        # settlement from running.
        if cron.KILL_SWITCH_PATH.exists():
            _log.warning(
                "run_trade_cycle: kill switch activated before placement — "
                "skipping %d signal(s)",
                len(strong_opps) + len(med_opps),
            )
            return None

        if strong_opps:
            from paper import _dynamic_kelly_cap

            strong_cap = _dynamic_kelly_cap()
            placed_strong = (
                ctx.auto_place_trades(
                    strong_opps,
                    client=client,
                    cap=strong_cap,
                    live=live,
                    live_config=live_config,
                )
                or 0
            )
        if med_opps:
            placed_med = (
                ctx.auto_place_trades(
                    med_opps,
                    client=client,
                    cap=20.0,
                    live=live,
                    live_config=live_config,
                )
                or 0
            )

    synced_count = 0
    try:
        synced_count = ctx.sync_outcomes(client) or 0
    except Exception as exc:
        _log.warning("run_trade_cycle: sync_outcomes failed: %s", exc)

    paper_settled: list[dict] = []
    try:
        from paper import auto_settle_paper_trades as _post_settle

        paper_settled = _post_settle(client) or []
    except Exception as exc:
        _log.warning(
            "run_trade_cycle: auto_settle_paper_trades (post-place) failed: %s", exc
        )

    return TradeCycleResult(
        halted_reason=halted_reason,
        consistency_skip=consistency_skip,
        markets=markets,
        scanned=len(deduped_markets),
        dedup_removed=dedup_removed,
        stale_skipped=stale_skipped,
        all_results=all_results,
        no_quote_opps=no_quote_opps,
        liquid_opps=liquid_opps,
        strong_opps=strong_opps,
        med_opps=med_opps,
        signals_cache_entries=signals_cache_entries,
        gate_counts=gate_counts,
        dbg=dbg,
        pre_settled=pre_settled,
        strong_cap=strong_cap,
        placed_strong=placed_strong,
        placed_med=placed_med,
        synced_count=synced_count,
        paper_settled=paper_settled,
        shadow_logged_count=shadow_logged_count,
    )


def _run_batch_prewarm(ctx: CronContext, markets: list[dict]) -> None:
    """Pre-warm forecast/model caches for all unique city/date pairs so the
    parallel analyze pass hits cache instead of making redundant network
    requests. cron-only (watch always passes ``prewarm=False``) -- a direct
    relocation of cron.py's pre-extraction prewarm block, unchanged.
    """
    from weather_markets import parse_city_date as _parse_city_date

    city_dates: set[tuple[str, str]] = set()
    for m in markets:
        city, td = _parse_city_date(m)
        if city and td:
            city_dates.add((city, str(td)))
    if city_dates:
        _run_batch_prewarm_for_pairs(ctx, city_dates)

    # Suppress probing on any circuit that opened during prewarm -- must run
    # every call, not just when there were pairs to warm (an already-open
    # circuit still shouldn't stall the analysis pool on a probe timeout).
    # This used to sit at the same indent level as the "if city_dates"
    # prewarm block in cron.py, i.e. it always ran; an earlier draft of this
    # extraction nested it inside the "if city_dates" branch by mistake,
    # silently un-suppressing probing on any cycle with zero parseable
    # city/date pairs.
    from weather_markets import _ecmwf_om_cb, _ensemble_cb, _forecast_cb, _nbm_om_cb

    for cb in (_nbm_om_cb, _ensemble_cb, _forecast_cb, _ecmwf_om_cb):
        if cb.seconds_open() > 0:
            cb.suppress_probe()
            _log.warning(
                "run_trade_cycle: circuit '%s' open after prewarm — probing suppressed for this run",
                cb.name,
            )


def _run_batch_prewarm_for_pairs(
    ctx: CronContext, city_dates: set[tuple[str, str]]
) -> None:
    """The actual per-city-date-pair warming work, factored out of
    ``_run_batch_prewarm`` so the always-run circuit-breaker suppression
    above isn't nested inside the "only if there's something to warm" guard.
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import as_completed as _as_completed

    from colors import dim

    n_pairs = len(city_dates)
    print(
        dim(f"  [cron] pre-warming forecasts for {n_pairs} city/date pair(s)..."),
        flush=True,
    )

    # Step 1a: batch Open-Meteo forecast (3 HTTP calls cover all cities)
    from weather_markets import (
        batch_prewarm_ensemble,
        batch_prewarm_forecasts,
        flush_ensemble_disk_cache,
    )

    om_models = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]
    n_models = len(om_models)

    def _om_progress(current: int, total: int, model: str, ok: bool) -> None:
        tick = "OK" if ok else "FAIL"
        print(dim(f"  [OM batch] [{current}/{total}] {model:<20} {tick}"), flush=True)

    batch_written = batch_prewarm_forecasts(city_dates, progress_cb=_om_progress)
    print(
        dim(
            f"  [OM batch] {batch_written} cache entries written across {n_models} models"
        ),
        flush=True,
    )

    # Step 1b: batch ensemble prewarm.
    ens_models = [
        "icon_seamless",
        "gfs_seamless",
        "ecmwf_aifs025_ensemble",
        "gem_global",
        "ukmo_global_ensemble_20km",
    ]
    ens_vars = 2

    def _ens_progress(current: int, total: int, label: str, ok: bool) -> None:
        tick = "OK" if ok else "FAIL"
        print(dim(f"  [ENS batch] [{current}/{total}] {label:<26} {tick}"), flush=True)

    ens_written = batch_prewarm_ensemble(city_dates, progress_cb=_ens_progress)
    print(
        dim(
            f"  [ENS batch] {ens_written} cache entries written"
            f" across {len(ens_models)} models × {ens_vars} vars"
        ),
        flush=True,
    )
    # Flush to disk immediately so a canceled run still warms the next run.
    flush_ensemble_disk_cache()

    # Step 2: per-city sources that don't support batching.
    def _warm_one(city_date: tuple[str, str]) -> None:
        c, d = city_date
        dt = __import__("datetime").date.fromisoformat(d)
        for var in ("max", "min"):
            try:
                ctx.fetch_temperature_nbm(c, dt, var=var)
            except Exception:
                pass
            try:
                ctx.fetch_temperature_ecmwf(c, dt, var=var)
            except Exception:
                pass
        try:
            ctx.fetch_temperature_weatherapi(c, dt)
        except Exception:
            pass
        try:
            from nws import get_nws_daily_forecast as _nws_daily
            from weather_markets import CITY_COORDS as _city_coords

            coords = _city_coords.get(c)
            if coords:
                _nws_daily(c, coords)
        except Exception:
            pass
        try:
            from metar import fetch_metar as _fetch_metar
            from weather_markets import _metar_station_for_city as _metar_sta

            msta = _metar_sta(c)
            if msta:
                _fetch_metar(msta)
        except Exception:
            pass
        try:
            import mos as _mos_mod

            mos_sta = _mos_mod.get_mos_station(c)
            if mos_sta:
                _mos_mod.fetch_mos_best(mos_sta, target_date=dt)
        except Exception:
            pass
        try:
            from nws import get_live_observation as _nws_obs
            from weather_markets import CITY_COORDS as _city_coords2

            coords2 = _city_coords2.get(c)
            if coords2:
                _nws_obs(c, coords2)
        except Exception:
            pass
        try:
            from nws import get_live_precip_obs as _nws_precip_obs
            from weather_markets import CITY_COORDS as _city_coords3

            coords3 = _city_coords3.get(c)
            if coords3:
                _nws_precip_obs(c, coords3)
        except Exception:
            pass

    import threading as _threading

    warm_done = 0
    warm_lock = _threading.Lock()

    def _warm_one_tracked(city_date: tuple[str, str]) -> None:
        nonlocal warm_done
        _warm_one(city_date)
        with warm_lock:
            warm_done += 1
            cur = warm_done
            print(
                f"  [NBM/WA]  warming city sources... ({cur}/{n_pairs})",
                end="\r",
                flush=True,
            )

    warm_pool = ThreadPoolExecutor(max_workers=min(n_pairs, 8))
    try:
        warm_futures = [warm_pool.submit(_warm_one_tracked, cd) for cd in city_dates]
        try:
            for wf in _as_completed(warm_futures, timeout=200):
                try:
                    wf.result()
                except Exception as prewarm_exc:
                    _log.debug(
                        "run_trade_cycle: prewarm failed for a city: %s", prewarm_exc
                    )
        except TimeoutError:
            _log.warning(
                "run_trade_cycle: city source warm-up timed out after 200s — "
                "%d/%d pairs completed; analysis will skip MOS for uncached markets",
                warm_done,
                n_pairs,
            )
    finally:
        warm_pool.shutdown(wait=False)
    print(flush=True)  # newline after in-place counter
