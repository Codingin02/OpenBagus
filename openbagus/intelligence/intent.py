"""OpenBagus Bilingual Natural-Language Intent & Context Router.

Converts user text into structured quantitative research requests using lightweight
bilingual (Indonesian + English) token analysis, typo correction, conversational session
context, and strict hierarchical request routing.

Pipeline priority:
INPUT -> normalize -> classify request type -> resolve conversation context (session)
      -> resolve category/market-wide -> resolve explicit asset -> conservative fallback.

No local LLM. No cloud LLM.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.domains.crypto.catalog import CryptoAssetCatalog, TAXONOMY_CATEGORIES

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
    "SYSTEM_INFO",
    "PREFERENCE",
    "MARKET_OUTLOOK",
    "CATEGORY",
    "SCREEN",
    "EXPLAIN_LEVELS",
    "FOLLOW_UP",
)

REQUEST_TYPES = (
    "ASSET_ANALYSIS",
    "POSITION",
    "RISK_RETURN",
    "EXPLAIN_LEVELS",
    "COMPARE",
    "CATEGORY",
    "SCREEN",
    "MARKET_OUTLOOK",
    "SYSTEM_INFO",
    "PREFERENCE",
    "FOLLOW_UP",
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

COMPREHENSIVE_STOP_WORDS = {
    # Indonesian grammatical and conversational words
    "yang", "nggk", "nggak", "ga", "gak", "gitu", "gini", "kok", "sih", "dong", "deh", "kan", "tuh", "lah",
    "prospek", "prospeknya", "nanti", "kenapa", "mengapa", "bagaimana", "gimana", "apa", "apakah", "siapa",
    "dimana", "mana", "kapan", "berapa", "kira", "kira2", "kira-kira", "simpan", "tahan", "pegang", "serok",
    "beli", "jual", "tukar", "cutloss", "loss", "profit", "cuan", "rugi", "naik", "turun", "koin", "coin",
    "token", "crypto", "kripto", "pasar", "market", "kondisi", "sekarang", "ini", "itu", "tersebut", "dan",
    "atau", "tapi", "namun", "juga", "jika", "kalau", "kalo", "bila", "supaya", "agar", "untuk", "pada",
    "di", "ke", "dari", "dalam", "atas", "bawah", "dengan", "tanpa", "tentang", "oleh", "karena", "sebab",
    "anda", "kamu", "saya", "aku", "kita", "kami", "mereka", "dia", "ia", "dijalankan", "dibuat", "dipakai",
    "jalan", "pakai", "sumber", "data", "provider", "sistem", "terminal", "cli", "status", "info", "bisa",
    "ada", "tidak", "bukan", "jangan", "kasih", "tampilkan", "sembunyikan", "jelaskan", "terangkan", "tolong",
    "mohon", "enaknya", "bagusnya", "baiknya", "terbaik", "terburuk", "kuartal", "bulan", "minggu", "hari",
    "terakhir", "lalu", "depan", "high", "low", "all", "time", "ath", "atl", "volume", "besar", "kecil",
    "trus", "terus", "lanjut", "lanjutkan", "rekomendasi", "sinyal", "entrynya", "slnya", "tpnya", "risknya",
    "posisinya", "setupnya", "targetnya", "alasannya", "kenapanya", "bang", "bro", "gan", "kak", "om", "pak",
    # English grammatical and conversational words
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "in", "on", "at", "to", "for", "with",
    "about", "against", "between", "into", "through", "during", "before", "after", "above", "below", "from",
    "up", "down", "of", "off", "over", "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "should", "now",
    "what", "which", "who", "whom", "this", "that", "these", "those", "am", "have", "has", "had", "do", "does",
    "did", "doing", "would", "could", "give", "show", "hide", "without", "source", "sources", "running", "run",
    "prospect", "prospects", "outlook", "condition", "quarter", "gainers", "losers", "recent",
    # Trading actions, concepts, and directions (must not shadow target assets in multi-token queries)
    "buy", "sell", "long", "short", "entry", "exit", "position", "posisi", "posisinya",
    "leverage", "margin", "spot", "perp", "perps", "futures", "setup", "trade", "trading",
    "support", "resistance", "snr", "pivot", "pivots", "level", "levels", "risk", "resiko",
    "risiko", "drawdown", "tp", "sl", "target", "profit", "loss", "review", "analyze",
    "analysis", "analisa", "analisis", "attractive", "view", "opinion", "recommendation",
}


@dataclass
class SessionState:
    last_asset: str | None = None
    last_asset_2: str | None = None
    last_market: str = "all"
    last_intent: str = "ANALYZE"
    last_result: Any = None
    last_quant_result: Any = None
    last_category: str | None = None
    last_query: str = ""
    show_sources: bool = False


@dataclass
class IntentRequest:
    intent: str  # One of ALLOWED_INTENTS
    request_type: str = "ASSET_ANALYSIS"  # One of REQUEST_TYPES
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
    category: str | None = None
    preference_action: str | None = None
    system_query: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntentRouter:
    """Lightweight bilingual intent router with hierarchical classification and session memory."""

    def __init__(self, catalog: CryptoAssetCatalog | None = None, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.catalog = catalog or CryptoAssetCatalog(self.root)

    def parse(self, text: str, session: SessionState | None = None) -> IntentRequest:
        cleaned = text.strip()
        if not cleaned:
            return IntentRequest(intent="UNKNOWN", request_type="UNKNOWN", raw_query=text)

        lower = cleaned.lower()
        words = re.findall(r"\b[A-Za-z0-9/]+\b", cleaned)

        # -------------------------------------------------------------
        # 1. System Information Classification
        # -------------------------------------------------------------
        sys_triggers = [
            "anda dijalankan di mana", "kamu jalan dimana", "dijalankan di mana",
            "kamu ini apa", "siapa kamu", "siapa anda", "anda siapa",
            "provider apa yang dipakai", "sumber data apa", "data source apa",
            "status openbagus", "what is openbagus", "where are you running",
            "what providers do you use", "system info", "runtime info",
            "kamu pakai model apa", "model ai apa", "arsitektur openbagus",
        ]
        if any(trig in lower for trig in sys_triggers):
            return IntentRequest(
                intent="SYSTEM_INFO",
                request_type="SYSTEM_INFO",
                raw_query=text,
                system_query=cleaned,
            )

        # -------------------------------------------------------------
        # 2. Preference Updates (Sources / Views)
        # -------------------------------------------------------------
        pref_hide_triggers = [
            "jangan kasih sources", "tanpa sources", "hide sources", "sources off",
            "no sources", "tanpa sumber", "jangan tampilkan sources",
            "jangan tampilkan sumber", "sources hide", "sembunyikan sources",
        ]
        if any(trig in lower for trig in pref_hide_triggers):
            return IntentRequest(
                intent="PREFERENCE",
                request_type="PREFERENCE",
                preference_action="hide_sources",
                raw_query=text,
            )

        pref_show_triggers = [
            "tampilkan sources", "show sources", "sources on", "kasih sources",
            "dengan sources", "tampilkan sumber", "sources show", "munculkan sources",
        ]
        if any(trig in lower for trig in pref_show_triggers):
            return IntentRequest(
                intent="PREFERENCE",
                request_type="PREFERENCE",
                preference_action="show_sources",
                raw_query=text,
            )

        # -------------------------------------------------------------
        # 3. Market-Wide Outlook Classification
        # -------------------------------------------------------------
        mkt_triggers = [
            "gimana prospek crypto", "prospek crypto", "prospek pasar crypto",
            "kondisi pasar crypto", "kondisi market crypto", "market outlook",
            "crypto outlook", "kondisi crypto sekarang", "kondisi pasar sekarang",
            "bagaimana prospek crypto", "bagaimana market crypto", "bagaimana kondisi crypto",
            "crypto overview", "market overview", "prospek market",
        ]
        if any(trig in lower for trig in mkt_triggers):
            return IntentRequest(
                intent="MARKET_OUTLOOK",
                request_type="MARKET_OUTLOOK",
                raw_query=text,
            )

        # -------------------------------------------------------------
        # 4. Screening and Category Classification
        # -------------------------------------------------------------
        screen_triggers = [
            "koin yang high 1 kuartal terakhir", "koin performa terbaik", "top gainers",
            "koin volume besar", "screen crypto", "daftar koin high", "koin potensial",
        ]
        if any(trig in lower for trig in screen_triggers):
            return IntentRequest(
                intent="SCREEN",
                request_type="SCREEN",
                raw_query=text,
            )

        # Check explicit taxonomy category
        for cat in TAXONOMY_CATEGORIES:
            cat_l = cat.lower()
            if cat_l in lower and cat_l not in ("other / unknown", "bitcoin"):
                return IntentRequest(
                    intent="CATEGORY",
                    request_type="CATEGORY",
                    category=cat,
                    raw_query=text,
                )

        # -------------------------------------------------------------
        # 5. Asset Comparison Detection (e.g. BTC vs ETH)
        # -------------------------------------------------------------
        vs_match = re.search(r"\b([A-Za-z0-9]+)\s+(?:vs|versus|v)\s+([A-Za-z0-9]+)\b", cleaned, re.IGNORECASE)
        if vs_match or ("bandingkan" in lower and len(words) >= 3):
            c1, c2 = (vs_match.group(1), vs_match.group(2)) if vs_match else (words[1], words[2])
            a1, _ = self.catalog.resolve_asset(c1)
            a2, _ = self.catalog.resolve_asset(c2)
            if a1 and a2:
                return IntentRequest(
                    intent="COMPARE",
                    request_type="COMPARE",
                    asset=a1.symbol,
                    asset_2=a2.symbol,
                    target_assets=[a1.symbol, a2.symbol],
                    focus="compare",
                    raw_query=text,
                )

        # -------------------------------------------------------------
        # 6. Conversational Follow-Up on Previous Asset
        # -------------------------------------------------------------
        # If user asks e.g. "kok risk dan TPnya nggk ada sih" or "entry dimana" or "kenapa gitu"
        # without introducing a new asset, bind to session.last_asset
        if session and session.last_asset:
            followup_level_triggers = [
                "tpnya", "risknya", "slnya", "entrynya", "tp nya", "risk nya", "sl nya",
                "tp", "sl", "risk", "take profit", "stop loss", "level", "levels", "nggk ada",
                "nggak ada", "tidak ada", "kenapa", "kok", "alasannya",
            ]
            followup_position_triggers = [
                "entry dimana", "masuk dimana", "bisa beli", "bisa serok", "enaknya long",
                "bagusnya long", "long apa short", "long or short", "beli sekarang",
            ]
            followup_outlook_triggers = [
                "gimana prospeknya", "prospeknya", "kondisinya", "pandangan", "analisanya",
            ]

            is_level_followup = any(trig in lower for trig in followup_level_triggers)
            is_pos_followup = any(trig in lower for trig in followup_position_triggers)
            is_out_followup = any(trig in lower for trig in followup_outlook_triggers)

            if is_level_followup or is_pos_followup or is_out_followup:
                req_type = "EXPLAIN_LEVELS" if is_level_followup else ("POSITION" if is_pos_followup else "FOLLOW_UP")
                intent = "STRUCTURE" if is_level_followup else ("POSITION" if is_pos_followup else "ANALYZE")
                return IntentRequest(
                    intent=intent,
                    request_type=req_type,
                    asset=session.last_asset,
                    target_assets=[session.last_asset],
                    raw_query=text,
                )

        # -------------------------------------------------------------
        # 7. Typo correction for crypto vocabulary
        # -------------------------------------------------------------
        vocab_keys = list(CRYPTO_VOCAB_CANONICAL.keys())
        clean_tokens: list[str] = []
        for w in words:
            wl = w.lower()
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

        # -------------------------------------------------------------
        # 8. Explicit Asset Resolution
        # -------------------------------------------------------------
        asset: str | None = None
        asset_2: str | None = None
        target_assets: list[str] = []

        # Check explicit preposition target: "di ADA", "di SOL", "pada BTC", "koin SOL", "token DOGE"
        prep_match = re.search(r"\b(?:di|pada|koin|coin|token)\s+([A-Za-z0-9]+)\b", cleaned, re.IGNORECASE)
        if prep_match:
            candidate = prep_match.group(1)
            if candidate.lower() not in COMPREHENSIVE_STOP_WORDS:
                a_obj, amb = self.catalog.resolve_asset(candidate)
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]

        # Check standalone token or exact query (e.g. "ADA", "BTC", "SOL", "Manta", "Five")
        if not asset:
            stripped_clean = cleaned.strip("? !.").upper()
            if stripped_clean == "ADA":
                asset = "ADA"
                target_assets = ["ADA"]
            elif len(words) == 1 and stripped_clean.lower() not in COMPREHENSIVE_STOP_WORDS:
                a_obj, amb = self.catalog.resolve_asset(words[0])
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]
                elif amb:
                    return IntentRequest(
                        intent="ANALYZE",
                        request_type="ASSET_ANALYSIS",
                        is_ambiguous=True,
                        candidates=[a.symbol for a in amb],
                        raw_query=text,
                    )

        # Multi-token scan strictly excluding COMPREHENSIVE_STOP_WORDS
        if not asset:
            for orig_w, clean_w in zip(words, clean_tokens):
                orig_lower = orig_w.lower()
                clean_lower = clean_w.lower()
                if orig_lower in COMPREHENSIVE_STOP_WORDS or clean_lower in COMPREHENSIVE_STOP_WORDS:
                    continue
                if orig_lower == "ada":  # Indonesian "ada" protection
                    continue
                a_obj, _ = self.catalog.resolve_asset(orig_w)
                if not a_obj:
                    a_obj, _ = self.catalog.resolve_asset(clean_w)
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]
                    break

        # -------------------------------------------------------------
        # 9. Intent & Request Type Classification for Asset Query
        # -------------------------------------------------------------
        market = "all"
        focus = "general"
        intent = "ANALYZE"
        request_type = "ASSET_ANALYSIS"

        if any(k in norm_text for k in ["buy", "beli", "serok", "akumulasi", "spot buy"]):
            intent = "BUY_SPOT"
            market = "spot"
            focus = "spot"
            request_type = "POSITION"
        elif any(k in norm_text for k in ["sell", "jual", "cut loss", "exit spot"]):
            intent = "SELL_SPOT"
            market = "spot"
            focus = "spot"
            request_type = "POSITION"
        elif any(k in norm_text for k in [
            "long atau short", "long or short", "enaknya long apa short", "bagusnya long atau short",
            "enaknya long", "bagusnya long", "leverage", "perp", "perpetual", "futures",
        ]):
            intent = "LONG_SHORT"
            market = "perpetual"
            focus = "leverage" if "leverage" in norm_text else "long_short"
            request_type = "POSITION"
        elif any(k in norm_text for k in ["margin", "position size", "posisi size", "sizing", "modal berapa", "margin berapa", "size berapa"]):
            intent = "POSITION"
            market = "perpetual" if "margin" in norm_text else "all"
            focus = "capital"
            request_type = "POSITION"
        elif any(k in norm_text for k in ["position", "posisi", "posisinya", "entry", "entry dimana", "masuk dimana", "setup", "trade setup"]):
            intent = "POSITION"
            focus = "setup"
            request_type = "POSITION"
        elif "divergence" in norm_text or "divergent" in lower:
            intent = "DIVERGENCE"
            focus = "divergence"
            request_type = "EXPLAIN_LEVELS"
        elif any(k in norm_text for k in ["support", "resistance", "snr", "s/r", "pivot", "structure", "struktur", "levels"]):
            intent = "STRUCTURE"
            focus = "structure"
            request_type = "EXPLAIN_LEVELS"
        elif any(k in norm_text for k in ["risk", "resiko", "risiko", "drawdown", "volatility", "volatilitas", "stop loss"]):
            intent = "RISK"
            focus = "risk"
            request_type = "RISK_RETURN"
        elif any(k in norm_text for k in ["funding rate", "funding", "fr"]):
            intent = "FUNDING"
            focus = "funding"
            market = "perpetual"
            request_type = "POSITION"
        elif any(k in norm_text for k in ["open interest", "oi"]):
            intent = "OPEN_INTEREST"
            focus = "open_interest"
            market = "perpetual"
            request_type = "POSITION"

        # Check for capital inputs (equity / risk)
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

        # Fallback handling
        needs_asset = False
        clarification_prompt = None
        if not asset:
            if intent in ("DIVERGENCE", "POSITION", "STRUCTURE", "RISK", "LONG_SHORT", "BUY_SPOT", "SELL_SPOT", "FUNDING", "OPEN_INTEREST"):
                needs_asset = True
                clarification_prompt = "Which asset do you want to analyze?"
            else:
                return IntentRequest(intent="UNKNOWN", request_type="UNKNOWN", raw_query=text)

        return IntentRequest(
            intent=intent,
            request_type=request_type,
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
