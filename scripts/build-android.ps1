param([switch]$Install, [switch]$Test, [switch]$Release)
$ErrorActionPreference = 'Stop'
$threadRoot = Split-Path -Parent $PSScriptRoot
if (-not $env:JAVA_HOME) { $env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr' }
if (-not $env:ANDROID_HOME) {
    $env:ANDROID_HOME = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { "$env:LOCALAPPDATA\Android\Sdk" }
}
if (!(Test-Path -LiteralPath "$env:JAVA_HOME\bin\java.exe")) { throw 'Set JAVA_HOME to a JDK 17+ installation, or install Android Studio.' }
if (!(Test-Path -LiteralPath $env:ANDROID_HOME)) { throw 'Set ANDROID_HOME to your Android SDK directory.' }
$threadGradle = Join-Path $threadRoot 'android\gradlew.bat'
Push-Location "$threadRoot\android"
try {
    $threadVariant = if ($Release) { 'release' } else { 'debug' }
    if ($Release -and $Test) { & $threadGradle --console=plain :app:assembleRelease :ui-probe:assembleDebug }
    elseif ($Release) { & $threadGradle --console=plain :app:assembleRelease }
    elseif ($Test) { & $threadGradle --console=plain :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest }
    else { & $threadGradle --console=plain :app:assembleDebug }
    if ($LASTEXITCODE -ne 0) { throw "Android build failed ($LASTEXITCODE)." }
    if ($Install -or $Test) {
        & "$env:ANDROID_HOME\platform-tools\adb.exe" install -r "app\build\outputs\apk\$threadVariant\app-$threadVariant.apk"
        if ($LASTEXITCODE -ne 0) { throw 'APK install failed.' }
        if ($Test -and $Release) {
            & "$env:ANDROID_HOME\platform-tools\adb.exe" install -r 'ui-probe\build\outputs\apk\debug\ui-probe-debug.apk'
            if ($LASTEXITCODE -ne 0) { throw 'Companion UI probe install failed.' }
            & "$threadRoot\.venv\Scripts\python.exe" -X utf8 "$threadRoot\scripts\check_android_release.py"
            if ($LASTEXITCODE -ne 0) { throw 'Release microphone check failed; inspect reports/android-release-microphone-check.json.' }
        } elseif ($Test) {
            & "$env:ANDROID_HOME\platform-tools\adb.exe" install -r 'app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk'
            if ($LASTEXITCODE -ne 0) { throw 'Test APK install failed.' }
            $threadTestOutput = & "$env:ANDROID_HOME\platform-tools\adb.exe" shell am instrument -w -e notClass com.thread.app.ThreadLiveDeviceTest,com.thread.app.WidgetLiveDeviceTest,com.thread.app.SmartActionsLiveDeviceTest com.thread.app.test/androidx.test.runner.AndroidJUnitRunner
            $threadTestOutput | Write-Output
            & "$env:ANDROID_HOME\platform-tools\adb.exe" shell am start -n com.thread.app/.MainActivity
            if (($threadTestOutput -join "`n") -notmatch 'OK \([0-9]+ tests?\)') { throw 'Android device checks failed; inspect the instrumentation output.' }
        }
        & "$env:ANDROID_HOME\platform-tools\adb.exe" shell am start -n com.thread.app/.MainActivity
    }
} finally { Pop-Location }
