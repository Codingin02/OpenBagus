"""OpenBagus Canonical Crypto Quantitative Decision Engine."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from openbagus.data.http import validate_finite_number


@dataclass
class EvidenceBlockResult:
    name: str
    direction_score: float
    quality: float
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuantDecisionResult:
    asset: str
    market: str
    decision: str
    regime: str
    confidence: str
    price: float
    entry_zone: str
    stop_price: float | None
    tp1: float | None
    tp2: float | None
    reward_risk: float | None
    reward_risk_str: str
    leverage_ceiling: str
    leverage_num: int
    why: dict[str, str]
    sources: list[str]
    evidence_count: int
    composite_score: float
    composite_quality: float
    rr_gate_passed: bool
    quality_gate_passed: bool
    microstructure: dict[str, Any] = field(default_factory=dict)


class QuantEngine:
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
        trades: dict[str, Any] | None = None,
        sentiment: dict[str, Any] | None = None,
        stablecoins: dict[str, Any] | None = None,
        market_type: str = "spot",
    ) -> QuantDecisionResult:
        price = validate_finite_number(spot_ticker.get("price"), min_val=0.0) or 0.0
        high = validate_finite_number(spot_ticker.get("high"), min_val=0.0) or (price * 1.02)
        low = validate_finite_number(spot_ticker.get("low"), min_val=0.0) or (price * 0.98)
        volume = validate_finite_number(spot_ticker.get("volume"), min_val=0.0) or 0.0
        quote_vol = validate_finite_number(spot_ticker.get("quote_volume"), min_val=0.0) or (volume * price)
        pct_change = validate_finite_number(spot_ticker.get("pct_change")) or 0.0

        ev_trend = self._eval_trend_momentum(price, high, low, pct_change, klines)
        ev_vol = self._eval_volatility_regime(price, high, low, klines)
        ev_micro = self._eval_microstructure_liquidity(price, volume, quote_vol, pct_change, orderbook, trades, spot_ticker)
        ev_deriv = self._eval_derivatives_basis(price, pct_change, derivatives)
        ev_context = self._eval_context_sentiment(sentiment, stablecoins)

        evidence_list = [ev_trend, ev_vol, ev_micro, ev_deriv, ev_context]
        active_families = [e for e in evidence_list if e.quality >= 0.35]
        active_count = len(active_families)

        deriv_available = derivatives is not None and ev_deriv.quality >= 0.35

        if market_type == "spot":
            if deriv_available:
                weights = {
                    "trend": 0.30,
                    "micro": 0.25,
                    "volatility": 0.20,
                    "derivatives": 0.15,
                    "context": 0.10,
                }
            else:
                weights = {
                    "trend": 0.353,
                    "micro": 0.294,
                    "volatility": 0.235,
                    "derivatives": 0.0,
                    "context": 0.118,
                }
        else:
            weights = {
                "derivatives": 0.30,
                "trend": 0.25,
                "micro": 0.20,
                "volatility": 0.20,
                "context": 0.05,
            }

        composite_score = (
            weights["trend"] * ev_trend.direction_score
            + weights["micro"] * ev_micro.direction_score
            + weights["volatility"] * ev_vol.direction_score
            + weights["derivatives"] * ev_deriv.direction_score
            + weights["context"] * ev_context.direction_score
        )

        composite_quality = (
            weights["trend"] * ev_trend.quality
            + weights["micro"] * ev_micro.quality
            + weights["volatility"] * ev_vol.quality
            + weights["derivatives"] * ev_deriv.quality
            + weights["context"] * ev_context.quality
        )

        # Cross-exchange confirmation bonus / single source penalty
        is_cross_confirmed = spot_ticker.get("is_cross_confirmed", False)
        sources_list = spot_ticker.get("cross_exchange_sources", [spot_ticker.get("provider", "Market Feed")])
        if is_cross_confirmed and len(sources_list) >= 2:
            composite_quality = min(1.0, composite_quality + 0.05)
        elif len(sources_list) <= 1:
            composite_quality = max(0.20, composite_quality - 0.05)

        quality_gate_passed = (
            active_count >= self.MIN_INDEPENDENT_EVIDENCE_COUNT
            and composite_quality >= self.MIN_COMPOSITE_QUALITY
        )

        if composite_quality >= 0.75 and active_count >= 4:
            confidence = "HIGH"
        elif composite_quality >= 0.50 and active_count >= 3:
            confidence = "MODERATE"
        else:
            confidence = "LOW"

        pivot = (high + low + price) / 3.0
        r1 = (2.0 * pivot) - low
        s1 = (2.0 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        atr = ev_vol.details.get("atr", (high - low) * 0.5)
        atr_buffer = max(price * 0.005, atr * 0.5)

        regime = ev_vol.details.get("regime", "CHOPPY")

        # Directional threshold
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
                ideal_pullback = round((tp1 + (self.MINIMUM_REWARD_RISK * stop_price)) / (1.0 + self.MINIMUM_REWARD_RISK), 2)
                decision = "WAIT" if market_type == "spot" else "NO_TRADE"
                entry_zone = f"Pullback limit: {self._fmt_px(ideal_pullback)} (for RR >= 1.5)"

        elif quality_gate_passed and is_bearish:
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

        if market_type == "perpetual" and decision in ("LONG", "SHORT") and stop_price:
            stop_dist_pct = abs(price - stop_price) / price
            base_lev = max(1, min(self.hard_leverage_max, int(0.08 / max(stop_dist_pct, 0.015))))
            if regime == "VOLATILE":
                base_lev = max(1, base_lev - 1)
            if quote_vol < 50_000_000:
                base_lev = 1
            if confidence == "LOW":
                base_lev = 1

            leverage_num = base_lev
            leverage_ceiling = f"{base_lev}x (conservative ceiling; max {self.hard_leverage_max}x policy)"
        else:
            leverage_ceiling = "-"
            leverage_num = 0

        sources = list(sources_list)
        if derivatives and derivatives.get("provider"):
            sources.append(derivatives["provider"])
        if sentiment and sentiment.get("provider"):
            sources.append(sentiment["provider"])

        why = {
            "Trend": f"{ev_trend.summary} ({ev_trend.direction_score:+.2f})",
            "Derivatives": f"{ev_deriv.summary} ({ev_deriv.direction_score:+.2f})" if deriv_available else "No derivatives contract (0.00)",
            "Microstructure": f"{ev_micro.summary} ({ev_micro.direction_score:+.2f})",
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
            microstructure=ev_micro.details,
        )

    def _eval_trend_momentum(
        self, price: float, high: float, low: float, pct_change: float, klines: list[dict[str, Any]] | None
    ) -> EvidenceBlockResult:
        if klines and len(klines) >= 10:
            closes = [c["close"] for c in klines]
            h1_ret = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 else 0.0
            h4_ret = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else 0.0

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
            score = max(-1.0, min(1.0, pct_change / 5.0))
            quality = 0.60
            summary = "24h momentum expansion" if score > 0.3 else ("24h momentum contraction" if score < -0.3 else "Neutral 24h momentum")

        return EvidenceBlockResult(
            name="Trend / Momentum",
            direction_score=round(score, 2),
            quality=quality,
            summary=summary,
            details={"score": round(score, 2), "pct_change": pct_change},
        )

    def _eval_volatility_regime(
        self, price: float, high: float, low: float, klines: list[dict[str, Any]] | None
    ) -> EvidenceBlockResult:
        range_pct = ((high - low) / low * 100.0) if low > 0 else 0.0

        atr = (high - low) * 0.6
        if klines and len(klines) >= 14:
            tr_list = []
            for i in range(1, min(15, len(klines))):
                c_prev = klines[i - 1]["close"]
                h_cur = klines[i]["high"]
                l_cur = klines[i]["low"]
                tr = max(h_cur - l_cur, abs(h_cur - c_prev), abs(l_cur - c_prev))
                tr_list.append(tr)
            if tr_list:
                atr = sum(tr_list) / len(tr_list)

        if range_pct > 8.0:
            regime = "VOLATILE"
            score = -0.30
            summary = f"Elevated volatility (range: {range_pct:.1f}%)"
        elif range_pct > 3.0:
            regime = "TRENDING"
            score = 0.20
            summary = f"Healthy trend volatility ({range_pct:.1f}%)"
        elif range_pct < 1.5:
            regime = "COMPRESSED"
            score = 0.00
            summary = f"Compressed range ({range_pct:.1f}%)"
        else:
            regime = "CHOPPY"
            score = -0.15
            summary = f"Choppy sideways range ({range_pct:.1f}%)"

        return EvidenceBlockResult(
            name="Volatility / Regime",
            direction_score=round(score, 2),
            quality=0.80,
            summary=summary,
            details={"regime": regime, "atr": atr, "range_pct": range_pct},
        )

    def _eval_microstructure_liquidity(
        self,
        price: float,
        volume: float,
        quote_vol: float,
        pct_change: float,
        orderbook: dict[str, Any] | None,
        trades: dict[str, Any] | None,
        spot_ticker: dict[str, Any],
    ) -> EvidenceBlockResult:
        vol_score = 0.0
        if quote_vol > 500_000_000:
            liq_label = "Tier 1 Liquid"
            vol_score = 0.20 if pct_change >= 0 else -0.20
        elif quote_vol > 50_000_000:
            liq_label = "Moderate Liquid"
            vol_score = 0.10 if pct_change >= 0 else -0.10
        elif quote_vol > 5_000_000:
            liq_label = "Low Liquidity"
            vol_score = -0.10
        else:
            liq_label = "Illiquid / Thin"
            vol_score = -0.30

        ob_imbalance = 0.0
        microprice_dev = 0.0
        has_ob = False
        if orderbook and "imbalance" in orderbook:
            has_ob = True
            ob_imbalance = float(orderbook.get("imbalance") or 0.0)
            microprice_dev = float(orderbook.get("microprice_dev_bps") or 0.0)

        trade_flow = 0.0
        trade_status = "DATA_GAP"
        if trades and trades.get("status") == "OK":
            trade_status = "CONFIRMED"
            trade_flow = float(trades.get("trade_flow_imbalance") or 0.0)

        # Microstructure fusion: dampens order book imbalance if trade flow contradicts
        if has_ob and trade_status == "CONFIRMED":
            if (ob_imbalance > 0.2 and trade_flow < -0.1) or (ob_imbalance < -0.2 and trade_flow > 0.1):
                effective_ob = ob_imbalance * 0.4
            else:
                effective_ob = ob_imbalance
            micro_score = (effective_ob * 0.5) + (trade_flow * 0.5)
            quality = 0.85
            summary = f"Order flow {trade_flow:+.2f} & book {ob_imbalance:+.2f} ({liq_label})"
        elif has_ob:
            effective_ob = ob_imbalance * 0.6
            micro_score = effective_ob
            quality = 0.70
            summary = f"Book imbalance {ob_imbalance:+.2f} (Trade flow {trade_status}, {liq_label})"
        elif trade_status == "CONFIRMED":
            micro_score = trade_flow * 0.7
            quality = 0.70
            summary = f"Trade flow imbalance {trade_flow:+.2f} ({liq_label})"
        else:
            micro_score = vol_score
            quality = 0.55
            summary = f"Volume confirmed ({liq_label})"

        combined_score = max(-1.0, min(1.0, (vol_score * 0.3) + (micro_score * 0.7)))

        return EvidenceBlockResult(
            name="Microstructure / Liquidity",
            direction_score=round(combined_score, 2),
            quality=quality,
            summary=summary,
            details={
                "order_book_imbalance": round(ob_imbalance, 3),
                "trade_flow_imbalance": round(trade_flow, 3),
                "microprice_dev_bps": round(microprice_dev, 2),
                "trade_flow_status": trade_status,
                "quote_vol": quote_vol,
                "liquidity_tier": liq_label,
            },
        )

    def _eval_derivatives_basis(
        self, price: float, pct_change: float, derivatives: dict[str, Any] | None
    ) -> EvidenceBlockResult:
        if not derivatives:
            return EvidenceBlockResult(
                name="Derivatives / Basis",
                direction_score=0.0,
                quality=0.0,
                summary="No derivatives data available",
                details={},
            )

        funding_rate = float(derivatives.get("funding_rate") or 0.0)
        zscore = float(derivatives.get("funding_zscore") or 0.0)
        basis = float(derivatives.get("basis") or 0.0)
        basis_bps = float(derivatives.get("basis_bps") or (basis / price * 10000.0 if price > 0 else 0.0))
        oi = float(derivatives.get("open_interest") or 0.0)

        # Crowded-long vs crowded-short penalty
        if funding_rate > 0.0004 or zscore > 2.0:
            score = -0.55
            summary = f"Crowded long risk (funding: {funding_rate * 100:.3f}%)"
        elif funding_rate < -0.0004 or zscore < -2.0:
            score = 0.55
            summary = f"Crowded short squeeze setup (funding: {funding_rate * 100:.3f}%)"
        elif funding_rate > 0.0001:
            score = 0.15
            summary = f"Moderate positive funding ({funding_rate * 100:.3f}%)"
        elif funding_rate < -0.0001:
            score = -0.15
            summary = f"Moderate negative funding ({funding_rate * 100:.3f}%)"
        else:
            score = 0.05
            summary = f"Neutral funding ({funding_rate * 100:.3f}%)"

        if basis_bps > 15.0 and score > 0:
            score = min(1.0, score + 0.10)
        elif basis_bps < -15.0 and score < 0:
            score = max(-1.0, score - 0.10)

        return EvidenceBlockResult(
            name="Derivatives / Basis",
            direction_score=round(score, 2),
            quality=0.85,
            summary=summary,
            details={
                "funding_rate": funding_rate,
                "funding_zscore": zscore,
                "basis": basis,
                "basis_bps": round(basis_bps, 2),
                "open_interest": oi,
            },
        )

    def _eval_context_sentiment(
        self, sentiment: dict[str, Any] | None, stablecoins: dict[str, Any] | None
    ) -> EvidenceBlockResult:
        if not sentiment:
            return EvidenceBlockResult(
                name="Context / Sentiment",
                direction_score=0.0,
                quality=0.50,
                summary="Sentiment neutral / default",
                details={},
            )

        fng_val = int(sentiment.get("value", 50))
        fng_cls = sentiment.get("classification", "Neutral")

        if fng_val >= 75:
            score = 0.20
        elif fng_val >= 55:
            score = 0.10
        elif fng_val <= 25:
            score = -0.20
        elif fng_val <= 45:
            score = -0.10
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
