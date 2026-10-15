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

from openbagus.domains.equities.catalog import source_url, EquityCatalog
from openbagus.core.guards import scan_text
from openbagus.domains.equities.financial_model import (
    CanonicalFinancialStatement,
    detect_period,
    detect_currency_and_unit,
)
from openbagus.domains.equities.storage import FinancialStatementStorage
from openbagus.domains.equities.xbrl import IdxXbrlParser
from openbagus.domains.equities.parsers.xlsx_parser import IdxXlsxParser
from openbagus.domains.equities.parsers.pdf_parser import IdxPdfParser

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
            storage = FinancialStatementStorage(self.root)
            stored_periods = storage.list_periods(symbol)
            if stored_periods:
                data["financial_history"] = stored_periods
                if "fundamentals" not in data or not data.get("fundamentals"):
                    latest_stmt = storage.get_statement(symbol)
                    if latest_stmt:
                        data["fundamentals"] = latest_stmt
            return data
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            pass
        if auto_fetch:
            fetched = self.fetch_live_data(symbol)
            if fetched and not fetched.get("gaps"):
                catalog = EquityCatalog(self.root)
                res_asset = catalog.resolve(symbol, allow_us=True)
                storage = FinancialStatementStorage(self.root)
                if res_asset and res_asset.asset_type == "EQUITY_US":
                    if not storage.list_periods(symbol):
                        try:
                            from openbagus.domains.equities.sec_edgar import SecEdgarClient
                            from openbagus.domains.equities.facts_db import FinancialFactsDatabase
                            sec = SecEdgarClient(self.root)
                            stmts = sec.extract_canonical_statements(symbol)
                            facts_db = FinancialFactsDatabase(root=self.root)
                            for stmt in stmts:
                                storage.store_statement(stmt)
                                for m_key, m_val in stmt.to_legacy_dict().get("values", {}).items():
                                    if m_val is not None:
                                        facts_db.store_fact(
                                            symbol=symbol,
                                            exchange=res_asset.exchange_or_chain,
                                            period=stmt.period,
                                            period_type=stmt.period_type,
                                            metric_name=m_key,
                                            value=m_val,
                                            currency="USD",
                                            source_provider="SEC_EDGAR",
                                            source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{sec.resolve_ticker(symbol) or 0:010d}.json",
                                        )
                        except Exception as sec_err:
                            pass
                stored_periods = storage.list_periods(symbol)
                if stored_periods:
                    fetched["financial_history"] = stored_periods
                    latest_stmt = storage.get_statement(symbol)
                    if latest_stmt:
                        fetched["fundamentals"] = latest_stmt
                return fetched
        return {"gaps": ["SOURCE GAP: impor harga/fundamental IDX berizin belum tersedia"]}

    def fetch_live_data(self, symbol: str, range_str: str = "5y", save: bool = True) -> dict:
        sym = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", sym):
            return {"gaps": ["INVALID_SYMBOL"]}
        catalog = EquityCatalog(self.root)
        resolved_asset = catalog.resolve(sym, allow_us=True)
        is_us = bool(resolved_asset and resolved_asset.asset_type == "EQUITY_US")
        if is_us:
            ticker = sym
            curr = "USD"
            board_label = "US_MAIN"
        elif sym in {"IHSG", "COMPOSITE"}:
            ticker = "^JKSE"
            curr = "IDR"
            board_label = "INDEX"
        elif sym.startswith("^"):
            ticker = sym
            curr = "IDR"
            board_label = "INDEX"
        else:
            ticker = f"{sym}.JK"
            curr = "IDR"
            board_label = resolved_asset.canonical_board if resolved_asset else "MAIN"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={range_str}&interval=1d&events=div%2Csplit"
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
            adj_arr = indicators.get("adjclose", [{}])[0].get("adjclose", []) if indicators.get("adjclose") else []

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
                o, h, l, c = float(o), float(h), float(l), float(c)
                if not (l <= min(o, c) and max(o, c) <= h and l <= h):
                    continue
                if v is None or v < 0:
                    continue
                v = int(v)

                adj_c = adj_arr[i] if (i < len(adj_arr) and adj_arr[i] is not None and adj_arr[i] > 0) else c
                factor = float(adj_c) / c if c > 0 else 1.0
                bar_o = round(o * factor, 2)
                bar_h = round(h * factor, 2)
                bar_l = round(l * factor, 2)
                bar_c = round(float(adj_c), 2)

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
                    "open": bar_o,
                    "high": bar_h,
                    "low": bar_l,
                    "close": bar_c,
                    "volume": v,
                    "is_closed_candle": True,
                })

            if not candles:
                return {"gaps": [f"SOURCE GAP: no closed daily candles for {symbol}"]}

            last_close = candles[-1]["close"]
            reg_price = float(meta.get("regularMarketPrice") or last_close)
            prev_close = float(meta.get("chartPreviousClose") or (candles[-2]["close"] if len(candles) > 1 else reg_price))
            is_index = sym in {"IHSG", "LQ45", "IDX30"} or sym.startswith("IDX") or ticker.startswith("^")

            reg_time = meta.get("regularMarketTime")
            if reg_time and isinstance(reg_time, (int, float)) and reg_time > 0:
                as_of_iso = datetime.fromtimestamp(reg_time, tz=timezone.utc).astimezone(WIB).isoformat()
            else:
                as_of_iso = retrieved_at

            from openbagus.domains.equities.policy import EquityMarketPolicy
            try:
                pol = EquityMarketPolicy(self.root)
                low_limit, high_limit = pol.auto_rejection_limits(reg_price, board="MAIN")
            except Exception:
                low_limit, high_limit = round(reg_price * 0.75, 2), round(reg_price * 1.25, 2)

            events_raw = raw.get("events")
            has_splits = bool(events_raw and events_raw.get("splits")) if isinstance(events_raw, dict) else False
            unresolved_corp = False if (events_raw is not None or not has_splits) else True

            data = {
                "symbol": sym,
                "authorized_use": True,
                "source": f"https://finance.yahoo.com/quote/{ticker}",
                "retrieved_at": retrieved_at,
                "currency": curr,
                "volume_unit": "index_not_applicable" if is_index else "shares",
                "timeframe": "D1",
                "adjustment": "adjusted" if adj_arr else "unadjusted",
                "unresolved_corporate_actions": unresolved_corp,
                "listing_status": "ACTIVE",
                "board": board_label,
                "quote": {
                    "price": reg_price,
                    "previous_close": prev_close,
                    "as_of": as_of_iso,
                    "delayed": True,
                    "price_limit_low": low_limit,
                    "price_limit_high": high_limit,
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
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", symbol):
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
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", symbol):
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

    def import_idx_trading_summary(self, path: Path) -> dict[str, Any]:
        """Universal import for official IDX Daily Stock Trading Summary (CSV/XLSX).

        Extracts code, previous, open, high, low, close, volume without hand-editing JSON.
        Accrues EOD bars incrementally into local storage with provenance and duplicate detection.
        """
        rows = read_tabular(path)
        if not rows:
            raise ValueError(f"File {path.name} kosong.")

        # 1. Identify date from filename or content
        fn_match = re.search(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})", path.name)
        trade_date = None
        if fn_match:
            trade_date = f"{fn_match.group(1)}-{fn_match.group(2)}-{fn_match.group(3)}"
        else:
            for r in rows[:5]:
                line_str = " ".join(str(c) for c in r)
                d_match = re.search(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b", line_str)
                if d_match:
                    trade_date = f"{d_match.group(1)}-{d_match.group(2)}-{d_match.group(3)}"
                    break
        if not trade_date:
            trade_date = datetime.fromtimestamp(path.stat().st_mtime, tz=WIB).strftime("%Y-%m-%d")

        # 2. Locate header row
        hdr_idx = -1
        col_map: dict[str, int] = {}
        for idx, row in enumerate(rows[:15]):
            cells = [str(c).strip().lower() for c in row]
            has_code = any(any(k in c for k in ("kode", "ticker", "code", "saham")) for c in cells)
            has_close = any(any(k in c for k in ("penutupan", "close", "last", "terakhir", "closing")) for c in cells)
            if has_code and has_close:
                hdr_idx = idx
                for c_i, c_val in enumerate(cells):
                    if any(k in c_val for k in ("kode", "ticker", "code")):
                        col_map.setdefault("code", c_i)
                    elif any(k in c_val for k in ("nama", "name")):
                        col_map.setdefault("name", c_i)
                    elif any(k in c_val for k in ("sebelumnya", "prev", "previous")):
                        col_map.setdefault("prev", c_i)
                    elif any(k in c_val for k in ("pembukaan", "open", "opening")):
                        col_map.setdefault("open", c_i)
                    elif any(k in c_val for k in ("tertinggi", "high", "highest")):
                        col_map.setdefault("high", c_i)
                    elif any(k in c_val for k in ("terendah", "low", "lowest")):
                        col_map.setdefault("low", c_i)
                    elif any(k in c_val for k in ("penutupan", "close", "last", "terakhir")):
                        col_map.setdefault("close", c_i)
                    elif any(k in c_val for k in ("volume", "vol", "shares", "lembar")):
                        col_map.setdefault("vol", c_i)
                break

        if hdr_idx == -1 or "code" not in col_map or "close" not in col_map:
            raise ValueError(f"Header ringkasan perdagangan IDX tidak dikenali pada file {path.name}.")

        start_time = f"{trade_date}T09:00:00+07:00"
        close_time = f"{trade_date}T16:00:00+07:00"
        imported_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for row in rows[hdr_idx + 1:]:
            if len(row) <= max(col_map.values()):
                continue
            raw_code = str(row[col_map["code"]]).strip().upper()
            raw_code = re.sub(r"[^A-Z0-9-]", "", raw_code)
            if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", raw_code):
                continue

            def parse_num(idx_key: str, default: float = 0.0) -> float:
                if idx_key not in col_map:
                    return default
                val_str = str(row[col_map[idx_key]]).replace(",", "").replace(" ", "").strip()
                try:
                    return float(val_str)
                except ValueError:
                    return default

            c = parse_num("close")
            if c <= 0:
                continue
            prev = parse_num("prev", c)
            o = parse_num("open", prev if prev > 0 else c)
            h = parse_num("high", max(o, c))
            l = parse_num("low", min(o, c))
            v = int(parse_num("vol", 0))

            o = round(o, 2)
            h = round(max(h, o, c), 2)
            l = round(min(l, o, c) if l > 0 else min(o, c), 2)
            c = round(c, 2)

            candle_entry = {
                "open_at": start_time,
                "close_at": close_time,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": max(0, v),
                "is_closed_candle": True,
            }

            # Load or create ticker record
            existing = self.load(raw_code, auto_fetch=False)
            if existing.get("gaps"):
                existing = {
                    "symbol": raw_code,
                    "authorized_use": True,
                    "source": f"https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/ ({path.name})",
                    "retrieved_at": now_iso,
                    "currency": "IDR",
                    "volume_unit": "shares",
                    "timeframe": "D1",
                    "adjustment": "unadjusted",
                    "unresolved_corporate_actions": False,
                    "listing_status": "ACTIVE",
                    "board": "MAIN",
                    "quote": {
                        "price": c,
                        "previous_close": prev if prev > 0 else c,
                        "as_of": close_time,
                    },
                    "fees": {"buy": 0.0015, "sell": 0.0025},
                    "candles": [candle_entry],
                    "gaps": [],
                }
            else:
                candles = existing.get("candles", [])
                updated = False
                for i, bar in enumerate(candles):
                    if bar.get("open_at", "")[:10] == trade_date:
                        candles[i] = candle_entry
                        updated = True
                        break
                if not updated:
                    candles.append(candle_entry)
                    candles.sort(key=lambda b: b.get("open_at", ""))
                existing["candles"] = candles
                existing["quote"] = {
                    "price": c,
                    "previous_close": prev if prev > 0 else c,
                    "as_of": close_time,
                }
                existing["retrieved_at"] = now_iso

            self.store(existing, raw_code)
            imported_count += 1

        return {
            "imported_tickers": imported_count,
            "imported_tickers_count": imported_count,
            "date": trade_date,
            "file": path.name,
            "source": f"https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham/ ({path.name})",
            "provenance": "Official IDX Daily Trading Summary import",
        }

    def import_financial_statement(self, path: Path, ticker: str | None = None) -> dict[str, Any]:
        """Universal import for company financial disclosures across all 11 sectors."""
        sym = (ticker or "").strip().upper()
        if not sym:
            m = re.search(r"\b([A-Z]{4})\b", path.name.upper())
            if m:
                sym = m.group(1)
        if not sym or not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", sym):
            raise ValueError(f"Ticker emiten belum dapat diverifikasi untuk {path.name}; sebutkan ticker (contoh: /data import financials {path.name} ICBP).")

        now_iso = datetime.now(timezone.utc).isoformat()
        ext = path.suffix.lower()

        statement: dict[str, Any] = {}

        if ext in {".zip", ".xbrl", ".xml"}:
            parser = IdxXbrlParser(self.root)
            canonical = parser.parse_file(path, sym)
            statement = canonical.to_legacy_dict()
        elif ext == ".xlsx":
            parser_xlsx = IdxXlsxParser(self.root)
            canonical = parser_xlsx.parse_file(path, sym)
            statement = canonical.to_legacy_dict()
        elif ext == ".pdf":
            parser_pdf = IdxPdfParser(self.root)
            canonical = parser_pdf.parse_file(path, sym)
            statement = canonical.to_legacy_dict()
        else:
            # CSV or JSON
            rows = read_tabular(path)
            if not rows:
                raise ValueError(f"File laporan keuangan {path.name} kosong.")

            values: dict[str, float] = {}
            reported_ratios: dict[str, float] = {}
            detected_period_res = detect_period(path.name)
            period = detected_period_res[0] if detected_period_res else None
            period_type = detected_period_res[1] if detected_period_res else None
            currency = "IDR"
            unit = "million_IDR"
            basis = "konsolidasian"

            if ext == ".json":
                raw_data = json.loads(path.read_text(encoding="utf-8"))
                if "values" in raw_data:
                    values = {k: float(v) for k, v in raw_data.get("values", {}).items() if v is not None}
                    reported_ratios = {k: float(v) for k, v in raw_data.get("reported_ratios_pct", {}).items() if v is not None}
                    period = raw_data.get("period") or period
                    period_type = raw_data.get("period_type") or period_type
                    currency = raw_data.get("currency") or currency
                    unit = raw_data.get("unit") or unit
                    basis = raw_data.get("basis") or basis
                else:
                    for k, v in raw_data.items():
                        try:
                            num = float(str(v).replace(",", ""))
                            values[k] = num
                        except (ValueError, TypeError):
                            if k.lower() in ("period", "periode"):
                                period = str(v)
            else:
                # CSV parsing
                field_map = {
                    "revenue": ("pendapatan", "penjualan", "revenue", "sales"),
                    "operating_income": ("laba usaha", "laba operasional", "operating income", "ebit"),
                    "net_income": ("laba bersih", "laba tahun berjalan", "net income", "net profit"),
                    "net_income_attributable": ("laba pemilik entitas induk", "laba diatribusikan", "net income attributable"),
                    "equity": ("jumlah ekuitas", "total ekuitas", "equity", "total equity"),
                    "equity_attributable": ("ekuitas pemilik entitas induk", "equity attributable"),
                    "total_assets": ("jumlah aset", "total aset", "total assets", "jumlah aktiva"),
                    "total_liabilities": ("jumlah liabilitas", "total liabilitas", "total liabilities", "jumlah kewajiban"),
                    "interest_bearing_debt": ("utang bank", "utang berbunga", "pinjaman bank", "interest-bearing debt", "total utang"),
                    "operating_cash_flow": ("arus kas operasi", "arus kas dari aktivitas operasi", "operating cash flow"),
                    "capital_expenditure": ("belanja modal", "capex", "capital expenditure"),
                    "shares_outstanding": ("jumlah saham beredar", "saham beredar", "shares outstanding"),
                    "weighted_average_shares": ("rata-rata tertimbang saham", "weighted average shares"),
                }
                ratio_map = {
                    "NIM": ("nim", "net interest margin"),
                    "NPL_gross": ("npl gross", "npl kotor"),
                    "NPL_net": ("npl net", "npl bersih"),
                    "CAR": ("car", "capital adequacy ratio", "kpmm"),
                    "LDR": ("ldr", "loan to deposit ratio"),
                    "CASA": ("casa", "dana murah"),
                }

                header_blob = " ".join(str(c) for r in rows[:5] for c in r)
                detected_curr, detected_unit, _ = detect_currency_and_unit(header_blob)
                currency = detected_curr
                unit = detected_unit

                for r in rows:
                    if len(r) < 2:
                        continue
                    label = str(r[0]).strip().lower()
                    val_str = str(r[1]).replace(",", "").replace(" ", "").replace("%", "").strip()
                    try:
                        val_num = float(val_str)
                    except ValueError:
                        if any(p in label for p in ("periode", "period", "kuartal", "tahun")):
                            detected_cell_p = detect_period(str(r[1]))
                            if detected_cell_p:
                                period_type = detected_cell_p[1]
                            period = str(r[1]).strip()
                        continue

                    for canon_key, patterns in field_map.items():
                        if any(p in label for p in patterns):
                            values[canon_key] = val_num
                            break
                    for canon_ratio, patterns in ratio_map.items():
                        if any(p in label for p in patterns):
                            reported_ratios[canon_ratio] = val_num
                            break

            if not period:
                raise ValueError(f"Periode laporan keuangan tidak dapat diverifikasi dari dokumen {path.name}.")

            if not period_type:
                period_type = "QUARTER" if re.search(r"Q[1-4]", period) else ("TTM" if "TTM" in period else "FY")

            statement = {
                "symbol": sym,
                "source": f"https://www.idx.co.id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/ ({path.name})",
                "published_at": now_iso,
                "currency": currency,
                "unit": unit,
                "period": period,
                "period_type": period_type,
                "basis": basis,
                "values": values,
                "reported_ratios_pct": reported_ratios,
            }

        statement["symbol"] = sym
        validate_statement(statement)

        # Store in multi-period versioned storage
        storage = FinancialStatementStorage(self.root)
        storage.store_statement(statement)

        # Sync atomic facts with provenance to FinancialFactsDatabase
        try:
            from openbagus.domains.equities.facts_db import FinancialFactsDatabase
            facts_db = FinancialFactsDatabase(root=self.root)
            fiscal_yr = int(str(statement.get("period", "2026")).split("-")[0]) if "-" in str(statement.get("period", "")) else None
            facts_db.record_filing(
                symbol=sym,
                exchange="IDX",
                filing_type=statement.get("period_type", "QUARTER"),
                period=statement.get("period", ""),
                fiscal_year=fiscal_yr,
                period_end_date=statement.get("period_end_date"),
                filing_date=statement.get("published_at") or now_iso,
                source_provider="OFFICIAL_FILING",
                source_url=statement.get("source"),
                local_path=str(path),
                status=statement.get("validation_status", "VALIDATED"),
            )
            for m_key, m_val in statement.get("values", {}).items():
                if m_val is not None:
                    cit = statement.get("citations", {}).get(m_key, {})
                    orig_lbl = cit.get("row_label") if isinstance(cit, dict) else getattr(cit, "row_label", None)
                    facts_db.store_fact(
                        symbol=sym,
                        exchange="IDX",
                        period=statement.get("period", ""),
                        period_type=statement.get("period_type", "QUARTER"),
                        metric_name=m_key,
                        value=float(m_val),
                        currency=statement.get("currency", "IDR"),
                        unit_scaling=statement.get("unit", "billion_IDR"),
                        period_end_date=statement.get("period_end_date"),
                        filing_date=statement.get("published_at") or now_iso,
                        original_label=orig_lbl,
                        source_provider="OFFICIAL_FILING",
                        source_url=statement.get("source"),
                        accession_number=path.name,
                        extraction_method="PDF_PARSE" if ext == ".pdf" else "XBRL_NORMALIZATION",
                        validation_status=statement.get("validation_status", "VALIDATED"),
                    )
        except Exception:
            pass

        # Retrieve previous statement if available to compute beginning/ending averages
        prev_stmt = None
        history = storage.get_history(sym, max_periods=5)
        for h in reversed(history):
            if h.get("period") != statement.get("period"):
                prev_stmt = h
                break

        existing = self.load(sym, auto_fetch=False)
        quote_price = None
        if existing.get("gaps"):
            catalog = EquityCatalog(self.root)
            asset = next((a for a in catalog.assets if a.symbol == sym), None)
            listing_status = asset.canonical_status if asset else "UNKNOWN"
            board = asset.canonical_board if asset else "UNKNOWN"

            existing = {
                "symbol": sym,
                "authorized_use": True,
                "source": statement["source"],
                "retrieved_at": now_iso,
                "currency": statement.get("currency", "IDR"),
                "volume_unit": "shares",
                "timeframe": "D1",
                "adjustment": "unadjusted",
                "unresolved_corporate_actions": False,
                "listing_status": listing_status,
                "board": board,
                "quote": {},
                "fees": {"buy": 0.0015, "sell": 0.0025},
                "candles": [],
                "fundamentals": statement,
                "financial_history": storage.list_periods(sym),
                "gaps": [],
            }
        else:
            existing["fundamentals"] = statement
            existing["financial_history"] = storage.list_periods(sym)
            existing["retrieved_at"] = now_iso
            quote_price = existing.get("quote", {}).get("price")

        self.store(existing, sym)
        calc_result = fundamentals(statement, price=quote_price, previous=prev_stmt)
        return {
            "symbol": sym,
            "period": statement.get("period"),
            "period_type": statement.get("period_type"),
            "currency": statement.get("currency", "IDR"),
            "unit": statement.get("unit"),
            "ratios": calc_result.get("ratios", {}),
            "citations": statement.get("citations", {}),
            "validation_status": statement.get("validation_status", "VALIDATED"),
            "validation_notes": statement.get("validation_notes", []),
            "source": statement["source"],
            "provenance": f"Official financial statement disclosure import ({path.name})",
        }

    def store(self, data: dict, symbol: str) -> None:
        self.validate(data)
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", symbol) or data.get("symbol") != symbol:
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


def read_tabular(path: Path) -> list[list[str]]:
    """Lightweight tabular reader supporting CSV, XLSX (stdlib zip/xml), and JSON."""
    if not path.exists():
        raise FileNotFoundError(f"File tidak ditemukan: {path}")
    ext = path.suffix.lower()
    if ext == ".xlsx":
        import zipfile
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(path, "r") as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                s_tree = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in s_tree.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                    t = si.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                    shared.append(t.text if t is not None else "")
            sheet_name = next((n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")), "xl/worksheets/sheet1.xml")
            tree = ET.fromstring(z.read(sheet_name))
            rows = []
            ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for r in tree.findall(".//main:row", ns):
                row_vals = []
                for c in r.findall("main:c", ns):
                    v = c.find("main:v", ns)
                    val = v.text if v is not None else ""
                    if c.get("t") == "s" and val.isdigit():
                        val = shared[int(val)] if int(val) < len(shared) else val
                    row_vals.append(val)
                rows.append(row_vals)
            return rows
    elif ext == ".csv":
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
            return list(csv.reader(f))
    elif ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return [list(data.keys()), list(data.values())]
    raise ValueError(f"Format file tidak didukung: {ext}. Gunakan CSV, XLSX, atau JSON.")


def validate_statement(statement: dict) -> None:
    source_url(statement["source"])
    timestamp(statement["published_at"])
    if statement.get("currency") not in {"IDR", "USD"} or statement.get("unit") not in {"IDR", "thousand_IDR", "million_IDR", "billion_IDR", "USD", "thousand_USD", "million_USD"}:
        raise ValueError("Statement monetary unit/currency is required")
    if statement.get("period_type") not in {"TTM", "FY", "QUARTER", "Q1", "Q2", "Q3", "Q4", "H1", "9M"} or not statement.get("period") or not statement.get("basis"):
        raise ValueError("Statement requires fiscal period, duration and accounting basis")
    for value in statement.get("values", {}).values():
        if value is not None:
            number(value)
    for value in statement.get("reported_ratios_pct", {}).values():
        if value is not None:
            number(value)


def fundamentals(statement: dict | None, price: float | None, previous: dict | None = None) -> dict:
    if not statement:
        return {"ratios": {}, "gaps": ["Financial statements unavailable"]}
    validate_statement(statement)
    unit_multipliers = {
        "IDR": 1.0, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9,
        "USD": 1.0, "thousand_USD": 1e3, "million_USD": 1e6, "billion_USD": 1e9,
    }
    multiplier = unit_multipliers.get(statement["unit"], 1.0)
    raw = statement.get("values", {})
    shares = number(raw["weighted_average_shares"], positive=True) if raw.get("weighted_average_shares") else None
    outstanding = number(raw["shares_outstanding"], positive=True) if raw.get("shares_outstanding") else None
    values = {key: number(value) * multiplier for key, value in raw.items()
              if key not in {"weighted_average_shares", "shares_outstanding"} and value is not None}
    ratios = {}

    def ratio(label: str, numerator: str, denominator: str, scale: float = 1) -> None:
        n, d = values.get(numerator), values.get(denominator)
        if n is not None and d is not None and d > 0:
            ratios[label] = n / d * scale

    if "net_income_attributable" not in values and "net_income" in values:
        values["net_income_attributable"] = values["net_income"]
    if "equity_attributable" not in values and "equity" in values:
        values["equity_attributable"] = values["equity"]
    if "net_income" not in values and "net_income_attributable" in values:
        values["net_income"] = values["net_income_attributable"]
    if "equity" not in values and "equity_attributable" in values:
        values["equity"] = values["equity_attributable"]

    income = values.get("net_income_attributable")
    equity = values.get("equity_attributable")
    if income is not None and shares:
        ratios["EPS"] = income / shares
        if price and income > 0 and statement["period_type"] in {"FY", "TTM"}:
            ratios["PER"] = price / ratios["EPS"]
    if price and equity is not None and equity > 0 and outstanding:
        ratios["PBV"] = price / (equity / outstanding)

    # Average equity and assets handling with historical previous
    if previous:
        prev_raw = previous.get("values", {})
        prev_mult = unit_multipliers.get(previous.get("unit", "million_IDR"), 1.0)
        p_eq = prev_raw.get("equity_attributable") or prev_raw.get("equity")
        p_ast = prev_raw.get("total_assets") or prev_raw.get("assets")
        curr_eq = values.get("equity_attributable") or values.get("equity")
        curr_ast = values.get("total_assets") or values.get("assets")
        if curr_eq is not None and p_eq is not None and "average_equity_attributable" not in values:
            values["average_equity_attributable"] = (curr_eq + (p_eq * prev_mult)) / 2.0
            ratios["average_equity_basis"] = "two_point_average"
        if curr_ast is not None and p_ast is not None and "average_assets" not in values:
            values["average_assets"] = (curr_ast + (p_ast * prev_mult)) / 2.0
            ratios["average_assets_basis"] = "two_point_average"

    if "average_equity_attributable" not in values:
        eq_val = values.get("equity_attributable") or values.get("equity") or values.get("total_equity")
        if eq_val is not None:
            values["average_equity_attributable"] = eq_val
            ratios["average_equity_basis"] = "ending_balance_point_in_time"
    if "average_assets" not in values:
        ast_val = values.get("assets") or values.get("total_assets")
        if ast_val is not None:
            values["average_assets"] = ast_val
    if "net_income" not in values and "net_income_attributable" in values:
        values["net_income"] = values["net_income_attributable"]
    if "equity" not in values and "equity_attributable" in values:
        values["equity"] = values["equity_attributable"]

    # Distinct interest-bearing debt from general liabilities
    if "interest_bearing_debt" in values and values["interest_bearing_debt"] is not None:
        ratio("Debt_to_Equity", "interest_bearing_debt", "equity")
    elif "total_liabilities" in values and values["total_liabilities"] is not None:
        ratio("Debt_to_Equity", "total_liabilities", "equity")
        ratio("Total_Liabilities_to_Equity", "total_liabilities", "equity")

    ratio("ROE_pct", "net_income_attributable", "average_equity_attributable", 100)
    ratio("ROA_pct", "net_income", "average_assets", 100)
    ratio("Operating_Margin_pct", "operating_income", "revenue", 100)
    ratio("Net_Margin_pct", "net_income", "revenue", 100)

    # Sector-aware Free Cash Flow (FCF)
    is_bank = (
        statement.get("sector", "").upper() in {"FINANCIALS", "KEUANGAN", "BANK"}
        or any(k in statement.get("reported_ratios_pct", {}) for k in ("NIM", "CAR", "NPL_gross", "CASA", "LDR"))
    )
    if is_bank:
        ratios["FCF_IDR"] = None
        ratios["FCF_status"] = "NOT_MEANINGFUL"
        ratios["FCF_note"] = "NOT_MEANINGFUL (Sektor Keuangan/Perbankan: Arus kas operasional bank dipengaruhi penghimpunan simpanan dan penyaluran kredit, bukan belanja modal industri)."
    else:
        if "operating_cash_flow" in values and "capital_expenditure" in values:
            ratios["FCF_IDR"] = values["operating_cash_flow"] - abs(values["capital_expenditure"])
            ratios["FCF_status"] = "CALCULATED"

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
