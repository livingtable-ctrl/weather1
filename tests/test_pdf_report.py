"""Tests for pdf_report.py -- batch-38 item M-23f: this module had zero
test coverage despite being web-reachable (web_app.py's /api/weekly-report
downloads whatever it renders) and excluded from the coverage gate."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPRESENTATIVE_DATA = {
    "generated_at": "2026-08-24 12:00 UTC",
    "balance": 1234.56,
    "pnl": 78.9,
    "win_rate": 0.625,
    "settled": 16,
    "max_drawdown": 4.2,
    "brier": 0.1834,
    "brier_n": 40,
    "streak_kind": "win",
    "streak_n": 3,
    "fg_score": 72,
    "fg_label": "Confident",
    "open_trades": [
        {
            "ticker": "KXHIGHNY-26AUG24-T85",
            "side": "yes",
            "quantity": 5,
            "entry_price": 0.62,
            "cost": 3.1,
            "target_date": "2026-08-24",
        }
    ],
    "recent_settled": [
        {
            "ticker": "KXHIGHNY-26AUG23-T84",
            "side": "no",
            "outcome": "win",
            "pnl": 2.4,
            "entered_at": "2026-08-23T10:00:00",
        },
        {
            "ticker": "KXHIGHNY-26AUG22-T83",
            "side": "yes",
            "outcome": "loss",
            "pnl": -1.1,
            "entered_at": "2026-08-22T09:30:00",
        },
    ],
}


def _data_with(**overrides) -> dict:
    data = {
        k: (v.copy() if isinstance(v, dict | list) else v)
        for k, v in _REPRESENTATIVE_DATA.items()
    }
    data["open_trades"] = [dict(t) for t in _REPRESENTATIVE_DATA["open_trades"]]
    data["recent_settled"] = [dict(t) for t in _REPRESENTATIVE_DATA["recent_settled"]]
    data.update(overrides)
    return data


class TestGenerateHtml:
    def test_renders_without_exception_and_writes_file(self, tmp_path):
        from pdf_report import _generate_html

        out = tmp_path / "report.html"
        _generate_html(_data_with(), out)

        assert out.exists()
        html_text = out.read_text(encoding="utf-8")
        assert html_text.startswith("<!DOCTYPE html>")

    def test_key_fields_present_in_output(self, tmp_path):
        from pdf_report import _generate_html

        out = tmp_path / "report.html"
        _generate_html(_data_with(), out)
        html_text = out.read_text(encoding="utf-8")

        assert "$1234.56" in html_text
        assert "+$78.90" in html_text
        assert "62%" in html_text
        assert "0.1834" in html_text
        assert "4.2%" in html_text
        assert "KXHIGHNY-26AUG24-T85" in html_text
        assert "KXHIGHNY-26AUG23-T84" in html_text

    def test_negative_pnl_renders_with_minus_sign(self, tmp_path):
        from pdf_report import _generate_html

        out = tmp_path / "report.html"
        _generate_html(_data_with(pnl=-42.5), out)
        html_text = out.read_text(encoding="utf-8")

        assert "-$42.50" in html_text
        assert "+$-42.50" not in html_text

    def test_empty_open_and_settled_trades_render_placeholder_text(self, tmp_path):
        from pdf_report import _generate_html

        out = tmp_path / "report.html"
        _generate_html(_data_with(open_trades=[], recent_settled=[]), out)
        html_text = out.read_text(encoding="utf-8")

        assert "No open positions." in html_text
        assert "No settled trades yet." in html_text

    def test_ticker_html_is_escaped_not_injected_raw(self, tmp_path):
        """M-23f hardening: a ticker (exchange-controlled, not this
        operator's own input) containing HTML-significant characters must
        not be interpolated verbatim into the served report.

        Positive control: the SAME malicious string is asserted absent in
        raw form AND its escaped form is asserted present -- proving
        html.escape actually ran on this field, not just that the raw
        payload happened to be dropped somewhere upstream."""
        from pdf_report import _generate_html

        malicious_ticker = "<script>alert(1)</script>"
        out = tmp_path / "report.html"
        _generate_html(
            _data_with(
                open_trades=[
                    {
                        "ticker": malicious_ticker,
                        "side": "yes",
                        "quantity": 1,
                        "entry_price": 0.5,
                        "cost": 0.5,
                        "target_date": "2026-08-24",
                    }
                ]
            ),
            out,
        )
        html_text = out.read_text(encoding="utf-8")

        assert malicious_ticker not in html_text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_text

    def test_outcome_and_entered_at_html_are_escaped(self, tmp_path):
        from pdf_report import _generate_html

        out = tmp_path / "report.html"
        _generate_html(
            _data_with(
                recent_settled=[
                    {
                        "ticker": "T",
                        "side": "yes",
                        "outcome": "<b>win</b>",
                        "pnl": 1.0,
                        "entered_at": "<i>2026-08-24</i>",
                    }
                ]
            ),
            out,
        )
        html_text = out.read_text(encoding="utf-8")

        assert "<b>win</b>" not in html_text
        # .upper() runs before escaping, so the tag letters are upper-cased too.
        assert "&lt;B&gt;WIN&lt;/B&gt;" in html_text
        # entered_at is sliced to [:10] chars BEFORE escaping, so the raw
        # "<i>2026-08-24</i>" (17 chars) is truncated to "<i>2026-08"
        # (10 chars) first, then escaped.
        assert "<i>2026-08" not in html_text
        assert "&lt;i&gt;2026-08" in html_text

    def test_missing_optional_fields_do_not_raise(self, tmp_path):
        """win_rate/brier can be None (e.g. no settled trades yet) -- must
        render a placeholder, not crash on a None format spec."""
        from pdf_report import _generate_html

        out = tmp_path / "report.html"
        _generate_html(_data_with(win_rate=None, brier=None), out)
        html_text = out.read_text(encoding="utf-8")

        assert out.exists()
        assert "—" in html_text  # em-dash placeholder for both None fields


class TestGeneratePdf:
    def test_renders_without_exception_and_writes_valid_pdf(self, tmp_path):
        pytest.importorskip("fpdf")
        from pdf_report import _generate_pdf

        out = tmp_path / "report.pdf"
        _generate_pdf(_data_with(), out)

        assert out.exists()
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_empty_trades_do_not_raise(self, tmp_path):
        pytest.importorskip("fpdf")
        from pdf_report import _generate_pdf

        out = tmp_path / "report.pdf"
        _generate_pdf(_data_with(open_trades=[], recent_settled=[]), out)

        assert out.exists()
        assert out.read_bytes()[:5] == b"%PDF-"

    def test_em_dash_and_non_latin1_ticker_do_not_crash_helvetica(self, tmp_path):
        """_pdf() strips characters outside Latin-1 so fpdf2's core
        Helvetica font (Latin-1 only) doesn't raise -- exercise a ticker
        with a non-Latin-1 character (an em-dash survives via the explicit
        replace; anything else falls back to '?')."""
        pytest.importorskip("fpdf")
        from pdf_report import _generate_pdf

        out = tmp_path / "report.pdf"
        data = _data_with(
            open_trades=[
                {
                    "ticker": "KXHIGH—NY",
                    "side": "yes",
                    "quantity": 1,
                    "entry_price": 0.5,
                    "cost": 0.5,
                    "target_date": "2026-08-24",
                }
            ]
        )
        _generate_pdf(data, out)  # must not raise UnicodeEncodeError

        assert out.exists()


class TestPdfHelper:
    def test_replaces_em_dash_with_hyphen(self):
        from pdf_report import _pdf

        assert _pdf("A—B") == "A-B"

    def test_non_latin1_char_falls_back_to_replacement(self):
        from pdf_report import _pdf

        # U+2603 SNOWMAN has no Latin-1 representation.
        result = _pdf("temp ☃ reading")
        assert "☃" not in result

    def test_plain_ascii_is_unchanged(self):
        from pdf_report import _pdf

        assert _pdf("Balance: $100.00") == "Balance: $100.00"


class TestGenerateWeeklyReport:
    def test_html_fallback_path_used_when_fpdf_unavailable(self, tmp_path, monkeypatch):
        import pdf_report

        monkeypatch.setattr(pdf_report, "_HAS_FPDF", False)
        monkeypatch.setattr(pdf_report, "_collect_data", lambda: _data_with())

        out_path = str(tmp_path / "report.html")
        result = pdf_report.generate_weekly_report(out_path)

        assert result.endswith(".html")
        assert Path(result).exists()
        assert Path(result).read_text(encoding="utf-8").startswith("<!DOCTYPE html>")

    def test_pdf_path_used_when_fpdf_available(self, tmp_path, monkeypatch):
        pytest.importorskip("fpdf")
        import pdf_report

        monkeypatch.setattr(pdf_report, "_HAS_FPDF", True)
        monkeypatch.setattr(pdf_report, "_collect_data", lambda: _data_with())

        out_path = str(tmp_path / "report.pdf")
        result = pdf_report.generate_weekly_report(out_path)

        assert result.endswith(".pdf")
        assert Path(result).read_bytes()[:5] == b"%PDF-"

    def test_pdf_suffix_downgraded_to_html_when_fpdf_unavailable(
        self, tmp_path, monkeypatch
    ):
        """A caller-supplied .pdf output_path must not silently produce a
        file with a .pdf extension that's actually HTML content."""
        import pdf_report

        monkeypatch.setattr(pdf_report, "_HAS_FPDF", False)
        monkeypatch.setattr(pdf_report, "_collect_data", lambda: _data_with())

        out_path = str(tmp_path / "report.pdf")
        result = pdf_report.generate_weekly_report(out_path)

        assert result.endswith(".html")
        assert not Path(out_path).exists()
        assert Path(result).exists()

    def test_default_output_path_uses_data_dir(self, tmp_path, monkeypatch):
        import pdf_report

        monkeypatch.setattr(pdf_report, "DATA_DIR", tmp_path)
        monkeypatch.setattr(pdf_report, "_HAS_FPDF", False)
        monkeypatch.setattr(pdf_report, "_collect_data", lambda: _data_with())

        result = pdf_report.generate_weekly_report()

        assert Path(result).parent == tmp_path
        assert Path(result).name == "weekly_report.html"
