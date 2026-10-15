# White Bagusmax V4.1

Status: REVIEW_REQUIRED. V4 tetap VISUAL_REJECTED / REVISION_REQUIRED.
Kandidat ini bukan persetujuan visual pengguna. GATE B NOT STARTED.

## Baseline dan Scope

Worktree: `E:\Projects\OpenBagus-3D`, branch `feat/bagusmax-3d-art`.
Input langsung adalah source V4, bukan pembangunan ulang dari V3.
Source V4 SHA-256:
`de444488d02f27ded4445c5ac426ae306857a65b9a52789f8e0ba0a9bed340bb`.
GLB V4 SHA-256:
`239d72a0392e704c859ea4436fee220b758781169e6b2ed64a4ff9d39e7df608`.

Baseline aktual: 216,400 triangles, 110,510 exported vertices, 13 meshes,
5 materials, 32 joints, 8 morphs, max 4 influences, 0 clips, 10,810,532 bytes.
Joint names, hierarchy, rest head/tail/matrices, transforms, weights dan actual
morph deltas dicatat sebelum editing dalam `baseline_audit.json`.
Tidak ditemukan non-uniform/negative object scale pada mesh yang diekspor.

Checklist sebelum edit: periksa overlap torso/arm dan cap; periksa crease 145;
hapus deltoid-like ridge tanpa mengubah body ratio; orientasikan rest hand
bersama bind chain; periksa geometry siku 130, bukan hanya material; ulang
intermediate angles dan pose lama; bandingkan GLB menggunakan LBS independen.

## A. Mengapa Shoulder V4 Terlihat Ditempel

Torso dan kedua arm adalah closed shells terpisah. BVH menemukan 552 pasangan
face beririsan pada masing-masing torso/arm. Cap arm tidak merupakan continuous
skin dengan torso. Karena keduanya tidak berbagi vertex/normal, weighted arm
dan rigid torso dapat memperlihatkan socket/crease walaupun GLB valid.

Corrective shoulder V4 hanya memodifikasi arm, dengan maximum rest delta
sekitar 211 mm. Memindahkan arm surface saja tidak membuat torso attachment
ikut mengalir. Wireframe, normals dan weight heatmaps membedakan masalah ini
dari sekadar material atau pencahayaan.

## B. Mesh, Weights dan Morph

Penyebabnya kombinasi konstruksi shell, weight falloff dan corrective field.
Tidak ada inverse-bind mismatch yang terbukti sebagai penyebab utama V4.
V4 juga baru mengaktifkan Shoulder_90 setelah 60 degrees; intermediate
underarm dapat kembali terjepit sebelum corrective bekerja.

## C. Perubahan Spesifik

- Local shoulder-only boolean union membuang internal caps yang beririsan.
  Torso dan arm kini satu connected skin, `White_SoftSkin`. Head, face, port,
  legs dan feet tidak digabung atau dibangun ulang.
- Lower arm dipisahkan sementara pada operand konstruksi agar union tidak
  menghapus seluruh sisi abdomen. Displacement tersebut dikembalikan sebelum
  deformation; bukan offset yang dipakai untuk menyembunyikan gap saat render.
- Root surface direlaksasi lokal. Torso anchor, ShoulderVolume dan UpperArm
  mempunyai spatial falloff yang melewati attachment, bukan berakhir pada cap.
- Existing shoulder targets di-fit terhadap 20/40/60/75/90/120/145 degrees,
  bukan hanya satu gambar endpoint. Aktivasi low-angle diperbaiki.
- Dua `ShoulderForward_90_L/R` ditambahkan setelah uji C4 memperlihatkan ridge
  yang tidak dikoreksi oleh side-elevation targets. Sheet on/off membuktikan
  kebutuhan arah deformasi ini. Tidak ada joint atau polygon tambahan untuknya.
- Existing elbow targets direvisi secara geometris: curved compression,
  localized volume target dan surface relaxation. Warna/material panel V4
  tidak diganti untuk menciptakan ilusi perbaikan.
- Wrist/palm transition direlaksasi lokal sebelum rest orientation diperbaiki.

Dual-quaternion blending dipakai hanya untuk menghasilkan art target offline.
Hasilnya di-invert dan dibake ke POSITION morph. GLB tetap memakai ordinary
linear-blend skinning; tidak bergantung pada Blender Preserve Volume atau DQ
runtime. Tidak ada driver logic yang diklaim ikut diekspor.

## D. Shoulder Bukan Otot Manusia

Cap/deltoid ridge tidak diperbesar. Penyatuan skin dan local relaxation
menghilangkan garis socket netral, sementara medan deformasi membentuk broad
vinyl bridge. Ada residual underarm/neck compression dan sebagian contour
forward yang masih harus dinilai pengguna. Tidak ada klaim matematis G1/G2;
aspirasi G1-like diperiksa secara visual dari empat arah.

## E. Natural Palm-Inward Rest

Geometri hand diputar mirrored sekitar forearm axis: L +90 degrees, R -90
degrees dalam Blender Z-up. Twist di-blend pada z 0.55..0.76 m sehingga elbow
panel dan bending plane tidak diputar. Di bawah wrist, transform penuh berlaku
pada palm/fingers. Hand, Thumb, Index, Middle dan Ring rest bones ditransform
bersama geometri. Forearm/elbow/shoulder primary rest pivots dipertahankan.

Thumb root kini anterior. Basis palm +Y V4, yang ditetapkan dari thumb/finger
handedness, ditransform melalui delta rest Hand matrix. Debug arrow diukur
dari transform tersebut, bukan diset hanya untuk menunjukkan target arah.
Hasil aktual ada di `palm_axes.json` dan `neutral_palm_axis_debug.png`.

Rest ini bukan pose bone sementara atau animation. Semua pose rotations dan
morph default disimpan netral; geometri dan bind sudah memuat orientasi baru.
Gesture lama diuji dalam anatomical axes baru, bukan world-X yang dipaksakan
ke hand yang telah diputar.

## F. Kontrak Export dan Runtime-Neutral Mapping

Tetap 32 joint names dan hierarchy yang sama. Gunakan inverse binds V4.1;
jangan memakai array V4 lagi, khususnya untuk Hand dan digit bones.
Mesh ownership berubah: arm dan torso kini node `White_SoftSkin` dengan semua
targets, bukan target arrays pada dua `White_Arm_*` objects. Mesh data suffix
exporter bukan joint contract. Antigravity belum dimodifikasi.

| Morph names, L/R terpisah | Mesh | Default | Parameter / range | Export |
| --- | --- | --- | --- | --- |
| Shoulder_90_L, Shoulder_90_R | White_SoftSkin | 0 | side elevation 0..145 | POSITION + NORMAL |
| Shoulder_145_L, Shoulder_145_R | White_SoftSkin | 0 | side elevation 90..145 | POSITION + NORMAL |
| Elbow_90_L, Elbow_90_R | White_SoftSkin | 0 | forward elbow 50..130 | POSITION + NORMAL |
| Elbow_130_L, Elbow_130_R | White_SoftSkin | 0 | forward elbow 90..130 | POSITION + NORMAL |
| ShoulderForward_90_L | White_SoftSkin | 0 | forward shoulder 0..90, side gate | POSITION + NORMAL |
| ShoulderForward_90_R | White_SoftSkin | 0 | forward shoulder 0..90, side gate | POSITION + NORMAL |

Actual changed-vertex counts/deltas tersedia per target dalam `asset_audit.json`.
Morph normals dibake ke konvensi rigid per-joint blended normal matrices.
POSITION dan NORMAL diterapkan sebelum LBS. Manual Blender export tanpa normal
bake pipeline tidak identik dengan GLB handoff.
NORMAL targets di-fit terhadap beberapa intermediate poses, bukan hanya
dinormalisasi pada satu anchor. Skin objects parented ke rig di source Blender;
export menempatkan skinned mesh nodes sebagai scene roots dengan world transform
identik. Joint hierarchy dan inverse binds tidak dipalsukan untuk menghapus
validator warning. Perubahan hierarchy ini diuji lagi lewat LBS dan reimport.

Dengan `clamp` membatasi 0..1, E side elevation, F forward shoulder dan B elbow
flexion, semuanya degrees:

```text
uS = (1 - cos(radians(min(90, E)) / 2)) / (1 - cos(pi / 4))
vS = clamp((E - 90) / 55)
Shoulder_90 = uS * (1 - vS)
Shoulder_145 = vS

uF = (1 - cos(radians(min(90, F)) / 2)) / (1 - cos(pi / 4))
ShoulderForward_90 = uF * (1 - clamp((E - 30) / 60))

uB = clamp((B - 50) / 40)
vB = clamp((B - 90) / 40)
Elbow_90 = uB * (1 - vB)
Elbow_130 = vB
```

Sudut bukan node quaternion absolut. Gunakan `qDelta = inverse(restLocal) *
currentLocal`, lalu `q = restAbsolute * qDelta * inverse(restAbsolute)`;
quaternion unit, hemisphere w>=0. Dalam frame Blender Z-up, s L=+1/R=-1:

```text
E = degrees(2 * atan2(max(0, -s*qUpperArm.y), abs(qUpperArm.w)))
F = degrees(2 * atan2(max(0, -qUpperArm.x), abs(qUpperArm.w)))
B = degrees(2 * atan2(max(0, -qForearm.x), abs(qForearm.w)))
```

glTF Y-up quaternion vector kembali ke frame tersebut sebagai `(x,-z,y)`.
Helper semantics V4 tetap: ShoulderVolume parent Shoulder, ElbowVolume parent
UpperArm, masing-masing half-angle primary dalam absolute rest frame.
`helperDelta = inverse(H) * slerp(I, R*qDelta*inverse(R), .5) * H`;
`helperLocal = helperRestLocal * helperDelta`, R/H absolute rest orientations.
Ini kontrak matematika, bukan controller runtime yang dibuat di tugas ini.
Arbitrary twist, negative extension, simultaneous extreme forward/side dan
contact/holding belum disertifikasi.

## G. Elbow 130: Perubahan Geometry Nyata

Target elbow tidak sekadar diwarnai ulang. Curved surface existing dikombinasi
dengan localized volumetric target dan relaxed compression surface, lalu
inverse-LBS dibake kembali. Panel tetap bagian mesh yang sama. Inspect
`elbow_deformation_comparison.png` dan `elbow_panel_integrity.png`, termasuk
0/45/90/110/130/145 degrees kedua sisi. Inner crease masih perlu approval;
tidak diklaim sebagai inflatable pressure simulation atau perfect film match.

## H. Pose Tests, Regression dan Acceptance

70 named static tests diulang, ditambah 66 shoulder sequence snapshots pada
increment 5 degrees (0..160, L/R). Reverse evaluation dibandingkan dengan
pose yang sama setelah neutral reset untuk memeriksa history dependence.
Tidak dibuat timeline keyframes, Actions atau animation clips.

Independent evaluator membaca actual GLB joints, matrices, inverse binds,
weights dan morph accessors. Correspondence dibuat dari neutral sekali,
bukan nearest-surface search pada posed model. Reimport netral diuji terpisah.
Importer membuat Icosphere untuk bone display; widget tersebut bukan asset
GLB dan dikecualikan dari perbandingan skinned meshes, bukan disembunyikan
untuk memperbaiki cacat model.

Hasil final: 28/28 position comparisons PASS dengan maximum error 0.028518 mm
(tolerance 0.1 mm). Neutral reimport maximum surface error 0.000523 mm.
Khronos V4.1: 0 errors, 0 warnings, 11 infos UNUSED_OBJECT untuk unused UV.
V4 juga divalidasi ulang: 0 errors, 0 warnings, 13 infos.
Tidak ada normal error di atas 90 degrees pada shoulder/elbow samples,
C2, S3 dan C4 yang diuji. C5 masih mempunyai 55 affected vertices dengan
normal error di atas 90 degrees; F1 mempunyai 39. Keduanya LIMIT, bukan
pixel-identical export. Sheet morph verification menampilkan residual aktual.

Saved source diperiksa ulang: satu connected skin component, 0 Actions,
0 NLA, semua pose angles 0 dan 10 morph defaults 0. Semua digit groups
mempunyai localized nonzero influence. Palm inward dot L=1.0 dan R sekitar
0.99999994; kedua thumb roots anterior. Head/leg bounds identik dengan V4.
Semua 70 named poses dan 66 incremental snapshots mempunyai 0 near-zero
triangles pada evaluated skin. Reverse order menghasilkan geometry yang sama.

| Kelompok pose lama | V4 technical report | V4.1 revision inspection |
| --- | --- | --- |
| S0 | PASS, visual rejected | palm inward dan continuous neutral attachment; PASS static |
| S1-S4, C1, C4 | PASS | forward correction menjaga attachment; sampled static PASS, visual approval pending |
| S5/S6 L/R | PASS technical | socket diganti skin kontinu; LIMIT untuk final softness approval |
| E0-E4 L/R | PASS technical | posisi GLB PASS; inner compression di 130 tetap LIMIT visual |
| C2/C3 | PASS technical | tidak ada positional failure; C2 NORMAL residual utama diperbaiki |
| C5/F1 | LIMIT | LIMIT tetap, termasuk normal outliers yang dilaporkan |
| C6-C10 | PASS technical | static snapshots diulang, body/head/leg tidak direbuild |
| F2/F3 closed/hold | LIMIT | LIMIT, belum merupakan grasp/contact solver |

| Criterion | Status kandidat | Bukti / batas |
| --- | --- | --- |
| AC01 neutral attachment | PASS static | continuous skin; closeup dan wireframe |
| AC02 shoulder 145 | LIMIT visual | socket terpisah hilang; residual neck/underarm softness perlu approval |
| AC03 no bodybuilder | LIMIT visual | neutral lebih mengalir; forward/combined contour masih perlu penilaian |
| AC04 palm inward | PASS static | rest geometry, rest Hand/digit matrices, palm axes, GLB neutral |
| AC05 mirrored anatomy | PASS transform | mirrored rotations dan thumb anterior; bukan klaim setiap vertex identik |
| AC06 wrist continuity | LIMIT visual | finishing lokal; thumb/wrist notch belum sempurna |
| AC07 organic elbow 130 | LIMIT visual | geometric change nyata, inner compression masih perlu approval |
| AC08 elbow panel | PASS static | boundary tetap menyatu dan terbaca, material V4 tetap |
| AC09 no pose regression | LIMIT | suite diperiksa; tidak ada blanket all-pose collision/visual certificate |
| AC10 exported GLB | PASS targeted / LIMIT C5,F1 | 0/0 Khronos, 28 positional checks; normal residual tidak disembunyikan |
| AC11 neutral after tests | PASS saved rest | source disimpan sebelum disposable poses; defaults 0 |
| AC12 no animation | PASS | 0 clips, 0 Actions/NLA |
| AC13 previous assets | PASS hash | V4, V3, rollback dan asset sebelumnya tidak berubah |
| AC14 lighting | PASS | studio signature/spec tetap; diagnostics bukan Gate B |
| AC15 actual improvement | LIMIT approval | perubahan attachment dan hand jelas; keputusan penerimaan milik pengguna |

Shoulder 160 dan elbow 145 tetap LIMIT, bukan supported range. Forward targets
dikalibrasi sampai 90 degrees. Full range side sampai 145/elbow sampai 130
sudah diuji teknis, tetapi status visual tidak dinaikkan otomatis menjadi PASS.

## I. Statistik dan Berkas

Angka final canonical: `reports/bagusmax_3d/white_v4_1/glb_structure.json`.
Hash sebelum/sesudah: `asset_audit.json`, termasuk source dan GLB kandidat.
Performance CPU NumPy bukan FPS, GPU cost atau VRAM aplikasi; ketiganya
NOT_TESTED. Tidak ada perubahan renderer untuk membuat benchmark.

| Statistik | V4 aktual | V4.1 aktual |
| --- | --- | --- |
| Triangles | 216,400 | 208,032 |
| Exported vertices | 110,510 | 107,307 |
| Meshes / primitives | 13 / 13 | 11 / 11 |
| Materials / joints | 5 / 32 | 5 / 32 |
| Max influences | 4 | 4 |
| Morph targets | 8 | 10 |
| Animation clips | 0 | 0 |
| GLB bytes | 10,810,532 | 18,885,552 |

Triangle count turun 8,368 (3.87%) karena internal cap removal, bukan global
decimation. GLB bertambah sekitar 74.70% karena corrective ownership pada skin
kontinu dan NORMAL/POSITION targets yang lebih luas. Ini tradeoff yang nyata,
bukan optimisasi size. Lima CPU NumPy samples final: median 37.30 ms,
minimum 35.27, maximum 38.67; tidak boleh ditafsirkan sebagai GPU frame time.
Blender exporter masih mencetak dua armature-lookup messages; actual GLB memakai
satu skin/32 joints dan diverifikasi independen. Ini berbeda dari hasil final
Khronos yang 0 warnings. Actual runtime loader/animation controller NOT_TESTED.

SHA-256 final:

```text
bagusmax_white_anatomy_v4_1.blend
bca6b53329acb61b89f107dc610e1451ebe88d4ba3fa2ee5606f6915b1849f07
bagusmax_white_anatomy_v4_1.glb
9ec223bb6ecd563437ee17c2b7a20cdd74a9b10d7f98a74e0d1150bb66e9569b
```

`asset_hashes.json` mencocokkan ulang 12 protected files, termasuk V4, V3,
rollback, Detailed dan lighting spec. Semuanya dipertahankan secara byte-identical.

Created:

- `assets/bagusmax/source/bagusmax_white_anatomy_v4_1.blend`
- `assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb`
- `tools/bagusmax_asset_pipeline/refine_white_attachment.py`
- `reports/bagusmax_3d/white_v4_1/`
- `docs/bagusmax_3d/WHITE_ANATOMY_V4_1_HANDOFF.md`

Modified:

- `review_white_recovery.py`: `--attachment` menyusun V4.1 sheets, overlay,
  private external-reference viewer, actual stats dan official validation.

Review files:

- `shoulder_left_continuity_sheet.png`, `shoulder_right_continuity_sheet.png`
- `shoulder_L_incremental_sequence.png`, `shoulder_R_incremental_sequence.png`
- `shoulder_attachment_closeup.png`, `shoulder_side_silhouette.png`
- `shoulder_weight_diagnostic.png`, `shoulder_wireframe_comparison.png`
- `shoulder_deformation_glb_validation.png`, `morph_verification.png`
- `neutral_hands_front/left/right/back/three_quarter.png`
- `neutral_palm_axis_debug.png`, `neutral_glb_reimport.png`
- `palm_inward_comparison.png`, `full_body_silhouette_overlay.png`
- `elbow_deformation_comparison.png`, `elbow_panel_integrity.png`
- `forward_corrective_justification.png`, `final_neutral_character.png`
- `film_reference_comparison.html`, `approval_comparison.png`

Film comparison adalah private HTML yang merujuk original supplied stills di
Temp, bukan menyalin atau meng-embed film pixels ke repository. Jangan
publish viewer tersebut. Kamera/pose film tidak terkalibrasi; perbandingan
film bersifat kualitatif. Semua V4/V4.1 comparisons memakai kamera/studio sama.

Reproduksi dengan Blender/Python existing:

```text
blender --background --factory-startup --python tools/bagusmax_asset_pipeline/refine_white_attachment.py
python tools/bagusmax_asset_pipeline/review_white_recovery.py --attachment
```

`--after-only` memakai baseline renders yang sudah ada dan tidak berubah.
`--proof-only` memeriksa kandidat tersimpan tanpa re-export. Tidak diperlukan
software/dependency baru. Source builder tidak menulis file V4/V3/rollback.
`--inspect-saved` memeriksa neutral defaults, connected components dan finger
weights dari source tersimpan tanpa menulis ulang asset.

Referensi resmi: [glTF source specification](https://raw.githubusercontent.com/KhronosGroup/glTF/main/specification/2.0/Specification.adoc)
dan [Khronos Validator](https://github.com/KhronosGroup/glTF-Validator).
Blender manual endpoints yang diminta mengembalikan HTTP 402 pada web tool;
API lokal Blender 5.2.2 LTS dan exporter yang terpasang diperiksa langsung.

## J. Approval dan Batas Scope

Review diminta terutama untuk attachment 0..145, natural hanging hands dan
elbow compression. Residual softness, wrist finishing dan combined gestures
tetap LIMIT sampai dinilai; valid GLB tidak berarti visual approved.

Tidak ada animation runtime, Voice, ASR/TTS, financial/data system, Armored,
renderer atau Lighting Gate B yang diubah. Tidak ada stage, commit, merge,
push atau cherry-pick. Pekerjaan berhenti pada paket review ini dan menunggu
visual approval pengguna.
