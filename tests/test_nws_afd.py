"""Tests for nws_afd.py -- backlog.txt "NWS AFD (AREA FORECAST DISCUSSION)
PARSING," infra-only pass (fetch + narrative-section extraction;
confidence/lean scoring deliberately not built -- needs an LLM, no SDK/key
configured in this project yet).

Fetch mechanism mirrors mos.py's NBP fetch (test_mos_nbp.py) -- same IEM
AFOS text-mirror endpoint, same <pre class="afos-pre"> extraction, same
requests.Session mocking convention.

Section-extraction fixtures below are trimmed real bulletins, chosen and
live-verified 2026-07-30 (2 rounds of opus review + follow-up
self-verification) to cover the real structural variety across WFOs: a
bare ".DISCUSSION...", a bracketed-qualifier ".DISCUSSION /Through
Wednesday/..." (BOU/Denver -- the real H1 bug this pass fixed), and a
SYNOPSIS+SHORT TERM+LONG TERM multi-section bulletin with a qualifier on
the SHORT TERM/LONG TERM headers specifically -- picked because an
earlier, qualifier-intolerant verification pass mistakenly concluded some
of these offices (PSR in particular) had no narrative section at all, and
because the same fixture (with no "&&" between SHORT TERM and LONG TERM,
matching the real bulletin) is also the regression guard for a second
real bug: one section's capture swallowing the next section's header and
body whole when there's no "&&" between them.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import nws_afd

# Real AFDOKX bulletin (NYC/OKX WFO), fetched live 2026-07-30. Trimmed to
# the .DISCUSSION section plus the surrounding sections (.WHAT HAS CHANGED,
# .KEY MESSAGES before it; .AVIATION, .MARINE after it) needed to exercise
# the "&&"-boundary regex faithfully -- a bulletin with only one "&&" left
# in the text can't distinguish a correct non-greedy match from an
# incorrect greedy one, since both would stop at the same (only remaining)
# terminator.
_RAW_BULLETIN_OKX = """883
FXUS61 KOKX 300911
AFDOKX

Area Forecast Discussion
National Weather Service New York NY
511 AM EDT Thu Jul 30 2026

.WHAT HAS CHANGED...
Updated for 09Z TAFs.

&&

.KEY MESSAGES...
1) Slow moving low pressure will continue to produce intermittent
showers and thunderstorms today.

&&

.DISCUSSION...
.KEY MESSAGE 1...
An anomalously deep trough for late July over the Northeast
gradually weakens through tonight.

Forecast highs this afternoon are in the mid to upper 70s for most,
about 5 to 10 degrees lower than climo.

&&

.AVIATION /09Z THURSDAY THROUGH MONDAY/...
A slow moving low pressure system will linger near the area today.

&&

.MARINE...
Small craft advisory remains in effect for the outer waters.

&&
"""

# Real AFDBOU bulletin (Denver/BOU WFO), fetched live 2026-07-30. The
# ".DISCUSSION /Through Wednesday/..." header (bracketed time-range
# qualifier) is the real bug this pass fixed: the first-pass regex only
# matched bare ".DISCUSSION..." and silently missed this, so
# `py main.py afd Denver` reported nothing while this text was sitting
# right there.
_RAW_BULLETIN_BOU = """044
FXUS65 KBOU 300830
AFDBOU

Area Forecast Discussion
National Weather Service Denver/Boulder CO
230 AM MDT Thu Jul 30 2026

.KEY MESSAGES...

- Isolated showers and thunderstorms this afternoon.

&&

.DISCUSSION /Through Wednesday/...
Issued at 225 AM MDT Thu Jul 30 2026

Current radar shows ongoing isolated rain showers along the high
terrain, with gusty outflow winds up to 50 mph in the foothills.

&&

.AVIATION...
VFR conditions expected areawide.

&&
"""

# Real AFDLOX bulletin (LA/LOX WFO), fetched live 2026-07-30 and
# cross-checked against 5 consecutive days of LOX issuances. No
# ".DISCUSSION" section at all -- uses SYNOPSIS + SHORT TERM + LONG TERM
# instead. SHORT TERM's and LONG TERM's headers carry a bracketed
# qualifier ("(WED-SAT)...", "(SUN-WED)..."); SYNOPSIS's own qualifier
# ("...29/736 PM.") sits AFTER the "...", so the bare (non-qualifier-
# tolerant) regex actually still matches SYNOPSIS's header fine -- SHORT
# TERM/LONG TERM are what the qualifier tolerance is really needed for
# here. An earlier verification pass used a qualifier-intolerant regex to
# check office coverage and wrongly concluded some SHORT/LONG-TERM-only
# offices (PSR in particular) had no narrative section at all -- this
# fixture (and test_synopsis_short_long_term_fallback below) is the
# regression guard against that specific mistake recurring.
#
# CRITICALLY: there is deliberately NO "&&" between SHORT TERM and LONG
# TERM below, matching the real bulletin exactly (confirmed live, and
# confirmed this is LOX's house style across 5 consecutive issuances, not
# a one-off). An earlier version of this fixture inserted a "&&" there
# that the real bulletin doesn't have -- which is exactly what let a real
# duplication bug (SHORT TERM's capture swallowing LONG TERM's header and
# body, then LONG TERM re-matching the same content) pass a follow-up
# opus review's own re-derivation before being caught. Keeping this
# fixture byte-faithful to the source is the whole point.
_RAW_BULLETIN_LOX = """195
FXUS66 KLOX 300523
AFDLOX

Area Forecast Discussion
National Weather Service Los Angeles/Oxnard CA
1023 PM PDT Wed Jul 29 2026

.SYNOPSIS...29/736 PM.

Temperatures will become dangerously hot in many areas Friday
through the upcoming weekend.

&&

.SHORT TERM (WED-SAT)...29/1014 PM.

High temperatures today were nearly the same as yesterday.

.LONG TERM (SUN-WED)...29/1014 PM.

Warming trend continues into early next week.

&&

.AVIATION...
VFR conditions expected.

&&
"""


def _wrap_html(pre_text: str) -> str:
    return f'<html><body><pre class="afos-pre">{pre_text}</pre></body></html>'


class TestCityWfoOffice:
    def test_every_city_coords_city_has_an_entry(self):
        from weather_markets import CITY_COORDS

        missing = [c for c in CITY_COORDS if c not in nws_afd.CITY_WFO_OFFICE]
        assert missing == [], f"cities missing a WFO mapping: {missing}"

    def test_no_extra_entries_beyond_city_coords(self):
        from weather_markets import CITY_COORDS

        extra = [c for c in nws_afd.CITY_WFO_OFFICE if c not in CITY_COORDS]
        assert extra == [], f"WFO entries for cities not in CITY_COORDS: {extra}"

    def test_office_codes_are_three_uppercase_letters(self):
        for city, office in nws_afd.CITY_WFO_OFFICE.items():
            assert len(office) == 3 and office.isalpha() and office.isupper(), (
                city,
                office,
            )


class TestFetchAfdDiscussion:
    def setup_method(self):
        nws_afd._AFD_CACHE.clear()

    def test_extracts_bare_discussion_section(self):
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN_OKX)
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("NYC")

        assert result is not None
        assert "5 to 10 degrees lower than climo" in result
        assert "KEY MESSAGE 1" in result
        # Must not bleed into neighboring sections on either side.
        assert "WHAT HAS CHANGED" not in result
        assert "KEY MESSAGES..." not in result
        assert "AVIATION" not in result
        assert "MARINE" not in result

    def test_extracts_qualifier_discussion_section(self):
        """Regression guard for the real HIGH bug: a bracketed qualifier on
        the .DISCUSSION header line (BOU/Denver's real format) must not be
        silently missed."""
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN_BOU)
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("Denver")

        assert result is not None
        assert "gusty outflow winds up to 50 mph" in result
        assert "KEY MESSAGES" not in result
        assert "AVIATION" not in result

    def test_synopsis_short_long_term_fallback(self):
        """Regression guard for the real HIGH gap: offices with no
        .DISCUSSION section at all (LOX-shaped: SYNOPSIS + SHORT TERM +
        LONG TERM) must still produce a result, concatenated in canonical
        order, WITHOUT duplication. The fixture deliberately has no "&&"
        between SHORT TERM and LONG TERM (matching the real bulletin) --
        this is the regression guard for a real bug where SHORT TERM's
        capture swallowed LONG TERM's header and body whole, and LONG
        TERM's own regex then duplicated that same content (opus
        follow-up review, 2026-07-30)."""
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN_LOX)
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("LA")

        assert result is not None
        assert "dangerously hot" in result  # SYNOPSIS
        assert "nearly the same as yesterday" in result  # SHORT TERM
        assert "Warming trend continues" in result  # LONG TERM
        assert "AVIATION" not in result
        # No duplication: each section's text appears exactly once, and
        # SHORT TERM's body must not have swallowed LONG TERM's header.
        assert result.count("nearly the same as yesterday") == 1
        assert result.count("Warming trend continues") == 1
        assert "LONG TERM" not in result
        # Canonical order: SYNOPSIS before SHORT TERM before LONG TERM.
        assert result.index("dangerously hot") < result.index(
            "nearly the same as yesterday"
        )
        assert result.index("nearly the same as yesterday") < result.index(
            "Warming trend continues"
        )

    def test_no_narrative_section_returns_none(self):
        """Synthetic (not a real captured bulletin, since a live check
        2026-07-30 found all 20 currently-used offices have at least one
        narrative section) -- exercises the documented fallback for a
        bulletin with none of the 5 known section names, e.g. future
        format drift or a WFO structure not yet seen."""
        bulletin = """000
FXUS61 KZZZ 300911
AFDZZZ

Area Forecast Discussion
National Weather Service Nowhere ZZ

.KEY MESSAGES...
Nothing but a bullet summary today.

&&

.AVIATION...
VFR conditions expected.

&&

.FIRE WEATHER...
No red flag concerns.

&&
"""
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(bulletin)
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("NYC")
        assert result is None

    def test_empty_present_section_returns_none(self):
        """Regression guard for the real MEDIUM bug: a present-but-empty
        section (header immediately followed by "&&") must return None,
        not an empty string that slips past an `is None` guard."""
        bulletin = """.DISCUSSION...
&&
"""
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(bulletin)
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("NYC")
        assert result is None

    def test_section_with_no_closing_terminator_returns_none(self):
        """A .DISCUSSION section that's the last thing in the bulletin (no
        trailing "&&" before EOF, e.g. IEM trims a bulletin mid-section)
        must not hang or partially match -- the regex requires "&&" to
        close the section, so .search() correctly finds no match at all
        and the function falls through to None. Verified live 2026-07-30
        (opus follow-up review) that this doesn't hang; this test is the
        regression guard the review flagged as missing."""
        bulletin = """.DISCUSSION...
This is the last section in the bulletin, with no closing terminator.
"""
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(bulletin)
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("NYC")
        assert result is None

    def test_terminator_between_nested_sub_headers_truncates(self):
        """Documented, not "fixed": if a "&&" ever appears BETWEEN nested
        ".KEY MESSAGE N..." sub-headers inside .DISCUSSION (not observed
        live 2026-07-30 across any real bulletin checked, but not
        impossible), the section-body regex stops at that first "&&" and
        silently drops everything after it -- the same behavior as two
        genuinely separate sections. This is inherent to using "&&" as the
        sole section boundary marker (matches mos.py's own convention) and
        is deliberately not being made "smarter" here since there's no
        real bulletin evidence this shape occurs -- but it must be a
        proven, asserted behavior, not merely assumed correct."""
        bulletin = """.DISCUSSION...
.KEY MESSAGE 1...
First message body.

&&

.KEY MESSAGE 2...
Second message body -- must NOT appear in the result.

&&
"""
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(bulletin)
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("NYC")
        assert result is not None
        assert "First message body" in result
        assert "Second message body" not in result

    def test_unknown_city_returns_none_without_network_call(self):
        with patch.object(nws_afd._session, "get") as mock_get:
            result = nws_afd.fetch_afd_discussion("Nowhereville")
        assert result is None
        mock_get.assert_not_called()

    def test_service_notice_page_returns_none(self):
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = "<html><body>Service Notice</body></html>"
            mock_get.return_value.raise_for_status.return_value = None
            result = nws_afd.fetch_afd_discussion("NYC")
        assert result is None

    def test_caches_per_office_not_per_city(self):
        # Austin and SanAntonio share the EWX office -- one network call
        # should cover both, not two.
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN_LOX)
            mock_get.return_value.raise_for_status.return_value = None
            nws_afd.fetch_afd_discussion("Austin")
            nws_afd.fetch_afd_discussion("SanAntonio")
        assert mock_get.call_count == 1

    def test_ttl_cache_prevents_refetch(self):
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN_OKX)
            mock_get.return_value.raise_for_status.return_value = None
            nws_afd.fetch_afd_discussion("NYC")
            nws_afd.fetch_afd_discussion("NYC")
        assert mock_get.call_count == 1

    def test_negative_result_is_cached_not_refetched_every_call(self):
        """Regression guard for a bug caught during the ForecastCache swap
        (self-caught, not opus): ForecastCache.get() can't distinguish a
        genuine cache miss from a fresh negative-cache hit (both read as
        None), so naively porting the raw-dict "if cached is not None"
        check would have silently defeated negative caching -- every call
        after a failure would re-fetch forever instead of respecting the
        TTL. fetch_afd_discussion must use get_with_ts()'s `hit` flag."""
        with patch.object(
            nws_afd._session, "get", side_effect=Exception("read timeout")
        ) as mock_get:
            nws_afd.fetch_afd_discussion("NYC")
            nws_afd.fetch_afd_discussion("NYC")
        assert mock_get.call_count == 1

    def test_pil_built_from_office_code(self):
        with patch.object(nws_afd._session, "get") as mock_get:
            mock_get.return_value.text = _wrap_html(_RAW_BULLETIN_OKX)
            mock_get.return_value.raise_for_status.return_value = None
            nws_afd.fetch_afd_discussion("NYC")
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["pil"] == "AFDOKX"

    def test_fetch_exception_returns_none(self):
        with patch.object(
            nws_afd._session, "get", side_effect=Exception("read timeout")
        ):
            result = nws_afd.fetch_afd_discussion("NYC")
        assert result is None


@pytest.mark.integration
def test_city_wfo_office_matches_live_api():
    """Live check (run with `-m integration`, matches test_integration_live.py's
    convention) that CITY_WFO_OFFICE is still correct against
    api.weather.gov/points -- without this, the "live-verified 2026-07-30"
    claim in nws_afd.py's module comment would decay silently the moment
    any WFO boundary changes, exactly the kind of undetectable drift opus
    review (2026-07-30) flagged for the un-guarded original claim."""
    import requests

    from weather_markets import CITY_COORDS

    mismatches = []
    unreachable = []
    for city, (lat, lon, _tz) in CITY_COORDS.items():
        expected = nws_afd.CITY_WFO_OFFICE.get(city)
        try:
            resp = requests.get(
                f"https://api.weather.gov/points/{lat},{lon}",
                headers={"User-Agent": "weather1-bot (test_nws_afd integration)"},
                timeout=10,
            )
            resp.raise_for_status()
            live_office = resp.json()["properties"]["gridId"]
        except Exception as exc:
            # A single transient failure must not discard every city
            # already verified this run (opus follow-up review, 2026-07-30
            # -- an earlier version called pytest.skip() here directly,
            # aborting the whole test and losing all prior results on the
            # first flaky request). Collect and only skip if NONE of the
            # 21 cities were reachable.
            unreachable.append((city, str(exc)))
            continue
        if live_office != expected:
            mismatches.append((city, expected, live_office))

    if unreachable and len(unreachable) == len(CITY_COORDS):
        pytest.skip(f"api.weather.gov entirely unreachable: {unreachable[0]}")

    assert not mismatches, (
        f"CITY_WFO_OFFICE out of date for: {mismatches} "
        "(city, table_value, live_value)"
        + (f" -- also unreachable: {unreachable}" if unreachable else "")
    )
    if unreachable:
        pytest.fail(
            f"{len(unreachable)}/{len(CITY_COORDS)} cities unreachable "
            f"(not skipping, since {len(CITY_COORDS) - len(unreachable)} "
            f"others were successfully checked): {unreachable}"
        )
