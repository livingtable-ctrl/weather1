"""
Shared TypedDicts for the Kalshi weather markets bot.
Import these instead of using plain `dict` for better editor support.
"""

from __future__ import annotations

from typing import TypedDict


class ForecastResult(TypedDict, total=False):
    date: str
    city: str
    high_f: float
    low_f: float | None
    precip_in: float
    models_used: int
    high_range: tuple[float, float]
    low_range: tuple[float, float]


class MarketCondition(TypedDict, total=False):
    type: str  # "above" | "below" | "between" | "precip_any" | "precip_above"
    threshold: float  # for above/below
    lower: float  # for between
    upper: float  # for between
    amount: float  # for precip_above


class AnalysisResult(TypedDict, total=False):
    condition: MarketCondition
    forecast_prob: float
    market_prob: float
    edge: float
    net_edge: float
    kelly: float
    fee_adjusted_kelly: float
    recommended_side: str
    signal: str
    ci_low: float
    ci_high: float
    ci_width: float
    method: str
    n_members: int
    ensemble_stats: dict
    days_out: int


class MarketDict(TypedDict, total=False):
    ticker: str
    series_ticker: str
    title: str
    subtitle: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    volume: int
    open_interest: int
    close_time: str
    status: str
    result: str
    # Enriched fields added by enrich_with_forecast
    _city: str | None
    _date: object  # date | None
    _hour: int | None
    _forecast: ForecastResult | None
