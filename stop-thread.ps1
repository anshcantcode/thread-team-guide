# Stop only the workspace-owned processes recorded by THREAD's launchers.
$ErrorActionPreference = 'Stop'
foreach ($threadService in @('server', 'model')) {
    $threadPidPath = Join-Path $PSScriptRoot ".runtime\$threadService.pid"
    if (!(Test-Path -LiteralPath $threadPidPath)) { continue }
    $threadServiceId = [int](Get-Content -LiteralPath $threadPidPath)
    $threadProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $threadServiceId"
    if (!$threadProcess) { continue }
    $threadExpectedPath = if ($threadService -eq 'model') { Join-Path $PSScriptRoot '.runtime\llama\llama-server.exe' } else { Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
    if ($threadProcess.ExecutablePath -ne $threadExpectedPath) {
        Write-Warning "Skipped reused PID $threadServiceId; it is not the recorded THREAD executable."
        continue
    }
    if ($threadService -eq 'server') {
        if ($threadProcess.CommandLine -notlike '*-m uvicorn thread_agent.server:app*') { continue }
        # Windows venv launchers have a child Python process. Verify its command before stopping it.
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $threadServiceId" | Where-Object { $_.CommandLine -like '*-m uvicorn thread_agent.server:app*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
    }
    Stop-Process -Id $threadServiceId -ErrorAction SilentlyContinue
    Write-Host "Stopped THREAD $threadService."
}
