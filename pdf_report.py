"""
Weekly trading report generator.
Produces a PDF (requires fpdf2) or HTML fallback summary of portfolio performance.

Usage:
    from pdf_report import generate_weekly_report
    path = generate_weekly_report()  # returns path of created file
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

try:
    from fpdf import FPDF  # type: ignore[import-untyped]

    _HAS_FPDF = True
except ImportError:
    _HAS_FPDF = False


def _collect_data() -> dict:
    """Gather all data needed for the report."""
    from paper import (
        fear_greed_index,
        get_all_trades,
        get_balance,
        get_current_streak,
        get_max_drawdown_pct,
        get_open_trades,
        get_performance,
    )
    from tracker import brier_score

    perf = get_performance()
    streak_kind, streak_n = get_current_streak()
    fg_score, fg_label = fear_greed_index()

    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "balance": round(get_balance(), 2),
        "pnl": perf.get("total_pnl", 0.0),
        "win_rate": perf.get("win_rate"),
        "settled": perf.get("settled", 0),
        "max_drawdown": round(get_max_drawdown_pct() * 100, 1),
        "brier": brier_score(),
        "streak_kind": streak_kind,
        "streak_n": streak_n,
        "fg_score": fg_score,
        "fg_label": fg_label,
        "open_trades": get_open_trades(),
        "recent_settled": [t for t in get_all_trades() if t.get("settled")][-10:],
    }


def _generate_pdf(data: dict, output_path: Path) -> None:
    """Generate PDF using fpdf2."""
    pdf = FPDF()  # type: ignore[misc]
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Kalshi Weather Trading — Weekly Report", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generated: {data['generated_at']}", ln=True)
    pdf.ln(4)

    # Portfolio summary
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Portfolio Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pnl_str = (
        f"+${data['pnl']:.2f}" if data["pnl"] >= 0 else f"-${abs(data['pnl']):.2f}"
    )
    wr_str = f"{data['win_rate']:.0%}" if data["win_rate"] is not None else "—"
    bs_str = f"{data['brier']:.4f}" if data["brier"] is not None else "—"
    summary_lines = [
        f"Balance:      ${data['balance']:.2f}",
        f"Total P&L:    {pnl_str}",
        f"Win Rate:     {wr_str}  ({data['settled']} settled trades)",
        f"Brier Score:  {bs_str}",
        f"Max Drawdown: {data['max_drawdown']:.1f}%",
        f"Streak:       {data['streak_n']}x {data['streak_kind']}",
        f"Fear/Greed:   {data['fg_score']} — {data['fg_label']}",
    ]
    for line in summary_lines:
        pdf.cell(0, 6, line, ln=True)
    pdf.ln(4)

    # Open positions
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, f"Open Positions ({len(data['open_trades'])})", ln=True)
    pdf.set_font("Helvetica", "", 9)
    if not data["open_trades"]:
        pdf.cell(0, 6, "No open positions.", ln=True)
    else:
        col_w = [55, 18, 15, 22, 28, 32]
        headers = ["Ticker", "Side", "Qty", "Entry", "Cost", "Date"]
        pdf.set_font("Helvetica", "B", 9)
        for h, w in zip(headers, col_w):
            pdf.cell(w, 6, h, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
        for t in data["open_trades"]:
            row = [
                t.get("ticker", "")[:22],
                t.get("side", "").upper(),
                str(t.get("quantity", "")),
                f"${t.get('entry_price', 0):.3f}",
                f"${t.get('cost', 0):.2f}",
                str(t.get("target_date", ""))[:10],
            ]
            for val, w in zip(row, col_w):
                pdf.cell(w, 6, val, border=1)
            pdf.ln()
    pdf.ln(4)

    # Recent settled trades
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Recent Settled Trades (last 10)", ln=True)
    settled = data["recent_settled"]
    if not settled:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, "No settled trades.", ln=True)
    else:
        col_w2 = [55, 18, 22, 20, 25]
        headers2 = ["Ticker", "Side", "Outcome", "P&L", "Date"]
        pdf.set_font("Helvetica", "B", 9)
        for h, w in zip(headers2, col_w2):
            pdf.cell(w, 6, h, border=1)
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
        for t in reversed(settled):
            p = t.get("pnl") or 0.0
            p_str = f"+${p:.2f}" if p >= 0 else f"-${abs(p):.2f}"
            row2 = [
                t.get("ticker", "")[:22],
                t.get("side", "").upper(),
                (t.get("outcome") or "—").upper(),
                p_str,
                (t.get("entered_at") or "")[:10],
            ]
            for val, w in zip(row2, col_w2):
                pdf.cell(w, 6, val, border=1)
            pdf.ln()

    pdf.output(str(output_path))


def _generate_html(data: dict, output_path: Path) -> None:
    """Generate HTML report as fallback when fpdf2 is not installed."""
    pnl_cls = "pos" if data["pnl"] >= 0 else "neg"
    pnl_str = (
        f"+${data['pnl']:.2f}" if data["pnl"] >= 0 else f"-${abs(data['pnl']):.2f}"
    )
    wr_str = f"{data['win_rate']:.0%}" if data["win_rate"] is not None else "—"
    bs_str = f"{data['brier']:.4f}" if data["brier"] is not None else "—"

    open_rows = ""
    for t in data["open_trades"]:
        open_rows += (
            f"<tr><td>{t.get('ticker', '')[:28]}</td>"
            f"<td>{t.get('side', '').upper()}</td>"
            f"<td>{t.get('quantity', '')}</td>"
            f"<td>${t.get('entry_price', 0):.3f}</td>"
            f"<td>${t.get('cost', 0):.2f}</td>"
            f"<td>{t.get('target_date', '')}</td></tr>"
        )

    settled_rows = ""
    for t in reversed(data["recent_settled"]):
        p = t.get("pnl") or 0.0
        p_cls = "pos" if p >= 0 else "neg"
        p_str = f"+${p:.2f}" if p >= 0 else f"-${abs(p):.2f}"
        settled_rows += (
            f"<tr><td>{t.get('ticker', '')[:28]}</td>"
            f"<td>{t.get('side', '').upper()}</td>"
            f"<td>{(t.get('outcome') or '—').upper()}</td>"
            f"<td class='{p_cls}'>{p_str}</td>"
            f"<td>{(t.get('entered_at') or '')[:10]}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html><head><title>Kalshi Weekly Report</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0d1117; color: #c9d1d9; font-family: Consolas, monospace; padding: 24px; }}
  h1 {{ color: #58a6ff; margin-bottom: 6px; }}
  h2 {{ color: #8b949e; margin: 20px 0 8px; border-bottom: 1px solid #21262d; padding-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; font-size: 0.87em; }}
  th {{ background: #161b22; color: #8b949e; padding: 7px 10px; text-align: left; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #21262d; }}
  .pos {{ color: #3fb950; }} .neg {{ color: #f85149; }}
  .stat {{ display: inline-block; background: #161b22; border: 1px solid #21262d;
           border-radius: 6px; padding: 10px 16px; margin: 6px 6px 0 0; }}
  .stat-label {{ color: #8b949e; font-size: 0.78em; text-transform: uppercase; }}
  .stat-value {{ font-size: 1.3em; font-weight: bold; margin-top: 3px; }}
</style></head><body>
<h1>Kalshi Weather Trading — Weekly Report</h1>
<p style="color:#8b949e; margin-bottom:16px">Generated: {data["generated_at"]}</p>

<div>
  <div class="stat"><div class="stat-label">Balance</div><div class="stat-value pos">${data["balance"]:.2f}</div></div>
  <div class="stat"><div class="stat-label">P&amp;L</div><div class="stat-value {
        pnl_cls
    }">{pnl_str}</div></div>
  <div class="stat"><div class="stat-label">Win Rate</div><div class="stat-value">{
        wr_str
    }</div></div>
  <div class="stat"><div class="stat-label">Brier</div><div class="stat-value">{
        bs_str
    }</div></div>
  <div class="stat"><div class="stat-label">Max Drawdown</div><div class="stat-value">{data["max_drawdown"]:.1f}%</div></div>
  <div class="stat"><div class="stat-label">Fear/Greed</div><div class="stat-value">{
        data["fg_score"]
    } — {data["fg_label"]}</div></div>
</div>

<h2>Open Positions ({len(data["open_trades"])})</h2>
{
        "<p style='color:#8b949e'>No open positions.</p>"
        if not data["open_trades"]
        else f'''
<table><tr><th>Ticker</th><th>Side</th><th>Qty</th><th>Entry</th><th>Cost</th><th>Date</th></tr>
{open_rows}</table>'''
    }

<h2>Recent Settled Trades</h2>
{
        "<p style='color:#8b949e'>No settled trades yet.</p>"
        if not data["recent_settled"]
        else f'''
<table><tr><th>Ticker</th><th>Side</th><th>Outcome</th><th>P&amp;L</th><th>Date</th></tr>
{settled_rows}</table>'''
    }

</body></html>"""

    output_path.write_text(html, encoding="utf-8")


def generate_weekly_report(output_path: str | None = None) -> str:
    """
    Generate a weekly trading summary report.
    Creates a PDF if fpdf2 is installed, otherwise an HTML file.
    Returns the path of the created file.
    """
    data = _collect_data()

    if output_path is None:
        ext = ".pdf" if _HAS_FPDF else ".html"
        default_path = DATA_DIR / f"weekly_report{ext}"
    else:
        default_path = Path(output_path)

    default_path.parent.mkdir(exist_ok=True)

    if _HAS_FPDF:
        try:
            _generate_pdf(data, default_path)
        except Exception as exc:
            _log.error(
                "pdf_report: PDF generation failed, falling back to HTML: %s", exc
            )
            default_path = default_path.with_suffix(".html")
            _generate_html(data, default_path)
    else:
        # If caller passed .pdf but fpdf2 not installed, switch to .html
        if default_path.suffix == ".pdf":
            default_path = default_path.with_suffix(".html")
        _generate_html(data, default_path)

    return str(default_path)
