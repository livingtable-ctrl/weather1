// =============================================================================
// TEMPORARY SCAFFOLD — DELETE ONCE ALL /api/* ENDPOINTS ARE WIRED IN useData.js
// This file exists only so the UI renders during development before the backend
// endpoints are live. Every key here maps to a real endpoint listed in useData.js.
// =============================================================================

function balanceWalk(start, days, drift, vol, seed) {
  let s = seed || 1;
  function rng() { s = (s * 9301 + 49297) % 233280; return s / 233280; }
  const out = [];
  let bal = start;
  const now = Date.now();
  for (let i = 0; i < days; i++) {
    bal += drift + (rng() - 0.5) * vol;
    out.push({ t: now - (days - i) * 86400000, v: +bal.toFixed(2) });
  }
  return out;
}

const positions = [
  { ticker: 'KXHIGHNY-26MAY07-T68',  city: 'New York',     side: 'yes', cost: 42.50, qty: 100, mark: 0.51, fcst: 0.62, edge: 0.11, expiry: '2026-05-07', model: 'NBM',  age_h: 4  },
  { ticker: 'KXHIGHCHI-26MAY07-T72', city: 'Chicago',      side: 'no',  cost: 28.00, qty: 80,  mark: 0.38, fcst: 0.29, edge: 0.09, expiry: '2026-05-07', model: 'ICON', age_h: 6  },
  { ticker: 'KXHIGHMIA-26MAY08-T85', city: 'Miami',        side: 'yes', cost: 65.10, qty: 150, mark: 0.44, fcst: 0.58, edge: 0.14, expiry: '2026-05-08', model: 'GFS',  age_h: 11 },
  { ticker: 'KXHIGHLAX-26MAY07-T78', city: 'Los Angeles',  side: 'yes', cost: 35.00, qty: 100, mark: 0.39, fcst: 0.47, edge: 0.08, expiry: '2026-05-07', model: 'NBM',  age_h: 2  },
  { ticker: 'KXRAINNY-26MAY08',      city: 'New York',     side: 'no',  cost: 19.20, qty: 60,  mark: 0.32, fcst: 0.21, edge: 0.11, expiry: '2026-05-08', model: 'HRRR', age_h: 13 },
  { ticker: 'KXHIGHATL-26MAY09-T81', city: 'Atlanta',      side: 'yes', cost: 51.40, qty: 120, mark: 0.43, fcst: 0.55, edge: 0.12, expiry: '2026-05-09', model: 'ICON', age_h: 18 },
  { ticker: 'KXHIGHDEN-26MAY10-T64', city: 'Denver',       side: 'no',  cost: 22.00, qty: 50,  mark: 0.45, fcst: 0.34, edge: 0.11, expiry: '2026-05-10', model: 'NBM',  age_h: 22 },
  { ticker: 'KXLOWBOS-26MAY08-T48',  city: 'Boston',       side: 'yes', cost: 38.50, qty: 100, mark: 0.39, fcst: 0.49, edge: 0.10, expiry: '2026-05-08', model: 'GFS',  age_h: 5  },
];

const opportunities = [
  { ticker: 'KXHIGHSEA-26MAY09-T58', city: 'Seattle',       side: 'yes', yes_ask: 0.34, fcst: 0.51, edge: 0.17, tier: 'STRONG' },
  { ticker: 'KXHIGHHOU-26MAY08-T88', city: 'Houston',       side: 'no',  yes_ask: 0.62, fcst: 0.46, edge: 0.16, tier: 'STRONG' },
  { ticker: 'KXHIGHPHX-26MAY09-T92', city: 'Phoenix',       side: 'yes', yes_ask: 0.41, fcst: 0.55, edge: 0.14, tier: 'MED' },
  { ticker: 'KXRAINSF-26MAY08',      city: 'San Francisco', side: 'yes', yes_ask: 0.28, fcst: 0.40, edge: 0.12, tier: 'MED' },
  { ticker: 'KXHIGHDFW-26MAY10-T82', city: 'Dallas',        side: 'yes', yes_ask: 0.45, fcst: 0.56, edge: 0.11, tier: 'MED' },
  { ticker: 'KXHIGHPDX-26MAY09-T62', city: 'Portland',      side: 'no',  yes_ask: 0.58, fcst: 0.46, edge: 0.12, tier: 'MED' },
  { ticker: 'KXLOWMSP-26MAY08-T42',  city: 'Minneapolis',   side: 'yes', yes_ask: 0.36, fcst: 0.45, edge: 0.09, tier: 'LOW' },
];
opportunities.forEach((opp, i) => {
  opp.model_agreement = [92, 88, 76, 84, 79, 81, 71][i];
  opp.volume          = ['2.4k', '1.8k', '3.1k', '890', '1.2k', '950', '1.5k'][i];
  opp.stars           = opp.edge >= 0.15 ? '★★★' : opp.edge >= 0.10 ? '★★' : '★';
  opp.time_risk       = i < 2 ? 'LOW' : i < 5 ? 'MEDIUM' : 'HIGH';
  opp.near_threshold  = i === 3;
  opp.is_hedge        = i === 5;
  opp.kelly_dollars   = opp.edge * 1000 * 0.18;
  opp.already_held    = false;
  opp.forecast_prob   = opp.fcst * 100;
  opp.market_prob     = opp.yes_ask * 100;
  opp.edge_pct        = opp.edge * 100;
});

const balanceHist = balanceWalk(1000, 90, 1.85, 18, 7);

const circuitBreakers = [
  { key: 'open_meteo_forecast', label: 'Open-Meteo Forecast', state: 'closed', failures: 0, retry_in_s: 0,  latency_ms: 142  },
  { key: 'open_meteo_ensemble', label: 'Open-Meteo Ensemble', state: 'closed', failures: 1, retry_in_s: 0,  latency_ms: 281  },
  { key: 'nws',                 label: 'NWS / NBM',           state: 'closed', failures: 0, retry_in_s: 0,  latency_ms: 198  },
  { key: 'pirate_weather',      label: 'Pirate Weather',      state: 'open',   failures: 4, retry_in_s: 87, latency_ms: null },
  { key: 'kalshi_rest',         label: 'Kalshi REST',         state: 'closed', failures: 0, retry_in_s: 0,  latency_ms: 89   },
  { key: 'kalshi_ws',           label: 'Kalshi WebSocket',    state: 'closed', failures: 0, retry_in_s: 0,  latency_ms: 12   },
];

const recentTrades = [
  { ts: '2026-05-06 09:14', ticker: 'KXHIGHNY-26MAY06-T70',  city: 'New York',    side: 'yes', cost: 42.00, payout: 100, pnl: +58.00, brier: 0.048, model: 'NBM',  result: 'win'  },
  { ts: '2026-05-06 08:42', ticker: 'KXHIGHCHI-26MAY06-T68', city: 'Chicago',     side: 'no',  cost: 38.00, payout: 100, pnl: +62.00, brier: 0.064, model: 'ICON', result: 'win'  },
  { ts: '2026-05-06 08:03', ticker: 'KXHIGHMIA-26MAY06-T84', city: 'Miami',       side: 'yes', cost: 51.00, payout: 0,   pnl: -51.00, brier: 0.301, model: 'GFS',  result: 'loss' },
  { ts: '2026-05-05 17:55', ticker: 'KXHIGHLAX-26MAY05-T76', city: 'Los Angeles', side: 'yes', cost: 33.00, payout: 100, pnl: +67.00, brier: 0.082, model: 'NBM',  result: 'win'  },
  { ts: '2026-05-05 14:28', ticker: 'KXRAINBOS-26MAY05',     city: 'Boston',      side: 'no',  cost: 22.00, payout: 100, pnl: +78.00, brier: 0.041, model: 'HRRR', result: 'win'  },
  { ts: '2026-05-05 11:11', ticker: 'KXHIGHDEN-26MAY05-T60', city: 'Denver',      side: 'yes', cost: 41.00, payout: 0,   pnl: -41.00, brier: 0.213, model: 'NBM',  result: 'loss' },
  { ts: '2026-05-04 19:02', ticker: 'KXHIGHATL-26MAY04-T79', city: 'Atlanta',     side: 'yes', cost: 47.00, payout: 100, pnl: +53.00, brier: 0.071, model: 'ICON', result: 'win'  },
  { ts: '2026-05-04 16:40', ticker: 'KXLOWBOS-26MAY04-T46',  city: 'Boston',      side: 'no',  cost: 35.00, payout: 100, pnl: +65.00, brier: 0.063, model: 'GFS',  result: 'win'  },
];

const modelAccuracy = [
  { model: 'NBM',  trades: 182, brier: 0.143, win_rate: 0.61, edge_realized: 0.082 },
  { model: 'ICON', trades: 156, brier: 0.168, win_rate: 0.57, edge_realized: 0.064 },
  { model: 'GFS',  trades: 141, brier: 0.182, win_rate: 0.54, edge_realized: 0.051 },
  { model: 'HRRR', trades: 88,  brier: 0.171, win_rate: 0.58, edge_realized: 0.061 },
  { model: 'Ens.', trades: 567, brier: 0.151, win_rate: 0.60, edge_realized: 0.072 },
];

const calibration = [
  { bucket: 0.10, realized: 0.12, n: 41 },
  { bucket: 0.20, realized: 0.18, n: 58 },
  { bucket: 0.30, realized: 0.27, n: 72 },
  { bucket: 0.40, realized: 0.39, n: 88 },
  { bucket: 0.50, realized: 0.49, n: 96 },
  { bucket: 0.60, realized: 0.61, n: 81 },
  { bucket: 0.70, realized: 0.74, n: 67 },
  { bucket: 0.80, realized: 0.83, n: 41 },
  { bucket: 0.90, realized: 0.91, n: 23 },
];

let _bs = 11;
function _brng() { _bs = (_bs * 9301 + 49297) % 233280; return _bs / 233280; }
const brierHist = (() => {
  const out = []; let v = 0.22;
  for (let i = 0; i < 60; i++) {
    v += (_brng() - 0.55) * 0.01;
    v = Math.max(0.10, Math.min(0.25, v));
    out.push({ t: Date.now() - (60 - i) * 86400000, v: +v.toFixed(4) });
  }
  return out;
})();

const pnlAttribution = [
  { source: 'Model edge (NBM)',      pnl: +312.40 },
  { source: 'Model edge (Ensemble)', pnl: +218.60 },
  { source: 'Climatology bias',      pnl:  +84.10 },
  { source: 'Settlement lag',        pnl:  +61.30 },
  { source: 'ML calibration',        pnl:  +47.20 },
  { source: 'Slippage',              pnl:  -29.10 },
  { source: 'Fees (7% taker)',       pnl: -136.50 },
];

const alerts = [
  { ts: '09:14', level: 'warn', text: 'Pirate Weather circuit OPEN — failover to NWS/NBM' },
  { ts: '08:33', level: 'info', text: 'Auto-trade placed: KXHIGHATL-26MAY09 NO @ 0.43 (edge +12%)' },
  { ts: '07:50', level: 'info', text: 'Cron scan completed — 23 markets scanned, 4 trades placed' },
  { ts: '06:02', level: 'info', text: 'Daily backup → OneDrive/KalshiBot/data/ (1.4 MB)' },
  { ts: '21:18', level: 'good', text: 'Graduation gate: 28/30 trades · +$47 P&L · Brier 0.151' },
];

const forecastDetail = {
  city: 'Seattle',
  market: 'KXHIGHSEA-26MAY09-T58',
  threshold: 58,
  sources: [
    { name: 'NWS / NBM',   point: 60, p_over: 0.54, weight: 0.40 },
    { name: 'ICON',        point: 61, p_over: 0.58, weight: 0.22 },
    { name: 'GFS',         point: 59, p_over: 0.49, weight: 0.20 },
    { name: 'HRRR',        point: 62, p_over: 0.55, weight: 0.10 },
    { name: 'Climatology', point: 56, p_over: 0.36, weight: 0.08 },
  ],
  ensemble_p_over: 0.51,
  market_yes_ask: 0.34,
  edge: 0.17,
  confidence: 'STRONG',
};

const stats = {
  balance: 1247.83,
  starting_balance: 1000,
  open_count: 8,
  daily_spend: 184.30,
  max_daily_spend: 500,
  win_rate: 0.612,
  brier: 0.151,
  today_pnl: +127.40,
  week_pnl: +312.10,
  month_pnl: +247.83,
  settled_count: 567,
  fear_greed: 68,
  fear_greed_label: 'Greed',
  graduation: { trades_done: 567, trades_target: 30, total_pnl: 247.83, pnl_target: 50, brier: 0.151, brier_target: 0.20, ready: true },
  kill_switch: false,
  override_until: null,
  strategy: 'kelly',
  env: 'demo',
};

const mlModels = [
  { city: 'New York',    trades: 248, brier_before: 0.171, brier_after: 0.142, lift: 0.029, last_trained: '2026-05-04' },
  { city: 'Chicago',     trades: 211, brier_before: 0.183, brier_after: 0.156, lift: 0.027, last_trained: '2026-05-03' },
  { city: 'Miami',       trades: 198, brier_before: 0.165, brier_after: 0.149, lift: 0.016, last_trained: '2026-05-02' },
  { city: 'Los Angeles', trades: 224, brier_before: 0.158, brier_after: 0.139, lift: 0.019, last_trained: '2026-05-04' },
  { city: 'Atlanta',     trades: 187, brier_before: 0.176, brier_after: 0.151, lift: 0.025, last_trained: '2026-05-01' },
  { city: 'Denver',      trades: 156, brier_before: 0.192, brier_after: 0.168, lift: 0.024, last_trained: '2026-05-03' },
  { city: 'Seattle',     trades: 132, brier_before: 0.188, brier_after: 0.171, lift: 0.017, last_trained: '2026-04-30' },
  { city: 'Boston',      trades: 145, brier_before: 0.169, brier_after: 0.148, lift: 0.021, last_trained: '2026-05-02' },
];

const todayForecasts = {
  Chicago:  { high_f: 72.3, low_f: 58.1, high_range: [70.8, 73.9], precip_in: 0.02, models_used: 4 },
  NYC:      { high_f: 68.7, low_f: 55.4, high_range: [67.2, 70.1], precip_in: 0.18, models_used: 4 },
  LA:       { high_f: 81.2, low_f: 64.9, high_range: [79.5, 82.6], precip_in: 0,    models_used: 3 },
  Phoenix:  { high_f: 94.5, low_f: 71.2, high_range: [93.1, 95.8], precip_in: 0,    models_used: 4 },
  Miami:    { high_f: 87.3, low_f: 76.8, high_range: [86.9, 88.1], precip_in: 0.42, models_used: 4 },
};
const tomorrowForecasts = {
  Chicago:  { high_f: 75.8, low_f: 61.2, high_range: [74.1, 77.3], precip_in: 0,    models_used: 4 },
  NYC:      { high_f: 71.4, low_f: 58.9, high_range: [69.8, 72.7], precip_in: 0.05, models_used: 4 },
  LA:       { high_f: 82.6, low_f: 66.1, high_range: [81.2, 83.9], precip_in: 0,    models_used: 3 },
  Phoenix:  { high_f: 96.2, low_f: 72.8, high_range: [94.8, 97.4], precip_in: 0,    models_used: 4 },
  Miami:    { high_f: 88.1, low_f: 77.3, high_range: [87.5, 89.2], precip_in: 0.28, models_used: 4 },
};

const cityBrier = {
  'New York': 0.142, 'Chicago': 0.156, 'LA': 0.138,
  'Phoenix': 0.167, 'Houston': 0.149, 'Miami': 0.171,
  'Dallas': 0.145, 'Boston': 0.153,
};

const rocCurve = [
  { fpr: 0, tpr: 0 }, { fpr: 0.05, tpr: 0.32 }, { fpr: 0.12, tpr: 0.58 },
  { fpr: 0.21, tpr: 0.74 }, { fpr: 0.35, tpr: 0.86 }, { fpr: 0.52, tpr: 0.93 },
  { fpr: 0.71, tpr: 0.97 }, { fpr: 0.88, tpr: 0.99 }, { fpr: 1, tpr: 1 },
];
const auc = 0.847;

const brierByDays = { '1': 0.189, '2': 0.198, '3': 0.214, '4': 0.237, '5': 0.268, '6': 0.291, '7': 0.312 };

const priceImprovement = {
  avg_improvement_cents: 1.24,
  median_improvement_cents: 0.87,
  positive_pct: 68.3,
  total_trades: 24,
};

const cityCalibration = {
  'New York': { n: 248, brier: 0.142, bias: -0.008 },
  'Chicago':  { n: 211, brier: 0.156, bias:  0.012 },
  'Miami':    { n: 198, brier: 0.149, bias: -0.003 },
  'LA':       { n: 224, brier: 0.139, bias:  0.006 },
  'Atlanta':  { n: 187, brier: 0.151, bias: -0.011 },
  'Denver':   { n: 156, brier: 0.168, bias:  0.019 },
  'Seattle':  { n: 132, brier: 0.171, bias: -0.007 },
  'Boston':   { n: 145, brier: 0.148, bias:  0.004 },
};

const closedTrades = [
  { ticker: 'KXHIGHCHI-24-MAY01', city: 'Chicago', side: 'yes', outcome: 'yes', pnl:  8.40, entered_at: '2024-04-30T14:22:00', entry_price: 0.42 },
  { ticker: 'KXHIGHNYC-24-MAY02', city: 'NYC',     side: 'no',  outcome: 'no',  pnl:  6.20, entered_at: '2024-04-29T09:15:00', entry_price: 0.38 },
  { ticker: 'KXHIGHLA-24-MAY01',  city: 'LA',      side: 'yes', outcome: 'no',  pnl: -12.50,entered_at: '2024-04-28T16:40:00', entry_price: 0.51 },
  { ticker: 'KXHIGHPHX-24-APR30', city: 'Phoenix', side: 'yes', outcome: 'yes', pnl: 14.80, entered_at: '2024-04-27T11:05:00', entry_price: 0.36 },
  { ticker: 'KXHIGHMIA-24-MAY03', city: 'Miami',   side: 'no',  outcome: 'yes', pnl: -9.20, entered_at: '2024-04-26T13:50:00', entry_price: 0.44 },
  { ticker: 'KXHIGHHOU-24-MAY01', city: 'Houston', side: 'yes', outcome: 'yes', pnl: 11.30, entered_at: '2024-04-25T10:20:00', entry_price: 0.39 },
];

const agedPositions      = [{ ticker: 'KXHIGHCHI-26MAY07-T72', age_h: 42 }, { ticker: 'KXHIGHDEN-26MAY10-T64', age_h: 38 }];
const correlatedEvents   = [{ date: '2026-05-12', cities: ['Chicago', 'NYC'], count: 2 }, { date: '2026-05-14', cities: ['LA', 'Phoenix'], count: 2 }];
const directionalBias    = { yes: 5, no: 3 };
const expiryCluster      = [
  { date: '2026-05-07', count: 3, total_cost: 105.50 },
  { date: '2026-05-08', count: 3, total_cost: 122.80 },
  { date: '2026-05-09', count: 1, total_cost:  51.40 },
  { date: '2026-05-10', count: 1, total_cost:  22.00 },
];

const cities = [...new Set(positions.map(p => p.city))];

const MOCK = {
  stats, positions, opportunities, balanceHist,
  circuitBreakers, recentTrades, modelAccuracy,
  calibration, brierHist, pnlAttribution, alerts,
  forecastDetail, mlModels, cities,
  todayForecasts, tomorrowForecasts, cityBrier,
  rocCurve, auc, brierByDays, priceImprovement,
  cityCalibration, closedTrades,
  agedPositions, correlatedEvents, directionalBias, expiryCluster,
};

export default MOCK;
