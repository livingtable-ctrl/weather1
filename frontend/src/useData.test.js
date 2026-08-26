import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  computeMark, fetchAllSafe, authHeader, mapStats, mapSignals, resolveOpportunities, resolveIfArray,
  mapForecasts, normalizeForecastEntry, mapScanStats, mapAnomalyStatus, mapAlerts,
  mergeFetchedAt, mapTrades, orderFeedSuccess,
  startVisibilityGatedPoll,
  API_TIMEOUT_MS, SCAN_VERSION_TIMEOUT_MS, anyFeedResolved, nextStatsTimestamp,
  makeScanVersionPoller, timeoutSignal,
  OVERVIEW_FEED_KEYS, RISK_FEED_KEYS,
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

// -----------------------------------------------------------------------
// batch-47 item 1: a backgrounded tab kept every poll loop firing
// unconditionally with nobody looking. `doc` is a fake EventTarget standing
// in for `document` (this repo runs vitest in the default node environment,
// no jsdom, matching the promptFn-injection pattern fetchAllSafe already
// uses for the same reason). vi.useFakeTimers() also fakes Date, so
// Date.now() inside startVisibilityGatedPoll's throttle check advances
// exactly with vi.advanceTimersByTime() below.
// -----------------------------------------------------------------------
describe('startVisibilityGatedPoll', () => {
  function makeFakeDoc(initialHidden) {
    const target = new EventTarget();
    target.hidden = initialHidden;
    return target;
  }

  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('visible tab: no call on mount, then fires every intervalMs', () => {
    const doc = makeFakeDoc(false);
    const fn = vi.fn();
    startVisibilityGatedPoll(fn, 1000, doc);
    // No immediate call — matches useData's existing pattern of an explicit
    // separate initial fetchAll() call before the interval is armed.
    expect(fn).toHaveBeenCalledTimes(0);
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(2000);
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('tab starts hidden: the interval never starts at all', () => {
    const doc = makeFakeDoc(true);
    const fn = vi.fn();
    startVisibilityGatedPoll(fn, 1000, doc);
    vi.advanceTimersByTime(5000);
    expect(fn).toHaveBeenCalledTimes(0);
  });

  it('backgrounding mid-run stops the interval — the actual bug being fixed', () => {
    const doc = makeFakeDoc(false);
    const fn = vi.fn();
    startVisibilityGatedPoll(fn, 1000, doc);
    vi.advanceTimersByTime(3000);
    expect(fn).toHaveBeenCalledTimes(3);

    doc.hidden = true;
    doc.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(10000); // would be +10 calls if ungated
    // Positive control: the same setInterval mechanism is still live in
    // principle (fake timers keep advancing) — only the gating stops it,
    // proving this isn't passing because nothing was scheduled to begin with.
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('regaining visibility AFTER intervalMs has elapsed since the last run: fires a catch-up call, then resumes the interval', () => {
    const doc = makeFakeDoc(false);
    const fn = vi.fn();
    startVisibilityGatedPoll(fn, 1000, doc);
    doc.hidden = true;
    doc.dispatchEvent(new Event('visibilitychange'));
    expect(fn).toHaveBeenCalledTimes(0);

    vi.advanceTimersByTime(5000); // well past intervalMs while hidden
    doc.hidden = false;
    doc.dispatchEvent(new Event('visibilitychange'));
    // Catch-up fires — this is the "operator isn't looking at hours-stale
    // data for the first few seconds" requirement.
    expect(fn).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  // opus review (batch-47, HIGH): an earlier version of this fix called
  // fn() unconditionally on every visibility-regain with no throttle --
  // verified live that 10 rapid tab-focus flips fired 10 immediate requests
  // in ~200ms, turning routine alt-tabbing into a burst that made the
  // 15-minute weather-alerts poll (rate-limit-sensitive, see its own
  // comment) fire far more often than the interval it's supposed to honor.
  it('regaining visibility BEFORE intervalMs has elapsed since the last run: does NOT re-fire immediately (rapid-flip burst protection)', () => {
    const doc = makeFakeDoc(false);
    const fn = vi.fn();
    startVisibilityGatedPoll(fn, 1000, doc);
    vi.advanceTimersByTime(1000); // one real tick — lastRunMs is now "fresh"
    expect(fn).toHaveBeenCalledTimes(1);

    // Rapid hide/show flip well inside the same interval window.
    doc.hidden = true;
    doc.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(50);
    doc.hidden = false;
    doc.dispatchEvent(new Event('visibilitychange'));
    // No extra call — the last run was 50ms ago, nowhere near intervalMs.
    expect(fn).toHaveBeenCalledTimes(1);

    // Positive control: polling genuinely resumed (not stuck stopped) — the
    // restarted interval ticks intervalMs after the restart point (t=1050),
    // i.e. at t=2050, not aligned to the original t=0 schedule.
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(2);
  });

  // opus review (batch-47, LOW): the `if (intervalId == null)` re-arm guard
  // in start() was previously unexercised — deleting it would let two
  // consecutive "visible" events silently double the interval's cadence.
  it('two consecutive visibility-regain events do not double the interval (re-arm guard)', () => {
    const doc = makeFakeDoc(false);
    const fn = vi.fn();
    startVisibilityGatedPoll(fn, 1000, doc);
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);

    // Fire "visible" twice in a row without ever going hidden in between.
    doc.dispatchEvent(new Event('visibilitychange'));
    doc.dispatchEvent(new Event('visibilitychange'));

    vi.advanceTimersByTime(1000);
    // If start() re-armed a second interval each time, this would be 4+
    // (2 stray immediate calls already suppressed by the throttle above,
    // plus 2 ticks from two overlapping 1000ms intervals). Must stay at 2.
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it('teardown() stops the interval AND stops reacting to further visibility changes', () => {
    const doc = makeFakeDoc(false);
    const fn = vi.fn();
    const teardown = startVisibilityGatedPoll(fn, 1000, doc);
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);

    teardown();
    vi.advanceTimersByTime(5000);
    expect(fn).toHaveBeenCalledTimes(1);

    // A visibility flip after teardown must not resurrect polling.
    doc.hidden = true;
    doc.dispatchEvent(new Event('visibilitychange'));
    doc.hidden = false;
    doc.dispatchEvent(new Event('visibilitychange'));
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// batch-61 item 3 (backlog L30717): mergeFetchedAt builds the per-endpoint
// "last SUCCESSFUL fetch" map that shared.jsx's feedFreshness() reads.
// Extracted from fetchAll's setData updater precisely so it is testable --
// frontend/ has no jsdom/RTL, so the merge body itself cannot be exercised.
// (The first version of this change shipped two mapAnomalyStatus tests that
// read as covering this and asserted nothing about it; opus review F7.)
// ---------------------------------------------------------------------------
describe('mergeFetchedAt', () => {
  const NOW = 1_700_000_000_000;

  it('stamps a feed that succeeded', () => {
    expect(mergeFetchedAt({}, { anomalyStatus: true }, NOW)).toEqual({ anomalyStatus: NOW });
  });

  it('does NOT stamp a feed that failed, and does not erase its previous value', () => {
    // The whole mechanism: a failed endpoint's timestamp must stop advancing
    // (that IS the staleness signal) without being cleared, since the card
    // still wants to say how old the last good reading was.
    const prev = { anomalyStatus: NOW - 500_000 };
    expect(mergeFetchedAt(prev, { anomalyStatus: false }, NOW)).toEqual(prev);
  });

  it('carries unrelated feeds forward untouched, so one outage cannot age another', () => {
    const prev = { trades: 111, positions: 222 };
    expect(mergeFetchedAt(prev, { anomalyStatus: true }, NOW)).toEqual({
      trades: 111, positions: 222, anomalyStatus: NOW,
    });
  });

  it('never mutates `prev` — fetchAll passes MOCK itself on the first merge', () => {
    // Mutating there would poison the module-level mock object for every
    // later consumer, permanently.
    const prev = { anomalyStatus: 1 };
    const out = mergeFetchedAt(prev, { anomalyStatus: true }, NOW);
    expect(prev).toEqual({ anomalyStatus: 1 });
    expect(out).not.toBe(prev);
  });

  it('handles a missing prev map (very first merge) without throwing', () => {
    expect(mergeFetchedAt(undefined, { anomalyStatus: true }, NOW)).toEqual({ anomalyStatus: NOW });
    expect(mergeFetchedAt(null, {}, NOW)).toEqual({});
  });

  it('positive control: the same call stamps a DIFFERENT value as the clock advances', () => {
    // Without this, an implementation that wrote a constant would satisfy
    // every assertion above while making every feed permanently "fresh".
    expect(mergeFetchedAt({}, { anomalyStatus: true }, NOW).anomalyStatus).toBe(NOW);
    expect(mergeFetchedAt({}, { anomalyStatus: true }, NOW + 60_000).anomalyStatus).toBe(NOW + 60_000);
  });

  it('mapAnomalyStatus null-return is the gate: a failed/errored fetch yields no stamp', () => {
    // fetchAll passes `Boolean(mapAnomalyStatus(raw))` as the success flag,
    // so this pins the two halves together end to end.
    for (const bad of [null, undefined, { error: 'db locked' }]) {
      const ok = Boolean(mapAnomalyStatus(bad));
      expect(mergeFetchedAt({}, { anomalyStatus: ok }, NOW)).toEqual({});
    }
    const good = Boolean(mapAnomalyStatus({ active: false, anomaly_detected: false }));
    expect(mergeFetchedAt({}, { anomalyStatus: good }, NOW)).toEqual({ anomalyStatus: NOW });
  });
});

// ---------------------------------------------------------------------------
// batch-63 item 3: the order-action freshness gate reads
// M.fetchedAt.positions / .opportunities, so those two keys must obey exactly
// the rule mergeFetchedAt already established for anomalyStatus -- stamped
// only when the merge actually TOOK the data. A key that stamps on a failed
// fetch would report a fresh quote that was never fetched, which is worse
// than having no gate at all.
// ---------------------------------------------------------------------------
describe('fetchedAt keys for the order-action gate (batch-63 item 3)', () => {
  const NOW = 1_700_000_000_000;

  it('a genuinely EMPTY list is a successful refresh and stamps', () => {
    // The predicates fetchAll keys off, evaluated on real mapper output.
    // Closing the last position, or a scan finding nothing, must advance
    // freshness -- treating "empty" as "failed" would make the confirm modal
    // warn forever on a legitimately quiet dashboard.
    expect(mapTrades({ open: [], closed: [] }).open).toEqual([]);
    expect(resolveOpportunities(mapSignals({ signals: [] }))).not.toBeUndefined();
  });

  it('a FAILED fetch does not stamp, so the timestamp stops advancing', () => {
    expect(mapTrades(null).open).toBeNull();
    expect(resolveOpportunities(mapSignals(null))).toBeUndefined();
  });

  it('one endpoint failing never disturbs the other two keys', () => {
    // The realistic three-key shape fetchAll now passes. positions failed;
    // its previous timestamp must survive untouched while the other two
    // advance -- otherwise a single /api/trades blip would either erase the
    // Close gate's age or fabricate a fresh one.
    const prev = { anomalyStatus: NOW - 500_000, positions: NOW - 400_000, opportunities: NOW - 300_000 };
    const next = mergeFetchedAt(prev, {
      anomalyStatus: true,
      positions: false,
      opportunities: true,
    }, NOW);
    expect(next).toEqual({
      anomalyStatus: NOW,
      positions: NOW - 400_000,
      opportunities: NOW,
    });
    // Positive control: prev itself was not mutated, so a later consumer
    // reading the old object still sees the old values.
    expect(prev.anomalyStatus).toBe(NOW - 500_000);
  });
});

// ---------------------------------------------------------------------------
// batch-63 item 3, opus-review round 2 (F5): the stamping predicates used to
// live inline in fetchAll's setData updater, where no test could reach them --
// mutating `positions: trades.open != null` to a bare `true` left all 235
// tests green. orderFeedSuccess is that logic extracted so the mutation dies.
// ---------------------------------------------------------------------------
describe('orderFeedSuccess', () => {
  it('reports success only for the feeds whose data the merge actually took', () => {
    const ok = orderFeedSuccess(mapTrades({ open: [], closed: [] }),
                                resolveOpportunities(mapSignals({ signals: [] })),
                                mapAnomalyStatus({ active: false }),
                                { balance: 100 }, { aged_positions: [] }, { ready: true });
    expect(ok).toEqual({
      anomalyStatus: true, positions: true, opportunities: true,
      stats: true, risk: true, graduation: true,
    });
  });

  it('a failed fetch on any feed reports false for that feed ONLY', () => {
    // The failure this exists to prevent: a key stamping fresh for data that
    // never arrived, which is worse than having no freshness gate at all.
    const OK_STATUS = { balance: 100 };
    const OK_RISK = { aged_positions: [] };
    const OK_GRAD = { ready: true };
    const REST = { risk: true, graduation: true };
    expect(orderFeedSuccess(mapTrades(null),
                            resolveOpportunities(mapSignals({ signals: [] })),
                            mapAnomalyStatus({ active: false }), OK_STATUS, OK_RISK, OK_GRAD))
      .toEqual({ anomalyStatus: true, positions: false, opportunities: true, stats: true, ...REST });

    expect(orderFeedSuccess(mapTrades({ open: [], closed: [] }),
                            resolveOpportunities(mapSignals(null)),
                            mapAnomalyStatus({ active: false }), OK_STATUS, OK_RISK, OK_GRAD))
      .toEqual({ anomalyStatus: true, positions: true, opportunities: false, stats: true, ...REST });

    expect(orderFeedSuccess(mapTrades({ open: [], closed: [] }),
                            resolveOpportunities(mapSignals({ signals: [] })),
                            mapAnomalyStatus(null), OK_STATUS, OK_RISK, OK_GRAD))
      .toEqual({ anomalyStatus: false, positions: true, opportunities: true, stats: true, ...REST });

    // batch-80 item 1: /api/status failing must isolate to `stats` alone.
    expect(orderFeedSuccess(mapTrades({ open: [], closed: [] }),
                            resolveOpportunities(mapSignals({ signals: [] })),
                            mapAnomalyStatus({ active: false }), null, OK_RISK, OK_GRAD))
      .toEqual({ anomalyStatus: true, positions: true, opportunities: true, stats: false, ...REST });

    // round-2 opus review M1/M2: /api/risk and /api/graduation each isolate
    // to their own key. Before they had keys at all, a 500 on either froze
    // cards on both tabs while `stats` kept stamping fresh.
    expect(orderFeedSuccess(mapTrades({ open: [], closed: [] }),
                            resolveOpportunities(mapSignals({ signals: [] })),
                            mapAnomalyStatus({ active: false }), OK_STATUS,
                            { error: 'db locked' }, OK_GRAD).risk).toBe(false);
    expect(orderFeedSuccess(mapTrades({ open: [], closed: [] }),
                            resolveOpportunities(mapSignals({ signals: [] })),
                            mapAnomalyStatus({ active: false }), OK_STATUS,
                            OK_RISK, { error: 'db locked' }).graduation).toBe(false);
  });

  it('every feed failing reports all false, and never throws on undefined input', () => {
    expect(orderFeedSuccess(mapTrades(null), undefined, null, null, null, null))
      .toEqual({
        anomalyStatus: false, positions: false, opportunities: false,
        stats: false, risk: false, graduation: false,
      });
    expect(() => orderFeedSuccess()).not.toThrow();
  });

  it('feeds straight into mergeFetchedAt: only the successes advance', () => {
    // The pairing is the whole invariant -- the predicate and the merge have
    // to agree, and this is the only place both are exercised together.
    const NOW = 1_700_000_000_000;
    const prev = { anomalyStatus: NOW - 500_000, positions: NOW - 400_000 };
    const next = mergeFetchedAt(
      prev,
      orderFeedSuccess(mapTrades(null), resolveOpportunities(mapSignals({ signals: [] })), null),
      NOW,
    );
    expect(next).toEqual({
      anomalyStatus: NOW - 500_000,   // failed: carried forward, not erased
      positions: NOW - 400_000,        // failed: carried forward, not erased
      opportunities: NOW,              // succeeded: stamped
    });
  });
});

// opus review F7: a 200-with-an-error body is truthy, so the old `if (!raw)`
// guard let it simultaneously CLEAR next.positions and stamp fetchedAt as a
// successful refresh -- a timestamp vouching for data the merge never took.
describe('mapTrades treats a 200-with-error body as a failed fetch', () => {
  it('returns the null sentinel for an error body, so nothing stamps', () => {
    const r = mapTrades({ error: 'sqlite is locked', open: [], closed: [] });
    expect(r.open).toBeNull();
    expect(r.closed).toBeNull();
    expect(orderFeedSuccess(r, undefined, null).positions).toBe(false);
    // Positive control: the same shape WITHOUT the error field stamps.
    expect(orderFeedSuccess(mapTrades({ open: [], closed: [] }), undefined, null).positions)
      .toBe(true);
  });
});

// opus review F3: /api/trades answers 200 with a snapshot-cache price when the
// live Kalshi batch-fetch fails, so "a mark exists" never meant "it is live".
describe('mapTrades carries the backend quote_is_live flag', () => {
  it('passes the flag through for the Close gate to read', () => {
    const cached = mapTrades({
      open: [{ id: 1, ticker: 'T', side: 'yes', current_yes_bid: 0.4, current_yes_ask: 0.5, quote_is_live: false }],
      closed: [],
    });
    expect(cached.open[0].quoteIsLive).toBe(false);
    // markIsLive is still true here -- that is exactly the gap: a cached
    // price looks live to every existing consumer.
    expect(cached.open[0].markIsLive).toBe(true);

    const live = mapTrades({
      open: [{ id: 1, ticker: 'T', side: 'yes', current_yes_bid: 0.4, current_yes_ask: 0.5, quote_is_live: true }],
      closed: [],
    });
    expect(live.open[0].quoteIsLive).toBe(true);
  });

  it('is undefined for an older backend that does not send it — no claim either way', () => {
    const r = mapTrades({
      open: [{ id: 1, ticker: 'T', side: 'yes', current_yes_bid: 0.4, current_yes_ask: 0.5 }],
      closed: [],
    });
    expect(r.open[0].quoteIsLive).toBeUndefined();
    // Must not be coerced to false, which would warn on every position
    // forever against a backend that simply predates the field.
    expect(r.open[0].quoteIsLive).not.toBe(false);
  });
});


// ---------------------------------------------------------------------------
// batch-80 item 1 — backlog "useData.js's apiFetch has no request timeout, so
// a HUNG backend freezes the whole dashboard silently instead of degrading"
// ---------------------------------------------------------------------------

describe('apiFetch request timeout', () => {
  const realFetch = global.fetch;
  beforeEach(() => { vi.stubGlobal('sessionStorage', createMemoryStorage()); });
  afterEach(() => { global.fetch = realFetch; vi.unstubAllGlobals(); });

  it('passes an AbortSignal to every endpoint fetch', async () => {
    // The defect was the ABSENCE of a signal, so this asserts a signal is
    // present and is a real AbortSignal -- not merely that fetch was called.
    const seen = [];
    global.fetch = (path, init) => {
      seen.push({ path, init });
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: 1 }) });
    };
    await fetchAllSafe(['/api/status'], () => null);
    expect(seen).toHaveLength(1);
    expect(seen[0].init.signal).toBeInstanceOf(AbortSignal);
    // Positive control: the headers the pre-existing code sent are still
    // there, so this proves the init object was extended rather than replaced.
    expect(seen[0].init.headers['X-Requested-With']).toBe('XMLHttpRequest');
  });

  it('a request that never settles resolves as a null feed, not a hang', async () => {
    // The whole point of the item. Uses a real AbortSignal.timeout with a
    // tiny budget and a fetch that only ever rejects when aborted -- i.e. a
    // faithful stand-in for a backend that accepts the connection and then
    // says nothing. Before the fix this promise never settled at all.
    let aborted = false;
    global.fetch = (path, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => {
        aborted = true;
        reject(Object.assign(new Error('timeout'), { name: 'TimeoutError' }));
      });
    });
    // 50ms budget, injected. Before fetchAllSafe threaded timeoutMs through,
    // this test genuinely waited out the full default (measured: 15008ms of
    // a 15.4s suite) while its own comment claimed a "tiny budget" -- and
    // apiFetch's timeoutMs parameter had no caller at all, so it was
    // decorative API surface. vi.useFakeTimers() cannot help here:
    // AbortSignal.timeout uses an internal timer, not the patched setTimeout.
    const results = await fetchAllSafe(['/api/status'], () => null, 50);
    expect(results).toHaveLength(1);
    // POSITIVE CONTROL, and the load-bearing half of this test: prove the
    // request was ended BY THE TIMEOUT. Without it, deleting the signal
    // entirely still passes -- the mock then throws a TypeError on the
    // missing signal, safe() swallows that into the same null, and the
    // assertions below cannot tell the two apart.
    expect(aborted).toBe(true);
    // safe() swallows non-auth failures into null, which is exactly what
    // every branch of fetchAll's merge already treats as "keep prior value".
    // That is what stops a timeout putting `undefined` where a tab expects
    // data -- trading a frozen dashboard for a crashing one.
    expect(results[0].status).toBe('fulfilled');
    expect(results[0].value).toBeNull();
  });

  it('the timeout budgets stay under the poll intervals that fire them', () => {
    // A timeout at or above its own poll interval lets requests stack, which
    // is the unbounded accumulation the item is about -- so these constants
    // are load-bearing, not decoration, and a later edit that raises either
    // past its interval should fail here rather than in production.
    expect(API_TIMEOUT_MS).toBeLessThan(60_000);        // main poll
    expect(SCAN_VERSION_TIMEOUT_MS).toBeLessThan(5_000); // scan-version poll
    // And above /api/weather-alerts' worst case: it fans out over
    // ThreadPoolExecutor(max_workers=8) with a per-city requests timeout=5,
    // so ceil(N/8) x 5s -- ~15s at CITY_COORDS' 21-city fallback.
    expect(API_TIMEOUT_MS).toBeGreaterThan(15_000);
    // opus review I4: the bounds above are a guardrail against a careless
    // edit, but they are satisfied by a wide range, so they say nothing
    // about the values actually chosen. Pin them too -- these were reasoned
    // from measured backend behaviour and a change to either should be a
    // deliberate one that updates this line.
    expect(API_TIMEOUT_MS).toBe(30_000);
    expect(SCAN_VERSION_TIMEOUT_MS).toBe(4_000);
  });
});

describe('anyFeedResolved', () => {
  it('is false when every endpoint failed — the hung-backend case', () => {
    expect(anyFeedResolved([null, null, null])).toBe(false);
    // Positive control: one survivor flips it, so the false above is about
    // the values and not about the function always returning false.
    expect(anyFeedResolved([null, { balance: 1 }, null])).toBe(true);
  });

  it('counts a genuinely empty but successful response as resolved', () => {
    // An empty list IS an answer. Treating it as a miss would suppress the
    // refresh marker on a perfectly healthy poll.
    expect(anyFeedResolved([[]])).toBe(true);
    expect(anyFeedResolved([{}])).toBe(true);
  });

  it('never throws on a non-array', () => {
    expect(anyFeedResolved(undefined)).toBe(false);
    expect(anyFeedResolved(null)).toBe(false);
  });
});

describe('orderFeedSuccess stats key (batch-80 item 1)', () => {
  it('matches mapStats own gate: a 200-with-an-error body is NOT a success', () => {
    // The predicate must be byte-for-byte mapStats' `status && !status.error`
    // gate, or the timestamp vouches for a merge that never happened.
    expect(orderFeedSuccess(null, undefined, null, { error: 'db locked' }).stats)
      .toBe(false);
    // Positive control: same shape without the error field does stamp.
    expect(orderFeedSuccess(null, undefined, null, { balance: 100 }).stats)
      .toBe(true);
  });

  it('pairs with mapStats: nothing stamps for a body mapStats refuses', () => {
    // The coupling is the invariant, so both halves are exercised together
    // here rather than asserted separately and left to drift.
    const errBody = { error: 'db locked', balance: 999 };
    const patch = mapStats(errBody, null, null, { balance: 5 });
    expect(patch.balance).toBe(5);   // mapStats took nothing from it
    expect(orderFeedSuccess(null, undefined, null, errBody).stats).toBe(false);
  });

  it('feeds mergeFetchedAt so only a real /api/status advances stats', () => {
    const NOW = 1_700_000_000_000;
    const prev = { stats: NOW - 500_000 };
    expect(mergeFetchedAt(prev, orderFeedSuccess(null, undefined, null, null), NOW))
      .toMatchObject({ stats: NOW - 500_000 });  // failed: carried forward
    expect(mergeFetchedAt(prev, orderFeedSuccess(null, undefined, null, { b: 1 }), NOW))
      .toMatchObject({ stats: NOW });            // succeeded: stamped
  });
});

describe('per-tab feed key lists (batch-80 item 1)', () => {
  // A tab's banner is a POOLED gate -- one verdict for several feeds -- so a
  // key that is misspelled or renamed silently inherits the pool's all-clear
  // and that feed goes unwatched with no visible symptom. This checks the
  // names mechanically against the map that actually produces them.
  const produced = Object.keys(
    orderFeedSuccess(mapTrades({ open: [], closed: [] }), [], null,
                     { b: 1 }, { c: 1 }, { d: 1 }),
  );

  it('every watched key is one orderFeedSuccess actually emits', () => {
    for (const k of [...OVERVIEW_FEED_KEYS, ...RISK_FEED_KEYS]) {
      expect(produced).toContain(k);
    }
    // Positive control: the check can fail. A name that is not produced must
    // not pass, or the loop above proves nothing.
    expect(produced).not.toContain('stat');
  });

  // opus review M4: the containment check above only pins MISSPELLINGS. It
  // is satisfied by an EMPTY list, so deleting 'positions' from
  // OVERVIEW_FEED_KEYS -- silently unwatching the positions feed -- passed.
  // Exact contents close that direction.
  it('the lists are exactly these keys, so a silent removal fails', () => {
    expect(OVERVIEW_FEED_KEYS).toEqual(['stats', 'positions', 'opportunities', 'graduation']);
    expect(RISK_FEED_KEYS).toEqual(['stats', 'positions', 'risk']);
  });

  // opus review M4, other half: a key ADDED to orderFeedSuccess and never
  // listed inherits the pool's all-clear and goes unwatched with no symptom
  // -- verbatim the case the rationale comment claimed was covered and was
  // not. Every produced key must be either watched or deliberately excluded,
  // so a new one forces a decision here rather than defaulting to unwatched.
  it('every key orderFeedSuccess emits is watched or explicitly excluded', () => {
    // Excluded = rendered by the OTHER tab, or reported by its own card.
    // RiskTab shows no opportunities and no graduation gates; OverviewTab
    // shows none of /api/risk's aged/correlated/expiry/directional figures;
    // anomalyStatus has its own dedicated card on RiskTab (batch-61).
    const RISK_EXCLUDED = ['anomalyStatus', 'opportunities', 'graduation'];
    const OVERVIEW_EXCLUDED = ['anomalyStatus', 'risk'];
    for (const k of produced) {
      expect(
        RISK_FEED_KEYS.includes(k) || RISK_EXCLUDED.includes(k),
        `RISK_FEED_KEYS neither watches nor excludes "${k}"`,
      ).toBe(true);
      expect(
        OVERVIEW_FEED_KEYS.includes(k) || OVERVIEW_EXCLUDED.includes(k),
        `OVERVIEW_FEED_KEYS neither watches nor excludes "${k}"`,
      ).toBe(true);
    }
    // Positive control: the exclusion lists name only keys that exist, so
    // they cannot be used to wave through a key that was renamed away.
    for (const k of [...RISK_EXCLUDED, ...OVERVIEW_EXCLUDED]) {
      expect(produced).toContain(k);
    }
  });

  it('both tabs watch the stats feed, which every headline number reads', () => {
    expect(OVERVIEW_FEED_KEYS).toContain('stats');
    expect(RISK_FEED_KEYS).toContain('stats');
  });

  it('RiskTab does not pool anomalyStatus — its own card reports that', () => {
    expect(RISK_FEED_KEYS).not.toContain('anomalyStatus');
  });
});

describe('nextStatsTimestamp (batch-80 item 1)', () => {
  const NOW = 1_700_000_000_000;
  const PREV = NOW - 60_000;

  it('does not re-stamp when every endpoint failed', () => {
    // The header's refresh countdown resets on this value changing, so an
    // unconditional stamp made a poll in which all 23 endpoints timed out
    // announce "just refreshed" -- the most reassuring the header can look,
    // during a total outage.
    expect(nextStatsTimestamp(PREV, [null, null, null], NOW)).toBe(PREV);
  });

  it('stamps when anything at all came back', () => {
    // Positive control for the assertion above: same shape, one survivor.
    expect(nextStatsTimestamp(PREV, [null, { balance: 1 }, null], NOW)).toBe(NOW);
  });

  it('a genuinely empty but successful response still counts as a refresh', () => {
    expect(nextStatsTimestamp(PREV, [[]], NOW)).toBe(NOW);
  });

  it('returns the previous value UNCHANGED, undefined included', () => {
    // MOCK.stats deliberately carries no timestamp, so `prev` really is
    // undefined on the first poll. App.jsx keys RefreshCountdown's effect on
    // [M.stats?.timestamp], and undefined -> null IS a dependency change, so
    // coercing here fired exactly one spurious "60s" reset on a cold load
    // against a hung backend -- the same false reassurance this function
    // removes everywhere else. The no-op has to be a true no-op.
    expect(nextStatsTimestamp(undefined, [null], NOW)).toBeUndefined();
    // Positive control: a real previous stamp is likewise returned as-is,
    // so the assertion above is about identity, not about undefined.
    expect(nextStatsTimestamp(PREV, [null], NOW)).toBe(PREV);
  });
});


// ---------------------------------------------------------------------------
// batch-80 item 1, opus review round 1 — M3 / M4 / I4
// ---------------------------------------------------------------------------

describe('makeScanVersionPoller (opus review M3)', () => {
  const realFetch = global.fetch;
  beforeEach(() => { vi.stubGlobal('sessionStorage', createMemoryStorage()); });
  afterEach(() => { global.fetch = realFetch; vi.unstubAllGlobals(); });

  function okResponse(version) {
    return Promise.resolve({ ok: true, json: async () => ({ version }) });
  }

  it('sends an AbortSignal on the 5s scan-version poll', async () => {
    // This assertion is the whole reason the poller was lifted out of the
    // mount useEffect. While it lived there, deleting its `signal:` left the
    // entire suite green -- half of this item's TIMEOUT deliverable had no
    // behavioural coverage at all.
    const seen = [];
    const poll = makeScanVersionPoller(() => {}, (path, init) => {
      seen.push({ path, init });
      return okResponse(1);
    });
    await poll();
    expect(seen).toHaveLength(1);
    expect(seen[0].path).toBe('/api/scan-version');
    expect(seen[0].init.signal).toBeInstanceOf(AbortSignal);
    // Positive control: the pre-existing auth header is still sent, so the
    // init object was extended rather than replaced.
    expect(seen[0].init.headers['X-Requested-With']).toBe('XMLHttpRequest');
  });

  it('fires onNewVersion only when the version CHANGES, never on first sight', async () => {
    // A null lastVersion must not fire, or every mount would trigger a
    // spurious full refresh. This is the behaviour the inline closure had;
    // extracting it must not have changed it.
    const fired = [];
    let version = 7;
    const poll = makeScanVersionPoller(() => fired.push(1), () => okResponse(version));
    await poll();
    expect(fired).toHaveLength(0);   // first sight: adopt, do not fire
    await poll();
    expect(fired).toHaveLength(0);   // unchanged: still nothing
    version = 8;
    await poll();
    expect(fired).toHaveLength(1);   // changed: fires exactly once
  });

  it('swallows a rejected fetch without throwing out of the interval', async () => {
    const poll = makeScanVersionPoller(() => { throw new Error('must not run'); },
      () => Promise.reject(new Error('timeout')));
    await expect(poll()).resolves.toBeUndefined();
  });

  it('ignores a non-ok response and a body with no version', async () => {
    const fired = [];
    const notOk = makeScanVersionPoller(() => fired.push(1),
      () => Promise.resolve({ ok: false, json: async () => ({ version: 1 }) }));
    await notOk();
    const noVersion = makeScanVersionPoller(() => fired.push(1),
      () => Promise.resolve({ ok: true, json: async () => ({}) }));
    await noVersion();
    expect(fired).toHaveLength(0);
  });
});

describe('timeoutSignal fallback (opus review L2)', () => {
  it('returns a real AbortSignal that aborts, with or without AbortSignal.timeout', async () => {
    // Vite transpiles syntax but does not polyfill runtime APIs, and
    // AbortSignal.timeout is Chrome 103+. On an older engine the bare call
    // throws -- and in makeScanVersionPoller it would throw during argument
    // evaluation, before fetch() returns a promise, so the trailing .catch()
    // could not attach and the 5s interval would raise uncaught every tick.
    const native = timeoutSignal(5);
    expect(native).toBeInstanceOf(AbortSignal);

    const realTimeout = AbortSignal.timeout;
    try {
      // eslint-disable-next-line no-import-assign
      AbortSignal.timeout = undefined;
      const fallback = timeoutSignal(5);
      expect(fallback).toBeInstanceOf(AbortSignal);
      expect(fallback.aborted).toBe(false);
      await new Promise(r => setTimeout(r, 40));
      // Positive control on the fallback: it must actually fire, not just
      // be an AbortSignal-shaped object that never aborts.
      expect(fallback.aborted).toBe(true);
    } finally {
      AbortSignal.timeout = realTimeout;
    }
  });
});
