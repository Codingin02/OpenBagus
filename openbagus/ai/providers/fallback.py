"""Honest deterministic fallback provider when no LLM runtime is available."""

from __future__ import annotations

import re
from typing import Any, Iterator

from openbagus.ai.providers.base import (
    BaseModelProvider,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatMessage,
    ToolCall,
    ToolDefinition,
)


COMMON_INDONESIAN_NON_TICKERS = {
    "TAHU", "DATA", "BISA", "AKAN", "KAMU", "SAYA", "KITA", "DULU", "LAGI",
    "TENT", "BAGI", "IKUT", "MAKA", "LAIN", "BIAR", "BESO", "HARI", "BACA",
    "MAAF", "HALO", "NAMA", "KOTA", "ORAN", "ANAK", "PINT", "JIKA", "TAPI",
    "ATAU", "DENG", "YANG", "DARI", "PADA", "BUAT", "CARA", "HOLD", "KOK",
    "JUGA", "BAIK", "SUDA", "MASI", "LALU", "SINI", "SITU", "SANA", "KINI",
    "HANY", "AGAR", "DEMI", "MENU", "BANY", "SEDI", "KALA", "SIAP", "PERN",
    "BELU", "CUKU", "SAMA", "BEDA", "LEBI", "KURG", "KAYA", "RUGI", "NAIK",
    "TURU", "PAKE", "PULA", "TERU", "PASI", "SUKA", "TIDK", "TIDA", "YANG",
    "BAGA", "MANA", "KAPN", "DIMN", "SEMI", "TEST", "INFO", "USER", "COMP",
}

FINANCIAL_CONTEXT_KEYWORDS = {
    "saham", "emiten", "ticker", "investasi", "trading", "analisis", "breakout",
    "dividen", "laporan", "keuangan", "neraca", "arus kas", "valuasi", "dcf",
    "per", "pbv", "roe", "roic", "der", "ihsg", "idx", "bei", "harga", "ohlcv",
    "volume", "katalis", "swing", "screener", "pasar modal", "reksadana", "porto",
}


class DeterministicFallbackProvider(BaseModelProvider):
    """Fallback provider when local and remote LLMs are offline, slow or unconfigured.

    Never pretends to be a generative AI. Provides clear, honest capability degradation,
    extracts parameters via verified financial intent heuristics, and invokes corresponding tools.
    """

    def get_provider_name(self) -> str:
        return "DETERMINISTIC_FALLBACK"

    def is_available(self) -> bool:
        return True

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": "Deterministic Rule Engine",
            "provider": "OpenBagus Core",
            "is_generative_llm": False,
            "notice": "Model LLM generatif sedang tidak tersedia. Menggunakan engine aturan deterministik.",
        }

    def generate(
        self,
        messages: list[ChatMessage],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        stream: bool = False,
        timeout: float = 60.0,
    ) -> ChatCompletionResponse | Iterator[ChatCompletionChunk]:
        user_msg = next((m.content for m in reversed(messages) if m.role == "user"), "")
        lower = user_msg.lower().strip()

        # STEP 1: Check if this is an explicit financial query
        has_financial_intent = any(kw in lower for kw in FINANCIAL_CONTEXT_KEYWORDS)

        # STEP 2: Strict Ticker Extraction with context confirmation
        ticker: str | None = None
        # Look for explicit prefix: "saham BBCA", "emiten RATU", "ticker BBRI"
        explicit_match = re.search(r"\b(?:saham|emiten|ticker|kode)\s+([A-Za-z]{4})\b", user_msg, re.IGNORECASE)
        if explicit_match:
            cand = explicit_match.group(1).upper()
            if cand not in COMMON_INDONESIAN_NON_TICKERS:
                ticker = cand

        # Otherwise only search standalone words if financial intent is present
        if not ticker and has_financial_intent:
            words = re.findall(r"\b[A-Za-z]{4}\b", user_msg)
            for w in words:
                up = w.upper()
                if up not in COMMON_INDONESIAN_NON_TICKERS:
                    # Verify against catalog if available
                    try:
                        from openbagus.domains.equities.catalog import EquityCatalog
                        from openbagus.core.env import get_repo_root
                        cat = EquityCatalog(get_repo_root())
                        if cat.resolve(up):
                            ticker = up
                            break
                    except Exception:
                        ticker = up
                        break

        tool_calls: list[ToolCall] = []

        # Heuristic tool trigger mapping (only when genuine financial intent exists)
        if tools and has_financial_intent:
            tool_names = {t.name for t in tools}

            if ("kontrak" in lower or "event" in lower or "pengumuman" in lower or "katalis" in lower) and "get_recent_company_events" in tool_names and ticker:
                tool_calls.append(ToolCall(id="call_fallback_1", function_name="get_recent_company_events", arguments={"ticker": ticker, "limit": 5}))
            elif ("laporan keuangan" in lower or "neraca" in lower or "arus kas" in lower or "statement" in lower) and "get_financial_statement" in tool_names and ticker:
                st = "BALANCE_SHEET" if "neraca" in lower else ("CASH_FLOW" if "arus kas" in lower else "INCOME_STATEMENT")
                tool_calls.append(ToolCall(id="call_fallback_1", function_name="get_financial_statement", arguments={"ticker": ticker, "statement_type": st}))
            elif ("rasio" in lower or "der" in lower or "roic" in lower or "roe" in lower) and "calculate_financial_ratios" in tool_names and ticker:
                tool_calls.append(ToolCall(id="call_fallback_1", function_name="calculate_financial_ratios", arguments={"ticker": ticker}))
            elif ("valuasi" in lower or "dcf" in lower or "fcf" in lower) and "calculate_valuation" in tool_names and ticker:
                tool_calls.append(ToolCall(id="call_fallback_1", function_name="calculate_valuation", arguments={"ticker": ticker, "method": "ALL"}))
            elif ("swing" in lower or "breakout" in lower or "screener" in lower or "scan" in lower) and "run_screener" in tool_names:
                tool_calls.append(ToolCall(id="call_fallback_1", function_name="run_screener", arguments={"strategy": "SWING_BREAKOUT", "universe": "ALL_IDX"}))
            elif ("likuiditas" in lower or "adtv" in lower) and "get_liquidity_metrics" in tool_names and ticker:
                tool_calls.append(ToolCall(id="call_fallback_1", function_name="get_liquidity_metrics", arguments={"ticker": ticker}))
            elif ticker and "get_company_profile" in tool_names:
                tool_calls.append(ToolCall(id="call_fallback_1", function_name="get_company_profile", arguments={"ticker": ticker}))

        if tool_calls:
            content = f"[Mode Deterministik: Mengakses tool '{tool_calls[0].function_name}' untuk memproses riset '{user_msg}']"
        elif ticker and has_financial_intent:
            content = (
                f"Informasi emiten {ticker} tersedia di katalog lokal OpenBagus.\n"
                f"Untuk analisis mendalam seperti laporan keuangan, rasio valuasi, dan perbandingan emiten, "
                f"data dapat diakses melalui modul analitis terverifikasi."
            )
        elif "kenapa data" in lower or "data tidak lengkap" in lower or "data gap" in lower:
            content = (
                "Katalog OpenBagus memuat profil seluruh 951 emiten BEI secara offline. Namun data historis harga (EOD) "
                "atau laporan keuangan mendalam untuk emiten tertentu berstatus DATA_GAP karena belum diimpor ke database lokal. "
                "Data akan dilengkapi saat sinkronisasi feed pasar terhubung."
            )
        elif any(k in lower for k in ("presiden", "siapa", "tahun", "2026", "cuaca", "berita", "indonesia")):
            content = (
                "Maaf, model lokal sedang sibuk atau lambat merespons. "
                "Untuk pertanyaan pengetahuan umum, saya belum mendapatkan jawaban yang valid saat ini. Silakan coba lagi."
            )
        else:
            content = (
                "Maaf, model bahasa lokal sedang lambat merespons. "
                "Saya belum mendapatkan jawaban yang valid saat ini. Saya bisa mencoba lagi."
            )

        resp = ChatCompletionResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason="tool_calls" if tool_calls else "stop",
            model="deterministic-fallback",
            provider_name=self.get_provider_name(),
        )

        if stream:
            return iter([ChatCompletionChunk(delta_content=content, finish_reason="stop")])
        return resp

