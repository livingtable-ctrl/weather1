"""Tests for output_formatters.py -- batch-38 items L-7/L-2:
cmd_history's confusion matrix was transposed (off-diagonal fp/fn cells
swapped vs tracker.get_confusion_matrix's own definitions), and cmd_history/
cmd_pnl_attribution had zero test references."""

from __future__ import annotations

from unittest.mock import MagicMock


def _mute_all_but_confusion_matrix(monkeypatch, module, confusion_matrix):
    """Stub every cmd_history dependency to a no-op/empty value except
    get_confusion_matrix, so the printed output is isolated to just the
    confusion-matrix block."""
    monkeypatch.setattr(module, "sync_outcomes", lambda client: 0)
    monkeypatch.setattr(
        module,
        "get_history",
        lambda n: [
            {
                "ticker": "T",
                "predicted_at": "2026-08-24",
                "our_prob": 0.6,
                "market_prob": 0.5,
                "edge": 0.1,
                "settled_yes": 1,
            }
        ],
    )
    monkeypatch.setattr(module, "brier_score_rolling_with_n", lambda: (None, 0))
    monkeypatch.setattr(
        module,
        "get_profit_factor",
        lambda: {"n": 0, "profit_factor": None, "win_loss_ratio": None},
    )
    monkeypatch.setattr(module, "get_market_calibration", lambda: {"buckets": []})
    monkeypatch.setattr(module, "get_confusion_matrix", lambda: confusion_matrix)
    monkeypatch.setattr(module, "get_roc_auc", lambda: None)
    monkeypatch.setattr(module, "get_edge_decay_curve", lambda: [])
    monkeypatch.setattr(module, "get_source_reliability", lambda: {})
    monkeypatch.setattr(module, "brier_score_by_method", lambda min_samples=1: {})


class TestCmdHistoryConfusionMatrix:
    def test_orientation_matches_tracker_definitions(self, monkeypatch, capsys):
        """Batch-38 item L-7: tracker.get_confusion_matrix defines
        fp = pred YES & actual NO, fn = pred NO & actual YES. The printed
        table's rows are Actual YES/Actual NO, columns are Pred YES/Pred
        NO -- so row "Actual YES" must show [tp, fn] and row "Actual NO"
        must show [fp, tn], using 4 distinct values so a swap is
        unambiguous either way.

        Mutation check: reverting the fix (swapping cm_rows back to
        [tp, fp] / [fn, tn]) makes this fail -- fp(=7) would appear in the
        Actual YES row and fn(=13) in the Actual NO row instead."""
        import output_formatters as of

        cm = {"tp": 41, "fp": 7, "tn": 29, "fn": 13}
        _mute_all_but_confusion_matrix(monkeypatch, of, cm)

        of.cmd_history(client=MagicMock())
        out = capsys.readouterr().out

        yes_line = next(line for line in out.splitlines() if "Actual YES" in line)
        no_line = next(line for line in out.splitlines() if "Actual NO" in line)

        assert "41" in yes_line and "13" in yes_line
        assert "7" not in yes_line.replace("Actual YES", "")
        assert "7" in no_line and "29" in no_line
        assert "13" not in no_line.replace("Actual NO", "")

    def test_precision_recall_f1_unaffected_by_display_fix(self, monkeypatch, capsys):
        """The P/R/F1 line is computed straight from the raw dict (not the
        display rows), so it must stay correct across the display fix."""
        import output_formatters as of

        cm = {"tp": 8, "fp": 2, "tn": 8, "fn": 2}
        _mute_all_but_confusion_matrix(monkeypatch, of, cm)

        of.cmd_history(client=MagicMock())
        out = capsys.readouterr().out

        assert "Precision: 80.00%" in out
        assert "Recall: 80.00%" in out
        assert "F1: 80.00%" in out

    def test_empty_confusion_matrix_skips_block(self, monkeypatch, capsys):
        import output_formatters as of

        _mute_all_but_confusion_matrix(monkeypatch, of, {})

        of.cmd_history(client=MagicMock())
        out = capsys.readouterr().out

        assert "Actual YES" not in out


class TestCmdHistorySmoke:
    def test_no_history_prints_hint_and_returns(self, monkeypatch, capsys):
        import output_formatters as of

        monkeypatch.setattr(of, "sync_outcomes", lambda client: 0)
        monkeypatch.setattr(of, "get_history", lambda n: [])

        of.cmd_history(client=MagicMock())
        out = capsys.readouterr().out

        assert "No history yet" in out

    def test_full_run_with_populated_data_does_not_raise(self, monkeypatch, capsys):
        """Smoke test (batch-38 item L-2): exercise the whole function with
        every dependency returning representative, non-empty data."""
        import output_formatters as of

        monkeypatch.setattr(of, "sync_outcomes", lambda client: 2)
        monkeypatch.setattr(
            of,
            "get_history",
            lambda n: [
                {
                    "ticker": "KXHIGHNY-26AUG24-T85",
                    "predicted_at": "2026-08-24",
                    "our_prob": 0.62,
                    "market_prob": 0.55,
                    "edge": 0.07,
                    "settled_yes": 1,
                },
                {
                    "ticker": "KXHIGHNY-26AUG23-T84",
                    "predicted_at": "2026-08-23",
                    "our_prob": None,
                    "market_prob": None,
                    "edge": None,
                    "settled_yes": None,
                },
            ],
        )
        import main

        monkeypatch.setattr(of, "brier_score_rolling_with_n", lambda: (0.15, 40))
        monkeypatch.setattr(main, "_brier_sparkline", lambda: "▂▃▅")
        monkeypatch.setattr(
            of,
            "get_calibration_trend",
            lambda weeks=8: [
                {"week": "2026-W33", "brier": 0.14, "n": 10},
                {"week": "2026-W34", "brier": 0.16, "n": 12},
            ],
        )
        monkeypatch.setattr(
            of,
            "get_calibration_by_city",
            lambda: {"NYC": {"brier": 0.14, "bias": 0.02, "n": 10}},
        )
        monkeypatch.setattr(
            of,
            "get_calibration_by_type",
            lambda: {"high": {"brier": 0.14, "bias": 0.02, "win_rate": 0.6, "n": 10}},
        )
        monkeypatch.setattr(
            of,
            "get_profit_factor",
            lambda: {
                "n": 5,
                "profit_factor": 1.8,
                "win_loss_ratio": 2.1,
                "gross_profit": 20.0,
                "gross_loss": 11.0,
                "n_wins": 3,
                "n_losses": 2,
                "avg_win": 6.6,
                "avg_loss": 5.5,
            },
        )
        monkeypatch.setattr(
            of,
            "get_market_calibration",
            lambda: {
                "buckets": [
                    {
                        "range": "50-60%",
                        "market_prob_avg": 0.55,
                        "actual_rate": 0.62,
                        "diff": 0.07,
                        "n": 12,
                    }
                ]
            },
        )
        monkeypatch.setattr(
            of, "get_confusion_matrix", lambda: {"tp": 4, "fp": 1, "tn": 3, "fn": 2}
        )
        monkeypatch.setattr(of, "get_roc_auc", lambda: {"auc": 0.74})
        monkeypatch.setattr(
            of,
            "get_edge_decay_curve",
            lambda: [{"days_label": "0-1d", "avg_edge": 0.05, "n": 6}],
        )
        monkeypatch.setattr(
            of,
            "get_source_reliability",
            lambda: {"NYC": {"nws": {"total": 5, "rate": 0.8, "successes": 4}}},
        )
        monkeypatch.setattr(
            of, "brier_score_by_method", lambda min_samples=1: {"nws": 0.15}
        )

        of.cmd_history(client=MagicMock())  # must not raise
        out = capsys.readouterr().out

        assert "Actual YES" in out
        assert "ROC-AUC" in out


class TestCmdPnlAttribution:
    def test_insufficient_data_prints_hint(self, monkeypatch, capsys):
        import output_formatters as of

        monkeypatch.setattr(of, "get_pnl_by_signal_source", lambda min_samples=5: {})

        of.cmd_pnl_attribution()
        out = capsys.readouterr().out

        assert "Not enough data" in out

    def test_renders_sorted_by_brier_ascending(self, monkeypatch, capsys):
        import output_formatters as of

        monkeypatch.setattr(
            of,
            "get_pnl_by_signal_source",
            lambda min_samples=5: {
                "nws": {"brier": 0.22, "win_rate": 0.55, "n": 12, "n_shadow": 0},
                "ensemble": {"brier": 0.14, "win_rate": 0.63, "n": 20, "n_shadow": 3},
            },
        )

        of.cmd_pnl_attribution()
        out = capsys.readouterr().out

        assert out.index("ensemble") < out.index("nws")
        assert "Shadow = never-traded" in out

    def test_no_shadow_data_omits_footnote(self, monkeypatch, capsys):
        import output_formatters as of

        monkeypatch.setattr(
            of,
            "get_pnl_by_signal_source",
            lambda min_samples=5: {
                "nws": {"brier": 0.20, "win_rate": 0.5, "n": 8, "n_shadow": 0},
            },
        )

        of.cmd_pnl_attribution()
        out = capsys.readouterr().out

        assert "Shadow = never-traded" not in out
