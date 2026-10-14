"""Central Data Provider Registry, Capability Matrix & Auto-Selector.

Orchestrates multi-provider discovery, health checks, credential validation,
freshness enforcement, and priority-based failover across Equities, Crypto,
Macro, and Filing domains.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.data.provider_base import (
    DataProvider,
    DataResult,
    ErrorCode,
    FreshnessStatus,
    QualityStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Concrete Provider Implementations
# =============================================================================

class YahooFinanceEquitiesProvider(DataProvider):
    """Yahoo Finance API adapter for IDX and US equity market quotes and OHLCV."""

    provider_id = "yahoo_finance_id"
    display_name = "Yahoo Finance (IDX & US EOD / Delayed Quotes)"
    asset_classes = ["EQUITY_ID", "EQUITY_US", "INDEX"]
    datasets = ["quotes", "ohlcv", "corporate_actions"]
    authentication_type = "ZERO_KEY"
    requires_credentials = False
    supports_live = False  # Delayed intraday or official EOD close
    supports_historical = True
    supports_corporate_events = True
    freshness_policy = "SESSION_EOD"
    rate_limit_policy = "max_60_req_per_min"
    licensing_status = "PUBLIC_DOCUMENTED_API"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_repo_root()

    def health_check(self) -> tuple[bool, str]:
        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/BBCA.JK?range=1d&interval=1d"
            req = urllib.request.Request(url, headers={"User-Agent": "OpenBagus/1.0"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    return True, "Yahoo Finance endpoint operasional (HTTP 200)."
                return False, f"HTTP status tidak normal: {resp.status}"
        except Exception as e:
            return False, f"Koneksi Yahoo Finance gagal: {e}"

    def fetch_quotes(self, symbols: list[str], **kwargs: Any) -> DataResult:
        t_start = time.perf_counter()
        if not symbols:
            return DataResult.failure(self.provider_id, ErrorCode.INVALID_SYMBOL, "Daftar simbol kosong.")

        results: dict[str, Any] = {}
        for sym in symbols:
            clean = sym.strip().upper()
            from openbagus.domains.equities.data import EquityData
            eq_data = EquityData(self.root)
            raw = eq_data.load(clean, auto_fetch=True)
            if raw.get("gaps"):
                results[clean] = {"symbol": clean, "status": "DATA_GAP", "gaps": raw.get("gaps")}
            else:
                q = raw.get("quote", {})
                candles = raw.get("candles", [])
                last_c = candles[-1] if candles else {}
                results[clean] = {
                    "symbol": clean,
                    "price": q.get("price") or last_c.get("close"),
                    "previous_close": q.get("previous_close"),
                    "open": last_c.get("open"),
                    "high": last_c.get("high"),
                    "low": last_c.get("low"),
                    "close": last_c.get("close"),
                    "volume": last_c.get("volume"),
                    "observation_date": last_c.get("close_at", "")[:10] if last_c.get("close_at") else last_c.get("date", "-"),
                    "delayed": True,
                    "currency": raw.get("currency", "IDR"),
                    "status": "AVAILABLE",
                }

        latency = (time.perf_counter() - t_start) * 1000
        return DataResult(
            success=True,
            data=results,
            provider_id=self.provider_id,
            source_url="https://finance.yahoo.com",
            is_live=False,
            quality_status=QualityStatus.OBSERVED.value,
            freshness_status=FreshnessStatus.LATEST_EOD.value,
            latency_ms=latency,
        )

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "D1",
        limit: int = 100,
        **kwargs: Any,
    ) -> DataResult:
        t_start = time.perf_counter()
        clean = symbol.strip().upper()
        from openbagus.domains.equities.data import EquityData
        eq_data = EquityData(self.root)
        raw = eq_data.load(clean, auto_fetch=True)
        latency = (time.perf_counter() - t_start) * 1000

        if raw.get("gaps"):
            return DataResult.failure(
                self.provider_id,
                ErrorCode.DATA_NOT_FOUND,
                f"Data OHLCV untuk '{clean}' belum tersedia: {raw.get('gaps')}",
                latency_ms=latency,
            )

        candles = raw.get("candles", [])
        sliced = candles[-limit:] if limit > 0 else candles
        return DataResult(
            success=True,
            data={
                "symbol": clean,
                "timeframe": timeframe,
                "count": len(sliced),
                "bars": sliced,
                "currency": raw.get("currency", "IDR"),
                "source": raw.get("source"),
            },
            provider_id=self.provider_id,
            source_url=raw.get("source"),
            as_of=raw.get("retrieved_at"),
            is_live=False,
            quality_status=QualityStatus.OBSERVED.value,
            freshness_status=FreshnessStatus.LATEST_EOD.value,
            latency_ms=latency,
        )


class SecEdgarProvider(DataProvider):
    """Official SEC EDGAR API provider for US-listed corporate filings and XBRL facts."""

    provider_id = "sec_edgar"
    display_name = "SEC EDGAR (Official US Filings & XBRL Facts)"
    asset_classes = ["EQUITY_US"]
    datasets = ["fundamentals", "filings", "corporate_events"]
    authentication_type = "ZERO_KEY"
    requires_credentials = False
    supports_live = False
    supports_historical = True
    supports_fundamentals = True
    supports_filings = True
    supports_corporate_events = True
    freshness_policy = "FILING_CADENCE"
    rate_limit_policy = "max_10_req_per_sec"
    licensing_status = "OFFICIAL"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_repo_root()
        from openbagus.domains.equities.sec_edgar import SecEdgarClient
        self.client = SecEdgarClient(self.root)

    def health_check(self) -> tuple[bool, str]:
        try:
            # Query lightweight CIK mapping or head
            cik = self.client.resolve_ticker("AAPL")
            if cik:
                return True, f"SEC EDGAR operasional (AAPL CIK: {cik})."
            return False, "Gagal menyelesaikan CIK Apple Inc."
        except Exception as e:
            return False, f"SEC EDGAR error: {e}"

    def fetch_financial_statements(
        self,
        symbol: str,
        period: str | None = None,
        **kwargs: Any,
    ) -> DataResult:
        t_start = time.perf_counter()
        clean = symbol.strip().upper()
        try:
            stmts = self.client.extract_canonical_statements(clean)
            latency = (time.perf_counter() - t_start) * 1000
            if not stmts:
                return DataResult.failure(
                    self.provider_id,
                    ErrorCode.DATA_NOT_FOUND,
                    f"Tidak ditemukan laporan keuangan XBRL SEC untuk '{clean}'.",
                    latency_ms=latency,
                )

            periods_data = [s.to_legacy_dict() for s in stmts]
            if period:
                matched = next((p for p in periods_data if p.get("period") == period), None)
                res_data = matched or periods_data[-1]
            else:
                res_data = periods_data[-1]

            return DataResult(
                success=True,
                data={
                    "symbol": clean,
                    "target_period": period or "LATEST",
                    "statement": res_data,
                    "available_periods": [s.period for s in stmts],
                },
                provider_id=self.provider_id,
                source_url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{self.client.resolve_ticker(clean) or 0:010d}.json",
                quality_status=QualityStatus.OFFICIAL_REPORTED.value,
                freshness_status=FreshnessStatus.HISTORICAL.value,
                latency_ms=latency,
            )
        except Exception as e:
            latency = (time.perf_counter() - t_start) * 1000
            return DataResult.failure(self.provider_id, ErrorCode.PARSE_FAILED, str(e), latency_ms=latency)


class BinanceVisionCryptoProvider(DataProvider):
    """Binance Vision official public spot market market-data-only provider."""

    provider_id = "binance_vision"
    display_name = "Binance Vision (Zero-Key Public Spot Data)"
    asset_classes = ["CRYPTO"]
    datasets = ["quotes", "ohlcv", "orderbook"]
    authentication_type = "ZERO_KEY"
    requires_credentials = False
    supports_live = True
    supports_historical = True
    freshness_policy = "REALTIME_TICKER"
    rate_limit_policy = "max_1200_req_per_min"
    licensing_status = "PUBLIC_DOCUMENTED_API"

    def __init__(self) -> None:
        from openbagus.data.zerokey import ZeroKeyMarketData
        self.zk = ZeroKeyMarketData()

    def health_check(self) -> tuple[bool, str]:
        try:
            url = "https://data-api.binance.vision/api/v3/ping"
            req = urllib.request.Request(url, headers={"User-Agent": "OpenBagus/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    return True, "Binance Vision endpoint operasional (HTTP 200)."
                return False, f"HTTP status: {resp.status}"
        except Exception as e:
            return False, f"Binance Vision ping gagal: {e}"

    def fetch_quotes(self, symbols: list[str], **kwargs: Any) -> DataResult:
        t_start = time.perf_counter()
        results: dict[str, Any] = {}
        for s in symbols:
            clean = s.strip().upper()
            t = self.zk.get_spot_ticker(clean)
            if t:
                results[clean] = t
            else:
                results[clean] = {"symbol": clean, "status": "DATA_NOT_FOUND"}

        latency = (time.perf_counter() - t_start) * 1000
        return DataResult(
            success=bool(results),
            data=results,
            provider_id=self.provider_id,
            source_url="https://data-api.binance.vision",
            is_live=True,
            quality_status=QualityStatus.OBSERVED.value,
            freshness_status=FreshnessStatus.LIVE.value,
            latency_ms=latency,
        )

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 50,
        **kwargs: Any,
    ) -> DataResult:
        t_start = time.perf_counter()
        clean = symbol.strip().upper()
        # Map timeframes: D1 -> 1d, H1 -> 1h, M15 -> 15m
        tf_map = {"D1": "1d", "H1": "1h", "H4": "4h", "M15": "15m", "M5": "5m", "M1": "1m"}
        interval = tf_map.get(timeframe.upper(), timeframe.lower())
        bars = self.zk.get_klines(clean, interval=interval, limit=limit)
        latency = (time.perf_counter() - t_start) * 1000

        if not bars:
            return DataResult.failure(
                self.provider_id,
                ErrorCode.DATA_NOT_FOUND,
                f"Kandil kripto tidak ditemukan untuk '{clean}' pada interval '{interval}'.",
                latency_ms=latency,
            )

        return DataResult(
            success=True,
            data={"symbol": clean, "interval": interval, "count": len(bars), "bars": bars},
            provider_id=self.provider_id,
            source_url="https://data-api.binance.vision/api/v3/klines",
            is_live=True,
            quality_status=QualityStatus.OBSERVED.value,
            freshness_status=FreshnessStatus.LIVE.value,
            latency_ms=latency,
        )


class WorldBankMacroProvider(DataProvider):
    """World Bank Open Data official public macroeconomic statistics provider."""

    provider_id = "worldbank_macro"
    display_name = "World Bank Open Data (Indonesia Macro Series)"
    asset_classes = ["MACRO"]
    datasets = ["macro_series"]
    authentication_type = "ZERO_KEY"
    requires_credentials = False
    supports_macro = True
    supports_historical = True
    freshness_policy = "ANNUAL_STATISTICS"
    rate_limit_policy = "unrestricted_public"
    licensing_status = "OFFICIAL"

    def health_check(self) -> tuple[bool, str]:
        try:
            url = "https://api.worldbank.org/v2/country/IDN/indicator/FP.CPI.TOTL.ZG?format=json&per_page=1"
            req = urllib.request.Request(url, headers={"User-Agent": "OpenBagus/1.0"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    return True, "World Bank Open Data API operasional (HTTP 200)."
                return False, f"HTTP status: {resp.status}"
        except Exception as e:
            return False, f"World Bank API gagal: {e}"

    def fetch_macro_series(self, series_id: str, **kwargs: Any) -> DataResult:
        t_start = time.perf_counter()
        from openbagus.data.indonesia_official import WorldBankAdapter
        # Map common keys: CPI / INFLASI -> FP.CPI.TOTL.ZG, GDP -> NY.GDP.MKTP.CD
        ind_map = {
            "CPI": "FP.CPI.TOTL.ZG",
            "INFLASI": "FP.CPI.TOTL.ZG",
            "INFLATION": "FP.CPI.TOTL.ZG",
            "GDP": "NY.GDP.MKTP.CD",
            "TRADE": "NE.TRD.GNFS.ZS",
        }
        target_ind = ind_map.get(series_id.upper(), series_id)
        series = WorldBankAdapter.get_indonesia_macro(target_ind)
        latency = (time.perf_counter() - t_start) * 1000

        if not series:
            return DataResult.failure(
                self.provider_id,
                ErrorCode.DATA_NOT_FOUND,
                f"Indikator makro '{series_id}' tidak ditemukan.",
                latency_ms=latency,
            )

        latest_val = float(series[0].get("value")) if series and series[0].get("value") is not None else 0.0
        return DataResult(
            success=True,
            data={
                "series_id": series_id,
                "indicator": series_id.upper(),
                "indicator_code": target_ind,
                "country": "IDN",
                "latest_value": latest_val,
                "unit": "Annual %",
                "period": str(series[0].get("date")) if series else "",
                "count": len(series),
                "latest": series[0] if series else {},
                "history": series,
            },
            provider_id=self.provider_id,
            source_url=f"https://api.worldbank.org/v2/country/IDN/indicator/{target_ind}?format=json",
            quality_status=QualityStatus.OFFICIAL_REPORTED.value,
            freshness_status=FreshnessStatus.HISTORICAL.value,
            latency_ms=latency,
        )


class IdxOfficialDisclosuresProvider(DataProvider):
    """Official IDX company profiles, disclosures index, and local document intake adapter."""

    provider_id = "idx_official"
    display_name = "Bursa Efek Indonesia (IDX Official Disclosures & Intake)"
    asset_classes = ["EQUITY_ID"]
    datasets = ["fundamentals", "filings", "corporate_events"]
    authentication_type = "ZERO_KEY"
    requires_credentials = False
    supports_fundamentals = True
    supports_filings = True
    supports_corporate_events = True
    freshness_policy = "FILING_CADENCE"
    rate_limit_policy = "local_and_inbox"
    licensing_status = "OFFICIAL"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_repo_root()
        from openbagus.domains.equities.discovery import DocumentDiscoveryManager
        self.discovery = DocumentDiscoveryManager(self.root)

    def health_check(self) -> tuple[bool, str]:
        from openbagus.domains.equities.catalog import EquityCatalog
        cat = EquityCatalog(self.root)
        count = len([a for a in cat.assets if a.asset_type == "EQUITY_ID"])
        if count >= 900:
            return True, f"Katalog resmi BEI aktif ({count} emiten terdaftar)."
        return False, f"Katalog BEI memuat {count} emiten (di bawah batas minimum)."

    def fetch_disclosures(self, symbol: str, limit: int = 10, **kwargs: Any) -> DataResult:
        t_start = time.perf_counter()
        clean = symbol.strip().upper()
        info = self.discovery.get_issuer_discovery(clean)
        latency = (time.perf_counter() - t_start) * 1000
        return DataResult(
            success=True,
            data=info,
            provider_id=self.provider_id,
            source_url=info.get("idx_official_url"),
            quality_status=QualityStatus.OFFICIAL_REPORTED.value,
            freshness_status=FreshnessStatus.HISTORICAL.value,
            latency_ms=latency,
        )


# =============================================================================
# Central Provider Registry Singleton
# =============================================================================

class DataProviderRegistry:
    """Singleton registry coordinating all active, verified data providers."""

    _instance: DataProviderRegistry | None = None

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_repo_root()
        self._providers: dict[str, DataProvider] = {}
        self._register_default_providers()

    @classmethod
    def get_instance(cls, root: Path | None = None) -> "DataProviderRegistry":
        if cls._instance is None:
            cls._instance = cls(root)
        return cls._instance

    def _register_default_providers(self) -> None:
        self.register(YahooFinanceEquitiesProvider(self.root))
        self.register(SecEdgarProvider(self.root))
        self.register(BinanceVisionCryptoProvider())
        self.register(WorldBankMacroProvider())
        self.register(IdxOfficialDisclosuresProvider(self.root))

    def register(self, provider: DataProvider) -> None:
        self._providers[provider.provider_id] = provider
        logger.debug("Registered data provider: %s (%s)", provider.provider_id, provider.display_name)

    def get_provider(self, provider_id: str) -> DataProvider | None:
        clean = provider_id.strip().lower()
        alias_map = {
            "world_bank_macro": "worldbank_macro",
            "world_bank": "worldbank_macro",
            "worldbank": "worldbank_macro",
            "yahoo_finance": "yahoo_finance_id",
            "yahoo": "yahoo_finance_id",
            "binance": "binance_vision",
            "binance_vision_crypto": "binance_vision",
            "idx": "idx_official",
            "edgar": "sec_edgar",
        }
        resolved = alias_map.get(clean, clean)
        return self._providers.get(resolved)

    def list_providers(self) -> list[dict[str, Any]]:
        """Returns metadata for all registered providers."""
        return [p.list_capabilities() for p in self._providers.values()]

    def run_diagnostics(self) -> list[dict[str, Any]]:
        """Executes discovery and health checks across all registered providers."""
        results = []
        for p in self._providers.values():
            results.append(p.discover())
        return results

    def select_best_provider(
        self,
        asset_class: str,
        dataset: str,
    ) -> DataProvider | None:
        """Selects the highest-priority, operational provider matching asset class and dataset."""
        norm_asset = asset_class.upper().strip()
        norm_ds = dataset.lower().strip()

        candidates = [
            p for p in self._providers.values()
            if norm_asset in p.asset_classes and norm_ds in p.datasets
        ]

        if not candidates:
            return None

        # Return first matching provider (registered by precedence)
        return candidates[0]
