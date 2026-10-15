param([string]$Python = 'E:\Projects\OpenBagus\.venv\Scripts\python.exe')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$models = 'E:\Projects\OpenBagus\models'
$store = Join-Path $models 'ollama'
$ollama = (Get-Command ollama -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $Python)) { throw "Python not found: $Python" }
foreach ($tag in @('2b-q4_K_M', '4b')) {
    $manifest = Join-Path $store "manifests\registry.ollama.ai\library\qwen3.5\$tag"
    if (-not (Test-Path -LiteralPath $manifest)) { throw "Model manifest missing: $manifest" }
    $data = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    foreach ($layer in @($data.config) + @($data.layers)) {
        $blob = Join-Path $store ('blobs\' + $layer.digest.Replace(':', '-'))
        if (-not (Test-Path -LiteralPath $blob)) { throw "Model blob missing: $blob" }
    }
}

$names = @('OLLAMA_HOST','OLLAMA_MODELS','OLLAMA_MAX_LOADED_MODELS','OPENBAGUS_MODEL_DIR','HF_HUB_OFFLINE','OPENBAGUS_LLM_ENDPOINT','OPENBAGUS_LLM_MODEL','OPENBAGUS_LLM_KEY','PYTHONUTF8')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$server = $null
Push-Location $root
try {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    $env:OLLAMA_HOST = "http://127.0.0.1:$port"
    $env:OLLAMA_MODELS = $store
    $env:OLLAMA_MAX_LOADED_MODELS = '1'
    $env:OPENBAGUS_MODEL_DIR = $models
    $env:HF_HUB_OFFLINE = '1'
    $env:PYTHONUTF8 = '1'
    foreach ($name in @('OPENBAGUS_LLM_ENDPOINT','OPENBAGUS_LLM_MODEL','OPENBAGUS_LLM_KEY')) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $logs = Join-Path $root 'reports\runtime'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $server = Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'chat_ollama_stdout.log') -RedirectStandardError (Join-Path $logs 'chat_ollama_stderr.log')
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        if ($server.HasExited) { throw 'Isolated Ollama exited; see reports/runtime/chat_ollama_stderr.log' }
        try {
            $tags = Invoke-RestMethod -Uri "$env:OLLAMA_HOST/api/tags" -TimeoutSec 1
            $available = @($tags.models | ForEach-Object { $_.name })
            if ('qwen3.5:2b-q4_K_M' -in $available -and 'qwen3.5:4b' -in $available) { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) { throw 'Repository-local Ollama models did not become ready' }
    Write-Host "ChatTest: $root"
    Write-Host "Local models: $models | Ollama: $env:OLLAMA_HOST"
    & $Python -B -m openbagus.cli
} finally {
    if ($server -and -not $server.HasExited) { & taskkill.exe /PID $server.Id /T /F | Out-Null }
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    Pop-Location
}
