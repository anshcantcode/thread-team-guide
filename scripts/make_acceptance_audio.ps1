param([string]$Corpus = 'evaluation/corpus.json', [string]$OutputDirectory = 'evaluation/audio')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$threadRoot = Split-Path $PSScriptRoot
$threadCorpus = Get-Content -LiteralPath (Join-Path $threadRoot $Corpus) -Raw | ConvertFrom-Json
$threadAudio = Join-Path $threadRoot $OutputDirectory
New-Item -ItemType Directory -Force -Path $threadAudio | Out-Null
$threadVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $threadFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($threadCase in $threadCorpus.cases) {
        if ($threadCase.mode -ne 'audio' -or $threadCase.silence) { continue }
        $threadVoice.SetOutputToWaveFile((Join-Path $threadAudio ($threadCase.id + '.wav')), $threadFormat)
        $threadVoice.Speak($threadCase.speech)
        $threadVoice.SetOutputToNull()
    }
    @{ source='Windows synthetic speech, not human recordings'; voice=$threadVoice.Voice.Name; format='16000 Hz mono PCM16'; corpus=$Corpus } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $threadAudio 'provenance.json') -Encoding utf8
} finally { $threadVoice.Dispose() }
Write-Output 'Synthetic acceptance audio generated. No microphone was used.'
