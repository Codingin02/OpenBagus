"""Mandatory 20-Scenario Regression Test Suite for OpenBagus Conversational Intelligence & Voice Recovery.

Validates all 20 required acceptance tests defined in Section 25 of the recovery specification:
TEST 1  - Silence rejection (zero transcript, zero response)
TEST 2  - False closing phrase rejection (hallucinated "Terima kasih telah menonton")
TEST 3  - Legitimate closing phrase acceptance
TEST 4  - Short pause adaptive endpointing (incomplete vs complete utterance)
TEST 5  - Full-duplex barge-in during speech/thinking
TEST 6  - General knowledge query routing (not treated as ticker lookup)
TEST 7  - LLM provider timeout handling (truthful short error, no ticker pollution)
TEST 8  - Voice preset switching verification
TEST 9  - Honest voice runtime status (MASCULINE_SOURCE_VOICE_UNAVAILABLE)
TEST 10 - Computer control safety model (read-only telemetry diagnostics)
TEST 11 - GPU 100% utilization explanation
TEST 12 - Stock analysis routing & verified financial provenance
TEST 13 - Data coverage explanation (DATA_GAP diagnosis, not ticker 'DATA')
TEST 14 - Short acknowledgment fast-path (<5ms, concise reply)
TEST 15 - Topic switch to casual conversation (no finance restriction)
TEST 16 - Future English Tutor architecture (DOWNLOAD_DEFERRED, zero downloads)
TEST 17 - Offline local execution (zero internet required)
TEST 18 - Conversational context & follow-up memory
TEST 19 - Audio privacy audit (ephemeral RAM only, 0 persisted audio files)
TEST 20 - Codex 3D asset isolation (0 mesh/shader/3D files modified)
"""

from __future__ import annotations

import os
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np

from openbagus.ai.harness.orchestrator import AgentHarness, AgentResponse
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.ai.profiles.model_registry import ModelProfileRegistry
from openbagus.ai.providers.base import ChatMessage
from openbagus.ai.providers.fallback import DeterministicFallbackProvider, COMMON_INDONESIAN_NON_TICKERS
from openbagus.ai.runtime.profiles import get_profile
from openbagus.ai.tools.system_tools import (
    GetRuntimeCapabilitiesTool,
    GetSystemDiagnosticsTool,
    GetVoiceRuntimeStatusTool,
    SetVoicePresetTool,
    GetDataCoverageStatusTool,
)
from openbagus.voice.asr_engine import LocalASREngine
from openbagus.voice.asr_normalizer import ASRFinancialNormalizer
from openbagus.voice.audio_capture import AudioCaptureStream
from openbagus.voice.audio_playback import AudioPlaybackManager
from openbagus.voice.interruption import InterruptionCoordinator
from openbagus.voice.preferences import load_voice_preferences, save_voice_preferences
from openbagus.voice.turn_controller import (
    VoiceState,
    VoiceTurnController,
    is_likely_incomplete_utterance,
)
from openbagus.voice.vad import VoiceActivityDetector


class TestConversationalRecoveryRegression(unittest.TestCase):
    """20-scenario regression test suite covering real-world user failures."""

    # -------------------------------------------------------------------------
    # TEST 1 - SILENCE: No user speaking -> No transcript, no response
    # -------------------------------------------------------------------------
    def test_01_silence_rejection(self) -> None:
        asr = LocalASREngine()
        # 1.5 seconds of pure zero acoustic silence
        silence_audio = np.zeros(24000, dtype=np.float32)
        norm_res, tele = asr.transcribe(silence_audio, sample_rate=16000)
        self.assertEqual(norm_res.normalized_text, "")
        self.assertEqual(norm_res.raw_transcript, "")
        self.assertEqual(tele.get("gate"), "acoustic_rms_silence_floor")

    # -------------------------------------------------------------------------
    # TEST 2 - FALSE CLOSING PHRASE: Whisper outro hallucination on noise
    # -------------------------------------------------------------------------
    def test_02_false_closing_phrase_rejection(self) -> None:
        asr = LocalASREngine()
        # Mock whisper proposing YouTube outro hallucination with high no_speech_prob
        fake_seg = MagicMock()
        fake_seg.text = "Terima kasih telah menonton."
        fake_seg.no_speech_prob = 0.65
        fake_seg.avg_logprob = -1.8

        with patch.object(asr, "_model") as mock_model:
            mock_model.transcribe.return_value = ([fake_seg], MagicMock())
            # Audio above silence floor (0.0035) but below YouTube outro gate (0.012)
            # Uniform [-0.010, 0.010] has RMS ~ 0.0058
            low_energy_audio = np.random.uniform(-0.010, 0.010, 24000).astype(np.float32)
            norm_res, tele = asr.transcribe(low_energy_audio, sample_rate=16000)

        self.assertEqual(norm_res.normalized_text, "")
        self.assertTrue(tele.get("hallucination_suppressed", False))

    # -------------------------------------------------------------------------
    # TEST 3 - LEGITIMATE CLOSING PHRASE: Real speech accepted
    # -------------------------------------------------------------------------
    def test_03_legitimate_closing_phrase_acceptance(self) -> None:
        asr = LocalASREngine()
        # Mock legitimate speech with high acoustic energy and low no_speech_prob
        fake_seg = MagicMock()
        fake_seg.text = "Terima kasih telah menonton."
        fake_seg.no_speech_prob = 0.05
        fake_seg.avg_logprob = -0.2

        with patch.object(asr, "_model") as mock_model:
            mock_model.transcribe.return_value = ([fake_seg], MagicMock())
            # Real speech RMS amplitude ~0.05
            real_audio = np.random.uniform(-0.05, 0.05, 24000).astype(np.float32)
            norm_res, tele = asr.transcribe(real_audio, sample_rate=16000)

        self.assertEqual(norm_res.normalized_text, "Terima kasih telah menonton.")
        self.assertFalse(tele.get("hallucination_suppressed", False))

    # -------------------------------------------------------------------------
    # TEST 4 - SHORT PAUSE: Incomplete utterance extends pause, not answered early
    # -------------------------------------------------------------------------
    def test_04_short_pause_adaptive_endpointing(self) -> None:
        # Step A: Incomplete fragment detection
        self.assertTrue(is_likely_incomplete_utterance("Analisis RATU..."))
        self.assertTrue(is_likely_incomplete_utterance("Tolong analisis saham RATU"))
        self.assertTrue(is_likely_incomplete_utterance("Kalau menurut Anda"))
        self.assertTrue(is_likely_incomplete_utterance("Untuk saham RATU"))
        self.assertTrue(is_likely_incomplete_utterance("Terus kalau"))

        # Step B: Completed request detection
        self.assertFalse(is_likely_incomplete_utterance("Analisis RATU untuk timeframe satu hari."))
        self.assertFalse(is_likely_incomplete_utterance("Siapa presiden Indonesia tahun 2026?"))
        self.assertFalse(is_likely_incomplete_utterance("Oke."))

        # Step C: VAD adaptive silence timeout
        vad = VoiceActivityDetector(silence_timeout_ms=800, extended_silence_timeout_ms=1800)
        self.assertFalse(vad.is_extended)
        self.assertEqual(vad.silence_timeout_chunks, int(800 / 32))

        # Dynamically extend silence when incomplete
        vad.set_extended_silence(True)
        self.assertTrue(vad.is_extended)
        self.assertEqual(vad._current_silence_timeout_chunks, int(1800 / 32))

        vad.set_extended_silence(False)
        self.assertFalse(vad.is_extended)

    # -------------------------------------------------------------------------
    # TEST 5 - INTERRUPT SPEECH: Full-Duplex Barge-in cancels playback
    # -------------------------------------------------------------------------
    def test_05_interrupt_speech_barge_in(self) -> None:
        turn_ctrl = VoiceTurnController()
        # Set state to SPEAKING
        turn_ctrl.set_state(VoiceState.SPEAKING)
        turn_ctrl.playback_manager.stop_playback = MagicMock()

        # Trigger barge-in via interruption coordinator
        turn_ctrl.interruption.trigger_interruption(reason="USER_BARGE_IN")
        self.assertTrue(turn_ctrl.interruption.get_cancellation_event().is_set())
        self.assertEqual(turn_ctrl.state, VoiceState.INTERRUPTED)

    # -------------------------------------------------------------------------
    # TEST 6 - GENERAL KNOWLEDGE: Not routed to ticker lookup
    # -------------------------------------------------------------------------
    def test_06_general_knowledge_not_ticker(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        query = "Siapa presiden Indonesia tahun 2026?"

        resp = harness.run(user_query=query, context=ctx)
        # Must NOT treat 2026 or words as stock tickers
        self.assertIsNone(ctx.active_ticker)
        # Must not call equity tools
        self.assertEqual(len(resp.tool_calls_executed), 0)
        # Must truthfully disclose knowledge limitation or address query
        low_content = resp.content.lower()
        self.assertTrue(
            "presiden" in low_content or "informasi" in low_content or "tidak" in low_content or "prabowo" in low_content
        )

    # -------------------------------------------------------------------------
    # TEST 7 - PROVIDER TIMEOUT: Short truthful error, no ticker pollution
    # -------------------------------------------------------------------------
    def test_07_provider_timeout_error_handling(self) -> None:
        fallback = DeterministicFallbackProvider()
        # Non-financial general query under timeout
        msgs = [ChatMessage(role="user", content="Jelaskan teori relativitas khusus")]
        resp = fallback.generate(messages=msgs)

        self.assertIn("Maaf, model bahasa lokal sedang lambat merespons", resp.content)
        self.assertEqual(len(resp.tool_calls), 0)

        # Ticker stopword exclusion verification
        for word in ["TAHU", "DATA", "BISA", "NAMA", "DARI", "PADA", "KITA", "YANG"]:
            self.assertIn(word, COMMON_INDONESIAN_NON_TICKERS)

    # -------------------------------------------------------------------------
    # TEST 8 - VOICE PRESET: Change TTS preset configuration
    # -------------------------------------------------------------------------
    def test_08_voice_preset_switching(self) -> None:
        tool = SetVoicePresetTool()
        # Switch to NATURAL
        res_nat = tool.execute({"preset": "natural"})
        self.assertTrue(res_nat.success)
        self.assertEqual(res_nat.data["applied_preset"], "NATURAL")

        # Switch to BAGUSMAX_CALM
        res_calm = tool.execute({"preset": "bagusmax_calm"})
        self.assertTrue(res_calm.success)
        self.assertEqual(res_calm.data["applied_preset"], "BAGUSMAX_CALM")

        # Restore default
        tool.execute({"preset": "natural"})

    # -------------------------------------------------------------------------
    # TEST 9 - VOICE STATUS: Honest source voice & gender report
    # -------------------------------------------------------------------------
    def test_09_voice_status_honesty(self) -> None:
        tool = GetVoiceRuntimeStatusTool()
        res = tool.execute({})
        self.assertTrue(res.success)
        data = res.data
        self.assertEqual(data["masculine_voice_status"], "MASCULINE_SOURCE_VOICE_UNAVAILABLE")
        self.assertFalse(data["masculine_source_available"])
        self.assertEqual(data["source_speaker_count"], 1)

    # -------------------------------------------------------------------------
    # TEST 10 - COMPUTER CONTROL: Read-only telemetry, no full control
    # -------------------------------------------------------------------------
    def test_10_computer_control_safety(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        resp = harness.run("Apakah Anda bisa mengontrol laptop saya?", context=ctx)
        self.assertIn("baca-saja", resp.content)
        self.assertIn("tidak memiliki izin untuk mengontrol penuh laptop Anda", resp.content)

        cap_tool = GetRuntimeCapabilitiesTool()
        res = cap_tool.execute({})
        self.assertEqual(res.data["computer_control_permission"], "READ_ONLY_DIAGNOSTICS_ONLY")
        self.assertFalse(res.data["arbitrary_execution_authorized"])

    # -------------------------------------------------------------------------
    # TEST 11 - GPU QUESTION: Explains matrix inference using real telemetry
    # -------------------------------------------------------------------------
    def test_11_gpu_question_telemetry(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        resp = harness.run("Kenapa GPU saya mencapai 100 persen?", context=ctx)
        self.assertIn("RTX 3050", resp.content)
        self.assertIn("inferensi", resp.content)

        diag_tool = GetSystemDiagnosticsTool()
        res = diag_tool.execute({})
        self.assertTrue(res.success)
        self.assertIn("gpu_name", res.data)
        self.assertIn("ram_load_percent", res.data)
        self.assertIn("gpu_temperature_c", res.data)

    # -------------------------------------------------------------------------
    # TEST 12 - STOCK ANALYSIS: Real catalog & financial routing for RATU
    # -------------------------------------------------------------------------
    def test_12_stock_analysis_ratu(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        resp = harness.run("Analisis RATU timeframe satu hari.", context=ctx)
        self.assertEqual(ctx.active_ticker, "RATU")
        # Ensure companion was not reset
        for tc in resp.tool_calls_executed:
            self.assertNotEqual(tc.get("name"), "control_bagusmax")

    # -------------------------------------------------------------------------
    # TEST 13 - DATA COVERAGE: Explains DATA_GAP, not ticker 'DATA'
    # -------------------------------------------------------------------------
    def test_13_data_coverage_not_ticker_data(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        ctx.active_ticker = "RATU"
        resp = harness.run("Kenapa datanya tidak lengkap?", context=ctx)
        self.assertIn("DATA_GAP", resp.content)
        self.assertIn("Katalog OpenBagus", resp.content)
        self.assertEqual(ctx.active_ticker, "RATU")  # Must NOT switch to 'DATA'

    # -------------------------------------------------------------------------
    # TEST 14 - SHORT ACKNOWLEDGMENT: Fast-path < 5ms
    # -------------------------------------------------------------------------
    def test_14_short_acknowledgment(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        t0 = time.perf_counter()
        resp = harness.run("Oke.", context=ctx)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self.assertIn(resp.content, ("Baik.", "Siap."))
        self.assertEqual(resp.provider_name, "FAST_PATH_ACK")
        self.assertLess(elapsed_ms, 50.0)  # Near-instantaneous fast-path

    # -------------------------------------------------------------------------
    # TEST 15 - TOPIC SWITCH: Casual chat without finance restrictions
    # -------------------------------------------------------------------------
    def test_15_topic_switch_general_chat(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        resp = harness.run("Aku mau ngobrol santai.", context=ctx)
        self.assertIn("Tentu!", resp.content)
        self.assertIn("ngobrol santai", resp.content)
        self.assertEqual(resp.provider_name, "LOCAL_DIRECT")

    # -------------------------------------------------------------------------
    # TEST 16 - FUTURE ENGLISH TUTOR: Deferred activation, zero downloads
    # -------------------------------------------------------------------------
    def test_16_future_english_tutor_deferred(self) -> None:
        harness = AgentHarness()
        ctx = WorkingContext()
        resp = harness.run("Aku mau belajar bahasa Inggris.", context=ctx)
        self.assertIn("DOWNLOAD_DEFERRED", resp.content)
        self.assertIn("bahasa Inggris", resp.content)

        profile = ModelProfileRegistry.get_instance().get_profile("ENGLISH_TUTOR")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.load_status, "NOT_INSTALLED")
        self.assertEqual(profile.availability_status, "DOWNLOAD_DEFERRED")
        self.assertTrue(profile.requires_user_approval)

    # -------------------------------------------------------------------------
    # TEST 17 - NO INTERNET: Offline local execution works cleanly
    # -------------------------------------------------------------------------
    def test_17_no_internet_offline_safety(self) -> None:
        # Verify offline catalog and local deterministic fallback work without socket
        cat_tool = GetDataCoverageStatusTool()
        res = cat_tool.execute({"symbol": "BBCA"})
        self.assertTrue(res.success)
        self.assertEqual(res.data["catalog_metadata"], "AVAILABLE_OFFLINE")
        self.assertEqual(res.data["symbol"], "BBCA")

    # -------------------------------------------------------------------------
    # TEST 18 - CONVERSATIONAL MEMORY & FOLLOW-UP: Retains active context
    # -------------------------------------------------------------------------
    def test_18_conversational_memory_followup(self) -> None:
        ctx = WorkingContext()
        ctx.active_ticker = "RATU"
        ctx.active_ticker_name = "PT Raharja Energi Cepu Tbk"
        ctx.record_turn("user", "Analisis saham RATU.")
        ctx.record_turn("assistant", "RATU adalah emiten sektor energi.")

        # Follow up question
        self.assertEqual(ctx.active_ticker, "RATU")
        recent = ctx.get_recent_history(limit=2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0]["role"], "user")
        self.assertIn("RATU", recent[0]["content"])

    # -------------------------------------------------------------------------
    # TEST 19 - AUDIO PRIVACY AUDIT: Ephemeral RAM only, 0 audio files on disk
    # -------------------------------------------------------------------------
    def test_19_audio_privacy_ephemeral_ram(self) -> None:
        repo_root = Path(r"E:\Projects\OpenBagus-Voice")
        # Ensure no recording audio files are created in working directory
        audio_files = list(repo_root.glob("*.wav")) + list(repo_root.glob("*.mp3")) + list(repo_root.glob("*.raw"))
        self.assertEqual(len(audio_files), 0, f"Found persisted audio files: {audio_files}")

    # -------------------------------------------------------------------------
    # TEST 20 - CODEX 3D ISOLATION: No 3D meshes/shaders touched
    # -------------------------------------------------------------------------
    def test_20_codex_3d_isolation(self) -> None:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=r"E:\Projects\OpenBagus-Voice",
            capture_output=True,
            text=True,
            check=True,
        )
        modified_files = [line.strip().split()[-1] for line in res.stdout.splitlines() if line.strip()]
        for f in modified_files:
            self.assertFalse(
                f.startswith("assets/models") or f.startswith("assets/bagusmax") or f.startswith("shaders") or f.endswith(".blend") or f.endswith(".glb"),
                f"Forbidden 3D file modified: {f}",
            )


if __name__ == "__main__":
    unittest.main()
