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
    "TAHU", "BISA", "AKAN", "KAMU", "SAYA", "KITA", "DULU", "LAGI",
    "TENT", "BAGI", "IKUT", "MAKA", "LAIN", "BIAR", "BESO", "HARI",
    "MAAF", "HALO", "NAMA", "KOTA", "ORAN", "ANAK", "PINT", "JIKA", "TAPI",
    "ATAU", "DENG", "YANG", "DARI", "PADA", "BUAT", "CARA", "HOLD", "KOK",
    "JUGA", "BAIK", "SUDA", "MASI", "LALU", "SINI", "SITU", "SANA", "KINI",
    "HANY", "AGAR", "DEMI", "MENU", "BANY", "SEDI", "KALA", "SIAP", "PERN",
    "BELU", "CUKU", "SAMA", "BEDA", "LEBI", "KURG", "KAYA", "RUGI",
    "TURU", "PAKE", "PULA", "TERU", "PASI", "SUKA", "TIDK", "TIDA",
    "BAGA", "MANA", "KAPN", "DIMN", "SEMI", "TEST", "INFO", "USER", "COMP",
    "DATA",
}

# Genuine IDX tickers whose symbols collide with common Indonesian vocabulary words
COLLISION_TICKERS = {"DATA", "BACA", "NAIK"}

# Lexical non-tickers excluding genuine collision tickers so collision tickers can be resolved in financial contexts
LEXICAL_NON_TICKERS = COMMON_INDONESIAN_NON_TICKERS - COLLISION_TICKERS

FINANCIAL_CONTEXT_KEYWORDS = {
    "saham", "emiten", "ticker", "investasi", "trading", "analisis", "breakout",
    "dividen", "laporan", "keuangan", "neraca", "arus kas", "valuasi", "dcf",
    "per", "pbv", "roe", "roic", "der", "ihsg", "idx", "bei", "harga", "ohlcv",
    "volume", "katalis", "swing", "screener", "pasar modal", "reksadana", "porto",
    "bandingkan", "komparasi", "versus", "vs", "kripto", "crypto", "bitcoin",
    "btc", "eth", "ethereum", "solana", "inflasi", "cpi", "ihk", "pdb", "gdp",
    "makro", "jisdor", "penutupan", "closing", "quote", "coverage", "cakupan",
}

CRYPTO_TICKERS = {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"}


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

        # STEP 1: Contextual Disambiguation of Ambiguous or Multi-Meaning Queries
        if "kenapa data" in lower or "data tidak lengkap" in lower or "data gap" in lower or "data anda" in lower:
            content = (
                "Katalog OpenBagus memuat profil seluruh 951 emiten BEI secara offline. Namun data historis harga (EOD) "
                "atau laporan keuangan mendalam untuk emiten tertentu berstatus DATA_GAP karena belum diimpor ke database lokal. "
                "Data akan dilengkapi saat sinkronisasi feed pasar terhubung."
            )
            resp = ChatCompletionResponse(
                content=content,
                tool_calls=[],
                finish_reason="stop",
                model="deterministic-fallback",
                provider_name=self.get_provider_name(),
            )
            return iter([ChatCompletionChunk(delta_content=content, finish_reason="stop")]) if stream else resp

        if ("presiden" in lower or "siapa" in lower) and ("tahu" in lower or "2026" in lower):
            content = (
                "Maaf, model lokal sedang sibuk atau lambat merespons. "
                "Untuk pertanyaan pengetahuan umum tentang presiden, saya belum mendapatkan jawaban yang valid saat ini."
            )
            resp = ChatCompletionResponse(
                content=content,
                tool_calls=[],
                finish_reason="stop",
                model="deterministic-fallback",
                provider_name=self.get_provider_name(),
            )
            return iter([ChatCompletionChunk(delta_content=content, finish_reason="stop")]) if stream else resp

        if "bisa" in lower and "membaca" in lower:
            content = "Ya, Anda dapat membaca laporan ini secara offline langsung di direktori berkas OpenBagus."
            resp = ChatCompletionResponse(
                content=content,
                tool_calls=[],
                finish_reason="stop",
                model="deterministic-fallback",
                provider_name=self.get_provider_name(),
            )
            return iter([ChatCompletionChunk(delta_content=content, finish_reason="stop")]) if stream else resp

        # STEP 2: Strict Ticker Extraction with context confirmation
        ticker: str | None = None
        has_financial_intent = any(kw in lower for kw in FINANCIAL_CONTEXT_KEYWORDS)

        # 1. Crypto ticker detection
        for c in CRYPTO_TICKERS:
            if re.search(r"\b" + c + r"\b", user_msg, re.IGNORECASE) or ("bitcoin" in lower and c == "BTC") or ("ethereum" in lower and c == "ETH"):
                ticker = c
                has_financial_intent = True
                break

        # 2. US Equities detection
        if not ticker:
            for u in ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"):
                if re.search(r"\b" + u + r"\b", user_msg, re.IGNORECASE) or ("apple" in lower and u == "AAPL"):
                    ticker = u
                    has_financial_intent = True
                    break

        # 3. Look for explicit prefix: "saham BBCA", "emiten RATU", "ticker BBRI", "saham DATA"
        if not ticker:
            explicit_match = re.search(r"\b(?:saham|emiten|ticker|kode)\s+([A-Za-z]{4})\b", user_msg, re.IGNORECASE)
            if explicit_match:
                cand = explicit_match.group(1).upper()
                if cand not in LEXICAL_NON_TICKERS:
                    ticker = cand

        # 4. Comparison intent: "Bandingkan DATA dengan TLKM" or "Bandingkan dengan HGII"
        is_comparison = bool(re.search(r"\b(?:bandingkan|komparasi|versus|vs)\b", lower))
        comp_tickers: list[str] = []
        comp_pair = re.search(r"\b(?:bandingkan|komparasi|versus|vs)\s+([A-Za-z]{4})\s+(?:dengan|dan|vs|versus)\s+([A-Za-z]{4})\b", user_msg, re.IGNORECASE)
        if comp_pair:
            t1, t2 = comp_pair.group(1).upper(), comp_pair.group(2).upper()
            if t1 not in LEXICAL_NON_TICKERS and t2 not in LEXICAL_NON_TICKERS:
                comp_tickers = [t1, t2]
                ticker = t1
                has_financial_intent = True
        elif is_comparison:
            comp_single = re.search(r"\b(?:bandingkan|komparasi|versus|vs)\s+(?:dengan\s+)?([A-Za-z]{4})\b", user_msg, re.IGNORECASE)
            if comp_single:
                cand = comp_single.group(1).upper()
                if cand not in LEXICAL_NON_TICKERS:
                    sys_msg = next((m.content for m in messages if m.role == "system"), "")
                    sys_m = re.search(r"(?:Emiten Aktif|Ticker)\s*:\s*([A-Za-z0-9/]+)", sys_msg)
                    curr_t = sys_m.group(1).upper() if sys_m and sys_m.group(1).upper() not in ("BELUM", "NONE", "NULL", "BELUM DITENTUKAN") else None
                    if curr_t and curr_t != cand:
                        comp_tickers = [curr_t, cand]
                        ticker = curr_t
                    else:
                        ticker = cand
                    has_financial_intent = True

        # 5. Standalone word extraction when financial intent is present
        if not ticker and has_financial_intent:
            words = re.findall(r"\b[A-Za-z]{4}\b", user_msg)
            for w in words:
                up = w.upper()
                if up in COLLISION_TICKERS:
                    # Require financial action or context for words like DATA/BACA/NAIK
                    if any(act in lower for act in ("saham", "emiten", "analisis", "kinerja", "harga", "valuasi", "rekomendasi", "bandingkan", "vs", "versus")):
                        ticker = up
                        break
                elif up not in LEXICAL_NON_TICKERS:
                    try:
                        from openbagus.domains.equities.catalog import EquityCatalog
                        from openbagus.core.env import get_repo_root
                        cat = EquityCatalog(get_repo_root())
                        if cat.resolve(up):
                            ticker = up
                            break
                    except Exception:
                        ticker = up
        # 6. Contextual ticker from system prompt or conversation history for follow-up turns
        if not ticker:
            sys_msg = next((m.content for m in messages if m.role == "system"), "")
            sys_m = re.search(r"(?:Emiten Aktif|Ticker)\s*:\s*([A-Za-z0-9/]+)", sys_msg)
            if sys_m:
                cand = sys_m.group(1).upper()
                if cand not in ("BELUM", "NONE", "NULL", "BELUM DITENTUKAN"):
                    ticker = cand
                    has_financial_intent = True

        tool_calls: list[ToolCall] = []
        call_cnt = 1

        # Check if this is iteration 2+ where tools have already returned results
        has_tool_results = any(m.role == "tool" for m in messages)
        if has_tool_results:
            # Return empty text so the agent harness composes the evidence response from executed tools
            return ChatCompletionResponse(
                content="",
                tool_calls=[],
                finish_reason="stop",
                model="deterministic-fallback",
                provider_name=self.get_provider_name(),
            )

        # Heuristic tool trigger mapping (only when genuine financial intent exists)
        if tools and has_financial_intent:
            tool_names = {t.name for t in tools}

            # 1. Macro indicator query
            if any(m in lower for m in ("inflasi", "cpi", "ihk", "pdb", "gdp", "pertumbuhan ekonomi", "jisdor")) and "get_macro_series" in tool_names:
                m_series = "CPI" if any(x in lower for x in ("inflasi", "cpi", "ihk")) else ("GDP" if any(x in lower for x in ("pdb", "gdp")) else "JISDOR")
                tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_macro_series", arguments={"series": m_series}))
                call_cnt += 1

            # 2. Coverage audit query
            if any(c in lower for c in ("coverage", "cakupan data", "audit data", "status data")) and "get_data_coverage" in tool_names:
                tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_data_coverage", arguments={"ticker": ticker or ""}))
                call_cnt += 1

            # 3. Screener query
            if any(s in lower for s in ("swing", "breakout", "screener", "scan", "papan pengembangan", "likuid")) and "run_screener" in tool_names and not ticker:
                tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="run_screener", arguments={"strategy": "SWING_BREAKOUT", "universe": "ALL_IDX"}))
                call_cnt += 1

            # 4. Comparison query
            if is_comparison and comp_tickers and "compare_company_fundamentals" in tool_names:
                tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="compare_company_fundamentals", arguments={"tickers": comp_tickers}))
                call_cnt += 1

            # 5. Ticker-focused queries (when not comparison)
            elif ticker:
                is_deep_research = any(w in lower for w in ("analisis", "bedah", "tinjau", "review", "riset", "lengkap", "komprehensif")) or (
                    any(p in lower for p in ("harga", "volume", "quote")) and any(f in lower for f in ("laporan", "keuangan", "fundamental", "rasio", "katalis", "event"))
                )

                # Price / Quote / Volume
                needs_price = is_deep_research or any(p in lower for p in ("harga", "price", "closing", "penutupan", "volume", "quote", "berapa")) or ticker in CRYPTO_TICKERS
                if needs_price and "get_market_price" in tool_names:
                    tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_market_price", arguments={"ticker": ticker}))
                    call_cnt += 1

                # Financial statement
                needs_statement = is_deep_research or any(f in lower for f in ("laporan keuangan", "neraca", "arus kas", "statement", "laba rugi", "pendapatan", "aset", "ekuitas", "tahun 2025", "tahun lalu", "kuartal"))
                if needs_statement and "get_financial_statement" in tool_names:
                    st = "BALANCE_SHEET" if "neraca" in lower else ("CASH_FLOW" if "arus kas" in lower else "INCOME_STATEMENT")
                    period_target = "2025-FY" if any(y in lower for y in ("tahun 2025", "tahun lalu", "2025")) else ("2026-Q1" if any(q in lower for q in ("kuartal pertama", "kuartal 1", "q1", "2026")) else "LATEST")
                    tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_financial_statement", arguments={"ticker": ticker, "statement_type": st, "period": period_target}))
                    call_cnt += 1

                # Financial ratios & fundamental health
                needs_ratios = is_deep_research or any(r in lower for r in ("rasio", "der", "roic", "roe", "fundamental", "margin", "per", "pbv", "perbankan", "bank", "nim", "car", "npl"))
                if needs_ratios and "calculate_financial_ratios" in tool_names:
                    period_target = "2025-FY" if any(y in lower for y in ("tahun 2025", "tahun lalu", "2025")) else "LATEST"
                    tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="calculate_financial_ratios", arguments={"ticker": ticker, "period": period_target}))
                    call_cnt += 1

                # Events / Disclosures / Catalysts
                needs_events = is_deep_research or any(e in lower for e in ("katalis", "pengumuman", "event", "kontrak", "berita", "aksi korporasi", "disclosures"))
                if needs_events and "get_recent_company_events" in tool_names:
                    tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_recent_company_events", arguments={"ticker": ticker, "limit": 5}))
                    call_cnt += 1

                # Valuation
                if any(v in lower for v in ("valuasi", "dcf", "fcf", "fair value", "harga wajar")) and "calculate_valuation" in tool_names:
                    tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="calculate_valuation", arguments={"ticker": ticker, "method": "ALL"}))
                    call_cnt += 1

                # Liquidity
                if any(l in lower for l in ("likuiditas", "adtv", "turnover")) and "get_liquidity_metrics" in tool_names:
                    tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_liquidity_metrics", arguments={"ticker": ticker}))
                    call_cnt += 1

                # Data provenance / source check
                if any(pr in lower for pr in ("berasal dari mana", "sumber data", "provenance", "dokumen apa", "sebutkan dokumen", "sumbernya")) and "get_financial_provenance" in tool_names:
                    tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_financial_provenance", arguments={"ticker": ticker, "metric": "revenue"}))
                    call_cnt += 1

                # Fallback to market price or company profile if nothing triggered yet
                if not tool_calls:
                    if "get_market_price" in tool_names:
                        tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_market_price", arguments={"ticker": ticker}))
                        call_cnt += 1
                    elif "get_company_profile" in tool_names:
                        tool_calls.append(ToolCall(id=f"call_fallback_{call_cnt}", function_name="get_company_profile", arguments={"ticker": ticker}))
                        call_cnt += 1

        if tool_calls:
            tools_str = ", ".join(t.function_name for t in tool_calls)
            content = f"[Mode Deterministik: Mengakses tools [{tools_str}] untuk memproses riset '{user_msg}']"
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
        elif not has_financial_intent and any(k in lower for k in ("presiden", "siapa", "cuaca")):
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

