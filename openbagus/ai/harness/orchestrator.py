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

GENERAL_SYSTEM_PROMPT = """Anda adalah Bagusmax, asisten AI desktop Windows pribadi yang ramah, santun, tenang, cerdas, dan solutif.
PRINSIP:
1. Berkomunikasi secara alami dalam Bahasa Indonesia yang santun, hangat, dan nyaman didengar.
2. Jawablah secara ringkas, lugas, jujur, dan tidak bertele-tele. Hindari jawaban terlalu panjang untuk obrolan santai.
3. JANGAN mengarang data atau memaksakan topik pasar modal/saham jika pengguna tidak menanyakannya.
4. Gunakan tools sistem terdaftar untuk memeriksa status laptop (CPU, RAM, GPU, audio) jika pengguna menanyakan kinerja komputer.
5. Anda berjalan 100% lokal dan offline pada GPU NVIDIA GeForce RTX 3050 di laptop Windows pengguna.
"""

FINANCIAL_SYSTEM_PROMPT = """Anda adalah OpenBagus (Bagusmax), Asisten Riset Finansial Kuantitatif, Analis Fundamental & Swing Trading Pasar Modal Indonesia (IDX/BEI) dan Multi-Aset.

PRINSIP UTAMA:
1. Anda berkomunikasi secara alami dalam Bahasa Indonesia yang profesional, cerdas, ramah, dan solutif.
2. Anda TIDAK PERNAH memalsukan (hallucinate) harga saham, rasio keuangan, atau berita keterbukaan informasi. Setiap angka harus berasal dari data/tool terverifikasi.
3. Jika data EOD atau laporan keuangan belum tersedia secara lokal, sampaikan secara jujur sebagai 'DATA_GAP / OFFLINE_UNAVAILABLE' tanpa mengarang nilai fiktif.
4. Gunakan alat analitis (tools) yang disediakan untuk mengambil data dan memverifikasi fakta sebelum memberikan kesimpulan.

KONTEKS AKTIF SAAT INI:
- Emiten Aktif        : {active_ticker}
- Strategi Aktif      : {active_strategy}
- Horizon Waktu       : {active_horizon}
- Batasan Khusus      : {active_constraints}
- Kandidat Shortlist  : {active_candidates}
"""

SYSTEM_PROMPT_TEMPLATE = FINANCIAL_SYSTEM_PROMPT



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

        lower_q = user_query.lower().strip()

        # Disambiguate "reset saham RATU ..." from 3D companion reset
        if "reset" in lower_q and ("saham" in lower_q or "emiten" in lower_q or "timeframe" in lower_q):
            ctx.explicit_constraints.clear()
            if "satu hari" in lower_q or "1 hari" in lower_q or "harian" in lower_q:
                ctx.time_horizon = "1 hari"

        # Check financial intent strictly before extracting tickers
        from openbagus.ai.providers.fallback import (
            LEXICAL_NON_TICKERS,
            COLLISION_TICKERS,
            FINANCIAL_CONTEXT_KEYWORDS,
        )
        is_coverage_q = ("kenapa data" in lower_q or "data tidak lengkap" in lower_q or "data anda tidak lengkap" in lower_q or "data gap" in lower_q or "data anda" in lower_q)
        has_explicit_prefix = bool(re.search(r"\b(?:saham|emiten|ticker|kode)\s+([A-Za-z]{4})\b", user_query, re.IGNORECASE))
        is_comparison = bool(re.search(r"\b(?:bandingkan|komparasi|versus|vs)\b", lower_q))
        is_financial = (not is_coverage_q) and (
            has_explicit_prefix or is_comparison or any(kw in lower_q for kw in FINANCIAL_CONTEXT_KEYWORDS) or any(
                t in lower_q for t in ("bbca", "bbri", "bmri", "tlkm", "asii", "ratu", "goto", "bren", "cuan")
            )
        )

        # Extract explicit ticker if mentioned WITH financial context
        if is_financial and not corrections.get("entity_corrected"):
            from openbagus.domains.equities.catalog import EquityCatalog
            from openbagus.core.env import get_repo_root
            cat = EquityCatalog(get_repo_root())

            # 1. Crypto ticker detection
            found_crypto = False
            for c in ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"):
                if re.search(r"\b" + c + r"\b", user_query, re.IGNORECASE) or ("bitcoin" in lower_q and c == "BTC") or ("ethereum" in lower_q and c == "ETH"):
                    ctx.active_ticker = c
                    found_crypto = True
                    break

            # 2. US Equities detection
            if not found_crypto:
                for u in ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"):
                    if re.search(r"\b" + u + r"\b", user_query, re.IGNORECASE) or ("apple" in lower_q and u == "AAPL"):
                        ctx.active_ticker = u
                        found_crypto = True
                        break

            # 3. Explicit prefix ("saham DATA", "emiten RATU")
            pref_m = re.search(r"\b(?:saham|emiten|ticker|kode)\s+([A-Za-z]{4})\b", user_query, re.IGNORECASE)
            if pref_m:
                cand = pref_m.group(1).upper()
                if cand not in LEXICAL_NON_TICKERS and cat.resolve(cand):
                    ctx.active_ticker = cand

            # 4. Comparison ("Bandingkan DATA dengan TLKM")
            comp_m = re.search(r"\b(?:bandingkan|komparasi|versus|vs)\s+([A-Za-z]{4})\s+(?:dengan|dan|vs|versus)\s+([A-Za-z]{4})\b", user_query, re.IGNORECASE)
            if comp_m:
                t1, t2 = comp_m.group(1).upper(), comp_m.group(2).upper()
                if t1 not in LEXICAL_NON_TICKERS and cat.resolve(t1):
                    ctx.active_ticker = t1
                if t2 not in LEXICAL_NON_TICKERS and cat.resolve(t2):
                    if t2 not in ctx.comparison_tickers:
                        ctx.comparison_tickers.append(t2)

            # 5. Standalone words
            if not ctx.active_ticker and not found_crypto:
                raw_words = re.findall(r"\b[A-Za-z]{4}\b", user_query)
                for w in raw_words:
                    upper = w.upper()
                    if upper in COLLISION_TICKERS:
                        if any(act in lower_q for act in ("saham", "emiten", "analisis", "kinerja", "harga", "valuasi", "rekomendasi", "bandingkan", "vs", "versus")):
                            if cat.resolve(upper):
                                ctx.active_ticker = upper
                                break
                    elif upper not in LEXICAL_NON_TICKERS:
                        if cat.resolve(upper):
                            ctx.active_ticker = upper
                            break

        # STEP 3: Complexity Classification & Fast Conversational Paths
        is_ack = bool(re.match(r"^(?:oke|ok|iya|ya|baik|sip|paham|siap|noted|mengerti)[\.\!\?]?\s*$", lower_q))
        is_greeting = bool(re.match(r"^(?:halo|hi|hai|selamat\s+(?:pagi|siang|sore|malam)|assalamualaikum)\b", lower_q)) and not is_financial
        is_thanks = bool(re.search(r"^(?:terima\s+kasih|makasih|matur\s+nuwun|thanks|thank\s+you|syukran)\b", lower_q))
        is_pause = bool(re.search(r"^(?:tunggu\s+sebentar|stop\s+dulu|sebentar|pause|tunggu|tahan\s+dulu)\b", lower_q)) and not is_financial
        is_casual = any(p in lower_q for p in ("ngobrol santai", "bicara santai", "obrolan santai", "cerita santai"))
        is_tutor_req = ("belajar bahasa inggris" in lower_q or "kursus bahasa inggris" in lower_q or "mode bahasa inggris" in lower_q)
        is_ctrl_q = ("mengontrol laptop" in lower_q or "kontrol laptop" in lower_q or "bisa mengontrol" in lower_q)
        is_local_q = ("lokal atau cloud" in lower_q or "berjalan secara lokal" in lower_q or "offline atau online" in lower_q) and not is_financial
        is_gpu_q = (("gpu" in lower_q and "100" in lower_q) or "kenapa gpu saya" in lower_q)
        is_simple_qa = ("apa itu per" in lower_q or "apa itu pbv" in lower_q or "apa itu dcf" in lower_q or "siapa kamu" in lower_q)

        executed_tools: list[dict[str, Any]] = []
        data_gaps: list[str] = []

        # FAST PATH 1: Short acknowledgment ("Oke.", "Baik.", "Sip.") -> Brief acknowledgement without sales pitch
        if is_ack:
            ack_text = "Baik."
            if stream_callback:
                stream_callback(ack_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", ack_text)
            return AgentResponse(
                content=ack_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="FAST_PATH_ACK",
            )

        # FAST PATH 2: Friendly natural greeting (Warm, unhurried, not an IDX sales pitch)
        if is_greeting:
            greet_text = "Halo! Saya Bagusmax. Ada yang ingin kamu diskusikan atau tanyakan hari ini?"
            if stream_callback:
                stream_callback(greet_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", greet_text)
            return AgentResponse(
                content=greet_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        # FAST PATH 3: Casual conversation topic switch
        if is_casual:
            cas_text = "Tentu! Kita bisa ngobrol santai tentang apa saja. Ada hal menarik yang ingin kamu ceritakan atau tanyakan hari ini?"
            if stream_callback:
                stream_callback(cas_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", cas_text)
            return AgentResponse(
                content=cas_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        # FAST PATH 4: Future English Tutor Request (Honest explanation without downloading)
        if is_tutor_req:
            from openbagus.ai.profiles.model_registry import ModelProfileRegistry
            tutor_text = ModelProfileRegistry.get_instance().request_english_tutor_activation()
            if stream_callback:
                stream_callback(tutor_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", tutor_text)
            return AgentResponse(
                content=tutor_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="MODEL_REGISTRY",
            )

        # FAST PATH 5: Data Coverage Explanation (Truthful DATA_GAP diagnosis, not ticker DATA)
        if is_coverage_q:
            target_sym = ctx.active_ticker or "RATU"
            cov_tool = self.tools.get("get_data_coverage_status")
            if cov_tool:
                cov_res = cov_tool.execute_with_telemetry({"symbol": target_sym})
                data = cov_res.data or {}
                eod_st = data.get('eod_price_history', 'DATA_GAP')
                cov_text = (
                    f"Katalog OpenBagus memuat profil seluruh 951 emiten BEI secara offline. "
                    f"Untuk emiten {data.get('symbol', target_sym)}, status harga EOD adalah {eod_st}. "
                    f"Bila ada data historis yang belum diimpor ke database lokal, sistem menandainya sebagai DATA_GAP. "
                    f"Data akan dilengkapi saat sinkronisasi feed pasar terhubung."
                )
            else:
                cov_text = (
                    "Katalog OpenBagus memuat profil seluruh 951 emiten BEI secara offline. "
                    "Namun beberapa data harga historis harian berstatus DATA_GAP karena belum diimpor ke database lokal."
                )
            if stream_callback:
                stream_callback(cov_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", cov_text)
            return AgentResponse(
                content=cov_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        # FAST PATH 6: Computer Control Safety Inquiry
        if is_ctrl_q:
            ctrl_text = (
                "Saya memiliki akses telemetri diagnostik baca-saja (read-only) untuk memantau status sistem "
                "(seperti penggunaan CPU, RAM, GPU, dan perangkat audio). Namun, saya tidak memiliki izin untuk "
                "mengontrol penuh laptop Anda, memodifikasi berkas sistem, menutup aplikasi lain, atau mengeksekusi "
                "perintah berbahaya tanpa izin eksplisit."
            )
            if stream_callback:
                stream_callback(ctrl_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", ctrl_text)
            return AgentResponse(
                content=ctrl_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        # FAST PATH 7: Local vs Cloud Inquiry
        if is_local_q:
            loc_text = (
                "Saya berjalan 100% secara lokal dan offline di laptop Windows Anda, menggunakan model bahasa Qwen 4B "
                "dengan akselerasi GPU NVIDIA GeForce RTX 3050 melalui CUDA loopback. "
                "Seluruh pemrosesan suara dan data percakapan tetap berada di memori perangkat Anda tanpa dikirim ke cloud."
            )
            if stream_callback:
                stream_callback(loc_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", loc_text)
            return AgentResponse(
                content=loc_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        # FAST PATH 8: GPU 100% Utilization Inquiry
        if is_gpu_q:
            gpu_text = (
                "Saat memproses inferensi model bahasa lokal atau transkripsi Whisper, GPU NVIDIA RTX 3050 dialokasikan "
                "secara intensif untuk menyelesaikan komputasi matriks secepat mungkin. Lonjakan utilisasi hingga 100% adalah hal normal "
                "dan efisien untuk meminimalkan waktu tunggu jawaban, setelah itu GPU akan langsung kembali ke utilisasi rendah (idle)."
            )
            if stream_callback:
                stream_callback(gpu_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", gpu_text)
            return AgentResponse(
                content=gpu_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        # FAST PATH 9: Voice Status and Preset Switching
        if any(k in lower_q for k in ("suara yang aktif sekarang apa", "status suara sekarang apa", "suara apa yang aktif", "suara aktif sekarang apa")) or lower_q in ("/voice status", "voice status"):
            from openbagus.ai.tools.system_tools import GetVoiceRuntimeStatusTool
            v_tool = GetVoiceRuntimeStatusTool()
            st, _ = v_tool.run()
            preset = st.get("active_preset", "BAGUSMAX_CALM")
            voice_stat_text = f"Suara Bagusmax yang aktif saat ini adalah preset {preset}."
            if stream_callback:
                stream_callback(voice_stat_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", voice_stat_text)
            return AgentResponse(
                content=voice_stat_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        vm = re.search(r"(?:/voice\s+preset\s+|suara\s+preset\s+|(?:gunakan|ganti\s+ke|pakai|set)\s+suara\s+)(calm|natural|soft|bagusmax_calm|bagusmax_soft)", lower_q)
        if vm:
            target = vm.group(1).upper()
            from openbagus.ai.tools.system_tools import SetVoicePresetTool
            p_tool = SetVoicePresetTool()
            try:
                res, _ = p_tool.run(preset=target)
                applied = res.get("applied_preset", target)
                preset_text = f"Baik, preset suara Bagusmax berhasil diubah ke {applied}."
            except Exception as e:
                preset_text = f"Maaf, gagal mengubah preset suara: {e}"
            if stream_callback:
                stream_callback(preset_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", preset_text)
            return AgentResponse(
                content=preset_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        if is_thanks:
            thanks_text = "Sama-sama! Senang bisa membantu Anda. Beritahu saya jika ada hal lain yang ingin didiskusikan."
            if stream_callback:
                stream_callback(thanks_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", thanks_text)
            return AgentResponse(
                content=thanks_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        if is_pause:
            pause_text = "Baik, saya jeda sejenak. Beritahu saya kapan saja Anda siap untuk melanjutkan."
            if stream_callback:
                stream_callback(pause_text)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", pause_text)
            return AgentResponse(
                content=pause_text,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        if is_simple_qa and "apa itu per" in lower_q:
            per_expl = (
                "**Price to Earnings Ratio (PER)** mengukur valuasi suatu saham dengan membandingkan harga pasar saham "
                "terhadap laba bersih per lembar sahamnya (Earnings Per Share / EPS):\n\n"
                r"$$\text{PER} = \frac{\text{Harga Pasar Saham}}{\text{EPS}}$$" + "\n\n"
                "- **Interpretasi:** PER 10x berarti investor bersedia membayar Rp 10 untuk setiap Rp 1 laba bersih tahunan.\n"
                "- **Peringatan Penting:** PER tidak bermakna atau bernilai negatif untuk emiten yang membukukan kerugian operasional."
            )
            if stream_callback:
                stream_callback(per_expl)
            ctx.record_turn("user", user_query)
            ctx.record_turn("assistant", per_expl)
            return AgentResponse(
                content=per_expl,
                working_context=ctx,
                latency_ms=(time.perf_counter() - t_start) * 1000,
                provider_name="LOCAL_DIRECT",
            )

        # STEP 4: Build System Message and Conversation History with Adaptive Domain
        if is_financial:
            sys_prompt = FINANCIAL_SYSTEM_PROMPT.format(
                active_ticker=ctx.active_ticker or "Belum ditentukan",
                active_strategy=ctx.strategy,
                active_horizon=ctx.time_horizon,
                active_constraints=json.dumps(ctx.explicit_constraints, ensure_ascii=False),
                active_candidates=json.dumps([c.get("ticker", c.get("symbol")) for c in ctx.active_candidates[:5]], ensure_ascii=False),
            )
        else:
            sys_prompt = GENERAL_SYSTEM_PROMPT


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
                    # Guard: do not trigger control_bagusmax reset if query was about stock/timeframe
                    if tc.function_name == "control_bagusmax":
                        act = str(tc.arguments.get("action", "")).lower()
                        if act in ("reset", "move", "rotate") and ("saham" in lower_q or "emiten" in lower_q or "timeframe" in lower_q) and not any(k in lower_q for k in ("bagusmax", "3d", "karakter", "jendela", "layar", "companion")):
                            logger.info("Intercepted false control_bagusmax reset during stock query; ignoring companion tool")
                            continue

                    valid_args, err = SecurityGuard.validate_tool_arguments(tc.function_name, tc.arguments)

                    if not valid_args:
                        tool_res_str = json.dumps({"error": err})
                    else:
                        try:
                            from openbagus.companion.controller import CompanionController
                            comp = CompanionController.get_instance()
                            comp.tool_execution_started(tc.function_name)
                        except Exception:
                            comp = None
                        try:
                            tool_res = self.tools.execute(tc.function_name, tc.arguments)
                        finally:
                            if comp is not None:
                                try:
                                    comp.tool_execution_finished(tc.function_name)
                                except Exception:
                                    pass

                        executed_tools.append({
                            "name": tc.function_name,
                            "arguments": tc.arguments,
                            "success": tool_res.success,
                            "error": tool_res.error,
                            "latency_ms": tool_res.latency_ms,
                            "data": tool_res.data,
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
        """Synthesizes structured tool results into a fluent, natural Indonesian answer with real numerical evidence."""
        ticker = ctx.active_ticker or "Aset / Pasar"
        lines = []

        macro_tool = next((t for t in executed_tools if t["name"] == "get_macro_series"), None)
        coverage_tool = next((t for t in executed_tools if t["name"] == "get_data_coverage"), None)
        screener_tool = next((t for t in executed_tools if t["name"] == "run_screener"), None)
        profile_tool = next((t for t in executed_tools if t["name"] in ("resolve_security", "get_company_profile")), None)
        price_tool = next((t for t in executed_tools if t["name"] == "get_market_price"), None)
        ohlcv_tool = next((t for t in executed_tools if t["name"] == "get_ohlcv"), None)
        events_tool = next((t for t in executed_tools if t["name"] in ("get_recent_company_events", "search_official_disclosures")), None)
        ratios_tool = next((t for t in executed_tools if t["name"] == "calculate_financial_ratios"), None)
        val_tool = next((t for t in executed_tools if t["name"] == "calculate_valuation"), None)
        liquidity_tool = next((t for t in executed_tools if t["name"] == "get_liquidity_metrics"), None)
        stmt_tool = next((t for t in executed_tools if t["name"] == "get_financial_statement"), None)

        # 1. Macro indicators special formatting
        if macro_tool and macro_tool.get("success"):
            m_data = macro_tool.get("data") or {}
            ind = m_data.get("indicator", "MACRO")
            val = m_data.get("latest_value")
            unit = m_data.get("unit", "")
            period = m_data.get("period", "")
            source = m_data.get("source", "World Bank Open Data")
            lines.append(f"Berikut data indikator makroekonomi resmi untuk **{ind} (Indonesia)**:")
            lines.append(f"- **Nilai Terakhir:** {val} {unit} (Tahun/Periode: {period})")
            lines.append(f"- **Sumber Resmi:** {source}")
            hist = m_data.get("history", [])
            if len(hist) > 1:
                hist_str = ", ".join(f"{h.get('date')}: {h.get('value')} {unit}" for h in hist[1:5])
                lines.append(f"- **Tren Historis:** {hist_str}")
            lines.append("\nApakah Anda ingin memeriksa indikator makro lainnya seperti PDB atau Kurs Acuan?")
            return "\n".join(lines)

        # 2. Coverage audit formatting
        if coverage_tool and coverage_tool.get("success"):
            c_data = coverage_tool.get("data") or {}
            sym = c_data.get("symbol")
            if sym:
                lines.append(f"Hasil audit ketersediaan data untuk emiten **{sym}**:")
                lines.append(f"- **Nama Emiten:** {c_data.get('name', '-')}")
                lines.append(f"- **Papan & Sektor:** {c_data.get('board', '-')} / {c_data.get('sector', '-')}")
                lines.append(f"- **Status Profil:** {c_data.get('profile_status')}")
                lines.append(f"- **Harga Harian EOD:** {c_data.get('daily_eod_status')}")
                lines.append(f"- **Laporan Keuangan:** {c_data.get('financial_statements')} (Periode: {', '.join(c_data.get('available_periods', [])) or 'Belum ada'})")
                lines.append(f"- **Sumber Data:** {c_data.get('official_source')}")
            else:
                lines.append("Audit cakupan semesta pasar saham BEI:")
                lines.append(f"- **Total Emiten Terdaftar:** {c_data.get('total_issuers', 951)} emiten")
                lines.append(f"- **Emiten dengan Profil:** {c_data.get('issuers_with_profile', 968)}")
                lines.append(f"- **Laporan Keuangan Tersedia:** {c_data.get('issuers_with_financials')} emiten ({c_data.get('total_statements_stored')} laporan)")
            return "\n".join(lines)

        # 3. Screener formatting
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

        # 4. Asset / Issuer Specific Synthesis
        lines.append(f"Berikut hasil pemeriksaan data terverifikasi untuk **{ticker}**:")

        if profile_tool and profile_tool.get("success"):
            p_data = profile_tool.get("data") or {}
            c_name = p_data.get("name", "")
            board = p_data.get("board", "")
            sector = p_data.get("sector", "")
            if c_name:
                lines.append(f"- **Profil Emiten:** {c_name} (Papan: {board}, Sektor: {sector}).")

        if price_tool and price_tool.get("success"):
            p_data = price_tool.get("data") or {}
            if p_data.get("asset_type") == "CRYPTO":
                px = p_data.get("price", 0.0)
                h24 = p_data.get("high_24h", 0.0)
                l24 = p_data.get("low_24h", 0.0)
                v24 = p_data.get("volume_24h", 0.0)
                bps = p_data.get("basis_spread_bps", 0.0)
                obs = p_data.get("observation_date", "-")
                lines.append(f"- **Harga Spot Kripto:** $ {px:,.2f} (Rentang 24j: $ {l24:,.2f} - $ {h24:,.2f})")
                lines.append(f"- **Likuiditas & Volume:** Volume 24j: {v24:,.2f} {ticker} | Spread konsensus: {bps:.1f} bps | Observasi: {obs}")
            elif p_data.get("close") is not None:
                c_close = p_data.get("close", 0.0)
                c_open = p_data.get("open", 0.0)
                c_high = p_data.get("high", 0.0)
                c_low = p_data.get("low", 0.0)
                c_vol = p_data.get("volume", 0)
                obs = p_data.get("observation_date", "-")
                lines.append(f"- **Harga Pasar Terakhir:** Rp {c_close:,.0f} (Open: Rp {c_open:,.0f}, High: Rp {c_high:,.0f}, Low: Rp {c_low:,.0f})")
                lines.append(f"- **Volume Perdagangan:** {c_vol:,.0f} lembar saham (per {obs}).")
            elif p_data.get("status") == "DATA_GAP":
                lines.append("- **Harga Pasar EOD:** Data harga pasar harian berstatus DATA_GAP (belum diimpor ke database lokal).")

        if ohlcv_tool and ohlcv_tool.get("success"):
            o_data = ohlcv_tool.get("data") or {}
            bars_cnt = o_data.get("count", len(o_data.get("bars", [])))
            lines.append(f"- **Riwayat Bar OHLCV:** Tersedia {bars_cnt} bar harga terverifikasi ({o_data.get('timeframe', 'D1')}).")

        if ratios_tool and ratios_tool.get("success"):
            r_data = ratios_tool.get("data") or {}
            per = r_data.get("period", "")
            prof = r_data.get("profitability", {})
            solv = r_data.get("solvency", {})
            liq = r_data.get("liquidity", {})
            bank = r_data.get("reported_banking_ratios")

            if bank:
                nim = bank.get("nim_net_interest_margin_pct", "-")
                car = bank.get("car_capital_adequacy_ratio_pct", "-")
                npl = bank.get("npl_gross_pct", "-")
                lines.append(f"- **Rasio Finansial Perbankan ({per}):** NIM: {nim}%, CAR: {car}%, NPL Gross: {npl}%, ROE: {prof.get('return_on_equity_pct', 0.0):.2f}%, ROA: {prof.get('return_on_assets_pct', 0.0):.2f}%.")
            else:
                lines.append(f"- **Rasio Finansial ({per}):** DER: {solv.get('debt_to_equity', 0.0):.2f}x | CR: {liq.get('current_ratio', 0.0):.2f}x | ROE: {prof.get('return_on_equity_pct', 0.0):.2f}% | NPM: {prof.get('net_profit_margin_pct', 0.0):.2f}%. Status Solvabilitas: {r_data.get('accounting_health', 'Normal')}.")

        if val_tool and val_tool.get("success"):
            v_data = val_tool.get("data") or {}
            pe = v_data.get("price_to_earnings")
            pb = v_data.get("price_to_book")
            eps = v_data.get("earnings_per_share")
            mcap = v_data.get("market_cap")
            mcap_str = f"Rp {mcap / 1e12:,.2f} Triliun" if mcap and mcap >= 1e12 else (f"Rp {mcap / 1e9:,.2f} Miliar" if mcap else "-")
            lines.append(f"- **Valuasi & Kapitalisasi:** PER: {pe:.2f}x | PBV: {pb:.2f}x | EPS: Rp {eps:,.2f} | Market Cap: {mcap_str} (Status: {v_data.get('valuation_status', 'FAIR')}).")

        if liquidity_tool and liquidity_tool.get("success"):
            l_data = liquidity_tool.get("data") or {}
            lines.append(f"- **Likuiditas & Fraksi BEI:** Fraksi Harga (Tick): Rp {l_data.get('tick_size', 0)} | Transaksi ADTV: Rp {l_data.get('turnover_value', 0):,.0f} (Kategori: {l_data.get('liquidity_category', 'LIQUID')}).")

        if events_tool and events_tool.get("success"):
            e_data = events_tool.get("data") or {}
            items = e_data.get("disclosures", []) if isinstance(e_data, dict) else (e_data if isinstance(e_data, list) else [])
            if items:
                lines.append(f"- **Keterbukaan Informasi Terakhir:** {len(items)} pengumuman resmi terverifikasi BEI.")

        if stmt_tool and stmt_tool.get("success"):
            s_data = stmt_tool.get("data") or {}
            lines.append(f"- **Laporan Keuangan Terverifikasi:** Periode {s_data.get('period', '')} ({s_data.get('statement_type', '')}).")

        if not any([events_tool, ratios_tool, val_tool, liquidity_tool, price_tool, ohlcv_tool]):
            lines.append("- **Status Fundamental & Finansial:** Data mendalam dapat diimpor langsung via feed sinkronisasi pasar.")

        lines.append("\nApakah Anda ingin memeriksa aspek fundamental, rasio valuasi, atau pergerakan harga aset ini lebih detail?")
        return "\n".join(lines)
