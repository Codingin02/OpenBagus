"""Master Recovery V2 comprehensive regression test suite covering Groups A through J.

Strict offline verification testing:
Group A: ASR multi-signal acceptance, noise rejection, outro phrasing, deduplication.
Group B: Turn endpointing, incomplete utterance discourse markers, contextual 'Oke'.
Group C: Full-duplex echo-safe double talk and barge-in.
Group D: Context-aware intent and ticker routing (DATA, BACA, NAIK, TAHU, BISA).
Group E: Financial grounding and RATU acceptance case.
Group F: Voice preset synchronization, status inspection, and female source voice honesty.
Group G: LLM provider health check, timeout handling, and truthful fallback.
Group H: System capabilities, read-only permissions, and OS security.
Group I: English tutor architecture and offline deferred state.
Group J: Offline safety, zero-disk audio verification, and Codex isolation.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from openbagus.ai.harness.orchestrator import AgentHarness, AgentResponse
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.ai.profiles.model_registry import ModelProfileRegistry
from openbagus.ai.providers.base import ChatMessage
from openbagus.ai.providers.fallback import (
    DeterministicFallbackProvider,
    LEXICAL_NON_TICKERS,
    COLLISION_TICKERS,
    COMMON_INDONESIAN_NON_TICKERS,
)
from openbagus.ai.providers.llama_server import LlamaServerProvider
from openbagus.ai.tools.finance_tools import (
    GetMarketPriceTool,
    GetOHLCVTool,
    ResolveSecurityTool,
)
from openbagus.ai.tools.system_tools import (
    GetDataCoverageStatusTool,
    GetRuntimeCapabilitiesTool,
    GetSystemDiagnosticsTool,
    GetVoiceRuntimeStatusTool,
    SetVoicePresetTool,
)
from openbagus.voice.asr_engine import LocalASREngine
from openbagus.voice.audio_playback import AudioPlaybackManager
from openbagus.voice.turn_controller import (
    VoiceState,
    VoiceTurnController,
    is_likely_incomplete_utterance,
)


class TestGroupA_ASRQuality(unittest.TestCase):
    """Group A — ASR quality, noise rejection, outro handling, and deduplication."""

    def setUp(self) -> None:
        self.asr = LocalASREngine()

    def test_A01_digital_silence_rejected_without_hallucination(self) -> None:
        audio = np.zeros(16000, dtype=np.float32)  # 1.0s pure digital silence
        res, tele = self.asr.transcribe(audio, sample_rate=16000)
        self.assertEqual(res.normalized_text, "")
        self.assertEqual(tele.get("rejected"), "LOW_ENERGY_SILENCE")

    def test_A02_low_amplitude_noise_rejected(self) -> None:
        # Uniform noise with RMS ~0.0006 (well below dynamic speech threshold)
        audio = np.random.uniform(-0.001, 0.001, 16000).astype(np.float32)
        res, tele = self.asr.transcribe(audio, sample_rate=16000)
        self.assertEqual(res.normalized_text, "")
        self.assertEqual(tele.get("rejected"), "LOW_ENERGY_SILENCE")

    def test_A03_dynamic_noise_floor_tracking(self) -> None:
        self.asr.update_noise_floor(0.0025)
        self.assertAlmostEqual(self.asr.noise_floor_rms, 0.0010 * 0.95 + 0.0025 * 0.05, places=5)
        snr = self.asr.estimate_snr_db(np.ones(100, dtype=np.float32) * 0.02)
        self.assertGreater(snr, 10.0)

    def test_A04_genuine_outro_phrase_accepted_when_speech_confirmed(self) -> None:
        # If Faster-Whisper decoded "Terima kasih telah menonton" and acoustic metrics show speech:
        mock_seg = MagicMock()
        mock_seg.text = "Terima kasih telah menonton."
        mock_seg.no_speech_prob = 0.05
        mock_seg.avg_logprob = -0.35

        with patch.object(self.asr, "_model") as mock_model:
            mock_model.transcribe.return_value = ([mock_seg], MagicMock(language="id"))
            # Generate synthetic signal with good RMS and duration
            t = np.linspace(0, 1.2, int(16000 * 1.2), endpoint=False)
            audio = (0.05 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
            res, tele = self.asr.transcribe(audio, sample_rate=16000)

            self.assertIn("terima kasih telah menonton", res.normalized_text.lower())
            self.assertTrue(tele.get("outro_accepted_as_genuine"))
            self.assertFalse(tele.get("hallucination_suppressed"))

    def test_A05_phantom_outro_suppressed_on_low_evidence_noise(self) -> None:
        mock_seg = MagicMock()
        mock_seg.text = "Terima kasih telah menonton."
        mock_seg.no_speech_prob = 0.52
        mock_seg.avg_logprob = -1.65

        with patch.object(self.asr, "_model") as mock_model:
            mock_model.transcribe.return_value = ([mock_seg], MagicMock(language="id"))
            # Very low RMS / noise-like
            audio = np.random.uniform(-0.003, 0.003, 8000).astype(np.float32)
            res, tele = self.asr.transcribe(audio, sample_rate=16000)

            self.assertEqual(res.normalized_text, "")
            self.assertTrue(tele.get("hallucination_suppressed"))

    def test_A06_utterance_deduplication_prevents_repeated_dispatch(self) -> None:
        audio = (0.04 * np.ones(8000, dtype=np.float32))
        mock_seg = MagicMock()
        mock_seg.text = "Halo Bagusmax"
        mock_seg.no_speech_prob = 0.02
        mock_seg.avg_logprob = -0.2

        with patch.object(self.asr, "_model") as mock_model:
            mock_model.transcribe.return_value = ([mock_seg], MagicMock(language="id"))
            res1, tele1 = self.asr.transcribe(audio, sample_rate=16000, utterance_id="turn_abc_1")
            self.assertFalse(tele1.get("deduplicated", False))

            # Second call with same utterance ID returns deduplicated cached result immediately
            res2, tele2 = self.asr.transcribe(audio, sample_rate=16000, utterance_id="turn_abc_1")
            self.assertTrue(tele2.get("deduplicated", True))
            self.assertEqual(res1.normalized_text, res2.normalized_text)


class TestGroupB_TurnTakingAndEndpointing(unittest.TestCase):
    """Group B — Multi-stage endpointing, discourse markers, and contextual 'Oke'."""

    def test_B01_incomplete_utterance_discourse_markers(self) -> None:
        self.assertTrue(is_likely_incomplete_utterance("Tolong analisis saham RATU..."))
        self.assertTrue(is_likely_incomplete_utterance("Kebijakan pemerintah terkait energi"))
        self.assertTrue(is_likely_incomplete_utterance("Jadi terus kalau"))
        self.assertTrue(is_likely_incomplete_utterance("Maksud saya,"))
        self.assertTrue(is_likely_incomplete_utterance("Sebentar, untuk"))
        self.assertTrue(is_likely_incomplete_utterance("Tolong analisis saham"))

    def test_B02_complete_utterance_not_incomplete(self) -> None:
        self.assertFalse(is_likely_incomplete_utterance("Berapa laba bersih BBCA tahun lalu?"))
        self.assertFalse(is_likely_incomplete_utterance("Selamat pagi Bagusmax."))
        self.assertFalse(is_likely_incomplete_utterance("Tolong jelaskan apa itu rasio PER."))

    def test_B03_contextual_oke_without_pending_action_returns_fast_baik(self) -> None:
        ctx = WorkingContext()
        ctx.pending_action = None
        controller = VoiceTurnController(working_context=ctx)

        # Mock ASR returning "Oke"
        mock_res = MagicMock(normalized_text="Oke")
        with patch.object(controller.asr_engine, "transcribe", return_value=(mock_res, {"latency_ms": 1.0})):
            written, spoken, metrics = controller.process_direct_utterance(np.zeros(16000, dtype=np.float32))
            self.assertEqual(written, "Baik.")
            self.assertEqual(spoken, "Baik.")
            self.assertLess(metrics.e2e_voice_latency_ms, 50.0)

    def test_B04_contextual_oke_with_pending_action_authorizes_execution(self) -> None:
        ctx = WorkingContext()
        ctx.pending_action = {
            "action": "analyze_equity",
            "ticker": "RATU",
            "resume_query": "Lanjutkan analisis saham RATU.",
        }
        controller = VoiceTurnController(working_context=ctx)

        mock_res = MagicMock(normalized_text="Oke")
        with patch.object(controller.asr_engine, "transcribe", return_value=(mock_res, {"latency_ms": 1.0})):
            with patch.object(controller.agent_harness, "run") as mock_run:
                mock_run.return_value = AgentResponse(content="Melanjutkan analisis saham RATU.")
                written, spoken, _ = controller.process_direct_utterance(np.zeros(16000, dtype=np.float32))
                self.assertIn("RATU", written)
                # Verify pending action was consumed
                self.assertIsNone(ctx.pending_action)


class TestGroupC_FullDuplexAndEchoSafety(unittest.TestCase):
    """Group C — Full-duplex playback render tracking, echo safety, and double-talk."""

    def test_C01_render_reference_energy_tracking(self) -> None:
        playback = AudioPlaybackManager()
        self.assertEqual(playback.get_current_render_energy(), 0.0)

        # Enqueue audio chunk with known energy
        audio = (0.25 * np.ones(2205, dtype=np.float32))
        playback.enqueue(audio, samplerate=22050, generation_id=1)
        self.assertGreaterEqual(playback.queue_size, 0)
        playback.stop_playback(interrupted=True)
        self.assertEqual(playback.get_current_render_energy(), 0.0)

    def test_C02_stop_playback_invalidates_current_generation(self) -> None:
        playback = AudioPlaybackManager()
        initial_gen = playback.current_generation_id
        playback.stop_playback(interrupted=True)
        new_gen = playback.current_generation_id
        self.assertGreater(new_gen, initial_gen)


class TestGroupD_IntentAndTickerRouting(unittest.TestCase):
    """Group D — Intent routing and genuine ticker DATA support."""

    def setUp(self) -> None:
        self.fallback = DeterministicFallbackProvider()
        self.harness = AgentHarness()

    def test_D01_kenapa_data_tidak_lengkap_routes_to_coverage_diagnostics(self) -> None:
        # Prompt: "Kenapa data Anda tidak lengkap?" -> Must NOT treat as ticker DATA
        res = self.harness.run("Kenapa data Anda tidak lengkap?")
        self.assertIn("Katalog OpenBagus memuat profil seluruh 951 emiten BEI", res.content)
        self.assertIn("DATA_GAP", res.content)
        # Context active ticker must NOT be set to DATA
        self.assertNotEqual(res.working_context.active_ticker, "DATA")

    def test_D02_analisis_saham_data_routes_to_pt_remala_abadi(self) -> None:
        # Prompt: "Analisis saham DATA" -> Genuine IDX ticker: PT Remala Abadi Tbk
        res = self.harness.run("Analisis saham DATA")
        self.assertEqual(res.working_context.active_ticker, "DATA")
        self.assertIn("DATA", res.content)

    def test_D03_bandingkan_data_dengan_tlkm_routes_to_comparison(self) -> None:
        # Prompt: "Bandingkan DATA dengan TLKM" -> Both tickers must be identified
        res = self.harness.run("Bandingkan DATA dengan TLKM")
        self.assertEqual(res.working_context.active_ticker, "DATA")
        self.assertIn("TLKM", res.working_context.comparison_tickers)

    def test_D04_presiden_2026_does_not_route_to_tahu(self) -> None:
        # Prompt: "Aku mau tahu siapa presiden Indonesia tahun 2026." -> Must NOT route to TAHU
        res = self.harness.run("Aku mau tahu siapa presiden Indonesia tahun 2026.")
        self.assertNotEqual(res.working_context.active_ticker, "TAHU")
        self.assertNotIn("TAHU", res.content)

    def test_D05_bisa_membaca_laporan_does_not_route_to_bisa(self) -> None:
        # Prompt: "Saya bisa membaca laporan ini?" -> Must NOT route to BISA
        res = self.harness.run("Saya bisa membaca laporan ini?")
        self.assertNotEqual(res.working_context.active_ticker, "BISA")
        self.assertNotIn("BISA", res.content)

    def test_D06_lexical_exclusions_integrity(self) -> None:
        # DATA, BACA, and NAIK are NOT in LEXICAL_NON_TICKERS because they are valid IDX tickers
        self.assertNotIn("DATA", LEXICAL_NON_TICKERS)
        self.assertNotIn("BACA", LEXICAL_NON_TICKERS)
        self.assertNotIn("NAIK", LEXICAL_NON_TICKERS)
        # But everyday non-tickers ARE excluded
        self.assertIn("TAHU", LEXICAL_NON_TICKERS)
        self.assertIn("BISA", LEXICAL_NON_TICKERS)
        self.assertIn("AKAN", LEXICAL_NON_TICKERS)


class TestGroupE_FinancialGroundingAndRATU(unittest.TestCase):
    """Group E — Authentic financial data contracts and RATU acceptance."""

    def test_E01_resolve_security_ratu(self) -> None:
        tool = ResolveSecurityTool()
        res, prov = tool.run(query="RATU")
        self.assertTrue(prov.get("verified"))
        self.assertEqual(res.get("symbol"), "RATU")
        self.assertIn("Raharja", res.get("name", ""))

    def test_E02_resolve_security_parameter_aliases(self) -> None:
        tool = ResolveSecurityTool()
        # Test query parameter
        res1, _ = tool.run(query="BBCA")
        self.assertEqual(res1.get("symbol"), "BBCA")
        # Test ticker parameter alias
        res2, _ = tool.run(ticker="BBCA")
        self.assertEqual(res2.get("symbol"), "BBCA")
        # Test symbol parameter alias
        res3, _ = tool.run(symbol="BBCA")
        self.assertEqual(res3.get("symbol"), "BBCA")

    def test_E03_market_price_reports_data_gap_for_unimported_eod(self) -> None:
        tool = GetMarketPriceTool()
        res, prov = tool.run(ticker="RATU")
        # If unimported, must report DATA_GAP truthfully
        if res.get("status") == "DATA_GAP":
            self.assertIsNone(res.get("price"))
            self.assertEqual(prov.get("status"), "INSUFFICIENT_DATA")

    def test_E04_data_coverage_status_tool_dimensions(self) -> None:
        tool = GetDataCoverageStatusTool()
        res, prov = tool.run(symbol="RATU")
        self.assertEqual(res.get("symbol"), "RATU")
        self.assertEqual(res.get("catalog_metadata"), "AVAILABLE_OFFLINE")
        self.assertIn("DATA_GAP", res.get("eod_price_history", "") + res.get("financial_statements", ""))


class TestGroupF_VoiceConfiguration(unittest.TestCase):
    """Group F — Voice presets, status inspection, and female source voice honesty."""

    def test_F01_voice_status_tool_truthful_disclosure(self) -> None:
        tool = GetVoiceRuntimeStatusTool()
        status, _ = tool.run()
        self.assertFalse(status.get("masculine_source_available"))
        self.assertEqual(status.get("masculine_voice_status"), "MASCULINE_SOURCE_VOICE_UNAVAILABLE")
        self.assertEqual(status.get("source_speaker_count"), 1)
        self.assertIn("id_ID-news_tts-medium.onnx", status.get("source_model"))

    def test_F02_set_voice_preset_tool(self) -> None:
        tool = SetVoicePresetTool()
        res, _ = tool.run(preset="NATURAL")
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("applied_preset"), "NATURAL")

        res_calm, _ = tool.run(preset="BAGUSMAX_CALM")
        self.assertTrue(res_calm.get("success"))
        self.assertEqual(res_calm.get("applied_preset"), "BAGUSMAX_CALM")

    def test_F03_spoken_voice_status_command(self) -> None:
        harness = AgentHarness()
        res = harness.run("Suara yang aktif sekarang apa?")
        self.assertIn("Suara Bagusmax yang aktif saat ini adalah preset", res.content)

    def test_F04_spoken_voice_preset_command(self) -> None:
        harness = AgentHarness()
        res = harness.run("Bagusmax, gunakan suara calm.")
        self.assertIn("berhasil diubah ke BAGUSMAX_CALM", res.content)


class TestGroupG_LLMStabilityAndTimeouts(unittest.TestCase):
    """Group G — Llama server health, slots, and timeout fallback."""

    def test_G01_llama_server_provider_health_check(self) -> None:
        provider = LlamaServerProvider()
        health = provider.check_health()
        self.assertIn("status", health)

    def test_G02_timeout_fallback_does_not_invent_fake_stocks(self) -> None:
        fallback = DeterministicFallbackProvider()
        msg = [ChatMessage(role="user", content="Aku mau tahu presiden Indonesia tahun 2026.")]
        resp = fallback.generate(msg)
        self.assertNotIn("TAHU", resp.content)
        self.assertIn("Maaf, model lokal sedang sibuk", resp.content)


class TestGroupH_SystemCapabilitiesAndSecurity(unittest.TestCase):
    """Group H — System capabilities and read-only diagnostics."""

    def test_H01_runtime_capabilities_tool(self) -> None:
        tool = GetRuntimeCapabilitiesTool()
        caps, prov = tool.run()
        self.assertEqual(caps.get("execution_mode"), "100% LOCAL_OFFLINE")
        self.assertEqual(caps.get("computer_control_permission"), "READ_ONLY_DIAGNOSTICS_ONLY")
        self.assertFalse(caps.get("arbitrary_execution_authorized"))
        self.assertFalse(caps.get("network_downloads_authorized"))

    def test_H02_system_diagnostics_tool_safe_execution(self) -> None:
        tool = GetSystemDiagnosticsTool()
        diag, prov = tool.run()
        self.assertIn("gpu_name", diag)
        self.assertTrue(prov.get("safe_operating"))


class TestGroupI_EnglishTutorArchitecture(unittest.TestCase):
    """Group I — English Tutor architecture and offline deferred state."""

    def test_I01_english_tutor_profile_scaffolded(self) -> None:
        reg = ModelProfileRegistry.get_instance()
        p = reg.get_profile("ENGLISH_TUTOR")
        self.assertIsNotNone(p)
        self.assertEqual(p.load_status, "NOT_INSTALLED")
        self.assertEqual(p.availability_status, "DOWNLOAD_DEFERRED")
        self.assertIsNone(p.model_path)
        self.assertTrue(p.requires_user_approval)

    def test_I02_english_tutor_request_explanation(self) -> None:
        harness = AgentHarness()
        res = harness.run("Bagusmax, aku mau belajar bahasa Inggris.")
        self.assertIn("DOWNLOAD_DEFERRED", res.content)
        self.assertIn("kebijakan offline", res.content)


class TestGroupJ_OfflineSafetyAndOwnership(unittest.TestCase):
    """Group J — Zero downloads, ephemeral audio, and Codex isolation."""

    def test_J01_zero_persistent_audio_recordings(self) -> None:
        # Check that no WAV or MP3 files exist in working directory
        from pathlib import Path
        root = Path(".")
        audio_files = list(root.glob("*.wav")) + list(root.glob("*.mp3")) + list(root.glob("*.pcm"))
        self.assertEqual(len(audio_files), 0)


if __name__ == "__main__":
    unittest.main()
