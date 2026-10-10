"""OpenBagus Canonical API Cache and Local Market Data Storage.

Implements a unified multi-layer cache:
1. Fast in-process memory cache (L1).
2. Persistent local SQLite database (L2) under %LOCALAPPDATA%\\OpenBagus\\cache.
3. Freshness-aware TTL policies, ETag/304 conditional revalidation, in-flight request
   deduplication, rate-limit cooldown governance, and non-secret credential state tracking.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbagus.data.http import SecureHttpClient, sanitize_url
from openbagus.intelligence.local_language import get_local_appdata_dir

# Freshness Policies in Seconds (Section B6)
DEFAULT_FRESHNESS_POLICIES: dict[str, float] = {
    "ORDERBOOK": 10.0,
    "SPOT_TICKER": 20.0,
    "INTRADAY_CANDLES": 90.0,
    "DAILY_CANDLES": 3600.0,
    "DERIVATIVES": 300.0,
    "SENTIMENT": 600.0,
    "DEFI": 600.0,
    "MACRO": 3600.0,
    "METADATA": 86400.0,
    "FX": 3600.0,
    "DEFAULT": 30.0,
    "NEGATIVE": 15.0,
}

SECRET_PARAM_NAMES = frozenset({
    "key", "apikey", "api_key", "token", "secret", "auth",
    "password", "bearer", "access_token",
})


def make_cache_key(
    url: str,
    method: str = "GET",
    auth_identity: str | None = None,
    vary_headers: dict[str, str] | None = None,
) -> str:
    """Generate a stable, deterministic cache key from non-secret request identity (Section B3, Section D).

    If secret query parameters or auth_identity are present, a non-reversible SHA256 hash
    of the credential identity is appended, ensuring two different accounts cannot share
    cache entries while never storing raw secrets in the key.
    """
    parsed = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_params: list[tuple[str, str]] = []
    secret_values: list[str] = []
    for k, v in sorted(query_params):
        k_lower = k.lower().replace("-", "_")
        if any(secret in k_lower for secret in SECRET_PARAM_NAMES):
            secret_values.append(v)
            continue
        filtered_params.append((k, v))
    norm_query = urllib.parse.urlencode(filtered_params)
    norm_url = urllib.parse.urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", norm_query, ""))

    ident_parts = [f"{method.upper()}:{norm_url}"]

    if auth_identity:
        auth_hash = hashlib.sha256(auth_identity.encode("utf-8")).hexdigest()[:16]
        ident_parts.append(f"auth:{auth_hash}")

    if vary_headers:
        norm_vary = ";".join(f"{k.lower()}={v}" for k, v in sorted(vary_headers.items()))
        ident_parts.append(f"vary:{norm_vary}")

    ident = "|".join(ident_parts)
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()


def detect_dataset_type(url: str) -> str:
    """Classify the dataset type based on URL path/query for policy selection."""
    u = url.lower()
    if "/depth" in u or "orderbook" in u:
        return "ORDERBOOK"
    if "/ticker/24hr" in u or "spot/tickers" in u or "market/tickers" in u or "pools/" in u:
        return "SPOT_TICKER"
    if "/klines" in u or "candles" in u:
        if "interval=1d" in u or "interval=1w" in u or "category=d1" in u:
            return "DAILY_CANDLES"
        return "INTRADAY_CANDLES"
    if any(k in u for k in ("funding", "openinterest", "premiumindex", "future-markets")):
        return "DERIVATIVES"
    if "fomc" in u or "cpi" in u or "fred" in u or "stlouisfed" in u:
        return "MACRO"
    if "frankfurter" in u or "kurs" in u or "fiat" in u:
        return "FX"
    if "alternative.me" in u or "sentiment" in u:
        return "SENTIMENT"
    if "llama.fi" in u or "defillama" in u:
        return "DEFI"
    if "assets" in u or "catalog" in u or "categories" in u:
        return "METADATA"
    return "DEFAULT"


@dataclass
class CacheEntry:
    cache_key: str
    provider: str
    dataset_type: str
    url: str
    data: Any
    etag: str | None
    last_modified: str | None
    observed_at: str
    retrieved_at: str
    expires_at: float
    cache_status: str


class MarketDataCache:
    """Canonical multi-layer market data cache with atomic SQLite storage and request coalescing."""

    _instance: MarketDataCache | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        db_path: Path | None = None,
        clock: Any | None = None,
        http_client: SecureHttpClient | None = None,
        max_l1_entries: int = 500,
        max_l1_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self._clock = clock
        self.http = http_client or SecureHttpClient(timeout=3.5)
        self.policies = dict(DEFAULT_FRESHNESS_POLICIES)
        self.max_l1_entries = max_l1_entries
        self.max_l1_bytes = max_l1_bytes

        # L1 Memory Cache (bounded LRU ordered dictionary)
        self._memory_cache: dict[str, CacheEntry] = {}
        self._negative_cache: dict[str, tuple[str, float]] = {}  # key -> (status, expires_at)
        self._lock = threading.RLock()

        # In-flight request deduplication (Section B10)
        self._in_flight: dict[str, threading.Event] = {}
        self._in_flight_results: dict[str, tuple[Any | None, str, dict[str, Any]]] = {}

        # Resolve L2 SQLite Path (Section B5)
        if db_path:
            self.db_path = Path(db_path)
        else:
            cache_dir = get_local_appdata_dir() / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = cache_dir / "openbagus_cache.db"

        self._conn: sqlite3.Connection | None = None
        self._init_sqlite()

    @classmethod
    def get_instance(cls, db_path: Path | None = None) -> MarketDataCache:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    def _now(self) -> float:
        return float(self._clock() if self._clock is not None else time.time())

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=10.0)
            self._conn.row_factory = sqlite3.Row
            try:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            except sqlite3.DatabaseError:
                pass
        return self._conn

    def _init_sqlite(self) -> None:
        try:
            conn = self._get_conn()
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS market_cache (
                        cache_key TEXT PRIMARY KEY,
                        provider TEXT,
                        dataset_type TEXT,
                        url TEXT,
                        etag TEXT,
                        last_modified TEXT,
                        response_json TEXT,
                        observed_at TEXT,
                        retrieved_at TEXT,
                        expires_at REAL,
                        cache_status TEXT
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS provider_health (
                        provider_id TEXT PRIMARY KEY,
                        status TEXT,
                        cooldown_until REAL,
                        retry_after INTEGER,
                        last_error TEXT,
                        updated_at TEXT
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS credential_validation (
                        provider_id TEXT PRIMARY KEY,
                        key_hash TEXT,
                        status TEXT,
                        checked_at TEXT,
                        error_category TEXT,
                        expires_at REAL
                    );
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache_metrics (
                        metric_name TEXT PRIMARY KEY,
                        metric_value INTEGER
                    );
                """)
        except sqlite3.DatabaseError:
            # Corruption recovery (Section F3)
            self._quarantine_corrupt_db()

    def _quarantine_corrupt_db(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self.db_path.exists():
            corrupt_path = self.db_path.with_name(f"{self.db_path.name}.corrupt_{int(time.time())}")
            try:
                self.db_path.rename(corrupt_path)
            except OSError:
                pass
        self._init_sqlite()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            self._memory_cache.clear()
            self._in_flight.clear()
            self._in_flight_results.clear()

    def __del__(self) -> None:
        self.close()

    def _record_stat(self, metric: str, increment: int = 1) -> None:
        with self._lock:
            try:
                conn = self._get_conn()
                with conn:
                    conn.execute("""
                        INSERT INTO cache_metrics (metric_name, metric_value)
                        VALUES (?, ?)
                        ON CONFLICT(metric_name) DO UPDATE SET metric_value = metric_value + ?;
                    """, (metric, increment, increment))
            except sqlite3.DatabaseError:
                pass

    def _get_stat(self, metric: str) -> int:
        with self._lock:
            try:
                conn = self._get_conn()
                cur = conn.execute("SELECT metric_value FROM cache_metrics WHERE metric_name = ?;", (metric,))
                row = cur.fetchone()
                return int(row["metric_value"]) if row else 0
            except sqlite3.DatabaseError:
                return 0

    def get_ttl(self, dataset_type: str) -> float:
        return self.policies.get(dataset_type, self.policies.get("DEFAULT", 30.0))

    # --- Provider Cooldown Governance (Section B11) ---

    def is_provider_in_cooldown(self, provider_id: str) -> bool:
        with self._lock:
            now = self._now()
            try:
                conn = self._get_conn()
                cur = conn.execute(
                    "SELECT cooldown_until FROM provider_health WHERE provider_id = ? AND cooldown_until > ?;",
                    (provider_id, now),
                )
                return cur.fetchone() is not None
            except sqlite3.DatabaseError:
                return False

    def set_provider_cooldown(self, provider_id: str, retry_after: int, error_msg: str = "RATE_LIMITED") -> None:
        with self._lock:
            now = self._now()
            cooldown_until = now + float(retry_after)
            try:
                conn = self._get_conn()
                with conn:
                    conn.execute("""
                        INSERT INTO provider_health (provider_id, status, cooldown_until, retry_after, last_error, updated_at)
                        VALUES (?, 'RATE_LIMITED', ?, ?, ?, datetime('now'))
                        ON CONFLICT(provider_id) DO UPDATE SET
                            status = 'RATE_LIMITED',
                            cooldown_until = ?,
                            retry_after = ?,
                            last_error = ?,
                            updated_at = datetime('now');
                    """, (provider_id, cooldown_until, retry_after, error_msg, cooldown_until, retry_after, error_msg))
            except sqlite3.DatabaseError:
                pass

    def clear_provider_cooldown(self, provider_id: str) -> None:
        with self._lock:
            try:
                conn = self._get_conn()
                with conn:
                    conn.execute("DELETE FROM provider_health WHERE provider_id = ?;", (provider_id,))
            except sqlite3.DatabaseError:
                pass

    def get_provider_cooldowns(self) -> dict[str, float]:
        with self._lock:
            now = self._now()
            cooldowns: dict[str, float] = {}
            try:
                conn = self._get_conn()
                cur = conn.execute("SELECT provider_id, cooldown_until FROM provider_health WHERE cooldown_until > ?;", (now,))
                for row in cur.fetchall():
                    cooldowns[row["provider_id"]] = round(row["cooldown_until"] - now, 1)
            except sqlite3.DatabaseError:
                pass
            return cooldowns

    def is_in_cooldown(self, provider_id: str) -> bool:
        return self.is_provider_in_cooldown(provider_id)

    def get_cooldown_remaining(self, provider_id: str) -> float:
        return self.get_provider_cooldowns().get(provider_id, 0.0)

    # --- Credential State Cache (Section C4) ---

    def get_credential_state(self, provider_id: str, key_hash: str) -> str | None:
        with self._lock:
            now = self._now()
            try:
                conn = self._get_conn()
                cur = conn.execute(
                    "SELECT status FROM credential_validation WHERE provider_id = ? AND key_hash = ? AND expires_at > ?;",
                    (provider_id, key_hash, now),
                )
                row = cur.fetchone()
                return str(row["status"]) if row else None
            except sqlite3.DatabaseError:
                return None

    def set_credential_state(
        self,
        provider_id: str,
        key_hash: str,
        status: str,
        error_category: str = "",
        ttl_seconds: float = 86400.0,
    ) -> None:
        with self._lock:
            expires_at = self._now() + ttl_seconds
            try:
                conn = self._get_conn()
                with conn:
                    conn.execute("""
                        INSERT INTO credential_validation (provider_id, key_hash, status, checked_at, error_category, expires_at)
                        VALUES (?, ?, ?, datetime('now'), ?, ?)
                        ON CONFLICT(provider_id) DO UPDATE SET
                            key_hash = ?,
                            status = ?,
                            checked_at = datetime('now'),
                            error_category = ?,
                            expires_at = ?;
                    """, (provider_id, key_hash, status, error_category, expires_at,
                          key_hash, status, error_category, expires_at))
            except sqlite3.DatabaseError:
                pass

    def get_all_credential_states(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        try:
            conn = self._get_conn()
            cur = conn.execute("SELECT provider_id, key_hash, status, checked_at, error_category FROM credential_validation;")
            for row in cur.fetchall():
                results[row["provider_id"]] = {
                    "key_hash": row["key_hash"],
                    "status": row["status"],
                    "checked_at": row["checked_at"],
                    "error_category": row["error_category"],
                }
        except sqlite3.DatabaseError:
            pass
        return results

    # --- Cache Storage and Retrieval ---

    def _estimated_l1_bytes(self) -> int:
        total = 0
        for entry in self._memory_cache.values():
            if isinstance(entry.data, (dict, list)):
                total += len(str(entry.data))
            elif isinstance(entry.data, str):
                total += len(entry.data)
            else:
                total += 128
        return total

    def _evict_l1_if_needed(self) -> None:
        now = self._now()
        # 1. Evict expired
        expired = [k for k, v in self._memory_cache.items() if now >= v.expires_at]
        for k in expired:
            self._memory_cache.pop(k, None)

        # 2. Evict oldest until count < max_l1_entries
        while len(self._memory_cache) >= self.max_l1_entries:
            oldest_key = next(iter(self._memory_cache))
            self._memory_cache.pop(oldest_key, None)

        # 3. Evict oldest until estimated bytes <= max_l1_bytes
        while self._estimated_l1_bytes() > self.max_l1_bytes and self._memory_cache:
            oldest_key = next(iter(self._memory_cache))
            self._memory_cache.pop(oldest_key, None)

    def _read_l1(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._memory_cache.get(key)
            if entry:
                if self._now() < entry.expires_at:
                    # Move to end for LRU
                    self._memory_cache[key] = self._memory_cache.pop(key)
                    return entry
                self._memory_cache.pop(key, None)
            return None

    def _read_l2(self, key: str) -> CacheEntry | None:
        with self._lock:
            now = self._now()
            try:
                conn = self._get_conn()
                cur = conn.execute("""
                    SELECT cache_key, provider, dataset_type, url, etag, last_modified,
                           response_json, observed_at, retrieved_at, expires_at, cache_status
                    FROM market_cache WHERE cache_key = ?;
                """, (key,))
                row = cur.fetchone()
                if not row:
                    return None
                data = json.loads(row["response_json"])
                entry = CacheEntry(
                    cache_key=row["cache_key"],
                    provider=row["provider"],
                    dataset_type=row["dataset_type"],
                    url=row["url"],
                    data=data,
                    etag=row["etag"],
                    last_modified=row["last_modified"],
                    observed_at=row["observed_at"],
                    retrieved_at=row["retrieved_at"],
                    expires_at=float(row["expires_at"]),
                    cache_status="CACHE_VALID" if now < float(row["expires_at"]) else "STALE_REFERENCE",
                )
                self._evict_l1_if_needed()
                self._memory_cache[key] = entry
                return entry
            except (sqlite3.DatabaseError, json.JSONDecodeError):
                return None

    def _write_entry(self, entry: CacheEntry, skip_l2: bool = False) -> None:
        with self._lock:
            self._evict_l1_if_needed()
            self._memory_cache[entry.cache_key] = entry
            if skip_l2:
                return
            try:
                raw_json = json.dumps(entry.data)
                conn = self._get_conn()
                with conn:
                    conn.execute("""
                        INSERT INTO market_cache (
                            cache_key, provider, dataset_type, url, etag, last_modified,
                            response_json, observed_at, retrieved_at, expires_at, cache_status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(cache_key) DO UPDATE SET
                            provider = ?,
                            dataset_type = ?,
                            url = ?,
                            etag = ?,
                            last_modified = ?,
                            response_json = ?,
                            observed_at = ?,
                            retrieved_at = ?,
                            expires_at = ?,
                            cache_status = ?;
                    """, (
                        entry.cache_key, entry.provider, entry.dataset_type, entry.url,
                        entry.etag, entry.last_modified, raw_json, entry.observed_at,
                        entry.retrieved_at, entry.expires_at, entry.cache_status,
                        entry.provider, entry.dataset_type, entry.url,
                        entry.etag, entry.last_modified, raw_json, entry.observed_at,
                        entry.retrieved_at, entry.expires_at, entry.cache_status,
                    ))
            except sqlite3.DatabaseError:
                self._quarantine_corrupt_db()

    def _extract_provider(self, url: str) -> str:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        if "binance" in netloc:
            return "binance"
        if "gateio" in netloc:
            return "gateio"
        if "bybit" in netloc:
            return "bybit"
        if "okx" in netloc:
            return "okx"
        if "geckoterminal" in netloc:
            return "geckoterminal"
        if "coingecko" in netloc:
            return "coingecko"
        if "coinlore" in netloc:
            return "coinlore"
        if "frankfurter" in netloc:
            return "frankfurter"
        return netloc or "public_provider"

    # --- Core Request Coordination Layer (Section B) ---

    def get_with_metadata(
        self,
        url: str,
        dataset_type: str | None = None,
        ttl_seconds: float | None = None,
        force_refresh: bool = False,
        network_fetcher: Any | None = None,
        ttl: float | None = None,
        auth_identity: str | None = None,
        vary_headers: dict[str, str] | None = None,
    ) -> tuple[Any | None, str, dict[str, Any]]:
        """Retrieve data from cache or network with request coalescing and conditional revalidation.
        
        Returns: (data, status_label, metadata_dict)
        where status_label is one of: FRESH, CACHE_VALID, REVALIDATED, STALE_REFERENCE, REFRESH_FAILED
        """
        now = self._now()
        cache_key = make_cache_key(url, auth_identity=auth_identity, vary_headers=vary_headers)
        ds_type = dataset_type or detect_dataset_type(url)
        effective_ttl = ttl if ttl is not None else ttl_seconds
        ttl_val = effective_ttl if effective_ttl is not None else self.get_ttl(ds_type)
        provider = self._extract_provider(url)

        # 1. Negative Cache Check (Section B12)
        with self._lock:
            neg = self._negative_cache.get(cache_key)
            if neg and now < neg[1] and not force_refresh:
                return None, "REFRESH_FAILED", {
                    "source": provider, "observed_at": "N/A", "retrieved_at": "N/A",
                    "freshness_status": "UNVERIFIED", "cache_status": "NEGATIVE_CACHE",
                }

        # 2. Check Cooldown
        if self.is_provider_in_cooldown(provider) and not force_refresh:
            stale = self._read_l1(cache_key) or self._read_l2(cache_key)
            if stale:
                self._record_stat("cache_hits", 1)
                return stale.data, "STALE_REFERENCE", {
                    "source": provider, "observed_at": stale.observed_at,
                    "retrieved_at": stale.retrieved_at, "freshness_status": "STALE_REFERENCE",
                    "cache_status": "STALE_REFERENCE",
                }
            return None, "RATE_LIMITED", {
                "source": provider, "observed_at": "N/A", "retrieved_at": "N/A",
                "freshness_status": "RATE_LIMITED", "cache_status": "COOLDOWN_ACTIVE",
            }

        # 3. Cache Hit Check (L1 & L2)
        if not force_refresh:
            l1_hit = self._read_l1(cache_key)
            if l1_hit and now < l1_hit.expires_at:
                self._record_stat("cache_hits", 1)
                return l1_hit.data, "CACHE_VALID", {
                    "source": provider, "observed_at": l1_hit.observed_at,
                    "retrieved_at": l1_hit.retrieved_at, "freshness_status": "CACHE_VALID",
                    "cache_status": "CACHE_VALID",
                }

            l2_hit = self._read_l2(cache_key)
            if l2_hit and now < l2_hit.expires_at:
                self._record_stat("cache_hits", 1)
                return l2_hit.data, "CACHE_VALID", {
                    "source": provider, "observed_at": l2_hit.observed_at,
                    "retrieved_at": l2_hit.retrieved_at, "freshness_status": "CACHE_VALID",
                    "cache_status": "CACHE_VALID",
                }

        # 4. In-flight Request Deduplication / Coalescing (Section B10)
        with self._lock:
            if cache_key in self._in_flight:
                event = self._in_flight[cache_key]
                is_leader = False
            else:
                event = threading.Event()
                self._in_flight[cache_key] = event
                is_leader = True

        if not is_leader:
            # Wait for in-flight request leader to complete
            event.wait(timeout=10.0)
            self._record_stat("deduplicated_requests", 1)
            with self._lock:
                if cache_key in self._in_flight_results:
                    return self._in_flight_results[cache_key]
            # Fallback to cache read
            res = self._read_l1(cache_key) or self._read_l2(cache_key)
            if res:
                return res.data, res.cache_status, {
                    "source": provider, "observed_at": res.observed_at,
                    "retrieved_at": res.retrieved_at, "freshness_status": res.cache_status,
                    "cache_status": res.cache_status,
                }
            return None, "REFRESH_FAILED", {"source": provider, "cache_status": "REFRESH_FAILED"}

        # 5. Leader Executes Network Fetch with Conditional Revalidation (Section B8)
        self._record_stat("cache_misses", 1)
        stale_entry = self._read_l2(cache_key) if not force_refresh else None
        headers: dict[str, str] = {}
        if stale_entry:
            if stale_entry.etag:
                headers["If-None-Match"] = stale_entry.etag
            if stale_entry.last_modified:
                headers["If-Modified-Since"] = stale_entry.last_modified

        result_data: Any | None = None
        result_status: str = "REFRESH_FAILED"
        result_meta: dict[str, Any] = {"source": provider}

        try:
            if network_fetcher is not None:
                raw, status, elapsed_ms, resp_headers = network_fetcher(url, headers)
            else:
                raw, status, elapsed_ms, resp_headers = self.http.fetch_with_metadata(url, headers=headers)

            # Case A: HTTP 304 Not Modified
            if (status in ("NOT_MODIFIED", 304)) and stale_entry:
                retrieved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                expires_at = now + ttl_val
                stale_entry.retrieved_at = retrieved_at
                stale_entry.expires_at = expires_at
                stale_entry.cache_status = "REVALIDATED"
                self._write_entry(stale_entry)
                self._record_stat("revalidated_requests", 1)
                result_data = stale_entry.data
                result_status = "REVALIDATED"
                result_meta = {
                    "source": provider, "observed_at": stale_entry.observed_at,
                    "retrieved_at": retrieved_at, "freshness_status": "REVALIDATED",
                    "cache_status": "REVALIDATED",
                }

            # Case B: HTTP 429 Rate Limited (Section B11)
            elif status in ("RATE_LIMITED", 429):
                retry_header = resp_headers.get("Retry-After") or resp_headers.get("retry-after")
                retry_after = int(retry_header) if retry_header and retry_header.isdigit() else 60
                self.set_provider_cooldown(provider, retry_after)
                if stale_entry:
                    result_data = stale_entry.data
                    result_status = "STALE_REFERENCE"
                    result_meta = {
                        "source": provider, "observed_at": stale_entry.observed_at,
                        "retrieved_at": stale_entry.retrieved_at, "freshness_status": "STALE_REFERENCE",
                        "cache_status": "STALE_REFERENCE",
                    }
                else:
                    result_data = None
                    result_status = "RATE_LIMITED"
                    result_meta = {
                        "source": provider, "observed_at": "N/A", "retrieved_at": "N/A",
                        "freshness_status": "RATE_LIMITED", "cache_status": "RATE_LIMITED",
                    }

            # Case C: HTTP 200 Reachable with payload
            elif (status in ("REACHABLE", 200) or status == "OK") and raw:
                try:
                    parsed_json = json.loads(raw)
                    obs_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    etag = resp_headers.get("ETag") or resp_headers.get("etag")
                    last_mod = resp_headers.get("Last-Modified") or resp_headers.get("last-modified")
                    cc = (resp_headers.get("Cache-Control") or resp_headers.get("cache-control") or "").lower()
                    is_no_store = "no-store" in cc
                    is_private = "private" in cc

                    if is_no_store:
                        # HTTP Cache-Control: no-store (Section D)
                        self._record_stat("network_fetches", 1)
                        result_data = parsed_json
                        result_status = "FRESH"
                        result_meta = {
                            "source": provider, "observed_at": obs_time,
                            "retrieved_at": obs_time, "freshness_status": "FRESH",
                            "cache_status": "NO_STORE",
                        }
                    else:
                        skip_l2 = is_private and not auth_identity
                        new_entry = CacheEntry(
                            cache_key=cache_key,
                            provider=provider,
                            dataset_type=ds_type,
                            url=sanitize_url(url),
                            data=parsed_json,
                            etag=etag,
                            last_modified=last_mod,
                            observed_at=obs_time,
                            retrieved_at=obs_time,
                            expires_at=now + ttl_val,
                            cache_status="FRESH",
                        )
                        self._write_entry(new_entry, skip_l2=skip_l2)
                        self._record_stat("network_fetches", 1)
                        result_data = parsed_json
                        result_status = "FRESH"
                        result_meta = {
                            "source": provider, "observed_at": obs_time,
                            "retrieved_at": obs_time, "freshness_status": "FRESH",
                            "cache_status": "FRESH",
                        }
                except (json.JSONDecodeError, ValueError):
                    # Negative cache for malformed JSON
                    with self._lock:
                        self._negative_cache[cache_key] = ("MALFORMED_JSON", now + self.policies["NEGATIVE"])
                    result_data = None
                    result_status = "REFRESH_FAILED"
                    result_meta = {"source": provider, "cache_status": "MALFORMED_JSON"}

            # Case D: Network/Host Error
            else:
                with self._lock:
                    self._negative_cache[cache_key] = (status, now + self.policies["NEGATIVE"])
                if stale_entry:
                    result_data = stale_entry.data
                    result_status = "STALE_REFERENCE"
                    result_meta = {
                        "source": provider, "observed_at": stale_entry.observed_at,
                        "retrieved_at": stale_entry.retrieved_at, "freshness_status": "STALE_REFERENCE",
                        "cache_status": "STALE_REFERENCE",
                    }
                else:
                    result_data = None
                    result_status = "REFRESH_FAILED"
                    result_meta = {"source": provider, "cache_status": status}

        finally:
            with self._lock:
                self._in_flight_results[cache_key] = (result_data, result_status, result_meta)
                event.set()
                self._in_flight.pop(cache_key, None)

        return result_data, result_status, result_meta

    def get_json(
        self,
        url: str,
        dataset_type: str | None = None,
        ttl_seconds: float | None = None,
        force_refresh: bool = False,
        network_fetcher: Any | None = None,
        ttl: float | None = None,
        auth_identity: str | None = None,
        vary_headers: dict[str, str] | None = None,
    ) -> Any | None:
        """Convenience method returning parsed JSON data or None."""
        data, _, _ = self.get_with_metadata(
            url,
            dataset_type=dataset_type,
            ttl_seconds=ttl_seconds,
            force_refresh=force_refresh,
            network_fetcher=network_fetcher,
            ttl=ttl,
            auth_identity=auth_identity,
            vary_headers=vary_headers,
        )
        return data

    # --- Cache Management and Invalidation (Section B9, E2) ---

    def refresh_asset(self, asset: str) -> int:
        """Force invalidate cached entries for a specific asset symbol (Section B9)."""
        sym = asset.upper().replace("/USD", "").replace("-USD", "").replace("USDT", "")
        with self._lock:
            # Invalidate L1 matching symbol
            keys_to_del = [k for k, v in self._memory_cache.items() if sym in v.url.upper()]
            for k in keys_to_del:
                self._memory_cache.pop(k, None)

        # Invalidate L2 matching symbol
        deleted = 0
        try:
            conn = self._get_conn()
            with conn:
                cur = conn.execute("DELETE FROM market_cache WHERE UPPER(url) LIKE ?;", (f"%{sym}%",))
                deleted = cur.rowcount
        except sqlite3.DatabaseError:
            pass
        return deleted

    def clear_cache(self) -> int:
        """Clear all market data cache entries while preserving configuration."""
        with self._lock:
            self._memory_cache.clear()
            self._negative_cache.clear()
        deleted = 0
        try:
            conn = self._get_conn()
            with conn:
                cur = conn.execute("DELETE FROM market_cache;")
                deleted = cur.rowcount
                conn.execute("DELETE FROM provider_health;")
        except sqlite3.DatabaseError:
            pass
        return deleted

    def get_stats(self) -> dict[str, Any]:
        """Collect comprehensive cache performance and storage statistics (Section E2)."""
        entry_count = 0
        try:
            conn = self._get_conn()
            cur = conn.execute("SELECT COUNT(*) AS cnt FROM market_cache;")
            entry_count = cur.fetchone()["cnt"]
        except sqlite3.DatabaseError:
            pass

        disk_size = 0
        if self.db_path.exists():
            try:
                disk_size = self.db_path.stat().st_size
                wal_path = self.db_path.with_name(f"{self.db_path.name}-wal")
                if wal_path.exists():
                    disk_size += wal_path.stat().st_size
            except OSError:
                pass

        return {
            "entry_count": entry_count,
            "memory_entries": len(self._memory_cache),
            "disk_size_bytes": disk_size,
            "disk_size_kb": round(disk_size / 1024, 1),
            "cache_hits": self._get_stat("cache_hits"),
            "cache_misses": self._get_stat("cache_misses"),
            "network_fetches": self._get_stat("network_fetches"),
            "deduplicated_requests": self._get_stat("deduplicated_requests"),
            "revalidated_requests": self._get_stat("revalidated_requests"),
            "provider_cooldowns": self.get_provider_cooldowns(),
        }

    def get_statistics(self) -> dict[str, Any]:
        """Alias for get_stats()."""
        return self.get_stats()

    def format_status_display(self) -> str:
        st = self.get_stats()
        hits = st["cache_hits"]
        fetches = st["network_fetches"]
        dedups = st["deduplicated_requests"]
        total_requests = hits + fetches + dedups
        hit_rate = f"{(hits / total_requests * 100):.1f}%" if total_requests > 0 else "N/A"
        cd_info = ", ".join(f"{k}: {v}s" for k, v in st["provider_cooldowns"].items()) or "None active"

        lines = [
            "OpenBagus API Cache Status",
            "==========================",
            f"Stored Entries      {st['entry_count']} records ({st['memory_entries']} in memory)",
            f"Local DB Size       {st['disk_size_kb']} KB",
            f"Cache Hits          {hits}",
            f"Network Fetches     {fetches}",
            f"Deduplicated Calls  {dedups}",
            f"Hit Rate            {hit_rate}",
            f"Provider Cooldowns  {cd_info}",
        ]
        return "\n".join(lines)

    def format_policy_display(self) -> str:
        lines = [
            "OpenBagus Market Data Freshness Policy",
            "======================================",
            f"Microstructure / Book  {self.policies['ORDERBOOK']}s TTL",
            f"Spot Quotes / Tickers  {self.policies['SPOT_TICKER']}s TTL",
            f"Intraday OHLCV Candles {self.policies['INTRADAY_CANDLES']}s TTL",
            f"Daily Closed Candles   {self.policies['DAILY_CANDLES']}s (1 hour)",
            f"Funding & Open Interest {self.policies['DERIVATIVES']}s (5 min)",
            f"Market Sentiment / TVL {self.policies['SENTIMENT']}s (10 min)",
            f"Macro (CPI / FOMC)     {self.policies['MACRO']}s (1 hour)",
            f"Forex Reference Rates  {self.policies['FX']}s (1 hour)",
            f"Asset Catalog Metadata {self.policies['METADATA']}s (24 hours)",
            f"Negative Cache Hold    {self.policies['NEGATIVE']}s (error backoff)",
            "",
            "Revalidation: ETag / If-None-Match & If-Modified-Since with HTTP 304 handling.",
        ]
        return "\n".join(lines)
