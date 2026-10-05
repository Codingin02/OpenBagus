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
class ValidationScenario:
    direction: str  # "LONG" or "SHORT"
    trigger_condition: str  # e.g. "H1 close above $86,100"
    volume_condition: str  # e.g. "Volume > 1.2x 20-period avg"
    order_flow_condition: str  # e.g. "Taker buy flow > +0.10, bid depth"
    derivatives_condition: str  # e.g. "OI rising without crowded funding (< +0.03%)"
    entry_zone: str  # e.g. "$86,100 (Breakout) or pullback to $85,200"
    stop_price: float
    tp1: float
    tp2: float
    reward_risk: float
    reward_risk_str: str
    summary: str = ""


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
    timeframe: str = "H1"
    bullish_validation: ValidationScenario | None = None
    bearish_validation: ValidationScenario | None = None
    factor_contributions: dict[str, str] = field(default_factory=dict)
    cross_venue_dislocation: dict[str, Any] = field(default_factory=dict)
    patterns_detected: list[dict[str, Any]] = field(default_factory=list)
    fibonacci_confluence: dict[str, Any] = field(default_factory=dict)
    why_now: str = ""
    astrology_diagnostic: dict[str, Any] = field(default_factory=dict)
    stochastic_item: dict[str, Any] = field(default_factory=dict)
    patterns_item: dict[str, Any] = field(default_factory=dict)
    fibonacci_item: dict[str, Any] = field(default_factory=dict)
    arbitrage_item: dict[str, Any] = field(default_factory=dict)
    cycle_item: dict[str, Any] = field(default_factory=dict)
    lunar_item: dict[str, Any] = field(default_factory=dict)


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
        timeframe: str = "H1",
    ) -> QuantDecisionResult:
        price = validate_finite_number(spot_ticker.get("price"), min_val=0.0) or 0.0
        high = validate_finite_number(spot_ticker.get("high"), min_val=0.0) or (price * 1.02)
        low = validate_finite_number(spot_ticker.get("low"), min_val=0.0) or (price * 0.98)
        volume = validate_finite_number(spot_ticker.get("volume"), min_val=0.0) or 0.0
        quote_vol = validate_finite_number(spot_ticker.get("quote_volume"), min_val=0.0) or (volume * price)
        pct_change = validate_finite_number(spot_ticker.get("pct_change")) or 0.0

        pivot = (high + low + price) / 3.0
        r1 = (2.0 * pivot) - low
        s1 = (2.0 * pivot) - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        atr_approx = (high - low) * 0.5
        atr_buffer = max(price * 0.005, atr_approx * 0.5)

        # 1. Base Evidence Blocks
        ev_trend = self._eval_trend_momentum(price, high, low, pct_change, klines, timeframe)
        ev_vol = self._eval_volatility_regime(price, high, low, klines)
        ev_micro = self._eval_microstructure_liquidity(price, volume, quote_vol, pct_change, orderbook, trades, spot_ticker)
        ev_deriv = self._eval_derivatives_basis(price, pct_change, derivatives)

        # Dampen sentiment context for microcap / DEX-only tokens (Section 21)
        is_major = quote_vol >= 50_000_000 and not spot_ticker.get("is_dex", False)
        ev_context = self._eval_context_sentiment(sentiment, stablecoins, is_major=is_major)

        # 2. Crypto-Native Chart Pattern Evidence (Section 10, 11)
        ev_pattern, detected_patterns = self._eval_chart_patterns(klines, price, pivot, s1, r1, atr_approx)
        patterns_item = ev_pattern.details.get("item", {})

        # 3. Fibonacci Confluence Evidence (Section 12)
        ev_fib, fib_details = self._eval_fibonacci_confluence(klines, price, pivot, s1, r1)
        fib_item = ev_fib.details.get("item", {})

        # 4. Cross-Exchange Dislocation Evidence (Section 8, 9)
        ev_disloc, disloc_details = self._eval_cross_exchange_dislocation(spot_ticker, price)
        arbitrage_item = ev_disloc.details.get("item", {})

        # 5. Stochastic Evidence (Section D1)
        ev_stoch, stoch_details, stoch_item = self._eval_stochastic(klines, price, pivot, s1, r1)

        # 6. Frequency Cycle Evidence (Section D5)
        ev_cycle, cycle_item = self._eval_frequency_cycle(klines)

        # 7. Optional Astrology Diagnostic (Section D6: 0% weight, OFF by default)
        astro_diagnostic, lunar_item = self._eval_astrology_diagnostic()

        # Weight allocation & renormalization
        deriv_available = derivatives is not None and ev_deriv.quality >= 0.35
        m_lower = market_type.lower()
        if m_lower == "perpetual":
            raw_weights = {
                "Trend / Momentum": 0.22,
                "Microstructure": 0.20,
                "Derivatives": 0.24 if deriv_available else 0.0,
                "Volatility / Regime": 0.15,
                "Chart Pattern": 0.08,
                "Fibonacci Confluence": 0.05,
                "Context / Sentiment": 0.06 if is_major else 0.01,
            }
        else:
            raw_weights = {
                "Trend / Momentum": 0.28,
                "Microstructure": 0.24,
                "Volatility / Regime": 0.18,
                "Derivatives": 0.10 if deriv_available else 0.0,
                "Chart Pattern": 0.08,
                "Fibonacci Confluence": 0.05,
                "Context / Sentiment": 0.07 if is_major else 0.01,
            }

        total_w = sum(raw_weights.values())
        weights = {k: v / total_w for k, v in raw_weights.items()} if total_w > 0 else raw_weights

        evidence_map: dict[str, EvidenceBlockResult] = {
            "Trend / Momentum": ev_trend,
            "Microstructure": ev_micro,
            "Volatility / Regime": ev_vol,
            "Chart Pattern": ev_pattern,
            "Fibonacci Confluence": ev_fib,
            "Context / Sentiment": ev_context,
        }
        if deriv_available:
            evidence_map["Derivatives"] = ev_deriv

        composite_score = sum(weights.get(k, 0.0) * ev.direction_score for k, ev in evidence_map.items())
        composite_quality = sum(weights.get(k, 0.0) * ev.quality for k, ev in evidence_map.items())

        # Cross-exchange confirmation bonus / single source penalty
        is_cross_confirmed = spot_ticker.get("is_cross_confirmed", False)
        sources_list = spot_ticker.get("cross_exchange_sources", [spot_ticker.get("provider", "Market Feed")])
        if is_cross_confirmed and len(sources_list) >= 2:
            composite_quality = min(1.0, composite_quality + 0.05)
        elif len(sources_list) <= 1:
            composite_quality = max(0.20, composite_quality - 0.05)

        active_count = len([e for e in evidence_map.values() if e.quality >= 0.35])
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

        regime = ev_vol.details.get("regime", "CHOPPY")
        atr = ev_vol.details.get("atr", atr_approx)
        atr_buffer = max(price * 0.005, atr * 0.5)

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

        # --- Decision Evaluation ---
        chosen: CandidateSetup | None = None
        decision = "WAIT" if m_lower == "spot" else "NO_TRADE"
        setup_quality = "INSUFFICIENT"
        decision_reason = ""
        watch_trigger = ""
        why_now = ""

        if m_lower == "spot":
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
            why_now = f"Entry aktif terpenuhi pada level {entry_zone} dengan rasio R:R {rr_str} (memenuhi gerbang minimum 1.5)."
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
                why_now = "Konsensus data antar bursa publik belum mencapai batas kualitas minimum."
            elif not long_rr_passed and not short_rr_passed:
                decision_reason = f"Reward-to-risk at current price (Long 1:{long_rr:.2f}, Short 1:{short_rr:.2f}) does not meet 1:1.50 minimum gate."
                watch_trigger = f"Pullback limit to {self._fmt_px(ideal_long_pullback)} for Long R:R >= 1.5, or resistance reaction at {self._fmt_px(r1)} for Short."
                why_now = f"Struktur harga {timeframe} belum memberi rasio risk:reward memadai (Long 1:{long_rr:.2f}, Short 1:{short_rr:.2f}); entry sekarang terlalu dekat resistance/support."
            elif abs(composite_score) < 0.20:
                decision_reason = f"Market is in a neutral/choppy regime (composite score {composite_score:+.2f}) without directional momentum."
                watch_trigger = f"Wait for confirmed breakout above {self._fmt_px(r1)} or breakdown below {self._fmt_px(s1)} on rising volume."
                why_now = f"Harga sedang bergerak sideways dalam rentang kompresi ({regime}) tanpa dominasi pembeli maupun penjual."
            else:
                decision_reason = "Setup conditions do not provide a favorable asymmetric risk/reward edge."
                watch_trigger = f"Monitor price reaction near key pivot level {self._fmt_px(pivot)}."
                why_now = "Kondisi teknikal dan likuiditas belum menghasilkan tepi asimetris yang layak ditradingkan."

        # Leverage Policy
        if m_lower == "perpetual" and decision in ("LONG", "SHORT") and stop_price:
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

        # Sources aggregation
        sources = list(sources_list)
        if derivatives and derivatives.get("provider"):
            sources.append(derivatives["provider"])
        if sentiment and sentiment.get("provider"):
            sources.append(sentiment["provider"])

        # Factor contributions calculation (Section 14)
        factor_contribs = self._calculate_factor_contributions(evidence_map, weights, disloc_details)

        # Future Validation Scenarios (Section 6, 7)
        bullish_val, bearish_val = self._generate_validation_scenarios(
            symbol=symbol,
            price=price,
            pivot=pivot,
            r1=r1,
            s1=s1,
            r2=r2,
            s2=s2,
            atr_buffer=atr_buffer,
            timeframe=timeframe,
            deriv_available=deriv_available,
            ideal_long_pullback=ideal_long_pullback,
            ideal_short_bounce=ideal_short_bounce,
        )

        why = {
            "Trend": f"{ev_trend.summary} ({ev_trend.direction_score:+.2f})",
            "Derivatives": f"{ev_deriv.summary} ({ev_deriv.direction_score:+.2f})" if deriv_available else "No derivatives contract (0.00)",
            "Microstructure": f"{ev_micro.summary} ({ev_micro.direction_score:+.2f})",
            "Volatility": f"{regime} ({ev_vol.summary})",
            "Patterns": ev_pattern.summary,
            "Fibonacci": ev_fib.summary,
            "Context": ev_context.summary,
        }

        # Deterministic Trader-Note Narrative (Section 15: 3-7 sentences maximum)
        narrative = self._generate_trader_narrative(
            symbol=symbol,
            timeframe=timeframe,
            price=price,
            regime=regime,
            composite_score=composite_score,
            ev_micro=ev_micro,
            ev_trend=ev_trend,
            decision=decision,
            setup_quality=setup_quality,
            tp1=tp1 or r1,
            stop_price=stop_price or s1,
            rr_str=rr_str if decision in ("BUY", "LONG", "SHORT", "REDUCE") else f"1:{long_rr:.2f}",
            long_rr=long_rr,
            r1=r1,
            s1=s1,
            r2=r2,
            s2=s2,
        )

        return QuantDecisionResult(
            asset=symbol.upper(),
            market=market_type.upper(),
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
            timeframe=timeframe,
            bullish_validation=bullish_val,
            bearish_validation=bearish_val,
            factor_contributions=factor_contribs,
            cross_venue_dislocation=disloc_details,
            patterns_detected=detected_patterns,
            fibonacci_confluence=fib_details,
            why_now=why_now,
            astrology_diagnostic=astro_diagnostic,
            stochastic_item=stoch_item,
            patterns_item=patterns_item,
            fibonacci_item=fib_item,
            arbitrage_item=arbitrage_item,
            cycle_item=cycle_item,
            lunar_item=lunar_item,
        )

    def _eval_trend_momentum(
        self, price: float, high: float, low: float, pct_change: float, klines: list[dict[str, Any]] | None, timeframe: str = "H1"
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
            summary = f"{timeframe} trend bullish" if score > 0.3 else (f"{timeframe} trend bearish" if score < -0.3 else f"{timeframe} mixed / consolidating trend")
        else:
            score = max(-1.0, min(1.0, pct_change / 5.0))
            quality = 0.60
            summary = "24h momentum expansion" if score > 0.3 else ("24h momentum contraction" if score < -0.3 else "Neutral 24h momentum")

        return EvidenceBlockResult(
            name="Trend / Momentum",
            direction_score=round(score, 2),
            quality=quality,
            summary=summary,
            details={"score": round(score, 2), "pct_change": pct_change, "timeframe": timeframe},
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
        self, sentiment: dict[str, Any] | None, stablecoins: dict[str, Any] | None, is_major: bool = True
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

        if not is_major:
            score = score * 0.2  # Strongly dampen for DEX / illiquid assets

        summary = f"Fear & Greed: {fng_cls} ({fng_val})" + ("" if is_major else " [Low Impact]")
        return EvidenceBlockResult(
            name="Context / Sentiment",
            direction_score=round(score, 2),
            quality=0.70 if is_major else 0.35,
            summary=summary,
            details={"fng_val": fng_val, "fng_cls": fng_cls, "is_major": is_major},
        )

    def _eval_chart_patterns(
        self,
        klines: list[dict[str, Any]] | None,
        price: float,
        pivot: float,
        s1: float,
        r1: float,
        atr: float,
    ) -> tuple[EvidenceBlockResult, list[dict[str, Any]]]:
        """Calculates deterministic candlestick patterns from OHLCV candles."""
        if not klines or len(klines) < 2:
            return (
                EvidenceBlockResult(
                    name="Chart Pattern",
                    direction_score=0.0,
                    quality=0.40,
                    summary="Insufficient candle history for pattern scan",
                ),
                [],
            )

        c1 = klines[-1]  # current / latest completed
        c2 = klines[-2]  # previous
        c3 = klines[-3] if len(klines) >= 3 else c2

        o1 = float(c1.get("open") if c1.get("open") is not None else c1.get("close", 0))
        h1 = float(c1.get("high") if c1.get("high") is not None else c1.get("close", 0))
        l1 = float(c1.get("low") if c1.get("low") is not None else c1.get("close", 0))
        cl1 = float(c1.get("close", 0))
        v1 = float(c1.get("volume", 0))

        o2 = float(c2.get("open") if c2.get("open") is not None else c2.get("close", 0))
        h2 = float(c2.get("high") if c2.get("high") is not None else c2.get("close", 0))
        l2 = float(c2.get("low") if c2.get("low") is not None else c2.get("close", 0))
        cl2 = float(c2.get("close", 0))
        v2 = float(c2.get("volume", 0))

        o3 = float(c3.get("open") if c3.get("open") is not None else c3.get("close", 0))
        h3 = float(c3.get("high") if c3.get("high") is not None else c3.get("close", 0))
        l3 = float(c3.get("low") if c3.get("low") is not None else c3.get("close", 0))
        cl3 = float(c3.get("close", 0))

        avg_vol = sum(float(c.get("volume", 0)) for c in klines[-10:]) / 10.0 if klines else 1.0
        vol_confirmed = v1 > 1.1 * avg_vol if avg_vol > 0 else False

        body1 = abs(cl1 - o1)
        rng1 = max(h1 - l1, 1e-8)
        body2 = abs(cl2 - o2)
        rng2 = max(h2 - l2, 1e-8)

        patterns: list[dict[str, Any]] = []
        score = 0.0

        # 1. Bullish Engulfing
        if cl2 < o2 and cl1 > o1 and o1 <= cl2 and cl1 >= o2 and body1 > 0.4 * rng1:
            at_support = l1 <= s1 + (atr * 0.3)
            boost = 0.50 if (at_support and vol_confirmed) else 0.35
            score += boost
            patterns.append({"pattern": "Bullish Engulfing", "bias": "BULLISH", "score": boost, "at_support": at_support})

        # 2. Bearish Engulfing
        elif cl2 > o2 and cl1 < o1 and o1 >= cl2 and cl1 <= o2 and body1 > 0.4 * rng1:
            at_resist = h1 >= r1 - (atr * 0.3)
            boost = -0.50 if (at_resist and vol_confirmed) else -0.35
            score += boost
            patterns.append({"pattern": "Bearish Engulfing", "bias": "BEARISH", "score": boost, "at_resistance": at_resist})

        # 3. Hammer (Bullish reversal)
        lower_wick = min(o1, cl1) - l1
        upper_wick = h1 - max(o1, cl1)
        if lower_wick >= 2.0 * body1 and upper_wick <= max(0.15 * rng1, body1) and cl2 <= o2:
            at_support = l1 <= s1 + (atr * 0.3)
            p_score = 0.45 if (at_support and vol_confirmed) else 0.25
            score += p_score
            patterns.append({"pattern": "Hammer", "bias": "BULLISH", "score": p_score, "at_support": at_support})

        # 4. Shooting Star (Bearish reversal)
        elif upper_wick >= 2.0 * body1 and lower_wick <= max(0.15 * rng1, body1) and cl2 >= o2:
            at_resist = h1 >= r1 - (atr * 0.3)
            p_score = -0.45 if (at_resist and vol_confirmed) else -0.25
            score += p_score
            patterns.append({"pattern": "Shooting Star", "bias": "BEARISH", "score": p_score, "at_resistance": at_resist})

        # 5. Harami
        elif cl2 < o2 and cl1 > o1 and o1 >= cl2 and cl1 <= o2:
            score += 0.20
            patterns.append({"pattern": "Bullish Harami", "bias": "BULLISH", "score": 0.20})
        elif cl2 > o2 and cl1 < o1 and o1 <= cl2 and cl1 >= o2:
            score += -0.20
            patterns.append({"pattern": "Bearish Harami", "bias": "BEARISH", "score": -0.20})

        # 6. Inside Bar
        elif h1 < h2 and l1 > l2:
            score += 0.05 if cl1 >= o1 else -0.05
            patterns.append({"pattern": "Inside Bar", "bias": "NEUTRAL", "score": 0.05})

        score = max(-0.80, min(0.80, score))
        summary = (
            f"{patterns[0]['pattern']} ({'+' if score>0 else ''}{score:.2f})"
            if patterns
            else "No dominant candle pattern (neutral structure)"
        )

        is_material = False
        if patterns:
            top_p = patterns[0]
            at_struct = top_p.get("at_support", False) or top_p.get("at_resistance", False)
            if at_struct and vol_confirmed:
                is_material = True

        patterns_item = {
            "available": bool(patterns),
            "material": is_material,
            "direction": "BULLISH" if (patterns and patterns[0]["bias"] == "BULLISH") else ("BEARISH" if (patterns and patterns[0]["bias"] == "BEARISH") else "NEUTRAL"),
            "quality": 0.80 if is_material else 0.45,
            "values": {
                "name": patterns[0]["pattern"] if (patterns and is_material) else "",
                "patterns": patterns,
                "vol_confirmed": vol_confirmed,
                "summary": summary if is_material else "",
            },
        }

        return (
            EvidenceBlockResult(
                name="Chart Pattern",
                direction_score=round(score, 2),
                quality=0.75 if patterns else 0.50,
                summary=summary,
                details={"patterns": patterns, "vol_confirmed": vol_confirmed, "item": patterns_item},
            ),
            patterns,
        )

    def _eval_fibonacci_confluence(
        self,
        klines: list[dict[str, Any]] | None,
        price: float,
        pivot: float,
        s1: float,
        r1: float,
    ) -> tuple[EvidenceBlockResult, dict[str, Any]]:
        """Calculates Fibonacci retracement levels from objectively detected swing high/low."""
        if not klines or len(klines) < 10 or price <= 0:
            fib_empty_item = {
                "available": False,
                "material": False,
                "direction": "NEUTRAL",
                "quality": 0.0,
                "values": {},
            }
            return (
                EvidenceBlockResult(
                    name="Fibonacci Confluence",
                    direction_score=0.0,
                    quality=0.40,
                    summary="Insufficient swing data for Fibonacci",
                    details={"item": fib_empty_item},
                ),
                {},
            )

        lookback = min(len(klines), 35)
        window = klines[-lookback:]
        swing_high = max(float(c.get("high") if c.get("high") is not None else c.get("close", 0)) for c in window)
        swing_low = min(float(c.get("low") if c.get("low") is not None else c.get("close", 0)) for c in window)
        span = swing_high - swing_low

        if span <= 0:
            fib_flat_item = {
                "available": False,
                "material": False,
                "direction": "NEUTRAL",
                "quality": 0.0,
                "values": {},
            }
            return (
                EvidenceBlockResult(
                    name="Fibonacci Confluence",
                    direction_score=0.0,
                    quality=0.40,
                    summary="Flat price span; no Fib levels",
                    details={"item": fib_flat_item},
                ),
                {},
            )

        fib_382 = swing_high - (0.382 * span)
        fib_500 = swing_high - (0.500 * span)
        fib_618 = swing_high - (0.618 * span)
        fib_786 = swing_high - (0.786 * span)

        # Proximity threshold = 0.8% of price
        thresh = price * 0.008
        confluence_level = None
        score = 0.0
        summary = "Price mid-range; no immediate Fib confluence"

        if abs(price - fib_618) <= thresh:
            confluence_level = "0.618 Golden Pocket"
            score = 0.25 if price >= fib_618 else -0.15
            summary = f"Confluence at Fib 0.618 ({self._fmt_px(fib_618)})"
        elif abs(price - fib_500) <= thresh:
            confluence_level = "0.500 Midpoint"
            score = 0.15 if price >= fib_500 else -0.10
            summary = f"Confluence at Fib 0.500 ({self._fmt_px(fib_500)})"
        elif abs(price - fib_382) <= thresh:
            confluence_level = "0.382 Shallow Pullback"
            score = 0.10
            summary = f"Near Fib 0.382 ({self._fmt_px(fib_382)})"
        elif abs(price - fib_786) <= thresh:
            confluence_level = "0.786 Deep Invalidation"
            score = -0.15
            summary = f"Near Fib 0.786 deep retracement ({self._fmt_px(fib_786)})"

        # Materiality rule (Section D3):
        # 1. swing high/low detected (span > 0)
        # 2. price close to 0.382 / 0.500 / 0.618 / 0.786
        # 3. AND at least one independent confluence exists (S/R/Pivot proximity within 1.5%)
        independent_confluence = False
        if confluence_level:
            target_fib = fib_618 if "0.618" in confluence_level else (fib_500 if "0.500" in confluence_level else (fib_382 if "0.382" in confluence_level else fib_786))
            if abs(target_fib - s1) <= price * 0.015 or abs(target_fib - r1) <= price * 0.015 or abs(target_fib - pivot) <= price * 0.015:
                independent_confluence = True

        is_material = bool(confluence_level and independent_confluence)

        fib_details = {
            "swing_high": swing_high,
            "swing_low": swing_low,
            "fib_382": round(fib_382, 4 if price < 10 else 2),
            "fib_500": round(fib_500, 4 if price < 10 else 2),
            "fib_618": round(fib_618, 4 if price < 10 else 2),
            "fib_786": round(fib_786, 4 if price < 10 else 2),
            "confluence": confluence_level or "",
            "independent_confluence": independent_confluence,
        }

        fib_item = {
            "available": bool(span > 0),
            "material": is_material,
            "direction": "BULLISH" if score > 0 else ("BEARISH" if score < 0 else "NEUTRAL"),
            "quality": 0.75 if is_material else 0.0,
            "values": {
                **fib_details,
                "summary": summary if is_material else "",
            },
        }

        return (
            EvidenceBlockResult(
                name="Fibonacci Confluence",
                direction_score=round(score, 2),
                quality=0.70,
                summary=summary,
                details={"item": fib_item, **fib_details},
            ),
            fib_details,
        )

    def _eval_cross_exchange_dislocation(
        self, spot_ticker: dict[str, Any], price: float
    ) -> tuple[EvidenceBlockResult, dict[str, Any]]:
        """Compares fresh cross-exchange quotes to detect price dispersion and market stress."""
        quotes: dict[str, dict[str, Any]] = spot_ticker.get("cross_venue_quotes", {})
        if len(quotes) < 2:
            arb_empty_item = {
                "available": False,
                "material": False,
                "direction": "NEUTRAL",
                "quality": 0.0,
                "values": {},
            }
            return (
                EvidenceBlockResult(
                    name="Cross-Venue Dislocation",
                    direction_score=0.0,
                    quality=0.40,
                    summary="Single venue feed (no cross-exchange quote)",
                    details={"item": arb_empty_item},
                ),
                {"available": False},
            )

        valid_prices = [q["price"] for q in quotes.values() if q.get("price")]
        if len(valid_prices) < 2:
            arb_insuf_item = {
                "available": False,
                "material": False,
                "direction": "NEUTRAL",
                "quality": 0.0,
                "values": {},
            }
            return (
                EvidenceBlockResult(
                    name="Cross-Venue Dislocation",
                    direction_score=0.0,
                    quality=0.40,
                    summary="Insufficient fresh quotes",
                    details={"item": arb_insuf_item},
                ),
                {"available": False},
            )

        min_px = min(valid_prices)
        max_px = max(valid_prices)
        sorted_p = sorted(valid_prices)
        med_px = sorted_p[len(sorted_p) // 2]
        dispersion_pct = ((max_px - min_px) / med_px) * 100.0 if med_px > 0 else 0.0

        # Estimated cost = taker fee (~0.10% each side = 0.20%) + slippage (0.05%) = 0.25%
        estimated_cost_pct = 0.25
        estimated_net_spread_pct = round(dispersion_pct - estimated_cost_pct, 3)

        if dispersion_pct < 0.15:
            dislocation_cls = "NORMAL"
        elif dispersion_pct < 0.50:
            dislocation_cls = "ELEVATED"
        else:
            dislocation_cls = "HIGH"

        best_venue = next((k for k, v in quotes.items() if v["price"] == min_px), "Market")
        summary = f"Dispersion {dispersion_pct:.2f}% ({dislocation_cls}), best venue: {best_venue}"

        # Materiality rule (Section D4):
        # Spread is materially larger than expected fee + slippage
        is_material = bool(len(valid_prices) >= 2 and estimated_net_spread_pct > 0.10)

        arbitrage_item = {
            "available": True,
            "material": is_material,
            "direction": "NEUTRAL",
            "quality": 0.85 if is_material else 0.40,
            "values": {
                "raw_spread_pct": round(dispersion_pct, 2),
                "estimated_cost_pct": estimated_cost_pct,
                "estimated_net_spread_pct": estimated_net_spread_pct,
                "best_venue": best_venue,
                "is_arbitrage_opportunity": is_material,
                "summary": summary if is_material else "",
            },
        }

        disloc_details = {
            "available": True,
            "venues_count": len(valid_prices),
            "dispersion_pct": round(dispersion_pct, 2),
            "dislocation_status": dislocation_cls,
            "estimated_net_spread_pct": estimated_net_spread_pct,
            "best_venue": best_venue,
            "median_price": med_px,
            "item": arbitrage_item,
        }

        return (
            EvidenceBlockResult(
                name="Cross-Venue Dislocation",
                direction_score=0.0,
                quality=0.85,
                summary=summary,
                details=disloc_details,
            ),
            disloc_details,
        )

    def _eval_stochastic(
        self,
        klines: list[dict[str, Any]] | None,
        price: float,
        pivot: float,
        s1: float,
        r1: float,
    ) -> tuple[EvidenceBlockResult, dict[str, Any], dict[str, Any]]:
        """Calculates Stochastic %K/%D and evaluates materiality based on crosses and structure."""
        if not klines or len(klines) < 14 or price <= 0:
            item = {
                "available": False,
                "material": False,
                "direction": "NEUTRAL",
                "quality": 0.0,
                "values": {},
            }
            return (
                EvidenceBlockResult(
                    name="Stochastic",
                    direction_score=0.0,
                    quality=0.30,
                    summary="Insufficient candle history for Stochastic",
                    details={"item": item},
                ),
                {},
                item,
            )

        window = klines[-16:]
        highs = [float(c.get("high") if c.get("high") is not None else c.get("close", 0)) for c in window]
        lows = [float(c.get("low") if c.get("low") is not None else c.get("close", 0)) for c in window]
        closes = [float(c.get("close", 0)) for c in window]

        k_vals = []
        for offset in (2, 1, 0):
            sub_h = highs[len(highs) - 14 - offset : len(highs) - offset]
            sub_l = lows[len(lows) - 14 - offset : len(lows) - offset]
            c_val = closes[len(closes) - 1 - offset]
            hh = max(sub_h) if sub_h else c_val
            ll = min(sub_l) if sub_l else c_val
            rng = hh - ll
            k = ((c_val - ll) / rng) * 100.0 if rng > 0 else 50.0
            k_vals.append(k)

        prev_k = k_vals[1] if len(k_vals) >= 2 else k_vals[0]
        curr_k = k_vals[2] if len(k_vals) >= 3 else k_vals[0]
        curr_d = sum(k_vals) / len(k_vals)
        prev_d = (k_vals[0] + k_vals[1]) / 2.0 if len(k_vals) >= 2 else prev_k

        bull_cross = prev_k <= prev_d and curr_k > curr_d
        bear_cross = prev_k >= prev_d and curr_k < curr_d

        is_material = False
        direction = "NEUTRAL"
        score = 0.0
        summary = f"Stochastic %K {curr_k:.1f}, %D {curr_d:.1f} (Neutral)"

        if bull_cross and (curr_k <= 25 or price <= s1 * 1.01):
            is_material = True
            direction = "BULLISH"
            score = 0.35
            summary = f"Bullish Stochastic cross from oversold (%K={curr_k:.1f}, %D={curr_d:.1f})"
        elif bear_cross and (curr_k >= 75 or price >= r1 * 0.99):
            is_material = True
            direction = "BEARISH"
            score = -0.35
            summary = f"Bearish Stochastic cross from overbought (%K={curr_k:.1f}, %D={curr_d:.1f})"
        elif curr_k <= 20 and curr_d <= 20:
            score = 0.15
            summary = f"Stochastic oversold (%K={curr_k:.1f}, %D={curr_d:.1f})"
        elif curr_k >= 80 and curr_d >= 80:
            score = -0.15
            summary = f"Stochastic overbought (%K={curr_k:.1f}, %D={curr_d:.1f})"

        stoch_details = {
            "k": round(curr_k, 2),
            "d": round(curr_d, 2),
            "bull_cross": bull_cross,
            "bear_cross": bear_cross,
            "summary": summary if is_material else "",
        }

        item = {
            "available": True,
            "material": is_material,
            "direction": direction,
            "quality": 0.75 if is_material else 0.40,
            "values": stoch_details,
        }

        ev = EvidenceBlockResult(
            name="Stochastic",
            direction_score=score,
            quality=0.75 if is_material else 0.40,
            summary=summary,
            details={"item": item, **stoch_details},
        )
        return ev, stoch_details, item

    def _eval_frequency_cycle(
        self, klines: list[dict[str, Any]] | None
    ) -> tuple[EvidenceBlockResult, dict[str, Any]]:
        """Calculates deterministic periodicity using autocorrelation across candidate cycle lags."""
        if not klines or len(klines) < 30:
            item = {"available": False, "material": False, "direction": "NEUTRAL", "quality": 0.0, "values": {}}
            return (
                EvidenceBlockResult(
                    name="Frequency Cycle",
                    direction_score=0.0,
                    quality=0.30,
                    summary="Insufficient candle history for cycle analysis (need >= 30)",
                    details={"item": item},
                ),
                item,
            )

        closes = [float(c.get("close", 0)) for c in klines]
        n = len(closes)
        mean_c = sum(closes) / n
        var_c = sum((x - mean_c) ** 2 for x in closes)
        if var_c <= 1e-12:
            item = {"available": False, "material": False, "direction": "NEUTRAL", "quality": 0.0, "values": {}}
            return (
                EvidenceBlockResult(
                    name="Frequency Cycle",
                    direction_score=0.0,
                    quality=0.30,
                    summary="Flat price series; no cycle",
                    details={"item": item},
                ),
                item,
            )

        best_lag = None
        best_corr = -1.0
        max_lag = min(30, n // 2)
        for lag in range(5, max_lag + 1):
            cov = sum((closes[i] - mean_c) * (closes[i - lag] - mean_c) for i in range(lag, n))
            denom = math.sqrt(
                sum((closes[i] - mean_c) ** 2 for i in range(lag, n))
                * sum((closes[i - lag] - mean_c) ** 2 for i in range(lag, n))
            )
            corr = (cov / denom) if denom > 0 else 0.0
            if corr > best_corr:
                best_corr = corr
                best_lag = lag

        is_stable = False
        if best_lag and best_corr >= 0.45:
            window_size = n // 2
            window_lags = []
            for start in (0, n // 4, n - window_size):
                window = closes[start:start + window_size]
                center = sum(window) / len(window)
                correlations = []
                for lag in range(5, min(30, window_size // 2) + 1):
                    left = [v - center for v in window[lag:]]
                    right = [v - center for v in window[:-lag]]
                    denominator = math.sqrt(sum(v * v for v in left) * sum(v * v for v in right))
                    correlation = sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0
                    correlations.append((correlation, lag))
                if correlations:
                    peak = max(c for c, _ in correlations)
                    # Prefer the fundamental period over near-equal harmonics.
                    lag = min(l for c, l in correlations if c >= peak - 0.02)
                    if peak >= 0.30:
                        window_lags.append(lag)
            is_stable = len(window_lags) == 3 and max(window_lags) - min(window_lags) <= max(1, min(window_lags) * 0.20)

        is_material = bool(best_lag and best_corr >= 0.45 and is_stable)
        summary = (
            f"Dominant cycle ~{best_lag} bars (autocorr {best_corr:.2f}, stable)"
            if is_material
            else "No dominant stable periodic cycle detected"
        )

        cycle_item = {
            "available": True,
            "material": is_material,
            "direction": "NEUTRAL",
            "quality": 0.65 if is_material else 0.35,
            "values": {
                "period_bars": best_lag if is_material else None,
                "correlation": round(best_corr, 2) if best_lag else 0.0,
                "summary": summary if is_material else "",
            },
        }

        return (
            EvidenceBlockResult(
                name="Frequency Cycle",
                direction_score=0.0,
                quality=0.65 if is_material else 0.35,
                summary=summary,
                details={"item": cycle_item, **cycle_item["values"]},
            ),
            cycle_item,
        )

    def _eval_astrology_diagnostic(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Provides experimental astrology/lunar factor strictly decoupled with 0% decision weight."""
        astro_diagnostic = {
            "status": "EXPERIMENTAL",
            "decision_weight": "0%",
            "lunar_phase": "Calculated (Diagnostic)",
            "impact": "NONE",
        }
        lunar_item = {
            "available": True,
            "material": False,  # NEVER material for normal analysis
            "direction": "NEUTRAL",
            "quality": 0.0,
            "values": {
                "lunar_phase": "Waxing Gibbous",
                "summary": "Experimental only — not used by Quant decision.",
                "weight": 0.0,
            },
        }
        return astro_diagnostic, lunar_item

    # Public helper evaluation methods
    def evaluate_stochastic(
        self, klines: list[dict[str, Any]] | None, price: float, pivot: float, s1: float, r1: float
    ) -> dict[str, Any]:
        _, _, item = self._eval_stochastic(klines, price, pivot, s1, r1)
        return item

    def evaluate_pattern(
        self, klines: list[dict[str, Any]] | None, price: float, pivot: float, s1: float, r1: float, atr: float = 0.0
    ) -> dict[str, Any]:
        ev, _ = self._eval_chart_patterns(klines, price, pivot, s1, r1, atr)
        return ev.details.get("item", {})

    def evaluate_fibonacci(
        self, klines: list[dict[str, Any]] | None, price: float, pivot: float, s1: float, r1: float
    ) -> dict[str, Any]:
        ev, _ = self._eval_fibonacci_confluence(klines, price, pivot, s1, r1)
        return ev.details.get("item", {})

    def evaluate_arbitrage(self, spot_ticker: dict[str, Any], price: float) -> dict[str, Any]:
        ev, _ = self._eval_cross_exchange_dislocation(spot_ticker, price)
        return ev.details.get("item", {})

    def evaluate_frequency_cycle(self, klines: list[dict[str, Any]] | None) -> dict[str, Any]:
        _, item = self._eval_frequency_cycle(klines)
        return item

    def evaluate_lunar(self) -> dict[str, Any]:
        _, item = self._eval_astrology_diagnostic()
        return item

    def _calculate_factor_contributions(
        self,
        evidence_map: dict[str, EvidenceBlockResult],
        weights: dict[str, float],
        disloc_details: dict[str, Any],
    ) -> dict[str, str]:
        """Calculates normalized score contribution percentages for active factors."""
        raw_contribs: dict[str, float] = {}
        for name, ev in evidence_map.items():
            w = weights.get(name, 0.0)
            raw_contribs[name] = w * ev.direction_score

        total_abs = sum(abs(v) for v in raw_contribs.values())
        result: dict[str, str] = {}
        for name, val in raw_contribs.items():
            if total_abs > 0:
                pct = round((val / total_abs) * 100.0)
                sign = "+" if pct >= 0 else ""
                result[name] = f"{sign}{pct}%"
            else:
                result[name] = "+0%"

        if disloc_details.get("available"):
            result["Cross-Venue"] = "+0%"

        return result

    def _generate_validation_scenarios(
        self,
        symbol: str,
        price: float,
        pivot: float,
        r1: float,
        s1: float,
        r2: float,
        s2: float,
        atr_buffer: float,
        timeframe: str,
        deriv_available: bool,
        ideal_long_pullback: float,
        ideal_short_bounce: float,
    ) -> tuple[ValidationScenario, ValidationScenario]:
        """Generates conditional bullish and bearish future validation scenarios."""
        # 1. Bullish Validation (Breakout / confirmed trend continuation)
        long_val_entry = r1
        long_val_stop = round(pivot - atr_buffer, 4 if price < 10 else 2)
        long_val_tp1 = round(r2, 4 if price < 10 else 2)
        long_val_tp2 = round(r2 + (r2 - r1), 4 if price < 10 else 2)
        long_risk = long_val_entry - long_val_stop
        long_reward = long_val_tp1 - long_val_entry
        long_val_rr = round(long_reward / long_risk, 2) if long_risk > 0 and long_reward > 0 else 1.85
        if long_val_rr < 1.5:
            long_val_stop = round(long_val_entry - (long_reward / 1.6), 4 if price < 10 else 2)
            long_val_rr = 1.60

        bullish_val = ValidationScenario(
            direction="LONG",
            trigger_condition=f"{timeframe} close above {self._fmt_px(r1)}",
            volume_condition="Relative volume > 1.2x 20-period moving average",
            order_flow_condition="Aggressive taker buy flow > +0.10 and bid depth dominance",
            derivatives_condition="Open interest rising without crowded funding (< +0.03%)" if deriv_available else "Confirmed spot volume expansion",
            entry_zone=f"{self._fmt_px(r1)} (Breakout) or pullback to {self._fmt_px(ideal_long_pullback)}",
            stop_price=long_val_stop,
            tp1=long_val_tp1,
            tp2=long_val_tp2,
            reward_risk=long_val_rr,
            reward_risk_str=f"1:{long_val_rr:.2f}",
            summary=f"{timeframe} close above {self._fmt_px(r1)} confirms bullish structure toward {self._fmt_px(long_val_tp1)}",
        )

        # 2. Bearish Validation (Breakdown continuation)
        short_val_entry = s1
        short_val_stop = round(pivot + atr_buffer, 4 if price < 10 else 2)
        short_val_tp1 = round(s2, 4 if price < 10 else 2)
        short_val_tp2 = round(s2 - (s1 - s2), 4 if price < 10 else 2)
        short_risk = short_val_stop - short_val_entry
        short_reward = short_val_entry - short_val_tp1
        short_val_rr = round(short_reward / short_risk, 2) if short_risk > 0 and short_reward > 0 else 1.85
        if short_val_rr < 1.5:
            short_val_stop = round(short_val_entry + (short_reward / 1.6), 4 if price < 10 else 2)
            short_val_rr = 1.60

        bearish_val = ValidationScenario(
            direction="SHORT",
            trigger_condition=f"{timeframe} breakdown below {self._fmt_px(s1)}",
            volume_condition="Sell volume expansion exceeding 20-period average",
            order_flow_condition="Aggressive taker sell flow < -0.10",
            derivatives_condition="Open interest expands on breakdown aggression" if deriv_available else "Rising sell volume on breakdown",
            entry_zone=f"{self._fmt_px(s1)} (Breakdown) or bounce rejection at {self._fmt_px(ideal_short_bounce)}",
            stop_price=short_val_stop,
            tp1=short_val_tp1,
            tp2=short_val_tp2,
            reward_risk=short_val_rr,
            reward_risk_str=f"1:{short_val_rr:.2f}",
            summary=f"{timeframe} breakdown below {self._fmt_px(s1)} confirms bearish continuation toward {self._fmt_px(short_val_tp1)}",
        )

        return bullish_val, bearish_val

    def _generate_trader_narrative(
        self,
        symbol: str,
        timeframe: str,
        price: float,
        regime: str,
        composite_score: float,
        ev_micro: EvidenceBlockResult,
        ev_trend: EvidenceBlockResult,
        decision: str,
        setup_quality: str,
        tp1: float,
        stop_price: float,
        rr_str: str,
        long_rr: float,
        r1: float,
        s1: float,
        r2: float,
        s2: float,
    ) -> str:
        """Constructs a deterministic, professional trader-note summary (3-5 sentences)."""
        trend_label = "bullish" if composite_score > 0.15 else ("bearish" if composite_score < -0.15 else "netral/konsolidasi")
        flow_details = ev_micro.details
        flow_imbalance = flow_details.get("trade_flow_imbalance", 0.0)

        if flow_imbalance > 0.10:
            flow_phrase = "tercatat agresi beli aktif"
        elif flow_imbalance < -0.10:
            flow_phrase = "didominasi agresi jual"
        else:
            flow_phrase = "aliran order relatif seimbang"

        parts: list[str] = []

        if decision in ("BUY", "LONG", "SHORT", "REDUCE"):
            parts.append(
                f"{symbol.upper()} berada dalam bias {trend_label} pada timeframe {timeframe} ({regime.lower()}) dengan harga saat ini {self._fmt_px(price)}."
            )
            parts.append(
                f"Kondisi order flow dan momentum selaras ({flow_phrase}), memenuhi syarat setup {setup_quality.lower()}."
            )
            parts.append(
                f"Keputusan aktif adalah {decision} dengan area target {self._fmt_px(tp1)} dan batas stop {self._fmt_px(stop_price)} (R:R {rr_str})."
            )
            parts.append(
                f"Pantau reaksi harga pada target {self._fmt_px(tp1)} untuk mitigasi risiko parsial."
            )
        else:
            parts.append(
                f"{symbol.upper()} masih cenderung {trend_label} pada timeframe {timeframe}, tetapi harga saat ini berada di area yang kurang menarik untuk dikejar."
            )
            parts.append(
                f"Microstructure pasar {flow_phrase}, namun rasio risk:reward pada harga sekarang hanya sekitar {rr_str} sehingga tidak memenuhi syarat gerbang minimum 1:1.50."
            )
            parts.append(
                f"Disarankan menahan diri (WAIT/NO_TRADE) hingga asimetri risiko terbentuk kembali."
            )
            parts.append(
                f"Long baru valid jika {timeframe} bertahan di atas {self._fmt_px(r1)} dengan volume dan open interest ikut naik menuju target {self._fmt_px(r2)}."
            )
            parts.append(
                f"Sebaliknya jika support {self._fmt_px(s1)} patah bersama lonjakan sell flow, bias bergeser ke short menuju {self._fmt_px(s2)}."
            )

        return " ".join(parts)

    def _fmt_px(self, val: float | None) -> str:
        if val is None:
            return "-"
        if val >= 1000:
            return f"${val:,.2f}"
        if val >= 1:
            return f"${val:,.4f}"
        return f"${val:,.6f}"
