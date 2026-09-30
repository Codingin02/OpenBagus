"""OpenBagus Printable & PDF Report Generator.

Creates standalone HTML documents styled for print or headless PDF conversion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root


def render_pdf_report(analysis_payload: Mapping[str, Any], output_path: Path | None = None) -> Path:
    """Generates an executive print-ready HTML/PDF report."""
    root = get_repo_root()
    dest = output_path or root / "reports/runtime/openbagus_executive_brief_latest.html"
    dest.parent.mkdir(parents=True, exist_ok=True)

    gen_time = analysis_payload.get("generated_at_utc", "N/A")
    asset_views = analysis_payload.get("asset_views", {})

    rows_html = ""
    for sym, view in asset_views.items():
        ms = view.get("market_structure", {})
        price = ms.get("current_price", "N/A")
        price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else str(price)
        rows_html += f"""
        <tr>
            <td><strong>{sym}</strong></td>
            <td>{price_str}</td>
            <td>{view.get('portfolio_stance')}</td>
            <td>{view.get('conviction_score')}/100</td>
            <td>{view.get('actionability_score')}/100</td>
            <td>{view.get('invalidation_level') or 'N/A'}</td>
            <td>{view.get('risk_note')}</td>
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
    <div class="meta">Generated: {gen_time} | Domain: Crypto (Active) | Engine: Standalone Python Quant Core</div>
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
