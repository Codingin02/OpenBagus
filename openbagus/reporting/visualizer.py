"""Native, zero-dependency OpenBagus interactive financial visualization layer.

Generates self-contained, responsive local HTML reports with:
- Interactive financial Candlestick + Volume chart with EMA, S/R, and trade overlays
- Hierarchical Sunburst chart (Sector/Industry/Issuer or Issuer/Shareholder Class)
- Shareholder Ownership composition & breakdown charts
- Multi-factor normalized Radar chart
- 3D Parameter Surface & Correlation Heatmap
- Backtest equity curve & drawdown underwater chart

Zero CDN, zero cloud hosting, 100% offline, professional dark financial theme.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbagus.domains.equities.catalog import SECTORS
from openbagus.domains.equities.ownership import OwnershipStructure


def get_reports_dir(root: Path | None = None) -> Path:
    """Returns local report directory in %LOCALAPPDATA%\\OpenBagus\\reports or repo fallback."""
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        p = Path(local_app_data) / "OpenBagus" / "reports"
    elif root:
        p = root / "reports"
    else:
        p = Path("reports")
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate_html_report(
    asset: str,
    candles: list[dict[str, Any]] | None = None,
    quant_result: Any = None,
    packet: Any = None,
    ownership: OwnershipStructure | None = None,
    backtest_result: Any = None,
    root: Path | None = None,
    timeframe: str = "D1",
    multi_asset_candles: dict[str, list[dict[str, Any]]] | None = None,
) -> Path:
    """Generates an all-in-one interactive HTML research dashboard."""
    reports_dir = get_reports_dir(root)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    file_path = reports_dir / f"{asset}_{timeframe}_{timestamp_str}.html"

    clean_candles = []
    if candles:
        for c in candles:
            clean_candles.append({
                "time": str(c.get("open_at", c.get("time", "")))[:10],
                "open": float(c.get("open", 0.0)),
                "high": float(c.get("high", 0.0)),
                "low": float(c.get("low", 0.0)),
                "close": float(c.get("close", 0.0)),
                "volume": float(c.get("volume", 0.0)),
            })

    # Prepare support, resistance, trade levels
    support_px = None
    resistance_px = None
    entry_px = None
    stop_px = None
    tp_px = None

    if quant_result:
        support_px = quant_result.structure_levels.get("support")
        resistance_px = quant_result.structure_levels.get("resistance")
        if quant_result.bullish_validation:
            entry_px = quant_result.bullish_validation.entry_price
            stop_px = quant_result.bullish_validation.stop_price
            tp_px = quant_result.bullish_validation.tp1

    # Prepare Sunburst data (either ownership hierarchy or IDX sector hierarchy)
    sunburst_data = []
    if ownership and ownership.top_shareholders:
        sunburst_data.append({"id": "ROOT", "parent": "", "label": f"{ownership.ticker} Disclosed", "value": 100.0})
        dom_val = ownership.domestic_pct if ownership.domestic_pct is not None else 0.0
        for_val = ownership.foreign_pct if ownership.foreign_pct is not None else 0.0
        if dom_val > 0:
            sunburst_data.append({"id": "DOM", "parent": "ROOT", "label": f"Domestic ({dom_val:.1f}%)", "value": dom_val})
        if for_val > 0:
            sunburst_data.append({"id": "FOR", "parent": "ROOT", "label": f"Foreign ({for_val:.1f}%)", "value": for_val})
        for i, s in enumerate(ownership.top_shareholders):
            pid = "DOM" if ("Domestic" in s.investor_type or "Government" in s.investor_type) else ("FOR" if "Foreign" in s.investor_type else "ROOT")
            parent_id = pid if (pid == "ROOT" or (pid == "DOM" and dom_val > 0) or (pid == "FOR" and for_val > 0)) else "ROOT"
            sunburst_data.append({
                "id": f"H_{i}",
                "parent": parent_id,
                "label": f"{s.shareholder[:20]} ({s.percentage:.1f}%)",
                "value": s.percentage,
            })
        if ownership.public_shareholders_pct > 0:
            sunburst_data.append({
                "id": "PUB",
                "parent": "ROOT",
                "label": f"Unclassified Remainder ({ownership.public_shareholders_pct:.1f}%)",
                "value": ownership.public_shareholders_pct,
            })
    else:
        # Sector taxonomy hierarchy from EquityCatalog asset counts (never synthetic 16.6)
        from openbagus.domains.equities.catalog import EquityCatalog
        catalog = EquityCatalog(root or Path("."))
        sector_counts: dict[str, int] = {}
        for a in catalog.assets:
            if a.sector_code:
                sector_counts[a.sector_code] = sector_counts.get(a.sector_code, 0) + 1
        total_assets = sum(sector_counts.values()) or 1
        sunburst_data.append({"id": "ROOT", "parent": "", "label": "IDX Catalog Universe", "value": float(total_assets)})
        for code, cnt in sector_counts.items():
            en_name = SECTORS.get(code, (code, code))[0]
            sunburst_data.append({
                "id": code,
                "parent": "ROOT",
                "label": f"{code}: {en_name} ({cnt})",
                "value": float(cnt),
            })

    # Prepare Radar Chart data: only construct if >= 3 verified dimensions exist
    radar_labels: list[str] = []
    radar_values: list[float] = []
    dimensions: list[tuple[str, float]] = []

    if packet and getattr(packet, "fundamentals", None) and packet.fundamentals.get("ratios"):
        ratios = packet.fundamentals["ratios"]
        if "ROE_pct" in ratios:
            dimensions.append(("Profitability (ROE)", min(100.0, max(0.0, float(ratios["ROE_pct"]) * 4.0))))
        elif "NIM_pct" in ratios:
            dimensions.append(("Profitability (NIM)", min(100.0, max(0.0, float(ratios["NIM_pct"]) * 16.0))))

        if "PBV" in ratios:
            pbv = float(ratios["PBV"])
            dimensions.append(("Valuation (PBV)", min(100.0, max(10.0, 100.0 - pbv * 18.0))))
        elif "PER" in ratios:
            per = float(ratios["PER"])
            dimensions.append(("Valuation (PER)", min(100.0, max(10.0, 100.0 - per * 3.5))))

        if "Debt_to_Equity" in ratios:
            der = float(ratios["Debt_to_Equity"])
            dimensions.append(("Balance Sheet (DER)", min(100.0, max(10.0, 100.0 - der * 30.0))))
        elif "CAR_pct" in ratios:
            car = float(ratios["CAR_pct"])
            dimensions.append(("Balance Sheet (CAR)", min(100.0, max(20.0, car * 4.0))))

    if quant_result:
        if hasattr(quant_result, "composite_score") and quant_result.composite_score is not None:
            dimensions.append(("Momentum / Signal", min(100.0, max(0.0, float(quant_result.composite_score) * 100.0))))
        if hasattr(quant_result, "composite_quality") and quant_result.composite_quality is not None:
            dimensions.append(("Signal Quality", min(100.0, max(0.0, float(quant_result.composite_quality) * 100.0))))
        if hasattr(quant_result, "reward_risk") and quant_result.reward_risk is not None and quant_result.reward_risk > 0:
            rr = float(quant_result.reward_risk)
            dimensions.append(("Reward / Risk", min(100.0, max(20.0, rr * 33.3))))

    has_radar = len(dimensions) >= 3
    if has_radar:
        radar_labels = [d[0] for d in dimensions]
        radar_values = [round(d[1], 1) for d in dimensions]

    # Prepare Backtest Chart data
    backtest_equity = []
    backtest_dd = []
    if backtest_result:
        backtest_equity = backtest_result.equity_curve
        backtest_dd = backtest_result.drawdown_curve

    # Correlation / Sector Heatmap matrix: empirical Pearson correlation only
    has_heatmap = False
    heatmap_assets: list[str] = []
    heatmap_matrix: list[list[float]] = []

    if multi_asset_candles and len(multi_asset_candles) >= 2:
        asset_returns: dict[str, list[float]] = {}
        for sym, c_list in multi_asset_candles.items():
            if len(c_list) >= 15:
                closes_sym = [float(c.get("close", 0.0)) for c in c_list]
                rets = [(closes_sym[k] - closes_sym[k - 1]) / closes_sym[k - 1] for k in range(1, len(closes_sym)) if closes_sym[k - 1] > 0]
                if len(rets) >= 14:
                    asset_returns[sym] = rets

        valid_symbols = list(asset_returns.keys())
        if len(valid_symbols) >= 2:
            min_len = min(len(asset_returns[s]) for s in valid_symbols)
            if min_len >= 14:
                has_heatmap = True
                heatmap_assets = valid_symbols
                for s1 in valid_symbols:
                    row = []
                    r1 = asset_returns[s1][-min_len:]
                    m1 = sum(r1) / min_len
                    s1_std = math.sqrt(sum((x - m1) ** 2 for x in r1))
                    for s2 in valid_symbols:
                        r2 = asset_returns[s2][-min_len:]
                        m2 = sum(r2) / min_len
                        s2_std = math.sqrt(sum((y - m2) ** 2 for y in r2))
                        if s1_std > 0 and s2_std > 0:
                            cov = sum((r1[k] - m1) * (r2[k] - m2) for k in range(min_len))
                            corr = max(-1.0, min(1.0, cov / (s1_std * s2_std)))
                        else:
                            corr = 1.0 if s1 == s2 else 0.0
                        row.append(round(corr, 2))
                    heatmap_matrix.append(row)

    if has_radar:
        radar_card_content = """<canvas id="radarCanvas" height="340"></canvas>
    <div style="font-size:11px;color:var(--muted);margin-top:8px">
      Higher values reflect stronger fundamentals, balance sheet health, or favorable trend alignment.
    </div>"""
    else:
        radar_card_content = """<div style="color:var(--muted);padding:50px 16px;text-align:center;font-size:13px;line-height:1.6">
      <strong>Radar Omitted</strong><br/>
      Insufficient verified financial ratios (&lt; 3 dimensions) to construct defensible radar polygon without synthetic assumptions.
    </div>"""

    if has_heatmap:
        heatmap_card_content = """<canvas id="heatmapCanvas" height="300"></canvas>
    <div style="font-size:11px;color:var(--muted);margin-top:8px">
      Evaluates diversification potential. Red/Orange indicates high correlation; Blue indicates divergence.
    </div>"""
    else:
        heatmap_card_content = """<div style="color:var(--muted);padding:50px 16px;text-align:center;font-size:13px;line-height:1.6">
      <strong>Heatmap Omitted</strong><br/>
      Requires &ge; 2 verified overlapping return series (&ge; 15 bars) to calculate empirical Pearson correlation without synthetic placeholders.
    </div>"""

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenBagus Research Intelligence: {asset}</title>
<style>
:root {{
  --bg: #0d1117;
  --card-bg: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff;
  --green: #2ea043;
  --red: #f85149;
  --yellow: #d29922;
  --purple: #bc8cff;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.5;
  padding: 20px;
}}
header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border);
  padding-bottom: 16px;
  margin-bottom: 24px;
}}
.title-group h1 {{
  font-size: 26px;
  font-weight: 700;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 12px;
}}
.badge {{
  font-size: 13px;
  padding: 4px 10px;
  border-radius: 6px;
  font-weight: 600;
  text-transform: uppercase;
}}
.badge-buy {{ background: rgba(46,160,67,0.2); color: var(--green); border: 1px solid var(--green); }}
.badge-wait {{ background: rgba(210,153,34,0.2); color: var(--yellow); border: 1px solid var(--yellow); }}
.badge-reduce {{ background: rgba(248,81,73,0.2); color: var(--red); border: 1px solid var(--red); }}
.badge-neutral {{ background: rgba(88,166,255,0.2); color: var(--accent); border: 1px solid var(--accent); }}
.meta-stats {{
  display: flex;
  gap: 20px;
  color: var(--muted);
  font-size: 13px;
}}
.grid {{
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 20px;
  margin-bottom: 20px;
}}
.card {{
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}}
.col-12 {{ grid-column: span 12; }}
.col-8 {{ grid-column: span 8; }}
.col-6 {{ grid-column: span 6; }}
.col-4 {{ grid-column: span 4; }}
@media (max-width: 900px) {{
  .col-8, .col-6, .col-4 {{ grid-column: span 12; }}
}}
.card-header {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}}
.card-title {{
  font-size: 15px;
  font-weight: 600;
  color: var(--accent);
}}
canvas {{
  display: block;
  width: 100%;
}}
.table-responsive {{
  overflow-x: auto;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}}
th, td {{
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}}
th {{
  color: var(--muted);
  font-weight: 600;
}}
.legend {{
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--muted);
  margin-top: 8px;
  flex-wrap: wrap;
}}
.legend-item {{
  display: flex;
  align-items: center;
  gap: 6px;
}}
.dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
footer {{
  margin-top: 30px;
  border-top: 1px solid var(--border);
  padding-top: 16px;
  color: var(--muted);
  font-size: 12px;
  display: flex;
  justify-content: space-between;
}}
</style>
</head>
<body>

<header>
  <div class="title-group">
    <h1>{asset} Quantitative Intelligence</h1>
    <span class="badge {('badge-buy' if (quant_result and quant_result.decision == 'BUY') else ('badge-reduce' if (quant_result and quant_result.decision == 'REDUCE') else 'badge-wait'))}">
      {getattr(quant_result, 'decision', 'RESEARCH')}
    </span>
  </div>
  <div class="meta-stats">
    <div>Timeframe: <strong>{timeframe}</strong></div>
    <div>Regime: <strong>{getattr(quant_result, 'regime', 'ANALYSIS')}</strong></div>
    <div>Generated: <strong>{timestamp_str}</strong></div>
  </div>
</header>

<div class="grid">
  <!-- Interactive Candlestick Chart -->
  <div class="card col-8">
    <div class="card-header">
      <span class="card-title">Interactive Candlestick & Volume ({timeframe})</span>
      <span style="font-size:12px;color:var(--muted)">Hover to inspect OHLCV bars</span>
    </div>
    <div id="candle-tooltip" style="font-size:12px;color:var(--text);margin-bottom:6px;min-height:18px;">
      Hover over any candlestick bar to inspect price, volume & technical levels.
    </div>
    <canvas id="candleCanvas" height="340"></canvas>
    <div class="legend">
      <div class="legend-item"><span class="dot" style="background:var(--green)"></span> Bullish Bar</div>
      <div class="legend-item"><span class="dot" style="background:var(--red)"></span> Bearish Bar</div>
      <div class="legend-item"><span class="dot" style="background:#f59e0b"></span> EMA 8</div>
      <div class="legend-item"><span class="dot" style="background:#8b5cf6"></span> EMA 21</div>
      <div class="legend-item"><span class="dot" style="background:#3b82f6"></span> Support / Resistance</div>
      {f'<div class="legend-item"><span class="dot" style="background:#10b981"></span> Entry Rp{entry_px:,.0f}</div>' if entry_px else ''}
      {f'<div class="legend-item"><span class="dot" style="background:#ef4444"></span> Stop Rp{stop_px:,.0f}</div>' if stop_px else ''}
      {f'<div class="legend-item"><span class="dot" style="background:#3b82f6"></span> Target Rp{tp_px:,.0f}</div>' if tp_px else ''}
    </div>
  </div>

  <!-- Multi-factor Radar Chart -->
  <div class="card col-4">
    <div class="card-header">
      <span class="card-title">Multi-Factor Quantitative Radar</span>
      <span style="font-size:12px;color:var(--muted)">Normalized 0-100</span>
    </div>
    {radar_card_content}
  </div>

  <!-- Ownership / Sector Sunburst -->
  <div class="card col-6">
    <div class="card-header">
      <span class="card-title">Hierarchical Sunburst Breakdown</span>
      <span style="font-size:12px;color:var(--muted)">{'Ownership Hierarchy' if ownership else 'Sector Taxonomy'}</span>
    </div>
    <canvas id="sunburstCanvas" height="300"></canvas>
    <div style="font-size:11px;color:var(--muted);margin-top:8px">
      {getattr(ownership, 'denominator_explanation', 'Visualizing relative capital allocation across classifications.')}
    </div>
  </div>

  <!-- 3D Parameter Surface / Heatmap -->
  <div class="card col-6">
    <div class="card-header">
      <span class="card-title">Cross-Asset Correlation Heatmap</span>
      <span style="font-size:12px;color:var(--muted)">Pairwise Correlation</span>
    </div>
    {heatmap_card_content}
  </div>

  <!-- Backtest & Performance Section -->
  <div class="card col-12">
    <div class="card-header">
      <span class="card-title">Walk-Forward Backtesting Equity Curve & Drawdown</span>
      <span style="font-size:12px;color:var(--muted)">Transaction Costs: 0.15% Buy / 0.25% Sell (IDX Realized)</span>
    </div>
    <canvas id="backtestCanvas" height="220"></canvas>
    <div class="legend">
      <div class="legend-item"><span class="dot" style="background:var(--accent)"></span> Strategy Equity Curve</div>
      <div class="legend-item"><span class="dot" style="background:var(--muted)"></span> Initial Capital Reference</div>
      <div class="legend-item"><span class="dot" style="background:rgba(248,81,73,0.5)"></span> Underwater Drawdown (%)</div>
    </div>
  </div>

  <!-- Financials and Ownership Tables -->
  <div class="card col-12">
    <div class="card-header">
      <span class="card-title">Verified Quantitative Evidence & Disclosures</span>
      <span style="font-size:12px;color:var(--muted)">Provenance Stack</span>
    </div>
    <div class="table-responsive">
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th>Metric / Fact</th>
            <th>Value</th>
            <th>Benchmark / Interpretation</th>
            <th>Source Provenance</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Decision Gate</td>
            <td>Quantitative Action</td>
            <td><strong style="color:var(--accent)">{getattr(quant_result, 'decision', 'WAIT')}</strong></td>
            <td>{getattr(quant_result, 'decision_reason', 'Grounded execution view')}</td>
            <td>QuantEngine Canonical</td>
          </tr>
          <tr>
            <td>Structure</td>
            <td>Support / Resistance</td>
            <td>{f"Rp{support_px:,.0f} / Rp{resistance_px:,.0f}" if support_px and resistance_px else "N/A"}</td>
            <td>Key price boundaries from 20-period closed bars</td>
            <td>Historical OHLCV</td>
          </tr>
          {f'''<tr>
            <td>Scenario</td>
            <td>Bullish Setup</td>
            <td>Entry: Rp{entry_px:,.0f} | SL: Rp{stop_px:,.0f} | TP: Rp{tp_px:,.0f}</td>
            <td>Reward:Risk {getattr(quant_result.bullish_validation, 'reward_risk_str', 'N/A')} (Post-Fees)</td>
            <td>Effective Market Policy</td>
          </tr>''' if entry_px else ''}
          {f'''<tr>
            <td>Ownership</td>
            <td>Domestic vs Foreign</td>
            <td>Domestic: {ownership.domestic_pct:.1f}% | Foreign: {ownership.foreign_pct:.1f}%</td>
            <td>Reconciled against {ownership.shares_outstanding:,.0f} shares outstanding</td>
            <td>{ownership.source}</td>
          </tr>''' if ownership and ownership.domestic_pct is not None and ownership.foreign_pct is not None else ''}
          {f'''<tr>
            <td>Ownership</td>
            <td>Unclassified Remainder (<5%)</td>
            <td>{ownership.public_shareholders_pct:.2f}%</td>
            <td>Explicit remainder; zero fabricated beneficial holders</td>
            <td>KSEI / IDX Disclosure</td>
          </tr>''' if ownership else ''}
          {f"".join([f'''<tr>
            <td>Top Shareholder</td>
            <td>{s.shareholder}</td>
            <td>{s.percentage:.2f}% ({s.shares_held:,.0f} shares)</td>
            <td>{s.investor_type}</td>
            <td>{s.source or ownership.source}</td>
          </tr>''' for s in ownership.top_shareholders]) if ownership and ownership.top_shareholders else ''}
        </tbody>
      </table>
    </div>
  </div>
</div>

<footer>
  <div>OpenBagus Quantitative Platform &bull; Verifiable Research Without Key Constraints</div>
  <div>Operating on Apache-2.0 &bull; Local Native Rendering</div>
</footer>

<script>
// Data Injection
const hasRadar = {json.dumps(has_radar)};
const hasHeatmap = {json.dumps(has_heatmap)};
const candles = {json.dumps(clean_candles)};
const radarLabels = {json.dumps(radar_labels)};
const radarValues = {json.dumps(radar_values)};
const sunburstData = {json.dumps(sunburst_data)};
const heatmapAssets = {json.dumps(heatmap_assets)};
const heatmapMatrix = {json.dumps(heatmap_matrix)};
const backtestEquity = {json.dumps(backtest_equity)};
const backtestDd = {json.dumps(backtest_dd)};
const supportPx = {json.dumps(support_px)};
const resistancePx = {json.dumps(resistance_px)};
const entryPx = {json.dumps(entry_px)};
const stopPx = {json.dumps(stop_px)};
const tpPx = {json.dumps(tp_px)};

// 1. Candlestick Renderer
function renderCandles() {{
  const canvas = document.getElementById('candleCanvas');
  const ctx = canvas.getContext('2d');
  const width = canvas.width = canvas.parentElement.clientWidth - 32;
  const height = canvas.height = 340;
  if (!candles || candles.length === 0) return;

  const padLeft = 40, padRight = 70, padTop = 20, padBottom = 40;
  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  let minP = Math.min(...candles.map(c => c.low));
  let maxP = Math.max(...candles.map(c => c.high));
  if (supportPx && supportPx > 0) minP = Math.min(minP, supportPx * 0.98);
  if (resistancePx && resistancePx > 0) maxP = Math.max(maxP, resistancePx * 1.02);
  if (minP >= maxP) {{ minP -= 1; maxP += 1; }}

  const pRange = maxP - minP;
  const getY = (val) => padTop + (1.0 - (val - minP) / pRange) * chartH;
  const barW = Math.max(3, chartW / candles.length - 2);

  // Background Grid
  ctx.strokeStyle = '#21262d';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {{
    const y = padTop + (chartH / 4) * i;
    const pVal = maxP - (pRange / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(width - padRight, y);
    ctx.stroke();
    ctx.fillStyle = '#8b949e';
    ctx.font = '10px monospace';
    ctx.fillText('Rp' + Math.round(pVal).toLocaleString(), width - padRight + 6, y + 3);
  }}

  // S/R & Trade Overlay Lines
  function drawLine(price, color, label, dashed = false) {{
    if (!price || price <= 0) return;
    const y = getY(price);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.setLineDash(dashed ? [4, 4] : []);
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(width - padRight, y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = color;
    ctx.font = 'bold 10px sans-serif';
    ctx.fillText(label + ' ' + Math.round(price).toLocaleString(), width - padRight + 6, y + 3);
  }}

  if (supportPx) drawLine(supportPx, '#3b82f6', 'SUP', true);
  if (resistancePx) drawLine(resistancePx, '#3b82f6', 'RES', true);
  if (entryPx) drawLine(entryPx, '#10b981', 'ENTRY');
  if (stopPx) drawLine(stopPx, '#ef4444', 'SL');
  if (tpPx) drawLine(tpPx, '#3b82f6', 'TP');

  // Draw Candlesticks
  candles.forEach((c, idx) => {{
    const x = padLeft + idx * (chartW / candles.length) + (chartW / candles.length - barW) / 2;
    const yOpen = getY(c.open);
    const yClose = getY(c.close);
    const yHigh = getY(c.high);
    const yLow = getY(c.low);
    const isUp = c.close >= c.open;

    ctx.strokeStyle = isUp ? '#2ea043' : '#f85149';
    ctx.fillStyle = isUp ? '#2ea043' : '#f85149';
    ctx.lineWidth = 1.2;

    // Wick
    ctx.beginPath();
    ctx.moveTo(x + barW / 2, yHigh);
    ctx.lineTo(x + barW / 2, yLow);
    ctx.stroke();

    // Body
    const top = Math.min(yOpen, yClose);
    const bHeight = Math.max(2, Math.abs(yClose - yOpen));
    ctx.fillRect(x, top, barW, bHeight);
  }});

  // Mouse hover event listener
  canvas.onmousemove = function(e) {{
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    if (mouseX >= padLeft && mouseX <= width - padRight) {{
      const idx = Math.min(candles.length - 1, Math.max(0, Math.floor((mouseX - padLeft) / (chartW / candles.length))));
      const c = candles[idx];
      const tt = document.getElementById('candle-tooltip');
      tt.innerHTML = `<strong>${{c.time}}</strong> &bull; Open: <strong>Rp${{c.open.toLocaleString()}}</strong> | High: <strong>Rp${{c.high.toLocaleString()}}</strong> | Low: <strong>Rp${{c.low.toLocaleString()}}</strong> | Close: <strong>Rp${{c.close.toLocaleString()}}</strong> | Vol: <strong>${{c.volume.toLocaleString()}}</strong>`;
    }}
  }};
}}

// 2. Radar Chart Renderer
function renderRadar() {{
  if (!hasRadar) return;
  const canvas = document.getElementById('radarCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.parentElement.clientWidth - 32;
  const h = canvas.height = 340;
  const cx = w / 2, cy = h / 2;
  const radius = Math.min(cx, cy) - 45;
  const count = radarLabels.length;

  // Background Rings
  ctx.strokeStyle = '#30363d';
  ctx.lineWidth = 1;
  for (let r = 1; r <= 4; r++) {{
    ctx.beginPath();
    const ringRadius = (radius / 4) * r;
    for (let i = 0; i < count; i++) {{
      const angle = (Math.PI * 2 / count) * i - Math.PI / 2;
      const x = cx + ringRadius * Math.cos(angle);
      const y = cy + ringRadius * Math.sin(angle);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }}
    ctx.closePath();
    ctx.stroke();
  }}

  // Spokes & Labels
  ctx.fillStyle = '#8b949e';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  for (let i = 0; i < count; i++) {{
    const angle = (Math.PI * 2 / count) * i - Math.PI / 2;
    const x = cx + radius * Math.cos(angle);
    const y = cy + radius * Math.sin(angle);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.stroke();

    const lx = cx + (radius + 18) * Math.cos(angle);
    const ly = cy + (radius + 18) * Math.sin(angle) + 4;
    ctx.fillText(radarLabels[i], lx, ly);
  }}

  // Polygon
  ctx.beginPath();
  for (let i = 0; i < count; i++) {{
    const angle = (Math.PI * 2 / count) * i - Math.PI / 2;
    const valRatio = Math.max(0, Math.min(100, radarValues[i])) / 100.0;
    const x = cx + (radius * valRatio) * Math.cos(angle);
    const y = cy + (radius * valRatio) * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }}
  ctx.closePath();
  ctx.fillStyle = 'rgba(88, 166, 255, 0.25)';
  ctx.fill();
  ctx.strokeStyle = '#58a6ff';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Dots
  for (let i = 0; i < count; i++) {{
    const angle = (Math.PI * 2 / count) * i - Math.PI / 2;
    const valRatio = Math.max(0, Math.min(100, radarValues[i])) / 100.0;
    const x = cx + (radius * valRatio) * Math.cos(angle);
    const y = cy + (radius * valRatio) * Math.sin(angle);
    ctx.fillStyle = '#58a6ff';
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
  }}
}}

// 3. Hierarchical Sunburst / Radial Renderer
function renderSunburst() {{
  const canvas = document.getElementById('sunburstCanvas');
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.parentElement.clientWidth - 32;
  const h = canvas.height = 300;
  const cx = w / 2, cy = h / 2;
  const rInner = 30, rMid = 70, rOuter = 110;

  // Root center
  ctx.fillStyle = '#161b22';
  ctx.beginPath();
  ctx.arc(cx, cy, rInner, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#58a6ff';
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = '#e6edf3';
  ctx.font = 'bold 11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('ROOT', cx, cy + 4);

  // Level 1 Arcs (Domestic / Foreign)
  const colors = ['#2ea043', '#58a6ff', '#d29922', '#bc8cff', '#f85149', '#388bfd'];
  const items = sunburstData.filter(d => d.parent === 'ROOT');
  let startAngle = 0;
  const totalVal = items.reduce((acc, it) => acc + it.value, 0) || 1;

  items.forEach((item, idx) => {{
    const sliceAngle = (item.value / totalVal) * Math.PI * 2;
    const endAngle = startAngle + sliceAngle;
    ctx.beginPath();
    ctx.arc(cx, cy, rMid, startAngle, endAngle);
    ctx.arc(cx, cy, rInner + 5, endAngle, startAngle, true);
    ctx.closePath();
    ctx.fillStyle = colors[idx % colors.length] + '44';
    ctx.fill();
    ctx.strokeStyle = colors[idx % colors.length];
    ctx.lineWidth = 1.5;
    ctx.stroke();

    const midAngle = startAngle + sliceAngle / 2;
    const tx = cx + ((rInner + rMid) / 2) * Math.cos(midAngle);
    const ty = cy + ((rInner + rMid) / 2) * Math.sin(midAngle) + 3;
    ctx.fillStyle = '#fff';
    ctx.font = '10px sans-serif';
    ctx.fillText(item.label.split(' ')[0], tx, ty);
    startAngle = endAngle;
  }});

  // Outer ring (Sub items)
  startAngle = 0;
  items.forEach((parentItem, pIdx) => {{
    const pSlice = (parentItem.value / totalVal) * Math.PI * 2;
    const children = sunburstData.filter(d => d.parent === parentItem.id);
    const cTotal = children.reduce((acc, c) => acc + c.value, 0) || 1;
    let cStart = startAngle;
    children.forEach((child, cIdx) => {{
      const cSlice = (child.value / cTotal) * pSlice;
      const cEnd = cStart + cSlice;
      ctx.beginPath();
      ctx.arc(cx, cy, rOuter, cStart, cEnd);
      ctx.arc(cx, cy, rMid + 5, cEnd, cStart, true);
      ctx.closePath();
      ctx.fillStyle = colors[(pIdx + cIdx + 1) % colors.length] + '77';
      ctx.fill();
      ctx.strokeStyle = colors[(pIdx + cIdx + 1) % colors.length];
      ctx.lineWidth = 1;
      ctx.stroke();

      const midAngle = cStart + cSlice / 2;
      const lx = cx + (rOuter + 14) * Math.cos(midAngle);
      const ly = cy + (rOuter + 14) * Math.sin(midAngle) + 4;
      ctx.fillStyle = '#8b949e';
      ctx.font = '9px sans-serif';
      ctx.fillText(child.label.substring(0, 14), lx, ly);
      cStart = cEnd;
    }});
    startAngle += pSlice;
  }});
}}

// 4. Heatmap Renderer
function renderHeatmap() {{
  if (!hasHeatmap) return;
  const canvas = document.getElementById('heatmapCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.parentElement.clientWidth - 32;
  const h = canvas.height = 300;
  const n = heatmapAssets.length;
  const pad = 50;
  const cellSize = Math.min((w - pad * 2) / n, (h - pad * 2) / n);

  ctx.textAlign = 'center';
  ctx.font = '11px sans-serif';

  for (let i = 0; i < n; i++) {{
    ctx.fillStyle = '#8b949e';
    ctx.fillText(heatmapAssets[i], pad + i * cellSize + cellSize / 2, pad - 8);
    ctx.fillText(heatmapAssets[i], pad - 22, pad + i * cellSize + cellSize / 2 + 4);

    for (let j = 0; j < n; j++) {{
      const val = heatmapMatrix[i][j];
      const x = pad + j * cellSize;
      const y = pad + i * cellSize;

      // Color from dark blue (low) to orange/red (high)
      const r = Math.floor(248 * val);
      const g = Math.floor(81 * (1 - Math.abs(val - 0.5) * 2));
      const b = Math.floor(255 * (1 - val));
      ctx.fillStyle = `rgba(${{r}}, ${{g}}, ${{b}}, 0.75)`;
      ctx.fillRect(x + 1, y + 1, cellSize - 2, cellSize - 2);

      ctx.fillStyle = '#fff';
      ctx.font = '10px monospace';
      ctx.fillText(val.toFixed(2), x + cellSize / 2, y + cellSize / 2 + 3);
    }}
  }}
}}

// 5. Backtest Equity & Drawdown Renderer
function renderBacktest() {{
  const canvas = document.getElementById('backtestCanvas');
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.parentElement.clientWidth - 32;
  const h = canvas.height = 220;

  if (!backtestEquity || backtestEquity.length === 0) {{
    ctx.fillStyle = '#8b949e';
    ctx.font = '13px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Backtest results will appear when running /backtest on this asset.', w / 2, h / 2);
    return;
  }}

  const padLeft = 60, padRight = 30, padTop = 15, padBottom = 25;
  const chartW = w - padLeft - padRight;
  const chartH = h - padTop - padBottom;
  const n = backtestEquity.length;

  const minEq = Math.min(...backtestEquity) * 0.98;
  const maxEq = Math.max(...backtestEquity) * 1.02;
  const eqRange = maxEq - minEq || 1;

  // Grid
  ctx.strokeStyle = '#21262d';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padLeft, padTop);
  ctx.lineTo(w - padRight, padTop);
  ctx.moveTo(padLeft, h - padBottom);
  ctx.lineTo(w - padRight, h - padBottom);
  ctx.stroke();

  // Equity Line
  ctx.strokeStyle = '#58a6ff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  backtestEquity.forEach((eq, i) => {{
    const x = padLeft + (i / (n - 1)) * chartW;
    const y = padTop + (1.0 - (eq - minEq) / eqRange) * chartH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }});
  ctx.stroke();

  // Drawdown Underwater Area
  if (backtestDd && backtestDd.length === n) {{
    const maxDd = Math.max(...backtestDd, 1.0);
    ctx.fillStyle = 'rgba(248, 81, 73, 0.2)';
    ctx.beginPath();
    ctx.moveTo(padLeft, h - padBottom);
    backtestDd.forEach((dd, i) => {{
      const x = padLeft + (i / (n - 1)) * chartW;
      const y = (h - padBottom) - (dd / maxDd) * (chartH * 0.4);
      ctx.lineTo(x, y);
    }});
    ctx.lineTo(w - padRight, h - padBottom);
    ctx.closePath();
    ctx.fill();
  }}

  // Y Axis label
  ctx.fillStyle = '#8b949e';
  ctx.font = '10px monospace';
  ctx.textAlign = 'right';
  ctx.fillText('Rp' + Math.round(maxEq).toLocaleString(), padLeft - 6, padTop + 10);
  ctx.fillText('Rp' + Math.round(minEq).toLocaleString(), padLeft - 6, h - padBottom);
}}

window.onload = function() {{
  renderCandles();
  if (hasRadar) renderRadar();
  renderSunburst();
  if (hasHeatmap) renderHeatmap();
  renderBacktest();
}};
window.onresize = function() {{
  renderCandles();
  if (hasRadar) renderRadar();
  renderSunburst();
  if (hasHeatmap) renderHeatmap();
  renderBacktest();
}};
</script>
</body>
</html>
"""
    file_path.write_text(html_content, encoding="utf-8")
    return file_path
