---
source_file: "docs/audit_findings.md"
type: "document"
community: "Community 267"
location: "L35"
tags:
  - graphify/document
  - graphify/EXTRACTED
  - community/Community_267
---

# CRITICAL Issues — 12 Total

## Connections
- [[Adversarial Code Audit — Kalshi Weather Trading Bot]] - `contains` [EXTRACTED]
- [[C1 · `order_executor.py` — order_id extraction bug (all GTC lifecycle dead)]] - `contains` [EXTRACTED]
- [[C10 · `paper.py` — P&L inconsistency between settle, calc, and attribution]] - `contains` [EXTRACTED]
- [[C11 · `paper.py` — AES backup encryption uses null-byte padded keys]] - `contains` [EXTRACTED]
- [[C12 · `paper.py` — fabricated METAR proxy observations still injected on settlement]] - `contains` [EXTRACTED]
- [[C2 · `order_executor.py` — idempotency fallback misses filled orders]] - `contains` [EXTRACTED]
- [[C3 · `order_executor.py` — `_recover_pending_orders()` referenced but does not exist]] - `contains` [EXTRACTED]
- [[C4 · `calibration.py`  `ml_bias.py` — Platt signal inversion can silently recur]] - `contains` [EXTRACTED]
- [[C5 · `ml_bias.py` — `_MODELS_CACHE = {}` permanently disables bias correction on transient failure]] - `contains` [EXTRACTED]
- [[C6 · `tracker.py` — `get_rolling_win_rate()` queries non-existent column]] - `contains` [EXTRACTED]
- [[C7 · `tracker.py` — `raw_prob` and `our_prob` labels inverted in storage]] - `contains` [EXTRACTED]
- [[C8 · `paper.py` — non-unique trade IDs after `undo_last_trade()`]] - `contains` [EXTRACTED]
- [[C9 · `paper.py` — `verify_backup()` silently passes for all SHA-256 files]] - `contains` [EXTRACTED]

#graphify/document #graphify/EXTRACTED #community/Community_267