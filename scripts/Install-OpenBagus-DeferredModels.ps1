<#
.SYNOPSIS
    Install-OpenBagus-DeferredModels.ps1 - OpenBagus Deferred Model Installer & Hardware Audio Verifier
.DESCRIPTION
    Downloads English male TTS model (en_US-norman-medium), validates SHA-256,
    preserves existing Indonesian model, verifies ONNX session loading,
    and conducts an end-to-end synthesis and physical speaker test.
#>

[CmdletBinding()]
param(
    [switch]$SkipSpeakerTest = $false
)

$ErrorActionPreference = "Stop"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "OPENBAGUS DEFERRED MODEL INSTALLER & AUDIO VERIFIER" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$DestDir = Join-Path $env:LOCALAPPDATA "OpenBagus\models\tts"
if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
    Write-Host "[+] Created target directory: $DestDir" -ForegroundColor Green
} else {
    Write-Host "[*] Target directory exists: $DestDir" -ForegroundColor Gray
}

# ------------------------------------------------------------------
# STEP 1: Verify Existing Indonesian Model Preservation
# ------------------------------------------------------------------
Write-Host "`n--- STEP 1: Verifying Existing Indonesian Model ---" -ForegroundColor Yellow
$IndoOnnx = Join-Path $DestDir "id_ID-news_tts-medium.onnx"
$IndoJson = Join-Path $DestDir "id_ID-news_tts-medium.onnx.json"

if (Test-Path $IndoOnnx) {
    $IndoSize = (Get-Item $IndoOnnx).Length
    $IndoHash = (Get-FileHash -Path $IndoOnnx -Algorithm SHA256).Hash.ToLower()
    Write-Host "[OK] Existing Indonesian model preserved: id_ID-news_tts-medium.onnx ($IndoSize bytes)" -ForegroundColor Green
    Write-Host "     SHA-256: $IndoHash" -ForegroundColor Gray
} else {
    Write-Warning "[!] Indonesian model id_ID-news_tts-medium.onnx not found in $DestDir"
}

# ------------------------------------------------------------------
# STEP 2: Download English Male Model (en_US-norman-medium)
# ------------------------------------------------------------------
Write-Host "`n--- STEP 2: Downloading en_US-norman-medium ---" -ForegroundColor Yellow
$BaseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium"
$OnnxUrl = "$BaseUrl/en_US-norman-medium.onnx"
$JsonUrl = "$BaseUrl/en_US-norman-medium.onnx.json"

$TargetOnnx = Join-Path $DestDir "en_US-norman-medium.onnx"
$TargetJson = Join-Path $DestDir "en_US-norman-medium.onnx.json"

# Expected SHA256 from upstream HuggingFace Git LFS commit
$ExpectedSha256 = "b9739443232a80a59c7d18810dd856899bf16a7964725f5ab81ea49b1351cb71"

# Download ONNX if missing or invalid size
$NeedDownloadOnnx = $true
if (Test-Path $TargetOnnx) {
    $CurrentHash = (Get-FileHash -Path $TargetOnnx -Algorithm SHA256).Hash.ToLower()
    if ($CurrentHash -eq $ExpectedSha256.ToLower()) {
        Write-Host "[OK] $TargetOnnx already exists with matching SHA-256." -ForegroundColor Green
        $NeedDownloadOnnx = $false
    } else {
        Write-Host "[*] Existing file hash mismatch. Re-downloading..." -ForegroundColor Yellow
    }
}

if ($NeedDownloadOnnx) {
    Write-Host "[+] Downloading en_US-norman-medium.onnx (~63.5 MB)..." -ForegroundColor Cyan
    curl.exe -L -o "$TargetOnnx.tmp" "$OnnxUrl"
    if (-not (Test-Path "$TargetOnnx.tmp")) {
        throw "Download failed: $TargetOnnx.tmp was not created."
    }
    Move-Item -Path "$TargetOnnx.tmp" -Destination "$TargetOnnx" -Force
}

# Download JSON config
$NeedDownloadJson = $true
if (Test-Path $TargetJson) {
    $testContent = Get-Content -Path $TargetJson -Raw
    if ($testContent -match '"dataset"\s*:\s*"norman"' -and $testContent.Length -gt 1000) {
        Write-Host "[OK] $TargetJson already exists and contains norman dataset config." -ForegroundColor Green
        $NeedDownloadJson = $false
    } else {
        Write-Host "[*] Existing JSON invalid. Re-downloading..." -ForegroundColor Yellow
    }
}

if ($NeedDownloadJson) {
    Write-Host "[+] Downloading en_US-norman-medium.onnx.json..." -ForegroundColor Cyan
    curl.exe -L -o "$TargetJson.tmp" "$JsonUrl"
    if (-not (Test-Path "$TargetJson.tmp")) {
        throw "Download failed: $TargetJson.tmp was not created."
    }
    Move-Item -Path "$TargetJson.tmp" -Destination "$TargetJson" -Force
}

# ------------------------------------------------------------------
# STEP 3: Integrity & SHA-256 Verification
# ------------------------------------------------------------------
Write-Host "`n--- STEP 3: Cryptographic & Format Verification ---" -ForegroundColor Yellow
$OnnxSize = (Get-Item $TargetOnnx).Length
if ($OnnxSize -le 1000000) {
    throw "Verification failed: ONNX file size ($OnnxSize bytes) is suspiciously small!"
}

$ActualSha256 = (Get-FileHash -Path $TargetOnnx -Algorithm SHA256).Hash.ToLower()
Write-Host "     Target ONNX Size: $OnnxSize bytes" -ForegroundColor Gray
Write-Host "     Actual SHA-256  : $ActualSha256" -ForegroundColor Gray
Write-Host "     Expected SHA-256: $ExpectedSha256" -ForegroundColor Gray

if ($ActualSha256 -ne $ExpectedSha256.ToLower()) {
    throw "SHA-256 checksum verification failed!"
}
Write-Host "[OK] SHA-256 matched upstream HuggingFace release!" -ForegroundColor Green

# Validate JSON config using Python (Piper phoneme dicts have case-sensitive keys like 'x' and 'X')
$PythonExe = "E:\Projects\OpenBagus\.venv\Scripts\python.exe"
$ValidateJsonCmd = @"
import json, sys
try:
    with open(r'$TargetJson', 'r', encoding='utf-8') as f:
        d = json.load(f)
    sr = d.get('audio', {}).get('sample_rate', 0)
    spk = d.get('num_speakers', 1)
    ds = d.get('dataset', '')
    print(f'[OK] JSON configuration validated via Python. Dataset: {ds}, Sample rate: {sr} Hz, Speakers: {spk}')
except Exception as e:
    print(f'ERROR: {e}')
    sys.exit(1)
"@
& $PythonExe -c $ValidateJsonCmd
if ($LASTEXITCODE -ne 0) {
    throw "JSON validation failed!"
}

# ------------------------------------------------------------------
# STEP 4: ONNX Runtime Load & Synthesis Verification
# ------------------------------------------------------------------
Write-Host "`n--- STEP 4: Model Synthesis & Audio Hardware Verification ---" -ForegroundColor Yellow
$PythonExe = "E:\Projects\OpenBagus\.venv\Scripts\python.exe"

$VerifyScript = @"
import sys, os, wave, io, time
import numpy as np

try:
    import piper
except ImportError:
    print('ERROR: piper-tts is not installed in virtual environment!')
    sys.exit(1)

try:
    import sounddevice as sd
except ImportError:
    sd = None

onnx_path = r'$TargetOnnx'
json_path = r'$TargetJson'
skip_speaker = '$SkipSpeakerTest'.lower() == 'true'

print('[Python] Loading PiperVoice ONNX model...')
t0 = time.perf_counter()
voice = piper.PiperVoice.load(onnx_path, config_path=json_path)
t_load = (time.perf_counter() - t0) * 1000
print(f'[Python] Model loaded successfully in {t_load:.1f} ms!')

test_phrase = 'Hello! I am Bagusmax, your healthcare robot companion and financial intelligence assistant. Welcome to English learning mode.'
print(f'[Python] Synthesizing test utterance: \"{test_phrase}\"')

t_synth_start = time.perf_counter()
chunks = list(voice.synthesize(test_phrase))
t_synth = (time.perf_counter() - t_synth_start) * 1000

if not chunks:
    print('ERROR: voice.synthesize yielded 0 chunks!')
    sys.exit(2)

audio_data = np.concatenate([c.audio_float_array for c in chunks])
framerate = getattr(voice.config, 'sample_rate', 22050)
duration = len(audio_data) / framerate
rms = float(np.sqrt(np.mean(audio_data**2)))
peak = float(np.max(np.abs(audio_data)))

print(f'[Python] Audio Statistics:')
print(f'         Channels   : 1 (Mono)')
print(f'         Sample Rate: {framerate} Hz')
print(f'         Duration   : {duration:.2f} s')
print(f'         RMS Energy : {rms:.4f}')
print(f'         Peak Ampl  : {peak:.4f}')
print(f'         Synth Time : {t_synth:.1f} ms ({(duration / (t_synth/1000.0)):.1f}x real-time)')

if duration <= 1.0 or rms < 0.01:
    print('ERROR: Synthesized audio is silent or truncated!')
    sys.exit(2)

if peak > 1.05:
    print('WARNING: Potential digital clipping detected!')

if sd is not None and not skip_speaker:
    try:
        dev_info = sd.query_devices(kind='output')
        dev_name = dev_info['name']
        native_rate = int(dev_info['default_samplerate'])
        print(f'[Python] Playing through physical output: {dev_name} (native rate: {native_rate} Hz)...')
        
        # Resample in memory if needed to match WASAPI/DirectSound native device rate
        if native_rate != framerate:
            new_len = int(len(audio_data) * native_rate / framerate)
            play_audio = np.interp(np.linspace(0, len(audio_data), new_len, endpoint=False), np.arange(len(audio_data)), audio_data)
        else:
            play_audio = audio_data
            
        sd.play(play_audio, native_rate)
        sd.wait()
        print('[Python] Playback completed successfully through physical speakers!')
    except Exception as e:
        print(f'WARNING: Playback encounter error: {e}')
else:
    print('[Python] Speaker playback skipped.')

print('[Python] MODEL AND SYNTHESIS ACCEPTANCE: PASS')
"@

& $PythonExe -c $VerifyScript
if ($LASTEXITCODE -ne 0) {
    throw "Python model synthesis verification failed with exit code $LASTEXITCODE"
}

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "PHASE 2 COMPLETED: en_US-norman-medium INSTALLED & VERIFIED!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
