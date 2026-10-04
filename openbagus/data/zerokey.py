"""OpenBagus Zero-Key Market Data Engine.

Unified zero-key public market data adapters for centralized exchanges,
derivatives, DEX pools, sentiment, and asset discovery.

Supported sources:
- Binance Vision (Spot, Klines, Depth)
- Gate.io (Spot, Klines, Orderbook, Futures, Funding Rates)
- OKX (Spot, Funding)
- Bybit (Spot, Linear)
- KuCoin (Spot, Futures)
- Kraken (Spot)
- GeckoTerminal (DEX Pools, Liquidity, Price)
- Alternative.me (Crypto Fear & Greed)
- CoinLore (Asset Discovery & Metadata)
- CoinGecko (Public Derivatives & Fallback Tickers)
- DefiLlama (Stablecoin TVL & Liquidity)
"""

from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


class ZeroKeyMarketData:
    """Unified client for zero-key public crypto market and derivatives data."""

    def __init__(self, timeout: float = 3.0) -> None:
        self.timeout = timeout
        self._cache: dict[str, tuple[float, Any]] = {}
        self._ctx_default = ssl.create_default_context()
        self._ctx_unverified = ssl._create_unverified_context()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) OpenBagus/2.0",
            "Accept": "application/json, */*",
        }

    def _get_json(self, url: str, ttl_seconds: float = 15.0) -> Any | None:
        now = time.time()
        if url in self._cache:
            ts, cached_data = self._cache[url]
            if now - ts < ttl_seconds:
                return cached_data

        req = urllib.request.Request(url, headers=self.headers)
        for ctx in (self._ctx_default, self._ctx_unverified):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    data = json.loads(raw)
                    self._cache[url] = (now, data)
                    return data
            except ssl.SSLError:
                continue
            except (TimeoutError, socket.timeout, urllib.error.URLError, Exception):
                break
        return None

    # -------------------------------------------------------------
    # 1. SPOT MARKET DATA (Ticker & 24h Stats)
    # -------------------------------------------------------------
    def get_spot_ticker(self, symbol: str) -> dict[str, Any] | None:
        sym = symbol.upper().replace("/USD", "").replace("-USD", "").replace("USDT", "")

        # Fallback 1: Binance Vision
        b_data = self._get_json(f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={sym}USDT")
        if isinstance(b_data, dict) and "lastPrice" in b_data:
            price = _safe_float(b_data.get("lastPrice"))
            if price:
                return {
                    "symbol": sym,
                    "price": price,
                    "open": _safe_float(b_data.get("openPrice")),
                    "high": _safe_float(b_data.get("highPrice")),
                    "low": _safe_float(b_data.get("lowPrice")),
                    "volume": _safe_float(b_data.get("volume")),
                    "quote_volume": _safe_float(b_data.get("quoteVolume")),
                    "pct_change": _safe_float(b_data.get("priceChangePercent")),
                    "bid": _safe_float(b_data.get("bidPrice")),
                    "ask": _safe_float(b_data.get("askPrice")),
                    "provider": "Binance Vision (Public)",
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }

        # Fallback 2: Gate.io Spot
        g_data = self._get_json(f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={sym}_USDT")
        if isinstance(g_data, list) and len(g_data) > 0 and isinstance(g_data[0], dict):
            row = g_data[0]
            price = _safe_float(row.get("last"))
            if price:
                return {
                    "symbol": sym,
                    "price": price,
                    "open": None,
                    "high": _safe_float(row.get("high_24h")),
                    "low": _safe_float(row.get("low_24h")),
                    "volume": _safe_float(row.get("base_volume")),
                    "quote_volume": _safe_float(row.get("quote_volume")),
                    "pct_change": _safe_float(row.get("change_percentage")),
                    "bid": _safe_float(row.get("highest_bid")),
                    "ask": _safe_float(row.get("lowest_ask")),
                    "provider": "Gate.io (Public)",
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }

        # Fallback 3: Bybit Spot
        by_data = self._get_json(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={sym}USDT")
        if isinstance(by_data, dict) and by_data.get("result", {}).get("list"):
            row = by_data["result"]["list"][0]
            price = _safe_float(row.get("lastPrice"))
            if price:
                return {
                    "symbol": sym,
                    "price": price,
                    "open": None,
                    "high": _safe_float(row.get("highPrice24h")),
                    "low": _safe_float(row.get("lowPrice24h")),
                    "volume": _safe_float(row.get("volume24h")),
                    "quote_volume": _safe_float(row.get("turnover24h")),
                    "pct_change": _safe_float(row.get("price24hPcnt")),
                    "bid": _safe_float(row.get("bid1Price")),
                    "ask": _safe_float(row.get("ask1Price")),
                    "provider": "Bybit (Public)",
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }

        # Fallback 4: OKX Spot
        ok_data = self._get_json(f"https://www.okx.com/api/v5/market/ticker?instId={sym}-USDT")
        if isinstance(ok_data, dict) and ok_data.get("data"):
            row = ok_data["data"][0]
            price = _safe_float(row.get("last"))
            if price:
                return {
                    "symbol": sym,
                    "price": price,
                    "open": _safe_float(row.get("open24h")),
                    "high": _safe_float(row.get("high24h")),
                    "low": _safe_float(row.get("low24h")),
                    "volume": _safe_float(row.get("vol24h")),
                    "quote_volume": _safe_float(row.get("volCcy24h")),
                    "pct_change": None,
                    "bid": _safe_float(row.get("bidPx")),
                    "ask": _safe_float(row.get("askPx")),
                    "provider": "OKX (Public)",
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }

        # Fallback 5: CoinGecko Simple Price
        cg_data = self._get_json(f"https://api.coingecko.com/api/v3/simple/price?ids={sym.lower()}&vs_currencies=usd&include_24hr_vol=true&include_24hr_change=true")
        if isinstance(cg_data, dict) and sym.lower() in cg_data:
            c = cg_data[sym.lower()]
            price = _safe_float(c.get("usd"))
            if price:
                return {
                    "symbol": sym,
                    "price": price,
                    "open": None,
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "volume": _safe_float(c.get("usd_24h_vol")),
                    "quote_volume": _safe_float(c.get("usd_24h_vol")),
                    "pct_change": _safe_float(c.get("usd_24h_change")),
                    "bid": None,
                    "ask": None,
                    "provider": "CoinGecko (Public)",
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }

        # Fallback 6: CoinLore
        cl_coins = self.search_coinlore(sym)
        if cl_coins:
            top = cl_coins[0]
            price = _safe_float(top.get("price_usd"))
            if price:
                return {
                    "symbol": sym,
                    "price": price,
                    "open": None,
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "volume": _safe_float(top.get("volume24")),
                    "quote_volume": _safe_float(top.get("volume24")),
                    "pct_change": _safe_float(top.get("percent_change_24h")),
                    "bid": None,
                    "ask": None,
                    "provider": "CoinLore (Public)",
                    "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }

        return None

    # -------------------------------------------------------------
    # 2. MULTI-TIMEFRAME CANDLESTICKS (Klines)
    # -------------------------------------------------------------
    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 50) -> list[dict[str, Any]]:
        sym = symbol.upper().replace("/USD", "").replace("-USD", "").replace("USDT", "")

        # Fallback 1: Binance Vision Klines
        b_url = f"https://data-api.binance.vision/api/v3/klines?symbol={sym}USDT&interval={interval}&limit={limit}"
        b_data = self._get_json(b_url, ttl_seconds=30.0)
        if isinstance(b_data, list) and len(b_data) > 0 and isinstance(b_data[0], list):
            candles = []
            for item in b_data:
                candles.append({
                    "time": int(item[0]),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5]),
                })
            return candles

        # Fallback 2: Gate.io Spot Candlesticks
        # Gate interval formats: 1h, 4h, 1d
        g_url = f"https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={sym}_USDT&interval={interval}&limit={limit}"
        g_data = self._get_json(g_url, ttl_seconds=30.0)
        if isinstance(g_data, list) and len(g_data) > 0 and isinstance(g_data[0], list):
            candles = []
            for item in g_data:
                # Gate format: [timestamp, volume, close, high, low, open]
                candles.append({
                    "time": int(item[0]) * 1000 if int(item[0]) < 10000000000 else int(item[0]),
                    "volume": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "open": float(item[5]),
                })
            return candles

        return []

    # -------------------------------------------------------------
    # 3. DERIVATIVES & PERPETUALS (Funding Rate, OI, Basis)
    # -------------------------------------------------------------
    def get_derivatives(self, symbol: str) -> dict[str, Any] | None:
        sym = symbol.upper().replace("/USD", "").replace("-USD", "").replace("USDT", "")

        # Fallback 1: Gate.io Futures (USDT perpetuals)
        g_url = f"https://api.gateio.ws/api/v4/futures/usdt/tickers?contract={sym}_USDT"
        g_data = self._get_json(g_url, ttl_seconds=15.0)
        if isinstance(g_data, list) and len(g_data) > 0 and isinstance(g_data[0], dict):
            row = g_data[0]
            mark_price = _safe_float(row.get("mark_price"))
            index_price = _safe_float(row.get("index_price"))
            funding_rate = _safe_float(row.get("funding_rate"))
            open_interest = _safe_float(row.get("total_size"))
            volume_24h = _safe_float(row.get("volume_24h_settle")) or _safe_float(row.get("volume_24h"))
            basis = (mark_price - index_price) if (mark_price and index_price) else 0.0

            # Fetch funding history for z-score calculation
            hist_url = f"https://api.gateio.ws/api/v4/futures/usdt/funding_rate?contract={sym}_USDT&limit=10"
            hist_data = self._get_json(hist_url, ttl_seconds=60.0)
            rates: list[float] = []
            if isinstance(hist_data, list):
                for h in hist_data:
                    rf = _safe_float(h.get("r"))
                    if rf is not None:
                        rates.append(rf)

            zscore = 0.0
            if len(rates) >= 3 and funding_rate is not None:
                mean = sum(rates) / len(rates)
                var = sum((r - mean) ** 2 for r in rates) / len(rates)
                std = var ** 0.5
                if std > 1e-8:
                    zscore = (funding_rate - mean) / std

            return {
                "symbol": sym,
                "contract": f"{sym}_USDT",
                "mark_price": mark_price,
                "index_price": index_price,
                "perpetual_price": _safe_float(row.get("last")),
                "funding_rate": funding_rate or 0.0,
                "funding_history": rates,
                "funding_zscore": round(zscore, 2),
                "open_interest": open_interest or 0.0,
                "volume_24h": volume_24h or 0.0,
                "basis": basis,
                "spread": _safe_float(row.get("lowest_ask")) - _safe_float(row.get("highest_bid")) if (row.get("lowest_ask") and row.get("highest_bid")) else 0.0,
                "provider": "Gate.io Futures (Public)",
            }

        # Fallback 2: CoinGecko Public Derivatives
        cg_data = self._get_json("https://api.coingecko.com/api/v3/derivatives", ttl_seconds=30.0)
        if isinstance(cg_data, list):
            match = next((d for d in cg_data if d.get("symbol") == f"{sym}USDT" or d.get("index_id") == sym), None)
            if match:
                price = _safe_float(match.get("price"))
                idx = _safe_float(match.get("index"))
                funding = _safe_float(match.get("funding_rate")) or 0.0
                # CoinGecko funding is in percent or fractional
                return {
                    "symbol": sym,
                    "contract": match.get("symbol", f"{sym}USDT"),
                    "mark_price": price,
                    "index_price": idx,
                    "perpetual_price": price,
                    "funding_rate": funding / 100.0 if funding > 0.01 else funding,
                    "funding_history": [],
                    "funding_zscore": 0.0,
                    "open_interest": _safe_float(match.get("open_interest")) or 0.0,
                    "volume_24h": _safe_float(match.get("volume_24h")) or 0.0,
                    "basis": _safe_float(match.get("basis")) or 0.0,
                    "spread": _safe_float(match.get("spread")) or 0.01,
                    "provider": f"{match.get('market', 'CoinGecko Derivatives')} (Public)",
                }

        return None

    # -------------------------------------------------------------
    # 4. ORDER BOOK & LIQUIDITY
    # -------------------------------------------------------------
    def get_orderbook(self, symbol: str, limit: int = 10) -> dict[str, Any] | None:
        sym = symbol.upper().replace("/USD", "").replace("-USD", "").replace("USDT", "")

        # Try Binance Vision Depth
        url = f"https://data-api.binance.vision/api/v3/depth?symbol={sym}USDT&limit={limit}"
        data = self._get_json(url, ttl_seconds=10.0)
        if isinstance(data, dict) and "bids" in data and "asks" in data:
            bids = [(_safe_float(b[0]), _safe_float(b[1])) for b in data["bids"] if len(b) >= 2]
            asks = [(_safe_float(a[0]), _safe_float(a[1])) for a in data["asks"] if len(a) >= 2]
            bid_vol = sum((p or 0.0) * (q or 0.0) for p, q in bids)
            ask_vol = sum((p or 0.0) * (q or 0.0) for p, q in asks)
            tot = bid_vol + ask_vol
            imbalance = ((bid_vol - ask_vol) / tot) if tot > 0 else 0.0
            return {
                "bids": bids,
                "asks": asks,
                "bid_depth_usd": bid_vol,
                "ask_depth_usd": ask_vol,
                "imbalance": round(imbalance, 3),
                "provider": "Binance Depth",
            }

        # Fallback to Gate.io Depth
        g_url = f"https://api.gateio.ws/api/v4/spot/order_book?currency_pair={sym}_USDT&limit={limit}"
        g_data = self._get_json(g_url, ttl_seconds=10.0)
        if isinstance(g_data, dict) and "bids" in g_data and "asks" in g_data:
            bids = [(_safe_float(b[0]), _safe_float(b[1])) for b in g_data["bids"] if len(b) >= 2]
            asks = [(_safe_float(a[0]), _safe_float(a[1])) for a in g_data["asks"] if len(a) >= 2]
            bid_vol = sum((p or 0.0) * (q or 0.0) for p, q in bids)
            ask_vol = sum((p or 0.0) * (q or 0.0) for p, q in asks)
            tot = bid_vol + ask_vol
            imbalance = ((bid_vol - ask_vol) / tot) if tot > 0 else 0.0
            return {
                "bids": bids,
                "asks": asks,
                "bid_depth_usd": bid_vol,
                "ask_depth_usd": ask_vol,
                "imbalance": round(imbalance, 3),
                "provider": "Gate.io Depth",
            }

        return None

    # -------------------------------------------------------------
    # 5. MARKET SENTIMENT & MACRO CONTEXT
    # -------------------------------------------------------------
    def get_sentiment(self) -> dict[str, Any]:
        data = self._get_json("https://api.alternative.me/fng/?limit=1", ttl_seconds=300.0)
        if isinstance(data, dict) and data.get("data"):
            row = data["data"][0]
            val = int(row.get("value", 50))
            cls = row.get("value_classification", "Neutral")
            return {"value": val, "classification": cls, "provider": "Alternative.me"}
        return {"value": 50, "classification": "Neutral", "provider": "Default"}

    def get_stablecoin_tvl(self) -> dict[str, Any] | None:
        data = self._get_json("https://stablecoins.llama.fi/stablecoins", ttl_seconds=600.0)
        if isinstance(data, dict) and "peggedAssets" in data:
            assets = data["peggedAssets"]
            tot_usd = sum(_safe_float(a.get("circulating", {}).get("peggedUSD")) or 0.0 for a in assets[:10])
            return {"total_stablecoin_mcap": tot_usd, "provider": "DefiLlama"}
        return None

    # -------------------------------------------------------------
    # 6. DEX POOL & ON-CHAIN ASSET RESOLUTION (GeckoTerminal)
    # -------------------------------------------------------------
    def get_dex_pool(self, query: str) -> dict[str, Any] | None:
        q = urllib.parse.quote(query.strip())
        url = f"https://api.geckoterminal.com/api/v2/search/pools?query={q}"
        data = self._get_json(url, ttl_seconds=120.0)
        if isinstance(data, dict) and data.get("data"):
            pools = data["data"]
            if pools:
                attr = pools[0].get("attributes", {})
                price = _safe_float(attr.get("base_token_price_usd"))
                res_usd = _safe_float(attr.get("reserve_in_usd"))
                vol_24h = _safe_float(attr.get("volume_usd", {}).get("h24"))
                if price:
                    return {
                        "name": attr.get("name", query),
                        "price_usd": price,
                        "liquidity_usd": res_usd or 0.0,
                        "volume_24h": vol_24h or 0.0,
                        "pool_address": attr.get("address", ""),
                        "provider": "GeckoTerminal DEX",
                    }
        return None

    # -------------------------------------------------------------
    # 7. ASSET DISCOVERY (CoinLore)
    # -------------------------------------------------------------
    def search_coinlore(self, query: str) -> list[dict[str, Any]]:
        # Fetch top 100 tickers from CoinLore
        data = self._get_json("https://api.coinlore.net/api/tickers/?start=0&limit=100", ttl_seconds=300.0)
        results = []
        if isinstance(data, dict) and "data" in data:
            ql = query.strip().lower()
            for c in data["data"]:
                sym = str(c.get("symbol", "")).lower()
                name = str(c.get("name", "")).lower()
                if ql == sym or ql == name or ql in sym or ql in name:
                    results.append(c)
        return results
