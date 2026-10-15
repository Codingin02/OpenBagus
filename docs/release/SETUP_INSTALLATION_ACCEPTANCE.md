# Windows Installation Acceptance (Consolidated Single Root)

**Target Environment:** Windows 11 x64, NVIDIA RTX 3050 Laptop 6 GB, Intel Core i5-13450HX, RAM 11.71 GB.

- **Installer Path:** `E:\Projects\OpenBagus\release\OpenBagus-Setup.exe`
- **Size:** 1,106,581,428 bytes (1.10 GB)
- **SHA-256:** `dac18e4fb38e8c89674d5bc09c527d14a1ce6f5f5d0a9c753ff7edec611a0aa6`
- **Application Target:** `E:\Projects\OpenBagus\_installed\OpenBagus\OpenBagus.exe`
- **Standalone Frozen Bundle:** `E:\Projects\OpenBagus\dist\OpenBagus\OpenBagus.exe` (24.8 MB)
- **Model Storage:** `E:\Projects\OpenBagus\models` (canonical repository root; zero duplicate bundling)
- **Installer Status:** Unsigned trial executable. No global system modifications (no Defender, SmartScreen, or PATH alteration).

## Evidence & Verification

1. **Compilation & Packaging:** Built from the consolidated repository using PyInstaller 6.22.3 and Inno Setup 6.7.3 (`ISCC.exe`). Log: `reports/runtime/release/build.log`.
2. **Standalone Executable Execution:** Running `dist/OpenBagus/OpenBagus.exe --diagnostics` succeeds with exit code 0 and reports `state: "READY"`, `frozen: true`, detecting the RTX 3050 GPU, microphone, speaker, and local models.
3. **End-to-End Acceptance:** Tested via `tests/run_windows_acceptance.py` exercising real stdin/stdout from `C:\Program Files` without `PYTHONPATH`, `PYTHONHOME`, or `VIRTUAL_ENV`. Log: `reports/runtime/release/windows_acceptance.json`. Failures: 0.
4. **Worktree Independence:** Tested after verified deletion of `OpenBagus-Voice`, `OpenBagus-ChatTest`, `OpenBagus-Data`, and `OpenBagus-3D`. No runtime or installer dependency on removed paths.

## Build Instructions

- Inno Setup script: `packaging/windows/OpenBagus.iss`
- PyInstaller specification: `packaging/windows/OpenBagus.spec`
- Build script: `python packaging/windows/build.py --inno .cache/build-tools/InnoSetup/ISCC.exe --release release`
