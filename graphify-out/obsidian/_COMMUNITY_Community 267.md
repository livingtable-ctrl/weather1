---
type: community
cohesion: 0.15
members: 13
---

# Community 267

**Cohesion:** 0.15 - loosely connected
**Members:** 13 nodes

## Members
- [[C1 · `order_executor.py` — order_id extraction bug (all GTC lifecycle dead)]] - document - docs/audit_findings.md
- [[C10 · `paper.py` — P&L inconsistency between settle, calc, and attribution]] - document - docs/audit_findings.md
- [[C11 · `paper.py` — AES backup encryption uses null-byte padded keys]] - document - docs/audit_findings.md
- [[C12 · `paper.py` — fabricated METAR proxy observations still injected on settlement]] - document - docs/audit_findings.md
- [[C2 · `order_executor.py` — idempotency fallback misses filled orders]] - document - docs/audit_findings.md
- [[C3 · `order_executor.py` — `_recover_pending_orders()` referenced but does not exist]] - document - docs/audit_findings.md
- [[C4 · `calibration.py`  `ml_bias.py` — Platt signal inversion can silently recur]] - document - docs/audit_findings.md
- [[C5 · `ml_bias.py` — `_MODELS_CACHE = {}` permanently disables bias correction on transient failure]] - document - docs/audit_findings.md
- [[C6 · `tracker.py` — `get_rolling_win_rate()` queries non-existent column]] - document - docs/audit_findings.md
- [[C7 · `tracker.py` — `raw_prob` and `our_prob` labels inverted in storage]] - document - docs/audit_findings.md
- [[C8 · `paper.py` — non-unique trade IDs after `undo_last_trade()`]] - document - docs/audit_findings.md
- [[C9 · `paper.py` — `verify_backup()` silently passes for all SHA-256 files]] - document - docs/audit_findings.md
- [[CRITICAL Issues — 12 Total]] - document - docs/audit_findings.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_267
SORT file.name ASC
```

## Connections to other communities
- 1 edge to [[_COMMUNITY_Community 364]]

## Top bridge nodes
- [[CRITICAL Issues — 12 Total]] - degree 13, connects to 1 community