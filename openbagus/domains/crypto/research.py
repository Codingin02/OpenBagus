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
from openbagus.intelligence.intent import IntentRequest, SessionState
from openbagus.intelligence.local_language import LocalLanguageEngine


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
        self.local_llm = LocalLanguageEngine(repo_root=self.root)

    def execute(self, req: IntentRequest, session: SessionState | None = None) -> str:
        # 1. Preferences
        if req.request_type == "PREFERENCE":
            if req.preference_action == "hide_sources":
                if session:
                    session.show_sources = False
                return "[PASS] Sources disembunyikan untuk tampilan normal. Ketik '/sources on' untuk menampilkan kembali."
            elif req.preference_action == "show_sources":
                if session:
                    session.show_sources = True
                return "[PASS] Sources diaktifkan untuk setiap analisis."
            elif req.preference_action == "no_ollama":
                return "[PASS] Preferensi disimpan: OpenBagus beroperasi tanpa Ollama menggunakan llama.cpp lokal / deterministik."

        # 2. Feedback handling (Section 2)
        if req.request_type == "FEEDBACK":
            if session and session.last_asset and session.last_quant_result:
                q = session.last_quant_result
                lines = [
                    f"Catatan feedback untuk {q.asset} ({q.market} / {q.timeframe}):",
                    "",
                    f"Keputusan Quant : {q.decision}",
                    f"Alasan          : {q.decision_reason}",
                    "",
                    "OpenBagus beroperasi secara deterministik dan hanya menerbitkan sinyal aktif ketika:",
                    "  1. Rasio Reward:Risk >= 1:1.50 (Risk Gate)",
                    "  2. Microstructure dan aliran order searah tanpa crowding",
                    "",
                    f"Kondisi validasi berikutnya untuk {q.asset}:",
                    f"  Bullish Long  : {q.bullish_validation.trigger_condition if q.bullish_validation else 'Breakout'}",
                    f"  Bearish Short : {q.bearish_validation.trigger_condition if q.bearish_validation else 'Breakdown'}",
                ]
                return "\n".join(lines)
            return (
                "Catatan feedback diterima. OpenBagus memprioritaskan proteksi modal dengan mewajibkan "
                "gerbang konsensus data dan rasio Reward:Risk >= 1:1.50 sebelum memicu sinyal."
            )

        # 3. Harness / Session memory handling (Section 18, 19)
        if req.request_type == "HARNESS":
            if req.preference_action == "clear_harness":
                if session:
                    session.clear()
                return "[PASS] Harness session memory cleared."
            return session.status_display() if session else "OpenBagus Harness\n\nStatus          ACTIVE\nSession Memory  LOCAL / EPHEMERAL\nClear on Exit   YES"

        # 4. System Information & Setup Config
        if req.request_type == "SETUP_CONFIG":
            st = self.local_llm.get_status_info()
            status_label = "TERPASANG / AKTIF" if st.get("available") else "BELUM TERPASANG (Fallback Deterministik Aktif)"
            lines = [
                "OpenBagus Local Language Engine (Qwen 0.6B)",
                "===========================================",
                "Model:          Qwen3-0.6B-Q8_0.gguf (~639 MB)",
                "Inference:      Direct llama.cpp CLI Subprocess (Zero-Ollama, Zero-Server)",
                f"Lokasi Runtime: {st.get('model_path')}",
                f"Status:         {status_label}",
                "",
                "Catatan:",
                "OpenBagus menggunakan mesin kuantitatif deterministik secara default.",
                "Model lokal berukuran < 1 GB ini hanya berperan untuk pemahaman bahasa alami",
                "dan narasi trader, tanpa mengubah keputusan maupun kalkulasi risiko kuantitatif.",
            ]
            return "\n".join(lines)

        if req.request_type == "SYSTEM_INFO":
            return self._render_system_info()

        # 5. Market-wide Outlook
        if req.request_type == "MARKET_OUTLOOK":
            return self._render_market_outlook()

        # 6. Screening and Taxonomy Category View
        if req.request_type in ("CATEGORY", "SCREEN"):
            return self._render_category_or_screen(req)

        # 7. Conversational Follow-up on Previous Levels / Trade Setup
        if req.request_type in ("FOLLOW_UP", "EXPLAIN_LEVELS"):
            if session and session.last_quant_result and session.last_asset == req.asset:
                return self._render_followup_levels_explanation(session.last_quant_result, req.raw_query)

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

        show_sources = session.show_sources if session else False

        if req.intent.upper() == "COMPARE" and len(req.target_assets) >= 2:
            return self._run_comparison(req.target_assets[0], req.target_assets[1], timeframe=req.timeframe, show_sources=show_sources)

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
                    "is_dex": True,
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

        # Timeframe mapping to provider interval
        tf_to_interval = {
            "M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m",
            "H1": "1h", "H4": "4h", "H6": "6h", "H12": "12h",
            "D1": "1d", "W1": "1w",
        }
        interval = tf_to_interval.get(req.timeframe, "1h")

        # Concurrently fetch remaining independent market evidence
        ev = self.zerokey.get_all_evidence(symbol, is_dex=is_dex, interval=interval)
        klines = ev.get("klines") or self.zerokey.get_klines(symbol, interval=interval)
        derivatives = ev.get("derivatives") if not is_dex else None
        orderbook = ev.get("orderbook") if not is_dex else None
        trades = ev.get("trades") if not is_dex else None
        sentiment = ev.get("sentiment") or self.zerokey.get_sentiment()
        stablecoins = ev.get("stablecoins") or self.zerokey.get_stablecoin_tvl()

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
            timeframe=req.timeframe,
        )

        # Update session memory
        if session:
            session.last_asset = symbol
            session.timeframe = req.timeframe
            session.market_type = market_type.upper()
            session.last_quant_result = q
            session.last_candidate_long = q.candidate_long
            session.last_candidate_short = q.candidate_short
            session.last_query = req.raw_query

        if req.focus == "capital":
            return self._render_capital_view(symbol, name, q, req.equity, req.risk_pct)
        elif intent_up == "STRUCTURE" or req.focus == "structure":
            return self._render_structure_view(q, show_sources=show_sources)
        elif intent_up == "RISK" or req.focus == "risk":
            return self._render_risk_view(q, show_sources=show_sources)
        else:
            return self._render_section_25_view(q, market_type=market_type, dex=is_dex, focus=req.focus, show_sources=show_sources)

    def _render_section_25_view(
        self,
        q: QuantDecisionResult,
        market_type: str,
        dex: bool = False,
        focus: str = "general",
        show_sources: bool = False,
    ) -> str:
        mkt_label = "DEX SPOT" if dex else market_type.upper()
        lines = [
            f"{q.asset} / {mkt_label} / {q.timeframe}",
            "",
            f"Decision       {q.decision}",
            f"Regime         {q.regime.capitalize()}",
            f"Data Quality   {q.data_quality.capitalize()}",
            f"Setup Quality  {q.setup_quality.capitalize()}",
            f"Price          {_fmt_price(q.price)}",
        ]

        if q.decision in ("BUY", "LONG", "SHORT", "REDUCE"):
            lines.append(f"Entry          {q.entry_zone}")
            lines.append(f"Stop           {_fmt_price(q.stop_price)}")
            lines.append(f"TP1            {_fmt_price(q.tp1)}")
            lines.append(f"Reward:Risk    {q.reward_risk_str}")
            if market_type.lower() == "perpetual":
                lines.append(f"Leverage       {q.leverage_ceiling}")
        else:
            lines.append(f"Reason         {q.decision_reason}")
            if q.watch_trigger:
                lines.append(f"Watch          {q.watch_trigger}")
            if q.why_now:
                lines.append(f"Why Now        {q.why_now}")

        # Future Validation Scenarios (Section 6, 7)
        if q.bullish_validation and q.bearish_validation:
            lines.append("")
            lines.append("Bullish Validation (LONG)")
            lines.append(f"  Trigger        {q.bullish_validation.trigger_condition}")
            lines.append(f"  Confirmation   {q.bullish_validation.volume_condition}, {q.bullish_validation.order_flow_condition}")
            lines.append(f"  Derivatives    {q.bullish_validation.derivatives_condition}")
            lines.append(f"  Setup          Entry {q.bullish_validation.entry_zone}, Stop {_fmt_price(q.bullish_validation.stop_price)}, TP1 {_fmt_price(q.bullish_validation.tp1)}, TP2 {_fmt_price(q.bullish_validation.tp2)} (R:R {q.bullish_validation.reward_risk_str})")

            lines.append("")
            lines.append("Bearish Validation (SHORT)")
            lines.append(f"  Trigger        {q.bearish_validation.trigger_condition}")
            lines.append(f"  Confirmation   {q.bearish_validation.volume_condition}, {q.bearish_validation.order_flow_condition}")
            lines.append(f"  Derivatives    {q.bearish_validation.derivatives_condition}")
            lines.append(f"  Setup          Entry {q.bearish_validation.entry_zone}, Stop {_fmt_price(q.bearish_validation.stop_price)}, TP1 {_fmt_price(q.bearish_validation.tp1)}, TP2 {_fmt_price(q.bearish_validation.tp2)} (R:R {q.bearish_validation.reward_risk_str})")

        # Cross-Venue Dislocation (Section 8, 9)
        if q.cross_venue_dislocation and q.cross_venue_dislocation.get("available"):
            cv = q.cross_venue_dislocation
            lines.append("")
            lines.append("Cross-Venue")
            lines.append(f"  Dispersion     {cv.get('dispersion_pct', 0.0):.2f}%")
            lines.append(f"  Best Venue     {cv.get('best_venue', 'Market')}")
            lines.append(f"  Dislocation    {cv.get('dislocation_status', 'NORMAL')}")

        # Decision Factors Contribution (Section 14)
        if q.factor_contributions:
            lines.append("")
            lines.append("Decision Factors")
            for factor_name, pct_str in q.factor_contributions.items():
                lines.append(f"  {factor_name:<24} {pct_str}")

        lines.append("")
        lines.append("Summary")
        narrative = self.local_llm.generate_narrative(q, language="id") if self.local_llm.is_available() else None
        lines.append(f"  {narrative or q.narrative}")

        lines.append("")
        lines.append("Why")
        for k, v in q.why.items():
            if market_type.lower() == "spot" and k == "Derivatives" and "No derivatives" in v:
                continue
            lines.append(f"  {k:<14} {v}")

        if show_sources:
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
            f"=== CAPITAL & POSITION SIZING: {name.upper()} ({symbol} / {q.timeframe}) ===",
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
            f"Data Quality: {q.data_quality.capitalize()} | Setup Quality: {q.setup_quality.capitalize()}",
        ]
        return "\n".join(lines)

    def _render_structure_view(self, q: QuantDecisionResult, show_sources: bool = False) -> str:
        lines = [
            f"{q.asset} / MARKET STRUCTURE / {q.timeframe}",
            "",
            f"Spot Price     {_fmt_price(q.price)}",
            f"Regime         {q.regime.capitalize()}",
            f"Data Quality   {q.data_quality.capitalize()}",
            f"Setup Quality  {q.setup_quality.capitalize()}",
            "",
            "Structural Levels",
            f"  Target 1     {_fmt_price(q.tp1) if q.tp1 else '-'}",
            f"  Target 2     {_fmt_price(q.tp2) if q.tp2 else '-'}",
            f"  Invalidation {_fmt_price(q.stop_price) if q.stop_price else '-'}",
        ]

        if q.fibonacci_confluence and q.fibonacci_confluence.get("confluence"):
            lines.append(f"  Fibonacci    {q.fibonacci_confluence.get('confluence')}")

        lines.append("")
        lines.append("Summary")
        lines.append(f"  {q.narrative}")
        lines.append("")
        lines.append("Why")
        for k, v in q.why.items():
            lines.append(f"  {k:<14} {v}")
        if show_sources:
            lines.append("")
            lines.append("Sources")
            lines.append(f"  {', '.join(q.sources)}")
        return "\n".join(lines)

    def _render_risk_view(self, q: QuantDecisionResult, show_sources: bool = False) -> str:
        lines = [
            f"{q.asset} / RISK PROFILE / {q.timeframe}",
            "",
            f"Decision       {q.decision}",
            f"Regime         {q.regime.capitalize()}",
            f"Data Quality   {q.data_quality.capitalize()}",
            f"Setup Quality  {q.setup_quality.capitalize()}",
            f"Price          {_fmt_price(q.price)}",
            f"Invalidation   {_fmt_price(q.stop_price) if q.stop_price else '-'}",
            f"Leverage Limit {q.leverage_ceiling}",
            "",
            "Summary",
            f"  {q.narrative}",
            "",
            "Risk Factors",
        ]
        for k, v in q.why.items():
            lines.append(f"  {k:<14} {v}")
        if show_sources:
            lines.append("")
            lines.append("Sources")
            lines.append(f"  {', '.join(q.sources)}")
        return "\n".join(lines)

    def _run_comparison(self, s1: str, s2: str, timeframe: str = "H1", show_sources: bool = False) -> str:
        a1, _ = self.catalog.resolve_asset(s1)
        a2, _ = self.catalog.resolve_asset(s2)
        sym1 = a1.symbol if a1 else s1.upper()
        sym2 = a2.symbol if a2 else s2.upper()

        tf_to_interval = {"M1": "1m", "M5": "5m", "M15": "15m", "M30": "30m", "H1": "1h", "H4": "4h", "H6": "6h", "H12": "12h", "D1": "1d", "W1": "1w"}
        interval = tf_to_interval.get(timeframe, "1h")

        t1 = self.zerokey.get_spot_ticker(sym1) or {}
        t2 = self.zerokey.get_spot_ticker(sym2) or {}
        k1 = self.zerokey.get_klines(sym1, interval=interval)
        k2 = self.zerokey.get_klines(sym2, interval=interval)
        d1 = self.zerokey.get_derivatives(sym1)
        d2 = self.zerokey.get_derivatives(sym2)
        sent = self.zerokey.get_sentiment()

        q1 = (
            self.quant.evaluate(sym1, t1, klines=k1, derivatives=d1, sentiment=sent, market_type="perpetual" if d1 else "spot", timeframe=timeframe)
            if t1.get("price")
            else None
        )
        q2 = (
            self.quant.evaluate(sym2, t2, klines=k2, derivatives=d2, sentiment=sent, market_type="perpetual" if d2 else "spot", timeframe=timeframe)
            if t2.get("price")
            else None
        )

        lines = [
            f"=== ASSET COMPARISON: {sym1} vs {sym2} ({timeframe}) ===",
            "",
            f"{'Metric':<22} {sym1:<20} {sym2:<20}",
            "-" * 62,
            f"{'Spot Price':<22} {(_fmt_price(q1.price) if q1 else 'N/A'):<20} {(_fmt_price(q2.price) if q2 else 'N/A'):<20}",
            f"{'Decision':<22} {(q1.decision if q1 else 'N/A'):<20} {(q2.decision if q2 else 'N/A'):<20}",
            f"{'Regime':<22} {(q1.regime.capitalize() if q1 else 'N/A'):<20} {(q2.regime.capitalize() if q2 else 'N/A'):<20}",
            f"{'Data Quality':<22} {(q1.data_quality.capitalize() if q1 else 'N/A'):<20} {(q2.data_quality.capitalize() if q2 else 'N/A'):<20}",
            f"{'Setup Quality':<22} {(q1.setup_quality.capitalize() if q1 else 'N/A'):<20} {(q2.setup_quality.capitalize() if q2 else 'N/A'):<20}",
            f"{'Composite Score':<22} {((f'{q1.composite_score:+.2f}') if q1 else 'N/A'):<20} {((f'{q2.composite_score:+.2f}') if q2 else 'N/A'):<20}",
        ]
        if show_sources:
            lines.append("")
            lines.append(f"Sources: {', '.join(q1.sources) if q1 else 'N/A'} / {', '.join(q2.sources) if q2 else 'N/A'}")
        return "\n".join(lines)

    def _render_system_info(self) -> str:
        return self.local_llm.answer_system_question(language="id")

    def _render_market_outlook(self) -> str:
        sent = self.zerokey.get_sentiment()
        tvl = self.zerokey.get_stablecoin_tvl()
        btc = self.zerokey.get_spot_ticker("BTC") or {}

        tvl_val = tvl.get("total_stablecoin_mcap") if tvl else None
        tvl_str = f"${tvl_val / 1e9:.2f}B" if tvl_val else "N/A"
        btc_px = btc.get("price")
        btc_px_str = _fmt_price(btc_px) if btc_px else "N/A"
        btc_chg = _fmt_pct(btc.get("pct_change"))

        lines = [
            "=== CRYPTO MARKET OUTLOOK ===",
            "",
            f"Sentimen Pasar:        {sent.get('classification', 'Neutral')} ({sent.get('value', 50)}/100)",
            f"Likuiditas Stablecoin: {tvl_str} (DefiLlama Top Pegged USD)",
            f"Aset Acuan (BTC):      {btc_px_str} ({btc_chg} 24h)",
            "",
            "Ringkasan Kondisi:",
            f"Pasar kripto saat ini berada dalam rezim sentimen {sent.get('classification', 'Neutral').lower()} dengan likuiditas stablecoin agregat sebesar {tvl_str}.",
            "Struktur harga aset acuan (Bitcoin) memimpin dinamika likuiditas pasar spot dan derivatif.",
            "Ketik simbol koin (misal 'BTC', 'ETH', 'SOL') untuk melihat setup kuantitatif dan analisis risiko spesifik.",
        ]
        return "\n".join(lines)

    def _render_category_or_screen(self, req: IntentRequest) -> str:
        if req.category:
            cat_name, assets = self.catalog.get_category_assets(req.category, limit=10)
            lines = [f"Aset dalam Kategori: {cat_name} ({len(assets)})", "-" * 60]
            for idx, a in enumerate(assets, 1):
                rank = f"#{a.rank}" if a.rank < 9000 else "N/A"
                lines.append(f"  {idx:<2}. {a.name:<24} ({a.symbol:<8}) {rank:<8}")
            lines.append("-" * 60)
            lines.append("Ketik simbol koin langsung untuk analisis (misal 'ETH').")
            return "\n".join(lines)

        assets = sorted(self.catalog.assets, key=lambda x: x.rank)[:10]
        lines = [
            "Crypto Market Screen / Top Assets",
            "================================",
            f"{'#':<4} {'Symbol':<8} {'Name':<24} {'Rank':<8} {'Category':<15}",
            "-" * 65,
        ]
        for idx, a in enumerate(assets, 1):
            rank = f"#{a.rank}" if a.rank < 9000 else "N/A"
            cat = a.categories[0] if a.categories else "General"
            lines.append(f"{idx:<4} {a.symbol:<8} {a.name:<24} {rank:<8} {cat:<15}")
        lines.append("-" * 65)
        lines.append("Ketik simbol koin langsung untuk analisis (misal 'BTC', 'SOL').")
        return "\n".join(lines)

    def _render_followup_levels_explanation(self, q: QuantDecisionResult, raw_query: str) -> str:
        lines = [
            f"Terkait {q.asset} ({q.market} / {q.timeframe}):",
            "",
            f"Keputusan Quant: {q.decision}",
            f"Kualitas Data:   {q.data_quality.capitalize()}",
            f"Kualitas Setup:  {q.setup_quality.capitalize()}",
            f"Harga Saat Ini:  {_fmt_price(q.price)}",
            "",
            "Penjelasan Target TP & Stop Loss (Risk):",
            "QuantEngine HANYA menampilkan level eksekusi (Entry, Stop Loss, dan Take Profit) ketika:",
            "  1. Kualitas Data memadai (Data Quality: High/Moderate)",
            "  2. Terdapat setup asimetris dengan rasio Reward:Risk >= 1:1.50 (Risk Gate)",
            "  3. Sinyal order flow dan momentum selaras tanpa kontradiksi ekstrem",
            "",
            f"Status untuk {q.asset}:",
            f"  Alasan:  {q.decision_reason}",
            f"  Pantau:  {q.watch_trigger}",
            "",
            "Hal ini diterapkan untuk memproteksi modal pengguna agar tidak memaksakan trade pada kondisi tidak menguntungkan.",
        ]
        return "\n".join(lines)
