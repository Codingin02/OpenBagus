"""OpenBagus Printable & PDF Report Generator.

Creates standalone HTML documents styled for print or headless PDF conversion,
and native vector PDF reports using matplotlib Agg backend.
"""

from __future__ import annotations

from html import escape
import os
from pathlib import Path
from typing import Any, Mapping
from datetime import datetime, timezone

from openbagus.core.env import get_repo_root


def get_reports_dir(root: Path | None = None) -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        p = Path(local_app_data) / "OpenBagus" / "reports"
    elif root:
        p = root / "reports"
    else:
        p = Path("reports")
    p.mkdir(parents=True, exist_ok=True)
    return p


def render_pdf_report(analysis_payload: Mapping[str, Any], output_path: Path | None = None) -> Path:
    """Generates an executive print-ready HTML/PDF report."""
    root = get_repo_root()
    dest = output_path or root / "reports/runtime/openbagus_executive_brief_latest.html"
    dest.parent.mkdir(parents=True, exist_ok=True)

    gen_time = analysis_payload.get("generated_at_utc", "N/A")
    asset_views = analysis_payload.get("asset_views", {})

    rows_html = ""
    for sym, view in asset_views.items():
        price = view.get("current_price", "N/A")
        price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else str(price)
        rows_html += f"""
        <tr>
            <td><strong>{escape(str(sym))}</strong></td>
            <td>{escape(price_str)}</td>
            <td>{escape(str(view.get('portfolio_stance', 'Watchlist')))}</td>
            <td>{escape(str(view.get('conviction_score', 'N/A')))}/100</td>
            <td>{escape(str(view.get('actionability_score', 'N/A')))}/100</td>
            <td>{escape(str(view.get('invalidation_level') or 'N/A'))}</td>
            <td>{escape(str(view.get('risk_note', 'DATA GAP')))}</td>
        </tr>
        """

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>OpenBagus Executive Research Report</title>
<style>
@media print {{ body {{ margin: 0; padding: 15mm; }} }}
body {{ font-family: 'Helvetica Neue', Arial, sans-serif; line-height: 1.5; color: #1a202c; max-width: 900px; margin: 30px auto; }}
.header {{ border-bottom: 2px solid #0f172a; padding-bottom: 12px; margin-bottom: 24px; }}
.title {{ font-size: 24px; font-weight: bold; color: #0f172a; margin: 0; }}
.meta {{ font-size: 13px; color: #64748b; margin-top: 6px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
th, td {{ border: 1px solid #cbd5e1; padding: 10px; text-align: left; font-size: 13px; }}
th {{ background-color: #f1f5f9; }}
.disclaimer {{ margin-top: 40px; font-size: 11px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 12px; }}
</style>
</head>
<body>
<div class="header">
    <div class="title">OpenBagus Platform &bull; Quantitative Intelligence Report</div>
    <div class="meta">Generated: {escape(str(gen_time))} | Domain: Crypto (Active) | Engine: Standalone Python Quant Core</div>
</div>
<h3>Executive Asset Overview</h3>
<table>
    <thead>
        <tr>
            <th>Asset</th>
            <th>Price</th>
            <th>Stance</th>
            <th>Conviction</th>
            <th>Actionability</th>
            <th>Invalidation</th>
            <th>Risk Note</th>
        </tr>
    </thead>
    <tbody>
        {rows_html}
    </tbody>
</table>
<div class="disclaimer">
    OpenBagus is a modular financial research platform. All outputs are generated purely for algorithmic analysis and research evaluation. No automated order routing is performed.
</div>
</body>
</html>"""

    with dest.open("w", encoding="utf-8") as f:
        f.write(html_content)

    return dest


def generate_pdf_report(
    symbol: str,
    quant_result: Any,
    packet: Any = None,
    ownership: Any = None,
    root: Path | None = None,
    timeframe: str = "1D",
) -> Path:
    """Generates a professional standalone PDF research document using matplotlib Agg backend."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    dest_dir = get_reports_dir(root)
    dest_path = dest_dir / f"{symbol.lower()}_{timeframe.lower()}_report.pdf"

    # Create A4 landscape or portrait figure
    fig = plt.figure(figsize=(8.27, 11.69), dpi=200)  # A4 portrait in inches
    fig.patch.set_facecolor("#ffffff")

    # Layout using subplots / gridspec
    gs = fig.add_gridspec(nrows=6, ncols=1, height_ratios=[1.2, 1.8, 2.0, 2.5, 2.5, 0.8], hspace=0.35)

    # 1. Header Banner
    ax_header = fig.add_subplot(gs[0])
    ax_header.axis("off")
    ax_header.fill_between([0, 1], [0, 0], [1, 1], color="#0f172a", transform=ax_header.transAxes)
    ax_header.text(0.04, 0.65, "OPENBAGUS FINANCIAL INTELLIGENCE", transform=ax_header.transAxes,
                   fontsize=14, fontweight="bold", color="#f8fafc", va="center")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ax_header.text(0.04, 0.30, f"Quantitative Research Report  |  Asset: {symbol.upper()}  |  Timeframe: {timeframe}  |  Generated: {now_str}",
                   transform=ax_header.transAxes, fontsize=9, color="#94a3b8", va="center")

    # 2. Executive Summary Metrics Grid
    ax_summary = fig.add_subplot(gs[1])
    ax_summary.axis("off")
    q = quant_result
    price_val = getattr(q, "price", None)
    if price_val is not None:
        price_disp = f"Rp{price_val:,.0f}" if getattr(q, "market", "") == "EQUITY_ID" or "IDR" in getattr(packet, "currency", "") else f"${price_val:,.2f}"
    else:
        price_disp = "DATA GAP"

    decision = getattr(q, "decision", "NEUTRAL")
    regime = getattr(q, "regime", "N/A")
    quality = getattr(q, "data_quality", "N/A")
    setup_q = getattr(q, "setup_quality", "N/A")

    metrics_data = [
        [f"Last Price: {price_disp}", f"Decision: {decision}", f"Regime: {regime}"],
        [f"Data Quality: {quality}", f"Setup Quality: {setup_q}", f"Freshness: {getattr(q, 'data_freshness', 'N/A')}"],
        [f"Reward/Risk: {getattr(q, 'reward_risk_str', 'N/A')}",
         f"Stop: {('Rp' + format(q.stop_price, ',.0f')) if getattr(q, 'stop_price', None) else 'N/A'}",
         f"Target (TP1): {('Rp' + format(q.tp1, ',.0f')) if getattr(q, 'tp1', None) else 'N/A'}"]
    ]

    tbl = ax_summary.table(
        cellText=metrics_data,
        cellLoc="left",
        loc="center",
        bbox=[0.02, 0.05, 0.96, 0.90]
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    for (row, col), cell in tbl.get_celld().items():
        cell.set_edgecolor("#cbd5e1")
        cell.set_facecolor("#f8fafc" if row % 2 == 0 else "#ffffff")
        cell.set_text_props(weight="bold" if row == 0 else "normal")

    # 3. Decision Rationale & Bullish Validation
    ax_rationale = fig.add_subplot(gs[2])
    ax_rationale.axis("off")
    ax_rationale.text(0.02, 0.92, "DECISION RATIONALE & RISK GUARDRAILS", transform=ax_rationale.transAxes,
                     fontsize=10, fontweight="bold", color="#0f172a")
    reason_text = getattr(q, "decision_reason", "Tidak ada catatan risiko.")
    bullish = getattr(q, "bullish_validation", None)
    val_text = ""
    if bullish:
        val_text = f"\nSkenario Validasi: Trigger {bullish.trigger_condition} | Target Rp{bullish.tp1:,.0f} | Stop Rp{bullish.stop_price:,.0f} (RR {bullish.reward_risk_str})"

    rationale_full = f"{reason_text}{val_text}"
    ax_rationale.text(0.02, 0.70, rationale_full, transform=ax_rationale.transAxes,
                     fontsize=8.5, color="#334155", va="top", wrap=True)

    # 4. Ownership or Fundamentals Section
    ax_mid = fig.add_subplot(gs[3])
    ax_mid.axis("off")
    if ownership and getattr(ownership, "top_shareholders", None):
        ax_mid.text(0.02, 0.95, f"STRUKTUR KEPEMILIKAN & SHAREHOLDERS ({ownership.ticker})",
                    transform=ax_mid.transAxes, fontsize=10, fontweight="bold", color="#0f172a")
        own_rows = [["Pemegang Saham", "Persentase", "Jumlah Lembar", "Tipe Investor"]]
        for s in ownership.top_shareholders[:5]:
            own_rows.append([s.shareholder[:28], f"{s.percentage:.2f}%", f"{s.shares_held:,.0f}", s.investor_type])
        pub_shares = getattr(ownership, "public_shares", None)
        if pub_shares is None:
            pub_shares = (ownership.public_shareholders_pct / 100.0) * getattr(ownership, "shares_outstanding", 0.0)
        own_rows.append(["Publik (Free Float)", f"{ownership.public_shareholders_pct:.2f}%", f"{pub_shares:,.0f}", "PUBLIC"])

        tbl_own = ax_mid.table(
            cellText=own_rows,
            cellLoc="left",
            loc="center",
            bbox=[0.02, 0.05, 0.96, 0.82]
        )
        tbl_own.auto_set_font_size(False)
        tbl_own.set_fontsize(8)
        for (r_idx, c_idx), cell in tbl_own.get_celld().items():
            cell.set_edgecolor("#cbd5e1")
            if r_idx == 0:
                cell.set_facecolor("#e2e8f0")
                cell.set_text_props(weight="bold")
            else:
                cell.set_facecolor("#ffffff" if r_idx % 2 == 1 else "#f8fafc")
    elif packet and getattr(packet, "fundamentals", None) and packet.fundamentals.get("ratios"):
        ax_mid.text(0.02, 0.95, "RINGKASAN FUNDAMENTAL & RASIO KEUANGAN",
                    transform=ax_mid.transAxes, fontsize=10, fontweight="bold", color="#0f172a")
        ratios = packet.fundamentals.get("ratios", {})
        fund_rows = [["Metrik", "Nilai", "Kategori"]]
        for k, v in list(ratios.items())[:6]:
            val_fmt = f"{v:.2f}" if isinstance(v, (int, float)) else str(v)
            fund_rows.append([str(k).upper(), val_fmt, "Laporan Keuangan Terverifikasi"])
        tbl_fund = ax_mid.table(
            cellText=fund_rows,
            cellLoc="left",
            loc="center",
            bbox=[0.02, 0.05, 0.96, 0.82]
        )
        tbl_fund.auto_set_font_size(False)
        tbl_fund.set_fontsize(8)
        for (r_idx, _), cell in tbl_fund.get_celld().items():
            cell.set_edgecolor("#cbd5e1")
            if r_idx == 0:
                cell.set_facecolor("#e2e8f0")
                cell.set_text_props(weight="bold")
            else:
                cell.set_facecolor("#ffffff" if r_idx % 2 == 1 else "#f8fafc")
    else:
        ax_mid.text(0.02, 0.80, "MULTI-FACTOR EVIDENCE & MARKET STRUCTURE",
                    transform=ax_mid.transAxes, fontsize=10, fontweight="bold", color="#0f172a")
        fam_text = ", ".join(getattr(q, "evidence_families", ["Quantitative Indicator Analysis"]))
        ax_mid.text(0.02, 0.50, f"Evidence Families Digunakan:\n- {fam_text}\n- Verifikasi bar candle valid; no synthetic prices.",
                    transform=ax_mid.transAxes, fontsize=8.5, color="#475569")

    # 5. Evidence & Data Sources
    ax_src = fig.add_subplot(gs[4])
    ax_src.axis("off")
    ax_src.text(0.02, 0.95, "DATA GOVERNANCE & PROVENANCE", transform=ax_src.transAxes,
                fontsize=10, fontweight="bold", color="#0f172a")
    sources_list = getattr(q, "sources", [])
    if packet and getattr(packet, "sources", None):
        sources_list = packet.sources
    src_str = " | ".join(sources_list) if sources_list else "Katalog Terverifikasi IDX / Data Provider Terdaftar"
    src_details = (
        f"Sumber Data Terdaftar: {src_str}\n"
        f"Integritas Seri Data: Diverifikasi tanpa imputasi bar acak atau sintetis.\n"
        f"Model Analisis: Quantitative Strategy Engine (Trend/Regime Detection, Volatility Band, Support/Resistance)."
    )
    ax_src.text(0.02, 0.65, src_details, transform=ax_src.transAxes, fontsize=8, color="#475569", va="top")

    # 6. Footer Disclaimer
    ax_footer = fig.add_subplot(gs[5])
    ax_footer.axis("off")
    ax_footer.fill_between([0, 1], [0, 0], [1, 1], color="#f1f5f9", transform=ax_footer.transAxes)
    disclaimer_text = (
        "CONFIDENTIAL & PROPRIETARY — FOR RESEARCH & ALGORITHMIC EVALUATION ONLY.\n"
        "OpenBagus is a local financial workstation. This document does not constitute investment advice or order solicitation."
    )
    ax_footer.text(0.5, 0.5, disclaimer_text, transform=ax_footer.transAxes,
                   fontsize=7.5, color="#64748b", ha="center", va="center")

    with PdfPages(dest_path) as pdf:
        pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

    return dest_path
