---
source_file: "order_executor.py"
type: "code"
community: "Community 12"
location: "L1136"
tags:
  - graphify/code
  - graphify/INFERRED
  - community/Community_12
---

# LivePositionStore

## Connections
- [[dot-__init__()_2]] - `method` [EXTRACTED]
- [[dot-exit()_1]] - `method` [EXTRACTED]
- [[dot-get_open()_1]] - `method` [EXTRACTED]
- [[dot-save_peak()_1]] - `method` [EXTRACTED]
- [[dot-test_does_not_overwrite_a_higher_stored_peak()]] - `calls` [EXTRACTED]
- [[dot-test_exit_wraps_exit_live_position()]] - `calls` [EXTRACTED]
- [[dot-test_get_open_converts_filled_unsettled_rows_to_positions()]] - `calls` [EXTRACTED]
- [[dot-test_records_new_peak_when_higher()]] - `calls` [EXTRACTED]
- [[dot-test_save_peak_persists_to_execution_log()]] - `calls` [EXTRACTED]
- [[ABTest]] - `uses` [INFERRED]
- [[Position]] - `uses` [INFERRED]
- [[PositionStore]] - `uses` [INFERRED]
- [[PositionStore backed by execution_log's SQLite rows. See…]] - `rationale_for` [EXTRACTED]
- [[TestAutoPlaceTradesCycleCheck]] - `uses` [INFERRED]
- [[TestCancelAndVerifySafeToReplace]] - `uses` [INFERRED]
- [[TestCheckLiveModelExits]] - `uses` [INFERRED]
- [[TestCheckLivePositionExits]] - `uses` [INFERRED]
- [[TestClearsTakerFee]] - `uses` [INFERRED]
- [[TestExitLivePosition]] - `uses` [INFERRED]
- [[TestFillInstrumentation]] - `uses` [INFERRED]
- [[TestFinalizeCancel]] - `uses` [INFERRED]
- [[TestFinalizeCancelReturnValue]] - `uses` [INFERRED]
- [[TestGetCurrentBook]] - `uses` [INFERRED]
- [[TestGetLiveOpenPositions]] - `uses` [INFERRED]
- [[TestGetTodayLiveSpendExcludesAmended]] - `uses` [INFERRED]
- [[TestGetTodayLiveSpendExcludesExitOrders]] - `uses` [INFERRED]
- [[TestLiveMinEdge]] - `uses` [INFERRED]
- [[TestLivePositionStore]] - `uses` [INFERRED]
- [[TestLoadLiveConfig]] - `uses` [INFERRED]
- [[TestMidpointPrice]] - `uses` [INFERRED]
- [[TestOpenTradesListLivePath]] - `uses` [INFERRED]
- [[TestPaperPositionStore]] - `uses` [INFERRED]
- [[TestPlaceLiveOrder]] - `uses` [INFERRED]
- [[TestPlaceLiveOrderDedup]] - `uses` [INFERRED]
- [[TestPollPendingOrders]] - `uses` [INFERRED]
- [[TestPollPendingOrdersExtended]] - `uses` [INFERRED]
- [[TestRecoverPendingOrders]] - `uses` [INFERRED]
- [[TestReplaceLiveOrder]] - `uses` [INFERRED]
- [[TestRepriceOrCancelPendingOrders]] - `uses` [INFERRED]
- [[TestResolveAmendStatus]] - `uses` [INFERRED]
- [[TestSharedAcrossPaperAndLive]] - `uses` [INFERRED]
- [[TestUpdateLivePeakProfits]] - `uses` [INFERRED]
- [[TestUpdatePeakProfitsSavesPerPosition]] - `uses` [INFERRED]
- [[TestVarGateFailsClosed]] - `uses` [INFERRED]
- [[_LiveDBTestBase]] - `uses` [INFERRED]
- [[_check_live_position_exits()]] - `calls` [EXTRACTED]
- [[execution_log.py]] - `calls` [EXTRACTED]
- [[order_executor.py]] - `implements` [EXTRACTED]
- [[test_live_execution.py]] - `imports` [EXTRACTED]
- [[test_positions.py]] - `imports` [EXTRACTED]

#graphify/code #graphify/INFERRED #community/Community_12