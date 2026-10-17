# OPENBAGUS — CODEX 3D GLB RUNTIME RESTORATION & ACCEPTANCE REPORT
**Version:** V5.4.3 / Codex 3D Restoration  
**Date:** October 17, 2026  
**Repository:** `E:\Projects\OpenBagus`  
**Target Hardware:** Windows 11 x64, Intel Core i5-13450HX, NVIDIA RTX 3050 Laptop GPU (6GB VRAM), 12GB RAM  
**Visual Source of Truth:** Authentic Blender Codex exports (`assets/bagusmax/runtime/*.glb`)  

---

## 1. Executive Summary & Root Cause Diagnostic

Audit of the OpenBagus repository and live logs revealed why the procedural placeholder geometry appeared instead of the authentic Codex 3D model, and why the CLI displayed `[Gagal membuka jendela 3D companion BAGUSMAX]` despite the companion window appearing:

### Root Cause A: Invalid GLB Path in Loader
In `openbagus/companion/model_loader.py`:
- `MODELS_DIR` was pointed to `REPO_ROOT / "assets" / "models"` looking for `bagusmax_white.glb`.
- The actual canonical Codex GLB assets authored in Blender reside in `assets/bagusmax/runtime/`:
  - `bagusmax_white_anatomy_v4_1.glb` (White Anatomy V4.1)
  - `bagusmax_armored_v1_1.glb` (Armored V1.1)
- The loader threw `FileNotFoundError`, failing to locate the asset.

### Root Cause B: Silent Procedural Fallback in Production
In `openbagus/companion/renderer.py`, `rebuild_mesh()` caught `Exception` and silently executed:
```python
except Exception:
    builder = build_bagusmax_armored if form == BagusmaxForm.ARMORED else build_bagusmax_white
    verts, idxs = builder(...)
```
This masked the file loading failure and rendered the procedural approximation mesh.

### Root Cause C: Missing `pygltflib` and Runtime GLB in Windows Spec
In `packaging/windows/OpenBagus.spec`:
- `pygltflib` was omitted from package collection.
- `assets/bagusmax/runtime/*.glb` was omitted from `datas`.

### Root Cause D: Collapsed Mesh Hierarchy & Sparse Accessor Crash
- The legacy loader collapsed all nodes into 5 hardcoded dictionary keys (`torso`, `head`, `arm_l`, `arm_r`, `legs`), overwriting `White_SoftSkin` with chest port parts.
- Blender exported morph targets using glTF `sparse` accessors; accessing `acc.bufferView` directly when `bufferView is None` caused runtime exceptions.

### Root Cause E: IPC Handshake Crash (`NameError: IPC_VERSION`)
In `%LOCALAPPDATA%\OpenBagus\logs\companion.log`:
```text
File "openbagus\companion\renderer.py", line 1612, in _dispatch
NameError: name 'IPC_VERSION' is not defined
```
When CLI sent `companion.ping`, `renderer.py` crashed on `IPC_VERSION`, closing the socket and causing `_verify_handshake()` to fail. The controller assumed startup failed and logged `[Gagal membuka jendela 3D companion BAGUSMAX]`.

---

## 2. Corrected Runtime Paths & Asset SHA-256 Verification

The original Codex Blender source files and exported GLB assets remain 100% unaltered. All hashes match exact specification:

| Asset Description | Relative Path | Size (Bytes) | Verified SHA-256 Checksum | Match Status |
| :--- | :--- | :--- | :--- | :--- |
| **White Anatomy V4.1 GLB** | `assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb` | 18,885,552 | `9ec223bb6ecd563437ee17c2b7a20cdd74a9b10d7f98a74e0d1150bb66e9569b` | **VERIFIED MATCH** |
| **White Anatomy V4.1 Source** | `assets/bagusmax/source/bagusmax_white_anatomy_v4_1.blend` | 27,249,740 | `bca6b53329acb61b89f107dc610e1451ebe88d4ba3fa2ee5606f6915b1849f07` | **VERIFIED MATCH** |
| **Armored Hero V1.1 GLB** | `assets/bagusmax/runtime/bagusmax_armored_v1_1.glb` | 3,909,556 | `6e65c46e5d5d6256a1a67b497db395ce31a56749205860be0be397f2bb052afb` | **VERIFIED MATCH** |
| **Armored Hero V1.1 Source** | `assets/bagusmax/source/bagusmax_armored_v1_1.blend` | 5,885,176 | `fcaeecce580325d7ef1173629e34a66e568baae720816fc4137df75eb7f7481a` | **VERIFIED MATCH** |

---

## 3. GLTF Structure Preservation & Geometry Data

The loader reconstructs the complete glTF 2.0 structure without mesh collapsing:

### Form A: BAGUSMAX White Anatomy V4.1 (FAST Mode)
- **Meshes Loaded (11/11 Preserved):**
  1. `Port_Latch_Edit` (Chest access port latch)
  2. `Chest_Access_Lid` (Access port hinged lid)
  3. `Port_Rim_Edit` (Port outer bezel)
  4. `Eye_ContourBridge` (Horizontal bridge connecting eyes)
  5. `Eye_L` (Left eye aperture)
  6. `Eye_R` (Right eye aperture)
  7. `Torso_Vinyl_Seam` (Anatomical welded vinyl seam line)
  8. `White_Head` (Smooth cranial geometry)
  9. `White_Leg_L` (Left columnar leg)
  10. `White_Leg_R` (Right columnar leg)
  11. `White_Torso.001` (`White_SoftSkin` inflatable vinyl body with 5-finger hands)
- **Total Vertices:** `107,307`
- **Total Triangles:** `208,032`
- **Skeletal Joints:** `32` joints preserved (`Root`, `Hips`, `Spine`, `Chest`, `Neck`, `Head`, `Shoulder_L/R`, `UpperArm_L/R`, `Forearm_L/R`, `Hand_L/R`, fingers, `Thigh_L/R`, `Shin_L/R`, `Foot_L/R`)
- **Morph Targets:** `10` corrective shape keys decoded via sparse accessors
- **Dimensions:** Width `1.248m`, Height `1.684m`, Depth `0.823m` (Vertical center $Y = 0.845m$)

### Form B: BAGUSMAX Armored Hero V1.1 (DEEP Mode)
- **Meshes Loaded (130/130 Preserved):** Full segmented modular armor suite, pauldrons, helmet, purple abdominal plates, back wings, gauntlets, knee guards, boots
- **Total Vertices:** `108,304`
- **Total Triangles:** `200,782`
- **Dimensions:** Width `1.489m`, Height `1.732m`, Depth `0.823m` (Vertical center $Y = 0.868m$)

---

## 4. Elimination of Procedural Fallback

In `openbagus/companion/renderer.py`, the silent `try ... except Exception: builder = build_bagusmax_white` fallback has been completely removed from production:
- If a GLB cannot be loaded or fails checksum verification, `CodexGLBLoadError` is immediately raised with the candidate path and root cause.
- Diagnostic flag `procedural_fallback: "DISABLED"` is confirmed active.
- `rebuild_mesh()` strictly returns authentic Codex glTF vertex buffers.

---

## 5. IPC Handshake & Subprocess Reliability

- Defined `IPC_VERSION = "1.0"` in `renderer.py`.
- `IPCServer._dispatch()` handles `companion.ping` and returns:
  ```json
  {
    "status": "ok",
    "app": "openbagus_companion",
    "version": "1.0",
    "pid": 25824,
    "model_source": "CODEX_GLB",
    "model_loaded": true,
    "form": "white",
    "diagnostics": {
      "model_source": "CODEX_GLB",
      "form": "WHITE",
      "asset_filename": "bagusmax_white_anatomy_v4_1.glb",
      "asset_exists": true,
      "sha256_verified": true,
      "total_vertices": 107307,
      "total_triangles": 208032,
      "mesh_count": 11,
      "joints_count": 32,
      "morph_targets_count": 10
    }
  }
  ```
- Subprocess launch timeout increased from 6.0s to 10.0s to ensure reliable initialization.
- Handshake verification validates `status == "ok"` and `app == "openbagus_companion"`.

---

## 6. Real-World Hardware & Voice Status

- **Audio Subsystem:** Realtek High Definition Audio (WASAPI Exclusive, 48000 Hz, 2ch, 10ms low-latency buffer).
- **VAD Silence Invariant:** 60-second quiet-room audit produces exactly 0 false speech endpoints.
- **ASR Pipeline:** Faster-Whisper on NVIDIA RTX 3050 Laptop GPU (CUDA `int8_float16`), verified Indonesian speech transcription.
- **Full-Duplex Barge-In:** Dynamic coupling threshold ($0.010 - 0.032$) allows immediate voice interruption without echo cancellation artifacts.
- **Data Privacy:** Strictly ephemeral zero-disk audio invariant maintained.

---

## 7. Rendering Screenshots

Live captures from the active OpenGL renderer running on the Windows 11 desktop:

1. **White Anatomy V4.1 (FAST Mode):** `reports/screenshots/white_actual_windows_popup.png` (75,078 bytes)
2. **Armored Hero V1.1 (DEEP Mode):** `reports/screenshots/armored_actual_windows_popup.png` (181,636 bytes)
3. **Full Desktop Composite:** `reports/screenshots/bagusmax_desktop_with_cli.png` (1920x1080)

---

## 8. Automated Test Suite Results

1. **Targeted Codex GLB Suite (`tests/test_codex_glb_loader.py`):**
   - `test_white_glb_path_and_sha256`: **PASS**
   - `test_armored_glb_path_and_sha256`: **PASS**
   - `test_white_asset_counts_and_structure`: **PASS** (11 meshes, 107,307 verts, 208,032 tris)
   - `test_armored_asset_counts_and_structure`: **PASS** (130 meshes, 108,304 verts, 200,782 tris)
   - `test_sha256_mismatch_raises_codex_glb_load_error`: **PASS**
   - `test_asset_diagnostics_contract`: **PASS**
   - `test_build_articulated_mesh_output_format`: **PASS**
   - `test_no_procedural_fallback_enforcement`: **PASS**
   - **Result:** `Ran 8 tests — OK (100%)`

2. **Live Session & Acceptance Suites (`tests/test_bagusmax_v5_4_1_live_correctness.py` & `tests/test_bagusmax_v5_4_acceptance.py`):**
   - **Result:** `Ran 30 tests — OK (100%)`

---

## 9. Frozen Executable & Windows Installer Verification

The Windows package was recompiled with `OpenBagus.spec` including `pygltflib` and `assets/bagusmax/runtime/*.glb`.

### Recompiled Windows Installer:
- **Installer Filename:** `OpenBagus-Setup.exe`
- **Output Directory:** `E:\Projects\OpenBagus\release\`
- **Size:** `1,133,639,747 bytes` (1.13 GB)
- **SHA-256 Checksum:** `2478023d9a3072a4cd847bf9ad7c62eaebaf6baa204ac7cac15e036be964986e`
- **Recorded In:** `release/SHA256SUMS.txt` & `release/release_manifest.json`

### Direct Execution Test of Installed Frozen Executable:
Running `_installed/OpenBagus/OpenBagus.exe --internal-companion-renderer --port 7492`:
```json
{
  "status": "ok",
  "app": "openbagus_companion",
  "version": "1.0",
  "pid": 23808,
  "model_source": "CODEX_GLB",
  "model_loaded": true,
  "form": "WHITE",
  "diagnostics": {
    "model_source": "CODEX_GLB",
    "form": "WHITE",
    "asset_filename": "bagusmax_white_anatomy_v4_1.glb",
    "resolved_asset": "E:\\Projects\\OpenBagus\\_installed\\OpenBagus\\_internal\\assets\\bagusmax\\runtime\\bagusmax_white_anatomy_v4_1.glb",
    "asset_exists": true,
    "asset_sha256": "9ec223bb6ecd563437ee17c2b7a20cdd74a9b10d7f98a74e0d1150bb66e9569b",
    "expected_sha256": "9ec223bb6ecd563437ee17c2b7a20cdd74a9b10d7f98a74e0d1150bb66e9569b",
    "sha256_verified": true,
    "renderer": "OPENGL",
    "procedural_fallback": "DISABLED",
    "total_vertices": 107307,
    "total_triangles": 208032,
    "mesh_count": 11,
    "joints_count": 32,
    "morph_targets_count": 10
  }
}
```
**Conclusion:** The installed application directly locates, parses, verifies, and renders the authentic Codex White Anatomy V4.1 GLB with 100% integrity and zero procedural fallback.

