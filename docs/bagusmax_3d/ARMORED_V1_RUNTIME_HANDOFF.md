# BAGUSMAX Armored V1 Runtime Handoff

Status: **REVIEW_REQUIRED / NOT APPROVED FOR INTEGRATION**. Antigravity tetap pemilik animation runtime, renderer dan behavior. Dokumen ini hanya menyediakan batas asset contract.

## Entry Points

| File | Fungsi |
|---|---|
| `assets/bagusmax/source/bagusmax_armored_v1.blend` | Editable source; desktop geometry aktif, original quality mesh datablocks dipertahankan, White copy untuk fitting |
| `assets/bagusmax/runtime/bagusmax_armored_v1.glb` | DESKTOP_RUNTIME, armor seated, relaxed hands, folded wings, 0 clips |
| `assets/bagusmax/runtime/bagusmax_armored_v1_quality.glb` | QUALITY review/export, IDs node sama, geometry lebih padat |
| `assets/bagusmax/armor/armor_assembly_manifest.json` | Part discovery dan actual transforms |
| `assets/bagusmax/armor/armor_attachment_map.json` | Rest joint matrices dan mechanical controls |
| `assets/bagusmax/armor/armor_materials.json` | Exported PBR material definitions |
| `assets/bagusmax/armor/armor_transformation_timeline.json` | Absolute reversible phase specification |
| `assets/bagusmax/armor/armor_white_fit.json` / `.bin` | Exact-layout White clearance dan surface region data; bukan animation |

Baca `ARMORED_V1_ASSEMBLY_CONTRACT.md` untuk matrix order, axis conversion, bone mapping, formulas, coverage dan event semantics. Jangan menebak node berdasarkan substring material merah. `part_id`/`gltf_node_name` canonical. Node `ARMOR_*` adalah geometry; `ASM_*` dan `CTRL_*` adalah mekanisme/assembly, bukan joint White tambahan.

White original wajib dibaca dari `bagusmax_white_anatomy_v4_1.glb` yang hash-nya cocok dengan attachment/fit manifest. Perubahan layout White memerlukan regeneration fit data, bukan bypass validation. Original White V4.1 10 corrective morphs tetap merupakan kontrak tersendiri dan tidak ditambahkan ke GLB armor. Source Armored mempunyai shape clearance tambahan hanya pada White copy dengan default 0.

## Acceptance Sebelum Integration

1. Pengguna menyetujui arah visual neutral empat arah, helmet/shoulder/hands dan folded wings.
2. Deep elbow clearance diperbaiki atau runtime envelope dibatasi secara eksplisit. Candidate ini belum memberi izin elbow 110-130 derajat.
3. Antigravity menguji primary White finger joints dan secondary mechanical control blend agar tidak double-curl.
4. Coverage/index masking dan normal recomputation di renderer diuji frame-by-frame; art preview tidak membuktikan tanpa pop-in.
5. Head/eyes tunggal, correct PBR color space, all rigid plates ikut node global, dan skinned face menggunakan IBMs.
6. Runtime FPS, frame-time, VRAM/RAM dan GLB upload cost di hardware target diukur. Angka parser NumPy bukan GPU benchmark.

## Test Evidence

- `validation_report.json`: actual desktop geometry/buffers, official Khronos result, independent transform tests.
- `quality_statistics.json`, `quality_desktop_profile.json`: profile tradeoff dan sampled surface error.
- `rig_compatibility.json`: original White versus Armored joint rest matrices.
- `blender_pose_matrices.json`, `independent_transforms.json`: actual GLB geometry samples versus Blender, termasuk original finger anchors.
- `neutral_reimport.json`: separate GLB import pada neutral pose.
- `collision_samples.json`: actual BVH surface-overlap pairs. Bukan hanya AABB check. Hanya pasangan kritis terpilih, bukan full collision certification.
- `assembly_determinism.json`: forward/reverse evaluation dan neutral return; tidak membuktikan continuous collision-free assembly.
- `source_geometry_audit.json`: local topology, manifold edges, volume dan transforms.
- `preservation_before.json`, `preservation_after.json`: SHA-256 White/rollback/legacy Armored/lighting spec.
- `saved_source_state.json`: 0 Actions, clearance default 0, studio unchanged.

## Reproduction

Gunakan existing Blender 5.2.2 LTS. Semua command dijalankan dari `E:\Projects\OpenBagus-3D`. Builder tidak mengubah runtime atau White files. Jangan menjalankan builder setelah approval tanpa persetujuan art baru, karena candidate Armored akan digenerate ulang.

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --stage blockout
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --stage detail
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --python tools/bagusmax_asset_pipeline/build_armored.py -- --verify-existing
& 'E:\Projects\OpenBagus\.venv\Scripts\python.exe' -B tools/bagusmax_asset_pipeline/review_armored.py
```

Validator menggunakan official `gltf-validator` yang sudah tersedia di local Temp cache, tanpa instalasi global. Letak cache adalah environment dependency, bukan runtime dependency. Scripts menghasilkan source, GLB, data art dan report; tidak menghasilkan Actions, animation clips, runtime controller, keyframes atau layanan baru.

## Technical References

- [Khronos glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html): scene graph, skins, inverse-bind matrices, rigid node transforms, metallic-roughness.
- [Khronos glTF Validator](https://github.com/KhronosGroup/glTF-Validator): official structural validation.
- Blender installed API/exporter dipakai untuk actual source evaluation dan export. Halaman Blender manual yang dicoba tidak dapat diakses melalui browser tool; tidak dianggap sebagai bukti hasil.

Tidak ada runtime FPS atau VRAM claim. Tidak ada commit, stage, merge atau push. Lighting Gate tetap terkunci.
