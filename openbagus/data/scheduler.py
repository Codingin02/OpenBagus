"""Data Sync Scheduler and Cache Freshness Policy Manager.

Provides tiered synchronization (Priority A through E) for market data,
cryptocurrency tickers, macroeconomic indicators, and regulatory filings.
Includes rate limiting, exponential backoff on 429 errors, and audit state.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from openbagus.core.env import get_repo_root
from openbagus.data.provider_base import ErrorCode
from openbagus.data.registry import DataProviderRegistry
from openbagus.data.zerokey import ZeroKeyMarketData
from openbagus.domains.equities.data import EquityData

logger = logging.getLogger(__name__)


class SyncPriority(str, Enum):
    """Tiered sync priorities."""
    A_USER_INTERACTIVE = "A_USER_INTERACTIVE"  # Immediate on-demand query
    B_ACTIVE_WATCHLIST = "B_ACTIVE_WATCHLIST"  # User-pinned tickers (5-15m)
    C_BENCHMARK_INDEX = "C_BENCHMARK_INDEX"    # Major indices (IHSG, BTC, etc.)
    D_MACRO_FILINGS = "D_MACRO_FILINGS"        # Monthly/quarterly updates
    E_BACKGROUND_SWEEP = "E_BACKGROUND_SWEEP"  # Broad catalog reconciliation


@dataclass
class SyncTaskResult:
    target: str
    target_type: str  # "EQUITY", "CRYPTO", "MACRO", "FILING"
    priority: str
    success: bool
    status: str
    timestamp: float
    latency_ms: float
    error_code: str | None = None
    error_message: str | None = None
    records_synced: int = 0


class DataSyncScheduler:
    """Manages scheduled and on-demand synchronization across all data providers."""

    _instance: DataSyncScheduler | None = None

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.eq_data = EquityData(self.root)
        self.registry = DataProviderRegistry.get_instance(self.root)
        self.zerokey = ZeroKeyMarketData.get_instance()

        self._lock = threading.Lock()
        self._history: list[SyncTaskResult] = []
        self._rate_limits: dict[str, dict[str, Any]] = {
            "YAHOO_FINANCE": {"max_per_min": 30, "calls": [], "backoff_until": 0.0},
            "BINANCE_VISION": {"max_per_min": 60, "calls": [], "backoff_until": 0.0},
            "SEC_EDGAR": {"max_per_min": 10, "calls": [], "backoff_until": 0.0},
            "WORLD_BANK": {"max_per_min": 30, "calls": [], "backoff_until": 0.0},
        }

    @classmethod
    def get_instance(cls, repo_root: Path | None = None) -> DataSyncScheduler:
        if cls._instance is None:
            cls._instance = cls(repo_root)
        return cls._instance

    # -------------------------------------------------------------------------
    # Rate Limiting & Backoff Governance
    # -------------------------------------------------------------------------

    def _can_call(self, provider_id: str) -> tuple[bool, float]:
        """Returns (can_call, wait_seconds)."""
        now = time.time()
        cfg = self._rate_limits.get(provider_id)
        if not cfg:
            return True, 0.0

        if now < cfg["backoff_until"]:
            return False, cfg["backoff_until"] - now

        # Prune calls older than 60s
        cfg["calls"] = [t for t in cfg["calls"] if now - t < 60.0]
        if len(cfg["calls"]) >= cfg["max_per_min"]:
            oldest = cfg["calls"][0]
            wait_s = max(0.5, 60.0 - (now - oldest))
            return False, wait_s

        return True, 0.0

    def _record_call(self, provider_id: str) -> None:
        cfg = self._rate_limits.get(provider_id)
        if cfg:
            cfg["calls"].append(time.time())

    def _trigger_backoff(self, provider_id: str, base_delay: float = 30.0) -> None:
        cfg = self._rate_limits.get(provider_id)
        if cfg:
            jitter = random.uniform(1.0, 5.0)
            cfg["backoff_until"] = time.time() + base_delay + jitter
            logger.warning(
                "Triggered rate-limit backoff on %s for %.1f seconds",
                provider_id,
                base_delay + jitter,
            )

    # -------------------------------------------------------------------------
    # Synchronization Operations
    # -------------------------------------------------------------------------

    def sync_ticker(
        self,
        ticker: str,
        priority: SyncPriority = SyncPriority.A_USER_INTERACTIVE,
        force: bool = False,
    ) -> SyncTaskResult:
        """Synchronizes an individual ticker (IDX equity or crypto)."""
        t0 = time.perf_counter()
        clean = ticker.strip().upper()
        is_crypto = clean in {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"} or clean.endswith(("USDT", "BUSD"))

        if is_crypto:
            # Crypto sync via ZeroKey
            sym = clean.replace("USDT", "")
            can_call, wait_s = self._can_call("BINANCE_VISION")
            if not can_call and not force:
                res = SyncTaskResult(
                    target=clean,
                    target_type="CRYPTO",
                    priority=priority.value,
                    success=False,
                    status="RATE_LIMITED",
                    timestamp=time.time(),
                    latency_ms=(time.perf_counter() - t0) * 1000,
                    error_code=ErrorCode.RATE_LIMITED.value,
                    error_message=f"Rate limit active. Wait {wait_s:.1f}s",
                )
                self._record_history(res)
                return res

            self._record_call("BINANCE_VISION")
            ticker_data = self.zerokey.get_spot_ticker(sym)
            latency = (time.perf_counter() - t0) * 1000

            if ticker_data:
                res = SyncTaskResult(
                    target=clean,
                    target_type="CRYPTO",
                    priority=priority.value,
                    success=True,
                    status="SUCCESS",
                    timestamp=time.time(),
                    latency_ms=latency,
                    records_synced=1,
                )
            else:
                res = SyncTaskResult(
                    target=clean,
                    target_type="CRYPTO",
                    priority=priority.value,
                    success=False,
                    status="FAILED",
                    timestamp=time.time(),
                    latency_ms=latency,
                    error_code=ErrorCode.NETWORK_OFFLINE.value,
                    error_message="Failed to retrieve crypto ticker from zero-key providers",
                )
            self._record_history(res)
            return res

        # Equity sync via Yahoo Finance provider / EquityData
        can_call, wait_s = self._can_call("YAHOO_FINANCE")
        if not can_call and not force:
            res = SyncTaskResult(
                target=clean,
                target_type="EQUITY",
                priority=priority.value,
                success=False,
                status="RATE_LIMITED",
                timestamp=time.time(),
                latency_ms=(time.perf_counter() - t0) * 1000,
                error_code=ErrorCode.RATE_LIMITED.value,
                error_message=f"Rate limit active. Wait {wait_s:.1f}s",
            )
            self._record_history(res)
            return res

        self._record_call("YAHOO_FINANCE")
        fresh = self.eq_data.fetch_live_data(clean, save=True)
        latency = (time.perf_counter() - t0) * 1000
        candles = fresh.get("candles", [])

        if candles:
            res = SyncTaskResult(
                target=clean,
                target_type="EQUITY",
                priority=priority.value,
                success=True,
                status="SUCCESS",
                timestamp=time.time(),
                latency_ms=latency,
                records_synced=len(candles),
            )
        else:
            gaps = fresh.get("gaps", ["No candles returned"])
            res = SyncTaskResult(
                target=clean,
                target_type="EQUITY",
                priority=priority.value,
                success=False,
                status="FAILED",
                timestamp=time.time(),
                latency_ms=latency,
                error_code=ErrorCode.DATA_NOT_FOUND.value,
                error_message="; ".join(gaps),
            )
        self._record_history(res)
        return res

    def sync_macro(
        self,
        series: str = "CPI",
        priority: SyncPriority = SyncPriority.D_MACRO_FILINGS,
        force: bool = False,
    ) -> SyncTaskResult:
        """Synchronizes official macroeconomic series."""
        t0 = time.perf_counter()
        clean = series.strip().upper()

        can_call, wait_s = self._can_call("WORLD_BANK")
        if not can_call and not force:
            res = SyncTaskResult(
                target=clean,
                target_type="MACRO",
                priority=priority.value,
                success=False,
                status="RATE_LIMITED",
                timestamp=time.time(),
                latency_ms=(time.perf_counter() - t0) * 1000,
                error_code=ErrorCode.RATE_LIMITED.value,
                error_message=f"Rate limit active. Wait {wait_s:.1f}s",
            )
            self._record_history(res)
            return res

        self._record_call("WORLD_BANK")
        prov = self.registry.get_provider("WORLD_BANK_MACRO")
        if not prov:
            res = SyncTaskResult(
                target=clean,
                target_type="MACRO",
                priority=priority.value,
                success=False,
                status="PROVIDER_UNAVAILABLE",
                timestamp=time.time(),
                latency_ms=(time.perf_counter() - t0) * 1000,
                error_code=ErrorCode.SOURCE_UNAVAILABLE.value,
                error_message="World Bank provider not registered",
            )
            self._record_history(res)
            return res

        data_res = prov.fetch_macro_series(clean)
        latency = (time.perf_counter() - t0) * 1000

        if data_res.success:
            count = len(data_res.data.get("history", [])) if isinstance(data_res.data, dict) else 1
            res = SyncTaskResult(
                target=clean,
                target_type="MACRO",
                priority=priority.value,
                success=True,
                status="SUCCESS",
                timestamp=time.time(),
                latency_ms=latency,
                records_synced=count,
            )
        else:
            res = SyncTaskResult(
                target=clean,
                target_type="MACRO",
                priority=priority.value,
                success=False,
                status="FAILED",
                timestamp=time.time(),
                latency_ms=latency,
                error_code=data_res.error_code or ErrorCode.ERR_UPSTREAM_NETWORK.value,
                error_message=data_res.error_message,
            )
        self._record_history(res)
        return res

    def sync_watchlist(
        self,
        tickers: list[str],
        priority: SyncPriority = SyncPriority.B_ACTIVE_WATCHLIST,
        delay_between_calls: float = 0.5,
    ) -> list[SyncTaskResult]:
        """Batches synchronization of multiple tickers with rate-limiting pauses."""
        results = []
        for sym in tickers:
            res = self.sync_ticker(sym, priority=priority)
            results.append(res)
            if delay_between_calls > 0:
                time.sleep(delay_between_calls)
        return results

    # -------------------------------------------------------------------------
    # Audit & Status
    # -------------------------------------------------------------------------

    def _record_history(self, res: SyncTaskResult) -> None:
        with self._lock:
            self._history.append(res)
            if len(self._history) > 200:
                self._history.pop(0)

    def get_status(self) -> dict[str, Any]:
        """Returns scheduler health, active rate-limits, and sync metrics."""
        with self._lock:
            total_syncs = len(self._history)
            successful_syncs = sum(1 for r in self._history if r.success)
            failed_syncs = total_syncs - successful_syncs

            recent = [asdict(r) for r in self._history[-10:]]

        return {
            "total_syncs": total_syncs,
            "successful_syncs": successful_syncs,
            "failed_syncs": failed_syncs,
            "rate_limits": {
                p: {
                    "calls_last_minute": len(cfg["calls"]),
                    "max_per_minute": cfg["max_per_min"],
                    "is_backed_off": time.time() < cfg["backoff_until"],
                }
                for p, cfg in self._rate_limits.items()
            },
            "recent_syncs": recent,
        }
