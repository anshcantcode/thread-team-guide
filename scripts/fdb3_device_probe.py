"""Actual emulator storage/handoff controls, not audio or a complete extension demo."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3_extension import EmulatorRegistry
from thread_agent.fdb3 import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--adb',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--timer',action='store_true',help='Create one 47-second diagnostic Clock handoff on the owned emulator')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    registry=EmulatorRegistry(args.serial,adb=args.adb)
    report={'started_at':time.time(),'session_id':registry.session_id,'serial':args.serial,
        'scope':'actual native device controls; no audio/model/controller qualification',
        'paid_requests':0,'qualification':False,'status':'running'}
    try:
        registry.input_started(1)
        def call(name,values,identity):
            result=registry.call_with_context(name,values,call_id=identity,revision=1,input_sequence=1)
            if result['status']!='success': raise RuntimeError(result['detail'])
            return result
        added=call('add_checklist_item',{'text':'wash turnip greens'},'add-once')
        duplicate=call('add_checklist_item',{'text':'wash turnip greens'},'add-once')
        assert duplicate['item_id']==added['item_id']
        call('set_checklist_item',{'item_id':added['item_id'],'checked':True},'check-once')
        registry._adb('shell','am','force-stop',registry.package)
        read=call('read_checklist',{},'read-after-restart')
        assert len(read['items'])==1 and read['items'][0]['checked'] is True
        report['persisted_checklist']=read
        if args.timer:
            receipt=call('request_timer_handoff',{'seconds':47,'label':'THREAD local diagnostic'},'timer-once')
            assert receipt['device_status']=='handed_off' and receipt['timer_creation_confirmed'] is False
            call('inspect_timer_handoff',{},'inspect')
            blocked=registry.call_with_context('request_timer_handoff',{'seconds':58,'label':'replacement'},
                call_id='timer-replacement',revision=1,input_sequence=1)
            assert blocked['status']=='error'
            report['handoff_receipt']=receipt
            report['replacement_blocked']=blocked
        # Capture only this explicitly selected owned emulator, not the desktop.
        screenshot=subprocess.run([args.adb,'-s',args.serial,'exec-out','screencap','-p'],
            check=True,capture_output=True,timeout=25).stdout
        (args.output/'device.png').write_bytes(screenshot)
        report['screenshot_sha256']=sha256(args.output/'device.png')
        report['status']='native_controls_passed'
    except BaseException as exc:
        report.update(status='failed',error_type=type(exc).__name__,error=str(exc))
        raise
    finally:
        report.update(finished_at=time.time(),device_commands=registry.records)
        (args.output/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'session_id':registry.session_id,'output':str(args.output)}))


if __name__=='__main__': main()
