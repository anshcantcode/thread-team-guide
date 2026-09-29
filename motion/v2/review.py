"""Optional audio/video critique from a multimodal model, using public film media."""
import argparse
import base64
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding='utf-8')
p=argparse.ArgumentParser();p.add_argument('--video',action='store_true');p.add_argument('--vertical',action='store_true');args=p.parse_args()
env=dict(line.split('=',1) for line in (ROOT.parents[1]/'.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
key=env['THREAD_API_KEY'].strip().strip('"').strip("'")
shape='vertical' if args.vertical else 'landscape'
media=ROOT/'output'/f'{shape}-review.mp4' if args.video else ROOT/'audio/mix-premaster.wav'
prompt='''Critically assess this actual 43-second THREAD product film audio. Transcribe each utterance you hear with approximate timestamps. Check all 12 user command lines for accidental truncation, missing words, directions spoken aloud, consistent character voice, unnatural cadence or garbling. The male assistant starts replying near 3.14 seconds and is intentionally cut off by Actually Mumbai at 4.02 seconds; this interruption is deliberate. Check that it sounds like a responsive interruption. Check voice/music balance, useful rhythmic energy, clicks, distortion, and the final word Thread. Do not invent meter readings. Return JSON with transcript_segments, audible_problems, performance, and concrete_recommended_changes. Do not automatically approve.'''
if args.video:
 prompt='''Review the attached 43-second product film based only on what you can actually see and hear. First describe each scene and quote its main visible words. Describe the very last visible frame precisely. Then report concrete defects, if any: overlapping text, cropped meaningful content, inconsistent data, or an unintelligible line of speech. Each defect must quote the exact affected words or identify the actual objects and give a timestamp. Do not infer missing transitions from sparsely sampled frames, or invent a container or a fade. If there is insufficient temporal resolution to judge an easing curve, say so. This is a fast cinematic representation of implemented capabilities; sample flights and captured public data are disclosed, and the purpose is not exact screen-recording fidelity. Assess pacing relative to this brief. Return JSON with scene_observations, last_frame, verified_issues (empty if none), audible_issues, and judgment_limitations. The master is 60 fps and 1440p landscape / 1080p portrait; this is a lower-resolution review proxy. Do not score or give automatic approval.'''
payload={'contents':[{'parts':[{'text':prompt},{'inlineData':{'mimeType':'video/mp4' if args.video else 'audio/wav','data':base64.b64encode(media.read_bytes()).decode()}}]}],'generationConfig':{'responseMimeType':'application/json','temperature':.1}}
model=env.get('THREAD_MODEL','gemini-3.5-flash-lite').strip()
req=urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key})
with urllib.request.urlopen(req,timeout=120) as r:data=json.load(r)
result='\n'.join(part.get('text','') for part in data['candidates'][0]['content']['parts'])
out=ROOT/'output'/f'{shape}-review.json' if args.video else ROOT/'audio/listening-review.json'
out.write_text(result,encoding='utf-8');print(result)
