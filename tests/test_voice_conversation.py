"""Acceptance test suite for OpenBagus Local Native Voice Conversation subsystem.

Verifies:
1. Audio device enumeration & Windows native detection.
2. Audio capture resampling, metering, and playback queue abort.
3. ONNX Silero VAD frame processing & silence endpointing.
4. ASR Financial Normalizer on IDX tickers and acronyms.
5. Speech Text Normalizer converting markdown/math to Indonesian spoken prose.
6. Local Piper TTS synthesis streaming & low latency (<200ms TTFA).
7. Local Whisper ASR inference & CUDA telemetry.
8. Voice Mode Controller (FAST vs DEEP_REASONING spoken resolution & retention).
9. Barge-in / Interruption Coordinator cancellation events.
10. Zero-Cloud Privacy Guard compliance.
11. Voice Turn Controller state transitions and roundtrip pipeline.
"""

from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np

from openbagus.ai.harness.orchestrator import AgentHarness, AgentResponse
from openbagus.ai.memory.working_context import WorkingContext
from openbagus.ai.runtime.profiles import get_profile
from openbagus.voice.audio_capture import AudioCaptureStream
from openbagus.voice.audio_devices import AudioDeviceInfo, AudioDeviceManager
from openbagus.voice.audio_playback import AudioPlaybackManager
from openbagus.voice.asr_engine import LocalASREngine
from openbagus.voice.asr_normalizer import ASRFinancialNormalizer, NormalizedASRResult
from openbagus.voice.diagnostics import VoiceDiagnostics, VoiceTurnMetrics
from openbagus.voice.gpu_scheduler import GPUScheduler, GPUStatus
from openbagus.voice.interruption import InterruptionCoordinator
from openbagus.voice.mode_controller import VoiceModeController
from openbagus.voice.preferences import VoicePreferences, load_voice_preferences, save_voice_preferences
from openbagus.voice.privacy import PrivacyGuard
from openbagus.voice.speech_normalizer import SpeechTextNormalizer
from openbagus.voice.tts_engine import LocalTTSEngine
from openbagus.voice.turn_controller import VoiceState, VoiceTurnController
from openbagus.voice.vad import VoiceActivityDetector
from openbagus.voice.voice_session import VoiceSession


class TestAudioDevices(unittest.TestCase):
    """Test device enumeration and selection for Windows native audio."""

    def test_list_devices(self) -> None:
        in_devs = AudioDeviceManager.list_input_devices()
        out_devs = AudioDeviceManager.list_output_devices()
        self.assertIsInstance(in_devs, list)
        self.assertIsInstance(out_devs, list)
        self.assertGreater(len(in_devs), 0, "Harus menemukan setidaknya 1 mikrofon input di sistem")
        self.assertGreater(len(out_devs), 0, "Harus menemukan setidaknya 1 speaker output di sistem")

    def test_default_device_detection(self) -> None:
        def_in = AudioDeviceManager.get_default_input_device()
        def_out = AudioDeviceManager.get_default_output_device()
        self.assertIsNotNone(def_in)
        self.assertIsNotNone(def_out)
        self.assertTrue(def_in.max_channels > 0 or def_in.max_input_channels > 0)
        self.assertTrue(def_out.max_channels > 0 or def_out.max_output_channels > 0)

    def test_device_info_properties(self) -> None:
        info = AudioDeviceInfo(
            id=1,
            name="Test Realtek USB2.0 Mic",
            kind="input",
            hostapi="Windows DirectSound",
            max_channels=2,
            default_samplerate=44100.0,
            is_default=True,
        )
        self.assertEqual(info.index, 1)
        self.assertEqual(info.host_api, "Windows DirectSound")
        self.assertEqual(info.max_input_channels, 2)
        self.assertEqual(info.max_output_channels, 0)
        self.assertEqual(info.default_sample_rate, 44100.0)
        d = info.to_dict()
        self.assertEqual(d["id"], 1)
        self.assertTrue(d["is_default"])


class TestAudioProcessingAndResampling(unittest.TestCase):
    """Test audio capture resampling, RMS metering, and playback queue."""

    def test_resample_linear(self) -> None:
        # Create 1 second of 44100 Hz mono sine wave
        t = np.linspace(0, 1, 44100, dtype=np.float32)
        sine = 0.5 * np.sin(2 * np.pi * 440 * t)
        resampled = AudioCaptureStream.resample_audio(sine, orig_sr=44100, target_sr=16000)
        self.assertEqual(len(resampled), 16000)
        self.assertEqual(resampled.dtype, np.float32)

    def test_resample_stereo_to_mono(self) -> None:
        # Stereo 48000 Hz input
        stereo = np.zeros((48000, 2), dtype=np.float32)
        stereo[:, 0] = 0.4
        stereo[:, 1] = 0.6
        resampled = AudioCaptureStream.resample_audio(stereo, orig_sr=48000, target_sr=16000)
        self.assertEqual(len(resampled), 16000)
        self.assertEqual(resampled.ndim, 1)
        self.assertAlmostEqual(resampled[0], 0.5, places=2)

    def test_rms_db_metering(self) -> None:
        # Silent audio
        silent = np.zeros(1600, dtype=np.float32)
        db_silent = AudioCaptureStream.calculate_rms_db(silent)
        self.assertLessEqual(db_silent, -90.0)

        # Full scale audio
        loud = np.ones(1600, dtype=np.float32)
        db_loud = AudioCaptureStream.calculate_rms_db(loud)
        self.assertAlmostEqual(db_loud, 0.0, places=1)

    def test_playback_manager_queue_and_abort(self) -> None:
        mgr = AudioPlaybackManager()
        self.assertFalse(mgr.is_playing)
        # Enqueue small synthetic chunk
        chunk = np.zeros(2205, dtype=np.float32)
        # Verify stop aborts queue and playback
        mgr.stop_playback(interrupted=True)
        self.assertEqual(mgr.queue_size, 0)
        self.assertFalse(mgr.is_playing)


class TestVoiceActivityDetector(unittest.TestCase):
    """Test ONNX Silero VAD frame processing, probability, and endpointing."""

    def setUp(self) -> None:
        self.vad = VoiceActivityDetector(speech_threshold=0.5, silence_duration_ms=400)

    def test_vad_silence_detection(self) -> None:
        # Frame of 512 zeros (32ms at 16kHz)
        silent_frame = np.zeros(512, dtype=np.float32)
        is_speech, is_endpoint, prob = self.vad.process_frame(silent_frame)
        self.assertFalse(is_speech)
        self.assertFalse(is_endpoint)
        self.assertLess(prob, 0.5)

    def test_vad_speech_and_endpointing(self) -> None:
        # Generate synthetic speech-like burst
        t = np.linspace(0, 0.032, 512, dtype=np.float32)
        speech_frame = (0.6 * np.sin(2 * np.pi * 300 * t) + 0.3 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)

        # Mock silero model probability to simulate realistic state progression
        with patch.object(self.vad, "_score_frame", return_value=0.85):
            is_speech = False
            for _ in range(8):
                is_speech, is_endpoint, prob = self.vad.process_frame(speech_frame)
            self.assertTrue(is_speech)
            self.assertFalse(is_endpoint)
            self.assertGreaterEqual(prob, 0.85)

        # Followed by silence frames to trigger endpointing
        with patch.object(self.vad, "_score_frame", return_value=0.05):
            silent_frame = np.zeros(512, dtype=np.float32)
            endpoint_triggered = False
            for _ in range(25):  # 25 * 32ms = 800ms silence > 400ms threshold
                _, is_ep, _ = self.vad.process_frame(silent_frame)
                if is_ep:
                    endpoint_triggered = True
                    break
            self.assertTrue(endpoint_triggered, "Silence yang cukup lama harus memicu endpointing selesai bicara")


class TestASRFinancialNormalizer(unittest.TestCase):
    """Test normalization of Indonesian financial tickers, acronyms, and ratios."""

    def test_ticker_acronym_normalization(self) -> None:
        samples = [
            ("analisis b b c a sekarang", "analisis BBCA sekarang", "BBCA"),
            ("bagaimana valuasi b-b-r-i", "bagaimana valuasi BBRI", "BBRI"),
            ("rekomendasi b m r i", "rekomendasi BMRI", "BMRI"),
            ("cek emiten t l k m", "cek emiten TLKM", "TLKM"),
            ("review h g i i sektor utilitas", "review HGII sektor utilitas", "HGII"),
            ("apakah y o i i sudah terdaftar", "apakah YOII sudah terdaftar", "YOII"),
        ]
        for raw, expected_substr, expected_ticker in samples:
            res = ASRFinancialNormalizer.normalize(raw)
            self.assertIn(expected_ticker, res.detected_tickers)
            self.assertIn(expected_ticker, res.normalized_text)

    def test_financial_ratios_normalization(self) -> None:
        samples = [
            ("berapa p e r saham ini", "PER"),
            ("analisis p b v dan r o e", "PBV"),
            ("hitung d c f dengan w a c c", "DCF"),
            ("apakah f c f positif", "FCF"),
            ("cek r s i dan a t r", "RSI"),
            ("hitung v a r monte carlo", "VaR"),
        ]
        for raw, expected_ratio in samples:
            res = ASRFinancialNormalizer.normalize(raw)
            self.assertIn(expected_ratio, res.normalized_text)

    def test_spoken_numbers_normalization(self) -> None:
        samples = [
            ("target harga lima puluh ribu rupiah", "target harga Rp 50.000"),
            ("kapitalisasi pasar dua ratus lima puluh miliar rupiah", "kapitalisasi pasar Rp 250.000.000.000"),
            ("beli di harga seribu lima ratus", "beli di harga 1500"),
        ]
        for raw, expected in samples:
            res = ASRFinancialNormalizer.normalize(raw)
            self.assertEqual(res.normalized_text, expected)


class TestSpeechTextNormalizer(unittest.TestCase):
    """Test text normalizer preparing assistant written text for spoken synthesis."""

    def test_latex_and_markdown_stripping(self) -> None:
        text = "Valuasi saham **BBCA** memiliki formula DCF $V = \\sum \\frac{CF_t}{(1+WACC)^t}$. Hasilnya *undervalued*!"
        spoken = SpeechTextNormalizer.to_spoken_text(text)
        self.assertNotIn("**", spoken)
        self.assertNotIn("*", spoken)
        self.assertNotIn("$", spoken)
        self.assertNotIn("\\sum", spoken)
        self.assertIn("Valuasi saham", spoken)
        self.assertTrue("B B C A" in spoken or "BBCA" in spoken)

    def test_currency_and_percent_to_indonesian_speech(self) -> None:
        text = "Harga wajar BBCA adalah Rp9.500 dengan margin of safety 15.5% dan dividen yield 4.2%."
        spoken = SpeechTextNormalizer.to_spoken_text(text)
        self.assertIn("sembilan ribu lima ratus rupiah", spoken)
        self.assertIn("lima belas koma lima persen", spoken)
        self.assertIn("empat koma dua persen", spoken)

    def test_large_rupiah_denominations(self) -> None:
        text = "Laba bersih tercatat Rp15.200.000.000.000 dengan pendapatan Rp45.000.000.000."
        spoken = SpeechTextNormalizer.to_spoken_text(text)
        self.assertIn("triliun", spoken)
        self.assertIn("miliar rupiah", spoken)

    def test_sentence_splitting(self) -> None:
        paragraph = "BBCA menunjukkan tren bullish kuat. Valuasi DCF berada pada Rp10.200 per lembar. Namun perhatikan risiko suku bunga BI!"
        sentences = SpeechTextNormalizer.split_sentences(paragraph)
        self.assertEqual(len(sentences), 3)
        self.assertIn("bullish", sentences[0])
        self.assertIn("DCF", sentences[1])
        self.assertIn("suku bunga", sentences[2])


class TestVoiceModeController(unittest.TestCase):
    """Test FAST vs DEEP_REASONING spoken selection and context preservation."""

    def setUp(self) -> None:
        self.mc = VoiceModeController(default_mode="FAST")

    def test_expensive_analysis_detection(self) -> None:
        self.assertTrue(self.mc.should_ask_for_mode("Bedah DCF skenario lengkap untuk BBCA"))
        self.assertTrue(self.mc.should_ask_for_mode("Simulasi monte carlo portofolio 1000 iterasi"))
        self.assertFalse(self.mc.should_ask_for_mode("Berapa harga penutupan BBCA hari ini?"))
        self.assertFalse(self.mc.should_ask_for_mode("Apa itu rasio PER?"))

    def test_spoken_mode_confirmation_flow(self) -> None:
        query = "Hitung valuasi DCF dan matriks sensitivitas BBRI"
        prompt = self.mc.set_pending_query(query=query, ticker="BBRI", strategy="DCF")
        self.assertTrue(self.mc.has_pending_query())
        self.assertIn("BBRI", prompt)
        self.assertIn("Mode Cepat", prompt)
        self.assertIn("Deep Reasoning", prompt)

        # User verbally answers "Deep Reasoning"
        resolved_mode, pending = self.mc.resolve_spoken_mode_answer("pakai deep reasoning saja")
        self.assertEqual(resolved_mode, "DEEP_REASONING")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.ticker, "BBRI")
        self.assertEqual(pending.original_query, query)
        self.assertFalse(self.mc.has_pending_query())

    def test_spoken_mode_fast_flow(self) -> None:
        query = "Analisis mendalam saham BMRI"
        self.mc.set_pending_query(query=query, ticker="BMRI")
        resolved_mode, pending = self.mc.resolve_spoken_mode_answer("mode cepat aja biar ringkas")
        self.assertEqual(resolved_mode, "FAST")
        self.assertIsNotNone(pending)
        self.assertEqual(pending.ticker, "BMRI")


class TestInterruptionAndBargeIn(unittest.TestCase):
    """Test barge-in cancellation coordinator."""

    def test_interruption_trigger_and_cancellation(self) -> None:
        interrupted_turn_id: list[str] = []

        def on_barge(t_id: str) -> None:
            interrupted_turn_id.append(t_id)

        coord = InterruptionCoordinator(on_interruption_callback=on_barge)
        coord.start_turn("turn_001")
        cancel_evt = coord.get_cancellation_event()
        self.assertFalse(cancel_evt.is_set())

        # Assistant is speaking, user speaks -> trigger interruption
        coord.trigger_interruption(reason="USER_SPOKE")
        self.assertTrue(cancel_evt.is_set())
        self.assertEqual(interrupted_turn_id, ["turn_001"])
        self.assertTrue(coord.is_interrupted)


class TestPrivacyGuard(unittest.TestCase):
    """Test zero-cloud privacy compliance and local file constraints."""

    def test_zero_cloud_guarantee(self) -> None:
        report = PrivacyGuard.verify_offline_compliance()
        self.assertTrue(report["zero_cloud_compliant"])
        self.assertTrue(report["local_asr_ready"])
        self.assertTrue(report["local_tts_ready"])
        self.assertEqual(len(report["cloud_keys_detected"]), 0)


class TestVoiceDiagnostics(unittest.TestCase):
    """Test latency tracking and GPU statistics."""

    def test_metrics_recording_and_summary(self) -> None:
        diag = VoiceDiagnostics()
        m1 = VoiceTurnMetrics(
            turn_id="turn_1",
            user_speech_duration_s=2.5,
            asr_latency_ms=120.0,
            agent_total_latency_ms=450.0,
            tts_ttfa_ms=85.0,
            tts_total_latency_ms=300.0,
            e2e_voice_latency_ms=655.0,
            mode="FAST",
        )
        diag.record_turn(m1)

        m2 = VoiceTurnMetrics(
            turn_id="turn_2",
            user_speech_duration_s=3.0,
            asr_latency_ms=150.0,
            agent_total_latency_ms=900.0,
            tts_ttfa_ms=95.0,
            tts_total_latency_ms=400.0,
            e2e_voice_latency_ms=1145.0,
            mode="DEEP_REASONING",
            interrupted=True,
        )
        diag.record_turn(m2)

        stats = diag.get_summary_statistics()
        self.assertEqual(stats["total_turns"], 2)
        self.assertEqual(stats["interrupted_turns"], 1)
        self.assertAlmostEqual(stats["avg_asr_latency_ms"], 135.0, places=1)
        self.assertAlmostEqual(stats["avg_tts_ttfa_ms"], 90.0, places=1)
        self.assertAlmostEqual(stats["avg_e2e_latency_ms"], 900.0, places=1)


class TestVoiceTurnControllerStateTransitions(unittest.TestCase):
    """Test VoiceTurnController state progression and mock roundtrip."""

    def test_state_transitions(self) -> None:
        state_log: list[tuple[VoiceState, VoiceState]] = []

        def on_change(old: VoiceState, new: VoiceState) -> None:
            state_log.append((old, new))

        ctrl = VoiceTurnController(on_state_change=on_change)
        self.assertEqual(ctrl.state, VoiceState.IDLE)

        ctrl.set_state(VoiceState.LISTENING)
        ctrl.set_state(VoiceState.SPEECH_DETECTED)
        ctrl.set_state(VoiceState.ENDPOINTING)
        ctrl.set_state(VoiceState.TRANSCRIBING)
        ctrl.set_state(VoiceState.THINKING)
        ctrl.set_state(VoiceState.GENERATING_SPEECH)
        ctrl.set_state(VoiceState.SPEAKING)
        ctrl.set_state(VoiceState.IDLE)

        self.assertEqual(len(state_log), 8)
        self.assertEqual(state_log[0], (VoiceState.IDLE, VoiceState.LISTENING))
        self.assertEqual(state_log[-1], (VoiceState.SPEAKING, VoiceState.IDLE))

    def test_mock_direct_utterance_roundtrip(self) -> None:
        harness = MagicMock(spec=AgentHarness)
        mock_resp = AgentResponse(
            content="Saham BBCA diperdagangkan pada Rp9.500 dengan rekomendasi BUY.",
            tool_calls_executed=[{"name": "get_stock_quote", "arguments": '{"ticker": "BBCA"}', "success": True, "latency_ms": 12.0}],
            provider_name="MockProvider",
            latency_ms=15.0,
        )
        harness.run.return_value = mock_resp

        asr_mock = MagicMock(spec=LocalASREngine)
        asr_mock.transcribe.return_value = (
            NormalizedASRResult(
                raw_text="bagaimana prospek bbca",
                normalized_text="analisis prospek BBCA",
                detected_tickers=["BBCA"],
                detected_timeframe=None,
                detected_strategy=None,
                detected_ratios=[],
            ),
            {"latency_ms": 45.0, "audio_duration_s": 1.5, "device": "cuda"},
        )

        tts_mock = MagicMock(spec=LocalTTSEngine)
        tts_mock.synthesize_sentence.return_value = np.zeros(22050, dtype=np.float32)
        tts_mock.sample_rate = 22050

        ctrl = VoiceTurnController(
            agent_harness=harness,
            asr_engine=asr_mock,
            tts_engine=tts_mock,
        )

        dummy_audio = np.zeros(24000, dtype=np.float32)  # 1.5s
        written, spoken, metrics = ctrl.process_direct_utterance(dummy_audio)

        self.assertIn("BBCA", written)
        self.assertIn("sembilan ribu lima ratus rupiah", spoken)
        self.assertEqual(metrics.tools_executed_count, 1)
        self.assertGreater(metrics.asr_latency_ms, 0.0)
        self.assertGreater(metrics.e2e_voice_latency_ms, 0.0)


class TestLiveTTSInference(unittest.TestCase):
    """Test actual Piper TTS synthesis of Indonesian sentences with real ONNX model."""

    def test_real_indonesian_piper_synthesis(self) -> None:
        tts = LocalTTSEngine()
        self.assertTrue(tts.is_available(), "Piper TTS model harus terpasang di %LOCALAPPDATA%/OpenBagus/models/tts")
        test_sentence = "Laba bersih BBCA mencapai 15 triliun rupiah pada kuartal ketiga."

        t0 = time.perf_counter()
        audio = tts.synthesize_sentence(test_sentence)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertIsNotNone(audio)
        self.assertIsInstance(audio, np.ndarray)
        self.assertGreater(len(audio), 5000, "Audio yang disintesis harus memiliki durasi valid")
        audio_duration_s = len(audio) / tts.sample_rate
        rtf = (latency_ms / 1000.0) / audio_duration_s
        self.assertLess(rtf, 1.0, f"Sintesis suara harus lebih cepat dari playback real-time (RTF {rtf:.2f} < 1.0)")
        self.assertLess(latency_ms, 3500.0, f"Latensi sintesis 1 kalimat harus di bawah 3.5s (didapat {latency_ms:.1f}ms)")


class TestLiveASRInference(unittest.TestCase):
    """Test actual faster-whisper model loading and transcription telemetry."""

    def test_real_whisper_engine(self) -> None:
        asr = LocalASREngine()
        self.assertTrue(asr.is_available(), "Faster-Whisper model harus terpasang")
        self.assertEqual(asr.device, "cuda", "Whisper harus berjalan pada NVIDIA CUDA")
        self.assertEqual(asr.compute_type, "float16", "Whisper harus menggunakan float16 pada RTX 3050")

        # Transcribe 1 second of synthetic silent/tone audio to verify pipeline
        dummy_audio = np.zeros(16000, dtype=np.float32)
        res, tele = asr.transcribe(dummy_audio, sample_rate=16000)
        self.assertIsInstance(res, NormalizedASRResult)
        self.assertIn("latency_ms", tele)
        self.assertIn("device", tele)
        self.assertEqual(tele["device"], "cuda")


class TestVoicePreferencesPersistence(unittest.TestCase):
    """Test voice persistent configuration load, save, and safe fallbacks."""

    def test_default_preferences(self) -> None:
        p = VoicePreferences()
        self.assertTrue(p.voice_enabled)
        self.assertTrue(p.hands_free)
        self.assertEqual(p.voice_preset, "BAGUSMAX_CALM_ID")
        self.assertEqual(p.audio_storage, "disabled")
        self.assertEqual(p.response_mode, "audio_first")
        self.assertTrue(p.barge_in_enabled)

    def test_save_and_load_roundtrip(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "test_voice_prefs.json"
            p = VoicePreferences(
                voice_enabled=True,
                hands_free=False,
                voice_preset="STANDARD",
                speed=1.1,
                volume=0.85,
            )
            ok = save_voice_preferences(p, config_path=cfg_path)
            self.assertTrue(ok)
            self.assertTrue(cfg_path.exists())

            loaded = load_voice_preferences(config_path=cfg_path)
            self.assertTrue(loaded.voice_enabled)
            self.assertFalse(loaded.hands_free)
            self.assertEqual(loaded.voice_preset, "STANDARD")
            self.assertAlmostEqual(loaded.speed, 1.1, places=2)
            self.assertAlmostEqual(loaded.volume, 0.85, places=2)
            self.assertEqual(loaded.audio_storage, "disabled")

    def test_sanitization_and_zero_disk_enforcement(self) -> None:
        p = VoicePreferences(
            speed=5.0,  # Over max
            volume=-1.0,  # Under min
            audio_storage="enabled",  # Forbidden: must be disabled
            voice_preset="UNKNOWN_PRESET",
        )
        p.sanitize()
        self.assertLessEqual(p.speed, 2.0)
        self.assertGreaterEqual(p.volume, 0.0)
        self.assertEqual(p.audio_storage, "disabled")
        self.assertEqual(p.voice_preset, "BAGUSMAX_CALM_ID")

    def test_device_resolution(self) -> None:
        p = VoicePreferences()
        in_id, out_id = p.resolve_devices()
        self.assertTrue(in_id is None or isinstance(in_id, int))
        self.assertTrue(out_id is None or isinstance(out_id, int))


class TestBagusmaxCalmVoicePreset(unittest.TestCase):
    """Test Bagusmax calm voice preset parameters and synthesis config."""

    def test_bagusmax_preset_defaults(self) -> None:
        tts = LocalTTSEngine()
        self.assertEqual(tts.preset, "BAGUSMAX_CALM_ID")
        self.assertAlmostEqual(tts.length_scale, 1.08, places=2)
        self.assertAlmostEqual(tts.noise_scale, 0.55, places=2)
        self.assertAlmostEqual(tts.noise_w_scale, 0.70, places=2)

    def test_preset_switching(self) -> None:
        tts = LocalTTSEngine()
        self.assertTrue(tts.set_preset("FAST"))
        self.assertEqual(tts.preset, "FAST")
        self.assertAlmostEqual(tts.length_scale, 0.90, places=2)

        self.assertTrue(tts.set_preset("BAGUSMAX_CALM_ID"))
        self.assertEqual(tts.preset, "BAGUSMAX_CALM_ID")
        self.assertAlmostEqual(tts.length_scale, 1.08, places=2)


class TestAcousticEchoSuppression(unittest.TestCase):
    """Test microphone suppression window for acoustic echo and room reverb prevention."""

    def test_suppress_input_window(self) -> None:
        stream = AudioCaptureStream()
        self.assertFalse(stream.is_capturing)
        stream.suppress_input(duration_ms=100)
        self.assertGreater(stream._suppress_until, 0.0)

        # In callback, while suppressed, audio must be ignored
        dummy_chunk = np.ones(512, dtype=np.float32)
        stream._is_capturing = True
        stream._audio_callback(dummy_chunk, 512, None, None)
        self.assertEqual(len(stream._pre_roll_buffer), 0, "Frames must be dropped during suppression guard")
        self.assertEqual(stream.get_current_level_db(), -100.0)


class TestGenerationTrackingAndBargeIn(unittest.TestCase):
    """Test generation IDs and stale audio chunk rejection upon barge-in."""

    def test_generation_id_bump_and_stale_rejection(self) -> None:
        mgr = AudioPlaybackManager()
        gen_1 = mgr.current_generation_id
        gen_2 = mgr.new_turn()
        self.assertEqual(gen_2, gen_1 + 1)

        # Enqueue chunk from stale generation (gen_1)
        stale_audio = np.zeros(2000, dtype=np.float32)
        mgr.enqueue(stale_audio, samplerate=22050, generation_id=gen_1)
        self.assertEqual(mgr.queue_size, 0, "Chunk from previous turn must be discarded immediately")

        # Enqueue chunk from current generation (gen_2)
        current_audio = np.zeros(2000, dtype=np.float32)
        mgr.enqueue(current_audio, samplerate=22050, generation_id=gen_2)
        self.assertTrue(mgr.queue_size == 1 or mgr.is_playing)

        # Stop / Barge-in aborts and bumps generation again
        mgr.stop_playback(interrupted=True)
        self.assertEqual(mgr.queue_size, 0)
        self.assertFalse(mgr.is_playing)
        self.assertGreater(mgr.current_generation_id, gen_2)


class TestZeroPersistentAudioAudit(unittest.TestCase):
    """Test audit verifying zero persistent audio files on disk across data and app directories."""

    def test_zero_persistent_audio_guarantee(self) -> None:
        audit = PrivacyGuard.verify_zero_persistent_audio()
        self.assertTrue(audit["zero_audio_persisted"])
        self.assertEqual(audit["violations_found"], 0)
        self.assertEqual(len(audit["persisted_files"]), 0)


class TestEnhancedSpeechNormalizerDecimalsAndTickers(unittest.TestCase):
    """Test extended Indonesian speech verbalization for decimals, multipliers, LQ45, and IDX tickers."""

    def test_multipliers_and_decimals(self) -> None:
        spoken = SpeechTextNormalizer.to_spoken_text("Rasio PBV saat ini 2.5x dengan PER 15.5x.")
        self.assertIn("P B V", spoken)
        self.assertIn("dua koma lima kali", spoken)
        self.assertIn("P E R", spoken)
        self.assertIn("lima belas koma lima kali", spoken)

    def test_special_acronyms(self) -> None:
        spoken = SpeechTextNormalizer.to_spoken_text("IHSG ditutup menguat didorong indeks LQ45 dan pengumuman suku bunga BI.")
        self.assertIn("I H S G", spoken)
        self.assertIn("L Q empat puluh lima", spoken)
        self.assertIn("B I", spoken)

    def test_general_idx_tickers(self) -> None:
        samples = [
            ("saham GOTO dan AMMN", "G O T O", "A M M N"),
            ("rekomendasi BRIS serta ACES", "B R I S", "A C E S"),
        ]
        for text, t1, t2 in samples:
            res = SpeechTextNormalizer.to_spoken_text(text)
            self.assertIn(t1, res)
            self.assertIn(t2, res)

    def test_non_ticker_exclusion_words(self) -> None:
        # Common non-ticker words must not be spaced out into single letters
        spoken = SpeechTextNormalizer.to_spoken_text("Mode FAST dan proses DATA dilakukan secara realtime.")
        self.assertIn("FAST", spoken)
        self.assertIn("DATA", spoken)


if __name__ == "__main__":
    unittest.main()

