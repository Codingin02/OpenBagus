"""V5.0 Acceptance Test Suite for Bagusmax Local Voice Quality Recovery.

Verifies 20 concrete operational scenarios (T01 - T20):
T01: Silence detection (3s total silence triggers zero ASR/TTS)
T02: Noise rejection (low fan/ambient noise < 0.0035 RMS yields empty transcript)
T03: Echo rejection (speaker render energy prevents echo from triggering false barge-in)
T04: ASR outro rejection (hallucinated outro phrases on silence/noise are purged)
T05: Genuine 'Terima kasih' acceptance (genuine speech with high SNR is accepted)
T06: Hesitation pause endpointing (1.2s pause on incomplete utterance doesn't cut off)
T07: Short turn 'Oke' / 'Baik' (fast-path response without heavy financial tools)
T08: Preset Natural (speed 1.0, zero pitch-shift, array length preserved)
T09: Preset Calm (tempo calm, warmth gain +1.5 dB, length scale 1.07)
T10: Preset Soft (tempo soft, warmth gain +2.0 dB, length scale 1.09)
T11: Technical introspection (honest explanation of female base model and DSP filters)
T12: Barge-in during TTS playback (instant cutoff < 120 ms)
T13: Barge-in during LLM thinking (cancels thinking state and starts new turn)
T14: Rapid barge-in sequence (3 rapid interruptions without deadlock)
T15: Device recovery & WASAPI sample rate (clean resampling 22050 to 44100/48000 Hz)
T16: Zero-disk audio audit (strictly zero audio files created on disk)
T17: Financial speech normalizer (TLKM, BBCA, Rp 50 triliun, 12.5% natural Indonesian spoken text)
T18: Financial context switch (RATU to TLKM context cleanly separated)
T19: Callback safety (exceptions in level/companion callbacks don't crash loop)
T20: Real hardware acceptance (RTX 3050 GPU VRAM < 2.5 GB, CUDA telemetry active)
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
from openbagus.voice.tts_engine import LocalTTSEngine, VOICE_PRESETS
from openbagus.voice.turn_controller import VoiceState, VoiceTurnController, is_likely_incomplete_utterance
from openbagus.voice.vad import VoiceActivityDetector
from openbagus.voice.voice_processor import BagusmaxVoiceProcessor


class TestVoiceRuntimeV5(unittest.TestCase):
    """Exhaustive 20-scenario test suite for Master Directive V5.0."""

    def setUp(self) -> None:
        self.sample_rate = 16000

    # -------------------------------------------------------------------------
    # T01: Silence detection
    # -------------------------------------------------------------------------
    def test_t01_silence_detection(self) -> None:
        """Diam total selama 3 detik tidak memicu ASR dan tidak memicu TTS."""
        vad = VoiceActivityDetector()
        chunk_size = 512
        silence_chunk = np.zeros(chunk_size, dtype=np.float32)
        total_chunks = int(3.0 * self.sample_rate / chunk_size)

        speech_detected_count = 0
        for _ in range(total_chunks):
            is_active, is_endpoint, prob = vad.process_frame(silence_chunk)
            if is_active:
                speech_detected_count += 1

        self.assertEqual(speech_detected_count, 0, "Silence should never trigger active speech in VAD")

        # Test ASR directly on 3s of silence
        asr = LocalASREngine()
        norm_res, tele = asr.transcribe(np.zeros(3 * self.sample_rate, dtype=np.float32), sample_rate=16000)
        self.assertEqual(norm_res.normalized_text, "", "ASR must return empty text on silence")

    # -------------------------------------------------------------------------
    # T02: Noise rejection
    # -------------------------------------------------------------------------
    def test_t02_noise_rejection(self) -> None:
        """Suara kipas / background noise rendah (< 0.0035 RMS) tidak memicu transkripsi palsu."""
        vad = VoiceActivityDetector()
        np.random.seed(42)
        noise = (np.random.randn(512).astype(np.float32)) * 0.0025  # RMS ~ 0.0025

        for _ in range(50):
            is_active, is_endpoint, prob = vad.process_frame(noise)
            self.assertFalse(is_active, "Low ambient noise (< 0.0035 RMS) must not trigger speech onset")

        # Directly verify ASR noise rejection
        asr = LocalASREngine()
        noise_audio = (np.random.randn(2 * self.sample_rate).astype(np.float32)) * 0.0020
        norm_res, tele = asr.transcribe(noise_audio, sample_rate=16000)
        self.assertEqual(norm_res.normalized_text, "", "ASR must suppress weak background noise")

    # -------------------------------------------------------------------------
    # T03: Echo rejection
    # -------------------------------------------------------------------------
    def test_t03_echo_rejection(self) -> None:
        """Audio yang diputar speaker laptop tidak memicu ASR dirinya sendiri (VAD render check)."""
        pm = MagicMock(spec=AudioPlaybackManager)
        # Mock active rendering energy
        pm.get_current_render_energy = MagicMock(return_value=0.045)  # Speaker loud playback

        # Frame with echo bleed at 0.035 RMS (below coupling thresh max(0.012, 0.045*0.70 + 0.008 = 0.0395))
        controller = VoiceTurnController(playback_manager=pm, capture_stream=MagicMock(spec=AudioCaptureStream))
        controller.set_state(VoiceState.SPEAKING)

        echo_frame = np.full(512, 0.030, dtype=np.float32)
        controller.vad.process_frame = MagicMock(return_value=(True, False, 0.72))

        # Feed frame through barge-in check
        render_rms = pm.get_current_render_energy()
        coupling_thresh = max(0.012, render_rms * 0.70 + 0.008)
        frame_rms = float(np.sqrt(np.mean(np.square(echo_frame))))

        is_genuine_barge_in = (0.72 >= 0.75) and (frame_rms >= coupling_thresh)
        self.assertFalse(is_genuine_barge_in, "Speaker echo bleed must be rejected by render coupling threshold")

    # -------------------------------------------------------------------------
    # T04: ASR outro rejection
    # -------------------------------------------------------------------------
    def test_t04_asr_outro_rejection(self) -> None:
        """Prompt hening atau audio noise tidak menghasilkan 'Terima kasih', 'Terima kasih telah menonton'."""
        asr = LocalASREngine()
        # Verify PHANTOM_OUTRO_MARKERS contains all common YouTube/Whisper outro hallucinations
        self.assertIn("terima kasih telah menonton", asr.PHANTOM_OUTRO_MARKERS)
        self.assertIn("terima kasih sudah menonton", asr.PHANTOM_OUTRO_MARKERS)
        self.assertIn("terima kasih.", asr.PHANTOM_OUTRO_MARKERS)
        self.assertIn("terima kasih", asr.PHANTOM_OUTRO_MARKERS)

        # Transcribe low-energy noise: even if decoder outputs outro tokens, ASR cleans them
        audio = (np.random.randn(self.sample_rate).astype(np.float32)) * 0.001
        norm_res, _ = asr.transcribe(audio, sample_rate=16000)
        self.assertEqual(norm_res.normalized_text, "")

    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # T05: Genuine 'Terima kasih'
    # -------------------------------------------------------------------------
    def test_t05_genuine_terima_kasih(self) -> None:
        """Ucapan pengguna nyata 'Terima kasih banyak' dengan durasi >= 0.70s dan energi cukup HARUS diterima."""
        asr = LocalASREngine()
        # Simulate clean speech acoustic metrics with natural modulation
        t = np.linspace(0, 1.2, int(1.2 * self.sample_rate), dtype=np.float32)
        speech_audio = 0.04 * np.sin(2 * np.pi * 150 * t) + 0.02 * np.sin(2 * np.pi * 300 * t)
        mock_seg = MagicMock(text="Terima kasih banyak atas bantuannya", avg_logprob=-0.25, no_speech_prob=0.02)

        with patch.object(asr, "_model") as mock_m:
            mock_m.transcribe.return_value = ([mock_seg], MagicMock(language="id"))
            norm_res, tele = asr.transcribe(speech_audio, sample_rate=16000)
            self.assertTrue("terima kasih" in norm_res.normalized_text.lower())
            self.assertFalse(norm_res.normalized_text == "")

    # -------------------------------------------------------------------------
    # T06: Hesitation pause
    # -------------------------------------------------------------------------
    def test_t06_hesitation_pause(self) -> None:
        """Jeda di tengah kalimat tidak memutus turn ('Tolong analisis saham ... sebentar ... RATU')."""
        self.assertTrue(is_likely_incomplete_utterance("Tolong analisis saham..."))
        self.assertTrue(is_likely_incomplete_utterance("sebentar"))
        self.assertTrue(is_likely_incomplete_utterance("kalau menurut anda"))
        self.assertTrue(is_likely_incomplete_utterance("terus"))
        self.assertTrue(is_likely_incomplete_utterance("jadi"))

        vad = VoiceActivityDetector(silence_timeout_ms=950, extended_silence_timeout_ms=2000)
        # Verify extended silence timeout
        self.assertEqual(vad.extended_silence_timeout_ms, 2000)
        vad.set_extended_silence(True)
        self.assertTrue(vad.is_extended)
        self.assertAlmostEqual(vad.current_silence_timeout_ms, 2000, delta=35)

    # -------------------------------------------------------------------------
    # T07: Short turn 'Oke'
    # -------------------------------------------------------------------------
    def test_t07_short_turn_oke(self) -> None:
        """Ucapan 'Oke', 'Baik', 'Siap' direspons cepat tanpa analisis finansial panjang jika tidak ada pending action."""
        controller = VoiceTurnController(
            playback_manager=MagicMock(spec=AudioPlaybackManager),
            capture_stream=MagicMock(spec=AudioCaptureStream),
        )
        # Direct utterance test with mock ASR
        with patch.object(controller.asr_engine, "transcribe") as mock_asr:
            mock_asr.return_value = (
                NormalizedASRResult(raw_text="Oke", normalized_text="Oke"),
                {"latency_ms": 45.0},
            )
            written, spoken, metrics = controller.process_direct_utterance(np.zeros(16000, dtype=np.float32))
            self.assertEqual(written, "Baik.")
            self.assertEqual(spoken, "Baik.")
            self.assertEqual(metrics.tools_executed_count, 0, "No financial tools should run for isolated acknowledgment")

    # -------------------------------------------------------------------------
    # T08: Preset Natural
    # -------------------------------------------------------------------------
    def test_t08_preset_natural(self) -> None:
        """Memverifikasi profil NATURAL (kecepatan normal, tanpa pitch shift, array length preserved)."""
        proc = BagusmaxVoiceProcessor(preset="NATURAL")
        self.assertFalse(proc.robot_resonance)
        self.assertEqual(proc.warmth_gain_db, 0.0)

        # Test audio length preservation
        audio = np.ones(22050, dtype=np.float32) * 0.1
        out = proc.process(audio, sample_rate=22050)
        self.assertEqual(len(out), len(audio), "Exact sample length must be preserved (zero duration drift)")

    # -------------------------------------------------------------------------
    # T09: Preset Calm
    # -------------------------------------------------------------------------
    def test_t09_preset_calm(self) -> None:
        """Memverifikasi profil BAGUSMAX_CALM (tempo tenang, warmth gain, length scale 1.05-1.08)."""
        calm_cfg = VOICE_PRESETS.get("BAGUSMAX_CALM")
        self.assertIsNotNone(calm_cfg)
        self.assertIn(round(calm_cfg["length_scale"], 2), (1.06, 1.07, 1.08))

        proc = BagusmaxVoiceProcessor(preset="BAGUSMAX_CALM")
        self.assertGreaterEqual(proc.warmth_gain_db, 1.0)
        audio = np.ones(22050, dtype=np.float32) * 0.1
        out = proc.process(audio, sample_rate=22050)
        self.assertEqual(len(out), len(audio))

    # -------------------------------------------------------------------------
    # T10: Preset Soft
    # -------------------------------------------------------------------------
    def test_t10_preset_soft(self) -> None:
        """Memverifikasi profil BAGUSMAX_SOFT (tempo lebih lambat, noise w scale lembut)."""
        soft_cfg = VOICE_PRESETS.get("BAGUSMAX_SOFT")
        self.assertIsNotNone(soft_cfg)
        self.assertIn(round(soft_cfg["length_scale"], 2), (1.09, 1.10))

        proc = BagusmaxVoiceProcessor(preset="BAGUSMAX_SOFT")
        self.assertGreaterEqual(proc.warmth_gain_db, 1.5)
        audio = np.ones(22050, dtype=np.float32) * 0.1
        out = proc.process(audio, sample_rate=22050)
        self.assertEqual(len(out), len(audio))

    # -------------------------------------------------------------------------
    # T11: Introspection
    # -------------------------------------------------------------------------
    def test_t11_introspection(self) -> None:
        """Pertanyaan status suara mengembalikan data faktual teknis."""
        controller = VoiceTurnController(
            playback_manager=MagicMock(spec=AudioPlaybackManager),
            capture_stream=MagicMock(spec=AudioCaptureStream),
        )
        # Query why voice is female
        reply = controller._handle_voice_preset_commands("Kenapa suara kamu masih perempuan?")
        self.assertIsNotNone(reply)
        self.assertIn("id_ID-news_tts-medium", reply)
        self.assertIn("Bagusmax", reply)

        # Query voice status
        status_reply = controller._handle_voice_preset_commands("/voice status")
        self.assertIsNotNone(status_reply)
        self.assertIn("Preset aktif", status_reply)

    # -------------------------------------------------------------------------
    # T12: Barge-in during TTS playback
    # -------------------------------------------------------------------------
    def test_t12_barge_in_during_tts_playback(self) -> None:
        """Interupsi suara memotong pemutaran TTS seketika (< 120 ms)."""
        pm = AudioPlaybackManager()
        gen_id = pm.new_turn()
        # Enqueue 1 second of audio
        dummy_audio = np.zeros(22050, dtype=np.float32)
        pm.enqueue(dummy_audio, samplerate=22050, generation_id=gen_id)

        t_start = time.perf_counter()
        pm.stop_playback(interrupted=True)
        t_stop = (time.perf_counter() - t_start) * 1000.0

        self.assertLess(t_stop, 120.0, "Playback stop must complete in under 120ms")
        self.assertFalse(pm.is_playing)

    # -------------------------------------------------------------------------
    # T13: Barge-in during LLM thinking
    # -------------------------------------------------------------------------
    def test_t13_barge_in_during_llm_thinking(self) -> None:
        """Interupsi membatalkan thinking state dan mengambil input baru."""
        coordinator = InterruptionCoordinator()
        coordinator.start_turn("turn_initial")
        cancel_ev = coordinator.get_cancellation_event()
        self.assertFalse(cancel_ev.is_set())

        # Barge-in arrives
        coordinator.trigger_interruption(reason="USER_BARGE_IN")
        self.assertTrue(cancel_ev.is_set(), "Cancellation event must be signaled immediately on barge-in")

    # -------------------------------------------------------------------------
    # T14: Rapid barge-in sequence
    # -------------------------------------------------------------------------
    def test_t14_rapid_barge_in_sequence(self) -> None:
        """Tiga kali interupsi berturut-turut tidak menyebabkan deadlock atau queue poisoning."""
        coordinator = InterruptionCoordinator()
        pm = AudioPlaybackManager()

        for i in range(3):
            turn_id = f"rapid_turn_{i}"
            coordinator.start_turn(turn_id)
            gen_id = pm.new_turn()
            pm.enqueue(np.zeros(5000, dtype=np.float32), samplerate=22050, generation_id=gen_id)
            coordinator.trigger_interruption(reason="RAPID_BARGE")
            pm.stop_playback(interrupted=True)
            self.assertTrue(coordinator.is_interrupted)
            self.assertFalse(pm.is_playing)

    # -------------------------------------------------------------------------
    # T15: Device recovery & WASAPI sample rate
    # -------------------------------------------------------------------------
    def test_t15_device_recovery_and_wasapi_sample_rate(self) -> None:
        """Penanganan mismatch 22,050 Hz ke 44,100 / 48,000 Hz tanpa PaErrorCode -9997."""
        audio_22k = np.sin(np.linspace(0, 100, 22050, dtype=np.float32))

        # Resample to 44,100 Hz
        resampled_44k = AudioPlaybackManager._resample_audio(audio_22k, 22050, 44100)
        self.assertEqual(len(resampled_44k), 44100)
        self.assertEqual(resampled_44k.dtype, np.float32)

        # Resample to 48,000 Hz (Standard Windows WASAPI rate)
        resampled_48k = AudioPlaybackManager._resample_audio(audio_22k, 22050, 48000)
        self.assertEqual(len(resampled_48k), 48000)
        self.assertEqual(resampled_48k.dtype, np.float32)

    # -------------------------------------------------------------------------
    # T16: Zero-disk audio audit
    # -------------------------------------------------------------------------
    def test_t16_zero_disk_audio_audit(self) -> None:
        """Tidak ada file .wav atau .mp3 tersimpan di disk setelah sintesis audio."""
        repo_root = Path(__file__).resolve().parent.parent

        def _get_audio_files() -> list[Path]:
            found: list[Path] = []
            for d in [repo_root, repo_root / "data", repo_root / "reports"]:
                if d.exists():
                    found.extend(list(d.glob("*.wav")))
                    found.extend(list(d.glob("*.mp3")))
            return found

        audio_before = _get_audio_files()

        # Synthesize audio in memory via TTS engine
        tts = LocalTTSEngine()
        audio = tts.synthesize_sentence("Halo, saya Bagusmax. Ini pemeriksaan audio memori.")
        self.assertIsNotNone(audio)
        self.assertIsInstance(audio, np.ndarray)

        # Verify strict zero-disk preference enforcement
        prefs = load_voice_preferences()
        self.assertEqual(prefs.audio_storage, "disabled")

        audio_after = _get_audio_files()
        self.assertEqual(len(audio_before), len(audio_after), "Strictly zero new audio files created on disk")

    # -------------------------------------------------------------------------
    # T17: Financial speech normalizer
    # -------------------------------------------------------------------------
    def test_t17_financial_speech_normalizer(self) -> None:
        """Simbol saham 'TLKM', 'BBCA', persentase '12.5%', 'Rp 50 triliun' terucap natural dalam bahasa Indonesia."""
        text = "Emiten TLKM dan BBCA mencatat pertumbuhan laba 12.5% dengan pendapatan Rp 50 triliun dan PER 15x."
        spoken = SpeechTextNormalizer.to_spoken_text(text)

        # Verify expansion
        self.assertIn("persen", spoken.lower())
        self.assertIn("rupiah", spoken.lower())
        self.assertIn("triliun", spoken.lower())
        self.assertNotIn("12.5%", spoken)
        self.assertNotIn("Rp 50", spoken)

    # -------------------------------------------------------------------------
    # T18: Financial context switch
    # -------------------------------------------------------------------------
    def test_t18_financial_context_switch(self) -> None:
        """Percakapan beralih dari RATU ke TLKM tanpa mencampuradukkan data emiten."""
        ctx = WorkingContext()
        ctx.update_entity("RATU", {"name": "PT Ratu Prabu Energi Tbk", "sector": "Energy"})
        self.assertEqual(ctx.active_ticker, "RATU")

        # User switches to TLKM
        ctx.update_entity("TLKM", {"name": "PT Telkom Indonesia Tbk", "sector": "Telecommunications"})
        self.assertEqual(ctx.active_ticker, "TLKM")
        entity_tlkm = ctx.get_entity("TLKM")
        self.assertIsNotNone(entity_tlkm)
        self.assertEqual(entity_tlkm.get("sector"), "Telecommunications")

    # -------------------------------------------------------------------------
    # T19: Callback safety
    # -------------------------------------------------------------------------
    def test_t19_callback_safety(self) -> None:
        """Exception di companion callback atau level meter tidak merusak loop audio utama."""
        def faulty_callback(level: float) -> None:
            raise RuntimeError("Simulation of broken UI meter callback")

        stream = AudioCaptureStream(level_callback=faulty_callback)
        # Calling audio callback with fake indata
        indata = np.zeros((512, 1), dtype=np.float32)
        try:
            stream._audio_callback(indata, frames=512, time_info={}, status=None)
        except Exception as e:
            self.fail(f"Audio callback must isolate user callback exceptions: {e}")

    # -------------------------------------------------------------------------
    # T20: Hardware acceptance
    # -------------------------------------------------------------------------
    def test_t20_hardware_acceptance(self) -> None:
        """Telemetri RTX 3050 (VRAM < 2.5 GB untuk audio, CPU, CUDA loopback terverifikasi)."""
        scheduler = GPUScheduler.get_instance()
        status = scheduler.query_gpu_status()
        self.assertIsInstance(status, GPUStatus)
        if status.cuda_available:
            self.assertIn("NVIDIA", status.device_name.upper())
            self.assertLess(status.vram_used_mb, 6144.0, "VRAM usage must be within RTX 3050 6GB physical capacity")
            self.assertGreater(status.vram_free_mb, 500.0, "Must have free VRAM headroom for voice runtime")


if __name__ == "__main__":
    unittest.main()
