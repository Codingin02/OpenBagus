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
class CandidateSetup:
    direction: str  # "LONG" or "SHORT"
    entry_zone: str
    stop_price: float
    tp1: float
    tp2: float
    reward_risk: float
    reward_risk_str: str
    setup_quality: str  # "STRONG", "MODERATE", "INSUFFICIENT"
    rr_gate_passed: bool
    reason: str = ""
    watch_trigger: str = ""


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
    data_quality: str = "MODERATE"
    setup_quality: str = "INSUFFICIENT"
    decision_reason: str = ""
    watch_trigger: str = ""
    candidate_long: CandidateSetup | None = None
    candidate_short: CandidateSetup | None = None
    narrative: str = ""
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

        if composite_quality >= 0.70 and active_count >= 4:
            data_quality = "HIGH"
        elif composite_quality >= 0.45 and active_count >= 3:
            data_quality = "MODERATE"
        else:
            data_quality = "LOW"
        confidence = data_quality

        pivot = (high + low + price) / 3.0
        r1 = (2.0 * pivot) - low
        s1 = (2.0 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        atr = ev_vol.details.get("atr", (high - low) * 0.5)
        atr_buffer = max(price * 0.005, atr * 0.5)

        regime = ev_vol.details.get("regime", "CHOPPY")

        # --- Evaluate Candidate LONG ---
        long_stop = round(s1 - atr_buffer, 4 if price < 10 else 2)
        long_tp1 = round(r1, 4 if price < 10 else 2)
        long_tp2 = round(r2, 4 if price < 10 else 2)
        long_risk_span = price - long_stop
        long_reward_span = long_tp1 - price
        long_rr = round(long_reward_span / long_risk_span, 2) if long_risk_span > 0 and long_reward_span > 0 else 0.0
        long_rr_passed = long_rr >= self.MINIMUM_REWARD_RISK
        ideal_long_pullback = round((long_tp1 + (self.MINIMUM_REWARD_RISK * long_stop)) / (1.0 + self.MINIMUM_REWARD_RISK), 4 if price < 10 else 2)

        if composite_score >= 0.20 and long_rr_passed and quality_gate_passed:
            long_setup_quality = "STRONG"
        elif composite_score >= 0.05 or long_rr >= 1.2:
            long_setup_quality = "MODERATE"
        else:
            long_setup_quality = "INSUFFICIENT"

        cand_long = CandidateSetup(
            direction="LONG",
            entry_zone=f"{self._fmt_px(min(price, pivot))} - {self._fmt_px(price)}" if long_rr_passed else f"Pullback limit: {self._fmt_px(ideal_long_pullback)}",
            stop_price=long_stop,
            tp1=long_tp1,
            tp2=long_tp2,
            reward_risk=long_rr,
            reward_risk_str=f"1:{long_rr:.2f}" + ("" if long_rr_passed else " (< 1.5 gate)"),
            setup_quality=long_setup_quality,
            rr_gate_passed=long_rr_passed,
            reason="Reward-to-risk below 1.5" if not long_rr_passed else "",
            watch_trigger=f"Pullback to {self._fmt_px(ideal_long_pullback)} for R:R >= 1.5" if not long_rr_passed else "",
        )

        # --- Evaluate Candidate SHORT ---
        short_stop = round(r1 + atr_buffer, 4 if price < 10 else 2)
        short_tp1 = round(s1, 4 if price < 10 else 2)
        short_tp2 = round(s2, 4 if price < 10 else 2)
        short_risk_span = short_stop - price
        short_reward_span = price - short_tp1
        short_rr = round(short_reward_span / short_risk_span, 2) if short_risk_span > 0 and short_reward_span > 0 else 0.0
        short_rr_passed = short_rr >= self.MINIMUM_REWARD_RISK
        ideal_short_bounce = round((short_tp1 + (self.MINIMUM_REWARD_RISK * short_stop)) / (1.0 + self.MINIMUM_REWARD_RISK), 4 if price < 10 else 2)

        if composite_score <= -0.20 and short_rr_passed and quality_gate_passed:
            short_setup_quality = "STRONG"
        elif composite_score <= -0.05 or short_rr >= 1.2:
            short_setup_quality = "MODERATE"
        else:
            short_setup_quality = "INSUFFICIENT"

        cand_short = CandidateSetup(
            direction="SHORT",
            entry_zone=f"{self._fmt_px(price)} - {self._fmt_px(max(price, pivot))}" if short_rr_passed else f"Bounce limit: {self._fmt_px(ideal_short_bounce)}",
            stop_price=short_stop,
            tp1=short_tp1,
            tp2=short_tp2,
            reward_risk=short_rr,
            reward_risk_str=f"1:{short_rr:.2f}" + ("" if short_rr_passed else " (< 1.5 gate)"),
            setup_quality=short_setup_quality,
            rr_gate_passed=short_rr_passed,
            reason="Reward-to-risk below 1.5" if not short_rr_passed else "",
            watch_trigger=f"Rejection at {self._fmt_px(short_stop)} for R:R >= 1.5" if not short_rr_passed else "",
        )

        chosen: CandidateSetup | None = None
        decision = "WAIT" if market_type == "spot" else "NO_TRADE"
        setup_quality = "INSUFFICIENT"
        decision_reason = ""
        watch_trigger = ""

        if market_type == "spot":
            if cand_long.setup_quality == "STRONG":
                decision = "BUY"
                chosen = cand_long
                setup_quality = "STRONG"
            elif composite_score <= -0.25:
                decision = "REDUCE"
                chosen = cand_short if cand_short.setup_quality == "STRONG" else None
                setup_quality = cand_short.setup_quality if chosen else "MODERATE"
            else:
                decision = "WAIT"
                setup_quality = cand_long.setup_quality if cand_long.setup_quality != "INSUFFICIENT" else "INSUFFICIENT"
        else:
            if cand_long.setup_quality == "STRONG":
                decision = "LONG"
                chosen = cand_long
                setup_quality = "STRONG"
            elif cand_short.setup_quality == "STRONG":
                decision = "SHORT"
                chosen = cand_short
                setup_quality = "STRONG"
            else:
                decision = "NO_TRADE"
                setup_quality = "MODERATE" if (cand_long.setup_quality == "MODERATE" or cand_short.setup_quality == "MODERATE") else "INSUFFICIENT"

        if chosen:
            entry_zone = chosen.entry_zone
            stop_price = chosen.stop_price
            tp1 = chosen.tp1
            tp2 = chosen.tp2
            reward_risk = chosen.reward_risk
            rr_gate_passed = True
            rr_str = f"1:{chosen.reward_risk:.2f}"
            decision_reason = f"Confirmed {chosen.direction} setup with favorable R:R ({rr_str}) and aligned market microstructure."
            watch_trigger = f"Invalidation below {self._fmt_px(stop_price)} or take profit at {self._fmt_px(tp1)}."
        else:
            entry_zone = "-"
            stop_price = None
            tp1 = None
            tp2 = None
            reward_risk = None
            rr_gate_passed = False
            rr_str = "-"

            if not quality_gate_passed:
                decision_reason = "Data consensus across public providers is insufficient for live risk allocation."
                watch_trigger = "Wait for additional independent exchange feeds to establish price consensus."
            elif not long_rr_passed and not short_rr_passed:
                decision_reason = f"Reward-to-risk at current price (Long 1:{long_rr:.2f}, Short 1:{short_rr:.2f}) does not meet 1:1.50 minimum gate."
                watch_trigger = f"Pullback limit to {self._fmt_px(ideal_long_pullback)} for Long R:R >= 1.5, or resistance reaction at {self._fmt_px(r1)} for Short."
            elif abs(composite_score) < 0.20:
                decision_reason = f"Market is in a neutral/choppy regime (composite score {composite_score:+.2f}) without directional momentum."
                watch_trigger = f"Wait for confirmed breakout above {self._fmt_px(r1)} or breakdown below {self._fmt_px(s1)} on rising volume."
            else:
                decision_reason = "Setup conditions do not provide a favorable asymmetric risk/reward edge."
                watch_trigger = f"Monitor price reaction near key pivot level {self._fmt_px(pivot)}."

        if market_type == "perpetual" and decision in ("LONG", "SHORT") and stop_price:
            stop_dist_pct = abs(price - stop_price) / price
            base_lev = max(1, min(self.hard_leverage_max, int(0.08 / max(stop_dist_pct, 0.015))))
            if regime == "VOLATILE":
                base_lev = max(1, base_lev - 1)
            if quote_vol < 50_000_000:
                base_lev = 1
            if data_quality == "LOW":
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

        # Deterministic 2-5 sentence narrative
        narrative_parts = [
            f"{symbol.upper()} diperdagangkan di {self._fmt_px(price)} dalam rezim {regime.lower()} dengan skor komposit {composite_score:+.2f}.",
            f"Kualitas data {data_quality.lower()} didorong sinyal {ev_micro.summary.lower()} dan {ev_trend.summary.lower()}.",
        ]
        if decision in ("BUY", "LONG", "SHORT", "REDUCE"):
            narrative_parts.append(
                f"Sinyal aktif menghasilkan keputusan {decision} (setup {setup_quality.lower()}) dengan target {self._fmt_px(tp1)} dan stop {self._fmt_px(stop_price)} (R:R {rr_str})."
            )
        else:
            narrative_parts.append(
                f"Keputusan saat ini adalah {decision} karena {decision_reason} Pantau: {watch_trigger}"
            )
        narrative = " ".join(narrative_parts)

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
            data_quality=data_quality,
            setup_quality=setup_quality,
            decision_reason=decision_reason,
            watch_trigger=watch_trigger,
            candidate_long=cand_long,
            candidate_short=cand_short,
            narrative=narrative,
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
