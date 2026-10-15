# OPENBAGUS — WORKTREE INVENTORY & PRE-MIGRATION AUDIT
**Date:** 2026-10-16  
**Execution Context:** Codex Ultra Consolidation  
**Target Root:** `E:\Projects\OpenBagus`  

---

## 1. Executive Summary

This inventory documents all active OpenBagus Git worktrees, branches, uncommitted assets, ignored files, AI models, and data storage discovered across the filesystem prior to single-repository consolidation.

In accordance with lossless migration directives:
- No file or directory is moved or removed until full verification, bit-exact backup, and integration are proven.
- All 3D assets (White V4.1, Armored V1, V1.1, V1.2 mechanical prototype, Blender sources, GLBs, tools, reports) are preserved.
- Operational AI models remain strictly within `E:\Projects\OpenBagus\models`.
- A dedicated backup area is created at `E:\Projects\OpenBagus\.migration\backups\`.

---

## 2. Worktree Inventory Matrix

| Worktree Path | Active Branch | HEAD Commit | Git Common Dir | Status | Untracked / Ignored Assets | Migration Destination |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `E:\Projects\OpenBagus` | `main` | `77188cc` | `E:/Projects/OpenBagus/.git` | Clean | `models/` (operational weights), `.cache/` | **Canonical Root** |
| `E:\Projects\OpenBagus-3D` | `feat/bagusmax-3d-art` | `95d16dc` | `E:/Projects/OpenBagus/.git` | Untracked Assets | 36 files: `.blend`, `.glb`, `tools/`, `docs/`, `reports/` (~120 MB) | `assets/bagusmax/`, `tools/`, `docs/`, `reports/` |
| `E:\Projects\OpenBagus-ChatTest`| `test/openbagus-chat-acceptance` | `f5a6e0f` | `E:/Projects/OpenBagus/.git` | Clean | `.cache/build-tools/InnoSetup`, `packaging/windows/` | `packaging/windows/`, `.cache/build-tools/` |
| `E:\Projects\OpenBagus-Data` | `feat/openbagus-automated-data-intelligence` | `2f41da3` | `E:/Projects/OpenBagus/.git` | Ignored Data | `data/equities/financial_facts.db` (417 KB), `openbagus/ai/credentials.py` | `data/equities/`, `openbagus/ai/` |
| `E:\Projects\OpenBagus-Voice` | `feat/openbagus-local-voice-live` | `218a377` | `E:/Projects/OpenBagus/.git` | Ignored Audio | `data/voice_candidates/` (sample wavs) | `.migration/backups/voice/` |

---

## 3. Discovered Filesystem Classifications

### 3.1 3D Art & Character Pipeline (`E:\Projects\OpenBagus-3D`)
- **Classification:** `UNTRACKED_SOURCE` & `BUILD_ARTIFACT`
- **Key Files Preserved:**
  - `assets/bagusmax/source/bagusmax_white_anatomy_v4_1.blend` (14.5 MB) — `BCA6B53329AC...`
  - `assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb` (18.9 MB) — `9EC223BB6ECD...`
  - `assets/bagusmax/source/bagusmax_armored_v1_1.blend` (18.9 MB) — `C13BD7967953...`
  - `assets/bagusmax/runtime/bagusmax_armored_v1_1.glb` (3.9 MB) — `6E65C46E5D5D...`
  - `assets/bagusmax/armor/armor_assembly_manifest.json` (369 KB)
  - `assets/bagusmax/armor/armor_white_fit.bin` (2.0 MB)
  - `tools/bagusmax_asset_pipeline/` (14 Python automation scripts: `build_armored.py`, `build_white.py`, etc.)
  - `docs/bagusmax_3d/` & `reports/bagusmax_3d/` (150+ review frames & collision reports)
- **Status:** Copied to `E:\Projects\OpenBagus` and backup verified 100% bit-exact. Armored V1.2 marked `REVIEW_REQUIRED`.

### 3.2 Financial Data & Audited Filings (`E:\Projects\OpenBagus-Data`)
- **Classification:** `IGNORED_BUT_REQUIRED` & `UNTRACKED_SOURCE`
- **Key Files Preserved:**
  - `data/equities/financial_facts.db` (417,792 bytes, SHA-256: `361598E31D632C5D417709CF7478B2282E4E8C04C99A8222F2E9D684850A1512`)
  - `data/equities/RATU.json`, `BBCA.json`, `TLKM.json`, `ASII.json`, `DATA.json`, `ISAT.json`
  - `openbagus/ai/credentials.py` (5,943 bytes, SHA-256: `EB53FA76CBD0CE6B599DABD4CCF062934B694145108C2A28E2EB20C9772EA370`)
- **Status:** Verified and consolidated into `E:\Projects\OpenBagus\data\equities\` and `openbagus/ai/`.

### 3.3 Windows Packaging & Acceptance Runtime (`E:\Projects\OpenBagus-ChatTest`)
- **Classification:** `TRACKED_COMMITTED` & `BUILD_ARTIFACT`
- **Key Files Preserved:**
  - `packaging/windows/OpenBagus.iss` (InnoSetup script)
  - `packaging/windows/OpenBagus.spec` (PyInstaller spec)
  - `packaging/windows/build.py` & `entrypoint.py`
  - `.cache/build-tools/InnoSetup/` (Inno Setup 6.7.3 compiler binaries)
  - `tests/run_windows_acceptance.py` & `tests/test_conversational_recovery_regression.py`
- **Status:** Integrated via commit `f5a6e0f` and local cache.

### 3.4 Bilingual Voice Runtime (`E:\Projects\OpenBagus-Voice`)
- **Classification:** `TRACKED_COMMITTED`
- **Key Files Preserved:**
  - `openbagus/voice/tts_engine.py` (Cross-cache model sharing)
  - `tests/run_v5_acceptance.py` (CRT heap-isolated 31-scenario acceptance runner)
  - `tests/test_voice_runtime_v5.py` (T01–T31 100% PASS)
- **Status:** Integrated via commit `218a377`.

---

## 4. Verification Checkpoint

All untracked and essential ignored files from the 4 satellite worktrees have been backed up to:
`E:\Projects\OpenBagus\.migration\backups\`
and copied into their respective target paths in `E:\Projects\OpenBagus\`.
Bit-exact SHA-256 checksums confirmed for all binary and source assets.
