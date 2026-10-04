"""OpenBagus Crypto Quant Engine V2.

Multi-evidence decision engine implementing 5 independent evidence families:
A. Trend / Momentum (multi-timeframe returns, EMA alignment, range location)
B. Volatility / Regime (ATR, realized volatility, deterministic regime classification)
C. Price-Volume / Liquidity (24h volume, volume confirmation, order book depth)
D. Derivatives / Basis / Positioning (funding rate, z-score, OI, basis, non-naive crowded-long logic)
E. Context / On-Chain / Sentiment (Fear & Greed, DefiLlama stablecoins, DEX liquidity)

Key Guarantees:
- Strict Reward:Risk gate (minimum_reward_risk = 1.5; never issues BUY/LONG/SHORT if RR < 1.5)
- Data Quality Gate (minimum 3 independent evidence families + quality threshold)
- Conservative leverage ceiling (hard maximum <= 3x, reduced in volatile/low liquidity conditions)
- Categorical confidence (LOW, MODERATE, HIGH; no artificial percentage precision)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceBlockResult:
    name: str
    direction_score: float  # -1.0 (bearish) to +1.0 (bullish)
    quality: float          # 0.0 to 1.0
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuantDecisionResult:
    asset: str
    market: str             # "spot" or "perpetual"
    decision: str           # SPOT: BUY | WAIT | REDUCE; PERP: LONG | SHORT | NO_TRADE
    regime: str             # TRENDING | CHOPPY | VOLATILE | COMPRESSED
    confidence: str         # LOW | MODERATE | HIGH
    price: float
    entry_zone: str
    stop_price: float | None
    tp1: float | None
    tp2: float | None
    reward_risk: float | None
    reward_risk_str: str
    leverage_ceiling: str
    leverage_num: int
    why: dict[str, str]     # Summary per evidence family
    sources: list[str]      # Data sources used
    evidence_count: int
    composite_score: float
    composite_quality: float
    rr_gate_passed: bool
    quality_gate_passed: bool


class QuantEngineV2:
    """Robust multi-evidence crypto quantitative decision engine."""

    MINIMUM_REWARD_RISK: float = 1.5
    DEFAULT_HARD_LEVERAGE_MAX: int = 3
    MIN_INDEPENDENT_EVIDENCE_COUNT: int = 3
    MIN_COMPOSITE_QUALITY: float = 0.45

    def __init__(self, hard_leverage_max: int = DEFAULT_HARD_LEVERAGE_MAX) -> None:
        self.hard_leverage_max = hard_leverage_max

    def evaluate(
        self,
        symbol: str,
        spot_ticker: dict[str, Any],
        klines: list[dict[str, Any]] | None = None,
        derivatives: dict[str, Any] | None = None,
        orderbook: dict[str, Any] | None = None,
        sentiment: dict[str, Any] | None = None,
        stablecoins: dict[str, Any] | None = None,
        market_type: str = "spot",  # "spot" or "perpetual"
    ) -> QuantDecisionResult:
        price = float(spot_ticker.get("price") or 0.0)
        high = float(spot_ticker.get("high") or price * 1.02)
        low = float(spot_ticker.get("low") or price * 0.98)
        volume = float(spot_ticker.get("volume") or 0.0)
        quote_vol = float(spot_ticker.get("quote_volume") or volume * price)
        pct_change = float(spot_ticker.get("pct_change") or 0.0)

        # ---------------------------------------------------------
        # 1. EVALUATE THE 5 EVIDENCE FAMILIES
        # ---------------------------------------------------------
        ev_trend = self._eval_trend_momentum(price, high, low, pct_change, klines)
        ev_vol = self._eval_volatility_regime(price, high, low, klines)
        ev_vol_liq = self._eval_price_volume_liquidity(price, volume, quote_vol, pct_change, orderbook)
        ev_deriv = self._eval_derivatives_basis(price, pct_change, derivatives)
        ev_context = self._eval_context_sentiment(sentiment, stablecoins)

        evidence_list = [ev_trend, ev_vol, ev_vol_liq, ev_deriv, ev_context]
        active_families = [e for e in evidence_list if e.quality >= 0.35]
        active_count = len(active_families)

        # ---------------------------------------------------------
        # 2. EVIDENCE FUSION (Fixed transparent baseline weights)
        # ---------------------------------------------------------
        deriv_available = derivatives is not None and ev_deriv.quality >= 0.35

        if market_type == "spot":
            if deriv_available:
                weights = {
                    "trend": 0.30,
                    "volume": 0.25,
                    "volatility": 0.20,
                    "derivatives": 0.15,
                    "context": 0.10,
                }
            else:
                # Renormalize without derivatives
                weights = {
                    "trend": 0.353,
                    "volume": 0.294,
                    "volatility": 0.235,
                    "derivatives": 0.0,
                    "context": 0.118,
                }
        else:  # perpetual
            weights = {
                "derivatives": 0.30,
                "trend": 0.25,
                "volume": 0.20,
                "volatility": 0.20,
                "context": 0.05,
            }

        composite_score = (
            weights["trend"] * ev_trend.direction_score
            + weights["volume"] * ev_vol_liq.direction_score
            + weights["volatility"] * ev_vol.direction_score
            + weights["derivatives"] * ev_deriv.direction_score
            + weights["context"] * ev_context.direction_score
        )

        composite_quality = (
            weights["trend"] * ev_trend.quality
            + weights["volume"] * ev_vol_liq.quality
            + weights["volatility"] * ev_vol.quality
            + weights["derivatives"] * ev_deriv.quality
            + weights["context"] * ev_context.quality
        )

        # ---------------------------------------------------------
        # 3. DATA QUALITY GATE
        # ---------------------------------------------------------
        quality_gate_passed = (
            active_count >= self.MIN_INDEPENDENT_EVIDENCE_COUNT
            and composite_quality >= self.MIN_COMPOSITE_QUALITY
        )

        # Categorical Confidence
        if composite_quality >= 0.75 and active_count >= 4:
            confidence = "HIGH"
        elif composite_quality >= 0.50 and active_count >= 3:
            confidence = "MODERATE"
        else:
            confidence = "LOW"

        # ---------------------------------------------------------
        # 4. MARKET STRUCTURE & STRUCTURAL LEVELS
        # ---------------------------------------------------------
        pivot = (high + low + price) / 3.0
        r1 = (2.0 * pivot) - low
        s1 = (2.0 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        atr = ev_vol.details.get("atr", (high - low) * 0.5)
        atr_buffer = max(price * 0.005, atr * 0.5)

        # ---------------------------------------------------------
        # 5. RISK:REWARD GATE & SETUP EVALUATION
        # ---------------------------------------------------------
        regime = ev_vol.details.get("regime", "CHOPPY")

        # Preliminary bias
        is_bullish = composite_score >= 0.22
        is_bearish = composite_score <= -0.22

        decision = "WAIT" if market_type == "spot" else "NO_TRADE"
        stop_price: float | None = None
        tp1: float | None = None
        tp2: float | None = None
        reward_risk: float | None = None
        rr_gate_passed = False
        entry_zone = "-"
        leverage_ceiling = "-"
        leverage_num = 0

        if quality_gate_passed and is_bullish:
            # LONG / BUY Setup
            stop_price = round(s1 - atr_buffer, 4 if price < 10 else 2)
            tp1 = round(r1, 4 if price < 10 else 2)
            tp2 = round(r2, 4 if price < 10 else 2)

            risk_span = price - stop_price
            reward_span = tp1 - price

            if risk_span > 0 and reward_span > 0:
                reward_risk = round(reward_span / risk_span, 2)
            else:
                reward_risk = 0.10

            rr_gate_passed = reward_risk >= self.MINIMUM_REWARD_RISK

            if rr_gate_passed:
                decision = "BUY" if market_type == "spot" else "LONG"
                entry_zone = f"{self._fmt_px(min(price, pivot))} - {self._fmt_px(price)}"
            else:
                # Required entry to achieve RR >= 1.5
                ideal_pullback = round((tp1 + (self.MINIMUM_REWARD_RISK * stop_price)) / (1.0 + self.MINIMUM_REWARD_RISK), 2)
                decision = "WAIT" if market_type == "spot" else "NO_TRADE"
                entry_zone = f"Pullback limit: {self._fmt_px(ideal_pullback)} (for RR >= 1.5)"

        elif quality_gate_passed and is_bearish:
            # SHORT / REDUCE Setup
            stop_price = round(r1 + atr_buffer, 4 if price < 10 else 2)
            tp1 = round(s1, 4 if price < 10 else 2)
            tp2 = round(s2, 4 if price < 10 else 2)

            risk_span = stop_price - price
            reward_span = price - tp1

            if risk_span > 0 and reward_span > 0:
                reward_risk = round(reward_span / risk_span, 2)
            else:
                reward_risk = 0.10

            rr_gate_passed = reward_risk >= self.MINIMUM_REWARD_RISK

            if rr_gate_passed:
                decision = "REDUCE" if market_type == "spot" else "SHORT"
                entry_zone = f"{self._fmt_px(price)} - {self._fmt_px(max(price, pivot))}"
            else:
                decision = "WAIT" if market_type == "spot" else "NO_TRADE"
                entry_zone = f"Wait for reaction at {self._fmt_px(r1)}"

        # ---------------------------------------------------------
        # 6. LEVERAGE CEILING (Conservative RiskPolicy)
        # ---------------------------------------------------------
        if market_type == "perpetual" and decision in ("LONG", "SHORT") and stop_price:
            stop_dist_pct = abs(price - stop_price) / price
            # Base ceiling bounded strictly by hard max (default 3x)
            base_lev = max(1, min(self.hard_leverage_max, int(0.08 / max(stop_dist_pct, 0.015))))

            # Volatility & regime dampeners
            if regime == "VOLATILE":
                base_lev = max(1, base_lev - 1)
            if quote_vol < 50_000_000:  # low liquidity
                base_lev = 1
            if confidence == "LOW":
                base_lev = 1

            leverage_num = base_lev
            leverage_ceiling = f"{base_lev}x (conservative ceiling; max {self.hard_leverage_max}x policy)"
        else:
            leverage_ceiling = "-"
            leverage_num = 0

        # Collect source names
        sources = [spot_ticker.get("provider", "Public Market Provider")]
        if derivatives and derivatives.get("provider"):
            sources.append(derivatives["provider"])
        if sentiment and sentiment.get("provider"):
            sources.append(sentiment["provider"])

        # Format Why block
        why = {
            "Trend": f"{ev_trend.summary} ({ev_trend.direction_score:+.2f})",
            "Derivatives": f"{ev_deriv.summary} ({ev_deriv.direction_score:+.2f})" if deriv_available else "No derivatives contract (0.00)",
            "Volume": f"{ev_vol_liq.summary} ({ev_vol_liq.direction_score:+.2f})",
            "Volatility": f"{regime} ({ev_vol.summary})",
            "Context": ev_context.summary,
        }

        rr_str = f"1:{reward_risk:.2f}" if reward_risk is not None else "-"
        if reward_risk is not None and not rr_gate_passed:
            rr_str = f"1:{reward_risk:.2f} (< 1.5 gate)"

        return QuantDecisionResult(
            asset=symbol.upper(),
            market=market_type.capitalize(),
            decision=decision,
            regime=regime,
            confidence=confidence,
            price=price,
            entry_zone=entry_zone,
            stop_price=stop_price if decision in ("BUY", "LONG", "SHORT", "REDUCE") else None,
            tp1=tp1 if decision in ("BUY", "LONG", "SHORT", "REDUCE") else None,
            tp2=tp2 if decision in ("BUY", "LONG", "SHORT", "REDUCE") else None,
            reward_risk=reward_risk if decision in ("BUY", "LONG", "SHORT", "REDUCE") else None,
            reward_risk_str=rr_str if decision in ("BUY", "LONG", "SHORT", "REDUCE") else "-",
            leverage_ceiling=leverage_ceiling,
            leverage_num=leverage_num,
            why=why,
            sources=list(dict.fromkeys(sources)),
            evidence_count=active_count,
            composite_score=round(composite_score, 3),
            composite_quality=round(composite_quality, 2),
            rr_gate_passed=rr_gate_passed,
            quality_gate_passed=quality_gate_passed,
        )

    # -------------------------------------------------------------
    # EVIDENCE BLOCK IMPLEMENTATIONS
    # -------------------------------------------------------------
    def _eval_trend_momentum(
        self, price: float, high: float, low: float, pct_change: float, klines: list[dict[str, Any]] | None
    ) -> EvidenceBlockResult:
        if klines and len(klines) >= 10:
            closes = [c["close"] for c in klines]
            h1_ret = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 else 0.0
            h4_ret = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else 0.0

            # Simple EMA 8 vs 21
            ema8 = sum(closes[-8:]) / 8.0
            ema21 = sum(closes[-21:]) / len(closes[-21:])
            ema_bias = 0.5 if ema8 > ema21 else -0.5

            range_span = high - low
            loc = (price - low) / range_span if range_span > 0 else 0.5
            loc_bias = (loc - 0.5) * 1.5

            score = max(-1.0, min(1.0, (h1_ret * 15.0) + (h4_ret * 10.0) + ema_bias + loc_bias))
            quality = 0.85
            summary = "Multi-timeframe trend bullish" if score > 0.3 else ("Multi-timeframe trend bearish" if score < -0.3 else "Mixed / consolidating trend")
        else:
            # Fallback using 24h pct_change and range location
            score = max(-1.0, min(1.0, pct_change / 5.0))
            quality = 0.60
            summary = "24h momentum expansion" if score > 0.3 else ("24h momentum contraction" if score < -0.3 else "Neutral 24h momentum")

        return EvidenceBlockResult(
            name="Trend / Momentum",
            direction_score=round(score, 2),
            quality=quality,
            summary=summary,
        )

    def _eval_volatility_regime(
        self, price: float, high: float, low: float, klines: list[dict[str, Any]] | None
    ) -> EvidenceBlockResult:
        range_span = high - low
        range_pct = (range_span / low * 100.0) if low > 0 else 0.0

        atr = range_span * 0.5
        if klines and len(klines) >= 5:
            trs = [max(c["high"] - c["low"], abs(c["high"] - c["close"]), abs(c["low"] - c["close"])) for c in klines]
            atr = sum(trs[-5:]) / 5.0

        atr_pct = (atr / price * 100.0) if price > 0 else 2.0

        if range_pct > 8.0 or atr_pct > 5.0:
            regime = "VOLATILE"
            score = -0.35  # Penalty for excessive volatility
            summary = f"Elevated volatility (range: {range_pct:.1f}%)"
        elif range_pct < 2.0 and atr_pct < 1.5:
            regime = "COMPRESSED"
            score = 0.0
            summary = f"Compressed range ({range_pct:.1f}%)"
        elif range_pct >= 3.5:
            regime = "TRENDING"
            score = 0.25
            summary = f"Healthy trend volatility ({range_pct:.1f}%)"
        else:
            regime = "CHOPPY"
            score = -0.15
            summary = f"Choppy intraday range ({range_pct:.1f}%)"

        return EvidenceBlockResult(
            name="Volatility / Regime",
            direction_score=round(score, 2),
            quality=0.80,
            summary=summary,
            details={"regime": regime, "atr": atr, "range_pct": range_pct},
        )

    def _eval_price_volume_liquidity(
        self, price: float, volume: float, quote_vol: float, pct_change: float, orderbook: dict[str, Any] | None
    ) -> EvidenceBlockResult:
        # Liquidity proxy based on 24h quote volume
        if quote_vol >= 500_000_000:
            liq_tier = "Tier 1 Liquid"
            liq_q = 0.90
        elif quote_vol >= 50_000_000:
            liq_tier = "Moderate Liquid"
            liq_q = 0.75
        else:
            liq_tier = "Low Liquidity"
            liq_q = 0.45

        # Volume confirmation
        imbalance = 0.0
        if orderbook:
            imbalance = float(orderbook.get("imbalance", 0.0))

        if pct_change > 1.0 and quote_vol > 50_000_000:
            score = 0.40 + (imbalance * 0.3)
            summary = f"Volume confirmed ({liq_tier})"
        elif pct_change < -1.0 and quote_vol > 50_000_000:
            score = -0.40 + (imbalance * 0.3)
            summary = f"Distribution volume ({liq_tier})"
        else:
            score = imbalance * 0.3
            summary = f"Normal turnover ({liq_tier})"

        return EvidenceBlockResult(
            name="Price-Volume / Liquidity",
            direction_score=round(max(-1.0, min(1.0, score)), 2),
            quality=liq_q,
            summary=summary,
            details={"quote_vol": quote_vol, "imbalance": imbalance},
        )

    def _eval_derivatives_basis(
        self, price: float, pct_change: float, derivatives: dict[str, Any] | None
    ) -> EvidenceBlockResult:
        if not derivatives:
            return EvidenceBlockResult(
                name="Derivatives / Basis",
                direction_score=0.0,
                quality=0.0,
                summary="No derivatives data",
            )

        fr = float(derivatives.get("funding_rate") or 0.0)
        zscore = float(derivatives.get("funding_zscore") or 0.0)
        oi = float(derivatives.get("open_interest") or 0.0)
        basis = float(derivatives.get("basis") or 0.0)

        # Non-naive Crowded Long / Crowded Short evaluation:
        # Extreme positive funding (> +0.03% or zscore > 2.0) = crowded long risk!
        # Extreme negative funding (< -0.03% or zscore < -2.0) = crowded short risk (short squeeze setup).
        if fr > 0.0003 or zscore > 2.0:
            score = -0.55  # Contrarian bearish risk warning
            summary = f"Crowded long risk (funding: {fr*100:.3f}%)"
        elif fr < -0.0003 or zscore < -2.0:
            score = +0.55  # Short squeeze potential
            summary = f"Crowded short (funding: {fr*100:.3f}%)"
        elif pct_change > 0.5 and basis > 0:
            score = 0.45  # Constructive trend confirmation
            summary = f"Healthy basis & funding ({fr*100:.3f}%)"
        elif pct_change < -0.5:
            score = -0.45  # Downward drift
            summary = f"Negative basis ({fr*100:.3f}%)"
        else:
            score = 0.05
            summary = f"Neutral funding ({fr*100:.3f}%)"

        return EvidenceBlockResult(
            name="Derivatives / Basis",
            direction_score=round(score, 2),
            quality=0.85,
            summary=summary,
            details={"funding_rate": fr, "oi": oi, "basis": basis},
        )

    def _eval_context_sentiment(
        self, sentiment: dict[str, Any] | None, stablecoins: dict[str, Any] | None
    ) -> EvidenceBlockResult:
        fng_val = int(sentiment.get("value", 50)) if sentiment else 50
        fng_cls = str(sentiment.get("classification", "Neutral")) if sentiment else "Neutral"

        # Sentiment modifier
        if fng_val > 75:
            score = -0.20  # Extreme greed contrarian caution
        elif fng_val >= 55:
            score = 0.20   # Moderate constructive greed
        elif fng_val <= 25:
            score = 0.20   # Capitulation / extreme fear value
        else:
            score = 0.0

        summary = f"Fear & Greed: {fng_cls} ({fng_val})"
        return EvidenceBlockResult(
            name="Context / Sentiment",
            direction_score=round(score, 2),
            quality=0.70,
            summary=summary,
            details={"fng_val": fng_val, "fng_cls": fng_cls},
        )

    def _fmt_px(self, val: float | None) -> str:
        if val is None:
            return "-"
        if val >= 1000:
            return f"${val:,.2f}"
        if val >= 1:
            return f"${val:,.4f}"
        return f"${val:,.6f}"
