"""Independent audio recognition control; never use its reference as a model hint."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from thread_agent.fdb3_voice import WhisperSTT
from thread_agent.fdb3 import sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--whisper',required=True)
    parser.add_argument('--audio',required=True,type=Path)
    parser.add_argument('--reference',required=True,help='Authored developer fixture text, used only after transcription')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Use a fresh output file; previous controls are retained')
    recognizer=WhisperSTT(args.whisper)
    rows=[]
    for filtered in (False,True):
        started=time.time()
        text,chunks=recognizer.transcribe(str(args.audio),filter_silence=filtered)
        rows.append({'filter_silence':filtered,'text':text,'chunks':chunks,'elapsed_seconds':time.time()-started})
    words=lambda text: re.findall(r"[a-z0-9]+",text.casefold())
    passed=words(rows[1]['text'])==words(args.reference)
    report={'scope':'Authored synthetic audio control; no official benchmark scoring or human-accuracy claim',
        'input_sha256':sha256(args.audio),'whisper':args.whisper,'reference':args.reference,
        'passed':passed,'stt_requests':2,'paid_requests':0,'rows':rows}
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':passed,'before':rows[0]['text'],'after':rows[1]['text']}))
    return 0 if passed else 1


if __name__=='__main__': raise SystemExit(main())
