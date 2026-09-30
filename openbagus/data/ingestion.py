"""OpenBagus Runtime Data Ingestion Engine.

Ingests market, macro, and alternative data for active domains (currently crypto)
and shared cross-asset macro context.

Equity/IDX ingestion is explicitly disabled in this deployment phase.
Research-only execution: does not execute trades or call private execution APIs.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _from_epoch_seconds(value: float | int | None) -> str | None:
    if value is None:
        return None
    return _to_iso(datetime.fromtimestamp(float(value), timezone.utc))


def _from_epoch_millis(value: float | int | None) -> str | None:
    if value is None:
        return None
    return _from_epoch_seconds(float(value) / 1000.0)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        if f != f:  # NaN check
            return None
        return f
    except (TypeError, ValueError):
        return None


def _short_error(exc: BaseException | str) -> str:
    text = str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        text = f"HTTP {exc.code}: {exc.reason}"
    elif isinstance(exc, urllib.error.URLError):
        text = f"URL error: {exc.reason}"
    return text.replace("\n", " ")[:240]


class RuntimeDataIngestion:
    """Fetch public research data and persist runtime outputs."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.source_config = self._load_config("config/openbagus_data_sources.json")
        self.freshness_config = self._load_config("config/openbagus_freshness_policy.json")
        self.request_policy = self.source_config.get("request_policy", {
            "timeout_seconds": 12,
            "max_retries": 2,
            "backoff_seconds": 1.0,
            "user_agent": "OpenBagus-Research/2.0",
        })
        self.run_id = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        self.fetched_at_utc = _to_iso(_utc_now())
        self.market_rows: list[dict[str, Any]] = []
        self.macro_rows: list[dict[str, Any]] = []
        self.source_health: list[dict[str, Any]] = []
        self.warnings: list[str] = []

        # Windows SSL context fallback
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def _load_config(self, relative_path: str) -> dict[str, Any]:
        p = self.root / relative_path
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def run(
        self,
        *,
        mode: str = "real",
        assets: list[str] | None = None,
        idx_symbols: list[str] | None = None,
        all_core: bool = False,
        db_path: str | None = None,
    ) -> dict[str, Any]:
        selected_assets = self._select_crypto_assets(assets, all_core)

        # Equity domain is strictly disabled
        if idx_symbols:
            self.warnings.append("Equities domain is currently disabled. Requested IDX symbols were not fetched.")

        if mode == "dry-run":
            self._record_dry_run(selected_assets, all_core)
        elif mode == "real":
            for asset in selected_assets:
                self._fetch_crypto_asset(asset)
            if all_core or not assets:
                self._fetch_core_macro_market()
                self._fetch_defillama_stablecoins()
                self._fetch_fred_if_available()
        else:
            raise ValueError(f"Unsupported mode: {mode}")

        duckdb_result = self._persist_duckdb(db_path)
        payload = self._build_payload(mode, selected_assets, all_core, duckdb_result)
        self._write_reports(payload)
        return payload

    def _select_crypto_assets(self, assets: list[str] | None, all_core: bool) -> list[str]:
        configured = self.source_config.get("core_assets", {}).get("crypto", {})
        selected = list(assets or [])
        if all_core or not assets:
            selected.extend(configured.keys())
        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped = []
        for a in selected:
            if a in configured and a not in seen:
                seen.add(a)
                deduped.append(a)
        return deduped

    def _record_dry_run(self, assets: list[str], all_core: bool) -> None:
        planned_count = len(assets)
        if all_core or not assets:
            planned_count += len(self.source_config.get("core_assets", {}).get("macro_market", {})) + 2
        self.source_health.append({
            "source_name": "openbagus_dry_run_plan",
            "provider": "local_runtime",
            "asset_class": "runtime_plan",
            "country": "GLOBAL",
            "status": "WARNING",
            "reason": f"dry-run only; planned source attempts: {planned_count}",
            "source_ref": "local_config",
            "rows_returned": 0,
            "checked_at_utc": self.fetched_at_utc,
        })

    def _fetch_json(
        self,
        *,
        source_name: str,
        provider: str,
        asset_class: str,
        country: str,
        source_url: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        timeout = float(self.request_policy.get("timeout_seconds", 12))
        max_retries = int(self.request_policy.get("max_retries", 2))
        backoff = float(self.request_policy.get("backoff_seconds", 1.0))
        user_agent = str(self.request_policy.get("user_agent", "OpenBagus-Research/2.0"))

        req_headers = {"User-Agent": user_agent, "Accept": "application/json"}
        if headers:
            req_headers.update(headers)

        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(source_url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=timeout, context=self.ssl_context) as resp:
                    raw_data = resp.read().decode("utf-8", errors="replace")
                    return {
                        "ok": True,
                        "payload": json.loads(raw_data),
                        "source_name": source_name,
                        "provider": provider,
                        "asset_class": asset_class,
                        "country": country,
                        "source_url": source_url,
                        "error": None,
                    }
            except Exception as e:
                last_error = _short_error(e)
                if attempt < max_retries:
                    time.sleep(backoff * (attempt + 1))

        return {
            "ok": False,
            "payload": None,
            "source_name": source_name,
            "provider": provider,
            "asset_class": asset_class,
            "country": country,
            "source_url": source_url,
            "error": last_error,
        }

    def _fetch_crypto_asset(self, asset: str) -> None:
        asset_cfg = self.source_config.get("core_assets", {}).get("crypto", {}).get(asset)
        if not asset_cfg:
            return

        template = self.source_config.get("source_templates", {}).get("binance_24hr", {})
        urls = [template.get("url", "https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}")]
        urls.extend(template.get("fallback_urls", []))
        symbol = asset_cfg["binance_symbol"]

        for url_tmpl in urls:
            source_url = url_tmpl.format(symbol=urllib.parse.quote(symbol, safe=""))
            fetch = self._fetch_json(
                source_name=f"binance_24hr_{symbol}",
                provider=template.get("provider", "binance_public"),
                asset_class="crypto_market",
                country=asset_cfg.get("country", "GLOBAL"),
                source_url=source_url,
            )
            if fetch["ok"] and isinstance(fetch["payload"], dict):
                row = self._crypto_row_from_binance(asset, asset_cfg, template, source_url, fetch["payload"])
                if row:
                    self.market_rows.append(row)
                    self.source_health.append({
                        "source_name": row["source_name"],
                        "provider": row["provider"],
                        "asset_class": "crypto_market",
                        "country": row["country"],
                        "status": row["status"],
                        "reason": f"freshness: {row['freshness_status']}",
                        "source_url": source_url,
                        "rows_returned": 1,
                        "checked_at_utc": self.fetched_at_utc,
                    })
                    return

        # Binance failed, try CoinGecko fallback
        self._fetch_crypto_from_coingecko(asset, asset_cfg)

    def _crypto_row_from_binance(
        self,
        asset: str,
        asset_cfg: dict[str, Any],
        template: dict[str, Any],
        source_url: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        price = _safe_float(payload.get("lastPrice"))
        observed_at = _from_epoch_millis(payload.get("closeTime"))
        if price is None or observed_at is None:
            return None

        freshness = self._freshness("crypto_market", observed_at)
        return {
            "run_id": self.run_id,
            "symbol": asset,
            "provider_symbol": asset_cfg["binance_symbol"],
            "asset_class": "crypto_market",
            "country": asset_cfg.get("country", "GLOBAL"),
            "currency": "USD",
            "provider": template.get("provider", "binance_public"),
            "source_name": f"binance_24hr_{asset_cfg['binance_symbol']}",
            "source_url": source_url,
            "source_ref": "Binance public 24hr ticker",
            "fetched_at_utc": self.fetched_at_utc,
            "observed_at_utc": observed_at,
            "freshness_minutes": freshness["minutes"],
            "freshness_status": freshness["status"],
            "confidence": template.get("source_quality", 0.90),
            "source_quality": template.get("source_quality", 0.90),
            "price": price,
            "open": _safe_float(payload.get("openPrice")),
            "high": _safe_float(payload.get("highPrice")),
            "low": _safe_float(payload.get("lowPrice")),
            "volume": _safe_float(payload.get("volume")),
            "quote_volume": _safe_float(payload.get("quoteVolume")),
            "status": "OK" if freshness["status"] != "STALE" else "WARNING",
            "extra": {
                "weighted_avg_price": _safe_float(payload.get("weightedAvgPrice")),
                "price_change": _safe_float(payload.get("priceChange")),
                "price_change_percent": _safe_float(payload.get("priceChangePercent")),
                "count": payload.get("count"),
            },
        }

    def _fetch_crypto_from_coingecko(self, asset: str, asset_cfg: dict[str, Any]) -> None:
        template = self.source_config.get("source_templates", {}).get("coingecko_simple", {})
        coin_id = asset_cfg.get("coingecko_id")
        if not coin_id:
            self.source_health.append({
                "source_name": f"coingecko_{asset}",
                "provider": "coingecko_public",
                "asset_class": "crypto_market",
                "country": "GLOBAL",
                "status": "FAIL",
                "reason": "Missing coingecko_id mapping",
                "source_url": "",
                "rows_returned": 0,
                "checked_at_utc": self.fetched_at_utc,
            })
            return

        source_url = template.get("url", "").format(id=urllib.parse.quote(coin_id, safe=""))
        fetch = self._fetch_json(
            source_name=f"coingecko_{coin_id}",
            provider=template.get("provider", "coingecko_public"),
            asset_class="crypto_market",
            country=asset_cfg.get("country", "GLOBAL"),
            source_url=source_url,
        )

        if fetch["ok"] and isinstance(fetch["payload"], dict) and coin_id in fetch["payload"]:
            cdata = fetch["payload"][coin_id]
            price = _safe_float(cdata.get("usd"))
            observed_at = _from_epoch_seconds(cdata.get("last_updated_at")) or self.fetched_at_utc
            if price is not None:
                freshness = self._freshness("crypto_market", observed_at)
                row = {
                    "run_id": self.run_id,
                    "symbol": asset,
                    "provider_symbol": coin_id,
                    "asset_class": "crypto_market",
                    "country": asset_cfg.get("country", "GLOBAL"),
                    "currency": "USD",
                    "provider": template.get("provider", "coingecko_public"),
                    "source_name": f"coingecko_{coin_id}",
                    "source_url": source_url,
                    "source_ref": "CoinGecko public simple price",
                    "fetched_at_utc": self.fetched_at_utc,
                    "observed_at_utc": observed_at,
                    "freshness_minutes": freshness["minutes"],
                    "freshness_status": freshness["status"],
                    "confidence": template.get("source_quality", 0.85),
                    "source_quality": template.get("source_quality", 0.85),
                    "price": price,
                    "volume": _safe_float(cdata.get("usd_24h_vol")),
                    "status": "OK" if freshness["status"] != "STALE" else "WARNING",
                    "extra": {
                        "price_change_24h": _safe_float(cdata.get("usd_24h_change")),
                    },
                }
                self.market_rows.append(row)
                self.source_health.append({
                    "source_name": row["source_name"],
                    "provider": row["provider"],
                    "asset_class": "crypto_market",
                    "country": row["country"],
                    "status": row["status"],
                    "reason": f"freshness: {row['freshness_status']}",
                    "source_url": source_url,
                    "rows_returned": 1,
                    "checked_at_utc": self.fetched_at_utc,
                })
                return

        self.source_health.append({
            "source_name": f"crypto_{asset}",
            "provider": "crypto_fallback",
            "asset_class": "crypto_market",
            "country": "GLOBAL",
            "status": "FAIL",
            "reason": fetch.get("error") or "All crypto sources exhausted",
            "source_url": source_url,
            "rows_returned": 0,
            "checked_at_utc": self.fetched_at_utc,
        })

    def _fetch_core_macro_market(self) -> None:
        macros = self.source_config.get("core_assets", {}).get("macro_market", {})
        template = self.source_config.get("source_templates", {}).get("yahoo_chart", {})

        for name, cfg in macros.items():
            symbol = cfg.get("yahoo_symbol")
            if not symbol:
                continue

            source_url = template.get("url", "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d").format(
                symbol=urllib.parse.quote(symbol, safe="")
            )
            fetch = self._fetch_json(
                source_name=f"yahoo_macro_{name}",
                provider="yahoo_finance_public",
                asset_class="macro_market",
                country=cfg.get("country", "US"),
                source_url=source_url,
            )

            if fetch["ok"] and isinstance(fetch["payload"], dict):
                result = fetch["payload"].get("chart", {}).get("result", [])
                if result and isinstance(result, list):
                    meta = result[0].get("meta", {})
                    price = _safe_float(meta.get("regularMarketPrice"))
                    ts = meta.get("regularMarketTime")
                    observed_at = _from_epoch_seconds(ts) or self.fetched_at_utc

                    if price is not None:
                        freshness = self._freshness("macro_indicators", observed_at)
                        self.macro_rows.append({
                            "run_id": self.run_id,
                            "symbol": name,
                            "indicator_code": name,
                            "indicator_name": cfg.get("description", name),
                            "country": cfg.get("country", "US"),
                            "asset_class": "macro_market",
                            "provider": "yahoo_finance_public",
                            "source_name": f"yahoo_{name}",
                            "source_url": source_url,
                            "fetched_at_utc": self.fetched_at_utc,
                            "observed_at_utc": observed_at,
                            "freshness_minutes": freshness["minutes"],
                            "freshness_status": freshness["status"],
                            "value": price,
                            "unit": cfg.get("unit", "INDEX"),
                            "status": "OK" if freshness["status"] != "STALE" else "WARNING",
                        })
                        self.source_health.append({
                            "source_name": f"yahoo_{name}",
                            "provider": "yahoo_finance_public",
                            "asset_class": "macro_market",
                            "country": cfg.get("country", "US"),
                            "status": "OK",
                            "reason": f"macro observation valid: {price}",
                            "source_url": source_url,
                            "rows_returned": 1,
                            "checked_at_utc": self.fetched_at_utc,
                        })
                        continue

            self.source_health.append({
                "source_name": f"macro_{name}",
                "provider": "yahoo_finance_public",
                "asset_class": "macro_market",
                "country": cfg.get("country", "US"),
                "status": "WARNING",
                "reason": fetch.get("error") or "Failed to fetch macro proxy",
                "source_url": source_url,
                "rows_returned": 0,
                "checked_at_utc": self.fetched_at_utc,
            })

    def _fetch_defillama_stablecoins(self) -> None:
        template = self.source_config.get("source_templates", {}).get("defillama_stablecoins", {})
        source_url = template.get("url", "https://stablecoins.llama.fi/stablecoins?includePrices=true")

        fetch = self._fetch_json(
            source_name="defillama_stablecoins",
            provider="defillama_public",
            asset_class="crypto_stablecoin_macro",
            country="GLOBAL",
            source_url=source_url,
        )

        if fetch["ok"] and isinstance(fetch["payload"], dict):
            pegged_assets = fetch["payload"].get("peggedAssets", [])
            total_mcap = 0.0
            for item in pegged_assets[:10]:
                circ = _safe_float(item.get("circulating", {}).get("peggedUSD"))
                if circ:
                    total_mcap += circ

            self.macro_rows.append({
                "run_id": self.run_id,
                "symbol": "TOTAL_STABLECOIN_MCAP",
                "indicator_code": "TOTAL_STABLECOIN_MCAP",
                "indicator_name": "Top-10 Stablecoin Total Market Cap",
                "country": "GLOBAL",
                "asset_class": "crypto_stablecoin_macro",
                "provider": "defillama_public",
                "source_name": "defillama_stablecoins",
                "source_url": source_url,
                "fetched_at_utc": self.fetched_at_utc,
                "observed_at_utc": self.fetched_at_utc,
                "freshness_minutes": 0.0,
                "freshness_status": "FRESH",
                "value": total_mcap,
                "unit": "USD",
                "status": "OK",
            })
            self.source_health.append({
                "source_name": "defillama_stablecoins",
                "provider": "defillama_public",
                "asset_class": "crypto_stablecoin_macro",
                "country": "GLOBAL",
                "status": "OK",
                "reason": f"Top-10 mcap aggregated: {total_mcap:,.0f} USD",
                "source_url": source_url,
                "rows_returned": 1,
                "checked_at_utc": self.fetched_at_utc,
            })
        else:
            self.source_health.append({
                "source_name": "defillama_stablecoins",
                "provider": "defillama_public",
                "asset_class": "crypto_stablecoin_macro",
                "country": "GLOBAL",
                "status": "WARNING",
                "reason": fetch.get("error") or "DefiLlama fetch returned no data",
                "source_url": source_url,
                "rows_returned": 0,
                "checked_at_utc": self.fetched_at_utc,
            })

    def _fetch_fred_if_available(self) -> None:
        api_key = os.environ.get("FRED_API_KEY")
        if not api_key:
            return  # optional key, skip silently

        template = self.source_config.get("source_templates", {}).get("fred_series", {})
        series_map = {"DGS10": "US10Y_FRED", "DTWEXBGS": "USD_NOMINAL_INDEX"}

        for series_id, indicator_code in series_map.items():
            source_url = template.get("url", "").format(series_id=series_id, api_key=api_key)
            fetch = self._fetch_json(
                source_name=f"fred_{series_id}",
                provider="fred_stlouisfed",
                asset_class="macro_official",
                country="US",
                source_url=source_url,
            )
            if fetch["ok"] and isinstance(fetch["payload"], dict):
                obs = fetch["payload"].get("observations", [])
                if obs:
                    latest = obs[-1]
                    val = _safe_float(latest.get("value"))
                    date_str = latest.get("date")
                    if val is not None:
                        self.macro_rows.append({
                            "run_id": self.run_id,
                            "symbol": indicator_code,
                            "indicator_code": indicator_code,
                            "indicator_name": f"FRED Official Series {series_id}",
                            "country": "US",
                            "asset_class": "macro_official",
                            "provider": "fred_stlouisfed",
                            "source_name": f"fred_{series_id}",
                            "source_url": source_url,
                            "fetched_at_utc": self.fetched_at_utc,
                            "observed_at_utc": f"{date_str}T00:00:00Z" if date_str else self.fetched_at_utc,
                            "freshness_minutes": 0.0,
                            "freshness_status": "FRESH",
                            "value": val,
                            "unit": "RATE" if "10" in series_id else "INDEX",
                            "status": "OK",
                        })

    def _freshness(self, category: str, observed_at_utc: str) -> dict[str, Any]:
        dt = _parse_iso(observed_at_utc)
        if not dt:
            return {"minutes": None, "status": "UNKNOWN"}

        age_mins = max(0.0, (_utc_now() - dt).total_seconds() / 60.0)
        policy = self.freshness_config.get("policies", {}).get(category, {})
        max_fresh = policy.get("max_fresh_age_minutes", 120)
        max_acceptable = policy.get("max_acceptable_age_minutes", 720)

        if age_mins <= max_fresh:
            status = "FRESH"
        elif age_mins <= max_acceptable:
            status = "LAGGING_WITHIN_MAX"
        else:
            status = "STALE"

        return {"minutes": round(age_mins, 2), "status": status}

    def _persist_duckdb(self, db_path: str | None = None) -> dict[str, Any]:
        """Optionally persists to DuckDB if available in python environment."""
        target_path = Path(db_path) if db_path else self.root / "data/processed/openbagus_runtime.duckdb"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import duckdb  # type: ignore
        except ImportError:
            return {
                "status": "SKIPPED",
                "reason": "duckdb package is not installed; continuing in file-based storage mode",
                "tables_written": [],
            }

        try:
            conn = duckdb.connect(str(target_path))
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_snapshots_runtime (
                    run_id VARCHAR,
                    symbol VARCHAR,
                    asset_class VARCHAR,
                    price DOUBLE,
                    volume DOUBLE,
                    observed_at_utc VARCHAR,
                    fetched_at_utc VARCHAR,
                    status VARCHAR
                )
            """)
            for row in self.market_rows:
                conn.execute(
                    "INSERT INTO market_snapshots_runtime VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        row.get("run_id"),
                        row.get("symbol"),
                        row.get("asset_class"),
                        row.get("price"),
                        row.get("volume"),
                        row.get("observed_at_utc"),
                        row.get("fetched_at_utc"),
                        row.get("status"),
                    ],
                )

            conn.execute("""
                CREATE TABLE IF NOT EXISTS macro_snapshots_runtime (
                    run_id VARCHAR,
                    symbol VARCHAR,
                    indicator_code VARCHAR,
                    value DOUBLE,
                    unit VARCHAR,
                    observed_at_utc VARCHAR,
                    status VARCHAR
                )
            """)
            for row in self.macro_rows:
                conn.execute(
                    "INSERT INTO macro_snapshots_runtime VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        row.get("run_id"),
                        row.get("symbol"),
                        row.get("indicator_code"),
                        row.get("value"),
                        row.get("unit"),
                        row.get("observed_at_utc"),
                        row.get("status"),
                    ],
                )
            conn.close()
            return {
                "status": "WRITTEN",
                "db_path": str(target_path),
                "tables_written": ["market_snapshots_runtime", "macro_snapshots_runtime"],
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "reason": f"Failed writing to DuckDB: {_short_error(e)}",
                "tables_written": [],
            }

    def _build_payload(
        self,
        mode: str,
        selected_assets: list[str],
        all_core: bool,
        duckdb_result: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "platform": "OpenBagus",
            "active_domain": "crypto",
            "mode": mode,
            "run_id": self.run_id,
            "generated_at_utc": self.fetched_at_utc,
            "selected_symbols": selected_assets,
            "all_core": all_core,
            "market_rows": self.market_rows,
            "macro_rows": self.macro_rows,
            "source_health": self.source_health,
            "warnings": self.warnings,
            "duckdb_runtime": duckdb_result,
        }

    def _write_reports(self, payload: dict[str, Any]) -> None:
        runtime_dir = self.root / "reports/runtime"
        raw_dir = self.root / "data/raw"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        latest_json = runtime_dir / "openbagus_real_data_snapshot_latest.json"
        with latest_json.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        # Raw backup with run_id
        run_json = raw_dir / f"ingestion_snapshot_{self.run_id}.json"
        with run_json.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        # Markdown report
        latest_md = runtime_dir / "openbagus_real_data_snapshot_latest.md"
        with latest_md.open("w", encoding="utf-8") as f:
            f.write(self._generate_markdown_report(payload))

    def _generate_markdown_report(self, payload: dict[str, Any]) -> str:
        lines = [
            "# OpenBagus Market & Macro Ingestion Snapshot",
            "",
            f"- Run ID: `{payload['run_id']}`",
            f"- Generated At (UTC): `{payload['generated_at_utc']}`",
            f"- Active Domain: `crypto`",
            f"- Mode: `{payload['mode']}`",
            "",
            "## Market Assets (Active Domain: Crypto)",
            "",
            "| Symbol | Price | Volume | Observed At (UTC) | Freshness | Status | Provider |",
            "| --- | ---: | ---: | --- | --- | --- | --- |",
        ]
        for row in payload.get("market_rows", []):
            vol_str = f"{row['volume']:,.2f}" if row.get("volume") is not None else "N/A"
            price_str = f"${row['price']:,.2f}" if row.get("price") is not None else "N/A"
            lines.append(
                f"| {row['symbol']} | {price_str} | {vol_str} | {row['observed_at_utc']} | "
                f"{row['freshness_status']} | {row['status']} | {row['provider']} |"
            )

        lines.extend([
            "",
            "## Shared Macro Overlay",
            "",
            "| Indicator | Value | Unit | Country | Observed At (UTC) | Status |",
            "| --- | ---: | --- | --- | --- | --- |",
        ])
        for row in payload.get("macro_rows", []):
            val = row.get("value")
            val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val)
            lines.append(
                f"| {row['indicator_code']} | {val_str} | {row.get('unit', '')} | {row.get('country', '')} | "
                f"{row.get('observed_at_utc', '')} | {row.get('status', '')} |"
            )

        lines.extend([
            "",
            "## Source Health & Reliability",
            "",
            "| Source | Status | Rows | Reason |",
            "| --- | --- | ---: | --- |",
        ])
        for h in payload.get("source_health", []):
            lines.append(f"| {h['source_name']} | {h['status']} | {h.get('rows_returned', 0)} | {h.get('reason', '')} |")

        if payload.get("warnings"):
            lines.extend(["", "## Warnings", ""])
            for w in payload["warnings"]:
                lines.append(f"- {w}")

        lines.append("")
        return "\n".join(lines)


def run_runtime_ingestion(
    *,
    mode: str = "real",
    assets: list[str] | None = None,
    idx_symbols: list[str] | None = None,
    all_core: bool = False,
    db_path: str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Convenience functional wrapper for RuntimeDataIngestion."""
    engine = RuntimeDataIngestion(repo_root=repo_root)
    return engine.run(
        mode=mode,
        assets=assets,
        idx_symbols=idx_symbols,
        all_core=all_core,
        db_path=db_path,
    )
