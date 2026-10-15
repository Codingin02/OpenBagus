# White Bagusmax: Anatomy and Deformation Handoff

Status: **Gate A review, belum disetujui pengguna**. Gate B berupa spesifikasi
draft saja. White diperinci dari source refined yang sudah ada; scene baseline
tidak dibangun ulang. Kode aplikasi dan Armored tidak berubah.

## Source dan Runtime

Worktree: `E:\Projects\OpenBagus-3D`, branch `feat/bagusmax-3d-art`.

| Peran | Path relatif |
| --- | --- |
| Original dan rollback pertama | `assets/bagusmax/source/bagusmax_white.blend`, `bagusmax_white_before_anatomy_refinement.blend` |
| Baseline refinement, tidak ditimpa | `assets/bagusmax/source/bagusmax_white_anatomy_refined.blend` |
| Source detail editable | `assets/bagusmax/source/bagusmax_white_anatomy_detailed.blend` |
| GLB tanpa animasi | `assets/bagusmax/runtime/bagusmax_white_anatomy_detailed.glb` |
| Hash semua source | `reports/bagusmax_3d/white_detail/source_hashes.json` |
| Review neutral dan pose | `reports/bagusmax_3d/white_detail/` |
| Kontrak lighting | `docs/bagusmax_3d/WHITE_LIGHTING_SPEC.md` |

SHA-256 original dan rollback pertama sama:
`1edb34fd517a8c58e51fc251ce56adc5eb71931d385cc4594fafad6691da6dfa`.
Hash source refined sebelum/sesudah task tetap
`7335edd1d6e2039f02782089e4ffe1bf6aa8eb4983d3dfd2c7e87ee8db2b3506`.

Mesh lama tangan/port disimpan sebagai datablock fake-user dalam source detail,
selain source baseline terpisah. Source aktif tetap punya mesh bernama, UV dan
vertex groups, bukan satu baked object. Tangan memakai union/remesh lokal;
torso, kepala dan kaki tidak direkonstruksi.

## Reference Feature Matrix

Nomor frame mengacu pada 19 lampiran pengguna pada request detail terakhir.
Foto film tidak orthographic atau terkalibrasi. Panel perbandingan foto hanya
untuk private review; jangan commit atau distribusikan tanpa hak terkait.

| Feature | Baseline refined | Film observation | Koreksi | Confidence | Frame | Test view |
| --- | --- | --- | --- | --- | --- | --- |
| Lower belly | masih ada titik kecil di pusat | dasar lembut dan bulat | angkat pusat bawah lokal | medium | 2,8 | front, legs, clay |
| Head/face | mata sedikit terangkat | mata/garis mengikuti capsule | proyeksi ke permukaan kepala | high | 1,10,12,18 | head 25/50/100/150% |
| Shoulder | root terlihat terpisah saat raised | akar lengan empuk | pivot upper arm disesuaikan, blend weight | medium | 3,5,9,13,16 | shoulder, T2/T3/T5 |
| Elbow | belum ada panel | region oval vinyl dan boundary | material pada face mesh dan seam tipis fitted | high | 4,5,7,9,13,16 | elbow, profile, T4 side |
| Torso seam | tidak ada | seam horizontal halus | satu seam keliling mengikuti torso | high | 11,12,18 | torso/profile |
| Chest port | ring dan simbol C | tutup bundar dengan latch melintang | lid, rim tertutup dan latch tipis | high | 1,3,10,11,12,18 | port/raking |
| Hands | jari bead-like dan palm/wrist tegas | palm lembut, thumb dan 3 finger terlihat | redesign lokal, tip panjang rounded | medium | 1,6,9,14,17,19 | hand, T2 side |
| Legs | pendek dan grounded | pendek, inflated, tanpa sepatu | bentuk dipertahankan, Foot weights diaktifkan | medium | 2,8 | legs, T9 |
| Rear | hidden detail belum jelas | tidak ada full rear baru | tidak mengarang detail rear | low | tidak tersedia | back/T10 |

Viewpoint evidence: front/three-quarter 2,3,10,11,12,14,17,18,19;
side/three-quarter 5,7,9,16; head/port close-up 1,10,12,18;
non-neutral hug/hand/arm 4,6,8,13,15. Tidak ada referensi rear terkalibrasi.

## Proporsi dan Surface

Pengukuran world-space mesh bounds, normalized standing height:

| Ratio | Refined baseline | Detailed |
| --- | ---: | ---: |
| Arm span / H | 0.7411 | 0.7411 |
| Head width / H | 0.2504 | 0.2504 |
| Head depth / H | 0.1721 | 0.1721 |
| Torso width / H | 0.5282 | 0.5282 |
| Torso depth / H | 0.4884 | 0.4884 |

Silhouette utama dipertahankan. Lower belly mendapat koreksi kecil terlokalisasi;
jari dibuat lebih panjang, palm/wrist lebih penuh. Source torso/limb tetap
bertopologi smooth yang sudah ada. Close-up wrist masih memiliki ridge ringan.

Port diameter sekitar 0.073 m, anatomical left (+X Blender). Rim dan lid
menempel pada torso; latch melintang mengikuti referensi, tanpa opening SD-card.
Panel siku adalah material region pada arm mesh sehingga mengikuti skin langsung.
Seam tambahan dan port memakai bobot nearest surface vertex, bukan posisi world
tetap. Transfer ini aproximasi; belum dibuktikan cocok untuk semua deformasi.

Vinyl nonmetallic off-white roughness 0.43 dipertahankan. Panel roughness 0.52,
seam 0.56, port warna sedikit berbeda. Ada 5 material, tanpa texture eksternal.
Tidak ada lighting/shadow desktop yang dibake.

## Rig dan Audit

20 joint baseline dipertahankan, tanpa joint tambahan. Hierarchy:

```text
Root -> Hips -> Spine -> Chest -> Neck -> Head
Chest -> Shoulder_L/R -> UpperArm_L/R -> Forearm_L/R -> Hand_L/R
Hips -> Thigh_L/R -> Shin_L/R -> Foot_L/R
```

Pivot UpperArm_L/R diubah dari (+/-0.3383,0,1.32) menjadi
(+/-0.24,0,1.37); Shoulder_L/R tail mengikuti titik tersebut. Elbow/Hand pivots
tetap. Arm weights dihaluskan, shoulder root memakai blend kecil ke Chest.
Foot_L/R kini mempunyai bobot langsung, selain Thigh/Shin. Joint logical seperti
Root/Neck/Shoulder memengaruhi descendant lewat hierarchy walaupun tidak selalu
punya vertex weights langsung. Tidak ada finger joint; Hand menggerakkan seluruh
palm/fingers. Artikulasi per jari memerlukan ekspansi rig yang ditinjau kemudian.

Source memakai linear blend skinning, sama dengan kontrak GLB; preserve-volume
Blender tidak dipakai untuk menyamarkan deformasi yang tidak tersedia pada
runtime LBS. `Edit_Hand/Wrist/Elbow/Shoulder` mendukung seleksi manual arm;
torso/head/leg tetap punya region edit dari refinement sebelumnya.

Audit `asset_audit.json`: setiap mesh manifold, tidak ada duplicate vertex
positions pada toleransi 1e-7, triangle degenerate, atau bobot invalid. Bobot
deform ternormalisasi dan paling banyak 4 influence. UV tangan provisional;
tidak ada texture yang membutuhkan bake acceptance. Audit tersebut bukan
sertifikasi self-intersection semua surface dan semua pose.

## Pose Inspection

T1 rest; T2/T3 angkat lengan kiri/kanan dengan elbow flexion; T4 elbow sekitar
90 derajat; T5 kedua arm ke depan sebagai awal hug; T6 tilt head kiri/kanan;
T7 lean torso forward; T8 lean sideways; T9 gerak leg moderat; T10 rotasi Root
180 derajat. T2/T4/T5 juga punya side render. Setiap pose diterapkan sementara,
tanpa keyframes; source disimpan netral sebelum inspeksi dan pose di-reset.

Tidak ada volume ratio whole-mesh yang keluar dari rentang inspeksi 0.85-1.15.
Ini tidak menjamin bentuk lokal: T2/T3 masih menunjukkan upper shoulder yang
kurang bulat dan elbow agak angular. T4 juga memiliki crease lokal pada bagian
dalam elbow. T5 adalah arm-forward inspection, bukan hug yang menyentuh badan.
T6-T10 tampak stabil pada sudut yang diuji, tetapi belum collision-certified.
Tidak ada deformasi yang dinyatakan production-ready untuk semua gerakan.

Semua seam/port ikut pose melalui skin. Kecocokan permukaan ekstrem belum
disetujui. Source dan GLB berisi **0 action/animation**.

## Validasi dan Performance

GLB: 15 meshes, 17 primitives, 5 materials, 20 joints, 161,200 triangles,
84,922 exported vertices; sekitar 5.32 MB. Header/accessor/index/normal/UV/
weights diperiksa oleh reviewer lokal. Khronos glTF Validator: **0 errors,
0 warnings**; info hanya unused UV karena material tanpa texture. Blender
import balik: 15 visible meshes, satu armature, 0 actions.

Blender exporter memberi pesan parent-armature fallback karena skinned mesh
berada sebagai root scene nodes; Khronos tidak menemukan warning dan native
Blender import sukses. Antigravity perlu memuat node names, skins, inverse bind
matrices dan JOINTS/WEIGHTS; mesh datablock names dapat memiliki suffix internal.

Hardware terdeteksi RTX 3050 Laptop 6 GB. Single-sample Blender import sekitar
0.694 s; bukan load-time aplikasi. Estimasi vertex/index buffers 6.38 MiB,
bukan VRAM actual. Draw calls potensial 17 primitives. FPS/frame time,
CPU/GPU skinning aplikasi dan memory runtime **NOT TESTED**. Tidak ada klaim
60 FPS atau decimation hanya untuk mengejar angka triangle.

## File Scope dan Approval

| File/area | Perubahan |
| --- | --- |
| `detail_white_anatomy.py` | local mesh details, skin weights, static export, pose inspection |
| `review_white_details.py` | reuse validator/boards, film comparison private, hash proof |
| Source/GLB detailed | aset baru; source refined dan rollback dipertahankan |
| `white_detail/` | neutral/detail/pose render, audit, validation, performance |
| Handoff ini | kontrak source/rig/status aktual |
| Lighting spec | draft projection/alpha/monitor contract, tanpa runtime code |

Gate B **belum dimulai**. Anchor draft monitor (0.50,0.10), runtime projection,
transparent shadow, DPI/multi-monitor serta desktop captures dibahas di
`WHITE_LIGHTING_SPEC.md`. Implementasi baru boleh dimulai setelah persetujuan
visual Gate A dan koordinasi ownership Antigravity.

Belum ada commit, stage, merge atau push. Working tree 3D berisi aset untracked
yang disengaja. Main OpenBagus tetap clean saat pemeriksaan terakhir. Armored,
audio, LLM, CLI, Harness, finance, preferences dan renderer aplikasi tidak diedit.
