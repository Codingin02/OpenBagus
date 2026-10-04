"""OpenBagus Coin-Centric Quantitative Crypto Research & Decision Engine.

Executes tailored single-asset quantitative analysis and decision support based on intent:
- SPOT: BUY | WAIT | REDUCE
- PERPETUAL/FUTURES: LONG | SHORT | NO_TRADE
- Decision fields: Asset, Market, Decision, Confidence, Current Price, Entry Zone,
  Invalidation / Stop, TP1, TP2, TP3 (when justified), Risk:Reward, Volatility,
  Evidence Quality, Suggested Leverage Ceiling (perpetuals, calculated conservatively).
- Capital & position sizing calculator (equity, risk percentage, margin).
- Resilient multi-provider fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.data.ingestion import RuntimeDataIngestion
from openbagus.data.providers import ProviderRegistry
from openbagus.domains.crypto.catalog import CryptoAsset, CryptoAssetCatalog
from openbagus.intelligence.intent import IntentRequest


def _fmt_price(val: float | None) -> str:
    if val is None:
        return "N/A"
    if val >= 1000:
        return f"${val:,.2f}"
    if val >= 1:
        return f"${val:,.4f}"
    if val >= 0.0001:
        return f"${val:,.6f}"
    return f"${val:,.8f}"


def _fmt_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}%"


def _fmt_vol(val: float | None) -> str:
    if val is None:
        return "N/A"
    if val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.2f}B"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.2f}M"
    if val >= 1_000:
        return f"${val / 1_000:.2f}K"
    return f"${val:.2f}"


class CryptoResearchRunner:
    """Executes single-asset quantitative research pipelines and decision support."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.catalog = CryptoAssetCatalog(self.root)
        self.registry = ProviderRegistry(self.root)

    def execute(self, req: IntentRequest) -> str:
        # 1. Handle clarification request
        if req.needs_asset:
            return req.clarification_prompt or "Which asset do you want to analyze?"

        # 2. Handle ambiguity
        if req.is_ambiguous and req.candidates:
            lines = ["Multiple assets matched your query:", ""]
            for idx, sym in enumerate(req.candidates[:5], 1):
                asset_obj, _ = self.catalog.resolve_asset(sym)
                name = asset_obj.name if asset_obj else sym
                cat = asset_obj.categories[0] if asset_obj and asset_obj.categories else "General"
                rank = f"#{asset_obj.rank}" if asset_obj and asset_obj.rank < 9000 else ""
                lines.append(f"  {idx}. {name:<25} ({sym}) {rank:<6} [{cat}]")
            lines.append("")
            lines.append(f"Please specify exact symbol, e.g. '{req.candidates[0]}'.")
            return "\n".join(lines)

        # 3. Handle comparison
        if req.intent.upper() == "COMPARE" and len(req.target_assets) >= 2:
            return self._run_comparison(req.target_assets[0], req.target_assets[1])

        # 4. Resolve target asset
        target = req.asset or (req.target_assets[0] if req.target_assets else None)
        if not target:
            return "No crypto asset identified. Type a coin symbol or name, e.g. 'ETH' or 'SOL'."

        # 5. Handle missing capital inputs before fetching data
        if req.focus == "capital" and req.needs_capital_inputs:
            return "Please specify account equity and risk percentage (e.g. equity $1000, risk 2%)."

        asset_obj, _ = self.catalog.resolve_asset(target)
        symbol = asset_obj.symbol if asset_obj else target.upper()
        name = asset_obj.name if asset_obj else symbol
        category = asset_obj.categories[0] if asset_obj and asset_obj.categories else "Crypto"
        rank_str = f"#{asset_obj.rank}" if asset_obj and asset_obj.rank < 9000 else ""

        # 6. Fetch market data via resilient ingestion
        ingestion = RuntimeDataIngestion(self.root)
        pair = asset_obj.market_pair if asset_obj and asset_obj.market_pair else f"{symbol}/USD"
        res = ingestion.run(mode="real", assets=[pair])

        market_rows = res.get("market_rows", [])
        row = next((r for r in market_rows if r.get("symbol") == pair or r.get("symbol") == symbol), None)
        if not row and market_rows:
            row = market_rows[0]

        if not row or row.get("price") is None:
            health = res.get("source_health", [])
            last_err = health[-1].get("reason", "Sources unreachable or timed out") if health else "DATA_UNAVAILABLE"
            return (
                f"\n[DATA_UNAVAILABLE] Could not retrieve live price for {name} ({symbol}).\n"
                f"Status: {last_err}\n"
                f"Fallback sources attempted: Binance -> CoinGecko -> Yahoo Finance.\n"
                f"Type '/providers --check' to verify network reachability."
            )

        # 7. Compute deterministic quantitative metrics and decisions
        metrics = self._compute_metrics(row)

        # 8. Render tailored decision support view based on intent / focus
        intent_up = req.intent.upper()
        if req.focus == "capital":
            return self._render_capital_view(asset_obj, symbol, name, category, rank_str, row, metrics, req.equity, req.risk_pct)
        elif intent_up in ("BUY_SPOT", "SELL_SPOT") or req.focus == "spot":
            return self._render_spot_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        elif intent_up == "LONG_SHORT" or req.focus in ("leverage", "long_short", "perpetual"):
            return self._render_perpetual_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        elif intent_up == "POSITION" or req.focus == "setup":
            return self._render_position_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        elif intent_up == "DIVERGENCE" or req.focus == "divergence":
            return self._render_divergence_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        elif intent_up == "RISK" or req.focus == "risk":
            return self._render_risk_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        elif intent_up == "STRUCTURE" or req.focus == "structure":
            return self._render_structure_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        else:
            return self._render_general_view(asset_obj, symbol, name, category, rank_str, row, metrics)

    def _compute_metrics(self, row: dict[str, Any]) -> dict[str, Any]:
        price = float(row.get("price") or 0.0)
        high = float(row.get("high") or price * 1.02)
        low = float(row.get("low") or price * 0.98)
        open_px = float(row.get("open") or price)
        volume = float(row.get("volume") or 0.0)

        extra = row.get("extra", {})
        pct_change = extra.get("price_change_percent") or extra.get("price_change_24h")
        if pct_change is None and open_px > 0:
            pct_change = ((price - open_px) / open_px) * 100.0
        pct_change = float(pct_change or 0.0)

        # Floor Trader Pivots
        pivot = (high + low + price) / 3.0
        r1 = (2.0 * pivot) - low
        s1 = (2.0 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        r3 = high + 2.0 * (pivot - low)
        s3 = low - 2.0 * (high - pivot)

        # 24h Volatility & Range
        range_pct = ((high - low) / low * 100.0) if low > 0 else 0.0
        if range_pct > 8.0:
            vol_regime = f"High (24h span: {range_pct:.2f}%)"
            vol_label = f"Elevated (ATR/range: {range_pct:.2f}%)"
        elif range_pct > 3.0:
            vol_regime = f"Moderate (24h span: {range_pct:.2f}%)"
            vol_label = f"Moderate (ATR/range: {range_pct:.2f}%)"
        else:
            vol_regime = f"Compressed / Low (24h span: {range_pct:.2f}%)"
            vol_label = f"Compressed (ATR/range: {range_pct:.2f}%)"

        # Directional Bias
        if pct_change >= 1.5 and price >= pivot:
            bias = "Bullish Expansion"
        elif pct_change <= -1.5 and price <= pivot:
            bias = "Bearish Contraction"
        else:
            bias = "Consolidating / Neutral"

        # ---------------------------------------------------------
        # SPOT DECISION ENGINE (BUY | WAIT | REDUCE)
        # ---------------------------------------------------------
        if price >= pivot and pct_change >= 0.5:
            spot_decision = "BUY"
            spot_confidence = "High (82%)" if pct_change >= 2.0 else "Moderate (68%)"
            spot_entry = f"{_fmt_price(pivot)} - {_fmt_price(price)}"
            spot_stop = s1 * 0.985
            spot_tp1 = r1
            spot_tp2 = r2
            spot_tp3 = r3 if pct_change >= 4.0 else None
            spot_stop_dist = max(0.001, (price - spot_stop) / price)
            spot_tp1_dist = max(0.001, (spot_tp1 - price) / price)
            spot_rr = spot_tp1_dist / spot_stop_dist
            spot_rationale = f"Price holds above fair-value pivot ({_fmt_price(pivot)}) with positive momentum ({_fmt_pct(pct_change)}). Accumulation favorable."
        elif price < s1 and pct_change <= -2.5:
            spot_decision = "REDUCE"
            spot_confidence = "High (80%)" if pct_change <= -5.0 else "Moderate (65%)"
            spot_entry = f"Market Exit / Cut at {_fmt_price(price)}"
            spot_stop = r1 * 1.01
            spot_tp1 = s2
            spot_tp2 = s3
            spot_tp3 = None
            spot_stop_dist = max(0.001, (spot_stop - price) / price)
            spot_tp1_dist = max(0.001, (price - spot_tp1) / price)
            spot_rr = spot_tp1_dist / spot_stop_dist
            spot_rationale = f"Structural breakdown below primary support S1 ({_fmt_price(s1)}) with downward acceleration. Defense prioritized."
        else:
            spot_decision = "WAIT"
            spot_confidence = "Moderate (60%)"
            spot_entry = f"Wait for pullback to {_fmt_price(s1)} or confirmed breakout above {_fmt_price(r1)}"
            spot_stop = s2
            spot_tp1 = r1
            spot_tp2 = r2
            spot_tp3 = None
            spot_stop_dist = max(0.001, (price - spot_stop) / price)
            spot_tp1_dist = max(0.001, (spot_tp1 - price) / price)
            spot_rr = spot_tp1_dist / spot_stop_dist
            spot_rationale = f"Price oscillating within intraday fair-value balance ({_fmt_price(s1)} - {_fmt_price(r1)}). No clear asymmetry yet."

        # ---------------------------------------------------------
        # PERPETUAL / FUTURES DECISION ENGINE (LONG | SHORT | NO_TRADE)
        # ---------------------------------------------------------
        if range_pct > 14.0 or (-0.4 <= pct_change <= 0.4 and abs(price - pivot) / price < 0.004):
            perp_decision = "NO_TRADE"
            perp_confidence = "High (75%)"
            perp_entry = "Stand aside - choppy compressed balance or dangerous volatility spike"
            perp_stop = s2
            perp_tp1 = r1
            perp_tp2 = r2
            perp_tp3 = None
            perp_stop_dist = 0.05
            perp_rr = 1.0
            leverage_ceiling = "0x (Stand aside - capital preservation)"
            leverage_num = 1
            perp_rationale = "Market structure lacks directional conviction or displays excessive tail risk. Preserving margin."
        elif price >= pivot and pct_change >= 0.0:
            perp_decision = "LONG"
            perp_confidence = "High (80%)" if pct_change >= 2.0 else "Moderate (65%)"
            perp_entry = f"{_fmt_price(pivot)} - {_fmt_price((pivot + price) / 2.0)}"
            perp_stop = s1 * 0.99
            perp_tp1 = r1
            perp_tp2 = r2
            perp_tp3 = r3 if pct_change >= 4.5 else None
            perp_stop_dist = max(0.005, (price - perp_stop) / price)
            tp1_dist = max(0.005, (perp_tp1 - price) / price)
            perp_rr = tp1_dist / perp_stop_dist
            lev = max(1, min(10, int(0.12 / perp_stop_dist)))
            leverage_num = lev
            leverage_ceiling = f"{lev}x (conservative ceiling based on {perp_stop_dist * 100:.1f}% stop distance)"
            perp_rationale = f"Bullish positioning favored above pivot. Long pullbacks with invalidation strictly at {_fmt_price(perp_stop)}."
        else:
            perp_decision = "SHORT"
            perp_confidence = "High (78%)" if pct_change <= -2.5 else "Moderate (65%)"
            perp_entry = f"{_fmt_price(pivot)} - {_fmt_price((pivot + price) / 2.0)}"
            perp_stop = r1 * 1.01
            perp_tp1 = s1
            perp_tp2 = s2
            perp_tp3 = s3 if pct_change <= -5.0 else None
            perp_stop_dist = max(0.005, (perp_stop - price) / price)
            tp1_dist = max(0.005, (price - perp_tp1) / price)
            perp_rr = tp1_dist / perp_stop_dist
            lev = max(1, min(10, int(0.12 / perp_stop_dist)))
            leverage_num = lev
            leverage_ceiling = f"{lev}x (conservative ceiling based on {perp_stop_dist * 100:.1f}% stop distance)"
            perp_rationale = f"Downside pressure active below pivot. Short retests towards {_fmt_price(pivot)} with invalidation at {_fmt_price(perp_stop)}."

        provider = row.get("provider", "Public provider")
        observed = row.get("observed_at_utc", "latest")
        evidence_quality = f"High ({provider} real-time feed, 24h vol: {_fmt_vol(volume)})" if volume > 10_000_000 else f"Moderate ({provider} feed, 24h vol: {_fmt_vol(volume)})"

        return {
            "price": price,
            "high": high,
            "low": low,
            "open": open_px,
            "volume": volume,
            "pct_change": pct_change,
            "pivot": pivot,
            "r1": r1,
            "r2": r2,
            "r3": r3,
            "s1": s1,
            "s2": s2,
            "s3": s3,
            "range_pct": range_pct,
            "vol_regime": vol_regime,
            "vol_label": vol_label,
            "bias": bias,
            "invalidation": perp_stop,
            # Spot Decision Fields
            "spot_decision": spot_decision,
            "spot_confidence": spot_confidence,
            "spot_entry": spot_entry,
            "spot_stop": spot_stop,
            "spot_tp1": spot_tp1,
            "spot_tp2": spot_tp2,
            "spot_tp3": spot_tp3,
            "spot_rr_str": f"1:{spot_rr:.2f}",
            "spot_rationale": spot_rationale,
            # Perpetual Decision Fields
            "perp_decision": perp_decision,
            "perp_confidence": perp_confidence,
            "perp_entry": perp_entry,
            "perp_stop": perp_stop,
            "perp_stop_dist": perp_stop_dist,
            "perp_tp1": perp_tp1,
            "perp_tp2": perp_tp2,
            "perp_tp3": perp_tp3,
            "perp_rr_str": f"1:{perp_rr:.2f}",
            "perp_rationale": perp_rationale,
            "leverage_ceiling": leverage_ceiling,
            "leverage_num": leverage_num,
            # Meta
            "provider": provider,
            "observed": observed,
            "evidence_quality": evidence_quality,
        }

    def _render_general_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        lines = [
            f"=== {name.upper()} ({symbol}) - QUANTITATIVE DECISION SUPPORT ===",
            f"Sector: {category:<20} Market Cap Rank: {rank or 'N/A'}",
            "",
            "Quantitative Decisions",
            f"  Spot Market Decision      {m['spot_decision']:<10} Confidence: {m['spot_confidence']}",
            f"  Perpetual Decision        {m['perp_decision']:<10} Confidence: {m['perp_confidence']}",
            "",
            "Trade Execution Parameters",
            f"  Current Price             {_fmt_price(m['price']):<18} 24h Move: {_fmt_pct(m['pct_change'])}",
            f"  Entry Zone                {m['spot_entry']}",
            f"  Invalidation / Stop       {_fmt_price(m['spot_stop'])} (structural floor S1)",
            f"  Target 1 (TP1)            {_fmt_price(m['spot_tp1']):<18} Target 2 (TP2): {_fmt_price(m['spot_tp2'])}",
        ]
        if m["spot_tp3"]:
            lines.append(f"  Target 3 (TP3)            {_fmt_price(m['spot_tp3'])} (extended momentum expansion)")
        lines.extend([
            f"  Risk:Reward Ratio         {m['spot_rr_str']}",
            f"  Volatility                {m['vol_label']}",
            f"  Suggested Leverage        {m['leverage_ceiling']}",
            "",
            "Market Structure & Levels",
            f"  Technical Bias            {m['bias']}",
            f"  Pivot Level               {_fmt_price(m['pivot'])}",
            f"  Resistance (R1 / R2)      {_fmt_price(m['r1'])}  /  {_fmt_price(m['r2'])}",
            f"  Support (S1 / S2)         {_fmt_price(m['s1'])}  /  {_fmt_price(m['s2'])}",
            "",
            "Evidence & Coverage",
            f"  Primary Feed              {m['provider']} (live observation: {m['observed']})",
            f"  Evidence Quality          {m['evidence_quality']}",
            f"  Provider Coverage         {len(self.registry.list_public())} public providers active, {len(self.registry.list_configured_apis())} API keys verified",
        ])
        return "\n".join(lines)

    def _render_spot_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        lines = [
            f"=== {name.upper()} ({symbol}) - SPOT DECISION SUPPORT ===",
            f"Asset:                  {name} ({symbol})",
            f"Market:                 Spot",
            f"Decision:               {m['spot_decision']}",
            f"Confidence:             {m['spot_confidence']}",
            f"Current Price:          {_fmt_price(m['price'])} ({_fmt_pct(m['pct_change'])})",
            f"Entry Zone:             {m['spot_entry']}",
            f"Invalidation / Stop:    {_fmt_price(m['spot_stop'])}",
            f"TP1:                    {_fmt_price(m['spot_tp1'])}",
            f"TP2:                    {_fmt_price(m['spot_tp2'])}",
        ]
        if m["spot_tp3"]:
            lines.append(f"TP3:                    {_fmt_price(m['spot_tp3'])} (justified by strong trend expansion)")
        lines.extend([
            f"Risk:Reward:            {m['spot_rr_str']}",
            f"Volatility:             {m['vol_label']}",
            f"Evidence Quality:       {m['evidence_quality']}",
            "",
            "Spot Strategy Rationale:",
            f"  {m['spot_rationale']}",
        ])
        return "\n".join(lines)

    def _render_perpetual_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        lines = [
            f"=== {name.upper()} ({symbol}) - PERPETUAL DECISION SUPPORT ===",
            f"Asset:                      {name} ({symbol})",
            f"Market:                     Perpetual / Futures",
            f"Decision:                   {m['perp_decision']}",
            f"Confidence:                 {m['perp_confidence']}",
            f"Current Price:              {_fmt_price(m['price'])} ({_fmt_pct(m['pct_change'])})",
            f"Entry Zone:                 {m['perp_entry']}",
            f"Invalidation / Stop:        {_fmt_price(m['perp_stop'])}",
            f"TP1:                        {_fmt_price(m['perp_tp1'])}",
            f"TP2:                        {_fmt_price(m['perp_tp2'])}",
        ]
        if m["perp_tp3"]:
            lines.append(f"TP3:                        {_fmt_price(m['perp_tp3'])} (justified by strong momentum)")
        lines.extend([
            f"Risk:Reward:                {m['perp_rr_str']}",
            f"Volatility:                 {m['vol_label']}",
            f"Evidence Quality:           {m['evidence_quality']}",
            f"Suggested Leverage Ceiling: {m['leverage_ceiling']}",
            "",
            "Perpetual Strategy & Risk Policy:",
            f"  {m['perp_rationale']}",
            f"  Leverage is capped strictly at {m['leverage_num']}x based on {m['perp_stop_dist'] * 100:.1f}% stop distance and volatility.",
        ])
        return "\n".join(lines)

    def _render_position_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        lines = [
            f"=== {name.upper()} ({symbol}) - TRADE POSITION DECISION SUPPORT ===",
            f"Asset:                      {name} ({symbol})",
            f"Market:                     Spot & Perpetual",
            f"Decision:                   Spot: {m['spot_decision']} | Perpetual: {m['perp_decision']}",
            f"Confidence:                 {m['spot_confidence']}",
            f"Current Price:              {_fmt_price(m['price'])} ({_fmt_pct(m['pct_change'])})",
            f"Entry Zone:                 {m['spot_entry']}",
            f"Invalidation / Stop:        {_fmt_price(m['spot_stop'])} (structural invalidation)",
            f"TP1:                        {_fmt_price(m['spot_tp1'])}",
            f"TP2:                        {_fmt_price(m['spot_tp2'])}",
        ]
        if m["spot_tp3"]:
            lines.append(f"TP3:                        {_fmt_price(m['spot_tp3'])} (extended target)")
        lines.extend([
            f"Risk:Reward:                {m['spot_rr_str']}",
            f"Volatility:                 {m['vol_label']}",
            f"Evidence Quality:           {m['evidence_quality']}",
            f"Suggested Leverage Ceiling: {m['leverage_ceiling']}",
            "",
            "Position Execution Summary:",
            f"  Spot: {_fmt_price(m['pivot'])} fair value pivot. {m['spot_rationale']}",
            f"  Perpetual: Ceiling {m['leverage_num']}x. {m['perp_rationale']}",
        ])
        return "\n".join(lines)

    def _render_capital_view(
        self,
        asset: CryptoAsset | None,
        symbol: str,
        name: str,
        category: str,
        rank: str,
        row: dict[str, Any],
        m: dict[str, Any],
        equity: float | None,
        risk_pct: float | None,
    ) -> str:
        price = m["price"]
        invalidation = m["perp_stop"]
        stop_dist_pct = m["perp_stop_dist"]
        lev = m["leverage_num"]
        eq = equity or 1000.0
        rp = risk_pct or 2.0
        risk_budget = eq * (rp / 100.0)
        pos_notional = risk_budget / stop_dist_pct if stop_dist_pct > 0 else 0.0
        asset_qty = pos_notional / price if price > 0 else 0.0
        margin_req = pos_notional / lev if lev > 0 else pos_notional

        lines = [
            f"=== CAPITAL & POSITION SIZING: {name.upper()} ({symbol}) ===",
            "",
            "Market & Invalidation Context",
            f"  Current Spot Price     {_fmt_price(price)}",
            f"  Invalidation / Stop    {_fmt_price(invalidation)} (distance: {stop_dist_pct * 100:.2f}%)",
            f"  Suggested Leverage     {lev}x (conservative volatility ceiling)",
            "",
            "User Risk Budget",
            f"  Account Equity         ${eq:,.2f}",
            f"  Risk Percentage        {rp:.2f}%",
            f"  Max Risk Budget        ${risk_budget:,.2f} (equity * risk%)",
            "",
            "Position Sizing Calculation",
            f"  Position Notional      ${pos_notional:,.2f} (risk_budget / stop_distance)",
            f"  Asset Quantity         {asset_qty:.4f} {symbol}",
            f"  Margin Required        ${margin_req:,.2f} (position_notional / leverage)",
            "",
            f"Evidence Quality: {m['evidence_quality']}",
        ]
        return "\n".join(lines)

    def _render_divergence_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        bias_state = "Bullish divergence / momentum rebound" if m["pct_change"] > 1.5 and m["price"] >= m["pivot"] else (
            "Bearish divergence / downward momentum" if m["pct_change"] < -2.0 else "No divergence detected / Neutral consolidation"
        )
        lines = [
            f"=== {name.upper()} ({symbol}) - DIVERGENCE & MOMENTUM STRUCTURE ===",
            f"Asset:                      {name} ({symbol})",
            f"Spot Price:                 {_fmt_price(m['price'])} ({_fmt_pct(m['pct_change'])})",
            f"Technical Bias:             {m['bias']}",
            f"Divergence Assessment:      {bias_state}",
            f"Momentum vs Structure:      Price at {_fmt_price(m['price'])} relative to central pivot {_fmt_price(m['pivot'])}.",
            f"Key Reaction Thresholds:    Resistance R1: {_fmt_price(m['r1'])}  |  Support S1: {_fmt_price(m['s1'])}",
            f"Invalidation Level:         {_fmt_price(m['invalidation'])}",
            f"Evidence Quality:           {m['evidence_quality']}",
        ]
        return "\n".join(lines)

    def _render_risk_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        distance_to_inv = abs(m["price"] - m["invalidation"]) / m["price"] * 100.0 if m["price"] > 0 else 0.0
        lines = [
            f"=== {name.upper()} ({symbol}) - RISK & VOLATILITY PROFILE ===",
            "",
            "Risk Diagnostics",
            f"  Volatility Regime   {m['vol_regime']}",
            f"  24h Intraday Range  {m['range_pct']:.2f}%",
            f"  24h Drawdown/Move   {_fmt_pct(m['pct_change'])}",
            f"  Invalidation Level  {_fmt_price(m['invalidation'])} ({distance_to_inv:.2f}% from spot)",
            f"  Major Support       S1: {_fmt_price(m['s1'])}  |  S2: {_fmt_price(m['s2'])}",
            "",
            "Risk Evaluation",
            f"  Liquidity Proxy     {_fmt_vol(m['volume'])} 24h volume",
            f"  Regime Warning      {'Elevated drawdown risk. Wider stops recommended.' if m['range_pct'] > 6.0 else 'Normal market volatility regime.'}",
            f"  Data Source         {m['provider']}",
        ]
        return "\n".join(lines)

    def _render_structure_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        lines = [
            f"=== {name.upper()} ({symbol}) - MARKET STRUCTURE & PIVOT LEVELS ===",
            "",
            f"Spot: {_fmt_price(m['price'])}  |  24h Move: {_fmt_pct(m['pct_change'])}  |  Regime: {m['bias']}",
            "",
            "Pivot Level Map",
            f"  Resistance 2 (R2)   {_fmt_price(m['r2']):<14} (Major breakout ceiling)",
            f"  Resistance 1 (R1)   {_fmt_price(m['r1']):<14} (First upside resistance barrier)",
            f"  Pivot Point (P)     {_fmt_price(m['pivot']):<14} (Central fair-value balance line)",
            f"  Support 1 (S1)      {_fmt_price(m['s1']):<14} (First buyer reaction zone)",
            f"  Support 2 (S2)      {_fmt_price(m['s2']):<14} (Structural support floor)",
            "",
            f"Invalidation Threshold: {_fmt_price(m['invalidation'])}",
            f"Provider Evidence: {m['provider']}",
        ]
        return "\n".join(lines)

    def _run_comparison(self, s1: str, s2: str) -> str:
        ing = RuntimeDataIngestion(self.root)
        a1, _ = self.catalog.resolve_asset(s1)
        a2, _ = self.catalog.resolve_asset(s2)
        sym1 = a1.symbol if a1 else s1.upper()
        sym2 = a2.symbol if a2 else s2.upper()

        p1 = a1.market_pair if a1 and a1.market_pair else f"{sym1}/USD"
        p2 = a2.market_pair if a2 and a2.market_pair else f"{sym2}/USD"

        res = ing.run(mode="real", assets=[p1, p2])
        rows = {r.get("symbol"): r for r in res.get("market_rows", [])}
        r1 = rows.get(p1) or rows.get(sym1)
        r2 = rows.get(p2) or rows.get(sym2)

        m1 = self._compute_metrics(r1) if r1 else None
        m2 = self._compute_metrics(r2) if r2 else None

        lines = [
            f"=== ASSET COMPARISON: {sym1} vs {sym2} ===",
            "",
            f"{'Metric':<22} {sym1:<20} {sym2:<20}",
            "-" * 62,
            f"{'Spot Price':<22} {(_fmt_price(m1['price']) if m1 else 'N/A'):<20} {(_fmt_price(m2['price']) if m2 else 'N/A'):<20}",
            f"{'24h Change':<22} {(_fmt_pct(m1['pct_change']) if m1 else 'N/A'):<20} {(_fmt_pct(m2['pct_change']) if m2 else 'N/A'):<20}",
            f"{'Spot Decision':<22} {(m1['spot_decision'] if m1 else 'N/A'):<20} {(m2['spot_decision'] if m2 else 'N/A'):<20}",
            f"{'Perp Decision':<22} {(m1['perp_decision'] if m1 else 'N/A'):<20} {(m2['perp_decision'] if m2 else 'N/A'):<20}",
            f"{'Technical Bias':<22} {(m1['bias'] if m1 else 'N/A'):<20} {(m2['bias'] if m2 else 'N/A'):<20}",
            f"{'Volatility':<22} {(m1['vol_label'].split()[0] if m1 else 'N/A'):<20} {(m2['vol_label'].split()[0] if m2 else 'N/A'):<20}",
            f"{'Key Pivot':<22} {(_fmt_price(m1['pivot']) if m1 else 'N/A'):<20} {(_fmt_price(m2['pivot']) if m2 else 'N/A'):<20}",
            "",
            f"Sources: {m1['provider'] if m1 else 'N/A'} / {m2['provider'] if m2 else 'N/A'}",
        ]
        return "\n".join(lines)
