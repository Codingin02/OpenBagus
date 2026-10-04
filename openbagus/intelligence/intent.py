"""OpenBagus Bilingual Natural-Language Intent Parser.

Converts user text into structured quantitative research requests using lightweight
bilingual (Indonesian + English) token analysis, difflib typo-tolerant vocabulary matching,
and token-aware asset recognition.

No local LLM. No cloud LLM.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.domains.crypto.catalog import CryptoAssetCatalog

ALLOWED_INTENTS = (
    "ANALYZE",
    "POSITION",
    "BUY_SPOT",
    "SELL_SPOT",
    "LONG_SHORT",
    "RISK",
    "STRUCTURE",
    "DIVERGENCE",
    "COMPARE",
    "FUNDING",
    "OPEN_INTEREST",
    "UNKNOWN",
)

CRYPTO_VOCAB_CANONICAL = {
    "position": ["positin", "posisi", "posisinya", "positioning", "postition", "positon", "open position", "setup"],
    "divergence": ["divergent", "divergen", "divergensi", "divergences", "div", "diverge"],
    "resistance": ["resistan", "resisten", "resist", "resistensi", "resitance"],
    "support": ["suport", "suprot", "supportnya", "suppot"],
    "leverage": ["leverag", "leveraj", "leverage-nya", "levrage"],
    "liquidation": ["likuidasi", "liquidasi", "liquidated"],
    "structure": ["struktur", "strukture", "structur"],
    "analysis": ["analisa", "analisis", "analize", "analyze", "review"],
    "compare": ["komparasi", "bandingkan", "vs", "versus"],
    "funding": ["fundin", "fundingrate", "fr"],
    "perpetual": ["perp", "perps", "futures", "futur"],
    "bitcoin": ["bitcon", "btcoin", "bitkoin"],
    "ethereum": ["etherium", "ethreum", "ethirium"],
    "solana": ["solanna", "solna"],
}

ACTION_STOP_WORDS = {
    "open", "position", "positin", "positioning", "posisi", "posisinya",
    "buy", "beli", "serok", "akumulasi", "sell", "jual",
    "long", "short", "leverage", "margin", "perp", "futures",
    "entry", "masuk", "dimana", "mana", "kapan", "sekarang", "now",
    "divergence", "divergent", "divergen", "divergensi",
    "support", "resistance", "snr", "pivot", "pivots", "structure", "struktur", "levels", "level",
    "risk", "resiko", "risiko", "drawdown", "sl", "tp",
    "gimana", "bagaimana", "review", "analyze", "analyse", "analisis", "view", "opinion",
    "ada", "apa", "apakah", "berapa", "bisa", "ini", "itu", "di", "pada", "ke", "dari", "dan", "atau",
    "v", "vs", "versus", "bandingkan", "compare", "with", "and", "or", "for", "of", "in", "is", "the", "a", "an", "to", "as", "at", "by", "if", "so", "do",
    "not", "no", "command", "can", "how", "what", "when", "where", "which", "who", "why", "tidak", "bukan", "jangan", "test",
    "enaknya", "bagusnya", "dong", "nih", "ya", "kan", "lah", "bang", "bro", "gan", "kak", "om",
    "target", "tp1", "tp2", "tp3", "take", "profit", "stop", "loss", "order",
}


@dataclass
class IntentRequest:
    intent: str  # One of ALLOWED_INTENTS
    asset: str | None = None
    asset_2: str | None = None
    target_assets: list[str] = field(default_factory=list)
    market: str = "all"  # "spot", "perpetual", "all"
    focus: str = "general"
    horizon: str | None = None
    needs_asset: bool = False
    clarification_prompt: str | None = None
    equity: float | None = None
    risk_pct: float | None = None
    needs_capital_inputs: bool = False
    raw_query: str = ""
    is_ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntentRouter:
    """Lightweight bilingual intent router and asset extractor."""

    def __init__(self, catalog: CryptoAssetCatalog | None = None, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.catalog = catalog or CryptoAssetCatalog(self.root)

    def parse(self, text: str) -> IntentRequest:
        cleaned = text.strip()
        if not cleaned:
            return IntentRequest(intent="UNKNOWN", raw_query=text)

        lower = cleaned.lower()
        words = re.findall(r"\b[A-Za-z0-9/]+\b", cleaned)

        # 1. Typo correction against curated crypto vocabulary using difflib
        vocab_keys = list(CRYPTO_VOCAB_CANONICAL.keys())
        clean_tokens: list[str] = []
        for w in words:
            wl = w.lower()
            # Direct mapping
            mapped = None
            for canon, typos in CRYPTO_VOCAB_CANONICAL.items():
                if wl in typos:
                    mapped = canon
                    break
            if not mapped:
                close = difflib.get_close_matches(wl, vocab_keys, n=1, cutoff=0.75)
                mapped = close[0] if close else w
            clean_tokens.append(mapped)

        norm_text = " ".join(clean_tokens).lower()

        # 2. Intent and Market Detection
        market = "all"
        focus = "general"

        # Compare detection: "BTC vs ETH", "btc V eth", "compare BTC and ETH"
        vs_match = re.search(r"\b([A-Za-z0-9]+)\s+(?:vs|versus|v|and|dan)\s+([A-Za-z0-9]+)\b", cleaned, re.IGNORECASE)
        is_compare = bool(vs_match) or "compare" in norm_text or "bandingkan" in norm_text or " vs " in f" {lower} "

        if is_compare:
            intent = "COMPARE"
            focus = "compare"
        elif any(k in norm_text for k in ["buy", "beli", "serok", "akumulasi", "spot buy"]):
            intent = "BUY_SPOT"
            market = "spot"
            focus = "spot"
        elif any(k in norm_text for k in ["sell", "jual", "cut loss", "exit spot"]):
            intent = "SELL_SPOT"
            market = "spot"
            focus = "spot"
        elif any(k in norm_text for k in [
            "long atau short", "long or short", "enaknya long apa short", "bagusnya long atau short",
            "enaknya long", "bagusnya long", "leverage", "perp", "perpetual", "futures",
        ]):
            intent = "LONG_SHORT"
            market = "perpetual"
            focus = "leverage" if "leverage" in norm_text else "long_short"
        elif any(k in norm_text for k in ["margin", "position size", "posisi size", "sizing", "modal berapa", "margin berapa", "size berapa"]):
            intent = "POSITION"
            market = "perpetual" if "margin" in norm_text else "all"
            focus = "capital"
        elif any(k in norm_text for k in ["position", "posisi", "posisinya", "entry", "entry dimana", "masuk dimana", "setup", "trade setup"]):
            intent = "POSITION"
            focus = "setup"
        elif "divergence" in norm_text or "divergent" in lower:
            intent = "DIVERGENCE"
            focus = "divergence"
        elif any(k in norm_text for k in ["support", "resistance", "snr", "s/r", "pivot", "structure", "struktur", "levels"]):
            intent = "STRUCTURE"
            focus = "structure"
        elif any(k in norm_text for k in ["risk", "resiko", "risiko", "drawdown", "volatility", "volatilitas", "stop loss"]):
            intent = "RISK"
            focus = "risk"
        elif any(k in norm_text for k in ["funding rate", "funding", "fr"]):
            intent = "FUNDING"
            focus = "funding"
            market = "perpetual"
        elif any(k in norm_text for k in ["open interest", "oi"]):
            intent = "OPEN_INTEREST"
            focus = "open_interest"
            market = "perpetual"
        elif any(k in norm_text for k in ["gimana", "bagaimana", "review", "analyze", "analisis", "pantau", "view", "opinion"]):
            intent = "ANALYZE"
            focus = "general"
        else:
            intent = "ANALYZE"

        # 3. Asset Resolution
        asset: str | None = None
        asset_2: str | None = None
        target_assets: list[str] = []

        # If comparison matched
        if intent == "COMPARE" and vs_match:
            c1, c2 = vs_match.group(1), vs_match.group(2)
            a1, _ = self.catalog.resolve_asset(c1)
            a2, _ = self.catalog.resolve_asset(c2)
            if a1 and a2:
                asset = a1.symbol
                asset_2 = a2.symbol
                target_assets = [a1.symbol, a2.symbol]

        # Check explicit preposition target: "di ADA", "di SOL", "pada BTC", "koin SOL"
        if not asset:
            prep_match = re.search(r"\b(?:di|pada|koin|coin|token)\s+([A-Za-z0-9]+)\b", cleaned, re.IGNORECASE)
            if prep_match:
                candidate = prep_match.group(1)
                a_obj, amb = self.catalog.resolve_asset(candidate)
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]

        # Check standalone query (e.g. query is literally "ADA", "ADA?", "BTC", "SOL", "Manta")
        if not asset:
            stripped_clean = cleaned.strip("? !.").upper()
            if stripped_clean == "ADA":
                asset = "ADA"
                target_assets = ["ADA"]
            elif len(words) == 1:
                a_obj, amb = self.catalog.resolve_asset(words[0])
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]
                elif amb:
                    return IntentRequest(
                        intent=intent,
                        market=market,
                        focus=focus,
                        is_ambiguous=True,
                        candidates=[a.symbol for a in amb],
                        raw_query=text,
                    )

        # Token scan excluding ACTION_STOP_WORDS and Indonesian grammar words
        if not asset:
            for orig_w, clean_w in zip(words, clean_tokens):
                orig_lower = orig_w.lower()
                clean_lower = clean_w.lower()
                if orig_lower in ACTION_STOP_WORDS or clean_lower in ACTION_STOP_WORDS:
                    continue
                # Special ADA protection: do not treat "ada" as Cardano ADA here
                if orig_lower == "ada":
                    continue
                a_obj, _ = self.catalog.resolve_asset(orig_w)
                if not a_obj:
                    a_obj, _ = self.catalog.resolve_asset(clean_w)
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]
                    break

        # 4. Check for clarification requirement (e.g. "ada divergence?")
        needs_asset = False
        clarification_prompt = None
        if not asset:
            if intent in ("DIVERGENCE", "POSITION", "STRUCTURE", "RISK", "LONG_SHORT", "BUY_SPOT", "SELL_SPOT", "FUNDING", "OPEN_INTEREST"):
                needs_asset = True
                clarification_prompt = "Which asset do you want to analyze?"
            else:
                return IntentRequest(intent="UNKNOWN", raw_query=text)

        # 5. Extract capital sizing inputs if focus == "capital"
        equity_val: float | None = None
        risk_pct_val: float | None = None
        needs_capital_inputs = False
        if focus == "capital":
            eq_m = re.search(r"(?:equity|modal|capital|saldo|balance)[\s:=]*\$?(\d+(?:\.\d+)?)", cleaned, re.IGNORECASE)
            if not eq_m:
                eq_m = re.search(r"\$(\d+(?:\.\d+)?)", cleaned)
            if eq_m:
                try:
                    equity_val = float(eq_m.group(1))
                except ValueError:
                    pass
            risk_m = re.search(r"(?:risk|resiko|risiko)?[\s:=]*(\d+(?:\.\d+)?)\s*%", cleaned, re.IGNORECASE)
            if risk_m:
                try:
                    risk_pct_val = float(risk_m.group(1))
                except ValueError:
                    pass
            if equity_val is None or risk_pct_val is None:
                needs_capital_inputs = True

        return IntentRequest(
            intent=intent,
            asset=asset,
            asset_2=asset_2,
            target_assets=target_assets,
            market=market,
            focus=focus,
            needs_asset=needs_asset,
            clarification_prompt=clarification_prompt,
            equity=equity_val,
            risk_pct=risk_pct_val,
            needs_capital_inputs=needs_capital_inputs,
            raw_query=text,
        )
