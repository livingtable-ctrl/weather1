"""param_sweep.py — Auto-test threshold ranges against historical outcomes.

Usage:
    py param_sweep.py
    or from main.py: py main.py sweep
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)


def sweep_parameter(
    param_name: str,
    values: list[float],
    trades: list[dict],
) -> list[dict]:
    """
    For each value in `values`, simulate applying that parameter value
    to the historical trade list and compute win rate, trade count, avg edge.

    `trades` is a list of paper trade dicts with keys: edge, won (bool or 0/1), kelly_fraction.
    Returns a list of result dicts sorted by win_rate desc.
    """
    results = []

    for val in values:
        filtered = []
        for t in trades:
            edge = t.get("edge", t.get("expected_value", 0))
            if edge is None:
                continue
            if param_name == "PAPER_MIN_EDGE" and float(edge) < val:
                continue
            if param_name == "MED_EDGE" and float(edge) < val:
                continue
            filtered.append(t)

        total = len(filtered)
        if total == 0:
            results.append(
                {
                    "param": param_name,
                    "value": val,
                    "trades": 0,
                    "win_rate": None,
                    "avg_edge": None,
                }
            )
            continue

        wins = sum(1 for t in filtered if t.get("won") or t.get("outcome") == "yes")
        avg_edge = (
            sum(float(t.get("edge", t.get("expected_value", 0)) or 0) for t in filtered)
            / total
        )

        results.append(
            {
                "param": param_name,
                "value": val,
                "trades": total,
                "win_rate": round(wins / total, 4),
                "avg_edge": round(avg_edge, 4),
            }
        )

    results.sort(
        key=lambda r: float(r["win_rate"]) if r["win_rate"] is not None else -1.0,  # type: ignore[arg-type]
        reverse=True,
    )
    return results


def run_sweep(trades: list[dict] | None = None) -> dict:
    """
    Run a sweep across key parameters using historical paper trades.
    Prints results and returns a summary dict.
    """
    if trades is None:
        try:
            from paper import load_paper_trades

            trades = load_paper_trades()
        except Exception as exc:
            _log.warning(
                "param_sweep: could not load paper trades: %s", exc, exc_info=True
            )
            trades = []

    if not trades:
        return {"error": "No historical trades to sweep against."}

    # Only sweep settled trades (we know outcomes)
    settled = [t for t in trades if t.get("outcome") in ("yes", "no") or "won" in t]

    params_to_sweep = {
        "PAPER_MIN_EDGE": [0.03, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12, 0.15],
        "MED_EDGE": [0.10, 0.12, 0.15, 0.17, 0.20],
    }

    all_results = {}
    for param, values in params_to_sweep.items():
        results = sweep_parameter(param, values, settled)
        all_results[param] = results

        print(f"\n  Sweep: {param}")
        print(f"  {'Value':>8}  {'Trades':>6}  {'Win Rate':>10}  {'Avg Edge':>10}")
        print("  " + "─" * 42)
        for r in results:
            wr = f"{r['win_rate']:.1%}" if r["win_rate"] is not None else "N/A"
            ae = f"{r['avg_edge']:.3f}" if r["avg_edge"] is not None else "N/A"
            print(f"  {r['value']:>8.3f}  {r['trades']:>6}  {wr:>10}  {ae:>10}")

    # Save results
    out_path = Path(__file__).parent / "data" / "param_sweep_results.json"
    import safe_io

    try:
        safe_io.atomic_write_json(all_results, out_path)
        _log.info("param_sweep: results saved to %s", out_path)
    except Exception as exc:
        _log.warning("param_sweep: could not save results: %s", exc)

    return all_results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_sweep()
