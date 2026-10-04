"""OpenBagus Coin-Centric Quantitative Crypto Research Engine.

Executes tailored single-asset quantitative analysis based on intent:
- general: market overview, trend, key levels, provider evidence
- setup: trade-setup research view (bias, candidate zone, invalidation, risk/reward context)
- risk: risk regime, drawdown, volatility, distance to invalidation
- structure: support/resistance pivot levels, market structure regime
- compare: side-by-side multi-asset comparison
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
    """Executes single-asset quantitative research pipelines."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.catalog = CryptoAssetCatalog(self.root)
        self.registry = ProviderRegistry(self.root)

    def execute(self, req: IntentRequest) -> str:
        # Handle ambiguity
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

        # Handle comparison
        if req.intent == "compare" and len(req.target_assets) >= 2:
            return self._run_comparison(req.target_assets[0], req.target_assets[1])

        # Resolve asset
        target = req.asset or (req.target_assets[0] if req.target_assets else None)
        if not target:
            return "No crypto asset identified. Type a coin symbol or name, e.g. 'ETH' or 'SOL'."

        asset_obj, _ = self.catalog.resolve_asset(target)
        symbol = asset_obj.symbol if asset_obj else target.upper()
        name = asset_obj.name if asset_obj else symbol
        category = asset_obj.categories[0] if asset_obj and asset_obj.categories else "Crypto"
        rank_str = f"#{asset_obj.rank}" if asset_obj and asset_obj.rank < 9000 else ""

        # Fetch market data via resilient ingestion
        ingestion = RuntimeDataIngestion(self.root)
        pair = asset_obj.market_pair if asset_obj and asset_obj.market_pair else f"{symbol}/USD"
        res = ingestion.run(mode="real", assets=[pair])

        market_rows = res.get("market_rows", [])
        row = next((r for r in market_rows if r.get("symbol") == pair or r.get("symbol") == symbol), None)
        if not row and market_rows:
            row = market_rows[0]

        if not row or row.get("price") is None:
            # Check source health to report exact provider failure status
            health = res.get("source_health", [])
            last_err = health[-1].get("reason", "Sources unreachable or timed out") if health else "Provider timeout"
            return (
                f"\n[DATA GAP] Could not retrieve live price for {name} ({symbol}).\n"
                f"Status: {last_err}\n"
                f"Fallback sources attempted: Binance -> CoinGecko -> Yahoo Finance.\n"
                f"Type '/providers --check' to verify network reachability."
            )

        # Compute quantitative metrics
        metrics = self._compute_metrics(row)

        # Render tailored view based on intent / focus
        if req.focus == "setup" or req.intent == "setup":
            return self._render_setup_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        elif req.focus == "risk" or req.intent == "risk":
            return self._render_risk_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        elif req.focus == "structure" or req.intent == "structure":
            return self._render_structure_view(asset_obj, symbol, name, category, rank_str, row, metrics)
        else:
            return self._render_general_view(asset_obj, symbol, name, category, rank_str, row, metrics)

    def _compute_metrics(self, row: dict[str, Any]) -> dict[str, Any]:
        price = row.get("price") or 0.0
        high = row.get("high") or price * 1.02
        low = row.get("low") or price * 0.98
        open_px = row.get("open") or price
        volume = row.get("volume") or 0.0

        extra = row.get("extra", {})
        pct_change = extra.get("price_change_percent") or extra.get("price_change_24h")
        if pct_change is None and open_px > 0:
            pct_change = ((price - open_px) / open_px) * 100.0

        # Pivot Levels (Floor Trader Pivots)
        pivot = (high + low + price) / 3.0
        r1 = (2.0 * pivot) - low
        s1 = (2.0 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)

        # Volatility & Range
        range_pct = ((high - low) / low * 100.0) if low > 0 else 0.0
        if range_pct > 10.0:
            vol_regime = "High / Elevated Volatility"
        elif range_pct > 4.0:
            vol_regime = "Moderate Volatility"
        else:
            vol_regime = "Compressed / Low Volatility"

        # Directional Bias
        if pct_change is not None and pct_change >= 2.0 and price >= pivot:
            bias = "Bullish Expansion"
            candidate_zone = f"{_fmt_price(pivot)} - {_fmt_price(s1)}"
            invalidation = s1 * 0.985
            scenarios = "Continuation likely if price holds above pivot; watch for breakout past resistance R1."
        elif pct_change is not None and pct_change <= -2.0 and price <= pivot:
            bias = "Bearish Contraction"
            candidate_zone = f"{_fmt_price(r1)} - {_fmt_price(pivot)}"
            invalidation = r1 * 1.015
            scenarios = "Downward pressure dominates; bounce towards pivot may encounter seller absorption."
        else:
            bias = "Neutral / Consolidating"
            candidate_zone = f"{_fmt_price(s1)} - {_fmt_price(pivot)}"
            invalidation = s2
            scenarios = "Range-bound auction within day's high/low. Reversal watch at boundaries."

        provider = row.get("provider", "Public provider")
        observed = row.get("observed_at_utc", "latest")

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
            "s1": s1,
            "s2": s2,
            "range_pct": range_pct,
            "vol_regime": vol_regime,
            "bias": bias,
            "candidate_zone": candidate_zone,
            "invalidation": invalidation,
            "scenarios": scenarios,
            "provider": provider,
            "observed": observed,
        }

    def _render_general_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        lines = [
            f"=== {name.upper()} ({symbol}) - QUANTITATIVE MARKET RESEARCH ===",
            f"Sector: {category:<20} Market Cap Rank: {rank or 'N/A'}",
            "",
            "Market Snapshot",
            f"  Spot Price       {_fmt_price(m['price']):<18} 24h Change   {_fmt_pct(m['pct_change'])}",
            f"  24h High         {_fmt_price(m['high']):<18} 24h Low      {_fmt_price(m['low'])}",
            f"  24h Volume       {_fmt_vol(m['volume']):<18} Vol Regime   {m['vol_regime']}",
            "",
            "Market Structure & Levels",
            f"  Technical Bias   {m['bias']}",
            f"  Pivot Level      {_fmt_price(m['pivot'])}",
            f"  Resistance       R1: {_fmt_price(m['r1'])}  |  R2: {_fmt_price(m['r2'])}",
            f"  Support          S1: {_fmt_price(m['s1'])}  |  S2: {_fmt_price(m['s2'])}",
            f"  Invalidation     {_fmt_price(m['invalidation'])}",
            "",
            "Evidence & Coverage",
            f"  Primary Source   {m['provider']}",
            f"  {self.registry.coverage_summary()}",
        ]
        return "\n".join(lines)

    def _render_setup_view(
        self, asset: CryptoAsset | None, symbol: str, name: str, category: str, rank: str, row: dict[str, Any], m: dict[str, Any]
    ) -> str:
        lines = [
            f"=== {name.upper()} ({symbol}) - TRADE SETUP RESEARCH VIEW ===",
            f"Note: Research-only hypothesis. OpenBagus does not execute orders.",
            "",
            "Setup Hypothesis",
            f"  Directional Bias    {m['bias']}",
            f"  Spot Price          {_fmt_price(m['price'])} ({_fmt_pct(m['pct_change'])})",
            f"  Candidate Zone      {m['candidate_zone']}",
            f"  Invalidation Level  {_fmt_price(m['invalidation'])} (structural invalidation)",
            f"  Target Zones        Target 1: {_fmt_price(m['r1'])}  |  Target 2: {_fmt_price(m['r2'])}",
            "",
            "Risk & Scenario Context",
            f"  Volatility Regime   {m['vol_regime']} (24h span: {m['range_pct']:.2f}%)",
            f"  Primary Scenario    {m['scenarios']}",
            "",
            "Source Quality",
            f"  Data Feed           {m['provider']} (live observation: {m['observed']})",
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
            f"{'Metric':<22} {sym1:<18} {sym2:<18}",
            "-" * 58,
            f"{'Spot Price':<22} {(_fmt_price(m1['price']) if m1 else 'N/A'):<18} {(_fmt_price(m2['price']) if m2 else 'N/A'):<18}",
            f"{'24h Change':<22} {(_fmt_pct(m1['pct_change']) if m1 else 'N/A'):<18} {(_fmt_pct(m2['pct_change']) if m2 else 'N/A'):<18}",
            f"{'24h Volume':<22} {(_fmt_vol(m1['volume']) if m1 else 'N/A'):<18} {(_fmt_vol(m2['volume']) if m2 else 'N/A'):<18}",
            f"{'Technical Bias':<22} {(m1['bias'] if m1 else 'N/A'):<18} {(m2['bias'] if m2 else 'N/A'):<18}",
            f"{'Volatility Regime':<22} {(m1['vol_regime'].split()[0] if m1 else 'N/A'):<18} {(m2['vol_regime'].split()[0] if m2 else 'N/A'):<18}",
            f"{'Key Pivot':<22} {(_fmt_price(m1['pivot']) if m1 else 'N/A'):<18} {(_fmt_price(m2['pivot']) if m2 else 'N/A'):<18}",
            "",
            f"Sources: {m1['provider'] if m1 else 'N/A'} / {m2['provider'] if m2 else 'N/A'}",
        ]
        return "\n".join(lines)
