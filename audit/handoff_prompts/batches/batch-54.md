# Batch 54: KXTORNADO monthly count model (OPTIONAL — start well before May 2027 peak season)

## Context

Repo: weather1. Source: Expansion Dossier B12 (score 6.2, rank 9), Rev 4, 2026-08-24. Optional capacity work — no deadline, but the family's volume peaks May-June (peak tornado season), so a Q1-2027 start captures a full high-volume season of shadow samples. Live-verified 2026-08-24: 83 markets, 505K cumulative contracts, monthly ladders (brackets 25→275+) listed through Jan 2027; settlement = SPC's **preliminary** storm-report count ("Storm Reports Legend" on the Preliminary Report Summary). `KXTORNADO` is already in nothing — zero repo/backlog mentions (verified); distinct from the legacy annual `TORNADO` series.

Files: NEW module (suggest `tornado_climatology.py`, mirroring `hurricane_climatology.py`), `weather_markets.py` (series registration + one `analyze_trade` dispatch hook + condition parser for `KXTORNADO-26SEP-75`-shape tickers). Small overlap with Track C's registry region — run after 51/52 or rebase onto them.

Ceremony: full 29-step workflow (new trade-entry path), opus review effort=high.

## The model (follow the hurricane season-count pattern exactly)

Climatology + count-to-date bootstrap, the shape `_analyze_hurricane_count_trade` already established: per-month climatological distribution of SPC preliminary counts (2005-2025, free CSV from SPC), conditioned mid-month on reports-to-date (a truncated-count update, same machinery as hurricane count-to-date caching). Shadow-only behind a new 20-settled gate + env flag, per convention. Monthly cadence → ~12 settlements/year; the gate takes ~2 seasons to fill — say so in the graduation entry rather than pretending otherwise.

Data notes: SPC preliminary reports systematically overcount vs final (duplicates) — the market settles on PRELIMINARY, so model the preliminary series itself, not final tornado counts; do not "correct" toward final. Late-month markets become arithmetic (count already ≥ bracket) — the model must handle already-decided brackets by pricing 0/1, and sizing should not treat those as edge.

## Go/no-go validation (run first, <1 day)

Pull SPC monthly preliminary counts 2005-2025; build the per-month climatological ladder; price the current month's live ladder from climatology + month-to-date reports; compare vs live prices. Gate: any bracket >10¢ from a well-calibrated climatology early in a month. If the market matches climatology tightly everywhere, there is no edge for this approach — file the numbers and close.

## Constraints

- Free data only (SPC storm reports CSV); no grib, no new deps; Windows-fine.
- Scoped tests: new test file + `tests/test_weather_markets.py` dispatch/parser tests. **Never the full suite.**
- backlog.txt: graduation-gate entry with criteria + the validation numbers; run `python backlog_index.py`.
