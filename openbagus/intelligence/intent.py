"""OpenBagus Bilingual Natural-Language Intent & Context Router.

Converts user text into structured quantitative research requests using lightweight
bilingual (Indonesian + English) token analysis, typo correction, conversational session
context, and strict hierarchical request routing.

Pipeline priority:
1. Slash command
2. Feedback / preference
3. Session follow-up
4. System question (including Harness)
5. Explicit category request
6. Explicit asset request
7. Market-wide query
8. Conservative fuzzy asset lookup
9. Clarification

No local LLM. No cloud LLM.
"""

from __future__ import annotations

import ast
import difflib
import operator as _op
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.domains.crypto.catalog import (
    CryptoAssetCatalog,
    DEX_SLANG_EXCLUSIONS,
    TAXONOMY_CATEGORIES,
)
from openbagus.intelligence.local_language import LocalLanguageEngine

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
    "FEEDBACK",
    "HARNESS",
    "SETUP_CONFIG",
    "CHART",
    "FIAT_FX",
    "CALCULATOR",
    "CRYPTO_QUOTE",
    "EXECUTION_REQUEST",
    "COMMAND",
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
    "FEEDBACK",
    "HARNESS",
    "SETUP_CONFIG",
    "CHART",
    "FIAT_FX",
    "CALCULATOR",
    "CRYPTO_QUOTE",
    "EXECUTION_REQUEST",
    "COMMAND",
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
    "ingin", "mau", "tahu", "tau", "menggunakan", "guna", "apapun", "model", "cloud", "lokal", "tanya",
    "semua", "parameter", "spek", "speknya", "dibawah", "ollama", "llm", "ohh", "iya", "harness", "herness", "hernes", "sistem", "system",
    "lagi", "tampilin", "chart", "grafik", "whale", "cpi", "fomc", "pembuat", "pembuatnya", "bikin", "tadi",
    "cara", "mobil", "ban", "jalan", "tol", "ganti", "mengganti", "motor", "rumah", "orang", "makan", "minum", "kerja",
    # English grammatical and conversational words
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "in", "on", "at", "to", "for", "with",
    "about", "against", "between", "into", "through", "during", "before", "after", "above", "below", "from",
    "up", "down", "of", "off", "over", "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "any", "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "should", "now",
    "what", "which", "who", "whom", "this", "that", "these", "those", "am", "have", "has", "had", "do", "does",
    "did", "doing", "would", "could", "give", "show", "hide", "without", "source", "sources", "running", "run",
    "prospect", "prospects", "outlook", "condition", "quarter", "gainers", "losers", "recent",
    # Trading actions, concepts, and directions
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
    last_comparison_assets: list[str] = field(default_factory=list)
    timeframe: str = "H1"
    market_type: str = "PERPETUAL"
    last_intent: str = "ANALYZE"
    last_result: Any = None
    last_quant_result: Any = None
    last_research_packet: Any = None
    last_candidate_long: Any = None
    last_candidate_short: Any = None
    last_category: str | None = None
    last_query: str = ""
    last_research_at: str | None = None
    language: str = "AUTO"
    show_sources: bool = False
    clear_on_exit: bool = True
    recent_preferences: dict[str, Any] = field(default_factory=dict)
    conversational_turns: list[dict[str, str]] = field(default_factory=list)

    def add_turn(self, user_text: str, assistant_text: str) -> None:
        self.conversational_turns.append({"user": user_text, "assistant": assistant_text})
        if len(self.conversational_turns) > 4:
            self.conversational_turns = self.conversational_turns[-4:]

    def clear(self) -> None:
        self.last_asset = None
        self.last_asset_2 = None
        self.last_comparison_assets = []
        self.timeframe = "H1"
        self.market_type = "PERPETUAL"
        self.last_intent = "ANALYZE"
        self.last_result = None
        self.last_quant_result = None
        self.last_research_packet = None
        self.last_candidate_long = None
        self.last_candidate_short = None
        self.last_category = None
        self.last_query = ""
        self.last_research_at = None
        self.language = "AUTO"
        self.conversational_turns = []

    def status_display(self) -> str:
        lines = [
            "OpenBagus Harness",
            "",
            "Status          ACTIVE",
            f"Current Asset   {self.last_asset or 'NONE'}",
            f"Market          {self.market_type}",
            f"Timeframe       {self.timeframe}",
            "Session Memory  LOCAL / EPHEMERAL",
            f"Sources         {'ON' if self.show_sources else 'OFF'}",
            f"Turns Cached    {len(self.conversational_turns)}/4",
            f"Clear on Exit   {'YES' if self.clear_on_exit else 'NO'}",
        ]
        return "\n".join(lines)


@dataclass
class IntentRequest:
    intent: str  # One of ALLOWED_INTENTS
    request_type: str = "ASSET_ANALYSIS"  # One of REQUEST_TYPES
    asset: str | None = None
    asset_2: str | None = None
    target_assets: list[str] = field(default_factory=list)
    market: str = "all"  # "spot", "perpetual", "all"
    timeframe: str = "H1"  # "M1", "M5", "M15", "M30", "H1", "H4", "H6", "H12", "D1", "W1"
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
    relation_to_context: str = "UNCERTAIN"  # CONTINUE, SWITCH, UNRELATED, UNCERTAIN
    topic: str | None = None
    needs_topic_switch_confirmation: bool = False
    switch_target_asset: str | None = None
    amount: float = 1.0
    has_position_context: bool = False
    asset_id: str | None = None

    @property
    def domain(self) -> str:
        if self.request_type in {"HARNESS", "SETUP_CONFIG"}:
            return "SYSTEM_INFO"
        if self.request_type == "SCREEN":
            return "CATEGORY"
        if self.system_query in {"list_assets", "list_categories"}:
            return "COMMAND"
        if self.request_type in {"FIAT_FX", "CALCULATOR", "CRYPTO_QUOTE", "EXECUTION_REQUEST", "COMMAND", "CATEGORY", "CHART", "SYSTEM_INFO", "PREFERENCE", "FEEDBACK", "UNKNOWN"}:
            return self.request_type
        return "CRYPTO_RESEARCH"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_timeframe(text: str, default_tf: str = "H1") -> tuple[str, str]:
    """Extracts trading timeframe notation from text and returns (normalized_tf, text_without_tf)."""
    # 1. Standard trading timeframe codes
    code_match = re.search(r"\b(M1|M5|M15|M30|H1|H4|H6|H12|D1|W1)\b", text, re.IGNORECASE)
    if code_match:
        tf = code_match.group(1).upper()
        cleaned = re.sub(r"\b" + re.escape(code_match.group(1)) + r"\b", " ", text, flags=re.IGNORECASE)
        return tf, re.sub(r"\s+", " ", cleaned).strip()

    # 2. Natural language timeframe expressions
    nl_patterns = [
        (r"\b1\s*(?:menit|minute|min)\b", "M1"),
        (r"\b5\s*(?:menit|minutes|min)\b", "M5"),
        (r"\b15\s*(?:menit|minutes|min)\b", "M15"),
        (r"\b30\s*(?:menit|minutes|min)\b", "M30"),
        (r"\b1\s*(?:jam|hour|hr)\b", "H1"),
        (r"\b4\s*(?:jam|hours|hrs)\b", "H4"),
        (r"\b6\s*(?:jam|hours|hrs)\b", "H6"),
        (r"\b12\s*(?:jam|hours|hrs)\b", "H12"),
        (r"\b(?:1\s*(?:hari|day)|harian|daily)\b", "D1"),
        (r"\b(?:1\s*(?:minggu|week)|mingguan|weekly)\b", "W1"),
        (r"\b(?:short\s*term|short-term)\b", "H1"),
        (r"\b(?:hari ini|today|intraday)\b", "H1"),
        (r"\bswing\b", "H4"),
    ]
    for pat, tf in nl_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cleaned = re.sub(pat, " ", text, flags=re.IGNORECASE)
            return tf, re.sub(r"\s+", " ", cleaned).strip()

    return default_tf, text


# ---------------------------------------------------------------------------
# Safe arithmetic evaluator for CALCULATOR domain gate
# ---------------------------------------------------------------------------
_CALC_OPS = {
    ast.Add: _op.add,
    ast.Sub: _op.sub,
    ast.Mult: _op.mul,
    ast.Div: _op.truediv,
    ast.Pow: _op.pow,
    ast.USub: _op.neg,
}


def _safe_calc(expr: str) -> str | None:
    """Evaluate a simple arithmetic expression; return string result or None on failure."""
    # strip whitespace variants around = and ? to get the expression
    clean = expr.rstrip(" =?").strip()
    if len(clean) > 256:
        return None
    try:
        tree = ast.parse(clean, mode="eval")
    except (SyntaxError, RecursionError):
        return None
    if sum(1 for _ in ast.walk(tree)) > 64:
        return None

    def _eval(node: ast.expr) -> float:  # type: ignore[type-arg]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
            left, right = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent limit")
            result = _CALC_OPS[type(node.op)](left, right)
            if not math.isfinite(result) or abs(result) > 1e100:
                raise ValueError("Result limit")
            return result
        if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
            return _CALC_OPS[type(node.op)](_eval(node.operand))
        raise ValueError("Unsupported node")

    try:
        result = _eval(tree.body)  # type: ignore[arg-type]
        if result == int(result):
            return str(int(result))
        return f"{result:.6g}"
    except Exception:
        return None


# Known command words for typo correction (difflib)
_COMMAND_VOCAB = [
    "assets", "categories", "category", "chart", "harness", "sources",
    "screen", "compare", "help", "version", "status", "providers", "doctor", "setup",
]

class IntentRouter:
    """Lightweight bilingual intent router with hierarchical classification and session memory."""

    def __init__(self, catalog: CryptoAssetCatalog | None = None, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.catalog = catalog or CryptoAssetCatalog(self.root)
        self.local_llm = LocalLanguageEngine(repo_root=self.root)

    def parse(self, text: str, session: SessionState | None = None) -> IntentRequest:
        request = self._parse(text, session)
        request.has_position_context = bool(re.search(
            r"\b(?:aku\s+pegang|saya\s+(?:pegang|sudah\s+beli)|posisi\s+\w+\s+saya|"
            r"(?:i\s+(?:already\s+)?hold|i\s+own|my\s+position)|should\s+i\s+reduce|"
            r"jual\s+sebagian|kurangi\s+posisi)\b", text, re.IGNORECASE))
        return request

    def _parse(self, text: str, session: SessionState | None = None) -> IntentRequest:
        cleaned = text.strip()
        if not cleaned:
            return IntentRequest(intent="UNKNOWN", request_type="UNKNOWN", raw_query=text)

        lower = cleaned.lower()
        if re.fullmatch(r"(?:jelasin dalam bahasa indonesia|pakai bahasa indonesia|bahasa indonesia|indonesia aja|explain in english|use english|english please)[?!. ]*", lower):
            return IntentRequest(intent="PREFERENCE", request_type="PREFERENCE", preference_action="language_id" if "indonesia" in lower else "language_en", raw_query=text, relation_to_context="CONTINUE")
        default_tf = session.timeframe if session and session.timeframe else "H1"
        detected_tf, query_no_tf = _parse_timeframe(cleaned, default_tf=default_tf)
        lower_no_tf = query_no_tf.lower()
        words = re.findall(r"\b[A-Za-z0-9/-]+\b", query_no_tf)

        # Non-research requests must never enter crypto discovery or Harness switching.
        fiat_aliases = {"dollar": "USD", "dolar": "USD", "rupiah": "IDR", "rp": "IDR",
                        "euro": "EUR", "yen": "JPY", "pound": "GBP", "sterling": "GBP"}
        fiat_codes = {"USD", "IDR", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "SGD", "MYR"}
        currencies = [fiat_aliases.get(w.lower(), w.upper()) for w in words
                      if w.lower() in fiat_aliases or w.upper() in fiat_codes]
        if len(set(currencies)) >= 2:
            base, quote = currencies[0], next(c for c in currencies if c != currencies[0])
            if re.search(r"harga\s+rupiah.*(?:dibandingkan|vs).*dolar", lower):
                base, quote = "USD", "IDR"
            number = re.search(r"\b\d+(?:\.\d+)?\b", cleaned)
            return IntentRequest(intent="FIAT_FX", request_type="FIAT_FX", raw_query=text,
                                 focus=f"{base}/{quote}", amount=float(number.group()) if number else 1.0,
                                 relation_to_context="UNRELATED")

        if re.fullmatch(r"[\d\s+\-*/().=?]+", cleaned) and re.search(r"[+\-*/]", cleaned):
            result = _safe_calc(cleaned)
            return IntentRequest(intent="CALCULATOR", request_type="CALCULATOR",
                                 raw_query=text, focus=result or "CALCULATOR_INVALID",
                                 relation_to_context="UNRELATED")

        payment = re.search(r"\b(?:card|kartu|payment|bayar|rekening)\b", lower)
        if (payment and re.search(r"\b(?:beli|buy|purchase|bayar)\b", lower)) or re.search(
            r"\b(?:purchase|execute\s+(?:order|trade)|place\s+order)\b", lower
        ):
            return IntentRequest(intent="EXECUTION_REQUEST", request_type="EXECUTION_REQUEST",
                                 raw_query=text, relation_to_context="UNRELATED")

        category_names = {c.lower(): c for c in TAXONOMY_CATEGORIES if c.lower() != "bitcoin"}
        category_names.update({"other": "Other / Unknown", "others": "Other / Unknown",
                               "lainnya": "Other / Unknown"})
        category = category_names.get(lower.strip("?!. "))
        if category:
            return IntentRequest(intent="CATEGORY", request_type="CATEGORY", category=category,
                                 raw_query=text, relation_to_context="UNRELATED")

        command_match = re.search(r"\b(?:berikan|tampilkan|kasih|lihat|daftar|list|show)\s+(assets?|categories)\b", lower)
        command = command_match.group(1) if command_match else lower.strip("?!. ")
        if command == "asset":
            command = "assets"
        matches = difflib.get_close_matches(command, _COMMAND_VOCAB, n=1, cutoff=0.75) if " " not in command else []
        command = matches[0] if matches else command
        if command in ("categories", "category", "assets"):
            return IntentRequest(intent="SYSTEM_INFO", request_type="SYSTEM_INFO",
                                 system_query="list_assets" if command == "assets" else "list_categories",
                                 raw_query=text, relation_to_context="UNRELATED")
        if command in ("help", "status", "providers", "doctor", "setup", "version"):
            return IntentRequest(intent="COMMAND", request_type="COMMAND", system_query=command,
                                 raw_query=text, relation_to_context="UNRELATED")

        chart_match = re.fullmatch(r"(?:chart|chat|char)\s+([A-Za-z0-9/]+)", lower)
        if chart_match:
            asset, _ = self.catalog.resolve_asset(chart_match.group(1))
            return IntentRequest(intent="CHART", request_type="CHART",
                                 asset=asset.symbol if asset else None, raw_query=text,
                                 relation_to_context="UNRELATED")

        is_analysis = re.search(r"\b(?:analisa|analisis|analysis|analyze|review|risk|risiko|position|posisi|long|short|setup)\b", lower)
        quote_match = re.search(r"\b(?:harga|price|berapa)\s+([A-Za-z0-9/]+)", lower)
        amount_match = re.search(r"\b(\d+(?:\.\d+)?)\s+([A-Za-z][A-Za-z0-9/]*)\s+(?:berapa|to|in)", lower)
        if not is_analysis and (quote_match or amount_match):
            symbol = amount_match.group(2) if amount_match else quote_match.group(1)
            if symbol.lower() not in DEX_SLANG_EXCLUSIONS:
                asset, _ = self.catalog.resolve_asset(symbol, is_explicit=True)
                if asset:
                    return IntentRequest(intent="CRYPTO_QUOTE", request_type="CRYPTO_QUOTE",
                                         asset=asset.symbol, raw_query=text,
                                         amount=float(amount_match.group(1)) if amount_match else 1.0,
                                         relation_to_context="UNRELATED")

        # -------------------------------------------------------------
        # 0. Fast Path for pure exact known asset symbols (BTC, ETH, SOL, NEAR, ZEC, etc.)
        # Prevents unnecessary LLM invocation for straightforward queries
        # -------------------------------------------------------------

        if len(words) == 1 and not cleaned.startswith("/"):
            pure_cand = words[0].upper()
            if pure_cand not in COMPREHENSIVE_STOP_WORDS and pure_cand.lower() not in DEX_SLANG_EXCLUSIONS:
                resolved, ambiguous = self.catalog.resolve_asset(words[0], is_explicit=True)
                if ambiguous:
                    return IntentRequest(intent="ANALYZE", request_type="ASSET_ANALYSIS", is_ambiguous=True, candidates=[a.id for a in ambiguous[:5]], raw_query=text)
                if resolved:
                    pure_cand = resolved.symbol
                    needs_switch = bool(session and session.last_asset and session.last_asset != pure_cand)
                    return IntentRequest(
                        intent="ANALYZE",
                        request_type="ASSET_ANALYSIS",
                        asset=pure_cand,
                        asset_id=resolved.id,
                        target_assets=[pure_cand],
                        timeframe=detected_tf,
                        raw_query=text,
                        needs_topic_switch_confirmation=needs_switch,
                        switch_target_asset=pure_cand if needs_switch else None,
                        relation_to_context="SWITCH" if needs_switch else "CONTINUE",
                    )

        # -------------------------------------------------------------
        # 1. Exact Slash Commands
        # -------------------------------------------------------------
        if cleaned.startswith("/"):
            cmd = cleaned[1:].strip().lower()
            if cmd in ("harness", "harness status"):
                return IntentRequest(intent="SYSTEM_INFO", request_type="HARNESS", timeframe=detected_tf, raw_query=text)
            if cmd in ("harness clear", "harness reset"):
                return IntentRequest(intent="SYSTEM_INFO", request_type="HARNESS", preference_action="clear_harness", timeframe=detected_tf, raw_query=text)
            if cmd.startswith("switch"):
                switch_arg = cleaned[1:].replace("switch", "", 1).strip()
                if switch_arg:
                    a_obj, _ = self.catalog.resolve_asset(switch_arg)
                    sw_sym = a_obj.symbol if a_obj else switch_arg.upper()
                    return IntentRequest(
                        intent="ANALYZE",
                        request_type="ASSET_ANALYSIS",
                        asset=sw_sym,
                        target_assets=[sw_sym],
                        timeframe=detected_tf,
                        raw_query=text,
                        relation_to_context="SWITCH",
                        needs_topic_switch_confirmation=False,
                    )
            if cmd.startswith("sources"):
                act = "show_sources" if any(x in cmd for x in ("on", "1", "show")) else "hide_sources"
                return IntentRequest(intent="PREFERENCE", request_type="PREFERENCE", preference_action=act, timeframe=detected_tf, raw_query=text)
            if cmd.startswith("chart"):
                chart_arg = cmd.replace("chart", "", 1).strip()
                if chart_arg:
                    a_obj, _ = self.catalog.resolve_asset(chart_arg)
                    if a_obj:
                        return IntentRequest(intent="CHART", request_type="CHART", asset=a_obj.symbol, timeframe=detected_tf, raw_query=text)
                target_sym = session.last_asset if (session and session.last_asset) else "BTC"
                return IntentRequest(intent="CHART", request_type="CHART", asset=target_sym, timeframe=detected_tf, raw_query=text)

        # -------------------------------------------------------------
        # 2. Obvious System / Preference / Feedback Requests (Deterministic)
        # Executed BEFORE any asset lookup to prevent false token matching
        # -------------------------------------------------------------
        # 2a. Feedback triggers
        feedback_triggers = [
            r"\bwkwk+\b",
            r"\btolol\b",
            r"\bbego\b",
            r"\bbodoh\b",
            r"\bgenerik\b",
            r"\bjawabannya\s+generik\b",
            r"\bkayak\s+ai\b",
            r"\bkayak\s+bot\b",
            r"\bkacau\s+banget\b",
            r"\bsampah\b",
            r"\bjelek\b",
            r"\brusak\b",
            r"\bno\s+trade\s+semua\b",
            r"\bkok\s+no\s+trade\b",
            r"\baneh\s+nih\b",
            r"\bgimana\s+sih\b",
            r"\bkok\s+gini\b",
            r"\bsummary\s+jelek\b",
            r"\bsummarynya\s+kayak\s+ai\b",
            r"\btolol\s+nih\b",
        ]
        is_explicit_token = bool(re.search(r"\b(?:koin|coin|token|analyze)\s+[A-Za-z0-9]+\b", lower, re.IGNORECASE))
        if not is_explicit_token and any(re.search(pat, lower) for pat in feedback_triggers):
            return IntentRequest(
                intent="FEEDBACK",
                request_type="FEEDBACK",
                asset=session.last_asset if session else None,
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE",
            )

        # 2b. Preferences: Sources toggles
        pref_hide_sources = [
            "jangan kasih sources", "tanpa sources", "hide sources", "sources off",
            "no sources", "tanpa sumber", "jangan tampilkan sources",
            "jangan tampilkan sumber", "sources hide", "sembunyikan sources",
            "jangan tampilin sources", "jangan tampilin sumber",
            "jangan tampilkan sources lagi", "jangan tampilin sources lagi",
            "tanpa sumber lagi", "hide sources please",
        ]
        if any(trig in lower for trig in pref_hide_sources):
            return IntentRequest(
                intent="PREFERENCE",
                request_type="PREFERENCE",
                preference_action="hide_sources",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE",
            )

        pref_show_sources = [
            "tampilkan sources", "show sources", "sources on", "kasih sources",
            "dengan sources", "tampilkan sumber", "sources show", "munculkan sources",
            "tampilin sources", "tampilin sumber", "aktifkan sources",
        ]
        if any(trig in lower for trig in pref_show_sources):
            return IntentRequest(
                intent="PREFERENCE",
                request_type="PREFERENCE",
                preference_action="show_sources",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE",
            )

        # 2c. Preferences: Chart toggles
        pref_hide_chart = [
            "jangan tampilkan chart", "tanpa chart", "chart off", "hide chart",
            "sembunyikan chart", "tanpa grafik", "jangan kasih chart", "jangan tampilin chart",
            "chart hide", "matikan chart", "matikan grafik",
        ]
        if any(trig in lower for trig in pref_hide_chart):
            return IntentRequest(
                intent="PREFERENCE",
                request_type="PREFERENCE",
                preference_action="hide_chart",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE",
            )

        pref_show_chart = [
            "tampilkan chart lagi", "show chart", "chart on", "aktifkan chart",
            "grafik on", "chart show", "munculkan chart", "tampilin chart lagi",
        ]
        if any(trig in lower for trig in pref_show_chart):
            return IntentRequest(
                intent="PREFERENCE",
                request_type="PREFERENCE",
                preference_action="show_chart",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE",
            )

        # 2d. Preferences: Ollama toggle
        pref_ollama_triggers = [
            r"\b(?:jangan\s+pakai|no|tanpa|bukan)\s+ollama\b",
            r"\bjangan\s+(?:pake|gunakan)\s+ollama\b",
            r"\bga\s+usah\s+ollama\b",
        ]
        if any(re.search(trig, lower) for trig in pref_ollama_triggers):
            return IntentRequest(
                intent="PREFERENCE",
                request_type="PREFERENCE",
                preference_action="no_ollama",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE",
            )

        # 2e. Setup Config requests
        setup_triggers = [
            r"\b(?:kasih|pakai|download|install|pasang)\s+(?:model\s+)?llm\b",
            r"\bllm\s+lokal\b",
            r"\bspek(?:nya)?\s+dibawah\b",
            r"\bsetup\s+model\b",
            r"\bsetup\s+llm\b",
            r"\bqwen\b",
        ]
        if any(re.search(trig, lower) for trig in setup_triggers):
            return IntentRequest(
                intent="SYSTEM_INFO",
                request_type="SETUP_CONFIG",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="UNRELATED",
            )

        # 2f. System Info requests
        sys_triggers = [
            r"\babout\s+(?:sistem|system)\b",
            r"\btentang\s+(?:sistem|system|openbagus)\b",
            r"\bsiapa\s+pembuat\s+openbagus\b",
            r"\bsiapa\s+(?:yang\s+)?(?:buat|bikin|ciptakan)\s+openbagus\b",
            r"\bsiapa\s+pembuatnya\b",
            r"\bsiapa\s+yang\s+(?:buat|bikin)\b",
            r"\bwho\s+made\s+openbagus\b",
            r"\bcreator\s+openbagus\b",
            r"\banda\s+dijalankan\s+di\s+mana\b",
            r"\bkamu\s+jalan\s+dimana\b",
            r"\bdijalankan\s+di\s+mana\b",
            r"\bkamu\s+ini\s+apa\b",
            r"\bsiapa\s+kamu\b",
            r"\bsiapa\s+anda\b",
            r"\banda\s+siapa\b",
            r"\bprovider\s+apa\b",
            r"\bsumber\s+data\b",
            r"\bstatus\s+openbagus\b",
            r"\bwhat\s+is\s+openbagus\b",
            r"\bwhere\s+are\s+you\s+running\b",
            r"\bwhat\s+providers\s+do\s+you\s+use\b",
            r"\bsystem\s+info\b",
            r"\bruntime\s+info\b",
            r"\bkamu\s+pakai\s+model\s+apa\b",
            r"\bmodel\s+ai\b",
            r"\barsitektur\s+openbagus\b",
            r"\bai\s+lokal\b",
            r"\bapakah\s+sistem\b",
            r"\bsistem\s+ini\b",
        ]
        if any(re.search(trig, lower) for trig in sys_triggers):
            return IntentRequest(
                intent="SYSTEM_INFO",
                request_type="SYSTEM_INFO",
                timeframe=detected_tf,
                raw_query=text,
                system_query=cleaned,
                relation_to_context="UNRELATED",
            )

        # -------------------------------------------------------------
        # 3. Harness / Session Follow-up & Continuity
        # -------------------------------------------------------------
        harness_triggers = [
            r"\b(?:harness|hernes|herness|hernesnya+|harnessnya)\b",
            r"\bhern[es]+(?:nya+)?\b",
            r"\bharn[es]+(?:nya+)?\b",
            r"\bsession\s*memory\b",
            r"\bmemorynya\s*(?:disimpan|dimana|aktif)?\b",
            r"\bharness\s*aktif\b",
            r"\bmana\s+(?:harness|hernes|herness)",
        ]
        if any(re.search(trig, lower) for trig in harness_triggers):
            return IntentRequest(
                intent="SYSTEM_INFO",
                request_type="HARNESS",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="UNRELATED",
            )

        # Context continuity question (e.g. "ini masih nyambung sama BTC tadi nggak?")
        continuity_triggers = [
            r"\b(?:ini\s+)?masih\s+nyambung\b",
            r"\bada\s+hubungannya\b",
            r"\bhubungannya\s+apa\b",
            r"\bmasih\s+konek\b",
            r"\bnyambung\s+sama\b",
        ]
        if any(re.search(pat, lower) for pat in continuity_triggers):
            if session and session.last_asset:
                return IntentRequest(
                    intent="SYSTEM_INFO",
                    request_type="HARNESS",
                    asset=session.last_asset,
                    system_query="continuity_check",
                    timeframe=detected_tf,
                    raw_query=text,
                    relation_to_context="CONTINUE",
                )

        # Follow-up on previous asset without naming a new coin
        if session and session.last_asset:
            followup_level_triggers = [
                "tpnya", "risknya", "slnya", "entrynya", "tp nya", "risk nya", "sl nya",
                "tp", "sl", "take profit", "stop loss", "levels", "nggk ada",
                "nggak ada", "tidak ada", "kenapa", "kok", "alasannya", "kenapanya",
            ]
            followup_position_triggers = [
                "entry dimana", "entry tadi dimana", "entry di mana", "entry tadi di mana", "entry tadi",
                "masuk dimana", "bisa beli", "bisa serok", "enaknya long",
                "bagusnya long", "long apa short", "long or short", "beli sekarang",
            ]
            followup_outlook_triggers = [
                "gimana prospeknya", "prospeknya", "kondisinya", "pandangan", "analisanya",
            ]
            is_level_followup = any(trig in lower for trig in followup_level_triggers)
            is_pos_followup = any(trig in lower for trig in followup_position_triggers)
            is_out_followup = any(trig in lower for trig in followup_outlook_triggers)

            other_coins = [w.upper() for w in words if w.upper() in {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "NEAR"} and w.upper() != session.last_asset]
            if not other_coins and (is_level_followup or is_pos_followup or is_out_followup):
                req_type = "EXPLAIN_LEVELS" if is_level_followup else ("POSITION" if is_pos_followup else "FOLLOW_UP")
                intent_code = "STRUCTURE" if is_level_followup else ("POSITION" if is_pos_followup else "ANALYZE")
                return IntentRequest(
                    intent=intent_code,
                    request_type=req_type,
                    asset=session.last_asset,
                    target_assets=[session.last_asset],
                    timeframe=detected_tf,
                    raw_query=text,
                    relation_to_context="CONTINUE",
                )

        # -------------------------------------------------------------
        # 3b. Deterministic Asset Comparison Detection (e.g. BTC vs ETH, compare BTC ETH)
        # Prioritized BEFORE LLM to ensure comparison never triggers switch prompt
        # -------------------------------------------------------------
        comp_c1, comp_c2 = None, None
        vs_m = re.search(r"\b([A-Za-z0-9]+)\s+(?:vs|versus|v)\s+([A-Za-z0-9]+)\b", query_no_tf, re.IGNORECASE)
        if vs_m:
            comp_c1, comp_c2 = vs_m.group(1), vs_m.group(2)
        elif any(k in lower for k in ("bandingkan", "compare", "komparasi")):
            cand_assets = []
            for w in words:
                wl = w.lower()
                if wl not in COMPREHENSIVE_STOP_WORDS and wl not in DEX_SLANG_EXCLUSIONS and wl not in ("bandingkan", "compare", "komparasi", "versus", "vs", "dengan", "dan", "and", "with"):
                    a_obj, _ = self.catalog.resolve_asset(w)
                    if a_obj and a_obj.symbol not in cand_assets:
                        cand_assets.append(a_obj.symbol)
            if len(cand_assets) >= 2:
                comp_c1, comp_c2 = cand_assets[0], cand_assets[1]

        if comp_c1 and comp_c2:
            a1, _ = self.catalog.resolve_asset(comp_c1)
            a2, _ = self.catalog.resolve_asset(comp_c2)
            if a1 and a2:
                return IntentRequest(
                    intent="COMPARE",
                    request_type="COMPARE",
                    asset=a1.symbol,
                    asset_2=a2.symbol,
                    target_assets=[a1.symbol, a2.symbol],
                    timeframe=detected_tf,
                    focus="compare",
                    raw_query=text,
                    needs_topic_switch_confirmation=False,
                    relation_to_context="CONTINUE",
                )

        # -------------------------------------------------------------
        # 4. Local Language Model Intent Interpretation
        # For free-form / ambiguous natural language queries
        # -------------------------------------------------------------
        if self.local_llm.is_available() and len(words) > 1 and not cleaned.startswith("/"):
            session_ctx = {
                "last_asset": session.last_asset if session else None,
                "last_market": session.market_type if session else "PERPETUAL",
                "last_timeframe": detected_tf,
                "last_request_type": getattr(session, "last_intent", "ANALYZE") if session else None,
            }
            llm_res = self.local_llm.interpret_intent(cleaned, session_context=session_ctx)
            if llm_res and llm_res.get("request_type") and llm_res["request_type"] != "UNKNOWN":
                req_t = llm_res["request_type"]
                relation = llm_res.get("relation_to_context", "UNCERTAIN")
                cand_asset = llm_res.get("asset")
                verified_asset = None
                if cand_asset and req_t in ("ANALYZE", "POSITION", "RISK", "COMPARE", "CHART", "MARKET_OUTLOOK"):
                    a_obj, _ = self.catalog.resolve_asset(str(cand_asset))
                    if a_obj:
                        asset_names = [a_obj.symbol.lower(), a_obj.name.lower()] + [al.lower() for al in a_obj.aliases]
                        if any(re.search(rf"\b{re.escape(an)}\b", lower) for an in asset_names if len(an) >= 2):
                            verified_asset = a_obj.symbol

                tf = llm_res.get("timeframe") or detected_tf
                mkt = "perpetual" if re.search(r"\b(?:perp|perpetual|futures|long|short|leverage|open\s+position)\b", lower_no_tf) else "all"
                topic = llm_res.get("topic")

                if req_t == "HARNESS":
                    if any(k in lower for k in ("harness", "herness", "memory", "state", "nyambung", "konteks")):
                        return IntentRequest(intent="SYSTEM_INFO", request_type="HARNESS", timeframe=tf, raw_query=text, relation_to_context=relation)
                elif req_t == "FEEDBACK":
                    if any(re.search(pat, lower) for pat in feedback_triggers):
                        return IntentRequest(intent="FEEDBACK", request_type="FEEDBACK", asset=session.last_asset if session else None, timeframe=tf, raw_query=text, relation_to_context="CONTINUE")
                elif req_t == "SYSTEM_INFO":
                    if any(re.search(trig, lower) for trig in sys_triggers):
                        return IntentRequest(intent="SYSTEM_INFO", request_type="SYSTEM_INFO", timeframe=tf, raw_query=text, system_query=cleaned, relation_to_context="UNRELATED")
                elif req_t == "SETUP_CONFIG":
                    if any(re.search(trig, lower) for trig in setup_triggers):
                        return IntentRequest(intent="SYSTEM_INFO", request_type="SETUP_CONFIG", timeframe=tf, raw_query=text, relation_to_context="UNRELATED")
                elif req_t == "PREFERENCE":
                    if any(k in lower for k in ("sources", "sumber", "chart", "grafik", "ollama", "hide", "sembunyikan")):
                        return IntentRequest(intent="PREFERENCE", request_type="PREFERENCE", timeframe=tf, raw_query=text, relation_to_context=relation)
                elif req_t == "CHART":
                    if any(k in lower for k in ("chart", "grafik", "candle")):
                        chart_target = verified_asset or (session.last_asset if session else None)
                        if chart_target:
                            return IntentRequest(intent="CHART", request_type="CHART", asset=chart_target, timeframe=tf, raw_query=text, relation_to_context=relation)
                    elif verified_asset:
                        needs_sw = bool(session and session.last_asset and session.last_asset != verified_asset and not cleaned.lower().startswith("/switch"))
                        return IntentRequest(
                            intent="ANALYZE",
                            request_type="ASSET_ANALYSIS",
                            asset=verified_asset,
                            target_assets=[verified_asset],
                            market=mkt,
                            timeframe=tf,
                            raw_query=text,
                            relation_to_context="SWITCH" if needs_sw else relation,
                            needs_topic_switch_confirmation=needs_sw,
                            switch_target_asset=verified_asset if needs_sw else None,
                        )
                elif (req_t == "MARKET_OUTLOOK" or topic == "macro") and any(k in lower for k in ("cpi", "fomc", "macro", "makro", "inflasi", "outlook", "pasar", "market", "fed")):
                    macro_target = verified_asset or (session.last_asset if session else "BTC")
                    return IntentRequest(intent="MARKET_OUTLOOK", request_type="MARKET_OUTLOOK", asset=macro_target, focus="macro", timeframe=tf, raw_query=text, relation_to_context=relation)
                elif topic == "large_flow" and any(k in lower for k in ("whale", "flow", "aliran", "dana", "mempool", "transaksi")):
                    flow_target = verified_asset or (session.last_asset if session else "BTC")
                    return IntentRequest(intent="ANALYZE", request_type="ASSET_ANALYSIS", asset=flow_target, focus="large_flow", timeframe=tf, raw_query=text, relation_to_context=relation)
                elif (req_t in ("ANALYZE", "POSITION", "RISK") or req_t == "MARKET_OUTLOOK") and verified_asset:
                    is_pos = (
                        req_t == "POSITION"
                        or any(k in lower for k in ("posisi", "posisinya", "open", "entry", "setup", "long", "short"))
                        or detected_tf != "H1"
                        or "h1" in lower
                    )
                    intent_code = "POSITION" if is_pos else ("RISK" if req_t == "RISK" else "ANALYZE")
                    req_type_code = "POSITION" if is_pos else "ASSET_ANALYSIS"
                    final_mkt = mkt
                    needs_sw = bool(session and session.last_asset and session.last_asset != verified_asset and intent_code != "COMPARE" and not cleaned.lower().startswith("/switch"))
                    return IntentRequest(
                        intent=intent_code,
                        request_type=req_type_code,
                        asset=verified_asset,
                        target_assets=[verified_asset],
                        market=final_mkt,
                        timeframe=tf,
                        raw_query=text,
                        relation_to_context="SWITCH" if needs_sw else relation,
                        needs_topic_switch_confirmation=needs_sw,
                        switch_target_asset=verified_asset if needs_sw else None,
                    )

        # -------------------------------------------------------------
        # 5. Explicit Chart, Macro, Large Flow, and Category Interpretation
        # -------------------------------------------------------------
        # Chart queries (e.g. "tampilkan chart btc h1", "kasih grafik eth h1", "chart sol")
        chart_match = re.search(r"\b(?:tampilkan\s+chart|kasih\s+grafik|chart|grafik)\s+([A-Za-z0-9]+)\b", query_no_tf, re.IGNORECASE)
        if not chart_match:
            chart_match = re.search(r"\b([A-Za-z0-9]+)\s+(?:chart|grafik)\b", query_no_tf, re.IGNORECASE)
        if chart_match:
            c_cand = chart_match.group(1)
            if c_cand.lower() not in COMPREHENSIVE_STOP_WORDS and c_cand.lower() not in DEX_SLANG_EXCLUSIONS:
                a_obj, _ = self.catalog.resolve_asset(c_cand)
                if a_obj:
                    return IntentRequest(
                        intent="CHART",
                        request_type="CHART",
                        asset=a_obj.symbol,
                        timeframe=detected_tf,
                        raw_query=text,
                        relation_to_context="SWITCH" if session and session.last_asset != a_obj.symbol else "CONTINUE",
                    )
        chart_phrases = {
            "chart", "grafik", "chartnya", "grafiknya", "chart dong", "chartnya dong",
            "grafik dong", "grafiknya dong", "tampilkan chart", "kasih grafik", "buka chart",
            "lihat chart", "tampilin chart", "open chart", "show chart", "tampilkan grafik",
        }
        stripped_lower = lower.strip("?!. ")
        if stripped_lower in chart_phrases or any(stripped_lower.startswith(p) for p in ("chartnya", "grafiknya", "buka chart", "lihat chart", "tampilin chart")):
            target_asset = session.last_asset if (session and session.last_asset) else "BTC"
            return IntentRequest(
                intent="CHART",
                request_type="CHART",
                asset=target_asset,
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE",
            )

        # Macro CPI / FOMC queries (e.g. "gimana CPI pengaruh ke BTC?", "cpi btc", "fomc eth")
        if re.search(r"\b(?:cpi|fomc)\b", lower):
            m_target = None
            for w in words:
                wl = w.lower()
                if wl not in COMPREHENSIVE_STOP_WORDS and wl not in DEX_SLANG_EXCLUSIONS and wl not in ("cpi", "fomc"):
                    a_obj, _ = self.catalog.resolve_asset(w)
                    if a_obj:
                        m_target = a_obj.symbol
                        break
            if not m_target:
                m_target = session.last_asset if (session and session.last_asset) else "BTC"
            return IntentRequest(
                intent="MARKET_OUTLOOK",
                request_type="MARKET_OUTLOOK",
                asset=m_target,
                focus="macro",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE" if session and session.last_asset == m_target else "SWITCH",
            )

        # Large Flow / Whale queries (e.g. "ada whale gerak?", "whale btc")
        if re.search(r"\b(?:whale|aliran\s+dana|large\s*flow)\b", lower):
            w_target = None
            for w in words:
                wl = w.lower()
                if wl not in COMPREHENSIVE_STOP_WORDS and wl not in DEX_SLANG_EXCLUSIONS and wl not in ("whale", "flow"):
                    a_obj, _ = self.catalog.resolve_asset(w)
                    if a_obj:
                        w_target = a_obj.symbol
                        break
            if not w_target:
                w_target = session.last_asset if (session and session.last_asset) else "BTC"
            return IntentRequest(
                intent="ANALYZE",
                request_type="ASSET_ANALYSIS",
                asset=w_target,
                focus="large_flow",
                timeframe=detected_tf,
                raw_query=text,
                relation_to_context="CONTINUE" if session and session.last_asset == w_target else "SWITCH",
            )

        # -------------------------------------------------------------
        # 6. Explicit Category / Screening Requests
        # -------------------------------------------------------------
        screen_triggers = [
            "koin yang high 1 kuartal terakhir", "koin performa terbaik", "top gainers",
            "koin volume besar", "screen crypto", "daftar koin high", "koin potensial",
        ]
        if any(trig in lower for trig in screen_triggers):
            return IntentRequest(
                intent="SCREEN",
                request_type="SCREEN",
                timeframe=detected_tf,
                raw_query=text,
            )

        # Category request MUST be an exact match or explicit prefix ("kategori AI", "list DeFi")
        cat_matched: str | None = None
        exact_cats = {c.lower(): c for c in TAXONOMY_CATEGORIES if c.lower() not in ("other / unknown", "bitcoin")}
        stripped_lower = cleaned.strip("? !.").lower()
        if stripped_lower in exact_cats:
            cat_matched = exact_cats[stripped_lower]
        else:
            for cat_l, cat_orig in exact_cats.items():
                cat_regex = (
                    rf"\b(?:kategori|category|sektor|sector|list|daftar)\s+{re.escape(cat_l)}\b|"
                    rf"\b{re.escape(cat_l)}\s+(?:kategori|category|sektor|sector|list|daftar|coins?|tokens?)\b|"
                    rf"\b(?:coin|koin|token)\s+{re.escape(cat_l)}\b"
                )
                if re.search(cat_regex, lower):
                    cat_matched = cat_orig
                    break

        if cat_matched:
            return IntentRequest(
                intent="CATEGORY",
                request_type="CATEGORY",
                category=cat_matched,
                timeframe=detected_tf,
                raw_query=text,
            )


        # -------------------------------------------------------------
        # 6. Typo correction for crypto vocabulary
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
        # 7. Explicit Asset Resolution
        # -------------------------------------------------------------
        asset: str | None = None
        asset_2: str | None = None
        target_assets: list[str] = []
        explicit_crypto = bool(re.search(r"\b(?:crypto|kripto|koin|coin|token|analyze|analisa|analisis|review)\b", lower))
        known_asset = any(w.lower() in {a.symbol.lower(), a.name.lower(), a.id.lower(), *[v.lower() for v in a.aliases]}
                          for w in words for a in self.catalog.assets)
        research_words = bool(re.search(r"\b(?:entry|risk|risiko|support|resistance|position|posisi|long|short|funding|prospek)\b", lower))
        if not (explicit_crypto or known_asset or research_words):
            return IntentRequest(intent="UNKNOWN", request_type="UNKNOWN", raw_query=text,
                                 relation_to_context="UNRELATED")

        # Check explicit preposition/directive target: "di ADA", "pada BTC", "koin SOL", "token DOGE", "analyze TOLOL"
        prep_match = re.search(r"\b(?:di|pada|koin|coin|token|analyze)\s+([A-Za-z0-9]+)\b", query_no_tf, re.IGNORECASE)
        if prep_match:
            candidate = prep_match.group(1)
            if candidate.lower() not in COMPREHENSIVE_STOP_WORDS:
                a_obj, amb = self.catalog.resolve_asset(candidate, is_explicit=True)
                if amb:
                    return IntentRequest(intent="ANALYZE", request_type="ASSET_ANALYSIS", is_ambiguous=True, candidates=[a.id for a in amb[:5]], raw_query=text)
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]

        # Check standalone token or exact query (e.g. "ADA", "BTC", "SOL", "NEAR", "Manta")
        if not asset:
            stripped_clean = query_no_tf.strip("? !.").upper()
            if stripped_clean == "ADA":
                asset = "ADA"
                target_assets = ["ADA"]
            elif len(words) == 1 and stripped_clean.lower() not in COMPREHENSIVE_STOP_WORDS and stripped_clean.lower() not in DEX_SLANG_EXCLUSIONS:
                a_obj, amb = self.catalog.resolve_asset(words[0])
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]
                elif amb:
                    return IntentRequest(
                        intent="ANALYZE",
                        request_type="ASSET_ANALYSIS",
                        is_ambiguous=True,
                        candidates=[a.id for a in amb[:5]],
                        timeframe=detected_tf,
                        raw_query=text,
                    )

        # Multi-token scan strictly excluding COMPREHENSIVE_STOP_WORDS and DEX_SLANG_EXCLUSIONS
        if not asset:
            for orig_w, clean_w in zip(words, clean_tokens):
                orig_lower = orig_w.lower()
                clean_lower = clean_w.lower()
                if orig_lower in COMPREHENSIVE_STOP_WORDS or clean_lower in COMPREHENSIVE_STOP_WORDS:
                    continue
                if orig_lower in DEX_SLANG_EXCLUSIONS or clean_lower in DEX_SLANG_EXCLUSIONS:
                    continue
                if orig_lower == "ada":  # Indonesian "ada" protection
                    continue
                if not explicit_crypto and not any(orig_lower in {a.symbol.lower(), a.name.lower(), a.id.lower(), *[v.lower() for v in a.aliases]} for a in self.catalog.assets):
                    continue
                a_obj, _ = self.catalog.resolve_asset(orig_w, is_explicit=explicit_crypto)
                if not a_obj:
                    a_obj, _ = self.catalog.resolve_asset(clean_w, is_explicit=explicit_crypto)
                if a_obj:
                    asset = a_obj.symbol
                    target_assets = [a_obj.symbol]
                    break

        # -------------------------------------------------------------
        # 8. Conversational Follow-Up on Previous Asset (if no new asset)
        # -------------------------------------------------------------
        if not asset and session and session.last_asset:
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
                    timeframe=detected_tf,
                    raw_query=text,
                )

        # -------------------------------------------------------------
        # 9. Market-Wide Outlook Classification (if no asset)
        # -------------------------------------------------------------
        if not asset:
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
                    timeframe=detected_tf,
                    raw_query=text,
                )

        # -------------------------------------------------------------
        # 10. Intent & Request Type Classification for Asset Query
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
        elif re.search(r"\b(?:long|short)\b", norm_text) or any(k in norm_text for k in [
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
        elif any(k in norm_text for k in [
            "position", "posisi", "posisinya", "entry", "entry dimana", "masuk dimana", "setup", "trade setup", "open posisi", "open position",
        ]):
            intent = "POSITION"
            focus = "setup"
            request_type = "POSITION"
            market = "perpetual" if re.search(r"\bopen\s+(?:position|posisi)\b", norm_text) else "all"
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
        elif detected_tf != "H1" or "h1" in lower:
            # Query explicitly specifying timeframe like "gimana BTC h1?" or "BTC H4"
            intent = "POSITION"
            focus = "setup"
            market = "all"
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
                needs_switch = False
                target_switch = None
                return IntentRequest(
                    intent="UNKNOWN",
                    request_type="UNKNOWN",
                    timeframe=detected_tf,
                    raw_query=text,
                    needs_topic_switch_confirmation=needs_switch,
                    switch_target_asset=target_switch,
                )

        needs_switch = False
        target_switch = None
        if asset and session and session.last_asset and session.last_asset != asset and intent != "COMPARE":
            if not cleaned.lower().startswith("/switch"):
                needs_switch = True
                target_switch = asset

        return IntentRequest(
            intent=intent,
            request_type=request_type,
            asset=asset,
            asset_2=asset_2,
            target_assets=target_assets,
            market=market,
            timeframe=detected_tf,
            focus=focus,
            needs_asset=needs_asset,
            clarification_prompt=clarification_prompt,
            equity=equity_val,
            risk_pct=risk_pct_val,
            needs_capital_inputs=needs_capital_inputs,
            raw_query=text,
            needs_topic_switch_confirmation=needs_switch,
            switch_target_asset=target_switch,
            relation_to_context="SWITCH" if needs_switch else "CONTINUE",
        )
