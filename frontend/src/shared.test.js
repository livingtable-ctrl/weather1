import { describe, it, expect } from 'vitest';
import { buildPaperOrderBody, sideAwareEntryPrice, summarizeBulkResults, effectiveSelection, gradGateStatus } from './shared.jsx';

// batch-26 item 1: the signals cache (and this opp object) stores
// yes_bid/yes_ask/forecast_prob/market_prob in YES-space regardless of the
// recommended side. Approving a NO signal must flip entry_price to
// side-space (1 - yes_bid) before POSTing to /api/paper-order, or the
// server computes kelly_fraction(P_yes, yes_price) for a NO recommendation
// -- P_yes is always < market_prob by construction whenever the
// recommendation is NO, so Kelly is exactly 0.0 and the server rejects with
// a misleading "no edge" 400.
//
// entry_prob must NOT be flipped -- opus review (batch-26) caught that
// every server-side consumer of the stored entry_prob (tracker's Brier/
// calibration scoring, order_executor's model-reversal exit shift, paper's
// pnl_attribution) treats it as YES-space, matching the bot's own
// order_executor.py call sites (entry_prob=analysis["forecast_prob"]).
// Flipping it would have corrupted live calibration data for every NO
// approval. web_app.py's /api/paper-order route converts to side-space
// internally, for its own Kelly-cap check only -- see web_app.py's
// api_paper_order.

describe('buildPaperOrderBody', () => {
  it('YES signal: sends yes_ask as entry_price, forecast_prob as-is', () => {
    const opp = {
      ticker: 'KXHIGH-26AUG22-T70', side: 'YES', edge_pct: 12.5,
      yes_bid: 0.28, yes_ask: 0.32, market_prob: 30, forecast_prob: 42.5,
      city: 'NYC', target_date: '2026-08-22',
    };
    const body = buildPaperOrderBody(opp, 5);
    expect(body.side).toBe('yes');
    expect(body.entry_price).toBeCloseTo(0.32, 10);
    expect(body.entry_prob).toBeCloseTo(0.425, 10);
    // Positive control: prove the ask-side field was actually read, not a
    // coincidence -- yes_bid and yes_ask are deliberately distinct.
    expect(body.entry_price).not.toBe(opp.yes_bid);
  });

  it('NO signal: flips entry_price to 1-yes_bid but leaves entry_prob in YES-space (NOT flipped)', () => {
    // Model thinks YES is only 30% likely; market prices YES at 55% (NO
    // fairly priced ~45%) -- a genuine NO recommendation with real edge.
    const opp = {
      ticker: 'KXHIGH-26AUG22-T80', side: 'NO', edge_pct: 25.0,
      yes_bid: 0.54, yes_ask: 0.56, market_prob: 55, forecast_prob: 30,
      city: 'Chicago', target_date: '2026-08-22',
    };
    const body = buildPaperOrderBody(opp, 3);
    expect(body.side).toBe('no');
    // Correct NO-space entry price: 1 - yes_bid (the no_ask), not yes_ask
    // and not market_prob/100 (the as-shipped bug's unconditional value).
    expect(body.entry_price).toBeCloseTo(1 - 0.54, 10);
    expect(body.entry_price).not.toBeCloseTo(opp.market_prob / 100, 10);
    expect(body.entry_price).not.toBeCloseTo(opp.yes_ask, 10);
    // entry_prob stays YES-space, unflipped -- server-side storage
    // (tracker Brier scoring, exit-shift math) expects this convention
    // regardless of side. Flipping it here would silently invert every
    // NO trade's calibration record.
    expect(body.entry_prob).toBeCloseTo(0.30, 10);
    expect(body.entry_prob).not.toBeCloseTo(1 - 0.30, 10);
  });

  it('NO signal with no live yes_bid quote: entry_price falls back to 1 - market_prob/100, not the raw market_prob', () => {
    const opp = {
      ticker: 'KXHIGH-26AUG22-T90', side: 'no', edge_pct: 10.0,
      yes_bid: null, yes_ask: null, market_prob: 60, forecast_prob: 45,
    };
    const body = buildPaperOrderBody(opp, 2);
    expect(body.entry_price).toBeCloseTo(1 - 0.60, 10);
    expect(body.entry_price).not.toBeCloseTo(0.60, 10);
    expect(body.entry_prob).toBeCloseTo(0.45, 10);
  });

  it('YES signal with no live yes_ask quote: falls back to market_prob/100', () => {
    const opp = {
      ticker: 'KXHIGH-26AUG22-T60', side: 'yes', edge_pct: 8.0,
      yes_bid: 0, yes_ask: 0, market_prob: 40, forecast_prob: 52,
    };
    const body = buildPaperOrderBody(opp, 1);
    expect(body.entry_price).toBeCloseTo(0.40, 10);
  });

  it('a yes_bid of exactly 1.0 (degenerate one-sided book) falls back to the mid, not entry_price=0', () => {
    // opus review (LOW-8): askSidePrice = 1 - 1.0 = 0 must not be treated
    // as a valid price -- 0 is falsy-adjacent but was previously accepted
    // by a bare `!= null` check. Must fall back to the mid instead of
    // sending an unplaceable $0 order.
    const opp = {
      ticker: 'KXHIGH-26AUG22-T85', side: 'no', edge_pct: 9.0,
      yes_bid: 1.0, yes_ask: 1.0, market_prob: 92, forecast_prob: 70,
    };
    const body = buildPaperOrderBody(opp, 1);
    expect(body.entry_price).toBeGreaterThan(0);
    expect(body.entry_price).toBeCloseTo(1 - 0.92, 10);
  });

  it('missing forecast_prob: entry_prob is null (server skips the Kelly cap, matches existing contract), not a bogus flipped value', () => {
    const opp = {
      ticker: 'KXHIGH-26AUG22-T50', side: 'no', edge_pct: 5.0,
      yes_bid: 0.45, yes_ask: 0.50, market_prob: 48, forecast_prob: null,
    };
    const body = buildPaperOrderBody(opp, 1);
    expect(body.entry_prob).toBeNull();
    // entry_price must still be correctly side-flipped even when
    // entry_prob is unavailable -- this is the "second-order more severe"
    // case from the audit (Kelly cap skip must not also get the wrong price).
    expect(body.entry_price).toBeCloseTo(1 - 0.45, 10);
  });

  it('defaults side to yes when opp.side is missing', () => {
    const opp = {
      ticker: 'KXHIGH-26AUG22-T65', edge_pct: 6.0,
      yes_bid: 0.33, yes_ask: 0.37, market_prob: 35, forecast_prob: 41,
    };
    const body = buildPaperOrderBody(opp, 1);
    expect(body.side).toBe('yes');
    expect(body.entry_price).toBeCloseTo(0.37, 10);
  });

  it('net_edge prefers the raw 6dp cache ratio over re-dividing the 1dp edge_pct', () => {
    // signals_cache_entries serves net_edge rounded to 6dp and edge_pct to
    // 1dp; deriving from edge_pct would collapse 0.123456 to 0.123.
    const opp = {
      ticker: 'KXHIGH-26AUG22-T75', side: 'yes', edge_pct: 12.3,
      net_edge: 0.123456, yes_bid: 0.28, yes_ask: 0.32,
      market_prob: 30, forecast_prob: 42,
    };
    const body = buildPaperOrderBody(opp, 1);
    expect(body.net_edge).toBe(0.123456);
    expect(body.net_edge).not.toBeCloseTo(0.123, 10);
  });

  it('net_edge falls back to edge_pct/100 when the raw field is absent (mock data)', () => {
    const opp = {
      ticker: 'KXHIGH-26AUG22-T75', side: 'yes', edge_pct: 12.5,
      yes_bid: 0.28, yes_ask: 0.32, market_prob: 30, forecast_prob: 42,
    };
    expect(buildPaperOrderBody(opp, 1).net_edge).toBeCloseTo(0.125, 10);
    expect(buildPaperOrderBody({ ...opp, edge_pct: null }, 1).net_edge).toBeNull();
  });
});

// opus review (batch-26): sideAwareEntryPrice is now a standalone exported
// helper, shared by buildPaperOrderBody AND handleAction/the qty-input
// default/the "Kelly contracts" detail display/the confirm-dialog cost --
// an earlier draft only fixed buildPaperOrderBody, leaving those other
// UI surfaces still dividing by the raw YES-space market_prob for a NO
// signal (same defect class as item 3, just on the frontend).
describe('sideAwareEntryPrice', () => {
  it('matches buildPaperOrderBody entry_price for both sides', () => {
    const yesOpp = {
      side: 'yes', yes_bid: 0.28, yes_ask: 0.32, market_prob: 30,
    };
    const noOpp = {
      side: 'no', yes_bid: 0.54, yes_ask: 0.56, market_prob: 55,
    };
    expect(sideAwareEntryPrice(yesOpp)).toBe(
      buildPaperOrderBody(yesOpp, 1).entry_price
    );
    expect(sideAwareEntryPrice(noOpp)).toBe(
      buildPaperOrderBody(noOpp, 1).entry_price
    );
  });

  it('NO side never coincidentally equals the raw YES-space market_prob', () => {
    const opp = { side: 'no', yes_bid: 0.60, yes_ask: 0.62, market_prob: 61 };
    const price = sideAwareEntryPrice(opp);
    expect(price).toBeCloseTo(1 - 0.60, 10);
    expect(price).not.toBeCloseTo(opp.market_prob / 100, 5);
  });
});

// -----------------------------------------------------------------------
// summarizeBulkResults — batch-41 C-1/C-2: bulk-approve and bulk-close both
// used to print an unconditional "✓ Placed N" / "✓ Closed N" toast without
// inspecting what the N responses actually said. These tests prove the
// counting logic itself distinguishes real successes from failures -- the
// exact guard the original bug never had.
// -----------------------------------------------------------------------
describe('summarizeBulkResults', () => {
  it('all fulfilled with no error field: every response counts as succeeded', () => {
    const results = [
      { status: 'fulfilled', value: { ok: true } },
      { status: 'fulfilled', value: { ok: true } },
      { status: 'fulfilled', value: { ok: true } },
    ];
    expect(summarizeBulkResults(results)).toEqual({ succeeded: 3, failed: 0, total: 3 });
  });

  it('a fulfilled response carrying {error} is NOT counted as a success', () => {
    // This is the positive control for the original bug: prove the counter
    // actually inspects response bodies rather than trusting Promise
    // settlement alone (a resolved fetch that the server rejected still
    // "fulfills" the promise).
    const results = [
      { status: 'fulfilled', value: { ok: true } },
      { status: 'fulfilled', value: { error: 'insufficient balance' } },
      { status: 'fulfilled', value: { ok: true } },
    ];
    expect(summarizeBulkResults(results)).toEqual({ succeeded: 2, failed: 1, total: 3 });
  });

  it('a rejected settlement (network failure) counts as failed, not silently dropped', () => {
    const results = [
      { status: 'fulfilled', value: { ok: true } },
      { status: 'rejected', reason: new TypeError('Failed to fetch') },
    ];
    expect(summarizeBulkResults(results)).toEqual({ succeeded: 1, failed: 1, total: 2 });
  });

  it('all responses carry {error}: succeeded is 0, never the unconditional total', () => {
    const results = [
      { status: 'fulfilled', value: { error: 'kill switch active' } },
      { status: 'fulfilled', value: { error: 'kill switch active' } },
    ];
    const { succeeded, failed, total } = summarizeBulkResults(results);
    expect(succeeded).toBe(0);
    expect(failed).toBe(2);
    // Positive control that total (the old, buggy count) and succeeded
    // (the new, correct count) actually diverge here -- proves the fix
    // isn't a no-op that happens to equal the old behavior in this case.
    expect(succeeded).not.toBe(total);
  });

  it('custom getError extracts a nested error field (SignalsTab wraps {opp, d})', () => {
    const results = [
      { status: 'fulfilled', value: { opp: { ticker: 'A' }, d: { ok: true } } },
      { status: 'fulfilled', value: { opp: { ticker: 'B' }, d: { error: 'no edge' } } },
    ];
    expect(summarizeBulkResults(results, (v) => v.d?.error)).toEqual({
      succeeded: 1, failed: 1, total: 2,
    });
  });

  it('empty results: zero everything, not a crash or NaN', () => {
    expect(summarizeBulkResults([])).toEqual({ succeeded: 0, failed: 0, total: 0 });
  });
});

// -----------------------------------------------------------------------
// effectiveSelection — batch-41 C-3: a bulk-selection count/checkbox/action
// must always agree with what's currently visible under a filter, without
// permanently losing a selection made before the filter was applied.
// -----------------------------------------------------------------------
describe('effectiveSelection', () => {
  it('selection entirely within the visible set is returned unchanged', () => {
    const selected = new Set(['a', 'b']);
    const eff = effectiveSelection(selected, ['a', 'b', 'c']);
    expect([...eff].sort()).toEqual(['a', 'b']);
  });

  it('a selected id no longer visible is excluded from the effective set', () => {
    // This is the exact C-3 bug: 10 selected, a filter narrows the table to
    // 2 visible rows -- the effective (actionable/displayed) selection must
    // be 2, not 10.
    const selected = new Set(['a', 'b', 'c', 'd']);
    const eff = effectiveSelection(selected, ['a', 'c']);
    expect([...eff].sort()).toEqual(['a', 'c']);
    expect(eff.size).toBe(2);
    expect(eff.size).not.toBe(selected.size);
  });

  it('does not mutate the original selectedIds set', () => {
    const selected = new Set(['a', 'b', 'c']);
    effectiveSelection(selected, ['a']);
    expect(selected.size).toBe(3);
    expect([...selected].sort()).toEqual(['a', 'b', 'c']);
  });

  it('non-destructive: a selection excluded by a narrow filter reappears once the filter widens again', () => {
    // Chosen design (AskUserQuestion, batch-41 C-3): selectedIds itself is
    // never pruned by filtering. Calling effectiveSelection again against a
    // wider visible set, with the SAME original selectedIds untouched,
    // must restore what a narrower filter had hidden -- proving nothing was
    // silently and permanently dropped.
    const selected = new Set(['a', 'b']);
    const narrowed = effectiveSelection(selected, ['a']);
    expect([...narrowed]).toEqual(['a']);
    const widened = effectiveSelection(selected, ['a', 'b', 'c']);
    expect([...widened].sort()).toEqual(['a', 'b']);
  });

  it('accepts visible keys as a Set or a plain array with identical results', () => {
    const selected = new Set(['x', 'y', 'z']);
    const viaArray = effectiveSelection(selected, ['x', 'y']);
    const viaSet = effectiveSelection(selected, new Set(['x', 'y']));
    expect([...viaArray].sort()).toEqual([...viaSet].sort());
  });

  it('empty selection or empty visible set both yield an empty result', () => {
    expect(effectiveSelection(new Set(), ['a', 'b']).size).toBe(0);
    expect(effectiveSelection(new Set(['a', 'b']), []).size).toBe(0);
  });
});

// -----------------------------------------------------------------------
// gradGateStatus — batch-41 audit-M-11 (opus review MEDIUM-6): a real
// null brier (mapStats no longer falls back to MOCK's baked-in 0.151)
// must render as "insufficient data" / not-complete, never coerce through
// `null <= target` (which JS evaluates as `0 <= target` = true).
// -----------------------------------------------------------------------
describe('gradGateStatus', () => {
  it('null current (inverted gate, e.g. Brier): noData=true, complete=false, pct=0', () => {
    const { noData, complete, pct } = gradGateStatus(null, 0.20, true);
    expect(noData).toBe(true);
    expect(complete).toBe(false);
    expect(pct).toBe(0);
  });

  it('positive control: null current does NOT paint the gate green via `null <= target` coercion', () => {
    // This is the exact bug: null <= 0.20 evaluates true in JS. Confirms
    // gradGateStatus doesn't fall into that trap.
    expect(null <= 0.20).toBe(true); // sanity-check the JS coercion itself
    expect(gradGateStatus(null, 0.20, true).complete).toBe(false);
  });

  it('a real brier at/below target (inverted): complete=true', () => {
    const { noData, complete } = gradGateStatus(0.18, 0.20, true);
    expect(noData).toBe(false);
    expect(complete).toBe(true);
  });

  it('a real brier above target (inverted): complete=false, not insufficient-data', () => {
    const { noData, complete } = gradGateStatus(0.25, 0.20, true);
    expect(noData).toBe(false);
    expect(complete).toBe(false);
  });

  it('non-inverted gate (e.g. Trades done >= target): complete when current >= target', () => {
    expect(gradGateStatus(30, 30, false).complete).toBe(true);
    expect(gradGateStatus(29, 30, false).complete).toBe(false);
  });

  it('inverted pct scale runs from 0.25 baseline down to target, clamped to [0, 100]', () => {
    // At current == target, pct must be exactly 100 (gate just cleared).
    expect(gradGateStatus(0.20, 0.20, true).pct).toBeCloseTo(100, 10);
    // At current == 0.25 baseline, pct must be 0.
    expect(gradGateStatus(0.25, 0.20, true).pct).toBeCloseTo(0, 10);
    // Beyond the baseline (worse than 0.25), still clamped to 0, not negative.
    expect(gradGateStatus(0.30, 0.20, true).pct).toBe(0);
  });
});
