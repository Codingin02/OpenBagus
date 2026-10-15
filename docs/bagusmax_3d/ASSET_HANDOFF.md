# Bagusmax White Asset Handoff

Status: **AWAITING_USER_VISUAL_REVIEW**. Ini aset review, bukan integrasi aplikasi
atau sertifikasi rig produksi. Armored belum dibuat; tunggu persetujuan White.

## File

Semua path relatif terhadap worktree `E:\Projects\OpenBagus-3D`.

- Source editable: `assets/bagusmax/source/bagusmax_white.blend`.
- Runtime: `assets/bagusmax/runtime/bagusmax_white.glb`.
- Pipeline: `tools/bagusmax_asset_pipeline/build_white.py`.
- Round-trip/pose inspection: `tools/bagusmax_asset_pipeline/inspect_in_blender.py`.
- GLB validation dan reference boards: `tools/bagusmax_asset_pipeline/review_white.py`.
- Preview material/clay: `reports/bagusmax_3d/white_material_*.png`, `white_clay_*.png`.
- Front juga menjadi full-body view; torso dan head memiliki close-up tersendiri.
- Perbandingan kamera/tinggi seragam: `white_geometry_comparison.png`.
- Perbandingan referensi pengguna: `white_front_comparison.png`.
- Turnaround: `white_turnaround.png`; pose test: `white_wave_test.png`.
- Metadata aktual: `white_asset_status.json`, `white_glb_validation.json`,
  `white_roundtrip_validation.json` dalam `reports/bagusmax_3d/`.

## Authoring dan Export

Blender **5.2.2 LTS**, glTF 2.0 binary, embedded geometry/material/skin/animations.
Source menggunakan profil quad yang dibentuk khusus, subdivision, remesh lokal
untuk menyatukan telapak/jari, serta boolean union pergelangan. Bukan penggantian
primitive lama dengan sphere bersegmen lebih banyak.

Source: 135.786 triangle. Runtime: **82.438 triangle**, 42.712 exported vertices,
10 mesh dan 3 material; file 2.783.000 byte. Source mesh dipertahankan saat
derivasi runtime melalui decimation sebelum Armature modifier. Tidak diperlukan
Draco, Meshopt, CDN atau file texture eksternal untuk memuat GLB.

Estimasi vertex/index buffers sekitar **3,22 MiB**, bukan total VRAM aplikasi.
Performance OpenBagus bersama LLM/audio belum diukur dan menjadi scope Antigravity.

Material nonmetallic glTF PBR:

- `Vinyl_WarmWhite`: broad highlights, roughness 0.43.
- `Face_Charcoal`: roughness 0.65, tanpa emission.
- `AccessPort_White`: roughness 0.49.

UV tersedia. Layout prosedural belum dianggap final untuk texturing artistik.
Tidak ada texture/baked normal/AO/HDRI yang dibundel; preview memakai studio lights
dan world netral. Eevee dipakai untuk review cepat, Cycles untuk preview awal.

## Coordinates

- Blender: meter, +Z up, -Y forward, +X anatomical left.
- glTF: +Y up, +Z forward, +X anatomical left.
- Konversi Blender ke glTF: `(x, y, z) -> (x, z, -y)`.
- Jangan melakukan konversi tersebut dua kali pada file glTF yang sudah Y-up.
- Root authoring pada `(0,0,0)`, scale 1. Soles paling bawah sekitar 0,003 m.
- Tinggi geometris rest pose: **1,672 m**.
- Bounds Blender: X +/-0,692229; Y -0,439045..0,352852; Z 0,003..1,675.
- Bounds glTF: X +/-0,692229; Y 0,003..1,675; Z -0,352852..0,439045.
- Jika target aplikasi 1,5 m, gunakan satu parent scale `1.5/1.672`, sekitar
  0,897129, dan offset floor yang sesuai. Jangan scale tiap bagian sendiri.
- Armored baru nantinya harus mengikuti Root/tinggi yang sama. Jangan menganggap
  Armored existing langsung kompatibel atau menggantinya sebelum review.

## Skeleton dan Clips

20 joint, anatomical L/R konsisten:

```text
Root
  Hips
    Spine
      Chest
        Neck -> Head
        Shoulder_L -> UpperArm_L -> Forearm_L -> Hand_L
        Shoulder_R -> UpperArm_R -> Forearm_R -> Hand_R
    Thigh_L -> Shin_L -> Foot_L
    Thigh_R -> Shin_R -> Foot_R
```

Clips: `IDLE`, `LISTEN`, `SPEAK`, `WAVE`, `THINK`, `RETURN_TO_IDLE`.
Clips pendek disediakan sebagai asset-side samples, bukan voice-event integration.
`RETURN_TO_IDLE` merupakan rest target; controller harus blend dari pose aktif.
Head/eyes memakai Head joint, tanpa human mouth, facial blend shapes atau lip-sync.
Finger geometry terintegrasi, tetapi belum memiliki finger bones individual.

## Instruksi Integrasi untuk Antigravity

**Jangan langsung copy GLB ini ke lokasi runtime aplikasi.** Tunggu persetujuan
visual pengguna dan perbaikan/acceptance deformasi yang masih diperlukan.

Pembacaan read-only pada checkpoint `95d16dc` menunjukkan
`openbagus/companion/model_loader.py` masih mengelompokkan mesh melalui substring
nama, melakukan overwrite pada part key yang sama, dan memakai rigid pivots.
Kontrak itu tidak cukup untuk file skinned ini: mata, bridge dan chest port adalah
node tersendiri; kedua kaki juga node tersendiri.

Antigravity perlu:

1. Mempertahankan seluruh nodes/primitives, bukan overwrite berdasarkan kategori.
2. Mengevaluasi hierarchy, node TRS/matrix, skins dan inverse bind matrices.
3. Membaca `JOINTS_0`/`WEIGHTS_0`, buffer offsets/stride, termasuk accessor `MAT4`.
4. Mengevaluasi animation samplers/channels dalam satuan waktu glTF, serta blend
   saat perubahan state. Jangan double-apply rigid pivot setelah skinning.
5. Mendukung hingga empat bone influences. Joint matrix untuk skinning dalam
   ruang mesh adalah `inverse(mesh_world) * joint_world * inverse_bind`.
6. Memakai normals yang benar, material base color/roughness nonmetallic,
   tone mapping yang tidak membakar white highlights, dan color-space yang tepat.
7. Memetakan L/R secara anatomis. Legacy pivot `arm_l` pada -X bukan naming contract
   rig baru; jangan mirror aset secara tidak sengaja.
8. Menyesuaikan camera/floor/scale dari bounds nyata, bukan hardcoded ukuran lama.
9. Memetakan event aplikasi ke clip yang sudah disetujui. Codex tidak mengubah
   controller, renderer, preferences, voice maupun financial source.

Shader dapat melakukan GPU skinning, atau loader dapat menyiapkan posed buffers;
pilihan implementasi dan pengujian runtime sepenuhnya milik Antigravity.

## Review dan Limitasi

Perbandingan clay memakai tinggi dan kamera yang sama. Geometry checks membuktikan
manifold edge topology, UV/weight presence, finite positions, valid indices,
normalized weights, satu skin/20 joints dan enam animation names. Import ulang
GLB melalui Blender berhasil dan actual runtime front/clay telah dirender.
Pose WAVE telah diperiksa secara visual; ini bukan collision certification.

Defek yang masih memerlukan keputusan/finishing:

- Kontur tangan masih stylized; bentuk jari/ibu jari dapat disempurnakan artist.
- Inner elbow saat WAVE masih memiliki lipatan angular. Weight painting dan
  retopology deformation zones belum dinyatakan production-ready.
- Tidak ada pengujian seluruh poses terhadap self-intersection atau penetrasi.
- Surface kecil chest port sangat halus dan dapat hilang pada ukuran popup kecil.
- Reference fidelity pada permukaan tersembunyi tidak diklaim exact.
- Gambar referensi pengguna bersifat private review, tidak disertakan dalam GLB.
  Izin redistribusi gambar atau commercial character likeness tidak diverifikasi.
- Lampiran saat ini hanya White; referensi Red Armored belum tersedia pada task ini.

## Reproduce

Jalankan hanya dari worktree 3D, menggunakan PowerShell `-NoProfile`:

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python tools/bagusmax_asset_pipeline/build_white.py
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python tools/bagusmax_asset_pipeline/inspect_in_blender.py
& 'E:\Projects\OpenBagus\.venv\Scripts\python.exe' tools/bagusmax_asset_pipeline/review_white.py
```

`build_white.py -- --export-only` meregenerasi source dan GLB tanpa rerender semua
view. Baseline GLB yang dipakai untuk comparison tetap file existing worktree pada
`assets/models/bagusmax_white.glb`, bukan source main yang mungkin sedang berubah.
Reference-board regeneration memerlukan lampiran yang masih tersedia pada temp
folder jika salinan privat belum ada.

Tidak ada merge, commit, push atau runtime application integration yang dilakukan.
