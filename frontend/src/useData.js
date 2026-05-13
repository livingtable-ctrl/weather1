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
  return pwd ? { Authorization: 'Basic ' + btoa(':' + pwd) } : {};
}

async function apiFetch(path) {
  const res = await fetch(path, { headers: authHeader() });
  if (res.status === 401) {
    const p = window.prompt('Dashboard password:');
    if (p !== null) sessionStorage.setItem('kalshi-pwd', p);
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
function mapStats(status, grad, config, prevStats) {
  const base = { ...prevStats };

  if (status && !status.error) {
    if (status.balance          != null) base.balance          = status.balance;
    if (status.open_count       != null) base.open_count       = status.open_count;
    if (status.brier            != null) base.brier            = status.brier;
    if (status.kill_switch_active != null) base.kill_switch    = status.kill_switch_active;
    if (status.today_pnl        != null) base.today_pnl        = status.today_pnl;
    if (status.starting_balance != null) base.starting_balance = status.starting_balance;
    if (status.daily_spend      != null) base.daily_spend      = status.daily_spend;
    if (status.fear_greed_score != null) {
      base.fear_greed       = status.fear_greed_score;
      base.fear_greed_label = status.fear_greed_label;
    }
  }

  // max_daily_spend lives in /api/config, not /api/status
  if (config && !config.error && config.max_daily_spend != null) {
    base.max_daily_spend = config.max_daily_spend;
  }

  if (grad && !grad.error) {
    if (grad.win_rate  != null) base.win_rate  = grad.win_rate;
    if (grad.total_pnl != null) base.month_pnl = grad.total_pnl;
    if (grad.fear_greed_score != null && base.fear_greed == null) {
      base.fear_greed       = grad.fear_greed_score;
      base.fear_greed_label = grad.fear_greed_label;
    }
    base.graduation = {
      trades_done:   grad.trades_done   ?? base.graduation?.trades_done   ?? 0,
      trades_target: base.graduation?.trades_target ?? 30,
      total_pnl:     grad.total_pnl     ?? base.graduation?.total_pnl     ?? 0,
      pnl_target:    base.graduation?.pnl_target    ?? 50,
      brier:         grad.brier         ?? base.graduation?.brier         ?? null,
      brier_target:  base.graduation?.brier_target  ?? 0.20,
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
  weatherapi:           'WeatherAPI',
  pirate_weather:       'Pirate Weather',
  nws:                  'NWS / NBM',
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
    const markLive = t.current_yes_ask != null;
    return {
      id:         t.id,
      ticker:     t.ticker,
      city:       t.city,
      side:       t.side,
      cost:       t.cost,
      qty:        t.quantity,
      mark:       t.current_yes_ask ?? t.actual_fill_price ?? t.entry_price ?? 0,
      markIsLive: markLive,
      fcst:       t.entry_prob,
      edge:       t.net_edge,
      expiry:     t.target_date,
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
function mapSignals(raw) {
  if (!raw) return null;
  const sigs = Array.isArray(raw) ? raw : (raw.signals || []);
  return {
    signals: sigs.map(s => ({ ...s, side: (s.side || '').toLowerCase() })),
    generatedAt: raw.generated_at || null,
    stale: raw.stale || false,
    staleMessage: raw.message || null,
  };
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
  if (raw.city_heatmap)         patch.cityBrier        = raw.city_heatmap;
  if (raw.roc_auc        != null) patch.auc            = raw.roc_auc;
  if (raw.component_attribution) patch.pnlAttribution  = raw.component_attribution;
  return patch;
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
      const results = await Promise.allSettled([
        safe('/api/status'),            // 0
        safe('/api/graduation'),        // 1
        safe('/api/trades'),            // 2
        safe('/api/risk'),              // 3
        safe('/api/circuit-status'),    // 4
        safe('/api/balance_history'),   // 5
        safe('/api/analytics'),         // 6
        safe('/api/price-improvement'), // 7
        safe('/api/today_forecasts'),   // 8
        safe('/api/live_signals'),      // 9
        safe('/api/config'),            // 10
        safe('/api/ab-tests'),          // 11
        safe('/api/override'),          // 12
        safe('/api/system-events'),     // 13
        safe('/api/backup-status'),     // 14
        safe('/api/brier_history'),     // 15
      ]);

      // Unwrap allSettled — treat rejected as null
      const [
        statusR, gradR, tradesR, riskR,
        cbsR, balHistR, analyticsR,
        priceImpR, forecastsR, signalsR,
        configR, abTestsR, overrideR,
        systemEventsR, backupStatusR,
        brierHistoryR,
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
        const trades = mapTrades(tradesR);
        if (trades.closed?.length) next.closedTrades = trades.closed;
        if (trades.open?.length)   next.positions    = trades.open;

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
        const sigsResult = mapSignals(signalsR);
        if (sigsResult) {
          if (sigsResult.signals.length) next.opportunities = sigsResult.signals;
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
        if (Array.isArray(systemEventsR) && systemEventsR.length) next.alerts = systemEventsR;

        // Backup status (Settings / future footer)
        if (backupStatusR && !backupStatusR.error) next.backupStatus = backupStatusR;

        // Brier history trend (AnalyticsTab chart)
        if (Array.isArray(brierHistoryR) && brierHistoryR.length) next.brierHistory = brierHistoryR;

        return next;
      });
    } catch (e) {
      // AUTH errors: user was already prompted via window.prompt in apiFetch.
      // Reschedule a fresh fetch after 5 s so the new password is used.
      if (e.isAuth) {
        setTimeout(fetchAll, 5_000);
      }
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

    sse.addEventListener('open', () => setConnected(true));
    sse.addEventListener('error', () => setConnected(false));

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

  // ── Lifecycle ───────────────────────────────────────────────────────────
  useEffect(() => {
    fetchAll();
    startSSE();
    timerRef.current = setInterval(fetchAll, 60_000); // refresh every 60 s

    // Fast scan-version poll: detect cron completion without waiting 60 s.
    // Checks signals_cache.json mtime every 5 s; triggers fetchAll() the
    // moment the timestamp advances (i.e. a new cron run just finished).
    let lastVersion = null;
    const scanPollRef = setInterval(() => {
      fetch('/api/scan-version')
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
      sseRef.current?.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { ...data, refresh: fetchAll };
}
