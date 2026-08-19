# Initial Git State (Section 3 record)

Recorded: start of audit session, before any investigative action.

- Branch: `claude/code-max-depth-audit-5518e9`
- HEAD: `d190d09dd699df5266e85650a6ddf8e2d1420891`
- HEAD commit: `feat(weather_markets): blend far-tail climatology into rain forecast signal beyond the 16-day horizon` (2026-08-17 16:12:32 -0400)
- Working tree: clean (no staged, no unstaged, no untracked files)
- `.env`: absent from worktree root (only `.env.example` present) — no live credentials reachable in this worktree.

## Recent commit history (context for "recent feature work" scope)

```
d190d09d feat(weather_markets): blend far-tail climatology into rain forecast signal beyond the 16-day horizon
e5331a8d fix(main,order_executor,execution_log): route cmd_order's live fills through execution_log instead of the paper ledger
b0f4cad2 fix(weather_markets): source real daily-high for persistence_prob's dead branch
8a84e568 chore(graphify-out): complete v0.9.42→v0.9.45 AST cache migration, full refresh
105cf4ce fix(execution_log,order_executor): settle partial live exits' own row so per-trade P&L isn't under-reported
6364b38b fix(main,monte_carlo): compare city-local target_date against city-local today, not UTC
d320142d feat(settlement_monitor,ml_bias): wire METAR calibration into settlement-lag force-close gate
5d9b6c56 feat(ml_bias,cron,main): auto-retrain METAR calibration weekly, fix test-isolation leak
4557a77b feat(main,ml_bias,tracker,cron): add EMOS activation confirmation gate
c00c533c chore(graphify-out): incremental update for L18222 + L18015 + accuracy-override
```

This audit is scoped as a GENERAL issue scan (not one named feature). Per the doc's depth hierarchy
(FEATURE > FEATURE DEPENDENCIES > REGRESSIONS > UNRELATED DISCOVERY), the recent feature commits above
(excluding graphify chores) receive SCOPE A/B depth; the rest of the repository receives SCOPE D
(aggressive discovery, not exhaustive).
