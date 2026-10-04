"""OpenBagus Coin-Centric Quantitative Crypto Research & Decision Engine."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.data.ingestion import RuntimeDataIngestion
from openbagus.data.providers import ProviderRegistry
from openbagus.data.zerokey import ZeroKeyMarketData
from openbagus.domains.crypto.catalog import CryptoAsset, CryptoAssetCatalog
from openbagus.domains.crypto.quant import QuantDecisionResult, QuantEngine
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
    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.catalog = CryptoAssetCatalog(self.root)
        self.registry = ProviderRegistry(self.root)
        self.zerokey = ZeroKeyMarketData(timeout=3.5)
        self.quant = QuantEngine()

    def execute(self, req: IntentRequest) -> str:
        if req.needs_asset:
            return req.clarification_prompt or "Which asset do you want to analyze?"

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

        if req.intent.upper() == "COMPARE" and len(req.target_assets) >= 2:
            return self._run_comparison(req.target_assets[0], req.target_assets[1])

        target = req.asset or (req.target_assets[0] if req.target_assets else None)
        if not target:
            return "No crypto asset identified. Type a coin symbol or name, e.g. 'ETH' or 'SOL'."

        if req.focus == "capital" and req.needs_capital_inputs:
            return "Please specify account equity and risk percentage (e.g. equity $1000, risk 2%)."

        asset_obj, _ = self.catalog.resolve_asset(target)
        symbol = asset_obj.symbol if asset_obj else target.upper()
        name = asset_obj.name if asset_obj else symbol

        ticker = self.zerokey.get_spot_ticker(symbol)
        is_dex = False
        if not ticker:
            pool = self.zerokey.get_dex_pool(symbol)
            if pool:
                is_dex = True
                price_usd = float(pool.get("price_usd") or 0.0)
                vol_usd = float(pool.get("volume_24h") or 0.0)
                ticker = {
                    "symbol": symbol,
                    "price": price_usd,
                    "open": None,
                    "high": price_usd * 1.02,
                    "low": price_usd * 0.98,
                    "volume": vol_usd,
                    "quote_volume": vol_usd,
                    "pct_change": 0.0,
                    "bid": None,
                    "ask": None,
                    "provider": pool.get("provider", "GeckoTerminal DEX"),
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            else:
                pair = asset_obj.market_pair if asset_obj and asset_obj.market_pair else f"{symbol}/USD"
                res = RuntimeDataIngestion(self.root).run(mode="real", assets=[pair])
                rows = res.get("market_rows", [])
                if rows and rows[0].get("price"):
                    r = rows[0]
                    p = float(r.get("price") or 0.0)
                    ticker = {
                        "symbol": symbol,
                        "price": p,
                        "open": r.get("open"),
                        "high": r.get("high") or (p * 1.02),
                        "low": r.get("low") or (p * 0.98),
                        "volume": r.get("volume") or 0.0,
                        "quote_volume": r.get("volume") or 0.0,
                        "pct_change": 0.0,
                        "bid": None,
                        "ask": None,
                        "provider": r.get("provider", "RuntimeDataIngestion"),
                        "observed_at": r.get("observed_at_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                    }

        if not ticker or ticker.get("price") is None:
            return (
                f"\n[DATA_UNAVAILABLE] Could not retrieve live market data for {name} ({symbol}).\n"
                f"Status: Zero-key public providers (Binance, Gate.io, Bybit, OKX, GeckoTerminal, CoinLore) did not return quotes.\n"
                f"Type '/providers --check' to verify network reachability."
            )

        klines = self.zerokey.get_klines(symbol)
        derivatives = None if is_dex else self.zerokey.get_derivatives(symbol)
        orderbook = None if is_dex else self.zerokey.get_orderbook(symbol)
        trades = None if is_dex else self.zerokey.get_recent_trades(symbol)
        sentiment = self.zerokey.get_sentiment()
        stablecoins = self.zerokey.get_stablecoin_tvl()

        intent_up = req.intent.upper()
        if intent_up in ("LONG_SHORT", "FUNDING", "OPEN_INTEREST") or req.focus in ("leverage", "long_short", "perpetual"):
            market_type = "perpetual"
        elif intent_up in ("BUY_SPOT", "SELL_SPOT") or req.focus == "spot":
            market_type = "spot"
        else:
            market_type = "perpetual" if derivatives is not None else "spot"

        q = self.quant.evaluate(
            symbol=symbol,
            spot_ticker=ticker,
            klines=klines,
            derivatives=derivatives,
            orderbook=orderbook,
            trades=trades,
            sentiment=sentiment,
            stablecoins=stablecoins,
            market_type=market_type,
        )

        if req.focus == "capital":
            return self._render_capital_view(symbol, name, q, req.equity, req.risk_pct)
        elif intent_up == "STRUCTURE" or req.focus == "structure":
            return self._render_structure_view(q)
        elif intent_up == "RISK" or req.focus == "risk":
            return self._render_risk_view(q)
        else:
            return self._render_section_25_view(q, market_type=market_type, dex=is_dex, focus=req.focus)

    def _render_section_25_view(
        self, q: QuantDecisionResult, market_type: str, dex: bool = False, focus: str = "general"
    ) -> str:
        mkt_label = "DEX SPOT" if dex else market_type.upper()
        if q.decision in ("BUY", "LONG", "SHORT", "REDUCE"):
            entry_str = q.entry_zone
            stop_str = _fmt_price(q.stop_price)
            tp1_str = _fmt_price(q.tp1)
            rr_str = q.reward_risk_str
            lev_str = q.leverage_ceiling
        elif focus == "setup":
            entry_str = q.entry_zone
            stop_str = _fmt_price(q.stop_price) if q.stop_price else "-"
            tp1_str = _fmt_price(q.tp1) if q.tp1 else "-"
            rr_str = q.reward_risk_str if q.reward_risk else "-"
            lev_str = "-"
        else:
            entry_str = "-"
            stop_str = "-"
            tp1_str = "-"
            rr_str = "-"
            lev_str = "-"

        lines = [
            f"{q.asset} / {mkt_label}",
            "",
            f"Decision       {q.decision}",
            f"Regime         {q.regime.capitalize()}",
            f"Evidence       {q.confidence.capitalize()}",
            f"Price          {_fmt_price(q.price)}",
            f"Entry          {entry_str}",
            f"Stop           {stop_str}",
            f"TP1            {tp1_str}",
            f"Reward:Risk    {rr_str}",
        ]
        if market_type.lower() == "perpetual":
            lines.append(f"Leverage       {lev_str}")

        lines.append("")
        lines.append("Why")
        for k, v in q.why.items():
            if market_type.lower() == "spot" and k == "Derivatives" and "No derivatives" in v:
                continue
            lines.append(f"  {k:<14} {v}")

        lines.append("")
        lines.append("Sources")
        lines.append(f"  {', '.join(q.sources)}")
        return "\n".join(lines)

    def _render_capital_view(
        self,
        symbol: str,
        name: str,
        q: QuantDecisionResult,
        equity: float | None,
        risk_pct: float | None,
    ) -> str:
        price = q.price
        stop_price = q.stop_price or (price * 0.95)
        stop_dist_pct = abs(price - stop_price) / price if price > 0 else 0.05
        lev = q.leverage_num if q.leverage_num > 0 else 1
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
            f"  Invalidation / Stop    {_fmt_price(stop_price)} (distance: {stop_dist_pct * 100:.2f}%)",
            f"  Suggested Leverage     {lev}x (conservative ceiling; max {self.quant.hard_leverage_max}x policy)",
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
            f"Evidence Quality: {q.confidence.capitalize()} ({q.evidence_count} independent sources, quality: {q.composite_quality:.2f})",
        ]
        return "\n".join(lines)

    def _render_structure_view(self, q: QuantDecisionResult) -> str:
        lines = [
            f"{q.asset} / MARKET STRUCTURE",
            "",
            f"Spot Price     {_fmt_price(q.price)}",
            f"Regime         {q.regime.capitalize()}",
            f"Evidence       {q.confidence.capitalize()}",
            "",
            "Structural Levels",
            f"  Target 1     {_fmt_price(q.tp1) if q.tp1 else '-'}",
            f"  Target 2     {_fmt_price(q.tp2) if q.tp2 else '-'}",
            f"  Invalidation {_fmt_price(q.stop_price) if q.stop_price else '-'}",
            "",
            "Why",
        ]
        for k, v in q.why.items():
            lines.append(f"  {k:<14} {v}")
        lines.append("")
        lines.append("Sources")
        lines.append(f"  {', '.join(q.sources)}")
        return "\n".join(lines)

    def _render_risk_view(self, q: QuantDecisionResult) -> str:
        lines = [
            f"{q.asset} / RISK PROFILE",
            "",
            f"Decision       {q.decision}",
            f"Regime         {q.regime.capitalize()}",
            f"Evidence       {q.confidence.capitalize()}",
            f"Price          {_fmt_price(q.price)}",
            f"Invalidation   {_fmt_price(q.stop_price) if q.stop_price else '-'}",
            f"Leverage Limit {q.leverage_ceiling}",
            "",
            "Risk Factors",
        ]
        for k, v in q.why.items():
            lines.append(f"  {k:<14} {v}")
        lines.append("")
        lines.append("Sources")
        lines.append(f"  {', '.join(q.sources)}")
        return "\n".join(lines)

    def _run_comparison(self, s1: str, s2: str) -> str:
        a1, _ = self.catalog.resolve_asset(s1)
        a2, _ = self.catalog.resolve_asset(s2)
        sym1 = a1.symbol if a1 else s1.upper()
        sym2 = a2.symbol if a2 else s2.upper()

        t1 = self.zerokey.get_spot_ticker(sym1) or {}
        t2 = self.zerokey.get_spot_ticker(sym2) or {}
        k1 = self.zerokey.get_klines(sym1)
        k2 = self.zerokey.get_klines(sym2)
        d1 = self.zerokey.get_derivatives(sym1)
        d2 = self.zerokey.get_derivatives(sym2)
        sent = self.zerokey.get_sentiment()

        q1 = (
            self.quant.evaluate(sym1, t1, klines=k1, derivatives=d1, sentiment=sent, market_type="perpetual" if d1 else "spot")
            if t1.get("price")
            else None
        )
        q2 = (
            self.quant.evaluate(sym2, t2, klines=k2, derivatives=d2, sentiment=sent, market_type="perpetual" if d2 else "spot")
            if t2.get("price")
            else None
        )

        lines = [
            f"=== ASSET COMPARISON: {sym1} vs {sym2} ===",
            "",
            f"{'Metric':<22} {sym1:<20} {sym2:<20}",
            "-" * 62,
            f"{'Spot Price':<22} {(_fmt_price(q1.price) if q1 else 'N/A'):<20} {(_fmt_price(q2.price) if q2 else 'N/A'):<20}",
            f"{'Decision':<22} {(q1.decision if q1 else 'N/A'):<20} {(q2.decision if q2 else 'N/A'):<20}",
            f"{'Regime':<22} {(q1.regime.capitalize() if q1 else 'N/A'):<20} {(q2.regime.capitalize() if q2 else 'N/A'):<20}",
            f"{'Evidence':<22} {(q1.confidence.capitalize() if q1 else 'N/A'):<20} {(q2.confidence.capitalize() if q2 else 'N/A'):<20}",
            f"{'Composite Score':<22} {((f'{q1.composite_score:+.2f}') if q1 else 'N/A'):<20} {((f'{q2.composite_score:+.2f}') if q2 else 'N/A'):<20}",
            "",
            f"Sources: {', '.join(q1.sources) if q1 else 'N/A'} / {', '.join(q2.sources) if q2 else 'N/A'}",
        ]
        return "\n".join(lines)
