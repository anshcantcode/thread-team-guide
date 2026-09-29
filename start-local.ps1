param([switch]$ModelOnly, [int]$Port = 8766)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$threadPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $threadPython)) { throw 'Run run.ps1 once to create the Python environment.' }
if (!$ModelOnly) {
    $env:THREAD_PROVIDER = 'local'
    & (Join-Path $PSScriptRoot 'run.ps1') -Port $Port
    return
}
$threadExecutable = Join-Path $PSScriptRoot '.runtime\llama\llama-server.exe'
$threadLocalKey = Join-Path $PSScriptRoot '.runtime\local-api.key'
$threadModel = Join-Path $PSScriptRoot '.runtime\models\Qwen3.5-4B-Q4_K_M.gguf'
$threadVision = Join-Path $PSScriptRoot '.runtime\models\mmproj-F16.gguf'
$threadSpeechInstalled = & $threadPython -c "import importlib.util; print(int(importlib.util.find_spec('faster_whisper') is not None))"
if ($threadSpeechInstalled -ne '1' -or !(Test-Path -LiteralPath $threadExecutable) -or !(Test-Path -LiteralPath $threadModel) -or !(Test-Path -LiteralPath $threadVision) -or !(Test-Path -LiteralPath '.runtime\whisper')) {
    & $threadPython -m pip install -r requirements-local.lock
    if ($LASTEXITCODE -ne 0) { throw 'Local dependencies could not be installed.' }
    & $threadPython scripts/setup_local.py
    if ($LASTEXITCODE -ne 0) { throw 'Local model download or verification failed.' }
}
if (!(Test-Path -LiteralPath $threadLocalKey)) {
    & $threadPython -c "from pathlib import Path; import secrets; Path('.runtime/local-api.key').write_text(secrets.token_urlsafe(32), encoding='utf-8')"
}
$threadHealthy = $false
try { $threadHealthy = (Invoke-WebRequest 'http://127.0.0.1:8088/health' -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200 } catch {}
if (!$threadHealthy) {
    $threadLoading = $false
    if (Test-Path -LiteralPath '.runtime\model.pid') {
        $threadRecordedId = [int](Get-Content -LiteralPath '.runtime\model.pid')
        $threadRecorded = Get-CimInstance Win32_Process -Filter "ProcessId = $threadRecordedId"
        $threadLoading = $threadRecorded.ExecutablePath -eq $threadExecutable
    }
    if (!$threadLoading) {
        if (Get-NetTCPConnection -LocalPort 8088 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 8088 belongs to another process. Inspect it before starting the model.' }
        $threadArguments = "--model `"$threadModel`" --mmproj `"$threadVision`" --host 127.0.0.1 --port 8088 --ctx-size 8192 --parallel 1 --n-gpu-layers 99 --batch-size 512 --ubatch-size 128 --flash-attn on --jinja --alias thread-local --api-key-file `"$threadLocalKey`" --cors-origins http://127.0.0.1:$Port --no-ui --image-min-tokens 1024"
        $threadModelProcess = Start-Process -FilePath $threadExecutable -ArgumentList $threadArguments -WorkingDirectory (Split-Path $threadExecutable) -WindowStyle Hidden -PassThru -RedirectStandardOutput '.runtime\model.out.log' -RedirectStandardError '.runtime\model.err.log'
        $threadModelProcess.Id | Set-Content -LiteralPath '.runtime\model.pid'
        Write-Host 'Loading Qwen3.5 4B on the GPU. Log: .runtime\model.err.log'
    }
    $threadDeadline = (Get-Date).AddSeconds(60)
    while (!$threadHealthy -and (Get-Date) -lt $threadDeadline) {
        Start-Sleep -Milliseconds 500
        try { $threadHealthy = (Invoke-WebRequest 'http://127.0.0.1:8088/health' -TimeoutSec 2 -UseBasicParsing).StatusCode -eq 200 } catch {}
    }
    if (!$threadHealthy) { throw 'The local model did not become ready. Check .runtime\model.err.log, available GPU memory, and the downloaded files.' }
}
Write-Host 'Local Qwen3.5 is ready.'
