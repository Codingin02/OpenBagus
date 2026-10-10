"""OpenBagus Canonical Crypto Quantitative Decision Engine."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
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
    entry_price: float = 0.0
    scenario_type: str = "Breakout"
    rr_gate_passed: bool = False
    trigger_level: float | None = None
    trigger_state: str = "UNKNOWN"


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
    data_freshness: str = "UNVERIFIED"
    contradictions: list[str] = field(default_factory=list)
    evidence_families: dict[str, str] = field(default_factory=dict)
    structure_levels: dict[str, float] = field(default_factory=dict)


class QuantEngine:
    MINIMUM_REWARD_RISK: float = 1.5
    DEFAULT_HARD_LEVERAGE_MAX: int = 3
    MIN_INDEPENDENT_EVIDENCE_COUNT: int = 3
    MIN_COMPOSITE_QUALITY: float = 0.45

    def __init__(self, hard_leverage_max: int = DEFAULT_HARD_LEVERAGE_MAX) -> None:
        self.hard_leverage_max = hard_leverage_max

    def evaluate_equity(self, symbol: str, data: dict, policy: Any, *, timeframe: str = "D1",
                        has_position_context: bool = False, is_index: bool = False,
                        now: Any = None) -> QuantDecisionResult:
        from datetime import datetime, timezone
        from openbagus.domains.equities.data import timestamp

        now = now or datetime.now(timezone.utc)
        quote = data.get("quote", {})
        price = validate_finite_number(quote.get("price"), min_val=0) or 0.0
        fresh = policy.freshness(quote, now)
        gaps = list(data.get("gaps", []))
        if not price:
            gaps.append("Harga IDR belum tersedia")
        if fresh != "FRESH":
            gaps.append(f"Data Freshness: {fresh}; bukan harga aktif terverifikasi")
        if data.get("timeframe") != timeframe:
            gaps.append(f"OHLCV {data.get('timeframe', 'UNAVAILABLE')} tidak mendukung {timeframe}")
        bars = []
        for bar in data.get("candles", []):
            end = timestamp(bar["close_at"])
            if end <= now:
                bars.append({**{k: float(bar[k]) for k in ("open", "high", "low", "close", "volume")},
                             "time": timestamp(bar["open_at"]).timestamp() * 1000,
                             "close_time": end.timestamp() * 1000, "is_closed": True})
        bars, valid = self._closed_candles(bars)
        if len(bars) < 21 or not valid:
            gaps.append("Minimal 21 closed OHLCV diperlukan")
        horizon_seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800,
                           "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800}.get(timeframe, 0)
        latest_age = (now.timestamp() - bars[-1]["close_time"] / 1000) if bars else float("inf")
        if not horizon_seconds or latest_age > horizon_seconds * (5 if timeframe in {"D1", "W1"} else 2):
            gaps.append("Closed candles stale; technical levels are historical only")
        if data.get("adjustment") == "unadjusted" and data.get("unresolved_corporate_actions") is not False:
            gaps.append("Split/dividen/rights adjustment belum terkonfirmasi")
        if data.get("listing_status") != "ACTIVE" or data.get("board") not in {"MAIN", "DEVELOPMENT", "NEW_ECONOMY"}:
            gaps.append("Listing/suspension/board belum memenuhi regular-market guard")
        if data.get("market_segment", "regular") != "regular":
            gaps.append("Setup aktif hanya untuk pasar reguler, bukan tunai/negosiasi/FCA")
        session = policy.session_status(now)
        if session != "OPEN":
            gaps.append(f"Market session: {session}")
        source = data.get("source")
        q = QuantDecisionResult(symbol, "IDX INDEX" if is_index else "IDX CASH EQUITY", "WAIT",
            "UNVERIFIED", "LOW", price, "N/A", None, None, None, None, "N/A", "N/A", 0,
            {}, [source] if source else [], 0, 0.0, 0.0, False, False, timeframe=timeframe,
            data_quality="LOW", data_freshness=fresh)
        if bars and price:
            high, low = bars[-1]["high"], bars[-1]["low"]
            trend = self._eval_trend_momentum(price, high, low, 0, bars, timeframe)
            vol = self._eval_volatility_regime(price, high, low, bars)
            support = min(b["low"] for b in bars[-20:])
            resistance = max(b["high"] for b in bars[-20:])
            q.structure_levels = {"support": support, "resistance": resistance}
            q.regime = "UPTREND" if trend.direction_score > 0.2 else ("DOWNTREND" if trend.direction_score < -0.2 else "RANGE")
            q.factor_contributions = {"EMA": str(trend.details), "ATR": str(vol.details)}
            average_volume = sum(b["volume"] for b in bars[-21:-1]) / min(20, max(1, len(bars) - 1))
            relative_volume = bars[-1]["volume"] / average_volume if average_volume > 0 else None
            q.microstructure = {"relative_volume": relative_volume, "volume_unit": "shares",
                                "atr": vol.details.get("atr"), "institutional_flow": "UNAVAILABLE"}
            q.evidence_families = {"Price": q.regime, "Volume": "CONFIRMED" if relative_volume and relative_volume >= 1.2 else "UNCONFIRMED"}
            q.evidence_count = int(trend.quality >= 0.35) + int(relative_volume is not None)
            benchmark = data.get("benchmark_candles", [])
            if benchmark and len(benchmark) == len(data.get("candles", [])) and len(bars) == len(benchmark):
                aligned = all(a["close_at"] == b.get("close_at") for a, b in zip(data["candles"], benchmark))
                if aligned and len(benchmark) >= 21:
                    b0, b1 = benchmark[-21], benchmark[-1]
                    if float(b0["close"]) > 0 and timestamp(b1["close_at"]) <= now:
                        q.microstructure["relative_strength_vs_IHSG_pct"] = ((bars[-1]["close"] / bars[-21]["close"] - 1)
                            - (float(b1["close"]) / float(b0["close"]) - 1)) * 100
            if is_index:
                gaps.append("Indeks bukan saham yang dapat dibeli langsung; outlook saja")
            if not gaps:
                try:
                    reference = float(quote["previous_close"])
                    lower, upper = float(quote["price_limit_low"]), float(quote["price_limit_high"])
                    fees = data["fees"]
                    buy_fee, sell_fee = float(fees["buy"]), float(fees["sell"])
                    if not all(math.isfinite(v) for v in (reference, lower, upper, buy_fee, sell_fee)) or not 0 < lower <= price <= upper or not 0 <= min(buy_fee, sell_fee) <= max(buy_fee, sell_fee) < 1:
                        raise ValueError("Price bounds/costs unavailable")
                    entry = policy.round_price(price, reference, up=True)
                    stop = policy.round_price(support, reference, up=False)
                    target = policy.round_price(resistance, reference, up=False)
                    risk = entry - stop + entry * buy_fee + stop * sell_fee
                    reward = target - entry - entry * buy_fee - target * sell_fee
                    rr = reward / risk if risk > 0 else 0.0
                    if lower <= stop < entry < target <= upper and rr >= self.MINIMUM_REWARD_RISK:
                        q.bullish_validation = ValidationScenario("BUY", "Harga bertahan di atas support dengan volume >= 1.2x rata-rata 20 bar",
                            "Relative volume >= 1.2", "Order flow belum tersedia", "Tidak berlaku untuk cash equity",
                            f"Rp{entry:,.0f}", stop, target, target, rr, f"1:{rr:.2f}", entry_price=entry,
                            scenario_type="Structural continuation", rr_gate_passed=True, trigger_level=entry, trigger_state="UNCONFIRMED")
                    q.quality_gate_passed = True
                    q.data_quality = "MODERATE"
                    if q.regime == "UPTREND" and relative_volume and relative_volume >= 1.2 and q.bullish_validation:
                        q.decision = "BUY"
                        q.entry_zone, q.stop_price, q.tp1 = f"Rp{entry:,.0f}", stop, target
                        q.reward_risk, q.reward_risk_str, q.rr_gate_passed = rr, f"1:{rr:.2f}", True
                        q.setup_quality = "MODERATE"
                        q.bullish_validation.trigger_state = "CONFIRMED"
                    elif q.regime == "DOWNTREND":
                        q.decision = "REDUCE" if has_position_context else "AVOID_ENTRY"
                    elif has_position_context:
                        q.decision = "HOLD"
                    else:
                        gaps.append("Volume, arah tren atau RR struktural belum mendukung entry")
                except (ValueError, TypeError, KeyError, ZeroDivisionError):
                    gaps.append("Fraksi harga, batas harga instrumen atau biaya belum terverifikasi")
        q.decision_reason = "; ".join(gaps) if gaps else "Struktur, volume dan batas risiko mendukung research view; bukan order."
        q.why_now = q.decision_reason
        q.why = {"risk": q.decision_reason}
        return q

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
        has_position_context: bool = False,
    ) -> QuantDecisionResult:
        price = validate_finite_number(spot_ticker.get("price"), min_val=0.0) or 0.0
        high = validate_finite_number(spot_ticker.get("high"), min_val=0.0) or price
        low = validate_finite_number(spot_ticker.get("low"), min_val=0.0) or price
        range_valid = 0 < low <= price <= high and high > low
        freshness = self._freshness(spot_ticker.get("observed_at"))
        klines, candles_valid = self._closed_candles(klines)
        bar_seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600,
                       "H4": 14400, "H6": 21600, "H12": 43200, "D1": 86400, "W1": 604800}.get(timeframe, 3600)
        last_close = (klines[-1].get("close_time") or klines[-1].get("time")) if klines else None
        candle_age = (time.time() - last_close / 1000) if isinstance(last_close, (int, float)) else None
        candles_fresh = candle_age is not None and 0 <= candle_age <= bar_seconds * 2
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

        orderbook = orderbook if self._freshness((orderbook or {}).get("observed_at")) == "FRESH" else None
        trades = trades if self._freshness((trades or {}).get("observed_at")) == "FRESH" else None
        derivatives = derivatives if self._freshness((derivatives or {}).get("observed_at")) == "FRESH" else None
        sentiment = sentiment if self._freshness((sentiment or {}).get("timestamp"), max_age=172800) == "FRESH" else None

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
        ev_fib, fib_details = self._eval_fibonacci_confluence(klines, price, pivot, s1, r1, ev_vol.details.get("atr"))
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

        # Price-derived confluence is one family, not several independent votes.
        independent = {"Price": ev_trend, "Microstructure": ev_micro,
                       "Derivatives": ev_deriv, "Context": ev_context}
        active_count = sum(e.quality >= 0.35 for e in independent.values())
        quality_gate_passed = (
            active_count >= self.MIN_INDEPENDENT_EVIDENCE_COUNT
            and composite_quality >= self.MIN_COMPOSITE_QUALITY
            and freshness == "FRESH" and range_valid and candles_valid and candles_fresh
        )

        if composite_quality >= 0.70 and active_count >= 4:
            data_quality = "HIGH"
        elif composite_quality >= 0.45 and active_count >= 3:
            data_quality = "MODERATE"
        else:
            data_quality = "LOW"
        confidence = data_quality
        if freshness != "FRESH" or not range_valid or not candles_valid or not candles_fresh:
            data_quality = confidence = "LOW"

        regime = ev_vol.details.get("regime", "CHOPPY")
        atr = ev_vol.details.get("atr", atr_approx)
        atr_buffer = max(price * 0.005, atr * 0.5 if atr > 0 else (high - low) * 0.3)

        # --- Evaluate Candidate LONG ---
        long_stop = round(s1 - atr_buffer, 4 if price < 10 else 2)
        long_tp1 = round(r1, 4 if price < 10 else 2)
        long_tp2 = round(r2, 4 if price < 10 else 2)
        long_risk_span = price - long_stop
        long_reward_span = long_tp1 - price
        long_rr = round(long_reward_span / long_risk_span, 2) if long_risk_span > 0 and long_reward_span > 0 else 0.0
        long_rr_passed = 0 < long_stop < price < long_tp1 and long_rr >= self.MINIMUM_REWARD_RISK

        if composite_score >= 0.20 and long_rr_passed and quality_gate_passed:
            long_setup_quality = "STRONG"
        elif composite_score >= 0.05 or long_rr >= 1.2:
            long_setup_quality = "MODERATE"
        else:
            long_setup_quality = "INSUFFICIENT"

        cand_long = CandidateSetup(
            direction="LONG",
            entry_zone=self._fmt_px(price),
            stop_price=long_stop,
            tp1=long_tp1,
            tp2=long_tp2,
            reward_risk=long_rr,
            reward_risk_str=f"1:{long_rr:.2f}" + ("" if long_rr_passed else " (< 1.5 gate)"),
            setup_quality=long_setup_quality,
            rr_gate_passed=long_rr_passed,
            reason="Reward-to-risk below 1.5" if not long_rr_passed else "",
            watch_trigger="Wait for a structurally valid pullback with sufficient R:R" if not long_rr_passed else "",
        )

        # --- Evaluate Candidate SHORT ---
        short_stop = round(r1 + atr_buffer, 4 if price < 10 else 2)
        short_tp1 = round(s1, 4 if price < 10 else 2)
        short_tp2 = round(s2, 4 if price < 10 else 2)
        short_risk_span = short_stop - price
        short_reward_span = price - short_tp1
        short_rr = round(short_reward_span / short_risk_span, 2) if short_risk_span > 0 and short_reward_span > 0 else 0.0
        short_rr_passed = 0 < short_tp1 < price < short_stop and short_rr >= self.MINIMUM_REWARD_RISK

        if composite_score <= -0.20 and short_rr_passed and quality_gate_passed:
            short_setup_quality = "STRONG"
        elif composite_score <= -0.05 or short_rr >= 1.2:
            short_setup_quality = "MODERATE"
        else:
            short_setup_quality = "INSUFFICIENT"

        cand_short = CandidateSetup(
            direction="SHORT",
            entry_zone=self._fmt_px(price),
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
            elif composite_score <= -0.25 and quality_gate_passed:
                decision = "REDUCE" if has_position_context else "AVOID_ENTRY"
                chosen = None
                setup_quality = "MODERATE"
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
                decision_reason = f"Price freshness {freshness}; candle integrity/freshness {'OK' if candles_valid and candles_fresh else 'DATA_GAP'}; {active_count} independent evidence families. Fresh, valid data and at least three families are required."
                watch_trigger = "Verify fresh price, closed candles and independent order-flow/positioning/context evidence."
                why_now = f"Harga {freshness}; candle {'valid/segar' if candles_valid and candles_fresh else 'belum valid/segar'}; {active_count} keluarga bukti independen. Konfluensi harga bukan konfirmasi independen."
            elif not long_rr_passed and not short_rr_passed:
                decision_reason = f"Reward-to-risk at current price (Long 1:{long_rr:.2f}, Short 1:{short_rr:.2f}) does not meet 1:1.50 minimum gate."
                watch_trigger = f"Wait for a structurally valid pullback or resistance reaction at {self._fmt_px(r1)} with sufficient R:R."
                why_now = f"Struktur harga {timeframe} belum memberi rasio risk:reward memadai (Long 1:{long_rr:.2f}, Short 1:{short_rr:.2f}); entry sekarang terlalu dekat resistance/support."
            elif abs(composite_score) < 0.20:
                decision_reason = f"Market is in a neutral/choppy regime (composite score {composite_score:+.2f}) without directional momentum."
                watch_trigger = f"Wait for confirmed breakout above {self._fmt_px(r1)} or breakdown below {self._fmt_px(s1)} on rising volume."
                why_now = f"Harga sedang bergerak sideways dalam rentang kompresi ({regime}) tanpa dominasi pembeli maupun penjual."
            else:
                decision_reason = "Setup conditions do not provide a favorable asymmetric risk/reward edge."
                watch_trigger = f"Monitor price reaction near key pivot level {self._fmt_px(pivot)}."
                why_now = "Kondisi teknikal dan likuiditas belum menghasilkan tepi asimetris yang layak ditradingkan."

        if m_lower == "spot" and decision in {"REDUCE", "AVOID_ENTRY"}:
            decision_reason = ("Existing-position review: bearish spot evidence supports a reduction review; no order is executed."
                               if has_position_context else "Bearish spot evidence: avoid a new entry; no existing holding is assumed.")

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
            composite_score=composite_score,
            klines=klines,
        )
        if not range_valid or not candles_valid:
            bullish_val = bearish_val = None
        contradictions = []
        if ev_trend.direction_score * ev_micro.direction_score < -0.05:
            contradictions.append("Trend and observed order flow disagree; require a closed-candle trigger with flow confirmation.")
        if ev_trend.direction_score * ev_deriv.direction_score < -0.05 and deriv_available:
            contradictions.append("Price trend and funding positioning disagree; crowded funding is a risk, not a reversal confirmation.")
        if ev_micro.details.get("order_book_imbalance", 0) * ev_micro.details.get("trade_flow_imbalance", 0) < -0.02:
            contradictions.append("Resting book and executed trade flow disagree; book liquidity alone does not confirm buying/selling.")
        if ev_trend.direction_score > 0.20 and stoch_details.get("k", 50) >= 80:
            contradictions.append(f"Bullish trend with Stochastic overbought (%K={stoch_details.get('k', 0):.1f}); momentum extended near resistance.")
        elif ev_trend.direction_score < -0.20 and stoch_details.get("k", 50) <= 20:
            contradictions.append(f"Bearish trend with Stochastic oversold (%K={stoch_details.get('k', 0):.1f}); downward momentum extended near support.")
        if disloc_details.get("arbitrage_status") == "EXECUTION_RISK":
            contradictions.append("Cross-venue bid-ask spread is abnormally wide; execution slippage risk is elevated.")

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
            data_freshness=freshness,
            contradictions=contradictions,
            evidence_families={k: e.summary for k, e in independent.items() if e.quality >= 0.35},
            structure_levels={"support": s1, "resistance": r1, "pivot": pivot},
        )

    @staticmethod
    def _freshness(observed_at: Any, max_age: float = 180) -> str:
        try:
            if isinstance(observed_at, (int, float)) or str(observed_at).isdigit():
                stamp = datetime.fromtimestamp(float(observed_at), timezone.utc)
            else:
                stamp = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                return "UNVERIFIED"
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            return "FRESH" if -5 <= age <= max_age else "STALE" if age > max_age else "FUTURE"
        except (TypeError, ValueError, OverflowError, OSError):
            return "UNVERIFIED"

    @staticmethod
    def _closed_candles(candles: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], bool]:
        accepted = []
        valid = True
        now_ms = time.time() * 1000
        seen = set()
        for candle in sorted(candles or [], key=lambda c: validate_finite_number(c.get("time")) or 0):
            end = validate_finite_number(candle.get("close_time"))
            start = validate_finite_number(candle.get("time"))
            if candle.get("is_closed") is False or (end is not None and end > now_ms) or (start is not None and start > now_ms):
                continue
            values = [validate_finite_number(candle.get(k), min_val=0) for k in ("high", "low", "close")]
            high, low, close = values
            opening = validate_finite_number(candle.get("open", close), min_val=0)
            if None in values or opening is None or not 0 < low <= min(opening, close) <= max(opening, close) <= high:
                valid = False
                continue
            stamp = candle.get("time")
            if stamp is not None and stamp in seen:
                valid = False
                continue
            if stamp is not None:
                seen.add(stamp)
            accepted.append({**candle, "high": high, "low": low, "close": close, "open": opening,
                             "volume": validate_finite_number(candle.get("volume"), min_val=0) or 0.0})
        return accepted, valid

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        alpha = 2.0 / (period + 1)
        result = values[0]
        for value in values[1:]:
            result += alpha * (value - result)
        return result

    def _eval_trend_momentum(
        self, price: float, high: float, low: float, pct_change: float, klines: list[dict[str, Any]] | None, timeframe: str = "H1"
    ) -> EvidenceBlockResult:
        ema8 = ema21 = None
        if klines and len(klines) >= 21:
            closes = [c["close"] for c in klines]
            h1_ret = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 else 0.0
            h4_ret = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else 0.0

            ema8 = self._ema(closes, 8)
            ema21 = self._ema(closes, 21)
            ema_bias = 0.5 if ema8 > ema21 else -0.5 if ema8 < ema21 else 0.0

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
            details={"score": round(score, 2), "pct_change": pct_change, "timeframe": timeframe,
                     "ema8": ema8, "ema21": ema21, "return_horizon": "1 and 4 bars; not independent higher-timeframe candles"},
        )

    def _eval_volatility_regime(
        self, price: float, high: float, low: float, klines: list[dict[str, Any]] | None
    ) -> EvidenceBlockResult:
        range_pct = ((high - low) / low * 100.0) if low > 0 else 0.0

        atr = 0.0
        if klines and len(klines) >= 15:
            tr_list = []
            for i in range(1, len(klines)):
                c_prev = klines[i - 1]["close"]
                h_cur = klines[i]["high"]
                l_cur = klines[i]["low"]
                tr = max(h_cur - l_cur, abs(h_cur - c_prev), abs(l_cur - c_prev))
                tr_list.append(tr)
            atr = sum(tr_list[:14]) / 14
            for tr in tr_list[14:]:
                atr = (atr * 13 + tr) / 14

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
            quality=0.80 if atr > 0 else 0.30,
            summary=summary,
            details={"regime": regime, "atr": atr, "range_pct": range_pct,
                     "atr_status": "WILDER_14" if atr > 0 else "DATA_GAP"},
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
        if quote_vol > 500_000_000:
            liq_label = "Tier 1 Liquid"
        elif quote_vol > 50_000_000:
            liq_label = "Moderate Liquid"
        elif quote_vol > 5_000_000:
            liq_label = "Low Liquidity"
        else:
            liq_label = "Illiquid / Thin"

        ob_imbalance = 0.0
        microprice_dev = 0.0
        has_ob = False
        if orderbook and validate_finite_number(orderbook.get("imbalance"), min_val=-1, max_val=1) is not None:
            has_ob = True
            ob_imbalance = float(orderbook.get("imbalance") or 0.0)
            microprice_dev = validate_finite_number(orderbook.get("microprice_dev_bps")) or 0.0

        trade_flow = 0.0
        trade_status = "DATA_GAP"
        if trades and trades.get("status") == "OK" and validate_finite_number(trades.get("trade_flow_imbalance"), min_val=-1, max_val=1) is not None:
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
            micro_score = 0.0
            quality = 0.0
            summary = f"Order book / trade flow DATA_GAP ({liq_label}); turnover is not order flow"

        combined_score = max(-1.0, min(1.0, micro_score))

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

        funding_rate = validate_finite_number(derivatives.get("funding_rate"))
        if funding_rate is None:
            return EvidenceBlockResult("Derivatives / Basis", 0, 0, "Funding DATA_GAP")
        zscore = validate_finite_number(derivatives.get("funding_zscore")) or 0.0
        basis = validate_finite_number(derivatives.get("basis")) or 0.0
        basis_bps = validate_finite_number(derivatives.get("basis_bps")) or 0.0
        oi = validate_finite_number(derivatives.get("open_interest"), min_val=0)

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
                "open_interest_unit": derivatives.get("open_interest_unit", "UNKNOWN"),
                "open_interest_change_pct": None,
            },
        )

    def _eval_context_sentiment(
        self, sentiment: dict[str, Any] | None, stablecoins: dict[str, Any] | None, is_major: bool = True
    ) -> EvidenceBlockResult:
        fng_val = validate_finite_number((sentiment or {}).get("value"), min_val=0, max_val=100)
        if fng_val is None:
            return EvidenceBlockResult(
                name="Context / Sentiment",
                direction_score=0.0,
                quality=0.0,
                summary="Sentiment DATA_GAP",
                details={},
            )

        fng_val = int(fng_val)
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
        atr: float | None = None,
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

        if atr is None:
            atr = self._eval_volatility_regime(price, swing_high, swing_low, klines).details.get("atr", 0.0)
        thresh = max(0.0, atr * 0.25)
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
            if any(abs(target_fib - structure) <= thresh for structure in (s1, r1, pivot)):
                independent_confluence = True

        long_risk = price - (s1 - atr * 0.5)
        short_risk = (r1 + atr * 0.5) - price
        actionable = ((long_risk > 0 and (r1 - price) / long_risk >= self.MINIMUM_REWARD_RISK)
                      or (short_risk > 0 and (price - s1) / short_risk >= self.MINIMUM_REWARD_RISK))
        is_material = bool(span >= 2 * atr > 0 and confluence_level and independent_confluence and actionable)

        fib_details = {
            "swing_high": swing_high,
            "swing_low": swing_low,
            "fib_382": round(fib_382, 4 if price < 10 else 2),
            "fib_500": round(fib_500, 4 if price < 10 else 2),
            "fib_618": round(fib_618, 4 if price < 10 else 2),
            "fib_786": round(fib_786, 4 if price < 10 else 2),
            "confluence": confluence_level or "",
            "independent_confluence": independent_confluence,
            "actionable_structure": actionable,
            "proximity_atr": abs(price - target_fib) / atr if confluence_level and atr else None,
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
                direction_score=round(score, 2) if is_material else 0.0,
                quality=0.70,
                summary=summary,
                details={"item": fib_item, **fib_details},
            ),
            fib_details,
        )

    def _eval_cross_exchange_dislocation(
        self, spot_ticker: dict[str, Any], price: float
    ) -> tuple[EvidenceBlockResult, dict[str, Any]]:
        """Compares fresh cross-exchange quotes to detect executable price dispersion and market stress."""
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

        from openbagus.domains.crypto.arbitrage import ArbitrageEngine
        arb_engine = ArbitrageEngine()
        opp = arb_engine.evaluate_cross_venue_arbitrage(
            symbol=spot_ticker.get("symbol", "CRYPTO"),
            venues=quotes,
            declared_notional=1000.0,
        )

        min_px = min(valid_prices)
        max_px = max(valid_prices)
        sorted_p = sorted(valid_prices)
        med_px = sorted_p[len(sorted_p) // 2]
        dispersion_pct = ((max_px - min_px) / med_px) * 100.0 if med_px > 0 else 0.0

        estimated_cost_pct = 0.25
        estimated_net_spread_pct = round(dispersion_pct - estimated_cost_pct, 3)

        if dispersion_pct < 0.15:
            dislocation_cls = "NORMAL"
        elif dispersion_pct < 0.50:
            dislocation_cls = "ELEVATED"
        else:
            dislocation_cls = "HIGH"

        best_venue = opp.buy_venue if opp.buy_venue != "N/A" else next((k for k, v in quotes.items() if v["price"] == min_px), "Market")
        summary = f"Dispersion {dispersion_pct:.2f}% ({dislocation_cls}), best venue: {best_venue} [{opp.status}]"

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
                "arbitrage_status": opp.status,
                "rationale": opp.rationale,
                "summary": summary if is_material else "",
            },
        }

        disloc_details = {
            "available": True,
            "venues_count": len(valid_prices),
            "dispersion_pct": round(dispersion_pct, 2),
            "dislocation_status": dislocation_cls,
            "arbitrage_status": opp.status,
            "estimated_net_spread_pct": round(opp.net_spread_pct, 3),
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
        if not klines or len(klines) < 17 or price <= 0:
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

        window = klines[-17:]
        highs = [float(c.get("high") if c.get("high") is not None else c.get("close", 0)) for c in window]
        lows = [float(c.get("low") if c.get("low") is not None else c.get("close", 0)) for c in window]
        closes = [float(c.get("close", 0)) for c in window]

        k_vals = []
        for offset in (3, 2, 1, 0):
            sub_h = highs[len(highs) - 14 - offset : len(highs) - offset]
            sub_l = lows[len(lows) - 14 - offset : len(lows) - offset]
            c_val = closes[len(closes) - 1 - offset]
            hh = max(sub_h) if sub_h else c_val
            ll = min(sub_l) if sub_l else c_val
            rng = hh - ll
            k = ((c_val - ll) / rng) * 100.0 if rng > 0 else 50.0
            k_vals.append(k)

        prev_k = k_vals[-2]
        curr_k = k_vals[-1]
        curr_d = sum(k_vals[-3:]) / 3
        prev_d = sum(k_vals[:3]) / 3

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
        from openbagus.intelligence.astro import LunarCycleResearch
        lunar_info = LunarCycleResearch.get_lunar_phase()
        astro_diagnostic = {
            "status": "EXPERIMENTAL",
            "decision_weight": "0%",
            "lunar_phase": lunar_info.phase_name,
            "illumination_pct": lunar_info.illumination_pct,
            "impact": "NONE",
        }
        lunar_item = {
            "available": True,
            "material": False,  # NEVER material for normal analysis
            "direction": "NEUTRAL",
            "quality": 0.0,
            "values": {
                "lunar_phase": lunar_info.phase_name,
                "illumination_pct": lunar_info.illumination_pct,
                "summary": f"{lunar_info.phase_name} ({lunar_info.illumination_pct:.0f}% iluminasi) — Riset eksperimental; bobot 0%.",
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
        composite_score: float = 0.0,
        klines: list[dict[str, Any]] | None = None,
    ) -> tuple[ValidationScenario | None, ValidationScenario | None]:
        """Choose one gated, structurally consistent scenario per direction."""
        variants = (
            ("LONG", "Breakout", r1, pivot - atr_buffer, r2, r2 + (r2 - r1)),
            ("LONG", "Pullback", s1, s2 - atr_buffer, r1, r2),
            ("SHORT", "Breakdown", s1, pivot + atr_buffer, s2, s2 - (s1 - s2)),
            ("SHORT", "Rejection", r1, r2 + atr_buffer, s1, s2),
        )
        candidates = [self._validation_candidate(*variant, timeframe, deriv_available, klines) for variant in variants]
        selected = []
        for direction in ("LONG", "SHORT"):
            valid = [c for c in candidates if c and c.direction == direction and c.rr_gate_passed]
            momentum_aligned = composite_score >= 0.20 if direction == "LONG" else composite_score <= -0.20
            selected.append(max(valid, key=lambda c: (momentum_aligned == (c.scenario_type in {"Breakout", "Breakdown"}), c.reward_risk), default=None))
        return selected[0], selected[1]

    def _validation_candidate(self, direction: str, style: str, entry: float, stop: float,
                              tp1: float, tp2: float, timeframe: str, derivatives: bool,
                              klines: list[dict[str, Any]] | None = None) -> ValidationScenario | None:
        geometry = 0 < stop < entry < tp1 if direction == "LONG" else 0 < tp1 < entry < stop
        if not geometry or not all(math.isfinite(v) for v in (entry, stop, tp1, tp2)):
            return None
        risk, reward = abs(entry - stop), abs(tp1 - entry)
        rr = reward / risk
        relation = "above" if direction == "LONG" else "below"
        trigger = f"{timeframe} close {relation} {self._fmt_px(entry)}"
        if style == "Pullback":
            trigger = f"{timeframe} reaction/hold at {self._fmt_px(entry)} with close above support"
        elif style == "Rejection":
            trigger = f"{timeframe} rejection at {self._fmt_px(entry)} with close below resistance"
        return ValidationScenario(
            direction=direction, trigger_condition=trigger,
            volume_condition="Volume expansion relative to recent candles",
            order_flow_condition="Bid dominance" if direction == "LONG" else "Sell flow dominance",
            derivatives_condition="Non-crowded funding and aligned OI" if derivatives else "Spot volume confirmation",
            entry_zone=self._fmt_px(entry), stop_price=stop, tp1=tp1, tp2=tp2,
            reward_risk=rr, reward_risk_str=f"1:{rr:.2f}", entry_price=entry,
            scenario_type=style, rr_gate_passed=rr >= self.MINIMUM_REWARD_RISK,
            trigger_level=entry, trigger_state=self._trigger_state(direction, style, entry, timeframe, klines),
            summary=f"Conditional {style.lower()}: {trigger}",
        )

    @staticmethod
    def _trigger_state(direction: str, style: str, level: float, timeframe: str,
                       klines: list[dict[str, Any]] | None) -> str:
        seconds = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600,
                   "H4": 14400, "H6": 21600, "H12": 43200, "D1": 86400, "W1": 604800}.get(timeframe)
        closed = []
        for candle in klines or []:
            timestamp = validate_finite_number(candle.get("time"))
            end = validate_finite_number(candle.get("close_time"))
            if end and end > 1e10:
                end /= 1000
            if timestamp and timestamp > 1e10:
                timestamp /= 1000
            is_closed = candle.get("is_closed")
            if is_closed is None:
                is_closed = bool((end and end <= time.time()) or (timestamp and seconds and timestamp + seconds <= time.time()))
            close = validate_finite_number(candle.get("close"), min_val=0)
            if is_closed and close is not None:
                closed.append(candle)
        if not closed:
            return "UNKNOWN"
        candle = closed[-1]
        confirmed = float(candle["close"]) > level if direction == "LONG" else float(candle["close"]) < level
        if style == "Pullback":
            confirmed = confirmed and candle.get("low") is not None and float(candle["low"]) <= level
        elif style == "Rejection":
            confirmed = confirmed and candle.get("high") is not None and float(candle["high"]) >= level
        return "CONFIRMED" if confirmed else "NOT_CONFIRMED"

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
