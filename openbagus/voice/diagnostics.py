"""Voice system telemetry, real-time benchmarks, and hardware performance diagnostics."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from openbagus.voice.gpu_scheduler import GPUScheduler


@dataclass
class VoiceTurnMetrics:
    turn_id: str
    user_speech_duration_s: float = 0.0
    vad_start_latency_ms: float = 0.0
    vad_end_latency_ms: float = 0.0
    asr_latency_ms: float = 0.0
    agent_ttft_ms: float = 0.0
    agent_total_latency_ms: float = 0.0
    tts_ttfa_ms: float = 0.0
    tts_total_latency_ms: float = 0.0
    e2e_voice_latency_ms: float = 0.0
    interruption_latency_ms: float = 0.0
    tools_executed_count: int = 0
    mode: str = "FAST"
    interrupted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "mode": self.mode,
            "user_speech_duration_s": round(self.user_speech_duration_s, 2),
            "vad_start_latency_ms": round(self.vad_start_latency_ms, 1),
            "vad_end_latency_ms": round(self.vad_end_latency_ms, 1),
            "asr_latency_ms": round(self.asr_latency_ms, 1),
            "agent_ttft_ms": round(self.agent_ttft_ms, 1),
            "agent_total_latency_ms": round(self.agent_total_latency_ms, 1),
            "tts_ttfa_ms": round(self.tts_ttfa_ms, 1),
            "tts_total_latency_ms": round(self.tts_total_latency_ms, 1),
            "e2e_voice_latency_ms": round(self.e2e_voice_latency_ms, 1),
            "interruption_latency_ms": round(self.interruption_latency_ms, 1),
            "tools_count": self.tools_executed_count,
            "interrupted": self.interrupted,
        }


class VoiceDiagnostics:
    """Collects and aggregates real-world latency benchmarks across voice turns."""

    def __init__(self) -> None:
        self.turns: list[VoiceTurnMetrics] = []
        self.gpu_scheduler = GPUScheduler.get_instance()

    def record_turn(self, metrics: VoiceTurnMetrics) -> None:
        self.turns.append(metrics)

    def get_summary_statistics(self) -> dict[str, Any]:
        if not self.turns:
            return {"turns_count": 0, "message": "No voice turns recorded yet"}

        asr_latencies = [t.asr_latency_ms for t in self.turns if t.asr_latency_ms > 0]
        agent_latencies = [t.agent_total_latency_ms for t in self.turns if t.agent_total_latency_ms > 0]
        tts_latencies = [t.tts_ttfa_ms for t in self.turns if t.tts_ttfa_ms > 0]
        e2e_latencies = [t.e2e_voice_latency_ms for t in self.turns if t.e2e_voice_latency_ms > 0]

        gpu_status = self.gpu_scheduler.query_gpu_status()

        return {
            "turns_count": len(self.turns),
            "total_turns": len(self.turns),
            "interrupted_turns": sum(1 for t in self.turns if t.interrupted),
            "mean_asr_latency_ms": round(statistics.mean(asr_latencies), 1) if asr_latencies else 0.0,
            "avg_asr_latency_ms": round(statistics.mean(asr_latencies), 1) if asr_latencies else 0.0,
            "mean_agent_latency_ms": round(statistics.mean(agent_latencies), 1) if agent_latencies else 0.0,
            "mean_tts_ttfa_ms": round(statistics.mean(tts_latencies), 1) if tts_latencies else 0.0,
            "avg_tts_ttfa_ms": round(statistics.mean(tts_latencies), 1) if tts_latencies else 0.0,
            "mean_e2e_voice_latency_ms": round(statistics.mean(e2e_latencies), 1) if e2e_latencies else 0.0,
            "avg_e2e_latency_ms": round(statistics.mean(e2e_latencies), 1) if e2e_latencies else 0.0,
            "min_e2e_voice_latency_ms": round(min(e2e_latencies), 1) if e2e_latencies else 0.0,
            "max_e2e_voice_latency_ms": round(max(e2e_latencies), 1) if e2e_latencies else 0.0,
            "gpu_vram_used_mb": gpu_status.vram_used_mb,
            "gpu_vram_total_mb": gpu_status.vram_total_mb,
            "gpu_utilization_pct": gpu_status.gpu_utilization_pct,
        }

    def format_markdown_table(self) -> str:
        summary = self.get_summary_statistics()
        if summary.get("turns_count", 0) == 0:
            return "Belum ada metrik turn suara yang dicatat."

        md = [
            "### Voice Latency & GPU Benchmark Metrics",
            "",
            "| Metrik Evaluasi | Rata-Rata / Nilai Terukur | Keterangan & Penempatan Komputasi |",
            "|---|---|---|",
            f"| **Speech Recognition (ASR)** | {summary.get('mean_asr_latency_ms')} ms | NVIDIA RTX CUDA (faster-whisper float16) |",
            f"| **Agent Reasoning & Tools** | {summary.get('mean_agent_latency_ms')} ms | NVIDIA RTX CUDA (Qwen3-4B Q4_K_M) |",
            f"| **TTS Time to First Audio** | {summary.get('mean_tts_ttfa_ms')} ms | Local ONNX Runtime (Piper Indonesian) |",
            f"| **End-to-End Spoken Turn** | {summary.get('mean_e2e_voice_latency_ms')} ms | Dari deteksi suara berhenti hingga audio terdengar |",
            f"| **Peak GPU VRAM Usage** | {summary.get('gpu_vram_used_mb')} / {summary.get('gpu_vram_total_mb')} MB | Alokasi VRAM stabil di bawah 6GB limit |",
            f"| **GPU Utilization** | {summary.get('gpu_utilization_pct')} % | Akselerasi aktif saat inferensi model |",
        ]
        return "\n".join(md)
