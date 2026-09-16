"""Optional model-assisted listening review of the exported soundtrack."""
import argparse
import base64
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
p.add_argument('--video',action='store_true')
args=p.parse_args()
values=dict(line.split('=',1) for line in (ROOT.parent/'.env').read_text().splitlines() if '=' in line and not line.lstrip().startswith('#'))
key=values['THREAD_API_KEY'].strip().strip('"').strip("'")
prompt='''Review this actual 58-second product-film soundtrack as a critical sound editor. Listen to the attached audio, not an imagined script. A character deliberately interrupts an assistant around 18 seconds; the music deliberately drops at that moment. That interruption is intentional. Identify the spoken words with rough timestamps; flag any garbled words, unintelligible speech, direction text accidentally spoken, clicks or distortion, distracting music, odd narration cadence, inconsistent voices, abrupt ending, and whether the music and voice feel balanced. Specifically compare the character making the flight request at 12 seconds with the character saying Wait at 18 seconds: do they sound consistent as the same person changing her mind? Do not invent meter readings. Return JSON with transcript_segments, audible_problems (empty if none), voice_performance, character_consistency, music_and_effects, and recommended_edits. Be specific and candid.'''
media=ROOT/'audio/mix-premaster.wav'
if args.video:
    media=ROOT/'output/review-with-audio.mp4'
    prompt='''Critically review this actual 58-second THREAD product film with its attached audio. Assess it as a motion-design editor: type readability, hierarchy, cropping, transitions, pacing, narration synchronization, sound balance, and visual consistency. The goal is a premium blue-on-ink product film, an interruption that changes the edit, and real phone screens. The flight exchange is expressly labeled as an illustrated interaction with demo data; the interruption around 18 seconds is deliberate. Identify any unintended blank frames, clipped typography, illegible claims, awkward camera moves, repetitive motion, poor sound transitions, or missing word endings. Do not make up problems and do not praise automatically. Return JSON with overall_assessment, timestamped_issues (severity, time, concrete_problem, practical_fix), strengths, and whether export is ready. Base this only on the attached video. A 540p review proxy may soften phone text; the master is 1440p. Do not treat that proxy resolution as a source defect.'''
payload={'contents':[{'parts':[{'text':prompt},{'inlineData':{'mimeType':'video/mp4' if args.video else 'audio/wav','data':base64.b64encode(media.read_bytes()).decode()}}]}],'generationConfig':{'responseMimeType':'application/json','temperature':.15}}
model=values.get('THREAD_MODEL','gemini-3.5-flash-lite').strip()
req=urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-goog-api-key':key})
with urllib.request.urlopen(req,timeout=120) as r:data=json.load(r)
result='\n'.join(p.get('text','') for p in data['candidates'][0]['content']['parts'])
(ROOT/('output/film-review.json' if args.video else 'audio/listening-review.json')).write_text(result,encoding='utf-8')
print(result)
