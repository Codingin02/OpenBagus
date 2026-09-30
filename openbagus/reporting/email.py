"""OpenBagus Email Report Renderer.

Generates institutional HTML and plain-text email reports for cross-asset macro
and digital asset quantitative intelligence.
"""

from __future__ import annotations

from html import escape
from typing import Any, Mapping


def render_email_report(
    analysis_payload: Mapping[str, Any],
    report_type: str = "crypto_macro",
) -> dict[str, str]:
    """Render a concise email body; detailed analysis belongs in the attachment."""
    gen_time = analysis_payload.get("generated_at_utc", "N/A")
    asset_views = analysis_payload.get("asset_views", {})
    freshness = analysis_payload.get("data_freshness_summary", {})
    source_health = analysis_payload.get("source_health_summary", {})

    subject = f"[OpenBagus Intelligence] Daily Research Brief - {gen_time[:10]}"
    overall_status = freshness.get("overall_analysis_status", "DATA GAP")
    source_failures = source_health.get("fail", 0)
    text_lines = [
        "OPENBAGUS RESEARCH INTELLIGENCE",
        f"Generated: {gen_time}",
        "Domain: Crypto (Active)",
        f"Data freshness: {overall_status}",
        f"Source gap: {source_failures} failed source(s)",
        "",
        "Quantitative highlights:",
    ]
    html_highlights = []
    for sym, view in list(asset_views.items())[:10]:
        line = (
            f"{sym}: {view.get('portfolio_stance', 'Watchlist')}; "
            f"Conviction {view.get('conviction_score', 'N/A')}/100; "
            f"Actionability {view.get('actionability_score', 'N/A')}/100; "
            f"Risk: {view.get('risk_note', 'DATA GAP')}"
        )
        text_lines.append(f"- {line}")
        html_highlights.append(f"<li>{escape(line)}</li>")

    if not html_highlights:
        text_lines.append("- DATA GAP: no asset analysis is available.")
        html_highlights.append("<li>DATA GAP: no asset analysis is available.</li>")

    text_lines.extend(
        [
            "",
            "Detailed analysis is attached as a print-ready HTML report.",
            "Research-only. No broker or exchange order execution.",
        ]
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{escape(subject)}</title></head>
<body style="font-family:Arial,sans-serif;color:#172033;line-height:1.5;max-width:680px;margin:24px auto">
<h2 style="margin-bottom:4px">OpenBagus Research Intelligence</h2>
<p style="margin-top:0;color:#526078">Generated: {escape(str(gen_time))} | Domain: Crypto</p>
<p><strong>Data freshness:</strong> {escape(str(overall_status))}<br>
<strong>Source gap:</strong> {escape(str(source_failures))} failed source(s)</p>
<h3>Quantitative highlights</h3>
<ul>{''.join(html_highlights)}</ul>
<p>Detailed analysis is attached as a print-ready HTML report.</p>
<hr>
<p style="font-size:12px;color:#64748b">Research-only. No broker or exchange order execution.</p>
</body>
</html>"""

    return {
        "subject": subject,
        "text": "\n".join(text_lines),
        "html": html,
    }
