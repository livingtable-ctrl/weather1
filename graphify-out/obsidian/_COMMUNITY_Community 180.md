---
type: community
cohesion: 0.12
members: 18
---

# Community 180

**Cohesion:** 0.12 - loosely connected
**Members:** 18 nodes

## Members
- [[Grade Audit Module Doc main.py]] - document - docs/grade_audit/modules/main.md
- [[Grade Audit Module Doc order_executor.py]] - document - docs/grade_audit/modules/order_executor.md
- [[Grade Audit Module Doc paper.py]] - document - docs/grade_audit/modules/paper.md
- [[Graduation Brier Threshold (≤0.23)]] - document - docs/grade_audit/modules/paper.md
- [[No exception when ENABLE_MICRO_LIVE is not 'true' (gate is skipped entirely).]] - rationale - tests/test_graduation_gate.py
- [[No exception when ENABLE_MICRO_LIVE='false'.]] - rationale - tests/test_graduation_gate.py
- [[No exception when ENABLE_MICRO_LIVE=true and count = MIN_BRIER_SAMPLES.]] - rationale - tests/test_graduation_gate.py
- [[P2-D Gate must fail-closed when the tracker DB is unavailable. If…]] - rationale - tests/test_graduation_gate.py
- [[RuntimeError raised when ENABLE_MICRO_LIVE=true and count  MIN_BRIER_SAMPLES.]] - rationale - tests/test_graduation_gate.py
- [[Tests for the graduation gate in main.py (_check_graduation_gate).]] - rationale - tests/test_graduation_gate.py
- [[_drawdown_snapshot() Effective Balance Gate]] - document - docs/grade_audit/modules/paper.md
- [[client_order_id Idempotency Check]] - document - docs/grade_audit/modules/kalshi_client.md
- [[test_gate_fails_closed_when_db_unavailable()]] - code - tests/test_graduation_gate.py
- [[test_gate_passes_when_micro_live_and_sufficient_samples()]] - code - tests/test_graduation_gate.py
- [[test_gate_raises_when_micro_live_and_insufficient_samples()]] - code - tests/test_graduation_gate.py
- [[test_gate_skipped_when_micro_live_explicitly_false()]] - code - tests/test_graduation_gate.py
- [[test_gate_skipped_when_micro_live_false()]] - code - tests/test_graduation_gate.py
- [[test_graduation_gate.py]] - code - tests/test_graduation_gate.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_180
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Anomaly Detection & PDF Reporting]]
- 1 edge to [[_COMMUNITY_Community 351]]
- 1 edge to [[_COMMUNITY_Black Swan Halt State]]
- 1 edge to [[_COMMUNITY_Test Fixture Cache Clearing (conftest)]]
- 1 edge to [[_COMMUNITY_Community 97]]
- 1 edge to [[_COMMUNITY_Community 273]]
- 1 edge to [[_COMMUNITY_Community 105]]
- 1 edge to [[_COMMUNITY_Community 49]]
- 1 edge to [[_COMMUNITY_Circuit Breaker & Session Retry Infrastructure]]
- 1 edge to [[_COMMUNITY_Community 40]]
- 1 edge to [[_COMMUNITY_Community 56]]
- 1 edge to [[_COMMUNITY_Community 235]]
- 1 edge to [[_COMMUNITY_Community 142]]

## Top bridge nodes
- [[Grade Audit Module Doc paper.py]] - degree 9, connects to 5 communities
- [[Grade Audit Module Doc order_executor.py]] - degree 7, connects to 5 communities
- [[Grade Audit Module Doc main.py]] - degree 6, connects to 3 communities
- [[client_order_id Idempotency Check]] - degree 2, connects to 1 community