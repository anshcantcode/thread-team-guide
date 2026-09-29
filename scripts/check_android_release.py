"""Opt-in check of the installed minified APK using its real microphone and Gemini.

Uses only Android shell/UI APIs, so test code cannot keep app classes alive in R8.
Requires an unlocked phone, prior microphone/cloud consent, and internet access.
Default: embedded phone backend, with no laptop server or USB reverse mappings.
Use --relay only to recheck an older laptop-backed build.
Audio follows the normal live app path; the report stores counts, never audio/captions.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import socket
import time
from datetime import datetime, timezone
from urllib.request import urlopen
import xml.etree.ElementTree as ET
import zipfile
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
ADB=Path(os.environ['LOCALAPPDATA'])/'Android/Sdk/platform-tools/adb.exe'
REPORT=ROOT/'reports/android-release-microphone-check.json'

def adb(*args):
    return subprocess.check_output([str(ADB),*args],timeout=25).decode('utf-8',errors='replace')

def pid():
    try:return adb('shell','pidof','com.thread.app').strip()
    except subprocess.CalledProcessError:return ''

def hierarchy():
    # The CLI dump waits for an idle screen, which live captions/animation may
    # never provide. This companion process reads accessibility directly and
    # returns only named call controls, never captions or other personal text.
    output = adb('shell', 'am', 'instrument', '-w', 'com.thread.probe/com.thread.probe.ReleaseUiProbe')
    prefix = 'INSTRUMENTATION_RESULT: thread_controls='
    line = next((line for line in output.splitlines() if line.startswith(prefix)), None)
    assert line is not None, 'Install the ui-probe debug APK; the release UI probe is unavailable.'
    root = ET.Element('hierarchy')
    for control in json.loads(line[len(prefix):]):
        ET.SubElement(root, 'node', package='com.thread.app', text=control['label'], clickable='true', bounds=control['bounds'])
    return root

def find(root,*labels):
    return next((n for n in root.iter('node') if n.get('package')=='com.thread.app' and (n.get('text') in labels or n.get('content-desc') in labels)),None)

def click(*labels):
    root=hierarchy()
    node=find(root,*labels)
    if node is None:raise AssertionError('Expected THREAD control: '+', '.join(labels))
    parents={child:parent for parent in root.iter() for child in parent}
    while node.get('clickable')!='true' and node in parents:
        node=parents[node]
    assert node.get('clickable')=='true','No clickable ancestor for '+', '.join(labels)
    x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds','')))
    print('Tap '+', '.join(labels)+' at '+node.get('bounds',''),flush=True)
    adb('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))

def wait_control(*labels):
    deadline=time.monotonic()+8
    while find(hierarchy(),*labels) is None:
        assert time.monotonic()<deadline,'Control did not appear: '+', '.join(labels)
        time.sleep(.25)

def sessions():
    return re.findall(r'WebSocket /live/(session-[a-f0-9]+)',(ROOT/'.runtime/server.err.log').read_text(encoding='utf-8',errors='replace'))

def closed(sid):
    with urlopen('http://127.0.0.1:8766/api/sessions/'+sid+'/export',timeout=8) as response:
        return [e for e in json.load(response)['events'] if e['type']=='live_disconnected']

def phone_metrics(process_id):
    # Only aggregate durations are logged. Never export general app/network logs.
    log = adb('logcat', '-d', '--pid=' + process_id, '-v', 'raw', 'python.stdout:I', '*:S')
    result = []
    for line in log.splitlines():
        if not line.startswith('THREAD_VOICE_METRICS '): continue
        value = json.loads(line.removeprefix('THREAD_VOICE_METRICS '))
        fields = ('input_audio_seconds', 'generated_audio_seconds', 'connected_seconds')
        if set(value) == set(fields) and all(isinstance(value[k], (int, float)) for k in fields): result.append(value)
    return result

def verify_phone_package(path):
    key = (dotenv_values(ROOT / '.env').get('THREAD_API_KEY') or '').encode()
    python_entries = []
    private_names = {'.env', 'notebook.sqlite3', 'notebook.sqlite3-wal', 'notebook.sqlite3-shm', 'notebook.sqlite3-journal', 'phone-config-import.json'}
    def private(name): return PurePosixPath(name.replace('\\', '/')).name in private_names
    with zipfile.ZipFile(path) as apk:
        assert 'assets/chaquopy/app.imy' in apk.namelist(), 'The APK has no embedded app code.'
        for entry in apk.infolist():
            if entry.is_dir(): continue
            data = apk.read(entry)
            assert not key or key not in data, 'The APK contains the configured personal key.'
            assert not private(entry.filename), 'Private data was packaged.'
            if entry.filename.startswith('assets/chaquopy/') and entry.filename.endswith('.imy'):
                with zipfile.ZipFile(io.BytesIO(data)) as python:
                    for item in python.infolist():
                        if item.is_dir(): continue
                        assert not key or key not in python.read(item), 'Embedded Python contains the configured personal key.'
                        assert not private(item.filename), 'Private Python data was packaged.'
                    if entry.filename == 'assets/chaquopy/app.imy': python_entries = python.namelist()
    assert any(name.startswith('thread_agent/android_backend.') for name in python_entries), 'The phone entrypoint is missing.'
    assert all(name.startswith('thread_agent/') for name in python_entries), 'Unexpected application Python payload.'
    return {'personal_key_absent': True if key else None, 'private_notebook_absent': True, 'embedded_app_files': len(python_entries)}

def alive_for(seconds,expected):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if pid()!=expected:raise AssertionError('The release app process stopped during microphone inference.')
        time.sleep(.5)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--relay', action='store_true')
    args = parser.parse_args()
    report={'passed':False,'started_at':datetime.now(timezone.utc).isoformat(),'variant':'release, minified, not debuggable','cycles':[],
            'backend': 'laptop relay' if args.relay else 'embedded phone Python',
            'ui_observer': 'read-only companion APK process; no release app internals or cached UI dumps',
            'scope':'Actual microphone start, sustained PCM/VAD inference, mute/unmute, end, and cold restart. UI driven through Android shell; no app internals or test keep rules.'}
    try:
        if not args.relay:
            mappings = adb('reverse', '--list')
            assert 'tcp:8766' not in mappings and 'tcp:8767' not in mappings, 'Remove the USB backend reverse mappings first.'
            with socket.socket() as probe:
                probe.settimeout(1)
                assert probe.connect_ex(('127.0.0.1', 8766)) != 0, 'Stop the laptop backend before testing phone independence.'
            report['no_usb_backend_reverse'] = True
            report['laptop_backend_stopped'] = True
        package=adb('shell','dumpsys','package','com.thread.app')
        assert 'versionName=' in package and 'DEBUGGABLE' not in package,'Install the actual release APK first.'
        assert 'android.permission.RECORD_AUDIO: granted=true' in package,'Grant microphone permission in THREAD first.'
        mapping=(ROOT/'android/app/build/outputs/mapping/release/mapping.txt').read_text()
        for name in ('TensorInfo','TensorInfo$OnnxTensorType','OnnxJavaType','OnnxTensor'):
            assert f'ai.onnxruntime.{name} -> ai.onnxruntime.{name}:' in mapping,f'R8 renamed required ONNX class {name}.'
        report['apk_sha256']=hashlib.sha256((ROOT/'android/app/build/outputs/apk/release/app-release.apk').read_bytes()).hexdigest()
        if not args.relay: report['package_checks'] = verify_phone_package(ROOT/'android/app/build/outputs/apk/release/app-release.apk')
        installed=adb('shell','pm','path','com.thread.app').strip().removeprefix('package:')
        assert adb('shell','sha256sum',installed).split()[0]==report['apk_sha256'],'Installed APK differs from the release artifact.'
        report['installed_apk_matches']=True
        for cycle in range(2):
            before=len(sessions()) if args.relay else 0
            adb('shell','am','force-stop','com.thread.app')
            adb('shell','am','start','-n','com.thread.app/.MainActivity','--ez','talk','true')
            time.sleep(1)
            expected=pid();assert expected,'THREAD did not start.'
            deadline=time.monotonic()+35
            while True:
                assert pid()==expected,'THREAD crashed while starting the microphone.'
                if find(hierarchy(),'Mute') is not None:break
                if time.monotonic()>deadline:raise AssertionError('Voice did not connect; check phone key, consent and provider availability.')
                time.sleep(.5)
            alive_for(12,expected)
            click('Mute');wait_control('Unmute');alive_for(2,expected)
            click('Unmute');wait_control('Mute');alive_for(8,expected)
            if args.relay:
                active=sessions();assert len(active)>before,'No native live connection was observed by the relay.'
                sid=active[-1]
                previous=len(closed(sid))
            else:
                sid=None
                previous=len(phone_metrics(expected))
            click('End conversation','End')
            deadline=time.monotonic()+8
            while find(hierarchy(),'Mute','Unmute') is not None:
                assert time.monotonic()<deadline,'End did not remove active call controls.'
                time.sleep(.25)
            print('Call controls closed; waiting for backend disconnect counters.',flush=True)
            deadline=time.monotonic()+10
            while len(events:=(closed(sid) if args.relay else phone_metrics(expected)))<=previous:
                assert time.monotonic()<deadline,'End did not close the voice connection.'
                time.sleep(.25)
            event=events[-1]
            assert event['input_audio_seconds']>=15,'The microphone did not stream sustained audio through the detector.'
            assert pid()==expected,'THREAD crashed when ending the conversation.'
            row={'cycle':cycle+1,'passed':True,'pid':expected,'session_id':sid,
                 **{key:event[key] for key in ('input_audio_seconds','generated_audio_seconds','connected_seconds')}}
            report['cycles'].append(row)
            REPORT.write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(f"Release microphone cycle {cycle+1} PASS: {event['input_audio_seconds']} seconds of PCM processed",flush=True)
        report['passed']=True
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        # The test owns these calls; leave no active microphone if any assertion fails.
        adb('shell','am','force-stop','com.thread.app')
        adb('shell','am','start','-n','com.thread.app/.MainActivity')
        REPORT.write_text(json.dumps(report,indent=2),encoding='utf-8')

if __name__=='__main__':main()
