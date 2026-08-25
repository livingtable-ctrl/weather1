import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { buildPaperOrderBody, sideAwareEntryPrice, summarizeBulkResults, effectiveSelection, gradGateStatus, fmtSigned, brierAlertTier, haltOrResume, oppKey, pruneExpired, filterRejected, validateOverrideDuration, summarizeTradeOutcomes, sumUnrealizedPnl, positionUnrealizedPnl, balanceDeltaPct, TAB_LIST, tabForHotkey } from './shared.jsx';

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
