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
    get_min_edge_for_confidence,
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
    markets: list[dict]  # raw, pre-dedup/stale-filter fetch result
    deduped_markets: list[dict]  # post-dedup/stale-filter -- what all_results
    # /liquid_opps/no_quote_opps/strong_opps/med_opps were actually built
    # from; a caller reconstructing the display table (position-protection
    # unification's sibling, backlog.txt's [CMD_WATCH RUNS THREE INDEPENDENT
    # get_weather_markets() SCANS...] entry) needs THIS list, not `markets`,
    # for parity with main.py's own _analyze_once (which dedupes before
    # everything downstream reads its `markets` variable).
    scanned: int  # post-dedup/stale market count == len(deduped_markets)
    dedup_removed: int
    stale_skipped: int
    effective_min_edge: float  # the real threshold _passes_threshold/_passes_edge
    # were computed against (max(min_edge, get_paper_min_edge())) -- a caller
    # sourcing its own display from this result's liquid_opps/no_quote_opps
    # needs this, not its own separately-passed `min_edge`, to print an
    # accurate "dimmed below >X%" threshold that matches what's actually dimmed.
    all_results: list[tuple[dict, dict]]  # every (enriched, analysis) analyzed
    ticker_city: dict[str, str]  # ticker -> city for every successfully-enriched
    # market, tagged before the not-analysis skip -- see its own comment at
    # the init site for why this must NOT be derived from all_results (narrower).
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
    strong_opps/med_opps include every threshold-passing candidate that also
    clears validate()'s deterministic edge gates (net_edge sign, raw-edge
    sign/magnitude, Kelly floor, confidence-tiered min_edge -- see the
    ``_clears_placement_gate`` computation below), regardless of liquidity --
    matching cron's
    pre-extraction behavior exactly. Watch's orders can be live, so it passes
    ``True`` to additionally require ``weather_markets.is_liquid()`` before a
    candidate is eligible for strong_opps/med_opps -- matching watch's
    pre-extraction liquid_opps-only auto-trade behavior.

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
            from consistency import find_violations, record_shadow_observations

            violations = find_violations(markets)
            # backlog.txt "RAIN ARBITRAGE-CHECK SHADOW SIGNAL HAS NO
            # GRADUATION DECISION YET": persist this cycle's shadow-only
            # rain-arb observations regardless of whether any violation
            # fired (cycles_observed needs every cycle as its denominator,
            # not just cycles with a hit) -- own try/except so a persistence
            # bug can never turn into a consistency_skip/trading-halt.
            # record_shadow_observations() already has its own internal
            # try/except (never raises); this outer one exists only in case
            # something ABOVE that (e.g. the import itself) fails. Logs at
            # WARNING, not DEBUG, matching this project's other once-per-
            # cycle observational-failure calls (e.g. check_series_drift) --
            # opus-review-caught: DEBUG would let a permanently-broken
            # recorder silently produce nothing for months.
            try:
                record_shadow_observations(violations)
            except Exception as _rec_exc:
                _log.warning(
                    "record_shadow_observations failed (non-fatal): %s", _rec_exc
                )
            if violations:
                # backlog.txt "RAIN MARKETS -- CONSISTENCY.PY'S ARBITRAGE
                # CHECK STILL BLANKET-EXCLUDES KXRAIN*M": rain's ladder
                # monotonicity has never been checked against live prices
                # before, so a burst of never-before-seen shadow violations
                # on rollout must not itself halt real (temperature) auto-
                # trading -- this circuit breaker exists to catch corrupted
                # market DATA, and mixing in an intentionally-unvalidated
                # new signal would defeat that purpose. getattr (not
                # v.is_shadow) so a test/caller stub without the attribute
                # still counts as a real violation, matching this file's
                # existing defensive-attribute-access convention.
                real_viol = [
                    v for v in violations if not getattr(v, "is_shadow", False)
                ]
                shadow_viol = [v for v in violations if getattr(v, "is_shadow", False)]
                # opus-review-caught: sampling the first 5 of an edge-sorted
                # list could be entirely shadow rain noise (rain's thin
                # monthly ladders can carry inflated edges), hiding the real
                # violations from the log at exactly the moment the count
                # line says something is wrong. Log each population's own
                # top samples separately instead of one mixed slice.
                _log.warning(
                    "run_trade_cycle: %d consistency violation(s) detected "
                    "(%d real, %d shadow) — real: %s | shadow: %s",
                    len(violations),
                    len(real_viol),
                    len(shadow_viol),
                    [v.description for v in real_viol[:5]],
                    [v.description for v in shadow_viol[:5]],
                )
                if len(real_viol) > 5:
                    consistency_skip = True
                    _log.error(
                        "run_trade_cycle: %d non-shadow violations exceed threshold (5) — "
                        "skipping auto-trading this cycle",
                        len(real_viol),
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
    # Computed once here (single snapshot for the whole cycle -- also read
    # directly by the scan loop below, not recomputed there) so
    # TradeCycleResult can expose it to callers -- see the dataclass field's
    # own docstring.
    effective_min_edge = (
        get_paper_min_edge()
        if min_edge is None
        else max(min_edge, get_paper_min_edge())
    )

    all_results: list[tuple[dict, dict]] = []
    no_quote_opps: list[tuple[dict, dict]] = []
    liquid_opps: list[tuple[dict, dict]] = []
    strong_opps: list[tuple[dict, dict]] = []
    med_opps: list[tuple[dict, dict]] = []
    signals_cache_entries: list[dict] = []
    # ticker->city map for every successfully-enriched market, tagged BEFORE
    # the `if not analysis: continue` skip below (opus review, 2026-08-03) --
    # matches main.py's _analyze_once own _arb_ticker_city tagging point
    # exactly. Building this narrower (e.g. only from `all_results`, which is
    # populated AFTER that skip) would silently drop every market
    # analyze_trade() returned falsy for from a caller's arb-exposure
    # city-cost lookup -- real for ~32 of analyze_trade's own falsy-return
    # paths (no forecast data, spread too wide, stale target date, etc.).
    ticker_city: dict[str, str] = {}
    dbg: dict[str, int] = {
        "no_analysis": 0,
        "analysis_errors": 0,  # a future raised, distinct from analyze_trade returning falsy
        "same_day": 0,  # informational only — same-day markets are not filtered
        "mkt_prob": 0,
        "divergence": 0,
        "net_edge": 0,
        "prob_edge": 0,
        "passed": 0,
        # Passed the net_edge/prob_edge threshold above but denied a tier
        # because it fails one of validate()'s deterministic pre-checks
        # (net_edge sign, raw-edge sign/magnitude, Kelly floor, or
        # confidence-tiered min_edge) -- would have been announced STRONG/MED
        # before this gate existed but could never actually have placed. See
        # "placement_gate" comment below.
        "placement_gate": 0,
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
                    ticker_city[m.get("ticker", "")] = enriched.get("_city", "")
                    if not analysis:
                        dbg["no_analysis"] += 1
                        continue

                    analysis["market_implied"] = resolve_market_implied_for_analysis(
                        market_implied_by_event,
                        enriched.get("_city"),
                        enriched.get("_date"),
                        m.get("ticker", ""),
                    )
                    # None-safe versions of `.get(key, default)`: a caller
                    # that sets either key present-but-None (the same real
                    # shape web_app.py:2874 shows for net_edge elsewhere in
                    # this codebase -- see backlog.txt's "[RESOLVED
                    # 2026-08-08] _validate_trade_opportunity() HAS 2 MORE
                    # LATENT None-VALUE CRASH SITES..." entry) must not
                    # silently skip the fallback and crash downstream on
                    # `net_edge <= 0` / `abs(adjusted_edge)`.
                    net_edge = analysis.get("net_edge")
                    if net_edge is None:
                        net_edge = analysis.get("edge")
                    if net_edge is None:
                        net_edge = 0.0
                    adjusted_edge = analysis.get("adjusted_edge")
                    if adjusted_edge is None:
                        adjusted_edge = net_edge

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
                    # auto-trading. Uses the single `effective_min_edge`
                    # snapshotted once above (opus review, 2026-08-03): this
                    # used to recompute the identical formula on every
                    # iteration, which silently shadowed the hoisted variable
                    # of the same name -- functionally harmless (byte-
                    # identical formula) but meant a mid-scan
                    # get_paper_min_edge() config write could apply to only
                    # some markets in the same cycle. One snapshot for the
                    # whole cycle is the more consistent behavior anyway.
                    passes_threshold = True
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

                    # Mirror order_executor._validate_trade_opportunity's
                    # deterministic edge pre-checks here (backlog.txt "STRONG/MED
                    # TIER CLASSIFICATION AND FINAL PLACEMENT VALIDATION USE
                    # DIFFERENT, DISAGREEING EDGE MEASURES") so a candidate can
                    # only earn STRONG/MED if it can structurally clear
                    # placement's own edge gates, not just the
                    # adjusted_edge/eff_strong_edge/MED_EDGE bar above. Two of
                    # validate()'s edge checks are mirrored exactly:
                    #   1. net_edge (EV/entry-ask) must be positive -- opus review
                    #      (2026-08-07) caught this as the FIRST check validate()
                    #      makes, immediately above the raw-edge block below; an
                    #      earlier version of this fix mirrored only the raw-edge
                    #      block and missed it, leaving a real gap (a wide-spread
                    #      market can have net_edge<=0 while abs(adjusted_edge)
                    #      still clears MED_EDGE/eff_strong_edge, since adjusted_edge
                    #      = net_edge * edge_confidence_factor preserves sign and
                    #      the tier check above uses abs()).
                    #   2. raw `edge` -- the side-agnostic (blended_prob -
                    #      market_prob) figure, priced off the market MID rather
                    #      than the entry ASK net_edge/adjusted_edge use -- must
                    #      agree in sign with `side` and clear MIN_EDGE in
                    #      magnitude, independently of adjusted_edge ever
                    #      qualifying. Skipped (defaults to passing) when "edge"
                    #      is absent, matching validate()'s own `if "edge" in
                    #      opp:` guard.
                    # validate()'s ci_adjusted_kelly/fee_adjusted_kelly floor
                    # (>= 0.002) is mirrored below via clears_kelly_floor --
                    # backlog.txt follow-up entry filed 2026-08-07, resolved
                    # 2026-08-08 after auditing every STRONG/MED-tier-qualifying
                    # test fixture across the suite (this file's
                    # _strong_market_analysis/_med_market_analysis,
                    # test_cron_integration.py's 5 fake_analysis dicts) and
                    # adding a realistic ci_adjusted_kelly to each that lacked
                    # one -- real analyze_trade() output always populates it,
                    # these mocks stand in for it entirely.
                    #
                    # validate()'s confidence-tiered min_edge check
                    # (get_min_edge_for_confidence, keyed off ensemble_spread)
                    # is mirrored below using `live` -- already threaded
                    # through run_trade_cycle's own signature -- exactly as
                    # validate() computes it. Resolved 2026-08-08 (explicit
                    # user choice over the cheaper alternative: a regression
                    # test asserting MED_EDGE's numeric domination, with no
                    # runtime code change). Deliberately NOT mirrored:
                    # validate()'s A/B-test min_edge override
                    # (_MIN_EDGE_AB_TEST.pick_variant()) -- not because
                    # pick_variant() is stateful (it isn't -- ab_test.py's
                    # pick_variant() reads state but only mutates it in
                    # record_outcome(), called on trade settlement, not here),
                    # but because its random tie-breaking makes a second call
                    # here genuinely nondeterministic relative to the real
                    # call validate() makes at placement time -- mirroring it
                    # would just be a second, disagreeing coin flip, not a
                    # meaningful structural check. (Numerically it stays a
                    # non-issue regardless: _MIN_EDGE_AB_TEST's variants max
                    # out at 0.09, well under MED_EDGE's 0.15 default.)
                    # Local import (not module-level) matching order_executor's
                    # own `from utils import MIN_EDGE as _MIN_EDGE` inside
                    # _validate_trade_opportunity -- a module-level value-import
                    # would freeze this at whatever MIN_EDGE was when trade_cycle
                    # was first imported, going stale exactly like main.py's
                    # Settings-screen `global MIN_EDGE` rebind exists to work
                    # around (main.py's MIN_EDGE is in the live-editable
                    # setting_keys list; trade_cycle is imported lazily but then
                    # cached in sys.modules for the rest of the process).
                    from utils import MIN_EDGE as _MIN_EDGE

                    # Note on how much this magnitude check actually bites:
                    # prob_edge = |edge| / time_decay, and the pre-existing
                    # prob-edge gate above already requires prob_edge >= 0.12
                    # for days_out <= 1 (min_prob_edge_for_days_out). At
                    # MIN_EDGE's own 0.07 default, this magnitude check is
                    # subsumed by that gate whenever time_decay == 1 (a fresh
                    # market) -- it only does independent work when MIN_EDGE
                    # is raised above that (this deployment currently runs
                    # MIN_EDGE=0.15) or when time_decay < 1 shrinks prob_edge's
                    # effective floor below MIN_EDGE. Don't read "this rarely
                    # fires in tests with the 0.07 default" as "this check is
                    # unnecessary" -- it's load-bearing for the real deployed
                    # config, and the live incident this fix addresses depended
                    # on exactly that.
                    raw_edge = analysis.get("edge")
                    clears_placement_gate = True
                    if net_edge <= 0:
                        clears_placement_gate = False
                    if raw_edge is not None:
                        if side == "yes" and raw_edge <= 0:
                            clears_placement_gate = False
                        elif side == "no" and raw_edge >= 0:
                            clears_placement_gate = False
                        elif abs(raw_edge) < _MIN_EDGE:
                            clears_placement_gate = False
                    # Mirrors validate()'s confidence-tiered min_edge check
                    # (same ensemble_spread key, same is_live flag, same
                    # get_min_edge_for_confidence call). Compared against
                    # net_edge (not adjusted_edge, which this loop's own
                    # passes_threshold gate above already used) -- not a
                    # byte-for-byte match of validate()'s own `edge` variable
                    # at this point, though: this `net_edge` (assigned above)
                    # falls back to the raw `edge` field when the `net_edge`
                    # key is absent, while validate()'s `edge` defaults
                    # straight to 0.0 with no such fallback. That divergence
                    # predates this check (shared with the net_edge<=0 gate
                    # right above) and only ever makes tier classification
                    # MORE permissive than placement's real gate, never less
                    # -- validate() remains the final, authoritative check
                    # before any order is placed. On lookup failure, this
                    # falls back to the freshly-imported `_MIN_EDGE` (not
                    # module-level `MIN_EDGE`, which order_executor.py's own
                    # equivalent fallback uses and which can go stale after a
                    # live Settings-screen edit+reload) -- matches this
                    # file's own existing anti-staleness convention (see
                    # `_MIN_EDGE`'s own import comment above) rather than
                    # replicating that known order_executor.py quirk.
                    _ens_spread = analysis.get("ensemble_spread")
                    if _ens_spread is not None:
                        try:
                            _confidence_min_edge = get_min_edge_for_confidence(
                                float(_ens_spread), is_live=bool(live)
                            )
                        except Exception:
                            _confidence_min_edge = (
                                get_paper_min_edge() if not live else _MIN_EDGE
                            )
                    else:
                        _confidence_min_edge = (
                            get_paper_min_edge() if not live else _MIN_EDGE
                        )
                    if net_edge < _confidence_min_edge:
                        clears_placement_gate = False
                    # Mirrors validate()'s Kelly floor exactly, including its
                    # None-safe ci_adjusted_kelly -> fee_adjusted_kelly -> 0.0
                    # fallback chain (order_executor.py's _validate_trade_
                    # opportunity, fixed for the same None-crash bug class
                    # 2026-08-08).
                    candidate_kelly = analysis.get("ci_adjusted_kelly")
                    if candidate_kelly is None:
                        candidate_kelly = analysis.get("fee_adjusted_kelly")
                    if candidate_kelly is None:
                        candidate_kelly = 0.0
                    if candidate_kelly < 0.002:
                        clears_placement_gate = False
                    analysis["_clears_placement_gate"] = clears_placement_gate
                    if passes_threshold and not clears_placement_gate:
                        dbg["placement_gate"] += 1

                    analysis["tier"] = None
                    if passes_threshold and clears_placement_gate:
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
                    # backlog.txt "DASHBOARD STARS + WATCH-MODE STRONG ALERT
                    # KEY OFF SIGNAL TEXT, NOT THE tier FIELD": stars now key
                    # off the authoritative `tier` this loop itself just set
                    # above (None unless the candidate cleared passes_
                    # threshold + every placement gate), not signal text
                    # alone, which is driven only by adjusted_edge magnitude
                    # and has no awareness of the placement gates.
                    star_tier = analysis.get("tier")
                    stars = (
                        "★★★"
                        if star_tier == TIER_STRONG and time_risk == "LOW"
                        else "★★"
                        if star_tier in (TIER_STRONG, TIER_MED)
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
                            "tier": star_tier,
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
        deduped_markets=deduped_markets,
        scanned=len(deduped_markets),
        dedup_removed=dedup_removed,
        stale_skipped=stale_skipped,
        effective_min_edge=effective_min_edge,
        all_results=all_results,
        ticker_city=ticker_city,
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
            from weather_markets import _CITY_TZ as _mos_city_tz

            mos_sta = _mos_mod.get_mos_station(c)
            if mos_sta:
                _mos_mod.fetch_mos_best(mos_sta, target_date=dt, tz=_mos_city_tz.get(c))
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
