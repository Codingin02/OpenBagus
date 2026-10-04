"""OpenBagus Crypto Asset Catalog and Taxonomy.

Maintains dynamic asset discovery, symbol/alias resolution, ambiguous selection,
and taxonomy classifications across DeFi, Layer 1/2/3, AI, Memecoins, RWA, etc.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root

TAXONOMY_CATEGORIES = [
    "Bitcoin",
    "Layer 1",
    "Layer 2",
    "Layer 3",
    "DeFi",
    "Memecoin",
    "Stablecoin",
    "RWA",
    "AI",
    "DePIN",
    "Gaming",
    "Oracle",
    "Privacy",
    "Exchange Token",
    "Payments",
    "Interoperability",
    "Liquid Staking",
    "Restaking",
    "NFT / Metaverse",
    "Infrastructure",
    "Other / Unknown",
]


@dataclass
class CryptoAsset:
    id: str
    symbol: str
    name: str
    aliases: list[str] = field(default_factory=list)
    binance_symbol: str = ""
    coingecko_id: str = ""
    yahoo_symbol: str = ""
    categories: list[str] = field(default_factory=lambda: ["Other / Unknown"])
    rank: int = 9999
    market_pair: str = ""
    chain: str = "Native"

    def matches(self, term: str) -> bool:
        norm = term.strip().lower()
        if not norm:
            return False
        if norm == self.symbol.lower():
            return True
        if norm == self.id.lower():
            return True
        if norm == self.name.lower():
            return True
        return norm in [a.lower() for a in self.aliases]


# Comprehensive seed catalog covering top assets and taxonomy groups
CORE_CATALOG: list[CryptoAsset] = [
    CryptoAsset("bitcoin", "BTC", "Bitcoin", ["btc", "bitcoin", "xbt"], "BTCUSDT", "bitcoin", "BTC-USD", ["Bitcoin", "Layer 1"], 1, "BTC/USD"),
    CryptoAsset("ethereum", "ETH", "Ethereum", ["eth", "ethereum", "ether"], "ETHUSDT", "ethereum", "ETH-USD", ["Layer 1", "Infrastructure"], 2, "ETH/USD"),
    CryptoAsset("tether", "USDT", "Tether USD", ["usdt", "tether"], "USDCUSDT", "tether", "USDT-USD", ["Stablecoin"], 3, "USDT/USD"),
    CryptoAsset("binancecoin", "BNB", "BNB", ["bnb", "binance coin"], "BNBUSDT", "binancecoin", "BNB-USD", ["Layer 1", "Exchange Token"], 4, "BNB/USD"),
    CryptoAsset("solana", "SOL", "Solana", ["sol", "solana"], "SOLUSDT", "solana", "SOL-USD", ["Layer 1", "DeFi"], 5, "SOL/USD"),
    CryptoAsset("usd-coin", "USDC", "USDC", ["usdc", "usd coin"], "USDCUSDT", "usd-coin", "USDC-USD", ["Stablecoin"], 6, "USDC/USD"),
    CryptoAsset("ripple", "XRP", "XRP", ["xrp", "ripple"], "XRPUSDT", "ripple", "XRP-USD", ["Payments", "Layer 1"], 7, "XRP/USD"),
    CryptoAsset("dogecoin", "DOGE", "Dogecoin", ["doge", "dogecoin"], "DOGEUSDT", "dogecoin", "DOGE-USD", ["Memecoin", "Payments"], 8, "DOGE/USD"),
    CryptoAsset("cardano", "ADA", "Cardano", ["ada", "cardano"], "ADAUSDT", "cardano", "ADA-USD", ["Layer 1"], 9, "ADA/USD"),
    CryptoAsset("avalanche-2", "AVAX", "Avalanche", ["avax", "avalanche"], "AVAXUSDT", "avalanche-2", "AVAX-USD", ["Layer 1", "DeFi"], 10, "AVAX/USD"),
    CryptoAsset("sui", "SUI", "Sui", ["sui"], "SUIUSDT", "sui", "SUI20947-USD", ["Layer 1"], 11, "SUI/USD"),
    CryptoAsset("shiba-inu", "SHIB", "Shiba Inu", ["shib", "shiba"], "SHIBUSDT", "shiba-inu", "SHIB-USD", ["Memecoin"], 12, "SHIB/USD"),
    CryptoAsset("chainlink", "LINK", "Chainlink", ["link", "chainlink"], "LINKUSDT", "chainlink", "LINK-USD", ["Oracle", "Infrastructure"], 13, "LINK/USD"),
    CryptoAsset("pepe", "PEPE", "Pepe", ["pepe", "pepecoin"], "PEPEUSDT", "pepe", "PEPE24478-USD", ["Memecoin"], 14, "PEPE/USD"),
    CryptoAsset("near", "NEAR", "NEAR Protocol", ["near"], "NEARUSDT", "near", "NEAR-USD", ["Layer 1", "AI"], 15, "NEAR/USD"),
    CryptoAsset("aptos", "APT", "Aptos", ["apt", "aptos"], "APTUSDT", "aptos", "APT21794-USD", ["Layer 1"], 16, "APT/USD"),
    CryptoAsset("polygon-ecosystem-token", "POL", "Polygon", ["pol", "matic", "polygon"], "POLUSDT", "polygon-ecosystem-token", "POL-USD", ["Layer 2", "Infrastructure"], 17, "POL/USD"),
    CryptoAsset("arbitrum", "ARB", "Arbitrum", ["arb", "arbitrum"], "ARBUSDT", "arbitrum", "ARB11841-USD", ["Layer 2"], 18, "ARB/USD"),
    CryptoAsset("optimism", "OP", "Optimism", ["op", "optimism"], "OPUSDT", "optimism", "OP-USD", ["Layer 2"], 19, "OP/USD"),
    CryptoAsset("starknet", "STRK", "Starknet", ["strk", "starknet"], "STRKUSDT", "starknet", "STRK-USD", ["Layer 2"], 20, "STRK/USD"),
    CryptoAsset("bittensor", "TAO", "Bittensor", ["tao", "bittensor"], "TAOUSDT", "bittensor", "TAO-USD", ["AI"], 21, "TAO/USD"),
    CryptoAsset("render-token", "RENDER", "Render", ["render", "rndr"], "RENDERUSDT", "render-token", "RENDER-USD", ["AI", "DePIN"], 22, "RENDER/USD"),
    CryptoAsset("fetch-ai", "FET", "Artificial Superintelligence Alliance", ["fet", "fetch", "asi"], "FETUSDT", "fetch-ai", "FET-USD", ["AI"], 23, "FET/USD"),
    CryptoAsset("aave", "AAVE", "Aave", ["aave"], "AAVEUSDT", "aave", "AAVE-USD", ["DeFi"], 24, "AAVE/USD"),
    CryptoAsset("uniswap", "UNI", "Uniswap", ["uni", "uniswap"], "UNIUSDT", "uniswap", "UNI7083-USD", ["DeFi"], 25, "UNI/USD"),
    CryptoAsset("maker", "MKR", "Maker", ["mkr", "maker", "sky"], "MKRUSDT", "maker", "MKR-USD", ["DeFi", "RWA"], 26, "MKR/USD"),
    CryptoAsset("pendle", "PENDLE", "Pendle", ["pendle"], "PENDLEUSDT", "pendle", "PENDLE-USD", ["DeFi"], 27, "PENDLE/USD"),
    CryptoAsset("ethena", "ENA", "Ethena", ["ena", "ethena"], "ENAUSDT", "ethena", "ENA-USD", ["DeFi", "Stablecoin"], 28, "ENA/USD"),
    CryptoAsset("ondo-finance", "ONDO", "Ondo", ["ondo"], "ONDOUSDT", "ondo-finance", "ONDO-USD", ["RWA", "DeFi"], 29, "ONDO/USD"),
    CryptoAsset("lido-dao", "LDO", "Lido DAO", ["ldo", "lido"], "LDOUSDT", "lido-dao", "LDO-USD", ["Liquid Staking", "DeFi"], 30, "LDO/USD"),
    CryptoAsset("kaspa", "KAS", "Kaspa", ["kas", "kaspa"], "KASUSDT", "kaspa", "KAS-USD", ["Layer 1"], 31, "KAS/USD"),
    CryptoAsset("sei-network", "SEI", "Sei", ["sei"], "SEIUSDT", "sei-network", "SEI-USD", ["Layer 1"], 32, "SEI/USD"),
    CryptoAsset("injective-protocol", "INJ", "Injective", ["inj", "injective"], "INJUSDT", "injective-protocol", "INJ-USD", ["DeFi", "Layer 1"], 33, "INJ/USD"),
    CryptoAsset("celestia", "TIA", "Celestia", ["tia", "celestia"], "TIAUSDT", "celestia", "TIA22861-USD", ["Infrastructure", "Modular"], 34, "TIA/USD"),
    CryptoAsset("dogwifhat", "WIF", "dogwifhat", ["wif", "dogwifhat"], "WIFUSDT", "dogwifcoin", "WIF-USD", ["Memecoin"], 35, "WIF/USD"),
    CryptoAsset("bonk", "BONK", "Bonk", ["bonk"], "BONKUSDT", "bonk", "BONK-USD", ["Memecoin"], 36, "BONK/USD"),
    CryptoAsset("floki", "FLOKI", "Floki", ["floki"], "FLOKIUSDT", "floki", "FLOKI-USD", ["Memecoin"], 37, "FLOKI/USD"),
    CryptoAsset("worldcoin-wld", "WLD", "Worldcoin", ["wld", "worldcoin"], "WLDUSDT", "worldcoin-wld", "WLD-USD", ["AI", "Identity"], 38, "WLD/USD"),
    CryptoAsset("jupiter-exchange-solana", "JUP", "Jupiter", ["jup", "jupiter"], "JUPUSDT", "jupiter-exchange-solana", "JUP-USD", ["DeFi"], 39, "JUP/USD"),
    CryptoAsset("monero", "XMR", "Monero", ["xmr", "monero"], "XMRUSDT", "monero", "XMR-USD", ["Privacy", "Payments"], 40, "XMR/USD"),
    CryptoAsset("cosmos", "ATOM", "Cosmos", ["atom", "cosmos"], "ATOMUSDT", "cosmos", "ATOM-USD", ["Interoperability", "Layer 1"], 41, "ATOM/USD"),
    CryptoAsset("polkadot", "DOT", "Polkadot", ["dot", "polkadot"], "DOTUSDT", "polkadot", "DOT-USD", ["Interoperability", "Layer 1"], 42, "DOT/USD"),
    CryptoAsset("thorchain", "RUNE", "THORChain", ["rune", "thorchain"], "RUNEUSDT", "thorchain", "RUNE-USD", ["Interoperability", "DeFi"], 43, "RUNE/USD"),
    CryptoAsset("filecoin", "FIL", "Filecoin", ["fil", "filecoin"], "FILUSDT", "filecoin", "FIL-USD", ["DePIN", "Infrastructure"], 44, "FIL/USD"),
    CryptoAsset("immutable-x", "IMX", "Immutable", ["imx", "immutable"], "IMXUSDT", "immutable-x", "IMX-USD", ["Gaming", "Layer 2"], 45, "IMX/USD"),
    # Ambiguous test case assets: Harmony (ONE) vs BigONE (ONE)
    CryptoAsset("harmony", "ONE", "Harmony", ["one", "harmony"], "ONEUSDT", "harmony", "ONE-USD", ["Layer 1"], 180, "ONE/USD"),
    CryptoAsset("bigone-token", "ONE", "BigONE Token", ["one", "bigone"], "", "bigone-token", "", ["Exchange Token"], 650, "ONE/USD"),
]


DEX_SLANG_EXCLUSIONS = {
    # Indonesian conversational slang / profanity / filler words
    "tolol", "wkwk", "wkwkwk", "kok", "aneh", "gimana", "nanti", "kenapa", "nggk", "nggak", "ga", "gak",
    "sih", "gitu", "gini", "bego", "bodoh", "anjing", "bangsat", "pantek", "kontol", "memek", "tai", "asu",
    "anjir", "anjrit", "kacau", "rusak", "parah", "jelek", "sampah", "busuk", "generik", "robot", "apa",
    "siapa", "dimana", "mana", "kapan", "bagaimana", "yah", "loh", "dong", "deh", "kan", "tuh", "lah",
    "harness", "hernes", "memory", "state", "jawabannya", "jawaban", "summarynya", "summary",
    # English conversational words
    "stupid", "idiot", "nonsense", "garbage", "trash", "terrible", "bad", "generic", "bot", "ai", "llm",
}


class CryptoAssetCatalog:
    """Manages searchable crypto asset universe, aliases, and category filtering."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.cache_path = self.root / "data/crypto_asset_catalog.json"
        self.assets: list[CryptoAsset] = []
        self._load()

    def _load(self) -> None:
        if self.cache_path.exists():
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self.assets = [CryptoAsset(**item) for item in data]
                return
            except Exception:
                pass
        self.assets = list(CORE_CATALOG)

    def save_cache(self) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            serializable = [asdict(a) for a in self.assets]
            self.cache_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        except Exception:
            pass

    def resolve_asset(self, term: str, is_explicit: bool = False) -> tuple[CryptoAsset | None, list[CryptoAsset]]:
        """Resolves term to a single asset, or returns candidates if ambiguous.

        Returns:
            (asset, []) if exactly one matched
            (None, [candidates]) if multiple matched (ambiguous)
            (None, []) if none matched
        """
        clean = term.strip()
        if not clean:
            return None, []

        clean_lower = clean.lower()
        if clean_lower in DEX_SLANG_EXCLUSIONS and not is_explicit:
            return None, []

        exact_symbol = [a for a in self.assets if a.symbol.lower() == clean_lower]
        if len(exact_symbol) == 1:
            return exact_symbol[0], []
        if len(exact_symbol) > 1:
            exact_symbol.sort(key=lambda x: x.rank)
            if all(a.symbol.upper() == exact_symbol[0].symbol.upper() for a in exact_symbol):
                return exact_symbol[0], []
            return None, exact_symbol

        # Try exact name / id / alias
        exact_name = [a for a in self.assets if a.name.lower() == clean_lower or a.id.lower() == clean_lower]
        if len(exact_name) == 1:
            return exact_name[0], []
        if len(exact_name) > 1:
            exact_name.sort(key=lambda x: x.rank)
            return exact_name[0], []

        # Try alias
        alias_matches = [a for a in self.assets if clean_lower in [al.lower() for al in a.aliases]]
        if len(alias_matches) == 1:
            return alias_matches[0], []
        if len(alias_matches) > 1:
            return None, alias_matches

        # Prefix search (require at least 2 characters to avoid single letter spurious matches)
        if len(clean_lower) >= 2:
            prefix_matches = [
                a for a in self.assets
                if a.symbol.lower().startswith(clean_lower) or a.name.lower().startswith(clean_lower)
            ]
            if len(prefix_matches) == 1:
                return prefix_matches[0], []
            if len(prefix_matches) > 1:
                # Sort by rank
                prefix_matches.sort(key=lambda x: x.rank)
                return None, prefix_matches[:5]

        # Online Discovery fallback (e.g. Manta, Kaspa, newly listed tokens)
        if len(clean_lower) >= 2:
            discovered = self.discover_online(clean)
            if discovered:
                # Check exact symbol in discovered
                exact_sym = [a for a in discovered if a.symbol.lower() == clean_lower]
                if len(exact_sym) == 1:
                    return exact_sym[0], []
                # Check exact name / alias in discovered
                exact_nm = [a for a in discovered if a.name.lower() == clean_lower or clean_lower in [al.lower() for al in a.aliases]]
                if len(exact_nm) == 1:
                    return exact_nm[0], []
                if len(discovered) == 1:
                    return discovered[0], []
                discovered.sort(key=lambda x: x.rank)
                return None, discovered[:5]

        return None, []

    def discover_online(self, term: str) -> list[CryptoAsset]:
        """Dynamically queries online metadata sources (CoinGecko / CoinLore / GeckoTerminal) to resolve unknown assets."""
        clean = term.strip()
        if len(clean) < 2:
            return []

        new_assets: list[CryptoAsset] = []

        url = f"https://api.coingecko.com/api/v3/search?query={urllib.parse.quote(clean)}"
        from openbagus.data.http import SecureHttpClient
        http = SecureHttpClient(timeout=3.5)
        data = http.get_json(url)
        if isinstance(data, dict):
            coins = data.get("coins", [])
            for c in coins[:5]:
                cid = c.get("id")
                sym = (c.get("symbol") or "").upper()
                name = c.get("name") or sym
                rank = c.get("market_cap_rank") or 9999
                if not sym or not cid:
                    continue
                existing = next((a for a in self.assets if a.symbol == sym and a.coingecko_id == cid), None)
                if existing:
                    new_assets.append(existing)
                else:
                    new_asset = CryptoAsset(
                        id=cid,
                        symbol=sym,
                        name=name,
                        aliases=[sym.lower(), name.lower(), cid],
                        binance_symbol=f"{sym}USDT",
                        coingecko_id=cid,
                        yahoo_symbol=f"{sym}-USD",
                        categories=["Other / Unknown"],
                        rank=rank,
                        market_pair=f"{sym}/USD",
                        chain="Native",
                    )
                    new_assets.append(new_asset)
                    self.assets.append(new_asset)
            if new_assets:
                self.save_cache()
                return new_assets

        # 2. Try CoinLore Search fallback
        try:
            from openbagus.data.zerokey import ZeroKeyMarketData

            zk = ZeroKeyMarketData(timeout=3.0)
            cl_results = zk.search_coinlore(clean)
            for c in cl_results[:5]:
                sym = str(c.get("symbol", "")).upper()
                name = str(c.get("name", sym))
                cid = str(c.get("nameid") or c.get("id") or sym.lower())
                rank = int(c.get("rank") or 9999)
                if not sym:
                    continue
                existing = next((a for a in self.assets if a.symbol == sym), None)
                if existing:
                    new_assets.append(existing)
                else:
                    new_asset = CryptoAsset(
                        id=cid,
                        symbol=sym,
                        name=name,
                        aliases=[sym.lower(), name.lower(), cid],
                        binance_symbol=f"{sym}USDT",
                        coingecko_id=cid,
                        yahoo_symbol=f"{sym}-USD",
                        categories=["Other / Unknown"],
                        rank=rank,
                        market_pair=f"{sym}/USD",
                        chain="Native",
                    )
                    new_assets.append(new_asset)
                    self.assets.append(new_asset)
            if new_assets:
                self.save_cache()
                return new_assets
        except Exception:
            pass

        # 3. Try GeckoTerminal DEX Pool fallback (for DEX-only tokens)
        try:
            from openbagus.data.zerokey import ZeroKeyMarketData

            zk = ZeroKeyMarketData(timeout=3.0)
            pool = zk.get_dex_pool(clean)
            if pool:
                pool_name = pool.get("name", clean.upper())
                sym = clean.upper()
                existing = next((a for a in self.assets if a.symbol == sym), None)
                if existing:
                    new_assets.append(existing)
                else:
                    new_asset = CryptoAsset(
                        id=clean.lower(),
                        symbol=sym,
                        name=pool_name,
                        aliases=[clean.lower(), pool_name.lower()],
                        binance_symbol=f"{sym}USDT",
                        coingecko_id=clean.lower(),
                        yahoo_symbol=f"{sym}-USD",
                        categories=["DEX Token"],
                        rank=9999,
                        market_pair=pool_name,
                        chain="DEX",
                    )
                    new_assets.append(new_asset)
                    self.assets.append(new_asset)
                    self.save_cache()
                    return new_assets
        except Exception:
            pass

        return new_assets

    def search_assets(self, query: str, limit: int = 10) -> list[CryptoAsset]:
        clean = query.strip().lower()
        if not clean:
            return sorted(self.assets, key=lambda x: x.rank)[:limit]

        matches = []
        for a in self.assets:
            if clean in a.symbol.lower() or clean in a.name.lower() or any(clean in al.lower() for al in a.aliases):
                matches.append(a)

        matches.sort(key=lambda x: (x.symbol.lower() != clean, x.rank))
        return matches[:limit]

    def get_category_assets(self, category_query: str, limit: int = 20) -> tuple[str, list[CryptoAsset]]:
        cq = category_query.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
        matched_cat = "Other / Unknown"

        for cat in TAXONOMY_CATEGORIES:
            norm = cat.lower().replace(" ", "").replace("_", "").replace("-", "")
            if cq == norm or cq in norm:
                matched_cat = cat
                break

        res = [a for a in self.assets if any(matched_cat.lower() in c.lower() for c in a.categories)]
        res.sort(key=lambda x: x.rank)
        return matched_cat, res[:limit]

    def get_all_categories(self) -> dict[str, int]:
        counts: dict[str, int] = {c: 0 for c in TAXONOMY_CATEGORIES}
        for a in self.assets:
            for cat in a.categories:
                for c in TAXONOMY_CATEGORIES:
                    if c.lower() in cat.lower():
                        counts[c] = counts.get(c, 0) + 1
        return {k: v for k, v in counts.items() if v > 0}
