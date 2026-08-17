---
type: community
cohesion: 0.25
members: 8
---

# Community 448

**Cohesion:** 0.25 - loosely connected
**Members:** 8 nodes

## Members
- [[2026-04-10-live-order-lifecycle]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md
- [[Live Order Lifecycle Implementation Plan]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md
- [[Task 1 Add daily_live_loss table and functions to execution_log.py]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md
- [[Task 2 Replace _SESSION_LOSS with DB-backed daily loss in main.py]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md
- [[Task 3 Add settlement columns and functions to execution_log.py]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md
- [[Task 4 Extend _poll_pending_orders for GTC cancellation and settlement]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md
- [[Task 5 Live taxaudit export]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md
- [[Task 6 Live P&L dashboard]] - document - docs/superpowers/plans/2026-04-10-live-order-lifecycle.md

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_448
SORT file.name ASC
```
