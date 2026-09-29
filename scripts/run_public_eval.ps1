[CmdletBinding()]
param(
    [string]$EnvFile,
    [string]$OutputPath
)

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$kitStorage = (Resolve-Path -LiteralPath (Join-Path $repoRoot 'theme5_kit')).Path
$kit = (Resolve-Path -LiteralPath (Join-Path $repoRoot 'theme5_kit\participant-kit\participant-kit')).Path
$evaluator = Join-Path $kit 'eval_submission.py'
if (!(Test-Path -LiteralPath $evaluator -PathType Leaf)) {
    throw 'The Samsung evaluator is missing from the repository kit.'
}

$resolvedEnvFile = $null
if ($EnvFile) {
    $resolvedEnvFile = (Resolve-Path -LiteralPath $EnvFile -ErrorAction Stop).Path
    if (!(Test-Path -LiteralPath $resolvedEnvFile -PathType Leaf)) {
        throw 'EnvFile must name an existing file.'
    }
}

$resolvedOutputPath = $null
if ($OutputPath) {
    $resolvedOutputPath = [IO.Path]::GetFullPath($OutputPath)
    $kitPrefix = $kitStorage + [IO.Path]::DirectorySeparatorChar
    if ($resolvedOutputPath.Equals($kitStorage, [StringComparison]::OrdinalIgnoreCase) -or
        $resolvedOutputPath.StartsWith($kitPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'OutputPath must be outside the Samsung kit.'
    }
    $outputDirectory = Split-Path -Parent $resolvedOutputPath
    if ($outputDirectory -and !(Test-Path -LiteralPath $outputDirectory -PathType Container)) {
        New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    }
}

$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $python -PathType Leaf) {
    $pythonLauncherArgs = @()
} else {
    $python = 'py'
    $pythonLauncherArgs = @('-3.11')
}
$evaluationArgs = @('-B', $evaluator, $repoRoot, '--time-scale', '1', '--reps', '3')
if ($resolvedOutputPath) {
    $evaluationArgs += @('--out', $resolvedOutputPath)
}

$previousMediaRoot = [Environment]::GetEnvironmentVariable('PARTICIPANT_MEDIA_ROOT', 'Process')
$previousEnvFile = [Environment]::GetEnvironmentVariable('PARTICIPANT_ENV_FILE', 'Process')
$exitCode = 1
try {
    $env:PARTICIPANT_MEDIA_ROOT = $kit
    if ($resolvedEnvFile) {
        $env:PARTICIPANT_ENV_FILE = $resolvedEnvFile
    }
    & $python @pythonLauncherArgs @evaluationArgs
    $exitCode = $LASTEXITCODE
} finally {
    if ($null -eq $previousMediaRoot) {
        Remove-Item Env:PARTICIPANT_MEDIA_ROOT -ErrorAction SilentlyContinue
    } else {
        $env:PARTICIPANT_MEDIA_ROOT = $previousMediaRoot
    }
    if ($null -eq $previousEnvFile) {
        Remove-Item Env:PARTICIPANT_ENV_FILE -ErrorAction SilentlyContinue
    } else {
        $env:PARTICIPANT_ENV_FILE = $previousEnvFile
    }
}
exit $exitCode
