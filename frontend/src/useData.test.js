import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { computeMark, fetchAllSafe, authHeader, mapStats } from './useData.js';

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

// ---------------------------------------------------------------------------
// authHeader — AUD-0054: the CSRF header (X-Requested-With) is the actual
// security-relevant property web_app.py's _check_auth enforces (see
// tests/test_web_auth.py's server-side coverage of the same header). This
// helper had coverage only implicitly, through fetchAllSafe's mocked-fetch
// assertions on the Authorization value -- never a direct assertion on the
// CSRF header's presence/value, in either the password-set or
// password-unset case.
// ---------------------------------------------------------------------------
describe('authHeader', () => {
  beforeEach(() => {
    vi.stubGlobal('sessionStorage', createMemoryStorage());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('includes the CSRF header when no password is stored', () => {
    const headers = authHeader();
    expect(headers['X-Requested-With']).toBe('XMLHttpRequest');
    expect(headers.Authorization).toBeUndefined();
  });

  it('includes the CSRF header alongside Authorization once a password is stored', () => {
    sessionStorage.setItem('kalshi-pwd', 'secret');
    const headers = authHeader();
    expect(headers['X-Requested-With']).toBe('XMLHttpRequest');
    expect(headers.Authorization).toBe('Basic ' + btoa(':secret'));
  });
});

// ---------------------------------------------------------------------------
// fetchAllSafe — regression coverage for the password-prompt-storm bug
// (backlog L18070): a batch 401 must produce exactly ONE prompt, not one
// per failing endpoint, and only the endpoints that actually failed auth
// should be retried.
// ---------------------------------------------------------------------------

function createMemoryStorage() {
  let store = {};
  return {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    clear: () => { store = {}; },
  };
}

/** Builds a fetch mock: `handlers[path]` is either a fixed status/body, or
 *  a function (callCountForPath, init) => {status, body} for per-call
 *  behavior — `init` is fetch's second argument, so a handler can inspect
 *  the actual headers/credentials sent on that specific call. */
function makeFetchMock(handlers) {
  const callCounts = {};
  return vi.fn(async (path, init) => {
    callCounts[path] = (callCounts[path] || 0) + 1;
    const h = handlers[path];
    const result = typeof h === 'function' ? h(callCounts[path], init) : h;
    return {
      status: result.status,
      ok: result.status >= 200 && result.status < 300,
      json: async () => result.body ?? {},
    };
  });
}

describe('fetchAllSafe', () => {
  beforeEach(() => {
    vi.stubGlobal('sessionStorage', createMemoryStorage());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('all endpoints succeed: never prompts', async () => {
    const endpoints = ['/api/a', '/api/b', '/api/c'];
    vi.stubGlobal('fetch', makeFetchMock({
      '/api/a': { status: 200, body: { a: 1 } },
      '/api/b': { status: 200, body: { b: 2 } },
      '/api/c': { status: 200, body: { c: 3 } },
    }));
    const promptFn = vi.fn(() => 'unused');

    const results = await fetchAllSafe(endpoints, promptFn);

    expect(promptFn).not.toHaveBeenCalled();
    expect(results.map(r => r.status)).toEqual(['fulfilled', 'fulfilled', 'fulfilled']);
    expect(results.map(r => r.value)).toEqual([{ a: 1 }, { b: 2 }, { c: 3 }]);
  });

  it('every endpoint 401s: prompts exactly ONCE, not once per endpoint (the core regression)', async () => {
    // 5 endpoints all missing/stale auth — the pre-fix behavior called
    // window.prompt() once per endpoint here (5 blocking dialogs).
    const endpoints = ['/api/a', '/api/b', '/api/c', '/api/d', '/api/e'];
    vi.stubGlobal('fetch', makeFetchMock(
      Object.fromEntries(endpoints.map(p => [p, { status: 401 }]))
    ));
    const promptFn = vi.fn(() => null); // user cancels — still must only be asked once

    await fetchAllSafe(endpoints, promptFn);

    expect(promptFn).toHaveBeenCalledTimes(1);
  });

  it('correct password entered: retries with the fresh credential and this batch completes with real data', async () => {
    const endpoints = ['/api/a', '/api/b', '/api/c'];
    // /api/a succeeds first try. /api/b and /api/c 401 on any call that
    // doesn't carry the correct Authorization header — this is what actually
    // catches a mutation that stores the password AFTER retrying (the retry
    // would then go out with no/stale credentials and fail exactly like the
    // original request did), not just a call-count check that can't tell
    // whether the retry sent real credentials.
    const expectedAuth = 'Basic ' + btoa(':correct-password');
    const authed = (call, init) =>
      init?.headers?.Authorization === expectedAuth
        ? { status: 200, body: { ok: 'authed' } }
        : { status: 401 };
    const fetchMock = makeFetchMock({
      '/api/a': { status: 200, body: { ok: 'a' } },
      '/api/b': (call, init) => authed(call, init).status === 200 ? { status: 200, body: { ok: 'b' } } : { status: 401 },
      '/api/c': (call, init) => authed(call, init).status === 200 ? { status: 200, body: { ok: 'c' } } : { status: 401 },
    });
    vi.stubGlobal('fetch', fetchMock);
    const promptFn = vi.fn(() => 'correct-password');

    const results = await fetchAllSafe(endpoints, promptFn);

    expect(promptFn).toHaveBeenCalledTimes(1);
    // Positive control: prove the retry actually happened (2 calls each for
    // the endpoints that 401'd), not just that the final result looks right.
    expect(fetchMock).toHaveBeenCalledTimes(5); // a:1 + b:2 + c:2
    expect(results.map(r => r.status)).toEqual(['fulfilled', 'fulfilled', 'fulfilled']);
    expect(results.map(r => r.value)).toEqual([{ ok: 'a' }, { ok: 'b' }, { ok: 'c' }]);
    expect(sessionStorage.getItem('kalshi-pwd')).toBe('correct-password');
  });

  it('a still-successful endpoint is never re-fetched just because a sibling 401\'d (selective retry, not blanket)', async () => {
    const endpoints = ['/api/a', '/api/b'];
    const fetchMock = makeFetchMock({
      '/api/a': { status: 200, body: { ok: 'a' } }, // never fails
      '/api/b': (call) => call === 1 ? { status: 401 } : { status: 200, body: { ok: 'b' } },
    });
    vi.stubGlobal('fetch', fetchMock);
    const promptFn = vi.fn(() => 'pw');

    await fetchAllSafe(endpoints, promptFn);

    const aCalls = fetchMock.mock.calls.filter(c => c[0] === '/api/a').length;
    expect(aCalls).toBe(1); // not re-fetched on retry
  });

  it('a concurrent overlapping batch already resolved auth while this one was in flight: skips its own prompt', async () => {
    // Simulates two overlapping fetchAllSafe() calls (e.g. the 60s poll
    // firing while a fast "cron just finished" refresh is still pending):
    // /api/a's handler writes a fresh password to sessionStorage as a side
    // effect, standing in for a sibling batch's own prompt resolving WHILE
    // this batch's requests are still in flight. By the time this batch's
    // Promise.allSettled resolves, the stored password has already changed
    // underneath it, so it should retry directly instead of prompting again.
    const endpoints = ['/api/a', '/api/b'];
    const fetchMock = makeFetchMock({
      '/api/a': () => {
        sessionStorage.setItem('kalshi-pwd', 'concurrent-password');
        return { status: 401 };
      },
      '/api/b': (call, init) =>
        init?.headers?.Authorization === 'Basic ' + btoa(':concurrent-password')
          ? { status: 200, body: { ok: 'b' } }
          : { status: 401 },
    });
    vi.stubGlobal('fetch', fetchMock);
    const promptFn = vi.fn(() => 'should-never-be-called');

    const results = await fetchAllSafe(endpoints, promptFn);

    expect(promptFn).not.toHaveBeenCalled();
    expect(results[1]).toEqual({ status: 'fulfilled', value: { ok: 'b' } });
  });

  it('user cancels the prompt: failed endpoints stay rejected, password is not stored', async () => {
    const endpoints = ['/api/a', '/api/b'];
    vi.stubGlobal('fetch', makeFetchMock({
      '/api/a': { status: 200, body: { ok: 'a' } },
      '/api/b': { status: 401 },
    }));
    const promptFn = vi.fn(() => null); // Cancel

    const results = await fetchAllSafe(endpoints, promptFn);

    expect(results[0]).toEqual({ status: 'fulfilled', value: { ok: 'a' } });
    expect(results[1].status).toBe('rejected');
    expect(results[1].reason.isAuth).toBe(true);
    expect(sessionStorage.getItem('kalshi-pwd')).toBeNull();
  });
});

describe('mapStats — top-level stats.brier null handling', () => {
  it('a real successful /api/status response with brier: null overwrites a stale mock value with null, not preserving it', () => {
    const status = { balance: 100, open_count: 0, brier: null };
    const prevStats = { brier: 0.271 }; // MOCK.stats.brier seed value
    const result = mapStats(status, null, null, prevStats);
    expect(result.brier).toBeNull();
  });

  it('a numeric brier from a successful response is still applied normally', () => {
    const status = { balance: 100, open_count: 0, brier: 0.183 };
    const prevStats = { brier: 0.271 };
    const result = mapStats(status, null, null, prevStats);
    expect(result.brier).toBe(0.183);
  });

  it('a failed /api/status fetch (status.error set) leaves prevStats.brier untouched', () => {
    const status = { error: 'HTTP 500' };
    const prevStats = { brier: 0.271 };
    const result = mapStats(status, null, null, prevStats);
    expect(result.brier).toBe(0.271);
  });

  it('status === null (fetch threw) leaves prevStats.brier untouched', () => {
    const prevStats = { brier: 0.271 };
    const result = mapStats(null, null, null, prevStats);
    expect(result.brier).toBe(0.271);
  });
});
