# BAGUSMAX Armored V1 Acceptance Report

Status: **REVIEW_REQUIRED / REVISION_REQUIRED for deep elbow clearance**. Tidak production-ready. STOP untuk visual review; tidak lanjut runtime, animation atau lighting.

## A. Baseline Preserved

White/rollback/legacy/lighting protected files: PASS. Lihat preservation_before.json / preservation_after.json.

White V4.1 source SHA-256: `bca6b53329acb61b89f107dc610e1451ebe88d4ba3fa2ee5606f6915b1849f07`.
White V4.1 GLB SHA-256: `9ec223bb6ecd563437ee17c2b7a20cdd74a9b10d7f98a74e0d1150bb66e9569b`.

## B. New Armor Construction

124 rigid armor geometry parts, 51 assembly/mechanical controls, existing 32-joint rig. Chest/collar/flanks, helmet, 4 abdominal bands, pauldrons, medial-open C-shell upperarms, elbow bearings, gauntlets/inlays, gloves, pelvis/legs/boots, rear pack dan two-hinge wings. Modular geometry tidak di-skin menjadi rubber.

## C. Visual Reference Fidelity

Interpretasi film-inspired, bukan measured film reconstruction. Semua 15 original references diindeks read-only. Folded wings LOW confidence. White skeleton/head constraints menyebabkan proporsi berbeda dari sebagian toy/flight references. Tidak ada pixel film dalam GLB/source/textures atau PNG model review.

![Neutral review](../../reports/bagusmax_3d/armored_v1/comparison_sheet.png)

## D. Modular Assembly

Part names, pivots, bounds, material IDs, parents, local bind, start/target dan visibility/animation/LOD groups berasal dari actual GLB. Offset diterapkan pada assembly root saja; child parts mewarisinya.

## E. Transformation Concept

Curved deterministic 3.4-second phase specification dan disposable static previews. Repeated .40/.70/.40 serta neutral return PASS. White coverage dan clearance data tersedia, tetapi continuous path collision/pop-free occlusion belum lulus integrasi.

![Assembly](../../reports/bagusmax_3d/armored_v1/assembly_preview.png)

## F. Rig And Articulation

31 independent GLB rigid-transform/vertex probe evaluations: PASS; maximum error 0.001237 mm. Original 32-joint rest comparison: PASS. Neutral reimport: PASS.

Shoulder samples kiri/kanan sampai 145 bersih pada selected pairs. Elbow 0/45/90 bersih; **110/120/130 FAIL** upperarm/forearm surface overlap. Jangan mengintegrasikan deep elbow atau menyebutnya supported. Individual hand contact, full lower-body envelope dan seluruh swept pairs belum disertifikasi.

Independent render memakai geometry/matrices dari GLB pada camera/studio sama. Diagnostic baked mesh normals dihitung ulang oleh Blender; parity shader OpenGL dan GPU normal pipeline aplikasi **NOT_TESTED**.

![Export verification](../../reports/bagusmax_3d/armored_v1/export_verification.png)

## G. Runtime Integration Contract

Lihat ARMORED_V1_ASSEMBLY_CONTRACT.md dan ARMORED_V1_RUNTIME_HANDOFF.md. Canonical assets berada di assets/bagusmax/armor/. Tidak ada IPC handler, controller, companion renderer, ASR/TTS, voice atau data-provider edit. GLB menyertakan head/face; hindari duplicate face saat memuat White bersama armor.

## H. Performance

| Measurement | DESKTOP_RUNTIME | QUALITY |
|---|---:|---:|
| Triangles | 183,676 | 246,640 |
| Exported vertices | 92,292 | 123,774 |
| Meshes / draw primitives | 128 | 128 |
| Materials | 7 | 7 |
| GLB bytes | 3,419,872 | 4,288,120 |
| Geometry buffer bytes | 3,292,052 | 4,167,416 |
| Animation clips | 0 | 0 |
| Morph targets in armor GLB | 0 | 0 |

Khronos desktop: 0 errors / 0 warnings / 4 infos. Quality: 0 errors / 0 warnings. Texture count/memory: 0. Max skin influences on face: 1; armor rigid, 0 skin influences. Source includes original White corrective keys plus default-zero clearance on its private copy; these are not armor GLB morphs.

Sampled quality-to-desktop surface deviation max 0.4664 mm, not a Hausdorff bound. Median NumPy CPU full geometry evaluation 11.058 ms on execution host; includes decoded buffers/array allocation, **not runtime FPS**. GLB parse 12.561 ms, not GPU upload.

Geometry audit: 0 nonmanifold edges across armor parts; 0 degenerate exported triangles. Runtime FPS, VRAM/RAM and OpenGL behavior **NOT_TESTED**. 128 draw primitives remain a performance risk pending integration.

## I. Known Imperfections

- Deep elbow plate intersection remains. Limit candidate to tested 0/45/90 samples until revised; no continuous safe-envelope guarantee.
- Shape/fidelity, helmet scale, C-shell medial treatment, hand contact and folded wing design need visual approval.
- White compression/index masks are assembly data, not a completed occlusion solution. Motion pop/cancel/hidden-window behavior require Antigravity integration tests.
- Selected critical BVH pairs are not exhaustive. One leg-step and head samples do not certify every hip/knee/neck pose.
- No public redistribution rights cleared for the film-inspired character or original film references.

## Acceptance Matrix

| Test | Status | Evidence / Limitation |
|---|---|---|
| T01 | PASS | Original White, rollback, legacy Armored dan lighting spec SHA-256 tidak berubah |
| T02 | PASS | 124 armor parts dan 51 controls dapat dialamatkan melalui actual exported node IDs |
| T03 | LIMIT | Silhouette 4 arah tersedia; proporsi kepala/leg mengikuti White dan fidelity film belum disetujui user |
| T04 | LIMIT | Helmet putih/merah terbaca; head turn/nod diuji, full helmet/face contact certification belum lengkap |
| T05 | PASS | Chest/collar/flank berketebalan dan 4 front/rear segmented purple bands tersedia |
| T06 | LIMIT | Shoulder 0/30/60/90/120/145 kiri-kanan bersih untuk selected critical pairs; bukan full swept self-collision certification |
| T07 | LIMIT | Elbow 0/45/90 bersih; 110/120/130 FAIL upperarm/forearm overlap. Deep flexion belum usable |
| T08 | LIMIT | Relaxed/fist/point dan existing finger anchor tests tersedia; seluruh contact/holding poses belum diuji |
| T09 | LIMIT | Neutral dan satu leg-step sample tersedia; full hip/knee/ankle envelope belum disertifikasi |
| T10 | PASS | Default folded wings dan hinges bertahan setelah export/reimport; desain folded merupakan interpretasi |
| T11 | PASS | Deployed dan partial wings terhubung secara rigid pada dua hinge per sisi; selected critical pairs tidak beririsan |
| T12 | PASS | Actual start/target matrices; progress berulang menghasilkan transforms sama |
| T13 | LIMIT | Reverse transforms dan neutral reset exact; coverage occlusion/pop sepanjang motion masih NOT_TESTED |
| T14 | PASS | Actual GLB hierarchy, independent transformed geometry dan neutral reimport |
| T15 | PASS | 7 material PBR diekspor; tidak ada texture atau permanent flame |
| T16 | PASS | 32 existing White joints dan global rest matrices cocok |
| T17 | PASS | Matched neutral/details/assembly/pose/export review images tersedia, tidak berarti user approval |
| T18 | LIMIT | Triangle/vertex/material/node/buffer/CPU metrics diukur; runtime FPS/VRAM NOT_TESTED |
| T19 | PASS | Hanya additive 3D art changes; no runtime/Voice/Data/lighting edits |
| T20 | PASS | Manifest per-node, articulation formulas, visibility contract dan event specification tersedia; controller tidak dibuat |

## J. Git And Exact Files

Branch `feat/bagusmax-3d-art`; work remains untracked/uncommitted. No stage, commit, merge or push. Previous White and legacy Armored candidates remain unchanged. New canonical implementation: `tools/bagusmax_asset_pipeline/build_armored.py` and `review_armored.py`. New source/runtime/armor data and explicit user-requested art docs/reports only. Exact generated files are listed in `reports/bagusmax_3d/armored_v1/deliverable_inventory.json`.

## K. Visual Approval

Review neutral four directions, helmet/hand details, folded/deployed wings and matched export sheet. Mohon tentukan persetujuan arah visual atau koreksi proporsi. **Deep elbow limitation tetap memerlukan revisi meskipun arah visual disetujui.** Tidak ada tahap runtime atau lighting yang dimulai.
