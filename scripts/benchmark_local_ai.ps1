# benchmark_local_ai.ps1 — Evaluates inference throughput for FAST and DEEP Ollama models on RTX 3050

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   OpenBagus Local AI Benchmark (RTX 3050 6GB GPU)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

$prompt = @{
    model = "qwen3.5:2b-q4_K_M"
    messages = @(
        @{
            role = "user"
            content = "Jelaskan perbedaan mendasar antara PER dan PBV untuk saham perbankan di BEI secara ringkas dalam 2 paragraf."
        }
    )
    think = $false
    stream = $false
    options = @{
        temperature = 0.2
        num_predict = 128
        num_gpu = 99
        num_ctx = 2048
    }
} | ConvertTo-Json -Depth 5

# 1. FAST Benchmark
Write-Host "[1/2] Pengujian Mode FAST (qwen3.5:2b-q4_K_M, think=false)..." -ForegroundColor Yellow
try {
    $t0 = [System.Diagnostics.Stopwatch]::StartNew()
    $res = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method Post -Body $prompt -ContentType "application/json" -TimeoutSec 60
    $t0.Stop()
    $evalDuration = $res.eval_duration / 1e9
    $evalCount = $res.eval_count
    $tokPerSec = if ($evalDuration -gt 0) { [math]::Round($evalCount / $evalDuration, 1) } else { 0 }
    Write-Host "      Latency Total     : $($t0.ElapsedMilliseconds) ms" -ForegroundColor Green
    Write-Host "      Prompt Eval Count : $($res.prompt_eval_count) tokens" -ForegroundColor Gray
    Write-Host "      Output Tokens     : $evalCount tokens" -ForegroundColor Gray
    Write-Host "      Throughput        : $tokPerSec tokens/detik" -ForegroundColor Green
} catch {
    Write-Host "      FAST Benchmark Gagal: $_" -ForegroundColor Red
}

Write-Host ""

# 2. DEEP Benchmark
Write-Host "[2/2] Pengujian Mode DEEP_REASONING (qwen3.5:4b, think=true)..." -ForegroundColor Yellow
$promptDeep = @{
    model = "qwen3.5:4b"
    messages = @(
        @{
            role = "user"
            content = "Hitung dan evaluasi dampak kenaikan suku bunga BI 25 bps terhadap margin bunga bersih (NIM) 4 bank besar IDX."
        }
    )
    think = $true
    stream = $false
    options = @{
        temperature = 0.2
        num_predict = 256
        num_gpu = 99
        num_ctx = 4096
    }
} | ConvertTo-Json -Depth 5

try {
    $t1 = [System.Diagnostics.Stopwatch]::StartNew()
    $resDeep = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/chat" -Method Post -Body $promptDeep -ContentType "application/json" -TimeoutSec 120
    $t1.Stop()
    $evalDurationD = $resDeep.eval_duration / 1e9
    $evalCountD = $resDeep.eval_count
    $tokPerSecD = if ($evalDurationD -gt 0) { [math]::Round($evalCountD / $evalDurationD, 1) } else { 0 }
    Write-Host "      Latency Total     : $($t1.ElapsedMilliseconds) ms" -ForegroundColor Green
    Write-Host "      Prompt Eval Count : $($resDeep.prompt_eval_count) tokens" -ForegroundColor Gray
    Write-Host "      Output Tokens     : $evalCountD tokens" -ForegroundColor Gray
    Write-Host "      Throughput        : $tokPerSecD tokens/detik" -ForegroundColor Green
    if ($resDeep.message.thinking) {
        Write-Host "      Thinking Trace    : Dihasilkan ($($resDeep.message.thinking.Length) karakter) [TERPISAH]" -ForegroundColor Cyan
    }
} catch {
    Write-Host "      DEEP Benchmark Gagal: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "Benchmark selesai." -ForegroundColor Cyan
