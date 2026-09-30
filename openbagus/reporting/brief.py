"""OpenBagus Professional Brief Renderer.

Formats research outputs into clean, high-signal briefs for terminal,
CLI output and local report delivery.
"""

from __future__ import annotations

from typing import Any, Mapping


def render_crypto_brief(analysis_payload: Mapping[str, Any], date_str: str | None = None) -> str:
    """Renders a digital assets daily brief from analysis payload."""
    gen_time = analysis_payload.get("generated_at_utc", "N/A")
    date_display = date_str or gen_time[:10]
    asset_views = analysis_payload.get("asset_views", {})

    lines = [
        f"*OPENBAGUS - DIGITAL ASSETS DAILY BRIEF*",
        f"Date: {date_display} (UTC: {gen_time})",
        f"Domain: Crypto (Active) | Status: {analysis_payload.get('data_freshness_summary', {}).get('overall_analysis_status', 'OK')}",
        "",
        "--- MARKET CORE QUANTITATIVE STANCE ---",
    ]

    for symbol, view in asset_views.items():
        dq = view.get("data_quality", {})
        price = (
            view.get("current_price")
            or view.get("market_structure", {}).get("current_price")
            or view.get("market_structure", {}).get("support_resistance", {}).get("latest_close")
            or "N/A"
        )
        if isinstance(price, (int, float)):
            price_str = f"${price:,.2f}"
        else:
            price_str = str(price)

        conv = view.get("conviction_score", 0)
        act = view.get("actionability_score", 0)
        stance = view.get("portfolio_stance", "Watchlist")
        inv = view.get("invalidation_level")
        inv_str = f"${inv:,.2f}" if inv else "N/A"
        sr = view.get("market_structure", {}).get("support_resistance", {})
        sup = sr.get("support")
        res = sr.get("resistance")
        sup_str = f"${sup:,.2f}" if sup else "N/A"
        res_str = f"${res:,.2f}" if res else "N/A"

        lines.extend([
            f"*{symbol}* ({price_str})",
            f"  - Stance: {stance} | Conv: {conv}/100 | Act: {act}/100",
            f"  - Key Levels: Sup {sup_str} | Res {res_str} | Inval {inv_str}",
            f"  - Risk: {view.get('risk_note', 'N/A')}",
            "",
        ])

    macro_views = analysis_payload.get("macro_views", {})
    if macro_views:
        lines.append("--- CROSS-ASSET MACRO OVERLAY ---")
        for country, data in macro_views.items():
            if isinstance(data, dict):
                inds = data.get("indicators", [])
                for ind in inds[:4]:
                    val = ind.get("value")
                    val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
                    lines.append(f"  - {ind.get('indicator_name', ind.get('indicator_code'))}: {val_str} {ind.get('unit', '')}")
        lines.append("")

    lines.append("> OpenBagus Research: Automated quantitative intelligence. Not a trade recommendation.")
    return "\n".join(lines)


def render_macro_brief(analysis_payload: Mapping[str, Any]) -> str:
    """Renders a macro intelligence summary brief."""
    gen_time = analysis_payload.get("generated_at_utc", "N/A")
    lines = [
        f"*OPENBAGUS - MACRO CONTEXT & LIQUIDITY BRIEF*",
        f"Generated: {gen_time}",
        "",
        "--- MACRO INDICATORS ---",
    ]
    macro_views = analysis_payload.get("macro_views", {})
    for country, data in macro_views.items():
        if isinstance(data, dict):
            for ind in data.get("indicators", []):
                val = ind.get("value")
                val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
                lines.append(f"• {ind.get('indicator_name')}: {val_str} ({ind.get('freshness_status', 'OK')})")

    lines.append("")
    lines.append("> OpenBagus Umbrella Platform: Domain-neutral quantitative research.")
    return "\n".join(lines)
