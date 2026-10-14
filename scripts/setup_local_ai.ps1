# setup_local_ai.ps1 — Verifies local AI environment, Ollama models, and GPU acceleration

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "   OpenBagus Local AI & Hardware Verifier" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Ollama API
Write-Host "[1/4] Memeriksa status service Ollama..." -NoNewline
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 3
    Write-Host " [OK]" -ForegroundColor Green
    $models = $resp.models
    Write-Host "      Terpasang $($models.Count) model di Ollama." -ForegroundColor Gray
} catch {
    Write-Host " [OFFLINE]" -ForegroundColor Red
    Write-Host "      Pastikan service Ollama berjalan di port 11434." -ForegroundColor Yellow
}

# 2. Check FAST & DEEP models
Write-Host "[2/4] Memeriksa ketersediaan model FAST dan DEEP..."
$fastFound = $false
$deepFound = $false
if ($models) {
    foreach ($m in $models) {
        if ($m.name -like "*qwen3.5:2b*") {
            $fastFound = $true
            Write-Host "      FAST Model : $($m.name) [DITEMUKAN]" -ForegroundColor Green
        }
        if ($m.name -like "*qwen3.5:4b*") {
            $deepFound = $true
            Write-Host "      DEEP Model : $($m.name) [DITEMUKAN]" -ForegroundColor Green
        }
    }
}
if (-not $fastFound) {
    Write-Host "      FAST Model (qwen3.5:2b-q4_K_M) belum terpasang. Jalankan: ollama pull qwen3.5:2b-q4_K_M" -ForegroundColor Yellow
}
if (-not $deepFound) {
    Write-Host "      DEEP Model (qwen3.5:4b) belum terpasang. Jalankan: ollama pull qwen3.5:4b" -ForegroundColor Yellow
}

# 3. Check GPU & CUDA
Write-Host "[3/4] Memeriksa NVIDIA GPU (nvidia-smi)..." -NoNewline
try {
    $smi = nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader,nounits
    Write-Host " [OK]" -ForegroundColor Green
    Write-Host "      GPU: $smi" -ForegroundColor Gray
} catch {
    Write-Host " [TIDAK DITEMUKAN / CPU ONLY]" -ForegroundColor Yellow
}

# 4. Check Show OpenBagus Python dependencies
Write-Host "[4/4] Memeriksa dependensi 3D Companion (moderngl, glfw)..." -NoNewline
try {
    & .venv\Scripts\python -c "import moderngl, glfw, pyrr; print('OK')" 2>$null
    Write-Host " [OK]" -ForegroundColor Green
} catch {
    Write-Host " [KURANG]" -ForegroundColor Yellow
    Write-Host "      Jalankan: .venv\Scripts\pip install moderngl glfw pyrr" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Verifikasi selesai. Untuk memulai OpenBagus: .venv\Scripts\python -m openbagus" -ForegroundColor Cyan
