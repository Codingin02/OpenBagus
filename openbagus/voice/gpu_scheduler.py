"""NVIDIA RTX GPU scheduler, VRAM memory monitor, and inference concurrency coordinator."""

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GPUStatus:
    cuda_available: bool
    device_name: str
    vram_total_mb: float
    vram_used_mb: float
    vram_free_mb: float
    gpu_utilization_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cuda_available": self.cuda_available,
            "device_name": self.device_name,
            "vram_total_mb": round(self.vram_total_mb, 1),
            "vram_used_mb": round(self.vram_used_mb, 1),
            "vram_free_mb": round(self.vram_free_mb, 1),
            "gpu_utilization_pct": round(self.gpu_utilization_pct, 1),
        }


class GPUScheduler:
    """Coordinates GPU allocation between ASR, LLM, and TTS to prevent VRAM spikes and OOM."""

    _instance: GPUScheduler | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._gpu_inference_lock = threading.RLock()
        self._active_task: str | None = None
        self._peak_vram_used = 0.0

    @classmethod
    def get_instance(cls) -> GPUScheduler:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def query_gpu_status(self) -> GPUStatus:
        """Queries live VRAM and utilization using nvidia-smi."""
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu", "--format=csv,noheader,nounits"],
                text=True,
                timeout=2,
            )
            parts = [p.strip() for p in out.strip().split(",")]
            name = parts[0]
            total = float(parts[1])
            used = float(parts[2])
            free = float(parts[3])
            util = float(parts[4]) if len(parts) > 4 else 0.0

            if used > self._peak_vram_used:
                self._peak_vram_used = used

            return GPUStatus(
                cuda_available=True,
                device_name=name,
                vram_total_mb=total,
                vram_used_mb=used,
                vram_free_mb=free,
                gpu_utilization_pct=util,
            )
        except Exception:
            return GPUStatus(
                cuda_available=False,
                device_name="None / CPU",
                vram_total_mb=0.0,
                vram_used_mb=0.0,
                vram_free_mb=0.0,
                gpu_utilization_pct=0.0,
            )

    def acquire_gpu(self, task_name: str, timeout: float = 30.0) -> bool:
        """Acquires GPU lock for serialized inference."""
        acquired = self._gpu_inference_lock.acquire(timeout=timeout)
        if acquired:
            self._active_task = task_name
        return acquired

    def release_gpu(self) -> None:
        """Releases GPU lock after inference completion."""
        self._active_task = None
        try:
            self._gpu_inference_lock.release()
        except RuntimeError:
            pass

    def get_scheduling_summary(self) -> dict[str, Any]:
        status = self.query_gpu_status()
        return {
            "gpu_status": status.to_dict(),
            "active_task": self._active_task,
            "peak_vram_used_mb": round(self._peak_vram_used, 1),
            "asr_placement": "NVIDIA CUDA (float16)" if status.cuda_available else "CPU (int8)",
            "llm_placement": "NVIDIA CUDA (Q4_K_M offloaded)" if status.cuda_available else "CPU",
            "tts_placement": "ONNX Runtime (CPU/SIMD)",
            "vad_placement": "ONNX Runtime (CPU)",
        }
