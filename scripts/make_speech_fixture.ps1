# Synthetic English speech for transport/inference checks; never records a microphone.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$threadReports = Join-Path (Split-Path $PSScriptRoot) 'reports'
New-Item -ItemType Directory -Force -Path $threadReports | Out-Null
$threadSpeech = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $threadFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $threadSpeech.SetOutputToWaveFile((Join-Path $threadReports 'synthetic-request.wav'), $threadFormat)
    $threadSpeech.Speak('Find a flight from Chennai to Mumbai tomorrow after nine PM.')
} finally { $threadSpeech.Dispose() }
Write-Host 'Created reports/synthetic-request.wav using a system voice. No microphone was used.'
