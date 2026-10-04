"""OpenBagus Multi-Provider Registry and Health Monitor.

Tracks public and authenticated data providers, credential requirements,
and capability matrices across crypto, macro, onchain, and alternative data.
"""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import RuntimeEnv, get_repo_root

VALID_KEY_STATES = (
    "MISSING",
    "UNVERIFIED",
    "VALID",
    "INVALID",
    "RATE_LIMITED",
    "UNREACHABLE",
    "UNSUPPORTED",
)

ENHANCED_PROVIDER_TARGET = 12


@dataclass
class ProviderSpec:
    id: str
    display_name: str
    capabilities: list[str]
    credential_env_names: list[str] = field(default_factory=list)
    credential_required: bool = True
    public_access: bool = False
    ping_url: str | None = None
    notes: str = ""

    def is_configured(self, env: RuntimeEnv | Mapping[str, str] | None = None) -> bool:
        if self.public_access and not self.credential_required:
            return True
        for name in self.credential_env_names:
            if env:
                val = env.get(name) if hasattr(env, "get") else env.get(name)
            else:
                val = os.environ.get(name)
            if val and str(val).strip():
                return True
        return False


# Canonical Provider Definitions
PROVIDERS: list[ProviderSpec] = [
    # Zero-Key Centralized Spot Market Providers
    ProviderSpec(
        id="binance",
        display_name="Binance Public Market Data",
        capabilities=["crypto_price", "crypto_market", "crypto_history", "crypto_orderbook"],
        credential_env_names=["BINANCE_API_KEY"],
        credential_required=False,
        public_access=True,
        ping_url="https://data-api.binance.vision/api/v3/ping",
        notes="Primary public crypto exchange source (no key required for public ticker/orderbook).",
    ),
    ProviderSpec(
        id="gate",
        display_name="Gate.io Public Market Data",
        capabilities=["crypto_price", "crypto_market", "crypto_orderbook", "crypto_history"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.gateio.ws/api/v4/spot/time",
        notes="Zero-key spot market ticker, order book, and candlestick feed.",
    ),
    ProviderSpec(
        id="okx",
        display_name="OKX Public Market Data",
        capabilities=["crypto_price", "crypto_market"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://www.okx.com/api/v5/public/time",
        notes="Zero-key public ticker and market data.",
    ),
    ProviderSpec(
        id="bybit",
        display_name="Bybit Public Market Data",
        capabilities=["crypto_price", "crypto_market"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.bybit.com/v5/market/time",
        notes="Zero-key spot and linear market ticker feed.",
    ),
    ProviderSpec(
        id="kucoin",
        display_name="KuCoin Public Market Data",
        capabilities=["crypto_price", "crypto_market"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.kucoin.com/api/v1/timestamp",
        notes="Zero-key spot orderbook and ticker feed.",
    ),
    ProviderSpec(
        id="kraken",
        display_name="Kraken Public Market Data",
        capabilities=["crypto_price", "crypto_market"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.kraken.com/0/public/Time",
        notes="Zero-key public ticker feed.",
    ),
    # Zero-Key Derivatives Providers
    ProviderSpec(
        id="gate_futures",
        display_name="Gate.io Public Derivatives",
        capabilities=["crypto_derivatives", "funding", "open_interest"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.gateio.ws/api/v4/futures/usdt/contracts/BTC_USDT",
        notes="Zero-key perpetual contracts, mark price, funding rates, and open interest.",
    ),
    ProviderSpec(
        id="okx_futures",
        display_name="OKX Public Derivatives",
        capabilities=["crypto_derivatives", "funding", "open_interest"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP",
        notes="Zero-key swap funding rates and open interest.",
    ),
    ProviderSpec(
        id="bybit_futures",
        display_name="Bybit Public Derivatives",
        capabilities=["crypto_derivatives", "funding", "open_interest"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT",
        notes="Zero-key linear perpetual tickers, funding, and open interest.",
    ),
    ProviderSpec(
        id="kucoin_futures",
        display_name="KuCoin Public Derivatives",
        capabilities=["crypto_derivatives", "funding", "open_interest"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api-futures.kucoin.com/api/v1/contracts/active",
        notes="Zero-key futures contracts and funding rates.",
    ),
    # Zero-Key DEX, DeFi, Sentiment, Discovery & Aggregators
    ProviderSpec(
        id="geckoterminal",
        display_name="GeckoTerminal DEX Discovery",
        capabilities=["dex_discovery", "dex_liquidity", "crypto_price"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.geckoterminal.com/api/v2/networks",
        notes="Zero-key on-chain DEX pool discovery, liquidity reserves, and pool volume.",
    ),
    ProviderSpec(
        id="defillama",
        display_name="DefiLlama Public API",
        capabilities=["crypto_liquidity", "crypto_onchain", "stablecoin_tvl"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://stablecoins.llama.fi/stablecoins",
        notes="DeFi liquidity, stablecoin market cap, and TVL metrics.",
    ),
    ProviderSpec(
        id="alternative_me",
        display_name="Alternative.me Fear & Greed",
        capabilities=["sentiment", "market_sentiment"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.alternative.me/fng/?limit=1",
        notes="Zero-key crypto market sentiment and fear/greed regime indicator.",
    ),
    ProviderSpec(
        id="coinlore",
        display_name="CoinLore Asset Discovery",
        capabilities=["crypto_discovery", "crypto_metadata"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://api.coinlore.net/api/global/",
        notes="Zero-key global crypto asset universe and broad discovery metadata.",
    ),
    ProviderSpec(
        id="coingecko",
        display_name="CoinGecko",
        capabilities=["crypto_price", "crypto_market", "crypto_metadata", "crypto_history", "crypto_derivatives"],
        credential_env_names=["COINGECKO_API_KEY"],
        credential_required=False,
        public_access=True,
        ping_url="https://api.coingecko.com/api/v3/ping",
        notes="Comprehensive crypto metadata, public derivatives, and fallback pricing.",
    ),
    ProviderSpec(
        id="yahoo_finance",
        display_name="Yahoo Finance Public Proxy",
        capabilities=["macro", "crypto_proxy", "market_or_macro_proxy"],
        credential_env_names=[],
        credential_required=False,
        public_access=True,
        ping_url="https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=1d&interval=1d",
        notes="Public macro proxy for yields, VIX, commodities, and index charts.",
    ),
    # User-Declared & Supported Optional Providers
    ProviderSpec(
        id="fred",
        display_name="FRED (Federal Reserve Economic Data)",
        capabilities=["macro", "economic"],
        credential_env_names=["FRED_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Official US Federal Reserve interest rates, inflation, and money supply.",
    ),
    ProviderSpec(
        id="alpha_vantage",
        display_name="Alpha Vantage",
        capabilities=["macro", "crypto_price", "crypto_history", "forex"],
        credential_env_names=["ALPHAVANTAGE_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Global financial data and digital currency historical series.",
    ),
    ProviderSpec(
        id="coinmarketcap",
        display_name="CoinMarketCap",
        capabilities=["crypto_price", "crypto_market", "crypto_metadata"],
        credential_env_names=["COINMARKETCAP_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Crypto market rankings, listings, and global metrics.",
    ),
    ProviderSpec(
        id="cryptocompare",
        display_name="CryptoCompare",
        capabilities=["crypto_price", "crypto_history", "crypto_market"],
        credential_env_names=["CRYPTOCOMPARE_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Aggregated multi-exchange crypto pricing and historical daily bars.",
    ),
    ProviderSpec(
        id="finnhub",
        display_name="Finnhub",
        capabilities=["crypto_market", "crypto_price", "sentiment"],
        credential_env_names=["FINNHUB_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Real-time market feeds and institutional market sentiment.",
    ),
    ProviderSpec(
        id="fmp",
        display_name="Financial Modeling Prep (FMP)",
        capabilities=["macro", "economic", "crypto_price"],
        credential_env_names=["FMP_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Economic calendars, macro indicators, and crypto market prices.",
    ),
    ProviderSpec(
        id="twelve_data",
        display_name="Twelve Data",
        capabilities=["crypto_price", "crypto_history", "forex"],
        credential_env_names=["TWELVE_DATA_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Technical indicators and multi-asset time-series data.",
    ),
    ProviderSpec(
        id="polygon",
        display_name="Polygon.io",
        capabilities=["crypto_market", "crypto_price", "crypto_history"],
        credential_env_names=["POLYGON_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Institutional crypto market aggregates and tick feeds.",
    ),
    ProviderSpec(
        id="coinalyze",
        display_name="Coinalyze (Coin Analysis)",
        capabilities=["crypto_derivatives", "funding", "open_interest"],
        credential_env_names=["COINALYZE_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Crypto derivatives metrics, funding rates, liquidations, and open interest.",
    ),
    ProviderSpec(
        id="bitquery",
        display_name="Bitquery",
        capabilities=["crypto_onchain", "dex_trades"],
        credential_env_names=["BITQUERY_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Multi-chain DEX trading flows and on-chain blockchain intelligence.",
    ),
    ProviderSpec(
        id="thegraph",
        display_name="The Graph",
        capabilities=["crypto_onchain", "subgraphs"],
        credential_env_names=["THEGRAPH_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Decentralized protocol subgraphs and smart contract indexing.",
    ),
    ProviderSpec(
        id="tiingo",
        display_name="Tiingo",
        capabilities=["crypto_price", "crypto_history", "news"],
        credential_env_names=["TIINGO_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Crypto pricing and curated financial news streams.",
    ),
    ProviderSpec(
        id="stockdata",
        display_name="StockData.org",
        capabilities=["market_data", "crypto_price"],
        credential_env_names=["STOCKDATA_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Global market and crypto price feeds.",
    ),
    ProviderSpec(
        id="eia",
        display_name="EIA (U.S. Energy Information Administration)",
        capabilities=["energy", "macro", "commodities"],
        credential_env_names=["EIA_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Energy commodity series (crude oil, natural gas, power grid metrics).",
    ),
    ProviderSpec(
        id="bea",
        display_name="BEA (Bureau of Economic Analysis)",
        capabilities=["economic", "macro"],
        credential_env_names=["BEA_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="US GDP, personal consumption expenditure (PCE), and trade balance accounts.",
    ),
    ProviderSpec(
        id="census",
        display_name="U.S. Census Bureau",
        capabilities=["economic", "demographics"],
        credential_env_names=["CENSUS_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Economic surveys and retail/trade monthly data.",
    ),
    ProviderSpec(
        id="un_comtrade",
        display_name="UN Comtrade",
        capabilities=["trade", "macro"],
        credential_env_names=["UN_COMTRADE_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="United Nations global merchandise trade statistics.",
    ),
    ProviderSpec(
        id="companies_house",
        display_name="Companies House / OpenCorporates",
        capabilities=["fundamental", "entity"],
        credential_env_names=["COMPANIES_HOUSE_API_KEY", "OPENCORPORATES_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Corporate registry, entity verification, and legal structure data.",
    ),
    ProviderSpec(
        id="openalex",
        display_name="OpenAlex",
        capabilities=["research", "scholarly"],
        credential_env_names=["OPENALEX_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="Scholarly literature index, scientific research, and academic graph.",
    ),
    # Unmapped / Reserved User Providers
    ProviderSpec(
        id="mass_sse",
        display_name="Mass SSE",
        capabilities=["UNMAPPED"],
        credential_env_names=["MASS_SSE_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="User-declared provider (unmapped slot; pending user endpoint specification).",
    ),
    ProviderSpec(
        id="pls",
        display_name="PLS",
        capabilities=["UNMAPPED"],
        credential_env_names=["PLS_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="User-declared provider (unmapped slot; pending user endpoint specification).",
    ),
    ProviderSpec(
        id="openvici",
        display_name="OpenVICI",
        capabilities=["UNMAPPED"],
        credential_env_names=["OPENVICI_API_KEY"],
        credential_required=True,
        public_access=False,
        notes="User-declared provider (unmapped slot; pending user endpoint specification).",
    ),
]


def validate_fred(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "MISSING"
    url = f"https://api.stlouisfed.org/fred/series?series_id=GNPCA&api_key={urllib.parse.quote(k)}&file_type=json"
    headers = {"User-Agent": "OpenBagus-Research", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return "VALID" if "seriess" in data else "INVALID"
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return "RATE_LIMITED"
        if exc.code in {400, 401, 403}:
            return "INVALID"
        return "INVALID"
    except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError, OSError):
        return "UNREACHABLE"
    except Exception:
        return "INVALID"


def validate_alpha_vantage(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "MISSING"
    if not re.fullmatch(r"[A-Za-z0-9]{8,32}", k) or k.lower() == "demo":
        return "INVALID"
    url = f"https://www.alphavantage.co/query?function=INCOME_STATEMENT&symbol=NVDA&apikey={urllib.parse.quote(k)}"
    headers = {"User-Agent": "OpenBagus-Research", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if "Error Message" in data or "The **demo** API key" in str(data):
                return "INVALID"
            if "Information" in data:
                info = str(data["Information"]).lower()
                if "rate limit" in info or "frequency" in info:
                    return "RATE_LIMITED"
                if "invalid" in info:
                    return "INVALID"
            reports = data.get("annualReports")
            if isinstance(reports, list) and len(reports) > 0:
                latest = reports[0].get("fiscalDateEnding", "")
                if latest >= "2020":
                    return "VALID"
                return "INVALID"
            return "VALID" if "annualReports" in data or "symbol" in data else "INVALID"
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return "RATE_LIMITED"
        if exc.code in {401, 403}:
            return "INVALID"
        return "INVALID"
    except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError, OSError):
        return "UNREACHABLE"
    except Exception:
        return "INVALID"


def validate_coinmarketcap(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "MISSING"
    url = "https://pro-api.coinmarketcap.com/v1/key/info"
    headers = {
        "X-CMC_PRO_API_KEY": k,
        "Accept": "application/json",
        "User-Agent": "OpenBagus-Research",
    }
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            status = data.get("status", {})
            err_code = status.get("error_code", 0)
            if err_code == 0:
                return "VALID"
            if err_code in {1001, 1002, 1003, 1004, 1005}:
                return "INVALID"
            if err_code == 1008:
                return "RATE_LIMITED"
            return "VALID" if resp.status == 200 else "INVALID"
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return "RATE_LIMITED"
        if exc.code in {401, 403}:
            return "INVALID"
        return "INVALID"
    except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError, OSError):
        return "UNREACHABLE"
    except Exception:
        return "INVALID"


def validate_cryptocompare(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "MISSING"
    url = f"https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=USD&api_key={urllib.parse.quote(k)}"
    headers = {"User-Agent": "OpenBagus-Research", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if "USD" in data:
                return "VALID"
            if data.get("Response") == "Error":
                msg = data.get("Message", "").lower()
                if "key" in msg or "auth" in msg or "credential" in msg:
                    return "INVALID"
                if "rate" in msg or "limit" in msg:
                    return "RATE_LIMITED"
            return "VALID" if resp.status == 200 else "INVALID"
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return "RATE_LIMITED"
        if exc.code in {401, 403}:
            return "INVALID"
        return "INVALID"
    except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError, OSError):
        return "UNREACHABLE"
    except Exception:
        return "INVALID"


def validate_coinalyze(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "MISSING"
    url = f"https://api.coinalyze.net/v1/future-markets?api_key={urllib.parse.quote(k)}"
    headers = {"User-Agent": "OpenBagus-Research", "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=5.0, context=ctx) as resp:
            if resp.status == 200:
                return "VALID"
            return "INVALID"
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return "RATE_LIMITED"
        if exc.code in {401, 403}:
            return "INVALID"
        return "INVALID"
    except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError, OSError):
        return "UNREACHABLE"
    except Exception:
        return "INVALID"


VALIDATORS = {
    "fred": validate_fred,
    "alpha_vantage": validate_alpha_vantage,
    "coinmarketcap": validate_coinmarketcap,
    "cryptocompare": validate_cryptocompare,
    "coinalyze": validate_coinalyze,
}

CAPABILITY_CATEGORIES = ("MARKET", "METADATA", "DERIVATIVES", "ONCHAIN", "DEFI", "MACRO")


def classify_provider_capability(p: ProviderSpec) -> str:
    caps = set(p.capabilities)
    if "dex_discovery" in caps or "dex_liquidity" in caps:
        return "DEX"
    if "sentiment" in caps or "market_sentiment" in caps:
        return "SENTIMENT"
    if "crypto_discovery" in caps:
        return "DISCOVERY"
    if "crypto_derivatives" in caps or "funding" in caps or "open_interest" in caps:
        return "DERIVATIVES"
    if "crypto_liquidity" in caps or "stablecoin_tvl" in caps or p.id == "defillama":
        return "DEFI"
    if "crypto_onchain" in caps or "dex_trades" in caps or "subgraphs" in caps:
        return "ONCHAIN"
    if any(c in caps for c in ("macro", "economic", "energy", "trade", "demographics")):
        return "MACRO"
    if "crypto_metadata" in caps and "crypto_price" not in caps:
        return "METADATA"
    return "MARKET"


class ProviderRegistry:
    """Central registry and health inspector for OpenBagus data providers."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.env = RuntimeEnv(self.root)
        self.providers: dict[str, ProviderSpec] = {p.id: p for p in PROVIDERS}
        from openbagus.data.http import SecureHttpClient
        self.http = SecureHttpClient(timeout=2.5)

    def get(self, provider_id: str) -> ProviderSpec | None:
        return self.providers.get(provider_id)

    def list_all(self) -> list[ProviderSpec]:
        return list(self.providers.values())

    def list_public(self) -> list[ProviderSpec]:
        return [p for p in self.providers.values() if p.public_access]

    def list_configured_apis(self) -> list[ProviderSpec]:
        return [p for p in self.providers.values() if not p.public_access and p.is_configured(self.env)]

    def list_missing_apis(self) -> list[ProviderSpec]:
        return [p for p in self.providers.values() if not p.public_access and not p.is_configured(self.env)]

    def get_key(self, provider_id: str) -> str | None:
        p = self.get(provider_id)
        if not p:
            return None
        for env_name in p.credential_env_names:
            val = self.env.get(env_name) if hasattr(self.env, "get") else os.environ.get(env_name)
            if val and str(val).strip():
                return str(val).strip()
        return None

    def validate_key(self, provider_id: str, key: str | None = None) -> str:
        """Validate API key for provider. Returns VALID, INVALID, RATE_LIMITED, UNREACHABLE, MISSING, UNSUPPORTED."""
        p = self.get(provider_id)
        if not p:
            return "UNSUPPORTED"
        if p.public_access:
            return "PUBLIC"
        val = key.strip() if key is not None else self.get_key(provider_id)
        if not val:
            return "MISSING"
        validator = VALIDATORS.get(provider_id)
        if not validator:
            return "UNSUPPORTED"
        return validator(val)

    def check_reachability(self, provider_id: str, timeout: float = 2.5) -> dict[str, Any]:
        p = self.get(provider_id)
        if not p or not p.ping_url:
            return {"provider": provider_id, "status": "NO_PING_URL", "latency_ms": None}

        _, status, elapsed_ms = self.http.fetch_raw(p.ping_url, timeout=timeout)
        lat = elapsed_ms if status == "REACHABLE" else None
        return {
            "provider": p.id,
            "display_name": p.display_name,
            "status": status,
            "latency_ms": lat,
        }

    def check_all_public(self, timeout: float = 2.5) -> list[dict[str, Any]]:
        results = []
        for p in self.list_public():
            res = self.check_reachability(p.id, timeout=timeout)
            results.append(res)
        return results

    def format_providers_view(self, run_live_check: bool = False) -> str:
        lines = []
        lines.append("OpenBagus Data Providers")
        lines.append("========================")
        lines.append("")
        lines.append("ZERO-KEY CORE (No API Key Required)")
        lines.append("-----------------------------------")

        live_health: dict[str, dict[str, Any]] = {}
        live_status: dict[str, str] = {}
        if run_live_check:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
                pub_futs = {ex.submit(self.check_reachability, p.id, 2.0): p.id for p in self.list_public() if p.ping_url}
                key_futs = {
                    ex.submit(self.validate_key, p.id, self.get_key(p.id)): p.id
                    for p in self.providers.values()
                    if not p.public_access and self.get_key(p.id)
                }
                for f in concurrent.futures.as_completed(pub_futs):
                    pid = pub_futs[f]
                    try:
                        live_health[pid] = f.result()
                    except Exception:
                        live_health[pid] = {"provider": pid, "status": "UNAVAILABLE", "latency_ms": None}
                for f in concurrent.futures.as_completed(key_futs):
                    pid = key_futs[f]
                    try:
                        live_status[pid] = f.result()
                    except Exception:
                        live_status[pid] = "INVALID"

        zero_key_order = ("MARKET", "DERIVATIVES", "DEX", "DEFI", "SENTIMENT", "DISCOVERY")
        public_providers = [p for p in self.providers.values() if p.public_access]

        for cat in zero_key_order:
            cat_providers = [p for p in public_providers if classify_provider_capability(p) == cat]
            if not cat_providers:
                continue
            lines.append(f"{cat}")
            for p in cat_providers:
                if run_live_check and p.ping_url:
                    health = live_health.get(p.id, {"status": "UNAVAILABLE", "latency_ms": None})
                    lat = f" ({health['latency_ms']}ms)" if health.get("latency_ms") else ""
                    lines.append(f"  {p.display_name:<30} {health['status']}{lat}")
                else:
                    lines.append(f"  {p.display_name:<30} PUBLIC")
            lines.append("")

        lines.append("OPTIONAL KEYED (Enhancement Providers)")
        lines.append("--------------------------------------")
        keyed_providers = [p for p in self.providers.values() if not p.public_access]
        keyed_order = ("DERIVATIVES", "ONCHAIN", "MACRO", "MARKET")

        for cat in keyed_order:
            cat_providers = [p for p in keyed_providers if classify_provider_capability(p) == cat]
            if not cat_providers:
                continue
            lines.append(f"{cat}")
            for p in cat_providers:
                k = self.get_key(p.id)
                if not k:
                    status = "MISSING"
                elif run_live_check:
                    status = live_status.get(p.id, "INVALID")
                else:
                    status = "UNVERIFIED" if p.id in VALIDATORS else "UNSUPPORTED"
                lines.append(f"  {p.display_name:<30} {status}")
            lines.append("")

        lines.append("Use '/providers --check' to run live reachability and credential checks.")
        lines.append("Use '/setup' to configure optional provider API keys.")
        return "\n".join(lines)
