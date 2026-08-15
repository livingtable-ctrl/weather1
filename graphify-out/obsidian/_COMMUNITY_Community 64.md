---
type: community
cohesion: 0.14
members: 35
---

# Community 64

**Cohesion:** 0.14 - loosely connected
**Members:** 35 nodes

## Members
- [[dot-test_declining_scan_still_registers_settlement_monitor()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_fall_back_pre_transition_registration()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_non_eastern_host_converts_correctly()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_real_clock_produces_plausible_values()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_registration_during_eastern_after_midnight_pacific_before()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_spring_forward_pre_transition_registration()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_stale_series_error_skips_only_settlement_task()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_summer_eastern_host()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[dot-test_winter_eastern_host()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[A stand-in for the `datetime` class, injected via `monkeypatch.setattr(main,…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[Aug Eastern EDT(-4) through PacificArizona PDTMST(-7) -- a 3-hour spread,…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[Host machine's own clock is UTC, not Eastern -- ST must reflect Eastern's…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[If settlement_monitor's own module-level _CITY_SERIES_TICKER assertion fires (a…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[Jan Eastern EST(-5) through Pacific PST(-8)Arizona MST(-7, unchanged) --…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[Lightweight, non-flaky integration check against the real system clock (no time…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[Regression coverage for a real bug found in this implementation snapshotting…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[Regression coverage for a real bug hit while implementing this an earlier…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[Regression coverage answering n to the very first prompt (KalshiWeatherScan)…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[TestDstTransitionRegression]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[TestFirstPromptDeclineStillRegistersOthers]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[TestHappyPath]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[TestHostTimezoneIndependence]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[TestRealTimeIntegration]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[TestSettlementMonitorImportFailureIsolated]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[TestZoneDateCrossingRegression]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[ZoneInfo]] - code
- [[_capturing_run()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[_extract()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[_make_fake_dt()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[_run_cmd_schedule_and_capture()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[_settlement_call()]] - code - tests/test_cmd_schedule_settlement_monitor.py
- [[cmd_schedule() must register a settlement-monitor task that spans every tracked…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[datetime_4]] - code
- [[subprocess.run replacement that records the command and reports success -- a…]] - rationale - tests/test_cmd_schedule_settlement_monitor.py
- [[test_cmd_schedule_settlement_monitor.py]] - code - tests/test_cmd_schedule_settlement_monitor.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_64
SORT file.name ASC
```

## Connections to other communities
- 9 edges to [[_COMMUNITY_Community 91]]
- 6 edges to [[_COMMUNITY_METAR Settlement Monitoring]]
- 4 edges to [[_COMMUNITY_Ensemble Weight Blending Tests]]
- 3 edges to [[_COMMUNITY_Community 206]]
- 3 edges to [[_COMMUNITY_METAR Lock-In Confidence Tests]]
- 3 edges to [[_COMMUNITY_ML Bias Correction & Audit Plans]]
- 3 edges to [[_COMMUNITY_Community 99]]
- 2 edges to [[_COMMUNITY_Tracker P&L Attribution Tests]]
- 1 edge to [[_COMMUNITY_Community 112]]
- 1 edge to [[_COMMUNITY_Community 122]]
- 1 edge to [[_COMMUNITY_Community 211]]
- 1 edge to [[_COMMUNITY_Community 349]]
- 1 edge to [[_COMMUNITY_Community 394]]

## Top bridge nodes
- [[ZoneInfo]] - degree 45, connects to 13 communities
- [[test_cmd_schedule_settlement_monitor.py]] - degree 17, connects to 2 communities