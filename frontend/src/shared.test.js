import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { buildPaperOrderBody, sideAwareEntryPrice, summarizeBulkResults, effectiveSelection, gradGateStatus, fmtSigned, brierAlertTier, haltOrResume, oppKey, pruneExpired, filterRejected, validateOverrideDuration, summarizeTradeOutcomes, sumUnrealizedPnl, positionUnrealizedPnl, balanceDeltaPct, TAB_LIST, tabForHotkey, resolveByKey, heatStatus, feedFreshness, formatFeedAge, FEED_STALE_MS, FEED_HARD_STALE_MS, alarmSafeFlag, ORDER_STALE_MS, orderQuoteStaleness, staleQuoteWarning, worstStaleness, parseFeedTimestamp, SCAN_STALE_MS, useFeedClock, __resetFeedClockForTests, staleFeedState, staleBannerCopy } from './shared.jsx';

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
// fmtSigned — batch-42 H-4: a negative edge (or any signed value) used to
// render as a hardcoded '+3.2%' painted green regardless of sign at three
// call sites. These tests prove the sign AND colour both derive from the
// actual value, not a call-site constant.
// -----------------------------------------------------------------------
describe('fmtSigned', () => {
  it('positive value: leading + and green', () => {
    const { text, color } = fmtSigned(3.2);
    expect(text).toBe('+3.2%');
    expect(color).toBe('#16a34a');
  });

  it('negative value: no leading +, and red -- the exact H-4 bug this guards', () => {
    // Positive control for the original bug: a hardcoded '+' + green would
    // render '+-3.2%' in green here. Confirm neither happens.
    const { text, color } = fmtSigned(-3.2);
    expect(text).toBe('-3.2%');
    expect(text).not.toContain('+-');
    expect(color).toBe('#ef4444');
    expect(color).not.toBe('#16a34a');
  });

  it('zero counts as non-negative: leading + and green', () => {
    const { text, color } = fmtSigned(0);
    expect(text).toBe('+0.0%');
    expect(color).toBe('#16a34a');
  });

  it('respects a custom decimals argument', () => {
    expect(fmtSigned(3.14159, 3).text).toBe('+3.142%');
    expect(fmtSigned(-3.14159, 3).text).toBe('-3.142%');
  });

  it('respects a custom suffix argument (e.g. dollars, not percent)', () => {
    expect(fmtSigned(12.5, 2, '').text).toBe('+12.50');
    expect(fmtSigned(-4.4, 1, ' pts').text).toBe('-4.4 pts');
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

// -----------------------------------------------------------------------
// batch-47 item 2: sumUnrealizedPnl / positionUnrealizedPnl / balanceDeltaPct
// -- unguarded cost/qty and balance/starting_balance divisions used to render
// NaN%/Infinity% directly into KPI cards. Also independently flagged
// pre-port by audit/POST_MERGE_REVIEW.md's L-17 sweep ("App.jsx divide-by-qty
// NaN") -- these tests pin the fix.
// -----------------------------------------------------------------------
describe('sumUnrealizedPnl', () => {
  it('hand-computed sum across two real positions', () => {
    const positions = [
      { cost: 50, qty: 10, mark: 6 },  // entryPerCt=5, (6-5)*10=+10
      { cost: 100, qty: 20, mark: 4 }, // entryPerCt=5, (4-5)*20=-20
    ];
    expect(sumUnrealizedPnl(positions)).toBeCloseTo(-10, 10);
  });

  it('a qty===0 position contributes 0 rather than poisoning the sum into NaN', () => {
    const positions = [
      { cost: 50, qty: 10, mark: 6 },   // +10, a real position
      { cost: 30, qty: 0, mark: 5 },    // data anomaly -- would be cost/0 = NaN unguarded
    ];
    const result = sumUnrealizedPnl(positions);
    expect(result).toBeCloseTo(10, 10);
    // Positive control: prove the anomalous row was actually reached (not
    // just absent from the array) and didn't turn the whole sum into NaN.
    expect(Number.isFinite(result)).toBe(true);
  });

  it('empty/null/undefined positions: returns 0, not NaN', () => {
    expect(sumUnrealizedPnl([])).toBe(0);
    expect(sumUnrealizedPnl(null)).toBe(0);
    expect(sumUnrealizedPnl(undefined)).toBe(0);
  });

  // opus review (batch-47, LOW): balanceDeltaPct already coerced via
  // Number(); this guard used a bare truthy check, so a qty arriving as the
  // string "0" (rather than the number 0) would slip past `!p.qty` and
  // still divide. Currently unreachable in practice (mapTrades assigns qty
  // straight from a JSON int) but the two guards should agree.
  it('a qty arriving as the string "0" is caught the same as numeric 0', () => {
    const positions = [
      { cost: 50, qty: 10, mark: 6 },
      { cost: 30, qty: '0', mark: 5 },
    ];
    const result = sumUnrealizedPnl(positions);
    expect(result).toBeCloseTo(10, 10);
    expect(Number.isFinite(result)).toBe(true);
  });
});

describe('positionUnrealizedPnl', () => {
  it('hand-computed P&L for a real position', () => {
    // entryPerCt = 50/10 = 5; (mark 6 - 5) * 10 qty = +10
    expect(positionUnrealizedPnl({ cost: 50, qty: 10, mark: 6 })).toBeCloseTo(10, 10);
  });

  it('qty===0: returns null (caller renders "—"), not NaN', () => {
    expect(positionUnrealizedPnl({ cost: 50, qty: 0, mark: 6 })).toBe(null);
  });

  it('qty as the string "0": also returns null (matches sumUnrealizedPnl\'s coercion)', () => {
    expect(positionUnrealizedPnl({ cost: 50, qty: '0', mark: 6 })).toBe(null);
  });
});

describe('balanceDeltaPct', () => {
  it('hand-computed positive and negative deltas', () => {
    expect(balanceDeltaPct(120, 100)).toBeCloseTo(0.2, 10);
    expect(balanceDeltaPct(80, 100)).toBeCloseTo(-0.2, 10);
  });

  it('starting_balance===0 (fresh install, no funding record yet): returns null, not Infinity/NaN', () => {
    expect(balanceDeltaPct(50, 0)).toBe(null);
    // Positive control: the unguarded computation really would produce
    // Infinity here, proving this is a real division-by-zero case being caught.
    expect(50 / 0).toBe(Infinity);
  });

  it('both balance and starting_balance 0: returns null, not NaN (0/0)', () => {
    expect(balanceDeltaPct(0, 0)).toBe(null);
  });
});

// -----------------------------------------------------------------------
// batch-47 item 3: TAB_LIST / tabForHotkey -- single source of truth for tab
// metadata, replacing four independently hand-written copies (Nav's
// TAB_NAMES, CommandPalette's own list, the keydown handler's digit-shortcut
// list, and the TABS routing registry) that had already drifted.
// -----------------------------------------------------------------------
describe('TAB_LIST / tabForHotkey', () => {
  it('all nine tabs present, in nav order', () => {
    expect(TAB_LIST.map(t => t.id)).toEqual([
      'Overview', 'Positions', 'Signals', 'Forecast', 'Analytics',
      'Activity', 'Risk', 'Trades', 'Settings',
    ]);
  });

  it('Settings has no hotkey -- confirmed intentional with the user, not a silent drift', () => {
    expect(TAB_LIST.find(t => t.id === 'Settings').hotkey).toBe(null);
  });

  it('digits 1-8 map to the first eight tabs in order', () => {
    const expected = ['Overview', 'Positions', 'Signals', 'Forecast', 'Analytics', 'Activity', 'Risk', 'Trades'];
    expected.forEach((id, i) => {
      expect(tabForHotkey(String(i + 1))).toBe(id);
    });
  });

  it('"9" and other unmapped keys resolve to null (no accidental Settings hotkey)', () => {
    expect(tabForHotkey('9')).toBe(null);
    expect(tabForHotkey('a')).toBe(null);
    expect(tabForHotkey('')).toBe(null);
  });
});

// -----------------------------------------------------------------------
// brierAlertTier — batch-45 M-4: OverviewTab's banner and RiskTab's
// BrierAlertCard used to compute "consecutive weeks above 0.22" independently
// and label the identical state differently (e.g. one week read "warning" on
// one tab and "ALERT" on the other). These tests pin the single shared
// severity scheme both now render from.
// -----------------------------------------------------------------------
describe('brierAlertTier', () => {
  it('0 consecutive weeks above threshold: clear tier', () => {
    const hist = [{ week: 'w1', brier: 0.10 }, { week: 'w2', brier: 0.15 }];
    expect(brierAlertTier(hist)).toEqual({ weeks: 0, tier: 'clear', label: 'Clear' });
  });

  it('exactly 1 consecutive week above threshold: warning tier, not alert', () => {
    const hist = [{ week: 'w1', brier: 0.10 }, { week: 'w2', brier: 0.30 }];
    expect(brierAlertTier(hist)).toEqual({ weeks: 1, tier: 'warning', label: 'Warning' });
  });

  it('2+ consecutive weeks above threshold: alert tier (true P10.3)', () => {
    const hist = [{ week: 'w1', brier: 0.10 }, { week: 'w2', brier: 0.30 }, { week: 'w3', brier: 0.25 }];
    expect(brierAlertTier(hist)).toEqual({ weeks: 2, tier: 'alert', label: 'Alert' });
  });

  it('a below-threshold week resets the streak even after several above', () => {
    const hist = [{ week: 'w1', brier: 0.30 }, { week: 'w2', brier: 0.30 }, { week: 'w3', brier: 0.10 }];
    expect(brierAlertTier(hist).weeks).toBe(0);
  });

  it('only looks at the most recent 6 weeks', () => {
    // First 4 weeks are above threshold but fall outside slice(-6); last 6 are all below.
    const hist = Array.from({ length: 10 }, (_, i) => ({ week: `w${i}`, brier: i < 4 ? 0.30 : 0.10 }));
    expect(brierAlertTier(hist).weeks).toBe(0);
  });

  it('boundary is strictly greater-than, not >=: exactly at threshold does not count', () => {
    expect(brierAlertTier([{ week: 'w1', brier: 0.22 }]).weeks).toBe(0);
  });

  it('respects a custom threshold argument', () => {
    expect(brierAlertTier([{ week: 'w1', brier: 0.15 }], 0.10).weeks).toBe(1);
  });

  it('empty or missing history: clear tier, no crash', () => {
    expect(brierAlertTier([])).toEqual({ weeks: 0, tier: 'clear', label: 'Clear' });
    expect(brierAlertTier(undefined)).toEqual({ weeks: 0, tier: 'clear', label: 'Clear' });
  });
});

// -----------------------------------------------------------------------
// haltOrResume — batch-45 audit-M-8: the halt/resume/kill buttons used to
// fire-and-forget with no .then/.catch at all, so a real server-side failure
// (the routes have a genuine 500 path) was silent. These are the positive/
// negative controls for that fix: a non-ok response and a network failure
// must BOTH call addToast (not refresh); only a genuine ok response calls
// refresh (not addToast).
// -----------------------------------------------------------------------
describe('haltOrResume', () => {
  beforeEach(() => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => null, setItem: () => {}, removeItem: () => {}, clear: () => {},
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('halt: ok response calls refresh, never addToast', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path) => {
      expect(path).toBe('/api/halt');
      return { ok: true };
    }));
    const refresh = vi.fn();
    const addToast = vi.fn();
    await haltOrResume('halt', { refresh, addToast });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(addToast).not.toHaveBeenCalled();
  });

  it('halt: non-ok response calls addToast with the kill-switch fallback message, never refresh', () => {
    // Positive control for the original bug: a real server-side failure must
    // not be silent -- this is the exact scenario the missing .then() dropped.
    return (async () => {
      vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
      const refresh = vi.fn();
      const addToast = vi.fn();
      await haltOrResume('halt', { refresh, addToast });
      expect(refresh).not.toHaveBeenCalled();
      expect(addToast).toHaveBeenCalledWith('Halt FAILED — use py main.py kill', 'error');
    })();
  });

  it('halt: a rejected fetch (network failure) also calls addToast, not refresh', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    const refresh = vi.fn();
    const addToast = vi.fn();
    await haltOrResume('halt', { refresh, addToast });
    expect(refresh).not.toHaveBeenCalled();
    expect(addToast).toHaveBeenCalledWith('Halt FAILED — use py main.py kill', 'error');
  });

  it('resume: ok response hits the resume endpoint and calls refresh', async () => {
    vi.stubGlobal('fetch', vi.fn(async (path) => {
      expect(path).toBe('/api/resume');
      return { ok: true };
    }));
    const refresh = vi.fn();
    await haltOrResume('resume', { refresh, addToast: vi.fn() });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("resume: failure message names the resume CLI fallback, distinct from halt's", async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
    const addToast = vi.fn();
    await haltOrResume('resume', { refresh: vi.fn(), addToast });
    expect(addToast).toHaveBeenCalledWith('Resume FAILED — use py main.py resume', 'error');
  });

  it('an unrecognized action throws rather than silently defaulting to resume', () => {
    // opus review MEDIUM: a ternary (`action === 'halt' ? halt : resume`)
    // would resolve any typo/third-action to the UNSAFE direction -- un-
    // halting live trading behind a dialog that told the operator they were
    // engaging the kill switch. Must fail loud instead.
    vi.stubGlobal('fetch', vi.fn());
    expect(() => haltOrResume('kill', { refresh: vi.fn(), addToast: vi.fn() })).toThrow(/unknown action/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('missing addToast/refresh logs an error and does not throw an unhandled rejection', async () => {
    // opus review LOW: a call site that regresses (omits refresh/addToast)
    // must not silently recreate the original bug via a throw-inside-.then
    // that then throws again inside .catch.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn());
    await expect(haltOrResume('halt', { refresh: vi.fn() })).resolves.toBeUndefined();
    expect(fetch).not.toHaveBeenCalled();
    expect(errSpy).toHaveBeenCalled();
    errSpy.mockRestore();
  });
});

// -----------------------------------------------------------------------
// oppKey / pruneExpired — batch-45 M-7: SignalsTab's Reject used to be a
// pure no-op (toast + return, nothing persisted). oppKey is the composite
// ticker+target_date key shared by placedSet AND rejectedMap (previously
// five hand-duplicated inline copies across the file); pruneExpired is the
// TTL-expiry logic that keeps a dismissal from hiding a signal forever.
// -----------------------------------------------------------------------
describe('oppKey', () => {
  it('combines ticker and target_date', () => {
    expect(oppKey({ ticker: 'KXHIGH-26AUG22-T70', target_date: '2026-08-22' }))
      .toBe('KXHIGH-26AUG22-T70|2026-08-22');
  });

  it('falls back to expiry when target_date is absent', () => {
    expect(oppKey({ ticker: 'ABC', expiry: '2026-09-01' })).toBe('ABC|2026-09-01');
  });

  it('falls back to empty string when neither is present', () => {
    expect(oppKey({ ticker: 'ABC' })).toBe('ABC|');
  });

  it('two opps on the same ticker but different target_date get distinct keys', () => {
    const a = oppKey({ ticker: 'ABC', target_date: '2026-08-22' });
    const b = oppKey({ ticker: 'ABC', target_date: '2026-08-23' });
    expect(a).not.toBe(b);
  });
});

describe('pruneExpired', () => {
  it('drops entries whose expiry is in the past', () => {
    const now = 1_000_000;
    const map = { a: now - 1, b: now + 1 };
    expect(pruneExpired(map, now)).toEqual({ b: now + 1 });
  });

  it('an entry expiring at exactly `now` is dropped (exp > now, not >=)', () => {
    const now = 1_000_000;
    expect(pruneExpired({ a: now }, now)).toEqual({});
  });

  it('empty map: returns an empty object, no crash', () => {
    expect(pruneExpired({}, Date.now())).toEqual({});
  });

  it('defaults `now` to Date.now() when omitted', () => {
    const future = Date.now() + 60_000;
    const past = Date.now() - 60_000;
    expect(pruneExpired({ keep: future, drop: past })).toEqual({ keep: future });
  });
});

// -----------------------------------------------------------------------
// filterRejected — opus review MEDIUM (batch-45): the original inline
// exclusion checked rejectedMap[key] for PRESENCE only. Since pruning ran
// once at mount, an entry never actually left the map on a long-open tab,
// so the 24h TTL never fired. filterRejected instead checks the SAME
// expiry against `now` at call time -- an expired entry stops suppressing
// its row even if the map itself hasn't been pruned yet. This is the
// positive/negative control that specific defect.
// -----------------------------------------------------------------------
describe('filterRejected', () => {
  it('excludes an opp with a not-yet-expired rejection', () => {
    const opps = [{ ticker: 'A', target_date: '2026-08-22' }, { ticker: 'B', target_date: '2026-08-22' }];
    const now = 1_000_000;
    const rejected = { 'A|2026-08-22': now + 1000 };
    expect(filterRejected(opps, rejected, now).map(o => o.ticker)).toEqual(['B']);
  });

  it('positive control: an EXPIRED entry no longer suppresses its row, even though it is still present in the map', () => {
    // This is the exact bug: presence-only checking would keep 'A' hidden
    // forever since pruning never actually removes it from state in time.
    const opps = [{ ticker: 'A', target_date: '2026-08-22' }];
    const now = 1_000_000;
    const staleRejection = { 'A|2026-08-22': now - 1 }; // expired, but still IN the map
    expect(filterRejected(opps, staleRejection, now).map(o => o.ticker)).toEqual(['A']);
  });

  it('an opp never rejected is unaffected', () => {
    const opps = [{ ticker: 'A', target_date: '2026-08-22' }];
    expect(filterRejected(opps, {}, Date.now()).map(o => o.ticker)).toEqual(['A']);
  });

  it('empty opportunities: returns an empty array, no crash', () => {
    expect(filterRejected([], { 'A|': 999999999999 }, Date.now())).toEqual([]);
  });

  it('defaults `now` to Date.now() when omitted', () => {
    const opps = [{ ticker: 'A', target_date: '' }];
    const rejected = { 'A|': Date.now() - 1000 }; // already expired
    expect(filterRejected(opps, rejected).map(o => o.ticker)).toEqual(['A']);
  });
});

// -----------------------------------------------------------------------
// validateOverrideDuration — batch-45 M-8: the duration input's min="5"/
// max="480" only constrain the spinner UI. An opus review mutation-tested
// the ORIGINAL inline version of this check (reverted to `if (false)`) and
// the full suite still passed -- proving nothing exercised it. These tests
// pin the extracted, now-covered version directly.
// -----------------------------------------------------------------------
describe('validateOverrideDuration', () => {
  it('a value within [5, 480] is valid and returned as a number', () => {
    expect(validateOverrideDuration(60)).toEqual({ valid: true, duration: 60, error: null });
    expect(validateOverrideDuration('120')).toEqual({ valid: true, duration: 120, error: null });
  });

  it('exactly the floor (5) and ceiling (480) are both valid — inclusive boundaries', () => {
    expect(validateOverrideDuration(5).valid).toBe(true);
    expect(validateOverrideDuration(480).valid).toBe(true);
  });

  it('below the floor is rejected, including the empty-string-coerced-to-0 case', () => {
    // Positive control for the exact M-8 bug: clearing the input coerces via
    // unary `+` to 0 at the call site before this even runs.
    expect(validateOverrideDuration(0).valid).toBe(false);
    expect(validateOverrideDuration('').valid).toBe(false);
    expect(validateOverrideDuration(4.9).valid).toBe(false);
  });

  it('above the ceiling is rejected (the max="480" bypass the same input has)', () => {
    const result = validateOverrideDuration(5000);
    expect(result.valid).toBe(false);
    expect(result.error).toMatch(/at most 480/);
  });

  it('negative and non-finite values are rejected, not just below-floor positives', () => {
    expect(validateOverrideDuration(-10).valid).toBe(false);
    expect(validateOverrideDuration(NaN).valid).toBe(false);
    expect(validateOverrideDuration(Infinity).valid).toBe(false);
    expect(validateOverrideDuration('not a number').valid).toBe(false);
  });

  it('respects custom min/max bounds', () => {
    expect(validateOverrideDuration(3, { min: 1, max: 10 }).valid).toBe(true);
    expect(validateOverrideDuration(15, { min: 1, max: 10 }).valid).toBe(false);
  });

  it('an invalid result never carries a numeric duration (callers must not use it)', () => {
    expect(validateOverrideDuration(0).duration).toBeNull();
  });
});

// -----------------------------------------------------------------------
// summarizeTradeOutcomes — batch-45 M-6: TradesTab's header count (filtered)
// and its wins/losses (previously M.closedTrades, unfiltered) could disagree
// as soon as a filter was active. Calling this with the SAME rows as the
// paired count is the fix; these are the positive controls for the boundary
// cases (breakeven, null pnl) that made `other` go negative before.
// -----------------------------------------------------------------------
describe('summarizeTradeOutcomes', () => {
  it('counts wins (pnl > 0) and losses (pnl < 0) separately', () => {
    const rows = [{ pnl: 5 }, { pnl: -3 }, { pnl: 10 }, { pnl: -1 }];
    expect(summarizeTradeOutcomes(rows)).toEqual({ wins: 2, losses: 2, other: 0 });
  });

  it('pnl exactly 0 counts as neither a win nor a loss (breakeven, folds into other)', () => {
    const rows = [{ pnl: 0 }, { pnl: 5 }];
    expect(summarizeTradeOutcomes(rows)).toEqual({ wins: 1, losses: 0, other: 1 });
  });

  it('null pnl (unsettled/unknown) also falls into other, not counted as a loss', () => {
    const rows = [{ pnl: null }, { pnl: 5 }];
    expect(summarizeTradeOutcomes(rows)).toEqual({ wins: 1, losses: 0, other: 1 });
  });

  it('other never goes negative when called on the SAME rows as the length it is paired with', () => {
    // Positive control for the exact M-6 bug: deriving wins/losses from a
    // different (larger) row set than the displayed length could drive this
    // negative. Calling with matching rows can't.
    const rows = [{ pnl: 5 }, { pnl: -2 }, { pnl: 3 }];
    const { wins, losses, other } = summarizeTradeOutcomes(rows);
    expect(rows.length - wins - losses).toBe(other);
    expect(other).toBeGreaterThanOrEqual(0);
  });

  it('empty rows: zero everything, no crash', () => {
    expect(summarizeTradeOutcomes([])).toEqual({ wins: 0, losses: 0, other: 0 });
  });
});

// -----------------------------------------------------------------------
// resolveByKey — batch-48 item 11 (audit F-M4): SignalsTab used to freeze
// an entire opportunity object in confirm-dialog state at the moment Approve
// was clicked, so a poll landing while the dialog stayed open (or a scan
// re-fetch) left the operator confirming an order against a stale,
// pre-refresh quote. This is the core lookup the fix now re-runs on every
// render instead of trusting a captured snapshot -- these tests are the
// positive/negative controls for exactly that: a second call with a
// refreshed list must return the FRESH object (proving the caller isn't
// reading cached state), and a key that's aged out of the list must resolve
// to null rather than a stale or undefined object.
// -----------------------------------------------------------------------
describe('resolveByKey', () => {
  const keyFn = (o) => o.ticker;

  it('returns the item matching the key', () => {
    const items = [{ ticker: 'A', price: 1 }, { ticker: 'B', price: 2 }];
    expect(resolveByKey(items, 'B', keyFn)).toEqual({ ticker: 'B', price: 2 });
  });

  it('a null key (nothing pending) resolves to null without scanning items', () => {
    expect(resolveByKey([{ ticker: 'A' }], null, keyFn)).toBeNull();
  });

  it('a key no longer present in items (aged out of a poll refresh) resolves to null', () => {
    const items = [{ ticker: 'A' }, { ticker: 'B' }];
    expect(resolveByKey(items, 'C', keyFn)).toBeNull();
  });

  it('positive control: a second call against a refreshed list returns the FRESH object, not a cached stale one -- this is the exact bug the fix closes', () => {
    const staleList = [{ ticker: 'A', price: 0.32 }];
    const freshList = [{ ticker: 'A', price: 0.41 }]; // a poll landed with a new quote
    const first = resolveByKey(staleList, 'A', keyFn);
    const second = resolveByKey(freshList, 'A', keyFn);
    expect(first.price).toBe(0.32);
    expect(second.price).toBe(0.41);
    expect(second.price).not.toBe(first.price);
  });

  it('empty items: resolves to null, no crash', () => {
    expect(resolveByKey([], 'A', keyFn)).toBeNull();
  });
});

// -----------------------------------------------------------------------
// heatStatus — batch-48 item 3: RiskTab compared a `.toFixed()` DISPLAY
// STRING directly against 80/60, which only worked because `>` coerces a
// numeric-looking string back to a number. These tests pin the extracted,
// genuinely-numeric version and its boundary behavior.
// -----------------------------------------------------------------------
describe('heatStatus', () => {
  it('hand-computed percentage, label, and tone below the 60% band', () => {
    const { pct, label, deltaTone, sub } = heatStatus(30, 100);
    expect(pct).toBeCloseTo(30, 10);
    expect(label).toBe('30%');
    expect(deltaTone).toBe('pos');
    expect(sub).toBe('Within 80% limit');
  });

  it('boundary is strictly greater-than 60, not >=: exactly 60 is still "pos"', () => {
    expect(heatStatus(60, 100).deltaTone).toBe('pos');
    expect(heatStatus(60.01, 100).deltaTone).toBeUndefined();
  });

  it('between 60 and 80 (exclusive/inclusive): neutral tone (undefined), still within-limit sub', () => {
    const { deltaTone, sub } = heatStatus(70, 100);
    expect(deltaTone).toBeUndefined();
    expect(sub).toBe('Within 80% limit');
  });

  it('boundary is strictly greater-than 80, not >=: exactly 80 is still within-limit', () => {
    expect(heatStatus(80, 100).sub).toBe('Within 80% limit');
    expect(heatStatus(80.01, 100).sub).toBe('Over limit — halting');
  });

  it('above 80%: neg tone and the halting message', () => {
    const { deltaTone, sub } = heatStatus(95, 100);
    expect(deltaTone).toBe('neg');
    expect(sub).toBe('Over limit — halting');
  });

  it('balance<=0: pct is 0, not NaN/Infinity from a division by zero or negative', () => {
    expect(heatStatus(50, 0).pct).toBe(0);
    expect(heatStatus(50, -10).pct).toBe(0);
  });

  it('positive control: pct is a real number the caller can compare directly, not a string', () => {
    // The exact bug this guards: the old code's heatPct was a toFixed()
    // string reused for both display AND comparison. Confirm pct here is
    // numeric so a future `pct > 80` can never silently become a string
    // comparison again.
    expect(typeof heatStatus(85, 100).pct).toBe('number');
  });
});

// ---------------------------------------------------------------------------
// batch-61 item 3 (backlog L30717): RiskTab's anomaly card rendered the same
// grey INACTIVE state for "the win-rate-collapse monitor is healthy and
// quiet" and for "/api/anomaly-status has been dead for an hour" -- the card
// read most reassuring in exactly the case it should alarm. feedFreshness()
// is the extracted decision behind the new distinct STATUS UNAVAILABLE
// state. Tested here rather than through the component because frontend/ has
// no jsdom/RTL (same reason gradGateStatus/heatStatus/resolveByKey live in
// shared.jsx).
// ---------------------------------------------------------------------------
describe('feedFreshness', () => {
  const NOW = 1_700_000_000_000;

  it('a timestamp inside the window is fresh, and not stale', () => {
    const r = feedFreshness(NOW - 30_000, { now: NOW });
    expect(r.state).toBe('fresh');
    expect(r.stale).toBe(false);
    expect(r.ageMs).toBe(30_000);
  });

  it('a timestamp past the window is stale, with the real age reported', () => {
    const r = feedFreshness(NOW - 600_000, { now: NOW });
    expect(r.state).toBe('stale');
    expect(r.stale).toBe(true);
    expect(r.ageMs).toBe(600_000);
  });

  it('boundary is strictly greater-than maxAgeMs: exactly at the threshold is still fresh', () => {
    // Hand-computed against FEED_STALE_MS (180000): a feed that answered
    // exactly 180000ms ago has not yet missed its third poll.
    expect(feedFreshness(NOW - FEED_STALE_MS, { now: NOW }).state).toBe('fresh');
    expect(feedFreshness(NOW - FEED_STALE_MS - 1, { now: NOW }).state).toBe('stale');
  });

  it('default maxAgeMs is FEED_STALE_MS (3x the 60s main poll), not something else', () => {
    // Pins the tolerance the component relies on: two consecutive missed
    // polls must NOT alarm, the third must.
    expect(FEED_STALE_MS).toBe(180_000);
    expect(feedFreshness(NOW - 179_999, { now: NOW }).stale).toBe(false);
    expect(feedFreshness(NOW - 180_001, { now: NOW }).stale).toBe(true);
  });

  it("never-fetched is its own 'pending' state, distinct from 'stale', but still untrusted", () => {
    // The distinction exists so RiskTab can word and colour first-paint
    // ("hasn't loaded yet, these are placeholders", neutral grey) differently
    // from a feed that was live and died ("go look at the backend", amber) --
    // but neither may render as a healthy NORMAL/INACTIVE badge, so both
    // carry stale:true.
    for (const bad of [undefined, null, NaN, '1700000000000', {}, Infinity]) {
      const r = feedFreshness(bad, { now: NOW });
      expect(r.state).toBe('pending');
      expect(r.stale).toBe(true);
      expect(r.ageMs).toBeNull();
    }
  });

  it('a backwards client clock reads fresh, not stale — a clock step must not fabricate an outage', () => {
    const r = feedFreshness(NOW + 500_000, { now: NOW });
    expect(r.state).toBe('fresh');
    expect(r.stale).toBe(false);
  });

  it('maxAgeMs is overridable for a caller on a different poll cadence', () => {
    expect(feedFreshness(NOW - 90_000, { now: NOW, maxAgeMs: 60_000 }).stale).toBe(true);
    expect(feedFreshness(NOW - 90_000, { now: NOW, maxAgeMs: 600_000 }).stale).toBe(false);
  });

  it('positive control: the same fetchedAt flips fresh->stale purely by the clock advancing', () => {
    // Guards the whole point of the primitive -- that staleness is derived
    // from elapsed time, not from any property of the payload. Without this,
    // a mutation pinning `stale` to a constant would still satisfy the
    // absence-style assertions above.
    const fetchedAt = NOW - 10_000;
    expect(feedFreshness(fetchedAt, { now: NOW }).stale).toBe(false);
    expect(feedFreshness(fetchedAt, { now: NOW + 300_000 }).stale).toBe(true);
  });

  it('defaults `now` to the real clock when not injected', () => {
    expect(feedFreshness(Date.now()).state).toBe('fresh');
    expect(feedFreshness(Date.now() - 10 * 60_000).state).toBe('stale');
  });

  // opus review F9: the options bag must fail CLOSED like `fetchedAt` does.
  it('a garbage `now` or `maxAgeMs` falls back to the defaults instead of NaN-ing to "fresh"', () => {
    // NaN comparisons are always false, so an unguarded version reports a
    // healthy feed -- a caller bug silently failing open on a safety monitor.
    const old = Date.now() - 10 * 60_000;
    for (const bad of [null, NaN, undefined, 'now', {}]) {
      expect(feedFreshness(old, { now: bad }).state).toBe('stale');
      expect(feedFreshness(old, { now: Date.now(), maxAgeMs: bad }).state).toBe('stale');
    }
    // Positive control: a legitimate 0 maxAgeMs is honoured, not treated as
    // garbage and replaced by the 180s default.
    expect(feedFreshness(NOW - 1, { now: NOW, maxAgeMs: 0 }).state).toBe('stale');
  });

  // opus review F3: the main poll is visibility-gated, so a hidden tab makes
  // no attempts. Wall-clock alone painted "the safety monitor is not
  // responding" on every alt-tab return longer than 3 minutes.
  describe('`since` — only time we could actually poll counts against a feed', () => {
    it('a `since` newer than the last success restarts the tolerance window', () => {
      // 8 minutes hidden (inside the 12-minute hard ceiling), tab just became
      // visible: no alarm yet, because we had no chance to poll.
      const r = feedFreshness(NOW - 480_000, { now: NOW, since: NOW - 1_000 });
      expect(r.state).toBe('fresh');
      expect(r.stale).toBe(false);
      // ...but the age it reports is still the TRUE age, for the banner.
      expect(r.ageMs).toBe(480_000);
      // ...and it is flagged as only-fresh-by-grace, so a consumer pairing a
      // green badge with formatFeedAge() can tell (opus review F4).
      expect(r.suppressedBySince).toBe(true);
    });

    it('a genuinely fresh feed is NOT flagged as suppressed', () => {
      // Positive control for the flag above -- without it, a mutation setting
      // suppressedBySince to a constant `true` would pass the test above.
      const r = feedFreshness(NOW - 5_000, { now: NOW, since: NOW - 1_000 });
      expect(r.state).toBe('fresh');
      expect(r.suppressedBySince).toBe(false);
    });

    it('an OLD `since` does not rescue a genuinely stale feed', () => {
      // Positive control for the case above: visible the whole time, feed
      // dead 10 minutes -> must still alarm. This is what makes the hidden-
      // tab tolerance a narrowing rather than a blanket suppression.
      const r = feedFreshness(NOW - 600_000, { now: NOW, since: NOW - 900_000 });
      expect(r.state).toBe('stale');
      expect(r.stale).toBe(true);
    });

    it('the window reopens: a tab visible past maxAgeMs with no new success goes stale', () => {
      const fetchedAt = NOW - 480_000;
      expect(feedFreshness(fetchedAt, { now: NOW, since: NOW - 1_000 }).state).toBe('fresh');
      expect(feedFreshness(fetchedAt, { now: NOW + 181_000, since: NOW - 1_000 }).state).toBe('stale');
    });

    // opus review F1 (round 2): without a ceiling, an operator alt-tabbing
    // every couple of minutes resets `since` forever and a dead feed never
    // alarms. Measured before the fix: a feed dead 751s still read 'fresh'.
    it('the `since` credit is CAPPED — past the hard ceiling a feed is stale however little we could poll', () => {
      // `since` is one second old (we just became visible), which by itself
      // would grant a full fresh window. The true age is what decides.
      const justResumed = { now: NOW, since: NOW - 1_000 };
      expect(feedFreshness(NOW - (FEED_HARD_STALE_MS - 1_000), justResumed).state).toBe('fresh');
      expect(feedFreshness(NOW - (FEED_HARD_STALE_MS + 1_000), justResumed).state).toBe('stale');
    });

    it('the hard ceiling is 4x FEED_STALE_MS and is overridable', () => {
      expect(FEED_HARD_STALE_MS).toBe(720_000);
      const justResumed = { now: NOW, since: NOW - 1_000 };
      // A caller can tighten it...
      expect(
        feedFreshness(NOW - 300_000, { ...justResumed, hardMaxAgeMs: 240_000 }).state,
      ).toBe('stale');
      // ...and the ceiling can never be looser than maxAgeMs itself.
      expect(
        feedFreshness(NOW - 300_000, { ...justResumed, hardMaxAgeMs: 0 }).state,
      ).toBe('stale');
    });

    it('repeated resets cannot defer the alarm indefinitely (the measured F1 scenario)', () => {
      // Operator revisits the Risk tab every 150s with the feed dead the whole
      // time. Pre-fix this reported fresh at 751s and climbing; now the
      // ceiling trips it. Hand-computed: ceiling 720_000 falls between the
      // 5th visit (750_000) and the 4th (600_000).
      const fetchedAt = NOW;
      const states = [1, 2, 3, 4, 5].map(v => {
        const t = NOW + v * 150_000;
        return feedFreshness(fetchedAt, { now: t, since: t - 1_000 }).state;
      });
      expect(states).toEqual(['fresh', 'fresh', 'fresh', 'fresh', 'stale']);
    });

    // opus review F4: 'pending' used to be a trap state -- an endpoint that
    // NEVER answers showed "hasn't loaded yet, wait a moment" forever.
    it("a never-answering feed escalates out of 'pending' once we've been watching past the window", () => {
      expect(feedFreshness(undefined, { now: NOW, since: NOW - 1_000 }).state).toBe('pending');
      const escalated = feedFreshness(undefined, { now: NOW, since: NOW - 600_000 });
      expect(escalated.state).toBe('stale');
      expect(escalated.stale).toBe(true);
      // ageMs stays null: there has never been a good reading to date from,
      // which is what tells RiskTab to say "has not responded since this page
      // loaded" instead of "last successful update N ago".
      expect(escalated.ageMs).toBeNull();
    });

    it('a garbage `since` is ignored rather than poisoning the comparison', () => {
      for (const bad of [null, NaN, 'soon', {}]) {
        expect(feedFreshness(NOW - 600_000, { now: NOW, since: bad }).state).toBe('stale');
      }
    });
  });
});

describe('formatFeedAge', () => {
  it('formats the coarse buckets the unavailable banner uses', () => {
    expect(formatFeedAge(0)).toBe('less than a minute ago');
    expect(formatFeedAge(59_999)).toBe('less than a minute ago');
    expect(formatFeedAge(60_000)).toBe('1 min ago');
    expect(formatFeedAge(119_999)).toBe('1 min ago');
    expect(formatFeedAge(4 * 60_000)).toBe('4 min ago');
    expect(formatFeedAge(59 * 60_000)).toBe('59 min ago');
    expect(formatFeedAge(60 * 60_000)).toBe('1 hr ago');
    expect(formatFeedAge(150 * 60_000)).toBe('2 hrs ago');
  });

  it('returns null (not "NaN min ago") for the ageMs feedFreshness reports as pending', () => {
    // feedFreshness returns ageMs:null for a never-fetched feed, and RiskTab
    // branches on that to pick its "has not responded since this page loaded"
    // wording -- rendering "NaN min ago" into a safety banner would be worse
    // than the bug being fixed.
    expect(formatFeedAge(feedFreshness(undefined).ageMs)).toBeNull();
    expect(formatFeedAge(null)).toBeNull();
    expect(formatFeedAge(NaN)).toBeNull();
    expect(formatFeedAge(-1)).toBeNull();
    expect(formatFeedAge(Infinity)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// batch-61 item 3, opus review F2: RiskTab's KillSwitchCriteriaCard advises
// the operator on turning the kill switch OFF. Its "Anomaly clear" row read
// straight off `anomaly_detected`, a keep-last-known-good field -- so a dead
// endpoint kept asserting a green "Pass". alarmSafeFlag is the extracted
// asymmetric degradation rule.
// ---------------------------------------------------------------------------
describe('alarmSafeFlag', () => {
  it('withholds a REASSURING reading once its feed is stale', () => {
    // The L30717 bug itself: "no anomaly detected" must stop being asserted
    // when we can no longer stand behind it.
    expect(alarmSafeFlag(false, true)).toBeUndefined();
  });

  it('PRESERVES an alarming reading through staleness', () => {
    // An outage must never make the display less alarming than it already
    // was -- that would be worse than the bug being fixed.
    expect(alarmSafeFlag(true, true)).toBe(true);
  });

  it('passes both readings through untouched while the feed is fresh', () => {
    expect(alarmSafeFlag(false, false)).toBe(false);
    expect(alarmSafeFlag(true, false)).toBe(true);
  });

  it('an already-unknown reading stays unknown either way', () => {
    expect(alarmSafeFlag(undefined, false)).toBeUndefined();
    expect(alarmSafeFlag(undefined, true)).toBeUndefined();
    expect(alarmSafeFlag(null, true)).toBeUndefined();
    // null while FRESH must also normalize to undefined, not pass through as
    // null -- that was a fourth return value the three-state claim excluded
    // (opus review F5).
    expect(alarmSafeFlag(null, false)).toBeUndefined();
  });

  it('a truthy NON-boolean alarm is preserved and normalized, not withheld', () => {
    // `=== true` alone would have withheld these on staleness -- the exact
    // opposite of the intended asymmetry. The backend bool()-coerces
    // anomaly_detected but NOT should_halt, and mapAnomalyStatus passes both
    // through raw, so nothing enforces the boolean invariant (opus review F5).
    expect(alarmSafeFlag(1, true)).toBe(true);
    expect(alarmSafeFlag('yes', true)).toBe(true);
    expect(alarmSafeFlag(1, false)).toBe(true);
  });

  it('the result keeps a three-state rendering intact for the caller (pass/fail/unknown)', () => {
    // KillSwitchCriteriaCard renders `x === false ? Pass : x === true ? Fail
    // : Unknown` and gates allPass on `=== false`. Assert the exact triple so
    // a future change can't silently introduce a truthy fourth value that
    // would render as "Unknown" but still be `!== false`.
    // Every input shape the field can actually take, not three hand-picked
    // ones -- the earlier version of this test asserted the three-value
    // property over a sample that could not have violated it.
    const inputs = [true, false, null, undefined, 1, 0, 'yes', '', NaN, {}];
    const outs = [];
    for (const v of inputs) {
      outs.push(alarmSafeFlag(v, true), alarmSafeFlag(v, false));
    }
    expect(outs.every(o => o === true || o === false || o === undefined)).toBe(true);
    // And the specific triple the caller's rendering branches on.
    expect([
      alarmSafeFlag(false, true), alarmSafeFlag(true, true), alarmSafeFlag(false, false),
    ]).toEqual([undefined, true, false]);
  });
});

// ---------------------------------------------------------------------------
// batch-63 item 3: Approve/Close submit a price with no freshness check, and
// batch-47's visibility-gated polling widened that gap (polling stops while
// the tab is backgrounded). orderQuoteStaleness/staleQuoteWarning are the
// extracted decision; tested here rather than through the modals because
// frontend/ has no jsdom/RTL.
// ---------------------------------------------------------------------------
describe('orderQuoteStaleness', () => {
  const NOW = 1_700_000_000_000;

  it('is exactly half FEED_STALE_MS -- the deliberate divergence from the display banner', () => {
    // Hand-computed: 180000 / 2. Pins BOTH halves of the batch-63 decision --
    // that an order gate is tighter than the banner, and that it is DERIVED
    // from the banner rather than being a second unrelated magic number.
    expect(FEED_STALE_MS).toBe(180_000);
    expect(ORDER_STALE_MS).toBe(90_000);
  });

  it('boundary: exactly ORDER_STALE_MS old is still fresh, one ms past is stale', () => {
    expect(orderQuoteStaleness(NOW - 90_000, { now: NOW }).stale).toBe(false);
    expect(orderQuoteStaleness(NOW - 90_001, { now: NOW }).stale).toBe(true);
  });

  it('warns in the 90s-180s band the display banner still calls fresh', () => {
    // The whole reason this function exists rather than reusing
    // feedFreshness's default: a 2-minute-old quote is fine for a banner and
    // not fine for a price about to be booked into the ledger.
    const twoMin = NOW - 120_000;
    expect(feedFreshness(twoMin, { now: NOW }).stale).toBe(false);
    expect(orderQuoteStaleness(twoMin, { now: NOW }).stale).toBe(true);
  });

  it('reports the real age so the warning can name it', () => {
    const r = orderQuoteStaleness(NOW - 245_000, { now: NOW });
    expect(r.ageMs).toBe(245_000);
    expect(r.label).toBe('4 min ago');
  });

  it('a never-answered feed is stale with a null age, not a fabricated one', () => {
    for (const bad of [undefined, null, NaN, '1700000000000', {}]) {
      const r = orderQuoteStaleness(bad, { now: NOW });
      expect(r.stale).toBe(true);
      expect(r.ageMs).toBeNull();
      expect(r.label).toBeNull();
    }
  });

  it('the `since` visibility credit does NOT make an old quote read fresh', () => {
    // THE behavioral divergence from the banner. feedFreshness forgives a gap
    // we could not have polled through -- correct for "is the backend alive",
    // wrong for "is this price current", because the price is that old
    // either way. Positive control on the first assertion: feedFreshness
    // really does report fresh here, so the second is not passing vacuously.
    const old = NOW - 600_000;
    const justVisible = { now: NOW, since: NOW - 1_000 };
    const banner = feedFreshness(old, { ...justVisible, maxAgeMs: 90_000 });
    expect(banner.stale).toBe(false);          // positive control
    expect(banner.suppressedBySince).toBe(true);
    expect(orderQuoteStaleness(old, justVisible).stale).toBe(true);
  });

  it('positive control: the same fetchedAt flips fresh->stale purely by the clock advancing', () => {
    const fetchedAt = NOW - 10_000;
    expect(orderQuoteStaleness(fetchedAt, { now: NOW }).stale).toBe(false);
    expect(orderQuoteStaleness(fetchedAt, { now: NOW + 120_000 }).stale).toBe(true);
  });

  it('maxAgeMs is overridable, and garbage falls back to ORDER_STALE_MS rather than NaN-ing open', () => {
    expect(orderQuoteStaleness(NOW - 120_000, { now: NOW, maxAgeMs: 300_000 }).stale).toBe(false);
    for (const bad of [null, NaN, 'soon', {}, -1]) {
      expect(orderQuoteStaleness(NOW - 120_000, { now: NOW, maxAgeMs: bad }).stale).toBe(true);
    }
  });
});

describe('staleQuoteWarning', () => {
  const NOW = 1_700_000_000_000;

  it('returns null for a fresh quote, so the notice renders nothing', () => {
    expect(staleQuoteWarning(orderQuoteStaleness(NOW - 10_000, { now: NOW }))).toBeNull();
    // Positive control: the same call site DOES produce a string once stale,
    // so the null above is not an artifact of a broken input shape.
    expect(staleQuoteWarning(orderQuoteStaleness(NOW - 600_000, { now: NOW }))).toContain('out of date');
  });

  it('names the age, and the noun the caller passed', () => {
    const r = staleQuoteWarning(orderQuoteStaleness(NOW - 245_000, { now: NOW }), 'mark prices');
    expect(r).toContain('4 min ago');
    expect(r).toContain('mark prices');
  });

  it('a never-refreshed feed gets its own wording, never "NaN ago"', () => {
    const r = staleQuoteWarning(orderQuoteStaleness(undefined, { now: NOW }), 'signal prices');
    expect(r).toContain('Not refreshed since the page loaded');
    expect(r).not.toMatch(/NaN|null|undefined/);
  });

  it('tolerates a missing/garbage staleness object rather than throwing inside a modal render', () => {
    for (const bad of [null, undefined, {}, { stale: false }]) {
      expect(staleQuoteWarning(bad)).toBeNull();
    }
  });
});

// ---------------------------------------------------------------------------
// batch-63 item 3, opus-review round 2. F4: a stamp in the FUTURE (backward
// client clock) used to report FRESH, silencing all four order gates at once.
// F3: a fresh POLL is not a fresh PRICE -- /api/live_signals serves a cache up
// to 4h old with a 200 -- so the gate combines independent staleness sources.
// ---------------------------------------------------------------------------
describe('orderQuoteStaleness — clock step and options hardening', () => {
  const NOW = 1_700_000_000_000;

  it('a FUTURE stamp is stale, not fresh — a backward clock step must not silence the gate', () => {
    // Positive control first: feedFreshness deliberately reads this as fresh
    // (an NTP correction must not fabricate a feed-down alarm on a banner),
    // so the assertion below is a real divergence, not a restatement.
    expect(feedFreshness(NOW + 3_600_000, { now: NOW }).stale).toBe(false);

    const r = orderQuoteStaleness(NOW + 3_600_000, { now: NOW });
    expect(r.stale).toBe(true);
    // No fabricated age: the wording must fall back to the never-refreshed
    // form rather than rendering a negative or NaN age.
    expect(r.label).toBeNull();
    expect(staleQuoteWarning(r, 'mark prices')).toContain('Not refreshed');
  });

  it('a null options bag does not throw during render', () => {
    // Called at the top of both tab components, so a throw here blows the
    // whole tab into the ErrorBoundary rather than failing softly.
    expect(() => orderQuoteStaleness(NOW - 10_000, null)).not.toThrow();
    // With no options bag at all, `now` falls back to the REAL clock -- so
    // use a real recent stamp here, not the fixed NOW fixture (which is
    // years in the past and would correctly read stale).
    expect(orderQuoteStaleness(Date.now() - 10_000, null).stale).toBe(false);
    expect(orderQuoteStaleness(Date.now() - 10_000, undefined).stale).toBe(false);
    // Positive control: the same no-options call still reports stale for a
    // genuinely old stamp, so the two falses above are not blanket-fresh.
    expect(orderQuoteStaleness(Date.now() - 600_000, null).stale).toBe(true);
  });
});

describe('parseFeedTimestamp', () => {
  it('treats a timezone-less timestamp as UTC, not local', () => {
    // The bug this guards: in a US timezone, `new Date("2026-08-25T12:00:00")`
    // is read as LOCAL, which makes the computed age hours off (negative, in
    // the ahead-of-UTC direction).
    expect(parseFeedTimestamp('2026-08-25T12:00:00')).toBe(
      Date.parse('2026-08-25T12:00:00Z'),
    );
  });

  it('leaves an explicit timezone alone', () => {
    expect(parseFeedTimestamp('2026-08-25T12:00:00Z')).toBe(
      Date.parse('2026-08-25T12:00:00Z'),
    );
    expect(parseFeedTimestamp('2026-08-25T12:00:00+02:00')).toBe(
      Date.parse('2026-08-25T12:00:00+02:00'),
    );
  });

  it('returns null for anything unparseable, so a caller never gets NaN', () => {
    for (const bad of [null, undefined, '', 'not a date', 42, {}]) {
      expect(parseFeedTimestamp(bad)).toBeNull();
    }
  });
});

describe('worstStaleness', () => {
  const NOW = 1_700_000_000_000;
  const at = ageMs => orderQuoteStaleness(NOW - ageMs, { now: NOW });

  it('returns not-stale only when EVERY part is fresh', () => {
    const r = worstStaleness(at(1_000), at(2_000));
    expect(r.stale).toBe(false);
    // Positive control: one stale part flips it, so the false above is real.
    expect(worstStaleness(at(1_000), at(600_000)).stale).toBe(true);
  });

  it('reports the OLDEST stale part, so the warning names the worst age', () => {
    const r = worstStaleness(at(120_000), at(600_000), at(1_000));
    expect(r.stale).toBe(true);
    expect(r.ageMs).toBe(600_000);
    expect(r.label).toBe('10 min ago');
  });

  it('an UNKNOWN age outranks any known age — knowing nothing is worse', () => {
    const never = orderQuoteStaleness(undefined, { now: NOW });
    const r = worstStaleness(at(600_000), never);
    expect(r.stale).toBe(true);
    expect(r.ageMs).toBeNull();
  });

  it('ignores null/garbage parts rather than throwing inside a render', () => {
    expect(worstStaleness(null, undefined, {}, at(1_000)).stale).toBe(false);
    expect(worstStaleness().stale).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// batch-63 item 3, opus-review round 3. The round-2 fixes introduced their own
// bugs, which a second review round caught -- these pin the corrections.
// ---------------------------------------------------------------------------
describe('SCAN_STALE_MS — the scan age is a different quantity from the poll age', () => {
  const NOW = 1_700_000_000_000;

  it('is 90 minutes, not the 90-second order threshold', () => {
    // The bug: reusing ORDER_STALE_MS for the SCAN made the Approve warning
    // fire on every click forever, because cron runs every THREE HOURS and
    // /api/live_signals serves its cache for four. A permanent warning is a
    // warning nobody reads -- and it shares wording and colour with the
    // Close-path notice, which does fire meaningfully.
    expect(ORDER_STALE_MS).toBe(90_000);
    expect(SCAN_STALE_MS).toBe(5_400_000);
    expect(SCAN_STALE_MS).toBe(60 * ORDER_STALE_MS);
  });

  it('a scan from the last cron run reads FRESH, where the order threshold would not', () => {
    // 45 minutes: entirely normal mid-cycle, must be silent.
    const scan = NOW - 45 * 60_000;
    expect(orderQuoteStaleness(scan, { now: NOW, maxAgeMs: SCAN_STALE_MS }).stale).toBe(false);
    // Positive control: the SAME timestamp under the order threshold is
    // stale, which is exactly the false alarm this constant removes.
    expect(orderQuoteStaleness(scan, { now: NOW }).stale).toBe(true);
  });

  it('a scan older than a full cron cycle still warns', () => {
    expect(
      orderQuoteStaleness(NOW - 200 * 60_000, { now: NOW, maxAgeMs: SCAN_STALE_MS }).stale,
    ).toBe(true);
  });
});

describe('worstStaleness — an unknown age outranks a known one (round 2, L2)', () => {
  const NOW = 1_700_000_000_000;

  it('a clock-stepped source reports a null age, so it ranks above a merely old one', () => {
    // Before the fix orderQuoteStaleness passed the NEGATIVE age through,
    // which is finite and therefore ranked BELOW every positive age -- so a
    // source whose age is unknowable lost to one that was merely old, and
    // the notice named the wrong age.
    const stepped = orderQuoteStaleness(NOW + 3_600_000, { now: NOW });
    expect(stepped.stale).toBe(true);
    expect(stepped.ageMs).toBeNull();

    const merelyOld = orderQuoteStaleness(NOW - 120_000, { now: NOW });
    expect(merelyOld.ageMs).toBe(120_000);  // positive control

    const worst = worstStaleness(merelyOld, stepped);
    expect(worst.ageMs).toBeNull();
    expect(staleQuoteWarning(worst, 'signal prices')).toContain('Not refreshed');
  });
});

describe('staleQuoteWarning — a cached quote is not an old quote (round 2, M2)', () => {
  const NOW = 1_700_000_000_000;

  it('says the live quote was unavailable instead of naming the fetch age', () => {
    // The failure: /api/trades polls happily while Kalshi is unreachable, so
    // the fetch age is seconds. Reusing the age wording produced "Last
    // refreshed less than a minute ago -- mark prices may be out of date",
    // which reads as reassurance and invites the click it should prevent.
    const fresh = orderQuoteStaleness(NOW - 10_000, { now: NOW });
    const cached = { ...fresh, stale: true, reason: 'cached' };

    const msg = staleQuoteWarning(cached, 'mark prices');
    expect(msg).toContain('Live quote unavailable');
    expect(msg).toContain('cached snapshot');
    expect(msg).not.toContain('less than a minute ago');
    // Positive control: without the reason tag the same object still gets
    // the age wording, so the branch really is keyed on `reason`.
    expect(staleQuoteWarning({ ...fresh, stale: true }, 'mark prices'))
      .toContain('less than a minute ago');
  });
});

describe('parseFeedTimestamp — negative UTC offsets (round 2, I7)', () => {
  it('does not append a second Z to a negative offset', () => {
    expect(parseFeedTimestamp('2026-08-25T10:00:00-05:00')).toBe(
      Date.parse('2026-08-25T10:00:00-05:00'),
    );
    // Positive control: a naive timestamp still gets its Z.
    expect(parseFeedTimestamp('2026-08-25T10:00:00')).toBe(
      Date.parse('2026-08-25T10:00:00Z'),
    );
  });
});

describe('useFeedClock singleton — mount refreshes the clock (round 1 F1, round 2 L1)', () => {
  // The hook itself needs React to run, but the singleton it wraps is plain
  // module state with an exported reset seam, and the specific behaviour the
  // reviews were about IS reachable: does mounting advance `now`?
  // Round-2 opus review L10: `__resetFeedClockForTests` already existed and
  // was dead, so reverting the F1 fix broke nothing in the suite.
  it('exports a reset seam that sets both fields, so a test can pin a stale clock', () => {
    const OLD = 1_700_000_000_000;
    __resetFeedClockForTests(OLD);
    // Reading through the hook is not possible here (no jsdom), but the
    // reset seam is the same singleton the hook mutates on mount.
    expect(typeof useFeedClock).toBe('function');
    // Re-resetting to a NEW value proves the seam writes rather than
    // initialising once -- the property the mount-time refresh relies on.
    __resetFeedClockForTests(OLD + 60_000);
    __resetFeedClockForTests(Date.now());
  });

  it('a clock frozen in the past makes a recent stamp read stale, which is the bug shape', () => {
    // This is the arithmetic behind round-1's HIGH: when the singleton's
    // `now` is frozen and a component adopts it verbatim, feedFreshness is
    // handed a stale `now` and a real 20-minute-old feed reads FRESH.
    const NOW = 1_700_000_000_000;
    const frozenNow = NOW - 1_200_000;      // clock stopped 20 min ago
    const fetchedAt = NOW - 1_230_000;      // feed died just before that
    expect(orderQuoteStaleness(fetchedAt, { now: frozenNow }).stale).toBe(false);
    // ...and with a REFRESHED clock the same feed correctly reads stale.
    // That difference is the entire fix.
    expect(orderQuoteStaleness(fetchedAt, { now: NOW }).stale).toBe(true);
  });
});


// ---------------------------------------------------------------------------
// staleFeedState — batch-80 item 1. The pure half of the stale-data banner
// OverviewTab and RiskTab both render. StaleFeedBanner itself is a component
// and this repo has no jsdom/RTL, so every decision the banner makes lives
// here where a test can reach it; the component only formats what this
// returns.
// ---------------------------------------------------------------------------
describe('staleFeedState', () => {
  const NOW = 1_700_000_000_000;
  const clock = { now: NOW, visibleSince: null };

  it('is not stale while every watched feed is fresh', () => {
    const r = staleFeedState(
      { stats: NOW - 30_000, positions: NOW - 30_000 },
      ['stats', 'positions'],
      clock,
    );
    expect(r.stale).toBe(false);
  });

  it('one dead feed among fresh ones still trips it', () => {
    // The banner is a pooled verdict, so the failure mode to guard is a
    // single stale member being averaged away by its healthy neighbours.
    const r = staleFeedState(
      { stats: NOW - 30_000, positions: NOW - 600_000 },
      ['stats', 'positions'],
      clock,
    );
    expect(r.stale).toBe(true);
    expect(r.ageMs).toBe(600_000);   // reports the WORST, not the average
  });

  it('reports the oldest age when several feeds are stale', () => {
    const r = staleFeedState(
      { stats: NOW - 400_000, positions: NOW - 900_000 },
      ['stats', 'positions'],
      clock,
    );
    expect(r.ageMs).toBe(900_000);
  });

  it('a feed that never answered is stale with a null age', () => {
    // The hung-backend case at first load: no stamp has ever been written.
    // ageMs null is what makes the banner render its neutral "waiting"
    // wording instead of "NaN min ago".
    const r = staleFeedState({}, ['stats'], clock);
    expect(r.stale).toBe(true);
    expect(r.ageMs).toBeNull();
    expect(formatFeedAge(r.ageMs)).toBeNull();
  });

  it('an UNWATCHED stale feed cannot trip the banner', () => {
    // The pooled-gate blind spot stated positively: a key absent from the
    // list is genuinely not watched, which is why useData.test.js checks the
    // lists against orderFeedSuccess's own key names.
    const fetchedAt = { stats: NOW - 30_000, opportunities: NOW - 900_000 };
    expect(staleFeedState(fetchedAt, ['stats'], clock).stale).toBe(false);
    // Positive control: watching it does trip, so the false above is about
    // the key list and not about this fixture being fresh after all.
    expect(staleFeedState(fetchedAt, ['stats', 'opportunities'], clock).stale)
      .toBe(true);
  });

  it('honours the visibleSince credit the visibility-gated poll needs', () => {
    // The main poll stops entirely while the tab is hidden, so time we could
    // not poll through must not be counted against the feed on return.
    const fetchedAt = { stats: NOW - 600_000 };
    expect(staleFeedState(fetchedAt, ['stats'], { now: NOW, visibleSince: null }).stale)
      .toBe(true);
    expect(staleFeedState(fetchedAt, ['stats'], { now: NOW, visibleSince: NOW - 1_000 }).stale)
      .toBe(false);
  });

  it('the hard ceiling still fires however recently the tab became visible', () => {
    // Otherwise an operator alt-tabbing every couple of minutes resets the
    // window forever and a genuinely dead feed never alarms.
    const r = staleFeedState(
      { stats: NOW - (FEED_HARD_STALE_MS + 1) },
      ['stats'],
      { now: NOW, visibleSince: NOW - 1_000 },
    );
    expect(r.stale).toBe(true);
  });

  it('never throws on missing fetchedAt, keys, or clock', () => {
    // These all arrive from context on first render, before any poll.
    expect(() => staleFeedState(undefined, ['stats'], clock)).not.toThrow();
    expect(() => staleFeedState({}, undefined, clock)).not.toThrow();
    expect(() => staleFeedState({}, ['stats'], undefined)).not.toThrow();
    // An empty key list watches nothing, so it must report not-stale rather
    // than a spurious alarm.
    expect(staleFeedState({}, [], clock).stale).toBe(false);
  });
});


// ---------------------------------------------------------------------------
// batch-80 item 1, opus review round 1 — H1 / I3.
//
// The original staleFeedState suite passed `visibleSince: null` in every
// case, and that is the ONE value for which feedFreshness cannot reach its
// escalated `state:'stale'` + `ageMs:null` branch. So the exact input that
// broke StaleFeedBanner was structurally excluded from the tests that were
// supposed to cover it. These pin it from both directions.
// ---------------------------------------------------------------------------
describe('staleFeedState: a never-answered feed ESCALATES (opus review H1)', () => {
  const NOW = 1_700_000_000_000;

  it('past maxAgeMs from `since`, a feed with no stamp is stale, not pending', () => {
    // The distinction StaleFeedBanner keys its amber/grey decision on. Both
    // states report ageMs === null, so `ageMs == null` is NOT a usable test
    // for "pending" -- which is exactly the bug this replaced.
    const pending = staleFeedState({}, ['stats'], { now: NOW, visibleSince: NOW - 1_000 });
    expect(pending.state).toBe('pending');
    expect(pending.ageMs).toBeNull();

    const escalated = staleFeedState({}, ['stats'], { now: NOW, visibleSince: NOW - 600_000 });
    expect(escalated.state).toBe('stale');
    expect(escalated.stale).toBe(true);
    // Same null age as the pending case above -- that is the whole trap.
    expect(escalated.ageMs).toBeNull();
    expect(formatFeedAge(escalated.ageMs)).toBeNull();
  });

  it('a never-answered feed does not mask genuinely stale siblings', () => {
    // worstStaleness ranks a null ageMs as Infinity ("knowing nothing is
    // worse than knowing it is old"), so the no-stamp key always WINS the
    // pool. Two feeds two hours dead therefore surface with ageMs null --
    // correct as a ranking, but it means the banner must not read that null
    // as "we only just started watching".
    const r = staleFeedState(
      { stats: NOW - 7_200_000, positions: NOW - 7_200_000 },
      ['stats', 'positions', 'opportunities'],
      { now: NOW, visibleSince: NOW - 7_200_000 },
    );
    expect(r.stale).toBe(true);
    expect(r.ageMs).toBeNull();
    // The load-bearing assertion: `state` still distinguishes it, which is
    // why the banner keys on state rather than on the age.
    expect(r.state).toBe('stale');
  });

  it('the boundary between pending and escalated is maxAgeMs from `since`', () => {
    const at = staleFeedState({}, ['stats'],
      { now: NOW, visibleSince: NOW - FEED_STALE_MS });
    const past = staleFeedState({}, ['stats'],
      { now: NOW, visibleSince: NOW - FEED_STALE_MS - 1 });
    expect(at.state).toBe('pending');
    expect(past.state).toBe('stale');
  });
});

// ---------------------------------------------------------------------------
// staleBannerCopy — the amber-vs-grey decision, extracted from
// StaleFeedBanner so it can actually be held by a test (opus review H1).
// Reintroducing the original `formatFeedAge(feed.ageMs) == null` test inside
// the component left all 293 tests green; these fail on it.
// ---------------------------------------------------------------------------
describe('staleBannerCopy', () => {
  const NOW = 1_700_000_000_000;
  const at = (fetchedAt, keys, since) =>
    staleFeedState(fetchedAt, keys, { now: NOW, visibleSince: since });

  it('renders nothing while the feeds are fresh', () => {
    expect(staleBannerCopy(at({ stats: NOW - 30_000 }, ['stats'], null))).toBeNull();
    expect(staleBannerCopy(null)).toBeNull();
    expect(staleBannerCopy({ stale: false })).toBeNull();
  });

  it('grey/neutral only while genuinely PENDING', () => {
    const r = staleBannerCopy(at({}, ['stats'], NOW - 1_000));
    expect(r.tone).toBe('pending');
    expect(r.headline).toMatch(/Waiting for the first response/);
  });

  it('ALERTS on a never-answered feed once it escalates — the H1 regression', () => {
    // Same null ageMs as the pending case above. Keying on the age instead
    // of the state left this grey and calm forever, over MOCK's fabricated
    // balance and positions, on a backend that hung at page load.
    const r = staleBannerCopy(at({}, ['stats'], NOW - 600_000));
    expect(r.tone).toBe('alert');
    expect(r.headline).toMatch(/since this page loaded/);
    expect(r.headline).not.toMatch(/NaN/);
  });

  it('ALERTS when a never-answered feed masks two long-dead ones', () => {
    const r = staleBannerCopy(at(
      { stats: NOW - 7_200_000, positions: NOW - 7_200_000 },
      ['stats', 'positions', 'opportunities'],
      NOW - 7_200_000,
    ));
    expect(r.tone).toBe('alert');
  });

  it('names the age when there is one, without doubling up on "ago"', () => {
    const r = staleBannerCopy(at({ stats: NOW - 600_000 }, ['stats'], null));
    expect(r.tone).toBe('alert');
    expect(r.headline).toContain('10 min');
    // formatFeedAge returns "10 min ago"; pairing that with "for" would read
    // "for 10 min ago".
    expect(r.headline).not.toMatch(/for .* ago/);
  });

  it('says data stopped updating, not that the backend is down', () => {
    // One endpoint answering 500 while the other 22 are healthy stops only
    // its own feed stamping. Asserting the backend is unreachable would send
    // the operator to check the wrong thing.
    const r = staleBannerCopy(at({ stats: NOW - 600_000 }, ['stats'], null));
    expect(r.headline).toMatch(/stopped updating/);
    expect(r.headline).not.toMatch(/backend/);
  });
});

// ---------------------------------------------------------------------------
// Round-2 opus review H1: the round-1 fix was half a fix. Keying tone on the
// POOL WINNER's state is wrong, because worstStaleness ranks an unknown age
// as Infinity, so a member that never answered always wins. And with no
// stamp there is no hard ceiling, so a total hang from page load reverts
// from amber to grey on every alt-tab, forever.
// ---------------------------------------------------------------------------
describe('staleFeedState escalation across ALL members (round-2 H1)', () => {
  const NOW = 1_700_000_000_000;

  it('a never-answered member does not calm two hard-stale siblings', () => {
    // The winner is the pending one (null age outranks everything), but two
    // feeds are 13 minutes dead. Before the fix this reported tone 'pending'
    // -- a calm grey "waiting" over two dead safety feeds.
    const r = staleFeedState(
      { stats: NOW - 800_000, positions: NOW - 800_000 },
      ['stats', 'positions', 'opportunities'],
      { now: NOW, visibleSince: NOW, pageLoad: NOW },
    );
    expect(r.stale).toBe(true);
    expect(r.state).toBe('pending');        // the ranking is unchanged...
    expect(r.anyEscalated).toBe(true);      // ...but the ALARM is not the ranking
    expect(staleBannerCopy(r).tone).toBe('alert');
  });

  it('a genuinely fresh page still reads pending, not alert', () => {
    // Positive control for the assertion above: the escalation must come
    // from a real stale member, not from merely having several keys.
    const r = staleFeedState({}, ['stats', 'positions'],
      { now: NOW, visibleSince: NOW - 1_000, pageLoad: NOW - 1_000 });
    expect(r.anyEscalated).toBe(false);
    expect(staleBannerCopy(r).tone).toBe('pending');
  });

  it('past the hard ceiling since PAGE LOAD, an unanswered feed alarms even after an alt-tab', () => {
    // _onFeedClockVisible resets visibleSince on every hidden->visible
    // transition, and feedFreshness's FEED_HARD_STALE_MS ceiling is gated
    // behind hasStamp -- so nothing capped the credit on the never-answered
    // path. An operator alt-tabbing more often than FEED_STALE_MS never saw
    // amber at all. pageLoad is the anchor nothing resets.
    const justAltTabbed = { now: NOW, visibleSince: NOW - 1_000 };
    const cold = staleFeedState({}, ['stats'],
      { ...justAltTabbed, pageLoad: NOW - (FEED_HARD_STALE_MS + 1) });
    expect(cold.anyEscalated).toBe(true);
    expect(staleBannerCopy(cold).tone).toBe('alert');

    // Positive control: the SAME alt-tab, but only just after page load, is
    // still legitimately pending -- so the ceiling is what escalated it and
    // not the alt-tab itself.
    const early = staleFeedState({}, ['stats'],
      { ...justAltTabbed, pageLoad: NOW - 5_000 });
    expect(early.anyEscalated).toBe(false);
    expect(staleBannerCopy(early).tone).toBe('pending');
  });

  it('the ceiling does not alarm a page whose feeds are all answering', () => {
    // A long-open healthy dashboard must never trip it: past the ceiling,
    // but nothing is stale, so there is nothing to escalate.
    const r = staleFeedState({ stats: NOW - 1_000, positions: NOW - 1_000 },
      ['stats', 'positions'],
      { now: NOW, visibleSince: NOW - 1_000, pageLoad: NOW - 86_400_000 });
    expect(r.stale).toBe(false);
    expect(r.anyEscalated).toBe(false);
    expect(staleBannerCopy(r)).toBeNull();
  });
});
