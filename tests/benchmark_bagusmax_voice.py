"""Benchmark and evaluation suite for Bagusmax film-inspired Indonesian voice profiles.

Tests the 12 mandatory sentences across three real style candidates:
- Profile A: NATURAL (baseline newsreader rate, 0 semitones, neutral)
- Profile B: BAGUSMAX_CALM (length_scale=1.08, gentle delivery, mild smoothing)
- Profile C: BAGUSMAX_SOFT (length_scale=1.12, -1 semitone, low-mid warmth, soft limiter)
"""

from __future__ import annotations

import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import time
from typing import Any
import numpy as np

from openbagus.voice.privacy import PrivacyGuard
from openbagus.voice.speech_normalizer import SpeechTextNormalizer
from openbagus.voice.tts_engine import LocalTTSEngine

BENCHMARK_SENTENCES = [
    "Halo. Saya Bagusmax.",
    "Senang bisa berbicara dengan Anda.",
    "Baik. Saya sedang mendengarkan.",
    "Sebentar. Saya akan memeriksa informasi itu.",
    "Tentu. Saya jelaskan secara perlahan.",
    "Saya memahami pertanyaan Anda.",
    "Untuk analisis yang lebih mendalam, saya membutuhkan sedikit waktu.",
    "Saat ini, data yang tersedia belum cukup untuk membuat kesimpulan.",
    "BBCA dan BBRI memiliki karakteristik bisnis yang berbeda.",
    "Arus kas bebas perusahaan tersebut masih negatif.",
    "Baik. Saya berhenti berbicara dan mendengarkan Anda.",
    "Terima kasih. Sampai jumpa.",
]


def run_benchmark(play_audio: bool = False) -> dict[str, Any]:
    print("=" * 80)
    print("BAGUSMAX FILM-INSPIRED VOICE BENCHMARK (12 SENTENCES x 3 PROFILES)".center(80))
    print("=" * 80)

    tts = LocalTTSEngine()
    if not tts.is_available():
        raise RuntimeError("Piper TTS model is not available")

    profiles = ["NATURAL", "BAGUSMAX_CALM", "BAGUSMAX_SOFT"]
    results: dict[str, list[dict[str, Any]]] = {}

    for prof in profiles:
        print(f"\n--- Testing Profile: {prof} ---")
        tts.set_preset(prof)
        results[prof] = []

        for idx, sentence in enumerate(BENCHMARK_SENTENCES, start=1):
            spoken = SpeechTextNormalizer.to_spoken_text(sentence)
            t0 = time.perf_counter()
            audio = tts.synthesize_sentence(spoken)
            dt_ms = (time.perf_counter() - t0) * 1000.0

            if audio is None or len(audio) == 0:
                print(f"[{idx:02d}] FAILED to synthesize: {sentence}")
                continue

            dur_s = len(audio) / tts.sample_rate
            rtf = (dt_ms / 1000.0) / dur_s
            rms = float(np.sqrt(np.mean(audio ** 2)))
            peak = float(np.max(np.abs(audio)))

            entry = {
                "index": idx,
                "text": sentence,
                "spoken_text": spoken,
                "duration_s": round(dur_s, 2),
                "latency_ms": round(dt_ms, 1),
                "rtf": round(rtf, 3),
                "rms": round(rms, 4),
                "peak": round(peak, 4),
            }
            results[prof].append(entry)
            print(f"  [{idx:02d}] {dur_s:4.2f}s | {dt_ms:6.1f}ms (RTF {rtf:5.3f}) | Peak {peak:4.2f} | \"{spoken}\"")

            if play_audio:
                try:
                    import sounddevice as sd
                    sd.play(audio, samplerate=tts.sample_rate)
                    sd.wait()
                except Exception:
                    pass

    # Audit zero persistent audio
    audit = PrivacyGuard.verify_zero_persistent_audio()
    print("\n" + "=" * 80)
    print(f"Zero Persistent Audio Audit: {'PASS (0 files on disk)' if audit['zero_audio_persisted'] else 'FAIL'}")
    print("=" * 80)

    return {"results": results, "audit": audit}


if __name__ == "__main__":
    run_benchmark(play_audio=False)
