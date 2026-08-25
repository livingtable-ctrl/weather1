"""
SPC preliminary storm-report climatology for Kalshi's KXTORNADO monthly
tornado-count markets (batch-54). Mirrors hurricane_climatology.py's
fetch/cache/probability module shape, which in turn mirrors acis_precip.py's.

WHAT THIS MODELS -- and why the distinction matters
---------------------------------------------------
KXTORNADO settles on SPC's **PRELIMINARY** storm-report count, not on the
final Storm Data publication. Live-confirmed 2026-08-25 against a real
market's own rules text:

  rules_primary:   "If the preliminary number of tornadoes in Aug is above
                    150 , then the market resolves to Yes."
  rules_secondary: 'The number of tornadoes will be determined by the
                    "Storm Reports Legend" shown in the bottom left corner
                    of the "Preliminary Report Summary."'

and the series' own settlement_sources entry points at
https://www.spc.noaa.gov/climo/online/monthly/newm.html -- SPC's monthly
summary tool. Preliminary counts systematically OVERCOUNT the final,
quality-controlled tornado database (duplicate reports for one tornado are
not yet merged), so this module deliberately models the PRELIMINARY series
itself and never "corrects" toward final counts. Using SPC's final SVRGIS
tornado database here would be a systematic downward bias against the thing
the market actually settles on.

DATA SOURCE
-----------
The newm.html tool renders from a per-year JSON the page fetches directly
(captured live 2026-08-25 from the page's own network traffic):

    https://www.spc.noaa.gov/climo/summary/<YYYY>/ruf/NAT/NAT.json

"ruf" is SPC's own path segment for the PRELIMINARY source (the tool's
Preliminary/Final radio buttons carry value="ruf"/value="smooth"); "NAT" is
the national (all-states) aggregate. Its `month` block is exactly the
"<year> Monthly Statistics" table the tool displays -- verified 2026-08-25
by reading the rendered table and the JSON side by side for 2026 (Jan 23,
Feb 55, Mar 210, Apr 307, May 170, Jun 399, Jul 136, Aug 88).

Cross-checked against Kalshi's own settlements, the only two that exist:
  KXTORNADO-26JUN settled with the count in (375, 400]  <-> SPC month=399
  KXTORNADO-26JUL settled with the count in (125, 150]  <-> SPC month=136

Coverage begins in 2004 (2003 and 1999 both 404; 2000 returns an all-zero
placeholder), which is why FIRST_AVAILABLE_YEAR exists and why
HISTORY_WINDOW_YEARS is 21 rather than hurricane_climatology's 30.

`month` vs `daily` -- NOT interchangeable
-----------------------------------------
The JSON carries both a `month` block (calendar-month totals) and a `daily`
block keyed "MMDD". They disagree for 104 of the 259 months in 2005-2026,
and the disagreements pair up across adjacent months. The cause is
SPC's convective day (12Z-12Z) vs the calendar day:

    2023: daily["0331"] = 163 (the Mar 31 2023 outbreak, which ran past 00Z)
          daily March sum = 253 but month["3"] = 161
          daily April sum = 121 but month["4"] = 213   (161+92 = 253, 121+92 = 213)

i.e. 92 of that convective day's reports fell on calendar April 1 and
`month` counts them in April, while `daily` books the whole convective day
under 03/31. **`month` is the calendar-month basis, and calendar-month is
what the market settles on** -- so `month` is the settlement basis here, and
`daily` is never used raw: `_calendar_daily()` re-attributes each month's
`daily - month` discrepancy onto the boundary day it must have come from
before any within-month share is taken.

An earlier version of this module took the share straight off the raw
convective-day block, on the theory that sharing a basis between numerator
and denominator made the artifact cancel. **It does not.** The residual is
one-directional and UPWARD -- mean +1.4 to +4.2 reports at day 25 across the
21-year window, never once negative, excursions to +29.5 -- i.e. a
systematic tilt toward YES on a ">N" ladder, worst late in the month.
Opus-review-caught, batch-54 round 1; `_calendar_daily()`'s docstring
carries the derivation and the measurements.

KNOWN BIASES (documented, not corrected)
----------------------------------------
1. SPC's preliminary count for a month keeps rising for days-to-weeks after
   the month ends as reports trickle in. Kalshi closes at midnight ET on the
   1st and settles ~10h later (expiration_time 14:00Z), so the number it
   settles on is a FRESH preliminary count, while the historical counts this
   module reads are MATURED ones. That biases the climatology slightly high
   relative to what actually settles.
2. The same maturation lag applies in the opposite direction to the current
   month's own count-to-date, which is the freshest (least matured) number in
   the whole calculation -- so the two biases partially cancel in
   conditioned_month_totals. Neither is quantified: reconstructing historical
   SPC snapshots isn't possible from this endpoint. Left as a graduation
   criterion in backlog.txt rather than a fudge factor here.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests

import safe_io
from circuit_breaker import CircuitBreaker
from paths import DATA_DIR

_log = logging.getLogger(__name__)

_session = requests.Session()

SPC_SUMMARY_URL_FMT = "https://www.spc.noaa.gov/climo/summary/{year}/ruf/NAT/NAT.json"

# Earliest year the endpoint serves real data for (probed live 2026-08-25:
# 1999 -> 404, 2000 -> 200 but an all-zero placeholder, 2003 -> 404,
# 2004 -> 200 with 1780 tornado reports). Nothing below this is requested.
FIRST_AVAILABLE_YEAR = 2004

# 21 complete calendar years -- the batch-54 spec's own 2005-2025 window, and
# very nearly the deepest this source supports (FIRST_AVAILABLE_YEAR is 2004,
# left as a buffer year rather than consumed). Deliberately NOT
# hurricane_climatology's 30: that source reaches back to 1851/1949, this one
# does not. A trend check across the window found no systematic drift worth
# shortening it for (2005-2014 mean annual preliminary count 1420.4 vs
# 2016-2025 mean 1427.6), so a flat unweighted window is used rather than a
# recency-weighted one.
HISTORY_WINDOW_YEARS = 21

# Historical years are immutable once the year is complete -- 30 days matches
# hurricane_climatology.CACHE_MAX_AGE's rationale. The CURRENT year's file is
# a different animal: it carries the in-progress month's running count-to-date
# and is republished continuously (the tool's own page footer stamps a UTC
# "last modified" that moves several times a day), so it gets a short TTL.
CACHE_MAX_AGE_HISTORICAL = 30 * 24 * 3600
CACHE_MAX_AGE_CURRENT = 6 * 3600

# Hard ceiling on how stale a CURRENT-year cache may be and still be trusted
# for a month-to-date count. Past this, month_to_date() returns None rather
# than handing back a count that is silently missing days of reports --
# a monthly COUNT market's probability is dominated by the count so far, so a
# stale-low count-to-date doesn't degrade the estimate gracefully, it biases
# every bracket's probability down at once. Fail closed instead; the caller
# (_analyze_tornado_count_trade) declines to produce a prediction.
# 36h, not 6h: one missed daily cron plus slack, so an ordinary transient SPC
# outage doesn't blank the model, while a genuinely dead feed does.
CURRENT_YEAR_MAX_STALENESS = 36 * 3600

# How far behind today SPC's own newest published daily entry may be before a
# count-to-date is refused -- see month_to_date's own comment. 2 days: SPC has
# not published today's own entry yet by construction, plus one day of slack
# so an ordinary overnight publication lag does not blank the model.
_PUBLICATION_MAX_LAG_DAYS = 2

# The just-completed year keeps maturing for weeks (KNOWN BIASES #1), but it
# stops being "the current year" at midnight on Jan 1 and would otherwise
# inherit the 30-day historical TTL -- pinning November and December at their
# freshest, least-matured values on disk for most of January. Treat the
# previous year as short-TTL through this many days into the new one.
_PREV_YEAR_SHORT_TTL_DAYS = 45

_MEM_CACHE: dict[int, dict] = {}

# One breaker for the endpoint as a whole, not one per year (contrast
# hurricane_climatology's per-file breakers, where ATL and PAC are genuinely
# independent URLs that rotate on their own schedules). Every year here is the
# same host and the same path template, so a failure is a source failure, not
# a per-year one. recovery_timeout is 30 minutes rather than
# hurricane_climatology's 1 day because the current year's file really does
# change through the day -- backing off for a full day would blank the
# count-to-date tilt long after the source recovered. failure_threshold is 3
# rather than hurricane's 2 for the same reason the breaker is shared: one
# scan prices every bracket of every open event and can attempt several
# years' fetches in a row, so a single transient blip is likelier to produce
# two adjacent failures here than in a two-URL-per-day module.
_spc_cb = CircuitBreaker(
    name="spc_ruf_summary", failure_threshold=3, recovery_timeout=1800
)


# The only HTTP statuses that mean "this YEAR does not exist", as opposed to
# "the SOURCE is unhealthy". Deliberately NOT the whole 4xx band
# (opus-review-caught, batch-54 round 2): 429 and 403 are what a rate limiter
# or WAF returns during a real outage, and exempting them removes the only
# backpressure on this module's fan-out. One scan prices ~105 brackets, each
# resolving ~4 load_year calls per window year, and neither _MEM_CACHE nor
# the disk cache stores a FAILURE -- so an exempted 429 would let a single
# scan issue thousands of requests, provoking more 429s. Self-reinforcing.
_NOT_PUBLISHED_STATUSES = frozenset({404, 410})


def _is_client_error(exc: BaseException) -> bool:
    """True only for a status meaning the requested YEAR is not published --
    see _NOT_PUBLISHED_STATUSES for why this is not the whole 4xx band, and
    fetch_spc_year_raw's own comment for why those must not trip the shared
    circuit breaker."""
    resp = getattr(exc, "response", None)
    status = getattr(resp, "status_code", None)
    return status in _NOT_PUBLISHED_STATUSES


def _cache_path(year: int) -> Path:
    return DATA_DIR / f"spc_ruf_nat_{year}.json"


def _cache_max_age(year: int) -> int:
    """Short TTL for the current year (its in-progress month advances daily)
    and, per _PREV_YEAR_SHORT_TTL_DAYS, for the just-completed year through
    the first weeks of January while its final months are still maturing."""
    today = datetime.now(UTC).date()
    if year >= today.year:
        return CACHE_MAX_AGE_CURRENT
    if (
        year == today.year - 1
        and today.timetuple().tm_yday <= _PREV_YEAR_SHORT_TTL_DAYS
    ):
        return CACHE_MAX_AGE_CURRENT
    return CACHE_MAX_AGE_HISTORICAL


def _cache_age(cache: Path) -> float | None:
    """Seconds since `cache` was last written, or None if it doesn't exist."""
    if not cache.exists():
        return None
    try:
        return time.time() - cache.stat().st_mtime
    except OSError as exc:
        _log.warning("tornado_climatology: cache stat failed for %s: %s", cache, exc)
        return None


def _cache_is_stale(cache: Path, year: int) -> bool:
    age = _cache_age(cache)
    return age is None or age > _cache_max_age(year)


def _looks_like_spc_summary(payload: object) -> bool:
    """Structural validation. SPC serves a soft-404 for unknown paths under
    /climo/online/monthly/ (confirmed live: several bogus URLs returned 200
    with the tool's own HTML), so a 200 is not by itself evidence of real
    data. Requires the national torn total plus all 12 calendar months
    present with integer tornado counts, and a non-empty daily block --
    the exact three fields every function below reads."""
    if not isinstance(payload, dict):
        return False
    if not isinstance(payload.get("torn"), int):
        return False
    month = payload.get("month")
    if not isinstance(month, dict):
        return False
    for m in range(1, 13):
        entry = month.get(str(m))
        if not isinstance(entry, dict) or not isinstance(entry.get("torn"), int):
            return False
    daily = payload.get("daily")
    if not isinstance(daily, dict) or not daily:
        return False
    # Opus-review-caught (batch-54): requiring only "daily is a non-empty
    # dict" let a shape change (SPC flattening entries to {"0801": 5}, or
    # renaming `torn`) pass validation and get CACHED, after which every
    # remaining-share silently computed 0.0 -- producing an identical
    # [count_to_date] * 21 distribution, a clamped 0.01 probability AND a
    # zero-width CI, which _price_and_size reads as maximum confidence. The
    # loudest possible wrong answer. Require at least one real MMDD -> int
    # entry so the shape is actually pinned.
    if not any(
        len(k) == 4
        and k.isdigit()
        and isinstance(v, dict)
        and isinstance(v.get("torn"), int)
        for k, v in daily.items()
    ):
        return False
    return True


def fetch_spc_year_raw(year: int, force: bool = False) -> str | None:
    """Raw JSON text of one year's national preliminary storm-report summary.
    Disk-cached (see _cache_max_age); falls back to a stale cache on fetch
    failure rather than returning None outright -- mirrors
    hurricane_climatology.fetch_hurdat2_raw's exact fail-open shape.

    Note the asymmetry that fail-open creates and that callers must respect:
    a stale HISTORICAL year is harmless (the data is immutable), a stale
    CURRENT year is not (see CURRENT_YEAR_MAX_STALENESS). This function
    deliberately still returns the stale text in both cases -- freshness
    policy belongs to month_to_date(), which is the only caller that cares.
    """
    cache = _cache_path(year)
    if not force and not _cache_is_stale(cache, year):
        try:
            # encoding="utf-8" explicit -- must match atomic_write_text's own
            # hard-coded "utf-8" write encoding, not the OS locale default
            # (cp1252 on Windows), same reasoning hurricane_climatology's
            # cache reads carry.
            return cache.read_text(encoding="utf-8")
        except Exception as exc:
            _log.warning("fetch_spc_year_raw: cache read failed for %d: %s", year, exc)

    # is_open() is stateful (it transitions OPEN -> HALF-OPEN and designates
    # the probing caller), so it is called exactly once per fetch.
    if not force and _spc_cb.is_open():
        _log.info(
            "[CircuitBreaker] spc_ruf_summary circuit open — skipping fetch for %d",
            year,
        )
        return _load_stale_cache_or_none(cache, year)

    url = SPC_SUMMARY_URL_FMT.format(year=year)
    try:
        resp = _session.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        # Opus-review-caught (batch-54): a 4xx is NOT a source failure, and
        # counting it as one is actively harmful given this module shares ONE
        # breaker across every year. Individual years legitimately 404 -- that
        # is why FIRST_AVAILABLE_YEAR exists, and it is exactly what happens
        # each January before SPC publishes the new year's file. Three such
        # 404s would open the shared breaker and stop fetches for the whole
        # 21-year history window, which on a cold cache blanks the family
        # entirely. Everything else -- transport failures, 5xx, AND the other
        # 4xx (notably 403/429) -- still counts; see
        # _NOT_PUBLISHED_STATUSES.
        if _is_client_error(exc):
            _log.info(
                "fetch_spc_year_raw: %d not published yet or unavailable (%s) -- "
                "not counted against the circuit breaker",
                year,
                exc,
            )
        else:
            _spc_cb.record_failure()
            _log.warning(
                "fetch_spc_year_raw: fetch failed for %d (%s): %s", year, url, exc
            )
        return _load_stale_cache_or_none(cache, year)

    try:
        payload = json.loads(text)
    except Exception as exc:
        _spc_cb.record_failure()
        _log.warning(
            "fetch_spc_year_raw: response for %d is not JSON (%s) -- refusing to cache",
            year,
            exc,
        )
        return _load_stale_cache_or_none(cache, year)

    if not _looks_like_spc_summary(payload):
        _spc_cb.record_failure()
        _log.warning(
            "fetch_spc_year_raw: response for %d doesn't look like an SPC summary "
            "-- refusing to cache",
            year,
        )
        return _load_stale_cache_or_none(cache, year)

    _spc_cb.record_success()

    try:
        # emergency_copy=False: a disposable, trivially re-fetchable cache,
        # not irreplaceable trading state -- a write failure here shouldn't
        # trip cron.py's data/.emergency/ monitor. Same call
        # hurricane_climatology.fetch_hurdat2_raw makes, for the same reason.
        safe_io.atomic_write_text(text, cache, emergency_copy=False)
    except Exception as exc:
        _log.warning("fetch_spc_year_raw: cache write failed for %d: %s", year, exc)

    return text


def _load_stale_cache_or_none(cache: Path, year: int) -> str | None:
    if not cache.exists():
        _log.warning(
            "fetch_spc_year_raw: source failed for %d and no cache exists", year
        )
        return None
    try:
        return cache.read_text(encoding="utf-8")
    except Exception as exc:
        _log.warning(
            "fetch_spc_year_raw: stale cache read failed for %d: %s", year, exc
        )
        return None


def load_year(year: int, force: bool = False) -> dict | None:
    """Parsed+validated summary for one year, or None if unavailable.

    Memory-cached per year, like hurricane_climatology._MEM_CACHE: a single
    analyze_trade() scan prices every bracket of every open KXTORNADO event
    (11-17 markets per event), and each one needs the full history window --
    without this, one scan would re-read 21 cache files per market.

    The memory cache deliberately does NOT hold the CURRENT year: that entry
    carries the in-progress month's running count and would otherwise be
    pinned for the life of the process, defeating CACHE_MAX_AGE_CURRENT.
    """
    if year < FIRST_AVAILABLE_YEAR:
        return None
    is_current = year >= datetime.now(UTC).date().year
    if not force and not is_current and year in _MEM_CACHE:
        return _MEM_CACHE[year]

    raw = fetch_spc_year_raw(year, force=force)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except Exception as exc:
        _log.warning("load_year: cached text for %d is not JSON: %s", year, exc)
        return None
    if not _looks_like_spc_summary(payload):
        # Reachable via a stale cache written before this validator existed,
        # or a truncated write -- never via the fetch path above, which
        # refuses to cache anything that fails the same check.
        _log.warning("load_year: cached payload for %d failed validation", year)
        return None
    if not is_current:
        _MEM_CACHE[year] = payload
    return payload


def month_total(year: int, month: int) -> int | None:
    """That year's PRELIMINARY tornado count for `month`, on the calendar-
    month basis the market settles on. None if the year is unavailable.

    For the CURRENT year and CURRENT month this is the running count-to-date,
    not a final total -- month_to_date() is the accessor that says so
    explicitly and applies the freshness policy."""
    payload = load_year(year)
    if payload is None:
        return None
    entry = payload["month"].get(str(month))
    # _looks_like_spc_summary already guarantees all 12 months exist with int
    # torn values, so this is defensive only.
    if not isinstance(entry, dict) or not isinstance(entry.get("torn"), int):
        return None
    return entry["torn"]


def _latest_daily_date(year: int) -> date | None:
    """The newest calendar date present in `year`'s daily block, or None if
    the year is unavailable or carries no parseable daily key.

    Used as SPC's own publication stamp -- see month_to_date's freshness
    check. Reads the RAW daily keys deliberately (not _calendar_daily's
    re-attributed output): the question here is "how far has SPC published",
    which is a property of the feed, not of the calendar re-attribution."""
    payload = load_year(year)
    if payload is None:
        return None
    newest: date | None = None
    for key in payload["daily"]:
        if len(key) != 4:
            continue
        try:
            candidate = date(year, int(key[:2]), int(key[2:]))
        except ValueError:
            continue
        if newest is None or candidate > newest:
            newest = candidate
    return newest


def month_to_date(year: int, month: int, *, today: date) -> int | None:
    """The in-progress month's preliminary count so far, or None when it
    cannot be trusted.

    `today` is REQUIRED and keyword-only, deliberately. Opus-review-caught
    (batch-54 round 2): this function used to resolve its own
    datetime.now(UTC).date(), which silently created a SECOND clock -- and
    the caller's clock is America/New_York, because the market settles on a
    US calendar month. They disagree for the 4-5h between 00:00Z and local
    midnight, i.e. exactly the window the caller's own ET conversion was
    written to rescue. Net effect: at 22:00 EDT on Sep 30, with the
    September market still open, the caller correctly entered its
    in-progress branch and then this function refused with "2026-09 is not
    the current month (2026-10)" -- so the model still went silent for the
    single most decision-relevant evening of each monthly cycle, and the
    regression test could not see it because it stubbed this function out.
    Reproduced end-to-end before the fix.

    Making the parameter required (no default) is the point: a default would
    just re-create the second clock for anyone who forgot to pass one.

    Returns None (never a stale number, never 0-as-a-fallback) when the
    current-year cache is older than CURRENT_YEAR_MAX_STALENESS -- see that
    constant's own comment for why a stale count-to-date is worse than no
    count-to-date for this market family.

    Only meaningful for the current year: a past year's month is complete, so
    month_total() is the number, and a future year has no data at all. Both
    are rejected outright rather than silently answered.
    """
    if (year, month) != (today.year, today.month):
        # Opus-review-caught (batch-54): the year check alone let this answer
        # two questions it has no business answering, because the current-year
        # payload zero-fills future months and carries completed ones at their
        # final value. month_to_date(2026, 9) in August returned 0 ("no
        # tornadoes so far in September") for a month that had not started,
        # and month_to_date(2026, 7) returned July's FINAL total under a name
        # meaning "count so far" -- which, paired with a mid-month as_of_day,
        # would add a historical remaining on top of an already-complete
        # total. _analyze_tornado_count_trade happens to guard this today;
        # this function's whole job is fail-closed freshness, so it guards
        # itself.
        _log.warning(
            "month_to_date: %d-%02d is not the current month (%d-%02d) -- refusing",
            year,
            month,
            today.year,
            today.month,
        )
        return None

    total = month_total(year, month)
    if total is None:
        return None

    age = _cache_age(_cache_path(year))
    if age is None or age > CURRENT_YEAR_MAX_STALENESS:
        _log.warning(
            "month_to_date: current-year SPC cache for %d is %s -- refusing to "
            "use a stale count-to-date for %d-%02d",
            year,
            "missing" if age is None else f"{age / 3600:.1f}h old",
            year,
            month,
        )
        return None

    # Opus-review-caught (batch-54): CACHE_MAX_AGE_CURRENT/
    # CURRENT_YEAR_MAX_STALENESS bound how old OUR COPY is, not how current
    # SPC's own data is. If SPC's generator stalls while the endpoint keeps
    # serving 200s, every check above passes -- fresh fetch, valid payload,
    # mtime of now -- and the count-to-date is silently days behind, which is
    # exactly the "biases every bracket down at once" failure those constants
    # exist to prevent. The payload carries no timestamp, but its current-year
    # `daily` block is elapsed-only (verified live 2026-08-25: 236 keys,
    # "0101".."0824", with today's own key absent), so the newest daily key IS
    # a publication-date stamp. Require it within 2 days: 1 for "today is not
    # published yet" plus 1 of slack, so an ordinary overnight lag does not
    # blank the model. abs(), not a one-sided lag (opus-review-caught): if
    # SPC ever zero-fills the current year's daily block through Dec 31 --
    # the exact shape change _looks_like_spc_summary's own comment worries
    # about -- _published becomes a FUTURE date, the one-sided difference
    # goes negative, and the stalled-feed guard is satisfied vacuously
    # forever.
    _published = _latest_daily_date(year)
    if _published is None or abs((today - _published).days) > _PUBLICATION_MAX_LAG_DAYS:
        _log.warning(
            "month_to_date: SPC's own newest daily entry for %d is %s (today "
            "%s) -- refusing a count-to-date from a stalled feed",
            year,
            _published.isoformat() if _published else "missing",
            today.isoformat(),
        )
        return None
    return total


def _history_window(end_year: int | None, window_years: int) -> range:
    """The most recent `window_years` COMPLETE calendar years ending at
    `end_year` (default: last year, computed from the real clock -- pass
    explicit for deterministic tests). Clamped at FIRST_AVAILABLE_YEAR so a
    long window never silently requests years the source 404s on."""
    if end_year is None:
        end_year = datetime.now(UTC).date().year - 1
    start = max(FIRST_AVAILABLE_YEAR, end_year - window_years + 1)
    return range(start, end_year + 1)


def monthly_totals(
    month: int,
    *,
    window_years: int = HISTORY_WINDOW_YEARS,
    end_year: int | None = None,
) -> list[int]:
    """Unconditional climatological distribution: each window year's own
    calendar-month preliminary tornado count for `month`.

    Iterates an explicit calendar range and drops only years whose data is
    genuinely unavailable -- it never fabricates a 0 for a missing year. That
    is the opposite of hurricane_climatology.season_end_total_distribution's
    choice, and deliberately so: there, a year with no matching storms is a
    real count-of-0 season; here, a missing year is a failed fetch, and a
    fabricated 0 would be a fake "month with no tornadoes at all", which has
    never happened in the record (the smallest month in 2005-2025 is 1).
    Callers must check the returned length before trusting it.

    Opus-review-caught (batch-54): this has NO production caller --
    _analyze_tornado_count_trade always goes through
    conditioned_month_totals(), which reduces to exactly this at
    as_of_day=0. Kept as a diagnostics/analysis helper (and as the reduction
    target the boundary test asserts against), NOT as evidence that the
    unconditional path is exercised in production.
    """
    totals: list[int] = []
    for y in _history_window(end_year, window_years):
        t = month_total(y, month)
        if t is None:
            _log.warning(
                "monthly_totals: no SPC data for %d -- excluded from window", y
            )
            continue
        totals.append(t)
    return totals


def _calendar_daily(year: int, month: int) -> dict[int, int] | None:
    """`year`'s `month` daily report counts, re-attributed from SPC's
    CONVECTIVE-day basis onto the CALENDAR-day basis the market settles on.
    None if the year is unavailable or its daily block is unusable.

    Sums to `month_total(year, month)` exactly, by construction.

    Why this exists (opus-review-caught, batch-54 round 1 -- the original
    implementation took a raw convective-day ratio and claimed the boundary
    artifact "cancelled out of the ratio". It does not; see the derivation
    below):

    SPC's convective day runs 12Z->12Z, so relative to the calendar month the
    `daily` block over-reaches past the month's end by half a day and
    under-reaches at its start:

        D = M + s_out - s_in

    where D is the daily sum, M the calendar month total, s_out the last
    convective day's reports that fell into the NEXT calendar month, and s_in
    the previous month's last convective day's reports that fell into THIS
    one. Taking a plain ratio `remaining_daily / D` and rescaling by M leaves

        bias = [ s_out * (M - T) + T * s_in ] / D     >= 0  always

    (T = the true calendar remaining). Both terms are non-negative, so the
    error never cancels -- it is one-directional and UPWARD, and the dominant
    term grows as the month elapses, i.e. it is worst exactly when the
    remaining term matters most. Measured against all 21 window years: mean
    +1.4 to +4.2 reports at day 25 depending on month, never once negative,
    with per-year excursions to +29.5. On a ">N" ladder that is a systematic
    tilt toward YES.

    `D - M` is precisely `s_out - s_in`, and under the documented cause the
    whole discrepancy sits on the month's boundary days -- only the first and
    last convective days of a month can move reports across a month boundary
    at all. Attributing it there reconciles the series to `M` exactly, and
    reconstructs the calendar series exactly whenever at most one side
    spills: verified against both real shapes, the trailing-spill case (Mar
    2023: D=253, M=161, recovers the true 71-report tail) and the
    leading-spill case (Mar 2017: D-M=-57, recovers 5 where the raw ratio
    gives 6.6 and hurricane's subtraction gives 62).

    HONEST LIMIT (opus-review-caught, batch-54 round 2): only `s_out - s_in`
    is observable, so when BOTH boundaries spill this nets them and touches
    one day, under-correcting by `min(s_in, s_out)` and leaving the last day
    over-weighted -- the same upward direction as the defect this replaces,
    much smaller. Lower-bounded from the real files at >= 15 of 252
    month-years, residual <= 12 reports (worst: 2018-11). Not fixable from
    this endpoint: `s_in` and `s_out` are not separately published. The net
    improvement over the raw ratio (mean +1.4 to +4.2, max +29.5) stands.
    """
    payload = load_year(year)
    if payload is None:
        return None
    total = month_total(year, month)
    if total is None:
        return None
    prefix = f"{month:02d}"
    counts: dict[int, int] = {}
    skipped = 0
    for key, entry in payload["daily"].items():
        if not key.startswith(prefix) or len(key) != 4:
            continue
        try:
            # date() rather than a bare int(): "0100" and "0132" are not real
            # days, and a phantom day 32 would become max(counts) and absorb
            # the delta subtraction while a day 0 would become the spill-in
            # target. _latest_daily_date already validates this way; this
            # matches it (opus-review-caught).
            day = date(year, month, int(key[2:])).day
            counts[day] = int(entry["torn"])
        except (KeyError, TypeError, ValueError):
            # Never silent: a daily block whose entries stopped being
            # {"torn": int} would otherwise make every share 0.0 and hand the
            # caller a degenerate, maximally-confident distribution.
            skipped += 1
    if skipped:
        _log.warning(
            "_calendar_daily: %d unusable daily entries for %d-%02d -- "
            "refusing to derive a share from a partial block",
            skipped,
            year,
            month,
        )
        return None
    if not counts:
        _log.warning("_calendar_daily: no daily entries for %d-%02d", year, month)
        return None

    delta = sum(counts.values()) - total
    if delta > 0:
        # Reports the convective basis carried past the month's end.
        last = max(counts)
        if counts[last] < delta:
            # Under the boundary-spill model this cannot happen: the spill out
            # is a SUBSET of the last convective day's own reports, so
            # delta = s_out - s_in <= s_out <= counts[last]. Verified across
            # all 260 real month-years on file (zero violations, zero
            # reconciliation failures). But the model is an attribution, not
            # something SPC publishes, so a future data anomaly could break
            # it -- and driving a day negative would yield a share outside
            # [0, 1] and a nonsense distribution. Refuse instead; the caller
            # drops the year.
            _log.warning(
                "_calendar_daily: %d-%02d needs to move %d reports off day %d "
                "which only has %d -- the boundary-spill model does not hold "
                "here, refusing",
                year,
                month,
                delta,
                last,
                counts[last],
            )
            return None
        counts[last] -= delta
    elif delta < 0:
        # Reports the previous month's last convective day contributed here.
        # Day 1 EXPLICITLY, not min(counts) (opus-review-caught): physically
        # a spill-in lands on calendar day 1, and those coincide only because
        # SPC's daily block is currently dense (verified: every cached year
        # has all 365/366 keys). If SPC ever published only non-zero days, a
        # quiet start of month would push the spill onto a later day and
        # inflate every earlier cutoff's share, with the suite still green.
        counts[1] = counts.get(1, 0) + -delta
    if sum(counts.values()) != total:  # pragma: no cover - arithmetic identity
        _log.warning(
            "_calendar_daily: re-attribution for %d-%02d did not reconcile "
            "(%d vs month total %d)",
            year,
            month,
            sum(counts.values()),
            total,
        )
        return None
    return counts


def remaining_share(year: int, month: int, as_of_day: int) -> float | None:
    """Fraction of `year`'s `month` tornado reports that fell on CALENDAR days
    after `as_of_day`. None when the year's daily block is unavailable or
    unusable.

    Returns 1.0 for as_of_day <= 0 (nothing has happened yet). Returns 0.0
    when no reports fell after `as_of_day` -- which includes the entirely
    routine end-of-month case (any cutoff at or past the month's last active
    day) as well as a month whose calendar total is 0. Opus-review-corrected:
    an earlier version of this docstring claimed 0.0 "only" meant a
    zero-total month and so "in practice means a data defect", which is
    wrong and is the kind of claim a later reader turns into a guard. What IS
    true is that an unusable daily block returns None rather than 0.0, so
    conditioned_month_totals() drops that year instead of silently treating
    it as "this month is already over".

    Computed from _calendar_daily(), NOT from the raw convective-day block --
    see that function's docstring for why the raw ratio is biased upward.
    """
    if as_of_day <= 0:
        return 1.0
    # A month whose real calendar total is 0 has no remaining share, and that
    # is a legitimate answer rather than a defect -- checked BEFORE
    # _calendar_daily, which cannot reconstruct anything from an empty daily
    # block and correctly refuses. Opus-review-caught: conflating the two
    # made a data defect look like "this month is already over", which drags
    # the whole distribution down instead of dropping the year.
    total = month_total(year, month)
    if total is None:
        return None
    if total == 0:
        return 0.0
    counts = _calendar_daily(year, month)
    if counts is None:
        return None
    return sum(v for day, v in counts.items() if day > as_of_day) / total


def conditioned_month_totals(
    month: int,
    as_of_day: int,
    count_to_date: int,
    *,
    window_years: int = HISTORY_WINDOW_YEARS,
    end_year: int | None = None,
) -> list[float]:
    """Bootstrap distribution of this month's FINAL preliminary count, given
    `count_to_date` reports through day `as_of_day`.

    For each window year y:

        total[y] = count_to_date + month_total(y) * remaining_share(y, as_of_day)

    i.e. this month's real progress so far, plus that year's own remaining
    portion of its own month total. Same "actual-to-date + historical-
    remaining" shape as acis_precip.historical_remaining_and_full_month_sums
    and hurricane_climatology.season_end_total_distribution, with one
    deliberate difference: the remaining term is a rescaled SHARE of that
    year's month total rather than hurricane's subtraction
    (max(0, end_count - historical_to_date)).

    Hurricane's subtraction cannot be used here, and neither can a raw
    convective-day ratio. `month` (calendar basis, the settlement basis) and
    `daily` (convective-day basis) disagree at month boundaries -- see this
    module's header -- and BOTH naive combinations inherit a one-directional
    upward bias from that. Measured across all 21 window years at day 25:
    the raw-ratio form runs +1.4 to +4.2 reports high on average (max +29.5),
    hurricane's subtraction +2.0 to +5.3 (max +92.0, and on Mar 2017's
    leading-spill shape it returns 62 where the truth is 5). remaining_share
    therefore works off _calendar_daily(), which re-attributes the
    discrepancy onto the boundary day it must have come from and reconciles
    to `month` exactly; see that function's docstring for the derivation.

    The result reduces exactly to monthly_totals() at as_of_day=0
    (remaining_share is 1.0, count_to_date is 0) and to a degenerate
    [count_to_date] * n at as_of_day past the end of the month.

    Returns floats, not ints: a rescaled share is not integral. Every
    consumer here compares against a threshold rather than counting
    occurrences of a specific value, so no rounding is applied -- rounding
    would only move mass across bracket boundaries for no gain.
    """
    totals: list[float] = []
    for y in _history_window(end_year, window_years):
        end_count = month_total(y, month)
        if end_count is None:
            _log.warning(
                "conditioned_month_totals: no SPC data for %d -- excluded from window",
                y,
            )
            continue
        share = remaining_share(y, month, as_of_day)
        if share is None:
            _log.warning(
                "conditioned_month_totals: no daily data for %d -- excluded from window",
                y,
            )
            continue
        totals.append(count_to_date + end_count * share)
    return totals


def exceedance_probability(
    totals: list[float], threshold: float, strike_type: str
) -> float:
    """strike_type: "greater" (Kalshi's real, live-confirmed ">N" strike shape
    on every KXTORNADO market sampled 2026-08-25 -- all 83 across 7 events)
    or "greater_or_equal" (accepted defensively; not seen live on this
    family). Clamped to [0.01, 0.99], matching every other probability this
    codebase produces. Returns 0.5 (maximally uninformative) if `totals` is
    empty rather than dividing by zero -- mirrors
    hurricane_climatology.exceedance_probability exactly."""
    if not totals:
        return 0.5
    if strike_type == "greater_or_equal":
        hits = sum(1 for t in totals if t >= threshold)
    else:
        hits = sum(1 for t in totals if t > threshold)
    return max(0.01, min(0.99, hits / len(totals)))


def bootstrap_ci(
    totals: list[float], threshold: float, strike_type: str, n: int = 500
) -> tuple[float, float]:
    """Mirrors hurricane_climatology.bootstrap_ci's exact resampling shape: n
    resamples-with-replacement of `totals` (already the conditioned or
    unconditional distribution -- the tilt is baked into each element, there
    is no separate actual/remaining decomposition to hold fixed), each
    resample's exceedance fraction, sorted, 5th/95th percentile returned.
    Returns (0.0, 1.0) if fewer than 15 historical years are available -- same
    threshold as hurricane_climatology.bootstrap_ci and
    acis_precip.bootstrap_ci_month_total.

    Unlike hurricane's, this guard is genuinely reachable: monthly_totals()/
    conditioned_month_totals() drop years whose data failed to load rather
    than fabricating a 0 for them, so a partly-unavailable source really can
    return fewer than 15 entries.
    """
    if len(totals) < 15:
        return (0.0, 1.0)

    def prob_from(sample: list[float]) -> float:
        if strike_type == "greater_or_equal":
            return sum(1 for s in sample if s >= threshold) / len(sample)
        return sum(1 for s in sample if s > threshold) / len(sample)

    k = len(totals)
    boot = sorted(prob_from(random.choices(totals, k=k)) for _ in range(n))
    return (boot[min(int(n * 0.05), n - 1)], boot[min(int(n * 0.95), n - 1)])


def is_already_decided(count_to_date: int, threshold: float, strike_type: str) -> bool:
    """True when this month's count has ALREADY crossed `threshold`, so the
    market's YES outcome is arithmetically settled with days still to run.

    Only a decided-YES is possible before the month ends: a monthly count is
    monotonically non-decreasing, so exceeding a floor can never be undone,
    while falling short is never final until the last day. There is
    deliberately no decided-NO branch.

    batch-54's own spec requires these be priced 0/1 and excluded from
    sizing -- see _analyze_tornado_count_trade, which zeroes their edge and
    Kelly so no shadow prediction or order is ever generated from arithmetic
    the market has already priced.
    """
    if strike_type == "greater_or_equal":
        return count_to_date >= threshold
    return count_to_date > threshold
