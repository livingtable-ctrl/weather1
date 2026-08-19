"""
Pass 14 (Performance) reproduction.

Demonstrates that paper.check_paper_position_exits() issues ONE
client.get_market(ticker) REST call PER open paper position (sequential,
unbatched) instead of a single batched client.get_markets(tickers=...) call
-- the exact anti-pattern commit 709b0043 fixed for web_app.py's /api/trades
route (batch-fetch live quotes for all open positions).

Safety: this script never touches real data files. paper.get_open_trades,
positions.PaperPositionStore.save_peak, positions.check_stop_losses, and
positions.check_breakeven_stops are all monkeypatched at the module level
before paper.check_paper_position_exits() is called, so no disk I/O against
data/paper_trades.json (real or otherwise) ever occurs. Run directly with
`python audit/reproductions/repro_n1_paper_position_exits.py` -- no pytest
fixtures, no conftest.py isolation needed because nothing real is touched.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paper  # noqa: E402

N_OPEN_POSITIONS = 12

fake_open_trades = [
    {
        "id": i,
        "ticker": f"KXHIGHNY-26AUG{i:02d}-T80",
        "side": "yes",
        "entry_price": 0.50,
        "quantity": 10,
        "cost": 5.0,
        "peak_profit_pct": 0.0,
    }
    for i in range(N_OPEN_POSITIONS)
]

get_market_calls: list[str] = []


class FakeClient:
    def get_market(self, ticker: str) -> dict:
        get_market_calls.append(ticker)
        # Neutral quote: no stop-loss/breakeven fires, isolates the call-count
        # measurement from exit-logic side effects.
        return {"ticker": ticker, "yes_bid": 0.50, "yes_ask": 0.52}

    def get_markets(self, **params) -> list[dict]:
        raise AssertionError(
            "get_markets(tickers=...) was never called -- confirms no "
            "batched path exists in check_paper_position_exits"
        )


# Monkeypatch every dependency check_paper_position_exits touches besides
# client.get_market, so this repro is a pure call-count measurement with
# zero real file I/O.
paper.get_open_trades = lambda: list(fake_open_trades)


class FakeStore:
    def save_peak(self, *a, **k):
        pass

    def exit(self, *a, **k):
        raise AssertionError("exit() should not be called -- neutral quotes")


paper.PaperPositionStore = lambda: FakeStore()
paper.check_stop_losses = lambda positions, prices: []
paper.check_breakeven_stops = lambda positions, prices: []
paper._shared_update_peak_profits = lambda positions, prices, save_fn: None

result = paper.check_paper_position_exits(FakeClient())

print(f"open positions:            {N_OPEN_POSITIONS}")
print(f"client.get_market() calls: {len(get_market_calls)}")
print(f"client.get_markets() calls: 0 (batched path never invoked)")
print(f"closed (expected 0):        {len(result)}")

assert len(get_market_calls) == N_OPEN_POSITIONS, (
    f"expected exactly {N_OPEN_POSITIONS} sequential get_market() calls "
    f"(one per open position), got {len(get_market_calls)}"
)
print(
    "\nCONFIRMED: check_paper_position_exits() makes N sequential "
    "client.get_market() calls for N open positions -- no batching, no "
    "WS-cache reuse (unlike order_executor._get_current_book)."
)
