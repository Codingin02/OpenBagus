"""Hardware capabilities and local runtime environment detector."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openbagus.intelligence.local_language import (
    BIN_DIR,
    LLAMA_SERVER_EXE,
    LOCAL_RUNTIME_DIR,
    MODELS_DIR,
)


@dataclass
class HardwareProfile:
    os_name: str
    os_version: str
    architecture: str
    cpu_cores: int
    total_ram_gb: float
    free_ram_gb: float
    gpu_name: str | None = None
    gpu_vendor: str | None = None
    vram_total_mb: float = 0.0
    vram_free_mb: float = 0.0
    cuda_available: bool = False
    llama_server_path: str | None = None
    llama_server_version: str | None = None
    ollama_path: str | None = None
    available_local_models: list[dict[str, Any]] = field(default_factory=list)
    recommended_profile: str = "BALANCED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "os_name": self.os_name,
            "os_version": self.os_version,
            "architecture": self.architecture,
            "cpu_cores": self.cpu_cores,
            "total_ram_gb": round(self.total_ram_gb, 2),
            "free_ram_gb": round(self.free_ram_gb, 2),
            "gpu_name": self.gpu_name or "None",
            "gpu_vendor": self.gpu_vendor or "None",
            "vram_total_mb": round(self.vram_total_mb, 1),
            "vram_free_mb": round(self.vram_free_mb, 1),
            "cuda_available": self.cuda_available,
            "llama_server": bool(self.llama_server_path),
            "ollama": bool(self.ollama_path),
            "models_count": len(self.available_local_models),
            "recommended_profile": self.recommended_profile,
        }


class HardwareDetector:
    """Discovers host hardware resources and installed local LLM runtimes."""

    @classmethod
    def detect(cls) -> HardwareProfile:
        os_name = platform.system()
        os_version = platform.release()
        architecture = platform.machine()
        cpu_cores = os.cpu_count() or 4

        # RAM detection
        total_ram = 8.0
        free_ram = 4.0
        if os_name == "Windows":
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json"],
                    timeout=5, text=True, errors="replace"
                )
                import json
                data = json.loads(out)
                total_ram = float(data.get("TotalVisibleMemorySize", 8388608)) / (1024 * 1024)
                free_ram = float(data.get("FreePhysicalMemory", 4194304)) / (1024 * 1024)
            except Exception:
                pass
        else:
            try:
                import psutil
                mem = psutil.virtual_memory()
                total_ram = mem.total / (1024 ** 3)
                free_ram = mem.available / (1024 ** 3)
            except Exception:
                pass

        # GPU detection
        gpu_name = None
        gpu_vendor = None
        vram_total = 0.0
        vram_free = 0.0
        cuda_avail = False

        try:
            smi = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                timeout=5, text=True, errors="replace"
            ).strip()
            if smi:
                parts = [p.strip() for p in smi.split("\n")[0].split(",")]
                if len(parts) >= 3:
                    gpu_name = parts[0]
                    vram_total = float(parts[1])
                    vram_free = float(parts[2])
                    gpu_vendor = "NVIDIA"
                    cuda_avail = True
        except Exception:
            pass

        # llama-server detection
        llama_path = None
        llama_ver = None
        if LLAMA_SERVER_EXE.is_file():
            llama_path = str(LLAMA_SERVER_EXE)
            try:
                ver_out = subprocess.check_output([str(LLAMA_SERVER_EXE), "--version"], timeout=3, text=True, errors="replace")
                llama_ver = ver_out.strip().split("\n")[0]
            except Exception:
                llama_ver = "llama.cpp server"
        elif shutil.which("llama-server"):
            llama_path = shutil.which("llama-server")
            llama_ver = "system llama-server"

        # Ollama detection
        ollama_path = shutil.which("ollama")
        if not ollama_path:
            alt_ollama = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
            if alt_ollama.is_file():
                ollama_path = str(alt_ollama)

        # Local model discovery
        models: list[dict[str, Any]] = []
        if MODELS_DIR.is_dir():
            for f in MODELS_DIR.glob("*.gguf"):
                size_mb = f.stat().st_size / (1024 * 1024)
                models.append({
                    "name": f.name,
                    "path": str(f),
                    "size_mb": round(size_mb, 1),
                    "format": "GGUF",
                    "source": "OpenBagus Local Models",
                })

        # Recommendation logic
        if cuda_avail and vram_total >= 4000:
            rec_profile = "BALANCED"
        elif total_ram >= 16.0:
            rec_profile = "BALANCED"
        else:
            rec_profile = "FAST"

        return HardwareProfile(
            os_name=os_name,
            os_version=os_version,
            architecture=architecture,
            cpu_cores=cpu_cores,
            total_ram_gb=total_ram,
            free_ram_gb=free_ram,
            gpu_name=gpu_name,
            gpu_vendor=gpu_vendor,
            vram_total_mb=vram_total,
            vram_free_mb=vram_free,
            cuda_available=cuda_avail,
            llama_server_path=llama_path,
            llama_server_version=llama_ver,
            ollama_path=ollama_path,
            available_local_models=models,
            recommended_profile=rec_profile,
        )
