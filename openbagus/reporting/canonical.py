"""Canonical financial chart data model and validation for OpenBagus.

Acts as the single authoritative source of truth for all visual renderers:
terminal, interactive window, static PNG, Word (.docx), and PDF/HTML.
Ensures no renderer alters financial observations or invents prices.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


class MalformedCandleError(ValueError):
    """Raised when candle data violates financial structural integrity."""
    pass


@dataclass
class CanonicalChartData:
    """Standardized financial dataset supplied to all OpenBagus chart renderers."""
    asset: str
    market: str = "SPOT"
    currency: str = "IDR"
    timeframe: str = "D1"
    candles: list[dict[str, Any]] = field(default_factory=list)
    quant_result: Any | None = None
    ownership: Any | None = None
    fundamentals: dict[str, Any] = field(default_factory=dict)
    macro_series: list[dict[str, Any]] = field(default_factory=list)
    backtest_result: Any | None = None
    data_freshness: str = "UNVERIFIED"
    price_as_of: str = ""
    sources: list[str] = field(default_factory=list)
    levels: list[dict[str, Any]] = field(default_factory=list)

    def validate_candles(self) -> None:
        """Strict validation of OHLCV sequence.
        
        Rejects non-positive prices, NaN/Inf, high < low, open outside [low, high],
        close outside [low, high], or negative volume.
        """
        if not self.candles:
            return
        for idx, c in enumerate(self.candles):
            try:
                o = float(c["open"])
                h = float(c["high"])
                l = float(c["low"])
                cl = float(c["close"])
                v = float(c.get("volume", 0.0) or 0.0)
            except (KeyError, TypeError, ValueError) as err:
                raise MalformedCandleError(f"Candle at index {idx} has invalid or missing numeric fields: {err}") from err

            for name, val in [("open", o), ("high", h), ("low", l), ("close", cl)]:
                if math.isnan(val) or math.isinf(val) or val <= 0:
                    raise MalformedCandleError(f"Candle at index {idx} has invalid {name} value: {val}")

            if v < 0 or math.isnan(v) or math.isinf(v):
                raise MalformedCandleError(f"Candle at index {idx} has negative or invalid volume: {v}")

            if h < l:
                raise MalformedCandleError(f"Candle at index {idx} has high ({h}) less than low ({l})")

            if o > h or o < l:
                raise MalformedCandleError(f"Candle at index {idx} has open ({o}) outside [low={l}, high={h}]")

            if cl > h or cl < l:
                raise MalformedCandleError(f"Candle at index {idx} has close ({cl}) outside [low={l}, high={h}]")

    @classmethod
    def from_research(
        cls,
        asset: str,
        candles: Sequence[Mapping[str, Any]] | None = None,
        quant_result: Any | None = None,
        packet: Any | None = None,
        ownership: Any | None = None,
        fundamentals: dict[str, Any] | None = None,
        macro_series: list[dict[str, Any]] | None = None,
        backtest_result: Any | None = None,
        timeframe: str = "D1",
        currency: str | None = None,
    ) -> CanonicalChartData:
        """Constructs a canonical dataset from research packet and quant decisions."""
        mkt = "SPOT"
        curr = currency or "USD"
        fresh = "UNVERIFIED"
        srcs = []
        as_of = ""

        if packet is not None:
            mkt = getattr(packet, "market", mkt)
            curr = currency or getattr(packet, "currency", curr)
            fresh = getattr(packet, "data_freshness", fresh)
            srcs = list(getattr(packet, "sources", []) or [])
            as_of = getattr(packet, "price_as_of", "")
            if fundamentals is None:
                fundamentals = getattr(packet, "fundamentals", {})
            if ownership is None:
                ownership = getattr(packet, "ownership", None)

        if quant_result is not None:
            mkt = getattr(quant_result, "market", mkt)
            fresh = getattr(quant_result, "data_freshness", fresh)
            if not srcs and hasattr(quant_result, "sources"):
                srcs = list(quant_result.sources or [])

        clean_candles = []
        if candles:
            for c in candles:
                clean_candles.append(dict(c))

        data = cls(
            asset=asset,
            market=mkt,
            currency=curr,
            timeframe=timeframe,
            candles=clean_candles,
            quant_result=quant_result,
            ownership=ownership,
            fundamentals=fundamentals or {},
            macro_series=macro_series or [],
            backtest_result=backtest_result,
            data_freshness=fresh,
            price_as_of=as_of,
            sources=srcs,
        )
        data.validate_candles()
        return data
