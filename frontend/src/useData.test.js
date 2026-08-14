import { describe, it, expect } from 'vitest';
import { computeMark } from './useData.js';

// Hand-computed fixtures mirroring positions.liquidation_price()'s convention:
// YES realizes at yes_bid, NO realizes at 1 - yes_ask. See backlog.txt for the
// concrete failure modes (including ones found by opus review after the
// initial version of this fix) these tests guard against.

describe('computeMark', () => {
  it('YES position: marks at the bid, not the ask (bug #1 — full-spread overstatement)', () => {
    const t = { side: 'yes', current_yes_bid: 0.62, current_yes_ask: 0.65 };
    const { mark, markIsLive } = computeMark(t);
    expect(mark).toBe(0.62);
    expect(markIsLive).toBe(true);
    // Positive control: prove the live quote fields were actually read, not
    // coincidentally equal to a fallback — ask and bid are deliberately distinct.
    expect(mark).not.toBe(t.current_yes_ask);
  });

  it('NO position: marks at 1 - ask, not the raw yes ask (bug #2 — wrong-side price)', () => {
    // 60/62-cent market, exactly the example from the backlog entry.
    const t = { side: 'no', current_yes_bid: 0.60, current_yes_ask: 0.62 };
    const { mark, markIsLive } = computeMark(t);
    expect(mark).toBeCloseTo(0.38, 10);
    expect(markIsLive).toBe(true);
    expect(mark).not.toBe(t.current_yes_ask);
  });

  it('no live quote: falls back to entry_price over actual_fill_price for display, flags markIsLive=false (bug #3)', () => {
    const t = { side: 'yes', current_yes_bid: null, current_yes_ask: null, actual_fill_price: 0.55, entry_price: 0.50 };
    const { mark, markIsLive } = computeMark(t);
    // entry_price preferred first (matches the cost/qty basis Unrealized P&L
    // is computed from, so the greyed-out fallback shows exactly $0 rather
    // than a few cents of phantom P&L from actual_fill_price's extra precision).
    expect(mark).toBe(0.50);
    expect(markIsLive).toBe(false);
  });

  it('no entry_price: falls back further to actual_fill_price', () => {
    const t = { side: 'yes', current_yes_bid: undefined, current_yes_ask: undefined, actual_fill_price: 0.48, entry_price: null };
    const { mark, markIsLive } = computeMark(t);
    expect(mark).toBe(0.48);
    expect(markIsLive).toBe(false);
  });

  it('a 0.0 bid is treated as no quote, not a real $0 price (thin/one-sided book)', () => {
    const t = { side: 'yes', current_yes_bid: 0, current_yes_ask: 0.70, entry_price: 0.45 };
    const { mark, markIsLive } = computeMark(t);
    expect(markIsLive).toBe(false);
    expect(mark).toBe(0.45);
  });

  it('a 0.0 ask is treated as no quote for a NO position', () => {
    const t = { side: 'no', current_yes_bid: 0.30, current_yes_ask: 0, entry_price: 0.65 };
    const { mark, markIsLive } = computeMark(t);
    expect(markIsLive).toBe(false);
    expect(mark).toBe(0.65);
  });

  it('NO position with ask == 1.0 realizes at exactly 0 — treated as no quote, not a submittable live price', () => {
    // Found by opus review: 1 - 1.0 = 0 passes a `!= null` check, which would
    // produce markIsLive=true with mark=0 — the server rejects exit_price<=0
    // with no manual-entry fallback shown, hard-blocking Close on a market
    // that legitimately quotes yes_ask=1.0 (a normal quote on an illiquid/
    // extreme-strike market, not an error; order_executor.py synthesizes this
    // exact value when no real ask is present). This is the specific case
    // that distinguishes `liveSidePrice ?? fallback` from a `> 0`-gated
    // markIsLive — a mutation from the `> 0` check back to `!= null` alone
    // must fail this test.
    const t = { side: 'no', current_yes_bid: 0.02, current_yes_ask: 1.0, entry_price: 0.03 };
    const { mark, markIsLive } = computeMark(t);
    expect(markIsLive).toBe(false);
    expect(mark).toBe(0.03);
  });

  it('a live mark is never 0 when markIsLive is true', () => {
    // Companion assertion to the case above, from the other direction.
    const t = { side: 'no', current_yes_bid: 0.02, current_yes_ask: 0.97, entry_price: 0.03 };
    const { mark, markIsLive } = computeMark(t);
    expect(markIsLive).toBe(true);
    expect(mark).toBeGreaterThan(0);
  });

  it('side is case-insensitive', () => {
    const t = { side: 'NO', current_yes_bid: 0.60, current_yes_ask: 0.62 };
    const { mark } = computeMark(t);
    expect(mark).toBeCloseTo(0.38, 10);
  });

  it('missing/unrecognized side defaults to the NO branch, matching liquidation_price()\'s if-yes/else default', () => {
    const t = { current_yes_bid: 0.62, current_yes_ask: 0.65 };
    const { mark } = computeMark(t);
    // NO branch: 1 - 0.65 = 0.35, NOT the YES branch's 0.62.
    expect(mark).toBeCloseTo(0.35, 10);
  });

  it('a string-typed live quote is coerced to a number, not left as a string (would otherwise crash .toFixed() downstream)', () => {
    const t = { side: 'yes', current_yes_bid: '0.62', current_yes_ask: '0.65' };
    const { mark, markIsLive } = computeMark(t);
    expect(mark).toBe(0.62);
    expect(typeof mark).toBe('number');
    expect(markIsLive).toBe(true);
  });

  it('a non-numeric quote string is treated as no quote, not a crash', () => {
    const t = { side: 'yes', current_yes_bid: 'not-a-number', entry_price: 0.40 };
    const { mark, markIsLive } = computeMark(t);
    expect(markIsLive).toBe(false);
    expect(mark).toBe(0.40);
  });
});
