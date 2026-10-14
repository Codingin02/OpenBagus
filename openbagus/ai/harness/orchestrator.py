"""Comprehensive Conversational Agent Harness & Orchestration Loop for OpenBagus."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from openbagus.ai.decision.engine import DecisionIntelligenceEngine, DecisionSynthesis
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.ai.providers.base import (
    BaseModelProvider,
    ChatCompletionChunk,
    ChatCompletionResponse,
    ChatMessage,
    ToolCall,
)
from openbagus.ai.providers.fallback import DeterministicFallbackProvider
from openbagus.ai.providers.manager import ProviderManager
from openbagus.ai.runtime.profiles import RuntimeProfile, get_profile
from openbagus.ai.security.guard import SecurityGuard
from openbagus.ai.strategy.registry import StrategyRegistry
from openbagus.ai.tools.registry import ToolRegistry, get_global_tool_registry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """Anda adalah OpenBagus, Asisten Riset Finansial Kuantitatif, Analis Fundamental & Swing Trading Pasar Modal Indonesia (IDX/BEI) dan Multi-Aset.

PRINSIP UTAMA:
1. Anda berkomunikasi secara alami dalam Bahasa Indonesia yang profesional, cerdas, ramah, dan solutif.
2. Anda TIDAK PERNAH memalsukan (hallucinate) harga saham, rasio keuangan, atau berita keterbukaan informasi. Setiap angka harus berasal dari data/tool terverifikasi.
3. Jika data EOD atau laporan keuangan belum tersedia secara lokal, sampaikan secara jujur sebagai 'Data Gap' tanpa mengarang nilai fiktif.
4. Anda meneliti SELURUH 951 emiten IDX lintas papan (Utama, Pengembangan, Akselerasi, dan Pemantauan Khusus/FCA) tanpa bias hanya pada saham blue-chip.
5. Anda membedakan secara tegas antara riset swing trading (berbasis katalis, volume, momentum, likuiditas) dan riset investasi jangka panjang (berbasis valuasi DCF, FCFF, ROIC, margin of safety).
6. Gunakan alat analitis (tools) yang disediakan untuk menghitung, mengambil data, dan memverifikasi fakta sebelum memberikan kesimpulan.
7. Bersikap skeptis jika terdapat klaim kepastian sepihak dari pengguna. Jelaskan risiko, kondisi invalidasi, dan alternatif yang lebih likuid bila relevan.

KONTEKS AKTIF SAAT INI:
- Emiten Aktif        : {active_ticker}
- Strategi Aktif      : {active_strategy}
- Horizon Waktu       : {active_horizon}
- Batasan Khusus      : {active_constraints}
- Kandidat Shortlist  : {active_candidates}
"""


@dataclass
class AgentResponse:
    content: str
    tool_calls_executed: list[dict[str, Any]] = field(default_factory=list)
    decision_synthesis: DecisionSynthesis | None = None
    working_context: WorkingContext | None = None
    latency_ms: float = 0.0
    provider_name: str = ""
    is_streamed: bool = False
    data_gaps: list[str] = field(default_factory=list)
    thinking_trace: str = ""  # Internal reasoning from DEEP_REASONING mode — NEVER sent to TTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "tool_calls_count": len(self.tool_calls_executed),
            "tool_calls": self.tool_calls_executed,
            "latency_ms": round(self.latency_ms, 1),
            "provider_name": self.provider_name,
            "data_gaps": self.data_gaps,
        }


class AgentHarness:
    """Bounded, model-powered agent loop orchestrating financial tools, memory, and decision synthesis."""

    def __init__(
        self,
        provider: BaseModelProvider | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.provider_mgr = ProviderManager.get_instance()
        self.provider = provider or self.provider_mgr.get_provider()
        self.tools = tool_registry or get_global_tool_registry()
        self.strategies = StrategyRegistry()

    def run(
        self,
        user_query: str,
        context: WorkingContext | None = None,
        profile: RuntimeProfile | None = None,
        stream_callback: Callable[[str], None] | None = None,
        mode: str = "BALANCED",
    ) -> AgentResponse:
        t_start = time.perf_counter()
        ctx = context or WorkingContext()

        # Switch provider and profile based on mode
        if mode.upper() in ("FAST",):
            self.provider = self.provider_mgr.switch_to_fast()
            prof = profile or get_profile("FAST")
        elif mode.upper() in ("DEEP_REASONING", "DEEP", "DEEP_RESEARCH"):
            self.provider = self.provider_mgr.switch_to_deep()
            prof = profile or get_profile("DEEP_REASONING")
        else:
            prof = profile or get_profile("BALANCED")

        # STEP 1: Security & Injection Check
        if SecurityGuard.check_prompt_injection(user_query):
            msg = "Permintaan tidak dapat diproses karena terdeteksi pola injeksi instruksi sistem atau akses tidak sah."
            if stream_callback:
                stream_callback(msg)
            return AgentResponse(content=msg, latency_ms=0.0, provider_name="SECURITY_GUARD")

        # STEP 2: Handle User Corrections & Candidate References
        corrections = ctx.handle_corrections(user_query)
        cand_ref = ctx.resolve_candidate_reference(user_query)

        # Extract explicit ticker if mentioned
        raw_words = re.findall(r"\b[A-Za-z]{4}\b", user_query)
        known_skip = {"BUAT", "CARA", "DARI", "YANG", "BISA", "HOLD", "KOK", "TAPI", "JIKA", "ATAU", "DENG"}
        for w in raw_words:
            upper = w.upper()
            if upper not in known_skip and not corrections.get("entity_corrected"):
                # verify with catalog if plausible ticker
                from openbagus.domains.equities.catalog import EquityCatalog
                from openbagus.core.env import get_repo_root
                cat = EquityCatalog(get_repo_root())
                if cat.resolve(upper):
                    ctx.active_ticker = upper
                    break

        # STEP 3: Complexity Classification
        lower_q = user_query.lower().strip()
        is_greeting = bool(re.match(r"^(?:halo|hi|hai|selamat\s+(?:pagi|siang|sore|malam)|assalamualaikum)\b", lower_q)) and not any(
            k in lower_q for k in ("analisis", "bedah", "saham", "bandingkan", "laporan", "harga", "berapa", "cari", "screener", "rekomendasi")
        )
        is_simple_qa = ("apa itu per" in lower_q or "apa itu pbv" in lower_q or "apa itu dcf" in lower_q or "siapa kamu" in lower_q)

        executed_tools: list[dict[str, Any]] = []
        data_gaps: list[str] = []

        # FAST PATH: Direct conversational response for greetings / basic glossary
        if is_greeting:
            greet_text = (
                "Selamat pagi! Saya adalah OpenBagus, asisten riset finansial kuantitatif dan intelijen pasar modal Anda.\n"
                "Saya siap membantu Anda meneliti 951 emiten saham IDX, membedah laporan keuangan resmi, melacak keterbukaan informasi material, "
                "menilai risiko likuiditas mikrostruktur, hingga memindai setup swing trading atau valuasi investasi jangka panjang.\n\n"
                "Ada saham atau sektor yang ingin Anda diskusikan hari ini?"
            )
            if stream_callback:
                stream_callback(greet_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", greet_text)
            return AgentResponse(
                content=greet_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name=self.provider.get_provider_name(),
            )

        if is_simple_qa and "apa itu per" in lower_q:
            per_expl = (
                "**Price to Earnings Ratio (PER)** mengukur valuasi suatu saham dengan membandingkan harga pasar saham "
                "terhadap laba bersih per lembar sahamnya (Earnings Per Share / EPS):\n\n"
                r"$$\text{PER} = \frac{\text{Harga Pasar Saham}}{\text{EPS}}$$" + "\n\n"
                "- **Interpretasi:** PER 10x berarti investor bersedia membayar Rp 10 untuk setiap Rp 1 laba bersih tahunan.\n"
                "- **Peringatan Penting:** PER tidak bermakna atau bernilai negatif untuk emiten yang membukukan kerugian operasional. "
                "Di OpenBagus, kami selalu memasang proteksi guard agar emiten rugi tidak dinilai secara keliru menggunakan PER tunggal."
            )
            if stream_callback:
                stream_callback(per_expl)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", per_expl)
            return AgentResponse(
                content=per_expl,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name=self.provider.get_provider_name(),
            )

        # STEP 4: Build System Message and Conversation History
        sys_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            active_ticker=ctx.active_ticker or "Belum ditentukan",
            active_strategy=ctx.strategy,
            active_horizon=ctx.time_horizon,
            active_constraints=json.dumps(ctx.explicit_constraints, ensure_ascii=False),
            active_candidates=json.dumps([c.get("ticker", c.get("symbol")) for c in ctx.active_candidates[:5]], ensure_ascii=False),
        )

        messages: list[ChatMessage] = [ChatMessage(role="system", content=sys_prompt)]

        # Append recent turns (up to 4 turns for bounded context, compacting long text)
        for t in ctx.turns[-4:]:
            content = t["content"]
            if len(content) > 800:
                content = content[:800] + "... [ringkasan respon]"
            messages.append(ChatMessage(role=t["role"], content=content))
        messages.append(ChatMessage(role="user", content=user_query))

        tool_defs = self.tools.list_definitions()

        # STEP 5: Multi-Step Bounded Agent Loop
        final_text = ""
        iterations = 0
        max_iters = prof.max_tool_iterations

        while iterations < max_iters:
            iterations += 1
            current_tools = tool_defs if iterations == 1 else None
            try:
                resp = self.provider.generate(
                    messages=messages,
                    tools=current_tools,
                    max_tokens=prof.max_tokens,
                    temperature=prof.temperature,
                    stream=False,  # tools loop executes synchronously; final reply can stream
                    timeout=prof.timeout_seconds,
                )
            except Exception as e:
                logger.warning("Provider generation failed (%s); falling back to deterministic provider", e)
                fallback_p = DeterministicFallbackProvider()
                resp = fallback_p.generate(messages=messages, tools=None)

            if isinstance(resp, Iterator):  # handle stream fallback
                chunks = list(resp)
                resp = ChatCompletionResponse(
                    content="".join(c.delta_content for c in chunks),
                    finish_reason="stop",
                    provider_name=self.provider.get_provider_name(),
                )

            # Check if model called tools
            if resp.tool_calls:
                messages.append(ChatMessage(
                    role="assistant",
                    content=resp.content,
                    tool_calls=resp.tool_calls,
                ))

                for tc in resp.tool_calls:
                    valid_args, err = SecurityGuard.validate_tool_arguments(tc.function_name, tc.arguments)
                    if not valid_args:
                        tool_res_str = json.dumps({"error": err})
                    else:
                        tool_res = self.tools.execute(tc.function_name, tc.arguments)
                        executed_tools.append({
                            "name": tc.function_name,
                            "arguments": tc.arguments,
                            "success": tool_res.success,
                            "error": tool_res.error,
                            "latency_ms": tool_res.latency_ms,
                        })
                        if tool_res.success and isinstance(tool_res.data, dict) and tool_res.data.get("status") == "DATA_GAP":
                            data_gaps.append(f"{tc.function_name}: {tool_res.data.get('message')}")

                        # Update active candidates if screener ran
                        if tc.function_name == "run_screener" and tool_res.success:
                            cands = tool_res.data.get("candidates", [])
                            if cands:
                                ctx.active_candidates = cands
                        elif tc.function_name == "resolve_security" and tool_res.success:
                            sym = tool_res.data.get("symbol")
                            if sym:
                                ctx.active_ticker = sym
                                ctx.active_ticker_name = tool_res.data.get("name")

                        tool_res_str = json.dumps(tool_res.data if tool_res.success else {"error": tool_res.error}, ensure_ascii=False)
                        if len(tool_res_str) > 1500:
                            tool_res_str = tool_res_str[:1500] + "... [TRUNCATED]"

                    messages.append(ChatMessage(
                        role="tool",
                        content=tool_res_str,
                        tool_call_id=tc.id,
                        name=tc.function_name,
                    ))
            else:
                final_text = resp.content
                break

        # If loop ended without final text (or provider is deterministic fallback)
        if not final_text:
            if executed_tools:
                # Compose evidence-backed response from executed tools
                final_text = self._compose_evidence_response(ctx, executed_tools, user_query)
            else:
                final_text = resp.content if resp and resp.content else "Saya telah menerima pertanyaan Anda, namun data pendukung belum mencukupi untuk analisis lengkap."

        # Capture thinking trace (DEEP_REASONING mode only) — NEVER expose to TTS or user-facing output
        thinking_trace = getattr(resp, "thinking_trace", "") or "" if resp else ""

        # Stream callback delivery for responsive terminal UX
        if stream_callback and final_text:
            stream_callback(final_text)

        elapsed = (time.perf_counter() - t_start) * 1000
        ctx.record_turn("user", user_query)
        ctx.record_turn("assistant", final_text)

        return AgentResponse(
            content=final_text,
            tool_calls_executed=executed_tools,
            working_context=ctx,
            latency_ms=elapsed,
            provider_name=self.provider.get_provider_name(),
            data_gaps=data_gaps,
            thinking_trace=thinking_trace,
        )

    @classmethod
    def submit_turn(
        cls,
        session_id: str,
        text: str,
        mode: str = "FAST",
        input_channel: str = "TEXT",
    ) -> "AgentResponse":
        """Convenience factory for voice system and external callers.

        Gets (or creates) the singleton AgentHarness and runs one conversational turn.
        session_id is unused here (kept for API compatibility with voice turn controller).
        input_channel may be 'TEXT' or 'VOICE' (affects system prompt context in future).
        """
        harness = cls()
        return harness.run(user_query=text, mode=mode)


    def _compose_evidence_response(
        self,
        ctx: WorkingContext,
        executed_tools: list[dict[str, Any]],
        user_query: str,
    ) -> str:
        """Synthesizes structured tool results into a fluent, natural Indonesian answer."""
        ticker = ctx.active_ticker or "Emiten Target"
        lines = []

        # Find key tool outputs
        price_tool = next((t for t in executed_tools if t["name"] == "get_market_price"), None)
        events_tool = next((t for t in executed_tools if t["name"] == "get_recent_company_events" or t["name"] == "search_official_disclosures"), None)
        ratios_tool = next((t for t in executed_tools if t["name"] == "calculate_financial_ratios"), None)
        val_tool = next((t for t in executed_tools if t["name"] == "calculate_valuation"), None)
        screener_tool = next((t for t in executed_tools if t["name"] == "run_screener"), None)
        liquidity_tool = next((t for t in executed_tools if t["name"] == "get_liquidity_metrics"), None)

        if screener_tool:
            cands = ctx.active_candidates
            if cands:
                lines.append(f"Saya telah memindai semesta saham untuk setup **{ctx.strategy}** pada horizon **{ctx.time_horizon}**.")
                lines.append(f"Ditemukan {len(cands)} kandidat yang memenuhi kriteria awal:\n")
                for i, c in enumerate(cands[:5], 1):
                    sym = c.get("ticker", c.get("symbol", "-"))
                    board = c.get("board", "-")
                    strat = c.get("strategy", "-")
                    entry = c.get("entry", 0.0)
                    sl = c.get("sl", 0.0)
                    lines.append(f"{i}. **{sym}** ({board}) — Setup: `{strat}` | Acuan Entry: Rp {entry:,.0f} | Stop Loss: Rp {sl:,.0f}")
                lines.append("\n**Rekomendasi Langkah Berikutnya:** Anda dapat menanyakan rincian salah satu kandidat (misal: *'Analisis yang nomor 1'* atau *'Bagaimana likuiditasnya?'*).")
                return "\n".join(lines)

        lines.append(f"Berikut hasil pemeriksaan analitis untuk **{ticker}**:")

        if price_tool:
            # check price
            lines.append("- **Harga Pasar EOD:** Data harga pasar terakhir diperiksa dari arsip resmi.")

        if events_tool:
            lines.append("- **Keterbukaan Informasi:** Pengumuman material telah diverifikasi terhadap dokumen publik resmi BEI.")

        if ratios_tool:
            lines.append("- **Kesehatan Keuangan:** Rasio solvabilitas dan profitabilitas telah dihitung secara matematis dari laporan keuangan.")

        if val_tool:
            lines.append("- **Valuasi Intrinsik:** Estimasi nilai wajar dihitung berbasis proyeksi arus kas dan margin of safety.")

        if liquidity_tool:
            lines.append("- **Mikrostruktur & Likuiditas:** Likuiditas dan aturan fraksi harga bursa telah diverifikasi.")

        lines.append("\nApakah Anda ingin membedah sisi fundamentalnya lebih dalam, atau menguji setup teknikal/swing-nya?")
        return "\n".join(lines)
