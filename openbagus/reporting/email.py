"""OpenBagus Email Report Renderer.

Generates institutional HTML and plain-text email reports for cross-asset macro
and digital asset quantitative intelligence.
"""

from __future__ import annotations

from typing import Any, Mapping


def render_email_report(
    analysis_payload: Mapping[str, Any],
    report_type: str = "crypto_macro",
) -> dict[str, str]:
    """Renders HTML and text versions of email reports."""
    gen_time = analysis_payload.get("generated_at_utc", "N/A")
    asset_views = analysis_payload.get("asset_views", {})
    macro_views = analysis_payload.get("macro_views", {})

    subject = f"[OpenBagus Intelligence] Daily Research Brief - {gen_time[:10]}"

    text_lines = [
        f"OPENBAGUS RESEARCH INTELLIGENCE",
        f"Generated: {gen_time}",
        f"Domain: Crypto (Active)",
        "",
        "=== QUANTITATIVE SUMMARY ===",
    ]
    for sym, view in asset_views.items():
        text_lines.append(
            f"{sym}: Stance={view.get('portfolio_stance')}, "
            f"Conviction={view.get('conviction_score')}/100, "
            f"Actionability={view.get('actionability_score')}/100"
        )
    text_lines.append("\n=== MACRO OVERLAY ===")
    for country, data in macro_views.items():
        if isinstance(data, dict):
            for ind in data.get("indicators", []):
                text_lines.append(f"{ind.get('indicator_name')}: {ind.get('value')} {ind.get('unit', '')}")

    html_rows = ""
    for sym, view in asset_views.items():
        ms = view.get("market_structure", {})
        price = ms.get("current_price", "N/A")
        price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else str(price)
        inv = view.get("invalidation_level", "N/A")
        inv_str = f"${inv:,.2f}" if isinstance(inv, (int, float)) else str(inv)

        html_rows += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; font-weight: bold;">{sym}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{price_str}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;"><span style="background: #e6fffa; color: #234e52; padding: 3px 8px; border-radius: 4px; font-weight: 600;">{view.get('portfolio_stance')}</span></td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: center;">{view.get('conviction_score')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: center;">{view.get('actionability_score')}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{inv_str}</td>
        </tr>
        """

    html_macro_rows = ""
    for country, data in macro_views.items():
        if isinstance(data, dict):
            for ind in data.get("indicators", []):
                val = ind.get("value")
                val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
                html_macro_rows += f"""
                <tr>
                    <td style="padding: 8px; border-bottom: 1px solid #edf2f7;">{ind.get('indicator_name')}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #edf2f7; font-weight: 600;">{val_str} {ind.get('unit', '')}</td>
                    <td style="padding: 8px; border-bottom: 1px solid #edf2f7; color: #718096;">{ind.get('freshness_status', 'OK')}</td>
                </tr>
                """

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f7fafc; color: #2d3748; margin: 0; padding: 20px; }}
.container {{ max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
.header {{ background: #0f172a; color: #ffffff; padding: 24px; text-align: left; }}
.header h1 {{ margin: 0; font-size: 20px; letter-spacing: 0.5px; }}
.header p {{ margin: 4px 0 0 0; color: #94a3b8; font-size: 13px; }}
.content {{ padding: 24px; }}
.table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 14px; }}
.table th {{ background: #f8fafc; padding: 10px; text-align: left; font-weight: 600; color: #475569; border-bottom: 2px solid #e2e8f0; }}
.footer {{ background: #f1f5f9; padding: 16px; text-align: center; font-size: 12px; color: #64748b; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>OpenBagus Market Intelligence</h1>
        <p>Active Domain: Crypto | UTC Generated: {gen_time}</p>
    </div>
    <div class="content">
        <h3 style="color: #0f172a; margin-top: 0;">Market Core Asset Stance</h3>
        <table class="table">
            <thead>
                <tr>
                    <th>Asset</th>
                    <th>Price</th>
                    <th>Stance</th>
                    <th>Conv</th>
                    <th>Act</th>
                    <th>Invalidation</th>
                </tr>
            </thead>
            <tbody>
                {html_rows}
            </tbody>
        </table>

        <h3 style="color: #0f172a; margin-top: 28px;">Macro & Global Liquidity Context</h3>
        <table class="table">
            <thead>
                <tr>
                    <th>Indicator</th>
                    <th>Value</th>
                    <th>Freshness</th>
                </tr>
            </thead>
            <tbody>
                {html_macro_rows}
            </tbody>
        </table>
    </div>
    <div class="footer">
        OpenBagus Platform &bull; Modular Financial & Alternative Data Architecture &bull; Research Output Only
    </div>
</div>
</body>
</html>"""

    return {
        "subject": subject,
        "text": "\n".join(text_lines),
        "html": html,
    }
