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


class DeterministicFallbackProvider(BaseModelProvider):
    """Fallback provider when local and remote LLMs are offline or unconfigured.

    Never pretends to be a generative AI. Provides clear, honest capability degradation,
    extracts parameters via rule heuristics, and invokes corresponding registered tools.
    """

    def get_provider_name(self) -> str:
        return "DETERMINISTIC_FALLBACK"

    def is_available(self) -> bool:
        return True

    def get_model_info(self) -> dict[str, Any]:
        return {
            "model_name": "Deterministic Heuristic Engine",
            "provider": "OpenBagus Core",
            "is_generative_llm": False,
            "notice": "Model LLM lokal belum aktif. Menggunakan engine aturan deterministik.",
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
        lower = user_msg.lower()

        tool_calls: list[ToolCall] = []

        # Ticker extraction
        words = re.findall(r"\b[A-Z]{4}\b", user_msg.upper())
        ticker = words[0] if words else None

        # Heuristic tool trigger mapping
        if tools:
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
            content = f"[Mode Deterministik: Mengakses tool '{tool_calls[0].function_name}' untuk memproses query '{user_msg}']"
        elif ticker:
            content = (
                f"Berdasarkan analisis OpenBagus untuk {ticker}:\n"
                f"Data laporan keuangan, rasio valuasi, dan perbandingan emiten {ticker} dapat diakses melalui tools. "
                f"Emiten aktif saat ini tercatat sebagai {ticker}."
            )
        else:
            content = (
                "OpenBagus beroperasi dalam mode fallback deterministik karena model LLM generatif belum terhubung.\n"
                "Anda dapat menanyakan analisis emiten, rasio keuangan, atau keterbukaan informasi terverifikasi."
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
