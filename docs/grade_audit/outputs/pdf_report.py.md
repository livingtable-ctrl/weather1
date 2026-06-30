# Grade Audit — pdf_report.py

**File:** `pdf_report.py`  
**Lines:** 279  
**Role:** Reporting utility — generates a weekly PDF or HTML summary of portfolio performance. Not in the live trade path.  
**Tier:** TIER 2 (all functions)  
**Test coverage:** Zero test files import this module.

---

## Function Inventory

### `_collect_data()` L:26–59

[pdf_report.py] `_collect_data()` L:26–59  7/10 — Gathers all report data from paper/tracker; correct for the reporting use case; `get_all_trades()[-10:]` slices the last 10 by list position which may not be chronologically last if trades are not sorted, and `brier_score_rolling_with_n()` uses the `multiday_predictions` view (I1 PASS via tracker).  [Confidence: Confirmed]

Notes:
- `get_all_trades()` returns trades in insertion order; slicing `[-10:]` is correct only if insertion order equals chronological order. Paper ledger appends, so this is true in practice — but fragile if the ledger is ever compacted or reordered. LOW risk.
- `brier_score_rolling_with_n()` is called without a `days_out` filter here, but that filter is already inside `tracker.py`'s `multiday_predictions` view — I1 is satisfied by the callee, not this function.
- No exception handling around any of the imports or calls. If `paper.py` or `tracker.py` raises (e.g. DB locked, missing file), the exception propagates all the way to the caller of `generate_weekly_report()`. For a reporting utility this is acceptable — a report failure should be visible, not silently swallowed.
- `get_balance()` is used here for display only (not a trading gate), so I8 does not apply.

---

### `_pdf()` L:62–64

[pdf_report.py] `_pdf()` L:62–64  8/10 — Correct Latin-1 sanitiser for fpdf2 Helvetica; replaces em-dash then encode/decode with `errors="replace"` handles all other non-Latin-1 codepoints safely; pure function with no side effects.  [Confidence: Confirmed]

---

### `_generate_pdf()` L:67–159

[pdf_report.py] `_generate_pdf()` L:67–159  7/10 — Produces a well-structured PDF with header/summary/open-positions/settled-trades sections; all string output goes through `_pdf()` so Latin-1 crashes are prevented; no exception handling if `pdf.output()` fails (e.g. permission error on the output path) — exception propagates up, which is acceptable for a report utility but worth noting.  [Confidence: Confirmed]

Minor issues:
- Line 85: `data["pnl"]` can be `None` if `get_performance()` returns a missing key defaulted to `0.0` via `.get()` — actually `.get("total_pnl", 0.0)` in `_collect_data()` guards this, so it is safe.
- Line 87: `data["win_rate"]` can be `None` — handled with the ternary. Correct.
- Line 109: `col_w = [55, 18, 15, 22, 28, 32]` sums to 170 mm. fpdf2 default page width minus margins (210−30 = 180 mm) leaves 10 mm spare — no overflow risk.
- No page overflow guard: if there are many open positions or settled trades, the table will overflow off the page bottom silently. FPDF auto-adds pages for `multi_cell` but NOT for `cell`. This is a cosmetic rendering bug for large datasets (>~25 rows). Not a financial correctness issue.

---

### `_generate_html()` L:162–251

[pdf_report.py] `_generate_html()` L:162–251  7/10 — Clean HTML fallback with dark-theme CSS; all data values are f-string formatted (no user-controlled content injection risk since all values come from internal DB/JSON); `output_path.write_text(..., encoding="utf-8")` is correct.  [Confidence: Confirmed]

Minor issues:
- Line 184: `p = t.get("pnl") or 0.0` — uses `or` which converts a legitimate `0.0` pnl to `0.0` correctly but also converts `-0.0` to `0.0` (harmless). More importantly, it converts `False` to `0.0` (not a real concern here). Safe in practice.
- Line 183: `reversed(data["recent_settled"])` — `data["recent_settled"]` is a list slice, so `reversed()` returns a `list_reverseiterator`. Correct.
- No exception handling around `output_path.write_text()` — acceptable for a reporting utility.
- The f-string inline HTML construction is verbose but correct; no XSS risk since all values originate from internal data.

---

### `generate_weekly_report()` L:254–278

[pdf_report.py] `generate_weekly_report()` L:254–278  7/10 — Top-level entry point; correctly dispatches to PDF or HTML based on `_HAS_FPDF`; handles the edge case where caller passes a `.pdf` path but fpdf2 is absent (silently switches to `.html`) — this silent suffix change could confuse callers expecting the returned path to match their input, but it is documented in the comment and the returned string will reflect the actual path; `DATA_DIR.mkdir(exist_ok=True)` at module load plus `default_path.parent.mkdir(exist_ok=True)` at call time ensures the output directory exists.  [Confidence: Confirmed]

Minor issues:
- Line 275: When `_HAS_FPDF` is False and caller passed a `.pdf` path, the suffix is silently changed. A log warning here would help the operator understand why the returned path differs from the requested path.
- No exception handling around `_collect_data()`, `_generate_pdf()`, or `_generate_html()` — any exception propagates to the caller. Callers in `main.py` (L:4651) and `web_app.py` (L:893) should handle this. Acceptable for a reporting helper.
- Zero test coverage. For a TIER 2 file this is not a blocker, but a smoke test (`generate_weekly_report()` returns a path that exists) would be trivially easy to add.

---

## Summary Table

| Function | Score | Confidence | Key Issue |
|---|---|---|---|
| `_collect_data()` | 7/10 | Confirmed | `[-10:]` slice order dependency; no error handling (acceptable) |
| `_pdf()` | 8/10 | Confirmed | Correct and safe Latin-1 sanitiser |
| `_generate_pdf()` | 7/10 | Confirmed | No page-overflow guard for large datasets (cosmetic only) |
| `_generate_html()` | 7/10 | Confirmed | Correct; minor `or 0.0` idiom |
| `generate_weekly_report()` | 7/10 | Confirmed | Silent `.pdf`→`.html` suffix change without log; no test coverage |

**No red flags (RF1–RF6) fired.**  
**No TIER 1 promotions required.**  
**No active financial correctness bugs found.**  
**File median: 7/10** — suitable for a reporting utility; no fixes required before live trading.

---

## Optional Low-Priority Improvements (not blocking)

1. **`generate_weekly_report()` L:275** — Add `import logging; logging.getLogger(__name__).warning(...)` when silently switching `.pdf` to `.html` so the operator knows why the returned path changed.
2. **`_generate_pdf()` L:108–127** — Consider using `multi_cell` or pagination guard for open-positions table to prevent silent PDF page-overflow when positions > ~25 rows.
3. **`_collect_data()` L:58** — Comment clarifying that `get_all_trades()` returns trades in insertion (chronological) order would make the `[-10:]` slice intent explicit.
