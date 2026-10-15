# White: Kontrak Lighting Desktop

Status: **DRAFT, belum diimplementasikan**. Gate A belum mendapat persetujuan
visual. Dokumen ini kontrak untuk Antigravity; tidak ada perubahan renderer,
popup, preferensi, voice, LLM atau CLI.

## Anchor dan Projection

Default anchor `(0.50,0.10)` terhadap work-area monitor aktif. Monitor dipilih
dari luas irisan terbesar popup dengan work-area; tie-break menggunakan monitor
yang berisi pusat popup. Perubahan monitor perlu transisi pendek yang dibatasi,
tanpa mengubah posisi popup.

Dengan work-area fisik `(mx,my,W,H)`, anchor desktop adalah
`(mx + anchor_x*W, my + anchor_y*H)`. Semua window bounds dan work-area harus
berasal dari API dengan DPI awareness yang konsisten. Logical coordinates wajib
dikonversi menggunakan DPI monitor sebelum dicampur dengan physical pixels.
Work-area dapat memiliki origin negatif dan tidak mencakup taskbar.

Untuk projection runtime, ubah anchor desktop ke popup NDC:

```text
nx = 2*(anchor_desktop_x-popup_left)/popup_width - 1
ny = 1 - 2*(anchor_desktop_y-popup_top)/popup_height
```

Unproject `(nx,ny,-1,1)` dan `(nx,ny,1,1)` melalui inverse view-projection,
lakukan perspective divide, lalu tentukan posisi key pada ray dengan virtual
depth yang dikonfigurasi. Anchor boleh berada di luar popup; NDC tidak perlu
dipaksa ke [-1,1]. Jangan memakai coordinate model/mesh sebagai anchor atau
mengalikan rotasi model ke arah key. Depth positif dan minimum jarak mencegah
singularity dekat anchor. Validasi juga ketika camera zoom/orientation berubah.

## Material dan Shadow

White memakai material dielectric nonmetalik: base color off-white,
roughness 0.43; panel vinyl 0.52 dan seam 0.56. Nilai tersebut asset-side dan
masih memerlukan penilaian runtime. Key besar dan lunak, fill lemah, ambient
terbatas; tone mapping mempertahankan highlight tanpa memutihkan seluruh model.
Tidak ada shadow atau directional highlight yang dibake ke GLB.

Runtime dapat memakai virtual-ground contact shadow dan projected shadow
ber-alpha sekitar 0.08 sebagai titik awal, dengan feathering. Arah offset
menjauhi anchor monitor; komponen horizontal berbalik saat popup berpindah dari
kanan ke kiri anchor. Panjang shadow dan intensity harus dibatasi.
Receiver hanya alat compositing, bukan lantai desktop nyata. Jangan tampilkan
rectangle receiver. Antigravity harus memeriksa straight/premultiplied alpha
dari pipeline Windows yang sebenarnya dan mencegah dark fringe.

Konfigurasi yang relevan: `enabled`, `anchor_x`, `anchor_y`, `intensity`,
`softness`, `shadow_opacity`, `shadow_softness`, `follow_active_monitor`.
Penyimpanan dan UI tetap memakai mekanisme aplikasi milik Antigravity.

## Acceptance Runtime

Semua berikut **NOT TESTED** pada task aset: popup transparent, actual monitor
selection/DPI, alpha blending, frame time, shader skinning, dan light anchoring.
Setelah persetujuan Gate A, Antigravity perlu menangkap top-left/top-center/
top-right/center/bottom-left/bottom-center/bottom-right, plus rotasi 180 derajat
dan perpindahan antar monitor. Catat bounds, monitor, anchor, view-projection,
light vector, shadow direction/opacity dan frame time. Bandingkan lights/shadows
off dan on dengan latar desktop tetap terlihat. Render Blender tidak menggantikan
bukti runtime Windows tersebut.
