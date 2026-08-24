import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  computeMark, fetchAllSafe, authHeader, mapStats, mapSignals, resolveOpportunities, resolveIfArray,
  mapForecasts, normalizeForecastEntry, mapScanStats, mapAnomalyStatus, mapAlerts,
} from './useData.js';

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
// mapStats — audit-M-11: a real, successful /api/graduation response with
// brier: null (genuinely "not enough trades yet", not a fetch failure) used
// to fall back to `base.graduation?.brier`, which on the very first poll
// reads MOCK's baked-in 0.151 -- and every later poll's fallback source is
// that same now-tainted prevStats, so the mock value became permanent.
// ---------------------------------------------------------------------------
const MOCK_GRADUATION = {
  trades_done: 567, trades_target: 30, total_pnl: 247.83, pnl_target: 50,
  brier: 0.151, brier_target: 0.20, ready: true,
};

describe('mapStats — graduation.brier null handling', () => {
  it('a real grad response with brier: null produces brier: null, NOT the prior/mock value', () => {
    const prevStats = { graduation: MOCK_GRADUATION };
    const grad = { trades_done: 2, trades_target: 30, total_pnl: 5, pnl_target: 50, brier: null, ready: false };
    const result = mapStats(null, grad, null, prevStats);
    expect(result.graduation.brier).toBeNull();
    // Positive control: prove the fallback source (prevStats) really did
    // carry the mock value, so a fallback-to-prevStats bug would have been
    // caught here rather than this test vacuously passing either way.
    expect(prevStats.graduation.brier).toBe(0.151);
  });

  it('a real grad response with a genuine numeric brier is used as-is', () => {
    const prevStats = { graduation: MOCK_GRADUATION };
    const grad = { trades_done: 40, trades_target: 30, total_pnl: 60, pnl_target: 50, brier: 0.183, ready: false };
    const result = mapStats(null, grad, null, prevStats);
    expect(result.graduation.brier).toBe(0.183);
  });

  it('grad fetch itself failed (grad is null): graduation is left untouched, still the prior value', () => {
    // This is the case the fallback logic legitimately exists for -- a
    // failed poll must not wipe the last known-good graduation state. The
    // fix only removes the fallback for a genuinely SUCCESSFUL response
    // with an explicit null, not for this case.
    const prevStats = { graduation: { ...MOCK_GRADUATION, brier: 0.171 } };
    const result = mapStats(null, null, null, prevStats);
    expect(result.graduation.brier).toBe(0.171);
  });

  it('grad fetch returned an error body: graduation is left untouched', () => {
    const prevStats = { graduation: { ...MOCK_GRADUATION, brier: 0.171 } };
    const result = mapStats(null, { error: 'db locked' }, null, prevStats);
    expect(result.graduation.brier).toBe(0.171);
  });
});

// ---------------------------------------------------------------------------
// mapSignals — audit-M-11: a real, empty scan response (raw.signals: [])
// must map to signals: [] (an array, never null/undefined) whenever the
// fetch itself succeeded -- this is the invariant the useData.js reducer's
// fix (`next.opportunities = sigsResult.signals`, unconditional once
// sigsResult is truthy) depends on. If mapSignals ever started returning
// signals: null/undefined for a real empty response, the unconditional
// assignment would wipe M.opportunities to a falsy value instead of an
// empty list -- this test guards the precondition the fix relies on.
// ---------------------------------------------------------------------------
describe('mapSignals — empty-scan invariant', () => {
  it('a real response with an empty signals array returns signals: [], not null/undefined', () => {
    const result = mapSignals({ signals: [], generated_at: '2026-08-24T00:00:00Z' });
    expect(result.signals).toEqual([]);
    expect(result.signals).not.toBeNull();
    expect(result.signals).not.toBeUndefined();
  });

  it('a fetch failure (raw is null/falsy) returns null overall, distinct from a real empty scan', () => {
    // This is the ONE case useData.js's reducer must still preserve prior
    // state for -- `if (sigsResult)` gates on this returning null.
    expect(mapSignals(null)).toBeNull();
  });

  it('a real response with signals present maps them through, lowercasing side', () => {
    const result = mapSignals({ signals: [{ ticker: 'A', side: 'YES' }] });
    expect(result.signals).toHaveLength(1);
    expect(result.signals[0].side).toBe('yes');
  });
});

// ---------------------------------------------------------------------------
// resolveOpportunities / resolveIfArray — opus review MEDIUM-6: the actual
// reducer lines audit-M-11 changed (useData.js's setData callback) aren't
// directly testable (fetchAll isn't exported, no component-test infra in
// this repo), so the fix was extracted into these two pure functions. These
// tests exercise exactly the "real empty response must clear MOCK data"
// claim the mapSignals/mapStats tests above only test the precondition of.
// ---------------------------------------------------------------------------
describe('resolveOpportunities', () => {
  it('a real empty scan (mapSignals result with signals: []) resolves to [], not undefined', () => {
    const sigsResult = mapSignals({ signals: [] });
    expect(resolveOpportunities(sigsResult)).toEqual([]);
  });

  it('a fetch failure (sigsResult is null) resolves to undefined -- the reducer must not touch next.opportunities', () => {
    expect(resolveOpportunities(null)).toBeUndefined();
  });

  it('a real non-empty scan passes signals through unchanged', () => {
    const sigsResult = mapSignals({ signals: [{ ticker: 'A', side: 'yes' }] });
    const resolved = resolveOpportunities(sigsResult);
    expect(resolved).toHaveLength(1);
    expect(resolved[0].ticker).toBe('A');
  });
});

describe('resolveIfArray', () => {
  it('a real empty array resolves to itself (used for alerts/brierHistory), not undefined', () => {
    expect(resolveIfArray([])).toEqual([]);
  });

  it('null/undefined (fetch failure) resolves to undefined', () => {
    expect(resolveIfArray(null)).toBeUndefined();
    expect(resolveIfArray(undefined)).toBeUndefined();
  });

  it('a non-array value (e.g. an error-shaped object) resolves to undefined', () => {
    expect(resolveIfArray({ error: 'db locked' })).toBeUndefined();
  });

  it('a real non-empty array passes through unchanged', () => {
    const arr = [{ week: '2026-W01', brier: 0.2 }];
    expect(resolveIfArray(arr)).toBe(arr);
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

// ---------------------------------------------------------------------------
// batch-44 M-3: RiskTab's own scan-filter presence guard
// (`M.scanStats.total_scanned > 0 || Object.keys(M.scanStats.filters).length
// > 0`) throws when `filters` is undefined -- the guard written to prevent a
// crash on malformed /api/scan-stats data was itself the crashing line.
// mapScanStats normalizes `filters`/`gate_counts` to always be plain objects
// so that guard (and the unguarded `Object.entries(M.scanStats.gate_counts)`
// a few lines below it) can never throw again.
// ---------------------------------------------------------------------------
describe('mapScanStats — malformed /api/scan-stats payloads', () => {
  it('a response missing `filters` entirely does not crash Object.keys() on it', () => {
    const result = mapScanStats({ total_scanned: 40, gate_counts: { passed: 3 } });
    // Positive control: prove this is really the malformed-input path, not a
    // coincidence -- filters must be present-but-empty, not merely non-throwing.
    expect(() => Object.keys(result.filters).length).not.toThrow();
    expect(result.filters).toEqual({});
    expect(result.gate_counts).toEqual({ passed: 3 });
  });

  it('a response missing `gate_counts` entirely coerces it to an empty object', () => {
    const result = mapScanStats({ total_scanned: 12, filters: { no_analysis: 5 } });
    expect(() => Object.entries(result.gate_counts)).not.toThrow();
    expect(result.gate_counts).toEqual({});
  });

  it('total_scanned defaults to 0 when missing/non-numeric, not undefined', () => {
    expect(mapScanStats({ filters: {}, gate_counts: {} }).total_scanned).toBe(0);
    expect(mapScanStats({ total_scanned: 'oops', filters: {}, gate_counts: {} }).total_scanned).toBe(0);
  });

  // opus review F10: RiskTab's bar chart does
  // `Math.max(1, ...allEntries.map(([, v]) => v))` over every filters/
  // gate_counts value -- one non-numeric value poisons that into NaN, and
  // every bar's width (NaN%) vanishes while the counts still render.
  it('a non-numeric filter/gate_count value is coerced to 0 rather than poisoning the bar-chart Math.max into NaN', () => {
    const result = mapScanStats({
      total_scanned: 10,
      filters: { no_analysis: 'oops', mkt_prob: 3 },
      gate_counts: { passed: null },
    });
    expect(() => Math.max(1, ...Object.values(result.filters), ...Object.values(result.gate_counts))).not.toThrow();
    expect(Number.isNaN(Math.max(1, ...Object.values(result.filters)))).toBe(false);
    expect(result.filters.no_analysis).toBe(0);
    expect(result.filters.mkt_prob).toBe(3);
    expect(result.gate_counts.passed).toBe(0);
  });

  it('a numeric-string filter value is coerced to a real number, not left as a string', () => {
    const result = mapScanStats({ total_scanned: 5, filters: { no_analysis: '7' }, gate_counts: {} });
    expect(result.filters.no_analysis).toBe(7);
    expect(typeof result.filters.no_analysis).toBe('number');
  });

  it('a well-formed response passes filters/gate_counts through unchanged', () => {
    const raw = { total_scanned: 23, filters: { no_analysis: 4, mkt_prob: 2 }, gate_counts: { passed: 3 } };
    expect(mapScanStats(raw)).toEqual(raw);
  });

  it('a fetch failure (raw is null) or an error-shaped response returns null', () => {
    expect(mapScanStats(null)).toBeNull();
    expect(mapScanStats({ error: 'db locked' })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// batch-44 M-3: RiskTab's anomaly-detection card reads
// `M.anomalyStatus.window_trades.length` and `.anomaly_messages.length`
// unguarded (throws on a missing array) plus `halt_threshold`/`min_samples`
// unguarded in arithmetic/template contexts (renders NaN/undefined on a
// missing number). mapAnomalyStatus normalizes exactly those fields.
// ---------------------------------------------------------------------------
describe('mapAnomalyStatus — malformed /api/anomaly-status payloads', () => {
  it('missing window_trades/anomaly_messages coerce to empty arrays, not undefined', () => {
    const result = mapAnomalyStatus({ active: true, win_rate: 0.5 });
    expect(() => result.window_trades.length).not.toThrow();
    expect(() => result.anomaly_messages.length).not.toThrow();
    expect(result.window_trades).toEqual([]);
    expect(result.anomaly_messages).toEqual([]);
  });

  // opus review F6: 0 is a plausible REAL threshold/sample-count, so
  // defaulting missing halt_threshold/min_samples to 0 would make a broken
  // endpoint read as "halt threshold is 0%, safety gate effectively
  // disabled" -- null (rendered as "—" in RiskTab) is the honest signal.
  it('missing halt_threshold/min_samples normalize to null, NOT 0 (0 is a plausible real threshold and would misreport the safety gate as disabled)', () => {
    const result = mapAnomalyStatus({ active: true });
    expect(result.halt_threshold).toBeNull();
    expect(result.min_samples).toBeNull();
    // Positive control: a genuine 0 threshold must still pass through as 0, not null.
    expect(mapAnomalyStatus({ active: true, halt_threshold: 0, min_samples: 0 }).halt_threshold).toBe(0);
  });

  // opus review F4: window_trades is normalized to an array, but each
  // element was still read unguarded downstream (`t.ticker.split(...)`,
  // `t.won`) -- the exact crash class M-3 exists to eliminate, on the same
  // endpoint, one level deeper.
  describe('window_trades element normalization (opus review F4)', () => {
    it('an element missing `ticker` does not crash `.split()` on it downstream', () => {
      const result = mapAnomalyStatus({ active: true, window_trades: [{ won: true, pnl: 1 }] });
      expect(() => result.window_trades[0].ticker.split('-')).not.toThrow();
      expect(result.window_trades[0].ticker).toBe('');
    });

    it('a malformed (null) element does not crash — coerced to a safe default row', () => {
      const result = mapAnomalyStatus({ active: true, window_trades: [null, { ticker: 'A-1', won: true, pnl: 2 }] });
      expect(() => result.window_trades[0].ticker.split('-')).not.toThrow();
      expect(result.window_trades[0]).toEqual({ ticker: '', won: false, pnl: null });
    });

    it('a well-formed element passes its real values through', () => {
      const result = mapAnomalyStatus({ active: true, window_trades: [{ ticker: 'KXHIGHATL-26MAY09', won: true, pnl: 3.2 }] });
      expect(result.window_trades[0]).toEqual({ ticker: 'KXHIGHATL-26MAY09', won: true, pnl: 3.2 });
    });

    it('a non-numeric pnl normalizes to null rather than a bogus number', () => {
      const result = mapAnomalyStatus({ active: true, window_trades: [{ ticker: 'A-1', won: false, pnl: 'n/a' }] });
      expect(result.window_trades[0].pnl).toBeNull();
    });
  });

  // opus review F5: a non-string anomaly_messages element rendered directly
  // as a React child throws "Objects are not valid as a React child".
  it('a non-string anomaly_messages element is coerced to a string, not left as an object (opus review F5)', () => {
    const result = mapAnomalyStatus({ active: true, anomaly_messages: [{ weird: 'object' }, 'a real message'] });
    expect(result.anomaly_messages).toEqual(['[object Object]', 'a real message']);
    expect(result.anomaly_messages.every(m => typeof m === 'string')).toBe(true);
  });

  it('a well-formed response passes every field through unchanged', () => {
    const raw = {
      active: true, anomaly_detected: false, should_halt: false, win_rate: 0.62,
      wins: 8, losses: 5, n: 13, halt_threshold: 0.35, min_samples: 10,
      window_trades: [{ ticker: 'A-1', won: true, pnl: 3.2 }],
      anomaly_messages: [],
    };
    expect(mapAnomalyStatus(raw)).toEqual(raw);
  });

  it('a fetch failure (raw is null) or an error-shaped response returns null', () => {
    expect(mapAnomalyStatus(null)).toBeNull();
    expect(mapAnomalyStatus({ error: 'db locked' })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// batch-44 M-3: ForecastTab computes `f.high_range[1] - f.high_range[0]` and
// `f.high_f.toFixed(1)` with no defaults -- one city missing `high_range` in
// a real /api/today_forecasts response used to take the whole tab into the
// ErrorBoundary. mapForecasts/normalizeForecastEntry coerce per-city fields
// to safe defaults instead.
// ---------------------------------------------------------------------------
describe('mapForecasts / normalizeForecastEntry — malformed per-city entries', () => {
  it('a city entry missing high_range gets a [high_f, high_f] fallback, not undefined', () => {
    const result = normalizeForecastEntry({ high_f: 72.3, precip_in: 0, models_used: 4 });
    expect(result.high_range).toEqual([72.3, 72.3]);
    // Positive control: prove the fallback is actually derived from high_f,
    // not a fixed [0, 0] stub -- the spread computed downstream must be 0.
    expect(result.high_range[1] - result.high_range[0]).toBe(0);
  });

  it('a city entry with a malformed (non-2-element or non-numeric) high_range also falls back safely', () => {
    expect(normalizeForecastEntry({ high_f: 60, high_range: [60] }).high_range).toEqual([60, 60]);
    expect(normalizeForecastEntry({ high_f: 60, high_range: ['a', 'b'] }).high_range).toEqual([60, 60]);
  });

  it('missing precip_in/models_used (with high_f present) default to 0, not undefined', () => {
    const result = normalizeForecastEntry({ high_f: 70 });
    expect(result.precip_in).toBe(0);
    expect(result.models_used).toBe(0);
  });

  it('a non-object city entry (null) is dropped rather than crashing downstream', () => {
    expect(normalizeForecastEntry(null)).toBeNull();
    expect(normalizeForecastEntry(undefined)).toBeNull();
  });

  // opus review F1: high_f is deliberately NOT defaulted, unlike the other
  // fields -- a fabricated 0.0°F is a fully plausible, wrong reading (renders
  // as a real temperature with a tight 0° range colored green), which is
  // worse on a weather-trading dashboard than the crash it would replace.
  // An entry missing high_f has nothing meaningful to render, so it's
  // dropped entirely, same as a non-object entry.
  it('a city entry missing high_f is dropped, not defaulted to a fabricated 0.0°F (opus review F1)', () => {
    expect(normalizeForecastEntry({ precip_in: 0.1, models_used: 3 })).toBeNull();
    expect(normalizeForecastEntry({})).toBeNull();
    // Positive control: a genuine 0-degree reading (rare but real, e.g.
    // freezing) must still pass through as 0, not be treated as "missing".
    expect(normalizeForecastEntry({ high_f: 0 }).high_f).toBe(0);
  });

  it('a well-formed city entry passes through with its real values, unmutated', () => {
    const raw = { high_f: 81.4, low_f: 63.2, precip_in: 0.12, models_used: 4, high_range: [79, 84] };
    expect(normalizeForecastEntry(raw)).toEqual(raw);
  });

  it('mapForecasts drops a malformed city (null) but keeps the rest of the map rendering', () => {
    const raw = {
      today: {
        Atlanta: { high_f: 88, high_range: [86, 90], precip_in: 0, models_used: 3 },
        Denver: null, // malformed -- e.g. backend returned a bare error string for this city
      },
    };
    const result = mapForecasts(raw);
    expect(Object.keys(result.todayForecasts)).toEqual(['Atlanta']);
    expect(result.todayForecasts.Denver).toBeUndefined();
  });

  it('mapForecasts drops a city missing high_f (opus review F1) but keeps the rest of the map rendering', () => {
    const raw = {
      today: {
        Atlanta: { high_f: 88, high_range: [86, 90], precip_in: 0, models_used: 3 },
        Denver: { precip_in: 0.2, models_used: 2 }, // missing high_f
      },
    };
    const result = mapForecasts(raw);
    expect(Object.keys(result.todayForecasts)).toEqual(['Atlanta']);
  });

  it('a city entry missing high_range but present in the map still renders with the fallback (no crash, no drop)', () => {
    const raw = { today: { Miami: { high_f: 90, precip_in: 0.4, models_used: 2 } } };
    const result = mapForecasts(raw);
    expect(result.todayForecasts.Miami.high_range).toEqual([90, 90]);
  });

  it('a fetch failure (raw is null) or an error-shaped response returns null', () => {
    expect(mapForecasts(null)).toBeNull();
    expect(mapForecasts({ error: 'db locked' })).toBeNull();
  });

  // opus review F7: a genuinely empty {} (every city filtered out by a
  // downstream provider outage) is real data and must clear stale MOCK/prior
  // forecasts -- the same audit-M-11 "truthy-length bug" this file already
  // fixed for opportunities/alerts/brierHistory. Only omitting the key
  // entirely (a legacy/different response shape) should preserve prior state.
  it('a today/tomorrow key present but genuinely empty ({}) is assigned as {}, clearing stale data (opus review F7)', () => {
    const result = mapForecasts({ today: {}, tomorrow: {} });
    expect(result).not.toBeNull();
    expect(result.todayForecasts).toEqual({});
    expect(result.tomorrowForecasts).toEqual({});
  });

  it('a today/tomorrow key omitted entirely (missing from the response) is left out of the result, preserving prior state', () => {
    expect(mapForecasts({ unrelated_field: 1 })).toBeNull();
  });

  it('every city in today filtered out for missing high_f still assigns an empty {} (real signal, not a fetch failure)', () => {
    const result = mapForecasts({ today: { Denver: { precip_in: 0.1 } } });
    expect(result.todayForecasts).toEqual({});
  });
});

// ---------------------------------------------------------------------------
// batch-44 M-5: ActivityTab reads `e.text` (levels error/warn/info/good);
// shared.jsx's SystemEventsCard used to read `evt.message || evt.msg ||
// evt.text` (levels error/warning/info) -- two schemas for the same
// /api/system-events array. The real backend (web_app.py's
// api_system_events) only ever sends `text` and `level: "info"|"warn"`.
// mapAlerts normalizes both fields once so every consumer reads one shape.
// ---------------------------------------------------------------------------
describe('mapAlerts — M-5 schema normalization', () => {
  it('an item using `message` instead of `text` (the SystemEventsCard-assumed field) is normalized to `text`', () => {
    const result = mapAlerts([{ ts: '2026-08-24T00:00:00Z', level: 'info', message: 'hello' }]);
    expect(result[0].text).toBe('hello');
  });

  it('an item using `msg` instead of `text` is also normalized to `text`', () => {
    const result = mapAlerts([{ ts: '2026-08-24T00:00:00Z', level: 'info', msg: 'hi there' }]);
    expect(result[0].text).toBe('hi there');
  });

  it('level "warning" (SystemEventsCard\'s assumed vocabulary) is normalized to "warn" (ActivityTab\'s / the real backend\'s vocabulary)', () => {
    const result = mapAlerts([{ ts: '', level: 'warning', text: 'circuit open' }]);
    expect(result[0].level).toBe('warn');
    // Positive control: prove this isn't a blanket default -- a correctly-
    // spelled level must pass through unchanged.
    const passthrough = mapAlerts([{ ts: '', level: 'error', text: 'x' }]);
    expect(passthrough[0].level).toBe('error');
  });

  // opus review F3: this is a safety/monitoring feed -- an unrecognized
  // future level must fail LOUD (visible in ActivityTab's warn count/filter)
  // rather than be downgraded to the blandest label and silently excluded
  // from error/warn counts. Also case-insensitive now ("WARN" must not fall
  // through to the default just because of casing).
  it('an unrecognized/missing level defaults to "warn" (fail loud), not "info" (opus review F3)', () => {
    expect(mapAlerts([{ ts: '', text: 'x' }])[0].level).toBe('warn');
    expect(mapAlerts([{ ts: '', level: 'critical', text: 'x' }])[0].level).toBe('warn');
  });

  it('level matching is case-insensitive ("WARN"/"Warning" still normalize correctly)', () => {
    expect(mapAlerts([{ ts: '', level: 'WARN', text: 'x' }])[0].level).toBe('warn');
    expect(mapAlerts([{ ts: '', level: 'Warning', text: 'x' }])[0].level).toBe('warn');
    expect(mapAlerts([{ ts: '', level: 'ERROR', text: 'x' }])[0].level).toBe('error');
  });

  it('a real, well-formed backend item (text + warn/info) passes through unchanged', () => {
    const result = mapAlerts([
      { ts: '2026-08-24T00:00:00Z', level: 'warn', text: 'Pirate Weather circuit OPEN', source: 'circuit' },
    ]);
    expect(result[0]).toEqual({ ts: '2026-08-24T00:00:00Z', level: 'warn', text: 'Pirate Weather circuit OPEN', source: 'circuit' });
  });

  // opus review F9: the other three mappers (mapAnomalyStatus,
  // normalizeForecastEntry, mapScanStats) spread the raw object so an
  // unknown future field passes through -- mapAlerts should too, for
  // consistency and so a future backend field isn't silently dropped.
  it('an unrecognized extra field on the raw event passes through (opus review F9 — spread for symmetry)', () => {
    const result = mapAlerts([{ ts: '', level: 'info', text: 'x', ticker: 'KXHIGHATL-26MAY09' }]);
    expect(result[0].ticker).toBe('KXHIGHATL-26MAY09');
  });

  it('a non-object array entry does not crash the mapper — normalized to an empty-text warn row', () => {
    expect(() => mapAlerts([null, 'oops', 42])).not.toThrow();
    expect(mapAlerts([null])[0]).toEqual({ ts: '', level: 'warn', text: '', source: null });
  });

  // opus review F2: mapAlerts guarantees `text` is a string, not a
  // NON-EMPTY one -- deleting SystemEventsCard's `|| JSON.stringify(evt)`
  // removed the only schema-drift tripwire in the app. Restore it here: a
  // real (non-empty) object matching none of text/message/msg is exactly
  // the "backend renamed the field" case this mapper exists to catch.
  it('an object with none of text/message/msg falls back to JSON.stringify(evt), not a silent blank row (opus review F2)', () => {
    const result = mapAlerts([{ ts: '2026-08-24T00:00:00Z', level: 'info', body: 'renamed field' }]);
    expect(result[0].text).toBe(JSON.stringify({ ts: '2026-08-24T00:00:00Z', level: 'info', body: 'renamed field' }));
    expect(result[0].text).not.toBe('');
  });

  it('a genuinely empty text ("") is preserved as-is, not treated as missing (deliberate no-message case)', () => {
    const result = mapAlerts([{ ts: '', level: 'info', text: '' }]);
    expect(result[0].text).toBe('');
  });

  it('a real empty array resolves to [], not undefined (preserves the resolveIfArray invariant)', () => {
    expect(mapAlerts([])).toEqual([]);
  });

  it('a fetch failure (raw is null, or a non-array error-shaped body) resolves to undefined', () => {
    expect(mapAlerts(null)).toBeUndefined();
    expect(mapAlerts({ error: 'db locked' })).toBeUndefined();
  });
});
