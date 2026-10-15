# White Bagusmax V4

Status: kandidat review visual, bukan production-ready. GATE B NOT STARTED.

## Checklist Cacat Sebelum Edit

Baseline diverifikasi dari GLB: 163,108 triangles, 13 meshes, 5 materials,
32 joints, 0 clips, 5,953,660 bytes. Seluruh hash manifest V3 cocok.
V3 source SHA-256: `7712634225a665564bbf1ce58bb5a60d6431ad7a1276d7a8aa2adbbb488588e9`.
V3 GLB SHA-256: `f301aaec43d0d513ebe1860978b3403717e7c29a958317a4fb4831e89d9d43c6`.

| Prioritas | Bukti V3 / reference | Cacat dan sebab yang diperiksa | Target koreksi |
| --- | --- | --- | --- |
| P0 elbow panels L/R | neutral elbow crops; film #8,20,33,34 | Interior linear color .50/.53/.51 dibanding base .79/.79/.765; inset lebar 1 mm, boundary vertex-color blur | Interior mendekati vinyl, seam terintegrasi tipis, tidak ada outline mesh terpisah |
| P0 torso sides | isolated torso crops; film #34,35 | Interior .60/.64/.61 dan broad inset; boundary tidak didukung pasti oleh stills | Restrained curved seam, tanpa broad gray cavity; bentuk abdomen V3 tetap |
| P0 shoulders | S5/S6 L/R | Root hanya ShoulderVolume/UpperArm, tanpa Chest anchor; pivot rendah; narrow bridge | Chest anchor, transisi helper lebih koheren; uji 0..145 dan batas aman |
| P0 elbows | E3/E4 L/R | Bobot dan frame pada band tekuk menghasilkan sudut, bukan kurva kompresi | Perluas blend; koreksi pose-space jika weights saja gagal |
| P1 wrist/hand | rest/F1 crops; film #12,20,35 | Cekungan wrist/palm residual, finger roots sederhana | Isi notch lokal, haluskan palm/thumb, validasi gestures statis |
| P1 hip/thigh | front/side/C9; film #13,19,34 | Jangan mengubah body ratio atau foot yang sudah baik | Pertahankan volume; inspect flexion, koreksi hanya bila ada regression |

Setiap still yang terlihat dalam percakapan ditinjau menurut pose/detail;
salinan identik tidak dihitung sebagai bukti independen. Hugging/raised-hand
menegaskan panel siku sebagai boundary vinyl lembut. Torso tetap interpretasi,
bukan FILM-CONFIRMED. Tidak ada reference rear terkalibrasi.

Source V3, detailed, rollback dan lighting spec tidak boleh ditulis ulang.
Output hanya derivative V4 dalam worktree art. Tidak ada animation, runtime,
Voice, Armored, lighting, stage, commit, merge atau push.

## A. Root Causes Terverifikasi

- Color attribute V3 menggelapkan seluruh interior oval, bukan hanya boundary.
  Depth 1 mm pada arm dan 0.4 mm pada torso ikut memberi impresi cekungan.
  AO dan studio tidak diperkuat untuk memperbaikinya.
- Kedua arm tidak memiliki custom split normals, semua face smooth, dan
  Preserve Volume tidak aktif. Jadi masalah panel bukan normal object terbalik
  atau efek DQ yang hilang di GLB.
- Longitudinal edge step di band joint V3 mencapai 35.41 mm; terdapat 3,122
  edge dengan langkah vertikal di atas 20 mm pada arm kiri. Total polygon
  tinggi tidak berarti elbow/shoulder mempunyai edge flow yang cukup.
- Root arm V3 tidak mempunyai bobot Chest. Half-angle helper pada pivot yang
  sama dengan primary menghasilkan bridge yang sempit saat elevasi.
- N-gon hasil local subdivision dapat ditessellasi ulang secara berbeda setelah
  deformation. Triangle luas nol ditemukan pada hasil evaluated walaupun audit
  base mesh lolos. N-gon tersebut kini ditriangulasi secara tetap sebelum morph.
- Blender memperbarui normal dari permukaan evaluated, sedangkan renderer LBS
  membaurkan normal per joint. NORMAL target yang semata dihitung dari rest
  corrective memberikan shading berbeda. Pipeline sekarang membake NORMAL
  corrective yang ditujukan pada pose terkalibrasi, lalu memeriksa hasil GLB.

## B. Geometry dan Skinning

### Panel Vinyl

Inset interior V3 dikembalikan ke permukaan arm/torso. V4 memakai micro-groove
terintegrasi sepanjang boundary, bukan objek oval terpisah atau flat decal.
Depth arm 0.25 mm, torso 0.10 mm. Interior hanya berubah 0.8% dari vinyl base;
boundary arm mempunyai contrast 11%, torso 9%, dengan transisi sempit.
Tidak ada texture bayangan atau cinematic highlight yang dibake.

Fungsi yang sama dipakai secara anatomically mirrored untuk kedua arm dan
kedua sisi torso. Ketebalan, koordinat dan parameter tidak diimprovisasi per sisi.
Boundary torso merupakan interpretasi restrained; bukan klaim ukuran/bentuk
FILM-CONFIRMED. Source V3 tetap tersedia sebagai alternatif sebelumnya.

### Topology dan Sambungan

Refinement hanya menyasar edge longitudinal yang panjang pada band sendi.
Langkah maksimum turun menjadi sekitar 11.95 mm, tanpa global subdivision.
N-gon distabilkan sebelum shape keys sehingga tessellation tidak berubah ketika
pose berubah. Hand/wrist memakai pengisian radial lebar yang kecil, tambahan
palm volume dan smoothing lokal pada transisi thumb/palm/wrist. Tangan tidak
diganti dengan model baru dan tidak diberi anatomi knuckle manusia.

Head, face, chest port, lower abdomen V3, kedua legs dan feet dipertahankan.
Full height dan depth tetap. Head dan leg bounds dicek identik. Arm span netral
bertambah sekitar 1.90 mm total karena menghapus indent panel V3, bukan karena
melebarkan torso atau mengubah body ratio.

### Rig

Tetap 32 joints, 20 nama canonical lama dan 12 tambahan V3. Tidak ada joint baru.
Parent-child relationships tidak berubah. Gunakan nama, jangan fixed joint index.

| Bone / region | V3 | V4 |
| --- | --- | --- |
| UpperArm L/R head | (+-0.29, 0, 1.27) | (+-0.39, 0, 1.34) m |
| Shoulder L/R tail | mengikuti UpperArm head | mengikuti UpperArm head baru |
| ShoulderVolume L/R head | sama dengan UpperArm | (+-0.29, 0, 1.22) m |
| ShoulderVolume orientation | sama dengan UpperArm | tetap sama dengan UpperArm |
| Elbow/Forearm/Hand pivots | V3 | dipertahankan |
| Finger joints | Thumb/Index/Middle/Ring L/R | dipertahankan |

Volume helper berada lebih medial dan rendah dari primary untuk menggerakkan
mass shoulder dengan lebih lembut. Ini deformation joint, bukan exposed hinge.
Chest anchor meningkat secara halus sampai 92% pada root paling atas; helper
dan UpperArm membagi sisa influence. Blend elbow diperluas. Semua deform
weights tetap normalized dengan maksimum empat influences.

Matrices, head/tail, parent dan bounds sebelum/sesudah ada dalam
`reports/bagusmax_3d/white_v4/asset_audit.json`. Inverse bind matrices runtime
harus berasal dari V4, bukan array V3 yang dipakai ulang.

## C. Source Preservation

Worktree `E:\Projects\OpenBagus-3D`, branch `feat/bagusmax-3d-art`.
V3 source/GLB, detailed source/GLB, rollback, dan `WHITE_LIGHTING_SPEC.md`
dicatat SHA-256 sebelum edit dan dicocokkan lagi sesudah production.
Manifest lengkap: `reports/bagusmax_3d/white_v4/asset_hashes.json`.
Tidak ada film still baru yang disalin ke asset distributable atau GLB.

Source V4 disimpan netral, semua corrective weights default 0. Drivers hanya
preview art di Blender; tidak ada Actions, NLA tracks atau animation clips.

## D. Bukti Visual

Semua perbandingan memakai studio, color management, exposure dan kamera
yang sama. Studio signature Detailed dan V3 dibandingkan sebelum render;
V4 tidak mengubah lighting. PNG asli 720x720, bukan hanya thumbnail karakter.

Folder `reports/bagusmax_3d/white_v4/`:

| Sheet | Isi |
| --- | --- |
| `sheet_A_anatomy.png` | Detailed/V3/V4 front, left, right, back, front/rear quarter |
| `sheet_B_elbow_L_isolated.png`, `sheet_B_elbow_R_isolated.png` | Detailed/V3/V4 front, back, outside, inside, quarter; neutral, 60, 130 |
| `sheet_C_torso_waist.png` | torso kiri/kanan, abdomen/waist, side dan hip flexion |
| `sheet_D_shoulder_progression.png` | L/R 0,30,60,90,120,145,160; V3/V4 |
| `sheet_E_elbow_progression.png` | L/R 0,30,60,90,110,130,145; V3/V4 |
| `sheet_F_hands.png` | neutral, point, closed dan hold inspection |
| `sheet_G_full_body.png` | V4 neutral front/side/back/quarter |
| `sheet_H_export.png` | Blender vs independent GLB, termasuk interpolated angles |
| `sheet_H_residuals.png` | perbedaan pada combined/hand poses juga ditampilkan |
| `approval_comparison.png` | ringkasan area keluhan sebelum/sesudah |

Pada sheet B, hanya arm terkait beserta seam asli yang masih visible pada
model tersebut yang ditampilkan. Torso/arm lain disembunyikan di SEMUA versi
agar inside surface dapat diinspeksi. Dedicated torso crops juga menyembunyikan
kedua arm secara identik. Full-body sheets tidak menyembunyikan bagian tersebut.

## E. Acceptance Matrix V3 / V4

PASS berikut berlaku untuk static inspection pada pose yang tercantum, bukan
sertifikasi seluruh ruang gerak atau object contact. V3 memakai status handoff
sebelumnya, didampingi baseline render ulang dengan studio identik.

| Test / kedua sisi bila berlaku | V3 | V4 | Bukti / batas |
| --- | --- | --- | --- |
| S0 | PASS | PASS | Neutral, silhouette dan height dipertahankan |
| S1-S4 | PASS | PASS | Forward elevation 30/60/90 dan side elevation 45; render ulang |
| S5 | LIMIT | PASS | Side elevation 90, bridge shoulder lebih halus |
| S6 | FAIL / UNSUPPORTED | PASS | Test lama side elevation 110; tambahan 120/145 juga diperiksa |
| E0-E3 | PASS | PASS | Flexion 0/30/60/90; panel tetap terikat |
| E4 | FAIL | PASS | Test lama 115; tambahan 110/130 diperiksa |
| C1, C2, C4, C6-C10 | PASS | PASS | Tidak terlihat regression bentuk pada snapshot; C2 normal residual tetap dilaporkan |
| C3 | LIMIT | PASS | Kedua shoulder sekitar 63 derajat; bridge lebih halus |
| C5 | LIMIT | LIMIT | Pose kombinasi diperiksa, tetapi soft contact dan grasp belum disertifikasi |
| F1 pointing | LIMIT | LIMIT | Wrist membaik lokal; finger-root pinch masih terlihat |
| F2 closed / F3 hold, L/R | NOT_TESTED | LIMIT | Snapshot baru; satu bone per digit membatasi gesture |
| Side elevation 160 | NOT_TESTED | LIMIT | Diuji, di luar corrective calibration 145 |
| Elbow flexion 145 | NOT_TESTED | LIMIT | Diuji, di luar corrective calibration 130 |
| Panel elbow dan torso | FAIL visual | PASS kandidat | Broad dark interior hilang; thin integrated boundary, sheet B/C |
| Actual OpenBagus runtime / GPU / contact | NOT_TESTED | NOT_TESTED | Di luar scope art, menunggu Antigravity |

Range usable kandidat: side elevation 0..145 dan forward elbow flexion 0..130
degrees, kiri/kanan, dengan helpers dan morph activation di bawah. Tidak
diklaim sebagai arbitrary twist, combined-extreme, atau full overhead 180.
Seluruh 66 static snapshots diulang; tidak ada near-zero triangle dalam metrik
evaluated kedua arm. Ini tidak menggantikan collision testing.

## Corrective Morph Contract

Alternatif A (pivot dan weights) dan B (edge flow + helpers) memperbaiki base
tetapi belum menyelesaikan high elevation/deep flexion. Alternatif C diterapkan
sebagai pose-space corrective terlokalisasi. Tidak ada DQ atau Bendy Bone
yang disamarkan sebagai native glTF LBS.

| Target, masing-masing L/R | Mesh | Input | Default / range |
| --- | --- | --- | --- |
| Shoulder_90 | White_Arm_L/R | outward side elevation | 0; naik 60..90, turun 90..145 |
| Shoulder_145 | White_Arm_L/R | outward side elevation | 0; naik 90..145 |
| Elbow_90 | White_Arm_L/R | forward elbow flexion | 0; naik 50..90, turun 90..130 |
| Elbow_130 | White_Arm_L/R | forward elbow flexion | 0; naik 90..130 |

Ada empat targets per arm, delapan total. Setiap target mempunyai POSITION
dan NORMAL yang benar-benar diekspor; ini bukan sekadar nama shape key.
Affected vertex counts dan maximum rest delta tercantum per target dalam audit.
Nama mesh GLB aktual adalah `White_Arm_L.002` dan `White_Arm_R.002`; suffix
object exporter bukan bagian dari nama joint atau corrective activation.

Posed section memakai kurva dengan boundary dan tangent yang sesuai, kemudian
di-bake kembali melalui inverse LBS ke rest-space morph. Inner elbow compression
dibatasi radius kelengkungan agar permukaan tidak melipat terbalik. NORMAL
target dibake untuk jalur rigid per-joint LBS. Geometry pipeline melakukan
repack accessor/buffer dengan parser terstruktur; tidak memodifikasi GLB V3.

### Rumus Aktivasi

`clamp(x)` berarti membatasi x ke 0..1. Semua sudut berikut dalam degrees.

```text
uS = clamp((elevation - 60) / 30)
vS = clamp((elevation - 90) / 55)
Shoulder_90 = uS * (1 - vS)
Shoulder_145 = vS

uE = clamp((flexion - 50) / 40)
vE = clamp((flexion - 90) / 40)
Elbow_90 = uE * (1 - vE)
Elbow_130 = vE
```

Sudut adalah delta dari rest, bukan quaternion node absolut. Dengan `s=+1`
untuk L dan `s=-1` untuk R, quaternion unit pada hemisphere `w>=0`:

```text
qDelta = inverse(primaryRestLocal) * primaryCurrentLocal
qWorldRest = primaryRestAbsolute * qDelta * inverse(primaryRestAbsolute)
elevation = degrees(2 * atan2(max(0, -s*qWorldRest.y), abs(qWorldRest.w)))
flexion = degrees(2 * atan2(max(0, -qWorldRest.x), abs(qWorldRest.w)))
```

Komponen rumus sudut memakai frame karakter Blender Z-up. Bila menghitung dari
glTF Y-up, quaternion vector kembali ke frame tersebut sebagai `(x,-z,y)`;
w tidak berubah. Jangan memakai world-Y runtime sebagai elevation axis tanpa
konversi ini. Ini side elevation dan elbow forward flexion, bukan arbitrary
twist/extension solver. Aktivasi di luar range uji tidak disertifikasi.

Empat helpers V3 tetap half-angle dari primary, dengan parent sibling:
ShoulderVolume parent Shoulder; ElbowVolume parent UpperArm. Dalam frame runtime
yang konsisten, `D=R*qDelta*inverse(R)`,
`helperDelta=inverse(H)*slerp(identity,D,0.5)*H`, dengan R/H absolute rest
orientations primary/helper. `helperNode=helperRestLocal*helperDelta`.

Antigravity mengatur primary, helpers dan morph weights; asset tidak berisi
controller. Morph POSITION/NORMAL diterapkan sebelum ordinary LBS. NORMAL
targets tidak boleh dibuang. Semua joint dalam pengujian rigid, scale 1.
Re-export Blender manual tanpa production pipeline kehilangan normal-target
pose bake dan tidak setara dengan GLB handoff ini.

## F. Export Verification

`gltf_skinning.py` membaca GLB JSON/BIN, strided/normalized/sparse accessors,
node hierarchy, joint transforms, inverse binds, JOINTS_0/WEIGHTS_0, dan morph
deltas. Evaluasinya NumPy, tanpa Blender Armature modifier atau glTF reimport.
Blender dipakai hanya sebagai intended surface dan studio untuk menampilkan
geometry hasil perhitungan independen tersebut.

Correspondence dibuat sekali dari vertex rest, lalu vertex yang sama dibandingkan
di setiap pose. Ini bukan nearest surface search pada posed model yang dapat
menyembunyikan pergeseran titik. Eighteen pose checks mencakup kedua shoulders
90/120/145, kedua elbows 60/90/110/130, S0, C2, C5 dan F1.

Independent results dan CPU evaluation samples ada di `independent_skinning.json`.
Normal residual tidak disembunyikan: anchor normals sangat dekat, tetapi
interpolated/combined/finger poses dapat berbeda secara lokal dari normal yang
direkonstruksi Blender. Sheet H/H-residuals menunjukkan hasil aktual.

Hasil final: 18/18 positional checks PASS, maximum corresponding-vertex error
0.010173 mm terhadap Blender. Tidak ada arm normal difference di atas 90 degrees
pada sampel shoulder/elbow independen. Normal tidak pixel-identical: pada
shoulder 120 maximum residual sekitar 25.23 degrees; pose antara anchor dan
pose kombinasi tetap mempunyai residual lokal. Source tersimpan diverifikasi
memiliki 0 Actions, 0 NLA tracks, pose angle 0 dan corrective weights 0.
Khronos final: 0 errors, 0 warnings, 13 infos UNUSED_OBJECT untuk unused UV.

Referensi kontrak:
[glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html),
[Khronos normal skinning](https://github.com/KhronosGroup/glTF-Sample-Renderer/blob/main/source/Renderer/shaders/animation.glsl),
[Three.js rigid skin normals](https://github.com/mrdoob/three.js/blob/dev/src/renderers/shaders/ShaderChunk/skinnormal_vertex.glsl.js).
Blender manual URL yang diminta tidak dapat dibaca melalui web tool; tidak
diklaim berhasil diakses. API dan exporter Blender existing diperiksa lokal.

## G. Performance dan Geometry

Statistik canonical berasal dari `glb_structure.json`, bukan angka baseline
yang diasumsikan. `khronos_validation.json` berasal dari official validator
yang sudah tersedia; tidak ada install software baru.

| Statistik aktual | V3 | V4 |
| --- | --- | --- |
| Triangles | 163,108 | 216,400 |
| Meshes / materials / joints | 13 / 5 / 32 | 13 / 5 / 32 |
| GLB bytes | 5,953,660 | 10,810,532 |
| Exported vertices / draw primitives | baseline tidak diulang di sini | 110,510 / 13 |
| Morph targets | 0 | 8, POSITION + NORMAL |
| Maximum vertex influences | 4 | 4 |
| Animation clips | 0 | 0 |
| Base geometry buffer bytes | baseline tidak diulang di sini | 7,954,208 |
| Morph buffer bytes | 0 | 2,825,872 |

Tambahan 53,292 triangles (+32.67%) berasal dari refinement lokal band sendi
dan boundary panel, bukan subdivision seluruh badan. Ukuran GLB naik terutama
karena topology lokal dan delapan sparse morph dengan NORMAL corrective.
Ini tradeoff fidelity, bukan klaim optimisasi ukuran. CPU NumPy evaluation
median 32.76 ms, minimum 27.89, maksimum 39.36, lima samples seluruh asset;
bukan pengukuran GPU atau rekomendasi menjalankan NumPy di runtime.

`pose_metrics.json` dan `baseline_pose_metrics.json` mencatat volume dan
near-zero triangles pada seluruh 66 static poses. Volume bukan collision
certificate atau pengukuran tekanan fisik. Inflatable compression sengaja
terjadi pada deep flexion; tidak diklaim mempertahankan volume 100%.
Contoh ratio volume arm kiri terhadap neutral: shoulder 30/60/90/120/145
adalah 1.025/1.055/1.008/0.975/0.930; elbow 30/60/90/110/130 adalah
0.994/0.967/0.897/0.870/0.849. Angka ini memperlihatkan residual expansion
dan compression, bukan pressure-conserving simulation.

CPU NumPy timing bukan GPU skinning time atau FPS OpenBagus. Runtime loader,
frame time, GPU skinning, VRAM dan object-contact workflows: NOT_TESTED.
Tidak ada renderer changes untuk memperoleh angka benchmark.

## H. Batasan

- Torso seam adalah interpretasi artistik; tidak ada rear reference terkalibrasi.
- Finger controls masih satu bone per digit. Closed-hand/object-holding penuh
  belum merupakan hand rig multi-phalange atau grasp/contact solver.
- Normal residual pada intermediate poses tidak sama dengan kesalahan posisi
  vertex. Keduanya dilaporkan terpisah; shader tidak diklaim pixel-identical.
- Tidak ada all-pose collision certification atau runtime application approval.
- GATE B NOT STARTED. Screen-space lighting dan lighting spec tidak diubah.

## I. File dan Reproduksi

Created:

- `assets/bagusmax/source/bagusmax_white_anatomy_v4.blend`
- `assets/bagusmax/runtime/bagusmax_white_anatomy_v4.glb`
- `tools/bagusmax_asset_pipeline/refine_white_deformation.py`
- `tools/bagusmax_asset_pipeline/gltf_skinning.py`
- `reports/bagusmax_3d/white_v4/`
- `docs/bagusmax_3d/WHITE_ANATOMY_V4_HANDOFF.md`

SHA-256 kandidat final:

```text
bagusmax_white_anatomy_v4.blend
de444488d02f27ded4445c5ac426ae306857a65b9a52789f8e0ba0a9bed340bb
bagusmax_white_anatomy_v4.glb
239d72a0392e704c859ea4436fee220b758781169e6b2ed64a4ff9d39e7df608
```

Modified:

- `review_white_recovery.py`: V4 review option, sheets, actual stats/hashes;
  default V3 workflow dipertahankan.
- `review_white.py`: optional contact-sheet cell size; default tetap sama.

Production command memakai Blender existing:

```text
blender --background --factory-startup --python tools/bagusmax_asset_pipeline/refine_white_deformation.py
python tools/bagusmax_asset_pipeline/review_white_recovery.py --v4
```

`--after-only` menggunakan baseline images dan studio signature yang sudah
diverifikasi ketika tidak ada perubahan baseline. `--verify-only` tidak
menulis ulang source, hanya mengevaluasi export dan render pembuktiannya.
Tidak ada stage, commit, merge atau push. Tidak ada branch/remote change.

## J. Approval

Persetujuan visual diminta pada panel, shoulder/deep-elbow shape dan batas
range yang didokumentasikan. Approval ini tidak sama dengan persetujuan
animation system, companion runtime, voice integration atau Lighting Gate B.
