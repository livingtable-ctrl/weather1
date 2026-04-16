# Research Backlog: Master Priority Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement any phase plan task-by-task.

**Goal:** Rank and phase all 20 research backlog items by expected ROI, implementation risk, and dependencies. Each phase has its own detailed plan file.

## Progress Tracker

| Phase | Status | Completed | Items Done |
|-------|--------|-----------|------------|
| A: Data Foundation | ✅ Done | 2026-04-16 | MOS, bias correction, METAR lock-in (3/3) |
| B: Risk Engine | ✅ Done | 2026-04-16 | Drawdown tiers, flash crash CB, confidence thresholds (3/3) |
| **C: New Data Sources** | **⬅ Next** | — | NBM, ECMWF AIFS, Gaussian method (0/3) |
| D: Monitoring & Settlement | Pending | — | Settlement lag, Brier, reliability diagram (0/3) |
| E: Walk-Forward Backtesting | Pending | — | Walk-forward engine (0/1) |
| F: WebSocket | Pending | — | Real-time order book (0/1) |
| G: Long-term | Pending | — | ML bias, arb, A/B, P&L, Telegram (0/5) |

**7 of 20 items complete (35%). 13 remaining.**

**Architecture:** Layered improvements — data quality first, then risk calibration, then monitoring, then advanced strategies.

**Tech Stack:** Python 3.12, SQLite WAL, Open-Meteo, IEM MOS API, NOAA AVW METAR API, properscoring, ecmwf-opendata, Herbie

---

## Status Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Done |
| 🔴 | Phase A — Immediate (this sprint) |
| 🟠 | Phase B — Near-term |
| 🟡 | Phase C — New data sources |
| 🟢 | Phase D — Monitoring & settlement |
| 🔵 | Phase E — Backtesting |
| 🟣 | Phase F — WebSocket |
| ⚪ | Phase G — Long-term |

---

## Ranked Backlog (all 20 items)

### Tier 1 — Highest ROI, Low Effort

| Rank | Item | Phase | Impact | Effort | Plan |
|------|------|-------|--------|--------|------|
| 1 | ~~Fix NYC settlement station (KNYC)~~ | ✅ Done | Critical | Trivial | — |
| 2 | ~~NOAA MOS via IEM API~~ | ✅ Done | Very High | Low | [Phase A](2026-04-16-phase-a-data-foundation.md) |
| 3 | ~~Per-city static bias correction~~ | ✅ Done | Very High | Low | [Phase A](2026-04-16-phase-a-data-foundation.md) |
| 4 | ~~METAR same-day lock-in (85-90% win rate)~~ | ✅ Done | Very High | Low | [Phase A](2026-04-16-phase-a-data-foundation.md) |

**Why first:** These three items directly increase edge on every trade. MOS is station-specific (Kalshi settles on ASOS stations). Bias correction removes a systematic error that costs money every day. METAR lock-in is the single highest-win-rate strategy known for this market type. All three are free APIs.

---

### Tier 2 — High ROI, Moderate Effort

| Rank | Item | Phase | Impact | Effort | Plan |
|------|------|-------|--------|--------|------|
| 5 | ~~Confidence-tiered edge thresholds~~ | ✅ Done | High | Low | [Phase B](2026-04-16-phase-b-risk-engine.md) |
| 6 | ~~Drawdown-tiered Kelly step reduction~~ | ✅ Done | High | Low | [Phase B](2026-04-16-phase-b-risk-engine.md) |
| 7 | ~~Per-market flash crash circuit breaker~~ | ✅ Done | High | Low | [Phase B](2026-04-16-phase-b-risk-engine.md) |
| 8 | **METAR settlement lag monitoring** | 🟢 D | High | Medium | [Phase D](2026-04-16-phase-d-monitoring-settlement.md) |

**Why second:** Risk calibration items (5-7) can be done in a few hours and protect capital immediately. Settlement lag (8) is a secondary high-win-rate strategy, but requires a persistent monitoring loop outside the cron schedule.

---

### Tier 3 — Good ROI, Higher Effort

| Rank | Item | Phase | Impact | Effort | Plan |
|------|------|-------|--------|--------|------|
| 9 | **NBM (National Blend of Models)** | 🟡 C | High | Medium | [Phase C](2026-04-16-phase-c-new-data-sources.md) |
| 10 | **ECMWF AIFS ensemble** | 🟡 C | High | Medium | [Phase C](2026-04-16-phase-c-new-data-sources.md) |
| 11 | **Gaussian probability distribution method** | 🟡 C | Medium | Low | [Phase C](2026-04-16-phase-c-new-data-sources.md) |
| 12 | **Reliability diagram in dashboard** | 🟢 D | Medium | Low | [Phase D](2026-04-16-phase-d-monitoring-settlement.md) |
| 13 | **Per-city per-season Brier segmentation** | 🟢 D | Medium | Medium | [Phase D](2026-04-16-phase-d-monitoring-settlement.md) |

**Why third:** ECMWF AIFS is 20% better than GFS for days 1-3. NBM is already blended by NWS. Both require new API clients. Gaussian method is a mathematical improvement to probability calculation. Monitoring items (12, 13) feed into calibration improvements but don't directly generate trades.

---

### Tier 4 — High Effort, Strong Long-term Value

| Rank | Item | Phase | Impact | Effort | Plan |
|------|------|-------|--------|--------|------|
| 14 | **Walk-forward backtesting** | 🔵 E | Very High | High | [Phase E](2026-04-16-phase-e-walk-forward-backtest.md) |
| 15 | **Kalshi WebSocket integration** | 🟣 F | High | High | [Phase F](2026-04-16-phase-f-websocket.md) |

**Why fourth:** Walk-forward is the only valid way to validate strategies on non-stationary markets — critical before scaling up. WebSocket enables real-time microstructure signals and settlement lag automation, but is infrastructure-heavy.

---

### Tier 5 — Long-Term

| Rank | Item | Phase | Impact | Effort | Plan |
|------|------|-------|--------|--------|------|
| 16 | **ML-based bias correction (LightGBM)** | ⚪ G | Very High | Very High | [Phase G](2026-04-16-phase-g-long-term.md) |
| 17 | **Cross-platform arbitrage (Kalshi ↔ Polymarket)** | ⚪ G | High | High | [Phase G](2026-04-16-phase-g-long-term.md) |
| 18 | **A/B experiment framework** | ⚪ G | Medium | Medium | [Phase G](2026-04-16-phase-g-long-term.md) |
| 19 | **Strategy P&L attribution** | ⚪ G | Medium | Medium | [Phase G](2026-04-16-phase-g-long-term.md) |
| 20 | **Telegram alerting** | ⚪ G | Low | Low | [Phase G](2026-04-16-phase-g-long-term.md) |

**Why last:** ML bias correction requires 6+ months of training data to be effective. Cross-platform arbitrage requires Polymarket API integration. A/B and P&L attribution are infrastructure for strategy research, not direct alpha. Telegram is convenience tooling.

---

## Phase Summary

| Phase | Items | Priority | Plan File |
|-------|-------|----------|-----------|
| ✅ A: Data Foundation | MOS + bias correction + METAR lock-in | **Done 2026-04-16** | [2026-04-16-phase-a-data-foundation.md](2026-04-16-phase-a-data-foundation.md) |
| ✅ B: Risk Engine | Confidence tiers + drawdown Kelly + flash crash CB | **Done 2026-04-16** | [2026-04-16-phase-b-risk-engine.md](2026-04-16-phase-b-risk-engine.md) |
| C: New Data Sources | NBM + ECMWF AIFS + Gaussian method | Near-term | [2026-04-16-phase-c-new-data-sources.md](2026-04-16-phase-c-new-data-sources.md) |
| D: Monitoring & Settlement | Settlement lag + per-city Brier + reliability diagram | Medium-term | [2026-04-16-phase-d-monitoring-settlement.md](2026-04-16-phase-d-monitoring-settlement.md) |
| E: Walk-Forward Backtesting | Walk-forward engine | Medium-term | [2026-04-16-phase-e-walk-forward-backtest.md](2026-04-16-phase-e-walk-forward-backtest.md) |
| F: WebSocket | Real-time order book | Medium-term | [2026-04-16-phase-f-websocket.md](2026-04-16-phase-f-websocket.md) |
| G: Long-term | ML bias + arb + A/B + P&L + Telegram | Long-term | [2026-04-16-phase-g-long-term.md](2026-04-16-phase-g-long-term.md) |

---

## Dependency Map

```
Phase A (data quality)
  └─ Phase C (more data sources)
       └─ Phase D (per-segment analysis needs more data)
            └─ Phase E (backtesting validates calibrated model)

Phase B (risk engine) — independent, do any time
Phase F (WebSocket) — independent of A-E
Phase G — depends on 6+ months of data from A-E
```

**Recommended order:** A → B (parallel) → C → D → E → F → G

**Current position:** ✅ A done → ✅ B done → **⬅ C next**
