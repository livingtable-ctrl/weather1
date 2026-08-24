/**
 * useData  — fetches all backend endpoints, merges into a single data object,
 * patches live updates from the SSE stream, and falls back to MOCK for any
 * missing or errored endpoint.
 *
 * Usage in App.jsx (replace the `const data = MOCK` stub line):
 *   import useData from './useData.js';
 *   const data = useData(setConnected);
 *
 * Auth note:
 *   Flask uses HTTP Basic Auth. REST calls use the Authorization header (stored
 *   in sessionStorage after a one-time window.prompt). EventSource cannot send
 *   custom headers, so SSE works only when DASHBOARD_PASSWORD is unset (open
 *   access) or when the browser has cached Basic Auth credentials from a prior
 *   page load. In all other cases `connected` stays false, but the 60-second
 *   polling still keeps data reasonably fresh.
 */

import { useState, useEffect, useRef } from 'react';
import MOCK from './mockData.js';

// ---------------------------------------------------------------------------
// Auth helpers
// ---------------------------------------------------------------------------
function getStoredPwd() {
  return sessionStorage.getItem('kalshi-pwd') || '';
}

export function authHeader() {
  const pwd = getStoredPwd();
  // X-Requested-With is a CSRF mitigation: a plain cross-site <form> POST (the
  // realistic vector against Basic Auth, since browsers re-attach cached Basic
  // credentials to same-origin requests regardless of the initiating page) can't
  // set custom headers, and a cross-origin fetch/XHR that tries to would trigger
  // a CORS preflight this server doesn't answer with permissive CORS headers, so
  // the browser blocks it. Every state-changing request in this app already
  // spreads authHeader() into its headers, so adding it here covers all of them
  // without touching each call site.
  const csrf = { 'X-Requested-With': 'XMLHttpRequest' };
  return pwd ? { ...csrf, Authorization: 'Basic ' + btoa(':' + pwd) } : csrf;
}

async function apiFetch(path) {
  const res = await fetch(path, { headers: authHeader() });
  if (res.status === 401) {
    throw Object.assign(new Error('AUTH'), { isAuth: true });
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Returns null on non-auth error; re-throws auth errors. */
async function safe(path) {
  try { return await apiFetch(path); }
  catch (e) {
    if (e.isAuth) throw e;
    return null;
  }
}

// ---------------------------------------------------------------------------
// Mappers  (endpoint JSON → MOCK-compatible shape)
// ---------------------------------------------------------------------------

/**
 * /api/status  + /api/graduation  → stats patch
 *
 * status  → {balance, open_count, brier, fear_greed_score, fear_greed_label,
 *             kill_switch_active, timestamp}
 * grad    → {trades_done, win_rate, total_pnl, brier, ready,
 *             fear_greed_score, fear_greed_label}
 */
export function mapStats(status, grad, config, prevStats) {
  const base = { ...prevStats };

  if (status && !status.error) {
    if (status.balance          != null) base.balance          = status.balance;
    if (status.open_count       != null) base.open_count       = status.open_count;
    // brier is always present on a successful response but can be a real null
    // (not enough settled predictions yet) -- a `!= null` gate would drop that
    // null and leave base.brier stuck on a stale/mock value forever.
    if ('brier' in status) base.brier = status.brier;
    if (status.kill_switch_active != null) base.kill_switch    = status.kill_switch_active;
    if (status.today_pnl        != null) base.today_pnl        = status.today_pnl;
    if (status.starting_balance != null) base.starting_balance = status.starting_balance;
    if (status.daily_spend      != null) base.daily_spend      = status.daily_spend;
    if (status.fear_greed_score != null) {
      base.fear_greed       = status.fear_greed_score;
      base.fear_greed_label = status.fear_greed_label;
    }
    // Drawdown risk row fields — new as of 2026-06-08 dashboard update
    if (status.peak_balance  != null) base.peak_balance  = status.peak_balance;
    if (status.halt_floor    != null) base.halt_floor    = status.halt_floor;
    if (status.kelly_factor  != null) base.kelly_factor  = status.kelly_factor;
    if (status.drawdown_pct  != null) base.drawdown_pct  = status.drawdown_pct;
    if (status.drawdown_tier != null) base.drawdown_tier = status.drawdown_tier;
    if (status.var_95      != null) base.var_95      = status.var_95;
    if (status.var_99      != null) base.var_99      = status.var_99;
    if (status.kalshi_env         != null) base.kalshi_env         = status.kalshi_env;
    if (status.is_live            != null) base.is_live            = status.is_live;
    if (status.portfolio_ev       != null) base.portfolio_ev       = status.portfolio_ev;
    if (status.portfolio_ev_roi_pct != null) base.portfolio_ev_roi_pct = status.portfolio_ev_roi_pct;
    if (status.portfolio_cost     != null) base.portfolio_cost     = status.portfolio_cost;
    // Backend omits EV fields when get_portfolio_expected_value() raises — clear
    // stale values so the card hides instead of showing old deployed capital.
    if (status.portfolio_ev == null && status.portfolio_cost == null) {
      delete base.portfolio_ev;
      delete base.portfolio_ev_roi_pct;
      delete base.portfolio_cost;
    }
  }

  // max_daily_spend lives in /api/config, not /api/status
  if (config && !config.error && config.max_daily_spend != null) {
    base.max_daily_spend = config.max_daily_spend;
  }

  if (grad && !grad.error) {
    if (grad.win_rate      != null) base.win_rate      = grad.win_rate;
    if (grad.profit_factor != null) base.profit_factor = grad.profit_factor;
    if (grad.total_pnl     != null) base.month_pnl     = grad.total_pnl;
    if (grad.fear_greed_score != null && base.fear_greed == null) {
      base.fear_greed       = grad.fear_greed_score;
      base.fear_greed_label = grad.fear_greed_label;
    }
    base.graduation = {
      trades_done:   grad.trades_done   ?? base.graduation?.trades_done   ?? 0,
      trades_target: grad.trades_target ?? base.graduation?.trades_target ?? 30,
      total_pnl:     grad.total_pnl     ?? base.graduation?.total_pnl     ?? 0,
      pnl_target:    grad.pnl_target    ?? base.graduation?.pnl_target    ?? 50,
      // audit-M-11: was `grad.brier ?? base.graduation?.brier ?? null` -- once
      // a real /api/graduation response succeeds (the `if (grad && !grad.error)`
      // gate above), an explicit null brier IS the real answer ("not enough
      // trades to compute yet"), not a fetch miss. Falling back to the prior
      // state here meant the very first successful-but-null response baked
      // MOCK's graduation.brier (0.151) into state permanently, since every
      // later poll's fallback read from that same now-tainted prevStats.
      brier:         grad.brier         ?? null,
      brier_target:  grad.brier_target  ?? base.graduation?.brier_target  ?? 0.20,
      ready:         grad.ready         ?? false,
    };
    // Derive settled_count from trades_done if not already set
    if (grad.trades_done != null) base.settled_count = grad.trades_done;
  }

  return base;
}

// CB label display names
const CB_LABELS = {
  open_meteo_forecast:  'Open-Meteo Forecast',
  open_meteo_ensemble:  'Open-Meteo Ensemble',
  nbm_openmeteo:        'NWS / NBM',
  nws:                  'NWS / NBM',
  weatherapi:           'WeatherAPI',
  pirate_weather:       'Pirate Weather',
  kalshi_api_read:      'Kalshi REST',
  climatology:          'Climatology',
};

/**
 * /api/circuit-status
 * → {open_meteo_forecast: {state, failures, retry_in_s, open_for_s}, ...}
 */
function mapCircuitBreakers(raw) {
  if (!raw || raw.error) return null;
  return Object.entries(raw).map(([key, cb]) => ({
    key,
    label:      CB_LABELS[key] || key,
    state:      cb.state      || 'closed',
    failures:   cb.failures   || 0,
    retry_in_s: cb.retry_in_s || 0,
    latency_ms: cb.latency_ms ?? null,
  }));
}

/**
 * Realizable mark for an open position, mirroring positions.liquidation_price()'s
 * convention: a YES holder can only sell at yes_bid, a NO holder only at
 * 1 - yes_ask (the NO bid) -- using the other side's price (or a mid) prices the
 * position at what a *buyer* would pay to open more, not what a *holder* can
 * actually realize by closing. A side price of 0 means no resting quote on that
 * side (not a real $0 market), so it's treated the same as a missing quote --
 * this also covers a NO position whose yes_ask is exactly 1.0 (a normal quote
 * on an illiquid/extreme-strike market, not an error), which would otherwise
 * compute a "live" mark of exactly 0 that the server's exit_price > 0 gate
 * would then reject with no manual-entry fallback offered. Unrecognized/
 * missing side falls to the NO branch, matching liquidation_price()'s own
 * if-yes/else-NO default. Falls back to entry_price/actual_fill_price only
 * for DISPLAY (markIsLive=false flags this so the UI can grey it out and
 * route Close through manual entry instead of silently submitting a
 * fabricated price) -- entry_price preferred first since it's what the
 * displayed cost-basis (cost/qty) is derived from, so the no-quote fallback
 * shows exactly $0 unrealized P&L rather than a few cents of phantom
 * gain/loss from actual_fill_price's extra fill-price precision.
 */
export function computeMark(t) {
  const side = (t.side || '').toLowerCase();
  const bid = t.current_yes_bid != null ? Number(t.current_yes_bid) : null;
  const ask = t.current_yes_ask != null ? Number(t.current_yes_ask) : null;
  const liveSidePrice = side === 'yes'
    ? (bid != null && bid > 0 ? bid : null)
    : (ask != null && ask > 0 ? 1 - ask : null);
  const markIsLive = liveSidePrice != null && liveSidePrice > 0;
  return {
    mark:       markIsLive ? liveSidePrice : (t.entry_price ?? t.actual_fill_price ?? 0),
    markIsLive,
  };
}

/**
 * /api/trades
 * → {open: [...paperTrade], closed: [...paperTrade]}
 *
 * Closed trades are passed through as-is (all fields the TradesTab uses are
 * already present in the paper_trades.json schema).
 * Open trades are shaped to match the PositionsTab's expected keys.
 */
function mapTrades(raw) {
  if (!raw) return { closed: null, open: null };

  const closed = (raw.closed || []).filter(t => t.settled);
  // Closed trades already have the right shape for TradesTab
  // (ticker, city, side, outcome, pnl, entered_at, actual_fill_price, net_edge, …)

  const open = (raw.open || []).map(t => {
    const { mark, markIsLive } = computeMark(t);
    return {
      id:         t.id,
      ticker:     t.ticker,
      city:       t.city,
      side:       t.side,
      cost:       t.cost,
      qty:        t.quantity,
      mark,
      markIsLive,
      fcst:       t.entry_prob,
      edge:       t.net_edge,
      // Use the date portion of close_time (when Kalshi closes the market)
      // rather than target_date (the observation day), which is one day early
      // for same-day trades that close overnight UTC.
      expiry:     t.close_time ? t.close_time.slice(0, 10) : t.target_date,
      close_time: t.close_time ?? null,
      model:      null,
      age_h:      t.entered_at
        ? Math.round((Date.now() - new Date(t.entered_at)) / 3_600_000)
        : 0,
    };
  });

  return { closed, open };
}

/**
 * /api/live_signals
 * → {signals: [...], summary: {...}, generated_at, stale?}
 *
 * Normalizes side to lowercase so SignalsTab doesn't need to care.
 */
export function mapSignals(raw) {
  if (!raw) return null;
  const sigs = raw.signals || [];
  return {
    signals: sigs.map(s => ({ ...s, side: (s.side || '').toLowerCase() })),
    generatedAt: raw.generated_at || null,
    stale: raw.stale || false,
    staleMessage: raw.message || null,
  };
}

// ---------------------------------------------------------------------------
// audit-M-11 (opus review MEDIUM-6): extracted so the reducer's exact fix is
// independently mutation-testable, not just its mapSignals()/Array.isArray
// preconditions. Both return `undefined` (never touch `next.*`) when the
// source fetch itself didn't produce real data -- distinct from a real
// response that's genuinely empty, which must be assigned so stale/MOCK
// data actually clears.
// ---------------------------------------------------------------------------

// mapSignals() always returns `.signals` as an array (possibly empty), never
// null/undefined, whenever sigsResult itself is non-null -- so this can
// safely be unconditional once sigsResult exists.
export function resolveOpportunities(sigsResult) {
  return sigsResult ? sigsResult.signals : undefined;
}

// Array.isArray alone, NOT `&& raw.length` -- a real empty array (0 alerts,
// 0 brier-history points) is real data and must replace MOCK's fabricated
// seed, not be treated the same as "the fetch failed".
export function resolveIfArray(raw) {
  return Array.isArray(raw) ? raw : undefined;
}

/**
 * /api/today_forecasts
 * → {today: {city: {high_f, low_f, precip_in, models_used, high_range}}, tomorrow: {...}}
 */
function mapForecasts(raw) {
  if (!raw || raw.error) return null;
  const result = {};
  if (raw.today    && Object.keys(raw.today).length)    result.todayForecasts    = raw.today;
  if (raw.tomorrow && Object.keys(raw.tomorrow).length) result.tomorrowForecasts = raw.tomorrow;
  return Object.keys(result).length ? result : null;
}

/**
 * /api/risk
 * → {city_exposure, directional: {yes, no}, expiry_clustering,
 *    total_exposure, aged_positions, correlated_events}
 */
function mapRisk(raw) {
  if (!raw || raw.error) return {};
  const patch = {};
  if (Array.isArray(raw.aged_positions))    patch.agedPositions    = raw.aged_positions;
  if (Array.isArray(raw.correlated_events)) patch.correlatedEvents = raw.correlated_events;
  if (Array.isArray(raw.expiry_clustering)) patch.expiryCluster    = raw.expiry_clustering;
  if (raw.directional) {
    patch.directionalBias = {
      yes: raw.directional.yes || 0,
      no:  raw.directional.no  || 0,
    };
  }
  return patch;
}

/**
 * /api/analytics
 * → {brier, brier_by_days, city_calibration, component_attribution,
 *    roc_auc?, confusion_matrix?, …}
 */
function mapAnalytics(raw) {
  if (!raw || raw.error) return {};
  const patch = {};
  if (raw.brier_by_days)        patch.brierByDays      = raw.brier_by_days;
  if (raw.city_calibration)     patch.cityCalibration  = raw.city_calibration;
  // roc_auc is a dict {auc, n, points} — extract the float
  if (raw.roc_auc?.auc != null) patch.auc              = raw.roc_auc.auc;
  if (raw.component_attribution) patch.brierBySource   = raw.component_attribution;
  return patch;
}

/**
 * /api/sameday-calibration
 * → {n, gate, gate_met, brier, t_sameday, calibration_buckets, by_time_of_day}
 * Passed through as-is — the dashboard card reads the raw shape directly.
 */
function mapSamedayCalib(raw) {
  if (!raw || raw.error) return null;
  return raw;
}

/**
 * /api/price-improvement
 * → {avg_improvement_cents, total_trades, median_improvement_cents, positive_pct}
 *
 * Filters out TKTEST synthetic rows — the endpoint may already do this, but
 * guard against total_trades with only synthetic data by checking for
 * avg_improvement_cents === null.
 */
function mapPriceImprovement(raw) {
  if (!raw || raw.error) return null;
  if (raw.avg_improvement_cents == null) return null; // insufficient real data
  return raw;
}

const ENDPOINTS = [
  '/api/status',               // 0
  '/api/graduation',           // 1
  '/api/trades',               // 2
  '/api/risk',                 // 3
  '/api/circuit-status',       // 4
  '/api/balance_history',      // 5
  '/api/analytics',            // 6
  '/api/price-improvement',    // 7
  '/api/today_forecasts',      // 8
  '/api/live_signals',         // 9
  '/api/config',               // 10
  '/api/ab-tests',             // 11
  '/api/override',             // 12
  '/api/system-events',        // 13
  '/api/backup-status',        // 14
  '/api/brier_history',        // 15
  '/api/forecast_quality',     // 16
  '/api/sameday-calibration',  // 17
  '/api/anomaly-status',       // 18
  '/api/calibration-status',   // 19
  '/api/scan-stats',           // 20
  '/api/emos-status',          // 21
];

/**
 * Runs `safe(path)` for every endpoint in `endpoints` in parallel. A batch
 * 401 (missing/stale stored password) hits every endpoint in the same
 * Promise.allSettled at once — prompting inside apiFetch itself (the old
 * behavior) meant every failing endpoint independently called
 * window.prompt(), i.e. up to `endpoints.length` blocking dialogs in a row,
 * and entering the password correctly on an early one couldn't fix the
 * later ones, since their requests had already been sent (and 401'd) before
 * that password existed. This prompts exactly ONCE per batch, after every
 * endpoint has settled, and retries only the ones that actually failed
 * auth — a correct password then completes this same batch instead of
 * leaving those endpoints null until the next scheduled poll.
 * `promptFn` is injectable so this can be unit-tested without a real browser
 * `window.prompt`.
 *
 * Two overlapping calls (e.g. the 60s poll firing while a "cron just
 * finished" fast-refresh is still in flight) can each independently hit a
 * batch 401 here. Snapshotting the stored password before this batch's
 * fetches go out, and re-checking it after they settle, lets a later call
 * detect that an earlier call's prompt already resolved while this one was
 * waiting — skipping its own prompt and retrying straight away with the
 * password that's already there, instead of asking the operator twice for
 * one real auth event.
 */
export async function fetchAllSafe(endpoints, promptFn = window.prompt) {
  const pwdBefore = sessionStorage.getItem('kalshi-pwd');
  const results = await Promise.allSettled(endpoints.map(safe));

  const authFailedIdx = results
    .map((r, i) => (r.status === 'rejected' && r.reason?.isAuth ? i : -1))
    .filter((i) => i !== -1);
  if (authFailedIdx.length) {
    let havePwd = sessionStorage.getItem('kalshi-pwd') !== pwdBefore;
    if (!havePwd) {
      const p = promptFn('Dashboard password:');
      if (p !== null) {
        sessionStorage.setItem('kalshi-pwd', p);
        havePwd = true;
      }
    }
    if (havePwd) {
      const retried = await Promise.allSettled(
        authFailedIdx.map((i) => safe(endpoints[i]))
      );
      authFailedIdx.forEach((idx, j) => { results[idx] = retried[j]; });
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// Main hook
// ---------------------------------------------------------------------------
export default function useData(setConnected) {
  const [data, setData] = useState(MOCK);
  const sseRef  = useRef(null);
  const timerRef = useRef(null);

  // ── Fetch all endpoints in parallel ────────────────────────────────────
  async function fetchAll() {
    try {
      const results = await fetchAllSafe(ENDPOINTS);

      // Unwrap allSettled — treat rejected as null
      const [
        statusR, gradR, tradesR, riskR,
        cbsR, balHistR, analyticsR,
        priceImpR, forecastsR, signalsR,
        configR, abTestsR, overrideR,
        systemEventsR, backupStatusR,
        brierHistoryR, forecastQualityR,
        samedayCalibR,
        anomalyStatusR, calibStatusR, scanStatsR,
        emosStatusR,
      ] = results.map(r => r.status === 'fulfilled' ? r.value : null);

      setData(prev => {
        // Start from the current state so SSE patches aren't wiped
        const next = { ...prev };

        // Stats (status + graduation + config for max_daily_spend)
        const statsPatch = mapStats(statusR, gradR, configR, prev.stats);
        next.stats = { ...MOCK.stats, ...statsPatch };

        // Circuit breakers
        const cbs = mapCircuitBreakers(cbsR);
        if (cbs?.length) next.circuitBreakers = cbs;

        // Trades → closedTrades + positions
        // (checking != null, not .length, so a genuinely empty list --
        // closing the last open position, or zero closed trades ever --
        // actually clears the UI instead of leaving stale/mock data behind;
        // mapTrades only returns null for closed/open when the fetch itself
        // failed, which is the one case we want to keep the prior state for)
        const trades = mapTrades(tradesR);
        if (trades.closed != null) next.closedTrades = trades.closed;
        if (trades.open != null)   next.positions    = trades.open;

        // Balance history — endpoint returns {labels, values, points}
        if (Array.isArray(balHistR?.points) && balHistR.points.length) next.balanceHist = balHistR.points;

        // Risk metrics
        Object.assign(next, mapRisk(riskR));

        // Analytics
        Object.assign(next, mapAnalytics(analyticsR));

        // Price improvement
        const pi = mapPriceImprovement(priceImpR);
        if (pi) next.priceImprovement = pi;

        // Forecasts
        const forecasts = mapForecasts(forecastsR);
        if (forecasts) Object.assign(next, forecasts);

        // Signals / opportunities
        // audit-M-11: was `if (sigsResult.signals.length)` -- mapSignals
        // always returns signals as an array (never null) whenever sigsResult
        // itself is non-null, so a real empty scan (`raw.signals: []`) kept
        // MOCK's 7 fabricated opportunities on screen under a genuine "Last
        // scan: Nm ago" header, live Approve buttons included. resolveOpportunities
        // (exported, unit-tested) makes this exact fix independently
        // mutation-testable rather than only testing mapSignals' precondition.
        const sigsResult = mapSignals(signalsR);
        const resolvedOpportunities = resolveOpportunities(sigsResult);
        if (resolvedOpportunities !== undefined) next.opportunities = resolvedOpportunities;
        if (sigsResult) {
          next.signalsMeta = {
            generatedAt: sigsResult.generatedAt,
            stale: sigsResult.stale,
            staleMessage: sigsResult.staleMessage,
          };
        }

        // Bot config (SettingsTab config grid)
        if (configR && !configR.error) next.config = configR;

        // A/B tests (SettingsTab A/B section)
        if (Array.isArray(abTestsR)) next.abTests = abTestsR;

        // Manual override (SettingsTab override panel)
        if (overrideR && !overrideR.error) {
          next.stats = {
            ...next.stats,
            override_until:  overrideR.expires_at  ?? null,
            override_reason: overrideR.reason       ?? null,
          };
        }

        // System events feed (OverviewTab alerts)
        // audit-M-11: same truthy-length bug as opportunities above -- a
        // real empty events feed kept MOCK's alerts on screen forever.
        // resolveIfArray (exported, unit-tested) makes this fix independently
        // mutation-testable.
        const resolvedAlerts = resolveIfArray(systemEventsR);
        if (resolvedAlerts !== undefined) next.alerts = resolvedAlerts;

        // Backup status (Settings / future footer)
        if (backupStatusR && !backupStatusR.error) next.backupStatus = backupStatusR;

        // Brier history trend (AnalyticsTab chart)
        // audit-M-11: same truthy-length bug -- a real empty history kept
        // MOCK's weekly Brier trend on screen forever.
        const resolvedBrierHistory = resolveIfArray(brierHistoryR);
        if (resolvedBrierHistory !== undefined) next.brierHistory = resolvedBrierHistory;

        // City calibration Brier scores — replace mock data with real values.
        // API returns {CityName: {brier, bias, n}}; extract .brier float.
        // If empty {} (not enough trades yet), clear mock so chart shows empty state.
        if (forecastQualityR && forecastQualityR.city_heatmap != null) {
          const raw = forecastQualityR.city_heatmap;
          const normalized = {};
          for (const [city, val] of Object.entries(raw)) {
            normalized[city] = typeof val === 'object' && val !== null ? val.brier : val;
          }
          next.cityBrier = normalized;
        }

        // Same-day METAR calibration — separate from multi-day, own card in Analytics tab.
        const sd = mapSamedayCalib(samedayCalibR);
        if (sd) next.samedayCalibration = sd;

        // Anomaly window — win-rate collapse detection state
        if (anomalyStatusR && !anomalyStatusR.error) next.anomalyStatus = anomalyStatusR;

        // Multi-day temperature-scaling calibration gate
        if (calibStatusR && !calibStatusR.error) next.calibrationStatus = calibStatusR;

        // Scan filter rejection counts from last cron run
        if (scanStatsR && !scanStatsR.error) next.scanStats = scanStatsR;

        // EMOS calibration status
        if (emosStatusR) next.emosStatus = emosStatusR;

        return next;
      });
    } catch {
      // Unexpected error in the merge/mapping logic above (not an endpoint
      // fetch failure — those are already caught per-endpoint by safe()).
      // Only catches synchronous throws in this try block, e.g. a bad
      // response shape from a mapper — a throw inside setData's updater
      // itself may surface as a React render error this can't see. Swallow
      // what it does catch so it doesn't kill the polling loop; the next
      // scheduled fetchAll() retries regardless.
    }
  }

  // ── SSE live patch ──────────────────────────────────────────────────────
  // SSE can't carry auth headers. Works when DASHBOARD_PASSWORD is unset
  // (open access) or when the browser has cached Basic Auth from prior login.
  // Falls back gracefully to polling-only if auth is required.
  //
  // SSE payload: {balance, open_count, brier, markets, ts}
  function startSSE() {
    if (sseRef.current) sseRef.current.close();

    const sse = new EventSource('/api/stream');
    sseRef.current = sse;

    let errorCount = 0;
    sse.addEventListener('open', () => { setConnected(true); errorCount = 0; });
    sse.addEventListener('error', () => {
      setConnected(false);
      errorCount++;
      // After 2 consecutive errors (covers auth 401 loop) give up — polling keeps data fresh.
      if (errorCount >= 2) {
        sse.close();
        sseRef.current = null;
      }
    });

    // Unnamed messages
    sse.addEventListener('message', handleSSEEvent);
    // Flask may send named 'status' events
    sse.addEventListener('status', handleSSEEvent);
  }

  function handleSSEEvent(e) {
    try {
      const update = JSON.parse(e.data);
      setData(prev => ({
        ...prev,
        stats: {
          ...prev.stats,
          ...(update.balance    != null && { balance:    update.balance    }),
          ...(update.open_count != null && { open_count: update.open_count }),
          ...(update.brier      != null && { brier:      update.brier      }),
        },
      }));
      setConnected(true);
    } catch { /* ignore parse errors */ }
  }

  // ── Weather alerts — separate 15-minute poll (NWS API is slow) ─────────
  async function fetchWeatherAlerts() {
    try {
      const result = await safe('/api/weather-alerts');
      if (result) setData(prev => ({ ...prev, weatherAlerts: result }));
    } catch { /* ignore */ }
  }

  // ── Lifecycle ───────────────────────────────────────────────────────────
  useEffect(() => {
    fetchAll();
    fetchWeatherAlerts();
    startSSE();
    timerRef.current = setInterval(fetchAll, 60_000); // refresh every 60 s
    const alertsPollRef = setInterval(fetchWeatherAlerts, 900_000); // 15 minutes

    // Fast scan-version poll: detect cron completion without waiting 60 s.
    // Checks signals_cache.json mtime every 5 s; triggers fetchAll() the
    // moment the timestamp advances (i.e. a new cron run just finished).
    let lastVersion = null;
    const scanPollRef = setInterval(() => {
      fetch('/api/scan-version', { headers: authHeader() })
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (!d || d.version == null) return;
          if (lastVersion !== null && d.version !== lastVersion) fetchAll();
          lastVersion = d.version;
        })
        .catch(() => {});
    }, 5_000);

    return () => {
      clearInterval(timerRef.current);
      clearInterval(scanPollRef);
      clearInterval(alertsPollRef);
      sseRef.current?.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { ...data, refresh: fetchAll };
}
