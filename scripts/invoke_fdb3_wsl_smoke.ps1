# Historical WSL comparison helper. Never stops another experiment's services.
param(
    [Parameter(Mandatory=$true)][ValidateSet('Prepare','Run')][string]$Stage,
    [switch]$GpuSlotGranted,
    [string]$WindowsReference
)
$ErrorActionPreference = 'Stop'
if (-not $GpuSlotGranted) { throw 'Wait for the active experiment owner to release the GPU, then pass -GpuSlotGranted.' }
$taskRepo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRepo
if ((git branch --show-current) -in @('', 'main', 'master')) { throw 'Use a dedicated named experiment branch.' }
$taskCommit = (git rev-parse HEAD).Trim()
$taskWhisperModel = if (Test-Path Env:THREAD_FDB3_WHISPER_MODEL) {
    $env:THREAD_FDB3_WHISPER_MODEL
} else {
    (Get-Content -Raw -LiteralPath (Join-Path $taskRepo 'config/fdb3-candidate.json') | ConvertFrom-Json).whisper.default_model
}
if ($taskWhisperModel -cnotin @('base.en', 'small.en')) { throw 'THREAD_FDB3_WHISPER_MODEL must be base.en or small.en' }
$taskWhisperEnv = 'THREAD_FDB3_WHISPER_MODEL=' + $taskWhisperModel
git diff --quiet HEAD -- participant thread_agent scripts config requirements-fdb3.lock requirements-fdb3-cuda.txt
if ($LASTEXITCODE -ne 0) { throw 'Commit runtime changes locally before exporting phase 2.' }
if (Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" | Where-Object { $_.CommandLine -match '--port\s+8098\b' }) {
    throw 'The active experiment owner must stop the :8098 planner first. This script will not stop it.'
}
$taskFreeRam = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1KB
if ($Stage -eq 'Prepare' -and ($taskFreeRam -lt 6GB -or (Get-PSDrive C).Free -lt 5GB)) {
    throw 'Preparation requires at least 6 GiB free host RAM and 5 GiB free C: disk. Preserve other workloads; checkpoint if unavailable.'
}
function Convert-ToTaskLinuxPath([string]$Value) {
    $resolved = [IO.Path]::GetFullPath($Value).Replace('\','/')
    return '/mnt/' + $resolved.Substring(0,1).ToLower() + $resolved.Substring(2)
}
$taskState = Join-Path $taskRepo '.thread-run/task-b-phase2.json'
if ($Stage -eq 'Prepare') {
    $taskId = $taskCommit.Substring(0,12) + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $taskLinuxRoot = '/opt/thread-task-b/' + $taskId
    $taskArchive = Join-Path $taskRepo ('.thread-run/task-b-prep/source-' + $taskId + '.tar')
    $taskIdentity = Join-Path $taskRepo ('.thread-run/task-b-prep/source-' + $taskId + '.json')
    New-Item -ItemType Directory -Path (Split-Path -Parent $taskArchive) -Force | Out-Null
    if (Test-Path -LiteralPath $taskArchive) { throw 'Archive already exists' }
    git archive --format=tar "--output=$taskArchive" HEAD -- participant thread_agent scripts config requirements-fdb3.lock requirements-fdb3-cuda.txt requirements-fdb3-bench.txt
    if ($LASTEXITCODE -ne 0) { throw 'Source export failed' }
    $identity = @{source_commit=$taskCommit; source_archive_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $taskArchive).Hash.ToLower(); dirty=$false}
    [IO.File]::WriteAllText($taskIdentity, ($identity | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    $state = @{source_commit=$taskCommit; linux_root=$taskLinuxRoot; status='PROVISIONING'; source_archive=$taskArchive; whisper_model=$taskWhisperModel}
    [IO.File]::WriteAllText($taskState, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    $taskLlamaCache = Join-Path $taskRepo '.thread-run/task-b-prep/llama-56381e407.tar.gz'
    & wsl.exe -d THREAD-Submission-Sprint3 -u root -- env $taskWhisperEnv bash (Convert-ToTaskLinuxPath (Join-Path $PSScriptRoot 'fdb3_wsl_phase2.sh')) prepare $taskLinuxRoot (Convert-ToTaskLinuxPath $taskArchive) (Convert-ToTaskLinuxPath $taskIdentity) (Convert-ToTaskLinuxPath $taskLlamaCache)
    $taskExit = $LASTEXITCODE
    $state.status = if ($taskExit -eq 0) { 'PREPARED_NOT_RUN' } else { 'PROVISIONING_FAILED' }
    [IO.File]::WriteAllText($taskState, ($state | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    exit $taskExit
}
if (-not (Test-Path -LiteralPath $taskState)) { throw 'Run the Prepare command first.' }
$state = Get-Content -Raw -LiteralPath $taskState | ConvertFrom-Json
if ($state.source_commit -ne $taskCommit -or $state.status -ne 'PREPARED_NOT_RUN') { throw 'Prepared source is stale or provisioning failed; inspect phase-2 state.' }
if ($state.whisper_model -cne $taskWhisperModel) { throw 'Whisper choice changed since preparation; use the prepared choice or prepare a fresh task.' }
if (-not $WindowsReference -or -not (Test-Path -LiteralPath $WindowsReference)) { throw 'Supply -WindowsReference with the preserved historical archive directory.' }
$taskReferenceEnv = 'THREAD_WINDOWS_REFERENCE=' + (Convert-ToTaskLinuxPath $WindowsReference)
& wsl.exe -d THREAD-Submission-Sprint3 -u root -- env $taskWhisperEnv $taskReferenceEnv bash ($state.linux_root + '/source/scripts/fdb3_wsl_phase2.sh') run $state.linux_root
exit $LASTEXITCODE
