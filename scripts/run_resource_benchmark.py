"""Benchmark resource usage (GPU VRAM, System RAM, latency) with Show OpenBagus companion active."""

import ctypes
from ctypes import wintypes
import subprocess
import time

from openbagus.ai.harness.orchestrator import AgentHarness
from openbagus.companion.controller import CompanionController
from openbagus.voice.tts_engine import LocalTTSEngine


def get_sys_ram_mb() -> float:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return float(stat.ullTotalPhys - stat.ullAvailPhys) / (1024**2)


def get_proc_ram_mb(pid: int | None) -> float:
    if not pid:
        return 0.0
    try:
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        h_proc = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid)
        if not h_proc:
            return 0.0
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        ctypes.windll.psapi.GetProcessMemoryInfo(h_proc, ctypes.byref(pmc), pmc.cb)
        ctypes.windll.kernel32.CloseHandle(h_proc)
        return float(pmc.WorkingSetSize) / (1024**2)
    except Exception:
        return 0.0


def get_vram() -> float:
    try:
        out = (
            subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
            )
            .decode()
            .strip()
        )
        return float(out)
    except Exception:
        return 0.0


def main() -> None:
    comp = CompanionController.get_instance()

    # 1. Baseline
    vram_base = get_vram()
    ram_base = get_sys_ram_mb()
    print(f"1. Baseline (No companion) - VRAM: {vram_base:.1f} MB, Sys RAM Used: {ram_base:.1f} MB")

    # 2. Companion Visible
    comp.show()
    time.sleep(2.0)
    st = comp.get_status()
    comp_pid = st.get("pid")
    comp_ram = get_proc_ram_mb(comp_pid)
    vram_comp = get_vram()
    ram_comp = get_sys_ram_mb()
    print(
        f"2. Companion Visible (PID {comp_pid}) - Process WorkingSet: {comp_ram:.1f} MB, "
        f"Sys VRAM: {vram_comp:.1f} MB, Sys RAM: {ram_comp:.1f} MB"
    )

    # 3. FAST Model Inference with Companion Visible
    harness = AgentHarness()
    print("3. Testing FAST model inference with companion visible...")
    t0 = time.perf_counter()
    res_fast = harness.run(user_query="Apa itu rasio PER saham?", mode="FAST")
    lat_fast = (time.perf_counter() - t0) * 1000.0
    vram_fast = get_vram()
    print(
        f"   FAST Latency: {lat_fast:.1f} ms, VRAM during FAST: {vram_fast:.1f} MB, "
        f"Response text length: {len(res_fast.content)}"
    )

    # 4. DEEP Model Inference with Companion Visible
    print("4. Testing DEEP model inference with companion visible...")
    comp.set_state("DEEP_THINKING")
    t0 = time.perf_counter()
    res_deep = harness.run(user_query="Hitung Fair Value jika EPS Rp 450 dan target PER 15x.", mode="DEEP")
    lat_deep = (time.perf_counter() - t0) * 1000.0
    vram_deep = get_vram()
    trace_len = len(res_deep.thinking_trace or "")
    print(
        f"   DEEP Latency: {lat_deep:.1f} ms, VRAM during DEEP: {vram_deep:.1f} MB, "
        f"Thinking trace length: {trace_len}"
    )

    # 5. TTS Voice Synthesis with Companion Animating
    print("5. Testing TTS Voice synthesis while companion is animating...")
    comp.set_state("SPEAKING")
    tts = LocalTTSEngine()
    t0 = time.perf_counter()
    chunks = list(
        tts.synthesize_stream("Rasio price to earnings BBCA berada pada level wajar industri perbankan.")
    )
    lat_tts = (time.perf_counter() - t0) * 1000.0
    print(f"   TTS Latency: {lat_tts:.1f} ms, Audio Chunks: {len(chunks)}")

    comp.close()
    print("Resource benchmark completed successfully!")


if __name__ == "__main__":
    main()
