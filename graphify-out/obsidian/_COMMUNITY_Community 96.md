---
type: community
cohesion: 0.11
members: 27
---

# Community 96

**Cohesion:** 0.11 - loosely connected
**Members:** 27 nodes

## Members
- [[92 Send to all configured Discord webhooks (comma-separated…]] - rationale - notify.py
- [[Check send_system_alert()'s persisted cooldown for `cooldown_key` and, if…]] - rationale - notify.py
- [[Desktop toast notifications for strong trade signals. Uses plyer for cross-…]] - rationale - notify.py
- [[Halt Dependency Inversion Check PASS (no suppression)]] - document - docs/grade_audit/outputs/notify.py.md
- [[NOTIFY_COOLDOWN_STATE_PATH Constant]] - code - paths.py
- [[Send a STRONG BUY notification through all configured backends. Tries desktop…]] - rationale - notify.py
- [[Send a system-level alert (not trade-specific) through all configured backends.…]] - rationale - notify.py
- [[Send an email notification via SMTP (STARTTLS). Reads SMTP_HOST, SMTP_PORT,…]] - rationale - notify.py
- [[Send via Pushover API. Requires PUSHOVER_TOKEN and PUSHOVER_USER in env.…]] - rationale - notify.py
- [[Send via ntfy.sh. Requires NTFY_TOPIC in env (or pass topic explicitly).…]] - rationale - notify.py
- [[Standing report replacing backlog.txt's per-entry prose ENABLEMENT TRIGGER text…]] - rationale - weather_markets.py
- [[Tests for P1-3, P1-4, P1-7, P1-8, P1-10, P1-18 fixes.]] - rationale - tests/test_p1_remaining.py
- [[Tests for notify.py's system-alert cooldown persistence. backlog.txt…]] - rationale - tests/test_notify.py
- [[_send_discord()]] - code - notify.py
- [[_send_email()]] - code - notify.py
- [[_send_ntfy()]] - code - notify.py
- [[_send_pushover()]] - code - notify.py
- [[_system_cooldown_elapsed()]] - code - notify.py
- [[alert_strong_signal()]] - code - notify.py
- [[get_signal_graduation_report()]] - code - weather_markets.py
- [[notify.py]] - code - notify.py
- [[notify.py File Grade median 610, zero test coverage]] - document - docs/grade_audit/outputs/notify.py.md
- [[notify.py Grade Audit]] - document - docs/grade_audit/outputs/notify.py.md
- [[send_system_alert()]] - code - notify.py
- [[test_notify.py]] - code - tests/test_notify.py
- [[test_p1_remaining.py]] - code - tests/test_p1_remaining.py
- [[teststest_regression.py baseline gate]] - code - tests/test_regression.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_96
SORT file.name ASC
```

## Connections to other communities
- 13 edges to [[_COMMUNITY_Black Swan Detection & Walk-Forward Backtest]]
- 9 edges to [[_COMMUNITY_Black Swan Halt State]]
- 4 edges to [[_COMMUNITY_Community 37]]
- 4 edges to [[_COMMUNITY_Trade Cycle Engine & Arbitrage Gates]]
- 4 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 3 edges to [[_COMMUNITY_Community 195]]
- 3 edges to [[_COMMUNITY_Community 38]]
- 2 edges to [[_COMMUNITY_Community 32]]
- 2 edges to [[_COMMUNITY_Community 368]]
- 2 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 1 edge to [[_COMMUNITY_NWSCircuit-Breaker Data Validation]]
- 1 edge to [[_COMMUNITY_Backtest Engine & Atomic Writes]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 574]]
- 1 edge to [[_COMMUNITY_Community 149]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Community 553]]
- 1 edge to [[_COMMUNITY_Community 204]]
- 1 edge to [[_COMMUNITY_Community 472]]
- 1 edge to [[_COMMUNITY_Community 400]]
- 1 edge to [[_COMMUNITY_Community 474]]
- 1 edge to [[_COMMUNITY_Community 473]]
- 1 edge to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 184]]
- 1 edge to [[_COMMUNITY_Execution Log Live-Loss Tracking]]
- 1 edge to [[_COMMUNITY_Community 164]]
- 1 edge to [[_COMMUNITY_Community 569]]

## Top bridge nodes
- [[test_p1_remaining.py]] - degree 38, connects to 19 communities
- [[notify.py]] - degree 20, connects to 6 communities
- [[_system_cooldown_elapsed()]] - degree 8, connects to 3 communities
- [[test_notify.py]] - degree 8, connects to 3 communities
- [[alert_strong_signal()]] - degree 9, connects to 2 communities