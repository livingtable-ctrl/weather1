"""
NOAA HURDAT2 best-track climatology for Kalshi's season-total hurricane/
tropical-storm-count markets (backlog.txt "HURRICANE MARKETS" -- season-count
model). Mirrors acis_precip.py's fetch/cache/probability module shape.

HURDAT2 is unauthenticated, public, and was never touched by this bot before
this feature. It only carries FINALIZED seasons -- the current year's season
isn't added until roughly the following April -- so it supplies the
climatological base distribution only. Current-season-to-date counts (the
live "tilt") come from a different source entirely: Kalshi's own settled
KXHURRICANENAMES markets (see weather_markets.py's
refresh_hurricane_count_to_date/_get_cached_hurricane_count_to_date), not
anything in this module.

Two files cover all three Kalshi-relevant basins: NOAA's Atlantic HURDAT2
("ATL") and its combined Eastern+Central Pacific HURDAT2 ("PAC" -- storms are
distinguished by their own 2-letter ID prefix, "EP" or "CP", confirmed live
2026-08-03 that the nepac file already contains both).
"""

from __future__ import annotations

import logging
import random
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests

from paths import DATA_DIR

_log = logging.getLogger(__name__)

_session = requests.Session()

# NOAA embeds a release-date suffix in the filename and updates it once a
# year (each January/February, adding the just-finished season). If NOAA
# rotates the filename again, these two need a manual refresh -- confirmed
# live 2026-08-03, both current through the 2025 season.
HURDAT2_URLS = {
    "ATL": "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-02272026.txt",
    "PAC": "https://www.nhc.noaa.gov/data/hurdat/hurdat2-nepac-1949-2025-02272026.txt",
}

# Kalshi's own basin vocabulary (ATL/EPAC/CPAC market-ticker infixes) mapped
# to (a) which HURDAT2 file carries that basin's storms and (b) the 2-letter
# storm-ID prefix within that file identifying them. An explicit map, not a
# string slice, so a future HURDAT2 ID-format change fails loudly instead of
# silently mis-scoping a basin's storm list.
BASIN_FILE_AND_PREFIX = {
    "ATL": ("ATL", "AL"),
    "EPAC": ("PAC", "EP"),
    "CPAC": ("PAC", "CP"),
}

CACHE_MAX_AGE = (
    30 * 24 * 3600
)  # 30 days, matches acis_precip.py's CACHE_MAX_AGE rationale

# HURDAT2's own sentinel for a missing wind reading (NOAA format doc) --
# never a real, physically-meaningful wind speed.
_MISSING_WIND = -999

# Kalshi's own settlement thresholds (confirmed live 2026-08-03 against real
# rules_primary text): "39 mph or above" = 34kt tropical-storm strength,
# "category 1 or above" = 64kt, "category 3 or above" (major) = 96kt.
COUNT_THRESHOLDS_KT = {
    "tropical_storm": 34,
    "hurricane": 64,
    "major_hurricane": 96,
}

# backlog.txt "HURRICANE MARKETS" -- time-to-next-event model (2026-08-07), for
# KXNEXTHURDATE ("will the next hurricane form before <date>?") and
# KXNEXTCAT5HURDATE ("will the next Category 5 hurricane form before <date>?").
# "hurricane" reuses the same 64kt threshold as COUNT_THRESHOLDS_KT (kept as a
# separate dict, not merged, since these two dicts serve different questions --
# season-end count vs. day of first occurrence). 137kt matches KXHURCAT's own
# live-confirmed Category-5 threshold (157 mph).
NEXT_EVENT_THRESHOLDS_KT = {
    "hurricane": 64,
    "cat5_hurricane": 137,
}

HISTORY_WINDOW_YEARS = 30  # most recent 30 COMPLETE seasons -- matches this
# codebase's existing 30-year convention (acis_precip.HISTORY_YEARS) and,
# independently, is a real judgment call worth documenting: Atlantic/Pacific
# storm-count climatology has trended with the AMO's active/quiet phases
# (elevated Atlantic activity since ~1995) -- a 30-year recent window avoids
# diluting a current-era estimate with the markedly quieter 1970-1994 stretch,
# not just a mechanical copy of the "30" number.

_MEM_CACHE: dict[str, list[dict]] = {}


def _cache_path(file_key: str) -> Path:
    return DATA_DIR / f"hurdat2_{file_key}.txt"


def _cache_is_stale(cache: Path) -> bool:
    if not cache.exists():
        return True
    return (time.time() - cache.stat().st_mtime) > CACHE_MAX_AGE


def fetch_hurdat2_raw(file_key: str, force: bool = False) -> str | None:
    """file_key is "ATL" or "PAC" (see HURDAT2_URLS/BASIN_FILE_AND_PREFIX).
    Disk-cached (30 days); falls back to a stale cache on fetch failure
    rather than returning None outright -- mirrors
    acis_precip.fetch_historical_daily's exact fail-open shape."""
    cache = _cache_path(file_key)
    if not force and cache.exists() and not _cache_is_stale(cache):
        try:
            return cache.read_text()
        except Exception as exc:
            _log.warning(
                "fetch_hurdat2_raw: cache read failed for %s: %s", file_key, exc
            )

    url = HURDAT2_URLS[file_key]
    try:
        resp = _session.get(url, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        _log.warning(
            "fetch_hurdat2_raw: fetch failed for %s (%s): %s", file_key, url, exc
        )
        return _load_stale_cache_or_none(cache, file_key)

    # A renamed/moved URL (NOAA rotates these yearly) can 200 with an HTML
    # error page instead of 404ing -- refuse to cache/parse anything that
    # doesn't look like real HURDAT2 storm-header data.
    if not text or not any(f"{p}0" in text for p in ("AL", "EP", "CP")):
        _log.warning(
            "fetch_hurdat2_raw: response for %s doesn't look like HURDAT2 data "
            "-- refusing to cache",
            file_key,
        )
        return _load_stale_cache_or_none(cache, file_key)

    try:
        cache.write_text(text)
    except Exception as exc:
        _log.warning("fetch_hurdat2_raw: cache write failed for %s: %s", file_key, exc)

    return text


def _load_stale_cache_or_none(cache: Path, file_key: str) -> str | None:
    if not cache.exists():
        _log.warning(
            "fetch_hurdat2_raw: API failed for %s and no cache exists", file_key
        )
        return None
    try:
        return cache.read_text()
    except Exception as exc:
        _log.warning(
            "fetch_hurdat2_raw: stale cache read failed for %s: %s", file_key, exc
        )
        return None


def parse_hurdat2(raw_text: str) -> list[dict]:
    """Parse HURDAT2 fixed-format text into one compact summary dict per
    storm: {"id", "name", "basin" (2-letter ID prefix, e.g. "AL"/"EP"/"CP"),
    "year", "max_wind_kt" (None if every reading was missing), "threshold_day"
    (dict kt -> (month, day) tuple of the storm's EARLIEST reading >= kt, or
    None if it never reached kt)}.

    threshold_day is built for the union of COUNT_THRESHOLDS_KT.values() (34/
    64/96, season-end count model) and NEXT_EVENT_THRESHOLDS_KT.values() (64/
    137, time-to-next-event model) -- kt=64 is shared by both, kt=137 (Category
    5) only matters to the next-event model. One parse serves both models; no
    separate fetch or pass over the raw text.

    threshold_day uses a (month, day) tuple, NOT an ordinal day-of-year --
    opus-review-caught (2026-08-03): tm_yday shifts by 1 for every date after
    Feb 29 in a leap year relative to a non-leap year, so comparing raw
    day-of-year integers across different years' storms (as count_as_of_day
    does) silently mis-cuts by a day whenever exactly one of "today" and the
    historical year being compared is a leap year. (month, day) tuples
    compare correctly in calendar order regardless of either year's leap
    status.

    Deliberately does not keep full per-row track data (lat/lon/pressure/wind
    radii) -- nothing downstream needs it, and the full Atlantic+Pacific
    record is ~90K rows.
    """
    storms: list[dict] = []
    lines = [ln for ln in raw_text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        header = [p.strip() for p in lines[i].split(",")]
        if len(header) < 3:
            _log.warning(
                "parse_hurdat2: unparseable header line %r -- stopping parse",
                lines[i],
            )
            break
        storm_id = header[0]
        name = header[1]
        try:
            n_rows = int(header[2])
        except ValueError:
            _log.warning(
                "parse_hurdat2: non-integer row count in header %r -- stopping parse",
                lines[i],
            )
            break
        if len(storm_id) < 8:
            _log.warning(
                "parse_hurdat2: storm ID %r shorter than expected -- stopping parse",
                storm_id,
            )
            break
        basin_prefix = storm_id[:2]
        try:
            year = int(storm_id[4:8])
        except ValueError:
            year = None

        max_wind: int | None = None
        threshold_day: dict[int, tuple[int, int] | None] = dict.fromkeys(
            set(COUNT_THRESHOLDS_KT.values()) | set(NEXT_EVENT_THRESHOLDS_KT.values())
        )
        for j in range(1, n_rows + 1):
            if i + j >= len(lines):
                _log.warning(
                    "parse_hurdat2: storm %s header claims %d rows but file "
                    "ended early -- using what was read",
                    storm_id,
                    n_rows,
                )
                break
            row = [p.strip() for p in lines[i + j].split(",")]
            if len(row) < 7:
                continue
            date_str, wind_str = row[0], row[6]
            try:
                wind = int(wind_str)
            except ValueError:
                continue
            # Opus-review-caught (2026-08-03): only the exact missing
            # sentinel was rejected -- a corrupted feed reporting a
            # nonsensical wind (negative-but-not-the-sentinel, or an absurd
            # value like 9999) would otherwise be accepted as real, silently
            # fabricating a major hurricane. 250kt is far above any storm
            # ever recorded (strongest on record ~185kt) -- a generous
            # sanity band, not a tight physical bound.
            if wind <= _MISSING_WIND or wind > 250:
                continue
            if max_wind is None or wind > max_wind:
                max_wind = wind
            try:
                d = date(int(date_str[0:4]), int(date_str[4:6]), int(date_str[6:8]))
            except ValueError:
                continue
            month_day = (d.month, d.day)
            for kt in threshold_day:
                if wind >= kt and threshold_day[kt] is None:
                    threshold_day[kt] = month_day

        storms.append(
            {
                "id": storm_id,
                "name": name,
                "basin": basin_prefix,
                "year": year,
                "max_wind_kt": max_wind,
                "threshold_day": threshold_day,
            }
        )
        i += n_rows + 1
    return storms


def load_basin_storms(basin: str, force: bool = False) -> list[dict] | None:
    """basin is Kalshi's own vocabulary: "ATL"/"EPAC"/"CPAC". Returns all
    parsed storms from that basin's HURDAT2 file (PAC covers BOTH EPAC and
    CPAC -- this filters to the requested basin's own storm-ID prefix), or
    None if the underlying file couldn't be fetched at all (no cache, no live
    fetch). Process-lifetime memory-cached per file_key, same shape as
    acis_precip's _MEM_CACHE (one real HURDAT2 file serves every basin/
    count_type/threshold query against it, not just the first)."""
    if basin not in BASIN_FILE_AND_PREFIX:
        raise ValueError(f"load_basin_storms: unknown basin {basin!r}")
    file_key, id_prefix = BASIN_FILE_AND_PREFIX[basin]

    if not force and file_key in _MEM_CACHE:
        all_storms = _MEM_CACHE[file_key]
    else:
        raw = fetch_hurdat2_raw(file_key, force=force)
        if raw is None:
            return None
        all_storms = parse_hurdat2(raw)
        _MEM_CACHE[file_key] = all_storms
        _warn_if_stale(all_storms, file_key)

    return [s for s in all_storms if s["basin"] == id_prefix]


def _warn_if_stale(all_storms: list[dict], file_key: str) -> None:
    """Opus-review-caught (2026-08-03): fetch_hurdat2_raw's own "looks like
    HURDAT2 data" check only confirms real storm-header lines are PRESENT,
    not that the file is COMPLETE -- a silently truncated download (a
    partial HTTP response written to disk before this bot ever notices)
    still passes that check and gets cached for 30 days, serving a much
    older effective history window with no visible signal anything is
    wrong. Checked at the FULL (pre-basin-filter) file level, not per-basin
    -- a real basin can legitimately have no recent storm (Central Pacific
    gap years are real), so per-basin recency isn't a valid staleness
    signal, but the Atlantic+combined-Pacific FILE itself is updated yearly
    and should always contain the last 1-2 complete seasons somewhere in it.
    Warns only -- never blocks trading, matching this module's fail-open
    convention elsewhere (acis_precip.py's identical "log loudly, keep
    going" pattern)."""
    years = [s["year"] for s in all_storms if s["year"] is not None]
    if not years:
        return
    newest = max(years)
    current_year = datetime.now(UTC).date().year
    if newest < current_year - 2:
        _log.warning(
            "hurricane_climatology: %s's newest storm year is %d, more than "
            "2 years behind %d -- HURDAT2 data may be stale or the cached "
            "file may be truncated",
            file_key,
            newest,
            current_year,
        )


def season_end_counts(storms: list[dict], year: int) -> dict[str, int]:
    """storms already filtered to one basin (via load_basin_storms). Counts,
    for the given year, how many distinct storms EVER reached each of
    tropical_storm/hurricane/major_hurricane strength -- a plain max-wind
    threshold check, matching Kalshi's own rules_primary text literally
    (e.g. "more than N storms with maximum sustained windspeeds of 39 mph or
    above"), not NHC's separate classification-code convention (which has
    itself changed over HURDAT2's 175-year record)."""
    season = [s for s in storms if s["year"] == year]
    return {
        count_type: sum(
            1 for s in season if s["max_wind_kt"] is not None and s["max_wind_kt"] >= kt
        )
        for count_type, kt in COUNT_THRESHOLDS_KT.items()
    }


def count_as_of_day(
    storms: list[dict], year: int, count_type: str, as_of: tuple[int, int]
) -> int:
    """How many of `year`'s storms had ALREADY reached `count_type` strength
    on or before `as_of` (a (month, day) tuple). Always <=
    season_end_counts(...)[count_type] for the same year, by construction.

    Takes a (month, day) tuple, NOT an ordinal day-of-year int -- see
    parse_hurdat2's own docstring for why (leap-year tm_yday misalignment
    across different years)."""
    kt = COUNT_THRESHOLDS_KT[count_type]
    season = [s for s in storms if s["year"] == year]
    return sum(
        1
        for s in season
        if s["threshold_day"].get(kt) is not None and s["threshold_day"][kt] <= as_of
    )


def season_end_total_distribution(
    storms: list[dict],
    count_type: str,
    *,
    window_years: int = HISTORY_WINDOW_YEARS,
    as_of_month_day: tuple[int, int] | None = None,
    current_count: int | None = None,
    end_year: int | None = None,
) -> list[int]:
    """Empirical bootstrap distribution of SEASON-END counts for
    `count_type`, built from the most recent `window_years` COMPLETE
    historical CALENDAR seasons (end_year - window_years + 1 .. end_year
    inclusive) -- NOT merely the years that happen to appear in `storms`.

    Opus-review-caught (2026-08-03): deriving the window from
    `{s["year"] for s in storms}` silently DROPS any season with zero
    storms of the requested basin's own ID prefix from the distribution
    entirely, instead of correctly contributing a 0. This is invisible for
    Atlantic/Eastern-Pacific (every year on record has at least one AL/EP
    storm) but measurably wrong for Central Pacific, which has real gap
    years with zero CP-prefixed storms (confirmed against the live HURDAT2
    file: only 42 of the 77 years 1949-2025 have any CP storm at all) --
    those gap years were silently excluded rather than counted as a real
    hurricane-count=0 season, materially overstating P(count > 0) for CPAC
    (measured live: 0.600 as coded vs the correct 0.367 over the same
    30-year span). Iterating an explicit calendar range and calling
    season_end_counts() for every single year in it (which correctly
    returns 0 for a year with no matching storms) fixes this.

    `end_year` defaults to last year (the most recent HURDAT2-COMPLETE
    season -- the current year's isn't added until the following spring),
    computed from the real clock; pass explicit for deterministic tests.

    Unconditional mode (as_of_month_day/current_count both None): returns
    each window year's real season-end count directly -- the plain
    climatological distribution.

    Conditional/tilted mode (both provided): for each window year, computes
    that year's OWN count-as-of the SAME calendar (month, day), then adds
    (this season's real current_count minus that year's historical to-date
    count) to that year's real season-end count -- i.e. bootstraps the
    REMAINING count from history and adds it to this season's actual
    progress so far. Mirrors
    acis_precip.historical_remaining_and_full_month_sums's "month-to-date-
    actual + historical-remaining-days" shape exactly, just discrete counts
    instead of a continuous inches total.
    """
    if end_year is None:
        end_year = datetime.now(UTC).date().year - 1
    window = range(end_year - window_years + 1, end_year + 1)
    totals: list[int] = []
    for y in window:
        end_count = season_end_counts(storms, y)[count_type]
        if as_of_month_day is None or current_count is None:
            totals.append(end_count)
            continue
        historical_to_date = count_as_of_day(storms, y, count_type, as_of_month_day)
        remaining = max(0, end_count - historical_to_date)
        totals.append(current_count + remaining)
    return totals


def exceedance_probability(
    totals: list[int], threshold: float, strike_type: str
) -> float:
    """strike_type: "greater" (Kalshi's real, live-confirmed ">N" strike
    shape for every one of these 5 series) or "greater_or_equal" (accepted
    defensively; not seen live on this market family, unlike KXHURCAT).
    Clamped to [0.01, 0.99], matching every other probability this codebase
    produces (e.g. acis_precip.bootstrap_ci_month_total) -- downstream Kelly
    sizing assumes a non-degenerate probability. Returns 0.5 (maximally
    uninformative) if `totals` is empty rather than dividing by zero."""
    if not totals:
        return 0.5
    if strike_type == "greater_or_equal":
        hits = sum(1 for t in totals if t >= threshold)
    else:
        hits = sum(1 for t in totals if t > threshold)
    return max(0.01, min(0.99, hits / len(totals)))


def bootstrap_ci(
    totals: list[int], threshold: float, strike_type: str, n: int = 500
) -> tuple[float, float]:
    """Mirrors acis_precip.bootstrap_ci_month_total's exact resampling
    shape: n resamples-with-replacement of `totals` (already the tilted or
    unconditional season-end-count bootstrap, not a separate remaining/actual
    decomposition -- there is no live month-to-date-style actual to hold
    fixed here, the tilt is already baked into each element of `totals`),
    each resample's exceedance fraction, sorted, 5th/95th percentile
    returned. Returns (0.0, 1.0) if fewer than 15 historical years are
    available (too few to trust a CI) -- same threshold as
    acis_precip.bootstrap_ci_month_total."""
    if len(totals) < 15:
        return (0.0, 1.0)

    def prob_from(sample: list[int]) -> float:
        if strike_type == "greater_or_equal":
            return sum(1 for s in sample if s >= threshold) / len(sample)
        return sum(1 for s in sample if s > threshold) / len(sample)

    k = len(totals)
    boot = sorted(prob_from(random.choices(totals, k=k)) for _ in range(n))
    return (boot[min(int(n * 0.05), n - 1)], boot[min(int(n * 0.95), n - 1)])


# ── Time-to-next-event model (backlog.txt "HURRICANE MARKETS", 2026-08-07) ──
# For KXNEXTHURDATE/KXNEXTCAT5HURDATE: "will the next [Category-5] hurricane
# form before <date>?" -- a genuinely different question shape than the
# season-end count model above (day of FIRST occurrence, not a season total),
# reusing the same underlying storms/threshold_day data.


_KNOWN_THRESHOLD_KT = set(COUNT_THRESHOLDS_KT.values()) | set(
    NEXT_EVENT_THRESHOLDS_KT.values()
)


def first_occurrence_day(
    storms: list[dict], year: int, kt: int
) -> tuple[int, int] | None:
    """Earliest (month, day) at which ANY of `year`'s storms first reached kt
    strength, or None if no storm did that year. `storms` already filtered to
    one basin (via load_basin_storms). Opus-review-caught (2026-08-07): kt
    must be one of the thresholds parse_hurdat2 actually tracks -- `dict.get`
    on an unrecognized kt silently returns None for every storm (indistinguishable
    from "no storm reached it"), producing a confidently wrong all-False
    result instead of a loud failure. Currently unreachable in production
    (the only caller derives kt from NEXT_EVENT_THRESHOLDS_KT), but fails
    loudly here rather than relying on that invariant holding forever."""
    if kt not in _KNOWN_THRESHOLD_KT:
        raise ValueError(
            f"first_occurrence_day: kt={kt} is not tracked by parse_hurdat2's "
            f"threshold_day (known: {sorted(_KNOWN_THRESHOLD_KT)})"
        )
    season = [s for s in storms if s["year"] == year]
    days = [
        s["threshold_day"][kt] for s in season if s["threshold_day"].get(kt) is not None
    ]
    return min(days) if days else None


def next_event_outcomes(
    storms: list[dict],
    kt: int,
    target_month_day: tuple[int, int],
    *,
    as_of_month_day: tuple[int, int] | None = None,
    window_years: int = HISTORY_WINDOW_YEARS,
    end_year: int | None = None,
) -> list[bool]:
    """Empirical outcomes ("did the event occur before target_month_day?") for
    the most recent `window_years` COMPLETE historical calendar seasons --
    same explicit calendar-range iteration season_end_total_distribution uses
    (not merely the years that happen to appear in `storms`), for the same
    reason: a year with zero qualifying storms must still contribute a real
    False, not be silently dropped.

    Two modes, mirroring season_end_total_distribution's own
    "as_of_month_day is None or current_count is None -> unconditional"
    fallback exactly -- conditioning on "today's date" is only valid when the
    caller actually KNOWS live that the event hasn't happened yet this season;
    assuming that whenever a live signal is merely unavailable would reproduce
    the exact stale-cache "flips a probability with no warning" failure mode
    _get_cached_hurricane_count_to_date's own staleness guard already exists to
    prevent for the count model.

    Unconditional mode (as_of_month_day=None, the default): every window year
    contributes one outcome, True iff the event's first occurrence that year
    was on or before target_month_day.

    Conditional mode (as_of_month_day provided -- only when live data confirms
    the event has NOT happened yet this season): first restrict to "eligible"
    years -- years where the event historically hadn't yet occurred by the same
    calendar point (None, i.e. never that year, or occurred strictly after
    as_of_month_day) -- then outcome is True iff that year's first occurrence
    was on or before target_month_day. This is the empirical probability of the
    event occurring before the target date, GIVEN it's confirmed still pending
    today; years where it had already resolved by an equivalent historical
    point aren't representative of today's real state and are excluded.
    """
    if end_year is None:
        end_year = datetime.now(UTC).date().year - 1
    window = range(end_year - window_years + 1, end_year + 1)
    outcomes: list[bool] = []
    for y in window:
        day = first_occurrence_day(storms, y, kt)
        if as_of_month_day is not None:
            eligible = day is None or day > as_of_month_day
            if not eligible:
                continue
        outcomes.append(day is not None and day <= target_month_day)
    return outcomes


def next_event_probability(outcomes: list[bool]) -> float:
    """Clamped to [0.01, 0.99], matching every other probability this codebase
    produces. Returns 0.5 (maximally uninformative) if `outcomes` is empty
    rather than dividing by zero -- mirrors exceedance_probability."""
    if not outcomes:
        return 0.5
    return max(0.01, min(0.99, sum(outcomes) / len(outcomes)))


# ── Storm-order model (backlog.txt "HURRICANE MARKETS", 2026-08-07) ──
# For KXFIRSTHURRICANE: "will <name> be the first hurricane in the Atlantic
# this season?" -- a third, genuinely different question shape from both
# models above: which NAME (of the season's fixed, alphabetically-ordered
# pre-assigned list) ends up being first to cross the hurricane threshold,
# not a season total or a single calendar date. Reuses the same underlying
# storms/threshold_day data as both other models.


## Opus-review-caught (2026-08-07, CRITICAL): HURDAT2's storm-ID embedded
# sequence number (e.g. "AL062026" -> "06") is NOT the same as a storm's
# rank among that season's NAMED storms, contrary to this module's own
# original claim -- verified live against the real cached Atlantic file:
# 27 of 30 window years (1996-2025) contain at least one UNNAMED system
# (unnamed tropical depressions/subtropical storms, spelled-out-number
# placeholder names like "ELEVEN"/"TWENTY-ONE") consuming a sequence number
# with no name of its own, 3 years have literal ID gaps (2017/2022/2024),
# and named storms are not always even in ID order (2021: KATE=AL10 before
# JULIAN=AL11; 2022: IAN=AL09 before HERMINE=AL10). Kalshi's own
# KXFIRSTHURRICANE/_ATLANTIC_STORM_NAMES_BY_SEASON position, and this
# module's own storms_named_so_far conditioning, are both NAME-index units
# (rank among the season's pre-assigned name list) -- comparing an ID
# sequence number against a name index silently mismatched on both
# arguments, measured to mis-rank 11 of 30 window years and shift ~10
# percentage points of probability mass between positions on real data.
_UNNAMED_STORM_NAMES = frozenset(
    {
        "UNNAMED",
        "ONE",
        "TWO",
        "THREE",
        "FOUR",
        "FIVE",
        "SIX",
        "SEVEN",
        "EIGHT",
        "NINE",
        "TEN",
        "ELEVEN",
        "TWELVE",
        "THIRTEEN",
        "FOURTEEN",
        "FIFTEEN",
        "SIXTEEN",
        "SEVENTEEN",
        "EIGHTEEN",
        "NINETEEN",
        "TWENTY",
        "TWENTY-ONE",
        "TWENTY-TWO",
        "TWENTY-THREE",
        "TWENTY-FOUR",
        "TWENTY-FIVE",
        "TWENTY-SIX",
        "TWENTY-SEVEN",
        "TWENTY-EIGHT",
        "TWENTY-NINE",
        "THIRTY",
    }
)


def _named_storms_in_naming_order(storms: list[dict], year: int) -> list[dict]:
    """Returns `year`'s storms that received a real NHC name (excludes
    UNNAMED/spelled-out-number placeholder systems -- see
    _UNNAMED_STORM_NAMES's own comment), ordered ALPHABETICALLY by name.

    Opus-review-caught (2026-08-07, MEDIUM), 2nd round: an earlier version
    of this function sorted by HURDAT2 storm-ID sequence number instead,
    on the claimed (and false) premise that ID order always matches real
    NHC name-assignment order once UNNAMED systems are excluded. Verified
    against the real cached Atlantic file: named storms are NOT always
    even in ID order -- HURDAT2 IDs are assigned by post-season reanalyzed
    genesis order, while NHC names are assigned in real time, and the two
    genuinely diverge in at least 6 of the last 30 years (2007, 2012, 2019,
    2021 KATE/JULIAN, 2022 IAN/HERMINE, 2023 GERT/EMILY/FRANKLIN).
    Alphabetical name order is the actual invariant -- NHC's whole naming
    convention IS strict alphabetical assignment within a season -- and
    sorting by name string reproduces the real list exactly in every one
    of those divergent years (spot-checked live). Not a proxy or a
    heuristic: this is definitionally what "naming order" means.

    Known, accepted limitation: this does NOT handle the rare Greek-
    letter/WMO-supplementary-name overflow for a >21-storm season (2020
    used Alpha/Beta/Gamma/... after exhausting the regular 21-name list;
    "ALPHA" sorts alphabetically before "ARTHUR", which is wrong for real
    assignment order) -- immaterial for this model's real use (KXFIRSTHURRICANE
    only ever asks about the first 21 names; the first hurricane of a
    season falling on an overflow name at all is a vanishingly rare edge
    case, and _parse_storm_order_condition already fails closed for any
    name outside the known 21)."""
    season = [
        s for s in storms if s["year"] == year and s["name"] not in _UNNAMED_STORM_NAMES
    ]
    return sorted(season, key=lambda s: s["name"])


def first_hurricane_position(
    storms: list[dict], year: int, kt: int = NEXT_EVENT_THRESHOLDS_KT["hurricane"]
) -> int | None:
    """Returns the 1-indexed NAME-index position (rank among `year`'s real
    NAMED storms only, in naming order -- see _named_storms_in_naming_
    order's own docstring for why this is NOT simply the HURDAT2 storm-ID
    sequence number) of WHICHEVER storm that year first reached kt
    strength, by date -- NOT necessarily the storm that formed earliest as
    a tropical storm. A later-named storm can intensify to hurricane
    strength before an earlier-named storm does (naming order tracks
    tropical-storm formation date, not hurricane-attainment date); this
    function answers "which name will the market actually resolve Yes for"
    (the hurricane-attainment race), not "which name formed first" (the
    naming race).

    Ties (two+ storms reaching kt on the same calendar day -- threshold_day
    is day-resolution only, see parse_hurdat2's own docstring) are broken by
    lowest name-index position: a defensible deterministic proxy for
    Kalshi's real "Source Agency's official advisory ordering" tiebreak
    (unavailable at this data's day-level resolution) -- a rare edge case,
    not the common path.

    `storms` already filtered to one basin (via load_basin_storms). Returns
    None if no NAMED storm that year ever reached kt.

    Same guard as first_occurrence_day's own docstring explains: kt must be
    one of the thresholds parse_hurdat2 actually tracks in threshold_day --
    `dict.get` on an untracked kt silently returns None for every storm
    (indistinguishable from "no storm reached it"), producing a confidently
    wrong None instead of a loud failure."""
    if kt not in _KNOWN_THRESHOLD_KT:
        raise ValueError(
            f"first_hurricane_position: kt={kt} is not tracked by "
            f"parse_hurdat2's threshold_day (known: {sorted(_KNOWN_THRESHOLD_KT)})"
        )
    named_in_order = _named_storms_in_naming_order(storms, year)
    candidates: list[tuple[tuple[int, int], int]] = []
    for position, s in enumerate(named_in_order, start=1):
        day = s["threshold_day"].get(kt)
        if day is None:
            continue
        candidates.append((day, position))
    if not candidates:
        return None
    _, position = min(candidates)
    return position


def first_hurricane_position_outcomes(
    storms: list[dict],
    target_position: int,
    storms_named_so_far: int,
    *,
    kt: int = NEXT_EVENT_THRESHOLDS_KT["hurricane"],
    window_years: int = HISTORY_WINDOW_YEARS,
    end_year: int | None = None,
) -> list[bool]:
    """Empirical outcomes ("was `target_position` the position of the first
    storm to reach kt strength") for the most recent `window_years` COMPLETE
    historical calendar seasons -- same explicit calendar-range iteration
    season_end_total_distribution/next_event_outcomes both use, for the same
    reason (a year with zero qualifying storms must still contribute a real
    False, not be silently dropped).

    Conditioned on `storms_named_so_far` (M): only years where the
    historical first-hurricane-position is None (no hurricane at all that
    year) or > M are "eligible" -- years where, like the current season
    after M names have already been used with none of them reaching
    hurricane strength, the first hurricane could still plausibly be
    pending. Mirrors next_event_outcomes' as_of_month_day eligibility filter
    exactly, with position standing in for calendar date as the "how far
    into the season" scalar. Pass storms_named_so_far=0 for the fully
    unconditional distribution (every window year is eligible, since
    position > 0 is true for every real position and None always passes)."""
    if end_year is None:
        end_year = datetime.now(UTC).date().year - 1
    window = range(end_year - window_years + 1, end_year + 1)
    outcomes: list[bool] = []
    for y in window:
        position = first_hurricane_position(storms, y, kt)
        eligible = position is None or position > storms_named_so_far
        if not eligible:
            continue
        outcomes.append(position == target_position)
    return outcomes


def bootstrap_ci_next_event(outcomes: list[bool], n: int = 500) -> tuple[float, float]:
    """Mirrors bootstrap_ci's exact resampling shape: n resamples-with-
    replacement of `outcomes`, each resample's True-fraction, sorted, 5th/95th
    percentile returned, clamped to [0.01, 0.99] -- same clamp
    next_event_probability itself already applies, and for the same reason:
    without it, a unanimous outcome set (very common here -- e.g. every
    recent Atlantic season had a hurricane by mid-September) produces a
    degenerate exact (1.0, 1.0)/(0.0, 0.0) CI. Opus-review-caught
    (2026-08-07): that degenerate CI, not the point estimate, is what
    downstream Kelly sizing keys off when ci_high<=ci_low -- unclamped, it
    silently forced `kelly_fraction(1.0, price) == 0.0` for the model's
    highest-confidence signals, blocking every real order AND (since shadow
    logging goes through the same size-then-log validator) permanently
    freezing tracker.count_settled_hurricane_next_event_predictions() at 0,
    so the 20-sample graduation gate could never open. Returns (0.0, 1.0)
    if fewer than 15 outcomes are available (too few to trust a CI) -- same
    threshold as bootstrap_ci. In unconditional mode `outcomes` always has
    exactly `window_years` (30) entries, so this floor is only reachable in
    conditional mode; opus-review-caught (2026-08-07) that this is NOT a
    late-season-only concern the way the docstring originally claimed --
    measured against real Atlantic data, the eligible set already drops
    below 15 by roughly Aug 1 (the start of peak season), not late in it."""
    if len(outcomes) < 15:
        return (0.0, 1.0)
    k = len(outcomes)
    boot = sorted(sum(random.choices(outcomes, k=k)) / k for _ in range(n))
    lo, hi = boot[min(int(n * 0.05), n - 1)], boot[min(int(n * 0.95), n - 1)]
    return (max(0.01, min(0.99, lo)), max(0.01, min(0.99, hi)))
