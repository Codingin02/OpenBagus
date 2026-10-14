# setup_show_openbagus.ps1 — Verifies 3D companion geometry, shaders, and launches standalone window test

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   SHOW OPENBAGUS 3D Companion Environment Check" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Test build character geometry
Write-Host "[1/3] Memeriksa pembentukan mesh 3D karakter..." -NoNewline
try {
    $geoRes = & .venv\Scripts\python -c "from openbagus.companion.renderer import build_character; v, i = build_character(); print(f'{len(v)//9} vertices, {len(i)//3} triangles')"
    Write-Host " [OK]" -ForegroundColor Green
    Write-Host "      Mesh: $geoRes" -ForegroundColor Gray
} catch {
    Write-Host " [GAGAL]" -ForegroundColor Red
}

# 2. Test controller and IPC interface
Write-Host "[2/3] Memeriksa controller companion dan IPC..." -NoNewline
try {
    $ctrlRes = & .venv\Scripts\python -c "from openbagus.companion.controller import CompanionController; c = CompanionController.get_instance(); print(c.get_status()['ipc_address'])"
    Write-Host " [OK]" -ForegroundColor Green
    Write-Host "      IPC Port: $ctrlRes" -ForegroundColor Gray
} catch {
    Write-Host " [GAGAL]" -ForegroundColor Red
}

# 3. Instructions
Write-Host "[3/3] Panduan Menjalankan SHOW OPENBAGUS:"
Write-Host "      Di dalam terminal OpenBagus:" -ForegroundColor Yellow
Write-Host "        /show-openbagus        -> Meluncurkan jendela 3D di sudut kanan desktop" -ForegroundColor Gray
Write-Host "        /show-openbagus hide   -> Menyembunyikan jendela" -ForegroundColor Gray
Write-Host "        /show-openbagus status -> Menampilkan status IPC dan animasi" -ForegroundColor Gray
Write-Host "        /show-openbagus close  -> Menutup jendela 3D" -ForegroundColor Gray
Write-Host "      Atau ucapkan secara natural: 'show open bagus'" -ForegroundColor Gray
Write-Host ""
