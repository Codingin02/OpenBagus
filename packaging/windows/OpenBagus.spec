from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files, copy_metadata

root = Path(SPECPATH).parents[1]
datas = [(str(root / "LICENSE"), ".")]
datas += collect_data_files("openbagus.domains.equities", includes=["idx_universe.json"])
binaries = []
hidden = collect_submodules("openbagus") + collect_submodules("openbagus_finance")
for package in ("piper", "faster_whisper", "onnxruntime", "ctranslate2", "sounddevice", "glfw", "moderngl", "pyrr", "glcontext"):
    data, libs, imports = collect_all(package)
    datas += data
    binaries += libs
    hidden += imports
for directory in ("config", "schemas"):
    if (root / directory).is_dir():
        for item in (root / directory).rglob("*"):
            if item.is_file() and not any(word in item.name for word in (".local.", "_local.json", "_local.env")):
                datas.append((str(item), str(item.parent.relative_to(root))))
datas.append((str(root / "data/local_ai/voice_preferences.json"), "data/local_ai"))
ollama = Path.home() / "AppData/Local/Programs/Ollama"
binaries.append((str(ollama / "ollama.exe"), "ollama"))
for item in (ollama / "lib/ollama").rglob("*"):
    if item.is_file() and not any(part in ("cuda_v13", "rocm_v7_1", "vulkan") for part in item.parts):
        destination = str(item.parent.relative_to(ollama))
        (binaries if item.suffix.lower() in (".exe", ".dll") else datas).append((str(item), "ollama/" + destination))
for name in ("piper-tts", "faster-whisper", "ctranslate2", "onnxruntime", "sounddevice"):
    datas += copy_metadata(name)
analysis = Analysis([str(root / "packaging/windows/entrypoint.py")], pathex=[str(root)],
                    binaries=binaries, datas=datas, hiddenimports=hidden,
                    excludes=["torch", "tensorflow", "PySide6", "PyQt5", "IPython", "tkinter"],
                    noarchive=False)
# Ollama resolves its own CUDA libraries; do not duplicate these at bundle root.
analysis.binaries = [item for item in analysis.binaries if item[0] not in ("cublas64_12.dll", "cublasLt64_12.dll")]
archive = PYZ(analysis.pure)
exe = EXE(archive, analysis.scripts, [], exclude_binaries=True, name="OpenBagus", console=True)
package = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="OpenBagus")
