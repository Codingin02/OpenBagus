# White Bagusmax: Anatomical Recovery

Status: kandidat review anatomi, bukan production-ready. Persetujuan visual user
belum diberikan. Range ekstrem tidak disertifikasi. GATE B NOT STARTED.
Source baseline: `assets/bagusmax/source/bagusmax_white_anatomy_detailed.blend`.
Baseline SHA-256: `dbfb5e734c37a101c969872668214e91d1b9ff615c389b0b2fa03ee994671a04`.
Original rollback SHA-256: `1edb34fd517a8c58e51fc251ce56adc5eb71931d385cc4594fafad6691da6dfa`.

## Visual Discrepancy Map

Frame numbers refer to the 38 images in the anatomical-recovery request.
Repeated copies are the same evidence, not independent confirmation.

| Region | Film observation and connection | Existing defect | Correction to test | Confidence / evidence |
| --- | --- | --- | --- | --- |
| Outer elbows | broad soft oval above/across flexion area, integrated vinyl | faint region with separate fitted boundary | integrated face material plus shallow relief; bind on arm vertices | high: 8,16,20,33,34,35 |
| Shoulder | inflated upper arm flows out of sloped chest | tapered root and two-rotation LBS blend flatten on elevation | shoulder volume helper and redistributed root weights | high: 8,13,19,20 |
| Elbow bend | rounded outside, compressed inner fold | angular hinge/collapse at 90 degrees | half-angle elbow helper actually weighted | high: 8,12,20,34 |
| Torso sides | curved region behind arm approaching lateral hip | not investigated/implemented in detailed source | subtle integrated panel; optional low-relief source variant | medium: 5,18,34,35; some boundaries occluded |
| Belly/hips | rounded lower volume overlaps inflated thighs softly | overly flat/central cusp and rigid thigh roots | broad lower curvature and pelvis/thigh weight transition | medium: 13,19,34 |
| Wrist | continuous narrowing into padded palm | circumferential notch left by local boolean | replace only damaged wrist band with quad rings | high: 7,12,20 |
| Fingers/thumb | four rounded digits with recognizable bases | stiff palm and parallel pill forms; no finger joints | local curvature/thumb correction; minimal individual controls | high: 2,7,12,20 |
| Head/port | capsule eyes and circular shallow latch | port already visibly improved | preserve; only validate contact under poses | high: 3,12,26 |

Neutral group: 3,5,13,14,16,18,26. Vinyl detail: 5,8,12,16,20,34,35.
Articulation group: 1,2,4,7,8,13,15,17,19,20,29,33,34,35.
Current-output comparison uses local `white_detail` renders and actual detailed
source, not a differently framed film camera. No calibrated rear reference exists.

## Recovery Constraints

Preserve the complete detailed source and GLB. Edit only a new source derivative.
Keep canonical bone names; any helpers must have actual weights and an explicit
runtime update formula. Blender-only effects do not count as runtime validation.
Before/after renders must use identical cameras, poses and studio light settings.
No Actions/NLA/animation clips. No application or Armored edits. No commit/push.

## Root Cause dan Perubahan Lokal

- Panel siku sebelumnya terlalu samar dan memakai objek seam terpisah. Kedua
  panel sekarang merupakan region warna vertex pada mesh lengan, bukan tempelan.
  Inset maksimum 1 mm mengikuti permukaan. Objek seam lama tetap tersembunyi
  dalam source untuk pemeriksaan, tidak ikut GLB.
- Pivot upper arm sebelumnya di `(+-0.24, 0, 1.37)`; sekarang
  `(+-0.29, 0, 1.27)` meter. Transisi bobot yang sempit dan tidak ada volume
  helper menghasilkan bentuk sendi kaku. Root lengan diperlebar lokal,
  shoulder weights direntangkan sepanjang z=1.02..1.405, helper benar-benar
  menerima bobot. Pivot siku tidak dipindah tanpa bukti yang memadai.
- Elbow helper membagi rotasi untuk mempertahankan bagian luar tekukan.
  Inner fold tetap terlihat, sebagaimana kompresi bahan lunak; flexion ekstrem
  belum memenuhi kualitas visual.
- Band pergelangan z=0.525..0.665 diganti lokal dengan sembilan segmen quad.
  Area lain tidak di-remesh global. Titik hampir berimpit pada hasil bisect
  dibersihkan dengan toleransi 0.01 mm. Telapak dipertahankan; ujung digit
  dilengkungkan dan thumb dikoreksi lokal.
- Abdomen bawah memakai koreksi kurva lebar, bukan menurunkan satu titik.
  Bobot pangkal paha dibaurkan ke Hips sampai 85%; Foot weights dipertahankan.
- Head, face, circular chest port, proporsi keseluruhan, dan studio inspeksi
  tidak dibangun ulang. Tidak ada global subdivision baru.

## Panel Torso dan Ketidakpastian

Region torso kiri/kanan tidak dinyatakan FILM-CONFIRMED. Frame #34 dan #35
menunjukkan area lateral, tetapi overlap lengan, pose, dan bayangan menghalangi
penentuan batas yang presisi. Repeated screenshots bukan bukti independen.

Variant A adalah material transition halus dengan inset maksimum 0.4 mm,
berada di mesh torso. Ini default GLB. Variant B tersedia melalui shape key
`White_Torso > TorsoSide_Relief_Optional`, range 0..1, menambah relief sampai
1.5 mm. Basis/value 0 = A; value 1 = B. Variant B tidak dipaksa ke runtime,
dan morph target ini sengaja tidak diekspor. Lihat `torso_variants.png`.

Close-up `torso_left/right` mengisolasi torso dengan kedua lengan disembunyikan
di KEDUA versi. Full-body/three-quarter/combined renders tidak menyembunyikan
lengan. Close-up isolasi bukan bukti kondisi normal tanpa occlusion.

## Hierarki dan Bone Mapping

20 nama lama dipertahankan; total sekarang 32 joints. Jangan mengandalkan urutan
index skeleton lama. Gunakan nama. Semua tambahan memiliki vertex weights.
Count bobot per kontrol tersedia pada `recovery_audit.json`.

```text
Root
  Hips
    Spine > Chest > Neck > Head
    Thigh_L > Shin_L > Foot_L
    Thigh_R > Shin_R > Foot_R
Chest
  Shoulder_L > UpperArm_L > Forearm_L > Hand_L
  Shoulder_R > UpperArm_R > Forearm_R > Hand_R
```

Untuk setiap suffix L/R:

| Bone tambahan | Parent | Fungsi |
| --- | --- | --- |
| ShoulderVolume | Shoulder | Half-angle dari UpperArm; mempertahankan root inflated |
| ElbowVolume | UpperArm | Half-angle dari Forearm; mengurangi collapse elbow |
| Thumb | Hand | Kontrol thumb independen |
| Index | Hand | Kontrol index independen |
| Middle | Hand | Kontrol middle independen |
| Ring | Hand | Kontrol digit terakhir independen |

Helper volume adalah SIBLING primary, bukan child primary yang akan menggandakan
rotasi. Empat digit per tangan mencakup thumb + tiga digit lainnya; satu bone
per digit, bukan rig multi-phalange. Jangan menganggap ada kontrol tiap knuckle.

Perubahan rest yang disengaja pada bone lama: head UpperArm L/R dan tail
Shoulder L/R. Ini juga mengubah orientation/rest matrices kedua pasangan tersebut.
Jangan menyalin animation transforms lama tanpa retargeting/rebase.
`baseline_skeleton` dan `skeleton` dalam audit menyimpan parent, head, tail,
serta matrix 4x4 SEMUA bone sebelum/sesudah. Itu sumber transform canonical,
bukan angka perkiraan dari gambar.

## Kontrak Deformasi Runtime

Linear blend skinning, maksimum empat influences, normalized weights. Tidak
mengandalkan Preserve Volume/DQ, Bendy Bones, Corrective Smooth, atau deformasi
simulasi Blender yang tidak dapat direpresentasikan oleh skin glTF standar.

Source Blender memakai 16 quaternion driver channels untuk empat helper.
Kontrol primary harus tetap dalam rotation mode QUATERNION. Driver half-angle
otomatis bekerja karena rest orientation helper disamakan dengan primary.
Drivers bukan animation clips dan tidak disimpan sebagai Actions/NLA.

GLB berisi joint biasa, BUKAN driver Blender. Antigravity harus memperbarui
empat helper setiap pose update, setelah quaternion primary ditentukan.
Tanpa aturan ini, kualitas deformasi yang ditunjukkan tidak berlaku.

Dengan quaternion unit, perkalian mengikuti urutan transform kolom:

```text
R = absolute rest orientation primary dalam armature space
H = absolute rest orientation helper dalam armature space
q = rotation delta primary dari rest, bukan quaternion node absolut
D = R * q * inverse(R)
half = slerp(identity, D, 0.5), shortest arc
helper_delta = inverse(H) * half * H
helper_node_local = helper_rest_local * helper_delta
```

Jika membaca quaternion node glTF langsung:
`q = inverse(primary_rest_local) * primary_current_local`.
Jangan mencampur Blender Z-up dan glTF Y-up, atau mengasumsikan bone axes
hasil import identik. Gunakan rest matrices pada koordinat runtime yang sama.
Implementasi pembanding: `update_volume_helpers()` pada pipeline recovery.
Untuk twist/gerak di luar pose yang diuji, belum ada jaminan kualitas.

Tidak ada perubahan pada loader, renderer, ASR/TTS, harness, finance, atau
English Tutor. Integrasi aplikasi OpenBagus: NOT TESTED, bukan automatic PASS.

## Bukti dan Pose

Semua gambar inspeksi memakai studio yang diwarisi, bukan cinematic lighting.
720x720 per snapshot; contact sheet hanya ringkasan. Periksa PNG asli bila
menilai crease. Before/after memakai kamera dan pose numerik yang sama.
Perubahan posisi pivot memang mengubah lintasan joint secara sengaja.

Folder: `reports/bagusmax_3d/white_v3/`.

- `anatomy_overview.png`: ringkasan delapan area before/after.
- `compare_front/left/right/three_quarter.png`: proporsi dan side silhouette.
- `compare_elbow_left/right.png`, `compare_E3_L/R.png`: kedua siku.
- `compare_torso_left/right.png`, `torso_variants.png`: region lateral.
- `compare_S5_L.png`, `poses_shoulders.png`: shoulder regression.
- `compare_C2/C4.png`, `poses_combined.png`: combined poses.
- `compare_legs/C9.png`: abdomen, paha, hip movement.
- `compare_hand.png`, `finger_controls.png`: wrist, thumb, digit.
- `poses_panels.png`, `poses_elbows.png`: attachment dan flexion.
- `film_comparison_private.png`: bukti referensi kualitatif, bukan rasio
  proporsi terkalibrasi atau klaim reproduksi film persis. Referensi bersifat
  private; tidak dipaketkan ke GLB dan tidak dipublikasikan.

Hasil visual per pose dicatat di bawah. PASS terbatas pada snapshot tersebut,
bukan semua kombinasi sudut atau collision certification. LIMIT berarti belum
memenuhi target kualitas penuh dan tidak boleh dipromosikan sebagai PASS.

| Pose | L | R | Observasi / batas |
| --- | --- | --- | --- |
| S0 neutral | PASS | PASS | Panel attached; wrist notch besar hilang |
| S1 forward 30 | PASS | PASS | Tidak ada tearing / collapse berat |
| S2 forward 60 | PASS | PASS | Transisi root lebih bulat; tetap stylized |
| S3 forward 90 | PASS | PASS | Tidak terputus; bukan sertifikasi twist |
| S4 side 45 | PASS | PASS | Moderate elevation tanpa crease bahu tajam |
| S5 side 90 | LIMIT | LIMIT | Attachment stabil, root masih meruncing dari sudut tertentu |
| S6 side 110 | FAIL | FAIL | Overhead belum didukung untuk kualitas film-like |
| E0 rest | PASS | PASS | Region lateral jelas |
| E1 flexion 30 | PASS | PASS | Volume dan attachment stabil |
| E2 flexion 60 | PASS | PASS | Outer bend lebih bulat |
| E3 flexion 90 | PASS | PASS | Inner fold terlihat; tidak severe collapse |
| E4 flexion 115 | FAIL | FAIL | Tekukan dalam masih tampak terlalu geometris |

| Combined | Hasil | Observasi |
| --- | --- | --- |
| C1 forward open hand | PASS | Static reach; tidak ada objek interaksi |
| C2 greeting | PASS | Forearm diarahkan naik; bukan animation wave |
| C3 lateral arms | LIMIT | Bentuk root pada elevasi tinggi masih perlu perhatian |
| C4 forward hug preparation | PASS | Kedua lengan stabil; bukan pelukan manusia tervalidasi |
| C5 inward forearms | LIMIT | Tidak disertifikasi untuk kontak tubuh/objek |
| C6 downward reach | PASS | Wrist dan arm continuity stabil |
| C7 forward torso bend | PASS | Port dan panel tetap mengikuti torso |
| C8 side lean | PASS | Tidak tampak tearing |
| C9 moderate hip | PASS | Tidak ada catastrophic thigh collapse |
| C10 head tilt + arm | PASS | Head/port stabil pada snapshot |
| F1 individual digits | LIMIT | Kontrol terpisah bekerja; belum hand articulation lengkap |

## Validation dan Performance

Audit mesh, weights, parent/rest transforms, source state dan round-trip:
`recovery_audit.json`. Struktur/buffer/draw statistics: `glb_structure.json`.
Khronos official validator: `khronos_validation.json`. Hash semua asset:
`asset_hashes.json`. Jangan memakai report dari `white_detail` sebagai bukti V3.

Round-trip membandingkan sampel setiap tiga vertex source terhadap semua vertex
GLB yang di-import kembali, pada S5_L, E3_L, E3_R, C2, C4, C9. Ini nearest-surface
sample comparison, bukan per-vertex topology identity, dan menggunakan helper
update yang diwajibkan di atas. Batas tes 0.5 mm; angka aktual ada dalam audit.

Khronos PASS tidak sama dengan acceptance visual. Buffer bytes bukan ukuran
VRAM nyata. Waktu import Blender bukan waktu loader OpenBagus. Runtime frame
time, FPS dan VRAM: NOT TESTED. Jangan mengklaim 60 FPS.

Hasil final yang terukur:

| Ukuran | Nilai |
| --- | --- |
| GLB | 5,953,660 bytes |
| Triangles | 163,108 (baseline 161,200; naik 1.18%) |
| Exported vertices | 83,864 |
| Meshes / draw primitives | 13 / 13 |
| Materials / joints | 5 / 32 |
| Clips / Actions / NLA | 0 / 0 / 0 |
| Maximum skin influences | 4 |
| Nonmanifold / degenerate / weight errors | 0 / 0 / 0 |
| Geometry buffer payload, termasuk COLOR_0 | 5,929,112 bytes |
| Blender import GLB | 0.451 s pada run audit final; bukan benchmark aplikasi |
| Round-trip, 6 snapshots | PASS, max 0.004709 mm |
| Khronos errors / warnings / infos | 0 / 0 / 13 |

13 infos Khronos adalah `UNUSED_OBJECT` (UV accessors tidak dipakai material
tanpa texture); bukan 13 skin errors. Exporter Blender memberi warning
fallback armature lookup karena sebagian mesh baseline tidak diparent langsung
ke armature. Armature modifier tetap eksplisit, native round-trip PASS, dan
Khronos final tidak memiliki warning. Parenting asli dipertahankan agar tidak
memperkenalkan warning skinned non-root node atau mengubah scene contract.

## Source Integrity dan Handoff

Source kandidat: `assets/bagusmax/source/bagusmax_white_anatomy_v3.blend`.
Runtime kandidat: `assets/bagusmax/runtime/bagusmax_white_anatomy_v3.glb`.
Detailed source dan GLB tetap tersedia; rollback asli tetap tersedia.
Hash lengkap kandidat ada di `asset_hashes.json`; baseline source di atas
harus tetap identik. Source disimpan neutral, variant B=0, tanpa Actions/NLA.

SHA-256 source V3:
`7712634225a665564bbf1ce58bb5a60d6431ad7a1276d7a8aa2adbbb488588e9`.
SHA-256 GLB V3:
`f301aaec43d0d513ebe1860978b3403717e7c29a958317a4fb4831e89d9d43c6`.
SHA-256 detailed GLB yang dipertahankan:
`8532a844dc62566912d46871f8c13f9d7e6b445ed1f35db46bc8f34b337f68b9`.

Branch kerja: `feat/bagusmax-3d-art`. Asset art tree masih untracked sebagaimana
awal task; GLB mengikuti ignore rules existing. Tidak ada stage, commit,
push, merge atau perubahan branch. Main OpenBagus diperiksa read-only.

Antigravity boleh mengandalkan nama bone lama, tambahan yang terdokumentasi,
skin standar dan report transform. Tidak boleh mengandalkan fixed 20 joints,
helper otomatis di glTF, rig multi-phalange, arbitrary twist, deep elbow,
overhead atau contact collision yang belum diuji. Ini bukan persetujuan untuk
mengubah aplikasi atau membuat animation clips pada task ini.

**GATE B NOT STARTED.** `WHITE_LIGHTING_SPEC.md` tidak diubah.
