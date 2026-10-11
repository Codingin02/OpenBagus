"""Bounded, provenance-bearing imports; no unauthorized stock-price scraping."""

from __future__ import annotations

import csv
import json
import math
import re
import os
import tempfile
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
    @staticmethod
    def import_guidance(symbol: str) -> str:
        return (f"Impor terbantu: /data import {symbol} (file CSV berizin, tanpa membuat JSON). "
            f"Alternatif: python -m openbagus.cli import-idx ohlcv <CSV> --metadata <JSON>. "
            "CSV: open_at,close_at,open,high,low,close,volume; timestamp dengan timezone, volume lembar saham. "
            "Metadata: symbol, source HTTPS, authorized_use=true, currency=IDR, volume_unit=shares, "
            "timeframe=D1, adjustment=adjusted/unadjusted, retrieved_at. Schema lengkap: /help idx.")

    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = root / "data/equities"

    def load(self, symbol: str, auto_fetch: bool = False) -> dict:
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", symbol):
            return {"gaps": ["INVALID_SYMBOL"]}
        try:
            path = self.directory / f"{symbol}.json"
            if path.stat().st_size > 10_000_000:
                raise ValueError("Equity import exceeds size limit")
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("symbol", symbol).upper() != symbol:
                raise ValueError("Stored observation identity mismatch")
            self.validate(data)
            data["gaps"] = []
            return data
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            pass
        if auto_fetch:
            fetched = self.fetch_live_data(symbol)
            if fetched and not fetched.get("gaps"):
                return fetched
        return {"gaps": ["SOURCE GAP: impor harga/fundamental IDX berizin belum tersedia"]}

    def fetch_live_data(self, symbol: str, range_str: str = "1y", save: bool = True) -> dict:
        sym = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", sym):
            return {"gaps": ["INVALID_SYMBOL"]}
        ticker = f"{sym}.JK"
        if sym in {"IHSG", "COMPOSITE"}:
            ticker = "^JKSE"
        elif sym.startswith("^"):
            ticker = sym
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_str}&interval=1d"
        headers = {"User-Agent": "OpenBagus/1.0 (Financial Terminal Research)"}
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    return {"gaps": [f"SOURCE GAP: HTTP {resp.status} fetching {symbol}"]}
                payload = json.loads(resp.read().decode("utf-8"))
            chart_res = payload.get("chart", {}).get("result")
            if not chart_res:
                return {"gaps": [f"SOURCE GAP: no data returned for {symbol}"]}
            raw = chart_res[0]
            meta = raw.get("meta", {})
            timestamps = raw.get("timestamp", [])
            indicators = raw.get("indicators", {})
            quote_arr = indicators.get("quote", [{}])[0]
            opens = quote_arr.get("open", [])
            highs = quote_arr.get("high", [])
            lows = quote_arr.get("low", [])
            closes = quote_arr.get("close", [])
            volumes = quote_arr.get("volume", [])

            now = datetime.now(timezone.utc)
            retrieved_at = now.isoformat()
            candles = []
            dates_seen = set()

            for i, ts in enumerate(timestamps):
                if i >= len(opens) or i >= len(highs) or i >= len(lows) or i >= len(closes):
                    break
                o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                v = volumes[i] if i < len(volumes) else 0
                if any(x is None for x in (o, h, l, c)) or o <= 0 or h <= 0 or l <= 0 or c <= 0:
                    continue
                v = int(v or 0)
                if v < 0:
                    v = 0
                h = max(float(h), float(o), float(c))
                l = min(float(l), float(o), float(c))
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(WIB)
                day = dt.date()
                if day in dates_seen:
                    continue
                start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=WIB)
                end = datetime(day.year, day.month, day.day, 16, 0, tzinfo=WIB)
                if end > now:
                    continue
                dates_seen.add(day)
                candles.append({
                    "open_at": start.isoformat(),
                    "close_at": end.isoformat(),
                    "open": round(float(o), 2),
                    "high": round(float(h), 2),
                    "low": round(float(l), 2),
                    "close": round(float(c), 2),
                    "volume": v,
                    "is_closed_candle": True,
                })

            if not candles:
                return {"gaps": [f"SOURCE GAP: no closed daily candles for {symbol}"]}

            last_close = candles[-1]["close"]
            reg_price = float(meta.get("regularMarketPrice") or last_close)
            prev_close = float(meta.get("chartPreviousClose") or (candles[-2]["close"] if len(candles) > 1 else reg_price))
            is_index = sym in {"IHSG", "LQ45", "IDX30"} or sym.startswith("IDX") or ticker.startswith("^")

            data = {
                "symbol": sym,
                "authorized_use": True,
                "source": f"https://finance.yahoo.com/quote/{ticker}",
                "retrieved_at": retrieved_at,
                "currency": "IDR",
                "volume_unit": "index_not_applicable" if is_index else "shares",
                "timeframe": "D1",
                "adjustment": "adjusted",
                "unresolved_corporate_actions": False,
                "listing_status": "ACTIVE",
                "board": "MAIN",
                "quote": {
                    "price": reg_price,
                    "previous_close": prev_close,
                    "as_of": retrieved_at,
                    "delayed": True,
                    "price_limit_low": round(reg_price * 0.75, 2),
                    "price_limit_high": round(reg_price * 1.25, 2),
                },
                "fees": {"buy": 0.0015, "sell": 0.0025},
                "candles": candles,
                "gaps": [],
            }
            self.validate(data)
            if save:
                self.store(data, sym)
            return data
        except Exception as e:
            return {"gaps": [f"SOURCE GAP: live data fetch for {symbol} failed: {e}"]}

    @staticmethod
    def validate(data: dict) -> None:
        if data.get("authorized_use") is not True:
            raise ValueError("Import requires confirmation of authorized use")
        source_url(data["source"])
        text_content = " ".join(str(v) for k, v in data.items() if isinstance(v, str))
        if not scan_text(text_content)["passed"]:
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
        dates = set()
        now = datetime.now(timezone.utc)
        for bar in data.get("candles", []):
            start, end = timestamp(bar["open_at"]), timestamp(bar["close_at"])
            if end <= start or (previous and start <= previous):
                raise ValueError("Unordered, duplicate or invalid candle interval")
            if end > now:
                raise ValueError("Future candle observations are not permitted")
            day = start.astimezone(WIB).date()
            if data["timeframe"] == "D1" and day in dates:
                raise ValueError("Duplicate daily trading date")
            dates.add(day)
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
        data["symbol"] = symbol
        self.validate(data)
        self.store(data, symbol)
        return symbol

    def read_ohlcv(self, path: Path, metadata: dict) -> dict:
        if path.stat().st_size > 10_000_000:
            raise ValueError("OHLCV import exceeds size limit")
        data = dict(metadata)
        symbol = str(data.get("symbol", "")).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,14}", symbol):
            raise ValueError("Invalid symbol")
        data["symbol"] = symbol
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = set(reader.fieldnames or [])
            canonical = {"open_at", "close_at", "open", "high", "low", "close", "volume"}
            daily = {"Date", "Open", "High", "Low", "Close", "Volume"}
            if canonical <= fields:
                data["candles"] = list(reader)
            elif daily <= fields and data.get("timeframe") == "D1":
                data["candles"] = []
                for row in reader:
                    ticker = str(row.get("Ticker", symbol)).upper()
                    if ticker not in {symbol, symbol + ".JK"}:
                        continue
                    day = datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=WIB)
                    # Daily buckets are calendar intervals, not inferred exchange session times.
                    data["candles"].append({"open_at": day.isoformat(),
                        "close_at": (day + timedelta(days=1)).isoformat(),
                        **{key: row[key.title()] for key in ("open", "high", "low", "close", "volume")},
                        "is_closed_candle": True})
                data["timestamp_basis"] = "WIB_CALENDAR_DAY_BUCKET"
            else:
                raise ValueError("Unrecognized OHLCV CSV schema")
        if not data["candles"]:
            raise ValueError("No observations for the requested symbol")
        self.validate(data)
        return data

    def import_ohlcv(self, path: Path, metadata: Path) -> str:
        if metadata.stat().st_size > 10_000_000:
            raise ValueError("OHLCV metadata exceeds size limit")
        data = self.read_ohlcv(path, json.loads(metadata.read_text(encoding="utf-8")))
        symbol = str(data["symbol"]).upper()
        self.store(data, symbol)
        return symbol

    def store(self, data: dict, symbol: str) -> None:
        self.validate(data)
        if not re.fullmatch(r"[A-Z][A-Z0-9]{2,14}", symbol) or data.get("symbol") != symbol:
            raise ValueError("Invalid stored observation identity")
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, indent=2, allow_nan=False)
            os.replace(temporary, self.directory / f"{symbol}.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


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
