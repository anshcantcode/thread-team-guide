"""Opt-in real-camera check of the installed release APK; requires camera permission and a configured voice session."""
import json
import time
from pathlib import Path
from check_android_release import adb, hierarchy, find, click, wait_control

def main():
    report = {'passed': False, 'variant': 'release, minified, not debuggable',
              'scope': 'Real camera start/stop control and Android camera service ownership; no app internals or retained frames.'}
    def active():
        return adb('shell', 'dumpsys', 'media.camera').split('Active Camera Clients:', 1)[1].split('Allowed user IDs:', 1)[0]
    try:
        adb('shell', 'am', 'start', '-n', 'com.thread.app/.MainActivity', '--ez', 'talk', 'true')
        deadline = time.monotonic()+35
        while find(hierarchy(), 'Mute') is None:
            assert time.monotonic() < deadline, 'Voice did not connect'
        assert 'com.thread.app' not in active(), 'Camera opened before explicit opt-in'
        click('Start camera')
        time.sleep(.5)
        click('Start camera')
        wait_control('Stop camera')
        time.sleep(5)
        assert find(hierarchy(), 'Stop camera') is not None, 'Sharing failed after start'
        assert 'com.thread.app' in active(), 'Android does not report an active THREAD camera'
        report['camera_active_only_after_start'] = True
        click('Stop camera')
        wait_control('Start camera')
        time.sleep(2)
        assert 'com.thread.app' not in active(), 'Camera was not released after Stop'
        assert find(hierarchy(), 'Mute') is not None, 'Stop camera ended voice'
        report['stop_releases_camera_and_preserves_voice'] = True
        click('End')
        report['passed'] = True
    finally:
        adb('shell', 'am', 'force-stop', 'com.thread.app')
        adb('shell', 'am', 'start', '-n', 'com.thread.app/.MainActivity')
        (Path(__file__).resolve().parents[1] / 'reports/android-camera-release-device.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))



if __name__ == '__main__': main()
