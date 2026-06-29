# MODULE: TIER 2 FILES

This module applies to all TIER 2 source files:
`consistency.py`, `notify.py`, `execution_log.py`, `paths.py`, `config.py`,
`climatology.py`, `schema_validator.py`, `system_health.py`, `ab_test.py`,
`cloud_backup.py`, `output_formatters.py`, `pdf_report.py`, `colors.py`

Dead-code candidates (grade but flag if dead):
`regime.py`, `feature_importance.py`, `param_sweep.py`, `kalshi_ws.py`

---

## Instructions

Grade every function using the TIER 2 compressed format from the preamble.

Apply the full rubric — the score is determined the same way as TIER 1. Only the
output format is compressed (one line per function).

**Exception:** If any function fires a red flag (RF1–RF6), promote it to a full TIER 1
block even in a TIER 2 file.

---

## Dead-code Candidate Files

For `regime.py`, `feature_importance.py`, `param_sweep.py`, `kalshi_ws.py`:

1. Check whether the module is imported anywhere in the live trade path
   (`cron.py`, `weather_markets.py`, `paper.py`, `order_executor.py`, `main.py cmd_cron`)
2. If it is NOT imported in the live path: flag the entire file as `SUSPECTED DEAD CODE`
   and list:
   - What imports it (if anything)
   - Whether removal is safe (what would need to change)
3. Still grade every function in the file — dead code can contain bugs that matter if
   the code is ever re-activated

---

## Specific Notes per File

**`consistency.py`:** Check whether it enforces (blocks trades) or only logs/notifies.
If notify-only: flag as INFO — the operator cannot distinguish a consistency failure
from normal operation without monitoring logs.

**`notify.py`:** Check whether notification failure can suppress a halt. If halt logic
anywhere calls notify before executing the halt action, that is a dependency inversion
— notify should be fire-and-forget after the halt, not a precondition.

**`execution_log.py`:** Check whether a crash between order placement and the log write
would leave the order unlogged. An unlogged order is invisible to the audit trail.

**`config.py`:** Check whether all trading-decision thresholds (drawdown tiers, Kelly
fraction, max positions, min edge) are accessible here and whether there is a
validation function that catches out-of-range values at startup.

**`ab_test.py`:** Check whether A/B test variant assignment is stable across cron
cycles for the same market. A round-robin that re-assigns on each cycle would
contaminate variant data.
