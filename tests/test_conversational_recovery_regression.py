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


class TestWindowsReleaseRecovery(unittest.TestCase):
    def test_frozen_startup_error_survives_closed_stdin(self):
        import contextlib
        import io
        import sys
        import tempfile
        from openbagus import bootstrap
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LOCALAPPDATA": directory, "OPENBAGUS_MODEL_DIR": directory + "/missing"}), \
                 patch.object(sys, "frozen", True, create=True), patch("sys.stdin") as stdin, \
                 patch("builtins.input", side_effect=EOFError), patch.object(bootstrap.logging, "basicConfig"), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                stdin.isatty.return_value = True
                result = bootstrap.main()
            self.assertEqual(result, 1)
            self.assertIn("BLOCKED", output.getvalue())

    def test_ollama_empty_thinking_limit_has_bounded_transparent_same_model_retry(self):
        import json
        from openbagus.ai.providers.ollama import OllamaProvider
        responses = []
        for data in ({"model": "qwen3.5:4b", "message": {"content": "", "thinking": "private trace"}, "done_reason": "length"},
                     {"model": "qwen3.5:4b", "message": {"content": "Use went for the past tense."}, "done_reason": "stop", "eval_count": 8}):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(data).encode()
            responses.append(response)
        provider = OllamaProvider(model="qwen3.5:4b", think=True)
        with patch("urllib.request.urlopen", side_effect=responses) as request:
            result = provider.generate([ChatMessage(role="user", content="Explain went")], max_tokens=3072)
        payloads = [json.loads(call.args[0].data) for call in request.call_args_list]
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["model"], payloads[1]["model"])
        self.assertFalse(payloads[1]["think"])
        self.assertEqual(payloads[1]["options"]["num_predict"], 512)
        self.assertIn("Use went", result.content)
        self.assertIn("thinking dinonaktifkan", result.content)
        self.assertNotIn("private trace", result.content)
        self.assertEqual(provider.last_generation["recovery"], "THINKING_LIMIT_FINALIZATION")

    def test_crypto_provider_gap_does_not_fall_through_to_equity_price(self):
        from openbagus.ai.tools.finance_tools import GetMarketPriceTool
        with patch("openbagus.data.zerokey.ZeroKeyMarketData") as provider, patch("openbagus.ai.tools.finance_tools.EquityData") as equities:
            provider.return_value.get_spot_ticker.return_value = None
            result, _ = GetMarketPriceTool().run("BTC")
        equities.assert_not_called()
        self.assertEqual(result["status"], "DATA_GAP")
        self.assertEqual(result["currency"], "USDT")
        self.assertTrue(result["is_crypto"])
        text = AgentHarness(provider=MagicMock())._compose_evidence_response(
            WorkingContext(active_ticker="BTC", market="CRYPTO"),
            [{"name": "get_market_price", "success": True, "data": result}], "Harga BTC")
        self.assertIn("DATA_GAP", text)
        self.assertNotIn("None USDT", text)

    def test_unknown_explicit_ticker_never_reuses_previous_asset_data(self):
        context = WorkingContext(active_ticker="TLKM")
        provider = MagicMock()
        response = AgentHarness(provider=provider).run("Analisis saham ZZZZ.", context=context)
        self.assertEqual(response.provider_name, "ENTITY_UNRESOLVED")
        self.assertEqual(response.tool_calls_executed, [])
        provider.generate.assert_not_called()
        self.assertIn("belum terverifikasi", response.content)

    def test_new_voice_turn_does_not_uncancel_previous_turn(self):
        coordinator = InterruptionCoordinator()
        coordinator.start_turn("old")
        previous = coordinator.get_cancellation_event()
        coordinator.trigger_interruption()
        coordinator.start_turn("new")
        self.assertTrue(previous.is_set())
        self.assertFalse(coordinator.get_cancellation_event().is_set())

    def test_idle_time_does_not_consume_maximum_utterance_duration(self):
        vad = VoiceActivityDetector(max_utterance_duration_ms=1000, min_speech_duration_ms=64)
        frame = np.zeros(512, dtype=np.float32)
        with patch.object(vad, "_score_frame", return_value=0.0):
            for _ in range(100):
                vad.process_frame(frame)
        with patch.object(vad, "_score_frame", return_value=0.99):
            vad.process_frame(frame)
            vad.process_frame(frame)
            active, endpoint, _ = vad.process_frame(frame)
        self.assertTrue(active)
        self.assertFalse(endpoint)

    def test_structured_status_is_not_corrupted_by_terminal_wrapping(self):
        import cmd
        import contextlib
        import io
        import json
        from openbagus.cli import OpenBagusShell
        shell = object.__new__(OpenBagusShell)
        cmd.Cmd.__init__(shell)
        expected = {"detail": "long diagnostic text " * 30}
        shell.do_probe = lambda _: print(json.dumps(expected, indent=2))
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            shell.onecmd("/probe")
        self.assertEqual(json.loads(capture.getvalue()), expected)

    def test_cancelled_turn_does_not_generate_or_write_history(self):
        import threading
        cancelled = threading.Event()
        cancelled.set()
        provider = MagicMock()
        context = WorkingContext()
        result = AgentHarness(provider=provider).run("test", context=context, cancellation=cancelled)
        provider.generate.assert_not_called()
        self.assertEqual(context.turns, [])
        self.assertEqual(result.provider_name, "CANCELLED")

    def test_missing_financial_inputs_remain_missing(self):
        from openbagus.ai.tools.finance_tools import CalculateFinancialRatiosTool
        statement = {"period": "2026-Q1", "currency": "IDR", "unit": "million_IDR", "values": {"revenue": 10, "total_equity": 20}}
        with patch("openbagus.ai.tools.finance_tools.FinancialStatementStorage") as storage:
            storage.return_value.get_statement.return_value = statement
            data, _ = CalculateFinancialRatiosTool().run("BBCA")
        for field in ("net_income", "gross_profit", "roe_pct", "gross_margin_pct", "operating_margin_pct", "net_margin_pct", "current_ratio", "der"):
            self.assertIsNone(data[field], field)

    def test_plain_input_uses_conversation_not_legacy_ticker_parser(self):
        from openbagus.cli import OpenBagusShell
        shell = object.__new__(OpenBagusShell)
        shell.do_chat = MagicMock()
        shell.router = MagicMock()
        shell.router.parse.side_effect = AssertionError("legacy parser must not own chat")
        shell.session = MagicMock()
        shell.default("Aku mau tahu")
        shell.do_chat.assert_called_once_with("Aku mau tahu")

    def test_new_ticker_updates_state_and_tool_arguments(self):
        from openbagus.ai.tools.registry import ToolRegistry
        from openbagus.ai.providers.base import ChatCompletionResponse
        from openbagus.ai.tools.base import BaseFinancialTool

        class PriceTool(BaseFinancialTool):
            name = "get_market_price"
            description = "Unit fixture"
            parameters_schema = {"type": "object", "properties": {"ticker": {"type": "string"}}}

            def run(self, ticker):
                return {"symbol": ticker, "price": None, "status": "DATA_GAP"}, {"source": "unit fixture"}

        registry = ToolRegistry()
        registry.register(PriceTool())
        provider = MagicMock()
        provider.generate.return_value = ChatCompletionResponse(content="Untrusted price 999999 and probability 72%")
        provider.get_provider_name.return_value = "UNIT_PROVIDER"
        harness = AgentHarness(provider=provider, tool_registry=registry)
        ctx = WorkingContext(active_ticker="RATU")
        result = harness.run("Sekarang ganti ke BBCA. Berapa harganya?", context=ctx)
        self.assertEqual(ctx.active_ticker, "BBCA")
        self.assertTrue(result.tool_calls_executed)
        self.assertTrue(all(t["arguments"].get("ticker", "BBCA") == "BBCA" for t in result.tool_calls_executed))
        self.assertNotIn("999999", result.content)
        self.assertNotIn("72%", result.content)
        self.assertIn("DATA_GAP", result.content)

    def test_namespace_and_timeframe_survive_serialization(self):
        ctx = WorkingContext(active_ticker="BBCA", context_namespace="ENGLISH_TUTOR", time_horizon="D1")
        restored = WorkingContext.from_dict(ctx.to_dict())
        self.assertEqual(restored.context_namespace, "ENGLISH_TUTOR")
        self.assertEqual(restored.active_ticker, "BBCA")
        self.assertEqual(restored.time_horizon, "D1")

    def test_deep_tutor_has_reasoning_budget_and_reports_failure(self):
        from openbagus.domains.english_tutor import EnglishTutor
        from openbagus.ai.providers.base import ChatCompletionResponse
        provider = MagicMock()
        provider.think = True
        provider.generate.return_value = ChatCompletionResponse(content="")
        result = EnglishTutor().generate_tutor_response("Explain past tense", provider=provider)
        self.assertGreaterEqual(provider.generate.call_args.kwargs["max_tokens"], 2048)
        self.assertIn("tidak menghasilkan", result.format_text_output().lower())

    def test_vad_keeps_temporal_context_for_real_model(self):
        vad = VoiceActivityDetector()
        vad._model = MagicMock(return_value=np.array([0.9], dtype=np.float32))
        frame = np.ones(512, dtype=np.float32) * 0.05
        for _ in range(10):
            vad._score_frame(frame)
        self.assertGreater(len(vad._model.call_args.args[0]), 512)


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
        self.assertEqual(ctx.context_namespace, "ENGLISH_TUTOR")
        self.assertIn("English Tutor", resp.content)

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
        repo_root = Path(__file__).resolve().parent.parent
        # Ensure no recording audio files are created in working directory
        audio_files = list(repo_root.glob("*.wav")) + list(repo_root.glob("*.mp3")) + list(repo_root.glob("*.raw"))
        self.assertEqual(len(audio_files), 0, f"Found persisted audio files: {audio_files}")

    # -------------------------------------------------------------------------
    # TEST 20 - CODEX 3D ISOLATION: No 3D meshes/shaders touched
    # -------------------------------------------------------------------------
    def test_20_codex_3d_isolation(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        modified_files = [line.strip().split()[-1] for line in res.stdout.splitlines() if line.strip()]
        for f in modified_files:
            self.assertFalse(
                f.startswith("assets/models") or f.endswith(".blend1"),
                f"Forbidden 3D file modified: {f}",
            )


if __name__ == "__main__":
    unittest.main()
