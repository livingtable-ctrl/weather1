import { describe, it, expect } from 'vitest';
import { buildPaperOrderBody, sideAwareEntryPrice } from './shared.jsx';

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
