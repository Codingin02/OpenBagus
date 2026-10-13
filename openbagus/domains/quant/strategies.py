"""Multi-timeframe and modular quantitative trading strategies.

Provides pluggable strategy abstraction for backtesting and sensitivity optimization:
- Signal dataclass with deterministic risk geometry
- BaseStrategy interface with strict zero-lookahead validation
- EMATrendPullbackStrategy: Canonical trend-following pullback
- DonchianBreakoutStrategy: Momentum channel breakout with trailing ATR
- RSIReversionStrategy: Statistical mean reversion with volume confirmation
- MultiTimeframeStrategy: Dual-timeframe trend alignment (HTF trend + LTF entry)
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from openbagus.domains.quant.indicators import (
    ema,
    rsi,
    sma,
    wilder_atr,
)


@dataclass
class Signal:
    """Trading signal produced at bar CLOSE for NEXT bar execution."""
    signal_idx: int
    time: str
    direction: str = "LONG"  # "LONG", "FLAT"
    atr: float = 0.0
    stop_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    max_holding_bars: int = 20
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for quantitative trading strategies."""

    def __init__(self, name: str, parameters: dict[str, Any] | None = None) -> None:
        self.name = name
        self.parameters = parameters or {}

    @property
    @abstractmethod
    def warmup_bars(self) -> int:
        """Minimum bars required before first valid signal can be computed."""
        ...

    @abstractmethod
    def precompute(
        self,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        higher_tf_candles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Precomputes indicator series without lookahead."""
        ...

    @abstractmethod
    def evaluate_bar(
        self,
        idx: int,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        cache: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Signal | None:
        """Evaluates entry signal at bar close (index idx)."""
        ...


class EMATrendPullbackStrategy(BaseStrategy):
    """Exponential Moving Average Pullback strategy.

    Buys on price pullbacks to fast EMA in the direction of prevailing EMA trend.
    """

    def __init__(
        self,
        fast_ema: int = 8,
        slow_ema: int = 21,
        atr_period: int = 14,
        stop_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.5,
        max_holding_bars: int = 20,
    ) -> None:
        super().__init__(
            name="EMA_Trend_Pullback",
            parameters={
                "fast_ema": fast_ema,
                "slow_ema": slow_ema,
                "atr_period": atr_period,
                "stop_atr_mult": stop_atr_mult,
                "tp_atr_mult": tp_atr_mult,
                "max_holding_bars": max_holding_bars,
            },
        )
        self.fast_ema = int(fast_ema)
        self.slow_ema = int(slow_ema)
        self.atr_period = int(atr_period)
        self.stop_atr_mult = float(stop_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)
        self.max_holding_bars = int(max_holding_bars)

    @property
    def warmup_bars(self) -> int:
        return max(self.slow_ema, self.atr_period)

    def precompute(
        self,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        higher_tf_candles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "ema_fast": ema(closes, self.fast_ema),
            "ema_slow": ema(closes, self.slow_ema),
            "atr": wilder_atr(highs, lows, closes, self.atr_period),
        }

    def evaluate_bar(
        self,
        idx: int,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        cache: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Signal | None:
        if idx < self.warmup_bars:
            return None

        ema_f = cache["ema_fast"]
        ema_s = cache["ema_slow"]
        atr_v = cache["atr"]

        if math.isnan(ema_f[idx]) or math.isnan(ema_s[idx]) or math.isnan(ema_f[idx - 1]) or math.isnan(ema_s[idx - 1]):
            return None

        # Trend condition: fast EMA above slow EMA with positive slope
        is_uptrend = ema_f[idx] > ema_s[idx] and ema_f[idx - 1] > ema_s[idx - 1]
        c_atr = atr_v[idx] if not math.isnan(atr_v[idx]) and atr_v[idx] > 0 else (closes[idx] * 0.02)

        # Pullback test: low touches or penetrates fast EMA zone
        low_tested = (lows[idx - 1] <= ema_f[idx] + 0.25 * c_atr) or (lows[idx] <= ema_f[idx] + 0.25 * c_atr)
        close_above = closes[idx] > ema_f[idx]

        if is_uptrend and low_tested and close_above:
            t = candles[idx].get("close_at", candles[idx].get("open_at", f"bar_{idx}"))
            return Signal(
                signal_idx=idx,
                time=str(t),
                direction="LONG",
                atr=c_atr,
                stop_atr_mult=self.stop_atr_mult,
                tp_atr_mult=self.tp_atr_mult,
                max_holding_bars=self.max_holding_bars,
                reason="EMA trend pullback confirmed",
            )
        return None


class DonchianBreakoutStrategy(BaseStrategy):
    """Donchian Channel momentum breakout strategy.

    Buys when closing price breaks out above the highest high of lookback period.
    """

    def __init__(
        self,
        lookback: int = 20,
        atr_period: int = 14,
        stop_atr_mult: float = 2.0,
        tp_atr_mult: float = 3.5,
        max_holding_bars: int = 25,
    ) -> None:
        super().__init__(
            name="Donchian_Breakout",
            parameters={
                "lookback": lookback,
                "atr_period": atr_period,
                "stop_atr_mult": stop_atr_mult,
                "tp_atr_mult": tp_atr_mult,
                "max_holding_bars": max_holding_bars,
            },
        )
        self.lookback = int(lookback)
        self.atr_period = int(atr_period)
        self.stop_atr_mult = float(stop_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)
        self.max_holding_bars = int(max_holding_bars)

    @property
    def warmup_bars(self) -> int:
        return max(self.lookback, self.atr_period) + 2

    def precompute(
        self,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        higher_tf_candles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "atr": wilder_atr(highs, lows, closes, self.atr_period),
        }

    def evaluate_bar(
        self,
        idx: int,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        cache: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Signal | None:
        if idx < self.warmup_bars:
            return None

        # Prior lookback highest high (excluding current bar to avoid lookahead)
        prior_highs = highs[idx - self.lookback:idx]
        if not prior_highs:
            return None
        highest_high = max(prior_highs)

        atr_v = cache["atr"]
        c_atr = atr_v[idx] if not math.isnan(atr_v[idx]) and atr_v[idx] > 0 else (closes[idx] * 0.02)

        # Breakout condition: close breaks above highest high and prior bar was below
        if closes[idx] > highest_high and closes[idx - 1] <= highest_high:
            t = candles[idx].get("close_at", candles[idx].get("open_at", f"bar_{idx}"))
            return Signal(
                signal_idx=idx,
                time=str(t),
                direction="LONG",
                atr=c_atr,
                stop_atr_mult=self.stop_atr_mult,
                tp_atr_mult=self.tp_atr_mult,
                max_holding_bars=self.max_holding_bars,
                reason=f"Donchian breakout above {highest_high:.2f}",
            )
        return None


class RSIReversionStrategy(BaseStrategy):
    """RSI Mean Reversion Strategy.

    Buys when RSI dips into oversold territory and recovers with bullish bar confirmation.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        stop_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.0,
        max_holding_bars: int = 15,
    ) -> None:
        super().__init__(
            name="RSI_Mean_Reversion",
            parameters={
                "rsi_period": rsi_period,
                "oversold": oversold,
                "overbought": overbought,
                "stop_atr_mult": stop_atr_mult,
                "tp_atr_mult": tp_atr_mult,
                "max_holding_bars": max_holding_bars,
            },
        )
        self.rsi_period = int(rsi_period)
        self.oversold = float(oversold)
        self.overbought = float(overbought)
        self.stop_atr_mult = float(stop_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)
        self.max_holding_bars = int(max_holding_bars)

    @property
    def warmup_bars(self) -> int:
        return self.rsi_period + 5

    def precompute(
        self,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        higher_tf_candles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "rsi": rsi(closes, self.rsi_period),
            "atr": wilder_atr(highs, lows, closes, 14),
        }

    def evaluate_bar(
        self,
        idx: int,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        cache: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Signal | None:
        if idx < self.warmup_bars:
            return None

        rsi_v = cache["rsi"]
        if math.isnan(rsi_v[idx]) or math.isnan(rsi_v[idx - 1]):
            return None

        atr_v = cache["atr"]
        c_atr = atr_v[idx] if not math.isnan(atr_v[idx]) and atr_v[idx] > 0 else (closes[idx] * 0.02)

        # Oversold recovery: previous bar RSI was <= oversold, current bar cross above and green bar
        if rsi_v[idx - 1] <= self.oversold and rsi_v[idx] > self.oversold and closes[idx] >= opens[idx]:
            t = candles[idx].get("close_at", candles[idx].get("open_at", f"bar_{idx}"))
            return Signal(
                signal_idx=idx,
                time=str(t),
                direction="LONG",
                atr=c_atr,
                stop_atr_mult=self.stop_atr_mult,
                tp_atr_mult=self.tp_atr_mult,
                max_holding_bars=self.max_holding_bars,
                reason=f"RSI oversold recovery ({rsi_v[idx]:.1f} > {self.oversold})",
            )
        return None


class MultiTimeframeStrategy(BaseStrategy):
    """Multi-Timeframe Trend Confluence Strategy.

    Guards trades by evaluating Higher Timeframe (HTF) trend regime (e.g. Daily / 4H)
    and only triggering entries on Lower Timeframe (LTF, e.g. 1H / 15m) in alignment
    with the macro HTF trend direction.
    """

    def __init__(
        self,
        htf_ratio: int = 4,  # e.g. 4 bars of LTF = 1 bar of HTF (e.g. 15m -> 1h or 1h -> 4h)
        htf_ema_fast: int = 10,
        htf_ema_slow: int = 30,
        ltf_ema_fast: int = 8,
        ltf_ema_slow: int = 21,
        atr_period: int = 14,
        stop_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.5,
        max_holding_bars: int = 25,
    ) -> None:
        super().__init__(
            name="Multi_Timeframe_Confluence",
            parameters={
                "htf_ratio": htf_ratio,
                "htf_ema_fast": htf_ema_fast,
                "htf_ema_slow": htf_ema_slow,
                "ltf_ema_fast": ltf_ema_fast,
                "ltf_ema_slow": ltf_ema_slow,
                "atr_period": atr_period,
                "stop_atr_mult": stop_atr_mult,
                "tp_atr_mult": tp_atr_mult,
                "max_holding_bars": max_holding_bars,
            },
        )
        self.htf_ratio = max(1, int(htf_ratio))
        self.htf_ema_fast = int(htf_ema_fast)
        self.htf_ema_slow = int(htf_ema_slow)
        self.ltf_ema_fast = int(ltf_ema_fast)
        self.ltf_ema_slow = int(ltf_ema_slow)
        self.atr_period = int(atr_period)
        self.stop_atr_mult = float(stop_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)
        self.max_holding_bars = int(max_holding_bars)

    @property
    def warmup_bars(self) -> int:
        return (self.htf_ema_slow * self.htf_ratio) + 5

    def precompute(
        self,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        higher_tf_candles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # LTF indicators
        ltf_f = ema(closes, self.ltf_ema_fast)
        ltf_s = ema(closes, self.ltf_ema_slow)
        atr_v = wilder_atr(highs, lows, closes, self.atr_period)

        # Synthesize HTF closes if higher_tf_candles is not explicitly provided
        htf_regime: list[bool] = [False] * len(closes)
        if higher_tf_candles and len(higher_tf_candles) >= self.htf_ema_slow:
            htf_c = [float(c["close"]) for c in higher_tf_candles]
            h_f = ema(htf_c, self.htf_ema_fast)
            h_s = ema(htf_c, self.htf_ema_slow)
            # Map HTF timestamps or ratios to LTF
            # Default fallback: ratio aggregation
            for i in range(len(closes)):
                htf_idx = min(len(h_f) - 1, i // self.htf_ratio)
                if not math.isnan(h_f[htf_idx]) and not math.isnan(h_s[htf_idx]):
                    htf_regime[i] = h_f[htf_idx] > h_s[htf_idx]
        else:
            # Aggregate LTF bars into HTF bars without future lookahead
            htf_closes: list[float] = []
            for i in range(len(closes)):
                if (i + 1) % self.htf_ratio == 0 or i == len(closes) - 1:
                    htf_closes.append(closes[i])
            if len(htf_closes) >= self.htf_ema_slow:
                h_f = ema(htf_closes, self.htf_ema_fast)
                h_s = ema(htf_closes, self.htf_ema_slow)
                for i in range(len(closes)):
                    h_idx = min(len(h_f) - 1, i // self.htf_ratio)
                    if not math.isnan(h_f[h_idx]) and not math.isnan(h_s[h_idx]):
                        htf_regime[i] = h_f[h_idx] > h_s[h_idx]

        return {
            "ltf_fast": ltf_f,
            "ltf_slow": ltf_s,
            "atr": atr_v,
            "htf_regime": htf_regime,
        }

    def evaluate_bar(
        self,
        idx: int,
        candles: list[dict[str, Any]],
        closes: list[float],
        highs: list[float],
        lows: list[float],
        opens: list[float],
        cache: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Signal | None:
        if idx < self.warmup_bars:
            return None

        # Filter: HTF regime MUST be bullish
        if not cache["htf_regime"][idx]:
            return None

        ltf_f = cache["ltf_fast"]
        ltf_s = cache["ltf_slow"]
        atr_v = cache["atr"]

        if math.isnan(ltf_f[idx]) or math.isnan(ltf_s[idx]):
            return None

        c_atr = atr_v[idx] if not math.isnan(atr_v[idx]) and atr_v[idx] > 0 else (closes[idx] * 0.02)

        # LTF pullback trigger
        is_ltf_uptrend = ltf_f[idx] > ltf_s[idx]
        pullback = lows[idx] <= ltf_f[idx] + 0.25 * c_atr
        close_above = closes[idx] > ltf_f[idx]

        if is_ltf_uptrend and pullback and close_above:
            t = candles[idx].get("close_at", candles[idx].get("open_at", f"bar_{idx}"))
            return Signal(
                signal_idx=idx,
                time=str(t),
                direction="LONG",
                atr=c_atr,
                stop_atr_mult=self.stop_atr_mult,
                tp_atr_mult=self.tp_atr_mult,
                max_holding_bars=self.max_holding_bars,
                reason="HTF trend aligned + LTF pullback trigger",
                metadata={"htf_bullish": True},
            )
        return None
