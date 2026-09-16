param([int]$Port = 0)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 is required. Install it and run again.' }
    & '.venv\Scripts\python.exe' -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
if (!(Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
$threadPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!$Port) { $Port = [int](& $threadPython -c "import os; from dotenv import dotenv_values; print(os.environ.get('THREAD_PORT') or dotenv_values('.env').get('THREAD_PORT') or 8766)") }
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a port between 1024 and 65535.' }
$threadProvider = & $threadPython -c "from thread_agent.planner import settings; print(settings()['provider'])"
Write-Host "THREAD workspace: http://127.0.0.1:$Port"
if ($threadProvider -eq 'local') { & (Join-Path $PSScriptRoot 'start-local.ps1') -ModelOnly -Port $Port }
$threadListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($threadListener) {
    try { $threadExisting = Invoke-RestMethod "http://127.0.0.1:$Port/api/config" -TimeoutSec 2 } catch { $threadExisting = $null }
    if ($threadExisting.protocol -like 'thread.v1*') { Write-Host 'THREAD is already running at that address.'; return }
    throw "Port $Port belongs to another app. Run .\run.ps1 -Port 8767 to choose a different port."
}
New-Item -ItemType Directory -Force -Path '.runtime' | Out-Null
$threadServer = Start-Process -FilePath $threadPython -ArgumentList "-m uvicorn thread_agent.server:app --host 127.0.0.1 --port $Port" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput '.runtime\server.out.log' -RedirectStandardError '.runtime\server.err.log'
$threadServer.Id | Set-Content -LiteralPath '.runtime\server.pid'
$threadDeadline = (Get-Date).AddSeconds(20)
$threadReady = $false
while ((Get-Date) -lt $threadDeadline) {
    try {
        $threadStarted = Invoke-RestMethod "http://127.0.0.1:$Port/api/config" -TimeoutSec 1
        if ($threadStarted.protocol -like 'thread.v1*') { $threadReady = $true; break }
    } catch { Start-Sleep -Milliseconds 200 }
}
if (!$threadReady) { throw 'THREAD did not become ready. See .runtime\server.err.log.' }
Write-Host 'Running in the background. Logs: .runtime\server.err.log. Stop with .\stop-thread.ps1.'
