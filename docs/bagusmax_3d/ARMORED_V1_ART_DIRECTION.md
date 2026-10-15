# BAGUSMAX Armored V1 Art Direction

Status: **REVIEW_REQUIRED**, bukan persetujuan visual atau production-ready. White V4.1 sendiri masih menunggu visual approval. Candidate Armored tidak menggantikannya.

## Bentuk Dan Batasan

Armor merupakan asset baru di atas salinan rig White V4.1, bukan recolor White atau penggantian skeleton. Proporsi tulang, head, rest matrices dan 32 nama joint dipertahankan. Armor dibuat dari thick surface patches, anatomical loft shells, rim bevel, bearing berlubang, dan control node kaku. Tidak ada deformasi rubber pada plate, animation clip, shader highlight palsu, texture unduhan, api jet permanen, atau lampu baru.

Silhouette mengutamakan red upper torso dan aero pauldrons, empat purple abdominal segments, gauntlet besar, tangan graphite bersegmen, paha berarmor, sepatu berlapis, helmet beraperture putih, backpack dan sayap dua hinge. Hasilnya tetap interpretasi yang dibatasi ukuran kepala dan panjang tulang White, bukan rekonstruksi proporsi film yang terukur.

## Referensi

Semua 15 gambar diperiksa. ID, observasi, lokasi original dan SHA-256 tersedia dalam `reports/bagusmax_3d/armored_v1/reference_index.json`. Board privat `private_reference_review.html` mereferensikan original Temp secara eksternal; tidak mengandung salinan pixel film, base64, atau texture referensi. Original tidak dimodifikasi. HTML bergantung pada keberadaan file Temp dan tidak boleh dipublikasikan sebagai paket referensi berlisensi.

R01/R07 dan R02/R08 merupakan variasi crop yang hampir sama, bukan bukti tambahan independen. R03, R09, R11 dan R14 memperlihatkan interpretasi toy/product, bukan bukti topology film. R10 adalah film lab dengan pencahayaan gelap. Perspektif flight tidak dipakai sebagai ukuran orthographic.

| Komponen | Referensi | Contour / Proporsi | Lapisan, Material Dan Finish | Seam Dan Koneksi | Confidence / Area Tidak Terlihat |
|---|---|---|---|---|---|
| Helmet | R15, R12 | Kepala kompak, crown rendah, visor putih sempit dengan brow menurun di tengah, cheek/chin merah, fin samping | Red shell berketebalan, graphite gasket, violet ear inset; PBR merah roughness 0.30 | Crown/rear/chin/frame terpisah, seluruhnya pada Head; neck seal pada Chest | HIGH untuk appearance depan; MEDIUM untuk shell belakang. Aperture disesuaikan agar face White asli tetap terbaca |
| Chest | R02, R10, R11 | Dada lebar membulat, batas bawah turun ke tengah, mengecil ke abdomen | Front, collar, flank dan rear shells; access port; red finish | Panel dibuat sebagai permukaan tersendiri, bukan garis hitam untuk menyamarkan lubang; pada Chest | HIGH untuk red/purple allocation, MEDIUM untuk exact contour; ketebalan dan sisi dalam merupakan engineering approximation |
| Abdomen | R02, R10, R13 | Empat band lebar horizontal, stepped center detail, curve membungkus perut | Empat front dan empat rear plates violet; silver lock accents; roughness 0.40 | Plate front/rear tiap band pada assembly Spine; flank merah menutup batas lateral | HIGH untuk empat segment depan; LOW/MEDIUM untuk segmentasi rear yang tertutup referensi |
| Shoulder | R02, R12 | Aero cap besar, bukan bola atau deltoid anatomi White; outer violet oval | Red thick cap dan conforming violet inlay, dark bearing di bawah | Chest control dengan secondary rotation dan slide; bukan deformasi shell | HIGH untuk silhouette luar; MEDIUM/LOW untuk mekanisme tersembunyi |
| Upper Arm / Elbow | R02, R09 | Upper arm membulat, circular outer elbow bearing dan recess gelap | Red C-shell dengan medial clearance, graphite socket, silver ring dan hub | UpperArm / Forearm anchors asli; shell slide dan inner-edge cutout untuk flexion | HIGH untuk bearing luar; LOW untuk cutout/axial travel. Siku 110-130 masih bermasalah, bukan pose yang diterima |
| Forearm | R01, R02, R09 | Gauntlet lebar di tengah, taper ke wrist, collar miring agar siku punya ruang | Thick red shell, cuff dan conforming oval violet inlay | Forearm control; sliding cuff bukan stretch | HIGH untuk massa dan inlay; MEDIUM untuk collar; deep flexion belum lolos |
| Hands | R01, R02, R12 | Tiga kolom jari gelap plus thumb, silver knuckles; palm inward saat idle | Graphite palm, tiga segment per digit dan dua thumb segment, silver pin | Palm pada Hand; primary digit control pada joint Index/Middle/Ring/Thumb asli; secondary hinges di bawahnya | HIGH untuk material/knuckle allocation, MEDIUM/LOW untuk underside serta exact finger mechanism; contact poses masih perlu review |
| Pelvis / Legs | R02, R10, R14 | Pelvis taper, paha berisi, knee recess, boot toe/sole jelas | Front/rear pelvis, thigh shells dan raised local ridge, knee bearing, shin, boot dan graphite sole | Hips/Thigh/Shin/Foot asli; medial thigh clearance ditambah secara lokal | MEDIUM; ukuran mengikuti tulang White sehingga kaki terlihat lebih pendek dari sebagian referensi Armored |
| Backpack | R14, R09 | Pack kompak di punggung, circular dark rear apertures | Red housing, graphite vent dan recessed silver nozzle; tanpa emissive jet | Chest anchor; wing root melekat pada pack | MEDIUM untuk rear visual, LOW untuk interior propulsion yang tidak terlihat |
| Wings | R01, R04, R11, R13, R14 | Blade merah swept dan tapered; bentang lebih lebar dari shoulder | Main dan tip thick blades, root/tip hinges dan pins, panel accents | Dua hinge per sisi; root di backpack, tip di main wing | HIGH untuk deployed silhouette umum; **LOW untuk folded state**. Folded configuration adalah interpretasi engineering, bukan FILM-CONFIRMED |

## Fitting White

Torso White asli lebih lebar dan dalam daripada abdomen armor referensi. Membesarkan semua armor untuk menyembunyikannya akan menghasilkan silhouette yang salah. Solusinya non-destruktif dan eksplisit:

- Original `.blend` dan GLB White tetap byte-identical.
- Source Armored berisi salinan White untuk fitting, dengan `ArmorClearance` default **0**, terbatas pada anatomical torso region. Bentuk kepala, tangan, kaki dan tulang tidak diubah.
- GLB Armored menyertakan face/head dan skeleton, tidak menyertakan duplikasi seluruh SoftSkin White.
- `armor_white_fit.bin/json` menyediakan delta POSITION sparse dan index groups berdasarkan vertex/triangle GLB White asli. Clearance dipakai hanya pada salinan buffer saat assembly. Normal perlu dihitung ulang; integrasi ini belum diuji di renderer aplikasi.
- Preview memperlihatkan coverage masks pada batas fase. Itu **bukan bukti bebas pop-in atau collision sepanjang jalur assembly**. Integrasi dan inspeksi motion coverage masih wajib.

## Studio Dan Quality

Camera orthographic, exposure, color management, world dan lampu diagnostik berasal dari source White. Lighting specification dan renderer tidak diubah. Perbandingan Blender/GLB memakai pose, framing dan studio sama. Refleksi film tidak dicocokkan dengan mengubah lighting.

Profile QUALITY mempertahankan seluruh detail mesh. DESKTOP_RUNTIME mengurangi hanya bagian lokal, dengan bidang reflektif lebar pada chest, abdomen, pelvis dan helmet tidak di-decimate. Curvature error diukur sebagai sample quality vertex ke desktop surface, bukan bukti Hausdorff maksimum. Source menyimpan mesh desktop aktif dan quality mesh datablocks yang memiliki fake user. Angka lengkap berada di `quality_desktop_profile.json`, `quality_statistics.json` dan `validation_report.json`.

## Review Utama

1. `comparison_sheet.png`: front, side, three-quarter, back, hand dan deployed wings.
2. `white_to_armored.png`: original White dan Armored pada camera yang sama.
3. `shoulder_L_continuity.png` / `shoulder_R_continuity.png`: attachment close-ups, bukan figure kecil saja.
4. `elbow_L_articulation.png` / `elbow_R_articulation.png`: 0/45/90/110/130, termasuk kegagalan deep bend.
5. `assembly_preview.png`: staged art proof, bukan runtime animation.
6. `export_verification.png`: Blender dan geometry yang dievaluasi dari GLB, serta neutral reimport.

Visual fidelity, ukuran helmet relatif terhadap torso, bentuk pauldron, glove rest dan folded wing design tetap memerlukan persetujuan manusia. Hasil validator tidak memberikan persetujuan itu.
