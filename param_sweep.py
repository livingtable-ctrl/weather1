"""param_sweep.py — Auto-test threshold ranges against historical outcomes.

Usage:
    py param_sweep.py
    or from main.py: py main.py sweep
"""

from __future__ import annotations

import json
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

    `trades` is a list of paper trade dicts with keys: net_edge, won (bool),
    outcome ('yes'/'no').  Returns a list of result dicts sorted by win_rate desc.

    Edge field priority: "edge" (legacy) → "net_edge" (current) → "expected_value" → 0.
    Note: net_edge is stored on the 0.15–0.87 scale (probability difference after spread
    adjustment), so thresholds should be calibrated against that range.
    """
    results = []

    for val in values:
        filtered = []
        for t in trades:
            # net_edge is the field paper.py writes; "edge"/"expected_value" are kept
            # for backwards compatibility with any hand-crafted test fixtures.
            edge = (
                t.get("edge")
                if t.get("edge") is not None
                else t.get("net_edge", t.get("expected_value", 0))
            )
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

        # Use the explicit won flag — don't fall back to outcome=='yes' because
        # that incorrectly counts NO bets that lost (outcome='yes', won=False) as wins.
        wins = sum(1 for t in filtered if t.get("won") is True)
        avg_edge = (
            sum(
                float(
                    (
                        t.get("edge")
                        if t.get("edge") is not None
                        else t.get("net_edge", t.get("expected_value", 0))
                    )
                    or 0  # outer `or 0` strips any None before float() sees it
                )
                for t in filtered
            )
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
        key=lambda r: (r["win_rate"] or 0.0),  # type: ignore[arg-type,return-value]
        reverse=True,
    )
    return results


def load_swept_min_edge(min_trades: int = 10) -> float | None:
    """
    Read data/param_sweep_results.json and return the PAPER_MIN_EDGE value with
    the best win-rate that has at least `min_trades` settled trades.
    Returns None when the file is absent or no threshold meets the sample floor.
    """
    try:
        out_path = Path(__file__).parent / "data" / "param_sweep_results.json"
        if not out_path.exists():
            return None
        data = json.loads(out_path.read_text())
        results = data.get("PAPER_MIN_EDGE", [])
        valid = [
            r
            for r in results
            if r.get("trades", 0) >= min_trades and r.get("win_rate") is not None
        ]
        if not valid:
            return None
        best = max(valid, key=lambda r: float(r["win_rate"]))
        val = float(best["value"])
        if 0.03 <= val <= 0.15:
            return val
    except Exception as _e:
        _log.warning(
            "load_swept_min_edge: failed to read param_sweep_results.json: %s", _e
        )
    return None


def run_sweep(trades: list[dict] | None = None) -> dict:
    """
    Run a sweep across key parameters using historical paper trades.
    Uses a 70/30 temporal split: optimises on the first 70%, validates on the last 30%.
    Results are only saved when the best threshold improves win rate over the unfiltered
    holdout baseline — preventing pure in-sample overfit from polluting live parameters.
    """
    if trades is None:
        try:
            from paper import load_paper_trades

            trades = load_paper_trades()
        except Exception as exc:
            _log.warning("param_sweep: could not load paper trades: %s", exc)
            trades = []

    if not trades:
        return {"error": "No historical trades to sweep against."}

    # Only sweep settled trades (we know outcomes)
    settled = [t for t in trades if t.get("outcome") in ("yes", "no") or "won" in t]

    if len(settled) < 20:
        return {"error": "Too few settled trades to split (need ≥20)."}

    # 70/30 temporal split — preserve chronological order
    split_idx = int(len(settled) * 0.70)
    train_trades = settled[:split_idx]
    val_trades = settled[split_idx:]

    # Thresholds are on the net_edge scale (0.15–0.87 range in current trades).
    # load_swept_min_edge clamps its return to [0.03, 0.15], so auto-tuned values
    # fed back into PAPER_MIN_EDGE config stay in the safe range regardless of
    # which threshold wins here.
    params_to_sweep = {
        "PAPER_MIN_EDGE": [0.15, 0.20, 0.25, 0.30, 0.35, 0.40],
        "MED_EDGE": [0.15, 0.20, 0.25, 0.30, 0.35],
    }

    all_results = {}
    should_save = True

    for param, values in params_to_sweep.items():
        train_results = sweep_parameter(param, values, train_trades)
        all_results[param] = train_results

        print(f"\n  Sweep: {param}")
        print(f"  {'Value':>8}  {'Trades':>6}  {'Win Rate':>10}  {'Avg Edge':>10}")
        print("  " + "─" * 42)
        for r in train_results:
            wr = f"{r['win_rate']:.1%}" if r["win_rate"] is not None else "N/A"
            ae = f"{r['avg_edge']:.3f}" if r["avg_edge"] is not None else "N/A"
            print(f"  {r['value']:>8.3f}  {r['trades']:>6}  {wr:>10}  {ae:>10}")

        # Validate best threshold on holdout
        valid_train = [r for r in train_results if r.get("win_rate") is not None]
        if not valid_train or not val_trades:
            continue
        best_val = max(valid_train, key=lambda r: float(r["win_rate"]))

        val_results = sweep_parameter(param, [best_val["value"]], val_trades)
        val_wr = val_results[0].get("win_rate") if val_results else None

        # Holdout baseline: unfiltered win rate on validation set
        baseline_results = sweep_parameter(param, [0.0], val_trades)
        baseline_wr = baseline_results[0].get("win_rate") if baseline_results else None

        if val_wr is not None and baseline_wr is not None:
            print(
                f"  Holdout win rate at {best_val['value']:.3f}: {val_wr:.1%}  "
                f"(baseline: {baseline_wr:.1%})"
            )
            if val_wr < baseline_wr:
                _log.warning(
                    "param_sweep: %s best threshold %.3f does not improve holdout "
                    "(%.1f%% vs baseline %.1f%%) — skipping save",
                    param,
                    best_val["value"],
                    val_wr * 100,
                    baseline_wr * 100,
                )
                should_save = False

    # Save results only when every param cleared the holdout bar
    if should_save:
        out_path = Path(__file__).parent / "data" / "param_sweep_results.json"
        import safe_io

        try:
            safe_io.atomic_write_json(all_results, out_path)
            _log.info("param_sweep: results saved to %s", out_path)
        except Exception as exc:
            _log.warning("param_sweep: could not save results: %s", exc)
    else:
        _log.warning("param_sweep: results NOT saved — holdout validation failed")

    return all_results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_sweep()
