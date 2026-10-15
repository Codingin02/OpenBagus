# BAGUSMAX Armored V1 Assembly Contract

Status: **REVIEW_REQUIRED**. Ini kontrak data dan evaluator art, bukan implementasi controller aplikasi.

## Data Canonical

- `assets/bagusmax/armor/armor_assembly_manifest.json`: actual GLB nodes, stable IDs, materials, pivots, bounds dan transforms.
- `armor_attachment_map.json`: 32 joint rest matrices, shoulder/forearm/wing semantics.
- `armor_materials.json`: PBR materials yang benar-benar diekspor.
- `armor_transformation_timeline.json`: phase times, easing, reversible path.
- `armor_white_fit.json` / `.bin`: sparse torso clearance dan triangle coverage groups untuk GLB White yang hash-nya tepat.

Manifest dibangun dari hasil export, bukan koordinat placeholder. Setiap part memiliki local transform sendiri; pendekatan assembly diwarisi dari `assembly_node`. **Jangan menerapkan start offset lagi pada child part**, karena akan menggandakan perpindahan. Child part memiliki start/target local matrix sama karena seluruh assembly root yang bergerak.

## Coordinate Dan Attachment

Blender: meter, +Z up, -Y forward, +X anatomical left. glTF: meter, +Y up, +Z forward, +X anatomical left.

```text
B = [[1,0,0], [0,0,1], [0,-1,0]]
p_gltf = B * p_blender
M_gltf = B4 * M_blender * inverse(B4)
world = parent_world * local
```

JSON matrix arrays column-major, vectors sebagai column. Quaternion berurutan **xyzw**, bukan wxyz. Scale default 1; jangan menambahkan transform mirror negatif.

Gunakan actual joint global transforms rig White sebagai parent space. Pada runtime yang memuat dua rig, hubungkan armor anchor ke joint White berdasarkan nama dan matching rest matrix. Jangan mengevaluasi dua skeleton terpisah dengan pose yang berbeda. GLB memuat 32 joint yang sama; tambahan 51 mechanical control nodes bukan deform joints.

Armor plate rigid mengikuti node world matrix. Hanya empat face/head meshes yang memakai skin dengan satu pengaruh per vertex. Tidak ada DQ dependency atau skinned rubber armor. Inverse-bind matrices pada face diverifikasi melalui parser GLB; joint rest matrices dibandingkan dengan original White.

## Primary Assemblies

| Group | Anchor | Fungsi |
|---|---|---|
| `ASM_HELMET` | Head | Rear/crown/chin/face frame/gasket/ears/fins |
| `ASM_CHEST`, `ASM_BACK`, `ASM_BACKPACK` | Chest | Front/collar/flanks, rear, pack/nozzles |
| `ASM_ABDOMEN_1..4` | Spine | Front/rear purple bands dan locks |
| `ASM_PELVIS` | Hips | Pelvis front/rear |
| `ASM_PAULDRON_L/R` | Chest | Secondary shoulder caps dan inlays |
| `ASM_UPPERARM_L/R` | UpperArm_L/R | Rigid C-shell dan shoulder recess |
| `ASM_ELBOW_L/R` | Forearm_L/R | Socket, metal ring dan hub |
| `ASM_FOREARM_L/R` | Forearm_L/R | Gauntlet, inlay, sliding cuff |
| `ASM_HAND_L/R` | Hand_L/R | Palm dan wrist mechanism |
| `CTRL_{INDEX,MIDDLE,RING,THUMB}_{L,R}_0` | Existing matching digit joint | Primary digit mechanical hinge, own assembly approach |
| Same `CTRL` with suffix 1/2 | Previous segment | Secondary phalange hinges; thumb mempunyai 0/1 |
| `ASM_THIGH_L/R` | Thigh_L/R | Thigh dan local ridge |
| `ASM_SHIN_L/R` | Shin_L/R | Knee bearing dan shin |
| `ASM_BOOT_L/R` | Foot_L/R | Boot dan sole |
| `ASM_WING_ROOT_L/R` | Backpack control | Root hinge dan main blade |
| `ASM_WING_TIP_L/R` | Wing root control | Tip hinge dan blade |

Bone-parented object space dalam Blender termasuk parent-bone convention. Jangan merekonstruksi offset dengan menebak bone tail; gunakan local matrices GLB yang sudah diekspor.

## Articulation Formulas

Di bawah ini Euler anatomis dalam absolute Blender rest axes, dalam radians. Untuk digunakan pada node glTF, rotasi delta menjadi `D = B * EulerXYZ(x,y,z) * transpose(B)`. Setiap control dibuat dengan rest world orientation identity. Rumus menggunakan **base local matrix**, bukan matrix hasil frame sebelumnya.

`s = +1` untuk L, `-1` untuk R; `E = abs(UpperArm delta Y)`, `Bend = abs(Forearm delta X)`. Primary joint deltas memakai kontrak White V4.1, bukan world Euler current yang telah mengandung parent rotations.

```text
Shoulder control rotation = Euler(0, -s * 0.64 * E, 0)
Shoulder local shift in its rest anatomical axes =
  (s * 0.07 * sin(E/2), 0, 0.025 * sin(E)) meters

f = clamp((degrees(Bend) - 55) / 75, 0, 1)
Forearm shell shift = (0,0,-0.055*f) meters
Upperarm shell shift = (0,0,+0.105*f) meters
```

Axial shell sliding menjaga plate tetap rigid. Itu tidak membuat 110-130 derajat otomatis usable: hasil collision masih menunjukkan limit pada deep bend. Jangan mengaktifkan pose di luar envelope yang disetujui hanya karena formula tersedia. Supported subset teknis saat review: elbow samples 0/45/90 bebas dari selected critical overlaps; 110/120/130 gagal upperarm/forearm clearance.

Primary existing finger bone menggerakkan primary digit assembly; child control menambah curl untuk segment berikutnya. Rest tambahan: 10 derajat pada anatomical Y masing-masing segment, thumb 6.5 derajat. Art proof fist memakai 65 derajat per segment (thumb 42.25), point memakai 5 derajat index dan 65 pada digit lain. Ini preset inspeksi, **bukan validasi contact atau gripping solver**. Jangan menjumlahkan primary bone curl dan control curl tanpa aturan yang jelas.

## Wing Contract

Default `p=0` FOLDED. PARTIAL `p=0.5`. DEPLOYED `p=1`.

```text
Root delta EulerXYZ = (0, s*89*(1-p), 0) degrees
Tip delta EulerXYZ  = (0, -s*154*(1-p), 0) degrees
```

Tip rotation selalu child dari root. Gunakan hinge pivots actual dari manifest; jangan rotate blade di sekitar centroid. Exported matrices sudah berada pada folded state. Untuk memperoleh base rotation dari folded target: `R_base = R_folded * inverse(D_folded)`, lalu `R_current = R_base * D_current`. Finger preset memakai cara serupa untuk menghilangkan rest curl sebelum menggantinya, bukan menumpuk curl per-frame.

Sayap harus tetap folded saat assembly/disassembly. Deploy hanya setelah armor seated dan manual/behavior state mengizinkan. Jet emission default off; GLB tidak memuat flame mesh atau particle.

## Timeline Dan Reversibility

Durasi artistik 3.4 detik, dapat diskalakan runtime. Prepare 0-.20; lower .20-.95; torso .55-1.75; arms 1.00-2.35; helmet 1.90-2.85; final lock 2.70-3.40. Finger assemblies berbagi phase dan world offset dengan palm sehingga bone parenting tidak memisahkan approach tangan.

```text
u = clamp((3.4*p - phase_start)/(phase_end-phase_start),0,1)
e = u*u*(3-2*u)
offset_world = start_offset_world*(1-e) + up_world*.08*sin(pi*e)
local_translation = seated_translation + inverse(parent_world_3x3)*offset_world
```

Rotation approach dipertahankan pada seated rotation, bukan random spin. Ini curved approach yang deterministik, bukan physical dynamics. Phase `inherit` tidak mendapat approach kedua. `armor_transformation_timeline.json` menyediakan nilai yang sama. Semua endpoints dan local matrices dapat ditemukan dalam manifest.

Reverse mengevaluasi `p` yang sama dengan arah menurun. Request ke target sama harus idempotent. Perubahan target di tengah transisi melanjutkan dari `p` sekarang, bukan reset ke nol. Evaluasi .40, .70, .40 wajib identik. Art test menguji repeated values dan return-to-neutral; **continuous path collision dan coverage pop belum dinyatakan lulus**.

## Coverage White

Original White bukan dihapus. FAST: tampilkan seluruh original White; armor hidden. ARMORED seated: sembunyikan White SoftSkin, legs, access port/lid/detail dan torso seam; gunakan satu set head/eyes/bridge saja. Pilih original White face atau embedded Armored face, jangan keduanya bersamaan.

Saat assembly, jangan sembunyikan seluruh White pada awal. Di art preview, clearance torso diinterpolasi selama Prepare; triangle region ditutup sesudah phase owner seated: lower .95, torso 1.75, arms 2.35 detik. White hands ditutup hanya bersama glove. Helmet mengitari white face; face tetap ada. Underlying dark mechanisms bergerak bersama assembly-nya.

Data fit mengacu pada SHA-256 GLB White dan vertex layout tertentu. Fail closed jika hash/layout tidak sesuai. Buat working copy POSITION/index buffers, apply sparse POSITION delta sebelum White corrective morphs dan LBS, hitung ulang normals, dan gabungkan index groups yang masih visible. Kembalikan ke delta 0 dan original indices saat FAST. Jangan memodifikasi original buffer permanen.

Region coverage preview adalah proof staging, bukan occlusion-certified transition. Chest/abdomen grouping masih coarse; coverage timing mungkin memerlukan adjustment setelah renderer integration. Partial failure/cancel harus mempertahankan last coherent coverage set sampai reset atau target baru, bukan memunculkan naked White di atas plate.

## Event Semantics (Specification Only)

| Event | Makna |
|---|---|
| `armor.prepare` | Load/verify manifests dan hashes, allocate working buffers, neutral assembly-safe pose; tidak mengubah target mode diam-diam |
| `armor.assembly.start` | Target ARMORED, progress dari state saat ini, wings folded |
| `armor.assembly.progress` | Set absolute normalized progress 0..1; nilai sama memberi transforms sama |
| `armor.assembly.complete` | Semua phase seated, coverage coherent, target ARMORED; bukan sekadar LLM selesai berpikir |
| `armor.disassembly.start` | Target FAST, reverse dari progress saat ini; fold wing dahulu |
| `armor.disassembly.complete` | Restore original White buffers/visibility, armor hidden |
| `armor.wing.fold` | Target wing progress 0; aman untuk idle/assembly |
| `armor.wing.deploy` | Target wing progress 1, hanya jika assembly complete dan pose clearance mengizinkan |
| `armor.wing.set_progress` | Absolute 0..1 wing progress, bukan additive rotation |
| `armor.cancel` | Hentikan advance, tahan progress/coverage coherent; tidak teleport ke White/Armored |
| `armor.reset` | Explicit FAST reset: fold/hide armor, restore original buffers dan White neutral; clear pending transitions |
| `armor.status` | Return target/state/progress/wing/asset-hash/error; read-only |

Jangan ikat availability asset pada lifetime stream LLM. Hidden-window pause/resume mempertahankan absolute state. Tidak ada IPC, event handler atau animation runtime yang dibuat dalam pekerjaan art ini.
