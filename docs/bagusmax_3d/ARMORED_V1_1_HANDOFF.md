# BAGUSMAX Armored V1.1 Handoff

Status: **REVIEW_REQUIRED**. Kandidat refinement lokal, bukan production-ready. STOP setelah paket ini; menunggu visual approval. Tidak ada perubahan runtime, animasi atau lighting.

## A. Verified Root Causes

- Upper-arm C-shell dan bibir proksimal forearm menyapu volume yang sama mulai sekitar 100 derajat. Parenting rigid utama benar; ini bukan kegagalan skin weights. Forearm distal slide saja tidak cukup untuk ukuran kedua shell.
- Elbow socket V1 mengikuti seluruh Forearm, sehingga cup tidak membagi sudut antarsegmen. Liner shoulder V1 ikut upper-arm stroke dan mendekati chest/collar pada elevation tinggi.
- Audit pasangan lebih luas menemukan upperarm/pauldron, socket/pauldron, dan forearm/wrist/palm terhadap pauldron pada pose gabungan. Klaim V1 pada selected pairs tidak mewakili envelope gabungan penuh.
- BVH mendeteksi perpotongan permukaan, bukan kedalaman penetrasi atau seluruh containment. Fixed mating hanya dikecualikan untuk pasangan co-moving yang eksplisit. HIDDEN_INTERNAL berarti sampel ray terhalang, bukan bukti semua sudut pandang bersih. Diagnosis setiap pasangan, kategori penyebab 1..8, pose dan gambar: intersection_diagnosis.json.

![Actual contact diagnostic](../../reports/bagusmax_3d/armored_v1_1/contact_diagnostic.png)

## B. Mechanical Changes

Forearm dan purple inlay asli dipotong hanya di sweep upper-arm 0..130 setiap 5 derajat (elevation 0/145), dengan margin cutter nominal 4 mm, bukan minimum air gap terukur. Bagian permukaan merah yang dipisahkan menjadi articulated inner guard, bukan mesh filler untuk menutupi clipping. Rim bevel lokal 1.5 mm; trimming guard memakai occupied shell aktual dan solver Manifold, toleransi tepi 0.5 mm, smoothing lokal cut vertices, lalu allowance guard tambahan 0.7 mm untuk kontak intermediate 105 derajat. Tidak ada global subdivision.

Cup/guard rigid dipasang ke existing ElbowVolume_L/R, bukan skin elastis. Cup diberi dome lokal; shoulder liner diperkecil dan dipasang ke pauldron. Joint dasar White tidak berubah. Forearm, gauntlet, wrist dan finger control tetap terpisah.

## C. V1 Versus V1.1

Semua pasangan gambar memakai pose, kamera, skala, material dan studio diagnostik yang sama. Tidak ada film pixels di aset atau PNG ini.

![Elbow left](../../reports/bagusmax_3d/armored_v1_1/elbow_L_comparison.png)
![Elbow right](../../reports/bagusmax_3d/armored_v1_1/elbow_R_comparison.png)
![Neutral](../../reports/bagusmax_3d/armored_v1_1/neutral_comparison.png)

## D. Elbow Clearance Matrix

Status mempertimbangkan seluruh pasangan yang diuji, bukan hanya upperarm/forearm. FAIL = exposed sampled surface crossing; LIMIT = hidden or unresolved contact; PASS = no non-mating BVH surface crossing in this tested pose.

| Pose | V1 local elbow | V1.1 local elbow | V1.1 all tested pairs |
|---|---|---|---|
| elbow_L_0 | PASS | PASS | FAIL |
| elbow_L_30 | PASS | PASS | FAIL |
| elbow_L_60 | PASS | PASS | FAIL |
| elbow_L_90 | PASS | PASS | FAIL |
| elbow_L_100 | FAIL | PASS | FAIL |
| elbow_L_110 | FAIL | PASS | FAIL |
| elbow_L_120 | FAIL | PASS | FAIL |
| elbow_L_130 | FAIL | PASS | FAIL |
| elbow_R_0 | PASS | PASS | FAIL |
| elbow_R_30 | PASS | PASS | FAIL |
| elbow_R_60 | PASS | PASS | FAIL |
| elbow_R_90 | PASS | PASS | FAIL |
| elbow_R_100 | FAIL | PASS | FAIL |
| elbow_R_110 | FAIL | PASS | FAIL |
| elbow_R_120 | FAIL | PASS | FAIL |
| elbow_R_130 | FAIL | PASS | FAIL |

## E. Shoulder And Combined Matrix

| Pose | V1 | V1.1 | Exposed V1.1 pairs |
|---|---|---|---:|
| neutral | FAIL | FAIL | 6 |
| shoulder_L_0 | FAIL | FAIL | 6 |
| shoulder_L_45 | FAIL | FAIL | 6 |
| shoulder_L_90 | FAIL | FAIL | 5 |
| shoulder_L_120 | FAIL | FAIL | 6 |
| shoulder_L_145 | FAIL | FAIL | 8 |
| combined_L_S45_E90 | FAIL | FAIL | 6 |
| combined_L_S90_E110 | FAIL | FAIL | 8 |
| combined_L_S90_E130 | FAIL | FAIL | 11 |
| combined_L_S120_E110 | FAIL | FAIL | 11 |
| combined_L_S145_E90 | FAIL | FAIL | 9 |
| forward_L | FAIL | FAIL | 7 |
| inward_L | FAIL | FAIL | 7 |
| near_chest_L | FAIL | FAIL | 6 |
| shoulder_R_0 | FAIL | FAIL | 6 |
| shoulder_R_45 | FAIL | FAIL | 6 |
| shoulder_R_90 | FAIL | FAIL | 5 |
| shoulder_R_120 | FAIL | FAIL | 6 |
| shoulder_R_145 | FAIL | FAIL | 8 |
| combined_R_S45_E90 | FAIL | FAIL | 6 |
| combined_R_S90_E110 | FAIL | FAIL | 8 |
| combined_R_S90_E130 | FAIL | FAIL | 11 |
| combined_R_S120_E110 | FAIL | FAIL | 11 |
| combined_R_S145_E90 | FAIL | FAIL | 9 |
| forward_R | FAIL | FAIL | 7 |
| inward_R | FAIL | FAIL | 7 |
| near_chest_R | FAIL | FAIL | 6 |
| wings_partial | FAIL | FAIL | 6 |
| wings_open | FAIL | FAIL | 6 |

5-degree out-and-back elbow and shoulder sweeps: intermediate_angle_sweep.json. Local elbow result: intermediate_elbow_clearance.json. Raw contacts retained, not silently waived. Same-angle return matrices are checked; no motion/animation authored. This is discrete sampling, not proof for every real-valued angle.

![Combined](../../reports/bagusmax_3d/armored_v1_1/combined_comparison.png)

## F. Modular Manifest And Articulation Contract

Canonical candidate data: assets/bagusmax/armor/v1_1/armor_assembly_manifest.json and armor_attachment_map.json. Every part has stable ID, actual exported parent/local rest transform, attachment point, White mount joint, installed state, dependencies and control mapping. Original IDs retained; new guard IDs are additive. Matrices are column-major glTF meters, Y-up, +Z forward, +X anatomical left. No Blender driver or constraint is assumed exported.

Let E=abs(UpperArm anatomical rest-axis Y delta) in degrees, B=abs(Forearm rest-axis X delta) in degrees, s=+1 left/-1 right; clamp means [0,1]. These are absolute evaluations from exported neutral, never accumulated deltas:

```text
f = clamp((B-55)/75)
c = clamp((E-60)/85)
r = clamp((E-30)/60) * f
ASM_FOREARM translation += (0,0,-0.055*f) meters
ASM_UPPERARM translation += (0,0,0.105*f*(1-0.6*c)) meters
ElbowVolume helper rotation = 0.5 * Forearm anatomical delta
ASM_ELBOW extra rotation X = -0.10*B degrees (total flexion phase 0.60)
ASM_PAULDRON rotation Y = -s*0.64*E degrees
ASM_PAULDRON translation += (s*(0.07*sin(E/2)+0.06*r),0.10*r,0.025*sin(E)) meters
```

Formula vectors are Blender anatomical rest axes (+Z up, -Y forward). Convert with B=[[1,0,0],[0,0,1],[0,-1,0]] to glTF and conjugate rotations into the exported local rest basis. Trig uses radians. Apply offsets on control nodes only; child parts inherit. Runtime implementation belongs to Antigravity and is NOT included. Tests evaluate these exact rules independently from GLB.

## G. Wing Rest Geometry

Original two-hinge wings and meshes unchanged. Default folded: root Y=s*89 degrees, tip Y=-s*154 degrees; deployed progress1, partial0.5 are disposable static inspections. No opening clip. wing_clearance.json checks main/tip against helmet, pauldron and backpack at all three static states. Complete continuous wing swept-volume certification is NOT_TESTED.

![Wing states](../../reports/bagusmax_3d/armored_v1_1/wing_states.png)
![Exploded](../../reports/bagusmax_3d/armored_v1_1/modular_exploded.png)

## H. Export Validation

Khronos: 0 errors / 0 warnings. 45 independent exported-joint/control/probe evaluations; max position error 0.001237 mm. Neutral round-trip checks every rigid vertex bidirectionally. All 32 original rest and inverse-bind matrices compared with White. Rendered GLB geometry uses exported buffers/matrices at the same pose/camera; normals recalculated for diagnostic rendering, not GPU shader parity certification.

![Export](../../reports/bagusmax_3d/armored_v1_1/export_verification.png)

| Metric | V1 | V1.1 |
|---|---:|---:|
| Triangles | 183,676 | 200,782 |
| Exported vertices | 92,292 | 108,304 |
| Meshes | 128 | 130 |
| Draw primitives | 128 | 132 |
| Materials | 7 | 7 |
| Morph targets in armor GLB | 0 | 0 |
| Animation clips | 0 | 0 |
| GLB bytes | 3,419,872 | 3,909,556 |
| Geometry buffer bytes | 3,292,052 | 3,778,980 |
| Degenerate triangles | 0 | 0 |

126 armor parts, 51 control nodes, 32 joints. Rigid armor has no blended weights; skinned head/face maximum 1 influence. Local split/clearance topology adds 17,106 triangles (9.31%); no global subdivision. Source nonmanifold edges: 0. See per-object audit for exact locations.

## I. FPS / VRAM

**NOT_TESTED**. File and buffer bytes are measured, not GPU allocation. No renderer changes or invented 60 FPS claim.

## J. Foundation And Rollback Integrity

SHA-256 preservation: **PASS**. All original White, V1, legacy rollback, lighting spec and V1 handoff/manifest files checked before/after.

A wrong captured default export path briefly replaced V1 GLB during refinement. It was restored byte-identically from untouched V1 saved source through the original exporter; the exporter now rejects any non-candidate path in revision mode. Recovery hash verified against the pre-edit baseline, not a newly invented baseline.

```text
assets/bagusmax/source/bagusmax_white_anatomy_v4_1.blend
bca6b53329acb61b89f107dc610e1451ebe88d4ba3fa2ee5606f6915b1849f07
assets/bagusmax/runtime/bagusmax_white_anatomy_v4_1.glb
9ec223bb6ecd563437ee17c2b7a20cdd74a9b10d7f98a74e0d1150bb66e9569b
assets/bagusmax/source/bagusmax_armored_v1.blend
95803df025b5ea4036dd5c5d66995922a79c7c3821a0760ae73e3564a68cb646
assets/bagusmax/runtime/bagusmax_armored_v1.glb
2178e34f25a74c363dd518b82a5ebbef3ec529b9799f1a545dd20885fb78ba4b
```

## K. Git And Exact Files

No stage, commit, merge, push, branch change or other-worktree edit. Existing art folders were already untracked. Only White-related read-only inspections and Armored art pipeline/candidate outputs are involved. deliverable_inventory.json records exact candidate files and SHA-256. Git status captured separately in git_status.txt.

## L. Review Package And Remaining Limits

| Criterion | Status | Evidence |
|---|---|---|
| Elbow and shoulder clearance | FAIL | See per-pose clearance_matrix.json; no silent rotation clamp |
| Local elbow 5-degree sweep | PASS | Both arms 0..130; excludes shoulder and intentional co-moving mating |
| Static wing clearance | PASS | Folded / partial / open against helmet, pauldron and backpack; not full continuous swept volume |
| Rigid modular articulation | PASS | 126 armor parts; all original IDs retained; 51 controls |
| GLB structural validation | PASS | {'numErrors': 0, 'numWarnings': 0, 'numInfos': 4, 'numHints': 0, 'truncated': False} |
| Independent GLB transforms | PASS | 45 poses; max 0.001237 mm |
| Neutral round-trip | PASS | All rigid vertices, both directions |
| White rig contract | PASS | 32 joint names, parents, rest and inverse bind matrices |
| Geometry integrity | PASS | 0 degenerate triangles; 0 nonmanifold edges |
| White / V1 / rollback preserved | PASS | SHA-256 equality |
| Neutral return / unchanged studio | PASS | Folded wings, relaxed hands, original diagnostic studio |
| No animation clips | PASS | Static disposable inspections only |
| Runtime FPS / VRAM | NOT_TESTED | No renderer or companion changes |
| Visual approval | NOT_TESTED | User review required; no production-ready claim |

Remaining exposed intersections (not hidden or relabelled):
- neutral: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_0: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_30: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_60: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_90: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_100: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_110: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_120: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_L_130: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_L_0: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_L_45: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_L_90: ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_L_120: ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_L_145: ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_ELBOW_SOCKET_L / ARMOR_PAULDRON_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_L / ARMOR_CHEST_FLANK_L, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_L_S45_E90: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_L_S90_E110: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_UPPERARM_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_L_S90_E130: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_FOREARM_L / ARMOR_PAULDRON_L, ARMOR_UPPERARM_L / ARMOR_CHEST_FRONT, ARMOR_UPPERARM_L / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_L / ARMOR_CHEST_FLANK_L, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_L_S120_E110: ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_ELBOW_SOCKET_L / ARMOR_PAULDRON_L, ARMOR_ELBOW_METAL_L / ARMOR_PAULDRON_L, ARMOR_FOREARM_L / ARMOR_PAULDRON_L, ARMOR_UPPERARM_L / ARMOR_CHEST_FRONT, ARMOR_UPPERARM_L / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_L_S145_E90: ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_ELBOW_SOCKET_L / ARMOR_PAULDRON_L, ARMOR_UPPERARM_L / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_L / ARMOR_CHEST_FLANK_L, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- forward_L: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- inward_L: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_UPPERARM_L / ARMOR_PAULDRON_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- near_chest_L: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_0: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_30: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_60: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_90: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_100: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_110: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_120: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- elbow_R_130: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_R_0: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_R_45: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_R_90: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_R_120: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- shoulder_R_145: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_ELBOW_SOCKET_R / ARMOR_PAULDRON_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_R / ARMOR_CHEST_FLANK_R
- combined_R_S45_E90: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_R_S90_E110: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_UPPERARM_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_R_S90_E130: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_FOREARM_R / ARMOR_PAULDRON_R, ARMOR_UPPERARM_R / ARMOR_CHEST_FRONT, ARMOR_UPPERARM_R / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_R / ARMOR_CHEST_FLANK_R
- combined_R_S120_E110: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_ELBOW_SOCKET_R / ARMOR_PAULDRON_R, ARMOR_ELBOW_METAL_R / ARMOR_PAULDRON_R, ARMOR_FOREARM_R / ARMOR_PAULDRON_R, ARMOR_UPPERARM_R / ARMOR_CHEST_FRONT, ARMOR_UPPERARM_R / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- combined_R_S145_E90: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_ELBOW_SOCKET_R / ARMOR_PAULDRON_R, ARMOR_UPPERARM_R / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR, ARMOR_PAULDRON_R / ARMOR_CHEST_FLANK_R
- forward_R: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- inward_R: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_UPPERARM_R / ARMOR_PAULDRON_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- near_chest_R: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- wings_partial: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR
- wings_open: ARMOR_UPPERARM_L / ARMOR_SHOULDER_RECESS_L, ARMOR_PAULDRON_L / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_L / ARMOR_CHEST_COLLAR, ARMOR_UPPERARM_R / ARMOR_SHOULDER_RECESS_R, ARMOR_PAULDRON_R / ARMOR_CHEST_FRONT, ARMOR_PAULDRON_R / ARMOR_CHEST_COLLAR

Missing collision tests: full mesh containment, exact signed clearance, contact with all White vinyl vertices, complete finger/hand/body pairs, continuous combined-angle sweep and renderer integration. Neutral guard seam remains uneven and purple inlay boundary needs further local finishing; do not treat it as visually approved. Folded wing interpretation needs human approval. Film references remain external read-only, with no copied pixels in public assets.

Next local repair option, not performed automatically: clearance-profile pauldron underside/medial lip against chest and combined arm sweep, then make the guard rim a regular manufactured split line. No White or global proportion changes, silent rotation clamp or darker shading workaround.

Please review final_neutral.png, elbow_L/R_comparison.png, shoulder_L/R_comparison.png, combined_comparison.png and export_verification.png. **REVIEW_REQUIRED remains until user approval and critical exposed contacts are resolved.** No further stage starts automatically.
