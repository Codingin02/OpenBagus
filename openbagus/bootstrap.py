"""Windows application bootstrap and owned local-provider lifecycle."""

from __future__ import annotations

import ctypes
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request


def _get_json(url, body=None, timeout=3):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    if "--internal-companion-renderer" in sys.argv:
        port = 7432
        if "--port" in sys.argv:
            idx = sys.argv.index("--port")
            if idx + 1 < len(sys.argv):
                try:
                    port = int(sys.argv[idx + 1])
                except ValueError:
                    pass
        from openbagus.companion.renderer import run_renderer
        run_renderer(port=port)
        return 0

    print("OpenBagus | STARTING", flush=True)
    frozen = bool(getattr(sys, "frozen", False))
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    app_dir = Path(sys.executable).parent if frozen else resources
    user_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OpenBagus"
    logs = user_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=logs / "application.log", level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    report = {"state": "STARTING", "executable": sys.executable, "frozen": frozen}
    server = None
    server_log = None
    lock_file = None
    shell = None
    job = None
    try:
        if os.name == "nt":
            import msvcrt
            lock_file = (user_dir / "application.lock").open("a+b")
            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError("OpenBagus sudah berjalan. Gunakan jendela yang tersedia.") from error
        print("CONFIG_LOADING", flush=True)
        config_path = app_dir / "openbagus.json"
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
        default_voice = resources / "data/local_ai/voice_preferences.json"
        if not (user_dir / "voice_preferences.json").exists() and default_voice.is_file():
            shutil.copyfile(default_voice, user_dir / "voice_preferences.json")
        os.environ["OPENBAGUS_MODEL_DIR"] = config.get("model_root", os.environ.get("OPENBAGUS_MODEL_DIR", "E:/Projects/OpenBagus/models"))
        if not Path(os.environ["OPENBAGUS_MODEL_DIR"]).is_dir():
            raise FileNotFoundError(f"Direktori model tidak tersedia: {os.environ['OPENBAGUS_MODEL_DIR']}")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["OLLAMA_NO_CLOUD"] = "1"
        os.environ["OLLAMA_MAX_LOADED_MODELS"] = "1"
        for name in ("OPENBAGUS_LLM_ENDPOINT", "OPENBAGUS_LLM_MODEL", "OPENBAGUS_LLM_KEY"):
            os.environ.pop(name, None)
        print("MODEL_DISCOVERY", flush=True)
        from openbagus.core.model_resolver import get_model_resolver
        resolver = get_model_resolver()
        resolver.configure_environment_caches()
        report["models"] = str(resolver.models_dir)
        store = resolver.models_dir / "ollama"
        for tag in ("2b-q4_K_M", "4b"):
            manifest = json.loads((store / "manifests/registry.ollama.ai/library/qwen3.5" / tag).read_text())
            for layer in [manifest["config"], *manifest["layers"]]:
                if not (store / "blobs" / layer["digest"].replace(":", "-")).is_file():
                    raise FileNotFoundError(f"Model blob tidak tersedia: {layer['digest']}")
        print("HARDWARE_CHECK", flush=True)
        from openbagus.ai.runtime.hardware import HardwareDetector
        report["hardware"] = HardwareDetector.detect().to_dict()
        print("PROVIDER_INITIALIZATION | memuat model lokal...", flush=True)
        executable = resources / "ollama/ollama.exe"
        if not executable.is_file():
            executable = Path(shutil.which("ollama") or user_dir.parent / "Programs/Ollama/ollama.exe")
        if not executable.is_file():
            raise FileNotFoundError("Runtime Ollama tidak ditemukan dalam paket.")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        host = f"http://127.0.0.1:{port}"
        os.environ["OLLAMA_HOST"] = host
        server_log = (logs / "local_provider.log").open("w", encoding="utf-8")
        if frozen and os.name == "nt":
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        try:
            server = subprocess.Popen([str(executable), "serve"], env=dict(os.environ),
                                      stdout=server_log, stderr=server_log,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        finally:
            if frozen and os.name == "nt":
                ctypes.windll.kernel32.SetDllDirectoryW(str(resources))
        if os.name == "nt":
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            job = kernel.CreateJobObjectW(None, None)
            limits = ctypes.create_string_buffer(144)
            ctypes.c_uint32.from_buffer(limits, 16).value = 0x2000
            if not kernel.SetInformationJobObject(job, 9, limits, len(limits)) or not kernel.AssignProcessToJobObject(job, int(server._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        deadline = time.monotonic() + 20
        while True:
            if server.poll() is not None:
                raise RuntimeError("Server lokal berhenti saat startup; periksa local_provider.log.")
            try:
                _get_json(host + "/api/tags")
                break
            except (OSError, ValueError):
                if time.monotonic() > deadline:
                    raise RuntimeError("Server lokal tidak merespons setelah 20 detik.")
                time.sleep(0.2)
        from openbagus.ai.providers.manager import ProviderManager
        from openbagus.ai.providers.base import ChatMessage
        manager = ProviderManager.get_instance()
        from openbagus.voice.preferences import load_voice_preferences
        preferred_mode = load_voice_preferences().default_mode
        provider = manager.switch_to_deep() if preferred_mode == "DEEP_REASONING" else manager.switch_to_fast()
        started = time.monotonic()
        probe = provider.generate([ChatMessage(role="user", content="Jawab hanya: siap")], max_tokens=2048 if preferred_mode == "DEEP_REASONING" else 32, timeout=90)
        if not probe.content.strip() or probe.provider_name == "DETERMINISTIC_FALLBACK":
            raise RuntimeError("Model lokal belum menghasilkan respons inferensi yang valid.")
        report.update(provider=probe.provider_name, model=probe.model, host=host,
                      load_probe_seconds=round(time.monotonic()-started, 3))
        print("DATA_PROVIDER_HEALTH_CHECK", flush=True)
        from openbagus.data.registry import YahooFinanceEquitiesProvider
        healthy, detail = YahooFinanceEquitiesProvider().health_check()
        report["financial_data"] = "DELAYED" if healthy else "OFFLINE"
        report["data_provider_detail"] = detail
        print("VOICE_INITIALIZATION", flush=True)
        from openbagus.voice.audio_devices import AudioDeviceManager
        report["microphone"] = AudioDeviceManager.get_microphone_status()[0]
        report["speaker"] = "READY" if AudioDeviceManager.get_default_output_device() else "UNAVAILABLE"
        report["state"] = "READY" if healthy else "DEGRADED_READY"
        from openbagus.cli import OpenBagusShell
        shell = OpenBagusShell()
        shell.startup_report = report
        (logs / "startup.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if "--diagnostics" in sys.argv:
            print(json.dumps(report, indent=2))
        else:
            shell.use_rawinput = sys.stdin.isatty()
            shell.cmdloop()
        return 0
    except KeyboardInterrupt:
        print("\nOpenBagus dihentikan.", flush=True)
        return 0
    except Exception as error:
        report.update(state="BLOCKED", error_type=type(error).__name__, error=str(error))
        (logs / "startup.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"BLOCKED: {error}\nDiagnostik: {logs}", flush=True)
        if frozen and sys.stdin.isatty():
            try:
                input("Tekan Enter untuk menutup...")
            except (EOFError, KeyboardInterrupt):
                pass
        return 1
    finally:
        if shell and shell.voice_session:
            shell.voice_session.stop()
        if server and server.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            else:
                server.terminate()
            server.wait(timeout=10)
        if job:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(job))
        if server_log:
            server_log.close()
        if lock_file:
            lock_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
