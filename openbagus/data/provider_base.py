"""Canonical Data Provider Architecture and Failure Taxonomy for OpenBagus.

Enforces standardized provider capabilities, explicit failure modes,
data provenance tracking, and zero-hallucination data contracts.
"""

from __future__ import annotations

import abc
import enum
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class ErrorCode(str, enum.Enum):
    """Canonical error taxonomy for all data provider operations."""
    INVALID_SYMBOL = "INVALID_SYMBOL"
    DATA_NOT_FOUND = "DATA_NOT_FOUND"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    API_KEY_MISSING = "API_KEY_MISSING"
    INVALID_API_KEY = "INVALID_API_KEY"
    BILLING_REQUIRED = "BILLING_REQUIRED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    NETWORK_OFFLINE = "NETWORK_OFFLINE"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    PARSE_FAILED = "PARSE_FAILED"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    STALE_DATA = "STALE_DATA"
    UNSUPPORTED_DATASET = "UNSUPPORTED_DATASET"
    LICENSE_RESTRICTION = "LICENSE_RESTRICTION"


class QualityStatus(str, enum.Enum):
    """Provenance and data truth classification."""
    OBSERVED = "OBSERVED"
    OFFICIAL_REPORTED = "OFFICIAL_REPORTED"
    NORMALIZED = "NORMALIZED"
    CALCULATED = "CALCULATED"
    ESTIMATED = "ESTIMATED"
    ASSUMPTION = "ASSUMPTION"
    UNAVAILABLE = "UNAVAILABLE"


class FreshnessStatus(str, enum.Enum):
    """Data freshness lifecycle state."""
    REALTIME_VERIFIED = "REALTIME_VERIFIED"
    DELAYED_VERIFIED = "DELAYED_VERIFIED"
    LATEST_EOD = "LATEST_EOD"
    HISTORICAL = "HISTORICAL"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"

    # Backwards-compatible aliases
    LIVE = "REALTIME_VERIFIED"
    DELAYED = "DELAYED_VERIFIED"
    LATEST_CLOSE = "LATEST_EOD"


@dataclass
class DataResult:
    """Standardized response container for all data provider calls."""
    success: bool
    data: Any = None
    error_code: str | None = None
    error_message: str | None = None
    provider_id: str = ""
    source_url: str | None = None
    as_of: str | None = None
    retrieved_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_live: bool = False
    quality_status: str = QualityStatus.UNAVAILABLE.value
    freshness_status: str = FreshnessStatus.UNKNOWN.value
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "provider_id": self.provider_id,
            "source_url": self.source_url,
            "as_of": self.as_of,
            "retrieved_at": self.retrieved_at,
            "is_live": self.is_live,
            "quality_status": self.quality_status,
            "freshness_status": self.freshness_status,
            "latency_ms": round(self.latency_ms, 1),
        }

    @classmethod
    def unsupported(cls, provider_id: str, dataset_name: str) -> "DataResult":
        return cls(
            success=False,
            error_code=ErrorCode.UNSUPPORTED_DATASET.value,
            error_message=f"Penyedia '{provider_id}' tidak mendukung dataset '{dataset_name}'.",
            provider_id=provider_id,
            quality_status=QualityStatus.UNAVAILABLE.value,
        )

    @classmethod
    def failure(
        cls,
        provider_id: str,
        error_code: ErrorCode | str,
        error_message: str,
        latency_ms: float = 0.0,
    ) -> "DataResult":
        code_str = error_code.value if isinstance(error_code, ErrorCode) else str(error_code)
        return cls(
            success=False,
            error_code=code_str,
            error_message=error_message,
            provider_id=provider_id,
            quality_status=QualityStatus.UNAVAILABLE.value,
            latency_ms=latency_ms,
        )


class DataProvider(abc.ABC):
    """Abstract Base Class for all OpenBagus market and macro data providers."""

    provider_id: str
    display_name: str
    asset_classes: list[str]  # e.g. ["EQUITY_ID", "EQUITY_US"], ["CRYPTO"], ["MACRO"]
    datasets: list[str]       # e.g. ["quotes", "ohlcv", "fundamentals", "filings", "corporate_events", "macro"]
    authentication_type: str  # "ZERO_KEY", "API_KEY", "BEARER_TOKEN", "OAUTH2"
    requires_credentials: bool = False
    supports_live: bool = False
    supports_historical: bool = False
    supports_fundamentals: bool = False
    supports_filings: bool = False
    supports_corporate_events: bool = False
    supports_macro: bool = False
    freshness_policy: str = "SESSION_EOD"
    rate_limit_policy: str = "standard"
    licensing_status: str = "PUBLIC_DOCUMENTED_API"

    def list_capabilities(self) -> dict[str, Any]:
        """Returns full structured metadata describing supported datasets and capabilities."""
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "asset_classes": self.asset_classes,
            "datasets": self.datasets,
            "authentication_type": self.authentication_type,
            "requires_credentials": self.requires_credentials,
            "supports_live": self.supports_live,
            "supports_historical": self.supports_historical,
            "supports_fundamentals": self.supports_fundamentals,
            "supports_filings": self.supports_filings,
            "supports_corporate_events": self.supports_corporate_events,
            "supports_macro": self.supports_macro,
            "freshness_policy": self.freshness_policy,
            "rate_limit_policy": self.rate_limit_policy,
            "licensing_status": self.licensing_status,
        }

    @abc.abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Returns (is_healthy, status_message)."""
        pass

    def verify_credentials(self) -> tuple[str, str]:
        """Validates configured credentials if required. Returns (state, message)."""
        if not self.requires_credentials:
            return "VALIDATED", "Zero-key public access (tidak membutuhkan credentials)."
        return "NOT_CONFIGURED", "API credentials belum dikonfigurasi."

    def discover(self) -> dict[str, Any]:
        """Discovers provider operational state and latency metrics."""
        t_start = time.perf_counter()
        healthy, msg = self.health_check()
        latency = (time.perf_counter() - t_start) * 1000
        cred_state, cred_msg = self.verify_credentials()
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "healthy": healthy,
            "status_message": msg,
            "latency_ms": round(latency, 1),
            "credential_state": cred_state,
            "credential_message": cred_msg,
            "capabilities": self.list_capabilities(),
        }

    # -------------------------------------------------------------------------
    # Core Data Methods (Default to unsupported with explicit status)
    # -------------------------------------------------------------------------

    def fetch_quotes(self, symbols: list[str], **kwargs: Any) -> DataResult:
        return DataResult.unsupported(self.provider_id, "quotes")

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "D1",
        limit: int = 100,
        **kwargs: Any,
    ) -> DataResult:
        return DataResult.unsupported(self.provider_id, "ohlcv")

    def fetch_financial_statements(
        self,
        symbol: str,
        period: str | None = None,
        **kwargs: Any,
    ) -> DataResult:
        return DataResult.unsupported(self.provider_id, "financial_statements")

    def fetch_disclosures(
        self,
        symbol: str,
        limit: int = 10,
        **kwargs: Any,
    ) -> DataResult:
        return DataResult.unsupported(self.provider_id, "disclosures")

    def fetch_corporate_actions(
        self,
        symbol: str,
        **kwargs: Any,
    ) -> DataResult:
        return DataResult.unsupported(self.provider_id, "corporate_actions")

    def fetch_macro_series(
        self,
        series_id: str,
        **kwargs: Any,
    ) -> DataResult:
        return DataResult.unsupported(self.provider_id, "macro_series")
