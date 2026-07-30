"""nws_afd.py — NWS Area Forecast Discussion (AFD) fetch/parse.

backlog.txt "NWS AFD (AREA FORECAST DISCUSSION) PARSING" — infra-only pass.
Fetches and returns the WFO's current narrative forecast-reasoning text for
a city. Confidence/directional-lean extraction is deliberately NOT
implemented here: the free-form prose ("about 5 to 10 degrees lower than
climo") isn't consistent enough across WFOs for a regex to score reliably,
and this project has no LLM SDK/API key configured yet. That scoring step
is a separate follow-up once one exists — see backlog.txt's "When to
revisit."

Also builds CITY_WFO_OFFICE, backlog.txt's "registry #9" (city -> WFO id),
which weather_markets.city_registry_report() consumes as a completeness
check and the deferred CLI-report settlement fetch (backlog.txt "DATA-DRIVEN
SIGMA ... CLI-REPORT SETTLEMENT FETCH") can reuse once it's picked up.

Fetch mechanism mirrors mos.py's _fetch_nbp_percentiles (same IEM AFOS
text-bulletin mirror, same <pre class="afos-pre"> extraction, same
retry-on-5xx session config) — AFD uses a WFO-office PIL (AFD<office>)
instead of NBP's station-based one.

WFO section-naming reality check (opus review, 2026-07-30, live-verified):
not every WFO's AFD has a single ".DISCUSSION..." block, and it isn't even
consistent per-office day to day — it depends on which sections that
shift's forecaster included. Live-checked all 20 offices the same day:
  - 8 offices (OKX/NYC, LOT/Chicago, BOX/Boston, LWX/Washington, PHI/
    Philadelphia, MPX/Minneapolis, HGX/Houston, VEF/LasVegas) plus TBW
    (St. Petersburg): plain ".DISCUSSION..." — matches even a naive
    bare-header regex.
  - BOU (Denver): ".DISCUSSION /Through Wednesday/..." — same section
    name, with a bracketed time-range qualifier on the header line. A
    match-only-bare-".DISCUSSION..." regex silently misses this (real
    bug, caught by opus review — the qualifier tolerance below fixes it).
  - LOX (LA), SEW (Seattle): ".SYNOPSIS...", ".SHORT TERM...",
    ".LONG TERM..." — no ".DISCUSSION" section at all.
  - OUN (Oklahoma City): ".NEAR TERM...", ".SHORT TERM...", ".LONG TERM...".
  - The remaining 7 (MFL/Miami, FWD/Dallas, PSR/Phoenix, FFC/Atlanta,
    EWX/Austin+SanAntonio, MTR/SanFrancisco, LIX/NewOrleans): ".SHORT
    TERM..."/".LONG TERM..." only — critically, several of these (PSR
    included) use a bracketed qualifier on THOSE headers too (e.g. PSR's
    ".SHORT TERM /TODAY THROUGH FRIDAY/...") -- an earlier, qualifier-
    intolerant verification pass on this same data mistakenly concluded
    PSR had no narrative section at all; the qualifier-tolerant regex
    below (applied uniformly to every section name, not just DISCUSSION)
    corrects that. With it, all 20 offices produced at least one
    narrative section on this live check — but a bulletin with truly none
    of the 5 known section names (further format drift, or an office this
    project hasn't seen yet) is still handled: fetch_afd_discussion()
    returns None rather than falling back to .KEY MESSAGES, which is a
    terse bullet summary, not the same kind of forecaster-reasoning prose
    — silently substituting it would change what this function returns
    without documenting it.
So this fetches whichever of the known narrative sections the current
bulletin actually contains (possibly none), concatenated in the canonical
order NWS uses them, rather than assuming exactly one always exists.
"""

from __future__ import annotations

import html as _html
import logging
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from forecast_cache import ForecastCache

_log = logging.getLogger(__name__)

# Verified live 2026-07-30: queried api.weather.gov/points/{lat},{lon} for
# every weather_markets.CITY_COORDS city (the `gridId` field, confirmed
# identical to `cwa` in every response) — then cross-checked each resulting
# AFD<office> PIL actually resolves to a real bulletin on IEM's afos mirror
# (200 + a real <pre class="afos-pre"> block, not the "no product found"
# service-notice page) for all 20 distinct offices. Same
# verify-live-not-assume standard as weather_markets._CITY_METAR_STATION.
# Re-verified by tests/test_nws_afd.py::TestCityWfoOffice (offline,
# structural) and, when run with `-m integration`, against the live API.
# Static, not derived at call-time: a city's WFO essentially never changes,
# and deriving it live on every use would add a network dependency (and a
# second call to an endpoint nws.py's own _get_gridpoint already caches)
# for a value that's effectively constant.
CITY_WFO_OFFICE: dict[str, str] = {
    "NYC": "OKX",
    "Chicago": "LOT",
    "LA": "LOX",
    "Miami": "MFL",
    "Boston": "BOX",
    "Dallas": "FWD",
    "Phoenix": "PSR",
    "Seattle": "SEW",
    "Denver": "BOU",
    "Atlanta": "FFC",
    "Austin": "EWX",
    "Washington": "LWX",
    "Philadelphia": "PHI",
    "OklahomaCity": "OUN",
    "SanFrancisco": "MTR",
    "Minneapolis": "MPX",
    "Houston": "HGX",
    "SanAntonio": "EWX",  # shares Austin's office (San Antonio/Austin WFO)
    "LasVegas": "VEF",
    "NewOrleans": "LIX",
    "StPetersburg": "TBW",
}

_AFD_URL = "https://mesonet.agron.iastate.edu/wx/afos/p.php"

# 1 hour, matches mos.py's _NBP_CACHE_TTL. AFDs are typically issued ~2-4x/day
# (more often near active weather) so this is conservative, not lossy — the
# point is to avoid re-fetching every scan cycle, not to catch every update.
# Forward-looking today: the only current caller (cmd_afd, a one-shot CLI
# command) never issues a second call within one process, so the TTL/
# per-office dedup this buys doesn't fire in practice yet — it matters once
# this is called repeatedly from a longer-running process (cron/watch).
_AFD_CACHE_TTL = 3600
_AFD_CACHE: ForecastCache[str | None] = ForecastCache(
    ttl_secs=_AFD_CACHE_TTL, max_size=25
)

_AFD_PRE_RE = re.compile(r'<pre class="afos-pre">(.*?)</pre>', re.S)

# Narrative sections that carry a forecaster's own reasoning/confidence
# language, in the canonical order NWS AFDs use them when more than one is
# present (SYNOPSIS is the big-picture setup; NEAR/SHORT/LONG TERM are
# time-scoped detail; DISCUSSION is the single-block form some offices use
# instead of splitting by time range). Deliberately excludes .KEY MESSAGES —
# a terse bullet-point summary, not the same kind of prose reasoning.
_AFD_NARRATIVE_SECTIONS = (
    "SYNOPSIS",
    "NEAR TERM",
    "SHORT TERM",
    "LONG TERM",
    "DISCUSSION",
)


def _section_header_re(name: str) -> re.Pattern[str]:
    """Build a header-matching regex for one AFD section name (matches just
    the header line, not its body).

    `[^\\n]*?` tolerates a bracketed qualifier on the same header line, e.g.
    ".DISCUSSION /Through Wednesday/..." (confirmed live on BOU/Denver —
    matching only ".NAME..." missed this silently; real bug caught by
    opus review 2026-07-30). Anchored at line-start (re.M) so the header
    name can't accidentally match inside ordinary sentence prose elsewhere
    in the bulletin.

    Known cosmetic side effect of the non-greedy `[^\\n]*?`: it stops at
    the FIRST "..." on the header line, so for headers where the
    forecaster's issuance timestamp comes right after the section name
    (e.g. LOX's ".SYNOPSIS...29/736 PM.") that timestamp becomes the first
    line of the extracted body instead of being consumed as part of the
    header. Confirmed live on LOX/VEF (opus follow-up review, 2026-07-30).
    Harmless noise for the CLI display; worth revisiting only if/when an
    LLM scorer consumes this text and the leading timestamp line turns out
    to matter.
    """
    return re.compile(rf"^\.{re.escape(name)}[^\n]*?\.\.\.", re.M)


_AFD_SECTION_HEADER_RES: dict[str, re.Pattern[str]] = {
    name: _section_header_re(name) for name in _AFD_NARRATIVE_SECTIONS
}


def _section_body(text: str, name: str) -> str | None:
    """Return one section's body text, or None if the section (or a real
    closing boundary for it) isn't present.

    A section's body ends at whichever comes first: the next "&&"
    terminator, or the START of the next _AFD_NARRATIVE_SECTIONS header
    (any OTHER tracked name) -- NOT just the next "&&" alone. Some offices
    (confirmed live 2026-07-30 on LOX/SEW, reproduced across 5 consecutive
    days of LOX issuances -- this is a house style, not a one-off) put two
    narrative sections back-to-back with no "&&" between them at all
    (".SHORT TERM...body...\\n.LONG TERM...body...\\n&&"). Relying on "&&"
    alone let SHORT TERM's capture swallow LONG TERM's header AND body,
    then LONG TERM's own regex re-matched and duplicated that same content
    -- a real, currently-reproducing bug caught by a follow-up opus review
    (the first version of this fix's own test fixture had an extra "&&"
    inserted that isn't in the real bulletin, which is exactly why the
    test didn't catch it).

    Deliberately does NOT stop at nested, non-tracked sub-headers like
    ".KEY MESSAGE N..." inside .DISCUSSION -- those aren't one of this
    project's 5 tracked names, so a real .DISCUSSION block containing
    multiple nested KEY MESSAGE sub-headers is still captured whole, up
    to its own real "&&" (see test_extracts_bare_discussion_section).
    If genuinely no boundary exists at all (no "&&" and no other tracked
    header after this one) the section is treated as unparseable and
    skipped, rather than capturing to end-of-bulletin (which could pull
    in an unrelated signature/footer block).
    """
    header_match = _AFD_SECTION_HEADER_RES[name].search(text)
    if not header_match:
        return None
    start = header_match.end()

    and_pos = text.find("&&", start)
    other_header_positions = [
        m.start()
        for other in _AFD_NARRATIVE_SECTIONS
        if other != name
        for m in [_AFD_SECTION_HEADER_RES[other].search(text, start)]
        if m
    ]
    boundaries = ([and_pos] if and_pos != -1 else []) + other_header_positions
    if not boundaries:
        return None
    end = min(boundaries)

    body = text[start:end].strip()
    return body or None


_session = requests.Session()
# Matches mos.py's IEM-mirror session: retry once on the 5xx codes IEM's
# proxy is actually observed to return, rather than negative-caching a
# transient blip for a full TTL window.
_session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=1, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504]
        )
    ),
)


def fetch_afd_discussion(city: str) -> str | None:
    """Fetch and return the current AFD's narrative reasoning text for a city.

    Concatenates whichever of _AFD_NARRATIVE_SECTIONS the current bulletin
    actually contains (canonical order), since offices — and even the same
    office on different days — don't consistently use a single
    ".DISCUSSION" block (see module docstring). Returns None when: the city
    has no WFO mapping, the HTTP fetch fails, the response is IEM's "no
    product found" service-notice page rather than a real bulletin, or the
    bulletin contains none of the known narrative sections (format drift,
    or a hypothetical bulletin with only non-narrative sections like
    .KEY MESSAGES/.FIRE WEATHER/.CLIMATE — not observed live across any of
    the 20 offices this project currently uses, see module docstring).

    Cached per WFO office (not per city) for _AFD_CACHE_TTL seconds — cities
    sharing an office (Austin/SanAntonio both use EWX) share one fetch.
    """
    office = CITY_WFO_OFFICE.get(city)
    if not office:
        return None

    # get_with_ts's `hit` flag (not plain get()'s return value) distinguishes
    # a fresh negative-cache entry (fetch failed/no section last time, still
    # within TTL — hit=True, value=None) from a genuine cache miss (hit=
    # False) -- plain get() can't tell those apart since both read as None.
    cached_value, hit, _ts = _AFD_CACHE.get_with_ts(office)
    if hit:
        return cached_value

    pil = f"AFD{office}"
    try:
        resp = _session.get(_AFD_URL, params={"pil": pil}, timeout=(5, 10))
        resp.raise_for_status()
        page_html = resp.text
    except Exception as exc:
        _log.warning("fetch_afd_discussion(%s): fetch failed: %s", city, exc)
        _AFD_CACHE.set(office, None)
        return None

    pre_match = _AFD_PRE_RE.search(page_html)
    if not pre_match:
        # No <pre class="afos-pre"> block == IEM's "Service Notice" error
        # page (unknown PIL / no product found), not a real bulletin --
        # same convention as mos.py's _fetch_nbp_percentiles.
        _log.warning(
            "fetch_afd_discussion(%s): no afos-pre block for AFD%s "
            "(IEM service-notice page, not a real bulletin)",
            city,
            office,
        )
        _AFD_CACHE.set(office, None)
        return None

    text = _html.unescape(pre_match.group(1))
    parts = [
        body
        for name in _AFD_NARRATIVE_SECTIONS
        if (body := _section_body(text, name)) is not None
    ]

    if not parts:
        # A real, fetched bulletin with none of the known narrative
        # sections is worth a WARNING (not DEBUG): this is exactly the
        # class of "ran successfully but silently produced nothing useful"
        # gap this project's own convention (mos.py's _parse_nbp_bulletin,
        # near_settlement_log) treats as loud, not quiet — a DEBUG-level
        # message here is invisible by default (main.py disables DEBUG
        # logging unless --debug is passed), which is exactly how an
        # 11-of-20-office miss shipped unnoticed on the first pass of this
        # feature (opus review, 2026-07-30).
        _log.warning(
            "fetch_afd_discussion(%s): AFD%s bulletin has none of the known "
            "narrative sections %s -- may be a format this office doesn't "
            "use today, or real format drift",
            city,
            office,
            _AFD_NARRATIVE_SECTIONS,
        )
        result = None
    else:
        result = "\n\n".join(parts)

    _AFD_CACHE.set(office, result)
    return result
