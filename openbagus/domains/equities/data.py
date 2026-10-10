"""Bounded, provenance-bearing imports; no unauthorized stock-price scraping."""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openbagus.domains.equities.catalog import source_url
from openbagus.core.guards import scan_text

WIB = timezone(timedelta(hours=7), "Asia/Jakarta")


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp requires an explicit timezone")
    return result


def number(value, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric field")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError("Invalid numeric field")
    return result


class EquityData:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "data/equities"

    def load(self, symbol: str) -> dict:
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,14}", symbol):
            return {"gaps": ["INVALID_SYMBOL"]}
        try:
            data = json.loads((self.directory / f"{symbol}.json").read_text(encoding="utf-8"))
            self.validate(data)
            data["gaps"] = []
            return data
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return {"gaps": ["SOURCE GAP: impor harga/fundamental IDX berizin belum tersedia"]}

    @staticmethod
    def validate(data: dict) -> None:
        if data.get("authorized_use") is not True:
            raise ValueError("Import requires confirmation of authorized use")
        source_url(data["source"])
        if not scan_text(json.dumps(data))["passed"]:
            raise ValueError("Unsafe imported metadata")
        if data.get("currency") != "IDR" or data.get("volume_unit") not in {"shares", "index_not_applicable"}:
            raise ValueError("IDX input requires IDR and explicit share volume units")
        if data.get("adjustment") not in {"adjusted", "unadjusted"}:
            raise ValueError("Historical adjustment basis is required")
        timestamp(data["retrieved_at"])
        if data.get("timeframe") not in {"M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1"}:
            raise ValueError("Explicit supported OHLCV timeframe required")
        if data.get("quote"):
            q = data["quote"]
            number(q["price"], positive=True)
            timestamp(q["as_of"])
        previous = None
        for bar in data.get("candles", []):
            start, end = timestamp(bar["open_at"]), timestamp(bar["close_at"])
            if end <= start or (previous and start <= previous):
                raise ValueError("Unordered, duplicate or invalid candle interval")
            previous = start
            o, h, l, c = [number(bar[k], positive=True) for k in ("open", "high", "low", "close")]
            if not l <= min(o, c) <= max(o, c) <= h or number(bar["volume"]) < 0:
                raise ValueError("Invalid OHLCV")
        for field in ("fundamentals", "previous_fundamentals"):
            if data.get(field):
                validate_statement(data[field])
        if len(data.get("events", [])) > 500:
            raise ValueError("Too many event summaries")
        for event in data.get("events", []):
            source_url(event["source"])
            timestamp(event["published_at"])
            if not event.get("observation_period") or len(event.get("summary", "")) > 600:
                raise ValueError("Event requires observation period and a short factual summary")
            if event.get("event_at"):
                timestamp(event["event_at"])
        for field in ("quote", "fees"):
            for key, value in data.get(field, {}).items():
                if key in {"price", "previous_close", "price_limit_low", "price_limit_high", "buy", "sell"}:
                    number(value)
        for bar in data.get("benchmark_candles", []):
            timestamp(bar["close_at"])
            number(bar["close"], positive=True)

    def import_file(self, path: Path) -> str:
        if path.stat().st_size > 10_000_000:
            raise ValueError("Equity import exceeds size limit")
        data = json.loads(path.read_text(encoding="utf-8"))
        symbol = str(data.get("symbol", "")).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,14}", symbol):
            raise ValueError("Invalid symbol")
        self.validate(data)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{symbol}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return symbol

    def import_ohlcv(self, path: Path, metadata: Path) -> str:
        if path.stat().st_size > 10_000_000 or metadata.stat().st_size > 10_000_000:
            raise ValueError("OHLCV import exceeds size limit")
        data = json.loads(metadata.read_text(encoding="utf-8"))
        with path.open(encoding="utf-8-sig", newline="") as stream:
            data["candles"] = list(csv.DictReader(stream))
        self.validate(data)
        symbol = str(data["symbol"]).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,14}", symbol):
            raise ValueError("Invalid symbol")
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{symbol}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        return symbol


def validate_statement(statement: dict) -> None:
    source_url(statement["source"])
    timestamp(statement["published_at"])
    if statement.get("currency") != "IDR" or statement.get("unit") not in {"IDR", "thousand_IDR", "million_IDR", "billion_IDR"}:
        raise ValueError("Statement monetary unit/currency is required")
    if statement.get("period_type") not in {"TTM", "FY", "QUARTER"} or not statement.get("period") or not statement.get("basis"):
        raise ValueError("Statement requires fiscal period, duration and accounting basis")
    for value in statement.get("values", {}).values():
        number(value)
    for value in statement.get("reported_ratios_pct", {}).values():
        number(value)


def fundamentals(statement: dict | None, price: float | None, previous: dict | None = None) -> dict:
    if not statement:
        return {"ratios": {}, "gaps": ["Financial statements unavailable"]}
    validate_statement(statement)
    multiplier = {"IDR": 1, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9}[statement["unit"]]
    raw = statement.get("values", {})
    shares = number(raw["weighted_average_shares"], positive=True) if raw.get("weighted_average_shares") else None
    outstanding = number(raw["shares_outstanding"], positive=True) if raw.get("shares_outstanding") else None
    values = {key: number(value) * multiplier for key, value in raw.items()
              if key not in {"weighted_average_shares", "shares_outstanding"}}
    ratios = {}

    def ratio(label: str, numerator: str, denominator: str, scale: float = 1) -> None:
        n, d = values.get(numerator), values.get(denominator)
        if n is not None and d is not None and d > 0:
            ratios[label] = n / d * scale

    income = values.get("net_income_attributable")
    equity = values.get("equity_attributable")
    if income is not None and shares:
        ratios["EPS"] = income / shares
        if price and income > 0 and statement["period_type"] in {"FY", "TTM"}:
            ratios["PER"] = price / ratios["EPS"]
    if price and equity is not None and equity > 0 and outstanding:
        ratios["PBV"] = price / (equity / outstanding)
    ratio("ROE_pct", "net_income_attributable", "average_equity_attributable", 100)
    ratio("ROA_pct", "net_income", "average_assets", 100)
    ratio("Debt_to_Equity", "interest_bearing_debt", "equity")
    ratio("Operating_Margin_pct", "operating_income", "revenue", 100)
    ratio("Net_Margin_pct", "net_income", "revenue", 100)
    if "operating_cash_flow" in values and "capital_expenditure" in values:
        ratios["FCF_IDR"] = values["operating_cash_flow"] - abs(values["capital_expenditure"])
    ratio("Payout_Ratio_pct", "dividends_attributable", "net_income_attributable", 100)
    if price and outstanding and statement["period_type"] in {"FY", "TTM"} and values.get("dividends_attributable") is not None:
        ratios["Dividend_Yield_pct"] = values["dividends_attributable"] / outstanding / price * 100
    if previous:
        validate_statement(previous)
        comparable = (previous["basis"] == statement["basis"] and previous["period_type"] == statement["period_type"]
                      and statement.get("comparison", {}).get("previous_period") == previous["period"]
                      and statement.get("comparison", {}).get("kind") in {"YoY", "QoQ"})
        comparable = comparable and (statement["comparison"]["kind"] != "QoQ" or statement["period_type"] == "QUARTER")
        if comparable:
            old = fundamentals(previous, None)["normalized_values"]
            for name in ("revenue", "net_income_attributable"):
                if values.get(name) is not None and old.get(name, 0) > 0:
                    ratios[f"{name}_growth_{statement['comparison']['kind']}_pct"] = (values[name] / old[name] - 1) * 100
    for key, value in statement.get("reported_ratios_pct", {}).items():
        if key in {"NIM", "NPL_gross", "NPL_net", "CAR", "LDR", "LFR", "CASA", "loan_growth", "deposit_growth", "cost_of_credit"}:
            ratios[key + "_pct"] = number(value)
    return {"ratios": ratios, "normalized_values": values, "source": statement["source"],
            "period": statement["period"], "period_type": statement["period_type"], "basis": statement["basis"],
            "published_at": statement["published_at"], "gaps": [] if ratios else ["Reported fields insufficient for ratios"]}
